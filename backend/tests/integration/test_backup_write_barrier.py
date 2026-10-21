from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.maintenance.backup import (
    BackupError,
    BackupSettings,
    create_backup,
    new_keyring,
    write_keyring,
)
from app.maintenance.barrier import (
    MaintenanceBarrierTimeout,
    hold_maintenance_write_barrier,
)

pytestmark = pytest.mark.mysql


def _settings_with_one_connection(settings: DatabaseSettings) -> DatabaseSettings:
    return DatabaseSettings(
        url=settings.url,
        pool_size=1,
        max_overflow=0,
    )


def test_backup_barrier_blocks_writes_but_keeps_reads_available(
    mysql_settings: DatabaseSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_MAINTENANCE_WRITE_LOCK_TIMEOUT_SECONDS", "0")
    backup_engine = create_database_engine(
        _settings_with_one_connection(mysql_settings)
    )
    writer_engine = create_database_engine(
        _settings_with_one_connection(mysql_settings)
    )
    try:
        with hold_maintenance_write_barrier(backup_engine, timeout_seconds=0):
            with writer_engine.connect() as reader:
                revision = reader.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                )
                reader.rollback()
            assert isinstance(revision, str)

            with (
                pytest.raises(MaintenanceBarrierTimeout, match="remained busy"),
                writer_engine.begin() as writer,
            ):
                writer.execute(
                    sa.text("UPDATE alembic_version SET version_num = version_num")
                )

        with writer_engine.begin() as writer:
            result = writer.execute(
                sa.text("UPDATE alembic_version SET version_num = version_num")
            )
        assert result.rowcount == 1
    finally:
        writer_engine.dispose()
        backup_engine.dispose()


def test_concurrent_writers_share_barrier_until_both_transactions_finish(
    mysql_settings: DatabaseSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_MAINTENANCE_WRITE_LOCK_TIMEOUT_SECONDS", "0")
    first_writer_engine = create_database_engine(
        _settings_with_one_connection(mysql_settings)
    )
    second_writer_engine = create_database_engine(
        _settings_with_one_connection(mysql_settings)
    )
    backup_engine = create_database_engine(
        _settings_with_one_connection(mysql_settings)
    )
    try:
        with first_writer_engine.begin() as first_writer:
            first_writer.execute(
                sa.text(
                    "UPDATE alembic_version SET version_num = version_num WHERE 1 = 0"
                )
            )

            with second_writer_engine.begin() as second_writer:
                second_writer.execute(
                    sa.text(
                        "UPDATE alembic_version "
                        "SET version_num = version_num WHERE 1 = 0"
                    )
                )

                with (
                    pytest.raises(MaintenanceBarrierTimeout, match="remained busy"),
                    hold_maintenance_write_barrier(backup_engine, timeout_seconds=0),
                ):
                    pytest.fail("backup acquired an exclusive writer barrier")

        with hold_maintenance_write_barrier(backup_engine, timeout_seconds=0):
            pass
    finally:
        backup_engine.dispose()
        second_writer_engine.dispose()
        first_writer_engine.dispose()


def test_dump_failure_preserves_a_durable_failed_snapshot(
    mysql_settings: DatabaseSettings,
    tmp_path: Path,
) -> None:
    backup_url = os.getenv("APP_TEST_BACKUP_DATABASE_URL")
    if backup_url is None or not backup_url.strip():
        pytest.fail("APP_TEST_BACKUP_DATABASE_URL is required", pytrace=False)
    backup_settings = DatabaseSettings.from_url(
        backup_url,
        pool_size=1,
        max_overflow=0,
    )
    key_id = f"failure-{uuid4().hex}"
    keyring_path = tmp_path / "keyring.json"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    write_keyring(keyring_path, new_keyring(key_id))

    migration_engine = create_database_engine(mysql_settings)
    snapshot_id: int | None = None
    try:
        with pytest.raises(BackupError, match="could not be executed safely"):
            create_backup(
                BackupSettings(
                    database=backup_settings,
                    storage_root=storage_root,
                    destination_root=tmp_path / "backups",
                    keyring_path=keyring_path,
                    mysqldump_executable=os.fspath(tmp_path / "missing-mysqldump.exe"),
                    lease_wait_timeout_seconds=0,
                )
            )

        with migration_engine.connect() as connection:
            snapshot = connection.execute(
                sa.text(
                    """
                    SELECT id, status, failure_code
                    FROM backup_snapshots
                    WHERE key_id = :key_id
                    """
                ),
                {"key_id": key_id},
            ).one()
            connection.rollback()
        snapshot_id = int(snapshot.id)
        assert str(snapshot.status) == "failed"
        assert str(snapshot.failure_code) == "backuperror"
    finally:
        if snapshot_id is not None:
            with migration_engine.begin() as connection:
                connection.execute(
                    sa.text("DELETE FROM backup_snapshots WHERE id = :snapshot_id"),
                    {"snapshot_id": snapshot_id},
                )
        migration_engine.dispose()
