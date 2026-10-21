"""Add the immutable row used to coordinate writers with local backups."""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def upgrade() -> None:
    barrier = op.create_table(
        "maintenance_write_barrier",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("sentinel", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_maintenance_write_barrier"),
        sa.CheckConstraint(
            "id = 1 AND sentinel = 1",
            name="ck_maintenance_write_barrier_singleton",
        ),
        **_TABLE_OPTIONS,
    )
    op.bulk_insert(barrier, [{"id": 1, "sentinel": 1}])


def downgrade() -> None:
    connection = op.get_bind()
    row = connection.execute(
        sa.text("SELECT id, sentinel FROM maintenance_write_barrier")
    ).one_or_none()
    if row is None or tuple(row) != (1, 1):
        raise RuntimeError(
            "0019 downgrade refused because the maintenance barrier is invalid"
        )
    op.drop_table("maintenance_write_barrier")
