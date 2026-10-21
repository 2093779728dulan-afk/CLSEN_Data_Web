from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.db.settings import DatabaseSettings
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from tests.integration.historical_schema_support import (
    create_historical_schema_engine as _create_migration_test_engine,
)

pytestmark = pytest.mark.mysql

_HEAD_REVISION = "0028"
_PUBLICATION_COMPATIBILITY_INDEX = "fk_dataset_publications_version"
_EXPECTED_PUBLICATION_COMPATIBILITY_INDEX = (
    (1, "dataset_id", 1, None, "A", "BTREE"),
    (2, "version_id", 1, None, "A", "BTREE"),
)
_EXPECTED_ISSUE_REVIEW_COMPATIBILITY_INDEX = (
    (1, "version_id", 1, None, "A", "BTREE"),
    (2, "validation_run_id", 1, None, "A", "BTREE"),
    (3, "validation_issue_id", 1, None, "A", "BTREE"),
)

_ADMIN_OPERATION_TRIGGER_NAMES = (
    "trg_admin_operation_tokens_no_update",
    "trg_admin_operation_tokens_no_delete",
    "trg_admin_operation_results_no_update",
    "trg_admin_operation_results_no_delete",
)
_REVIEW_REPAIR_TABLES = (
    "review_operation_results",
    "version_review_events",
    "review_operation_tokens",
)
_PUBLICATION_RESULT_TABLE = "publication_command_results"


def _current_revision(settings: DatabaseSettings) -> str:
    engine = _create_migration_test_engine(settings)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(
                sa.text("SELECT version_num FROM alembic_version")
            )
    finally:
        engine.dispose()
    assert isinstance(revision, str)
    return revision


def _index_signature(
    connection: Connection,
    *,
    table_name: str,
    index_name: str,
) -> tuple[tuple[int, str, int, int | None, str | None, str], ...]:
    rows = (
        connection.execute(
            sa.text(
                """
                SELECT seq_in_index, column_name, non_unique, sub_part,
                       collation, index_type
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                  AND table_name = :table_name
                  AND index_name = :index_name
                ORDER BY seq_in_index
                """
            ),
            {"table_name": table_name, "index_name": index_name},
        )
        .tuples()
        .all()
    )
    return tuple(
        (
            int(row[0]),
            str(row[1]),
            int(row[2]),
            None if row[3] is None else int(row[3]),
            None if row[4] is None else str(row[4]).upper(),
            str(row[5]).upper(),
        )
        for row in rows
    )


def _publication_compatibility_index_signature(
    connection: Connection,
) -> tuple[tuple[int, str, int, int | None, str | None, str], ...]:
    return _index_signature(
        connection,
        table_name="dataset_publications",
        index_name=_PUBLICATION_COMPATIBILITY_INDEX,
    )


def _issue_review_compatibility_index_signature(
    connection: Connection,
) -> tuple[tuple[int, str, int, int | None, str | None, str], ...]:
    return _index_signature(
        connection,
        table_name="issue_review_events",
        index_name="fk_issue_review_events_issue_run",
    )


def _drop_publication_compatibility_index_if_present(
    connection: Connection,
) -> None:
    if _publication_compatibility_index_signature(connection):
        connection.execute(
            sa.text(
                "DROP INDEX `fk_dataset_publications_version` ON `dataset_publications`"
            )
        )


def _reset_admin_operation_retry_state(connection: Connection) -> None:
    for trigger_name in _ADMIN_OPERATION_TRIGGER_NAMES:
        connection.execute(sa.text(f"DROP TRIGGER IF EXISTS `{trigger_name}`"))
    connection.execute(sa.text("DROP TABLE IF EXISTS admin_operation_results"))
    connection.execute(sa.text("DROP TABLE IF EXISTS admin_operation_tokens"))
    connection.execute(sa.text("UPDATE alembic_version SET version_num = '0010'"))


def _drop_review_repair_tables(connection: Connection) -> None:
    for table_name in _REVIEW_REPAIR_TABLES:
        connection.execute(sa.text(f"DROP TABLE `{table_name}`"))


def test_worker_observability_schema_roundtrips_without_business_data_changes(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.upgrade(alembic_config, _HEAD_REVISION)
    command.downgrade(alembic_config, "0022")
    engine = _create_migration_test_engine(mysql_settings)
    try:
        with engine.connect() as connection:
            sites_before = int(connection.scalar(sa.text("SELECT COUNT(*) FROM sites")))
        assert "worker_instances" not in sa.inspect(engine).get_table_names()
        assert "worker_consumer_states" not in sa.inspect(engine).get_table_names()

        command.upgrade(alembic_config, "0023")
        assert _current_revision(mysql_settings) == "0023"
        inspector = sa.inspect(engine)
        assert {
            column["name"] for column in inspector.get_columns("worker_instances")
        } == {
            "instance_id",
            "role",
            "build_id",
            "supported_queues",
            "lifecycle_status",
            "heartbeat_sequence",
            "started_at",
            "last_heartbeat_at",
            "stopped_at",
            "last_result_code",
        }
        assert {
            column["name"] for column in inspector.get_columns("worker_consumer_states")
        } == {
            "worker_instance_id",
            "queue_name",
            "last_poll_started_at",
            "last_poll_completed_at",
            "last_poll_succeeded_at",
            "last_poll_failed_at",
            "consecutive_failures",
            "last_result_code",
            "last_failure_code",
        }
        assert {
            index["name"] for index in inspector.get_indexes("worker_instances")
        } == {
            "ix_worker_instances_lifecycle_heartbeat",
            "ix_worker_instances_retention",
        }
        consumer_foreign_keys = inspector.get_foreign_keys("worker_consumer_states")
        assert len(consumer_foreign_keys) == 1
        assert consumer_foreign_keys[0]["referred_table"] == "worker_instances"
        assert consumer_foreign_keys[0]["options"]["ondelete"] == "CASCADE"

        instance_id = uuid4().bytes
        queue_names = (
            "return_dedup",
            "publication_outbox",
            "catalog_export",
            "catalog_import",
        )
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO worker_instances (
                        instance_id, role, build_id, supported_queues,
                        lifecycle_status
                    ) VALUES (
                        :instance_id, 'local_worker', :build_id,
                        CAST(:supported_queues AS JSON), 'running'
                    )
                    """
                ),
                {
                    "instance_id": instance_id,
                    "build_id": "migration-roundtrip",
                    "supported_queues": json.dumps(queue_names),
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO worker_consumer_states (
                        worker_instance_id, queue_name
                    ) VALUES (:instance_id, :queue_name)
                    """
                ),
                [
                    {"instance_id": instance_id, "queue_name": queue_name}
                    for queue_name in queue_names
                ],
            )
            assert (
                connection.scalar(
                    sa.text(
                        """
                    SELECT COUNT(*) FROM worker_consumer_states
                    WHERE worker_instance_id = :instance_id
                    """
                    ),
                    {"instance_id": instance_id},
                )
                == 4
            )
            connection.execute(
                sa.text(
                    "DELETE FROM worker_instances WHERE instance_id = :instance_id"
                ),
                {"instance_id": instance_id},
            )
            assert (
                connection.scalar(
                    sa.text(
                        """
                    SELECT COUNT(*) FROM worker_consumer_states
                    WHERE worker_instance_id = :instance_id
                    """
                    ),
                    {"instance_id": instance_id},
                )
                == 0
            )

        command.downgrade(alembic_config, "0022")
        assert _current_revision(mysql_settings) == "0022"
        tables = set(sa.inspect(engine).get_table_names())
        assert "worker_consumer_states" not in tables
        assert "worker_instances" not in tables
        with engine.connect() as connection:
            assert int(connection.scalar(sa.text("SELECT COUNT(*) FROM sites"))) == (
                sites_before
            )
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "0022")
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_batch_review_downgrade_refuses_to_drop_persisted_runs(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.upgrade(alembic_config, _HEAD_REVISION)
    engine = _create_migration_test_engine(mysql_settings)
    user_id: int | None = None
    try:
        with engine.begin() as connection:
            user = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status
                    ) VALUES (
                        :username, 'Batch Review Downgrade',
                        '$argon2id$test', 'active'
                    )
                    """
                ),
                {"username": f"batch-review-downgrade-{uuid4().hex}"},
            )
            assert user.lastrowid is not None
            user_id = int(user.lastrowid)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO batch_review_runs (
                        site_id, created_by_user_id, status, revision
                    ) VALUES (1, :user_id, 'preview', 0)
                    """
                ),
                {"user_id": user_id},
            )

        with pytest.raises(RuntimeError, match="0021 downgrade refused"):
            command.downgrade(alembic_config, "0020")
        assert _current_revision(mysql_settings) == "0021"
    finally:
        if user_id is not None:
            with engine.begin() as connection:
                connection.execute(sa.text("DELETE FROM batch_review_runs"))
                connection.execute(
                    sa.text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )
        engine.dispose()
        command.downgrade(alembic_config, "0020")
        command.upgrade(alembic_config, _HEAD_REVISION)


def _drop_publication_result_table(connection: Connection) -> None:
    connection.execute(sa.text(f"DROP TABLE `{_PUBLICATION_RESULT_TABLE}`"))


def _insert_stage_four_type_roundtrip_case(
    connection: Connection,
    *,
    attempt_status: str,
) -> tuple[int, int]:
    if attempt_status not in {"succeeded", "failed"}:
        raise ValueError("attempt_status must be terminal")
    user = connection.execute(
        sa.text(
            """
            INSERT INTO users (
                username_normalized, display_name, password_hash, status
            ) VALUES (
                :username, 'Type Roundtrip Test', '$argon2id$test', 'active'
            )
            """
        ),
        {"username": f"type-roundtrip-{uuid4().hex}"},
    )
    assert user.lastrowid is not None
    user_id = int(user.lastrowid)
    raw_file = connection.execute(
        sa.text(
            """
            INSERT INTO raw_files (
                sha256, storage_key, original_filename,
                size_bytes, uploaded_by_user_id
            ) VALUES (
                :digest, :storage_key, 'type-roundtrip.csv', 1, :user_id
            )
            """
        ),
        {
            "digest": uuid4().bytes + uuid4().bytes,
            "storage_key": f"sha256/type-roundtrip/{uuid4().hex}",
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
                :raw_file_id, 1, 1,
                NULL, '2026-08-07', :batch_status,
                'business_report', 1,
                :user_id, CURRENT_TIMESTAMP(6),
                :user_id
            )
            """
        ),
        {
            "raw_file_id": raw_file.lastrowid,
            "batch_status": (
                "staged" if attempt_status == "succeeded" else "processing_failed"
            ),
            "user_id": user_id,
        },
    )
    assert batch.lastrowid is not None
    batch_id = int(batch.lastrowid)
    processing_token = uuid4().bytes
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
    attempt = connection.execute(
        sa.text(
            """
            INSERT INTO parse_attempts (
                batch_id, site_id, site_config_version_id,
                processing_token, operation_digest,
                attempt_number, report_type, confirmation_revision,
                parser_version, ruleset_version, status,
                source_row_count, created_by_user_id, completed_at
            ) VALUES (
                :batch_id, 1, 1,
                :processing_token, :operation_digest,
                1, 'return_report', 1,
                'parser-v1', 'rules-v1', :attempt_status,
                IF(:attempt_status = 'succeeded', 0, NULL),
                :user_id, CURRENT_TIMESTAMP(6)
            )
            """
        ),
        {
            "batch_id": batch_id,
            "processing_token": processing_token,
            "operation_digest": processing_token * 2,
            "attempt_status": attempt_status,
            "user_id": user_id,
        },
    )
    assert attempt.lastrowid is not None
    attempt_id = int(attempt.lastrowid)
    if attempt_status == "succeeded":
        connection.execute(
            sa.text(
                """
                INSERT INTO parse_baselines (
                    parse_attempt_id, report_type, attempt_status,
                    parser_version, ruleset_version,
                    data_digest, row_count, totals_json
                ) VALUES (
                    :attempt_id, 'return_report', 'succeeded',
                    'parser-v1', 'rules-v1', :data_digest, 0, '{}'
                )
                """
            ),
            {
                "attempt_id": attempt_id,
                "data_digest": uuid4().bytes + uuid4().bytes,
            },
        )
    return batch_id, attempt_id


def test_empty_database_upgrades_to_head_idempotently(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    try:
        command.upgrade(alembic_config, _HEAD_REVISION)
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, _HEAD_REVISION)
        command.upgrade(alembic_config, _HEAD_REVISION)

        assert _current_revision(mysql_settings) == _HEAD_REVISION
    finally:
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_each_historical_revision_upgrades_in_order(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    try:
        command.upgrade(alembic_config, _HEAD_REVISION)
        command.downgrade(alembic_config, "base")
        for revision in (
            "0001",
            "0002",
            "0003",
            "0004",
            "0005",
            "0006",
            "0007",
            "0008",
            "0009",
            "0010",
            "0011",
            "0012",
            "0013",
            "0014",
            "0015",
            "0016",
            "0017",
            "0018",
            "0019",
            "0020",
            "0021",
            "0022",
            "0023",
            "0024",
            "0025",
            "0026",
            "0027",
            _HEAD_REVISION,
        ):
            command.upgrade(alembic_config, revision)
            assert _current_revision(mysql_settings) == revision
    finally:
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_admin_operation_migration_recovers_an_exact_interrupted_table_create(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.downgrade(alembic_config, "0010")
    command.upgrade(alembic_config, "0011")
    engine = _create_migration_test_engine(mysql_settings)
    try:
        with engine.begin() as connection:
            for trigger_name in _ADMIN_OPERATION_TRIGGER_NAMES:
                connection.execute(sa.text(f"DROP TRIGGER IF EXISTS `{trigger_name}`"))
            connection.execute(sa.text("DROP TABLE admin_operation_results"))
            connection.execute(
                sa.text("UPDATE alembic_version SET version_num = '0010'")
            )

        command.upgrade(alembic_config, "0011")

        assert _current_revision(mysql_settings) == "0011"
        with engine.connect() as connection:
            assert (
                int(
                    connection.scalar(
                        sa.text("SELECT COUNT(*) FROM admin_operation_tokens")
                    )
                    or 0
                )
                == 0
            )
            assert (
                int(
                    connection.scalar(
                        sa.text("SELECT COUNT(*) FROM admin_operation_results")
                    )
                    or 0
                )
                == 0
            )
            triggers = frozenset(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT trigger_name
                        FROM information_schema.triggers
                        WHERE trigger_schema = DATABASE()
                          AND event_object_table IN (
                              'admin_operation_tokens',
                              'admin_operation_results'
                          )
                        """
                    )
                )
            )
            assert triggers == frozenset(_ADMIN_OPERATION_TRIGGER_NAMES)
    finally:
        with engine.begin() as connection:
            _reset_admin_operation_retry_state(connection)
        engine.dispose()
        command.upgrade(alembic_config, _HEAD_REVISION)


@pytest.mark.parametrize(
    "mutations",
    (
        ("ALTER TABLE admin_operation_tokens MODIFY registered_at DATETIME NOT NULL",),
        (
            "ALTER TABLE admin_operation_tokens "
            "DROP CHECK ck_admin_operation_tokens_kind",
            "ALTER TABLE admin_operation_tokens ADD CONSTRAINT "
            "ck_admin_operation_tokens_kind CHECK (operation_kind <> '')",
        ),
        (
            "CREATE INDEX ix_admin_operation_tokens_unexpected "
            "ON admin_operation_tokens (registered_at)",
        ),
        (
            "ALTER TABLE admin_operation_tokens "
            "DROP FOREIGN KEY fk_admin_operation_tokens_actor",
            "ALTER TABLE admin_operation_tokens ADD CONSTRAINT "
            "fk_admin_operation_tokens_actor FOREIGN KEY (actor_user_id) "
            "REFERENCES users (id) ON DELETE RESTRICT ON UPDATE CASCADE",
        ),
        (
            "DROP TABLE admin_operation_results",
            "ALTER TABLE admin_operation_tokens "
            "DROP INDEX uq_admin_operation_tokens_identity",
        ),
        (
            "DROP TRIGGER trg_admin_operation_tokens_no_update",
            "CREATE TRIGGER trg_admin_operation_tokens_no_update "
            "BEFORE UPDATE ON admin_operation_tokens FOR EACH ROW "
            "SET NEW.registered_at = OLD.registered_at",
        ),
    ),
    ids=(
        "column-type",
        "check-clause",
        "unexpected-index",
        "foreign-key-action",
        "missing-unique",
        "wrong-trigger",
    ),
)
def test_admin_operation_migration_rejects_wrong_partial_definitions(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
    mutations: tuple[str, ...],
) -> None:
    command.downgrade(alembic_config, "0010")
    command.upgrade(alembic_config, "0011")
    engine = _create_migration_test_engine(mysql_settings)
    try:
        with engine.begin() as connection:
            for mutation in mutations:
                connection.execute(sa.text(mutation))
            connection.execute(
                sa.text("UPDATE alembic_version SET version_num = '0010'")
            )

        with pytest.raises(
            RuntimeError,
            match="incompatible pre-existing administrator operation",
        ):
            command.upgrade(alembic_config, "0011")
        assert _current_revision(mysql_settings) == "0010"
    finally:
        with engine.begin() as connection:
            _reset_admin_operation_retry_state(connection)
        engine.dispose()
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_review_note_repair_validates_a_clean_0016_upgrade(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.upgrade(alembic_config, _HEAD_REVISION)
    command.downgrade(alembic_config, "0016")
    assert _current_revision(mysql_settings) == "0016"

    command.upgrade(alembic_config, "0017")

    assert _current_revision(mysql_settings) == "0017"


def test_review_note_repair_recreates_missing_empty_review_ledgers(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "0016")
    engine = _create_migration_test_engine(mysql_settings)
    try:
        with engine.begin() as connection:
            _drop_review_repair_tables(connection)

        command.upgrade(alembic_config, "0017")

        assert _current_revision(mysql_settings) == "0017"
        with engine.connect() as connection:
            restored_tables = frozenset(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = DATABASE()
                          AND table_name IN (
                              'review_operation_tokens',
                              'review_operation_results',
                              'version_review_events'
                          )
                        """
                    )
                )
            )
            restored_triggers = frozenset(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT trigger_name
                        FROM information_schema.triggers
                        WHERE trigger_schema = DATABASE()
                          AND event_object_table IN (
                              'review_operation_tokens',
                              'review_operation_results',
                              'version_review_events'
                          )
                        """
                    )
                )
            )
        assert restored_tables == {
            "review_operation_tokens",
            "review_operation_results",
            "version_review_events",
        }
        assert restored_triggers == {
            f"trg_{table_name}_no_{operation}"
            for table_name in restored_tables
            for operation in ("update", "delete")
        }
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_review_note_repair_recreates_a_missing_empty_publication_result_ledger(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "0016")
    engine = _create_migration_test_engine(mysql_settings)
    try:
        with engine.begin() as connection:
            _drop_publication_result_table(connection)

        command.upgrade(alembic_config, "0017")

        assert _current_revision(mysql_settings) == "0017"
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                      AND table_name = 'publication_command_results'
                    """
                    )
                )
                == 1
            )
            triggers = frozenset(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT trigger_name
                        FROM information_schema.triggers
                        WHERE trigger_schema = DATABASE()
                          AND event_object_table = 'publication_command_results'
                        """
                    )
                )
            )
        assert triggers == {
            "trg_publication_command_results_no_update",
            "trg_publication_command_results_no_delete",
        }
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_review_note_repair_rejects_missing_review_ledgers_when_revision_exists(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "0016")
    engine = _create_migration_test_engine(mysql_settings)
    username = f"review-repair-evidence-{uuid4().hex}"
    dataset_id: int | None = None
    user_id: int | None = None
    try:
        with engine.begin() as connection:
            user = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status
                    ) VALUES (
                        :username, 'Review repair evidence',
                        '$argon2id$test', 'active'
                    )
                    """
                ),
                {"username": username},
            )
            assert user.lastrowid is not None
            user_id = int(user.lastrowid)
            dataset = connection.execute(
                sa.text(
                    """
                    INSERT INTO daily_datasets (site_id, report_date, report_type)
                    VALUES (1, '2026-08-10', 'business_report')
                    """
                )
            )
            assert dataset.lastrowid is not None
            dataset_id = int(dataset.lastrowid)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO dataset_versions (
                        dataset_id, report_type, version_no, status,
                        data_revision, review_revision, ruleset_version, created_by
                    ) VALUES (
                        :dataset_id, 'business_report', 1, 'draft',
                        0, 1, 'review-repair-test', :user_id
                    )
                    """
                ),
                {"dataset_id": dataset_id, "user_id": user_id},
            )
            _drop_review_repair_tables(connection)

        with pytest.raises(
            RuntimeError,
            match="dataset versions with review-state evidence",
        ):
            command.upgrade(alembic_config, "0017")
        assert _current_revision(mysql_settings) == "0016"

        with engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM dataset_versions WHERE dataset_id = :dataset_id"),
                {"dataset_id": dataset_id},
            )
            connection.execute(
                sa.text("DELETE FROM daily_datasets WHERE id = :dataset_id"),
                {"dataset_id": dataset_id},
            )
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )
        command.upgrade(alembic_config, "0017")
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_review_note_repair_rejects_missing_publication_results_with_outbox_history(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "0016")
    engine = _create_migration_test_engine(mysql_settings)
    dedupe_key = f"publication-repair-evidence-{uuid4().hex}"
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO publication_outbox (
                        publication_event_id, site_config_version_id,
                        topic, dedupe_key, redacted_payload, available_at
                    )
                    SELECT NULL, MIN(id), 'site_config_changed', :dedupe_key,
                           JSON_OBJECT(), CURRENT_TIMESTAMP(6)
                    FROM site_config_versions
                    """
                ),
                {"dedupe_key": dedupe_key},
            )
            _drop_publication_result_table(connection)

        with pytest.raises(
            RuntimeError,
            match="publication_outbox publication-history evidence",
        ):
            command.upgrade(alembic_config, "0017")
        assert _current_revision(mysql_settings) == "0016"

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "DELETE FROM publication_outbox WHERE dedupe_key = :dedupe_key"
                ),
                {"dedupe_key": dedupe_key},
            )
        command.upgrade(alembic_config, "0017")
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_review_note_repair_rejects_an_existing_wrong_table_definition(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.upgrade(alembic_config, _HEAD_REVISION)
    command.downgrade(alembic_config, "0016")
    engine = _create_migration_test_engine(mysql_settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "CREATE INDEX ix_note_threads_unexpected "
                    "ON note_threads (created_at)"
                )
            )

        with pytest.raises(
            RuntimeError,
            match="incompatible pre-existing review/note contract",
        ):
            command.upgrade(alembic_config, "0017")
        assert _current_revision(mysql_settings) == "0016"
    finally:
        with engine.begin() as connection:
            connection.execute(
                sa.text("DROP INDEX ix_note_threads_unexpected ON note_threads")
            )
        engine.dispose()
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_review_note_repair_preserves_legacy_notes_with_review_ledgers_present(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.upgrade(alembic_config, _HEAD_REVISION)
    command.downgrade(alembic_config, "0016")
    engine = _create_migration_test_engine(mysql_settings)
    note_key = f"repair-note-{uuid4().hex}"
    created_at = datetime.now(UTC).replace(tzinfo=None)
    try:
        with engine.begin() as connection:
            batch_id, _attempt_id = _insert_stage_four_type_roundtrip_case(
                connection,
                # This test exercises the 0017 note repair, then intentionally
                # replays the complete migration history in ``finally``.  Use a
                # losslessly downgradeable parse fixture; the dedicated 0007
                # preflight test below covers mismatched failed attempts.
                attempt_status="succeeded",
            )
            author_user_id = int(
                connection.scalar(
                    sa.text(
                        "SELECT created_by_user_id FROM import_batches WHERE id = :id"
                    ),
                    {"id": batch_id},
                )
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO note_threads (
                        note_key, target_type, import_batch_id,
                        version_id, row_id, field_name, created_at
                    ) VALUES (
                        :note_key, 'import_batch', :batch_id,
                        NULL, NULL, NULL, :created_at
                    )
                    """
                ),
                {
                    "note_key": note_key,
                    "batch_id": batch_id,
                    "created_at": created_at,
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO notes (
                        note_key, revision_number, supersedes_note_id,
                        supersedes_revision_number, visibility, body,
                        author_user_id, review_revision, created_at
                    ) VALUES (
                        :note_key, 1, NULL, NULL, 'internal',
                        'preserved repair note', :author_user_id, NULL,
                        :created_at
                    )
                    """
                ),
                {
                    "note_key": note_key,
                    "author_user_id": author_user_id,
                    "created_at": created_at,
                },
            )

        legacy_statements = (
            "ALTER TABLE notes ADD COLUMN target_type VARCHAR(24) NULL, "
            "ADD COLUMN import_batch_id BIGINT UNSIGNED NULL, "
            "ADD COLUMN version_id BIGINT UNSIGNED NULL, "
            "ADD COLUMN row_id BIGINT UNSIGNED NULL, "
            "ADD COLUMN field_name VARCHAR(128) NULL",
            "UPDATE notes INNER JOIN note_threads "
            "ON note_threads.note_key = notes.note_key "
            "SET notes.target_type = note_threads.target_type, "
            "notes.import_batch_id = note_threads.import_batch_id, "
            "notes.version_id = note_threads.version_id, "
            "notes.row_id = note_threads.row_id, "
            "notes.field_name = note_threads.field_name",
            "ALTER TABLE notes MODIFY target_type VARCHAR(24) NOT NULL",
            "CREATE INDEX ix_notes_target_version_row "
            "ON notes (version_id, row_id, id)",
            "ALTER TABLE notes ADD CONSTRAINT fk_notes_import_batch "
            "FOREIGN KEY (import_batch_id) REFERENCES import_batches (id) "
            "ON DELETE RESTRICT ON UPDATE RESTRICT",
            "ALTER TABLE notes ADD CONSTRAINT fk_notes_version "
            "FOREIGN KEY (version_id) REFERENCES dataset_versions (id) "
            "ON DELETE RESTRICT ON UPDATE RESTRICT",
            "ALTER TABLE notes ADD CONSTRAINT fk_notes_version_row "
            "FOREIGN KEY (version_id, row_id) "
            "REFERENCES version_rows (version_id, id) "
            "ON DELETE RESTRICT ON UPDATE RESTRICT",
            "ALTER TABLE notes ADD CONSTRAINT ck_notes_target CHECK ("
            "(target_type = 'import_batch' AND import_batch_id IS NOT NULL "
            "AND version_id IS NULL AND row_id IS NULL AND field_name IS NULL) OR "
            "(target_type = 'version' AND import_batch_id IS NULL "
            "AND version_id IS NOT NULL AND row_id IS NULL AND field_name IS NULL) OR "
            "(target_type = 'row' AND import_batch_id IS NULL "
            "AND version_id IS NOT NULL AND row_id IS NOT NULL "
            "AND field_name IS NULL) OR "
            "(target_type = 'field' AND import_batch_id IS NULL "
            "AND version_id IS NOT NULL AND row_id IS NOT NULL "
            "AND field_name IS NOT NULL))",
            "ALTER TABLE notes DROP FOREIGN KEY fk_notes_previous_revision",
            "DROP INDEX fk_notes_previous_revision ON notes",
            "ALTER TABLE notes DROP CHECK ck_notes_revision_chain",
            "ALTER TABLE notes ADD CONSTRAINT fk_notes_previous_revision "
            "FOREIGN KEY (note_key, supersedes_note_id) "
            "REFERENCES notes (note_key, id) "
            "ON DELETE RESTRICT ON UPDATE RESTRICT",
            "ALTER TABLE notes ADD CONSTRAINT ck_notes_revision_chain CHECK ("
            "(revision_number = 1 AND supersedes_note_id IS NULL) OR "
            "(revision_number > 1 AND supersedes_note_id IS NOT NULL))",
            "ALTER TABLE notes DROP INDEX uq_notes_key_revision_id",
            "ALTER TABLE notes DROP FOREIGN KEY fk_notes_thread",
            "ALTER TABLE notes DROP CHECK ck_notes_body_nonempty",
            "ALTER TABLE notes ALTER COLUMN visibility DROP DEFAULT",
            "ALTER TABLE notes DROP COLUMN supersedes_revision_number",
        )
        with engine.begin() as connection:
            for statement in legacy_statements:
                connection.execute(sa.text(statement))
            for trigger_name in (
                "trg_notes_no_update",
                "trg_notes_no_delete",
                "trg_note_threads_no_update",
                "trg_note_threads_no_delete",
            ):
                connection.execute(sa.text(f"DROP TRIGGER IF EXISTS `{trigger_name}`"))
            connection.execute(sa.text("DROP TABLE note_threads"))

        command.upgrade(alembic_config, "0017")

        assert _current_revision(mysql_settings) == "0017"
        with engine.connect() as connection:
            restored_thread = connection.execute(
                sa.text(
                    """
                    SELECT target_type, import_batch_id, version_id,
                           row_id, field_name, created_at
                    FROM note_threads WHERE note_key = :note_key
                    """
                ),
                {"note_key": note_key},
            ).one()
            assert tuple(restored_thread) == (
                "import_batch",
                batch_id,
                None,
                None,
                None,
                created_at,
            )
            restored_note = connection.execute(
                sa.text(
                    """
                    SELECT revision_number, supersedes_note_id,
                           supersedes_revision_number, visibility, body,
                           author_user_id, created_at
                    FROM notes WHERE note_key = :note_key
                    """
                ),
                {"note_key": note_key},
            ).one()
            assert tuple(restored_note) == (
                1,
                None,
                None,
                "internal",
                "preserved repair note",
                author_user_id,
                created_at,
            )
            restored_tables = frozenset(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = DATABASE()
                          AND table_name IN (
                               'note_threads',
                               'publication_command_results',
                               'review_operation_tokens',
                               'review_operation_results',
                               'version_review_events'
                          )
                        """
                    )
                )
            )
            assert restored_tables == {
                "note_threads",
                "publication_command_results",
                "review_operation_tokens",
                "review_operation_results",
                "version_review_events",
            }
    finally:
        engine.dispose()
        command.upgrade(alembic_config, _HEAD_REVISION)
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_publication_downgrade_compatibility_index_survives_stepwise_replay(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.upgrade(alembic_config, _HEAD_REVISION)
    command.downgrade(alembic_config, "0015")
    engine = _create_migration_test_engine(mysql_settings)
    try:
        with engine.begin() as connection:
            _drop_publication_compatibility_index_if_present(connection)
            connection.execute(
                sa.text(
                    "CREATE INDEX `fk_dataset_publications_version` "
                    "ON `dataset_publications` (`dataset_id`, `version_id`)"
                )
            )
            assert (
                _publication_compatibility_index_signature(connection)
                == _EXPECTED_PUBLICATION_COMPATIBILITY_INDEX
            )

        # Simulate retry after the index DDL committed but the Alembic revision
        # marker did not: 0016 must accept the exact pre-existing definition.
        command.upgrade(alembic_config, "0016")
        assert _current_revision(mysql_settings) == "0016"
        with engine.connect() as connection:
            assert (
                _publication_compatibility_index_signature(connection)
                == _EXPECTED_PUBLICATION_COMPATIBILITY_INDEX
            )
            assert (
                _issue_review_compatibility_index_signature(connection)
                == _EXPECTED_ISSUE_REVIEW_COMPATIBILITY_INDEX
            )

        command.downgrade(alembic_config, "0015")
        assert _current_revision(mysql_settings) == "0015"
        with engine.connect() as connection:
            assert (
                _publication_compatibility_index_signature(connection)
                == _EXPECTED_PUBLICATION_COMPATIBILITY_INDEX
            )
            assert (
                _issue_review_compatibility_index_signature(connection)
                == _EXPECTED_ISSUE_REVIEW_COMPATIBILITY_INDEX
            )

        command.upgrade(alembic_config, "0016")
        assert _current_revision(mysql_settings) == "0016"
    finally:
        engine.dispose()
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_publication_downgrade_compatibility_index_rejects_wrong_definition(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.upgrade(alembic_config, _HEAD_REVISION)
    command.downgrade(alembic_config, "0015")
    engine = _create_migration_test_engine(mysql_settings)
    try:
        with engine.begin() as connection:
            _drop_publication_compatibility_index_if_present(connection)
            connection.execute(
                sa.text(
                    "CREATE INDEX `fk_dataset_publications_version` "
                    "ON `dataset_publications` (`version_id`)"
                )
            )

        with pytest.raises(RuntimeError, match="incompatible dataset publication"):
            command.upgrade(alembic_config, "0016")
        assert _current_revision(mysql_settings) == "0015"
        with engine.connect() as connection:
            assert _publication_compatibility_index_signature(connection) == (
                (1, "version_id", 1, None, "A", "BTREE"),
            )
    finally:
        with engine.begin() as connection:
            _drop_publication_compatibility_index_if_present(connection)
        engine.dispose()
        command.downgrade(alembic_config, "0015")
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_seeded_roles_site_configuration_utf8mb4_and_utc(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.upgrade(alembic_config, _HEAD_REVISION)
    engine = _create_migration_test_engine(mysql_settings)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                assert (
                    connection.scalar(sa.text("SELECT @@session.time_zone")) == "+00:00"
                )
                assert (
                    connection.scalar(sa.text("SELECT @@character_set_database"))
                    == "utf8mb4"
                )
                assert connection.execute(
                    sa.text("SELECT code FROM roles ORDER BY id")
                ).scalars().all() == ["admin", "data_manager", "viewer"]
                site = connection.execute(
                    sa.text(
                        """
                        SELECT s.code, c.source_timezone, c.reporting_timezone,
                               c.currency_code
                        FROM sites AS s
                        JOIN site_current_configs AS current
                          ON current.site_id = s.id
                        JOIN site_config_versions AS c
                          ON c.id = current.current_config_version_id
                        WHERE s.code = 'amazon_us'
                        """
                    )
                ).one()
                assert tuple(site) == (
                    "amazon_us",
                    "America/Los_Angeles",
                    "America/Los_Angeles",
                    "USD",
                )

                display_name = f"四字节字符😀-{uuid4().hex}"
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO users (
                            username_normalized, display_name, password_hash, status
                        ) VALUES (:username, :display_name, :password_hash, 'active')
                        """
                    ),
                    {
                        "username": f"unicode-{uuid4().hex}",
                        "display_name": display_name,
                        "password_hash": "$argon2id$test-only",
                    },
                )
                assert (
                    connection.scalar(
                        sa.text(
                            "SELECT display_name FROM users WHERE display_name = :value"
                        ),
                        {"value": display_name},
                    )
                    == display_name
                )
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_raw_file_integrity_schema_and_lease_lookup_indexes(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, _HEAD_REVISION)
    inspector = sa.inspect(mysql_engine)

    columns = {
        column["name"]: column
        for column in inspector.get_columns("raw_file_integrity_statuses")
    }
    assert set(columns) == {
        "raw_file_id",
        "status",
        "is_blocking",
        "first_detected_at",
        "last_checked_at",
        "resolved_at",
    }
    assert columns["is_blocking"]["computed"]["persisted"] is True

    indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes("file_ingest_leases")
    }
    assert indexes["ix_file_ingest_leases_storage_key_status_expires"] == (
        "storage_key",
        "status",
        "expires_at",
    )
    assert indexes["ix_file_ingest_leases_sha256_status_expires"] == (
        "sha256",
        "status",
        "expires_at",
    )


def test_raw_file_integrity_status_supports_idempotent_detection_and_recovery(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, _HEAD_REVISION)
    checked_at = datetime.now(UTC).replace(tzinfo=None)

    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status
                    ) VALUES (
                        :username, 'Integrity Migration Test',
                        '$argon2id$test', 'active'
                    )
                    """
                ),
                {"username": f"integrity-{uuid4().hex}"},
            )
            assert user.lastrowid is not None
            raw_file = connection.execute(
                sa.text(
                    """
                    INSERT INTO raw_files (
                        sha256, storage_key, original_filename,
                        size_bytes, uploaded_by_user_id
                    ) VALUES (
                        :sha256, :storage_key, 'integrity.csv', 1, :user_id
                    )
                    """
                ),
                {
                    "sha256": uuid4().bytes + uuid4().bytes,
                    "storage_key": f"sha256/test/{uuid4().hex}",
                    "user_id": user.lastrowid,
                },
            )
            assert raw_file.lastrowid is not None

            upsert = sa.text(
                """
                INSERT INTO raw_file_integrity_statuses (
                    raw_file_id, status, first_detected_at, last_checked_at
                ) VALUES (
                    :raw_file_id, 'missing', :detected_at, :checked_at
                ) AS incoming
                ON DUPLICATE KEY UPDATE
                    status = incoming.status,
                    first_detected_at = COALESCE(
                        raw_file_integrity_statuses.first_detected_at,
                        incoming.first_detected_at
                    ),
                    last_checked_at = incoming.last_checked_at,
                    resolved_at = NULL
                """
            )
            connection.execute(
                upsert,
                {
                    "raw_file_id": raw_file.lastrowid,
                    "detected_at": checked_at,
                    "checked_at": checked_at,
                },
            )
            connection.execute(
                upsert,
                {
                    "raw_file_id": raw_file.lastrowid,
                    "detected_at": checked_at,
                    "checked_at": checked_at + timedelta(seconds=1),
                },
            )
            detected = connection.execute(
                sa.text(
                    """
                    SELECT status, is_blocking, first_detected_at,
                           last_checked_at, resolved_at
                    FROM raw_file_integrity_statuses
                    WHERE raw_file_id = :raw_file_id
                    """
                ),
                {"raw_file_id": raw_file.lastrowid},
            ).one()
            assert tuple(detected) == (
                "missing",
                1,
                checked_at,
                checked_at + timedelta(seconds=1),
                None,
            )

            resolved_at = checked_at + timedelta(seconds=2)
            connection.execute(
                sa.text(
                    """
                    UPDATE raw_file_integrity_statuses
                    SET status = 'available', last_checked_at = :resolved_at,
                        resolved_at = :resolved_at
                    WHERE raw_file_id = :raw_file_id
                    """
                ),
                {"raw_file_id": raw_file.lastrowid, "resolved_at": resolved_at},
            )
            recovered = connection.execute(
                sa.text(
                    """
                    SELECT status, is_blocking, resolved_at
                    FROM raw_file_integrity_statuses
                    WHERE raw_file_id = :raw_file_id
                    """
                ),
                {"raw_file_id": raw_file.lastrowid},
            ).one()
            assert tuple(recovered) == ("available", 0, resolved_at)

            savepoint = connection.begin_nested()
            try:
                with pytest.raises(DBAPIError) as exc_info:
                    connection.execute(
                        sa.text(
                            """
                            UPDATE raw_file_integrity_statuses
                            SET status = 'hash_mismatch', resolved_at = NULL,
                                first_detected_at = NULL
                            WHERE raw_file_id = :raw_file_id
                            """
                        ),
                        {"raw_file_id": raw_file.lastrowid},
                    )
                assert getattr(exc_info.value.orig, "args", (None,))[0] == 3819
            finally:
                savepoint.rollback()
        finally:
            transaction.rollback()


def test_stage_four_schema_exposes_confirmation_and_success_contracts(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, _HEAD_REVISION)
    inspector = sa.inspect(mysql_engine)

    batch_columns = {
        column["name"]: column for column in inspector.get_columns("import_batches")
    }
    assert {
        "site_id",
        "detected_report_type",
        "detector_version",
        "detection_summary",
        "detected_at",
        "confirmed_report_type",
        "confirmation_revision",
        "confirmed_by_user_id",
        "confirmed_at",
        "processing_token",
        "processing_operation_digest",
        "processing_started_at",
    } <= batch_columns.keys()
    assert batch_columns["site_id"]["nullable"] is False
    batch_unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("import_batches")
    }
    assert "uq_import_batches_processing_token" in batch_unique_constraints

    attempt_columns = {
        column["name"]: column for column in inspector.get_columns("parse_attempts")
    }
    assert {
        "site_id",
        "processing_token",
        "operation_digest",
        "report_type",
        "confirmation_revision",
    } <= attempt_columns.keys()
    assert attempt_columns["processing_token"]["nullable"] is False
    assert attempt_columns["operation_digest"]["nullable"] is False
    attempt_unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("parse_attempts")
    }
    assert "uq_parse_attempts_processing_token" in attempt_unique_constraints

    for table_name, prefix in (
        ("parse_operation_tokens", "parse_operation_tokens"),
        ("report_date_operation_tokens", "report_date_operation_tokens"),
    ):
        token_columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        assert set(token_columns) == {
            "operation_token",
            "batch_id",
            "operation_digest",
            "registered_at",
        }
        assert all(not column["nullable"] for column in token_columns.values())
        operation_token_type = token_columns["operation_token"]["type"]
        operation_digest_type = token_columns["operation_digest"]["type"]
        batch_id_type = token_columns["batch_id"]["type"]
        registered_at_type = token_columns["registered_at"]["type"]
        assert isinstance(operation_token_type, mysql.BINARY)
        assert isinstance(operation_digest_type, mysql.BINARY)
        assert isinstance(batch_id_type, mysql.BIGINT)
        assert isinstance(registered_at_type, mysql.DATETIME)
        assert operation_token_type.length == 16
        assert operation_digest_type.length == 32
        assert batch_id_type.unsigned is True
        assert registered_at_type.fsp == 6
        assert inspector.get_pk_constraint(table_name)["constrained_columns"] == [
            "operation_token"
        ]
        token_uniques = {
            constraint["name"]: constraint["column_names"]
            for constraint in inspector.get_unique_constraints(table_name)
        }
        assert token_uniques[f"uq_{prefix}_identity"] == [
            "operation_token",
            "batch_id",
            "operation_digest",
        ]
        token_foreign_keys = {
            constraint["name"]: constraint
            for constraint in inspector.get_foreign_keys(table_name)
        }
        batch_foreign_key = token_foreign_keys[f"fk_{prefix}_batch"]
        assert batch_foreign_key["constrained_columns"] == ["batch_id"]
        assert batch_foreign_key["referred_table"] == "import_batches"
        assert batch_foreign_key["referred_columns"] == ["id"]

    baseline_columns = {
        column["name"] for column in inspector.get_columns("parse_baselines")
    }
    assert "attempt_status" in baseline_columns

    for table_name in (
        "business_parse_baseline_rows",
        "business_version_base_rows",
        "business_report_rows",
    ):
        column_names = {column["name"] for column in inspector.get_columns(table_name)}
        assert "conversion_rate_total" in column_names
        assert "session_percentage_total" not in column_names

    batch_foreign_keys = {
        constraint["name"]
        for constraint in inspector.get_foreign_keys("import_batches")
    }
    assert {
        "fk_import_batches_current_parse_baseline",
        "fk_import_batches_site_config_owner",
        "fk_import_batches_confirmed_by",
        "fk_import_batches_parse_operation_token",
    } <= batch_foreign_keys
    batch_foreign_key_details = {
        constraint["name"]: constraint
        for constraint in inspector.get_foreign_keys("import_batches")
    }
    batch_token_foreign_key = batch_foreign_key_details[
        "fk_import_batches_parse_operation_token"
    ]
    assert batch_token_foreign_key["constrained_columns"] == [
        "processing_token",
        "id",
        "processing_operation_digest",
    ]
    assert batch_token_foreign_key["referred_table"] == "parse_operation_tokens"
    assert batch_token_foreign_key["referred_columns"] == [
        "operation_token",
        "batch_id",
        "operation_digest",
    ]
    attempt_foreign_keys = {
        constraint["name"]: constraint
        for constraint in inspector.get_foreign_keys("parse_attempts")
    }
    attempt_token_foreign_key = attempt_foreign_keys[
        "fk_parse_attempts_operation_token"
    ]
    assert attempt_token_foreign_key["constrained_columns"] == [
        "processing_token",
        "batch_id",
        "operation_digest",
    ]
    assert attempt_token_foreign_key["referred_table"] == "parse_operation_tokens"
    assert attempt_token_foreign_key["referred_columns"] == [
        "operation_token",
        "batch_id",
        "operation_digest",
    ]
    baseline_foreign_keys = {
        constraint["name"]
        for constraint in inspector.get_foreign_keys("parse_baselines")
    }
    assert "fk_parse_baselines_successful_attempt" in baseline_foreign_keys


def test_stage_four_upgrade_backfills_legacy_parse_ownership_and_preserves_rename(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.downgrade(alembic_config, "0006")
    engine = _create_migration_test_engine(mysql_settings)
    legacy_rate = Decimal("0.159000000")
    try:
        with engine.begin() as connection:
            user = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status
                    ) VALUES (
                        :username, 'Stage Four Migration', '$argon2id$test', 'active'
                    )
                    """
                ),
                {"username": f"stage-four-{uuid4().hex}"},
            )
            assert user.lastrowid is not None
            user_id = int(user.lastrowid)
            raw_file = connection.execute(
                sa.text(
                    """
                    INSERT INTO raw_files (
                        sha256, storage_key, original_filename,
                        size_bytes, uploaded_by_user_id
                    ) VALUES (
                        :digest, :storage_key, 'legacy.csv', 1, :user_id
                    )
                    """
                ),
                {
                    "digest": uuid4().bytes + uuid4().bytes,
                    "storage_key": f"sha256/legacy/{uuid4().hex}",
                    "user_id": user_id,
                },
            )
            assert raw_file.lastrowid is not None
            batch = connection.execute(
                sa.text(
                    """
                    INSERT INTO import_batches (
                        raw_file_id, site_config_version_id, report_type,
                        report_date, status, created_by_user_id
                    ) VALUES (
                        :raw_file_id, 1, 'business_report', :report_date,
                        'staged', :user_id
                    )
                    """
                ),
                {
                    "raw_file_id": raw_file.lastrowid,
                    "report_date": date(2026, 8, 7),
                    "user_id": user_id,
                },
            )
            assert batch.lastrowid is not None
            batch_id = int(batch.lastrowid)
            unparsed_raw_file = connection.execute(
                sa.text(
                    """
                    INSERT INTO raw_files (
                        sha256, storage_key, original_filename,
                        size_bytes, uploaded_by_user_id
                    ) VALUES (
                        :digest, :storage_key, 'legacy-unparsed.csv', 1, :user_id
                    )
                    """
                ),
                {
                    "digest": uuid4().bytes + uuid4().bytes,
                    "storage_key": f"sha256/legacy-unparsed/{uuid4().hex}",
                    "user_id": user_id,
                },
            )
            assert unparsed_raw_file.lastrowid is not None
            unparsed_batch = connection.execute(
                sa.text(
                    """
                    INSERT INTO import_batches (
                        raw_file_id, site_config_version_id, report_type,
                        report_date, status, source_row_count,
                        created_by_user_id
                    ) VALUES (
                        :raw_file_id, 1, 'return_report', :report_date,
                        'staged', 7, :user_id
                    )
                    """
                ),
                {
                    "raw_file_id": unparsed_raw_file.lastrowid,
                    "report_date": date(2026, 8, 8),
                    "user_id": user_id,
                },
            )
            assert unparsed_batch.lastrowid is not None
            unparsed_batch_id = int(unparsed_batch.lastrowid)
            attempt = connection.execute(
                sa.text(
                    """
                    INSERT INTO parse_attempts (
                        batch_id, site_config_version_id, attempt_number,
                        parser_version, ruleset_version, status,
                        source_row_count, created_by_user_id
                    ) VALUES (
                        :batch_id, 1, 1, 'legacy-parser', 'legacy-rules',
                        'succeeded', 1, :user_id
                    )
                    """
                ),
                {"batch_id": batch_id, "user_id": user_id},
            )
            assert attempt.lastrowid is not None
            attempt_id = int(attempt.lastrowid)
            source_row = connection.execute(
                sa.text(
                    """
                    INSERT INTO parsed_source_rows (
                        parse_attempt_id, source_row_number,
                        decoded_fields, row_digest
                    ) VALUES (:attempt_id, 1, :fields, :digest)
                    """
                ),
                {
                    "attempt_id": attempt_id,
                    "fields": "{}",
                    "digest": bytes.fromhex("11" * 32),
                },
            )
            assert source_row.lastrowid is not None
            baseline = connection.execute(
                sa.text(
                    """
                    INSERT INTO parse_baselines (
                        parse_attempt_id, report_type, parser_version,
                        ruleset_version, data_digest, row_count, totals_json
                    ) VALUES (
                        :attempt_id, 'business_report', 'legacy-parser',
                        'legacy-rules', :digest, 1, :totals
                    )
                    """
                ),
                {
                    "attempt_id": attempt_id,
                    "digest": bytes.fromhex("22" * 32),
                    "totals": "{}",
                },
            )
            assert baseline.lastrowid is not None
            baseline_row = connection.execute(
                sa.text(
                    """
                    INSERT INTO parse_baseline_rows (
                        parse_baseline_id, parse_attempt_id,
                        parsed_source_row_id, report_type,
                        row_ordinal, row_digest
                    ) VALUES (
                        :baseline_id, :attempt_id, :source_row_id,
                        'business_report', 1, :digest
                    )
                    """
                ),
                {
                    "baseline_id": baseline.lastrowid,
                    "attempt_id": attempt_id,
                    "source_row_id": source_row.lastrowid,
                    "digest": bytes.fromhex("33" * 32),
                },
            )
            assert baseline_row.lastrowid is not None
            connection.execute(
                sa.text(
                    """
                    INSERT INTO business_parse_baseline_rows (
                        parse_baseline_row_id, parse_baseline_id,
                        session_percentage_total
                    ) VALUES (:row_id, :baseline_id, :legacy_rate)
                    """
                ),
                {
                    "row_id": baseline_row.lastrowid,
                    "baseline_id": baseline.lastrowid,
                    "legacy_rate": legacy_rate,
                },
            )
            connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET current_successful_parse_attempt_id = :attempt_id
                    WHERE id = :batch_id
                    """
                ),
                {"attempt_id": attempt_id, "batch_id": batch_id},
            )

        command.upgrade(alembic_config, "0007")
        with engine.connect() as connection:
            batch_row = connection.execute(
                sa.text(
                    """
                    SELECT site_id, report_type, confirmed_report_type,
                           confirmation_revision, confirmed_by_user_id,
                           processing_token, processing_started_at
                    FROM import_batches WHERE id = :batch_id
                    """
                ),
                {"batch_id": batch_id},
            ).one()
            assert tuple(batch_row) == (
                1,
                "business_report",
                "business_report",
                1,
                user_id,
                None,
                None,
            )
            unparsed_batch_row = connection.execute(
                sa.text(
                    """
                    SELECT site_id, report_type, confirmed_report_type,
                           confirmation_revision, source_row_count
                    FROM import_batches WHERE id = :batch_id
                    """
                ),
                {"batch_id": unparsed_batch_id},
            ).one()
            assert tuple(unparsed_batch_row) == (
                1,
                None,
                "return_report",
                1,
                None,
            )
            attempt_row = connection.execute(
                sa.text(
                    """
                    SELECT site_id, report_type, confirmation_revision,
                           processing_token, operation_digest,
                           status, started_at, completed_at
                    FROM parse_attempts WHERE id = :attempt_id
                    """
                ),
                {"attempt_id": attempt_id},
            ).one()
            assert tuple(attempt_row[:3]) == (
                1,
                "business_report",
                1,
            )
            assert bytes(attempt_row.processing_token) == attempt_id.to_bytes(
                16,
                byteorder="big",
            )
            assert (
                bytes(attempt_row.operation_digest)
                == hashlib.sha256(
                    f"legacy-parse-attempt:{attempt_id}".encode("ascii")
                ).digest()
            )
            assert attempt_row.status == "succeeded"
            assert attempt_row.completed_at is not None
            token_row = connection.execute(
                sa.text(
                    """
                    SELECT operation_token, batch_id,
                           operation_digest, registered_at
                    FROM parse_operation_tokens
                    WHERE operation_token = :operation_token
                    """
                ),
                {"operation_token": attempt_row.processing_token},
            ).one()
            assert bytes(token_row.operation_token) == bytes(
                attempt_row.processing_token
            )
            assert token_row.batch_id == batch_id
            assert bytes(token_row.operation_digest) == bytes(
                attempt_row.operation_digest
            )
            assert token_row.registered_at == attempt_row.started_at
            assert (
                connection.scalar(
                    sa.text("SELECT COUNT(*) FROM report_date_operation_tokens")
                )
                == 0
            )
            assert (
                connection.scalar(
                    sa.text(
                        """
                    SELECT attempt_status FROM parse_baselines
                    WHERE parse_attempt_id = :attempt_id
                    """
                    ),
                    {"attempt_id": attempt_id},
                )
                == "succeeded"
            )
            assert (
                connection.scalar(
                    sa.text(
                        """
                    SELECT conversion_rate_total
                    FROM business_parse_baseline_rows
                    WHERE parse_baseline_row_id = :row_id
                    """
                    ),
                    {"row_id": baseline_row.lastrowid},
                )
                == legacy_rate
            )

        command.downgrade(alembic_config, "0006")
        downgraded_inspector = sa.inspect(engine)
        assert "processing_token" not in {
            column["name"]
            for column in downgraded_inspector.get_columns("parse_attempts")
        }
        assert "operation_digest" not in {
            column["name"]
            for column in downgraded_inspector.get_columns("parse_attempts")
        }
        assert "parse_operation_tokens" not in downgraded_inspector.get_table_names()
        assert (
            "report_date_operation_tokens" not in downgraded_inspector.get_table_names()
        )
        for table_name in (
            "business_parse_baseline_rows",
            "business_version_base_rows",
            "business_report_rows",
        ):
            column_names = {
                column["name"]
                for column in downgraded_inspector.get_columns(table_name)
            }
            assert "session_percentage_total" in column_names
            assert "conversion_rate_total" not in column_names
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT report_type FROM import_batches WHERE id = :batch_id"
                    ),
                    {"batch_id": unparsed_batch_id},
                )
                == "return_report"
            )
            assert (
                connection.scalar(
                    sa.text(
                        """
                    SELECT session_percentage_total
                    FROM business_parse_baseline_rows
                    WHERE parse_baseline_row_id = :row_id
                    """
                    ),
                    {"row_id": baseline_row.lastrowid},
                )
                == legacy_rate
            )
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_stage_four_upgrade_preflight_stops_before_nontransactional_ddl(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.downgrade(alembic_config, "0006")
    engine = _create_migration_test_engine(mysql_settings)
    try:
        with engine.begin() as connection:
            user = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status
                    ) VALUES (
                        :username, 'Preflight Test', '$argon2id$test', 'active'
                    )
                    """
                ),
                {"username": f"preflight-{uuid4().hex}"},
            )
            assert user.lastrowid is not None
            raw_file = connection.execute(
                sa.text(
                    """
                    INSERT INTO raw_files (
                        sha256, storage_key, original_filename,
                        size_bytes, uploaded_by_user_id
                    ) VALUES (:digest, :key, 'processing.csv', 1, :user_id)
                    """
                ),
                {
                    "digest": uuid4().bytes + uuid4().bytes,
                    "key": f"sha256/preflight/{uuid4().hex}",
                    "user_id": user.lastrowid,
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO import_batches (
                        raw_file_id, site_config_version_id, report_type,
                        report_date, status, created_by_user_id
                    ) VALUES (
                        :raw_file_id, 1, 'business_report', '2026-08-07',
                        'processing', :user_id
                    )
                    """
                ),
                {"raw_file_id": raw_file.lastrowid, "user_id": user.lastrowid},
            )

        with pytest.raises(RuntimeError, match="processing"):
            command.upgrade(alembic_config, "0007")
        assert _current_revision(mysql_settings) == "0006"
        assert "site_id" not in {
            column["name"]
            for column in sa.inspect(engine).get_columns("import_batches")
        }
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_stage_four_downgrade_refuses_to_invent_unconfirmed_metadata(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.downgrade(alembic_config, "0007")
    engine = _create_migration_test_engine(mysql_settings)
    user_id: int | None = None
    raw_file_id: int | None = None
    try:
        with engine.begin() as connection:
            user = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status
                    ) VALUES (
                        :username, 'Downgrade Preflight', '$argon2id$test', 'active'
                    )
                    """
                ),
                {"username": f"downgrade-preflight-{uuid4().hex}"},
            )
            assert user.lastrowid is not None
            user_id = int(user.lastrowid)
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
                    "user_id": user.lastrowid,
                },
            )
            assert raw_file.lastrowid is not None
            raw_file_id = int(raw_file.lastrowid)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO import_batches (
                        raw_file_id, site_id, site_config_version_id,
                        report_type, report_date, status, created_by_user_id
                    ) VALUES (
                        :raw_file_id, 1, 1, NULL, NULL, 'uploaded', :user_id
                    )
                    """
                ),
                {"raw_file_id": raw_file.lastrowid, "user_id": user.lastrowid},
            )

        with pytest.raises(RuntimeError, match="downgrade"):
            command.downgrade(alembic_config, "0006")
        assert _current_revision(mysql_settings) == "0007"
        assert "confirmed_report_type" in {
            column["name"]
            for column in sa.inspect(engine).get_columns("import_batches")
        }
    finally:
        if user_id is not None and raw_file_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "DELETE FROM import_batches WHERE created_by_user_id = :user_id"
                    ),
                    {"user_id": user_id},
                )
                connection.execute(
                    sa.text("DELETE FROM raw_files WHERE id = :raw_file_id"),
                    {"raw_file_id": raw_file_id},
                )
                connection.execute(
                    sa.text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )
        engine.dispose()
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_stage_four_downgrade_refuses_to_drop_an_active_parse_lease(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.downgrade(alembic_config, "0007")
    engine = _create_migration_test_engine(mysql_settings)
    user_id: int | None = None
    raw_file_id: int | None = None
    try:
        with engine.begin() as connection:
            user = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status
                    ) VALUES (
                        :username, 'Active Parse Downgrade',
                        '$argon2id$test', 'active'
                    )
                    """
                ),
                {"username": f"active-downgrade-{uuid4().hex}"},
            )
            assert user.lastrowid is not None
            user_id = int(user.lastrowid)
            raw_file = connection.execute(
                sa.text(
                    """
                    INSERT INTO raw_files (
                        sha256, storage_key, original_filename,
                        size_bytes, uploaded_by_user_id
                    ) VALUES (:digest, :key, 'active.csv', 1, :user_id)
                    """
                ),
                {
                    "digest": uuid4().bytes + uuid4().bytes,
                    "key": f"sha256/active-downgrade/{uuid4().hex}",
                    "user_id": user_id,
                },
            )
            assert raw_file.lastrowid is not None
            raw_file_id = int(raw_file.lastrowid)
            processing_token = uuid4().bytes
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
                        :raw_file_id, 1, 1, NULL, '2026-08-07', 'uploaded',
                        'business_report', 1, :user_id, CURRENT_TIMESTAMP(6),
                        :user_id
                    )
                    """
                ),
                {
                    "raw_file_id": raw_file_id,
                    "user_id": user_id,
                },
            )
            assert batch.lastrowid is not None
            batch_id = int(batch.lastrowid)
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
                    "processing_token": processing_token,
                    "operation_digest": processing_token * 2,
                },
            )
            connection.execute(
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
                    "batch_id": batch_id,
                    "processing_token": processing_token,
                    "operation_digest": processing_token * 2,
                },
            )

        with pytest.raises(RuntimeError, match="active parse lease"):
            command.downgrade(alembic_config, "0006")
        assert _current_revision(mysql_settings) == "0007"
        assert "processing_operation_digest" in {
            column["name"]
            for column in sa.inspect(engine).get_columns("import_batches")
        }
    finally:
        if user_id is not None and raw_file_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        UPDATE import_batches
                        SET status = 'uploaded',
                            processing_token = NULL,
                            processing_operation_digest = NULL,
                            processing_started_at = NULL
                        WHERE created_by_user_id = :user_id
                        """
                    ),
                    {"user_id": user_id},
                )
                connection.execute(
                    sa.text(
                        """
                        DELETE FROM parse_operation_tokens
                        WHERE batch_id IN (
                            SELECT id FROM import_batches
                            WHERE created_by_user_id = :user_id
                        )
                        """
                    ),
                    {"user_id": user_id},
                )
                connection.execute(
                    sa.text(
                        "DELETE FROM import_batches WHERE created_by_user_id = :user_id"
                    ),
                    {"user_id": user_id},
                )
                connection.execute(
                    sa.text("DELETE FROM raw_files WHERE id = :raw_file_id"),
                    {"raw_file_id": raw_file_id},
                )
                connection.execute(
                    sa.text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )
        engine.dispose()
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, _HEAD_REVISION)


def test_stage_four_downgrade_rejects_lossy_failed_attempt_before_ddl(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.downgrade(alembic_config, "0007")
    engine = _create_migration_test_engine(mysql_settings)
    try:
        with engine.begin() as connection:
            batch_id, attempt_id = _insert_stage_four_type_roundtrip_case(
                connection,
                attempt_status="failed",
            )

        before = sa.inspect(engine)
        before_batch_foreign_keys = {
            constraint["name"]
            for constraint in before.get_foreign_keys("import_batches")
        }
        before_attempt_columns = {
            column["name"] for column in before.get_columns("parse_attempts")
        }
        before_business_columns = {
            column["name"]
            for column in before.get_columns("business_parse_baseline_rows")
        }

        with pytest.raises(RuntimeError, match="failed parse attempt"):
            command.downgrade(alembic_config, "0006")

        assert _current_revision(mysql_settings) == "0007"
        after = sa.inspect(engine)
        assert {
            constraint["name"]
            for constraint in after.get_foreign_keys("import_batches")
        } == before_batch_foreign_keys
        assert {
            column["name"] for column in after.get_columns("parse_attempts")
        } == before_attempt_columns
        assert {
            column["name"]
            for column in after.get_columns("business_parse_baseline_rows")
        } == before_business_columns
        assert "fk_import_batches_current_parse_baseline" in (before_batch_foreign_keys)
        assert "report_type" in before_attempt_columns
        assert "conversion_rate_total" in before_business_columns
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT report_type FROM parse_attempts WHERE id = :attempt_id"
                    ),
                    {"attempt_id": attempt_id},
                )
                == "return_report"
            )

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE parse_attempts
                    SET report_type = 'business_report'
                    WHERE id = :attempt_id
                    """
                ),
                {"attempt_id": attempt_id},
            )

        command.downgrade(alembic_config, "0006")
        assert _current_revision(mysql_settings) == "0006"
        assert "report_type" not in {
            column["name"]
            for column in sa.inspect(engine).get_columns("parse_attempts")
        }
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT report_type FROM import_batches WHERE id = :batch_id"
                    ),
                    {"batch_id": batch_id},
                )
                == "business_report"
            )

        command.upgrade(alembic_config, "0007")
        assert _current_revision(mysql_settings) == "0007"
        with engine.connect() as connection:
            repaired_attempt = connection.execute(
                sa.text(
                    """
                    SELECT report_type, status
                    FROM parse_attempts WHERE id = :attempt_id
                    """
                ),
                {"attempt_id": attempt_id},
            ).one()
        assert tuple(repaired_attempt) == ("business_report", "failed")
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, _HEAD_REVISION)
    assert _current_revision(mysql_settings) == _HEAD_REVISION


def test_stage_four_successful_attempt_type_roundtrips_through_baseline(
    alembic_config: Config,
    mysql_settings: DatabaseSettings,
) -> None:
    command.downgrade(alembic_config, "0007")
    engine = _create_migration_test_engine(mysql_settings)
    try:
        with engine.begin() as connection:
            batch_id, attempt_id = _insert_stage_four_type_roundtrip_case(
                connection,
                attempt_status="succeeded",
            )

        command.downgrade(alembic_config, "0006")
        assert _current_revision(mysql_settings) == "0006"
        assert "report_type" not in {
            column["name"]
            for column in sa.inspect(engine).get_columns("parse_attempts")
        }
        with engine.connect() as connection:
            downgraded_types = connection.execute(
                sa.text(
                    """
                    SELECT batches.report_type, baselines.report_type
                    FROM import_batches AS batches
                    INNER JOIN parse_attempts AS attempts
                        ON attempts.batch_id = batches.id
                    INNER JOIN parse_baselines AS baselines
                        ON baselines.parse_attempt_id = attempts.id
                    WHERE batches.id = :batch_id
                      AND attempts.id = :attempt_id
                    """
                ),
                {"batch_id": batch_id, "attempt_id": attempt_id},
            ).one()
        assert tuple(downgraded_types) == (
            "business_report",
            "return_report",
        )

        command.upgrade(alembic_config, "0007")
        assert _current_revision(mysql_settings) == "0007"
        with engine.connect() as connection:
            upgraded_types = connection.execute(
                sa.text(
                    """
                    SELECT attempts.report_type, baselines.report_type,
                           baselines.attempt_status
                    FROM parse_attempts AS attempts
                    INNER JOIN parse_baselines AS baselines
                        ON baselines.parse_attempt_id = attempts.id
                    WHERE attempts.id = :attempt_id
                    """
                ),
                {"attempt_id": attempt_id},
            ).one()
        assert tuple(upgraded_types) == (
            "return_report",
            "return_report",
            "succeeded",
        )
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, _HEAD_REVISION)
    assert _current_revision(mysql_settings) == _HEAD_REVISION
