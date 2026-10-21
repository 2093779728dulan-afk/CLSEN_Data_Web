from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from app.imports.storage import ContentNotFoundError
from app.parsers import ParseError
from app.parsers.types import ParsedReport, RecognitionResult
from app.parsers.workflow import (
    BatchSource,
    ChangeReportDateCommand,
    ConfirmAndParseCommand,
    ConfirmedParseContext,
    FailedParse,
    ParseFailure,
    ParseWorkflow,
    SuccessfulParse,
)

NOW = datetime(2026, 8, 7, 6, 0, tzinfo=UTC)
TOKEN = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CONTENT = b"synthetic-content"


def _source() -> BatchSource:
    return BatchSource(
        batch_id=7,
        original_filename="20260806-BusinessReport-synthetic.csv",
        storage_key=f"sha256/ab/{'ab' * 32}",
        sha256_hex="ab" * 32,
        size_bytes=len(CONTENT),
    )


def _command() -> ConfirmAndParseCommand:
    return ConfirmAndParseCommand(
        batch_id=7,
        report_type="business_report",
        report_date=date(2026, 8, 6),
        encoding="utf-8-sig",
        site_config_version_id=3,
        actor_user_id=9,
        operation_token=TOKEN,
    )


class RecordingStore:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.error: ContentNotFoundError | None = None

    def read_bytes(
        self,
        storage_key: str,
        expected_sha256_hex: str,
        expected_size: int,
    ) -> bytes:
        self.calls.append(
            ("read_bytes", storage_key, expected_sha256_hex, expected_size)
        )
        if self.error is not None:
            raise self.error
        return CONTENT


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.recovered: SuccessfulParse | FailedParse | None = None
        self.source = _source()
        self.context = ConfirmedParseContext(
            source=self.source,
            site_id=1,
            site_config_version_id=3,
            source_timezone="America/Los_Angeles",
            report_type="business_report",
            report_date=date(2026, 8, 6),
            encoding="utf-8-sig",
            confirmation_revision=2,
            actor_user_id=9,
            processing_token=TOKEN,
            operation_digest=_command().operation_digest,
            started_at=NOW,
        )

    def get_batch_source(self, batch_id: int) -> BatchSource:
        self.calls.append(("get_batch_source", batch_id))
        return self.source

    def record_recognition(
        self,
        *,
        batch_id: int,
        result: RecognitionResult,
        detector_version: str,
        detected_at: datetime,
    ) -> None:
        self.calls.append(
            (
                "record_recognition",
                batch_id,
                result,
                detector_version,
                detected_at,
            )
        )

    def begin_parse(
        self,
        *,
        command: ConfirmAndParseCommand,
        processing_token: UUID,
        started_at: datetime,
    ) -> ConfirmedParseContext:
        self.calls.append(("begin_parse", command, processing_token, started_at))
        return self.context

    def recover_terminal(
        self,
        processing_token: UUID,
        *,
        expected_batch_id: int,
        operation_digest: bytes,
    ) -> SuccessfulParse | FailedParse | None:
        self.calls.append(
            (
                "recover_terminal",
                processing_token,
                expected_batch_id,
                operation_digest,
            )
        )
        return self.recovered

    def change_report_date(
        self,
        *,
        command: ChangeReportDateCommand,
        changed_at: datetime,
    ) -> None:
        self.calls.append(("change_report_date", command, changed_at))

    def finish_success(self, **kwargs: Any) -> SuccessfulParse:
        self.calls.append(("finish_success", kwargs))
        return SuccessfulParse(
            batch_id=7,
            parse_attempt_id=11,
            parse_baseline_id=13,
            confirmation_revision=2,
            report_type="business_report",
            source_row_count=2,
        )

    def finish_failure(self, **kwargs: Any) -> FailedParse:
        self.calls.append(("finish_failure", kwargs))
        failure = kwargs["failure"]
        return FailedParse(
            batch_id=7,
            parse_attempt_id=12,
            confirmation_revision=2,
            error_code=failure.code,
        )


def test_inspection_records_a_non_authoritative_recognition_result() -> None:
    repository = RecordingRepository()
    store = RecordingStore()
    suggestion = RecognitionResult(
        status="suggested",
        report_type="business_report",
        detected_report_date=date(2026, 8, 6),
        encoding="utf-8-sig",
        ruleset_version="business_report_v1",
        header=("header",),
        issues=(),
    )
    workflow = ParseWorkflow(
        repository=repository,
        store=store,
        recognizer=lambda _filename, _content: suggestion,
        parser=lambda _content, _settings: cast(ParsedReport, None),
        clock=lambda: NOW,
    )

    result = workflow.inspect(7)

    assert result is suggestion
    assert repository.calls == [
        ("get_batch_source", 7),
        ("record_recognition", 7, suggestion, "amazon_report_detector_v1", NOW),
    ]
    assert store.calls == [
        (
            "read_bytes",
            repository.source.storage_key,
            repository.source.sha256_hex,
            repository.source.size_bytes,
        )
    ]


def test_success_is_persisted_before_the_workflow_returns() -> None:
    repository = RecordingRepository()
    store = RecordingStore()
    parsed_report = object()
    seen_settings: list[object] = []

    def parse(_content: bytes, settings: object) -> object:
        seen_settings.append(settings)
        return parsed_report

    workflow = ParseWorkflow(
        repository=repository,
        store=store,
        parser=parse,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )

    result = workflow.confirm_and_parse(_command())

    assert isinstance(result, SuccessfulParse)
    assert result.parse_attempt_id == 11
    settings = seen_settings[0]
    assert settings.report_type == "business_report"  # type: ignore[attr-defined]
    assert settings.encoding == "utf-8-sig"  # type: ignore[attr-defined]
    assert settings.source_timezone == "America/Los_Angeles"  # type: ignore[attr-defined]
    assert repository.calls[:2] == [
        ("recover_terminal", TOKEN, 7, _command().operation_digest),
        ("begin_parse", _command(), TOKEN, NOW),
    ]
    assert repository.calls[-1][0] == "finish_success"
    persisted = cast(dict[str, Any], repository.calls[-1][1])
    assert persisted["context"] is repository.context
    assert persisted["parsed_report"] is parsed_report
    assert persisted["completed_at"] == NOW


def test_expected_parse_failure_is_saved_as_an_immutable_failed_attempt() -> None:
    repository = RecordingRepository()
    store = RecordingStore()

    def fail(_content: bytes, _settings: object) -> object:
        raise ParseError(
            "invalid integer",
            code="invalid_integer",
            source_row_number=4,
            field_name="quantity",
        )

    workflow = ParseWorkflow(
        repository=repository,
        store=store,
        parser=fail,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )

    result = workflow.confirm_and_parse(_command())

    assert result == FailedParse(
        batch_id=7,
        parse_attempt_id=12,
        confirmation_revision=2,
        error_code="invalid_integer",
    )
    assert repository.calls[-1][0] == "finish_failure"
    failure_call = cast(dict[str, Any], repository.calls[-1][1])
    failure = failure_call["failure"]
    assert failure.code == "invalid_integer"
    assert failure.source_row_number == 4
    assert failure.field_name == "quantity"
    assert "invalid integer" not in repr(repository.calls[-1])


def test_missing_source_is_recorded_without_exposing_the_storage_error() -> None:
    repository = RecordingRepository()
    store = RecordingStore()
    store.error = ContentNotFoundError("sensitive-local-path")
    workflow = ParseWorkflow(
        repository=repository,
        store=store,
        clock=lambda: NOW,
    )

    result = workflow.confirm_and_parse(_command())

    assert result == FailedParse(
        batch_id=7,
        parse_attempt_id=12,
        confirmation_revision=2,
        error_code="source_content_unavailable",
    )
    assert repository.calls[-1][0] == "finish_failure"
    failure_call = cast(dict[str, Any], repository.calls[-1][1])
    assert failure_call["failure"].code == "source_content_unavailable"
    assert "sensitive-local-path" not in repr(repository.calls[-1])


def test_report_date_can_change_without_reading_or_parsing_the_source() -> None:
    repository = RecordingRepository()
    store = RecordingStore()
    workflow = ParseWorkflow(repository=repository, store=store, clock=lambda: NOW)
    command = ChangeReportDateCommand(
        batch_id=7,
        report_date=date(2026, 8, 5),
        actor_user_id=9,
        operation_token=TOKEN,
    )

    workflow.change_report_date(command)

    assert repository.calls == [("change_report_date", command, NOW)]
    assert store.calls == []


def test_report_date_command_digest_binds_all_command_fields() -> None:
    command = ChangeReportDateCommand(
        batch_id=7,
        report_date=date(2026, 8, 5),
        actor_user_id=9,
        operation_token=TOKEN,
    )

    assert len(command.operation_digest) == 32
    assert replace(command, batch_id=8).operation_digest != command.operation_digest
    assert (
        replace(command, report_date=date(2026, 8, 6)).operation_digest
        != command.operation_digest
    )
    assert (
        replace(command, actor_user_id=10).operation_digest != command.operation_digest
    )
    assert (
        replace(
            command,
            operation_token=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        ).operation_digest
        == command.operation_digest
    )


def test_report_date_command_requires_a_uuid_operation_token() -> None:
    with pytest.raises(ValueError, match="operation_token must be a UUID"):
        ChangeReportDateCommand(
            batch_id=7,
            report_date=date(2026, 8, 5),
            actor_user_id=9,
            operation_token=cast(Any, None),
        )


def test_parse_failure_repr_redacts_decoded_business_values() -> None:
    failure = ParseFailure(
        code="invalid_integer",
        decoded_header=("order-id", "customer-comments"),
        decoded_rows=(("sensitive-order", "sensitive-comment"),),
    )

    rendered = repr(failure)

    assert "sensitive-order" not in rendered
    assert "sensitive-comment" not in rendered


def test_same_operation_token_recovers_a_terminal_result_without_reparsing() -> None:
    repository = RecordingRepository()
    repository.recovered = SuccessfulParse(
        batch_id=7,
        parse_attempt_id=21,
        parse_baseline_id=22,
        confirmation_revision=3,
        report_type="business_report",
        source_row_count=2,
    )
    store = RecordingStore()
    command = ConfirmAndParseCommand(
        batch_id=7,
        report_type="business_report",
        report_date=date(2026, 8, 6),
        encoding="utf-8-sig",
        site_config_version_id=3,
        actor_user_id=9,
        operation_token=TOKEN,
    )
    workflow = ParseWorkflow(
        repository=repository,
        store=store,
        clock=lambda: NOW,
    )

    result = workflow.confirm_and_parse(command)

    assert result is repository.recovered
    assert repository.calls == [
        ("recover_terminal", TOKEN, 7, command.operation_digest)
    ]
    assert store.calls == []
