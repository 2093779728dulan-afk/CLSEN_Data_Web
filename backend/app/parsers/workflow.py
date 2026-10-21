"""Application workflow for recognition, confirmation, and immutable parsing."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID

from app.imports.storage import ContentStoreError
from app.imports.types import ReportType
from app.parsers.parser import parse_report
from app.parsers.recognition import DETECTOR_VERSION, recognize_report
from app.parsers.types import (
    ParsedReport,
    ParseError,
    ParseSettings,
    RecognitionResult,
    SupportedEncoding,
)

_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class BatchSource:
    """Immutable storage identity needed to inspect or parse one batch."""

    batch_id: int
    original_filename: str
    storage_key: str
    sha256_hex: str
    size_bytes: int

    def __post_init__(self) -> None:
        if self.batch_id < 1:
            raise ValueError("batch_id must be positive")
        if not self.original_filename:
            raise ValueError("original_filename must not be blank")
        if _DIGEST_PATTERN.fullmatch(self.sha256_hex) is None:
            raise ValueError("sha256_hex must be a lowercase SHA-256 digest")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")


@dataclass(frozen=True, slots=True)
class ConfirmAndParseCommand:
    """The human-confirmed choices used for exactly one parse operation."""

    batch_id: int
    report_type: ReportType
    report_date: date
    encoding: SupportedEncoding
    site_config_version_id: int
    actor_user_id: int
    operation_token: UUID

    def __post_init__(self) -> None:
        if self.batch_id < 1:
            raise ValueError("batch_id must be positive")
        if self.report_type not in {"business_report", "return_report"}:
            raise ValueError("report_type is not supported")
        if self.encoding not in {"utf-8-sig", "utf-8", "windows-1252"}:
            raise ValueError("encoding is not supported")
        if self.site_config_version_id < 1:
            raise ValueError("site_config_version_id must be positive")
        if self.actor_user_id < 1:
            raise ValueError("actor_user_id must be positive")
        if not isinstance(self.operation_token, UUID):
            raise ValueError("operation_token must be a UUID")

    @property
    def operation_digest(self) -> bytes:
        """Bind an idempotency token to every parse-affecting command field."""

        payload = json.dumps(
            {
                "actor_user_id": self.actor_user_id,
                "batch_id": self.batch_id,
                "encoding": self.encoding,
                "report_date": self.report_date.isoformat(),
                "report_type": self.report_type,
                "site_config_version_id": self.site_config_version_id,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        return hashlib.sha256(payload).digest()


@dataclass(frozen=True, slots=True)
class ChangeReportDateCommand:
    """Change batch ownership date without creating a parse attempt."""

    batch_id: int
    report_date: date
    actor_user_id: int
    operation_token: UUID

    def __post_init__(self) -> None:
        if self.batch_id < 1:
            raise ValueError("batch_id must be positive")
        if self.actor_user_id < 1:
            raise ValueError("actor_user_id must be positive")
        if not isinstance(self.operation_token, UUID):
            raise ValueError("operation_token must be a UUID")

    @property
    def operation_digest(self) -> bytes:
        """Bind a stable date-change token to every command field."""

        payload = json.dumps(
            {
                "actor_user_id": self.actor_user_id,
                "batch_id": self.batch_id,
                "report_date": self.report_date.isoformat(),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        return hashlib.sha256(payload).digest()


@dataclass(frozen=True, slots=True)
class ConfirmedParseContext:
    """Repository-owned processing lease and frozen confirmation revision."""

    source: BatchSource
    site_id: int
    site_config_version_id: int
    source_timezone: str | None
    report_type: ReportType
    report_date: date
    encoding: SupportedEncoding
    confirmation_revision: int
    actor_user_id: int
    processing_token: UUID
    operation_digest: bytes
    started_at: datetime

    def __post_init__(self) -> None:
        if len(self.operation_digest) != 32:
            raise ValueError("operation_digest must be a SHA-256 digest")


@dataclass(frozen=True, slots=True)
class ParseFailure:
    """Redacted structured failure safe for persistence and audit."""

    code: str
    source_row_number: int | None = None
    field_name: str | None = None
    decoded_header: tuple[str, ...] | None = field(default=None, repr=False)
    decoded_rows: tuple[tuple[str, ...], ...] = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class SuccessfulParse:
    batch_id: int
    parse_attempt_id: int
    parse_baseline_id: int
    confirmation_revision: int
    report_type: ReportType
    source_row_count: int


@dataclass(frozen=True, slots=True)
class FailedParse:
    batch_id: int
    parse_attempt_id: int
    confirmation_revision: int
    error_code: str


type ParseWorkflowResult = SuccessfulParse | FailedParse


class ParseContentStore(Protocol):
    def read_bytes(
        self,
        storage_key: str,
        expected_sha256_hex: str,
        expected_size: int,
    ) -> bytes: ...


class ParseRepository(Protocol):
    def get_batch_source(self, batch_id: int) -> BatchSource: ...

    def record_recognition(
        self,
        *,
        batch_id: int,
        result: RecognitionResult,
        detector_version: str,
        detected_at: datetime,
    ) -> None: ...

    def begin_parse(
        self,
        *,
        command: ConfirmAndParseCommand,
        processing_token: UUID,
        started_at: datetime,
    ) -> ConfirmedParseContext | ParseWorkflowResult: ...

    def recover_terminal(
        self,
        processing_token: UUID,
        *,
        expected_batch_id: int,
        operation_digest: bytes,
    ) -> SuccessfulParse | FailedParse | None: ...

    def change_report_date(
        self,
        *,
        command: ChangeReportDateCommand,
        changed_at: datetime,
    ) -> None: ...

    def finish_success(
        self,
        *,
        context: ConfirmedParseContext,
        parsed_report: ParsedReport,
        completed_at: datetime,
    ) -> SuccessfulParse: ...

    def finish_failure(
        self,
        *,
        context: ConfirmedParseContext,
        failure: ParseFailure,
        completed_at: datetime,
    ) -> FailedParse: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ParseWorkflow:
    """Keep file I/O and CPU parsing outside short database transactions."""

    def __init__(
        self,
        *,
        repository: ParseRepository,
        store: ParseContentStore,
        recognizer: Callable[[str, bytes], RecognitionResult] = recognize_report,
        parser: Callable[[bytes, ParseSettings], ParsedReport] = parse_report,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._store = store
        self._recognizer = recognizer
        self._parser = parser
        self._clock = clock

    def inspect(self, batch_id: int) -> RecognitionResult:
        """Persist detector evidence without treating it as confirmation."""

        source = self._repository.get_batch_source(batch_id)
        content = self._read_source(source)
        result = self._recognizer(source.original_filename, content)
        self._repository.record_recognition(
            batch_id=batch_id,
            result=result,
            detector_version=DETECTOR_VERSION,
            detected_at=self._clock(),
        )
        return result

    def confirm_and_parse(
        self,
        command: ConfirmAndParseCommand,
    ) -> ParseWorkflowResult:
        """Confirm choices, parse bytes, then atomically persist a terminal attempt."""

        processing_token = command.operation_token
        recovered = self._repository.recover_terminal(
            processing_token,
            expected_batch_id=command.batch_id,
            operation_digest=command.operation_digest,
        )
        if recovered is not None:
            if recovered.batch_id != command.batch_id:
                raise RuntimeError("operation token belongs to another import batch")
            return recovered

        context_or_result = self._repository.begin_parse(
            command=command,
            processing_token=processing_token,
            started_at=self._clock(),
        )
        if isinstance(context_or_result, (SuccessfulParse, FailedParse)):
            if context_or_result.batch_id != command.batch_id:
                raise RuntimeError("operation token belongs to another import batch")
            return context_or_result
        context = context_or_result
        try:
            content = self._read_source(context.source)
            parsed_report = self._parser(
                content,
                ParseSettings(
                    report_type=context.report_type,
                    encoding=context.encoding,
                    source_timezone=context.source_timezone,
                ),
            )
        except ParseError as error:
            return self._repository.finish_failure(
                context=context,
                failure=ParseFailure(
                    code=error.code,
                    source_row_number=error.source_row_number,
                    field_name=error.field_name,
                    decoded_header=getattr(error, "decoded_header", None),
                    decoded_rows=getattr(error, "decoded_rows", ()),
                ),
                completed_at=self._clock(),
            )
        except ContentStoreError:
            return self._repository.finish_failure(
                context=context,
                failure=ParseFailure(code="source_content_unavailable"),
                completed_at=self._clock(),
            )

        return self._repository.finish_success(
            context=context,
            parsed_report=parsed_report,
            completed_at=self._clock(),
        )

    def change_report_date(self, command: ChangeReportDateCommand) -> None:
        """Persist a human date correction without reparsing or moving a dataset."""

        self._repository.change_report_date(
            command=command,
            changed_at=self._clock(),
        )

    def _read_source(self, source: BatchSource) -> bytes:
        return self._store.read_bytes(
            source.storage_key,
            source.sha256_hex,
            source.size_bytes,
        )
