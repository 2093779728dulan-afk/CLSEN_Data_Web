from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import UUID

import pytest
from app.imports.service import IngestService
from app.imports.storage import BinaryReadStream, StagedContent, StoredContent
from app.imports.types import (
    CommitOutcomeUnknown,
    DuplicateBatchConflict,
    FinalizedImport,
    ImportCommand,
    ImportCreated,
    IngestCommitFailed,
    RecoveredImport,
)

NOW = datetime(2026, 8, 7, 4, 0, tzinfo=UTC)


class _ConnectionContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class RecordingRepository:
    def __init__(self, finalized: FinalizedImport) -> None:
        self.finalized = finalized
        self.calls: list[str] = []
        self.finalize_error: Exception | None = None
        self.recovered: RecoveredImport | None = None
        self.lock_error: Exception | None = None

    def create_lease(self, **_kwargs: Any) -> None:
        self.calls.append("create_lease")

    def renew_active_lease(self, **_kwargs: Any) -> None:
        self.calls.append("renew_active_lease")

    @contextmanager
    def digest_lock(self, _sha256_hex: str) -> Iterator[object]:
        self.calls.append("acquire_digest_lock")
        if self.lock_error is not None:
            raise self.lock_error
        try:
            yield object()
        finally:
            self.calls.append("release_digest_lock")

    def mark_committing(
        self,
        _connection: object,
        *,
        lease_token: UUID,
        staged: StagedContent,
        expires_at: datetime,
        checked_at: datetime,
    ) -> None:
        del lease_token, staged, expires_at, checked_at
        self.calls.append("mark_committing")

    def finalize_import(
        self,
        _connection: object,
        *,
        lease_token: UUID,
        command: ImportCommand,
        stored: StoredContent,
        completed_at: datetime,
    ) -> FinalizedImport:
        del lease_token, command, stored, completed_at
        self.calls.append("finalize_import")
        if self.finalize_error is not None:
            raise self.finalize_error
        return self.finalized

    def recover_completed(self, _lease_token: UUID) -> RecoveredImport | None:
        self.calls.append("recover_completed")
        return self.recovered

    def mark_failed(self, **_kwargs: Any) -> None:
        self.calls.append("mark_failed")


class RecordingStore:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.ready_error: Exception | None = None
        self.discard_error: Exception | None = None
        self.staged = StagedContent(
            lease_token=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            temporary_key=".ingest/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.part",
            path=Path("ignored.part"),
            sha256_hex="ab" * 32,
            size_bytes=7,
        )
        self.stored = StoredContent(
            storage_key=f"sha256/ab/{'ab' * 32}",
            sha256_hex="ab" * 32,
            size_bytes=7,
            reused=False,
        )

    def assert_ready(self) -> None:
        self.calls.append("assert_ready")
        if self.ready_error is not None:
            raise self.ready_error

    def write_stream(
        self,
        lease_token: UUID,
        source: BinaryReadStream,
    ) -> StagedContent:
        self.calls.append("write_stream")
        source.read()
        return StagedContent(
            lease_token=lease_token,
            temporary_key=f".ingest/{lease_token}.part",
            path=self.staged.path,
            sha256_hex=self.staged.sha256_hex,
            size_bytes=self.staged.size_bytes,
        )

    def promote(self, _staged: StagedContent) -> StoredContent:
        self.calls.append("promote")
        return self.stored

    def discard_staged(self, _staged: StagedContent) -> None:
        self.calls.append("discard_staged")
        if self.discard_error is not None:
            raise self.discard_error


def _command() -> ImportCommand:
    return ImportCommand(
        original_filename="business.csv",
        media_type="text/csv",
        created_by_user_id=9,
        site_config_version_id=1,
        report_date=date(2026, 8, 6),
    )


def _service(
    repository: RecordingRepository,
    store: RecordingStore,
) -> IngestService:
    return IngestService(
        repository=repository,
        store=store,
        lease_ttl=timedelta(minutes=30),
        lease_renew_interval=timedelta(minutes=5),
        clock=lambda: NOW,
        token_factory=lambda: UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )


def test_storage_configuration_is_checked_before_lease_creation() -> None:
    repository = RecordingRepository(FinalizedImport(1, 2, created=True))
    store = RecordingStore()
    store.ready_error = ValueError("different devices")

    with pytest.raises(ValueError, match="different devices"):
        _service(repository, store).ingest(BytesIO(b"content"), _command())

    assert store.calls == ["assert_ready"]
    assert repository.calls == []


def test_duplicate_upload_returns_existing_batch_without_creating_another() -> None:
    repository = RecordingRepository(FinalizedImport(11, 22, created=False))
    store = RecordingStore()
    store.stored = StoredContent(
        storage_key=store.stored.storage_key,
        sha256_hex=store.stored.sha256_hex,
        size_bytes=store.stored.size_bytes,
        reused=True,
    )

    result = _service(repository, store).ingest(BytesIO(b"content"), _command())

    assert result == DuplicateBatchConflict(
        existing_batch_id=22,
        raw_file_id=11,
        sha256_hex="ab" * 32,
    )
    assert repository.calls == [
        "create_lease",
        "acquire_digest_lock",
        "mark_committing",
        "finalize_import",
        "release_digest_lock",
    ]
    assert store.calls == ["assert_ready", "write_stream", "promote"]


def test_matching_unreferenced_content_can_create_the_first_batch() -> None:
    repository = RecordingRepository(FinalizedImport(31, 42, created=True))
    store = RecordingStore()
    store.stored = StoredContent(
        storage_key=store.stored.storage_key,
        sha256_hex=store.stored.sha256_hex,
        size_bytes=store.stored.size_bytes,
        reused=True,
    )

    result = _service(repository, store).ingest(BytesIO(b"content"), _command())

    assert result == ImportCreated(
        raw_file_id=31,
        batch_id=42,
        sha256_hex="ab" * 32,
        storage_key=f"sha256/ab/{'ab' * 32}",
        size_bytes=7,
        content_reused=True,
    )


def test_known_finalize_failure_leaves_object_and_committing_lease() -> None:
    repository = RecordingRepository(FinalizedImport(1, 2, created=True))
    repository.finalize_error = IngestCommitFailed("rolled back")
    store = RecordingStore()

    with pytest.raises(IngestCommitFailed, match="rolled back"):
        _service(repository, store).ingest(BytesIO(b"content"), _command())

    assert "mark_committing" in repository.calls
    assert "mark_failed" not in repository.calls
    assert "discard_staged" not in store.calls


def test_digest_lock_failure_discards_staged_content_and_fails_lease() -> None:
    repository = RecordingRepository(FinalizedImport(1, 2, created=True))
    repository.lock_error = TimeoutError("digest lock timeout")
    store = RecordingStore()

    with pytest.raises(TimeoutError, match="digest lock timeout"):
        _service(repository, store).ingest(BytesIO(b"content"), _command())

    assert repository.calls[-1] == "mark_failed"
    assert store.calls[-1] == "discard_staged"


def test_staged_cleanup_failure_does_not_hide_the_primary_ingest_error() -> None:
    repository = RecordingRepository(FinalizedImport(1, 2, created=True))
    repository.lock_error = TimeoutError("digest lock timeout")
    store = RecordingStore()
    store.discard_error = OSError("injected staged cleanup failure")

    with pytest.raises(TimeoutError, match="digest lock timeout"):
        _service(repository, store).ingest(BytesIO(b"content"), _command())

    assert store.calls[-1] == "discard_staged"
    assert repository.calls[-1] == "mark_failed"


def test_unknown_commit_outcome_recovers_completed_lease() -> None:
    repository = RecordingRepository(FinalizedImport(1, 2, created=True))
    repository.finalize_error = CommitOutcomeUnknown("connection lost")
    repository.recovered = RecoveredImport(raw_file_id=51, batch_id=62)
    store = RecordingStore()

    result = _service(repository, store).ingest(BytesIO(b"content"), _command())

    assert result == RecoveredImport(raw_file_id=51, batch_id=62)
    assert repository.calls[-2:] == ["release_digest_lock", "recover_completed"]


def test_unknown_commit_outcome_without_completed_lease_is_reported() -> None:
    repository = RecordingRepository(FinalizedImport(1, 2, created=True))
    repository.finalize_error = CommitOutcomeUnknown("connection lost")
    store = RecordingStore()

    with pytest.raises(CommitOutcomeUnknown, match="connection lost"):
        _service(repository, store).ingest(BytesIO(b"content"), _command())

    assert "recover_completed" in repository.calls
