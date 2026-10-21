"""Persist batch-review orchestration runs and item state."""

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import mysql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _id_type() -> sa.BigInteger:
    return sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")


def _timestamp_type() -> sa.DateTime:
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def _code_type(length: int) -> sa.String:
    return sa.String(length=length).with_variant(
        mysql.VARCHAR(length=length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


def upgrade() -> None:
    op.create_table(
        "batch_review_runs",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("site_id", _id_type(), nullable=False),
        sa.Column("created_by_user_id", _id_type(), nullable=False),
        sa.Column("status", _code_type(32), nullable=False),
        sa.Column("revision", _id_type(), server_default=sa.text("0"), nullable=False),
        sa.Column("confirmed_at", _timestamp_type(), nullable=True),
        sa.Column("confirmed_by_user_id", _id_type(), nullable=True),
        sa.Column("confirmation_statement_version", _code_type(64), nullable=True),
        sa.Column("operation_kind", _code_type(32), nullable=True),
        sa.Column("operation_token", mysql.BINARY(16), nullable=True),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=True),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_batch_review_runs"),
        sa.UniqueConstraint("id", "site_id", name="uq_batch_review_runs_id_site"),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name="fk_batch_review_runs_site",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_batch_review_runs_created_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"],
            ["users.id"],
            name="fk_batch_review_runs_confirmed_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('preview', 'confirmed', 'running', 'paused', "
            "'completed', 'completed_with_exceptions')",
            name="ck_batch_review_runs_status",
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_batch_review_runs_revision_nonnegative",
        ),
        sa.CheckConstraint(
            "((confirmed_at IS NULL AND confirmed_by_user_id IS NULL "
            "AND confirmation_statement_version IS NULL) OR "
            "(confirmed_at IS NOT NULL AND confirmed_by_user_id IS NOT NULL "
            "AND confirmation_statement_version IS NOT NULL))",
            name="ck_batch_review_runs_confirmation_complete",
        ),
        sa.CheckConstraint(
            "((operation_kind IS NULL AND operation_token IS NULL "
            "AND operation_digest IS NULL) OR "
            "(operation_kind IS NOT NULL AND operation_token IS NOT NULL "
            "AND OCTET_LENGTH(operation_token) = 16 "
            "AND operation_digest IS NOT NULL "
            "AND OCTET_LENGTH(operation_digest) = 32))",
            name="ck_batch_review_runs_operation_identity",
        ),
        sa.Index(
            "ix_batch_review_runs_site_status",
            "site_id",
            "status",
            "updated_at",
            "id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "batch_review_items",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("run_id", _id_type(), nullable=False),
        sa.Column("site_id", _id_type(), nullable=False),
        sa.Column("batch_id", _id_type(), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("detected_report_date", sa.Date(), nullable=True),
        sa.Column("detected_report_type", _code_type(32), nullable=True),
        sa.Column("detected_encoding", _code_type(64), nullable=True),
        sa.Column("recognition_status", _code_type(32), nullable=False),
        sa.Column("target_report_date", sa.Date(), nullable=True),
        sa.Column("target_report_type", _code_type(32), nullable=True),
        sa.Column("selected", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("status", _code_type(32), nullable=False),
        sa.Column("reason_code", _code_type(64), nullable=True),
        sa.Column("reason_message", sa.String(length=512), nullable=True),
        sa.Column("manual_review_url", sa.String(length=1024), nullable=True),
        sa.Column("parse_attempt_id", _id_type(), nullable=True),
        sa.Column("parse_baseline_id", _id_type(), nullable=True),
        sa.Column("dataset_id", _id_type(), nullable=True),
        sa.Column("version_id", _id_type(), nullable=True),
        sa.Column("validation_run_id", _id_type(), nullable=True),
        sa.Column("operation_token", mysql.BINARY(16), nullable=True),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=True),
        sa.Column(
            "attempt_count", _id_type(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "retry_allowed", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "outcome_unknown", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("lease_token", mysql.BINARY(16), nullable=True),
        sa.Column("lease_started_at", _timestamp_type(), nullable=True),
        sa.Column("lease_expires_at", _timestamp_type(), nullable=True),
        sa.Column(
            "lease_fence", _id_type(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_batch_review_items"),
        sa.UniqueConstraint(
            "run_id",
            "batch_id",
            name="uq_batch_review_items_run_batch",
        ),
        sa.UniqueConstraint(
            "run_id",
            "id",
            name="uq_batch_review_items_run_id",
        ),
        sa.UniqueConstraint(
            "operation_token",
            name="uq_batch_review_items_operation_token",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "site_id"],
            ["batch_review_runs.id", "batch_review_runs.site_id"],
            name="fk_batch_review_items_run",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "site_id"],
            ["import_batches.id", "import_batches.site_id"],
            name="fk_batch_review_items_batch",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parse_attempt_id"],
            ["parse_attempts.id"],
            name="fk_batch_review_items_parse_attempt",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parse_baseline_id"],
            ["parse_baselines.id"],
            name="fk_batch_review_items_parse_baseline",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["daily_datasets.id"],
            name="fk_batch_review_items_dataset",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["dataset_versions.id"],
            name="fk_batch_review_items_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["validation_run_id"],
            ["validation_runs.id"],
            name="fk_batch_review_items_validation_run",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('eligible', 'skipped', 'queued', 'parsing', "
            "'materializing', 'validating', 'ready_for_publish', "
            "'manual_review', 'failed')",
            name="ck_batch_review_items_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_batch_review_items_attempt_count_nonnegative",
        ),
        sa.CheckConstraint(
            "((operation_token IS NULL AND operation_digest IS NULL) OR "
            "(operation_token IS NOT NULL AND OCTET_LENGTH(operation_token) = 16 "
            "AND operation_digest IS NOT NULL "
            "AND OCTET_LENGTH(operation_digest) = 32))",
            name="ck_batch_review_items_operation_identity",
        ),
        sa.CheckConstraint(
            "((lease_token IS NULL AND lease_started_at IS NULL "
            "AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND OCTET_LENGTH(lease_token) = 16 "
            "AND lease_started_at IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND lease_expires_at > lease_started_at))",
            name="ck_batch_review_items_lease_identity",
        ),
        sa.CheckConstraint(
            "lease_fence >= 0",
            name="ck_batch_review_items_lease_fence_nonnegative",
        ),
        sa.CheckConstraint(
            "NOT retry_allowed OR status = 'failed'",
            name="ck_batch_review_items_retry_failed_only",
        ),
        sa.Index(
            "ix_batch_review_items_run_status",
            "run_id",
            "status",
            "id",
        ),
        sa.Index(
            "ix_batch_review_items_run_target",
            "run_id",
            "target_report_date",
            "target_report_type",
            "id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "batch_review_commands",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("site_id", _id_type(), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("run_id", _id_type(), nullable=False),
        sa.Column("item_id", _id_type(), nullable=True),
        sa.Column("status", _code_type(24), nullable=False),
        sa.Column("response_revision", _id_type(), nullable=True),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("completed_at", _timestamp_type(), nullable=True),
        sa.PrimaryKeyConstraint("operation_token", name="pk_batch_review_commands"),
        sa.ForeignKeyConstraint(
            ["run_id", "site_id"],
            ["batch_review_runs.id", "batch_review_runs.site_id"],
            name="fk_batch_review_commands_run",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "item_id"],
            ["batch_review_items.run_id", "batch_review_items.id"],
            name="fk_batch_review_commands_item",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_batch_review_commands_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation_kind IN ('create_preflight', 'confirm', 'advance_item', "
            "'pause', 'resume', 'retry_item')",
            name="ck_batch_review_commands_kind",
        ),
        sa.CheckConstraint(
            "OCTET_LENGTH(operation_token) = 16 "
            "AND OCTET_LENGTH(operation_digest) = 32",
            name="ck_batch_review_commands_identity",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'outcome_unknown')",
            name="ck_batch_review_commands_status",
        ),
        sa.CheckConstraint(
            "((operation_kind IN ('advance_item', 'retry_item') "
            "AND item_id IS NOT NULL) OR "
            "(operation_kind NOT IN ('advance_item', 'retry_item') "
            "AND item_id IS NULL))",
            name="ck_batch_review_commands_item_scope",
        ),
        sa.Index(
            "ix_batch_review_commands_run_created",
            "run_id",
            "created_at",
            "operation_token",
        ),
        **_TABLE_OPTIONS,
    )


def _assert_downgrade_preconditions() -> None:
    if context.is_offline_mode():
        raise RuntimeError("0021 downgrade requires an online migration connection")
    connection = op.get_bind()
    row_count = connection.scalar(sa.text("SELECT COUNT(*) FROM batch_review_runs"))
    if int(row_count or 0) != 0:
        raise RuntimeError(
            "0021 downgrade refused: batch review orchestration rows still exist"
        )


def downgrade() -> None:
    _assert_downgrade_preconditions()
    op.drop_table("batch_review_commands")
    op.drop_table("batch_review_items")
    op.drop_table("batch_review_runs")
