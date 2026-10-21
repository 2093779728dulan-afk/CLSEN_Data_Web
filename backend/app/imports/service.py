"""Idempotent orchestration across MySQL and immutable local storage."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.imports.storage import (
    BinaryReadStream,
    LocalContentStore,
    StagedContent,
    StoredContent,
)
from app.imports.types import (
    CommitOutcomeUnknown,
    DuplicateBatchConflict,
    FinalizedImport,
    ImportCommand,
    ImportCreated,
    IngestResult,
    RecoveredImport,
)

_LOGGER = logging.getLogger(__name__)


class IngestRepository(Protocol):
    """Database operations required by the ingest state machine."""

    def create_lease(
        self,
        *,
        lease_token: UUID,
        temporary_path: str,
        created_by_user_id: int,
        expires_at: datetime,
    ) -> None: ...

    def renew_active_lease(
        self,
        *,
        lease_token: UUID,
        expires_at: datetime,
        checked_at: datetime,
    ) -> None: ...

    def digest_lock(self, sha256_hex: str) -> AbstractContextManager[Any]: ...

    def mark_committing(
        self,
        connection: Any,
        *,
        lease_token: UUID,
        staged: StagedContent,
        expires_at: datetime,
        checked_at: datetime,
    ) -> None: ...

    def finalize_import(
        self,
        connection: Any,
        *,
        lease_token: UUID,
        command: ImportCommand,
        stored: StoredContent,
        completed_at: datetime,
    ) -> FinalizedImport: ...

    def recover_completed(self, lease_token: UUID) -> RecoveredImport | None: ...

    def mark_failed(
        self,
        *,
        lease_token: UUID,
        failed_at: datetime,
    ) -> None: ...


class ContentStore(Protocol):
    def assert_ready(self) -> None: ...

    def write_stream(
        self,
        lease_token: UUID,
        source: BinaryReadStream,
    ) -> StagedContent: ...

    def promote(self, staged: StagedContent) -> StoredContent: ...

    def discard_staged(self, staged: StagedContent) -> None: ...


class _RenewingReader:
    """Renew an active lease as the content store pulls bounded chunks."""

    def __init__(
        self,
        source: BinaryReadStream,
        *,
        renew: Callable[[], None],
        interval: timedelta,
        clock: Callable[[], datetime],
    ) -> None:
        self._source = source
        self._renew = renew
        self._interval = interval
        self._clock = clock
        self._next_renewal = clock() + interval

    def read(self, size: int = -1) -> bytes:
        content = self._source.read(size)
        now = self._clock()
        if content and now >= self._next_renewal:
            self._renew()
            self._next_renewal = now + self._interval
        return content


def _utc_now() -> datetime:
    return datetime.now(UTC)


class IngestService:
    """Coordinate leases, immutable publication, and one import transaction."""

    def __init__(
        self,
        *,
        repository: IngestRepository,
        store: ContentStore | LocalContentStore,
        lease_ttl: timedelta,
        lease_renew_interval: timedelta,
        clock: Callable[[], datetime] = _utc_now,
        token_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        if lease_renew_interval <= timedelta(0):
            raise ValueError("lease_renew_interval must be positive")
        if lease_renew_interval >= lease_ttl:
            raise ValueError("lease_renew_interval must be shorter than lease_ttl")
        self._repository = repository
        self._store = store
        self._lease_ttl = lease_ttl
        self._lease_renew_interval = lease_renew_interval
        self._clock = clock
        self._token_factory = token_factory

    def ingest(self, source: BinaryReadStream, command: ImportCommand) -> IngestResult:
        """Store one upload and create at most one batch for its content."""

        self._store.assert_ready()
        lease_token = self._token_factory()
        now = self._clock()
        self._repository.create_lease(
            lease_token=lease_token,
            temporary_path=f".ingest/{lease_token}.part",
            created_by_user_id=command.created_by_user_id,
            expires_at=now + self._lease_ttl,
        )

        renewing_source = _RenewingReader(
            source,
            renew=lambda: self._renew_lease(lease_token),
            interval=self._lease_renew_interval,
            clock=self._clock,
        )
        try:
            staged = self._store.write_stream(lease_token, renewing_source)
        except BaseException:
            self._best_effort_mark_failed(lease_token)
            raise

        content_published = False
        try:
            with self._repository.digest_lock(staged.sha256_hex) as connection:
                checked_at = self._clock()
                self._repository.mark_committing(
                    connection,
                    lease_token=lease_token,
                    staged=staged,
                    expires_at=checked_at + self._lease_ttl,
                    checked_at=checked_at,
                )
                stored = self._store.promote(staged)
                content_published = True
                finalized = self._repository.finalize_import(
                    connection,
                    lease_token=lease_token,
                    command=command,
                    stored=stored,
                    completed_at=self._clock(),
                )
        except CommitOutcomeUnknown as error:
            try:
                recovered = self._repository.recover_completed(lease_token)
            except Exception as recovery_error:
                _LOGGER.exception(
                    "Could not recover an uncertain ingest commit",
                    extra={"lease_token": str(lease_token)},
                )
                raise error from recovery_error
            if recovered is not None:
                return recovered
            raise
        except BaseException:
            if not content_published:
                self._best_effort_discard_staged(staged, lease_token=lease_token)
                self._best_effort_mark_failed(lease_token)
            raise

        return self._result_from_finalization(finalized, stored)

    def _renew_lease(self, lease_token: UUID) -> None:
        checked_at = self._clock()
        self._repository.renew_active_lease(
            lease_token=lease_token,
            expires_at=checked_at + self._lease_ttl,
            checked_at=checked_at,
        )

    def _best_effort_mark_failed(self, lease_token: UUID) -> None:
        try:
            self._repository.mark_failed(
                lease_token=lease_token,
                failed_at=self._clock(),
            )
        except BaseException:
            _LOGGER.exception(
                "Could not mark failed file ingest lease",
                extra={"lease_token": str(lease_token)},
            )

    def _best_effort_discard_staged(
        self,
        staged: StagedContent,
        *,
        lease_token: UUID,
    ) -> None:
        try:
            self._store.discard_staged(staged)
        except BaseException:
            _LOGGER.exception(
                "Could not discard staged content after a failed ingest",
                extra={"lease_token": str(lease_token)},
            )

    @staticmethod
    def _result_from_finalization(
        finalized: FinalizedImport,
        stored: StoredContent,
    ) -> ImportCreated | DuplicateBatchConflict:
        if not finalized.created:
            return DuplicateBatchConflict(
                existing_batch_id=finalized.batch_id,
                raw_file_id=finalized.raw_file_id,
                sha256_hex=stored.sha256_hex,
            )
        return ImportCreated(
            raw_file_id=finalized.raw_file_id,
            batch_id=finalized.batch_id,
            sha256_hex=stored.sha256_hex,
            storage_key=stored.storage_key,
            size_bytes=stored.size_bytes,
            content_reused=stored.reused,
        )
