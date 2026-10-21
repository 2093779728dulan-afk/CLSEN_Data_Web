"""Application boundary for atomic draft edits and review events."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from .types import (
    AddRowCommand,
    ChangeRowStateCommand,
    CreateNoteCommand,
    MarkReadyCommand,
    RestoreFieldValueCommand,
    ReturnToDraftCommand,
    ReviewIssueCommand,
    ReviewMutationResult,
    ReviseNoteCommand,
    SetFieldValueCommand,
)


class ReviewRepository(Protocol):
    """Persistence adapter owning one complete transaction per command."""

    def set_field_value(
        self,
        command: SetFieldValueCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult: ...

    def restore_field_value(
        self,
        command: RestoreFieldValueCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult: ...

    def add_row(
        self,
        command: AddRowCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult: ...

    def change_row_state(
        self,
        command: ChangeRowStateCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult: ...

    def create_note(
        self,
        command: CreateNoteCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult: ...

    def revise_note(
        self,
        command: ReviseNoteCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult: ...

    def review_issue(
        self,
        command: ReviewIssueCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult: ...

    def mark_ready(
        self,
        command: MarkReadyCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult: ...

    def return_to_draft(
        self,
        command: ReturnToDraftCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ReviewService:
    """Attach a single service timestamp and delegate each atomic operation."""

    def __init__(
        self,
        *,
        repository: ReviewRepository,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def set_field_value(self, command: SetFieldValueCommand) -> ReviewMutationResult:
        return self._repository.set_field_value(command, occurred_at=self._clock())

    def restore_field_value(
        self,
        command: RestoreFieldValueCommand,
    ) -> ReviewMutationResult:
        return self._repository.restore_field_value(
            command,
            occurred_at=self._clock(),
        )

    def add_row(self, command: AddRowCommand) -> ReviewMutationResult:
        return self._repository.add_row(command, occurred_at=self._clock())

    def change_row_state(
        self,
        command: ChangeRowStateCommand,
    ) -> ReviewMutationResult:
        return self._repository.change_row_state(
            command,
            occurred_at=self._clock(),
        )

    def create_note(self, command: CreateNoteCommand) -> ReviewMutationResult:
        return self._repository.create_note(command, occurred_at=self._clock())

    def revise_note(self, command: ReviseNoteCommand) -> ReviewMutationResult:
        return self._repository.revise_note(command, occurred_at=self._clock())

    def review_issue(self, command: ReviewIssueCommand) -> ReviewMutationResult:
        return self._repository.review_issue(command, occurred_at=self._clock())

    def mark_ready(self, command: MarkReadyCommand) -> ReviewMutationResult:
        return self._repository.mark_ready(command, occurred_at=self._clock())

    def return_to_draft(
        self,
        command: ReturnToDraftCommand,
    ) -> ReviewMutationResult:
        return self._repository.return_to_draft(
            command,
            occurred_at=self._clock(),
        )
