"""Add durable backup manifests and isolated restore verification records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0018"
down_revision = "0017"
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


def _create_object_immutability_triggers() -> None:
    op.execute(
        """
        CREATE TRIGGER trg_backup_snapshot_objects_immutable_update
        BEFORE UPDATE ON backup_snapshot_objects
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'backup snapshot objects are immutable'
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_backup_snapshot_objects_immutable_delete
        BEFORE DELETE ON backup_snapshot_objects
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'backup snapshot objects are immutable'
        """
    )


def upgrade() -> None:
    op.create_table(
        "backup_snapshots",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("backup_uuid", mysql.BINARY(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("database_name", sa.String(length=64), nullable=False),
        sa.Column("schema_revision", sa.String(length=32), nullable=False),
        sa.Column("key_id", sa.String(length=128), nullable=False),
        sa.Column("manifest_sha256", mysql.BINARY(length=32), nullable=True),
        sa.Column(
            "raw_file_count",
            _bigint(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "publication_count",
            _bigint(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "version_count",
            _bigint(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "audit_event_count",
            _bigint(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("started_at", _utc_datetime(), nullable=False),
        sa.Column("sealed_at", _utc_datetime(), nullable=True),
        sa.Column("completed_at", _utc_datetime(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("restore_verified_at", _utc_datetime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_backup_snapshots"),
        sa.UniqueConstraint("backup_uuid", name="uq_backup_snapshots_uuid"),
        sa.CheckConstraint(
            "status IN ('running', 'sealed', 'succeeded', 'failed')",
            name="ck_backup_snapshots_status",
        ),
        sa.CheckConstraint(
            "((status = 'running' AND completed_at IS NULL "
            "AND sealed_at IS NULL AND manifest_sha256 IS NULL "
            "AND failure_code IS NULL) OR "
            "(status = 'sealed' AND completed_at IS NULL "
            "AND sealed_at IS NOT NULL AND manifest_sha256 IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(status = 'succeeded' AND completed_at IS NOT NULL "
            "AND sealed_at IS NOT NULL AND manifest_sha256 IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(status = 'failed' AND completed_at IS NOT NULL "
            "AND failure_code IS NOT NULL "
            "AND ((sealed_at IS NULL AND manifest_sha256 IS NULL) OR "
            "(sealed_at IS NOT NULL AND manifest_sha256 IS NOT NULL))))",
            name="ck_backup_snapshots_terminal_shape",
        ),
        sa.Index("ix_backup_snapshots_status_started", "status", "started_at", "id"),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "backup_snapshot_objects",
        sa.Column("backup_snapshot_id", _bigint(), nullable=False),
        sa.Column("raw_file_id", _bigint(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("sha256", mysql.BINARY(length=32), nullable=False),
        sa.Column("size_bytes", _bigint(), nullable=False),
        sa.ForeignKeyConstraint(
            ["backup_snapshot_id"],
            ["backup_snapshots.id"],
            name="fk_backup_snapshot_objects_snapshot",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_file_id"],
            ["raw_files.id"],
            name="fk_backup_snapshot_objects_raw_file",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "backup_snapshot_id",
            "raw_file_id",
            name="pk_backup_snapshot_objects",
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name="ck_backup_snapshot_objects_size_nonnegative",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "restore_verifications",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("verification_uuid", mysql.BINARY(length=16), nullable=False),
        sa.Column("backup_snapshot_id", _bigint(), nullable=False),
        sa.Column("target_database_name", sa.String(length=64), nullable=False),
        sa.Column(
            "target_storage_root_sha256", mysql.BINARY(length=32), nullable=False
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", _utc_datetime(), nullable=False),
        sa.Column("completed_at", _utc_datetime(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["backup_snapshot_id"],
            ["backup_snapshots.id"],
            name="fk_restore_verifications_snapshot",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_restore_verifications"),
        sa.UniqueConstraint(
            "verification_uuid",
            name="uq_restore_verifications_uuid",
        ),
        sa.CheckConstraint(
            "target_database_name LIKE 'clsen\\_restore\\_%'",
            name="ck_restore_verifications_target_database",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_restore_verifications_status",
        ),
        sa.CheckConstraint(
            "((status = 'running' AND completed_at IS NULL "
            "AND failure_code IS NULL) OR "
            "(status = 'succeeded' AND completed_at IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(status = 'failed' AND completed_at IS NOT NULL "
            "AND failure_code IS NOT NULL))",
            name="ck_restore_verifications_terminal_shape",
        ),
        sa.Index(
            "ix_restore_verifications_snapshot_completed",
            "backup_snapshot_id",
            "completed_at",
            "id",
        ),
        **_TABLE_OPTIONS,
    )

    _create_object_immutability_triggers()


def downgrade() -> None:
    connection = op.get_bind()
    snapshot_count = connection.scalar(sa.text("SELECT COUNT(*) FROM backup_snapshots"))
    verification_count = connection.scalar(
        sa.text("SELECT COUNT(*) FROM restore_verifications")
    )
    if snapshot_count or verification_count:
        raise RuntimeError(
            "0018 downgrade refused because backup or restore audit evidence exists"
        )

    op.execute("DROP TRIGGER IF EXISTS trg_backup_snapshot_objects_immutable_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_backup_snapshot_objects_immutable_update")
    op.drop_table("restore_verifications")
    op.drop_table("backup_snapshot_objects")
    op.drop_table("backup_snapshots")
