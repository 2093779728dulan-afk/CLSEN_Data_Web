from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.imports.reconcile import StorageReconciler
from app.imports.storage import (
    ContentHashMismatchError,
    ContentNotFoundError,
    ContentObject,
    QuarantinedContent,
    QuarantinedTemporary,
    TemporaryObject,
)

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
DIGEST = "12" * 32
STORAGE_KEY = f"sha256/12/{DIGEST}"
SCAN_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


class RecordingReconcileRepository:
    def __init__(self) -> None:
        self.valid_lease = False
        self.raw_reference = False
        self.calls: list[str] = []
        self.references: list[dict[str, object]] = []
        self.status_updates: list[tuple[int, str]] = []
        self.checked_times: list[datetime] = []
        self.temporary_reclaimable = False

    def expire_stale_leases(self, *, checked_at: datetime) -> int:
        self.calls.append("expire_stale_leases")
        return 0

    @contextmanager
    def digest_lock(self, _sha256_hex: str) -> Iterator[object]:
        self.calls.append("digest_lock")
        yield object()

    def has_valid_lease(
        self,
        _connection: object,
        *,
        storage_key: str,
        sha256_hex: str,
        checked_at: datetime,
    ) -> bool:
        del storage_key, sha256_hex, checked_at
        self.calls.append("has_valid_lease")
        return self.valid_lease

    def has_raw_file_reference(
        self,
        _connection: object,
        *,
        storage_key: str,
        sha256_hex: str,
    ) -> bool:
        del storage_key, sha256_hex
        self.calls.append("has_raw_file_reference")
        return self.raw_reference

    def referenced_files(self) -> list[dict[str, object]]:
        self.calls.append("referenced_files")
        return self.references

    def record_integrity_status(
        self,
        *,
        raw_file_id: int,
        status: str,
        checked_at: datetime,
        connection: object | None = None,
    ) -> None:
        del connection
        self.calls.append("record_integrity_status")
        self.status_updates.append((raw_file_id, status))
        self.checked_times.append(checked_at)

    def temporary_object_reclaimable(
        self,
        *,
        lease_token: UUID,
        temporary_path: str,
        checked_at: datetime,
    ) -> bool:
        del lease_token, temporary_path, checked_at
        self.calls.append("temporary_object_reclaimable")
        return self.temporary_reclaimable


class RecordingReconcileStore:
    def __init__(self, objects: list[ContentObject]) -> None:
        self.objects = objects
        self.temporary_objects: list[TemporaryObject] = []
        self.quarantined: list[str] = []
        self.quarantined_temporary: list[str] = []
        self.validation_error: Exception | None = None

    def iter_objects(self) -> list[ContentObject]:
        return self.objects

    def quarantine(
        self,
        storage_key: str,
        scan_id: UUID,
    ) -> QuarantinedContent | None:
        self.quarantined.append(storage_key)
        return QuarantinedContent(
            storage_key=storage_key,
            quarantine_key=f"{scan_id}/{storage_key}",
            path=Path("quarantined"),
            size_bytes=7,
        )

    def iter_temporary_objects(self) -> list[TemporaryObject]:
        return self.temporary_objects

    def quarantine_temporary(
        self,
        temporary: TemporaryObject,
        scan_id: UUID,
    ) -> QuarantinedTemporary | None:
        self.quarantined_temporary.append(temporary.temporary_key)
        return QuarantinedTemporary(
            lease_token=temporary.lease_token,
            temporary_key=temporary.temporary_key,
            quarantine_key=f"{scan_id}/{temporary.temporary_key}",
            path=Path("quarantined-temporary"),
            size_bytes=temporary.size_bytes,
        )

    def validate(
        self,
        storage_key: str,
        expected_sha256_hex: str,
        expected_size: int,
    ) -> bool:
        del storage_key, expected_sha256_hex, expected_size
        if self.validation_error is not None:
            raise self.validation_error
        return True


def _object(age: timedelta) -> ContentObject:
    return ContentObject(
        storage_key=STORAGE_KEY,
        path=Path("content"),
        size_bytes=7,
        modified_at=NOW - age,
    )


def _temporary_object(age: timedelta) -> TemporaryObject:
    token = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    return TemporaryObject(
        lease_token=token,
        temporary_key=f".ingest/{token}.part",
        path=Path("temporary"),
        size_bytes=7,
        modified_at=NOW - age,
    )


def _reconciler(
    repository: RecordingReconcileRepository,
    store: RecordingReconcileStore,
) -> StorageReconciler:
    return StorageReconciler(
        repository=repository,
        store=store,
        orphan_age=timedelta(hours=24),
        clock=lambda: NOW,
    )


def test_object_at_exactly_orphan_age_is_not_quarantined() -> None:
    repository = RecordingReconcileRepository()
    store = RecordingReconcileStore([_object(timedelta(hours=24))])

    report = _reconciler(repository, store).reconcile_orphans(scan_id=SCAN_ID)

    assert report.quarantined == ()
    assert store.quarantined == []
    assert "digest_lock" not in repository.calls


def test_old_object_with_valid_lease_is_not_quarantined() -> None:
    repository = RecordingReconcileRepository()
    repository.valid_lease = True
    store = RecordingReconcileStore([_object(timedelta(hours=25))])

    report = _reconciler(repository, store).reconcile_orphans(scan_id=SCAN_ID)

    assert report.skipped_valid_lease == (STORAGE_KEY,)
    assert store.quarantined == []


def test_old_unreferenced_object_is_quarantined() -> None:
    repository = RecordingReconcileRepository()
    store = RecordingReconcileStore([_object(timedelta(hours=25))])

    report = _reconciler(repository, store).reconcile_orphans(scan_id=SCAN_ID)

    assert tuple(item.storage_key for item in report.quarantined) == (STORAGE_KEY,)
    assert store.quarantined == [STORAGE_KEY]
    assert repository.calls.index("has_valid_lease") < repository.calls.index(
        "has_raw_file_reference"
    )


def test_reference_added_before_locked_recheck_prevents_quarantine() -> None:
    repository = RecordingReconcileRepository()
    repository.raw_reference = True
    store = RecordingReconcileStore([_object(timedelta(hours=25))])

    report = _reconciler(repository, store).reconcile_orphans(scan_id=SCAN_ID)

    assert report.skipped_reference == (STORAGE_KEY,)
    assert store.quarantined == []


def test_old_temporary_object_with_live_lease_is_not_quarantined() -> None:
    repository = RecordingReconcileRepository()
    store = RecordingReconcileStore([])
    store.temporary_objects = [_temporary_object(timedelta(hours=25))]

    report = _reconciler(repository, store).reconcile_orphans(scan_id=SCAN_ID)

    assert report.skipped_temporary_lease == (store.temporary_objects[0].temporary_key,)
    assert store.quarantined_temporary == []


def test_old_temporary_object_with_terminal_lease_is_quarantined() -> None:
    repository = RecordingReconcileRepository()
    repository.temporary_reclaimable = True
    store = RecordingReconcileStore([])
    store.temporary_objects = [_temporary_object(timedelta(hours=25))]

    report = _reconciler(repository, store).reconcile_orphans(scan_id=SCAN_ID)

    assert tuple(item.temporary_key for item in report.quarantined_temporary) == (
        store.temporary_objects[0].temporary_key,
    )
    assert store.quarantined_temporary == [store.temporary_objects[0].temporary_key]


def test_missing_reference_records_blocking_integrity_status() -> None:
    repository = RecordingReconcileRepository()
    repository.references = [
        {
            "id": 71,
            "sha256": bytes.fromhex(DIGEST),
            "storage_key": STORAGE_KEY,
            "size_bytes": 7,
        }
    ]
    store = RecordingReconcileStore([])
    store.validation_error = ContentNotFoundError("missing")

    report = _reconciler(repository, store).check_referenced_integrity()

    assert report == {71: "missing"}
    assert repository.status_updates == [(71, "missing")]


def test_hash_mismatch_records_specific_integrity_status() -> None:
    repository = RecordingReconcileRepository()
    repository.references = [
        {
            "id": 72,
            "sha256": bytes.fromhex(DIGEST),
            "storage_key": STORAGE_KEY,
            "size_bytes": 7,
        }
    ]
    store = RecordingReconcileStore([])
    store.validation_error = ContentHashMismatchError("corrupt")

    report = _reconciler(repository, store).check_referenced_integrity()

    assert report == {72: "hash_mismatch"}
    assert repository.status_updates == [(72, "hash_mismatch")]


def test_valid_reference_resolves_a_previous_integrity_failure() -> None:
    repository = RecordingReconcileRepository()
    repository.references = [
        {
            "id": 73,
            "sha256": bytes.fromhex(DIGEST),
            "storage_key": STORAGE_KEY,
            "size_bytes": 7,
        }
    ]
    store = RecordingReconcileStore([])

    report = _reconciler(repository, store).check_referenced_integrity()

    assert report == {73: "available"}
    assert repository.status_updates == [(73, "available")]


def test_each_integrity_result_uses_time_observed_after_its_digest_lock() -> None:
    repository = RecordingReconcileRepository()
    repository.references = [
        {
            "id": raw_file_id,
            "sha256": bytes.fromhex(DIGEST),
            "storage_key": STORAGE_KEY,
            "size_bytes": 7,
        }
        for raw_file_id in (81, 82)
    ]
    store = RecordingReconcileStore([])
    observations = iter((NOW, NOW + timedelta(minutes=1)))
    reconciler = StorageReconciler(
        repository=repository,
        store=store,
        orphan_age=timedelta(hours=24),
        clock=lambda: next(observations),
    )

    reconciler.check_referenced_integrity()

    assert repository.checked_times == [NOW, NOW + timedelta(minutes=1)]
