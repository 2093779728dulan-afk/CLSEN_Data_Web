"""Repair historical shop membership without changing product or stock identity."""

from alembic import op
from app.maintenance.catalog_shop_membership_backfill import backfill_shop_memberships

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade():
    backfill_shop_memberships(op.get_bind())


def downgrade():
    raise RuntimeError(
        "Confirmed shop membership and catalog history must be retained."
    )
