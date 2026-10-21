# ruff: noqa: E501
"""Include explicit exclusions in the shared draft identity reservation."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "catalog_draft_identity_reservations",
        sa.Column(
            "decision_kind",
            mysql.VARCHAR(16, charset="ascii", collation="ascii_bin"),
            nullable=False,
            server_default="mapped",
        ),
    )
    op.alter_column(
        "catalog_draft_identity_reservations",
        "target_sku_row_key",
        existing_type=mysql.VARCHAR(64, charset="ascii", collation="ascii_bin"),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_catalog_draft_reservation_decision",
        "catalog_draft_identity_reservations",
        "(decision_kind='mapped' AND target_sku_row_key IS NOT NULL) OR (decision_kind='excluded' AND target_sku_row_key IS NULL)",
    )


def downgrade() -> None:
    # Exclusion reservations cannot be represented by the older application.
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM catalog_draft_identity_reservations WHERE decision_kind='excluded'"
        )
    ):
        raise RuntimeError("Withdraw exclusion drafts before downgrade")
    op.drop_constraint(
        "ck_catalog_draft_reservation_decision",
        "catalog_draft_identity_reservations",
        type_="check",
    )
    op.alter_column(
        "catalog_draft_identity_reservations",
        "target_sku_row_key",
        existing_type=mysql.VARCHAR(64, charset="ascii", collation="ascii_bin"),
        nullable=False,
    )
    op.drop_column("catalog_draft_identity_reservations", "decision_kind")
