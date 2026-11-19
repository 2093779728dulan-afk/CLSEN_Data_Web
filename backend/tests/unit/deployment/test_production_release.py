from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.deployment import entrypoint
from app.deployment.production import database_pair
from app.maintenance import production_backup as backup
from app.maintenance.backup import (
    BackupIntegrityError,
    encrypt_file,
    new_keyring,
    write_keyring,
)


@pytest.mark.parametrize(
    "catalog,orders",
    [
        ("clsen_data", "clsen_production"),
        ("clsen_data_test_release123", "clsen_production_test_release123"),
    ],
)
def test_paired_store_identity(catalog: str, orders: str) -> None:
    database_pair(catalog, orders)


@pytest.mark.parametrize(
    "catalog,orders",
    [
        ("clsen_data", "clsen_production_test_release123"),
        ("clsen_data_test_other", "clsen_production_test_release123"),
        ("clsen_data_test_release123", "clsen_production"),
        ("clsen_data", "clsen_production`; DROP DATABASE mysql;"),
    ],
)
def test_rejects_mixed_store_identity(catalog: str, orders: str) -> None:
    with pytest.raises(ValueError, match="paired"):
        database_pair(catalog, orders)


@pytest.mark.parametrize("command", ["api", "worker"])
def test_runtime_reads_internal_token_from_secret_file(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "x" * 48
    (tmp_path / "production_service_token").write_text(secret)
    monkeypatch.setenv("DEPLOYMENT_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("APP_PRODUCTION_SERVICE_URL", "http://production:23011")
    monkeypatch.setenv("APP_PRODUCTION_SERVICE_TOKEN", "stale-token")
    monkeypatch.setattr(entrypoint, "_configure_process_environment", MagicMock())
    monkeypatch.setattr(entrypoint, "schema_preflight_main", lambda _: 2)
    assert entrypoint.main([command]) == 2
    import os

    assert os.environ["APP_PRODUCTION_SERVICE_TOKEN"] == secret


def test_backup_requires_stopped_writers(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="writers"):
        backup.backup(tmp_path / "output", tmp_path / "keyring", {}, quiesced=False)
    assert not (tmp_path / "output").exists()


def synthetic_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    keyring = tmp_path / "keyring.json"
    write_keyring(keyring, new_keyring("release-test"))
    roots = {name: tmp_path / name for name in ["raw", "production"]}
    for root in roots.values():
        root.mkdir()
    (roots["raw"] / "source.csv").write_bytes(b"sku,units\nSIM,3\n")
    (roots["production"] / "review.json").write_bytes(b'{"status":"DRAFT"}')
    engine = MagicMock()
    monkeypatch.setattr(backup, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(
        backup,
        "connection_settings",
        lambda *a: (
            "clsen_production_backup",
            "x" * 48,
            "mysql",
            "/ca.pem",
            "unused",
        ),
    )
    monkeypatch.setattr(
        backup, "fingerprint", lambda *a: {"sim": {"rows": 1, "checksum": 123}}
    )
    monkeypatch.setattr(
        backup,
        "mysql_command",
        lambda args, **kw: kw["output"].write(
            b"CREATE TABLE sim (id int);\nINSERT INTO sim VALUES (1);\n"
        ),
    )
    directory = tmp_path / "backup"
    backup.backup(directory, keyring, roots, quiesced=True)
    return directory, keyring, roots


def test_encrypted_backup_covers_both_stores_and_all_source_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, keyring, roots = synthetic_backup(tmp_path, monkeypatch)
    target = tmp_path / "restored"
    manifest = backup.unpack(directory, keyring, target)
    assert set(manifest["databases"]) == {"catalog", "production"}
    assert set(manifest["files"]) == {"raw/source.csv", "production/review.json"}
    for name, root in roots.items():
        for source in root.iterdir():
            assert (
                target / "content" / name / source.name
            ).read_bytes() == source.read_bytes()
    assert not list(directory.glob("*.sql"))
    assert not list(directory.glob(".staging-*"))


def test_encrypted_backup_rejects_tampered_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, keyring, _ = synthetic_backup(tmp_path, monkeypatch)
    artifact = directory / "backup.enc"
    content = bytearray(artifact.read_bytes())
    content[-12] ^= 1
    artifact.write_bytes(content)
    with pytest.raises(BackupIntegrityError):
        backup.unpack(directory, keyring, tmp_path / "restored")


def test_archive_refuses_links_and_incomplete_source_sets(tmp_path: Path) -> None:
    keyring = new_keyring("release-test")
    keyring_file = tmp_path / "keyring.json"
    write_keyring(keyring_file, keyring)
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as bundle:
        info = tarfile.TarInfo("manifest.json")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../outside"
        bundle.addfile(info)
    directory = tmp_path / "backup"
    directory.mkdir()
    artifact = encrypt_file(
        archive,
        directory / "backup.enc",
        keyring=keyring,
        artifact_type="production-backup-v1",
    )
    from dataclasses import asdict

    (directory / "catalog.json").write_text(json.dumps({"artifact": asdict(artifact)}))
    with pytest.raises(ValueError, match="non-file"):
        backup.unpack(directory, keyring_file, tmp_path / "restored")


def test_restore_failure_cleans_only_new_test_databases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, keyring, _ = synthetic_backup(tmp_path, monkeypatch)
    monkeypatch.setenv("APP_DEPLOYMENT_DATABASE", "clsen_data_test_release")
    monkeypatch.setenv("PRODUCTION_DATABASE_NAME", "clsen_production_test_release")
    monkeypatch.setenv("APP_DISPOSABLE_TEST_RUN", "true")
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.return_value = 0
    monkeypatch.setattr(backup, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(
        backup,
        "mysql_command",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("synthetic failure")),
    )
    target = tmp_path / "restore-tests"
    with pytest.raises(RuntimeError, match="synthetic failure"):
        backup.restore_test(directory, keyring, target)
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    dropped = [sql for sql in statements if sql.startswith("DROP DATABASE")]
    assert len(dropped) == 1
    assert dropped[0].startswith("DROP DATABASE `clsen_data_test_restore_")
    assert list(target.iterdir()) == []


def test_restore_refuses_production_database_before_any_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DEPLOYMENT_DATABASE", "clsen_data")
    monkeypatch.setenv("PRODUCTION_DATABASE_NAME", "clsen_production")
    monkeypatch.setenv("APP_DISPOSABLE_TEST_RUN", "true")
    with pytest.raises(ValueError, match="disposable MySQL"):
        backup.restore_test(tmp_path, tmp_path, tmp_path)
