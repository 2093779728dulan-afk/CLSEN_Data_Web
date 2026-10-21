"""Add current raw-file integrity state and lease lookup indexes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0006"
down_revision = "0005"
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
        "raw_file_integrity_statuses",
        sa.Column("raw_file_id", _bigint(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "is_blocking",
            sa.Boolean(),
            sa.Computed("status <> 'available'", persisted=True),
            nullable=False,
        ),
        sa.Column("first_detected_at", _utc_datetime(), nullable=True),
        sa.Column("last_checked_at", _utc_datetime(), nullable=False),
        sa.Column("resolved_at", _utc_datetime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('available', 'missing', 'size_mismatch', 'hash_mismatch')",
            name="ck_raw_file_integrity_statuses_status",
        ),
        sa.CheckConstraint(
            "((status = 'available' AND "
            "((first_detected_at IS NULL AND resolved_at IS NULL) OR "
            "(first_detected_at IS NOT NULL AND resolved_at IS NOT NULL))) OR "
            "(status <> 'available' AND first_detected_at IS NOT NULL "
            "AND resolved_at IS NULL))",
            name="ck_raw_file_integrity_statuses_lifecycle",
        ),
        sa.CheckConstraint(
            "first_detected_at IS NULL OR first_detected_at <= last_checked_at",
            name="ck_raw_file_integrity_statuses_detected_order",
        ),
        sa.CheckConstraint(
            "resolved_at IS NULL OR resolved_at <= last_checked_at",
            name="ck_raw_file_integrity_statuses_checked_order",
        ),
        sa.CheckConstraint(
            "resolved_at IS NULL OR first_detected_at IS NULL "
            "OR first_detected_at <= resolved_at",
            name="ck_raw_file_integrity_statuses_resolved_order",
        ),
        sa.ForeignKeyConstraint(
            ["raw_file_id"],
            ["raw_files.id"],
            name="fk_raw_file_integrity_statuses_raw_file",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "raw_file_id",
            name="pk_raw_file_integrity_statuses",
        ),
        sa.Index(
            "ix_raw_file_integrity_blocking_checked",
            "is_blocking",
            "last_checked_at",
            "raw_file_id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_index(
        "ix_file_ingest_leases_storage_key_status_expires",
        "file_ingest_leases",
        ["storage_key", "status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_file_ingest_leases_sha256_status_expires",
        "file_ingest_leases",
        ["sha256", "status", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_file_ingest_leases_sha256_status_expires",
        table_name="file_ingest_leases",
    )
    op.drop_index(
        "ix_file_ingest_leases_storage_key_status_expires",
        table_name="file_ingest_leases",
    )
    op.drop_table("raw_file_integrity_statuses")
