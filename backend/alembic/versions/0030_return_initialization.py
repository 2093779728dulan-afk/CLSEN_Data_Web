"""Identify first-snapshot jobs without altering report publications."""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "return_dedup_staging_jobs",
        sa.Column("initialization_revision", sa.BigInteger(), nullable=True),
    )
    op.execute(
        """
        CREATE TRIGGER return_initialization_identity_guard BEFORE UPDATE ON
        return_dedup_staging_jobs FOR EACH ROW BEGIN IF NOT
        (OLD.initialization_revision <=> NEW.initialization_revision) THEN SIGNAL
        SQLSTATE '45000' SET MESSAGE_TEXT='initialization identity is immutable'; END
        IF; END
        """
    )


def downgrade() -> None:
    raise RuntimeError("Initialization evidence must be retained")
