"""Nullable formal SKU with explicit, revisioned provenance."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("product_skus", "product_sku_revisions"):
        for column, kind in (
            ("internal_display_sku", sa.String(128)),
            ("display_key_sha256", mysql.BINARY(32)),
            ("display_key_bytes", mysql.VARBINARY(512)),
        ):
            op.alter_column(table, column, existing_type=kind, nullable=True)
        op.add_column(
            table,
            sa.Column(
                "code_status", sa.String(16), nullable=False, server_default="legacy"
            ),
        )
        op.add_column(table, sa.Column("code_evidence", sa.Text(), nullable=True))
        op.create_check_constraint(
            "ck_" + table + "_formal_code",
            table,
            "(internal_display_sku IS NULL AND display_key_sha256 IS NULL AND "
            "display_key_bytes IS NULL "
            "AND code_status='pending' AND code_evidence IS NOT NULL AND "
            "CHAR_LENGTH(TRIM(code_evidence))>0) OR "
            "(internal_display_sku IS NOT NULL AND "
            "CHAR_LENGTH(TRIM(internal_display_sku))>0 "
            "AND display_key_sha256 IS NOT NULL AND display_key_bytes IS NOT NULL "
            "AND ((code_status='confirmed' AND code_evidence IS NOT NULL AND "
            "CHAR_LENGTH(TRIM(code_evidence))>0) "
            "OR code_status='legacy'))",
        )


def downgrade():
    raise RuntimeError(
        "Formal SKU history must be retained; restore a verified backup instead."
    )
