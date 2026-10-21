# ruff: noqa: E501
"""Append-only, pre-catalog source identity correction evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "report_source_scope_corrections",
        sa.Column(
            "id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
        ),
        sa.Column(
            "report_source_scope_id", mysql.BIGINT(unsigned=True), nullable=False
        ),
        sa.Column("site_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("operation_token", mysql.BINARY(16), nullable=False, unique=True),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("seller_account_scope_key", mysql.BINARY(32), nullable=False),
        sa.Column("seller_account_display_name", sa.String(128), nullable=False),
        sa.Column("actor_user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("evidence", mysql.JSON(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint(
            "report_source_scope_id", name="uq_scope_single_correction"
        ),
        sa.ForeignKeyConstraint(
            ["report_source_scope_id", "site_id"],
            ["report_source_scopes.id", "report_source_scopes.site_id"],
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT", onupdate="RESTRICT"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    for event in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER scope_correction_no_{event.lower()} BEFORE {event} ON report_source_scope_corrections FOR EACH ROW BEGIN IF NOT EXISTS (SELECT 1 FROM terminal_write_guard_bypass_accounts WHERE account_identity = USER()) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'scope correction evidence is immutable'; END IF; END"
        )


def downgrade():
    raise RuntimeError("Source correction evidence cannot be discarded by downgrade")
