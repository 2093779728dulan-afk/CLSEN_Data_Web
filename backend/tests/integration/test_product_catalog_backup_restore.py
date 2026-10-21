from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.settings import DatabaseSettings
from app.maintenance.backup import (
    BackupSettings,
    create_backup,
    load_keyring,
    new_keyring,
    verify_encrypted_file,
    write_keyring,
)
from app.maintenance.restore import RestoreSettings, verify_restore
from app.maintenance.schema_revision import (
    BACKUP_READER_SCHEMA_REVISIONS,
    CURRENT_SCHEMA_REVISION,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_ROOT = REPOSITORY_ROOT / "backend" / "tests" / "fixtures" / "backups" / "v1_0020"


def _decode_golden(source: Path, destination: Path) -> None:
    destination.write_bytes(
        base64.b64decode(source.read_text(encoding="ascii").strip(), validate=True)
    )


def test_current_reader_authenticates_independent_v1_0020_golden(
    tmp_path: Path,
) -> None:
    catalog = json.loads((GOLDEN_ROOT / "catalog.json").read_text(encoding="utf-8"))
    sums = json.loads((GOLDEN_ROOT / "sha256sums.json").read_text(encoding="utf-8"))
    keyring = load_keyring(GOLDEN_ROOT / "test-keyring.json")
    assert "0020" in BACKUP_READER_SCHEMA_REVISIONS
    for artifact in catalog["artifacts"]:
        decoded = tmp_path / artifact["relative_path"]
        _decode_golden(GOLDEN_ROOT / artifact["relative_path"], decoded)
        assert (
            hashlib.sha256(decoded.read_bytes()).hexdigest()
            == artifact["ciphertext_sha256"]
        )
        assert (
            sums[artifact["relative_path"]]["ciphertext_sha256"]
            == artifact["ciphertext_sha256"]
        )
        verify_encrypted_file(
            decoded,
            keyring=keyring,
            expected_sha256=artifact["plaintext_sha256"],
            expected_size=artifact["plaintext_size"],
        )


@pytest.mark.mysql
def test_current_head_encrypted_backup_restores_to_random_database(
    tmp_path: Path,
) -> None:
    if os.getenv("APP_REQUIRE_PRODUCT_CATALOG_BACKUP_RESTORE") != "1":
        pytest.skip("canonical backup/restore runner is required")
    mysqldump = shutil.which("mysqldump.exe") or shutil.which("mysqldump")
    mysql = shutil.which("mysql.exe") or shutil.which("mysql")
    if not mysqldump or not mysql:
        pytest.fail("MySQL backup/restore clients are required", pytrace=False)
    source = DatabaseSettings.from_env(
        "APP_TEST_BACKUP_DATABASE_URL", pool_size=1, max_overflow=0
    )
    migrations = ScriptDirectory.from_config(
        Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))
    )
    assert migrations.get_heads() == [CURRENT_SCHEMA_REVISION]
    assert "0023" in BACKUP_READER_SCHEMA_REVISIONS
    assert "0024" in BACKUP_READER_SCHEMA_REVISIONS
    assert "0025" in BACKUP_READER_SCHEMA_REVISIONS
    assert "0026" in BACKUP_READER_SCHEMA_REVISIONS
    assert "0027" in BACKUP_READER_SCHEMA_REVISIONS
    assert "0028" in BACKUP_READER_SCHEMA_REVISIONS
    assert "0029" in BACKUP_READER_SCHEMA_REVISIONS
    assert CURRENT_SCHEMA_REVISION in BACKUP_READER_SCHEMA_REVISIONS
    storage = tmp_path / "storage"
    destination = tmp_path / "backups"
    restore_root = tmp_path / "restore"
    storage.mkdir()
    keyring_path = tmp_path / "keyring.json"
    write_keyring(keyring_path, new_keyring("current-head-test"))
    result = create_backup(
        BackupSettings(
            database=source,
            storage_root=storage,
            destination_root=destination,
            keyring_path=keyring_path,
            mysqldump_executable=mysqldump,
            retention_count=2,
        )
    )
    url = source.url
    option_file = tmp_path / "administrator.cnf"
    ca_path = str(url.query.get("ssl_ca", ""))
    if ca_path:
        ca_path = Path(ca_path).as_posix()
    option_file.write_text(
        "[client]\n"
        "user=root\n"
        f"host={url.host}\n"
        f"port={url.port}\n"
        "protocol=TCP\n"
        "default-character-set=utf8mb4\n"
        + (f'ssl-ca="{ca_path}"\nssl-mode=VERIFY_CA\n' if ca_path else ""),
        encoding="utf-8",
    )
    restored = verify_restore(
        RestoreSettings(
            backup_directory=result.directory,
            temporary_root=restore_root,
            keyring_path=keyring_path,
            source_database=source,
            administrator_option_file=option_file,
            mysql_executable=mysql,
            cleanup_after_success=True,
            forbidden_roots=(storage, destination),
        )
    )
    assert restored.database_name.startswith("clsen_restore_")
    assert restored.retained is False
    assert not restored.target_directory.exists()
