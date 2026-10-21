"""Coarse application boundary for atomic daily-draft transactions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from .types import (
    DiscardDraftCommand,
    DraftMutationResult,
    ForceRebuildDraftCommand,
    MaterializeBaselineCommand,
    ReassignUnpublishedDraftDateCommand,
)


class DatasetRepository(Protocol):
    """Atomic persistence operations; implementations own every transaction."""

    def materialize_baseline(
        self,
        command: MaterializeBaselineCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult: ...

    def force_rebuild_draft(
        self,
        command: ForceRebuildDraftCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult: ...

    def discard_active_draft(
        self,
        command: DiscardDraftCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult: ...

    def reassign_unpublished_draft_date(
        self,
        command: ReassignUnpublishedDraftDateCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DatasetService:
    """Attach one service timestamp and delegate each atomic write as a unit."""

    def __init__(
        self,
        *,
        repository: DatasetRepository,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def materialize_baseline(
        self,
        command: MaterializeBaselineCommand,
    ) -> DraftMutationResult:
        return self._repository.materialize_baseline(
            command,
            occurred_at=self._clock(),
        )

    def force_rebuild_draft(
        self,
        command: ForceRebuildDraftCommand,
    ) -> DraftMutationResult:
        return self._repository.force_rebuild_draft(
            command,
            occurred_at=self._clock(),
        )

    def discard_active_draft(
        self,
        command: DiscardDraftCommand,
    ) -> DraftMutationResult:
        return self._repository.discard_active_draft(
            command,
            occurred_at=self._clock(),
        )

    def reassign_unpublished_draft_date(
        self,
        command: ReassignUnpublishedDraftDateCommand,
    ) -> DraftMutationResult:
        return self._repository.reassign_unpublished_draft_date(
            command,
            occurred_at=self._clock(),
        )
