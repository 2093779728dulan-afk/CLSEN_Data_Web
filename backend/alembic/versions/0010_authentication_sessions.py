"""Add durable opaque sessions for the HTTP authentication boundary."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0010"
down_revision = "0009"
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
        "auth_sessions",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("token_hash", mysql.BINARY(length=32), nullable=False),
        sa.Column("csrf_token_hash", mysql.BINARY(length=32), nullable=False),
        sa.Column("user_id", _bigint(), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.Column("expires_at", _utc_datetime(), nullable=False),
        sa.Column("last_seen_at", _utc_datetime(), nullable=False),
        sa.Column("revoked_at", _utc_datetime(), nullable=True),
        sa.Column("revoked_reason", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_sessions_user",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_auth_sessions_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_auth_sessions_revocation_after_creation",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_reason IS NOT NULL)",
            name="ck_auth_sessions_revocation_pair",
        ),
        sa.Index(
            "ix_auth_sessions_user_active_expiry",
            "user_id",
            "revoked_at",
            "expires_at",
            "id",
        ),
        **_TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("auth_sessions")
