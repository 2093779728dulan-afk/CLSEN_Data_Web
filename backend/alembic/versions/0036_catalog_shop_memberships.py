"""Versioned approved shop membership independent of Seller SKU mappings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "product_catalog_shop_memberships",
        sa.Column("site_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("catalog_version_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "report_source_scope_id", mysql.BIGINT(unsigned=True), nullable=False
        ),
        sa.Column("sku_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("source_import_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("source_row_key", sa.String(128), nullable=True),
        sa.Column("evidence_digest", mysql.BINARY(32), nullable=False),
        sa.PrimaryKeyConstraint(
            "site_id", "catalog_version_id", "report_source_scope_id", "sku_id"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_version_id", "site_id", "sku_id"],
            [
                "product_catalog_sku_members.catalog_version_id",
                "product_catalog_sku_members.site_id",
                "product_catalog_sku_members.sku_id",
            ],
            name="fk_catalog_shop_member_sku",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_source_scope_id", "site_id"],
            ["report_source_scopes.id", "report_source_scopes.site_id"],
            name="fk_catalog_shop_member_scope",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_import_id", "site_id"],
            ["catalog_imports.id", "catalog_imports.site_id"],
            name="fk_catalog_shop_member_import",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    from app.maintenance.catalog_shop_membership_backfill import (
        backfill_shop_memberships,
    )

    backfill_shop_memberships(op.get_bind())
    for operation in ("UPDATE", "DELETE"):
        op.execute(
            sa.text(f"""
            CREATE TRIGGER trg_catalog_shop_members_no_{operation.lower()}
            BEFORE {operation} ON product_catalog_shop_memberships FOR EACH ROW
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM terminal_write_guard_bypass_accounts
                    WHERE account_identity=USER()) THEN
                    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='shop membership is
                    immutable';
                END IF;
            END
        """)
        )


def downgrade():
    raise RuntimeError("Approved shop membership history must be retained.")
