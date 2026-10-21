from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.mysql

_DOWNGRADE_RESTORE_INDEXES = {
    "version_base_snapshot_members": {
        "ix_vbsm_parent_version_restore",
        "ix_vbsm_parse_baseline_restore",
    },
    "dataset_drafts": {"ix_dataset_drafts_dataset_version_restore"},
}


@pytest.fixture(name="mysql_engine")
def _historical_schema_engine(historical_mysql_engine: Engine) -> Engine:
    return historical_mysql_engine


def _insert_user(connection: Connection) -> int:
    result = connection.execute(
        sa.text(
            """
            INSERT INTO users (
                username_normalized, display_name, password_hash, status
            ) VALUES (
                :username, 'Stage Five Schema', '$argon2id$test', 'active'
            )
            """
        ),
        {"username": f"stage-five-schema-{uuid4().hex}"},
    )
    assert result.lastrowid is not None
    return int(result.lastrowid)


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
    status: str = "draft",
    sealed: bool = False,
) -> int:
    result = connection.execute(
        sa.text(
            """
            INSERT INTO dataset_versions (
                dataset_id, report_type, version_no, status,
                ruleset_version, created_by, sealed_at
            ) VALUES (
                :dataset_id, :report_type, :version_no, :status,
                'stage-five-v1', :user_id,
                IF(:sealed, CURRENT_TIMESTAMP(6), NULL)
            )
            """
        ),
        {
            "dataset_id": dataset_id,
            "report_type": report_type,
            "version_no": version_no,
            "status": status,
            "user_id": user_id,
            "sealed": sealed,
        },
    )
    assert result.lastrowid is not None
    return int(result.lastrowid)


def _assert_rejected(
    connection: Connection,
    statement: str,
    parameters: dict[str, object],
) -> None:
    savepoint = connection.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            connection.execute(sa.text(statement), parameters)
    finally:
        savepoint.rollback()


@pytest.fixture
def stage_five_revision(alembic_config: Config) -> Iterator[None]:
    command.upgrade(alembic_config, "0028")
    try:
        command.downgrade(alembic_config, "0008")
        yield
    finally:
        command.upgrade(alembic_config, "0028")


def test_stage_five_schema_exposes_hardened_drafts_and_immutable_ledgers(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    inspector = sa.inspect(mysql_engine)

    assert {
        "daily_dataset_locks",
        "draft_operation_tokens",
        "draft_operation_results",
        "draft_disposition_events",
    } <= set(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("dataset_drafts")} >= {
        "dataset_id",
        "version_id",
        "version_status",
    }
    assert {
        column["name"] for column in inspector.get_columns("version_parent_versions")
    } >= {"child_version_id", "parent_version_id", "report_type"}
    assert {
        column["name"]
        for column in inspector.get_columns("version_base_snapshot_members")
    } >= {"snapshot_id", "report_type"}
    base_columns = {
        column["name"]: column for column in inspector.get_columns("version_base_rows")
    }
    assert base_columns["row_state"]["nullable"] is False
    assert base_columns["row_state"]["default"] == "'active'"

    lock_columns = {
        column["name"]: column
        for column in inspector.get_columns("daily_dataset_locks")
    }
    assert set(lock_columns) == {"dataset_id", "lock_revision"}
    assert all(not column["nullable"] for column in lock_columns.values())
    assert str(lock_columns["lock_revision"]["default"]).strip("'") == "0"
    assert inspector.get_pk_constraint("daily_dataset_locks")[
        "constrained_columns"
    ] == ["dataset_id"]
    lock_foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("daily_dataset_locks")
    }
    dataset_lock = lock_foreign_keys["fk_daily_dataset_locks_dataset"]
    assert dataset_lock["constrained_columns"] == ["dataset_id"]
    assert dataset_lock["referred_table"] == "daily_datasets"
    assert dataset_lock["referred_columns"] == ["id"]

    result_columns = {
        column["name"]: column
        for column in inspector.get_columns("draft_operation_results")
    }
    for frozen_column in (
        "result_version_no",
        "result_status",
        "result_data_revision",
        "result_review_revision",
    ):
        assert result_columns[frozen_column]["nullable"] is False
    for frozen_column in (
        "superseded_version_id_1",
        "superseded_version_id_2",
    ):
        assert result_columns[frozen_column]["nullable"] is True

    result_foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("draft_operation_results")
    }
    identity = result_foreign_keys["fk_draft_operation_results_identity"]
    assert identity["constrained_columns"] == [
        "operation_token",
        "operation_kind",
        "operation_digest",
        "actor_user_id",
    ]
    assert identity["referred_table"] == "draft_operation_tokens"
    assert identity["referred_columns"] == [
        "operation_token",
        "operation_kind",
        "operation_digest",
        "actor_user_id",
    ]
    for ordinal in (1, 2):
        superseded = result_foreign_keys[
            f"fk_draft_operation_results_superseded_{ordinal}"
        ]
        assert superseded["constrained_columns"] == [f"superseded_version_id_{ordinal}"]
        assert superseded["referred_table"] == "dataset_versions"
        assert superseded["referred_columns"] == ["id"]

    disposition_foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("draft_disposition_events")
    }
    disposition_identity = disposition_foreign_keys[
        "fk_draft_disposition_events_identity"
    ]
    assert disposition_identity["constrained_columns"] == [
        "operation_token",
        "operation_kind",
        "operation_digest",
        "actor_user_id",
    ]
    assert disposition_identity["referred_table"] == "draft_operation_tokens"
    assert disposition_identity["referred_columns"] == [
        "operation_token",
        "operation_kind",
        "operation_digest",
        "actor_user_id",
    ]


def test_stage_five_migration_roundtrips_twice_without_leaking_restore_indexes(
    alembic_config: Config,
    mysql_engine: Engine,
    stage_five_revision: None,
) -> None:
    try:
        for _ in range(2):
            command.downgrade(alembic_config, "0007")
            downgraded = sa.inspect(mysql_engine)
            assert "daily_dataset_locks" not in downgraded.get_table_names()
            for table_name, expected_indexes in _DOWNGRADE_RESTORE_INDEXES.items():
                assert expected_indexes <= {
                    index["name"] for index in downgraded.get_indexes(table_name)
                }

            command.upgrade(alembic_config, "0008")
            upgraded = sa.inspect(mysql_engine)
            assert "daily_dataset_locks" in upgraded.get_table_names()
            with mysql_engine.connect() as connection:
                assert connection.scalar(
                    sa.text("SELECT COUNT(*) FROM daily_dataset_locks")
                ) == connection.scalar(sa.text("SELECT COUNT(*) FROM daily_datasets"))
            for table_name, restore_indexes in _DOWNGRADE_RESTORE_INDEXES.items():
                assert restore_indexes.isdisjoint(
                    index["name"] for index in upgraded.get_indexes(table_name)
                )
    finally:
        command.upgrade(alembic_config, "0028")


def test_stage_five_dataset_locks_backfill_and_reject_orphans(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.downgrade(alembic_config, "0007")
    dataset_id: int | None = None
    try:
        with mysql_engine.begin() as connection:
            dataset_id = _insert_dataset(
                connection,
                report_date=date(2098, 12, 31),
                report_type="business_report",
            )
            expected_lock_count = int(
                connection.scalar(sa.text("SELECT COUNT(*) FROM daily_datasets")) or 0
            )

        command.upgrade(alembic_config, "0008")

        with mysql_engine.connect() as connection:
            transaction = connection.begin()
            try:
                assert (
                    connection.scalar(
                        sa.text("SELECT COUNT(*) FROM daily_dataset_locks")
                    )
                    == expected_lock_count
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
                maximum_dataset_id = int(
                    connection.scalar(sa.text("SELECT MAX(id) FROM daily_datasets"))
                    or 0
                )
                _assert_rejected(
                    connection,
                    """
                    INSERT INTO daily_dataset_locks (dataset_id, lock_revision)
                    VALUES (:dataset_id, 0)
                    """,
                    {"dataset_id": maximum_dataset_id + 1},
                )
                _assert_rejected(
                    connection,
                    "DELETE FROM daily_datasets WHERE id = :dataset_id",
                    {"dataset_id": dataset_id},
                )
            finally:
                transaction.rollback()
    finally:
        command.upgrade(alembic_config, "0028")
        if dataset_id is not None:
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


def test_stage_five_version_and_active_pointer_constraints(
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
                report_date=date(2098, 1, 1),
                report_type="business_report",
            )
            _assert_rejected(
                connection,
                """
                INSERT INTO dataset_versions (
                    dataset_id, report_type, version_no, status,
                    ruleset_version, created_by
                ) VALUES (
                    :dataset_id, 'business_report', 0, 'draft',
                    'stage-five-v1', :user_id
                )
                """,
                {"dataset_id": dataset_id, "user_id": user_id},
            )
            _assert_rejected(
                connection,
                """
                INSERT INTO dataset_versions (
                    dataset_id, report_type, version_no, status,
                    ruleset_version, created_by
                ) VALUES (
                    :dataset_id, 'business_report', 1, 'discarded',
                    'stage-five-v1', :user_id
                )
                """,
                {"dataset_id": dataset_id, "user_id": user_id},
            )
            draft_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                report_type="business_report",
                version_no=1,
                user_id=user_id,
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO dataset_drafts (
                        dataset_id, version_id, version_status
                    ) VALUES (:dataset_id, :version_id, 'draft')
                    """
                ),
                {"dataset_id": dataset_id, "version_id": draft_id},
            )
            _assert_rejected(
                connection,
                """
                UPDATE dataset_drafts
                SET version_status = 'published'
                WHERE dataset_id = :dataset_id
                """,
                {"dataset_id": dataset_id},
            )
            _assert_rejected(
                connection,
                """
                UPDATE dataset_versions
                SET status = 'discarded', sealed_at = CURRENT_TIMESTAMP(6)
                WHERE id = :version_id
                """,
                {"version_id": draft_id},
            )
        finally:
            transaction.rollback()


def test_stage_five_lineage_and_snapshot_members_cannot_cross_report_types(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            business_dataset = _insert_dataset(
                connection,
                report_date=date(2098, 1, 2),
                report_type="business_report",
            )
            return_dataset = _insert_dataset(
                connection,
                report_date=date(2098, 1, 2),
                report_type="return_report",
            )
            child_id = _insert_version(
                connection,
                dataset_id=business_dataset,
                report_type="business_report",
                version_no=1,
                user_id=user_id,
            )
            return_parent_id = _insert_version(
                connection,
                dataset_id=return_dataset,
                report_type="return_report",
                version_no=1,
                user_id=user_id,
            )
            _assert_rejected(
                connection,
                """
                INSERT INTO version_parent_versions (
                    child_version_id, parent_version_id, parent_ordinal,
                    lineage_type, report_type
                ) VALUES (
                    :child_id, :parent_id, 0, 'merge_source', 'business_report'
                )
                """,
                {"child_id": child_id, "parent_id": return_parent_id},
            )

            snapshot = connection.execute(
                sa.text(
                    """
                    INSERT INTO version_base_snapshots (
                        version_id, report_type, snapshot_kind,
                        data_digest, row_count, totals_json
                    ) VALUES (
                        :version_id, 'business_report', 'merge',
                        :digest, 0, '{}'
                    )
                    """
                ),
                {"version_id": child_id, "digest": uuid4().bytes * 2},
            )
            assert snapshot.lastrowid is not None
            _assert_rejected(
                connection,
                """
                INSERT INTO version_base_snapshot_members (
                    snapshot_id, member_ordinal, member_type, member_role,
                    parent_version_id, report_type
                ) VALUES (
                    :snapshot_id, 0, 'dataset_version', 'merge_source',
                    :parent_id, 'business_report'
                )
                """,
                {
                    "snapshot_id": snapshot.lastrowid,
                    "parent_id": return_parent_id,
                },
            )
            _assert_rejected(
                connection,
                """
                INSERT INTO version_base_snapshot_members (
                    snapshot_id, member_ordinal, member_type, member_role,
                    parent_version_id, report_type
                ) VALUES (
                    :snapshot_id, 0, 'dataset_version', 'parse_input',
                    :parent_id, 'business_report'
                )
                """,
                {
                    "snapshot_id": snapshot.lastrowid,
                    "parent_id": child_id,
                },
            )
        finally:
            transaction.rollback()


def test_stage_five_base_row_state_and_keep_both_reason_are_constrained(
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
                report_date=date(2098, 1, 3),
                report_type="business_report",
            )
            version_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                report_type="business_report",
                version_no=1,
                user_id=user_id,
            )
            parent_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                report_type="business_report",
                version_no=2,
                user_id=user_id,
            )
            snapshot = connection.execute(
                sa.text(
                    """
                    INSERT INTO version_base_snapshots (
                        version_id, report_type, snapshot_kind,
                        data_digest, row_count, totals_json
                    ) VALUES (
                        :version_id, 'business_report', 'merge',
                        :digest, 1, '{}'
                    )
                    """
                ),
                {"version_id": version_id, "digest": uuid4().bytes * 2},
            )
            assert snapshot.lastrowid is not None
            member = connection.execute(
                sa.text(
                    """
                    INSERT INTO version_base_snapshot_members (
                        snapshot_id, member_ordinal, member_type, member_role,
                        parent_version_id, report_type
                    ) VALUES (
                        :snapshot_id, 0, 'dataset_version', 'merge_target',
                        :parent_id, 'business_report'
                    )
                    """
                ),
                {"snapshot_id": snapshot.lastrowid, "parent_id": parent_id},
            )
            assert member.lastrowid is not None
            statement = """
                INSERT INTO version_base_rows (
                    version_id, snapshot_id, report_type, logical_row_id,
                    row_ordinal, source_member_id, row_state,
                    merge_action, merge_reason
                ) VALUES (
                    :version_id, :snapshot_id, 'business_report', :logical_row_id,
                    0, :member_id, :row_state, 'keep_both', :merge_reason
                )
            """
            common = {
                "version_id": version_id,
                "snapshot_id": snapshot.lastrowid,
                "logical_row_id": uuid4().bytes,
                "member_id": member.lastrowid,
            }
            _assert_rejected(
                connection,
                statement,
                {**common, "row_state": "invalid", "merge_reason": "reason"},
            )
            _assert_rejected(
                connection,
                statement,
                {**common, "row_state": "active", "merge_reason": "   "},
            )
        finally:
            transaction.rollback()


def test_stage_five_operation_identity_and_disposition_constraints(
    alembic_config: Config,
    mysql_engine: Engine,
    stage_five_revision: None,
) -> None:
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            dataset_id = _insert_dataset(
                connection,
                report_date=date(2098, 1, 4),
                report_type="business_report",
            )
            source_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                report_type="business_report",
                version_no=1,
                user_id=user_id,
                status="discarded",
                sealed=True,
            )
            result_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                report_type="business_report",
                version_no=2,
                user_id=user_id,
            )
            operation_token = uuid4().bytes
            operation_digest = uuid4().bytes * 2
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :token, 'reassign_date', :digest,
                        :user_id, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": operation_token,
                    "digest": operation_digest,
                    "user_id": user_id,
                },
            )
            result_statement = """
                INSERT INTO draft_operation_results (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, result_kind,
                    result_dataset_id, result_version_id,
                    result_version_no, result_status,
                    result_data_revision, result_review_revision,
                    superseded_version_id_1, superseded_version_id_2,
                    source_dataset_id, source_version_id, completed_at
                ) VALUES (
                    :token, :kind, :digest, :user_id, 'reassigned',
                    :dataset_id, :result_id,
                    2, 'draft', 0, 0,
                    :superseded_1, :superseded_2,
                    :dataset_id, :source_id, CURRENT_TIMESTAMP(6)
                )
            """
            result_parameters = {
                "token": operation_token,
                "kind": "reassign_date",
                "digest": operation_digest,
                "user_id": user_id,
                "dataset_id": dataset_id,
                "result_id": result_id,
                "source_id": source_id,
                "superseded_1": source_id,
                "superseded_2": None,
            }
            _assert_rejected(
                connection,
                result_statement,
                {**result_parameters, "kind": "discard_draft"},
            )
            _assert_rejected(
                connection,
                result_statement,
                {
                    **result_parameters,
                    "superseded_1": None,
                    "superseded_2": source_id,
                },
            )
            _assert_rejected(
                connection,
                result_statement,
                {
                    **result_parameters,
                    "superseded_2": source_id,
                },
            )
            connection.execute(
                sa.text(result_statement),
                result_parameters,
            )

            cancel_token = uuid4().bytes
            cancel_digest = uuid4().bytes * 2
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :token, 'reassign_date', :digest,
                        :user_id, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": cancel_token,
                    "digest": cancel_digest,
                    "user_id": user_id,
                },
            )
            _assert_rejected(
                connection,
                """
                INSERT INTO draft_operation_results (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, result_kind,
                    result_dataset_id, result_version_id,
                    result_version_no, result_status,
                    result_data_revision, result_review_revision,
                    superseded_version_id_1,
                    source_dataset_id, source_version_id, completed_at
                ) VALUES (
                    :token, 'reassign_date', :digest,
                    :user_id, 'cancelled',
                    :dataset_id, :result_id,
                    2, 'cancelled', 0, 0,
                    :source_id,
                    :dataset_id, :source_id, CURRENT_TIMESTAMP(6)
                )
                """,
                {
                    "token": cancel_token,
                    "digest": cancel_digest,
                    "user_id": user_id,
                    "dataset_id": dataset_id,
                    "result_id": result_id,
                    "source_id": source_id,
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
                        :token, 'reassign_date', :digest,
                        :user_id, 'cancelled',
                        :dataset_id, :result_id,
                        2, 'cancelled', 0, 0, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": cancel_token,
                    "digest": cancel_digest,
                    "user_id": user_id,
                    "dataset_id": dataset_id,
                    "result_id": result_id,
                },
            )

            _assert_rejected(
                connection,
                """
                INSERT INTO draft_disposition_events (
                    operation_token, operation_kind, operation_digest,
                    dataset_id, version_id, event_type,
                    actor_user_id, terminal_data_revision,
                    terminal_review_revision, reason, occurred_at
                ) VALUES (
                    :token, 'reassign_date', :digest,
                    :dataset_id, :source_id, 'date_reassigned',
                    :user_id, 0, 0, 'move date', CURRENT_TIMESTAMP(6)
                )
                """,
                {
                    "token": operation_token,
                    "digest": operation_digest,
                    "dataset_id": dataset_id,
                    "source_id": source_id,
                    "user_id": user_id,
                },
            )
            other_user_id = _insert_user(connection)
            disposition_statement = """
                INSERT INTO draft_disposition_events (
                    operation_token, operation_kind, operation_digest,
                    dataset_id, version_id, event_type,
                    successor_dataset_id, successor_version_id,
                    actor_user_id, terminal_data_revision,
                    terminal_review_revision, reason, occurred_at
                ) VALUES (
                    :token, :kind, :digest,
                    :dataset_id, :source_id, :event_type,
                    :dataset_id, :result_id,
                    :user_id, 0, 0, 'move date', CURRENT_TIMESTAMP(6)
                )
            """
            disposition_parameters = {
                "token": operation_token,
                "kind": "reassign_date",
                "digest": operation_digest,
                "dataset_id": dataset_id,
                "source_id": source_id,
                "result_id": result_id,
                "event_type": "date_reassigned",
                "user_id": user_id,
            }
            _assert_rejected(
                connection,
                disposition_statement,
                {**disposition_parameters, "digest": uuid4().bytes * 2},
            )
            _assert_rejected(
                connection,
                disposition_statement,
                {**disposition_parameters, "user_id": other_user_id},
            )
            _assert_rejected(
                connection,
                disposition_statement,
                {
                    **disposition_parameters,
                    "kind": "materialize_baseline",
                    "event_type": "superseded",
                },
            )
            _assert_rejected(
                connection,
                disposition_statement,
                {**disposition_parameters, "event_type": "force_rebuilt"},
            )
            connection.execute(
                sa.text(disposition_statement),
                disposition_parameters,
            )
            _assert_rejected(
                connection,
                disposition_statement,
                {**disposition_parameters, "reason": "duplicate"},
            )
        finally:
            transaction.rollback()


@pytest.mark.parametrize(
    ("operation_kind", "result_kind", "result_status"),
    (
        ("materialize_baseline", "force_rebuilt", "draft"),
        ("materialize_baseline", "created", "discarded"),
        ("force_rebuild", "created", "draft"),
        ("discard_draft", "discarded", "draft"),
        ("reassign_date", "cancelled", "draft"),
        ("reassign_date", "reassigned", "cancelled"),
    ),
)
def test_stage_five_operation_results_reject_inconsistent_terminal_semantics(
    operation_kind: str,
    result_kind: str,
    result_status: str,
    alembic_config: Config,
    mysql_engine: Engine,
    stage_five_revision: None,
) -> None:
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            dataset_id = _insert_dataset(
                connection,
                report_date=date(2098, 1, 20),
                report_type="business_report",
            )
            version_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                report_type="business_report",
                version_no=1,
                user_id=user_id,
            )
            operation_token = uuid4().bytes
            operation_digest = uuid4().bytes * 2
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :token, :operation_kind, :digest,
                        :user_id, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": operation_token,
                    "operation_kind": operation_kind,
                    "digest": operation_digest,
                    "user_id": user_id,
                },
            )
            _assert_rejected(
                connection,
                """
                INSERT INTO draft_operation_results (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, result_kind,
                    result_dataset_id, result_version_id,
                    result_version_no, result_status,
                    result_data_revision, result_review_revision,
                    completed_at
                ) VALUES (
                    :token, :operation_kind, :digest,
                    :user_id, :result_kind,
                    :dataset_id, :version_id,
                    1, :result_status, 0, 0, CURRENT_TIMESTAMP(6)
                )
                """,
                {
                    "token": operation_token,
                    "operation_kind": operation_kind,
                    "digest": operation_digest,
                    "user_id": user_id,
                    "result_kind": result_kind,
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                    "result_status": result_status,
                },
            )
        finally:
            transaction.rollback()


def test_stage_five_upgrade_preflight_rejects_invalid_0007_data_before_ddl(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.downgrade(alembic_config, "0007")
    user_id: int | None = None
    dataset_id: int | None = None
    version_id: int | None = None
    try:
        with mysql_engine.begin() as connection:
            user_id = _insert_user(connection)
            dataset_id = _insert_dataset(
                connection,
                report_date=date(2098, 1, 5),
                report_type="business_report",
            )
            version_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                report_type="business_report",
                version_no=1,
                user_id=user_id,
                sealed=True,
            )

        with pytest.raises(RuntimeError, match="sealed state"):
            command.upgrade(alembic_config, "0008")

        inspector = sa.inspect(mysql_engine)
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0007"
            )
        assert "version_status" not in {
            column["name"] for column in inspector.get_columns("dataset_drafts")
        }
        assert "draft_operation_tokens" not in inspector.get_table_names()
        assert "daily_dataset_locks" not in inspector.get_table_names()
    finally:
        try:
            if (
                user_id is not None
                and dataset_id is not None
                and version_id is not None
            ):
                with mysql_engine.begin() as connection:
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
        finally:
            command.upgrade(alembic_config, "0028")


@pytest.mark.parametrize(
    ("protected_table", "expected_label"),
    (
        ("draft_operation_results", "draft operation result"),
        ("draft_operation_tokens", "draft operation token"),
        ("draft_disposition_events", "draft disposition event"),
    ),
)
def test_stage_five_downgrade_refuses_to_drop_immutable_history_before_ddl(
    protected_table: str,
    expected_label: str,
    alembic_config: Config,
    mysql_engine: Engine,
    stage_five_revision: None,
) -> None:
    operation_token = uuid4().bytes
    operation_digest = uuid4().bytes * 2
    with mysql_engine.begin() as connection:
        user_id = _insert_user(connection)
        dataset_id = _insert_dataset(
            connection,
            report_date=date(2098, 2, 1 + len(protected_table)),
            report_type="business_report",
        )
        version_id = _insert_version(
            connection,
            dataset_id=dataset_id,
            report_type="business_report",
            version_no=1,
            user_id=user_id,
            status=(
                "discarded"
                if protected_table == "draft_disposition_events"
                else "draft"
            ),
            sealed=protected_table == "draft_disposition_events",
        )
        if protected_table in {
            "draft_operation_tokens",
            "draft_operation_results",
            "draft_disposition_events",
        }:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :token, :kind, :digest,
                        :user_id, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": operation_token,
                    "kind": (
                        "discard_draft"
                        if protected_table == "draft_disposition_events"
                        else "materialize_baseline"
                    ),
                    "digest": operation_digest,
                    "user_id": user_id,
                },
            )
        if protected_table == "draft_operation_results":
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
                        :token, 'materialize_baseline', :digest,
                        :user_id, 'created',
                        :dataset_id, :version_id,
                        1, 'draft', 0, 0, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": operation_token,
                    "digest": operation_digest,
                    "user_id": user_id,
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                },
            )
        if protected_table == "draft_disposition_events":
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_disposition_events (
                        operation_token, operation_kind, operation_digest,
                        dataset_id, version_id,
                        event_type, actor_user_id,
                        terminal_data_revision, terminal_review_revision,
                        reason, occurred_at
                    ) VALUES (
                        :token, 'discard_draft', :digest,
                        :dataset_id, :version_id,
                        'discarded', :user_id,
                        0, 0, 'downgrade guard', CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": operation_token,
                    "digest": operation_digest,
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                    "user_id": user_id,
                },
            )

    try:
        with pytest.raises(RuntimeError, match=expected_label):
            command.downgrade(alembic_config, "0007")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0008"
            )
        assert "row_state" in {
            column["name"]
            for column in sa.inspect(mysql_engine).get_columns("version_base_rows")
        }
    finally:
        command.upgrade(alembic_config, "0008")
        with mysql_engine.begin() as connection:
            for statement in (
                "DELETE FROM draft_operation_results WHERE operation_token = :token",
                "DELETE FROM draft_disposition_events WHERE operation_token = :token",
                "DELETE FROM draft_operation_tokens WHERE operation_token = :token",
            ):
                connection.execute(
                    sa.text(statement),
                    {"token": operation_token},
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


def test_stage_five_downgrade_refuses_non_active_base_rows_before_ddl(
    alembic_config: Config,
    mysql_engine: Engine,
    stage_five_revision: None,
) -> None:
    with mysql_engine.begin() as connection:
        user_id = _insert_user(connection)
        dataset_id = _insert_dataset(
            connection,
            report_date=date(2098, 3, 1),
            report_type="business_report",
        )
        version_id = _insert_version(
            connection,
            dataset_id=dataset_id,
            report_type="business_report",
            version_no=1,
            user_id=user_id,
        )
        parent_id = _insert_version(
            connection,
            dataset_id=dataset_id,
            report_type="business_report",
            version_no=2,
            user_id=user_id,
        )
        snapshot = connection.execute(
            sa.text(
                """
                INSERT INTO version_base_snapshots (
                    version_id, report_type, snapshot_kind,
                    data_digest, row_count, totals_json
                ) VALUES (
                    :version_id, 'business_report', 'merge',
                    :digest, 1, '{}'
                )
                """
            ),
            {"version_id": version_id, "digest": uuid4().bytes * 2},
        )
        assert snapshot.lastrowid is not None
        snapshot_id = int(snapshot.lastrowid)
        member = connection.execute(
            sa.text(
                """
                INSERT INTO version_base_snapshot_members (
                    snapshot_id, member_ordinal, member_type, member_role,
                    parent_version_id, report_type
                ) VALUES (
                    :snapshot_id, 0, 'dataset_version', 'merge_target',
                    :parent_id, 'business_report'
                )
                """
            ),
            {"snapshot_id": snapshot_id, "parent_id": parent_id},
        )
        assert member.lastrowid is not None
        connection.execute(
            sa.text(
                """
                INSERT INTO version_base_rows (
                    version_id, snapshot_id, report_type, logical_row_id,
                    row_ordinal, source_member_id, row_state, merge_action
                ) VALUES (
                    :version_id, :snapshot_id, 'business_report',
                    :logical_row_id, 0, :member_id, 'excluded', 'keep_target'
                )
                """
            ),
            {
                "version_id": version_id,
                "snapshot_id": snapshot_id,
                "logical_row_id": uuid4().bytes,
                "member_id": int(member.lastrowid),
            },
        )

    try:
        with pytest.raises(RuntimeError, match="non-active base row"):
            command.downgrade(alembic_config, "0007")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0008"
            )
        assert "row_state" in {
            column["name"]
            for column in sa.inspect(mysql_engine).get_columns("version_base_rows")
        }
    finally:
        command.upgrade(alembic_config, "0008")
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM version_base_rows WHERE version_id = :version_id"),
                {"version_id": version_id},
            )
            connection.execute(
                sa.text(
                    "DELETE FROM version_base_snapshot_members "
                    "WHERE snapshot_id = :snapshot_id"
                ),
                {"snapshot_id": snapshot_id},
            )
            connection.execute(
                sa.text("DELETE FROM version_base_snapshots WHERE id = :snapshot_id"),
                {"snapshot_id": snapshot_id},
            )
            connection.execute(
                sa.text(
                    "DELETE FROM dataset_versions WHERE id IN (:version_id, :parent_id)"
                ),
                {"version_id": version_id, "parent_id": parent_id},
            )
            connection.execute(
                sa.text("DELETE FROM daily_datasets WHERE id = :dataset_id"),
                {"dataset_id": dataset_id},
            )
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )
