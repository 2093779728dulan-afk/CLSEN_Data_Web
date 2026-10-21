"""Harden daily draft lineage, immutable results, and terminal events."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import mysql

revision = "0008"
down_revision = "0007"
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
            f"0008 migration preflight rejected {count} {label}; "
            "resolve the incompatible data before retrying"
        )


def _drop_index_if_exists_online(
    index_name: str,
    *,
    table_name: str,
) -> None:
    """Remove a downgrade-only FK support index during an online upgrade."""

    if context.is_offline_mode():
        return
    existing_indexes = {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }
    if index_name in existing_indexes:
        op.drop_index(index_name, table_name=table_name)


def _assert_upgrade_preconditions() -> None:
    """Reject incompatible 0007 data before MySQL's first auto-commit."""

    _assert_no_rows(
        label="dataset version(s) with an invalid number or sealed state",
        query="""
            SELECT COUNT(*)
            FROM dataset_versions
            WHERE version_no = 0
               OR (
                    status IN ('draft', 'ready_for_publish')
                    AND sealed_at IS NOT NULL
               )
               OR (
                    status IN ('published', 'discarded')
                    AND sealed_at IS NULL
               )
        """,
    )
    _assert_no_rows(
        label="active draft pointer(s) targeting a terminal version",
        query="""
            SELECT COUNT(*)
            FROM dataset_drafts AS drafts
            INNER JOIN dataset_versions AS versions
                ON versions.dataset_id = drafts.dataset_id
               AND versions.id = drafts.version_id
            WHERE versions.status NOT IN ('draft', 'ready_for_publish')
        """,
    )
    _assert_no_rows(
        label="cross-report-type parent lineage relation(s)",
        query="""
            SELECT COUNT(*)
            FROM version_parent_versions AS lineage
            INNER JOIN dataset_versions AS children
                ON children.id = lineage.child_version_id
            INNER JOIN dataset_versions AS parents
                ON parents.id = lineage.parent_version_id
            WHERE children.report_type <> parents.report_type
        """,
    )
    _assert_no_rows(
        label="snapshot member(s) with inconsistent type or role",
        query="""
            SELECT COUNT(*)
            FROM version_base_snapshot_members AS members
            INNER JOIN version_base_snapshots AS snapshots
                ON snapshots.id = members.snapshot_id
            LEFT JOIN parse_baselines AS baselines
                ON baselines.id = members.parse_baseline_id
            LEFT JOIN dataset_versions AS parents
                ON parents.id = members.parent_version_id
            WHERE (
                    members.member_type = 'parse_baseline'
                    AND (
                        members.member_role <> 'parse_input'
                        OR baselines.report_type <> snapshots.report_type
                    )
                  )
               OR (
                    members.member_type = 'dataset_version'
                    AND (
                        members.member_role NOT IN (
                            'base', 'draft_predecessor', 'merge_target',
                            'merge_source', 'moved_source'
                        )
                        OR parents.report_type <> snapshots.report_type
                    )
                  )
        """,
    )
    _assert_no_rows(
        label="keep-both base row(s) without a reason",
        query="""
            SELECT COUNT(*)
            FROM version_base_rows
            WHERE merge_action = 'keep_both'
              AND (
                    merge_reason IS NULL
                    OR CHAR_LENGTH(TRIM(merge_reason)) = 0
              )
        """,
    )


def _assert_downgrade_preconditions() -> None:
    """Refuse to discard immutable draft command or disposition history."""

    _assert_no_rows(
        label="non-active base row(s) that cannot be represented by revision 0007",
        query="""
            SELECT COUNT(*)
            FROM version_base_rows
            WHERE row_state <> 'active'
        """,
    )
    for table_name, label in (
        ("draft_operation_results", "draft operation result(s)"),
        ("draft_disposition_events", "draft disposition event(s)"),
        ("draft_operation_tokens", "draft operation token(s)"),
    ):
        _assert_no_rows(
            label=f"{label} that would be lost by downgrade",
            query=f"SELECT COUNT(*) FROM {table_name}",
        )


def upgrade() -> None:
    _assert_upgrade_preconditions()

    op.create_table(
        "daily_dataset_locks",
        sa.Column("dataset_id", _id_type(), nullable=False),
        sa.Column(
            "lock_revision",
            _id_type(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("dataset_id", name="pk_daily_dataset_locks"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["daily_datasets.id"],
            name="fk_daily_dataset_locks_dataset",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        **_TABLE_OPTIONS,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO daily_dataset_locks (dataset_id, lock_revision)
            SELECT id, 0
            FROM daily_datasets
            """
        )
    )

    op.create_check_constraint(
        "ck_dataset_versions_version_no_positive",
        "dataset_versions",
        "version_no > 0",
    )
    op.create_check_constraint(
        "ck_dataset_versions_sealed_state",
        "dataset_versions",
        "((status IN ('draft', 'ready_for_publish') AND sealed_at IS NULL) OR "
        "(status IN ('published', 'discarded') AND sealed_at IS NOT NULL))",
    )
    op.create_unique_constraint(
        "uq_dataset_versions_dataset_id_status",
        "dataset_versions",
        ["dataset_id", "id", "status"],
    )

    op.add_column(
        "dataset_drafts",
        sa.Column("version_status", _code_type(32), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE dataset_drafts AS drafts
            INNER JOIN dataset_versions AS versions
                ON versions.dataset_id = drafts.dataset_id
               AND versions.id = drafts.version_id
            SET drafts.version_status = versions.status
            """
        )
    )
    op.alter_column(
        "dataset_drafts",
        "version_status",
        existing_type=_code_type(32),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_dataset_drafts_editable_status",
        "dataset_drafts",
        "version_status IN ('draft', 'ready_for_publish')",
    )
    op.create_index(
        "ix_dataset_drafts_version_status",
        "dataset_drafts",
        ["dataset_id", "version_id", "version_status"],
    )
    op.create_foreign_key(
        "fk_dataset_drafts_editable_version",
        "dataset_drafts",
        "dataset_versions",
        ["dataset_id", "version_id", "version_status"],
        ["dataset_id", "id", "status"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.drop_constraint(
        "fk_dataset_drafts_version",
        "dataset_drafts",
        type_="foreignkey",
    )
    _drop_index_if_exists_online(
        "ix_dataset_drafts_dataset_version_restore",
        table_name="dataset_drafts",
    )

    op.add_column(
        "version_parent_versions",
        sa.Column("report_type", _code_type(32), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE version_parent_versions AS lineage
            INNER JOIN dataset_versions AS children
                ON children.id = lineage.child_version_id
            SET lineage.report_type = children.report_type
            """
        )
    )
    op.alter_column(
        "version_parent_versions",
        "report_type",
        existing_type=_code_type(32),
        nullable=False,
    )
    op.create_index(
        "ix_vpv_child_type",
        "version_parent_versions",
        ["child_version_id", "report_type"],
    )
    op.create_index(
        "ix_vpv_parent_type",
        "version_parent_versions",
        ["parent_version_id", "report_type"],
    )
    op.create_foreign_key(
        "fk_vpv_child_type",
        "version_parent_versions",
        "dataset_versions",
        ["child_version_id", "report_type"],
        ["id", "report_type"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_vpv_parent_type",
        "version_parent_versions",
        "dataset_versions",
        ["parent_version_id", "report_type"],
        ["id", "report_type"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    op.add_column(
        "version_base_snapshot_members",
        sa.Column("report_type", _code_type(32), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE version_base_snapshot_members AS members
            INNER JOIN version_base_snapshots AS snapshots
                ON snapshots.id = members.snapshot_id
            SET members.report_type = snapshots.report_type
            """
        )
    )
    op.alter_column(
        "version_base_snapshot_members",
        "report_type",
        existing_type=_code_type(32),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_vbs_id_type",
        "version_base_snapshots",
        ["id", "report_type"],
    )
    op.create_index(
        "ix_vbsm_snapshot_type",
        "version_base_snapshot_members",
        ["snapshot_id", "report_type"],
    )
    op.create_index(
        "ix_vbsm_parse_baseline_type",
        "version_base_snapshot_members",
        ["parse_baseline_id", "report_type"],
    )
    op.create_index(
        "ix_vbsm_parent_version_type",
        "version_base_snapshot_members",
        ["parent_version_id", "report_type"],
    )
    op.create_check_constraint(
        "ck_vbsm_role_type",
        "version_base_snapshot_members",
        "((member_type = 'parse_baseline' AND member_role = 'parse_input') OR "
        "(member_type = 'dataset_version' AND member_role IN "
        "('base', 'draft_predecessor', 'merge_target', 'merge_source', "
        "'moved_source')))",
    )
    op.create_foreign_key(
        "fk_vbsm_snapshot_type",
        "version_base_snapshot_members",
        "version_base_snapshots",
        ["snapshot_id", "report_type"],
        ["id", "report_type"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_vbsm_parse_baseline_type",
        "version_base_snapshot_members",
        "parse_baselines",
        ["parse_baseline_id", "report_type"],
        ["id", "report_type"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_vbsm_parent_version_type",
        "version_base_snapshot_members",
        "dataset_versions",
        ["parent_version_id", "report_type"],
        ["id", "report_type"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    _drop_index_if_exists_online(
        "ix_vbsm_parent_version_restore",
        table_name="version_base_snapshot_members",
    )
    _drop_index_if_exists_online(
        "ix_vbsm_parse_baseline_restore",
        table_name="version_base_snapshot_members",
    )

    op.add_column(
        "version_base_rows",
        sa.Column(
            "row_state",
            _code_type(32),
            server_default=sa.text("'active'"),
            nullable=True,
        ),
    )
    op.execute(sa.text("UPDATE version_base_rows SET row_state = 'active'"))
    op.alter_column(
        "version_base_rows",
        "row_state",
        existing_type=_code_type(32),
        existing_server_default=sa.text("'active'"),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_vbr_row_state",
        "version_base_rows",
        "row_state IN ('active', 'excluded', 'deleted')",
    )
    op.create_check_constraint(
        "ck_vbr_keep_both_reason",
        "version_base_rows",
        "merge_action <> 'keep_both' OR "
        "(merge_reason IS NOT NULL AND CHAR_LENGTH(TRIM(merge_reason)) > 0)",
    )

    op.create_table(
        "draft_operation_tokens",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("registered_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint(
            "operation_token",
            name="pk_draft_operation_tokens",
        ),
        sa.UniqueConstraint(
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
            name="uq_draft_operation_tokens_identity",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_draft_operation_tokens_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation_kind IN "
            "('materialize_baseline', 'force_rebuild', "
            "'discard_draft', 'reassign_date')",
            name="ck_draft_operation_tokens_kind",
        ),
        sa.Index(
            "ix_draft_operation_tokens_actor_registered",
            "actor_user_id",
            "registered_at",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "draft_operation_results",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("result_kind", _code_type(32), nullable=False),
        sa.Column("result_dataset_id", _id_type(), nullable=False),
        sa.Column("result_version_id", _id_type(), nullable=False),
        sa.Column("result_version_no", _id_type(), nullable=False),
        sa.Column("result_status", _code_type(32), nullable=False),
        sa.Column("result_data_revision", _id_type(), nullable=False),
        sa.Column("result_review_revision", _id_type(), nullable=False),
        sa.Column("superseded_version_id_1", _id_type(), nullable=True),
        sa.Column("superseded_version_id_2", _id_type(), nullable=True),
        sa.Column("source_dataset_id", _id_type(), nullable=True),
        sa.Column("source_version_id", _id_type(), nullable=True),
        sa.Column("completed_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint(
            "operation_token",
            name="pk_draft_operation_results",
        ),
        sa.ForeignKeyConstraint(
            [
                "operation_token",
                "operation_kind",
                "operation_digest",
                "actor_user_id",
            ],
            [
                "draft_operation_tokens.operation_token",
                "draft_operation_tokens.operation_kind",
                "draft_operation_tokens.operation_digest",
                "draft_operation_tokens.actor_user_id",
            ],
            name="fk_draft_operation_results_identity",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_dataset_id", "result_version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_draft_operation_results_result",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_dataset_id", "source_version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_draft_operation_results_source",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_version_id_1"],
            ["dataset_versions.id"],
            name="fk_draft_operation_results_superseded_1",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_version_id_2"],
            ["dataset_versions.id"],
            name="fk_draft_operation_results_superseded_2",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "result_kind IN "
            "('created', 'merged', 'replaced', 'discarded', "
            "'force_discarded', 'reassigned', 'force_rebuilt', 'cancelled')",
            name="ck_draft_operation_results_kind",
        ),
        sa.CheckConstraint(
            "result_version_no > 0",
            name="ck_draft_operation_results_version_no_positive",
        ),
        sa.CheckConstraint(
            "result_status IN ('draft', 'discarded', 'cancelled')",
            name="ck_draft_operation_results_status",
        ),
        sa.CheckConstraint(
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
            name="ck_draft_operation_results_semantics",
        ),
        sa.CheckConstraint(
            "((source_dataset_id IS NULL AND source_version_id IS NULL) OR "
            "(source_dataset_id IS NOT NULL AND source_version_id IS NOT NULL))",
            name="ck_draft_operation_results_source_pair",
        ),
        sa.CheckConstraint(
            "superseded_version_id_2 IS NULL OR superseded_version_id_1 IS NOT NULL",
            name="ck_draft_operation_results_superseded_order",
        ),
        sa.CheckConstraint(
            "superseded_version_id_1 IS NULL "
            "OR superseded_version_id_2 IS NULL "
            "OR superseded_version_id_1 <> superseded_version_id_2",
            name="ck_draft_operation_results_superseded_distinct",
        ),
        sa.CheckConstraint(
            "result_kind <> 'cancelled' OR "
            "(superseded_version_id_1 IS NULL "
            "AND superseded_version_id_2 IS NULL "
            "AND source_dataset_id IS NULL "
            "AND source_version_id IS NULL)",
            name="ck_draft_operation_results_cancelled_lineage",
        ),
        sa.Index(
            "ix_draft_operation_results_result",
            "result_dataset_id",
            "result_version_id",
        ),
        sa.Index(
            "ix_draft_operation_results_source",
            "source_dataset_id",
            "source_version_id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "draft_disposition_events",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("dataset_id", _id_type(), nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column("event_type", _code_type(32), nullable=False),
        sa.Column("successor_dataset_id", _id_type(), nullable=True),
        sa.Column("successor_version_id", _id_type(), nullable=True),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("terminal_data_revision", _id_type(), nullable=False),
        sa.Column("terminal_review_revision", _id_type(), nullable=False),
        sa.Column("reason", mysql.LONGTEXT(), nullable=False),
        sa.Column("occurred_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_draft_disposition_events"),
        sa.UniqueConstraint(
            "version_id",
            name="uq_draft_disposition_events_version",
        ),
        sa.ForeignKeyConstraint(
            [
                "operation_token",
                "operation_kind",
                "operation_digest",
                "actor_user_id",
            ],
            [
                "draft_operation_tokens.operation_token",
                "draft_operation_tokens.operation_kind",
                "draft_operation_tokens.operation_digest",
                "draft_operation_tokens.actor_user_id",
            ],
            name="fk_draft_disposition_events_identity",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_draft_disposition_events_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["successor_dataset_id", "successor_version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_draft_disposition_events_successor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_draft_disposition_events_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "((event_type IN ('discarded', 'force_discarded') "
            "AND successor_dataset_id IS NULL AND successor_version_id IS NULL) OR "
            "(event_type IN ('superseded', 'date_reassigned', 'force_rebuilt') "
            "AND successor_dataset_id IS NOT NULL "
            "AND successor_version_id IS NOT NULL))",
            name="ck_draft_disposition_events_successor",
        ),
        sa.CheckConstraint(
            "((event_type IN ('discarded', 'force_discarded') "
            "AND operation_kind = 'discard_draft') OR "
            "(event_type = 'force_rebuilt' "
            "AND operation_kind = 'force_rebuild') OR "
            "(event_type = 'date_reassigned' "
            "AND operation_kind = 'reassign_date') OR "
            "(event_type = 'superseded' "
            "AND operation_kind IN ('materialize_baseline', 'reassign_date')))",
            name="ck_draft_disposition_events_operation_kind",
        ),
        sa.CheckConstraint(
            "CHAR_LENGTH(TRIM(reason)) > 0",
            name="ck_draft_disposition_events_reason",
        ),
        sa.Index(
            "ix_draft_disposition_events_dataset_time",
            "dataset_id",
            "occurred_at",
            "id",
        ),
        sa.Index(
            "ix_draft_disposition_events_operation",
            "operation_token",
            "id",
        ),
        sa.Index(
            "ix_draft_disposition_events_successor",
            "successor_dataset_id",
            "successor_version_id",
        ),
        **_TABLE_OPTIONS,
    )


def downgrade() -> None:
    _assert_downgrade_preconditions()

    op.drop_table("daily_dataset_locks")
    op.drop_table("draft_disposition_events")
    op.drop_table("draft_operation_results")
    op.drop_table("draft_operation_tokens")

    op.drop_constraint(
        "ck_vbr_keep_both_reason",
        "version_base_rows",
        type_="check",
    )
    op.drop_constraint("ck_vbr_row_state", "version_base_rows", type_="check")
    op.drop_column("version_base_rows", "row_state")

    op.drop_constraint(
        "fk_vbsm_parent_version_type",
        "version_base_snapshot_members",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_vbsm_parse_baseline_type",
        "version_base_snapshot_members",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_vbsm_snapshot_type",
        "version_base_snapshot_members",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_vbsm_role_type",
        "version_base_snapshot_members",
        type_="check",
    )
    op.create_index(
        "ix_vbsm_parent_version_restore",
        "version_base_snapshot_members",
        ["parent_version_id"],
    )
    op.create_index(
        "ix_vbsm_parse_baseline_restore",
        "version_base_snapshot_members",
        ["parse_baseline_id"],
    )
    op.drop_index(
        "ix_vbsm_parent_version_type",
        table_name="version_base_snapshot_members",
    )
    op.drop_index(
        "ix_vbsm_parse_baseline_type",
        table_name="version_base_snapshot_members",
    )
    op.drop_index(
        "ix_vbsm_snapshot_type",
        table_name="version_base_snapshot_members",
    )
    op.drop_constraint(
        "uq_vbs_id_type",
        "version_base_snapshots",
        type_="unique",
    )
    op.drop_column("version_base_snapshot_members", "report_type")

    op.drop_constraint(
        "fk_vpv_parent_type",
        "version_parent_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_vpv_child_type",
        "version_parent_versions",
        type_="foreignkey",
    )
    op.drop_index("ix_vpv_parent_type", table_name="version_parent_versions")
    op.drop_index("ix_vpv_child_type", table_name="version_parent_versions")
    op.drop_column("version_parent_versions", "report_type")

    op.create_index(
        "ix_dataset_drafts_dataset_version_restore",
        "dataset_drafts",
        ["dataset_id", "version_id"],
    )
    op.create_foreign_key(
        "fk_dataset_drafts_version",
        "dataset_drafts",
        "dataset_versions",
        ["dataset_id", "version_id"],
        ["dataset_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.drop_constraint(
        "fk_dataset_drafts_editable_version",
        "dataset_drafts",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_dataset_drafts_version_status",
        table_name="dataset_drafts",
    )
    op.drop_constraint(
        "ck_dataset_drafts_editable_status",
        "dataset_drafts",
        type_="check",
    )
    op.drop_column("dataset_drafts", "version_status")

    op.drop_constraint(
        "uq_dataset_versions_dataset_id_status",
        "dataset_versions",
        type_="unique",
    )
    op.drop_constraint(
        "ck_dataset_versions_sealed_state",
        "dataset_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_dataset_versions_version_no_positive",
        "dataset_versions",
        type_="check",
    )
