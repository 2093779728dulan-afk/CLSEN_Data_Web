# ruff: noqa: E501
"""Add temporary Seller SKU reservations for catalog drafts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _code(length: int) -> mysql.VARCHAR:
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def upgrade() -> None:
    op.create_table(
        "catalog_draft_identity_reservations",
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("site_id", _id(), nullable=False),
        sa.Column("import_id", _id(), nullable=False),
        sa.Column("report_source_scope_id", _id(), nullable=False),
        sa.Column("marketplace_scope_code", _code(32), nullable=False),
        sa.Column("seller_sku_match_sha256", mysql.BINARY(32), nullable=False),
        sa.Column("seller_sku_match_bytes", mysql.VARBINARY(1020), nullable=False),
        sa.Column("decision_group_key", _code(64), nullable=False),
        sa.Column("target_sku_row_key", _code(64), nullable=False),
        sa.Column("created_by_user_id", _id(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
            server_onupdate=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_catalog_draft_identity_reservations"),
        sa.UniqueConstraint(
            "site_id",
            "report_source_scope_id",
            "marketplace_scope_code",
            "seller_sku_match_sha256",
            "seller_sku_match_bytes",
            name="uq_catalog_draft_identity_reservations_key",
        ),
        sa.UniqueConstraint(
            "import_id",
            "decision_group_key",
            name="uq_catalog_draft_identity_reservations_group",
        ),
        sa.ForeignKeyConstraint(
            ["import_id", "site_id"],
            ["catalog_imports.id", "catalog_imports.site_id"],
            name="fk_catalog_draft_identity_reservations_import",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_source_scope_id", "site_id"],
            ["report_source_scopes.id", "report_source_scopes.site_id"],
            name="fk_catalog_draft_identity_reservations_scope",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_catalog_draft_identity_reservations_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "marketplace_scope_code='amazon_us'",
            name="ck_catalog_draft_identity_reservations_marketplace",
        ),
        sa.Index(
            "ix_catalog_draft_identity_reservations_owner",
            "site_id",
            "import_id",
            "id",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )


def downgrade() -> None:
    op.drop_table("catalog_draft_identity_reservations")
