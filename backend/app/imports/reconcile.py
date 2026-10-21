"""Reconcile content objects that cannot participate in a MySQL transaction."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.imports.storage import (
    ContentHashMismatchError,
    ContentIntegrityError,
    ContentNotFoundError,
    ContentObject,
    ContentSizeMismatchError,
    LocalContentStore,
    QuarantinedContent,
    QuarantinedTemporary,
    TemporaryObject,
)

_STORAGE_KEY_PATTERN = re.compile(
    r"sha256/(?P<prefix>[0-9a-f]{2})/(?P<digest>[0-9a-f]{64})\Z",
    re.ASCII,
)


class ReconcileRepository(Protocol):
    def expire_stale_leases(self, *, checked_at: datetime) -> int: ...

    def digest_lock(self, sha256_hex: str) -> AbstractContextManager[Any]: ...

    def has_valid_lease(
        self,
        connection: Any,
        *,
        storage_key: str,
        sha256_hex: str,
        checked_at: datetime,
    ) -> bool: ...

    def has_raw_file_reference(
        self,
        connection: Any,
        *,
        storage_key: str,
        sha256_hex: str,
    ) -> bool: ...

    def referenced_files(self) -> Iterable[Mapping[str, object]]: ...

    def record_integrity_status(
        self,
        *,
        raw_file_id: int,
        status: str,
        checked_at: datetime,
        connection: Any | None = None,
    ) -> None: ...

    def temporary_object_reclaimable(
        self,
        *,
        lease_token: UUID,
        temporary_path: str,
        checked_at: datetime,
    ) -> bool: ...


class ReconcileStore(Protocol):
    def iter_objects(self) -> Iterable[ContentObject]: ...

    def quarantine(
        self,
        storage_key: str,
        scan_id: UUID,
    ) -> QuarantinedContent | None: ...

    def validate(
        self,
        storage_key: str,
        expected_sha256_hex: str,
        expected_size: int,
    ) -> bool: ...

    def iter_temporary_objects(self) -> Iterable[TemporaryObject]: ...

    def quarantine_temporary(
        self,
        temporary: TemporaryObject,
        scan_id: UUID,
    ) -> QuarantinedTemporary | None: ...


@dataclass(frozen=True, slots=True)
class OrphanReconciliationReport:
    scanned_objects: int
    old_candidates: int
    scanned_temporary_objects: int
    old_temporary_candidates: int
    expired_leases: int
    quarantined: tuple[QuarantinedContent, ...]
    quarantined_temporary: tuple[QuarantinedTemporary, ...]
    skipped_valid_lease: tuple[str, ...]
    skipped_reference: tuple[str, ...]
    skipped_temporary_lease: tuple[str, ...]
    disappeared_concurrently: tuple[str, ...]
    temporary_disappeared_concurrently: tuple[str, ...]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _digest_from_storage_key(storage_key: str) -> str:
    match = _STORAGE_KEY_PATTERN.fullmatch(storage_key)
    if match is None or match.group("prefix") != match.group("digest")[:2]:
        raise ValueError("reconciliation received a non-canonical storage key")
    return match.group("digest")


class StorageReconciler:
    """Quarantine old orphans and persist referenced-object health."""

    def __init__(
        self,
        *,
        repository: ReconcileRepository,
        store: ReconcileStore | LocalContentStore,
        orphan_age: timedelta,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if orphan_age < timedelta(hours=24):
            raise ValueError("orphan_age must be at least 24 hours")
        self._repository = repository
        self._store = store
        self._orphan_age = orphan_age
        self._clock = clock

    def reconcile_orphans(
        self,
        *,
        scan_id: UUID | None = None,
    ) -> OrphanReconciliationReport:
        """Move only strictly old, unlocked, and unreferenced objects."""

        checked_at = self._clock()
        resolved_scan_id = scan_id or uuid4()
        expired_leases = self._repository.expire_stale_leases(checked_at=checked_at)
        objects = list(self._store.iter_objects())
        temporary_objects = list(self._store.iter_temporary_objects())
        cutoff = checked_at - self._orphan_age
        candidates = [item for item in objects if item.modified_at < cutoff]
        temporary_candidates = [
            item for item in temporary_objects if item.modified_at < cutoff
        ]

        quarantined: list[QuarantinedContent] = []
        skipped_valid_lease: list[str] = []
        skipped_reference: list[str] = []
        disappeared: list[str] = []
        for candidate in candidates:
            digest = _digest_from_storage_key(candidate.storage_key)
            with self._repository.digest_lock(digest) as connection:
                if self._repository.has_valid_lease(
                    connection,
                    storage_key=candidate.storage_key,
                    sha256_hex=digest,
                    checked_at=checked_at,
                ):
                    skipped_valid_lease.append(candidate.storage_key)
                    continue
                if self._repository.has_raw_file_reference(
                    connection,
                    storage_key=candidate.storage_key,
                    sha256_hex=digest,
                ):
                    skipped_reference.append(candidate.storage_key)
                    continue
                moved = self._store.quarantine(
                    candidate.storage_key,
                    resolved_scan_id,
                )
                if moved is None:
                    disappeared.append(candidate.storage_key)
                else:
                    quarantined.append(moved)

        quarantined_temporary: list[QuarantinedTemporary] = []
        skipped_temporary_lease: list[str] = []
        temporary_disappeared: list[str] = []
        for temporary in temporary_candidates:
            if not self._repository.temporary_object_reclaimable(
                lease_token=temporary.lease_token,
                temporary_path=temporary.temporary_key,
                checked_at=checked_at,
            ):
                skipped_temporary_lease.append(temporary.temporary_key)
                continue
            moved_temporary = self._store.quarantine_temporary(
                temporary,
                resolved_scan_id,
            )
            if moved_temporary is None:
                temporary_disappeared.append(temporary.temporary_key)
            else:
                quarantined_temporary.append(moved_temporary)

        return OrphanReconciliationReport(
            scanned_objects=len(objects),
            old_candidates=len(candidates),
            scanned_temporary_objects=len(temporary_objects),
            old_temporary_candidates=len(temporary_candidates),
            expired_leases=expired_leases,
            quarantined=tuple(quarantined),
            quarantined_temporary=tuple(quarantined_temporary),
            skipped_valid_lease=tuple(skipped_valid_lease),
            skipped_reference=tuple(skipped_reference),
            skipped_temporary_lease=tuple(skipped_temporary_lease),
            disappeared_concurrently=tuple(disappeared),
            temporary_disappeared_concurrently=tuple(temporary_disappeared),
        )

    def check_referenced_integrity(self) -> dict[int, str]:
        """Validate every referenced object and upsert its blocking state."""

        results: dict[int, str] = {}
        for row in self._repository.referenced_files():
            raw_file_id = _positive_int(row.get("id"), label="raw_file id")
            storage_key = _required_string(row.get("storage_key"), label="storage_key")
            digest = _binary_digest_hex(row.get("sha256"))
            size_bytes = _nonnegative_int(row.get("size_bytes"), label="size_bytes")

            with self._repository.digest_lock(digest) as connection:
                status = self._integrity_status(
                    storage_key=storage_key,
                    sha256_hex=digest,
                    size_bytes=size_bytes,
                )
                checked_at = self._clock()
                self._repository.record_integrity_status(
                    raw_file_id=raw_file_id,
                    status=status,
                    checked_at=checked_at,
                    connection=connection,
                )
            results[raw_file_id] = status
        return results

    def _integrity_status(
        self,
        *,
        storage_key: str,
        sha256_hex: str,
        size_bytes: int,
    ) -> str:
        try:
            self._store.validate(storage_key, sha256_hex, size_bytes)
        except ContentNotFoundError:
            return "missing"
        except ContentSizeMismatchError:
            return "size_mismatch"
        except ContentHashMismatchError:
            return "hash_mismatch"
        except ContentIntegrityError:
            return "hash_mismatch"
        return "available"


def _required_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _positive_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _binary_digest_hex(value: object) -> str:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError("sha256 must be binary")
    digest = bytes(value)
    if len(digest) != 32:
        raise ValueError("sha256 must contain exactly 32 bytes")
    return digest.hex()
