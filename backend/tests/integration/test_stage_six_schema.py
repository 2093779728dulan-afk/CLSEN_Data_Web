from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.mysql


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
                :username, 'Stage Six Schema', '$argon2id$test', 'active'
            )
            """
        ),
        {"username": f"stage-six-schema-{uuid4().hex}"},
    )
    assert result.lastrowid is not None
    return int(result.lastrowid)


def _insert_dataset(connection: Connection, *, report_date: date) -> int:
    result = connection.execute(
        sa.text(
            """
            INSERT INTO daily_datasets (site_id, report_date, report_type)
            VALUES (1, :report_date, 'business_report')
            """
        ),
        {"report_date": report_date},
    )
    assert result.lastrowid is not None
    return int(result.lastrowid)


def _insert_version(
    connection: Connection,
    *,
    dataset_id: int,
    user_id: int,
    version_no: int = 1,
    status: str = "draft",
) -> int:
    result = connection.execute(
        sa.text(
            """
            INSERT INTO dataset_versions (
                dataset_id, report_type, version_no, status,
                ruleset_version, created_by, sealed_at
            ) VALUES (
                :dataset_id, 'business_report', :version_no, :status,
                'stage-six-v1', :user_id,
                CASE
                    WHEN :status IN ('published', 'discarded')
                    THEN CURRENT_TIMESTAMP(6)
                    ELSE NULL
                END
            )
            """
        ),
        {
            "dataset_id": dataset_id,
            "version_no": version_no,
            "status": status,
            "user_id": user_id,
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


def test_stage_six_schema_exposes_review_and_publication_guards(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    inspector = sa.inspect(mysql_engine)

    assert {
        "note_threads",
        "publication_command_results",
        "review_operation_tokens",
        "review_operation_results",
        "terminal_write_guard_bypass_accounts",
        "version_review_events",
    } <= set(inspector.get_table_names())

    field_foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("field_changes")
    }
    assert field_foreign_keys["fk_field_changes_event_kind"]["constrained_columns"] == [
        "version_id",
        "id",
        "event_kind",
    ]
    assert field_foreign_keys["fk_field_changes_restore_previous"][
        "constrained_columns"
    ] == ["version_id", "row_id", "field_name", "restored_field_change_id"]
    assert field_foreign_keys["fk_field_changes_restore_parent"][
        "constrained_columns"
    ] == ["version_id", "restored_parent_version_id"]
    assert field_foreign_keys["fk_field_changes_restore_source"][
        "constrained_columns"
    ] == ["version_id", "row_id", "restored_source_row_id"]

    note_columns = {column["name"]: column for column in inspector.get_columns("notes")}
    assert "supersedes_revision_number" in note_columns
    assert note_columns["visibility"]["default"] is not None
    assert {
        "target_type",
        "import_batch_id",
        "version_id",
        "row_id",
        "field_name",
    }.isdisjoint(note_columns)
    assert "fk_notes_thread" in {
        foreign_key["name"] for foreign_key in inspector.get_foreign_keys("notes")
    }

    draft_result_columns = {
        column["name"]: column
        for column in inspector.get_columns("draft_operation_results")
    }
    assert draft_result_columns["create_revision_parent_version_id"]["nullable"] is True
    assert (
        draft_result_columns["published_move_source_parent_version_id"]["nullable"]
        is True
    )
    assert (
        draft_result_columns["published_move_source_lineage_type"]["nullable"] is True
    )
    draft_result_foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("draft_operation_results")
    }
    create_revision_parent = draft_result_foreign_keys[
        "fk_draft_operation_results_create_revision_parent"
    ]
    assert create_revision_parent["constrained_columns"] == [
        "result_version_id",
        "create_revision_parent_version_id",
    ]
    assert create_revision_parent["referred_table"] == "version_parent_versions"
    assert create_revision_parent["referred_columns"] == [
        "child_version_id",
        "parent_version_id",
    ]
    published_move_source = draft_result_foreign_keys[
        "fk_draft_operation_results_published_move_source"
    ]
    assert published_move_source["constrained_columns"] == [
        "result_version_id",
        "published_move_source_parent_version_id",
        "published_move_source_lineage_type",
    ]
    assert published_move_source["referred_table"] == "version_parent_versions"
    assert published_move_source["referred_columns"] == [
        "child_version_id",
        "parent_version_id",
        "lineage_type",
    ]

    publication_result_columns = {
        column["name"]: column
        for column in inspector.get_columns("publication_command_results")
    }
    assert (
        publication_result_columns["move_revision_operation_token"]["nullable"] is True
    )
    assert publication_result_columns["reversed_move_command_id"]["nullable"] is True
    publication_result_foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("publication_command_results")
    }
    assert publication_result_foreign_keys[
        "fk_publication_command_results_move_revision"
    ]["constrained_columns"] == [
        "move_revision_operation_token",
        "result_dataset_id",
        "result_version_id",
    ]
    assert publication_result_foreign_keys[
        "fk_publication_command_results_reversed_move"
    ]["constrained_columns"] == ["reversed_move_command_id"]

    review_result_columns = {
        column["name"]: column
        for column in inspector.get_columns("review_operation_results")
    }
    assert review_result_columns["result_import_batch_id"]["nullable"] is True
    assert review_result_columns["result_dataset_id"]["nullable"] is True
    assert review_result_columns["result_version_id"]["nullable"] is True
    assert "validation_run_id" in review_result_columns
    assert "version_review_event_id" in review_result_columns

    issue_foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("validation_issues")
    }
    assert issue_foreign_keys["fk_validation_issues_attempt"][
        "constrained_columns"
    ] == ["import_batch_id", "parse_attempt_id"]

    publication_foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("dataset_publications")
    }
    assert publication_foreign_keys["fk_dataset_publications_published_version"][
        "constrained_columns"
    ] == ["dataset_id", "version_id", "version_status"]

    with mysql_engine.connect() as connection:
        trigger_names = set(
            connection.scalars(
                sa.text(
                    """
                    SELECT TRIGGER_NAME
                    FROM information_schema.TRIGGERS
                    WHERE TRIGGER_SCHEMA = DATABASE()
                    """
                )
            )
        )
    assert {
        "trg_dataset_versions_terminal_update",
        "trg_business_rows_terminal_update",
        "trg_note_threads_no_update",
        "trg_version_review_events_no_update",
        "trg_return_rows_terminal_update",
    } <= trigger_names


def test_create_revision_draft_ledger_requires_exact_parent_lineage(
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
                report_date=date(2097, 6, 4),
            )
            parent_version_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                user_id=user_id,
                status="published",
            )
            result_version_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                user_id=user_id,
                version_no=2,
            )
            unrelated_version_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                user_id=user_id,
                version_no=3,
                status="published",
            )
            other_dataset_id = _insert_dataset(
                connection,
                report_date=date(2097, 6, 5),
            )
            cross_dataset_parent_id = _insert_version(
                connection,
                dataset_id=other_dataset_id,
                user_id=user_id,
                status="published",
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO dataset_drafts (
                        dataset_id, version_id, version_status
                    ) VALUES (
                        :dataset_id, :version_id, 'draft'
                    )
                    """
                ),
                {"dataset_id": dataset_id, "version_id": result_version_id},
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO version_parent_versions (
                        child_version_id, parent_version_id, parent_ordinal,
                        lineage_type, report_type
                    ) VALUES
                        (
                            :child_id, :parent_id, 1,
                            'draft_predecessor', 'business_report'
                        ),
                        (
                            :child_id, :cross_parent_id, 2,
                            'merge_source', 'business_report'
                        )
                    """
                ),
                {
                    "child_id": result_version_id,
                    "parent_id": parent_version_id,
                    "cross_parent_id": cross_dataset_parent_id,
                },
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
                        :token, 'create_revision', :digest,
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
                    source_dataset_id, source_version_id,
                    create_revision_parent_version_id, completed_at
                ) VALUES (
                    :token, :operation_kind, :digest,
                    :user_id, :result_kind,
                    :result_dataset_id, :result_version_id,
                    2, :result_status, 0, 0,
                    :superseded_1, :superseded_2,
                    :source_dataset_id, :source_version_id,
                    :parent_witness, CURRENT_TIMESTAMP(6)
                )
            """
            result_parameters: dict[str, object] = {
                "token": operation_token,
                "operation_kind": "create_revision",
                "digest": operation_digest,
                "user_id": user_id,
                "result_kind": "created",
                "result_dataset_id": dataset_id,
                "result_version_id": result_version_id,
                "result_status": "draft",
                "superseded_1": None,
                "superseded_2": None,
                "source_dataset_id": dataset_id,
                "source_version_id": parent_version_id,
                "parent_witness": parent_version_id,
            }

            for overrides in (
                {"result_kind": "merged"},
                {"result_status": "discarded"},
                {
                    "source_dataset_id": other_dataset_id,
                    "source_version_id": cross_dataset_parent_id,
                    "parent_witness": cross_dataset_parent_id,
                },
                {
                    "source_version_id": result_version_id,
                    "parent_witness": result_version_id,
                },
                {"superseded_1": parent_version_id},
                {"parent_witness": None},
                {"parent_witness": unrelated_version_id},
                {
                    "source_version_id": unrelated_version_id,
                    "parent_witness": unrelated_version_id,
                },
            ):
                _assert_rejected(
                    connection,
                    result_statement,
                    {**result_parameters, **overrides},
                )

            other_token = uuid4().bytes
            other_digest = uuid4().bytes * 2
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :token, 'materialize_baseline', :digest,
                        :user_id, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": other_token,
                    "digest": other_digest,
                    "user_id": user_id,
                },
            )
            _assert_rejected(
                connection,
                result_statement,
                {
                    **result_parameters,
                    "token": other_token,
                    "operation_kind": "materialize_baseline",
                    "digest": other_digest,
                    "source_dataset_id": None,
                    "source_version_id": None,
                },
            )

            connection.execute(sa.text(result_statement), result_parameters)
            assert connection.execute(
                sa.text(
                    """
                    SELECT source_dataset_id, source_version_id,
                           create_revision_parent_version_id
                    FROM draft_operation_results
                    WHERE operation_token = :token
                    """
                ),
                {"token": operation_token},
            ).one() == (
                dataset_id,
                parent_version_id,
                parent_version_id,
            )
        finally:
            transaction.rollback()


def test_published_move_draft_ledger_requires_moved_source_lineage(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user_id = _insert_user(connection)
            source_dataset_id = _insert_dataset(
                connection,
                report_date=date(2097, 6, 6),
            )
            target_dataset_id = _insert_dataset(
                connection,
                report_date=date(2097, 6, 7),
            )
            source_version_id = _insert_version(
                connection,
                dataset_id=source_dataset_id,
                user_id=user_id,
                status="published",
            )
            target_version_id = _insert_version(
                connection,
                dataset_id=target_dataset_id,
                user_id=user_id,
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO version_parent_versions (
                        child_version_id, parent_version_id, parent_ordinal,
                        lineage_type, report_type
                    ) VALUES (
                        :target_version_id, :source_version_id, 1,
                        'moved_source', 'business_report'
                    )
                    """
                ),
                {
                    "target_version_id": target_version_id,
                    "source_version_id": source_version_id,
                },
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
                        :token, 'create_published_move_revision', :digest,
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
                    source_dataset_id, source_version_id,
                    create_revision_parent_version_id,
                    published_move_source_parent_version_id,
                    published_move_source_lineage_type, completed_at
                ) VALUES (
                    :token, 'create_published_move_revision', :digest,
                    :user_id, :result_kind,
                    :target_dataset_id, :target_version_id,
                    1, :result_status, 0, 0,
                    NULL, :superseded_2,
                    :source_dataset_id, :source_version_id,
                    NULL, :source_parent_id, :source_lineage,
                    CURRENT_TIMESTAMP(6)
                )
            """
            result_parameters: dict[str, object] = {
                "token": operation_token,
                "digest": operation_digest,
                "user_id": user_id,
                "result_kind": "move_revision_created",
                "target_dataset_id": target_dataset_id,
                "target_version_id": target_version_id,
                "result_status": "draft",
                "superseded_2": None,
                "source_dataset_id": source_dataset_id,
                "source_version_id": source_version_id,
                "source_parent_id": source_version_id,
                "source_lineage": "moved_source",
            }
            for overrides in (
                {"result_kind": "created"},
                {"result_status": "cancelled"},
                {"source_dataset_id": target_dataset_id},
                {"source_parent_id": None},
                {"source_lineage": "merge_source"},
                {"superseded_2": source_version_id},
            ):
                _assert_rejected(
                    connection,
                    result_statement,
                    {**result_parameters, **overrides},
                )

            connection.execute(sa.text(result_statement), result_parameters)
            assert connection.execute(
                sa.text(
                    """
                    SELECT result_kind, source_dataset_id, source_version_id,
                           published_move_source_parent_version_id,
                           published_move_source_lineage_type
                    FROM draft_operation_results
                    WHERE operation_token = :token
                    """
                ),
                {"token": operation_token},
            ).one() == (
                "move_revision_created",
                source_dataset_id,
                source_version_id,
                source_version_id,
                "moved_source",
            )

            cancelled_token = uuid4().bytes
            cancelled_digest = uuid4().bytes * 2
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :token, 'create_published_move_revision', :digest,
                        :user_id, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": cancelled_token,
                    "digest": cancelled_digest,
                    "user_id": user_id,
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
                        superseded_version_id_1, superseded_version_id_2,
                        source_dataset_id, source_version_id,
                        create_revision_parent_version_id,
                        published_move_source_parent_version_id,
                        published_move_source_lineage_type, completed_at
                    ) VALUES (
                        :token, 'create_published_move_revision', :digest,
                        :user_id, 'cancelled',
                        :source_dataset_id, :source_version_id,
                        1, 'cancelled', 0, 0,
                        NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                        CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": cancelled_token,
                    "digest": cancelled_digest,
                    "user_id": user_id,
                    "source_dataset_id": source_dataset_id,
                    "source_version_id": source_version_id,
                },
            )
        finally:
            transaction.rollback()


def test_stage_six_change_validation_and_review_constraints(
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
                report_date=date(2097, 6, 1),
            )
            version_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                user_id=user_id,
            )
            row_result = connection.execute(
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
            assert row_result.lastrowid is not None
            row_id = int(row_result.lastrowid)

            event_result = connection.execute(
                sa.text(
                    """
                    INSERT INTO data_change_events (
                        version_id, sequence_number, data_revision,
                        event_kind, actor_user_id, reason
                    ) VALUES (
                        :version_id, 1, 1, 'row', :user_id, 'exclude duplicate'
                    )
                    """
                ),
                {"version_id": version_id, "user_id": user_id},
            )
            assert event_result.lastrowid is not None
            _assert_rejected(
                connection,
                """
                INSERT INTO field_changes (
                    id, version_id, event_kind, row_id, field_name,
                    operation, before_value_json, after_value_json
                ) VALUES (
                    :event_id, :version_id, 'field', :row_id, 'sku',
                    'set', JSON_QUOTE('before'), JSON_QUOTE('after')
                )
                """,
                {
                    "event_id": int(event_result.lastrowid),
                    "version_id": version_id,
                    "row_id": row_id,
                },
            )

            _assert_rejected(
                connection,
                """
                INSERT INTO validation_runs (
                    version_id, run_type, data_revision, ruleset_version,
                    status, result, data_digest, summary_json, completed_at
                ) VALUES (
                    :version_id, 'full', 0, 'stage-six-v1',
                    'succeeded', 'passed', NULL, '{}', CURRENT_TIMESTAMP(6)
                )
                """,
                {"version_id": version_id},
            )

            run_result = connection.execute(
                sa.text(
                    """
                    INSERT INTO validation_runs (
                        version_id, run_type, data_revision, ruleset_version,
                        status, result, data_digest, summary_json, completed_at
                    ) VALUES (
                        :version_id, 'full', 0, 'stage-six-v1',
                        'succeeded', 'passed', :digest, '{}', CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {"version_id": version_id, "digest": uuid4().bytes * 2},
            )
            assert run_result.lastrowid is not None
            issue_result = connection.execute(
                sa.text(
                    """
                    INSERT INTO validation_issues (
                        validation_run_id, version_id, severity, rule_code,
                        message, requires_note
                    ) VALUES (
                        :run_id, :version_id, 'warning', 'duplicate',
                        'potential duplicate', TRUE
                    )
                    """
                ),
                {
                    "run_id": int(run_result.lastrowid),
                    "version_id": version_id,
                },
            )
            assert issue_result.lastrowid is not None
            _assert_rejected(
                connection,
                """
                INSERT INTO issue_review_events (
                    version_id, validation_run_id, validation_issue_id,
                    issue_severity, issue_requires_note,
                    sequence_number, review_revision, event_type,
                    actor_user_id, comment
                ) VALUES (
                    :version_id, :run_id, :issue_id,
                    'warning', TRUE, 1, 1, 'acknowledge', :user_id, NULL
                )
                """,
                {
                    "version_id": version_id,
                    "run_id": int(run_result.lastrowid),
                    "issue_id": int(issue_result.lastrowid),
                    "user_id": user_id,
                },
            )
        finally:
            transaction.rollback()


def test_stage_six_restore_note_and_review_result_lineage(
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
                report_date=date(2097, 6, 3),
            )
            version_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                user_id=user_id,
            )
            parent_version_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                user_id=user_id,
                version_no=2,
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO version_parent_versions (
                        child_version_id, parent_version_id, parent_ordinal,
                        lineage_type, report_type
                    ) VALUES (
                        :version_id, :parent_version_id, 1,
                        'draft_predecessor', 'business_report'
                    )
                    """
                ),
                {
                    "version_id": version_id,
                    "parent_version_id": parent_version_id,
                },
            )
            row_result = connection.execute(
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
            assert row_result.lastrowid is not None
            row_id = int(row_result.lastrowid)

            first_event = connection.execute(
                sa.text(
                    """
                    INSERT INTO data_change_events (
                        version_id, sequence_number, data_revision,
                        event_kind, actor_user_id, reason
                    ) VALUES (
                        :version_id, 1, 1, 'field', :user_id, 'set sku'
                    )
                    """
                ),
                {"version_id": version_id, "user_id": user_id},
            )
            assert first_event.lastrowid is not None
            first_change_id = int(first_event.lastrowid)
            connection.execute(
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
                    "id": first_change_id,
                    "version_id": version_id,
                    "row_id": row_id,
                },
            )
            previous_event = connection.execute(
                sa.text(
                    """
                    INSERT INTO data_change_events (
                        version_id, sequence_number, data_revision,
                        event_kind, actor_user_id, reason
                    ) VALUES (
                        :version_id, 2, 2, 'field', :user_id,
                        'restore previous sku'
                    )
                    """
                ),
                {"version_id": version_id, "user_id": user_id},
            )
            assert previous_event.lastrowid is not None
            connection.execute(
                sa.text(
                    """
                    INSERT INTO field_changes (
                        id, version_id, event_kind, row_id, field_name,
                        operation, restored_field_change_id,
                        before_value_json, after_value_json
                    ) VALUES (
                        :id, :version_id, 'field', :row_id, 'sku',
                        'restore_previous', :previous_id,
                        JSON_QUOTE('after'), JSON_QUOTE('before')
                    )
                    """
                ),
                {
                    "id": int(previous_event.lastrowid),
                    "version_id": version_id,
                    "row_id": row_id,
                    "previous_id": first_change_id,
                },
            )

            parent_event = connection.execute(
                sa.text(
                    """
                    INSERT INTO data_change_events (
                        version_id, sequence_number, data_revision,
                        event_kind, actor_user_id, reason
                    ) VALUES (
                        :version_id, 3, 3, 'field', :user_id,
                        'restore parent sku'
                    )
                    """
                ),
                {"version_id": version_id, "user_id": user_id},
            )
            assert parent_event.lastrowid is not None
            connection.execute(
                sa.text(
                    """
                    INSERT INTO field_changes (
                        id, version_id, event_kind, row_id, field_name,
                        operation, restored_parent_version_id,
                        before_value_json, after_value_json
                    ) VALUES (
                        :id, :version_id, 'field', :row_id, 'sku',
                        'restore_parent', :parent_version_id,
                        JSON_QUOTE('before'), JSON_QUOTE('parent')
                    )
                    """
                ),
                {
                    "id": int(parent_event.lastrowid),
                    "version_id": version_id,
                    "row_id": row_id,
                    "parent_version_id": parent_version_id,
                },
            )

            invalid_event = connection.execute(
                sa.text(
                    """
                    INSERT INTO data_change_events (
                        version_id, sequence_number, data_revision,
                        event_kind, actor_user_id, reason
                    ) VALUES (
                        :version_id, 4, 4, 'field', :user_id,
                        'invalid mixed restore lineage'
                    )
                    """
                ),
                {"version_id": version_id, "user_id": user_id},
            )
            assert invalid_event.lastrowid is not None
            _assert_rejected(
                connection,
                """
                INSERT INTO field_changes (
                    id, version_id, event_kind, row_id, field_name,
                    operation, restored_field_change_id,
                    restored_parent_version_id,
                    before_value_json, after_value_json
                ) VALUES (
                    :id, :version_id, 'field', :row_id, 'sku',
                    'restore_previous', :previous_id, :parent_version_id,
                    JSON_QUOTE('parent'), JSON_QUOTE('before')
                )
                """,
                {
                    "id": int(invalid_event.lastrowid),
                    "version_id": version_id,
                    "row_id": row_id,
                    "previous_id": first_change_id,
                    "parent_version_id": parent_version_id,
                },
            )

            note_key = f"stage-six-{uuid4().hex}"
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
                {"note_key": note_key, "version_id": version_id},
            )
            _assert_rejected(
                connection,
                """
                INSERT INTO notes (
                    note_key, revision_number, body, author_user_id,
                    review_revision
                ) VALUES (
                    :note_key, 1, '   ', :user_id, 1
                )
                """,
                {"note_key": note_key, "user_id": user_id},
            )
            note_result = connection.execute(
                sa.text(
                    """
                    INSERT INTO notes (
                        note_key, revision_number, body, author_user_id,
                        review_revision
                    ) VALUES (
                        :note_key, 1, 'confirmed', :user_id, 1
                    )
                    """
                ),
                {"note_key": note_key, "user_id": user_id},
            )
            assert note_result.lastrowid is not None
            assert (
                connection.scalar(
                    sa.text("SELECT visibility FROM notes WHERE id = :note_id"),
                    {"note_id": int(note_result.lastrowid)},
                )
                == "internal"
            )

            validation_run = connection.execute(
                sa.text(
                    """
                    INSERT INTO validation_runs (
                        version_id, run_type, data_revision, ruleset_version,
                        status, result, data_digest, summary_json, completed_at
                    ) VALUES (
                        :version_id, 'full', 3, 'stage-six-v1',
                        'succeeded', 'passed', :digest, '{}',
                        CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {"version_id": version_id, "digest": uuid4().bytes * 2},
            )
            assert validation_run.lastrowid is not None
            operation_token = uuid4().bytes
            operation_digest = uuid4().bytes * 2
            connection.execute(
                sa.text(
                    """
                    INSERT INTO review_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :token, 'mark_ready', :digest, :user_id,
                        CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": operation_token,
                    "digest": operation_digest,
                    "user_id": user_id,
                },
            )
            review_event = connection.execute(
                sa.text(
                    """
                    INSERT INTO version_review_events (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, dataset_id, version_id,
                        from_status, to_status, data_revision,
                        from_review_revision, to_review_revision,
                        selected_validation_run_id,
                        confirmation_digest, confirmation_json,
                        reason, occurred_at
                    ) VALUES (
                        :token, 'mark_ready', :digest, :user_id,
                        :dataset_id, :version_id, 'draft', 'ready_for_publish',
                        3, 0, 1, :run_id, :confirmation_digest,
                        JSON_OBJECT(
                            'validation_run_id', :run_id,
                            'validation_data_digest', :validation_digest,
                            'ruleset_version', 'stage-six-v1',
                            'confirmed_report_date', '2097-06-03',
                            'confirmed_report_type', 'business_report',
                            'confirmed_row_count', 1,
                            'confirmed_totals', JSON_OBJECT()
                        ),
                        'review complete', CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": operation_token,
                    "digest": operation_digest,
                    "user_id": user_id,
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                    "run_id": int(validation_run.lastrowid),
                    "confirmation_digest": uuid4().bytes * 2,
                    "validation_digest": "11" * 32,
                },
            )
            assert review_event.lastrowid is not None
            connection.execute(
                sa.text(
                    """
                    INSERT INTO review_operation_results (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, result_kind,
                        result_dataset_id, result_version_id, result_status,
                        result_data_revision, result_review_revision,
                        version_review_event_id, completed_at
                    ) VALUES (
                        :token, 'mark_ready', :digest, :user_id, 'applied',
                        :dataset_id, :version_id, 'ready_for_publish',
                        3, 1, :review_event_id, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": operation_token,
                    "digest": operation_digest,
                    "user_id": user_id,
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                    "review_event_id": int(review_event.lastrowid),
                },
            )
        finally:
            transaction.rollback()


def test_stage_six_upgrade_preflight_stops_before_ddl(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.downgrade(alembic_config, "0008")
    user_id: int | None = None
    dataset_id: int | None = None
    version_id: int | None = None
    try:
        with mysql_engine.begin() as connection:
            user_id = _insert_user(connection)
            dataset_id = _insert_dataset(
                connection,
                report_date=date(2097, 6, 2),
            )
            version_id = _insert_version(
                connection,
                dataset_id=dataset_id,
                user_id=user_id,
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO validation_runs (
                        version_id, run_type, data_revision, ruleset_version,
                        status, result
                    ) VALUES (
                        :version_id, 'full', 0, 'stage-six-v1',
                        'succeeded', 'passed'
                    )
                    """
                ),
                {"version_id": version_id},
            )

        with pytest.raises(RuntimeError, match="validation run"):
            command.upgrade(alembic_config, "0009")

        inspector = sa.inspect(mysql_engine)
        assert "publication_command_results" not in inspector.get_table_names()
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0008"
            )
    finally:
        if user_id is not None and dataset_id is not None and version_id is not None:
            with mysql_engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "DELETE FROM validation_runs WHERE version_id = :version_id"
                    ),
                    {"version_id": version_id},
                )
                connection.execute(
                    sa.text("DELETE FROM dataset_versions WHERE id = :version_id"),
                    {"version_id": version_id},
                )
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
                connection.execute(
                    sa.text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )
        command.upgrade(alembic_config, "0028")


def test_stage_six_downgrade_rejects_create_revision_before_ddl(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "0028")
    command.downgrade(alembic_config, "0009")
    operation_token = uuid4().bytes
    user_id: int | None = None
    try:
        with mysql_engine.begin() as connection:
            user_id = _insert_user(connection)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :token, 'create_revision', :digest,
                        :user_id, CURRENT_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": operation_token,
                    "digest": uuid4().bytes * 2,
                    "user_id": user_id,
                },
            )

        with pytest.raises(RuntimeError, match="create-revision draft operation token"):
            command.downgrade(alembic_config, "0008")

        inspector = sa.inspect(mysql_engine)
        assert "create_revision_parent_version_id" in {
            column["name"]
            for column in inspector.get_columns("draft_operation_results")
        }
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0009"
            )
    finally:
        if user_id is not None:
            with mysql_engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "DELETE FROM draft_operation_tokens "
                        "WHERE operation_token = :token"
                    ),
                    {"token": operation_token},
                )
                connection.execute(
                    sa.text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )
        command.upgrade(alembic_config, "0028")
