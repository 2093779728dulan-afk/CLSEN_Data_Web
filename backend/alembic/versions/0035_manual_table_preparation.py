"""Isolated manual-table sources, revisions, receipts and column profiles."""

from alembic import op
from app.manual_tables.models import batches, operations, profiles

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    batches.create(bind)
    operations.create(bind)
    profiles.create(bind)


def downgrade():
    raise RuntimeError(
        "Manual source evidence and handed-off business history must be retained."
    )
