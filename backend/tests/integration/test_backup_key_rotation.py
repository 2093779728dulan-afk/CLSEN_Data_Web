from pathlib import Path

import pytest
from app.maintenance.backup import (
    BackupIntegrityError,
    BackupKeyring,
    encrypt_file,
    load_keyring,
    new_keyring,
    rotate_keyring,
    verify_encrypted_file,
    write_keyring,
)


def test_rotation_uses_new_key_and_retains_historical_restore_capability(
    tmp_path: Path,
) -> None:
    keyring_path = tmp_path / "external-keyring.json"
    old_source = tmp_path / "old.sql"
    new_source = tmp_path / "new.sql"
    old_encrypted = tmp_path / "old.sql.enc"
    new_encrypted = tmp_path / "new.sql.enc"
    old_source.write_bytes(b"historical database snapshot")
    new_source.write_bytes(b"new database snapshot")

    original = new_keyring("key-before-rotation")
    write_keyring(keyring_path, original)
    old_artifact = encrypt_file(
        old_source,
        old_encrypted,
        keyring=load_keyring(keyring_path),
        artifact_type="mysql_dump",
    )

    rotated = rotate_keyring(load_keyring(keyring_path), "key-after-rotation")
    write_keyring(keyring_path, rotated, overwrite=True)
    reloaded = load_keyring(keyring_path)
    new_artifact = encrypt_file(
        new_source,
        new_encrypted,
        keyring=reloaded,
        artifact_type="mysql_dump",
    )

    for encrypted, artifact in (
        (old_encrypted, old_artifact),
        (new_encrypted, new_artifact),
    ):
        verify_encrypted_file(
            encrypted,
            keyring=reloaded,
            expected_sha256=artifact.plaintext_sha256,
            expected_size=artifact.plaintext_size,
        )

    missing_historical_key = BackupKeyring(
        active_key_id="key-after-rotation",
        keys={
            "key-after-rotation": reloaded.keys["key-after-rotation"],
        },
    )
    with pytest.raises(BackupIntegrityError, match="historical keys"):
        verify_encrypted_file(
            old_encrypted,
            keyring=missing_historical_key,
            expected_sha256=old_artifact.plaintext_sha256,
            expected_size=old_artifact.plaintext_size,
        )
