from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from app.db.settings import DatabaseSettings
from app.maintenance.backup import (
    BackupIntegrityError,
    encrypt_file,
    new_keyring,
    write_keyring,
)
from app.maintenance.restore import RestoreSettings, _verify_database, verify_restore


def _database() -> DatabaseSettings:
    return DatabaseSettings.from_url(
        "mysql+pymysql://backup:secret@127.0.0.1:3306/clsen_data_test?charset=utf8mb4"
    )


def _settings(
    tmp_path: Path,
    *,
    backup_directory: Path,
    keyring_path: Path,
) -> RestoreSettings:
    option_file = tmp_path / "administrator.cnf"
    option_file.write_text("[client]\nuser=root\n", encoding="utf-8")
    return RestoreSettings(
        backup_directory=backup_directory,
        temporary_root=tmp_path / "restores",
        keyring_path=keyring_path,
        source_database=_database(),
        administrator_option_file=option_file,
        mysql_executable="mysql.exe",
    )


def test_restore_settings_reject_production_root_as_temporary_root(
    tmp_path: Path,
) -> None:
    production_root = tmp_path / "raw"

    with pytest.raises(ValueError, match="forbidden production root"):
        RestoreSettings(
            backup_directory=tmp_path / uuid4().hex,
            temporary_root=production_root,
            keyring_path=tmp_path / "keys.json",
            source_database=_database(),
            administrator_option_file=tmp_path / "admin.cnf",
            forbidden_roots=(production_root,),
        )


def test_restore_rejects_catalog_artifact_path_traversal(tmp_path: Path) -> None:
    backup_directory = tmp_path / uuid4().hex
    backup_directory.mkdir()
    keyring_path = tmp_path / "keys.json"
    write_keyring(keyring_path, new_keyring("active"))
    catalog = {
        "format": "clsen-local-backup-catalog-v1",
        "backup_uuid": backup_directory.name,
        "snapshot_id": 1,
        "key_id": "active",
        "manifest_sha256": "0" * 64,
        "status": "verified",
        "artifacts": [
            {
                "relative_path": "../outside.enc",
                "artifact_type": "manifest",
                "plaintext_sha256": "0" * 64,
                "plaintext_size": 0,
                "ciphertext_sha256": "0" * 64,
                "ciphertext_size": 0,
            }
        ],
    }
    (backup_directory / "backup.json").write_text(
        json.dumps(catalog),
        encoding="utf-8",
    )

    with pytest.raises(BackupIntegrityError, match="path is unsafe"):
        verify_restore(
            _settings(
                tmp_path,
                backup_directory=backup_directory,
                keyring_path=keyring_path,
            )
        )


def test_restore_rejects_catalogued_ciphertext_tampering(tmp_path: Path) -> None:
    backup_directory = tmp_path / uuid4().hex
    backup_directory.mkdir()
    keyring_path = tmp_path / "keys.json"
    keyring = new_keyring("active")
    write_keyring(keyring_path, keyring)
    plaintext = tmp_path / "manifest.json"
    plaintext.write_text("{}\n", encoding="utf-8")
    encrypted = backup_directory / "manifest.json.enc"
    artifact = encrypt_file(
        plaintext,
        encrypted,
        keyring=keyring,
        artifact_type="manifest",
    )
    catalog = {
        "format": "clsen-local-backup-catalog-v1",
        "backup_uuid": backup_directory.name,
        "snapshot_id": 1,
        "key_id": "active",
        "manifest_sha256": artifact.plaintext_sha256,
        "status": "verified",
        "artifacts": [
            {
                "relative_path": encrypted.name,
                "artifact_type": artifact.artifact_type,
                "plaintext_sha256": artifact.plaintext_sha256,
                "plaintext_size": artifact.plaintext_size,
                "ciphertext_sha256": artifact.ciphertext_sha256,
                "ciphertext_size": artifact.ciphertext_size,
            }
        ],
    }
    (backup_directory / "backup.json").write_text(
        json.dumps(catalog),
        encoding="utf-8",
    )
    changed = bytearray(encrypted.read_bytes())
    changed[-8] ^= 1
    encrypted.write_bytes(changed)

    with pytest.raises(BackupIntegrityError, match="differs from its catalogue"):
        verify_restore(
            _settings(
                tmp_path,
                backup_directory=backup_directory,
                keyring_path=keyring_path,
            )
        )


def test_restore_verifies_the_actual_current_site_config_column(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        tmp_path,
        backup_directory=tmp_path / uuid4().hex,
        keyring_path=tmp_path / "keys.json",
    )

    def run_mysql(
        _settings: RestoreSettings,
        *,
        operation: str,
        sql: str | None = None,
        **_kwargs: object,
    ) -> str:
        if operation == "verify restored database counts":
            return "0022\t2\t1\t3\t4\t5\t6\t7\t8"
        if operation == "verify restored site pointers":
            assert sql is not None
            assert "SELECT site_id, current_config_version_id" in sql
            return "1\t7"
        assert operation == "verify restored semantic checksum"
        assert sql == "CHECKSUM TABLE `product_styles`;"
        return "product_styles\t123"

    monkeypatch.setattr("app.maintenance.restore._run_mysql", run_mysql)

    _verify_database(
        settings,
        f"clsen_restore_{uuid4().hex}",
        {
            "schema_revision": "0022",
            "counts": {
                "raw_file_count": 2,
                "publication_count": 1,
                "version_count": 3,
                "audit_event_count": 4,
                "catalog_version_count": 5,
                "catalog_mapping_count": 6,
                "return_dedup_snapshot_count": 7,
                "fact_snapshot_tuple_count": 8,
            },
            "site_current_configs": [{"site_id": 1, "site_config_version_id": 7}],
            "semantic_table_checksums": {"product_styles": "123"},
        },
    )
