"""Harden review lineage, idempotent publication, and terminal writes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import mysql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_TABLE_OPTIONS: dict[str, Any] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _id_type() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _code_type(length: int) -> mysql.VARCHAR:
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def _timestamp_type() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def _assert_no_rows(*, label: str, query: str) -> None:
    if context.is_offline_mode():
        return
    count = op.get_bind().scalar(sa.text(query))
    if count:
        raise RuntimeError(
            f"0009 migration preflight rejected {count} {label}; "
            "resolve the incompatible data before retrying"
        )


def _assert_trigger_creation_policy() -> None:
    """Fail before non-transactional DDL when MySQL would reject triggers."""

    if context.is_offline_mode():
        return
    bind = op.get_bind()
    log_bin, trust_function_creators = bind.execute(
        sa.text(
            "SELECT @@GLOBAL.log_bin, "
            "@@GLOBAL.log_bin_trust_function_creators"
        )
    ).one()
    if int(log_bin) != 0 and int(trust_function_creators) != 1:
        raise RuntimeError(
            "0009 migration preflight requires "
            "log_bin_trust_function_creators=ON while binary logging is enabled; "
            "ask a MySQL administrator to configure the server and do not grant "
            "SUPER to the migration account"
        )
    trigger_privileges = bind.scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM information_schema.schema_privileges
            WHERE table_schema = DATABASE()
              AND privilege_type = 'TRIGGER'
              AND grantee = CONCAT(
                  CHAR(39), SUBSTRING_INDEX(CURRENT_USER(), '@', 1),
                  CHAR(39), '@', CHAR(39),
                  SUBSTRING_INDEX(CURRENT_USER(), '@', -1), CHAR(39)
              )
            """
        )
    )
    if int(trigger_privileges or 0) == 0:
        raise RuntimeError(
            "0009 migration preflight requires the migration account to have "
            "TRIGGER on this database; grant only TRIGGER on the application "
            "database and do not grant SUPER"
        )


_STAGE_SIX_NEW_TABLES = frozenset(
    {
        "note_threads",
        "publication_command_results",
        "review_operation_results",
        "review_operation_tokens",
        "terminal_write_guard_bypass_accounts",
        "version_review_events",
    }
)


def _has_recoverable_partial_upgrade() -> bool:
    """Detect only the post-DDL/pre-trigger interruption this migration can repair."""

    if context.is_offline_mode():
        return False
    rows = {
        str(value)
        for value in op.get_bind().scalars(
            sa.text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                  AND table_name IN (
                      'note_threads',
                      'publication_command_results',
                      'review_operation_results',
                      'review_operation_tokens',
                      'terminal_write_guard_bypass_accounts',
                      'version_review_events'
                  )
                """
            )
        )
    }
    if not rows:
        return False
    if rows != _STAGE_SIX_NEW_TABLES:
        raise RuntimeError(
            "0009 detected a partial upgrade before its terminal-write schema "
            "was complete; restore the test database or repair it explicitly "
            "before retrying"
        )
    return True


def _assert_upgrade_preconditions() -> None:
    """Reject data that cannot be hardened without inventing history."""

    _assert_no_rows(
        label="validation run(s) without a complete terminal result",
        query="""
            SELECT COUNT(*)
            FROM validation_runs
            WHERE status NOT IN ('succeeded', 'failed')
               OR result IS NULL
               OR data_digest IS NULL
               OR summary_json IS NULL
               OR completed_at IS NULL
               OR completed_at < started_at
               OR (status = 'succeeded' AND result NOT IN ('passed', 'failed'))
               OR (status = 'failed' AND result <> 'error')
        """,
    )
    _assert_no_rows(
        label="data change event(s) without exactly one matching subtype",
        query="""
            SELECT COUNT(*)
            FROM data_change_events AS events
            LEFT JOIN field_changes AS fields
                ON fields.version_id = events.version_id
               AND fields.id = events.id
            LEFT JOIN row_changes AS row_events
                ON row_events.version_id = events.version_id
               AND row_events.id = events.id
            WHERE (
                    events.event_kind = 'field'
                    AND (fields.id IS NULL OR row_events.id IS NOT NULL)
                  )
               OR (
                    events.event_kind = 'row'
                    AND (row_events.id IS NULL OR fields.id IS NOT NULL)
                  )
        """,
    )
    _assert_no_rows(
        label="data change event(s) with an invalid revision sequence",
        query="""
            SELECT COUNT(*)
            FROM data_change_events
            WHERE sequence_number = 0
               OR data_revision = 0
               OR sequence_number <> data_revision
               OR CHAR_LENGTH(TRIM(reason)) = 0
        """,
    )
    _assert_no_rows(
        label="duplicate data change revision(s)",
        query="""
            SELECT COUNT(*)
            FROM (
                SELECT version_id, data_revision
                FROM data_change_events
                GROUP BY version_id, data_revision
                HAVING COUNT(*) > 1
            ) AS duplicate_revisions
        """,
    )
    _assert_no_rows(
        label="field change(s) without complete value snapshots",
        query="""
            SELECT COUNT(*)
            FROM field_changes
            WHERE before_value_json IS NULL OR after_value_json IS NULL
        """,
    )
    _assert_no_rows(
        label="row change(s) without complete value snapshots",
        query="""
            SELECT COUNT(*)
            FROM row_changes
            WHERE before_value_json IS NULL OR after_value_json IS NULL
        """,
    )
    _assert_no_rows(
        label="restore-source field change(s) without a source row",
        query="""
            SELECT COUNT(*)
            FROM field_changes AS changes
            INNER JOIN version_rows AS version_row
                ON version_row.version_id = changes.version_id
               AND version_row.id = changes.row_id
            WHERE changes.operation = 'restore_source'
              AND version_row.original_parsed_source_row_id IS NULL
        """,
    )
    _assert_no_rows(
        label="restore-previous field change(s) without a prior field change",
        query="""
            SELECT COUNT(*)
            FROM field_changes AS current_changes
            INNER JOIN data_change_events AS current_events
                ON current_events.version_id = current_changes.version_id
               AND current_events.id = current_changes.id
            WHERE current_changes.operation = 'restore_previous'
              AND NOT EXISTS (
                    SELECT 1
                    FROM field_changes AS previous_changes
                    INNER JOIN data_change_events AS previous_events
                        ON previous_events.version_id = previous_changes.version_id
                       AND previous_events.id = previous_changes.id
                    WHERE previous_changes.version_id = current_changes.version_id
                      AND previous_changes.row_id = current_changes.row_id
                      AND previous_changes.field_name = current_changes.field_name
                      AND previous_events.data_revision <
                          current_events.data_revision
              )
        """,
    )
    _assert_no_rows(
        label="restore-parent field change(s) without exactly one parent version",
        query="""
            SELECT COUNT(*)
            FROM field_changes AS changes
            LEFT JOIN (
                SELECT child_version_id, COUNT(*) AS parent_count
                FROM version_parent_versions
                GROUP BY child_version_id
            ) AS parents
                ON parents.child_version_id = changes.version_id
            WHERE changes.operation = 'restore_baseline'
              AND COALESCE(parents.parent_count, 0) <> 1
        """,
    )
    _assert_no_rows(
        label="duplicate child-parent version lineage relation(s)",
        query="""
            SELECT COUNT(*)
            FROM (
                SELECT child_version_id, parent_version_id
                FROM version_parent_versions
                GROUP BY child_version_id, parent_version_id
                HAVING COUNT(*) > 1
            ) AS duplicate_parent_relations
        """,
    )
    _assert_no_rows(
        label="issue review event(s) with invalid kind or required comment",
        query="""
            SELECT COUNT(*)
            FROM issue_review_events AS events
            INNER JOIN validation_issues AS issues
                ON issues.version_id = events.version_id
               AND issues.validation_run_id = events.validation_run_id
               AND issues.id = events.validation_issue_id
            WHERE (events.event_type = 'acknowledge' AND issues.severity <> 'warning')
               OR (events.event_type IN ('resolve', 'reopen')
                   AND issues.severity <> 'blocking')
               OR (events.event_type = 'resolve'
                   AND (events.comment IS NULL
                        OR CHAR_LENGTH(TRIM(events.comment)) = 0))
               OR (events.event_type = 'acknowledge'
                   AND issues.requires_note = TRUE
                   AND (events.comment IS NULL
                        OR CHAR_LENGTH(TRIM(events.comment)) = 0))
               OR events.sequence_number = 0
               OR events.review_revision = 0
        """,
    )
    _assert_no_rows(
        label="publication pointer(s) targeting a non-published version",
        query="""
            SELECT COUNT(*)
            FROM dataset_publications AS publications
            INNER JOIN dataset_versions AS versions
                ON versions.dataset_id = publications.dataset_id
               AND versions.id = publications.version_id
            WHERE versions.status <> 'published'
        """,
    )
    _assert_no_rows(
        label="legacy publication command(s) without a canonical digest",
        query="SELECT COUNT(*) FROM publication_commands",
    )
    _assert_no_rows(
        label="note revision(s) with an empty body",
        query="""
            SELECT COUNT(*)
            FROM notes
            WHERE CHAR_LENGTH(TRIM(body)) = 0
        """,
    )
    _assert_no_rows(
        label="note revision(s) with a discontinuous or retargeted predecessor",
        query="""
            SELECT COUNT(*)
            FROM notes AS current_notes
            LEFT JOIN notes AS previous_notes
                ON previous_notes.note_key = current_notes.note_key
               AND previous_notes.id = current_notes.supersedes_note_id
            WHERE current_notes.revision_number > 1
              AND (
                    previous_notes.id IS NULL
                    OR previous_notes.revision_number + 1 <>
                        current_notes.revision_number
                    OR NOT (
                        previous_notes.target_type <=> current_notes.target_type
                    )
                    OR NOT (
                        previous_notes.import_batch_id <=>
                        current_notes.import_batch_id
                    )
                    OR NOT (
                        previous_notes.version_id <=> current_notes.version_id
                    )
                    OR NOT (previous_notes.row_id <=> current_notes.row_id)
                    OR NOT (
                        previous_notes.field_name <=> current_notes.field_name
                    )
                  )
        """,
    )


def _assert_downgrade_preconditions() -> None:
    """Refuse to discard identities or source lineage introduced by 0009."""

    _assert_no_rows(
        label="published-move draft operation result(s) that 0008 cannot represent",
        query="""
            SELECT COUNT(*)
            FROM draft_operation_results
            WHERE operation_kind = 'create_published_move_revision'
        """,
    )
    _assert_no_rows(
        label="published-move draft operation token(s) that 0008 cannot represent",
        query="""
            SELECT COUNT(*)
            FROM draft_operation_tokens
            WHERE operation_kind = 'create_published_move_revision'
        """,
    )
    _assert_no_rows(
        label="create-revision draft operation result(s) that 0008 cannot represent",
        query="""
            SELECT COUNT(*)
            FROM draft_operation_results
            WHERE operation_kind = 'create_revision'
        """,
    )
    _assert_no_rows(
        label="create-revision draft operation token(s) that 0008 cannot represent",
        query="""
            SELECT COUNT(*)
            FROM draft_operation_tokens
            WHERE operation_kind = 'create_revision'
        """,
    )
    for table_name, label in (
        ("publication_command_results", "publication command result(s)"),
        ("publication_commands", "publication command token(s)"),
        ("review_operation_results", "review operation result(s)"),
        ("version_review_events", "version review event(s)"),
        ("review_operation_tokens", "review operation token(s)"),
    ):
        _assert_no_rows(
            label=f"{label} that would lose its immutable identity",
            query=f"SELECT COUNT(*) FROM {table_name}",
        )
    _assert_no_rows(
        label="validation issue lineage relation(s) that 0008 cannot represent",
        query="""
            SELECT COUNT(*)
            FROM validation_issues
            WHERE import_batch_id IS NOT NULL
               OR parse_attempt_id IS NOT NULL
               OR parsed_source_row_id IS NOT NULL
               OR parse_baseline_id IS NOT NULL
               OR parse_baseline_row_id IS NOT NULL
        """,
    )
    _assert_no_rows(
        label="orphan note thread(s) that 0008 cannot represent",
        query="""
            SELECT COUNT(*)
            FROM note_threads AS threads
            LEFT JOIN notes ON notes.note_key = threads.note_key
            WHERE notes.id IS NULL
        """,
    )


def _create_immutable_trigger(table_name: str, operation: str) -> None:
    trigger_name = f"trg_{table_name}_no_{operation.lower()}"
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE {operation} ON {table_name}
            FOR EACH ROW
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM terminal_write_guard_bypass_accounts
                    WHERE account_identity = USER()
                ) THEN
                    SIGNAL SQLSTATE '45000'
                        SET MESSAGE_TEXT = '{table_name} is immutable';
                END IF;
            END
            """
        )
    )


def _create_row_guard_trigger(
    *,
    trigger_name: str,
    table_name: str,
    operation: str,
    version_predicate: str,
) -> None:
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE {operation} ON {table_name}
            FOR EACH ROW
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM terminal_write_guard_bypass_accounts
                    WHERE account_identity = USER()
                ) AND EXISTS (
                    SELECT 1
                    FROM dataset_versions
                    WHERE {version_predicate}
                      AND status IN ('published', 'discarded')
                ) THEN
                    SIGNAL SQLSTATE '45000'
                        SET MESSAGE_TEXT =
                            'terminal dataset version rows are immutable';
                END IF;
            END
            """
        )
    )


def _create_write_guard_triggers() -> None:
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_dataset_versions_terminal_update
            BEFORE UPDATE ON dataset_versions
            FOR EACH ROW
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM terminal_write_guard_bypass_accounts
                    WHERE account_identity = USER()
                ) THEN
                    IF OLD.status IN ('published', 'discarded') THEN
                        SIGNAL SQLSTATE '45000'
                            SET MESSAGE_TEXT =
                                'terminal dataset versions are immutable';
                    END IF;
                    IF NOT (
                        NEW.status = OLD.status
                        OR (OLD.status = 'draft'
                            AND NEW.status IN ('ready_for_publish', 'discarded'))
                        OR (OLD.status = 'ready_for_publish'
                            AND NEW.status IN ('draft', 'published', 'discarded'))
                    ) THEN
                        SIGNAL SQLSTATE '45000'
                            SET MESSAGE_TEXT = 'invalid dataset version transition';
                    END IF;
                    IF NEW.data_revision < OLD.data_revision
                       OR NEW.review_revision < OLD.review_revision THEN
                        SIGNAL SQLSTATE '45000'
                            SET MESSAGE_TEXT = 'dataset revisions cannot decrease';
                    END IF;
                    IF NOT (NEW.dataset_id <=> OLD.dataset_id)
                       OR NOT (NEW.report_type <=> OLD.report_type)
                       OR NOT (NEW.version_no <=> OLD.version_no)
                       OR NOT (NEW.ruleset_version <=> OLD.ruleset_version)
                       OR NOT (NEW.created_by <=> OLD.created_by)
                       OR NOT (NEW.created_at <=> OLD.created_at) THEN
                        SIGNAL SQLSTATE '45000'
                            SET MESSAGE_TEXT = 'dataset version identity is immutable';
                    END IF;
                END IF;
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_dataset_versions_terminal_delete
            BEFORE DELETE ON dataset_versions
            FOR EACH ROW
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM terminal_write_guard_bypass_accounts
                    WHERE account_identity = USER()
                ) AND OLD.status IN ('published', 'discarded') THEN
                    SIGNAL SQLSTATE '45000'
                        SET MESSAGE_TEXT = 'terminal dataset versions are immutable';
                END IF;
            END
            """
        )
    )

    row_tables = (
        ("version_rows", "version_rows"),
        ("business_rows", "business_report_rows"),
        ("return_rows", "return_report_rows"),
    )
    for trigger_prefix, table_name in row_tables:
        _create_row_guard_trigger(
            trigger_name=f"trg_{trigger_prefix}_terminal_insert",
            table_name=table_name,
            operation="INSERT",
            version_predicate="id = NEW.version_id",
        )
        _create_row_guard_trigger(
            trigger_name=f"trg_{trigger_prefix}_terminal_update",
            table_name=table_name,
            operation="UPDATE",
            version_predicate="id IN (OLD.version_id, NEW.version_id)",
        )
        _create_row_guard_trigger(
            trigger_name=f"trg_{trigger_prefix}_terminal_delete",
            table_name=table_name,
            operation="DELETE",
            version_predicate="id = OLD.version_id",
        )

    for table_name in (
        "validation_runs",
        "validation_issues",
        "publication_commands",
        "publication_command_results",
        "review_operation_tokens",
        "review_operation_results",
        "version_review_events",
        "note_threads",
        "notes",
    ):
        _create_immutable_trigger(table_name, "UPDATE")
        _create_immutable_trigger(table_name, "DELETE")


def _trigger_names() -> Iterable[str]:
    yield "trg_dataset_versions_terminal_update"
    yield "trg_dataset_versions_terminal_delete"
    for trigger_prefix in ("version_rows", "business_rows", "return_rows"):
        for operation in ("insert", "update", "delete"):
            yield f"trg_{trigger_prefix}_terminal_{operation}"
    for table_name in (
        "validation_runs",
        "validation_issues",
        "publication_commands",
        "publication_command_results",
        "review_operation_tokens",
        "review_operation_results",
        "version_review_events",
        "note_threads",
        "notes",
    ):
        yield f"trg_{table_name}_no_update"
        yield f"trg_{table_name}_no_delete"


def _drop_write_guard_triggers() -> None:
    for trigger_name in _trigger_names():
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger_name}"))


def upgrade() -> None:
    _assert_trigger_creation_policy()
    if _has_recoverable_partial_upgrade():
        _drop_write_guard_triggers()
        _create_write_guard_triggers()
        return
    _assert_upgrade_preconditions()

    op.create_table(
        "terminal_write_guard_bypass_accounts",
        sa.Column("account_identity", sa.String(length=288), nullable=False),
        sa.Column(
            "registered_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "account_identity",
            name="pk_terminal_write_guard_bypass_accounts",
        ),
        **_TABLE_OPTIONS,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO terminal_write_guard_bypass_accounts (account_identity)
            VALUES (USER())
            """
        )
    )

    op.create_unique_constraint(
        "uq_dce_version_id_kind",
        "data_change_events",
        ["version_id", "id", "event_kind"],
    )
    op.create_unique_constraint(
        "uq_dce_version_data_revision",
        "data_change_events",
        ["version_id", "data_revision"],
    )
    op.create_check_constraint(
        "ck_dce_revision_sequence",
        "data_change_events",
        "sequence_number > 0 AND data_revision > 0 "
        "AND sequence_number = data_revision",
    )
    op.create_check_constraint(
        "ck_dce_reason_nonempty",
        "data_change_events",
        "CHAR_LENGTH(TRIM(reason)) > 0",
    )
    op.create_unique_constraint(
        "uq_version_rows_restore_source",
        "version_rows",
        ["version_id", "id", "original_parsed_source_row_id"],
    )
    op.create_unique_constraint(
        "uq_vpv_child_parent",
        "version_parent_versions",
        ["child_version_id", "parent_version_id"],
    )
    op.drop_constraint(
        "ck_draft_operation_tokens_kind",
        "draft_operation_tokens",
        type_="check",
    )
    op.create_check_constraint(
        "ck_draft_operation_tokens_kind",
        "draft_operation_tokens",
        "operation_kind IN "
        "('materialize_baseline', 'force_rebuild', 'discard_draft', "
        "'reassign_date', 'create_revision', "
        "'create_published_move_revision')",
    )
    op.drop_constraint(
        "ck_draft_operation_results_kind",
        "draft_operation_results",
        type_="check",
    )
    op.create_check_constraint(
        "ck_draft_operation_results_kind",
        "draft_operation_results",
        "result_kind IN "
        "('created', 'merged', 'replaced', 'discarded', "
        "'force_discarded', 'reassigned', 'force_rebuilt', 'cancelled', "
        "'move_revision_created')",
    )
    op.add_column(
        "draft_operation_results",
        sa.Column("create_revision_parent_version_id", _id_type(), nullable=True),
    )
    op.add_column(
        "draft_operation_results",
        sa.Column(
            "published_move_source_parent_version_id",
            _id_type(),
            nullable=True,
        ),
    )
    op.add_column(
        "draft_operation_results",
        sa.Column(
            "published_move_source_lineage_type",
            _code_type(32),
            nullable=True,
        ),
    )
    op.drop_constraint(
        "ck_draft_operation_results_semantics",
        "draft_operation_results",
        type_="check",
    )
    op.create_check_constraint(
        "ck_draft_operation_results_semantics",
        "draft_operation_results",
        "((operation_kind = 'materialize_baseline' "
        "AND result_kind IN ('created', 'merged', 'replaced') "
        "AND result_status = 'draft') OR "
        "(operation_kind = 'force_rebuild' "
        "AND result_kind = 'force_rebuilt' "
        "AND result_status = 'draft') OR "
        "(operation_kind = 'discard_draft' "
        "AND result_kind IN ('discarded', 'force_discarded') "
        "AND result_status = 'discarded') OR "
        "(operation_kind = 'reassign_date' "
        "AND ((result_kind = 'reassigned' AND result_status = 'draft') "
        "OR (result_kind = 'cancelled' "
        "AND result_status = 'cancelled'))) OR "
        "(operation_kind = 'create_revision' "
        "AND result_kind = 'created' AND result_status = 'draft' "
        "AND source_dataset_id IS NOT NULL "
        "AND source_version_id IS NOT NULL "
        "AND source_dataset_id = result_dataset_id "
        "AND source_version_id <> result_version_id "
        "AND superseded_version_id_1 IS NULL "
        "AND superseded_version_id_2 IS NULL) OR "
        "(operation_kind = 'create_published_move_revision' "
        "AND ((result_kind = 'move_revision_created' "
        "AND result_status = 'draft' "
        "AND result_data_revision = 0 AND result_review_revision = 0 "
        "AND source_dataset_id IS NOT NULL "
        "AND source_version_id IS NOT NULL "
        "AND source_dataset_id <> result_dataset_id "
        "AND source_version_id <> result_version_id "
        "AND superseded_version_id_2 IS NULL) OR "
        "(result_kind = 'cancelled' AND result_status = 'cancelled' "
        "AND source_dataset_id IS NULL AND source_version_id IS NULL "
        "AND superseded_version_id_1 IS NULL "
        "AND superseded_version_id_2 IS NULL))))",
    )
    op.create_check_constraint(
        "ck_draft_operation_results_create_revision_parent",
        "draft_operation_results",
        "((operation_kind = 'create_revision' "
        "AND create_revision_parent_version_id IS NOT NULL "
        "AND create_revision_parent_version_id = source_version_id) OR "
        "(operation_kind <> 'create_revision' "
        "AND create_revision_parent_version_id IS NULL))",
    )
    op.create_index(
        "ix_draft_operation_results_create_revision_parent",
        "draft_operation_results",
        ["result_version_id", "create_revision_parent_version_id"],
    )
    op.create_foreign_key(
        "fk_draft_operation_results_create_revision_parent",
        "draft_operation_results",
        "version_parent_versions",
        ["result_version_id", "create_revision_parent_version_id"],
        ["child_version_id", "parent_version_id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_check_constraint(
        "ck_draft_operation_results_published_move_source",
        "draft_operation_results",
        "((operation_kind = 'create_published_move_revision' "
        "AND result_kind = 'move_revision_created' "
        "AND published_move_source_parent_version_id IS NOT NULL "
        "AND published_move_source_parent_version_id = source_version_id "
        "AND published_move_source_lineage_type = 'moved_source') OR "
        "((operation_kind <> 'create_published_move_revision' "
        "OR result_kind <> 'move_revision_created') "
        "AND published_move_source_parent_version_id IS NULL "
        "AND published_move_source_lineage_type IS NULL))",
    )
    op.create_index(
        "ix_draft_operation_results_published_move_source",
        "draft_operation_results",
        [
            "result_version_id",
            "published_move_source_parent_version_id",
            "published_move_source_lineage_type",
        ],
    )
    op.create_foreign_key(
        "fk_draft_operation_results_published_move_source",
        "draft_operation_results",
        "version_parent_versions",
        [
            "result_version_id",
            "published_move_source_parent_version_id",
            "published_move_source_lineage_type",
        ],
        ["child_version_id", "parent_version_id", "lineage_type"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_draft_operation_results_move_version",
        "draft_operation_results",
        ["operation_token", "result_dataset_id", "result_version_id"],
    )
    op.drop_constraint(
        "ck_draft_disposition_events_operation_kind",
        "draft_disposition_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_draft_disposition_events_operation_kind",
        "draft_disposition_events",
        "((event_type IN ('discarded', 'force_discarded') "
        "AND operation_kind = 'discard_draft') OR "
        "(event_type = 'force_rebuilt' "
        "AND operation_kind IN "
        "('force_rebuild', 'create_published_move_revision')) OR "
        "(event_type = 'date_reassigned' "
        "AND operation_kind = 'reassign_date') OR "
        "(event_type = 'superseded' "
        "AND operation_kind IN "
        "('materialize_baseline', 'reassign_date', "
        "'create_published_move_revision')))"
    )
    op.create_unique_constraint(
        "uq_field_changes_restore_previous",
        "field_changes",
        ["version_id", "row_id", "field_name", "id"],
    )
    for table_name, event_kind in (
        ("field_changes", "field"),
        ("row_changes", "row"),
    ):
        op.add_column(
            table_name,
            sa.Column("event_kind", sa.String(length=16), nullable=True),
        )
        op.execute(
            sa.text(
                f"UPDATE {table_name} SET event_kind = '{event_kind}'"
            )
        )
        op.alter_column(
            table_name,
            "event_kind",
            existing_type=sa.String(length=16),
            nullable=False,
        )
        op.create_check_constraint(
            f"ck_{table_name}_event_kind",
            table_name,
            f"event_kind = '{event_kind}'",
        )
        op.create_index(
            f"ix_{table_name}_event_kind",
            table_name,
            ["version_id", "id", "event_kind"],
        )

    for column_name in (
        "restored_field_change_id",
        "restored_parent_version_id",
        "restored_source_row_id",
    ):
        op.add_column(
            "field_changes",
            sa.Column(column_name, _id_type(), nullable=True),
        )
    op.execute(
        sa.text(
            """
            UPDATE field_changes AS current_changes
            INNER JOIN (
                SELECT ranked_changes.id, ranked_changes.previous_change_id
                FROM (
                    SELECT changes.id,
                           LAG(changes.id) OVER (
                               PARTITION BY changes.version_id,
                                            changes.row_id,
                                            changes.field_name
                               ORDER BY events.data_revision, changes.id
                           ) AS previous_change_id
                    FROM field_changes AS changes
                    INNER JOIN data_change_events AS events
                        ON events.version_id = changes.version_id
                       AND events.id = changes.id
                ) AS ranked_changes
            ) AS inferred_lineage
                ON inferred_lineage.id = current_changes.id
            SET current_changes.restored_field_change_id =
                inferred_lineage.previous_change_id
            WHERE current_changes.operation = 'restore_previous'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE field_changes AS changes
            INNER JOIN version_parent_versions AS lineage
                ON lineage.child_version_id = changes.version_id
            SET changes.restored_parent_version_id = lineage.parent_version_id
            WHERE changes.operation = 'restore_baseline'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE field_changes AS changes
            INNER JOIN version_rows AS version_row
                ON version_row.version_id = changes.version_id
               AND version_row.id = changes.row_id
            SET changes.restored_source_row_id =
                version_row.original_parsed_source_row_id
            WHERE changes.operation = 'restore_source'
            """
        )
    )
    op.drop_constraint(
        "ck_field_changes_operation",
        "field_changes",
        type_="check",
    )
    op.execute(
        sa.text(
            """
            UPDATE field_changes
            SET operation = 'restore_parent'
            WHERE operation = 'restore_baseline'
            """
        )
    )
    op.create_check_constraint(
        "ck_field_changes_operation",
        "field_changes",
        "operation IN "
        "('set', 'restore_source', 'restore_parent', 'restore_previous')",
    )
    op.alter_column(
        "field_changes",
        "before_value_json",
        existing_type=mysql.JSON(),
        nullable=False,
    )
    op.alter_column(
        "field_changes",
        "after_value_json",
        existing_type=mysql.JSON(),
        nullable=False,
    )
    op.alter_column(
        "row_changes",
        "before_value_json",
        existing_type=mysql.JSON(),
        nullable=False,
    )
    op.alter_column(
        "row_changes",
        "after_value_json",
        existing_type=mysql.JSON(),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_field_changes_restore_lineage",
        "field_changes",
        "((operation = 'set' AND restored_field_change_id IS NULL "
        "AND restored_parent_version_id IS NULL "
        "AND restored_source_row_id IS NULL) OR "
        "(operation = 'restore_previous' "
        "AND restored_field_change_id IS NOT NULL "
        "AND restored_field_change_id <> id "
        "AND restored_parent_version_id IS NULL "
        "AND restored_source_row_id IS NULL) OR "
        "(operation = 'restore_parent' "
        "AND restored_field_change_id IS NULL "
        "AND restored_parent_version_id IS NOT NULL "
        "AND restored_source_row_id IS NULL) OR "
        "(operation = 'restore_source' "
        "AND restored_field_change_id IS NULL "
        "AND restored_parent_version_id IS NULL "
        "AND restored_source_row_id IS NOT NULL))",
    )
    op.create_foreign_key(
        "fk_field_changes_restore_previous",
        "field_changes",
        "field_changes",
        ["version_id", "row_id", "field_name", "restored_field_change_id"],
        ["version_id", "row_id", "field_name", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_field_changes_restore_parent",
        "field_changes",
        "version_parent_versions",
        ["version_id", "restored_parent_version_id"],
        ["child_version_id", "parent_version_id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_field_changes_restore_source",
        "field_changes",
        "version_rows",
        ["version_id", "row_id", "restored_source_row_id"],
        ["version_id", "id", "original_parsed_source_row_id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_field_changes_event_kind",
        "field_changes",
        "data_change_events",
        ["version_id", "id", "event_kind"],
        ["version_id", "id", "event_kind"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.drop_constraint(
        "fk_field_changes_change_event",
        "field_changes",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_row_changes_event_kind",
        "row_changes",
        "data_change_events",
        ["version_id", "id", "event_kind"],
        ["version_id", "id", "event_kind"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.drop_constraint(
        "fk_row_changes_change_event",
        "row_changes",
        type_="foreignkey",
    )

    op.drop_constraint("ck_validation_runs_status", "validation_runs", type_="check")
    op.drop_constraint("ck_validation_runs_result", "validation_runs", type_="check")
    op.alter_column(
        "validation_runs",
        "status",
        existing_type=sa.String(length=24),
        existing_server_default=sa.text("'running'"),
        server_default=None,
        nullable=False,
    )
    op.alter_column(
        "validation_runs",
        "result",
        existing_type=sa.String(length=24),
        nullable=False,
    )
    op.alter_column(
        "validation_runs",
        "data_digest",
        existing_type=mysql.BINARY(length=32),
        nullable=False,
    )
    op.alter_column(
        "validation_runs",
        "summary_json",
        existing_type=mysql.JSON(),
        nullable=False,
    )
    op.alter_column(
        "validation_runs",
        "completed_at",
        existing_type=_timestamp_type(),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_validation_runs_terminal",
        "validation_runs",
        "completed_at >= started_at AND "
        "((status = 'succeeded' AND result IN ('passed', 'failed')) OR "
        "(status = 'failed' AND result = 'error'))",
    )

    op.create_unique_constraint(
        "uq_parse_baselines_attempt_id",
        "parse_baselines",
        ["parse_attempt_id", "id"],
    )
    op.create_unique_constraint(
        "uq_pbr_attempt_baseline_id",
        "parse_baseline_rows",
        ["parse_attempt_id", "parse_baseline_id", "id"],
    )
    for column_name in (
        "import_batch_id",
        "parse_attempt_id",
        "parsed_source_row_id",
        "parse_baseline_id",
        "parse_baseline_row_id",
    ):
        op.add_column(
            "validation_issues",
            sa.Column(column_name, _id_type(), nullable=True),
        )
    op.create_index(
        "ix_validation_issues_attempt",
        "validation_issues",
        ["import_batch_id", "parse_attempt_id"],
    )
    op.create_index(
        "ix_validation_issues_source_row",
        "validation_issues",
        ["parse_attempt_id", "parsed_source_row_id"],
    )
    op.create_index(
        "ix_validation_issues_baseline_row",
        "validation_issues",
        ["parse_attempt_id", "parse_baseline_id", "parse_baseline_row_id"],
    )
    op.create_foreign_key(
        "fk_validation_issues_attempt",
        "validation_issues",
        "parse_attempts",
        ["import_batch_id", "parse_attempt_id"],
        ["batch_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_validation_issues_source_row",
        "validation_issues",
        "parsed_source_rows",
        ["parse_attempt_id", "parsed_source_row_id"],
        ["parse_attempt_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_validation_issues_baseline",
        "validation_issues",
        "parse_baselines",
        ["parse_attempt_id", "parse_baseline_id"],
        ["parse_attempt_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_validation_issues_baseline_row",
        "validation_issues",
        "parse_baseline_rows",
        ["parse_attempt_id", "parse_baseline_id", "parse_baseline_row_id"],
        ["parse_attempt_id", "parse_baseline_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_check_constraint(
        "ck_validation_issues_lineage",
        "validation_issues",
        "((parse_attempt_id IS NULL AND import_batch_id IS NULL "
        "AND parsed_source_row_id IS NULL AND parse_baseline_id IS NULL "
        "AND parse_baseline_row_id IS NULL) OR "
        "(parse_attempt_id IS NOT NULL AND import_batch_id IS NOT NULL "
        "AND (parse_baseline_row_id IS NULL OR parse_baseline_id IS NOT NULL))) "
        "AND (field_name IS NULL OR row_id IS NOT NULL "
        "OR parsed_source_row_id IS NOT NULL OR parse_baseline_row_id IS NOT NULL)",
    )

    op.create_unique_constraint(
        "uq_validation_issues_review_kind",
        "validation_issues",
        [
            "version_id",
            "validation_run_id",
            "id",
            "severity",
            "requires_note",
        ],
    )
    op.add_column(
        "issue_review_events",
        sa.Column("issue_severity", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "issue_review_events",
        sa.Column("issue_requires_note", sa.Boolean(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE issue_review_events AS events
            INNER JOIN validation_issues AS issues
                ON issues.version_id = events.version_id
               AND issues.validation_run_id = events.validation_run_id
               AND issues.id = events.validation_issue_id
            SET events.issue_severity = issues.severity,
                events.issue_requires_note = issues.requires_note
            """
        )
    )
    op.alter_column(
        "issue_review_events",
        "issue_severity",
        existing_type=sa.String(length=16),
        nullable=False,
    )
    op.alter_column(
        "issue_review_events",
        "issue_requires_note",
        existing_type=sa.Boolean(),
        nullable=False,
    )
    op.create_index(
        "ix_issue_review_events_issue_kind",
        "issue_review_events",
        [
            "version_id",
            "validation_run_id",
            "validation_issue_id",
            "issue_severity",
            "issue_requires_note",
        ],
    )
    op.create_foreign_key(
        "fk_issue_review_events_issue_kind",
        "issue_review_events",
        "validation_issues",
        [
            "version_id",
            "validation_run_id",
            "validation_issue_id",
            "issue_severity",
            "issue_requires_note",
        ],
        ["version_id", "validation_run_id", "id", "severity", "requires_note"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.drop_constraint(
        "fk_issue_review_events_issue_run",
        "issue_review_events",
        type_="foreignkey",
    )
    op.create_check_constraint(
        "ck_issue_review_events_kind",
        "issue_review_events",
        "((event_type = 'acknowledge' AND issue_severity = 'warning') OR "
        "(event_type IN ('resolve', 'reopen') AND issue_severity = 'blocking'))",
    )
    op.create_check_constraint(
        "ck_issue_review_events_comment",
        "issue_review_events",
        "((event_type <> 'resolve' AND NOT "
        "(event_type = 'acknowledge' AND issue_requires_note = TRUE)) OR "
        "(comment IS NOT NULL AND CHAR_LENGTH(TRIM(comment)) > 0))",
    )
    op.create_check_constraint(
        "ck_issue_review_events_revision",
        "issue_review_events",
        "sequence_number > 0 AND review_revision > 0",
    )
    op.create_unique_constraint(
        "uq_issue_review_events_version_id",
        "issue_review_events",
        ["version_id", "id"],
    )

    op.create_table(
        "note_threads",
        sa.Column("note_key", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=24), nullable=False),
        sa.Column("import_batch_id", _id_type(), nullable=True),
        sa.Column("version_id", _id_type(), nullable=True),
        sa.Column("row_id", _id_type(), nullable=True),
        sa.Column("field_name", sa.String(length=128), nullable=True),
        sa.Column("created_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint("note_key", name="pk_note_threads"),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batches.id"],
            name="fk_note_threads_import_batch",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["dataset_versions.id"],
            name="fk_note_threads_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "row_id"],
            ["version_rows.version_id", "version_rows.id"],
            name="fk_note_threads_version_row",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "((target_type = 'import_batch' "
            "AND import_batch_id IS NOT NULL AND version_id IS NULL "
            "AND row_id IS NULL AND field_name IS NULL) OR "
            "(target_type = 'version' "
            "AND import_batch_id IS NULL AND version_id IS NOT NULL "
            "AND row_id IS NULL AND field_name IS NULL) OR "
            "(target_type = 'row' "
            "AND import_batch_id IS NULL AND version_id IS NOT NULL "
            "AND row_id IS NOT NULL AND field_name IS NULL) OR "
            "(target_type = 'field' "
            "AND import_batch_id IS NULL AND version_id IS NOT NULL "
            "AND row_id IS NOT NULL AND field_name IS NOT NULL))",
            name="ck_note_threads_target",
        ),
        sa.Index(
            "ix_note_threads_target_version_row",
            "version_id",
            "row_id",
            "note_key",
        ),
        **_TABLE_OPTIONS,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO note_threads (
                note_key, target_type, import_batch_id, version_id,
                row_id, field_name, created_at
            )
            SELECT note_key, target_type, import_batch_id, version_id,
                   row_id, field_name, created_at
            FROM notes
            WHERE revision_number = 1
            """
        )
    )
    op.add_column(
        "notes",
        sa.Column("supersedes_revision_number", _id_type(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE notes AS current_notes
            INNER JOIN notes AS previous_notes
                ON previous_notes.note_key = current_notes.note_key
               AND previous_notes.id = current_notes.supersedes_note_id
            SET current_notes.supersedes_revision_number =
                previous_notes.revision_number
            WHERE current_notes.revision_number > 1
            """
        )
    )
    op.alter_column(
        "notes",
        "visibility",
        existing_type=sa.String(length=24),
        server_default=sa.text("'internal'"),
        existing_nullable=False,
        nullable=False,
    )
    op.create_check_constraint(
        "ck_notes_body_nonempty",
        "notes",
        "CHAR_LENGTH(TRIM(body)) > 0",
    )
    op.drop_constraint(
        "fk_notes_previous_revision",
        "notes",
        type_="foreignkey",
    )
    # MySQL retains the implicit child-column index when a foreign key is
    # dropped.  The replacement foreign key has a different column shape, so
    # the stale same-named index must be removed before MySQL can create the
    # new supporting index.
    op.drop_index("fk_notes_previous_revision", table_name="notes")
    op.drop_constraint(
        "ck_notes_revision_chain",
        "notes",
        type_="check",
    )
    op.create_unique_constraint(
        "uq_notes_key_revision_id",
        "notes",
        ["note_key", "revision_number", "id"],
    )
    op.create_foreign_key(
        "fk_notes_previous_revision",
        "notes",
        "notes",
        ["note_key", "supersedes_revision_number", "supersedes_note_id"],
        ["note_key", "revision_number", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_notes_thread",
        "notes",
        "note_threads",
        ["note_key"],
        ["note_key"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_check_constraint(
        "ck_notes_revision_chain",
        "notes",
        "((revision_number = 1 AND supersedes_note_id IS NULL "
        "AND supersedes_revision_number IS NULL) OR "
        "(revision_number > 1 AND supersedes_note_id IS NOT NULL "
        "AND supersedes_revision_number = revision_number - 1))",
    )
    for constraint_name in (
        "fk_notes_version_row",
        "fk_notes_version",
        "fk_notes_import_batch",
    ):
        op.drop_constraint(constraint_name, "notes", type_="foreignkey")
    op.drop_constraint("ck_notes_target", "notes", type_="check")
    op.drop_index("ix_notes_target_version_row", table_name="notes")
    for column_name in (
        "field_name",
        "row_id",
        "version_id",
        "import_batch_id",
        "target_type",
    ):
        op.drop_column("notes", column_name)

    op.add_column(
        "dataset_publications",
        sa.Column("version_status", _code_type(32), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE dataset_publications
            SET version_status = 'published'
            """
        )
    )
    op.alter_column(
        "dataset_publications",
        "version_status",
        existing_type=_code_type(32),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_dataset_publications_published_status",
        "dataset_publications",
        "version_status = 'published'",
    )
    op.create_index(
        "ix_dataset_publications_version_status",
        "dataset_publications",
        ["dataset_id", "version_id", "version_status"],
    )
    op.create_foreign_key(
        "fk_dataset_publications_published_version",
        "dataset_publications",
        "dataset_versions",
        ["dataset_id", "version_id", "version_status"],
        ["dataset_id", "id", "status"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.drop_constraint(
        "fk_dataset_publications_version",
        "dataset_publications",
        type_="foreignkey",
    )

    # The old unique key is also the supporting child index for the actor
    # foreign key. Rebuild both command-related foreign keys around the key
    # and column migration so MySQL can replace that index safely.
    op.drop_constraint(
        "fk_publication_events_command",
        "publication_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_publication_commands_actor",
        "publication_commands",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_publication_commands_actor_type_key",
        "publication_commands",
        type_="unique",
    )
    op.drop_constraint(
        "ck_publication_commands_type",
        "publication_commands",
        type_="check",
    )
    op.drop_constraint(
        "ck_publication_commands_status",
        "publication_commands",
        type_="check",
    )
    op.add_column(
        "publication_commands",
        sa.Column("operation_digest", mysql.BINARY(32), nullable=True),
    )
    op.alter_column(
        "publication_commands",
        "command_type",
        new_column_name="operation_kind",
        existing_type=sa.String(length=32),
        type_=_code_type(32),
        existing_nullable=False,
        nullable=False,
    )
    op.alter_column(
        "publication_commands",
        "idempotency_key",
        new_column_name="operation_token",
        existing_type=sa.String(length=128),
        type_=mysql.BINARY(16),
        existing_nullable=False,
        nullable=False,
    )
    op.alter_column(
        "publication_commands",
        "created_at",
        new_column_name="registered_at",
        existing_type=_timestamp_type(),
        existing_server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        existing_nullable=False,
        nullable=False,
    )
    op.alter_column(
        "publication_commands",
        "operation_digest",
        existing_type=mysql.BINARY(32),
        nullable=False,
    )
    op.drop_column("publication_commands", "completed_at")
    op.drop_column("publication_commands", "redacted_result_payload")
    op.drop_column("publication_commands", "status")
    op.create_unique_constraint(
        "uq_publication_commands_token",
        "publication_commands",
        ["operation_token"],
    )
    op.create_unique_constraint(
        "uq_publication_commands_identity",
        "publication_commands",
        [
            "id",
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
        ],
    )
    op.create_check_constraint(
        "ck_publication_commands_kind",
        "publication_commands",
        "operation_kind IN "
        "('publish', 'replace', 'rollback', 'withdraw', 'move', 'reverse_move')",
    )
    op.create_foreign_key(
        "fk_publication_commands_actor",
        "publication_commands",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_publication_events_command",
        "publication_events",
        "publication_commands",
        ["command_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_publication_events_command_id",
        "publication_events",
        ["command_id", "id"],
    )
    op.create_table(
        "publication_command_results",
        sa.Column("command_id", _id_type(), nullable=False),
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("result_kind", _code_type(32), nullable=False),
        sa.Column("result_dataset_id", _id_type(), nullable=True),
        sa.Column("result_version_id", _id_type(), nullable=True),
        sa.Column("result_status", _code_type(32), nullable=True),
        sa.Column("result_data_revision", _id_type(), nullable=True),
        sa.Column("result_review_revision", _id_type(), nullable=True),
        sa.Column("validation_run_id", _id_type(), nullable=True),
        sa.Column("publication_event_id", _id_type(), nullable=True),
        sa.Column("move_revision_operation_token", mysql.BINARY(16), nullable=True),
        sa.Column("reversed_move_command_id", _id_type(), nullable=True),
        sa.Column("redacted_result_payload", mysql.JSON(), nullable=False),
        sa.Column("completed_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint("command_id", name="pk_publication_command_results"),
        sa.UniqueConstraint(
            "operation_token",
            name="uq_publication_command_results_token",
        ),
        sa.ForeignKeyConstraint(
            [
                "command_id",
                "operation_token",
                "operation_kind",
                "operation_digest",
                "actor_user_id",
            ],
            [
                "publication_commands.id",
                "publication_commands.operation_token",
                "publication_commands.operation_kind",
                "publication_commands.operation_digest",
                "publication_commands.actor_user_id",
            ],
            name="fk_publication_command_results_identity",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_dataset_id", "result_version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_publication_command_results_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_version_id", "validation_run_id"],
            ["validation_runs.version_id", "validation_runs.id"],
            name="fk_publication_command_results_validation",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["command_id", "publication_event_id"],
            ["publication_events.command_id", "publication_events.id"],
            name="fk_publication_command_results_event",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "move_revision_operation_token",
                "result_dataset_id",
                "result_version_id",
            ],
            [
                "draft_operation_results.operation_token",
                "draft_operation_results.result_dataset_id",
                "draft_operation_results.result_version_id",
            ],
            name="fk_publication_command_results_move_revision",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reversed_move_command_id"],
            ["publication_commands.id"],
            name="fk_publication_command_results_reversed_move",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "result_kind IN "
            "('published', 'replaced', 'rolled_back', 'withdrawn', "
            "'moved', 'move_reversed', 'cancelled')",
            name="ck_publication_command_results_kind",
        ),
        sa.CheckConstraint(
            "((operation_kind = 'publish' "
            "AND result_kind IN ('published', 'cancelled')) "
            "OR (operation_kind = 'replace' "
            "AND result_kind IN ('replaced', 'cancelled')) "
            "OR (operation_kind = 'rollback' "
            "AND result_kind IN ('rolled_back', 'cancelled')) "
            "OR (operation_kind = 'withdraw' "
            "AND result_kind IN ('withdrawn', 'cancelled')) "
            "OR (operation_kind = 'move' AND result_kind IN ('moved', 'cancelled')) "
            "OR (operation_kind = 'reverse_move' "
            "AND result_kind IN ('move_reversed', 'cancelled')))",
            name="ck_publication_command_results_semantics",
        ),
        sa.CheckConstraint(
            "((result_kind = 'cancelled' "
            "AND result_dataset_id IS NULL AND result_version_id IS NULL "
            "AND result_status IS NULL AND result_data_revision IS NULL "
            "AND result_review_revision IS NULL AND validation_run_id IS NULL "
            "AND publication_event_id IS NULL) OR "
            "(result_kind <> 'cancelled' "
            "AND result_dataset_id IS NOT NULL AND result_version_id IS NOT NULL "
            "AND result_status IS NOT NULL AND result_data_revision IS NOT NULL "
            "AND result_review_revision IS NOT NULL "
            "AND publication_event_id IS NOT NULL "
            "AND ((result_kind IN ('published', 'replaced', 'moved') "
            "AND validation_run_id IS NOT NULL) OR "
            "(result_kind NOT IN ('published', 'replaced', 'moved') "
            "AND validation_run_id IS NULL))))",
            name="ck_publication_command_results_lineage",
        ),
        sa.CheckConstraint(
            "((operation_kind = 'move' AND result_kind = 'moved' "
            "AND move_revision_operation_token IS NOT NULL "
            "AND reversed_move_command_id IS NULL) OR "
            "(operation_kind = 'reverse_move' "
            "AND result_kind = 'move_reversed' "
            "AND move_revision_operation_token IS NULL "
            "AND reversed_move_command_id IS NOT NULL "
            "AND reversed_move_command_id <> command_id) OR "
            "(result_kind = 'cancelled' "
            "AND move_revision_operation_token IS NULL "
            "AND reversed_move_command_id IS NULL) OR "
            "(operation_kind NOT IN ('move', 'reverse_move') "
            "AND move_revision_operation_token IS NULL "
            "AND reversed_move_command_id IS NULL))",
            name="ck_publication_command_results_move_lineage",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "review_operation_tokens",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("registered_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint("operation_token", name="pk_review_operation_tokens"),
        sa.UniqueConstraint(
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
            name="uq_review_operation_tokens_identity",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_review_operation_tokens_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation_kind IN "
            "('set_field', 'restore_previous_field', 'restore_parent_field', "
            "'restore_source_field', 'add_row', 'exclude_row', 'restore_row', "
            "'delete_row', 'create_note', 'revise_note', 'review_issue', "
            "'run_validation', 'mark_ready', 'return_to_draft')",
            name="ck_review_operation_tokens_kind",
        ),
        **_TABLE_OPTIONS,
    )
    op.create_table(
        "version_review_events",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("dataset_id", _id_type(), nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column("from_status", _code_type(32), nullable=False),
        sa.Column("to_status", _code_type(32), nullable=False),
        sa.Column("data_revision", _id_type(), nullable=False),
        sa.Column("from_review_revision", _id_type(), nullable=False),
        sa.Column("to_review_revision", _id_type(), nullable=False),
        sa.Column("selected_validation_run_id", _id_type(), nullable=True),
        sa.Column("confirmation_digest", mysql.BINARY(32), nullable=True),
        sa.Column("confirmation_json", mysql.JSON(), nullable=True),
        sa.Column("reason", mysql.LONGTEXT(), nullable=False),
        sa.Column("occurred_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_version_review_events"),
        sa.UniqueConstraint(
            "operation_token",
            name="uq_version_review_events_token",
        ),
        sa.UniqueConstraint(
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
            "dataset_id",
            "version_id",
            "id",
            name="uq_version_review_events_result_identity",
        ),
        sa.ForeignKeyConstraint(
            [
                "operation_token",
                "operation_kind",
                "operation_digest",
                "actor_user_id",
            ],
            [
                "review_operation_tokens.operation_token",
                "review_operation_tokens.operation_kind",
                "review_operation_tokens.operation_digest",
                "review_operation_tokens.actor_user_id",
            ],
            name="fk_version_review_events_token_identity",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_version_review_events_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "selected_validation_run_id"],
            ["validation_runs.version_id", "validation_runs.id"],
            name="fk_version_review_events_validation",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "to_review_revision = from_review_revision + 1",
            name="ck_version_review_events_revision",
        ),
        sa.CheckConstraint(
            "CHAR_LENGTH(TRIM(reason)) > 0",
            name="ck_version_review_events_reason",
        ),
        sa.CheckConstraint(
            "((operation_kind = 'mark_ready' "
            "AND from_status = 'draft' AND to_status = 'ready_for_publish' "
            "AND selected_validation_run_id IS NOT NULL "
            "AND confirmation_digest IS NOT NULL "
            "AND confirmation_json IS NOT NULL "
            "AND JSON_TYPE(confirmation_json) = 'OBJECT' "
            "AND JSON_LENGTH(confirmation_json) = 7 "
            "AND JSON_CONTAINS_PATH(confirmation_json, 'all', "
            "'$.validation_run_id', '$.validation_data_digest', "
            "'$.ruleset_version', '$.confirmed_report_date', "
            "'$.confirmed_report_type', '$.confirmed_row_count', "
            "'$.confirmed_totals') = 1) OR "
            "(operation_kind = 'return_to_draft' "
            "AND from_status = 'ready_for_publish' AND to_status = 'draft' "
            "AND selected_validation_run_id IS NULL "
            "AND confirmation_digest IS NULL AND confirmation_json IS NULL))",
            name="ck_version_review_events_transition",
        ),
        sa.Index(
            "ix_version_review_events_version_revision",
            "version_id",
            "to_review_revision",
            "id",
        ),
        **_TABLE_OPTIONS,
    )
    op.create_table(
        "review_operation_results",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("result_kind", _code_type(32), nullable=False),
        sa.Column("result_import_batch_id", _id_type(), nullable=True),
        sa.Column("result_dataset_id", _id_type(), nullable=True),
        sa.Column("result_version_id", _id_type(), nullable=True),
        sa.Column("result_status", _code_type(32), nullable=True),
        sa.Column("result_data_revision", _id_type(), nullable=True),
        sa.Column("result_review_revision", _id_type(), nullable=True),
        sa.Column("affected_row_id", _id_type(), nullable=True),
        sa.Column("data_change_event_id", _id_type(), nullable=True),
        sa.Column("issue_review_event_id", _id_type(), nullable=True),
        sa.Column("validation_run_id", _id_type(), nullable=True),
        sa.Column("version_review_event_id", _id_type(), nullable=True),
        sa.Column("note_id", _id_type(), nullable=True),
        sa.Column("completed_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint("operation_token", name="pk_review_operation_results"),
        sa.ForeignKeyConstraint(
            ["operation_token", "operation_kind", "operation_digest", "actor_user_id"],
            [
                "review_operation_tokens.operation_token",
                "review_operation_tokens.operation_kind",
                "review_operation_tokens.operation_digest",
                "review_operation_tokens.actor_user_id",
            ],
            name="fk_review_operation_results_identity",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_import_batch_id"],
            ["import_batches.id"],
            name="fk_review_operation_results_import_batch",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_dataset_id", "result_version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_review_operation_results_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_version_id", "affected_row_id"],
            ["version_rows.version_id", "version_rows.id"],
            name="fk_review_operation_results_row",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_version_id", "data_change_event_id"],
            ["data_change_events.version_id", "data_change_events.id"],
            name="fk_review_operation_results_change",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_version_id", "issue_review_event_id"],
            ["issue_review_events.version_id", "issue_review_events.id"],
            name="fk_review_operation_results_issue_review",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_version_id", "validation_run_id"],
            ["validation_runs.version_id", "validation_runs.id"],
            name="fk_review_operation_results_validation",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "operation_token",
                "operation_kind",
                "operation_digest",
                "actor_user_id",
                "result_dataset_id",
                "result_version_id",
                "version_review_event_id",
            ],
            [
                "version_review_events.operation_token",
                "version_review_events.operation_kind",
                "version_review_events.operation_digest",
                "version_review_events.actor_user_id",
                "version_review_events.dataset_id",
                "version_review_events.version_id",
                "version_review_events.id",
            ],
            name="fk_review_operation_results_version_review",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["note_id"],
            ["notes.id"],
            name="fk_review_operation_results_note",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "result_kind IN ('applied', 'cancelled')",
            name="ck_review_operation_results_kind",
        ),
        sa.CheckConstraint(
            "result_status IS NULL "
            "OR result_status IN ('draft', 'ready_for_publish')",
            name="ck_review_operation_results_status",
        ),
        sa.CheckConstraint(
            "((result_kind = 'cancelled' "
            "AND result_import_batch_id IS NULL "
            "AND result_dataset_id IS NULL AND result_version_id IS NULL "
            "AND result_status IS NULL AND result_data_revision IS NULL "
            "AND result_review_revision IS NULL) OR "
            "(result_kind = 'applied' AND "
            "((operation_kind IN ('create_note', 'revise_note') AND "
            "((result_import_batch_id IS NOT NULL "
            "AND result_dataset_id IS NULL AND result_version_id IS NULL "
            "AND result_status IS NULL AND result_data_revision IS NULL "
            "AND result_review_revision IS NULL) OR "
            "(result_import_batch_id IS NULL "
            "AND result_dataset_id IS NOT NULL "
            "AND result_version_id IS NOT NULL "
            "AND result_status IS NOT NULL "
            "AND result_data_revision IS NOT NULL "
            "AND result_review_revision IS NOT NULL))) OR "
            "(operation_kind NOT IN ('create_note', 'revise_note') "
            "AND result_import_batch_id IS NULL "
            "AND result_dataset_id IS NOT NULL "
            "AND result_version_id IS NOT NULL "
            "AND result_status IS NOT NULL "
            "AND result_data_revision IS NOT NULL "
            "AND result_review_revision IS NOT NULL))))",
            name="ck_review_operation_results_scope",
        ),
        sa.CheckConstraint(
            "((result_kind = 'cancelled' "
            "AND affected_row_id IS NULL AND data_change_event_id IS NULL "
            "AND issue_review_event_id IS NULL AND validation_run_id IS NULL "
            "AND version_review_event_id IS NULL AND note_id IS NULL) OR "
            "(result_kind = 'applied' AND "
            "((operation_kind IN ("
            "'set_field', 'restore_previous_field', 'restore_parent_field', "
            "'restore_source_field', 'add_row', 'exclude_row', "
            "'restore_row', 'delete_row') "
            "AND affected_row_id IS NOT NULL AND data_change_event_id IS NOT NULL "
            "AND issue_review_event_id IS NULL AND validation_run_id IS NULL "
            "AND version_review_event_id IS NULL AND note_id IS NULL) OR "
            "(operation_kind IN ('create_note', 'revise_note') "
            "AND affected_row_id IS NULL AND data_change_event_id IS NULL "
            "AND issue_review_event_id IS NULL AND validation_run_id IS NULL "
            "AND version_review_event_id IS NULL AND note_id IS NOT NULL) OR "
            "(operation_kind = 'review_issue' "
            "AND affected_row_id IS NULL AND data_change_event_id IS NULL "
            "AND issue_review_event_id IS NOT NULL "
            "AND validation_run_id IS NULL "
            "AND version_review_event_id IS NULL AND note_id IS NULL) OR "
            "(operation_kind = 'run_validation' "
            "AND affected_row_id IS NULL AND data_change_event_id IS NULL "
            "AND issue_review_event_id IS NULL "
            "AND validation_run_id IS NOT NULL "
            "AND version_review_event_id IS NULL AND note_id IS NULL) OR "
            "(operation_kind IN ('mark_ready', 'return_to_draft') "
            "AND affected_row_id IS NULL AND data_change_event_id IS NULL "
            "AND issue_review_event_id IS NULL AND validation_run_id IS NULL "
            "AND version_review_event_id IS NOT NULL "
            "AND note_id IS NULL))))",
            name="ck_review_operation_results_semantics",
        ),
        **_TABLE_OPTIONS,
    )

    _create_write_guard_triggers()


def downgrade() -> None:
    _assert_downgrade_preconditions()

    _drop_write_guard_triggers()

    # Drop the terminal publication ledger before removing the composite key
    # used by its published-move lineage foreign key.
    op.drop_table("publication_command_results")

    op.drop_constraint(
        "ck_draft_disposition_events_operation_kind",
        "draft_disposition_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_draft_disposition_events_operation_kind",
        "draft_disposition_events",
        "((event_type IN ('discarded', 'force_discarded') "
        "AND operation_kind = 'discard_draft') OR "
        "(event_type = 'force_rebuilt' "
        "AND operation_kind = 'force_rebuild') OR "
        "(event_type = 'date_reassigned' "
        "AND operation_kind = 'reassign_date') OR "
        "(event_type = 'superseded' "
        "AND operation_kind IN ('materialize_baseline', 'reassign_date')))"
    )
    op.drop_constraint(
        "uq_draft_operation_results_move_version",
        "draft_operation_results",
        type_="unique",
    )
    op.drop_constraint(
        "fk_draft_operation_results_published_move_source",
        "draft_operation_results",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_draft_operation_results_published_move_source",
        table_name="draft_operation_results",
    )
    op.drop_constraint(
        "ck_draft_operation_results_published_move_source",
        "draft_operation_results",
        type_="check",
    )
    op.drop_column(
        "draft_operation_results",
        "published_move_source_lineage_type",
    )
    op.drop_column(
        "draft_operation_results",
        "published_move_source_parent_version_id",
    )

    op.drop_constraint(
        "fk_draft_operation_results_create_revision_parent",
        "draft_operation_results",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_draft_operation_results_create_revision_parent",
        table_name="draft_operation_results",
    )
    op.drop_constraint(
        "ck_draft_operation_results_create_revision_parent",
        "draft_operation_results",
        type_="check",
    )
    op.drop_column(
        "draft_operation_results",
        "create_revision_parent_version_id",
    )
    op.drop_constraint(
        "ck_draft_operation_results_semantics",
        "draft_operation_results",
        type_="check",
    )
    op.create_check_constraint(
        "ck_draft_operation_results_semantics",
        "draft_operation_results",
        "((operation_kind = 'materialize_baseline' "
        "AND result_kind IN ('created', 'merged', 'replaced') "
        "AND result_status = 'draft') OR "
        "(operation_kind = 'force_rebuild' "
        "AND result_kind = 'force_rebuilt' "
        "AND result_status = 'draft') OR "
        "(operation_kind = 'discard_draft' "
        "AND result_kind IN ('discarded', 'force_discarded') "
        "AND result_status = 'discarded') OR "
        "(operation_kind = 'reassign_date' "
        "AND ((result_kind = 'reassigned' AND result_status = 'draft') "
        "OR (result_kind = 'cancelled' "
        "AND result_status = 'cancelled'))))",
    )
    op.drop_constraint(
        "ck_draft_operation_results_kind",
        "draft_operation_results",
        type_="check",
    )
    op.create_check_constraint(
        "ck_draft_operation_results_kind",
        "draft_operation_results",
        "result_kind IN "
        "('created', 'merged', 'replaced', 'discarded', "
        "'force_discarded', 'reassigned', 'force_rebuilt', 'cancelled')",
    )
    op.drop_constraint(
        "ck_draft_operation_tokens_kind",
        "draft_operation_tokens",
        type_="check",
    )
    op.create_check_constraint(
        "ck_draft_operation_tokens_kind",
        "draft_operation_tokens",
        "operation_kind IN "
        "('materialize_baseline', 'force_rebuild', "
        "'discard_draft', 'reassign_date')",
    )

    op.drop_table("review_operation_results")
    op.drop_table("version_review_events")
    op.drop_table("review_operation_tokens")

    for column_name, column_type in (
        ("target_type", sa.String(length=24)),
        ("import_batch_id", _id_type()),
        ("version_id", _id_type()),
        ("row_id", _id_type()),
        ("field_name", sa.String(length=128)),
    ):
        op.add_column(
            "notes",
            sa.Column(column_name, column_type, nullable=True),
        )
    op.execute(
        sa.text(
            """
            UPDATE notes
            INNER JOIN note_threads
                ON note_threads.note_key = notes.note_key
            SET notes.target_type = note_threads.target_type,
                notes.import_batch_id = note_threads.import_batch_id,
                notes.version_id = note_threads.version_id,
                notes.row_id = note_threads.row_id,
                notes.field_name = note_threads.field_name
            """
        )
    )
    op.alter_column(
        "notes",
        "target_type",
        existing_type=sa.String(length=24),
        nullable=False,
    )
    op.create_index(
        "ix_notes_target_version_row",
        "notes",
        ["version_id", "row_id", "id"],
    )
    op.create_foreign_key(
        "fk_notes_import_batch",
        "notes",
        "import_batches",
        ["import_batch_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_notes_version",
        "notes",
        "dataset_versions",
        ["version_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_notes_version_row",
        "notes",
        "version_rows",
        ["version_id", "row_id"],
        ["version_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_check_constraint(
        "ck_notes_target",
        "notes",
        "((target_type = 'import_batch' "
        "AND import_batch_id IS NOT NULL AND version_id IS NULL "
        "AND row_id IS NULL AND field_name IS NULL) OR "
        "(target_type = 'version' "
        "AND import_batch_id IS NULL AND version_id IS NOT NULL "
        "AND row_id IS NULL AND field_name IS NULL) OR "
        "(target_type = 'row' "
        "AND import_batch_id IS NULL AND version_id IS NOT NULL "
        "AND row_id IS NOT NULL AND field_name IS NULL) OR "
        "(target_type = 'field' "
        "AND import_batch_id IS NULL AND version_id IS NOT NULL "
        "AND row_id IS NOT NULL AND field_name IS NOT NULL))",
    )
    op.drop_constraint(
        "fk_notes_previous_revision",
        "notes",
        type_="foreignkey",
    )
    op.drop_index("fk_notes_previous_revision", table_name="notes")
    op.drop_constraint(
        "ck_notes_revision_chain",
        "notes",
        type_="check",
    )
    op.create_foreign_key(
        "fk_notes_previous_revision",
        "notes",
        "notes",
        ["note_key", "supersedes_note_id"],
        ["note_key", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_check_constraint(
        "ck_notes_revision_chain",
        "notes",
        "((revision_number = 1 AND supersedes_note_id IS NULL) OR "
        "(revision_number > 1 AND supersedes_note_id IS NOT NULL))",
    )
    op.drop_constraint(
        "uq_notes_key_revision_id",
        "notes",
        type_="unique",
    )
    op.drop_column("notes", "supersedes_revision_number")
    op.drop_constraint("fk_notes_thread", "notes", type_="foreignkey")
    op.drop_constraint("ck_notes_body_nonempty", "notes", type_="check")
    op.alter_column(
        "notes",
        "visibility",
        existing_type=sa.String(length=24),
        existing_server_default=sa.text("'internal'"),
        server_default=None,
        existing_nullable=False,
        nullable=False,
    )
    op.drop_table("note_threads")

    op.drop_constraint(
        "uq_publication_events_command_id",
        "publication_events",
        type_="unique",
    )
    op.drop_constraint(
        "fk_publication_events_command",
        "publication_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_publication_commands_actor",
        "publication_commands",
        type_="foreignkey",
    )
    op.drop_index("fk_publication_commands_actor", table_name="publication_commands")
    op.drop_constraint(
        "ck_publication_commands_kind",
        "publication_commands",
        type_="check",
    )
    op.drop_constraint(
        "uq_publication_commands_identity",
        "publication_commands",
        type_="unique",
    )
    op.drop_constraint(
        "uq_publication_commands_token",
        "publication_commands",
        type_="unique",
    )
    op.add_column(
        "publication_commands",
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'in_progress'"),
            nullable=False,
        ),
    )
    op.add_column(
        "publication_commands",
        sa.Column("redacted_result_payload", mysql.JSON(), nullable=True),
    )
    op.add_column(
        "publication_commands",
        sa.Column("completed_at", _timestamp_type(), nullable=True),
    )
    op.alter_column(
        "publication_commands",
        "registered_at",
        new_column_name="created_at",
        existing_type=_timestamp_type(),
        existing_server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        existing_nullable=False,
        nullable=False,
    )
    op.alter_column(
        "publication_commands",
        "operation_token",
        new_column_name="idempotency_key",
        existing_type=mysql.BINARY(16),
        type_=sa.String(length=128),
        existing_nullable=False,
        nullable=False,
    )
    op.alter_column(
        "publication_commands",
        "operation_kind",
        new_column_name="command_type",
        existing_type=_code_type(32),
        type_=sa.String(length=32),
        existing_nullable=False,
        nullable=False,
    )
    op.drop_column("publication_commands", "operation_digest")
    op.create_unique_constraint(
        "uq_publication_commands_actor_type_key",
        "publication_commands",
        ["actor_user_id", "command_type", "idempotency_key"],
    )
    op.create_check_constraint(
        "ck_publication_commands_type",
        "publication_commands",
        "command_type IN "
        "('publish', 'replace', 'rollback', 'withdraw', 'move', 'reverse_move')",
    )
    op.create_check_constraint(
        "ck_publication_commands_status",
        "publication_commands",
        "status IN ('in_progress', 'succeeded', 'failed')",
    )
    op.create_foreign_key(
        "fk_publication_commands_actor",
        "publication_commands",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_publication_events_command",
        "publication_events",
        "publication_commands",
        ["command_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    op.create_foreign_key(
        "fk_dataset_publications_version",
        "dataset_publications",
        "dataset_versions",
        ["dataset_id", "version_id"],
        ["dataset_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.drop_constraint(
        "fk_dataset_publications_published_version",
        "dataset_publications",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_dataset_publications_version_status",
        table_name="dataset_publications",
    )
    op.drop_constraint(
        "ck_dataset_publications_published_status",
        "dataset_publications",
        type_="check",
    )
    op.drop_column("dataset_publications", "version_status")

    op.create_foreign_key(
        "fk_issue_review_events_issue_run",
        "issue_review_events",
        "validation_issues",
        ["version_id", "validation_run_id", "validation_issue_id"],
        ["version_id", "validation_run_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.drop_constraint(
        "fk_issue_review_events_issue_kind",
        "issue_review_events",
        type_="foreignkey",
    )
    for constraint_name in (
        "ck_issue_review_events_revision",
        "ck_issue_review_events_comment",
        "ck_issue_review_events_kind",
    ):
        op.drop_constraint(constraint_name, "issue_review_events", type_="check")
    op.drop_index(
        "ix_issue_review_events_issue_kind",
        table_name="issue_review_events",
    )
    op.drop_column("issue_review_events", "issue_requires_note")
    op.drop_column("issue_review_events", "issue_severity")
    op.drop_constraint(
        "uq_issue_review_events_version_id",
        "issue_review_events",
        type_="unique",
    )
    op.drop_constraint(
        "uq_validation_issues_review_kind",
        "validation_issues",
        type_="unique",
    )

    for constraint_name in (
        "fk_validation_issues_baseline_row",
        "fk_validation_issues_baseline",
        "fk_validation_issues_source_row",
        "fk_validation_issues_attempt",
    ):
        op.drop_constraint(constraint_name, "validation_issues", type_="foreignkey")
    op.drop_constraint(
        "ck_validation_issues_lineage",
        "validation_issues",
        type_="check",
    )
    for index_name in (
        "ix_validation_issues_baseline_row",
        "ix_validation_issues_source_row",
        "ix_validation_issues_attempt",
    ):
        op.drop_index(index_name, table_name="validation_issues")
    for column_name in (
        "parse_baseline_row_id",
        "parse_baseline_id",
        "parsed_source_row_id",
        "parse_attempt_id",
        "import_batch_id",
    ):
        op.drop_column("validation_issues", column_name)
    op.drop_constraint(
        "uq_pbr_attempt_baseline_id",
        "parse_baseline_rows",
        type_="unique",
    )
    op.drop_constraint(
        "uq_parse_baselines_attempt_id",
        "parse_baselines",
        type_="unique",
    )

    op.drop_constraint(
        "ck_validation_runs_terminal",
        "validation_runs",
        type_="check",
    )
    op.alter_column(
        "validation_runs",
        "completed_at",
        existing_type=_timestamp_type(),
        nullable=True,
    )
    op.alter_column(
        "validation_runs",
        "summary_json",
        existing_type=mysql.JSON(),
        nullable=True,
    )
    op.alter_column(
        "validation_runs",
        "data_digest",
        existing_type=mysql.BINARY(length=32),
        nullable=True,
    )
    op.alter_column(
        "validation_runs",
        "result",
        existing_type=sa.String(length=24),
        nullable=True,
    )
    op.alter_column(
        "validation_runs",
        "status",
        existing_type=sa.String(length=24),
        server_default=sa.text("'running'"),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_validation_runs_status",
        "validation_runs",
        "status IN ('running', 'succeeded', 'failed')",
    )
    op.create_check_constraint(
        "ck_validation_runs_result",
        "validation_runs",
        "result IS NULL OR result IN ('passed', 'failed', 'error')",
    )

    op.create_foreign_key(
        "fk_field_changes_change_event",
        "field_changes",
        "data_change_events",
        ["version_id", "id"],
        ["version_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.drop_constraint(
        "fk_field_changes_event_kind",
        "field_changes",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_row_changes_change_event",
        "row_changes",
        "data_change_events",
        ["version_id", "id"],
        ["version_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.drop_constraint(
        "fk_row_changes_event_kind",
        "row_changes",
        type_="foreignkey",
    )
    for constraint_name in (
        "fk_field_changes_restore_previous",
        "fk_field_changes_restore_parent",
        "fk_field_changes_restore_source",
    ):
        op.drop_constraint(constraint_name, "field_changes", type_="foreignkey")
    op.drop_constraint(
        "ck_field_changes_restore_lineage",
        "field_changes",
        type_="check",
    )
    op.drop_constraint(
        "ck_field_changes_operation",
        "field_changes",
        type_="check",
    )
    op.execute(
        sa.text(
            """
            UPDATE field_changes
            SET operation = 'restore_baseline'
            WHERE operation = 'restore_parent'
            """
        )
    )
    op.create_check_constraint(
        "ck_field_changes_operation",
        "field_changes",
        "operation IN "
        "('set', 'restore_source', 'restore_baseline', 'restore_previous')",
    )
    op.alter_column(
        "row_changes",
        "after_value_json",
        existing_type=mysql.JSON(),
        nullable=True,
    )
    op.alter_column(
        "row_changes",
        "before_value_json",
        existing_type=mysql.JSON(),
        nullable=True,
    )
    op.alter_column(
        "field_changes",
        "after_value_json",
        existing_type=mysql.JSON(),
        nullable=True,
    )
    op.alter_column(
        "field_changes",
        "before_value_json",
        existing_type=mysql.JSON(),
        nullable=True,
    )
    for column_name in (
        "restored_source_row_id",
        "restored_parent_version_id",
        "restored_field_change_id",
    ):
        op.drop_column("field_changes", column_name)
    op.drop_constraint(
        "uq_field_changes_restore_previous",
        "field_changes",
        type_="unique",
    )
    op.drop_constraint(
        "uq_vpv_child_parent",
        "version_parent_versions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_version_rows_restore_source",
        "version_rows",
        type_="unique",
    )
    for table_name in ("row_changes", "field_changes"):
        op.drop_index(f"ix_{table_name}_event_kind", table_name=table_name)
        op.drop_constraint(
            f"ck_{table_name}_event_kind",
            table_name,
            type_="check",
        )
        op.drop_column(table_name, "event_kind")
    op.drop_constraint(
        "ck_dce_reason_nonempty",
        "data_change_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_dce_revision_sequence",
        "data_change_events",
        type_="check",
    )
    op.drop_constraint(
        "uq_dce_version_data_revision",
        "data_change_events",
        type_="unique",
    )
    op.drop_constraint(
        "uq_dce_version_id_kind",
        "data_change_events",
        type_="unique",
    )

    op.drop_table("terminal_write_guard_bypass_accounts")
