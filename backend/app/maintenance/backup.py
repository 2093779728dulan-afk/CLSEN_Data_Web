"""Encrypted, auditable local backups for the daily data review platform."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import struct
import subprocess
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.engine import URL, Connection, Engine

from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.maintenance.barrier import hold_maintenance_write_barrier
from app.maintenance.schema_revision import CURRENT_SCHEMA_REVISION

_MAGIC: Final = b"CLSEN-BACKUP-AESGCM-1\n"
_FORMAT_VERSION: Final = 1
_DEFAULT_CHUNK_SIZE: Final = 4 * 1024 * 1024
_KEY_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DATABASE_PATTERN: Final = re.compile(
    r"(?:clsen_data|clsen_data_test(?:_[a-z0-9_]+)?)\Z"
)
_STORAGE_KEY_PATTERN: Final = re.compile(r"sha256/[0-9a-f]{2}/[0-9a-f]{64}\Z")
_BACKUP_DIRECTORY_PATTERN: Final = re.compile(r"[0-9a-f]{32}\Z")
_SEMANTIC_CHECKSUM_TABLES: Final = (
    "audit_events",
    "business_report_rows",
    "catalog_audit_events",
    "catalog_draft_identity_reservations",
    "catalog_style_change_drafts",
    "daily_datasets",
    "dataset_publications",
    "fact_snapshot_tuples",
    "product_catalog_exclusions",
    "product_catalog_mappings",
    "product_catalog_publications",
    "product_catalog_sku_members",
    "product_catalog_style_members",
    "product_catalog_versions",
    "product_categories",
    "product_category_aliases",
    "product_identity_key_reservations",
    "product_sku_revisions",
    "product_skus",
    "product_style_revisions",
    "product_styles",
    "publication_snapshot_members",
    "publication_snapshots",
    "return_dedup_group_members",
    "return_dedup_group_revisions",
    "return_dedup_publications",
    "return_dedup_snapshot_groups",
    "return_dedup_snapshots",
    "return_report_rows",
    "version_rows",
)


class BackupError(RuntimeError):
    """A backup could not be completed without weakening safety guarantees."""


class BackupIntegrityError(BackupError):
    """Backup plaintext, ciphertext, or source content failed verification."""


@dataclass(frozen=True, slots=True)
class BackupKeyring:
    """External AES-256 keyring with one active key and retained historical keys."""

    active_key_id: str
    keys: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if _KEY_ID_PATTERN.fullmatch(self.active_key_id) is None:
            raise ValueError("active backup key ID is invalid")
        if self.active_key_id not in self.keys:
            raise ValueError("active backup key is missing from keyring")
        for key_id, key in self.keys.items():
            if _KEY_ID_PATTERN.fullmatch(key_id) is None:
                raise ValueError("backup keyring contains an invalid key ID")
            if not isinstance(key, bytes) or len(key) != 32:
                raise ValueError("every backup key must contain exactly 32 bytes")

    def key(self, key_id: str) -> bytes:
        try:
            return self.keys[key_id]
        except KeyError as error:
            raise BackupIntegrityError(
                f"backup key {key_id!r} is unavailable; retain historical keys"
            ) from error


@dataclass(frozen=True, slots=True)
class EncryptedArtifact:
    """Integrity metadata for one encrypted backup artifact."""

    relative_path: str
    artifact_type: str
    plaintext_sha256: str
    plaintext_size: int
    ciphertext_sha256: str
    ciphertext_size: int


@dataclass(frozen=True, slots=True)
class BackupResult:
    """Completed local backup identity and output location."""

    backup_uuid: UUID
    snapshot_id: int
    directory: Path
    key_id: str
    manifest_sha256: str
    artifact_count: int
    pruned_count: int


@dataclass(frozen=True, slots=True)
class BackupSettings:
    """Explicit local backup inputs and bounded operational timings."""

    database: DatabaseSettings
    storage_root: Path
    destination_root: Path
    keyring_path: Path
    mysqldump_executable: str = "mysqldump.exe"
    lock_timeout_seconds: int = 30
    lease_wait_timeout_seconds: int = 300
    retention_count: int = 30

    def __post_init__(self) -> None:
        database_name = self.database.url.database or ""
        if _DATABASE_PATTERN.fullmatch(database_name) is None:
            raise ValueError("backup database must be clsen_data or clsen_data_test*")
        for name, path in (
            ("storage root", self.storage_root),
            ("destination root", self.destination_root),
            ("keyring path", self.keyring_path),
        ):
            resolved = Path(os.path.abspath(os.fspath(path)))
            if not resolved.is_absolute() or resolved == Path(resolved.anchor):
                raise ValueError(f"{name} must be an explicit non-root absolute path")
            object.__setattr__(self, name.replace(" ", "_"), resolved)
        if self.destination_root == self.storage_root:
            raise ValueError(
                "backup destination must differ from the source storage root"
            )
        if not 0 <= self.lock_timeout_seconds <= 300:
            raise ValueError("backup lock timeout must be between 0 and 300 seconds")
        if not 0 <= self.lease_wait_timeout_seconds <= 3600:
            raise ValueError("lease wait timeout must be between 0 and 3600 seconds")
        if self.retention_count < 1:
            raise ValueError("retention count must be at least one")
        if not self.mysqldump_executable.strip():
            raise ValueError("mysqldump executable must not be blank")


def _json_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def load_keyring(path: Path) -> BackupKeyring:
    """Load a strict external keyring without accepting duplicate JSON keys."""

    resolved = Path(os.path.abspath(os.fspath(path)))
    if resolved.is_symlink() or not resolved.is_file():
        raise ValueError("backup keyring must be an existing regular non-symlink file")
    try:
        payload = json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=_json_without_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("backup keyring is unreadable or invalid JSON") from error
    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "active_key_id",
        "keys",
    }:
        raise ValueError("backup keyring has an unexpected shape")
    if payload["version"] != 1 or type(payload["version"]) is not int:
        raise ValueError("backup keyring version must be the integer 1")
    active_key_id = payload["active_key_id"]
    encoded_keys = payload["keys"]
    if not isinstance(active_key_id, str) or not isinstance(encoded_keys, dict):
        raise ValueError("backup keyring fields have invalid types")
    keys: dict[str, bytes] = {}
    for key_id, encoded_key in encoded_keys.items():
        if not isinstance(key_id, str) or not isinstance(encoded_key, str):
            raise ValueError("backup keyring entries must be strings")
        try:
            key = base64.b64decode(encoded_key, validate=True)
        except ValueError as error:
            raise ValueError("backup keyring contains invalid base64") from error
        keys[key_id] = key
    return BackupKeyring(active_key_id=active_key_id, keys=keys)


def write_keyring(
    path: Path, keyring: BackupKeyring, *, overwrite: bool = False
) -> None:
    """Atomically persist a keyring; callers must also enforce platform ACLs."""

    resolved = Path(os.path.abspath(os.fspath(path)))
    if resolved == Path(resolved.anchor):
        raise ValueError("keyring path must not be a filesystem root")
    if resolved.exists() and not overwrite:
        raise FileExistsError("refusing to overwrite an existing backup keyring")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.parent.is_symlink() or resolved.is_symlink():
        raise ValueError("backup keyring path must not traverse a final symlink")
    payload = {
        "version": 1,
        "active_key_id": keyring.active_key_id,
        "keys": {
            key_id: base64.b64encode(key).decode("ascii")
            for key_id, key in sorted(keyring.keys.items())
        },
    }
    temporary = resolved.with_name(f".{resolved.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            os.chmod(temporary, 0o600)
            stream.write(_canonical_json(payload) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, resolved)
        os.chmod(resolved, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def new_keyring(key_id: str) -> BackupKeyring:
    """Create an in-memory keyring with a random active AES-256 key."""

    return BackupKeyring(active_key_id=key_id, keys={key_id: secrets.token_bytes(32)})


def rotate_keyring(keyring: BackupKeyring, key_id: str) -> BackupKeyring:
    """Add a new active key while retaining every referenced historical key."""

    if key_id in keyring.keys:
        raise ValueError("new backup key ID already exists")
    return BackupKeyring(
        active_key_id=key_id,
        keys={**keyring.keys, key_id: secrets.token_bytes(32)},
    )


def _read_exact(stream: BinaryIO, size: int, *, label: str) -> bytes:
    value = stream.read(size)
    if len(value) != size:
        raise BackupIntegrityError(f"encrypted {label} is truncated")
    return value


def encrypt_file(
    source: Path,
    destination: Path,
    *,
    keyring: BackupKeyring,
    artifact_type: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> EncryptedArtifact:
    """Stream one file through independent AES-256-GCM chunks."""

    if chunk_size < 1024 or chunk_size > 64 * 1024 * 1024:
        raise ValueError("encryption chunk size is outside the supported range")
    if not artifact_type or len(artifact_type) > 128:
        raise ValueError("artifact type must be between 1 and 128 characters")
    source = Path(os.path.abspath(os.fspath(source)))
    destination = Path(os.path.abspath(os.fspath(destination)))
    if source.is_symlink() or not source.is_file():
        raise BackupIntegrityError("backup source must be a regular non-symlink file")
    if destination.exists():
        raise FileExistsError("refusing to overwrite an encrypted backup artifact")
    destination.parent.mkdir(parents=True, exist_ok=True)

    key_id = keyring.active_key_id
    key = keyring.key(key_id)
    aes = AESGCM(key)
    nonce_prefix = secrets.token_bytes(8)
    header = _canonical_json(
        {
            "algorithm": "AES-256-GCM",
            "artifact_type": artifact_type,
            "chunk_size": chunk_size,
            "key_id": key_id,
            "nonce_prefix": base64.b64encode(nonce_prefix).decode("ascii"),
            "version": _FORMAT_VERSION,
        }
    )
    if len(header) > 64 * 1024:
        raise ValueError("encrypted artifact header is too large")

    plaintext_hash = hashlib.sha256()
    plaintext_size = 0
    counter = 0
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with source.open("rb") as source_stream, temporary.open("xb") as output:
            os.chmod(temporary, 0o600)
            output.write(_MAGIC)
            output.write(struct.pack(">I", len(header)))
            output.write(header)
            while chunk := source_stream.read(chunk_size):
                if counter >= 2**32:
                    raise BackupError("encrypted artifact exceeded the chunk limit")
                length = struct.pack(">I", len(chunk))
                counter_bytes = struct.pack(">I", counter)
                nonce = nonce_prefix + counter_bytes
                associated_data = _MAGIC + header + counter_bytes + length
                ciphertext = aes.encrypt(nonce, chunk, associated_data)
                output.write(length)
                output.write(ciphertext)
                plaintext_hash.update(chunk)
                plaintext_size += len(chunk)
                counter += 1
            output.write(struct.pack(">I", 0))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        temporary.unlink(missing_ok=True)

    ciphertext_hash, ciphertext_size = sha256_file(destination)
    return EncryptedArtifact(
        relative_path=destination.name,
        artifact_type=artifact_type,
        plaintext_sha256=plaintext_hash.hexdigest(),
        plaintext_size=plaintext_size,
        ciphertext_sha256=ciphertext_hash,
        ciphertext_size=ciphertext_size,
    )


def iter_decrypted_chunks(
    source: Path,
    *,
    keyring: BackupKeyring,
) -> Iterator[bytes]:
    """Authenticate and yield plaintext chunks from one encrypted artifact."""

    source = Path(os.path.abspath(os.fspath(source)))
    if source.is_symlink() or not source.is_file():
        raise BackupIntegrityError("encrypted artifact must be a regular file")
    with source.open("rb") as stream:
        if _read_exact(stream, len(_MAGIC), label="artifact") != _MAGIC:
            raise BackupIntegrityError("encrypted artifact magic is invalid")
        header_size = struct.unpack(">I", _read_exact(stream, 4, label="header"))[0]
        if header_size == 0 or header_size > 64 * 1024:
            raise BackupIntegrityError("encrypted artifact header size is invalid")
        header = _read_exact(stream, header_size, label="header")
        try:
            metadata = json.loads(
                header.decode("utf-8"),
                object_pairs_hook=_json_without_duplicate_keys,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise BackupIntegrityError(
                "encrypted artifact header is invalid"
            ) from error
        if not isinstance(metadata, dict) or set(metadata) != {
            "algorithm",
            "artifact_type",
            "chunk_size",
            "key_id",
            "nonce_prefix",
            "version",
        }:
            raise BackupIntegrityError("encrypted artifact header shape is invalid")
        if metadata["algorithm"] != "AES-256-GCM" or metadata["version"] != 1:
            raise BackupIntegrityError("encrypted artifact algorithm is unsupported")
        key_id = metadata["key_id"]
        chunk_size = metadata["chunk_size"]
        if (
            not isinstance(key_id, str)
            or type(chunk_size) is not int
            or chunk_size < 1024
            or chunk_size > 64 * 1024 * 1024
        ):
            raise BackupIntegrityError("encrypted artifact header values are invalid")
        try:
            nonce_prefix = base64.b64decode(metadata["nonce_prefix"], validate=True)
        except (TypeError, ValueError) as error:
            raise BackupIntegrityError("encrypted artifact nonce is invalid") from error
        if len(nonce_prefix) != 8:
            raise BackupIntegrityError("encrypted artifact nonce prefix is invalid")

        aes = AESGCM(keyring.key(key_id))
        counter = 0
        while True:
            length = _read_exact(stream, 4, label="frame")
            plaintext_size = struct.unpack(">I", length)[0]
            if plaintext_size == 0:
                if stream.read(1):
                    raise BackupIntegrityError("encrypted artifact has trailing data")
                return
            if plaintext_size > chunk_size:
                raise BackupIntegrityError("encrypted artifact frame is too large")
            counter_bytes = struct.pack(">I", counter)
            ciphertext = _read_exact(
                stream,
                plaintext_size + 16,
                label="frame",
            )
            try:
                yield aes.decrypt(
                    nonce_prefix + counter_bytes,
                    ciphertext,
                    _MAGIC + header + counter_bytes + length,
                )
            except InvalidTag as error:
                raise BackupIntegrityError(
                    "encrypted artifact authentication failed"
                ) from error
            counter += 1


def decrypt_file(source: Path, destination: Path, *, keyring: BackupKeyring) -> None:
    """Decrypt one artifact atomically and refuse destination overwrite."""

    destination = Path(os.path.abspath(os.fspath(destination)))
    if destination.exists():
        raise FileExistsError("refusing to overwrite a decrypted backup artifact")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            os.chmod(temporary, 0o600)
            for chunk in iter_decrypted_chunks(source, keyring=keyring):
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def verify_encrypted_file(
    source: Path,
    *,
    keyring: BackupKeyring,
    expected_sha256: str,
    expected_size: int,
) -> None:
    """Fully authenticate an artifact and verify its plaintext digest and size."""

    digest = hashlib.sha256()
    size = 0
    for chunk in iter_decrypted_chunks(source, keyring=keyring):
        digest.update(chunk)
        size += len(chunk)
    if digest.hexdigest() != expected_sha256 or size != expected_size:
        raise BackupIntegrityError("encrypted artifact plaintext verification failed")


def sha256_file(path: Path) -> tuple[str, int]:
    """Hash a regular file while detecting a concurrent size change."""

    path = Path(os.path.abspath(os.fspath(path)))
    if path.is_symlink() or not path.is_file():
        raise BackupIntegrityError("hash source must be a regular non-symlink file")
    before = path.stat()
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_DEFAULT_CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    after = path.stat()
    if before.st_size != after.st_size or size != after.st_size:
        raise BackupIntegrityError("file changed while it was being hashed")
    return digest.hexdigest(), size


def _storage_path(root: Path, storage_key: str) -> Path:
    if _STORAGE_KEY_PATTERN.fullmatch(storage_key) is None:
        raise BackupIntegrityError("database contains an invalid raw-file storage key")
    candidate = Path(os.path.abspath(os.fspath(root / Path(storage_key))))
    if not candidate.is_relative_to(root):
        raise BackupIntegrityError("raw-file storage key escaped the storage root")
    return candidate


def _mysql_option_value(value: str) -> str:
    if not value or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise BackupError("MySQL option value is empty or contains control characters")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _write_mysql_option_file(path: Path, url: URL) -> None:
    values = {
        "user": url.username or "",
        "password": url.password or "",
        "host": url.host or "",
        "port": str(url.port or 3306),
    }
    lines = ["[client]"]
    for name, value in values.items():
        lines.append(f'{name}="{_mysql_option_value(value)}"')
    lines.extend(("protocol=TCP", "default-character-set=utf8mb4"))
    ssl_ca = url.query.get("ssl_ca")
    if isinstance(ssl_ca, str) and ssl_ca:
        lines.extend((f'ssl-ca="{_mysql_option_value(ssl_ca)}"', "ssl-mode=VERIFY_CA"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _run_mysqldump(settings: BackupSettings, destination: Path) -> None:
    url = settings.database.url
    database_name = url.database
    assert database_name is not None
    with tempfile.TemporaryDirectory(prefix="clsen-mysqldump-") as temporary_name:
        temporary = Path(temporary_name)
        os.chmod(temporary, 0o700)
        option_file = temporary / "client.cnf"
        _write_mysql_option_file(option_file, url)
        arguments = [
            settings.mysqldump_executable,
            f"--defaults-extra-file={option_file}",
            "--single-transaction",
            "--quick",
            "--routines",
            "--triggers",
            "--events",
            "--hex-blob",
            "--default-character-set=utf8mb4",
            "--no-tablespaces",
            "--set-gtid-purged=OFF",
            "--skip-comments",
            database_name,
        ]
        try:
            with destination.open("xb") as output:
                os.chmod(destination, 0o600)
                completed = subprocess.run(
                    arguments,
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    text=False,
                    timeout=3600,
                )
        except (OSError, subprocess.TimeoutExpired) as error:
            destination.unlink(missing_ok=True)
            raise BackupError("mysqldump could not be executed safely") from error
        if completed.returncode != 0:
            destination.unlink(missing_ok=True)
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            if len(detail) > 1000:
                detail = detail[:1000] + "..."
            raise BackupError(f"mysqldump failed: {detail or 'no diagnostic output'}")


def _active_lease_count(connection: Connection) -> int:
    value = connection.scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM file_ingest_leases
            WHERE status IN ('active', 'committing')
            """
        )
    )
    return int(value or 0)


@contextmanager
def _hold_barrier_after_leases(
    engine: Engine,
    *,
    lock_timeout_seconds: int,
    lease_wait_timeout_seconds: int,
) -> Iterator[Connection]:
    deadline = time.monotonic() + lease_wait_timeout_seconds
    while True:
        with hold_maintenance_write_barrier(
            engine,
            timeout_seconds=lock_timeout_seconds,
        ) as connection:
            if _active_lease_count(connection) == 0:
                yield connection
                return
        if time.monotonic() >= deadline:
            raise BackupError("active file-ingest leases did not drain before backup")
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def _raw_objects(connection: Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        sa.text(
            """
            SELECT id, storage_key, HEX(sha256) AS sha256_hex, size_bytes
            FROM raw_files
            ORDER BY id
            """
        )
    ).mappings()
    return [
        {
            "raw_file_id": int(row["id"]),
            "storage_key": str(row["storage_key"]),
            "sha256": str(row["sha256_hex"]).lower(),
            "size_bytes": int(row["size_bytes"]),
        }
        for row in rows
    ]


def _database_counts(connection: Connection) -> dict[str, int]:
    row = (
        connection.execute(
            sa.text(
                """
            SELECT
                (SELECT COUNT(*) FROM raw_files) AS raw_file_count,
                (SELECT COUNT(*) FROM dataset_publications) AS publication_count,
                (SELECT COUNT(*) FROM dataset_versions) AS version_count,
                (SELECT COUNT(*) FROM audit_events) AS audit_event_count,
                (SELECT COUNT(*) FROM product_catalog_versions)
                    AS catalog_version_count,
                (SELECT COUNT(*) FROM product_catalog_mappings)
                    AS catalog_mapping_count,
                (SELECT COUNT(*) FROM return_dedup_snapshots)
                    AS return_dedup_snapshot_count,
                (SELECT COUNT(*) FROM fact_snapshot_tuples)
                    AS fact_snapshot_tuple_count
            """
            )
        )
        .mappings()
        .one()
    )
    return {name: int(row[name]) for name in row}


def _site_config_pointers(connection: Connection) -> list[dict[str, int]]:
    rows = connection.execute(
        sa.text(
            """
            SELECT site_id,
                   current_config_version_id AS site_config_version_id
            FROM site_current_configs
            ORDER BY site_id
            """
        )
    ).mappings()
    return [
        {
            "site_id": int(row["site_id"]),
            "site_config_version_id": int(row["site_config_version_id"]),
        }
        for row in rows
    ]


def _semantic_table_checksums(connection: Connection) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for table in _SEMANTIC_CHECKSUM_TABLES:
        row = connection.exec_driver_sql(f"CHECKSUM TABLE `{table}`").one()
        if len(row) != 2 or row[1] is None:
            raise BackupIntegrityError("database semantic checksum is unavailable")
        checksums[table] = str(int(row[1]))
    return checksums


def _manifest_payload(
    *,
    backup_uuid: UUID,
    snapshot_id: int,
    database_name: str,
    schema_revision: str,
    key_id: str,
    started_at: datetime,
    counts: Mapping[str, int],
    semantic_checksums: Mapping[str, str],
    objects: list[dict[str, object]],
    site_configs: list[dict[str, int]],
) -> dict[str, object]:
    return {
        "format": "clsen-local-backup-manifest-v1",
        "backup_uuid": backup_uuid.hex,
        "snapshot_id": snapshot_id,
        "database_name": database_name,
        "schema_revision": schema_revision,
        "key_id": key_id,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "counts": dict(counts),
        "semantic_table_checksums": dict(semantic_checksums),
        "site_current_configs": site_configs,
        "raw_objects": objects,
    }


def _mark_failed(engine: Engine, snapshot_id: int | None, failure_code: str) -> None:
    if snapshot_id is None:
        return
    code = re.sub(r"[^a-z0-9_]+", "_", failure_code.casefold()).strip("_")[:64]
    code = code or "backup_failed"
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE backup_snapshots
                    SET status = 'failed', completed_at = UTC_TIMESTAMP(6),
                        failure_code = :failure_code
                    WHERE id = :snapshot_id AND status IN ('running', 'sealed')
                    """
                ),
                {"snapshot_id": snapshot_id, "failure_code": code},
            )
    except Exception:
        # Preserve the original exception. A sealed/running record is itself durable
        # evidence that reconciliation is required.
        return


def prune_successful_backups(
    settings: BackupSettings,
    engine: Engine,
    *,
    current_backup_uuid: UUID,
) -> int:
    """Apply retention only after at least one successful restore exercise."""

    with engine.connect() as connection:
        verified_count = int(
            connection.scalar(
                sa.text(
                    """
                    SELECT COUNT(*)
                    FROM backup_snapshots
                    WHERE status = 'succeeded' AND restore_verified_at IS NOT NULL
                    """
                )
            )
            or 0
        )
        if verified_count == 0:
            return 0
        rows = connection.execute(
            sa.text(
                """
                SELECT LOWER(HEX(backup_uuid)) AS backup_uuid
                FROM backup_snapshots
                WHERE status = 'succeeded'
                ORDER BY started_at DESC, id DESC
                """
            )
        ).mappings()
        ordered_uuids = [str(row["backup_uuid"]) for row in rows]

    expired = ordered_uuids[settings.retention_count :]
    deleted = 0
    resolved_root = settings.destination_root.resolve()
    for backup_uuid in expired:
        if backup_uuid == current_backup_uuid.hex:
            continue
        if _BACKUP_DIRECTORY_PATTERN.fullmatch(backup_uuid) is None:
            raise BackupIntegrityError("database contains an invalid backup UUID")
        target = settings.destination_root / backup_uuid
        if not target.exists():
            continue
        resolved_target = target.resolve()
        if (
            resolved_target.parent != resolved_root
            or resolved_target.name != backup_uuid
        ):
            raise BackupIntegrityError("refusing to prune an unsafe backup path")
        load_backup_catalog(resolved_target)
        shutil.rmtree(resolved_target)
        deleted += 1
    return deleted


def create_backup(settings: BackupSettings) -> BackupResult:
    """Create, encrypt, verify, and register one consistent local backup."""

    keyring = load_keyring(settings.keyring_path)
    settings.destination_root.mkdir(parents=True, exist_ok=True)
    if settings.destination_root.is_symlink():
        raise BackupError("backup destination root must not be a symlink")
    if settings.storage_root.is_symlink() or not settings.storage_root.is_dir():
        raise BackupError(
            "source storage root must be an existing non-symlink directory"
        )

    backup_uuid = uuid4()
    started_at = datetime.now(UTC)
    staging = settings.destination_root / f".{backup_uuid.hex}.staging"
    completed_directory = settings.destination_root / backup_uuid.hex
    if staging.exists() or completed_directory.exists():
        raise BackupError("backup UUID output path unexpectedly already exists")
    staging.mkdir()
    os.chmod(staging, 0o700)
    plaintext_directory = staging / ".plaintext"
    plaintext_directory.mkdir()
    os.chmod(plaintext_directory, 0o700)

    engine = create_database_engine(settings.database)
    snapshot_id: int | None = None
    manifest_sha256 = ""
    artifacts: list[EncryptedArtifact] = []
    finalized = False
    try:
        with engine.begin() as connection:
            schema_revision = str(
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                or ""
            )
            if schema_revision != CURRENT_SCHEMA_REVISION:
                raise BackupError(
                    f"database must be migrated to revision {CURRENT_SCHEMA_REVISION}"
                )
            database_name = str(connection.scalar(sa.text("SELECT DATABASE()")) or "")
            if database_name != settings.database.url.database:
                raise BackupError("connected database does not match backup settings")
            result = connection.execute(
                sa.text(
                    """
                    INSERT INTO backup_snapshots (
                        backup_uuid, status, database_name, schema_revision,
                        key_id, started_at
                    ) VALUES (
                        :backup_uuid, 'running', :database_name, :schema_revision,
                        :key_id, :started_at
                    )
                    """
                ),
                {
                    "backup_uuid": backup_uuid.bytes,
                    "database_name": database_name,
                    "schema_revision": schema_revision,
                    "key_id": keyring.active_key_id,
                    "started_at": started_at.replace(tzinfo=None),
                },
            )
            snapshot_id = int(result.lastrowid)

        with _hold_barrier_after_leases(
            engine,
            lock_timeout_seconds=settings.lock_timeout_seconds,
            lease_wait_timeout_seconds=settings.lease_wait_timeout_seconds,
        ) as connection:
            barrier_schema_revision = str(
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                or ""
            )
            barrier_database_name = str(
                connection.scalar(sa.text("SELECT DATABASE()")) or ""
            )
            if (
                barrier_schema_revision != schema_revision
                or barrier_database_name != database_name
            ):
                raise BackupError("database identity changed before backup sealing")
            objects = _raw_objects(connection)
            counts = _database_counts(connection)
            semantic_checksums = _semantic_table_checksums(connection)
            site_configs = _site_config_pointers(connection)
            if objects:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO backup_snapshot_objects (
                            backup_snapshot_id, raw_file_id, storage_key,
                            sha256, size_bytes
                        ) VALUES (
                            :backup_snapshot_id, :raw_file_id, :storage_key,
                            UNHEX(:sha256), :size_bytes
                        )
                        """
                    ),
                    [{"backup_snapshot_id": snapshot_id, **item} for item in objects],
                )
            manifest = _manifest_payload(
                backup_uuid=backup_uuid,
                snapshot_id=snapshot_id,
                database_name=database_name,
                schema_revision=schema_revision,
                key_id=keyring.active_key_id,
                started_at=started_at,
                counts=counts,
                semantic_checksums=semantic_checksums,
                objects=objects,
                site_configs=site_configs,
            )
            manifest_bytes = _canonical_json(manifest) + b"\n"
            manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
            manifest_path = plaintext_directory / "manifest.json"
            manifest_path.write_bytes(manifest_bytes)
            os.chmod(manifest_path, 0o600)
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE backup_snapshots
                    SET status = 'sealed',
                        raw_file_count = :raw_file_count,
                        publication_count = :publication_count,
                        version_count = :version_count,
                        audit_event_count = :audit_event_count,
                        sealed_at = UTC_TIMESTAMP(6),
                        manifest_sha256 = UNHEX(:manifest_sha256)
                    WHERE id = :snapshot_id AND status = 'running'
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "manifest_sha256": manifest_sha256,
                    **counts,
                },
            )
            if updated.rowcount != 1:
                raise BackupError("running backup snapshot could not be sealed")
            _run_mysqldump(settings, plaintext_directory / "database.sql")

        manifest_artifact = encrypt_file(
            plaintext_directory / "manifest.json",
            staging / "manifest.json.enc",
            keyring=keyring,
            artifact_type="manifest",
        )
        artifacts.append(manifest_artifact)
        dump_artifact = encrypt_file(
            plaintext_directory / "database.sql",
            staging / "database.sql.enc",
            keyring=keyring,
            artifact_type="mysql_dump",
        )
        artifacts.append(dump_artifact)

        object_root = staging / "objects"
        for item in objects:
            storage_key = str(item["storage_key"])
            source = _storage_path(settings.storage_root, storage_key)
            expected_hash = str(item["sha256"])
            expected_size_value = item["size_bytes"]
            if type(expected_size_value) is not int:
                raise BackupIntegrityError("raw object size is not an integer")
            expected_size = expected_size_value
            actual_hash, actual_size = sha256_file(source)
            if actual_hash != expected_hash or actual_size != expected_size:
                raise BackupIntegrityError(
                    f"raw object {storage_key!r} differs from its database identity"
                )
            destination = object_root / f"{expected_hash}.enc"
            artifact = encrypt_file(
                source,
                destination,
                keyring=keyring,
                artifact_type="raw_object",
            )
            artifacts.append(
                EncryptedArtifact(
                    relative_path=destination.relative_to(staging).as_posix(),
                    artifact_type=artifact.artifact_type,
                    plaintext_sha256=artifact.plaintext_sha256,
                    plaintext_size=artifact.plaintext_size,
                    ciphertext_sha256=artifact.ciphertext_sha256,
                    ciphertext_size=artifact.ciphertext_size,
                )
            )

        for artifact in artifacts:
            verify_encrypted_file(
                staging / artifact.relative_path,
                keyring=keyring,
                expected_sha256=artifact.plaintext_sha256,
                expected_size=artifact.plaintext_size,
            )
        if manifest_artifact.plaintext_sha256 != manifest_sha256:
            raise BackupIntegrityError("sealed manifest hash changed before encryption")

        shutil.rmtree(plaintext_directory)
        catalog = {
            "format": "clsen-local-backup-catalog-v1",
            "backup_uuid": backup_uuid.hex,
            "snapshot_id": snapshot_id,
            "key_id": keyring.active_key_id,
            "manifest_sha256": manifest_sha256,
            "status": "verified",
            "artifacts": [
                {
                    "relative_path": item.relative_path,
                    "artifact_type": item.artifact_type,
                    "plaintext_sha256": item.plaintext_sha256,
                    "plaintext_size": item.plaintext_size,
                    "ciphertext_sha256": item.ciphertext_sha256,
                    "ciphertext_size": item.ciphertext_size,
                }
                for item in artifacts
            ],
        }
        catalog_path = staging / "backup.json"
        catalog_path.write_bytes(_canonical_json(catalog) + b"\n")
        os.chmod(catalog_path, 0o600)
        os.replace(staging, completed_directory)

        with engine.begin() as connection:
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE backup_snapshots
                    SET status = 'succeeded', completed_at = UTC_TIMESTAMP(6)
                    WHERE id = :snapshot_id AND status = 'sealed'
                    """
                ),
                {"snapshot_id": snapshot_id},
            )
            if updated.rowcount != 1:
                raise BackupError("sealed backup snapshot could not be finalized")
        finalized = True
        pruned_count = prune_successful_backups(
            settings,
            engine,
            current_backup_uuid=backup_uuid,
        )
        return BackupResult(
            backup_uuid=backup_uuid,
            snapshot_id=snapshot_id,
            directory=completed_directory,
            key_id=keyring.active_key_id,
            manifest_sha256=manifest_sha256,
            artifact_count=len(artifacts),
            pruned_count=pruned_count,
        )
    except BaseException as error:
        if not finalized:
            _mark_failed(engine, snapshot_id, type(error).__name__)
        raise
    finally:
        engine.dispose()
        if staging.exists():
            resolved_staging = staging.resolve()
            resolved_root = settings.destination_root.resolve()
            if (
                resolved_staging.parent == resolved_root
                and resolved_staging.name == f".{backup_uuid.hex}.staging"
            ):
                shutil.rmtree(resolved_staging, ignore_errors=True)


def load_backup_catalog(backup_directory: Path) -> dict[str, Any]:
    """Load and strictly validate the public integrity catalogue."""

    directory = Path(os.path.abspath(os.fspath(backup_directory)))
    if directory.is_symlink() or not directory.is_dir():
        raise BackupIntegrityError("backup directory must be a regular directory")
    if _BACKUP_DIRECTORY_PATTERN.fullmatch(directory.name) is None:
        raise BackupIntegrityError("backup directory name must be a backup UUID")
    try:
        payload = json.loads(
            (directory / "backup.json").read_text(encoding="utf-8"),
            object_pairs_hook=_json_without_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise BackupIntegrityError(
            "backup catalogue is unreadable or invalid"
        ) from error
    if not isinstance(payload, dict) or payload.get("format") != (
        "clsen-local-backup-catalog-v1"
    ):
        raise BackupIntegrityError("backup catalogue format is unsupported")
    if payload.get("backup_uuid") != directory.name:
        raise BackupIntegrityError("backup catalogue UUID does not match its directory")
    if payload.get("status") != "verified" or not isinstance(
        payload.get("artifacts"), list
    ):
        raise BackupIntegrityError("backup catalogue is not a verified backup")
    return payload
