"""Isolated restore verification for encrypted local backups."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.maintenance.backup import (
    BackupIntegrityError,
    BackupKeyring,
    decrypt_file,
    load_backup_catalog,
    load_keyring,
    sha256_file,
    verify_encrypted_file,
)
from app.maintenance.schema_revision import BACKUP_READER_SCHEMA_REVISIONS

_RESTORE_DATABASE_PATTERN = re.compile(r"clsen_restore_[0-9a-f]{32}\Z")
_STORAGE_KEY_PATTERN = re.compile(r"sha256/[0-9a-f]{2}/[0-9a-f]{64}\Z")


class RestoreError(RuntimeError):
    """An isolated restore could not complete safely."""


@dataclass(frozen=True, slots=True)
class RestoreSettings:
    """Explicit paths and credentials for one random isolated restore."""

    backup_directory: Path
    temporary_root: Path
    keyring_path: Path
    source_database: DatabaseSettings
    administrator_option_file: Path
    mysql_executable: str = "mysql.exe"
    cleanup_after_success: bool = False
    forbidden_roots: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        path_fields = (
            "backup_directory",
            "temporary_root",
            "keyring_path",
            "administrator_option_file",
        )
        for name in path_fields:
            path = Path(os.path.abspath(os.fspath(getattr(self, name))))
            if path == Path(path.anchor):
                raise ValueError(f"{name} must not be a filesystem root")
            object.__setattr__(self, name, path)
        forbidden = tuple(
            Path(os.path.abspath(os.fspath(path))) for path in self.forbidden_roots
        )
        if any(self.temporary_root == path for path in forbidden):
            raise ValueError("temporary restore root is a forbidden production root")
        if not self.mysql_executable.strip():
            raise ValueError("mysql executable must not be blank")


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """Verified restore identity and retained or cleaned local targets."""

    verification_uuid: UUID
    database_name: str
    target_directory: Path
    backup_uuid: UUID
    retained: bool


def _load_json_bytes(value: bytes, *, label: str) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = item
        return result

    try:
        payload = json.loads(
            value.decode("utf-8"),
            object_pairs_hook=no_duplicates,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise BackupIntegrityError(f"{label} is not strict UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise BackupIntegrityError(f"{label} must be a JSON object")
    return payload


def _safe_artifact_path(backup_directory: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise BackupIntegrityError("backup artifact path must be a non-empty string")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts or "" in relative.parts:
        raise BackupIntegrityError("backup artifact path is unsafe")
    resolved = Path(os.path.abspath(os.fspath(backup_directory / relative)))
    if not resolved.is_relative_to(backup_directory):
        raise BackupIntegrityError("backup artifact escaped its backup directory")
    return resolved


def _verified_artifacts(
    backup_directory: Path,
    catalog: dict[str, Any],
    keyring: BackupKeyring,
) -> dict[str, dict[str, Any]]:
    artifacts_value = catalog.get("artifacts")
    if not isinstance(artifacts_value, list) or not artifacts_value:
        raise BackupIntegrityError("backup catalogue has no artifacts")
    artifacts: dict[str, dict[str, Any]] = {}
    for value in artifacts_value:
        if not isinstance(value, dict) or set(value) != {
            "relative_path",
            "artifact_type",
            "plaintext_sha256",
            "plaintext_size",
            "ciphertext_sha256",
            "ciphertext_size",
        }:
            raise BackupIntegrityError("backup catalogue contains an invalid artifact")
        relative_path = value["relative_path"]
        if not isinstance(relative_path, str) or relative_path in artifacts:
            raise BackupIntegrityError("backup catalogue has a duplicate artifact path")
        path = _safe_artifact_path(backup_directory, relative_path)
        expected_ciphertext_hash = value["ciphertext_sha256"]
        expected_ciphertext_size = value["ciphertext_size"]
        expected_plaintext_hash = value["plaintext_sha256"]
        expected_plaintext_size = value["plaintext_size"]
        if (
            not isinstance(expected_ciphertext_hash, str)
            or not isinstance(expected_plaintext_hash, str)
            or type(expected_ciphertext_size) is not int
            or type(expected_plaintext_size) is not int
        ):
            raise BackupIntegrityError("backup catalogue artifact metadata is invalid")
        actual_ciphertext_hash, actual_ciphertext_size = sha256_file(path)
        if (
            actual_ciphertext_hash != expected_ciphertext_hash
            or actual_ciphertext_size != expected_ciphertext_size
        ):
            raise BackupIntegrityError("encrypted artifact differs from its catalogue")
        verify_encrypted_file(
            path,
            keyring=keyring,
            expected_sha256=expected_plaintext_hash,
            expected_size=expected_plaintext_size,
        )
        artifacts[relative_path] = value
    return artifacts


def _artifact_of_type(
    artifacts: dict[str, dict[str, Any]],
    artifact_type: str,
) -> tuple[str, dict[str, Any]]:
    matches = [
        (relative, value)
        for relative, value in artifacts.items()
        if value["artifact_type"] == artifact_type
    ]
    if len(matches) != 1:
        raise BackupIntegrityError(
            f"backup must contain exactly one {artifact_type!r} artifact"
        )
    return matches[0]


def _run_mysql(
    settings: RestoreSettings,
    *,
    operation: str,
    sql: str | None = None,
    database_name: str | None = None,
    input_path: Path | None = None,
) -> str:
    arguments = [
        settings.mysql_executable,
        f"--defaults-extra-file={settings.administrator_option_file}",
        "--protocol=TCP",
        "--batch",
        "--raw",
        "--skip-column-names",
    ]
    if sql is not None:
        arguments.append(f"--execute={sql}")
    if database_name is not None:
        if _RESTORE_DATABASE_PATTERN.fullmatch(database_name) is None:
            raise RestoreError("refusing an unsafe restore database name")
        arguments.append(database_name)
    input_stream = None
    try:
        if input_path is not None:
            input_stream = input_path.open("rb")
        completed = subprocess.run(
            arguments,
            check=False,
            stdin=input_stream or subprocess.DEVNULL,
            capture_output=True,
            timeout=3600,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RestoreError(f"mysql failed during {operation}") from error
    finally:
        if input_stream is not None:
            input_stream.close()
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        if len(detail) > 1000:
            detail = detail[:1000] + "..."
        raise RestoreError(f"mysql failed during {operation}: {detail}")
    return completed.stdout.decode("utf-8", errors="strict").strip()


def _manifest_objects(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    values = manifest.get("raw_objects")
    if not isinstance(values, list):
        raise BackupIntegrityError("backup manifest raw_objects must be an array")
    result: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for value in values:
        if not isinstance(value, dict) or set(value) != {
            "raw_file_id",
            "storage_key",
            "sha256",
            "size_bytes",
        }:
            raise BackupIntegrityError("backup manifest has an invalid raw object")
        storage_key = value["storage_key"]
        digest = value["sha256"]
        size = value["size_bytes"]
        if (
            not isinstance(storage_key, str)
            or _STORAGE_KEY_PATTERN.fullmatch(storage_key) is None
            or not isinstance(digest, str)
            or len(digest) != 64
            or storage_key.rsplit("/", 1)[-1] != digest
            or type(size) is not int
            or size < 0
            or storage_key in seen_keys
        ):
            raise BackupIntegrityError("backup manifest raw object identity is invalid")
        seen_keys.add(storage_key)
        result.append(value)
    return result


def _restore_objects(
    *,
    backup_directory: Path,
    target_storage_root: Path,
    objects: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    keyring: BackupKeyring,
) -> None:
    object_artifacts: dict[str, tuple[str, dict[str, Any]]] = {}
    for relative, artifact in artifacts.items():
        if artifact["artifact_type"] != "raw_object":
            continue
        digest = artifact["plaintext_sha256"]
        if not isinstance(digest, str) or digest in object_artifacts:
            raise BackupIntegrityError("backup has duplicate raw-object content")
        object_artifacts[digest] = (relative, artifact)
    expected_digests = {str(item["sha256"]) for item in objects}
    if set(object_artifacts) != expected_digests:
        raise BackupIntegrityError("backup raw-object artifacts do not match manifest")
    for item in objects:
        digest = str(item["sha256"])
        relative, _artifact = object_artifacts[digest]
        destination = target_storage_root / str(item["storage_key"])
        resolved = Path(os.path.abspath(os.fspath(destination)))
        if not resolved.is_relative_to(target_storage_root):
            raise BackupIntegrityError("restored object escaped its target root")
        decrypt_file(
            _safe_artifact_path(backup_directory, relative),
            resolved,
            keyring=keyring,
        )
        actual_hash, actual_size = sha256_file(resolved)
        if actual_hash != digest or actual_size != item["size_bytes"]:
            raise BackupIntegrityError(
                "restored raw object failed identity verification"
            )


def _verify_database(
    settings: RestoreSettings,
    database_name: str,
    manifest: dict[str, Any],
) -> None:
    output = _run_mysql(
        settings,
        operation="verify restored database counts",
        database_name=database_name,
        sql=(
            "SELECT version_num,"
            "(SELECT COUNT(*) FROM raw_files),"
            "(SELECT COUNT(*) FROM dataset_publications),"
            "(SELECT COUNT(*) FROM dataset_versions),"
            "(SELECT COUNT(*) FROM audit_events),"
            "(SELECT COUNT(*) FROM product_catalog_versions),"
            "(SELECT COUNT(*) FROM product_catalog_mappings),"
            "(SELECT COUNT(*) FROM return_dedup_snapshots),"
            "(SELECT COUNT(*) FROM fact_snapshot_tuples) "
            "FROM alembic_version;"
        ),
    )
    fields = output.split("\t")
    if len(fields) != 9:
        raise RestoreError("restored database verification returned an invalid row")
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise BackupIntegrityError("backup manifest counts are invalid")
    expected = [
        str(manifest.get("schema_revision")),
        str(counts.get("raw_file_count")),
        str(counts.get("publication_count")),
        str(counts.get("version_count")),
        str(counts.get("audit_event_count")),
        str(counts.get("catalog_version_count")),
        str(counts.get("catalog_mapping_count")),
        str(counts.get("return_dedup_snapshot_count")),
        str(counts.get("fact_snapshot_tuple_count")),
    ]
    if fields != expected:
        raise RestoreError("restored database revision or counts differ from manifest")

    expected_sites = manifest.get("site_current_configs")
    if not isinstance(expected_sites, list):
        raise BackupIntegrityError("backup manifest site pointers are invalid")
    site_output = _run_mysql(
        settings,
        operation="verify restored site pointers",
        database_name=database_name,
        sql=(
            "SELECT site_id, current_config_version_id "
            "FROM site_current_configs ORDER BY site_id;"
        ),
    )
    actual_sites = (
        []
        if not site_output
        else [
            {
                "site_id": int(line.split("\t")[0]),
                "site_config_version_id": int(line.split("\t")[1]),
            }
            for line in site_output.splitlines()
        ]
    )
    if actual_sites != expected_sites:
        raise RestoreError("restored site configuration pointers differ from manifest")

    expected_checksums = manifest.get("semantic_table_checksums")
    if expected_checksums is None and manifest.get("schema_revision") in {
        "0020",
        "0021",
    }:
        return
    if not isinstance(expected_checksums, dict) or not expected_checksums:
        raise BackupIntegrityError("backup manifest semantic checksums are invalid")
    for table, expected_checksum in sorted(expected_checksums.items()):
        if (
            not isinstance(table, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", table) is None
            or not isinstance(expected_checksum, str)
            or not expected_checksum.isdecimal()
        ):
            raise BackupIntegrityError("backup manifest semantic checksum is invalid")
        checksum_output = _run_mysql(
            settings,
            operation="verify restored semantic checksum",
            database_name=database_name,
            sql=f"CHECKSUM TABLE `{table}`;",
        )
        checksum_fields = checksum_output.split("\t")
        if len(checksum_fields) != 2 or checksum_fields[1] != expected_checksum:
            raise RestoreError("restored database semantic checksum differs")


def _begin_verification(
    settings: RestoreSettings,
    *,
    verification_uuid: UUID,
    backup_uuid: UUID,
    database_name: str,
    target_directory: Path,
) -> tuple[Engine, int, int]:
    engine = create_database_engine(settings.source_database)
    try:
        with engine.begin() as connection:
            snapshot = connection.execute(
                sa.text(
                    """
                    SELECT id, status
                    FROM backup_snapshots
                    WHERE backup_uuid = :backup_uuid
                    """
                ),
                {"backup_uuid": backup_uuid.bytes},
            ).one_or_none()
            if snapshot is None or str(snapshot.status) != "succeeded":
                raise RestoreError(
                    "source backup snapshot is missing or not successful"
                )
            snapshot_id = int(snapshot.id)
            result = connection.execute(
                sa.text(
                    """
                    INSERT INTO restore_verifications (
                        verification_uuid, backup_snapshot_id,
                        target_database_name, target_storage_root_sha256,
                        status, started_at
                    ) VALUES (
                        :verification_uuid, :snapshot_id, :database_name,
                        :target_root_sha256, 'running', :started_at
                    )
                    """
                ),
                {
                    "verification_uuid": verification_uuid.bytes,
                    "snapshot_id": snapshot_id,
                    "database_name": database_name,
                    "target_root_sha256": hashlib.sha256(
                        os.fspath(target_directory).encode("utf-8")
                    ).digest(),
                    "started_at": datetime.now(UTC).replace(tzinfo=None),
                },
            )
            verification_id = int(result.lastrowid)
        return engine, snapshot_id, verification_id
    except BaseException:
        engine.dispose()
        raise


def _finish_verification(
    engine: Engine,
    *,
    snapshot_id: int,
    verification_id: int,
    succeeded: bool,
    failure_code: str | None = None,
) -> None:
    status = "succeeded" if succeeded else "failed"
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                UPDATE restore_verifications
                SET status = :status, completed_at = UTC_TIMESTAMP(6),
                    failure_code = :failure_code
                WHERE id = :verification_id AND status = 'running'
                """
            ),
            {
                "status": status,
                "failure_code": failure_code,
                "verification_id": verification_id,
            },
        )
        if succeeded:
            connection.execute(
                sa.text(
                    """
                    UPDATE backup_snapshots
                    SET restore_verified_at = UTC_TIMESTAMP(6)
                    WHERE id = :snapshot_id AND status = 'succeeded'
                    """
                ),
                {"snapshot_id": snapshot_id},
            )


def _safe_cleanup_directory(settings: RestoreSettings, target_directory: Path) -> None:
    resolved_root = settings.temporary_root.resolve()
    resolved_target = target_directory.resolve()
    if (
        resolved_target.parent != resolved_root
        or _RESTORE_DATABASE_PATTERN.fullmatch(resolved_target.name) is None
    ):
        raise RestoreError("refusing to clean an unsafe restore directory")
    shutil.rmtree(resolved_target)


def verify_restore(settings: RestoreSettings) -> RestoreResult:
    """Restore one backup to random isolated targets and verify every identity."""

    if (
        settings.administrator_option_file.is_symlink()
        or not settings.administrator_option_file.is_file()
    ):
        raise RestoreError("administrator option file must be a regular file")
    if settings.temporary_root.is_symlink():
        raise RestoreError("temporary restore root must not be a symlink")
    settings.temporary_root.mkdir(parents=True, exist_ok=True)
    keyring = load_keyring(settings.keyring_path)
    catalog = load_backup_catalog(settings.backup_directory)
    artifacts = _verified_artifacts(settings.backup_directory, catalog, keyring)

    backup_uuid = UUID(hex=str(catalog["backup_uuid"]))
    verification_uuid = uuid4()
    database_name = f"clsen_restore_{verification_uuid.hex}"
    target_directory = settings.temporary_root / database_name
    if target_directory.exists():
        raise RestoreError("random restore target unexpectedly already exists")
    target_directory.mkdir()
    os.chmod(target_directory, 0o700)
    target_storage_root = target_directory / "files"
    target_storage_root.mkdir()

    manifest_relative, manifest_artifact = _artifact_of_type(artifacts, "manifest")
    manifest_path = target_directory / "manifest.json"
    decrypt_file(
        _safe_artifact_path(settings.backup_directory, manifest_relative),
        manifest_path,
        keyring=keyring,
    )
    manifest_bytes = manifest_path.read_bytes()
    manifest = _load_json_bytes(manifest_bytes, label="backup manifest")
    schema_revision = manifest.get("schema_revision")
    if (
        manifest.get("format") != "clsen-local-backup-manifest-v1"
        or manifest.get("backup_uuid") != backup_uuid.hex
        or manifest.get("key_id") != catalog.get("key_id")
        or not isinstance(schema_revision, str)
        or schema_revision not in BACKUP_READER_SCHEMA_REVISIONS
        or manifest_artifact.get("plaintext_sha256") != catalog.get("manifest_sha256")
        or hashlib.sha256(manifest_bytes).hexdigest() != catalog.get("manifest_sha256")
    ):
        raise BackupIntegrityError("backup manifest identity is inconsistent")

    dump_relative, _dump_artifact = _artifact_of_type(artifacts, "mysql_dump")
    dump_path = target_directory / "database.sql"
    decrypt_file(
        _safe_artifact_path(settings.backup_directory, dump_relative),
        dump_path,
        keyring=keyring,
    )
    objects = _manifest_objects(manifest)
    _restore_objects(
        backup_directory=settings.backup_directory,
        target_storage_root=target_storage_root,
        objects=objects,
        artifacts=artifacts,
        keyring=keyring,
    )

    source_engine, snapshot_id, verification_id = _begin_verification(
        settings,
        verification_uuid=verification_uuid,
        backup_uuid=backup_uuid,
        database_name=database_name,
        target_directory=target_directory,
    )
    created_database = False
    try:
        _run_mysql(
            settings,
            operation="create isolated restore database",
            sql=(
                f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_0900_ai_ci;"
            ),
        )
        created_database = True
        _run_mysql(
            settings,
            operation="import isolated restore database",
            database_name=database_name,
            input_path=dump_path,
        )
        _verify_database(settings, database_name, manifest)
        _finish_verification(
            source_engine,
            snapshot_id=snapshot_id,
            verification_id=verification_id,
            succeeded=True,
        )
    except BaseException as error:
        code = re.sub(r"[^a-z0-9_]+", "_", type(error).__name__.casefold())[:64]
        with suppress(Exception):
            _finish_verification(
                source_engine,
                snapshot_id=snapshot_id,
                verification_id=verification_id,
                succeeded=False,
                failure_code=code or "restore_failed",
            )
        raise
    finally:
        source_engine.dispose()

    retained = True
    if settings.cleanup_after_success:
        if not created_database:
            raise RestoreError("restore database was not created; refusing cleanup")
        _run_mysql(
            settings,
            operation="drop verified isolated restore database",
            sql=f"DROP DATABASE `{database_name}`;",
        )
        _safe_cleanup_directory(settings, target_directory)
        retained = False
    return RestoreResult(
        verification_uuid=verification_uuid,
        database_name=database_name,
        target_directory=target_directory,
        backup_uuid=backup_uuid,
        retained=retained,
    )
