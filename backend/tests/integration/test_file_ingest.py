from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Barrier, Event
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.imports.reconcile import ReconcileRepository, StorageReconciler
from app.imports.repository import MySqlIngestRepository
from app.imports.service import IngestRepository, IngestService
from app.imports.storage import LocalContentStore, StoredContent
from app.imports.types import (
    CommitOutcomeUnknown,
    DuplicateBatchConflict,
    FinalizedImport,
    ImportCommand,
    ImportCreated,
    IngestCommitFailed,
    RecoveredImport,
)
from sqlalchemy.engine import Connection, Engine

pytestmark = pytest.mark.mysql

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
LEASE_TTL = timedelta(minutes=30)
RENEW_INTERVAL = timedelta(minutes=5)
_LOCK_NAME_TEST_SQL = "SHA2(CONCAT(DATABASE(), '-raw-object-', :digest), 256)"


class _InjectedLockBoundary(BaseException):
    """Simulate process-level interruption after MySQL executes a lock query."""


def _physical_connection_id(connection: Connection) -> int:
    driver_connection: Any = connection.connection.driver_connection
    return int(driver_connection.thread_id())


def _get_digest_lock(connection: Connection, digest: str) -> int | None:
    value = connection.scalar(
        sa.text(f"SELECT GET_LOCK({_LOCK_NAME_TEST_SQL}, 0)"),
        {"digest": digest},
    )
    connection.commit()
    return None if value is None else int(value)


def _release_digest_lock(connection: Connection, digest: str) -> int | None:
    value = connection.scalar(
        sa.text(f"SELECT RELEASE_LOCK({_LOCK_NAME_TEST_SQL})"),
        {"digest": digest},
    )
    connection.commit()
    return None if value is None else int(value)


@dataclass(frozen=True, slots=True)
class IngestCase:
    user_id: int
    store: LocalContentStore
    repository: MySqlIngestRepository
    engine: Engine

    def command(self) -> ImportCommand:
        return ImportCommand(
            original_filename=f"integration-{uuid4().hex}.csv",
            media_type="text/csv",
            created_by_user_id=self.user_id,
            site_config_version_id=1,
            report_date=date(2099, 1, 1),
        )

    def service(self, repository: IngestRepository | None = None) -> IngestService:
        return IngestService(
            repository=repository or self.repository,
            store=self.store,
            lease_ttl=LEASE_TTL,
            lease_renew_interval=RENEW_INTERVAL,
            clock=lambda: NOW,
        )


@pytest.fixture()
def ingest_case(
    alembic_config: Config,
    mysql_engine: Engine,
    tmp_path: Path,
) -> Iterator[IngestCase]:
    command.upgrade(alembic_config, "head")
    username = f"file-ingest-{uuid4().hex}"
    with mysql_engine.begin() as connection:
        result = connection.execute(
            sa.text(
                """
                INSERT INTO users (
                    username_normalized, display_name, password_hash, status
                ) VALUES (
                    :username, 'File Ingest Test', '$argon2id$test', 'active'
                )
                """
            ),
            {"username": username},
        )
        assert result.lastrowid is not None
        user_id = int(result.lastrowid)

    store = LocalContentStore(tmp_path / "storage", max_upload_bytes=1024 * 1024)
    repository = MySqlIngestRepository(mysql_engine, lock_timeout_seconds=5)
    case = IngestCase(
        user_id=user_id,
        store=store,
        repository=repository,
        engine=mysql_engine,
    )
    try:
        yield case
    finally:
        with mysql_engine.begin() as connection:
            raw_file_ids = list(
                connection.scalars(
                    sa.text(
                        "SELECT id FROM raw_files WHERE uploaded_by_user_id = :user_id"
                    ),
                    {"user_id": user_id},
                )
            )
            connection.execute(
                sa.text(
                    "DELETE FROM import_batches WHERE created_by_user_id = :user_id"
                ),
                {"user_id": user_id},
            )
            connection.execute(
                sa.text(
                    "DELETE FROM file_ingest_leases WHERE created_by_user_id = :user_id"
                ),
                {"user_id": user_id},
            )
            if raw_file_ids:
                connection.execute(
                    sa.text(
                        "DELETE FROM raw_file_integrity_statuses "
                        "WHERE raw_file_id IN :raw_file_ids"
                    ).bindparams(sa.bindparam("raw_file_ids", expanding=True)),
                    {"raw_file_ids": raw_file_ids},
                )
                connection.execute(
                    sa.text(
                        "DELETE FROM raw_files WHERE id IN :raw_file_ids"
                    ).bindparams(sa.bindparam("raw_file_ids", expanding=True)),
                    {"raw_file_ids": raw_file_ids},
                )
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )


def _row_counts(case: IngestCase, digest: str) -> tuple[int, int, int]:
    with case.engine.connect() as connection:
        raw_count = connection.scalar(
            sa.text("SELECT COUNT(*) FROM raw_files WHERE sha256 = :sha256"),
            {"sha256": bytes.fromhex(digest)},
        )
        batch_count = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM import_batches AS batches
                INNER JOIN raw_files AS files ON files.id = batches.raw_file_id
                WHERE files.sha256 = :sha256
                """
            ),
            {"sha256": bytes.fromhex(digest)},
        )
        lease_count = connection.scalar(
            sa.text(
                "SELECT COUNT(*) FROM file_ingest_leases "
                "WHERE created_by_user_id = :user_id"
            ),
            {"user_id": case.user_id},
        )
    return int(raw_count or 0), int(batch_count or 0), int(lease_count or 0)


def _age_object(case: IngestCase, storage_key: str, age: timedelta) -> None:
    timestamp = (NOW - age).timestamp()
    os.utime(case.store.root / storage_key, (timestamp, timestamp))


def test_unreferenced_content_object_is_reused_for_first_batch(
    ingest_case: IngestCase,
) -> None:
    content = b"unreferenced content object"
    staged = ingest_case.store.write_stream(uuid4(), BytesIO(content))
    preexisting = ingest_case.store.promote(staged)
    assert preexisting.reused is False

    result = ingest_case.service().ingest(
        BytesIO(content),
        ingest_case.command(),
    )

    assert isinstance(result, ImportCreated)
    assert result.content_reused is True
    assert _row_counts(ingest_case, result.sha256_hex) == (1, 1, 1)


def test_reupload_returns_existing_batch_without_new_rows(
    ingest_case: IngestCase,
) -> None:
    content = b"repeat upload"
    first = ingest_case.service().ingest(BytesIO(content), ingest_case.command())
    second = ingest_case.service().ingest(BytesIO(content), ingest_case.command())

    assert isinstance(first, ImportCreated)
    assert second == DuplicateBatchConflict(
        existing_batch_id=first.batch_id,
        raw_file_id=first.raw_file_id,
        sha256_hex=first.sha256_hex,
    )
    assert _row_counts(ingest_case, first.sha256_hex) == (1, 1, 2)


class _BarrierRepository:
    def __init__(self, inner: MySqlIngestRepository, barrier: Barrier) -> None:
        self._inner = inner
        self._barrier = barrier

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @contextmanager
    def digest_lock(self, sha256_hex: str) -> Iterator[Connection]:
        self._barrier.wait(timeout=5)
        with self._inner.digest_lock(sha256_hex) as connection:
            yield connection


def test_concurrent_duplicate_uploads_create_one_batch(
    ingest_case: IngestCase,
) -> None:
    barrier = Barrier(2)
    repository = cast(
        IngestRepository,
        _BarrierRepository(ingest_case.repository, barrier),
    )

    def upload() -> ImportCreated | DuplicateBatchConflict:
        result = ingest_case.service(repository).ingest(
            BytesIO(b"concurrent duplicate"),
            ingest_case.command(),
        )
        assert isinstance(result, (ImportCreated, DuplicateBatchConflict))
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: upload(), range(2)))

    created = [item for item in results if isinstance(item, ImportCreated)]
    duplicates = [item for item in results if isinstance(item, DuplicateBatchConflict)]
    assert len(created) == 1
    assert len(duplicates) == 1
    assert duplicates[0].existing_batch_id == created[0].batch_id
    assert duplicates[0].raw_file_id == created[0].raw_file_id
    assert _row_counts(ingest_case, created[0].sha256_hex) == (1, 1, 2)


class _FailingFinalizeRepository(_BarrierRepository):
    def __init__(self, inner: MySqlIngestRepository) -> None:
        super().__init__(inner, Barrier(1))

    def finalize_import(
        self,
        connection: Connection,
        *,
        lease_token: UUID,
        command: ImportCommand,
        stored: StoredContent,
        completed_at: datetime,
    ) -> FinalizedImport:
        def fail_before_lease_completion(
            _connection: Connection,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            normalized = " ".join(statement.split()).casefold()
            if (
                "update file_ingest_leases" in normalized
                and "set status = 'completed'" in normalized
            ):
                raise IngestCommitFailed("injected finalization statement failure")

        sa.event.listen(
            connection,
            "before_cursor_execute",
            fail_before_lease_completion,
        )
        try:
            return self._inner.finalize_import(
                connection,
                lease_token=lease_token,
                command=command,
                stored=stored,
                completed_at=completed_at,
            )
        finally:
            sa.event.remove(
                connection,
                "before_cursor_execute",
                fail_before_lease_completion,
            )


class _LostCommitAcknowledgementRepository(_BarrierRepository):
    def __init__(self, inner: MySqlIngestRepository) -> None:
        super().__init__(inner, Barrier(1))

    def finalize_import(
        self,
        connection: Connection,
        *,
        lease_token: UUID,
        command: ImportCommand,
        stored: StoredContent,
        completed_at: datetime,
    ) -> FinalizedImport:
        self._inner.finalize_import(
            connection,
            lease_token=lease_token,
            command=command,
            stored=stored,
            completed_at=completed_at,
        )
        raise CommitOutcomeUnknown("injected commit acknowledgement loss")


class _PausedLockRepository:
    def __init__(
        self,
        inner: MySqlIngestRepository,
        candidate_selected: Event,
        continue_scan: Event,
    ) -> None:
        self._inner = inner
        self._candidate_selected = candidate_selected
        self._continue_scan = continue_scan

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @contextmanager
    def digest_lock(self, sha256_hex: str) -> Iterator[Connection]:
        self._candidate_selected.set()
        if not self._continue_scan.wait(timeout=5):
            raise TimeoutError("test did not release the paused orphan scan")
        with self._inner.digest_lock(sha256_hex) as connection:
            yield connection


def test_finalization_failure_preserves_object_and_committing_lease(
    ingest_case: IngestCase,
) -> None:
    repository = cast(
        IngestRepository,
        _FailingFinalizeRepository(ingest_case.repository),
    )
    command_value = ingest_case.command()

    with pytest.raises(IngestCommitFailed, match="injected"):
        ingest_case.service(repository).ingest(
            BytesIO(b"commit failure"),
            command_value,
        )

    with ingest_case.engine.connect() as connection:
        lease = (
            connection.execute(
                sa.text(
                    """
                SELECT status, storage_key FROM file_ingest_leases
                WHERE created_by_user_id = :user_id
                """
                ),
                {"user_id": ingest_case.user_id},
            )
            .mappings()
            .one()
        )
        raw_count = connection.scalar(
            sa.text(
                "SELECT COUNT(*) FROM raw_files WHERE uploaded_by_user_id = :user_id"
            ),
            {"user_id": ingest_case.user_id},
        )
        batch_count = connection.scalar(
            sa.text(
                "SELECT COUNT(*) FROM import_batches "
                "WHERE created_by_user_id = :user_id"
            ),
            {"user_id": ingest_case.user_id},
        )
        integrity_count = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM raw_file_integrity_statuses AS statuses
                INNER JOIN raw_files AS files ON files.id = statuses.raw_file_id
                WHERE files.uploaded_by_user_id = :user_id
                """
            ),
            {"user_id": ingest_case.user_id},
        )
    assert lease["status"] == "committing"
    assert (ingest_case.store.root / str(lease["storage_key"])).is_file()
    assert raw_count == 0
    assert batch_count == 0
    assert integrity_count == 0


def test_commit_acknowledgement_loss_recovers_the_committed_batch(
    ingest_case: IngestCase,
) -> None:
    repository = cast(
        IngestRepository,
        _LostCommitAcknowledgementRepository(ingest_case.repository),
    )

    result = ingest_case.service(repository).ingest(
        BytesIO(b"commit acknowledgement loss"),
        ingest_case.command(),
    )

    assert isinstance(result, RecoveredImport)
    with ingest_case.engine.connect() as connection:
        lease = (
            connection.execute(
                sa.text(
                    """
                SELECT status, raw_file_id
                FROM file_ingest_leases
                WHERE created_by_user_id = :user_id
                """
                ),
                {"user_id": ingest_case.user_id},
            )
            .mappings()
            .one()
        )
        batch_id = connection.scalar(
            sa.text("SELECT id FROM import_batches WHERE raw_file_id = :raw_file_id"),
            {"raw_file_id": lease["raw_file_id"]},
        )
    assert lease["status"] == "completed"
    assert result.raw_file_id == lease["raw_file_id"]
    assert result.batch_id == batch_id


def test_lock_release_failure_does_not_hide_a_committed_import(
    ingest_case: IngestCase,
) -> None:
    def fail_release_lock(
        _connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if "RELEASE_LOCK" in statement:
            raise RuntimeError("injected release failure")

    sa.event.listen(
        ingest_case.engine,
        "before_cursor_execute",
        fail_release_lock,
    )
    try:
        result = ingest_case.service().ingest(
            BytesIO(b"release failure after commit"),
            ingest_case.command(),
        )
    finally:
        sa.event.remove(
            ingest_case.engine,
            "before_cursor_execute",
            fail_release_lock,
        )

    assert isinstance(result, ImportCreated)
    assert _row_counts(ingest_case, result.sha256_hex) == (1, 1, 1)


def test_get_lock_result_loss_invalidates_the_physical_connection(
    ingest_case: IngestCase,
) -> None:
    digest = "cd" * 32
    failed_connection_id: int | None = None

    def lose_get_lock_result(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal failed_connection_id
        if "GET_LOCK" in statement:
            failed_connection_id = _physical_connection_id(connection)
            raise _InjectedLockBoundary("injected GET_LOCK result loss")

    with ingest_case.engine.connect() as witness:
        witness_connection_id = _physical_connection_id(witness)
        sa.event.listen(
            ingest_case.engine,
            "after_cursor_execute",
            lose_get_lock_result,
        )
        try:
            with (
                pytest.raises(_InjectedLockBoundary, match="GET_LOCK result loss"),
                ingest_case.repository.digest_lock(digest),
            ):
                pytest.fail("the uncertain lock acquisition must not yield")
        finally:
            sa.event.remove(
                ingest_case.engine,
                "after_cursor_execute",
                lose_get_lock_result,
            )

        assert failed_connection_id is not None
        assert failed_connection_id != witness_connection_id
        with ingest_case.engine.connect() as replacement:
            replacement_connection_id = _physical_connection_id(replacement)
            witness_acquired = _get_digest_lock(witness, digest)
            try:
                assert replacement_connection_id != failed_connection_id
                assert witness_acquired == 1
            finally:
                if witness_acquired == 1:
                    _release_digest_lock(witness, digest)
                _release_digest_lock(replacement, digest)


def test_release_lock_interruption_invalidates_and_propagates(
    ingest_case: IngestCase,
) -> None:
    digest = "ef" * 32
    failed_connection_id: int | None = None

    def interrupt_release_lock(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal failed_connection_id
        if "RELEASE_LOCK" in statement:
            failed_connection_id = _physical_connection_id(connection)
            raise _InjectedLockBoundary("injected RELEASE_LOCK interruption")

    with ingest_case.engine.connect() as witness:
        witness_connection_id = _physical_connection_id(witness)
        sa.event.listen(
            ingest_case.engine,
            "after_cursor_execute",
            interrupt_release_lock,
        )
        try:
            with (
                pytest.raises(
                    _InjectedLockBoundary,
                    match="RELEASE_LOCK interruption",
                ),
                ingest_case.repository.digest_lock(digest),
            ):
                pass
        finally:
            sa.event.remove(
                ingest_case.engine,
                "after_cursor_execute",
                interrupt_release_lock,
            )

        assert failed_connection_id is not None
        assert failed_connection_id != witness_connection_id
        with ingest_case.engine.connect() as replacement:
            try:
                assert _physical_connection_id(replacement) != failed_connection_id
            finally:
                _release_digest_lock(replacement, digest)


def test_old_orphan_with_valid_lease_is_not_quarantined(
    ingest_case: IngestCase,
) -> None:
    staged = ingest_case.store.write_stream(uuid4(), BytesIO(b"leased orphan"))
    stored = ingest_case.store.promote(staged)
    _age_object(ingest_case, stored.storage_key, timedelta(hours=25))
    with ingest_case.engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO file_ingest_leases (
                    lease_token, temporary_path, storage_key, sha256,
                    size_bytes, created_by_user_id, status, expires_at
                ) VALUES (
                    :token, '.ingest/test.part', :storage_key, :sha256,
                    :size_bytes, :user_id, 'committing', :expires_at
                )
                """
            ),
            {
                "token": uuid4().bytes,
                "storage_key": stored.storage_key,
                "sha256": bytes.fromhex(stored.sha256_hex),
                "size_bytes": stored.size_bytes,
                "user_id": ingest_case.user_id,
                "expires_at": (NOW + timedelta(hours=1)).replace(tzinfo=None),
            },
        )

    report = StorageReconciler(
        repository=ingest_case.repository,
        store=ingest_case.store,
        orphan_age=timedelta(hours=24),
        clock=lambda: NOW,
    ).reconcile_orphans()

    assert report.skipped_valid_lease == (stored.storage_key,)
    assert (ingest_case.store.root / stored.storage_key).is_file()


def test_old_expired_orphan_is_quarantined_once(
    ingest_case: IngestCase,
) -> None:
    staged = ingest_case.store.write_stream(uuid4(), BytesIO(b"expired orphan"))
    stored = ingest_case.store.promote(staged)
    _age_object(ingest_case, stored.storage_key, timedelta(hours=25))

    reconciler = StorageReconciler(
        repository=ingest_case.repository,
        store=ingest_case.store,
        orphan_age=timedelta(hours=24),
        clock=lambda: NOW,
    )
    first = reconciler.reconcile_orphans()
    second = reconciler.reconcile_orphans()

    assert tuple(item.storage_key for item in first.quarantined) == (
        stored.storage_key,
    )
    assert second.quarantined == ()
    assert not (ingest_case.store.root / stored.storage_key).exists()


def test_expired_lease_quarantines_abandoned_temporary_upload(
    ingest_case: IngestCase,
) -> None:
    token = uuid4()
    staged = ingest_case.store.write_stream(
        token,
        BytesIO(b"process stopped before promotion"),
    )
    timestamp = (NOW - timedelta(hours=25)).timestamp()
    os.utime(staged.path, (timestamp, timestamp))
    with ingest_case.engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO file_ingest_leases (
                    lease_token, temporary_path, created_by_user_id,
                    status, expires_at
                ) VALUES (
                    :lease_token, :temporary_path, :user_id,
                    'active', :expires_at
                )
                """
            ),
            {
                "lease_token": token.bytes,
                "temporary_path": staged.temporary_key,
                "user_id": ingest_case.user_id,
                "expires_at": (NOW - timedelta(hours=1)).replace(tzinfo=None),
            },
        )

    report = StorageReconciler(
        repository=ingest_case.repository,
        store=ingest_case.store,
        orphan_age=timedelta(hours=24),
        clock=lambda: NOW,
    ).reconcile_orphans()

    assert tuple(item.temporary_key for item in report.quarantined_temporary) == (
        staged.temporary_key,
    )
    assert not staged.path.exists()
    assert report.quarantined_temporary[0].path.read_bytes() == (
        b"process stopped before promotion"
    )
    with ingest_case.engine.connect() as connection:
        status = connection.scalar(
            sa.text(
                "SELECT status FROM file_ingest_leases WHERE lease_token = :lease_token"
            ),
            {"lease_token": token.bytes},
        )
    assert status == "expired"


def test_two_concurrent_scans_quarantine_one_orphan(
    ingest_case: IngestCase,
) -> None:
    staged = ingest_case.store.write_stream(uuid4(), BytesIO(b"scan race"))
    stored = ingest_case.store.promote(staged)
    _age_object(ingest_case, stored.storage_key, timedelta(hours=25))
    barrier = Barrier(2)

    def scan() -> int:
        repository = cast(
            ReconcileRepository,
            _BarrierRepository(ingest_case.repository, barrier),
        )
        report = StorageReconciler(
            repository=repository,
            store=ingest_case.store,
            orphan_age=timedelta(hours=24),
            clock=lambda: NOW,
        ).reconcile_orphans()
        return len(report.quarantined)

    with ThreadPoolExecutor(max_workers=2) as executor:
        quarantined_counts = list(executor.map(lambda _index: scan(), range(2)))

    assert sum(quarantined_counts) == 1
    assert not (ingest_case.store.root / stored.storage_key).exists()


def test_scan_rechecks_reference_committed_after_candidate_selection(
    ingest_case: IngestCase,
) -> None:
    content = b"reference wins candidate race"
    staged = ingest_case.store.write_stream(uuid4(), BytesIO(content))
    stored = ingest_case.store.promote(staged)
    _age_object(ingest_case, stored.storage_key, timedelta(hours=25))
    candidate_selected = Event()
    continue_scan = Event()
    repository = cast(
        ReconcileRepository,
        _PausedLockRepository(
            ingest_case.repository,
            candidate_selected,
            continue_scan,
        ),
    )
    reconciler = StorageReconciler(
        repository=repository,
        store=ingest_case.store,
        orphan_age=timedelta(hours=24),
        clock=lambda: NOW,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(reconciler.reconcile_orphans)
        assert candidate_selected.wait(timeout=5)
        try:
            created = ingest_case.service().ingest(
                BytesIO(content),
                ingest_case.command(),
            )
            assert isinstance(created, ImportCreated)
        finally:
            continue_scan.set()
        report = future.result(timeout=5)

    assert report.skipped_reference == (stored.storage_key,)
    assert report.quarantined == ()
    assert (ingest_case.store.root / stored.storage_key).is_file()


def test_missing_reference_alert_is_idempotent_and_resolves_after_restore(
    ingest_case: IngestCase,
) -> None:
    content = b"referenced integrity"
    created = ingest_case.service().ingest(
        BytesIO(content),
        ingest_case.command(),
    )
    assert isinstance(created, ImportCreated)
    content_path = ingest_case.store.root / created.storage_key
    content_path.unlink()
    reconciler = StorageReconciler(
        repository=ingest_case.repository,
        store=ingest_case.store,
        orphan_age=timedelta(hours=24),
        clock=lambda: NOW,
    )

    assert reconciler.check_referenced_integrity()[created.raw_file_id] == "missing"
    assert reconciler.check_referenced_integrity()[created.raw_file_id] == "missing"
    restored = ingest_case.store.write_stream(uuid4(), BytesIO(content))
    ingest_case.store.promote(restored)
    assert reconciler.check_referenced_integrity()[created.raw_file_id] == "available"

    with ingest_case.engine.connect() as connection:
        rows = (
            connection.execute(
                sa.text(
                    """
                SELECT status, is_blocking, first_detected_at, resolved_at
                FROM raw_file_integrity_statuses
                WHERE raw_file_id = :raw_file_id
                """
                ),
                {"raw_file_id": created.raw_file_id},
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    assert rows[0]["status"] == "available"
    assert rows[0]["is_blocking"] == 0
    assert rows[0]["first_detected_at"] is not None
    assert rows[0]["resolved_at"] is not None


def test_older_integrity_scan_cannot_overwrite_newer_blocking_state(
    ingest_case: IngestCase,
) -> None:
    created = ingest_case.service().ingest(
        BytesIO(b"integrity ordering"),
        ingest_case.command(),
    )
    assert isinstance(created, ImportCreated)
    newer_check = NOW + timedelta(hours=2)
    older_check = NOW + timedelta(hours=1)

    ingest_case.repository.record_integrity_status(
        raw_file_id=created.raw_file_id,
        status="missing",
        checked_at=newer_check,
    )
    ingest_case.repository.record_integrity_status(
        raw_file_id=created.raw_file_id,
        status="available",
        checked_at=older_check,
    )

    with ingest_case.engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    """
                SELECT status, last_checked_at, resolved_at
                FROM raw_file_integrity_statuses
                WHERE raw_file_id = :raw_file_id
                """
                ),
                {"raw_file_id": created.raw_file_id},
            )
            .mappings()
            .one()
        )
    assert row["status"] == "missing"
    assert row["last_checked_at"] == newer_check.replace(tzinfo=None)
    assert row["resolved_at"] is None


def test_repeated_healthy_scan_preserves_the_actual_recovery_time(
    ingest_case: IngestCase,
) -> None:
    created = ingest_case.service().ingest(
        BytesIO(b"stable recovery timestamp"),
        ingest_case.command(),
    )
    assert isinstance(created, ImportCreated)
    detected_at = NOW + timedelta(minutes=1)
    recovered_at = NOW + timedelta(minutes=2)
    later_healthy_check = NOW + timedelta(minutes=3)

    ingest_case.repository.record_integrity_status(
        raw_file_id=created.raw_file_id,
        status="hash_mismatch",
        checked_at=detected_at,
    )
    ingest_case.repository.record_integrity_status(
        raw_file_id=created.raw_file_id,
        status="available",
        checked_at=recovered_at,
    )
    ingest_case.repository.record_integrity_status(
        raw_file_id=created.raw_file_id,
        status="available",
        checked_at=later_healthy_check,
    )

    with ingest_case.engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    """
                SELECT status, last_checked_at, resolved_at
                FROM raw_file_integrity_statuses
                WHERE raw_file_id = :raw_file_id
                """
                ),
                {"raw_file_id": created.raw_file_id},
            )
            .mappings()
            .one()
        )
    assert row["status"] == "available"
    assert row["last_checked_at"] == later_healthy_check.replace(tzinfo=None)
    assert row["resolved_at"] == recovered_at.replace(tzinfo=None)
