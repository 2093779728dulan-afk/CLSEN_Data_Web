from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.db.settings import DatabaseSettings
from app.maintenance.backup import (
    BackupIntegrityError,
    BackupSettings,
    decrypt_file,
    encrypt_file,
    load_keyring,
    new_keyring,
    rotate_keyring,
    verify_encrypted_file,
    write_keyring,
)


def _database(database: str = "clsen_data_test") -> DatabaseSettings:
    return DatabaseSettings.from_url(
        f"mysql+pymysql://backup:secret@127.0.0.1:3306/{database}?charset=utf8mb4"
    )


def test_keyring_roundtrip_and_rotation_retain_historical_key(tmp_path: Path) -> None:
    keyring_path = tmp_path / "keys.json"
    original = new_keyring("key-2026-08")
    write_keyring(keyring_path, original)

    loaded = load_keyring(keyring_path)
    rotated = rotate_keyring(loaded, "key-2026-09")
    write_keyring(keyring_path, rotated, overwrite=True)
    reloaded = load_keyring(keyring_path)

    assert reloaded.active_key_id == "key-2026-09"
    assert reloaded.keys["key-2026-08"] == original.keys["key-2026-08"]
    assert len(reloaded.keys["key-2026-09"]) == 32


def test_keyring_refuses_duplicate_json_keys(tmp_path: Path) -> None:
    keyring_path = tmp_path / "keys.json"
    keyring_path.write_text(
        '{"version":1,"version":1,"active_key_id":"a","keys":{}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_keyring(keyring_path)


def test_chunked_encryption_roundtrips_and_verifies_plaintext(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    encrypted = tmp_path / "source.bin.enc"
    decrypted = tmp_path / "decrypted.bin"
    content = bytes(range(256)) * 31
    source.write_bytes(content)
    keyring = new_keyring("active")

    artifact = encrypt_file(
        source,
        encrypted,
        keyring=keyring,
        artifact_type="unit_test",
        chunk_size=1024,
    )
    verify_encrypted_file(
        encrypted,
        keyring=keyring,
        expected_sha256=artifact.plaintext_sha256,
        expected_size=artifact.plaintext_size,
    )
    decrypt_file(encrypted, decrypted, keyring=keyring)

    assert decrypted.read_bytes() == content
    assert artifact.plaintext_size == len(content)
    assert artifact.ciphertext_size > artifact.plaintext_size


def test_encryption_uses_distinct_nonces_for_identical_plaintext(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    first = tmp_path / "first.enc"
    second = tmp_path / "second.enc"
    source.write_bytes(b"same plaintext")
    keyring = new_keyring("active")

    encrypt_file(source, first, keyring=keyring, artifact_type="test")
    encrypt_file(source, second, keyring=keyring, artifact_type="test")

    assert first.read_bytes() != second.read_bytes()


def test_encrypted_artifact_rejects_ciphertext_tampering(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    encrypted = tmp_path / "source.enc"
    source.write_bytes(b"sensitive source bytes" * 100)
    keyring = new_keyring("active")
    artifact = encrypt_file(
        source,
        encrypted,
        keyring=keyring,
        artifact_type="test",
        chunk_size=1024,
    )
    content = bytearray(encrypted.read_bytes())
    content[-8] ^= 0x80
    encrypted.write_bytes(content)

    with pytest.raises(BackupIntegrityError, match="authentication failed"):
        verify_encrypted_file(
            encrypted,
            keyring=keyring,
            expected_sha256=artifact.plaintext_sha256,
            expected_size=artifact.plaintext_size,
        )


def test_historical_artifact_requires_retained_key(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    encrypted = tmp_path / "source.enc"
    source.write_bytes(b"historical")
    original = new_keyring("old")
    artifact = encrypt_file(
        source,
        encrypted,
        keyring=original,
        artifact_type="test",
    )
    missing_old_key = new_keyring("new")

    with pytest.raises(BackupIntegrityError, match="historical keys"):
        verify_encrypted_file(
            encrypted,
            keyring=missing_old_key,
            expected_sha256=artifact.plaintext_sha256,
            expected_size=artifact.plaintext_size,
        )


@pytest.mark.parametrize("database", ["mysql", "clsen_data_restore", "clsen_data2"])
def test_backup_settings_reject_unsafe_database_names(
    tmp_path: Path,
    database: str,
) -> None:
    with pytest.raises(ValueError, match="backup database"):
        BackupSettings(
            database=_database(database),
            storage_root=tmp_path / "raw",
            destination_root=tmp_path / "backup",
            keyring_path=tmp_path / "keys.json",
        )


def test_keyring_format_contains_no_plaintext_metadata_beyond_key_contract(
    tmp_path: Path,
) -> None:
    keyring_path = tmp_path / "keys.json"
    write_keyring(keyring_path, new_keyring("active"))

    payload = json.loads(keyring_path.read_text(encoding="utf-8"))

    assert set(payload) == {"version", "active_key_id", "keys"}
