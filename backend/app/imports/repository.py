"""MySQL repository and connection-scoped locks for file ingestion."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.imports.storage import StagedContent, StoredContent
from app.imports.types import (
    CommitOutcomeUnknown,
    FinalizedImport,
    ImportCommand,
    IngestCommitFailed,
    InvalidLeaseTransition,
    LeaseExpired,
    RecoveredImport,
)

_LOGGER = logging.getLogger(__name__)
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_STORAGE_KEY_PATTERN = re.compile(
    r"sha256/(?P<prefix>[0-9a-f]{2})/(?P<digest>[0-9a-f]{64})\Z",
    re.ASCII,
)
_LOCK_NAME_SQL = "SHA2(CONCAT(DATABASE(), '-raw-object-', :digest), 256)"


def _mysql_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("database timestamps must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _digest_bytes(sha256_hex: str) -> bytes:
    if _DIGEST_PATTERN.fullmatch(sha256_hex) is None:
        raise ValueError("sha256 digest must be 64 lowercase hexadecimal characters")
    return bytes.fromhex(sha256_hex)


def _validate_storage_identity(
    *,
    storage_key: str,
    sha256_hex: str,
    size_bytes: int,
) -> bytes:
    if size_bytes < 0:
        raise ValueError("size_bytes must not be negative")
    digest = _digest_bytes(sha256_hex)
    match = _STORAGE_KEY_PATTERN.fullmatch(storage_key)
    if (
        match is None
        or match.group("digest") != sha256_hex
        or match.group("prefix") != sha256_hex[:2]
    ):
        raise ValueError("storage_key does not match the SHA-256 digest")
    return digest


def _invalidate_uncertain_lock_connection(
    connection: Connection,
    *,
    sha256_hex: str,
) -> None:
    """Keep a connection-scoped lock from returning to the pool."""

    try:
        connection.invalidate()
    except BaseException:
        _LOGGER.exception(
            "Could not invalidate a connection with uncertain digest-lock state",
            extra={"sha256": sha256_hex},
        )


class MySqlIngestRepository:
    """Persist the ingest state machine using short explicit transactions."""

    def __init__(self, engine: Engine, *, lock_timeout_seconds: int = 30) -> None:
        if lock_timeout_seconds < 0:
            raise ValueError("lock_timeout_seconds must not be negative")
        self._engine = engine
        self._lock_timeout_seconds = lock_timeout_seconds

    def create_lease(
        self,
        *,
        lease_token: UUID,
        temporary_path: str,
        created_by_user_id: int,
        expires_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO file_ingest_leases (
                        lease_token, temporary_path, created_by_user_id,
                        status, expires_at
                    ) VALUES (
                        :lease_token, :temporary_path, :created_by_user_id,
                        'active', :expires_at
                    )
                    """
                ),
                {
                    "lease_token": lease_token.bytes,
                    "temporary_path": temporary_path,
                    "created_by_user_id": created_by_user_id,
                    "expires_at": _mysql_datetime(expires_at),
                },
            )

    def renew_active_lease(
        self,
        *,
        lease_token: UUID,
        expires_at: datetime,
        checked_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.text(
                    """
                    UPDATE file_ingest_leases
                    SET expires_at = :expires_at
                    WHERE lease_token = :lease_token
                      AND status = 'active'
                      AND expires_at > :checked_at
                    """
                ),
                {
                    "lease_token": lease_token.bytes,
                    "expires_at": _mysql_datetime(expires_at),
                    "checked_at": _mysql_datetime(checked_at),
                },
            )
        if result.rowcount != 1:
            raise LeaseExpired("the active file ingest lease could not be renewed")

    @contextmanager
    def digest_lock(self, sha256_hex: str) -> Iterator[Connection]:
        """Serialize finalization and reconciliation for one content digest."""

        _digest_bytes(sha256_hex)
        with self._engine.connect() as connection:
            try:
                acquired = connection.scalar(
                    sa.text(f"SELECT GET_LOCK({_LOCK_NAME_SQL}, :timeout_seconds)"),
                    {
                        "digest": sha256_hex,
                        "timeout_seconds": self._lock_timeout_seconds,
                    },
                )
                connection.commit()
            except BaseException:
                _invalidate_uncertain_lock_connection(
                    connection,
                    sha256_hex=sha256_hex,
                )
                raise
            if acquired != 1:
                raise TimeoutError("could not acquire the content digest lock")
            try:
                yield connection
            finally:
                try:
                    if connection.in_transaction():
                        connection.rollback()
                    if not connection.invalidated:
                        released = connection.scalar(
                            sa.text(f"SELECT RELEASE_LOCK({_LOCK_NAME_SQL})"),
                            {"digest": sha256_hex},
                        )
                        connection.commit()
                        if released != 1:
                            raise RuntimeError(
                                "could not release the content digest lock"
                            )
                except BaseException as error:
                    _invalidate_uncertain_lock_connection(
                        connection,
                        sha256_hex=sha256_hex,
                    )
                    if isinstance(error, Exception):
                        _LOGGER.exception(
                            "Content digest lock release was uncertain; the physical "
                            "connection was invalidated",
                            extra={"sha256": sha256_hex},
                        )
                    else:
                        raise

    def mark_committing(
        self,
        connection: Connection,
        *,
        lease_token: UUID,
        staged: StagedContent,
        expires_at: datetime,
        checked_at: datetime,
    ) -> None:
        storage_key = f"sha256/{staged.sha256_hex[:2]}/{staged.sha256_hex}"
        digest = _validate_storage_identity(
            storage_key=storage_key,
            sha256_hex=staged.sha256_hex,
            size_bytes=staged.size_bytes,
        )
        with connection.begin():
            result = connection.execute(
                sa.text(
                    """
                    UPDATE file_ingest_leases
                    SET status = 'committing',
                        storage_key = :storage_key,
                        sha256 = :sha256,
                        size_bytes = :size_bytes,
                        expires_at = :expires_at
                    WHERE lease_token = :lease_token
                      AND status = 'active'
                      AND expires_at > :checked_at
                    """
                ),
                {
                    "lease_token": lease_token.bytes,
                    "storage_key": storage_key,
                    "sha256": digest,
                    "size_bytes": staged.size_bytes,
                    "expires_at": _mysql_datetime(expires_at),
                    "checked_at": _mysql_datetime(checked_at),
                },
            )
        if result.rowcount != 1:
            raise InvalidLeaseTransition(
                "the active lease could not transition to committing"
            )

    def finalize_import(
        self,
        connection: Connection,
        *,
        lease_token: UUID,
        command: ImportCommand,
        stored: StoredContent,
        completed_at: datetime,
    ) -> FinalizedImport:
        digest = _validate_storage_identity(
            storage_key=stored.storage_key,
            sha256_hex=stored.sha256_hex,
            size_bytes=stored.size_bytes,
        )
        checked_at = _mysql_datetime(completed_at)
        try:
            with connection.begin():
                raw_file_id = self._find_or_create_raw_file(
                    connection,
                    digest=digest,
                    command=command,
                    stored=stored,
                    uploaded_at=checked_at,
                )
                batch_id, created = self._find_or_create_batch(
                    connection,
                    raw_file_id=raw_file_id,
                    command=command,
                    created_at=checked_at,
                )
                self._mark_integrity_available(
                    connection,
                    raw_file_id=raw_file_id,
                    checked_at=checked_at,
                )
                lease_result = connection.execute(
                    sa.text(
                        """
                        UPDATE file_ingest_leases
                        SET status = 'completed',
                            raw_file_id = :raw_file_id,
                            completed_at = :completed_at
                        WHERE lease_token = :lease_token
                          AND status = 'committing'
                          AND sha256 = :sha256
                          AND storage_key = :storage_key
                          AND size_bytes = :size_bytes
                        """
                    ),
                    {
                        "lease_token": lease_token.bytes,
                        "raw_file_id": raw_file_id,
                        "completed_at": checked_at,
                        "sha256": digest,
                        "storage_key": stored.storage_key,
                        "size_bytes": stored.size_bytes,
                    },
                )
                if lease_result.rowcount != 1:
                    raise InvalidLeaseTransition(
                        "the committing lease could not be completed"
                    )
        except DBAPIError as error:
            if error.connection_invalidated:
                raise CommitOutcomeUnknown(
                    "the final commit acknowledgement was lost"
                ) from error
            raise IngestCommitFailed("the final ingest transaction failed") from error
        except InvalidLeaseTransition:
            raise
        except SQLAlchemyError as error:
            raise IngestCommitFailed("the final ingest transaction failed") from error

        return FinalizedImport(
            raw_file_id=raw_file_id,
            batch_id=batch_id,
            created=created,
        )

    def recover_completed(self, lease_token: UUID) -> RecoveredImport | None:
        with self._engine.connect() as connection:
            lease = (
                connection.execute(
                    sa.text(
                        """
                    SELECT status, sha256
                    FROM file_ingest_leases
                    WHERE lease_token = :lease_token
                    LIMIT 1
                    """
                    ),
                    {"lease_token": lease_token.bytes},
                )
                .mappings()
                .first()
            )
            if lease is None:
                return None
            if lease["status"] == "completed":
                return self._completed_import(connection, lease_token)
            digest_value = lease["sha256"]
        if not isinstance(digest_value, (bytes, bytearray, memoryview)):
            return None
        digest = bytes(digest_value)
        if len(digest) != 32:
            raise RuntimeError("file ingest lease has an invalid SHA-256 value")
        with self.digest_lock(digest.hex()) as connection:
            return self._completed_import(connection, lease_token)

    def mark_failed(self, *, lease_token: UUID, failed_at: datetime) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE file_ingest_leases
                    SET status = 'failed', completed_at = :failed_at
                    WHERE lease_token = :lease_token
                      AND status IN ('active', 'committing')
                    """
                ),
                {
                    "lease_token": lease_token.bytes,
                    "failed_at": _mysql_datetime(failed_at),
                },
            )

    def expire_stale_leases(self, *, checked_at: datetime) -> int:
        """Record terminal expiry without treating expired leases as protection."""

        timestamp = _mysql_datetime(checked_at)
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.text(
                    """
                    UPDATE file_ingest_leases
                    SET status = 'expired', completed_at = :checked_at
                    WHERE status IN ('active', 'committing')
                      AND expires_at <= :checked_at
                    """
                ),
                {"checked_at": timestamp},
            )
        return result.rowcount

    def temporary_object_reclaimable(
        self,
        *,
        lease_token: UUID,
        temporary_path: str,
        checked_at: datetime,
    ) -> bool:
        """Return whether a stale private object has no live ingest owner."""

        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                    SELECT temporary_path, status, expires_at
                    FROM file_ingest_leases
                    WHERE lease_token = :lease_token
                    LIMIT 1
                    """
                    ),
                    {"lease_token": lease_token.bytes},
                )
                .mappings()
                .first()
            )
        if row is None:
            return True
        if row["temporary_path"] != temporary_path:
            return False
        if row["status"] in {"completed", "expired", "failed"}:
            return True
        expires_at = row["expires_at"]
        if not isinstance(expires_at, datetime):
            raise RuntimeError("file ingest lease has an invalid expiry timestamp")
        return expires_at <= _mysql_datetime(checked_at)

    def has_valid_lease(
        self,
        connection: Connection,
        *,
        storage_key: str,
        sha256_hex: str,
        checked_at: datetime,
    ) -> bool:
        digest = _validate_storage_identity(
            storage_key=storage_key,
            sha256_hex=sha256_hex,
            size_bytes=0,
        )
        value = connection.scalar(
            sa.text(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM file_ingest_leases
                    WHERE status IN ('active', 'committing')
                      AND expires_at > :checked_at
                      AND (storage_key = :storage_key OR sha256 = :sha256)
                )
                """
            ),
            {
                "storage_key": storage_key,
                "sha256": digest,
                "checked_at": _mysql_datetime(checked_at),
            },
        )
        return bool(value == 1)

    def has_raw_file_reference(
        self,
        connection: Connection,
        *,
        storage_key: str,
        sha256_hex: str,
    ) -> bool:
        digest = _validate_storage_identity(
            storage_key=storage_key,
            sha256_hex=sha256_hex,
            size_bytes=0,
        )
        value = connection.scalar(
            sa.text(
                """
                SELECT EXISTS(
                    SELECT 1 FROM raw_files
                    WHERE storage_key = :storage_key OR sha256 = :sha256
                )
                """
            ),
            {"storage_key": storage_key, "sha256": digest},
        )
        return bool(value == 1)

    def referenced_files(self) -> Iterable[Mapping[str, object]]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                sa.text(
                    """
                    SELECT id, sha256, storage_key, size_bytes
                    FROM raw_files
                    ORDER BY id
                    """
                )
            ).mappings()
            return [dict(row) for row in rows]

    def record_integrity_status(
        self,
        *,
        raw_file_id: int,
        status: str,
        checked_at: datetime,
        connection: Connection | None = None,
    ) -> None:
        if status not in {
            "available",
            "missing",
            "size_mismatch",
            "hash_mismatch",
        }:
            raise ValueError("unsupported raw-file integrity status")
        timestamp = _mysql_datetime(checked_at)
        if connection is None:
            with self._engine.begin() as owned_connection:
                self._record_integrity_status(
                    owned_connection,
                    raw_file_id=raw_file_id,
                    status=status,
                    timestamp=timestamp,
                )
            return
        with connection.begin():
            self._record_integrity_status(
                connection,
                raw_file_id=raw_file_id,
                status=status,
                timestamp=timestamp,
            )

    def _record_integrity_status(
        self,
        connection: Connection,
        *,
        raw_file_id: int,
        status: str,
        timestamp: datetime,
    ) -> None:
        if status == "available":
            self._mark_integrity_available(
                connection,
                raw_file_id=raw_file_id,
                checked_at=timestamp,
            )
        else:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO raw_file_integrity_statuses (
                        raw_file_id, status, first_detected_at,
                        last_checked_at, resolved_at
                    ) VALUES (
                        :raw_file_id, :status, :checked_at,
                        :checked_at, NULL
                    ) AS incoming
                    ON DUPLICATE KEY UPDATE
                        first_detected_at = IF(
                            incoming.last_checked_at >=
                                raw_file_integrity_statuses.last_checked_at,
                            COALESCE(
                                raw_file_integrity_statuses.first_detected_at,
                                incoming.first_detected_at
                            ),
                            raw_file_integrity_statuses.first_detected_at
                        ),
                        resolved_at = IF(
                            incoming.last_checked_at >=
                                raw_file_integrity_statuses.last_checked_at,
                            NULL,
                            raw_file_integrity_statuses.resolved_at
                        ),
                        status = IF(
                            incoming.last_checked_at >=
                                raw_file_integrity_statuses.last_checked_at,
                            incoming.status,
                            raw_file_integrity_statuses.status
                        ),
                        last_checked_at = GREATEST(
                            raw_file_integrity_statuses.last_checked_at,
                            incoming.last_checked_at
                        )
                    """
                ),
                {
                    "raw_file_id": raw_file_id,
                    "status": status,
                    "checked_at": timestamp,
                },
            )

    @staticmethod
    def _find_or_create_raw_file(
        connection: Connection,
        *,
        digest: bytes,
        command: ImportCommand,
        stored: StoredContent,
        uploaded_at: datetime,
    ) -> int:
        existing = (
            connection.execute(
                sa.text(
                    """
                SELECT id, storage_key, size_bytes
                FROM raw_files
                WHERE sha256 = :sha256
                """
                ),
                {"sha256": digest},
            )
            .mappings()
            .first()
        )
        if existing is not None:
            if (
                existing["storage_key"] != stored.storage_key
                or int(existing["size_bytes"]) != stored.size_bytes
            ):
                raise IngestCommitFailed(
                    "existing raw-file metadata does not match stored content"
                )
            return int(existing["id"])

        result = connection.execute(
            sa.text(
                """
                INSERT INTO raw_files (
                    sha256, storage_key, original_filename, media_type,
                    size_bytes, uploaded_by_user_id, uploaded_at
                ) VALUES (
                    :sha256, :storage_key, :original_filename, :media_type,
                    :size_bytes, :uploaded_by_user_id, :uploaded_at
                )
                """
            ),
            {
                "sha256": digest,
                "storage_key": stored.storage_key,
                "original_filename": command.original_filename,
                "media_type": command.media_type,
                "size_bytes": stored.size_bytes,
                "uploaded_by_user_id": command.created_by_user_id,
                "uploaded_at": uploaded_at,
            },
        )
        if result.lastrowid is None:
            raise IngestCommitFailed("database did not return the raw-file ID")
        return int(result.lastrowid)

    @staticmethod
    def _find_or_create_batch(
        connection: Connection,
        *,
        raw_file_id: int,
        command: ImportCommand,
        created_at: datetime,
    ) -> tuple[int, bool]:
        existing_batch_id = connection.scalar(
            sa.text(
                """
                SELECT id FROM import_batches
                WHERE raw_file_id = :raw_file_id
                FOR UPDATE
                """
            ),
            {"raw_file_id": raw_file_id},
        )
        if existing_batch_id is not None:
            return int(existing_batch_id), False

        site_id = connection.scalar(
            sa.text(
                """
                SELECT site_id
                FROM site_config_versions
                WHERE id = :site_config_version_id
                """
            ),
            {"site_config_version_id": command.site_config_version_id},
        )
        if site_id is None:
            raise IngestCommitFailed("site configuration version does not exist")

        result = connection.execute(
            sa.text(
                """
                INSERT INTO import_batches (
                    raw_file_id, site_id, site_config_version_id,
                    report_date, candidate_report_date, status, created_by_user_id,
                    created_at, updated_at
                ) VALUES (
                    :raw_file_id, :site_id, :site_config_version_id,
                    :report_date, :report_date, 'uploaded', :created_by_user_id,
                    :created_at, :created_at
                )
                """
            ),
            {
                "raw_file_id": raw_file_id,
                "site_id": int(site_id),
                "site_config_version_id": command.site_config_version_id,
                "report_date": command.report_date,
                "created_by_user_id": command.created_by_user_id,
                "created_at": created_at,
            },
        )
        if result.lastrowid is None:
            raise IngestCommitFailed("database did not return the import batch ID")
        return int(result.lastrowid), True

    @staticmethod
    def _mark_integrity_available(
        connection: Connection,
        *,
        raw_file_id: int,
        checked_at: datetime,
    ) -> None:
        connection.execute(
            sa.text(
                """
                INSERT INTO raw_file_integrity_statuses (
                    raw_file_id, status, first_detected_at,
                    last_checked_at, resolved_at
                ) VALUES (
                    :raw_file_id, 'available', NULL, :checked_at, NULL
                ) AS incoming
                ON DUPLICATE KEY UPDATE
                    resolved_at = IF(
                        incoming.last_checked_at >=
                            raw_file_integrity_statuses.last_checked_at,
                        IF(
                            raw_file_integrity_statuses.status <> 'available'
                                AND raw_file_integrity_statuses.first_detected_at
                                    IS NOT NULL,
                            incoming.last_checked_at,
                            raw_file_integrity_statuses.resolved_at
                        ),
                        raw_file_integrity_statuses.resolved_at
                    ),
                    status = IF(
                        incoming.last_checked_at >=
                            raw_file_integrity_statuses.last_checked_at,
                        'available',
                        raw_file_integrity_statuses.status
                    ),
                    last_checked_at = GREATEST(
                        raw_file_integrity_statuses.last_checked_at,
                        incoming.last_checked_at
                    )
                """
            ),
            {"raw_file_id": raw_file_id, "checked_at": checked_at},
        )

    @staticmethod
    def _completed_import(
        connection: Connection,
        lease_token: UUID,
    ) -> RecoveredImport | None:
        row = (
            connection.execute(
                sa.text(
                    """
                SELECT leases.raw_file_id, batches.id AS batch_id
                FROM file_ingest_leases AS leases
                INNER JOIN import_batches AS batches
                    ON batches.raw_file_id = leases.raw_file_id
                WHERE leases.lease_token = :lease_token
                  AND leases.status = 'completed'
                LIMIT 1
                """
                ),
                {"lease_token": lease_token.bytes},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return RecoveredImport(
            raw_file_id=int(row["raw_file_id"]),
            batch_id=int(row["batch_id"]),
        )
