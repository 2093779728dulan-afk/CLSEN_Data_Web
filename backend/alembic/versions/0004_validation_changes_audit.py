"""Add validation, append-only change, note, and audit records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _bigint() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _utc_datetime() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def upgrade() -> None:
    op.create_table(
        "validation_runs",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("version_id", _bigint(), nullable=False),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column("data_revision", _bigint(), nullable=False),
        sa.Column("ruleset_version", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'running'"),
            nullable=False,
        ),
        sa.Column("result", sa.String(length=24), nullable=True),
        sa.Column("data_digest", mysql.BINARY(length=32), nullable=True),
        sa.Column("summary_json", mysql.JSON(), nullable=True),
        sa.Column(
            "started_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("completed_at", _utc_datetime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_validation_runs"),
        sa.UniqueConstraint(
            "version_id",
            "id",
            name="uq_validation_runs_version_id",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["dataset_versions.id"],
            name="fk_validation_runs_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "run_type IN ('parse_fidelity', 'draft_explainability', 'full')",
            name="ck_validation_runs_type",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_validation_runs_status",
        ),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('passed', 'failed', 'error')",
            name="ck_validation_runs_result",
        ),
        sa.Index(
            "ix_validation_runs_version_revision",
            "version_id",
            "data_revision",
            "id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "validation_issues",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column(
            "validation_run_id",
            _bigint(),
            nullable=False,
        ),
        sa.Column("version_id", _bigint(), nullable=False),
        sa.Column("row_id", _bigint(), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("rule_code", sa.String(length=128), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_value_json", mysql.JSON(), nullable=True),
        sa.Column("processed_value_json", mysql.JSON(), nullable=True),
        sa.Column("details_json", mysql.JSON(), nullable=True),
        sa.Column("requires_note", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_validation_issues"),
        sa.UniqueConstraint(
            "version_id",
            "validation_run_id",
            "id",
            name="uq_validation_issues_version_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "validation_run_id"],
            ["validation_runs.version_id", "validation_runs.id"],
            name="fk_validation_issues_run_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "row_id"],
            ["version_rows.version_id", "version_rows.id"],
            name="fk_validation_issues_version_row",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "severity IN ('warning', 'blocking')",
            name="ck_validation_issues_severity",
        ),
        sa.Index(
            "ix_validation_issues_run_severity",
            "validation_run_id",
            "severity",
            "id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "issue_review_events",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("version_id", _bigint(), nullable=False),
        sa.Column(
            "validation_run_id",
            _bigint(),
            nullable=False,
        ),
        sa.Column(
            "validation_issue_id",
            _bigint(),
            nullable=False,
        ),
        sa.Column("sequence_number", _bigint(), nullable=False),
        sa.Column("review_revision", _bigint(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", _bigint(), nullable=False),
        sa.Column("comment", mysql.LONGTEXT(), nullable=True),
        sa.Column("redacted_payload", mysql.JSON(), nullable=True),
        sa.Column(
            "occurred_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_issue_review_events"),
        sa.UniqueConstraint(
            "validation_issue_id",
            "sequence_number",
            name="uq_issue_review_events_issue_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "validation_run_id", "validation_issue_id"],
            [
                "validation_issues.version_id",
                "validation_issues.validation_run_id",
                "validation_issues.id",
            ],
            name="fk_issue_review_events_issue_run",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_issue_review_events_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "event_type IN ('acknowledge', 'resolve', 'reopen')",
            name="ck_issue_review_events_type",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "data_change_events",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("version_id", _bigint(), nullable=False),
        sa.Column("sequence_number", _bigint(), nullable=False),
        sa.Column("data_revision", _bigint(), nullable=False),
        sa.Column("event_kind", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", _bigint(), nullable=False),
        sa.Column("reason", mysql.LONGTEXT(), nullable=False),
        sa.Column(
            "occurred_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_data_change_events"),
        sa.UniqueConstraint(
            "version_id",
            "id",
            name="uq_data_change_events_version_id",
        ),
        sa.UniqueConstraint(
            "version_id",
            "sequence_number",
            name="uq_data_change_events_version_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["dataset_versions.id"],
            name="fk_data_change_events_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_data_change_events_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "event_kind IN ('field', 'row')",
            name="ck_data_change_events_kind",
        ),
        sa.Index(
            "ix_data_change_events_version_revision",
            "version_id",
            "data_revision",
            "id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "field_changes",
        sa.Column("id", _bigint(), autoincrement=False, nullable=False),
        sa.Column("version_id", _bigint(), nullable=False),
        sa.Column("row_id", _bigint(), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("before_value_json", mysql.JSON(), nullable=True),
        sa.Column("after_value_json", mysql.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_field_changes"),
        sa.ForeignKeyConstraint(
            ["version_id", "id"],
            ["data_change_events.version_id", "data_change_events.id"],
            name="fk_field_changes_change_event",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "row_id"],
            ["version_rows.version_id", "version_rows.id"],
            name="fk_field_changes_version_row",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation IN "
            "('set', 'restore_source', 'restore_baseline', 'restore_previous')",
            name="ck_field_changes_operation",
        ),
        sa.Index(
            "ix_field_changes_version_row",
            "version_id",
            "row_id",
            "id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "row_changes",
        sa.Column("id", _bigint(), autoincrement=False, nullable=False),
        sa.Column("version_id", _bigint(), nullable=False),
        sa.Column("row_id", _bigint(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("source_batch_id", _bigint(), nullable=True),
        sa.Column("before_value_json", mysql.JSON(), nullable=True),
        sa.Column("after_value_json", mysql.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_row_changes"),
        sa.ForeignKeyConstraint(
            ["version_id", "id"],
            ["data_change_events.version_id", "data_change_events.id"],
            name="fk_row_changes_change_event",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "row_id"],
            ["version_rows.version_id", "version_rows.id"],
            name="fk_row_changes_version_row",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_batch_id"],
            ["import_batches.id"],
            name="fk_row_changes_source_batch",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation IN ('add', 'exclude', 'restore', 'delete')",
            name="ck_row_changes_operation",
        ),
        sa.Index(
            "ix_row_changes_version_row",
            "version_id",
            "row_id",
            "id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "notes",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("note_key", sa.String(length=64), nullable=False),
        sa.Column("revision_number", _bigint(), nullable=False),
        sa.Column("supersedes_note_id", _bigint(), nullable=True),
        sa.Column("target_type", sa.String(length=24), nullable=False),
        sa.Column("import_batch_id", _bigint(), nullable=True),
        sa.Column("version_id", _bigint(), nullable=True),
        sa.Column("row_id", _bigint(), nullable=True),
        sa.Column("field_name", sa.String(length=128), nullable=True),
        sa.Column("visibility", sa.String(length=24), nullable=False),
        sa.Column("body", mysql.LONGTEXT(), nullable=False),
        sa.Column("author_user_id", _bigint(), nullable=False),
        sa.Column("review_revision", _bigint(), nullable=True),
        sa.Column(
            "created_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notes"),
        sa.UniqueConstraint(
            "note_key",
            "revision_number",
            name="uq_notes_key_revision",
        ),
        sa.UniqueConstraint(
            "note_key",
            "id",
            name="uq_notes_key_id",
        ),
        sa.UniqueConstraint(
            "supersedes_note_id",
            name="uq_notes_supersedes_note",
        ),
        sa.ForeignKeyConstraint(
            ["note_key", "supersedes_note_id"],
            ["notes.note_key", "notes.id"],
            name="fk_notes_previous_revision",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batches.id"],
            name="fk_notes_import_batch",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["dataset_versions.id"],
            name="fk_notes_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "row_id"],
            ["version_rows.version_id", "version_rows.id"],
            name="fk_notes_version_row",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name="fk_notes_author",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_notes_positive_revision",
        ),
        sa.CheckConstraint(
            "((revision_number = 1 AND supersedes_note_id IS NULL) OR "
            "(revision_number > 1 AND supersedes_note_id IS NOT NULL))",
            name="ck_notes_revision_chain",
        ),
        sa.CheckConstraint(
            "visibility IN ('internal', 'viewer_visible')",
            name="ck_notes_visibility",
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
            name="ck_notes_target",
        ),
        sa.Index("ix_notes_target_version_row", "version_id", "row_id", "id"),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "audit_events",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("site_id", _bigint(), nullable=True),
        sa.Column("actor_user_id", _bigint(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("redacted_payload", mysql.JSON(), nullable=False),
        sa.Column(
            "occurred_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name="fk_audit_events_site",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_events_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.Index(
            "ix_audit_events_type_occurred",
            "event_type",
            "occurred_at",
            "id",
        ),
        **_TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("notes")
    op.drop_table("row_changes")
    op.drop_table("field_changes")
    op.drop_table("data_change_events")
    op.drop_table("issue_review_events")
    op.drop_table("validation_issues")
    op.drop_table("validation_runs")
