from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Barrier, Event
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.api.errors import ApiError
from app.api.imports import (
    _resolve_batch_site_config_version_id,
    _resolve_current_site_config_version_id,
)
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.imports.repository import MySqlIngestRepository
from app.imports.service import IngestService
from app.imports.storage import LocalContentStore
from app.imports.types import ImportCommand, ImportCreated
from app.parsers.repository import (
    MySqlParseRepository,
    ParseAlreadyRunning,
    ParseStateConflict,
)
from app.parsers.types import ParsedReport
from app.parsers.workflow import (
    ChangeReportDateCommand,
    ConfirmAndParseCommand,
    ConfirmedParseContext,
    FailedParse,
    ParseFailure,
    ParseWorkflow,
    SuccessfulParse,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.mysql

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"
NOW = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)
SUCCESS_TOKEN = UUID("11111111-1111-1111-1111-111111111111")
FAILURE_TOKEN = UUID("22222222-2222-2222-2222-222222222222")


@dataclass(frozen=True, slots=True)
class ParseCase:
    engine: Engine
    store: LocalContentStore
    repository: MySqlParseRepository
    workflow: ParseWorkflow
    user_id: int
    batch_id: int
    additional_batch_ids: list[int]
    additional_config_version_ids: list[int]


class _InjectedBeginAcknowledgementLoss(RuntimeError):
    pass


class _LostBeginAcknowledgementRepository(MySqlParseRepository):
    def begin_parse(
        self,
        *,
        command: ConfirmAndParseCommand,
        processing_token: UUID,
        started_at: datetime,
    ) -> ConfirmedParseContext:
        super().begin_parse(
            command=command,
            processing_token=processing_token,
            started_at=started_at,
        )
        raise _InjectedBeginAcknowledgementLoss(
            "injected begin-parse acknowledgement loss"
        )


def _invalidated_commit_error() -> DBAPIError:
    return DBAPIError(
        statement="COMMIT",
        params=None,
        orig=RuntimeError("injected terminal commit acknowledgement loss"),
        connection_invalidated=True,
    )


class _LostSuccessCommitAcknowledgementRepository(MySqlParseRepository):
    def _finish_success(
        self,
        *,
        context: ConfirmedParseContext,
        parsed_report: ParsedReport,
        completed_at: datetime,
    ) -> SuccessfulParse:
        super()._finish_success(
            context=context,
            parsed_report=parsed_report,
            completed_at=completed_at,
        )
        raise _invalidated_commit_error()


class _LostFailureCommitAcknowledgementRepository(MySqlParseRepository):
    def _finish_failure(
        self,
        *,
        context: ConfirmedParseContext,
        failure: ParseFailure,
        completed_at: datetime,
    ) -> FailedParse:
        super()._finish_failure(
            context=context,
            failure=failure,
            completed_at=completed_at,
        )
        raise _invalidated_commit_error()


class _LostDateChangeCommitAcknowledgementRepository(MySqlParseRepository):
    def _change_report_date(
        self,
        *,
        command: ChangeReportDateCommand,
        changed_at: datetime,
    ) -> None:
        super()._change_report_date(command=command, changed_at=changed_at)
        raise _invalidated_commit_error()


def _is_begin_parse_batch_lock(statement: str) -> bool:
    normalized = " ".join(statement.split()).casefold()
    return (
        "from import_batches as batches" in normalized
        and "inner join raw_files as files" in normalized
        and "processing_operation_digest" in normalized
        and normalized.endswith("for update of batches")
    )


def _is_change_report_date_batch_lock(statement: str) -> bool:
    normalized = " ".join(statement.split()).casefold()
    return (
        "select site_id, status, report_date from import_batches" in normalized
        and normalized.endswith("for update")
    )


def _is_parse_operation_registration_insert(statement: str) -> bool:
    normalized = " ".join(statement.split()).casefold()
    return normalized.startswith("insert into parse_operation_tokens")


def _is_report_date_operation_registration_insert(statement: str) -> bool:
    normalized = " ".join(statement.split()).casefold()
    return normalized.startswith("insert into report_date_operation_tokens")


def _is_parse_operation_registration_lookup(statement: str) -> bool:
    normalized = " ".join(statement.split()).casefold()
    return "from parse_operation_tokens" in normalized


def _is_report_date_operation_registration_lookup(statement: str) -> bool:
    normalized = " ".join(statement.split()).casefold()
    return "from report_date_operation_tokens" in normalized


def _is_finish_success_batch_clear(statement: str) -> bool:
    normalized = " ".join(statement.split()).casefold()
    return (
        normalized.startswith("update import_batches")
        and "status = 'staged'" in normalized
        and "processing_token = null" in normalized
        and "current_successful_parse_attempt_id" in normalized
    )


def _physical_connection_id(connection: Connection) -> int:
    driver_connection: Any = connection.connection.driver_connection
    return int(driver_connection.thread_id())


@pytest.fixture()
def parse_case(
    alembic_config: Config,
    mysql_engine: Engine,
    tmp_path: Path,
) -> Iterator[ParseCase]:
    command.upgrade(alembic_config, "head")
    with mysql_engine.begin() as connection:
        user = connection.execute(
            sa.text(
                """
                INSERT INTO users (
                    username_normalized, display_name, password_hash, status
                ) VALUES (
                    :username, 'Parse Workflow Test', '$argon2id$test', 'active'
                )
                """
            ),
            {"username": f"parse-workflow-{uuid4().hex}"},
        )
        assert user.lastrowid is not None
        user_id = int(user.lastrowid)

    store = LocalContentStore(tmp_path / "storage", max_upload_bytes=1024 * 1024)
    ingest_repository = MySqlIngestRepository(mysql_engine, lock_timeout_seconds=5)
    ingest = IngestService(
        repository=ingest_repository,
        store=store,
        lease_ttl=timedelta(minutes=30),
        lease_renew_interval=timedelta(minutes=5),
        clock=lambda: NOW,
    )
    source_text = (FIXTURE_ROOT / "business-report.csv").read_text(encoding="utf-8")
    created = ingest.ingest(
        BytesIO(source_text.encode("utf-8-sig")),
        ImportCommand(
            original_filename="20260806-BusinessReport-synthetic.csv",
            media_type="text/csv",
            created_by_user_id=user_id,
            site_config_version_id=1,
        ),
    )
    assert isinstance(created, ImportCreated)
    parse_repository = MySqlParseRepository(mysql_engine)
    workflow = ParseWorkflow(
        repository=parse_repository,
        store=store,
        clock=lambda: NOW,
    )
    case = ParseCase(
        engine=mysql_engine,
        store=store,
        repository=parse_repository,
        workflow=workflow,
        user_id=user_id,
        batch_id=created.batch_id,
        additional_batch_ids=[],
        additional_config_version_ids=[],
    )
    try:
        yield case
    finally:
        _cleanup(case)


def _cleanup(case: ParseCase) -> None:
    with case.engine.begin() as connection:
        raw_file_ids = {
            raw_file_id
            for batch_id in (case.batch_id, *case.additional_batch_ids)
            if (raw_file_id := _delete_batch_graph(connection, batch_id)) is not None
        }
        for raw_file_id in raw_file_ids:
            connection.execute(
                sa.text(
                    "DELETE FROM file_ingest_leases WHERE raw_file_id = :raw_file_id"
                ),
                {"raw_file_id": raw_file_id},
            )
            connection.execute(
                sa.text(
                    "DELETE FROM raw_file_integrity_statuses "
                    "WHERE raw_file_id = :raw_file_id"
                ),
                {"raw_file_id": raw_file_id},
            )
            connection.execute(
                sa.text("DELETE FROM raw_files WHERE id = :raw_file_id"),
                {"raw_file_id": raw_file_id},
            )
        for config_id in case.additional_config_version_ids:
            connection.execute(
                sa.text("DELETE FROM site_config_versions WHERE id = :config_id"),
                {"config_id": config_id},
            )
        connection.execute(
            sa.text("DELETE FROM users WHERE id = :user_id"),
            {"user_id": case.user_id},
        )


def _delete_batch_graph(connection: Connection, batch_id: int) -> int | None:
    raw_file_id = connection.scalar(
        sa.text("SELECT raw_file_id FROM import_batches WHERE id = :batch_id"),
        {"batch_id": batch_id},
    )
    if raw_file_id is None:
        return None
    materialized_rows = (
        connection.execute(
            sa.text(
                """
                SELECT versions.id AS version_id, versions.dataset_id
                FROM version_input_batches AS inputs
                INNER JOIN dataset_versions AS versions
                    ON versions.id = inputs.version_id
                WHERE inputs.batch_id = :batch_id
                """
            ),
            {"batch_id": batch_id},
        )
        .mappings()
        .all()
    )
    if materialized_rows:
        version_ids = [int(row["version_id"]) for row in materialized_rows]
        dataset_ids = list({int(row["dataset_id"]) for row in materialized_rows})
        connection.execute(
            sa.text("DELETE FROM version_input_batches WHERE batch_id = :batch_id"),
            {"batch_id": batch_id},
        )
        connection.execute(
            sa.text("DELETE FROM dataset_versions WHERE id IN :version_ids").bindparams(
                sa.bindparam("version_ids", expanding=True)
            ),
            {"version_ids": version_ids},
        )
        connection.execute(
            sa.text("DELETE FROM daily_datasets WHERE id IN :dataset_ids").bindparams(
                sa.bindparam("dataset_ids", expanding=True)
            ),
            {"dataset_ids": dataset_ids},
        )
    connection.execute(
        sa.text(
            """
            UPDATE import_batches
            SET status = 'uploaded',
                current_successful_parse_attempt_id = NULL,
                report_type = NULL,
                source_row_count = NULL,
                processing_token = NULL,
                processing_operation_digest = NULL,
                processing_started_at = NULL,
                error_summary = NULL
            WHERE id = :batch_id
            """
        ),
        {"batch_id": batch_id},
    )
    baseline_ids = list(
        connection.scalars(
            sa.text(
                """
                SELECT id FROM parse_baselines
                WHERE parse_attempt_id IN (
                    SELECT id FROM parse_attempts WHERE batch_id = :batch_id
                )
                """
            ),
            {"batch_id": batch_id},
        )
    )
    if baseline_ids:
        baseline_rows = sa.text(
            "SELECT id FROM parse_baseline_rows "
            "WHERE parse_baseline_id IN :baseline_ids"
        ).bindparams(sa.bindparam("baseline_ids", expanding=True))
        baseline_row_ids = list(
            connection.scalars(
                baseline_rows,
                {"baseline_ids": baseline_ids},
            )
        )
        if baseline_row_ids:
            for table in (
                "business_parse_baseline_rows",
                "return_parse_baseline_rows",
            ):
                connection.execute(
                    sa.text(
                        f"DELETE FROM {table} WHERE parse_baseline_row_id IN :row_ids"
                    ).bindparams(sa.bindparam("row_ids", expanding=True)),
                    {"row_ids": baseline_row_ids},
                )
            connection.execute(
                sa.text(
                    "DELETE FROM parse_baseline_rows WHERE id IN :row_ids"
                ).bindparams(sa.bindparam("row_ids", expanding=True)),
                {"row_ids": baseline_row_ids},
            )
        connection.execute(
            sa.text("DELETE FROM parse_baselines WHERE id IN :baseline_ids").bindparams(
                sa.bindparam("baseline_ids", expanding=True)
            ),
            {"baseline_ids": baseline_ids},
        )
    connection.execute(
        sa.text(
            """
            DELETE FROM parsed_source_rows
            WHERE parse_attempt_id IN (
                SELECT id FROM parse_attempts WHERE batch_id = :batch_id
            )
            """
        ),
        {"batch_id": batch_id},
    )
    connection.execute(
        sa.text("DELETE FROM parse_attempts WHERE batch_id = :batch_id"),
        {"batch_id": batch_id},
    )
    for token_table in (
        "parse_operation_tokens",
        "report_date_operation_tokens",
    ):
        connection.execute(
            sa.text(f"DELETE FROM {token_table} WHERE batch_id = :batch_id"),
            {"batch_id": batch_id},
        )
    connection.execute(
        sa.text(
            "DELETE FROM audit_events "
            "WHERE object_type = 'import_batch' AND object_id = :object_id"
        ),
        {"object_id": str(batch_id)},
    )
    connection.execute(
        sa.text("DELETE FROM import_batches WHERE id = :batch_id"),
        {"batch_id": batch_id},
    )
    return int(raw_file_id)


def _ingest_additional_batch(case: ParseCase) -> int:
    ingest = IngestService(
        repository=MySqlIngestRepository(case.engine, lock_timeout_seconds=5),
        store=case.store,
        lease_ttl=timedelta(minutes=30),
        lease_renew_interval=timedelta(minutes=5),
        clock=lambda: NOW,
    )
    source_text = (FIXTURE_ROOT / "business-report.csv").read_text(encoding="utf-8")
    distinct_source = source_text.replace(
        "Synthetic Linen Shirt",
        "Concurrent Linen Shirt",
        1,
    )
    created = ingest.ingest(
        BytesIO(distinct_source.encode("utf-8-sig")),
        ImportCommand(
            original_filename="20260806-BusinessReport-additional.csv",
            media_type="text/csv",
            created_by_user_id=case.user_id,
            site_config_version_id=1,
        ),
    )
    assert isinstance(created, ImportCreated)
    case.additional_batch_ids.append(created.batch_id)
    return created.batch_id


def _insert_additional_site_config(case: ParseCase) -> int:
    with case.engine.begin() as connection:
        next_version = int(
            connection.scalar(
                sa.text(
                    "SELECT COALESCE(MAX(version_number), 0) + 1 "
                    "FROM site_config_versions WHERE site_id = 1"
                )
            )
            or 1
        )
        created = connection.execute(
            sa.text(
                """
                INSERT INTO site_config_versions (
                    site_id, version_number, source_timezone,
                    reporting_timezone, currency_code, effective_at,
                    change_reason, created_by_user_id
                ) VALUES (
                    1, :version_number, 'UTC', 'UTC', 'USD',
                    UTC_TIMESTAMP(6), 'Frozen configuration test', :user_id
                )
                """
            ),
            {"version_number": next_version, "user_id": case.user_id},
        )
        assert created.lastrowid is not None
        config_id = int(created.lastrowid)
    case.additional_config_version_ids.append(config_id)
    return config_id


def _business_command(
    case: ParseCase,
    *,
    operation_token: UUID,
    batch_id: int | None = None,
) -> ConfirmAndParseCommand:
    return ConfirmAndParseCommand(
        batch_id=case.batch_id if batch_id is None else batch_id,
        report_type="business_report",
        report_date=date(2026, 8, 7),
        encoding="utf-8-sig",
        site_config_version_id=1,
        actor_user_id=case.user_id,
        operation_token=operation_token,
    )


def test_api_configuration_resolution_uses_current_and_batch_frozen_pointers(
    parse_case: ParseCase,
) -> None:
    config_id = _insert_additional_site_config(parse_case)
    with parse_case.engine.begin() as connection:
        batch_frozen_config = int(
            connection.scalar(
                sa.text(
                    "SELECT site_config_version_id FROM import_batches "
                    "WHERE id = :batch_id"
                ),
                {"batch_id": parse_case.batch_id},
            )
        )
        original_current = int(
            connection.scalar(
                sa.text(
                    "SELECT current_config_version_id FROM site_current_configs "
                    "WHERE site_id = 1"
                )
            )
        )
        connection.execute(
            sa.text(
                "UPDATE site_current_configs "
                "SET current_config_version_id = :config_id WHERE site_id = 1"
            ),
            {"config_id": config_id},
        )
    try:
        assert (
            _resolve_current_site_config_version_id(parse_case.engine, None)
            == config_id
        )
        assert (
            _resolve_current_site_config_version_id(parse_case.engine, config_id)
            == config_id
        )
        with pytest.raises(ApiError) as upload_conflict:
            _resolve_current_site_config_version_id(parse_case.engine, original_current)
        assert upload_conflict.value.status_code == 409
        upload_detail = cast(dict[str, str], upload_conflict.value.detail)
        assert upload_detail == {
            "code": "site_config_version_conflict",
            "message": (
                "The supplied site configuration is not the server-selected version."
            ),
        }

        assert (
            _resolve_batch_site_config_version_id(
                parse_case.engine,
                parse_case.batch_id,
                None,
            )
            == batch_frozen_config
        )
        assert (
            _resolve_batch_site_config_version_id(
                parse_case.engine,
                parse_case.batch_id,
                batch_frozen_config,
            )
            == batch_frozen_config
        )
        with pytest.raises(ApiError) as parse_conflict:
            _resolve_batch_site_config_version_id(
                parse_case.engine,
                parse_case.batch_id,
                config_id,
            )
        assert parse_conflict.value.status_code == 409
        parse_detail = cast(dict[str, str], parse_conflict.value.detail)
        assert parse_detail == {
            "code": "site_config_version_conflict",
            "message": (
                "The supplied site configuration is not the server-selected version."
            ),
        }
    finally:
        with parse_case.engine.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE site_current_configs "
                    "SET current_config_version_id = :config_id WHERE site_id = 1"
                ),
                {"config_id": original_current},
            )


def test_parse_rejects_configuration_other_than_the_batch_frozen_version(
    parse_case: ParseCase,
) -> None:
    other_config_id = _insert_additional_site_config(parse_case)
    forged_command = replace(
        _business_command(parse_case, operation_token=uuid4()),
        site_config_version_id=other_config_id,
    )

    with pytest.raises(ParseStateConflict, match="frozen"):
        parse_case.workflow.confirm_and_parse(forged_command)

    with parse_case.engine.connect() as connection:
        batch_config_id = connection.scalar(
            sa.text(
                "SELECT site_config_version_id FROM import_batches WHERE id = :batch_id"
            ),
            {"batch_id": parse_case.batch_id},
        )
        attempt_count = connection.scalar(
            sa.text("SELECT COUNT(*) FROM parse_attempts WHERE batch_id = :batch_id"),
            {"batch_id": parse_case.batch_id},
        )

    assert batch_config_id == 1
    assert attempt_count == 0


def _date_command(
    case: ParseCase,
    *,
    report_date: date,
    operation_token: UUID,
    actor_user_id: int | None = None,
    batch_id: int | None = None,
) -> ChangeReportDateCommand:
    return ChangeReportDateCommand(
        batch_id=case.batch_id if batch_id is None else batch_id,
        report_date=report_date,
        actor_user_id=(case.user_id if actor_user_id is None else actor_user_id),
        operation_token=operation_token,
    )


def _workflow(
    case: ParseCase,
    repository: MySqlParseRepository,
) -> ParseWorkflow:
    return ParseWorkflow(
        repository=repository,
        store=case.store,
        clock=lambda: NOW,
    )


def _parse_state_counts(case: ParseCase) -> tuple[int, int, int]:
    with case.engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    """
                SELECT batches.confirmation_revision,
                       (
                           SELECT COUNT(*) FROM parse_attempts AS attempts
                           WHERE attempts.batch_id = batches.id
                       ) AS attempt_count,
                       (
                           SELECT COUNT(*)
                           FROM parse_baselines AS baselines
                           INNER JOIN parse_attempts AS attempts
                               ON attempts.id = baselines.parse_attempt_id
                           WHERE attempts.batch_id = batches.id
                       ) AS baseline_count
                FROM import_batches AS batches
                WHERE batches.id = :batch_id
                """
                ),
                {"batch_id": case.batch_id},
            )
            .mappings()
            .one()
        )
    return (
        int(row["confirmation_revision"]),
        int(row["attempt_count"]),
        int(row["baseline_count"]),
    )


def _batch_parse_registry_state(
    case: ParseCase,
    batch_id: int,
) -> tuple[str, int, int, int, bool, int]:
    """Read only state needed to prove a rejected token did not mutate a batch."""

    with case.engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT batches.status,
                           batches.confirmation_revision,
                           batches.processing_token IS NOT NULL AS has_processing_token,
                           (
                               SELECT COUNT(*)
                               FROM parse_attempts AS attempts
                               WHERE attempts.batch_id = batches.id
                           ) AS attempt_count,
                           (
                               SELECT COUNT(*)
                               FROM parse_baselines AS baselines
                               INNER JOIN parse_attempts AS attempts
                                   ON attempts.id = baselines.parse_attempt_id
                               WHERE attempts.batch_id = batches.id
                           ) AS baseline_count,
                           (
                               SELECT COUNT(*)
                               FROM parse_operation_tokens AS tokens
                               WHERE tokens.batch_id = batches.id
                           ) AS registry_count
                    FROM import_batches AS batches
                    WHERE batches.id = :batch_id
                    """
                ),
                {"batch_id": batch_id},
            )
            .mappings()
            .one()
        )
    return (
        str(row["status"]),
        int(row["confirmation_revision"]),
        int(row["attempt_count"]),
        int(row["baseline_count"]),
        bool(row["has_processing_token"]),
        int(row["registry_count"]),
    )


def _change_command_field(
    command: ConfirmAndParseCommand,
    field_name: str,
) -> ConfirmAndParseCommand:
    if field_name == "batch_id":
        return replace(command, batch_id=command.batch_id + 1)
    if field_name == "report_type":
        return replace(command, report_type="return_report")
    if field_name == "report_date":
        return replace(command, report_date=command.report_date + timedelta(days=1))
    if field_name == "encoding":
        return replace(command, encoding="utf-8")
    if field_name == "site_config_version_id":
        return replace(
            command,
            site_config_version_id=command.site_config_version_id + 1,
        )
    if field_name == "actor_user_id":
        return replace(command, actor_user_id=command.actor_user_id + 1)
    raise AssertionError(f"unhandled command field: {field_name}")


def test_success_then_failed_reparse_preserves_the_current_baseline(
    parse_case: ParseCase,
) -> None:
    suggestion = parse_case.workflow.inspect(parse_case.batch_id)

    assert suggestion.status == "suggested"
    assert suggestion.report_type == "business_report"
    assert suggestion.detected_report_date == date(2026, 8, 6)
    assert suggestion.encoding == "utf-8-sig"

    success_command = ConfirmAndParseCommand(
        batch_id=parse_case.batch_id,
        report_type="business_report",
        report_date=date(2026, 8, 7),
        encoding="utf-8-sig",
        site_config_version_id=1,
        actor_user_id=parse_case.user_id,
        operation_token=SUCCESS_TOKEN,
    )
    successful = parse_case.workflow.confirm_and_parse(success_command)
    assert isinstance(successful, SuccessfulParse)
    assert successful.report_type == "business_report"
    assert successful.source_row_count == 2
    assert (
        parse_case.repository.recover_terminal(
            SUCCESS_TOKEN,
            expected_batch_id=parse_case.batch_id,
            operation_digest=success_command.operation_digest,
        )
        == successful
    )
    assert parse_case.workflow.confirm_and_parse(success_command) == successful

    failed = parse_case.workflow.confirm_and_parse(
        ConfirmAndParseCommand(
            batch_id=parse_case.batch_id,
            report_type="return_report",
            report_date=date(2026, 8, 8),
            encoding="utf-8-sig",
            site_config_version_id=1,
            actor_user_id=parse_case.user_id,
            operation_token=FAILURE_TOKEN,
        )
    )
    assert isinstance(failed, FailedParse)
    assert failed.error_code == "header_mismatch"

    with parse_case.engine.connect() as connection:
        batch = (
            connection.execute(
                sa.text(
                    """
                SELECT status, report_type, confirmed_report_type, report_date,
                       current_successful_parse_attempt_id, source_row_count,
                       confirmation_revision, processing_token
                FROM import_batches
                WHERE id = :batch_id
                """
                ),
                {"batch_id": parse_case.batch_id},
            )
            .mappings()
            .one()
        )
        attempts = (
            connection.execute(
                sa.text(
                    """
                SELECT id, attempt_number, report_type, status,
                       confirmation_revision, source_row_count
                FROM parse_attempts
                WHERE batch_id = :batch_id
                ORDER BY attempt_number
                """
                ),
                {"batch_id": parse_case.batch_id},
            )
            .mappings()
            .all()
        )
        baseline_count = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*) FROM parse_baselines
                WHERE parse_attempt_id IN (
                    SELECT id FROM parse_attempts WHERE batch_id = :batch_id
                )
                """
            ),
            {"batch_id": parse_case.batch_id},
        )
        business_row_count = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM business_parse_baseline_rows AS typed
                INNER JOIN parse_baselines AS baselines
                    ON baselines.id = typed.parse_baseline_id
                INNER JOIN parse_attempts AS attempts
                    ON attempts.id = baselines.parse_attempt_id
                WHERE attempts.batch_id = :batch_id
                """
            ),
            {"batch_id": parse_case.batch_id},
        )

    assert batch["status"] == "processing_failed"
    assert batch["report_type"] == "business_report"
    assert batch["confirmed_report_type"] == "return_report"
    assert batch["report_date"] == date(2026, 8, 8)
    assert batch["current_successful_parse_attempt_id"] == successful.parse_attempt_id
    assert batch["source_row_count"] == 2
    assert batch["confirmation_revision"] == 2
    assert batch["processing_token"] is None
    assert [row["status"] for row in attempts] == ["succeeded", "failed"]
    assert [row["report_type"] for row in attempts] == [
        "business_report",
        "return_report",
    ]
    assert attempts[1]["source_row_count"] == 2
    assert baseline_count == 1
    assert business_row_count == 2


def test_retry_after_begin_acknowledgement_loss_reuses_the_active_revision(
    parse_case: ParseCase,
) -> None:
    operation_token = uuid4()
    parse_command = _business_command(
        parse_case,
        operation_token=operation_token,
    )
    lost_acknowledgement_workflow = _workflow(
        parse_case,
        _LostBeginAcknowledgementRepository(parse_case.engine),
    )

    with pytest.raises(
        _InjectedBeginAcknowledgementLoss,
        match="begin-parse acknowledgement loss",
    ):
        lost_acknowledgement_workflow.confirm_and_parse(parse_command)

    assert _parse_state_counts(parse_case) == (1, 0, 0)
    with pytest.raises(ParseAlreadyRunning, match="cannot change"):
        parse_case.workflow.change_report_date(
            ChangeReportDateCommand(
                batch_id=parse_case.batch_id,
                report_date=date(2026, 8, 9),
                actor_user_id=parse_case.user_id,
                operation_token=uuid4(),
            )
        )
    with pytest.raises(
        ParseStateConflict,
        match=r"operation token.*different parse choices",
    ):
        parse_case.workflow.confirm_and_parse(
            replace(
                parse_command,
                report_date=parse_command.report_date + timedelta(days=1),
            )
        )
    assert _parse_state_counts(parse_case) == (1, 0, 0)

    successful = parse_case.workflow.confirm_and_parse(parse_command)

    assert isinstance(successful, SuccessfulParse)
    assert successful.confirmation_revision == 1
    assert _parse_state_counts(parse_case) == (1, 1, 1)
    assert parse_case.workflow.confirm_and_parse(parse_command) == successful
    assert _parse_state_counts(parse_case) == (1, 1, 1)


def test_concurrent_same_operation_token_uses_one_revision_and_attempt(
    parse_case: ParseCase,
    mysql_settings: DatabaseSettings,
) -> None:
    first_engine = create_database_engine(mysql_settings)
    second_engine = create_database_engine(mysql_settings)
    row_lock_barrier = Barrier(2)
    connection_ids: dict[str, int] = {}

    def pause_first_after_row_lock(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_begin_parse_batch_lock(statement):
            connection_ids["first"] = _physical_connection_id(connection)
            row_lock_barrier.wait(timeout=10)

    def pause_second_before_row_lock(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_begin_parse_batch_lock(statement):
            connection_ids["second"] = _physical_connection_id(connection)
            row_lock_barrier.wait(timeout=10)

    sa.event.listen(
        first_engine,
        "after_cursor_execute",
        pause_first_after_row_lock,
    )
    sa.event.listen(
        second_engine,
        "before_cursor_execute",
        pause_second_before_row_lock,
    )
    parse_command = _business_command(parse_case, operation_token=uuid4())

    def parse(repository: MySqlParseRepository) -> SuccessfulParse:
        result = _workflow(parse_case, repository).confirm_and_parse(parse_command)
        assert isinstance(result, SuccessfulParse)
        return result

    try:
        first_repository = MySqlParseRepository(first_engine)
        second_repository = MySqlParseRepository(second_engine)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(parse, first_repository)
            second = executor.submit(parse, second_repository)
            first_result = first.result(timeout=20)
            second_result = second.result(timeout=20)
    finally:
        sa.event.remove(
            first_engine,
            "after_cursor_execute",
            pause_first_after_row_lock,
        )
        sa.event.remove(
            second_engine,
            "before_cursor_execute",
            pause_second_before_row_lock,
        )
        first_engine.dispose()
        second_engine.dispose()

    assert connection_ids["first"] != connection_ids["second"]
    assert first_result == second_result
    assert first_result.confirmation_revision == 1
    assert _parse_state_counts(parse_case) == (1, 1, 1)
    with parse_case.engine.connect() as connection:
        confirmation_event_count = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*) FROM audit_events
                WHERE object_type = 'import_batch'
                  AND object_id = :batch_id
                  AND event_type = 'import_selection_confirmed'
                """
            ),
            {"batch_id": str(parse_case.batch_id)},
        )
    assert confirmation_event_count == 1
    assert parse_case.workflow.confirm_and_parse(parse_command) == first_result
    assert _parse_state_counts(parse_case) == (1, 1, 1)


def test_concurrent_parse_token_for_different_batches_conflicts_without_mutation(
    parse_case: ParseCase,
    mysql_settings: DatabaseSettings,
) -> None:
    """A committed registry claim wins even when the other batch was already waiting."""

    conflicting_batch_id = _ingest_additional_batch(parse_case)
    first_engine = create_database_engine(mysql_settings)
    second_engine = create_database_engine(mysql_settings)
    first_registration_inserted = Event()
    second_registry_lookup_started = Event()
    allow_first_transaction_to_finish = Event()
    connection_ids: dict[str, int] = {}

    def pause_first_after_registration_insert(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_parse_operation_registration_insert(statement):
            connection_ids["first"] = _physical_connection_id(connection)
            first_registration_inserted.set()
            assert allow_first_transaction_to_finish.wait(timeout=10)

    def record_second_registry_lookup(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_parse_operation_registration_lookup(statement):
            connection_ids["second"] = _physical_connection_id(connection)
            second_registry_lookup_started.set()

    sa.event.listen(
        first_engine,
        "after_cursor_execute",
        pause_first_after_registration_insert,
    )
    sa.event.listen(
        second_engine,
        "before_cursor_execute",
        record_second_registry_lookup,
    )
    operation_token = uuid4()
    first_command = _business_command(parse_case, operation_token=operation_token)
    conflicting_command = _business_command(
        parse_case,
        batch_id=conflicting_batch_id,
        operation_token=operation_token,
    )

    def parse_first() -> SuccessfulParse:
        result = _workflow(
            parse_case,
            MySqlParseRepository(first_engine),
        ).confirm_and_parse(first_command)
        assert isinstance(result, SuccessfulParse)
        return result

    def parse_conflicting_batch() -> ParseStateConflict:
        with pytest.raises(ParseStateConflict, match="another import batch") as error:
            _workflow(
                parse_case,
                MySqlParseRepository(second_engine),
            ).confirm_and_parse(conflicting_command)
        return error.value

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(parse_first)
            assert first_registration_inserted.wait(timeout=10)
            conflicting = executor.submit(parse_conflicting_batch)
            assert second_registry_lookup_started.wait(timeout=10)
            allow_first_transaction_to_finish.set()
            first_result = first.result(timeout=20)
            conflicting_error = conflicting.result(timeout=20)
    finally:
        allow_first_transaction_to_finish.set()
        sa.event.remove(
            first_engine,
            "after_cursor_execute",
            pause_first_after_registration_insert,
        )
        sa.event.remove(
            second_engine,
            "before_cursor_execute",
            record_second_registry_lookup,
        )
        first_engine.dispose()
        second_engine.dispose()

    assert connection_ids["first"] != connection_ids["second"]
    assert isinstance(first_result, SuccessfulParse)
    assert "another import batch" in str(conflicting_error)
    assert _batch_parse_registry_state(parse_case, parse_case.batch_id) == (
        "staged",
        1,
        1,
        1,
        False,
        1,
    )
    assert _batch_parse_registry_state(parse_case, conflicting_batch_id) == (
        "uploaded",
        0,
        0,
        0,
        False,
        0,
    )
    with pytest.raises(ParseStateConflict, match="another import batch"):
        parse_case.workflow.confirm_and_parse(conflicting_command)


def test_finish_commit_pause_keeps_parse_token_owned_by_its_original_batch(
    parse_case: ParseCase,
    mysql_settings: DatabaseSettings,
) -> None:
    """An uncommitted terminal write cannot make its global token reusable."""

    conflicting_batch_id = _ingest_additional_batch(parse_case)
    first_engine = create_database_engine(mysql_settings)
    second_engine = create_database_engine(mysql_settings)
    finish_writes_ready = Event()
    allow_finish_commit = Event()
    second_registry_read = Event()
    connection_ids: dict[str, int] = {}

    def pause_after_first_finish_batch_clear(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_finish_success_batch_clear(statement):
            connection_ids["first"] = _physical_connection_id(connection)
            finish_writes_ready.set()
            assert allow_finish_commit.wait(timeout=10)

    def record_second_registry_read(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_parse_operation_registration_lookup(statement):
            connection_ids["second"] = _physical_connection_id(connection)
            second_registry_read.set()

    sa.event.listen(
        first_engine,
        "after_cursor_execute",
        pause_after_first_finish_batch_clear,
    )
    sa.event.listen(
        second_engine,
        "before_cursor_execute",
        record_second_registry_read,
    )
    operation_token = uuid4()
    first_command = _business_command(parse_case, operation_token=operation_token)
    conflicting_command = _business_command(
        parse_case,
        batch_id=conflicting_batch_id,
        operation_token=operation_token,
    )

    def parse_first() -> SuccessfulParse:
        result = _workflow(
            parse_case,
            MySqlParseRepository(first_engine),
        ).confirm_and_parse(first_command)
        assert isinstance(result, SuccessfulParse)
        return result

    def parse_conflicting_batch() -> ParseStateConflict:
        with pytest.raises(ParseStateConflict, match="another import batch") as error:
            _workflow(
                parse_case,
                MySqlParseRepository(second_engine),
            ).confirm_and_parse(conflicting_command)
        return error.value

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(parse_first)
            assert finish_writes_ready.wait(timeout=10)
            conflicting = executor.submit(parse_conflicting_batch)
            conflicting_error = conflicting.result(timeout=10)
            assert second_registry_read.is_set()
            allow_finish_commit.set()
            first_result = first.result(timeout=20)
    finally:
        allow_finish_commit.set()
        sa.event.remove(
            first_engine,
            "after_cursor_execute",
            pause_after_first_finish_batch_clear,
        )
        sa.event.remove(
            second_engine,
            "before_cursor_execute",
            record_second_registry_read,
        )
        first_engine.dispose()
        second_engine.dispose()

    assert connection_ids["first"] != connection_ids["second"]
    assert isinstance(first_result, SuccessfulParse)
    assert "another import batch" in str(conflicting_error)
    assert _batch_parse_registry_state(parse_case, parse_case.batch_id) == (
        "staged",
        1,
        1,
        1,
        False,
        1,
    )
    assert _batch_parse_registry_state(parse_case, conflicting_batch_id) == (
        "uploaded",
        0,
        0,
        0,
        False,
        0,
    )
    with pytest.raises(ParseStateConflict, match="another import batch"):
        parse_case.workflow.confirm_and_parse(conflicting_command)


def test_report_date_changes_without_creating_another_parse_attempt(
    parse_case: ParseCase,
) -> None:
    parse_command = _business_command(parse_case, operation_token=uuid4())
    successful = parse_case.workflow.confirm_and_parse(parse_command)
    assert isinstance(successful, SuccessfulParse)

    operation_token = uuid4()
    parse_case.workflow.change_report_date(
        _date_command(
            parse_case,
            report_date=date(2026, 8, 10),
            operation_token=operation_token,
        )
    )

    with parse_case.engine.connect() as connection:
        batch = connection.execute(
            sa.text(
                """
                SELECT report_date, report_type,
                       current_successful_parse_attempt_id,
                       confirmation_revision
                FROM import_batches
                WHERE id = :batch_id
                """
            ),
            {"batch_id": parse_case.batch_id},
        ).one()
        date_change_event = (
            connection.execute(
                sa.text(
                    """
                SELECT request_id,
                       JSON_UNQUOTE(JSON_EXTRACT(
                           redacted_payload, '$.operation_digest'
                       )) AS operation_digest,
                       JSON_UNQUOTE(JSON_EXTRACT(
                           redacted_payload, '$.previous_report_date'
                       )) AS previous_report_date,
                       JSON_UNQUOTE(JSON_EXTRACT(
                           redacted_payload, '$.report_date'
                       )) AS report_date,
                       JSON_UNQUOTE(JSON_EXTRACT(
                           redacted_payload, '$.changed'
                       )) AS changed
                FROM audit_events
                WHERE object_type = 'import_batch'
                  AND object_id = :batch_id
                  AND event_type = 'import_report_date_change_applied'
                """
                ),
                {"batch_id": str(parse_case.batch_id)},
            )
            .mappings()
            .one()
        )

    assert tuple(batch) == (
        date(2026, 8, 10),
        "business_report",
        successful.parse_attempt_id,
        1,
    )
    assert date_change_event["request_id"] == str(operation_token)
    assert (
        date_change_event["operation_digest"]
        == _date_command(
            parse_case,
            report_date=date(2026, 8, 10),
            operation_token=operation_token,
        ).operation_digest.hex()
    )
    assert date_change_event["previous_report_date"] == "2026-08-07"
    assert date_change_event["report_date"] == "2026-08-10"
    assert date_change_event["changed"] == "true"
    assert _parse_state_counts(parse_case) == (1, 1, 1)


def test_report_date_retry_after_ack_loss_does_not_overwrite_a_later_change(
    parse_case: ParseCase,
) -> None:
    first_token = uuid4()
    first_command = _date_command(
        parse_case,
        report_date=date(2026, 8, 10),
        operation_token=first_token,
    )
    lost_acknowledgement_workflow = _workflow(
        parse_case,
        _LostDateChangeCommitAcknowledgementRepository(parse_case.engine),
    )

    lost_acknowledgement_workflow.change_report_date(first_command)
    parse_case.workflow.change_report_date(
        _date_command(
            parse_case,
            report_date=date(2026, 8, 11),
            operation_token=uuid4(),
        )
    )
    parse_case.workflow.change_report_date(first_command)

    with parse_case.engine.connect() as connection:
        batch_date = connection.scalar(
            sa.text("SELECT report_date FROM import_batches WHERE id = :batch_id"),
            {"batch_id": parse_case.batch_id},
        )
        applied_events = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM audit_events
                WHERE event_type = 'import_report_date_change_applied'
                  AND object_type = 'import_batch'
                  AND object_id = :batch_id
                """
            ),
            {"batch_id": str(parse_case.batch_id)},
        )

    assert batch_date == date(2026, 8, 11)
    assert applied_events == 2
    assert _parse_state_counts(parse_case) == (0, 0, 0)


@pytest.mark.parametrize("field_name", ["report_date", "actor_user_id"])
def test_report_date_token_rejects_changed_command_fields(
    parse_case: ParseCase,
    field_name: str,
) -> None:
    operation_token = uuid4()
    command = _date_command(
        parse_case,
        report_date=date(2026, 8, 10),
        operation_token=operation_token,
    )
    parse_case.workflow.change_report_date(command)
    changed_command = (
        replace(command, report_date=date(2026, 8, 11))
        if field_name == "report_date"
        else replace(command, actor_user_id=parse_case.user_id + 1)
    )

    with pytest.raises(
        ParseStateConflict,
        match=r"date-change operation token.*different command fields",
    ):
        parse_case.workflow.change_report_date(changed_command)

    with parse_case.engine.connect() as connection:
        batch_date = connection.scalar(
            sa.text("SELECT report_date FROM import_batches WHERE id = :batch_id"),
            {"batch_id": parse_case.batch_id},
        )
        event_count = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*) FROM audit_events
                WHERE event_type = 'import_report_date_change_applied'
                  AND request_id = :request_id
                """
            ),
            {"request_id": str(operation_token)},
        )

    assert batch_date == date(2026, 8, 10)
    assert event_count == 1
    assert _parse_state_counts(parse_case) == (0, 0, 0)


def test_report_date_change_is_rejected_after_batch_materialization(
    parse_case: ParseCase,
) -> None:
    dataset_date = date(2090, 1, 1) + timedelta(days=parse_case.batch_id)
    with parse_case.engine.begin() as connection:
        dataset = connection.execute(
            sa.text(
                """
                INSERT INTO daily_datasets (site_id, report_date, report_type)
                VALUES (1, :report_date, 'business_report')
                """
            ),
            {"report_date": dataset_date},
        )
        assert dataset.lastrowid is not None
        version = connection.execute(
            sa.text(
                """
                INSERT INTO dataset_versions (
                    dataset_id, report_type, version_no, status,
                    ruleset_version, created_by
                ) VALUES (
                    :dataset_id, 'business_report', 1, 'draft',
                    'materialized-date-test-v1', :user_id
                )
                """
            ),
            {
                "dataset_id": int(dataset.lastrowid),
                "user_id": parse_case.user_id,
            },
        )
        assert version.lastrowid is not None
        connection.execute(
            sa.text(
                """
                INSERT INTO version_input_batches (
                    version_id, batch_id, input_ordinal, input_role
                ) VALUES (:version_id, :batch_id, 1, 'primary')
                """
            ),
            {
                "version_id": int(version.lastrowid),
                "batch_id": parse_case.batch_id,
            },
        )

    operation_token = uuid4()
    with pytest.raises(ParseStateConflict, match="materialized batch"):
        parse_case.workflow.change_report_date(
            _date_command(
                parse_case,
                report_date=date(2026, 8, 10),
                operation_token=operation_token,
            )
        )

    with parse_case.engine.connect() as connection:
        batch_date = connection.scalar(
            sa.text("SELECT report_date FROM import_batches WHERE id = :batch_id"),
            {"batch_id": parse_case.batch_id},
        )
        event_count = connection.scalar(
            sa.text("SELECT COUNT(*) FROM audit_events WHERE request_id = :request_id"),
            {"request_id": str(operation_token)},
        )
    assert batch_date is None
    assert event_count == 0
    assert _parse_state_counts(parse_case) == (0, 0, 0)


def test_report_date_change_is_rejected_for_a_rejected_batch(
    parse_case: ParseCase,
) -> None:
    with parse_case.engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE import_batches SET status = 'rejected' WHERE id = :batch_id"
            ),
            {"batch_id": parse_case.batch_id},
        )
    operation_token = uuid4()

    with pytest.raises(ParseStateConflict, match="rejected batch"):
        parse_case.workflow.change_report_date(
            _date_command(
                parse_case,
                report_date=date(2026, 8, 10),
                operation_token=operation_token,
            )
        )

    with parse_case.engine.connect() as connection:
        batch_date = connection.scalar(
            sa.text("SELECT report_date FROM import_batches WHERE id = :batch_id"),
            {"batch_id": parse_case.batch_id},
        )
        event_count = connection.scalar(
            sa.text("SELECT COUNT(*) FROM audit_events WHERE request_id = :request_id"),
            {"request_id": str(operation_token)},
        )
    assert batch_date is None
    assert event_count == 0
    assert _parse_state_counts(parse_case) == (0, 0, 0)


def test_same_report_date_still_persists_an_applied_terminal_audit(
    parse_case: ParseCase,
) -> None:
    first_token = uuid4()
    second_token = uuid4()
    report_date = date(2026, 8, 10)
    parse_case.workflow.change_report_date(
        _date_command(
            parse_case,
            report_date=report_date,
            operation_token=first_token,
        )
    )
    parse_case.workflow.change_report_date(
        _date_command(
            parse_case,
            report_date=report_date,
            operation_token=second_token,
        )
    )

    with parse_case.engine.connect() as connection:
        events = (
            connection.execute(
                sa.text(
                    """
                SELECT request_id,
                       JSON_UNQUOTE(JSON_EXTRACT(
                           redacted_payload, '$.changed'
                       )) AS changed
                FROM audit_events
                WHERE event_type = 'import_report_date_change_applied'
                  AND request_id IN (:first_token, :second_token)
                ORDER BY id
                """
                ),
                {
                    "first_token": str(first_token),
                    "second_token": str(second_token),
                },
            )
            .mappings()
            .all()
        )

    assert [(row["request_id"], row["changed"]) for row in events] == [
        (str(first_token), "true"),
        (str(second_token), "false"),
    ]
    assert _parse_state_counts(parse_case) == (0, 0, 0)


def test_concurrent_same_report_date_token_writes_one_terminal_audit(
    parse_case: ParseCase,
    mysql_settings: DatabaseSettings,
) -> None:
    first_engine = create_database_engine(mysql_settings)
    second_engine = create_database_engine(mysql_settings)
    row_lock_barrier = Barrier(2)
    connection_ids: dict[str, int] = {}

    def pause_first_after_row_lock(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_change_report_date_batch_lock(statement):
            connection_ids["first"] = _physical_connection_id(connection)
            row_lock_barrier.wait(timeout=10)

    def pause_second_before_row_lock(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_change_report_date_batch_lock(statement):
            connection_ids["second"] = _physical_connection_id(connection)
            row_lock_barrier.wait(timeout=10)

    sa.event.listen(
        first_engine,
        "after_cursor_execute",
        pause_first_after_row_lock,
    )
    sa.event.listen(
        second_engine,
        "before_cursor_execute",
        pause_second_before_row_lock,
    )
    operation_token = uuid4()
    date_command = _date_command(
        parse_case,
        report_date=date(2026, 8, 10),
        operation_token=operation_token,
    )

    def change(repository: MySqlParseRepository) -> None:
        _workflow(parse_case, repository).change_report_date(date_command)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                change,
                MySqlParseRepository(first_engine),
            )
            second = executor.submit(
                change,
                MySqlParseRepository(second_engine),
            )
            first.result(timeout=20)
            second.result(timeout=20)
    finally:
        sa.event.remove(
            first_engine,
            "after_cursor_execute",
            pause_first_after_row_lock,
        )
        sa.event.remove(
            second_engine,
            "before_cursor_execute",
            pause_second_before_row_lock,
        )
        first_engine.dispose()
        second_engine.dispose()

    with parse_case.engine.connect() as connection:
        batch_date = connection.scalar(
            sa.text("SELECT report_date FROM import_batches WHERE id = :batch_id"),
            {"batch_id": parse_case.batch_id},
        )
        event_count = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*) FROM audit_events
                WHERE event_type = 'import_report_date_change_applied'
                  AND request_id = :request_id
                """
            ),
            {"request_id": str(operation_token)},
        )

    assert connection_ids["first"] != connection_ids["second"]
    assert batch_date == date(2026, 8, 10)
    assert event_count == 1
    assert _parse_state_counts(parse_case) == (0, 0, 0)


def test_concurrent_report_date_token_for_different_batches_conflicts_without_audit(
    parse_case: ParseCase,
    mysql_settings: DatabaseSettings,
) -> None:
    conflicting_batch_id = _ingest_additional_batch(parse_case)
    first_engine = create_database_engine(mysql_settings)
    second_engine = create_database_engine(mysql_settings)
    first_registration_inserted = Event()
    second_registration_started = Event()
    allow_first_transaction_to_finish = Event()
    connection_ids: dict[str, int] = {}

    def pause_first_after_registration_insert(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_report_date_operation_registration_insert(statement):
            connection_ids["first"] = _physical_connection_id(connection)
            first_registration_inserted.set()
            assert allow_first_transaction_to_finish.wait(timeout=10)

    def record_second_registration_attempt(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_report_date_operation_registration_insert(statement):
            connection_ids["second"] = _physical_connection_id(connection)
            second_registration_started.set()

    sa.event.listen(
        first_engine,
        "after_cursor_execute",
        pause_first_after_registration_insert,
    )
    sa.event.listen(
        second_engine,
        "before_cursor_execute",
        record_second_registration_attempt,
    )
    operation_token = uuid4()
    first_command = _date_command(
        parse_case,
        report_date=date(2026, 8, 10),
        operation_token=operation_token,
    )
    conflicting_command = _date_command(
        parse_case,
        batch_id=conflicting_batch_id,
        report_date=date(2026, 8, 11),
        operation_token=operation_token,
    )

    def change_first() -> None:
        _workflow(
            parse_case,
            MySqlParseRepository(first_engine),
        ).change_report_date(first_command)

    def change_conflicting_batch() -> ParseStateConflict:
        with pytest.raises(
            ParseStateConflict,
            match="another import batch",
        ) as error:
            _workflow(
                parse_case,
                MySqlParseRepository(second_engine),
            ).change_report_date(conflicting_command)
        return error.value

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(change_first)
            assert first_registration_inserted.wait(timeout=10)
            conflicting = executor.submit(change_conflicting_batch)
            assert second_registration_started.wait(timeout=10)
            allow_first_transaction_to_finish.set()
            first.result(timeout=20)
            conflicting_error = conflicting.result(timeout=20)
    finally:
        allow_first_transaction_to_finish.set()
        sa.event.remove(
            first_engine,
            "after_cursor_execute",
            pause_first_after_registration_insert,
        )
        sa.event.remove(
            second_engine,
            "before_cursor_execute",
            record_second_registration_attempt,
        )
        first_engine.dispose()
        second_engine.dispose()

    assert connection_ids["first"] != connection_ids["second"]
    assert "another import batch" in str(conflicting_error)
    with parse_case.engine.connect() as connection:
        batches = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, report_date
                    FROM import_batches
                    WHERE id IN :batch_ids
                    ORDER BY id
                    """
                ).bindparams(sa.bindparam("batch_ids", expanding=True)),
                {"batch_ids": [parse_case.batch_id, conflicting_batch_id]},
            )
            .mappings()
            .all()
        )
        events = (
            connection.execute(
                sa.text(
                    """
                    SELECT object_id
                    FROM audit_events
                    WHERE event_type = 'import_report_date_change_applied'
                      AND request_id = :request_id
                    ORDER BY id
                    """
                ),
                {"request_id": str(operation_token)},
            )
            .mappings()
            .all()
        )
        registry_rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT batch_id
                    FROM report_date_operation_tokens
                    WHERE operation_token = :operation_token
                    """
                ),
                {"operation_token": operation_token.bytes},
            )
            .mappings()
            .all()
        )

    assert [(int(row["id"]), row["report_date"]) for row in batches] == [
        (parse_case.batch_id, date(2026, 8, 10)),
        (conflicting_batch_id, None),
    ]
    assert [row["object_id"] for row in events] == [str(parse_case.batch_id)]
    assert [int(row["batch_id"]) for row in registry_rows] == [parse_case.batch_id]
    with pytest.raises(ParseStateConflict, match="another import batch"):
        parse_case.workflow.change_report_date(conflicting_command)


def test_success_commit_acknowledgement_loss_recovers_without_duplicate_rows(
    parse_case: ParseCase,
) -> None:
    parse_command = _business_command(
        parse_case,
        operation_token=uuid4(),
    )
    lost_acknowledgement_workflow = _workflow(
        parse_case,
        _LostSuccessCommitAcknowledgementRepository(parse_case.engine),
    )

    successful = lost_acknowledgement_workflow.confirm_and_parse(parse_command)

    assert isinstance(successful, SuccessfulParse)
    assert successful.confirmation_revision == 1
    assert _parse_state_counts(parse_case) == (1, 1, 1)
    assert parse_case.workflow.confirm_and_parse(parse_command) == successful
    assert _parse_state_counts(parse_case) == (1, 1, 1)


def test_failure_commit_acknowledgement_loss_recovers_without_duplicate_rows(
    parse_case: ParseCase,
) -> None:
    parse_command = replace(
        _business_command(parse_case, operation_token=uuid4()),
        report_type="return_report",
    )
    lost_acknowledgement_workflow = _workflow(
        parse_case,
        _LostFailureCommitAcknowledgementRepository(parse_case.engine),
    )

    failed = lost_acknowledgement_workflow.confirm_and_parse(parse_command)

    assert isinstance(failed, FailedParse)
    assert failed.confirmation_revision == 1
    assert failed.error_code == "header_mismatch"
    assert _parse_state_counts(parse_case) == (1, 1, 0)
    assert parse_case.workflow.confirm_and_parse(parse_command) == failed
    assert _parse_state_counts(parse_case) == (1, 1, 0)


@pytest.mark.parametrize(
    ("field_name", "expected_message"),
    [
        pytest.param(
            "batch_id",
            r"operation token belongs to another import batch",
            id="batch_id",
        ),
        pytest.param(
            "report_type",
            r"operation token.*different parse choices",
            id="report_type",
        ),
        pytest.param(
            "report_date",
            r"operation token.*different parse choices",
            id="report_date",
        ),
        pytest.param(
            "encoding",
            r"operation token.*different parse choices",
            id="encoding",
        ),
        pytest.param(
            "site_config_version_id",
            r"operation token.*different parse choices",
            id="site_config_version_id",
        ),
        pytest.param(
            "actor_user_id",
            r"operation token.*different parse choices",
            id="actor_user_id",
        ),
    ],
)
def test_terminal_operation_token_rejects_changed_command_fields(
    parse_case: ParseCase,
    field_name: str,
    expected_message: str,
) -> None:
    parse_command = _business_command(
        parse_case,
        operation_token=uuid4(),
    )
    successful = parse_case.workflow.confirm_and_parse(parse_command)
    assert isinstance(successful, SuccessfulParse)

    with pytest.raises(
        ParseStateConflict,
        match=expected_message,
    ):
        parse_case.workflow.confirm_and_parse(
            _change_command_field(parse_command, field_name)
        )

    assert _parse_state_counts(parse_case) == (1, 1, 1)
