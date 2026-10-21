"""Application boundary for one atomic full validation run."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from .types import RunValidationCommand, ValidationRunReceipt


class ValidationRepository(Protocol):
    """Persistence adapter owning the complete evidence-read and write transaction."""

    def run_validation(
        self,
        command: RunValidationCommand,
        *,
        occurred_at: datetime,
    ) -> ValidationRunReceipt: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ValidationService:
    """Attach one service timestamp and delegate the atomic validation command."""

    def __init__(
        self,
        *,
        repository: ValidationRepository,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def run_validation(
        self,
        command: RunValidationCommand,
    ) -> ValidationRunReceipt:
        return self._repository.run_validation(command, occurred_at=self._clock())
