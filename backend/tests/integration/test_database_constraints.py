from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.imports.repository import MySqlIngestRepository
from app.imports.service import IngestService
from app.imports.storage import LocalContentStore
from app.imports.types import ImportCommand, ImportCreated
from app.parsers.repository import MySqlParseRepository, ParseStateConflict
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.mysql

APPEND_ONLY_EVENT_TABLES = (
    "issue_review_events",
    "data_change_events",
    "field_changes",
    "row_changes",
    "audit_events",
    "publication_events",
    "draft_disposition_events",
)

OPERATION_TOKEN_TABLES = (
    "parse_operation_tokens",
    "report_date_operation_tokens",
)

IMMUTABLE_RUNTIME_TABLES = (
    "site_config_versions",
    "raw_files",
    "parse_operation_tokens",
    "report_date_operation_tokens",
    "parse_attempts",
    "parsed_source_rows",
    "daily_datasets",
    "version_parent_versions",
    "version_input_batches",
    "parse_baselines",
    "parse_baseline_rows",
    "business_parse_baseline_rows",
    "return_parse_baseline_rows",
    "version_base_snapshots",
    "version_base_snapshot_members",
    "version_base_rows",
    "business_version_base_rows",
    "return_version_base_rows",
    "validation_runs",
    "validation_issues",
    "issue_review_events",
    "data_change_events",
    "field_changes",
    "row_changes",
    "note_threads",
    "notes",
    "audit_events",
    "publication_events",
    "publication_commands",
    "publication_command_results",
    "review_operation_tokens",
    "review_operation_results",
    "version_review_events",
    "draft_operation_tokens",
    "draft_operation_results",
    "draft_disposition_events",
)


@dataclass(frozen=True, slots=True)
class _RuntimeDatabase:
    engine: Engine
    username: str


@dataclass(frozen=True, slots=True)
class _BackupDatabase:
    engine: Engine
    username: str


@dataclass(frozen=True, slots=True)
class _AppendOnlyEventFixture:
    user_id: int
    dataset_id: int
    version_id: int
    version_row_id: int
    validation_run_id: int
    validation_issue_id: int
    publication_command_id: int
    request_id: str
    migration_connection_id: int


def _insert_user(connection: Connection) -> int:
    result = connection.execute(
        sa.text(
            """
            INSERT INTO users (
                username_normalized, display_name, password_hash, status
            ) VALUES (:username, 'Constraint Test', '$argon2id$test', 'active')
            """
        ),
        {"username": f"constraint-{uuid4().hex}"},
    )
    assert result.lastrowid is not None
    return int(result.lastrowid)


def _insert_stage_four_batch(
    connection: Connection,
    *,
    user_id: int,
    site_id: int = 1,
    site_config_version_id: int = 1,
    report_type: str = "business_report",
    status: str = "uploaded",
    processing_token: bytes | None = None,
) -> int:
    if (status == "processing") != (processing_token is not None):
        raise ValueError("processing status and token must be supplied together")
    raw_file = connection.execute(
        sa.text(
            """
            INSERT INTO raw_files (
                sha256, storage_key, original_filename,
                size_bytes, uploaded_by_user_id
            ) VALUES (:digest, :storage_key, 'stage-four.csv', 1, :user_id)
            """
        ),
        {
            "digest": uuid4().bytes + uuid4().bytes,
            "storage_key": f"sha256/stage-four/{uuid4().hex}",
            "user_id": user_id,
        },
    )
    assert raw_file.lastrowid is not None
    batch = connection.execute(
        sa.text(
            """
            INSERT INTO import_batches (
                raw_file_id, site_id, site_config_version_id,
                report_type, report_date, status,
                confirmed_report_type, confirmation_revision,
                confirmed_by_user_id, confirmed_at,
                created_by_user_id
            ) VALUES (
                :raw_file_id, :site_id, :site_config_version_id,
                NULL, '2026-08-07', :initial_status,
                :report_type, 1, :user_id, CURRENT_TIMESTAMP(6),
                :user_id
            )
            """
        ),
        {
            "raw_file_id": raw_file.lastrowid,
            "site_id": site_id,
            "site_config_version_id": site_config_version_id,
            "report_type": report_type,
            "initial_status": "uploaded" if processing_token is not None else status,
            "user_id": user_id,
        },
    )
    assert batch.lastrowid is not None
    batch_id = int(batch.lastrowid)
    if processing_token is not None:
        connection.execute(
            sa.text(
                """
                INSERT INTO parse_operation_tokens (
                    operation_token, batch_id, operation_digest, registered_at
                ) VALUES (
                    :processing_token, :batch_id, :operation_digest,
                    CURRENT_TIMESTAMP(6)
                )
                """
            ),
            {
                "processing_token": processing_token,
                "batch_id": batch_id,
                "operation_digest": processing_token * 2,
            },
        )
        updated = connection.execute(
            sa.text(
                """
                UPDATE import_batches
                SET status = 'processing',
                    processing_token = :processing_token,
                    processing_operation_digest = :operation_digest,
                    processing_started_at = CURRENT_TIMESTAMP(6)
                WHERE id = :batch_id
                """
            ),
            {
                "processing_token": processing_token,
                "operation_digest": processing_token * 2,
                "batch_id": batch_id,
            },
        )
        assert updated.rowcount == 1
    return batch_id


def _insert_stage_four_attempt(
    connection: Connection,
    *,
    batch_id: int,
    user_id: int,
    attempt_number: int = 1,
    site_id: int = 1,
    site_config_version_id: int = 1,
    report_type: str = "business_report",
    status: str = "succeeded",
    processing_token: bytes | None = None,
) -> int:
    resolved_processing_token = (
        processing_token if processing_token is not None else uuid4().bytes
    )
    operation_digest = resolved_processing_token * 2
    registered_identity = connection.execute(
        sa.text(
            """
            SELECT batch_id, operation_digest
            FROM parse_operation_tokens
            WHERE operation_token = :processing_token
            """
        ),
        {"processing_token": resolved_processing_token},
    ).first()
    if registered_identity is None:
        connection.execute(
            sa.text(
                """
                INSERT INTO parse_operation_tokens (
                    operation_token, batch_id, operation_digest, registered_at
                ) VALUES (
                    :processing_token, :batch_id, :operation_digest,
                    CURRENT_TIMESTAMP(6)
                )
                """
            ),
            {
                "processing_token": resolved_processing_token,
                "batch_id": batch_id,
                "operation_digest": operation_digest,
            },
        )
    else:
        assert tuple(registered_identity) == (batch_id, operation_digest)
    attempt = connection.execute(
        sa.text(
            """
            INSERT INTO parse_attempts (
                batch_id, site_id, site_config_version_id, processing_token,
                operation_digest,
                attempt_number, report_type, confirmation_revision,
                parser_version, ruleset_version, status,
                source_row_count, created_by_user_id, completed_at
            ) VALUES (
                :batch_id, :site_id, :site_config_version_id, :processing_token,
                :operation_digest,
                :attempt_number, :report_type, 1,
                'parser-v1', 'rules-v1', :status,
                IF(:status = 'succeeded', 0, NULL), :user_id,
                IF(:status = 'running', NULL, CURRENT_TIMESTAMP(6))
            )
            """
        ),
        {
            "batch_id": batch_id,
            "site_id": site_id,
            "site_config_version_id": site_config_version_id,
            "processing_token": resolved_processing_token,
            "operation_digest": operation_digest,
            "attempt_number": attempt_number,
            "report_type": report_type,
            "status": status,
            "user_id": user_id,
        },
    )
    assert attempt.lastrowid is not None
    return int(attempt.lastrowid)


def _insert_stage_four_baseline(
    connection: Connection,
    *,
    attempt_id: int,
    report_type: str = "business_report",
) -> int:
    baseline = connection.execute(
        sa.text(
            """
            INSERT INTO parse_baselines (
                parse_attempt_id, report_type, attempt_status,
                parser_version, ruleset_version,
                data_digest, row_count, totals_json
            ) VALUES (
                :attempt_id, :report_type, 'succeeded',
                'parser-v1', 'rules-v1', :digest, 0, :totals
            )
            """
        ),
        {
            "attempt_id": attempt_id,
            "report_type": report_type,
            "digest": uuid4().bytes + uuid4().bytes,
            "totals": "{}",
        },
    )
    assert baseline.lastrowid is not None
    return int(baseline.lastrowid)


def _assert_integrity_rejected(
    connection: Connection,
    statement: str,
    parameters: dict[str, object],
    *,
    expected_error_code: int | tuple[int, ...] | None = None,
    expected_constraint: str | None = None,
) -> None:
    savepoint = connection.begin_nested()
    try:
        with pytest.raises(DBAPIError) as exc_info:
            connection.execute(sa.text(statement), parameters)
        error_arguments = getattr(exc_info.value.orig, "args", ())
        error_code = error_arguments[0] if error_arguments else None
        if expected_error_code is not None:
            expected_error_codes = (
                expected_error_code
                if isinstance(expected_error_code, tuple)
                else (expected_error_code,)
            )
            assert error_code in expected_error_codes
        if expected_constraint is not None:
            error_message = str(exc_info.value.orig)
            assert expected_constraint in error_message or (
                error_code == 1216
                and "foreign key constraint fails" in error_message.lower()
            )
    finally:
        savepoint.rollback()


def _insert_dataset(
    connection: Connection,
    *,
    report_date: date,
    report_type: str,
) -> int:
    result = connection.execute(
        sa.text(
            """
            INSERT INTO daily_datasets (site_id, report_date, report_type)
            VALUES (1, :report_date, :report_type)
            """
        ),
        {"report_date": report_date, "report_type": report_type},
    )
    assert result.lastrowid is not None
    return int(result.lastrowid)


def _insert_version(
    connection: Connection,
    *,
    dataset_id: int,
    report_type: str,
    version_no: int,
    user_id: int,
) -> int:
    result = connection.execute(
        sa.text(
            """
            INSERT INTO dataset_versions (
                dataset_id, report_type, version_no, status,
                ruleset_version, created_by
            ) VALUES (
                :dataset_id, :report_type, :version_no, 'draft',
                'contract-v1', :user_id
            )
            """
        ),
        {
            "dataset_id": dataset_id,
            "report_type": report_type,
            "version_no": version_no,
            "user_id": user_id,
        },
    )
    assert result.lastrowid is not None
    return int(result.lastrowid)


@pytest.fixture()
def runtime_database(
    mysql_settings: DatabaseSettings,
    request: pytest.FixtureRequest,
) -> Iterator[_RuntimeDatabase]:
    value = os.getenv("APP_TEST_RUNTIME_DATABASE_URL")
    if value is None or not value.strip():
        if request.config.getoption("--require-mysql"):
            raise pytest.UsageError(
                "APP_TEST_RUNTIME_DATABASE_URL is required by --require-mysql"
            )
        pytest.skip("APP_TEST_RUNTIME_DATABASE_URL is not configured")

    runtime_settings = DatabaseSettings.from_url(
        value,
        pool_size=1,
        max_overflow=0,
    )
    migration_location = (
        (mysql_settings.url.host or "").casefold(),
        mysql_settings.url.port or 3306,
        mysql_settings.url.database,
    )
    runtime_location = (
        (runtime_settings.url.host or "").casefold(),
        runtime_settings.url.port or 3306,
        runtime_settings.url.database,
    )
    if runtime_location != migration_location:
        pytest.fail(
            "APP_TEST_RUNTIME_DATABASE_URL must target the same test database "
            "server as APP_TEST_DATABASE_URL",
            pytrace=False,
        )
    if runtime_settings.url.username == mysql_settings.url.username:
        pytest.fail(
            "the runtime and migration test URLs must use different accounts",
            pytrace=False,
        )

    username = runtime_settings.url.username
    assert username is not None
    engine = create_database_engine(runtime_settings)
    try:
        yield _RuntimeDatabase(engine=engine, username=username)
    finally:
        engine.dispose()


@pytest.fixture()
def backup_database(
    mysql_settings: DatabaseSettings,
    request: pytest.FixtureRequest,
) -> Iterator[_BackupDatabase]:
    value = os.getenv("APP_TEST_BACKUP_DATABASE_URL")
    if value is None or not value.strip():
        if request.config.getoption("--require-mysql"):
            raise pytest.UsageError(
                "APP_TEST_BACKUP_DATABASE_URL is required by --require-mysql"
            )
        pytest.skip("APP_TEST_BACKUP_DATABASE_URL is not configured")

    backup_settings = DatabaseSettings.from_url(
        value,
        pool_size=1,
        max_overflow=0,
    )
    migration_location = (
        (mysql_settings.url.host or "").casefold(),
        mysql_settings.url.port or 3306,
        mysql_settings.url.database,
    )
    backup_location = (
        (backup_settings.url.host or "").casefold(),
        backup_settings.url.port or 3306,
        backup_settings.url.database,
    )
    if backup_location != migration_location:
        pytest.fail(
            "APP_TEST_BACKUP_DATABASE_URL must target the same test database "
            "server as APP_TEST_DATABASE_URL",
            pytrace=False,
        )
    if backup_settings.url.username == mysql_settings.url.username:
        pytest.fail(
            "the backup and migration test URLs must use different accounts",
            pytrace=False,
        )
    runtime_value = os.getenv("APP_TEST_RUNTIME_DATABASE_URL")
    if runtime_value is not None and runtime_value.strip():
        runtime_settings = DatabaseSettings.from_url(
            runtime_value,
            pool_size=1,
            max_overflow=0,
        )
        if backup_settings.url.username == runtime_settings.url.username:
            pytest.fail(
                "the backup and runtime test URLs must use different accounts",
                pytrace=False,
            )

    username = backup_settings.url.username
    assert username is not None
    engine = create_database_engine(backup_settings)
    try:
        yield _BackupDatabase(engine=engine, username=username)
    finally:
        engine.dispose()


def _isolated_report_date() -> date:
    first_test_date = date(2100, 1, 1)
    available_days = (date.max - first_test_date).days
    return first_test_date + timedelta(days=uuid4().int % available_days)


@pytest.fixture()
def append_only_event_fixture(
    alembic_config: Config,
    mysql_engine: Engine,
) -> Iterator[_AppendOnlyEventFixture]:
    command.upgrade(alembic_config, "head")
    request_id = f"append-only-permission-{uuid4().hex}"

    with mysql_engine.begin() as connection:
        migration_connection_id = connection.scalar(sa.text("SELECT CONNECTION_ID()"))
        assert migration_connection_id is not None
        user_id = _insert_user(connection)
        dataset_id = _insert_dataset(
            connection,
            report_date=_isolated_report_date(),
            report_type="business_report",
        )
        version_id = _insert_version(
            connection,
            dataset_id=dataset_id,
            report_type="business_report",
            version_no=1,
            user_id=user_id,
        )

        version_row = connection.execute(
            sa.text(
                """
                INSERT INTO version_rows (
                    version_id, report_type, logical_row_id, row_ordinal
                ) VALUES (
                    :version_id, 'business_report', :logical_row_id, 1
                )
                """
            ),
            {"version_id": version_id, "logical_row_id": uuid4().bytes},
        )
        assert version_row.lastrowid is not None
        version_row_id = int(version_row.lastrowid)

        validation_run = connection.execute(
            sa.text(
                """
                INSERT INTO validation_runs (
                    version_id, run_type, data_revision, ruleset_version,
                    status, result, data_digest, summary_json, completed_at
                ) VALUES (
                    :version_id, 'full', 0, 'permission-test-v1',
                    'succeeded', 'passed', :digest, '{}', CURRENT_TIMESTAMP(6)
                )
                """
            ),
            {"version_id": version_id, "digest": uuid4().bytes * 2},
        )
        assert validation_run.lastrowid is not None
        validation_run_id = int(validation_run.lastrowid)

        validation_issue = connection.execute(
            sa.text(
                """
                INSERT INTO validation_issues (
                    validation_run_id, version_id, severity, rule_code,
                    message, requires_note
                ) VALUES (
                    :validation_run_id, :version_id, 'warning',
                    'permission_test', 'permission test issue', FALSE
                )
                """
            ),
            {
                "validation_run_id": validation_run_id,
                "version_id": version_id,
            },
        )
        assert validation_issue.lastrowid is not None
        validation_issue_id = int(validation_issue.lastrowid)

        publication_command = connection.execute(
            sa.text(
                """
                INSERT INTO publication_commands (
                    actor_user_id, operation_kind, operation_token,
                    operation_digest, redacted_request_payload
                ) VALUES (
                    :user_id, 'publish', :operation_token,
                    :operation_digest, :payload
                )
                """
            ),
            {
                "user_id": user_id,
                "operation_token": uuid4().bytes,
                "operation_digest": uuid4().bytes * 2,
                "payload": "{}",
            },
        )
        assert publication_command.lastrowid is not None
        publication_command_id = int(publication_command.lastrowid)

    fixture = _AppendOnlyEventFixture(
        user_id=user_id,
        dataset_id=dataset_id,
        version_id=version_id,
        version_row_id=version_row_id,
        validation_run_id=validation_run_id,
        validation_issue_id=validation_issue_id,
        publication_command_id=publication_command_id,
        request_id=request_id,
        migration_connection_id=int(migration_connection_id),
    )
    try:
        yield fixture
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "DELETE FROM draft_disposition_events "
                    "WHERE version_id = :version_id"
                ),
                {"version_id": version_id},
            )
            connection.execute(
                sa.text("DELETE FROM audit_events WHERE request_id = :request_id"),
                {"request_id": request_id},
            )
            connection.execute(
                sa.text("DELETE FROM notes WHERE note_key = :note_key"),
                {"note_key": request_id},
            )
            connection.execute(
                sa.text("DELETE FROM note_threads WHERE note_key = :note_key"),
                {"note_key": request_id},
            )
            connection.execute(
                sa.text(
                    "DELETE FROM publication_events WHERE command_id = :command_id"
                ),
                {"command_id": publication_command_id},
            )
            connection.execute(
                sa.text(
                    "DELETE FROM issue_review_events "
                    "WHERE validation_issue_id = :issue_id"
                ),
                {"issue_id": validation_issue_id},
            )
            connection.execute(
                sa.text("DELETE FROM field_changes WHERE version_id = :version_id"),
                {"version_id": version_id},
            )
            connection.execute(
                sa.text("DELETE FROM row_changes WHERE version_id = :version_id"),
                {"version_id": version_id},
            )
            connection.execute(
                sa.text(
                    "DELETE FROM data_change_events WHERE version_id = :version_id"
                ),
                {"version_id": version_id},
            )
            connection.execute(
                sa.text("DELETE FROM publication_commands WHERE id = :command_id"),
                {"command_id": publication_command_id},
            )
            connection.execute(
                sa.text("DELETE FROM validation_issues WHERE id = :issue_id"),
                {"issue_id": validation_issue_id},
            )
            connection.execute(
                sa.text("DELETE FROM validation_runs WHERE id = :run_id"),
                {"run_id": validation_run_id},
            )
            connection.execute(
                sa.text("DELETE FROM version_rows WHERE id = :row_id"),
                {"row_id": version_row_id},
            )
            connection.execute(
                sa.text("DELETE FROM dataset_versions WHERE id = :version_id"),
                {"version_id": version_id},
            )
            connection.execute(
                sa.text("DELETE FROM daily_datasets WHERE id = :dataset_id"),
                {"dataset_id": dataset_id},
            )
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )


def _insert_append_only_record(
    connection: Connection,
    table_name: str,
    fixture: _AppendOnlyEventFixture,
) -> int:
    if table_name == "issue_review_events":
        result = connection.execute(
            sa.text(
                """
                INSERT INTO issue_review_events (
                    version_id, validation_run_id, validation_issue_id,
                    issue_severity, issue_requires_note,
                    sequence_number, review_revision, event_type,
                    actor_user_id, comment
                ) VALUES (
                    :version_id, :run_id, :issue_id,
                    'warning', FALSE, 1, 1,
                    'acknowledge', :user_id, 'permission test'
                )
                """
            ),
            {
                "version_id": fixture.version_id,
                "run_id": fixture.validation_run_id,
                "issue_id": fixture.validation_issue_id,
                "user_id": fixture.user_id,
            },
        )
    elif table_name in {"data_change_events", "field_changes", "row_changes"}:
        event_kind = "field" if table_name != "row_changes" else "row"
        parent = connection.execute(
            sa.text(
                """
                INSERT INTO data_change_events (
                    version_id, sequence_number, data_revision,
                    event_kind, actor_user_id, reason
                ) VALUES (
                    :version_id, 1, 1, :event_kind, :user_id,
                    'permission test'
                )
                """
            ),
            {
                "version_id": fixture.version_id,
                "event_kind": event_kind,
                "user_id": fixture.user_id,
            },
        )
        assert parent.lastrowid is not None
        parent_id = int(parent.lastrowid)
        if table_name == "data_change_events":
            return parent_id
        if table_name == "field_changes":
            result = connection.execute(
                sa.text(
                    """
                    INSERT INTO field_changes (
                        id, version_id, event_kind, row_id, field_name,
                        operation, before_value_json, after_value_json
                    ) VALUES (
                        :id, :version_id, 'field', :row_id, 'sku', 'set',
                        JSON_QUOTE('before'), JSON_QUOTE('after')
                    )
                    """
                ),
                {
                    "id": parent_id,
                    "version_id": fixture.version_id,
                    "row_id": fixture.version_row_id,
                },
            )
        else:
            result = connection.execute(
                sa.text(
                    """
                    INSERT INTO row_changes (
                        id, version_id, event_kind, row_id, operation,
                        before_value_json, after_value_json
                    ) VALUES (
                        :id, :version_id, 'row', :row_id, 'exclude',
                        JSON_OBJECT('row_state', 'active'),
                        JSON_OBJECT('row_state', 'excluded')
                    )
                    """
                ),
                {
                    "id": parent_id,
                    "version_id": fixture.version_id,
                    "row_id": fixture.version_row_id,
                },
            )
        return parent_id
    elif table_name == "notes":
        connection.execute(
            sa.text(
                """
                INSERT INTO note_threads (
                    note_key, target_type, version_id, created_at
                ) VALUES (
                    :note_key, 'version', :version_id, CURRENT_TIMESTAMP(6)
                )
                """
            ),
            {
                "note_key": fixture.request_id,
                "version_id": fixture.version_id,
            },
        )
        result = connection.execute(
            sa.text(
                """
                INSERT INTO notes (
                    note_key, revision_number, body,
                    author_user_id, review_revision
                ) VALUES (
                    :note_key, 1, 'permission test', :user_id, 1
                )
                """
            ),
            {
                "note_key": fixture.request_id,
                "user_id": fixture.user_id,
            },
        )
    elif table_name == "audit_events":
        result = connection.execute(
            sa.text(
                """
                INSERT INTO audit_events (
                    site_id, actor_user_id, event_type, object_type,
                    object_id, request_id, redacted_payload
                ) VALUES (
                    1, :user_id, 'permission_test', 'dataset_version',
                    :object_id, :request_id, :payload
                )
                """
            ),
            {
                "user_id": fixture.user_id,
                "object_id": str(fixture.version_id),
                "request_id": fixture.request_id,
                "payload": "{}",
            },
        )
    elif table_name == "publication_events":
        result = connection.execute(
            sa.text(
                """
                INSERT INTO publication_events (
                    command_id, sequence_number, event_type, dataset_id,
                    next_version_id, reason, redacted_payload
                ) VALUES (
                    :command_id, 1, 'published', :dataset_id,
                    :version_id, 'permission test', :payload
                )
                """
            ),
            {
                "command_id": fixture.publication_command_id,
                "dataset_id": fixture.dataset_id,
                "version_id": fixture.version_id,
                "payload": "{}",
            },
        )
    elif table_name == "draft_disposition_events":
        operation_token = uuid4().bytes
        operation_digest = uuid4().bytes + uuid4().bytes
        connection.execute(
            sa.text(
                """
                INSERT INTO draft_operation_tokens (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, registered_at
                ) VALUES (
                    :operation_token, 'discard_draft',
                    :operation_digest, :user_id, CURRENT_TIMESTAMP(6)
                )
                """
            ),
            {
                "operation_token": operation_token,
                "operation_digest": operation_digest,
                "user_id": fixture.user_id,
            },
        )
        result = connection.execute(
            sa.text(
                """
                INSERT INTO draft_disposition_events (
                    operation_token, operation_kind, operation_digest,
                    dataset_id, version_id,
                    event_type, actor_user_id,
                    terminal_data_revision, terminal_review_revision,
                    reason, occurred_at
                ) VALUES (
                    :operation_token, 'discard_draft', :operation_digest,
                    :dataset_id, :version_id,
                    'discarded', :user_id,
                    0, 0, 'permission test', CURRENT_TIMESTAMP(6)
                )
                """
            ),
            {
                "operation_token": operation_token,
                "operation_digest": operation_digest,
                "dataset_id": fixture.dataset_id,
                "version_id": fixture.version_id,
                "user_id": fixture.user_id,
            },
        )
    else:
        raise AssertionError(f"unsupported append-only record table: {table_name}")

    assert result.lastrowid is not None
    return int(result.lastrowid)


def _assert_mysql_command_denied(
    connection: Connection,
    *,
    command: str,
    statement: str,
    parameters: dict[str, object] | None = None,
    expected_error_codes: tuple[int, ...] = (1142,),
) -> None:
    with pytest.raises(DBAPIError) as exc_info:
        connection.execute(sa.text(statement), parameters or {})

    error_arguments = getattr(exc_info.value.orig, "args", ())
    error_code = error_arguments[0] if error_arguments else None
    assert error_code in expected_error_codes, (
        f"expected MySQL access denial for {command}, got error code {error_code!r}"
    )


def _assert_table_command_denied(
    connection: Connection,
    *,
    command: str,
    table_name: str,
    event_id: int,
) -> None:
    if command == "UPDATE":
        statement = f"UPDATE {table_name} SET id = id WHERE id = :event_id"
    else:
        statement = f"DELETE FROM {table_name} WHERE id = :event_id"

    _assert_mysql_command_denied(
        connection,
        command=f"{command} on {table_name}",
        statement=statement,
        parameters={"event_id": event_id},
    )


def test_runtime_account_can_update_only_the_dataset_lock_revision(
    runtime_database: _RuntimeDatabase,
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.begin() as connection:
        dataset_id = _insert_dataset(
            connection,
            report_date=_isolated_report_date(),
            report_type="business_report",
        )

    try:
        with runtime_database.engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO daily_dataset_locks (dataset_id, lock_revision)
                    VALUES (:dataset_id, 0)
                    """
                ),
                {"dataset_id": dataset_id},
            )
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT lock_revision FROM daily_dataset_locks "
                        "WHERE dataset_id = :dataset_id"
                    ),
                    {"dataset_id": dataset_id},
                )
                == 0
            )
            connection.execute(
                sa.text(
                    "UPDATE daily_dataset_locks "
                    "SET lock_revision = lock_revision + 1 "
                    "WHERE dataset_id = :dataset_id"
                ),
                {"dataset_id": dataset_id},
            )

        with runtime_database.engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT lock_revision FROM daily_dataset_locks "
                        "WHERE dataset_id = :dataset_id"
                    ),
                    {"dataset_id": dataset_id},
                )
                == 1
            )
            _assert_mysql_command_denied(
                connection,
                command="UPDATE of daily_dataset_locks.dataset_id",
                statement=(
                    "UPDATE daily_dataset_locks SET dataset_id = dataset_id "
                    "WHERE dataset_id = :dataset_id"
                ),
                parameters={"dataset_id": dataset_id},
                expected_error_codes=(1143,),
            )
            _assert_mysql_command_denied(
                connection,
                command="DELETE on daily_dataset_locks",
                statement=(
                    "DELETE FROM daily_dataset_locks WHERE dataset_id = :dataset_id"
                ),
                parameters={"dataset_id": dataset_id},
            )
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "DELETE FROM daily_dataset_locks WHERE dataset_id = :dataset_id"
                ),
                {"dataset_id": dataset_id},
            )
            connection.execute(
                sa.text("DELETE FROM daily_datasets WHERE id = :dataset_id"),
                {"dataset_id": dataset_id},
            )


@pytest.mark.parametrize("table_name", APPEND_ONLY_EVENT_TABLES)
def test_runtime_account_can_append_but_cannot_mutate_append_only_events(
    table_name: str,
    runtime_database: _RuntimeDatabase,
    append_only_event_fixture: _AppendOnlyEventFixture,
) -> None:
    _assert_runtime_append_only_permissions(
        table_name,
        runtime_database,
        append_only_event_fixture,
    )


def test_runtime_account_cannot_overwrite_or_delete_note_revisions(
    runtime_database: _RuntimeDatabase,
    append_only_event_fixture: _AppendOnlyEventFixture,
) -> None:
    _assert_runtime_append_only_permissions(
        "notes",
        runtime_database,
        append_only_event_fixture,
    )


def test_runtime_account_can_persist_an_idempotent_import_batch_note_result(
    runtime_database: _RuntimeDatabase,
    append_only_event_fixture: _AppendOnlyEventFixture,
    mysql_engine: Engine,
) -> None:
    with mysql_engine.begin() as connection:
        batch_id = _insert_stage_four_batch(
            connection,
            user_id=append_only_event_fixture.user_id,
        )
        raw_file_id = connection.scalar(
            sa.text("SELECT raw_file_id FROM import_batches WHERE id = :batch_id"),
            {"batch_id": batch_id},
        )
        assert raw_file_id is not None

    operation_token = uuid4().bytes
    operation_digest = uuid4().bytes + uuid4().bytes
    note_key = f"batch-note-{uuid4().hex}"
    try:
        with runtime_database.engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO note_threads (
                            note_key, target_type, import_batch_id, created_at
                        ) VALUES (
                            :note_key, 'import_batch', :batch_id,
                            CURRENT_TIMESTAMP(6)
                        )
                        """
                    ),
                    {"note_key": note_key, "batch_id": batch_id},
                )
                note = connection.execute(
                    sa.text(
                        """
                        INSERT INTO notes (
                            note_key, revision_number, body, author_user_id
                        ) VALUES (
                            :note_key, 1, 'batch note', :user_id
                        )
                        """
                    ),
                    {
                        "note_key": note_key,
                        "user_id": append_only_event_fixture.user_id,
                    },
                )
                assert note.lastrowid is not None
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO review_operation_tokens (
                            operation_token, operation_kind, operation_digest,
                            actor_user_id, registered_at
                        ) VALUES (
                            :operation_token, 'create_note',
                            :operation_digest, :user_id, CURRENT_TIMESTAMP(6)
                        )
                        """
                    ),
                    {
                        "operation_token": operation_token,
                        "operation_digest": operation_digest,
                        "user_id": append_only_event_fixture.user_id,
                    },
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO review_operation_results (
                            operation_token, operation_kind, operation_digest,
                            actor_user_id, result_kind,
                            result_import_batch_id, note_id, completed_at
                        ) VALUES (
                            :operation_token, 'create_note',
                            :operation_digest, :user_id, 'applied',
                            :batch_id, :note_id, CURRENT_TIMESTAMP(6)
                        )
                        """
                    ),
                    {
                        "operation_token": operation_token,
                        "operation_digest": operation_digest,
                        "user_id": append_only_event_fixture.user_id,
                        "batch_id": batch_id,
                        "note_id": int(note.lastrowid),
                    },
                )
                assert (
                    connection.scalar(
                        sa.text(
                            """
                        SELECT result_import_batch_id
                        FROM review_operation_results
                        WHERE operation_token = :operation_token
                        """
                        ),
                        {"operation_token": operation_token},
                    )
                    == batch_id
                )
            finally:
                transaction.rollback()
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM import_batches WHERE id = :batch_id"),
                {"batch_id": batch_id},
            )
            connection.execute(
                sa.text("DELETE FROM raw_files WHERE id = :raw_file_id"),
                {"raw_file_id": raw_file_id},
            )


def test_runtime_account_cannot_write_terminal_guard_bypass_accounts(
    runtime_database: _RuntimeDatabase,
) -> None:
    with runtime_database.engine.connect() as connection:
        _assert_mysql_command_denied(
            connection,
            command="INSERT on terminal_write_guard_bypass_accounts",
            statement=(
                "INSERT INTO terminal_write_guard_bypass_accounts "
                "(account_identity) VALUES (:account_identity)"
            ),
            parameters={"account_identity": "clsen_app@untrusted"},
        )
        connection.rollback()


def test_runtime_account_cannot_mutate_a_published_version_or_its_rows(
    runtime_database: _RuntimeDatabase,
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.begin() as connection:
        user_id = _insert_user(connection)
        dataset_id = _insert_dataset(
            connection,
            report_date=_isolated_report_date(),
            report_type="business_report",
        )
        version_id = _insert_version(
            connection,
            dataset_id=dataset_id,
            report_type="business_report",
            version_no=1,
            user_id=user_id,
        )
        row = connection.execute(
            sa.text(
                """
                INSERT INTO version_rows (
                    version_id, report_type, logical_row_id, row_ordinal
                ) VALUES (
                    :version_id, 'business_report', :logical_row_id, 1
                )
                """
            ),
            {"version_id": version_id, "logical_row_id": uuid4().bytes},
        )
        assert row.lastrowid is not None
        row_id = int(row.lastrowid)
        connection.execute(
            sa.text(
                """
                UPDATE dataset_versions
                SET status = 'published', sealed_at = CURRENT_TIMESTAMP(6)
                WHERE id = :version_id
                """
            ),
            {"version_id": version_id},
        )

    try:
        with runtime_database.engine.connect() as connection:
            with pytest.raises(DBAPIError) as version_error:
                connection.execute(
                    sa.text(
                        """
                        UPDATE dataset_versions
                        SET data_revision = data_revision
                        WHERE id = :version_id
                        """
                    ),
                    {"version_id": version_id},
                )
            assert getattr(version_error.value.orig, "args", (None,))[0] == 1644
            connection.rollback()

        with runtime_database.engine.connect() as connection:
            with pytest.raises(DBAPIError) as row_error:
                connection.execute(
                    sa.text(
                        """
                        UPDATE version_rows
                        SET row_state = row_state
                        WHERE id = :row_id
                        """
                    ),
                    {"row_id": row_id},
                )
            assert getattr(row_error.value.orig, "args", (None,))[0] == 1644
            connection.rollback()
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM version_rows WHERE id = :row_id"),
                {"row_id": row_id},
            )
            connection.execute(
                sa.text("DELETE FROM dataset_versions WHERE id = :version_id"),
                {"version_id": version_id},
            )
            connection.execute(
                sa.text("DELETE FROM daily_datasets WHERE id = :dataset_id"),
                {"dataset_id": dataset_id},
            )
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )


@pytest.mark.parametrize("table_name", OPERATION_TOKEN_TABLES)
def test_runtime_account_can_register_but_not_mutate_operation_tokens(
    table_name: str,
    runtime_database: _RuntimeDatabase,
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.begin() as connection:
        user_id = _insert_user(connection)
        batch_id = _insert_stage_four_batch(connection, user_id=user_id)
        raw_file_id = connection.scalar(
            sa.text("SELECT raw_file_id FROM import_batches WHERE id = :batch_id"),
            {"batch_id": batch_id},
        )
        assert raw_file_id is not None

    operation_token = uuid4().bytes
    operation_digest = uuid4().bytes + uuid4().bytes
    try:
        with runtime_database.engine.connect() as connection:
            transaction = connection.begin()
            try:
                current_user = connection.scalar(sa.text("SELECT CURRENT_USER()"))
                assert str(current_user).partition("@")[0] == runtime_database.username
                connection.execute(
                    sa.text(
                        f"""
                        INSERT INTO {table_name} (
                            operation_token, batch_id,
                            operation_digest, registered_at
                        ) VALUES (
                            :operation_token, :batch_id,
                            :operation_digest, CURRENT_TIMESTAMP(6)
                        )
                        """
                    ),
                    {
                        "operation_token": operation_token,
                        "batch_id": batch_id,
                        "operation_digest": operation_digest,
                    },
                )
                assert (
                    connection.scalar(
                        sa.text(
                            f"""
                        SELECT COUNT(*) FROM {table_name}
                        WHERE operation_token = :operation_token
                          AND batch_id = :batch_id
                          AND operation_digest = :operation_digest
                        """
                        ),
                        {
                            "operation_token": operation_token,
                            "batch_id": batch_id,
                            "operation_digest": operation_digest,
                        },
                    )
                    == 1
                )
                if table_name == "parse_operation_tokens":
                    repository = MySqlParseRepository(runtime_database.engine)
                    token = UUID(bytes=operation_token)
                    assert not repository._claim_parse_operation(
                        connection,
                        processing_token=token,
                        batch_id=batch_id,
                        operation_digest=operation_digest,
                        registered_at=datetime.now(),
                    )
                    assert (
                        repository._recover_terminal_on_connection(
                            connection,
                            token,
                            expected_batch_id=batch_id,
                            operation_digest=operation_digest,
                            lock_rows=True,
                        )
                        is None
                    )
                    with pytest.raises(
                        ParseStateConflict, match="different parse choices"
                    ):
                        repository._claim_parse_operation(
                            connection,
                            processing_token=token,
                            batch_id=batch_id,
                            operation_digest=b"x" * 32,
                            registered_at=datetime.now(),
                        )
                _assert_mysql_command_denied(
                    connection,
                    command=f"UPDATE on {table_name}",
                    statement=(
                        f"UPDATE {table_name} SET registered_at = registered_at "
                        "WHERE operation_token = :operation_token"
                    ),
                    parameters={"operation_token": operation_token},
                )
                _assert_mysql_command_denied(
                    connection,
                    command=f"DELETE on {table_name}",
                    statement=(
                        f"DELETE FROM {table_name} "
                        "WHERE operation_token = :operation_token"
                    ),
                    parameters={"operation_token": operation_token},
                )
            finally:
                transaction.rollback()
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM import_batches WHERE id = :batch_id"),
                {"batch_id": batch_id},
            )
            connection.execute(
                sa.text("DELETE FROM raw_files WHERE id = :raw_file_id"),
                {"raw_file_id": raw_file_id},
            )
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )


def test_runtime_account_can_append_but_not_mutate_draft_operation_result(
    runtime_database: _RuntimeDatabase,
    append_only_event_fixture: _AppendOnlyEventFixture,
) -> None:
    operation_token = uuid4().bytes
    operation_digest = uuid4().bytes + uuid4().bytes
    with runtime_database.engine.connect() as connection:
        transaction = connection.begin()
        try:
            current_user = connection.scalar(sa.text("SELECT CURRENT_USER()"))
            assert str(current_user).partition("@")[0] == runtime_database.username
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :operation_token, 'materialize_baseline',
                        :operation_digest, :actor_user_id, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "operation_token": operation_token,
                    "operation_digest": operation_digest,
                    "actor_user_id": append_only_event_fixture.user_id,
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_operation_results (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, result_kind,
                        result_dataset_id, result_version_id,
                        result_version_no, result_status,
                        result_data_revision, result_review_revision,
                        completed_at
                    ) VALUES (
                        :operation_token, 'materialize_baseline',
                        :operation_digest, :actor_user_id, 'created',
                        :dataset_id, :version_id,
                        1, 'draft', 0, 0, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "operation_token": operation_token,
                    "operation_digest": operation_digest,
                    "actor_user_id": append_only_event_fixture.user_id,
                    "dataset_id": append_only_event_fixture.dataset_id,
                    "version_id": append_only_event_fixture.version_id,
                },
            )
            for table_name in (
                "draft_operation_results",
                "draft_operation_tokens",
            ):
                _assert_mysql_command_denied(
                    connection,
                    command=f"UPDATE on {table_name}",
                    statement=(
                        f"UPDATE {table_name} SET operation_token = operation_token "
                        "WHERE operation_token = :operation_token"
                    ),
                    parameters={"operation_token": operation_token},
                )
                _assert_mysql_command_denied(
                    connection,
                    command=f"DELETE on {table_name}",
                    statement=(
                        f"DELETE FROM {table_name} "
                        "WHERE operation_token = :operation_token"
                    ),
                    parameters={"operation_token": operation_token},
                )
        finally:
            transaction.rollback()


@pytest.mark.parametrize("table_name", IMMUTABLE_RUNTIME_TABLES)
def test_runtime_account_cannot_update_or_delete_immutable_tables(
    table_name: str,
    runtime_database: _RuntimeDatabase,
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    columns = sa.inspect(mysql_engine).get_columns(table_name)
    assert columns
    first_column = str(columns[0]["name"])

    with runtime_database.engine.connect() as connection:
        current_user = connection.scalar(sa.text("SELECT CURRENT_USER()"))
        assert str(current_user).partition("@")[0] == runtime_database.username

        _assert_mysql_command_denied(
            connection,
            command=f"UPDATE on {table_name}",
            statement=(
                f"UPDATE {table_name} SET {first_column} = {first_column} WHERE 1 = 0"
            ),
        )
        _assert_mysql_command_denied(
            connection,
            command=f"DELETE on {table_name}",
            statement=f"DELETE FROM {table_name} WHERE 1 = 0",
        )
        connection.rollback()


def test_runtime_account_can_reconcile_but_not_delete_raw_file_integrity(
    runtime_database: _RuntimeDatabase,
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    storage_key = f"sha256/permission/{uuid4().hex}"
    with mysql_engine.begin() as connection:
        user_id = _insert_user(connection)
        raw_file = connection.execute(
            sa.text(
                """
                INSERT INTO raw_files (
                    sha256, storage_key, original_filename,
                    size_bytes, uploaded_by_user_id
                ) VALUES (
                    :sha256, :storage_key, 'permission.csv', 1, :user_id
                )
                """
            ),
            {
                "sha256": uuid4().bytes + uuid4().bytes,
                "storage_key": storage_key,
                "user_id": user_id,
            },
        )
        assert raw_file.lastrowid is not None
        raw_file_id = int(raw_file.lastrowid)

    try:
        with runtime_database.engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO raw_file_integrity_statuses (
                            raw_file_id, status, first_detected_at,
                            last_checked_at
                        ) VALUES (
                            :raw_file_id, 'missing', CURRENT_TIMESTAMP(6),
                            CURRENT_TIMESTAMP(6)
                        )
                        """
                    ),
                    {"raw_file_id": raw_file_id},
                )
                connection.execute(
                    sa.text(
                        """
                        UPDATE raw_file_integrity_statuses
                        SET status = 'available',
                            last_checked_at = CURRENT_TIMESTAMP(6),
                            resolved_at = CURRENT_TIMESTAMP(6)
                        WHERE raw_file_id = :raw_file_id
                        """
                    ),
                    {"raw_file_id": raw_file_id},
                )
                assert connection.execute(
                    sa.text(
                        """
                        SELECT status, is_blocking
                        FROM raw_file_integrity_statuses
                        WHERE raw_file_id = :raw_file_id
                        """
                    ),
                    {"raw_file_id": raw_file_id},
                ).one() == ("available", 0)

                _assert_mysql_command_denied(
                    connection,
                    command="DELETE on raw_file_integrity_statuses",
                    statement=(
                        "DELETE FROM raw_file_integrity_statuses "
                        "WHERE raw_file_id = :raw_file_id"
                    ),
                    parameters={"raw_file_id": raw_file_id},
                )
            finally:
                transaction.rollback()
    finally:
        with mysql_engine.begin() as connection:
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
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )


def test_runtime_account_can_complete_full_file_ingest(
    runtime_database: _RuntimeDatabase,
    alembic_config: Config,
    mysql_engine: Engine,
    tmp_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.begin() as connection:
        user_id = _insert_user(connection)

    store = LocalContentStore(
        tmp_path / "runtime-ingest",
        max_upload_bytes=1024 * 1024,
    )
    service = IngestService(
        repository=MySqlIngestRepository(
            runtime_database.engine,
            lock_timeout_seconds=5,
        ),
        store=store,
        lease_ttl=timedelta(minutes=30),
        lease_renew_interval=timedelta(minutes=5),
    )

    try:
        result = service.ingest(
            BytesIO(b"runtime account end-to-end ingest"),
            ImportCommand(
                original_filename="runtime-permission.csv",
                media_type="text/csv",
                created_by_user_id=user_id,
                site_config_version_id=1,
                report_date=date(2099, 12, 30),
            ),
        )
        assert isinstance(result, ImportCreated)
        assert store.validate(
            result.storage_key,
            result.sha256_hex,
            result.size_bytes,
        )
    finally:
        with mysql_engine.begin() as connection:
            raw_file_ids = list(
                connection.scalars(
                    sa.text(
                        "SELECT id FROM raw_files WHERE uploaded_by_user_id = :user_id"
                    ),
                    {"user_id": user_id},
                )
            )
            connection.execute(
                sa.text(
                    "DELETE FROM import_batches WHERE created_by_user_id = :user_id"
                ),
                {"user_id": user_id},
            )
            connection.execute(
                sa.text(
                    "DELETE FROM file_ingest_leases WHERE created_by_user_id = :user_id"
                ),
                {"user_id": user_id},
            )
            if raw_file_ids:
                expanding_ids: sa.BindParameter[object] = sa.bindparam(
                    "raw_file_ids",
                    expanding=True,
                )
                connection.execute(
                    sa.text(
                        "DELETE FROM raw_file_integrity_statuses "
                        "WHERE raw_file_id IN :raw_file_ids"
                    ).bindparams(expanding_ids),
                    {"raw_file_ids": raw_file_ids},
                )
                connection.execute(
                    sa.text(
                        "DELETE FROM raw_files WHERE id IN :raw_file_ids"
                    ).bindparams(expanding_ids),
                    {"raw_file_ids": raw_file_ids},
                )
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )


def test_runtime_account_can_finalize_an_immutable_successful_parse(
    runtime_database: _RuntimeDatabase,
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    processing_token = uuid4().bytes
    with mysql_engine.begin() as connection:
        user_id = _insert_user(connection)
        batch_id = _insert_stage_four_batch(
            connection,
            user_id=user_id,
            status="processing",
            processing_token=processing_token,
        )
        raw_file_id = connection.scalar(
            sa.text("SELECT raw_file_id FROM import_batches WHERE id = :batch_id"),
            {"batch_id": batch_id},
        )
        assert raw_file_id is not None

    attempt_id: int | None = None
    try:
        with runtime_database.engine.begin() as connection:
            attempt_id = _insert_stage_four_attempt(
                connection,
                batch_id=batch_id,
                user_id=user_id,
                processing_token=processing_token,
            )
            _insert_stage_four_baseline(connection, attempt_id=attempt_id)
            switched = connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET current_successful_parse_attempt_id = :attempt_id,
                        report_type = 'business_report',
                        source_row_count = 0, status = 'staged',
                        processing_token = NULL,
                        processing_operation_digest = NULL,
                        processing_started_at = NULL
                    WHERE id = :batch_id
                    """
                ),
                {"attempt_id": attempt_id, "batch_id": batch_id},
            )
            assert switched.rowcount == 1

        with mysql_engine.connect() as connection:
            recovered = connection.execute(
                sa.text(
                    """
                    SELECT attempts.id,
                           batches.current_successful_parse_attempt_id,
                           batches.processing_token
                    FROM parse_attempts AS attempts
                    INNER JOIN import_batches AS batches
                        ON batches.id = attempts.batch_id
                    WHERE attempts.processing_token = :processing_token
                    """
                ),
                {"processing_token": processing_token},
            ).one()
            assert tuple(recovered) == (attempt_id, attempt_id, None)
    finally:
        with mysql_engine.begin() as connection:
            if attempt_id is not None:
                connection.execute(
                    sa.text(
                        """
                        UPDATE import_batches
                        SET current_successful_parse_attempt_id = NULL,
                            report_type = NULL,
                            source_row_count = NULL
                        WHERE id = :batch_id
                    """
                    ),
                    {"batch_id": batch_id},
                )
                connection.execute(
                    sa.text(
                        "DELETE FROM parse_baselines "
                        "WHERE parse_attempt_id = :attempt_id"
                    ),
                    {"attempt_id": attempt_id},
                )
                connection.execute(
                    sa.text("DELETE FROM parse_attempts WHERE id = :attempt_id"),
                    {"attempt_id": attempt_id},
                )
            connection.execute(
                sa.text(
                    "DELETE FROM parse_operation_tokens WHERE batch_id = :batch_id"
                ),
                {"batch_id": batch_id},
            )
            connection.execute(
                sa.text("DELETE FROM import_batches WHERE id = :batch_id"),
                {"batch_id": batch_id},
            )
            connection.execute(
                sa.text("DELETE FROM raw_files WHERE id = :raw_file_id"),
                {"raw_file_id": raw_file_id},
            )
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )


def _assert_runtime_append_only_permissions(
    table_name: str,
    runtime_database: _RuntimeDatabase,
    append_only_event_fixture: _AppendOnlyEventFixture,
) -> None:
    with runtime_database.engine.connect() as connection:
        transaction = connection.begin()
        try:
            runtime_connection_id = connection.scalar(sa.text("SELECT CONNECTION_ID()"))
            assert runtime_connection_id != (
                append_only_event_fixture.migration_connection_id
            )
            current_user = connection.scalar(sa.text("SELECT CURRENT_USER()"))
            assert str(current_user).partition("@")[0] == runtime_database.username

            event_id = _insert_append_only_record(
                connection,
                table_name,
                append_only_event_fixture,
            )
            assert (
                connection.scalar(
                    sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE id = :event_id"),
                    {"event_id": event_id},
                )
                == 1
            )

            _assert_table_command_denied(
                connection,
                command="UPDATE",
                table_name=table_name,
                event_id=event_id,
            )
            _assert_table_command_denied(
                connection,
                command="DELETE",
                table_name=table_name,
                event_id=event_id,
            )
        finally:
            transaction.rollback()


def test_backup_account_can_select_but_cannot_modify_migrated_data(
    backup_database: _BackupDatabase,
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    inserted_username = f"backup-permission-insert-{uuid4().hex}"
    with mysql_engine.begin() as connection:
        user_id = _insert_user(connection)

    try:
        with backup_database.engine.connect() as connection:
            transaction = connection.begin()
            try:
                current_user = connection.scalar(sa.text("SELECT CURRENT_USER()"))
                assert str(current_user).partition("@")[0] == backup_database.username
                assert (
                    connection.scalar(
                        sa.text("SELECT display_name FROM users WHERE id = :user_id"),
                        {"user_id": user_id},
                    )
                    == "Constraint Test"
                )

                _assert_mysql_command_denied(
                    connection,
                    command="INSERT on users",
                    statement="""
                        INSERT INTO users (
                            username_normalized, display_name, password_hash, status
                        ) VALUES (
                            :username, 'Backup Insert', '$argon2id$test', 'active'
                        )
                    """,
                    parameters={"username": inserted_username},
                )
                assert (
                    connection.scalar(
                        sa.text(
                            "SELECT COUNT(*) FROM users "
                            "WHERE username_normalized = :username"
                        ),
                        {"username": inserted_username},
                    )
                    == 0
                )

                _assert_mysql_command_denied(
                    connection,
                    command="UPDATE on users",
                    statement="""
                        UPDATE users
                        SET display_name = 'Backup Update'
                        WHERE id = :user_id
                    """,
                    parameters={"user_id": user_id},
                )
                assert (
                    connection.scalar(
                        sa.text("SELECT display_name FROM users WHERE id = :user_id"),
                        {"user_id": user_id},
                    )
                    == "Constraint Test"
                )

                _assert_mysql_command_denied(
                    connection,
                    command="DELETE on users",
                    statement="DELETE FROM users WHERE id = :user_id",
                    parameters={"user_id": user_id},
                )
                assert (
                    connection.scalar(
                        sa.text("SELECT COUNT(*) FROM users WHERE id = :user_id"),
                        {"user_id": user_id},
                    )
                    == 1
                )
            finally:
                transaction.rollback()

        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text("SELECT display_name FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )
                == "Constraint Test"
            )
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT COUNT(*) FROM users "
                        "WHERE username_normalized = :username"
                    ),
                    {"username": inserted_username},
                )
                == 0
            )
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM users WHERE username_normalized = :username"),
                {"username": inserted_username},
            )
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )


def test_backup_account_cannot_create_or_drop_tables(
    backup_database: _BackupDatabase,
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    create_target = f"backup_permission_create_{uuid4().hex}"
    drop_target = f"backup_permission_drop_{uuid4().hex}"
    with mysql_engine.begin() as connection:
        connection.execute(
            sa.text(
                f"CREATE TABLE {drop_target} "
                "(id BIGINT NOT NULL PRIMARY KEY) ENGINE=InnoDB"
            )
        )

    try:
        with backup_database.engine.connect() as connection:
            _assert_mysql_command_denied(
                connection,
                command=f"CREATE TABLE {create_target}",
                statement=(
                    f"CREATE TABLE {create_target} "
                    "(id BIGINT NOT NULL PRIMARY KEY) ENGINE=InnoDB"
                ),
            )
            connection.rollback()

        with backup_database.engine.connect() as connection:
            _assert_mysql_command_denied(
                connection,
                command=f"DROP TABLE {drop_target}",
                statement=f"DROP TABLE {drop_target}",
            )
            connection.rollback()

        inspector = sa.inspect(mysql_engine)
        assert not inspector.has_table(create_target)
        assert inspector.has_table(drop_target)
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(sa.text(f"DROP TABLE IF EXISTS {create_target}"))
            connection.execute(sa.text(f"DROP TABLE IF EXISTS {drop_target}"))


def test_backup_account_can_write_only_backup_audit_state(
    backup_database: _BackupDatabase,
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    backup_uuid = uuid4()
    verification_uuid = uuid4()
    snapshot_id: int | None = None
    verification_id: int | None = None
    try:
        with backup_database.engine.begin() as connection:
            snapshot_result = connection.execute(
                sa.text(
                    """
                    INSERT INTO backup_snapshots (
                        backup_uuid, status, database_name, schema_revision,
                        key_id, started_at
                    ) VALUES (
                        :backup_uuid, 'running', DATABASE(), '0019',
                        'permission-test', UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {"backup_uuid": backup_uuid.bytes},
            )
            snapshot_id = int(snapshot_result.lastrowid)
            connection.execute(
                sa.text(
                    """
                    UPDATE backup_snapshots
                    SET status = 'failed', completed_at = UTC_TIMESTAMP(6),
                        failure_code = 'permission_test'
                    WHERE id = :snapshot_id
                    """
                ),
                {"snapshot_id": snapshot_id},
            )
            verification_result = connection.execute(
                sa.text(
                    """
                    INSERT INTO restore_verifications (
                        verification_uuid, backup_snapshot_id,
                        target_database_name, target_storage_root_sha256,
                        status, started_at
                    ) VALUES (
                        :verification_uuid, :snapshot_id,
                        :target_database_name, :target_root_sha256,
                        'running', UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "verification_uuid": verification_uuid.bytes,
                    "snapshot_id": snapshot_id,
                    "target_database_name": f"clsen_restore_{uuid4().hex}",
                    "target_root_sha256": bytes(32),
                },
            )
            verification_id = int(verification_result.lastrowid)
            connection.execute(
                sa.text(
                    """
                    UPDATE restore_verifications
                    SET status = 'failed', completed_at = UTC_TIMESTAMP(6),
                        failure_code = 'permission_test'
                    WHERE id = :verification_id
                    """
                ),
                {"verification_id": verification_id},
            )

        with backup_database.engine.connect() as connection:
            _assert_mysql_command_denied(
                connection,
                command="DELETE on backup_snapshots",
                statement="DELETE FROM backup_snapshots WHERE id = :snapshot_id",
                parameters={"snapshot_id": snapshot_id},
            )
            connection.rollback()

        with backup_database.engine.connect() as connection:
            barrier_id = connection.scalar(
                sa.text(
                    "SELECT id FROM maintenance_write_barrier WHERE id = 1 FOR UPDATE"
                )
            )
            assert barrier_id == 1
            connection.rollback()

        with backup_database.engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError) as barrier_error:
                connection.execute(
                    sa.text(
                        "UPDATE maintenance_write_barrier SET sentinel = 2 WHERE id = 1"
                    )
                )
            assert getattr(barrier_error.value.orig, "args", (None,))[0] == 3819
            connection.rollback()

        with backup_database.engine.connect() as connection:
            _assert_mysql_command_denied(
                connection,
                command="DELETE on maintenance_write_barrier",
                statement="DELETE FROM maintenance_write_barrier WHERE id = 1",
            )
            connection.rollback()
    finally:
        with mysql_engine.begin() as connection:
            if verification_id is not None:
                connection.execute(
                    sa.text("DELETE FROM restore_verifications WHERE id = :id"),
                    {"id": verification_id},
                )
            if snapshot_id is not None:
                connection.execute(
                    sa.text("DELETE FROM backup_snapshots WHERE id = :id"),
                    {"id": snapshot_id},
                )


def test_daily_dataset_and_version_business_keys_are_unique(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            dataset_id = _insert_dataset(
                connection,
                report_date=date(2026, 8, 1),
                report_type="business_report",
            )
            with pytest.raises(IntegrityError):
                _insert_dataset(
                    connection,
                    report_date=date(2026, 8, 1),
                    report_type="business_report",
                )

            return_dataset_id = _insert_dataset(
                connection,
                report_date=date(2026, 8, 1),
                report_type="return_report",
            )
            _insert_version(
                connection,
                dataset_id=dataset_id,
                report_type="business_report",
                version_no=1,
                user_id=user_id,
            )
            with pytest.raises(IntegrityError):
                _insert_version(
                    connection,
                    dataset_id=dataset_id,
                    report_type="business_report",
                    version_no=1,
                    user_id=user_id,
                )
            assert return_dataset_id != dataset_id
        finally:
            transaction.rollback()


@pytest.mark.parametrize("pointer_table", ["dataset_drafts", "dataset_publications"])
def test_dataset_pointer_cannot_reference_another_dataset_version(
    pointer_table: str,
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            first_dataset = _insert_dataset(
                connection,
                report_date=date(2026, 8, 2),
                report_type="business_report",
            )
            second_dataset = _insert_dataset(
                connection,
                report_date=date(2026, 8, 3),
                report_type="business_report",
            )
            first_version = _insert_version(
                connection,
                dataset_id=first_dataset,
                report_type="business_report",
                version_no=1,
                user_id=user_id,
            )
            second_version = _insert_version(
                connection,
                dataset_id=second_dataset,
                report_type="business_report",
                version_no=1,
                user_id=user_id,
            )
            if pointer_table == "dataset_drafts":
                connection.execute(
                    sa.text(
                        "INSERT INTO dataset_drafts ("
                        "dataset_id, version_id, version_status"
                        ") VALUES (:dataset_id, :version_id, 'draft')"
                    ),
                    {"dataset_id": first_dataset, "version_id": first_version},
                )
            else:
                for version_id in (first_version, second_version):
                    connection.execute(
                        sa.text(
                            """
                            UPDATE dataset_versions
                            SET status = 'published',
                                sealed_at = CURRENT_TIMESTAMP(6)
                            WHERE id = :version_id
                            """
                        ),
                        {"version_id": version_id},
                    )
                connection.execute(
                    sa.text(
                        "INSERT INTO dataset_publications ("
                        "dataset_id, version_id, version_status"
                        ") VALUES (:dataset_id, :version_id, 'published')"
                    ),
                    {"dataset_id": first_dataset, "version_id": first_version},
                )
            with pytest.raises(IntegrityError):
                connection.execute(
                    sa.text(
                        f"UPDATE {pointer_table} SET version_id = :version_id "
                        "WHERE dataset_id = :dataset_id"
                    ),
                    {"dataset_id": first_dataset, "version_id": second_version},
                )
        finally:
            transaction.rollback()


def test_current_parse_attempt_pointer_must_belong_to_its_batch(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            first_batch = _insert_stage_four_batch(
                connection,
                user_id=user_id,
            )
            second_batch = _insert_stage_four_batch(
                connection,
                user_id=user_id,
            )
            attempt_id = _insert_stage_four_attempt(
                connection,
                batch_id=second_batch,
                user_id=user_id,
            )
            _insert_stage_four_baseline(connection, attempt_id=attempt_id)

            _assert_integrity_rejected(
                connection,
                """
                UPDATE import_batches
                SET current_successful_parse_attempt_id = :attempt_id,
                    report_type = 'business_report', source_row_count = 0
                WHERE id = :batch_id
                """,
                {"attempt_id": attempt_id, "batch_id": first_batch},
            )
        finally:
            transaction.rollback()


def test_current_parse_metadata_must_be_all_null_or_all_present(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            batch_id = _insert_stage_four_batch(connection, user_id=user_id)
            attempt_id = _insert_stage_four_attempt(
                connection,
                batch_id=batch_id,
                user_id=user_id,
            )
            _insert_stage_four_baseline(connection, attempt_id=attempt_id)

            invalid_combinations = (
                (None, None, 0),
                (None, "business_report", None),
                (None, "business_report", 0),
                (attempt_id, None, None),
                (attempt_id, None, 0),
                (attempt_id, "business_report", None),
            )
            for pointer, report_type, source_row_count in invalid_combinations:
                _assert_integrity_rejected(
                    connection,
                    """
                    UPDATE import_batches
                    SET current_successful_parse_attempt_id = :pointer,
                        report_type = :report_type,
                        source_row_count = :source_row_count
                    WHERE id = :batch_id
                    """,
                    {
                        "pointer": pointer,
                        "report_type": report_type,
                        "source_row_count": source_row_count,
                        "batch_id": batch_id,
                    },
                )

            updated = connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET current_successful_parse_attempt_id = :pointer,
                        report_type = 'business_report',
                        source_row_count = 0
                    WHERE id = :batch_id
                    """
                ),
                {"pointer": attempt_id, "batch_id": batch_id},
            )
            assert updated.rowcount == 1
        finally:
            transaction.rollback()


@pytest.mark.parametrize("table_name", OPERATION_TOKEN_TABLES)
def test_operation_token_registry_enforces_unique_token_and_batch_ownership(
    table_name: str,
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            first_batch_id = _insert_stage_four_batch(
                connection,
                user_id=user_id,
            )
            second_batch_id = _insert_stage_four_batch(
                connection,
                user_id=user_id,
            )
            operation_token = uuid4().bytes
            operation_digest = uuid4().bytes + uuid4().bytes
            connection.execute(
                sa.text(
                    f"""
                    INSERT INTO {table_name} (
                        operation_token, batch_id,
                        operation_digest, registered_at
                    ) VALUES (
                        :operation_token, :batch_id,
                        :operation_digest, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "operation_token": operation_token,
                    "batch_id": first_batch_id,
                    "operation_digest": operation_digest,
                },
            )

            _assert_integrity_rejected(
                connection,
                f"""
                INSERT INTO {table_name} (
                    operation_token, batch_id,
                    operation_digest, registered_at
                ) VALUES (
                    :operation_token, :batch_id,
                    :operation_digest, CURRENT_TIMESTAMP(6)
                )
                """,
                {
                    "operation_token": operation_token,
                    "batch_id": second_batch_id,
                    "operation_digest": uuid4().bytes + uuid4().bytes,
                },
                expected_error_code=1062,
            )
            _assert_integrity_rejected(
                connection,
                f"""
                INSERT INTO {table_name} (
                    operation_token, batch_id,
                    operation_digest, registered_at
                ) VALUES (
                    :operation_token, :missing_batch_id,
                    :operation_digest, CURRENT_TIMESTAMP(6)
                )
                """,
                {
                    "operation_token": uuid4().bytes,
                    "missing_batch_id": second_batch_id + 1_000_000,
                    "operation_digest": uuid4().bytes + uuid4().bytes,
                },
                expected_error_code=(1216, 1452),
                expected_constraint=f"fk_{table_name}_batch",
            )
            assert (
                connection.scalar(
                    sa.text(
                        f"SELECT COUNT(*) FROM {table_name} "
                        "WHERE operation_token = :operation_token"
                    ),
                    {"operation_token": operation_token},
                )
                == 1
            )
        finally:
            transaction.rollback()


def test_parse_operation_identity_foreign_keys_reject_batch_or_digest_mismatch(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            first_batch_id = _insert_stage_four_batch(
                connection,
                user_id=user_id,
            )
            second_batch_id = _insert_stage_four_batch(
                connection,
                user_id=user_id,
            )
            operation_token = uuid4().bytes
            operation_digest = operation_token * 2
            wrong_digest = uuid4().bytes + uuid4().bytes
            connection.execute(
                sa.text(
                    """
                    INSERT INTO parse_operation_tokens (
                        operation_token, batch_id,
                        operation_digest, registered_at
                    ) VALUES (
                        :operation_token, :batch_id,
                        :operation_digest, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "operation_token": operation_token,
                    "batch_id": first_batch_id,
                    "operation_digest": operation_digest,
                },
            )

            for batch_id, digest in (
                (first_batch_id, wrong_digest),
                (second_batch_id, operation_digest),
            ):
                _assert_integrity_rejected(
                    connection,
                    """
                    UPDATE import_batches
                    SET status = 'processing',
                        processing_token = :operation_token,
                        processing_operation_digest = :operation_digest,
                        processing_started_at = CURRENT_TIMESTAMP(6)
                    WHERE id = :batch_id
                    """,
                    {
                        "operation_token": operation_token,
                        "operation_digest": digest,
                        "batch_id": batch_id,
                    },
                    expected_error_code=(1216, 1452),
                    expected_constraint="fk_import_batches_parse_operation_token",
                )
                _assert_integrity_rejected(
                    connection,
                    """
                    INSERT INTO parse_attempts (
                        batch_id, site_id, site_config_version_id,
                        processing_token, operation_digest,
                        attempt_number, report_type, confirmation_revision,
                        parser_version, ruleset_version, status,
                        source_row_count, created_by_user_id, completed_at
                    ) VALUES (
                        :batch_id, 1, 1,
                        :operation_token, :operation_digest,
                        1, 'business_report', 1,
                        'parser-v1', 'rules-v1', 'failed',
                        NULL, :user_id, CURRENT_TIMESTAMP(6)
                    )
                    """,
                    {
                        "operation_token": operation_token,
                        "operation_digest": digest,
                        "batch_id": batch_id,
                        "user_id": user_id,
                    },
                    expected_error_code=(1216, 1452),
                    expected_constraint="fk_parse_attempts_operation_token",
                )

            claimed = connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET status = 'processing',
                        processing_token = :operation_token,
                        processing_operation_digest = :operation_digest,
                        processing_started_at = CURRENT_TIMESTAMP(6)
                    WHERE id = :batch_id
                    """
                ),
                {
                    "operation_token": operation_token,
                    "operation_digest": operation_digest,
                    "batch_id": first_batch_id,
                },
            )
            assert claimed.rowcount == 1
            attempt_id = _insert_stage_four_attempt(
                connection,
                batch_id=first_batch_id,
                user_id=user_id,
                status="failed",
                processing_token=operation_token,
            )
            assert attempt_id > 0
        finally:
            transaction.rollback()


def test_batch_review_tables_enforce_identity_state_and_site_boundaries(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            batch_id = _insert_stage_four_batch(connection, user_id=user_id)
            run = connection.execute(
                sa.text(
                    """
                    INSERT INTO batch_review_runs (
                        site_id, created_by_user_id, status, revision
                    ) VALUES (1, :user_id, 'preview', 0)
                    """
                ),
                {"user_id": user_id},
            )
            assert run.lastrowid is not None
            run_id = int(run.lastrowid)
            valid_item = {
                "run_id": run_id,
                "site_id": 1,
                "batch_id": batch_id,
                "filename": "batch.csv",
                "recognition_status": "recognized",
                "status": "eligible",
            }
            connection.execute(
                sa.text(
                    """
                    INSERT INTO batch_review_items (
                        run_id, site_id, batch_id, filename,
                        recognition_status, status
                    ) VALUES (
                        :run_id, :site_id, :batch_id, :filename,
                        :recognition_status, :status
                    )
                    """
                ),
                valid_item,
            )

            _assert_integrity_rejected(
                connection,
                """
                INSERT INTO batch_review_items (
                    run_id, site_id, batch_id, filename,
                    recognition_status, status
                ) VALUES (
                    :run_id, :site_id, :batch_id, :filename,
                    :recognition_status, :status
                )
                """,
                valid_item,
                expected_error_code=1062,
                expected_constraint="uq_batch_review_items_run_batch",
            )
            _assert_integrity_rejected(
                connection,
                "UPDATE batch_review_runs SET status = 'invalid' WHERE id = :run_id",
                {"run_id": run_id},
            )
            _assert_integrity_rejected(
                connection,
                "UPDATE batch_review_runs SET revision = -1 WHERE id = :run_id",
                {"run_id": run_id},
            )
            _assert_integrity_rejected(
                connection,
                """
                UPDATE batch_review_items
                SET status = 'invalid'
                WHERE run_id = :run_id AND batch_id = :batch_id
                """,
                {"run_id": run_id, "batch_id": batch_id},
            )
            _assert_integrity_rejected(
                connection,
                """
                UPDATE batch_review_items
                SET attempt_count = -1
                WHERE run_id = :run_id AND batch_id = :batch_id
                """,
                {"run_id": run_id, "batch_id": batch_id},
                expected_error_code=(1264, 3819),
            )
            other_site = connection.execute(
                sa.text(
                    """
                    INSERT INTO sites (code, display_name, status)
                    VALUES (:code, 'Batch Review Other Site', 'active')
                    """
                ),
                {"code": f"batch-review-{uuid4().hex}"},
            )
            assert other_site.lastrowid is not None
            other_config = connection.execute(
                sa.text(
                    """
                    INSERT INTO site_config_versions (
                        site_id, version_number, source_timezone,
                        reporting_timezone, currency_code,
                        effective_at, created_by_user_id
                    ) VALUES (
                        :site_id, 1, 'UTC', 'UTC', 'USD',
                        CURRENT_TIMESTAMP(6), :user_id
                    )
                    """
                ),
                {"site_id": other_site.lastrowid, "user_id": user_id},
            )
            assert other_config.lastrowid is not None
            other_batch_id = _insert_stage_four_batch(
                connection,
                user_id=user_id,
                site_id=int(other_site.lastrowid),
                site_config_version_id=int(other_config.lastrowid),
            )
            _assert_integrity_rejected(
                connection,
                """
                INSERT INTO batch_review_items (
                    run_id, site_id, batch_id, filename,
                    recognition_status, status
                ) VALUES (
                    :run_id, 2, :batch_id, 'cross-site.csv',
                    'recognized', 'eligible'
                )
                """,
                {"run_id": run_id, "batch_id": other_batch_id},
                expected_error_code=(1216, 1452),
            )
            _assert_integrity_rejected(
                connection,
                """
                UPDATE batch_review_items
                SET operation_token = :operation_token
                WHERE run_id = :run_id AND batch_id = :batch_id
                """,
                {
                    "operation_token": uuid4().bytes,
                    "run_id": run_id,
                    "batch_id": batch_id,
                },
                expected_constraint="ck_batch_review_items_operation_identity",
            )
            _assert_integrity_rejected(
                connection,
                "DELETE FROM import_batches WHERE id = :batch_id",
                {"batch_id": batch_id},
                expected_error_code=(1217, 1451),
            )
            connection.execute(
                sa.text("DELETE FROM batch_review_runs WHERE id = :run_id"),
                {"run_id": run_id},
            )
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT COUNT(*) FROM batch_review_items WHERE run_id = :run_id"
                    ),
                    {"run_id": run_id},
                )
                == 0
            )
        finally:
            transaction.rollback()


def test_parse_attempt_processing_token_is_unique(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            batch_id = _insert_stage_four_batch(connection, user_id=user_id)
            processing_token = uuid4().bytes
            attempt_id = _insert_stage_four_attempt(
                connection,
                batch_id=batch_id,
                user_id=user_id,
                processing_token=processing_token,
            )

            _assert_integrity_rejected(
                connection,
                """
                INSERT INTO parse_attempts (
                    batch_id, site_id, site_config_version_id,
                    processing_token, operation_digest,
                    attempt_number, report_type,
                    confirmation_revision, parser_version, ruleset_version,
                    status, source_row_count, created_by_user_id, completed_at
                ) VALUES (
                    :batch_id, 1, 1, :processing_token, :operation_digest, 2,
                    'business_report', 1, 'parser-v1', 'rules-v1',
                    'succeeded', 0, :user_id, CURRENT_TIMESTAMP(6)
                )
                """,
                {
                    "batch_id": batch_id,
                    "processing_token": processing_token,
                    "operation_digest": processing_token * 2,
                    "user_id": user_id,
                },
            )
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT id FROM parse_attempts "
                        "WHERE processing_token = :processing_token"
                    ),
                    {"processing_token": processing_token},
                )
                == attempt_id
            )
        finally:
            transaction.rollback()


def test_stage_four_confirmation_and_processing_lease_are_consistent(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            raw_file = connection.execute(
                sa.text(
                    """
                    INSERT INTO raw_files (
                        sha256, storage_key, original_filename,
                        size_bytes, uploaded_by_user_id
                    ) VALUES (:digest, :key, 'unconfirmed.csv', 1, :user_id)
                    """
                ),
                {
                    "digest": uuid4().bytes + uuid4().bytes,
                    "key": f"sha256/unconfirmed/{uuid4().hex}",
                    "user_id": user_id,
                },
            )
            batch = connection.execute(
                sa.text(
                    """
                    INSERT INTO import_batches (
                        raw_file_id, site_id, site_config_version_id,
                        report_type, report_date, status,
                        created_by_user_id
                    ) VALUES (
                        :raw_file_id, 1, 1, NULL, NULL, 'uploaded', :user_id
                    )
                    """
                ),
                {"raw_file_id": raw_file.lastrowid, "user_id": user_id},
            )
            assert batch.lastrowid is not None
            batch_id = int(batch.lastrowid)

            unconfirmed_token = uuid4().bytes
            connection.execute(
                sa.text(
                    """
                    INSERT INTO parse_operation_tokens (
                        operation_token, batch_id,
                        operation_digest, registered_at
                    ) VALUES (
                        :token, :batch_id,
                        :operation_digest, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "batch_id": batch_id,
                    "token": unconfirmed_token,
                    "operation_digest": unconfirmed_token * 2,
                },
            )
            _assert_integrity_rejected(
                connection,
                """
                UPDATE import_batches
                SET status = 'processing',
                    processing_token = :token,
                    processing_operation_digest = :operation_digest,
                    processing_started_at = CURRENT_TIMESTAMP(6)
                WHERE id = :batch_id
                """,
                {
                    "batch_id": batch_id,
                    "token": unconfirmed_token,
                    "operation_digest": unconfirmed_token * 2,
                },
            )
            _assert_integrity_rejected(
                connection,
                """
                UPDATE import_batches
                SET confirmation_revision = 1,
                    confirmed_report_type = 'business_report'
                WHERE id = :batch_id
                """,
                {"batch_id": batch_id},
            )
            connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET site_id = 1, report_date = '2026-08-07',
                        confirmed_report_type = 'business_report',
                        confirmation_revision = 1,
                        confirmed_by_user_id = :user_id,
                        confirmed_at = CURRENT_TIMESTAMP(6)
                    WHERE id = :batch_id
                    """
                ),
                {"batch_id": batch_id, "user_id": user_id},
            )

            _assert_integrity_rejected(
                connection,
                """
                UPDATE import_batches SET status = 'processing'
                WHERE id = :batch_id
                """,
                {"batch_id": batch_id},
            )
            processing_token = uuid4().bytes
            connection.execute(
                sa.text(
                    """
                    INSERT INTO parse_operation_tokens (
                        operation_token, batch_id,
                        operation_digest, registered_at
                    ) VALUES (
                        :token, :batch_id,
                        :operation_digest, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "batch_id": batch_id,
                    "token": processing_token,
                    "operation_digest": processing_token * 2,
                },
            )
            claimed = connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET status = 'processing',
                        processing_token = :token,
                        processing_operation_digest = :operation_digest,
                        processing_started_at = CURRENT_TIMESTAMP(6)
                    WHERE id = :batch_id AND status = 'uploaded'
                """
                ),
                {
                    "batch_id": batch_id,
                    "token": processing_token,
                    "operation_digest": processing_token * 2,
                },
            )
            assert claimed.rowcount == 1

            stale_completion = connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET status = 'processing_failed',
                        processing_token = NULL,
                        processing_operation_digest = NULL,
                        processing_started_at = NULL
                    WHERE id = :batch_id AND processing_token = :token
                    """
                ),
                {"batch_id": batch_id, "token": uuid4().bytes},
            )
            assert stale_completion.rowcount == 0
            assert (
                connection.scalar(
                    sa.text("SELECT status FROM import_batches WHERE id = :batch_id"),
                    {"batch_id": batch_id},
                )
                == "processing"
            )

            completed = connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET status = 'processing_failed',
                        processing_token = NULL,
                        processing_operation_digest = NULL,
                        processing_started_at = NULL
                    WHERE id = :batch_id AND processing_token = :token
                    """
                ),
                {"batch_id": batch_id, "token": processing_token},
            )
            assert completed.rowcount == 1
        finally:
            transaction.rollback()


def test_parse_baseline_and_current_pointer_require_matching_successful_attempt(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            batch_id = _insert_stage_four_batch(connection, user_id=user_id)

            no_baseline_attempt = _insert_stage_four_attempt(
                connection,
                batch_id=batch_id,
                user_id=user_id,
                attempt_number=1,
            )
            _assert_integrity_rejected(
                connection,
                """
                UPDATE import_batches
                SET current_successful_parse_attempt_id = :attempt_id,
                    report_type = 'business_report', source_row_count = 0
                WHERE id = :batch_id
                """,
                {"attempt_id": no_baseline_attempt, "batch_id": batch_id},
            )

            failed_attempt = _insert_stage_four_attempt(
                connection,
                batch_id=batch_id,
                user_id=user_id,
                attempt_number=2,
                status="failed",
            )
            _assert_integrity_rejected(
                connection,
                """
                INSERT INTO parse_baselines (
                    parse_attempt_id, report_type, attempt_status,
                    parser_version, ruleset_version,
                    data_digest, row_count, totals_json
                ) VALUES (
                    :attempt_id, 'business_report', 'succeeded',
                    'parser-v1', 'rules-v1', :digest, 0, :totals
                )
                """,
                {
                    "attempt_id": failed_attempt,
                    "digest": uuid4().bytes + uuid4().bytes,
                    "totals": "{}",
                },
            )

            successful_attempt = _insert_stage_four_attempt(
                connection,
                batch_id=batch_id,
                user_id=user_id,
                attempt_number=3,
            )
            _assert_integrity_rejected(
                connection,
                """
                INSERT INTO parse_baselines (
                    parse_attempt_id, report_type, attempt_status,
                    parser_version, ruleset_version,
                    data_digest, row_count, totals_json
                ) VALUES (
                    :attempt_id, 'return_report', 'succeeded',
                    'parser-v1', 'rules-v1', :digest, 0, :totals
                )
                """,
                {
                    "attempt_id": successful_attempt,
                    "digest": uuid4().bytes + uuid4().bytes,
                    "totals": "{}",
                },
            )
            _insert_stage_four_baseline(
                connection,
                attempt_id=successful_attempt,
            )
            switched = connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET current_successful_parse_attempt_id = :attempt_id,
                        report_type = 'business_report', source_row_count = 0
                    WHERE id = :batch_id
                    """
                ),
                {"attempt_id": successful_attempt, "batch_id": batch_id},
            )
            assert switched.rowcount == 1
            _assert_integrity_rejected(
                connection,
                """
                UPDATE import_batches SET report_type = 'return_report'
                WHERE id = :batch_id
                """,
                {"batch_id": batch_id},
            )
        finally:
            transaction.rollback()


def test_parse_attempt_cannot_mix_site_configuration_with_batch(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            same_site_config = connection.execute(
                sa.text(
                    """
                    INSERT INTO site_config_versions (
                        site_id, version_number, source_timezone,
                        reporting_timezone, currency_code,
                        effective_at, created_by_user_id
                    ) VALUES (
                        1, 2, 'America/Los_Angeles',
                        'America/Los_Angeles', 'USD',
                        CURRENT_TIMESTAMP(6), :user_id
                    )
                    """
                ),
                {"user_id": user_id},
            )
            assert same_site_config.lastrowid is not None
            site = connection.execute(
                sa.text(
                    """
                    INSERT INTO sites (code, display_name, status)
                    VALUES (:code, 'Other Site', 'active')
                    """
                ),
                {"code": f"other-{uuid4().hex}"},
            )
            assert site.lastrowid is not None
            config = connection.execute(
                sa.text(
                    """
                    INSERT INTO site_config_versions (
                        site_id, version_number, source_timezone,
                        reporting_timezone, currency_code,
                        effective_at, created_by_user_id
                    ) VALUES (
                        :site_id, 1, 'UTC', 'UTC', 'USD',
                        CURRENT_TIMESTAMP(6), :user_id
                    )
                    """
                ),
                {"site_id": site.lastrowid, "user_id": user_id},
            )
            assert config.lastrowid is not None
            batch_id = _insert_stage_four_batch(connection, user_id=user_id)
            _insert_stage_four_attempt(
                connection,
                batch_id=batch_id,
                user_id=user_id,
                attempt_number=1,
                site_config_version_id=int(same_site_config.lastrowid),
            )

            other_token = uuid4().bytes
            connection.execute(
                sa.text(
                    """
                    INSERT INTO parse_operation_tokens (
                        operation_token, batch_id,
                        operation_digest, registered_at
                    ) VALUES (
                        :processing_token, :batch_id,
                        :operation_digest, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "batch_id": batch_id,
                    "processing_token": other_token,
                    "operation_digest": other_token * 2,
                },
            )
            _assert_integrity_rejected(
                connection,
                """
                INSERT INTO parse_attempts (
                    batch_id, site_id, site_config_version_id, processing_token,
                    operation_digest,
                    attempt_number, report_type, confirmation_revision,
                    parser_version, ruleset_version, status,
                    source_row_count, created_by_user_id, completed_at
                ) VALUES (
                    :batch_id, :site_id, :config_id, :processing_token,
                    :operation_digest, 2,
                    'business_report', 1, 'parser-v1', 'rules-v1',
                    'succeeded', 0, :user_id, CURRENT_TIMESTAMP(6)
                )
                """,
                {
                    "batch_id": batch_id,
                    "site_id": site.lastrowid,
                    "config_id": config.lastrowid,
                    "processing_token": other_token,
                    "operation_digest": other_token * 2,
                    "user_id": user_id,
                },
            )
        finally:
            transaction.rollback()
