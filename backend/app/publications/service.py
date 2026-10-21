"""Application boundary for publication and published-date move commands."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from .commands import (
    CreatePublishedMoveRevisionCommand,
    CreateRevisionCommand,
    FinalizePublishedMoveCommand,
    PublishCommand,
    RollbackCommand,
    UndoPublishedMoveCommand,
)
from .results import DraftCommandResult, PublicationCommandResult


class PublicationRepository(Protocol):
    """Persistence adapter owning one complete transaction per command."""

    def publish(
        self,
        command: PublishCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult: ...

    def create_revision(
        self,
        command: CreateRevisionCommand,
        *,
        occurred_at: datetime,
    ) -> DraftCommandResult: ...

    def rollback(
        self,
        command: RollbackCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult: ...

    def create_published_move_revision(
        self,
        command: CreatePublishedMoveRevisionCommand,
        *,
        occurred_at: datetime,
    ) -> DraftCommandResult: ...

    def finalize_published_move(
        self,
        command: FinalizePublishedMoveCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult: ...

    def undo_published_move(
        self,
        command: UndoPublishedMoveCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PublicationService:
    """Attach one service timestamp and delegate each atomic publication write."""

    def __init__(
        self,
        *,
        repository: PublicationRepository,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def publish(self, command: PublishCommand) -> PublicationCommandResult:
        return self._repository.publish(command, occurred_at=self._clock())

    def create_revision(self, command: CreateRevisionCommand) -> DraftCommandResult:
        return self._repository.create_revision(command, occurred_at=self._clock())

    def rollback(self, command: RollbackCommand) -> PublicationCommandResult:
        return self._repository.rollback(command, occurred_at=self._clock())

    def create_published_move_revision(
        self,
        command: CreatePublishedMoveRevisionCommand,
    ) -> DraftCommandResult:
        return self._repository.create_published_move_revision(
            command,
            occurred_at=self._clock(),
        )

    def finalize_published_move(
        self,
        command: FinalizePublishedMoveCommand,
    ) -> PublicationCommandResult:
        return self._repository.finalize_published_move(
            command,
            occurred_at=self._clock(),
        )

    def undo_published_move(
        self,
        command: UndoPublishedMoveCommand,
    ) -> PublicationCommandResult:
        return self._repository.undo_published_move(
            command,
            occurred_at=self._clock(),
        )
