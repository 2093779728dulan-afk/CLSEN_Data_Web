"""Command-line entry points for local backup and key lifecycle operations."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import NoReturn

from dotenv import load_dotenv

from app.db.settings import DatabaseSettings
from app.maintenance.backup import (
    BackupSettings,
    create_backup,
    load_keyring,
    new_keyring,
    rotate_keyring,
    write_keyring,
)
from app.maintenance.restore import RestoreSettings, verify_restore


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clsen-maintenance")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("keyring-init")
    create.add_argument("--path", required=True, type=_path)
    create.add_argument("--key-id", required=True)

    rotate = commands.add_parser("keyring-rotate")
    rotate.add_argument("--path", required=True, type=_path)
    rotate.add_argument("--key-id", required=True)

    backup = commands.add_parser("backup")
    backup.add_argument("--destination", required=True, type=_path)
    backup.add_argument("--keyring", required=True, type=_path)
    backup.add_argument(
        "--database-environment",
        choices=("APP_BACKUP_DATABASE_URL", "APP_TEST_BACKUP_DATABASE_URL"),
        default="APP_BACKUP_DATABASE_URL",
    )
    backup.add_argument("--mysqldump", default="mysqldump")
    backup.add_argument("--lock-timeout", type=int, default=30)
    backup.add_argument("--lease-wait-timeout", type=int, default=300)
    backup.add_argument("--retention-count", type=int, default=30)

    restore = commands.add_parser("restore-verify")
    restore.add_argument("--backup-directory", required=True, type=_path)
    restore.add_argument("--temporary-root", required=True, type=_path)
    restore.add_argument("--keyring", required=True, type=_path)
    restore.add_argument("--administrator-option-file", required=True, type=_path)
    restore.add_argument(
        "--source-database-environment",
        choices=("APP_BACKUP_DATABASE_URL", "APP_TEST_BACKUP_DATABASE_URL"),
        default="APP_BACKUP_DATABASE_URL",
    )
    restore.add_argument("--mysql", default="mysql")
    restore.add_argument("--cleanup", action="store_true")
    return parser


def _fail(message: str) -> NoReturn:
    raise SystemExit(message)


def main(arguments: list[str] | None = None) -> int:
    """Run one explicit maintenance command without logging secret values."""

    options = _parser().parse_args(arguments)
    repository_root = _repository_root()
    load_dotenv(repository_root / ".env", override=False)

    if options.command == "keyring-init":
        write_keyring(options.path, new_keyring(options.key_id))
        print(json.dumps({"status": "created", "key_id": options.key_id}))
        return 0
    if options.command == "keyring-rotate":
        current = load_keyring(options.path)
        rotated = rotate_keyring(current, options.key_id)
        write_keyring(options.path, rotated, overwrite=True)
        print(
            json.dumps(
                {
                    "status": "rotated",
                    "key_id": options.key_id,
                    "retained_key_count": len(rotated.keys),
                }
            )
        )
        return 0
    if options.command == "restore-verify":
        storage_value = os.getenv("APP_STORAGE_ROOT")
        if storage_value is None or not storage_value.strip():
            _fail("APP_STORAGE_ROOT must be configured")
        executable = shutil.which(options.mysql)
        if executable is None:
            _fail("mysql executable is not available on PATH")
        restore_result = verify_restore(
            RestoreSettings(
                backup_directory=options.backup_directory,
                temporary_root=options.temporary_root,
                keyring_path=options.keyring,
                source_database=DatabaseSettings.from_env(
                    options.source_database_environment,
                    pool_size=1,
                    max_overflow=0,
                ),
                administrator_option_file=options.administrator_option_file,
                mysql_executable=executable,
                cleanup_after_success=options.cleanup,
                forbidden_roots=(repository_root, _path(storage_value)),
            )
        )
        print(
            json.dumps(
                {
                    "status": "succeeded",
                    "verification_uuid": restore_result.verification_uuid.hex,
                    "backup_uuid": restore_result.backup_uuid.hex,
                    "database_name": restore_result.database_name,
                    "target_directory": str(restore_result.target_directory),
                    "retained": restore_result.retained,
                }
            )
        )
        return 0
    if options.command != "backup":
        _fail("unsupported maintenance command")

    storage_value = os.getenv("APP_STORAGE_ROOT")
    if storage_value is None or not storage_value.strip():
        _fail("APP_STORAGE_ROOT must be configured")
    executable = shutil.which(options.mysqldump)
    if executable is None:
        _fail("mysqldump executable is not available on PATH")
    settings = BackupSettings(
        database=DatabaseSettings.from_env(
            options.database_environment,
            pool_size=1,
            max_overflow=0,
        ),
        storage_root=_path(storage_value),
        destination_root=options.destination,
        keyring_path=options.keyring,
        mysqldump_executable=executable,
        lock_timeout_seconds=options.lock_timeout,
        lease_wait_timeout_seconds=options.lease_wait_timeout,
        retention_count=options.retention_count,
    )
    backup_result = create_backup(settings)
    print(
        json.dumps(
            {
                "status": "succeeded",
                "backup_uuid": backup_result.backup_uuid.hex,
                "snapshot_id": backup_result.snapshot_id,
                "directory": str(backup_result.directory),
                "key_id": backup_result.key_id,
                "manifest_sha256": backup_result.manifest_sha256,
                "artifact_count": backup_result.artifact_count,
                "pruned_count": backup_result.pruned_count,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
