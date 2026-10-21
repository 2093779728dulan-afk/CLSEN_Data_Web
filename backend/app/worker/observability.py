"""Frozen Worker observability vocabulary and safe event construction."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from app.catalog.export_service import CatalogExportFinalizationError
from app.catalog.import_repository import CatalogImportRepositoryError
from app.catalog.return_dedup_repository import ReturnDedupError
from app.worker.outbox import OutboxError

QueueName = Literal[
    "return_dedup",
    "publication_outbox",
    "catalog_export",
    "catalog_import",
]
QueueOutcome = Literal["succeeded", "failed", "skipped"]

QUEUE_NAMES: tuple[QueueName, ...] = (
    "return_dedup",
    "publication_outbox",
    "catalog_export",
    "catalog_import",
)
HEARTBEAT_SECONDS = 10
STALE_SECONDS = 30
OFFLINE_SECONDS = 60
REFRESH_SECONDS = 15
RETENTION_DAYS = 30
RETENTION_DELETE_LIMIT = 500

_SAFE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}", flags=re.ASCII)
_SAFE_FAILURE_CODES = frozenset(
    {
        "catalog_export_error",
        "catalog_import_error",
        "consumer_state_write_failed",
        "consumer_unexpected_error",
        "heartbeat_write_failed",
        "publication_outbox_error",
        "retention_cleanup_failed",
        "return_dedup_error",
        "worker_registration_failed",
        "worker_stop_write_failed",
    }
)
_DOMAIN_FAILURES: dict[QueueName, tuple[type[BaseException], str]] = {
    "return_dedup": (ReturnDedupError, "return_dedup_error"),
    "publication_outbox": (OutboxError, "publication_outbox_error"),
    "catalog_export": (CatalogExportFinalizationError, "catalog_export_error"),
    "catalog_import": (CatalogImportRepositoryError, "catalog_import_error"),
}


@dataclass(frozen=True, slots=True)
class PollOutcome:
    result_code: str
    did_work: bool

    def __post_init__(self) -> None:
        _validate_code(self.result_code, label="result code")


class WorkerTelemetry(Protocol):
    def can_claim(self) -> bool: ...

    def poll_started(self, queue_name: QueueName) -> None: ...

    def poll_succeeded(self, queue_name: QueueName, outcome: PollOutcome) -> None: ...

    def poll_failed(self, queue_name: QueueName, failure_code: str) -> None: ...


def _validate_code(value: str, *, label: str) -> None:
    if _SAFE_CODE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a closed safe code")


def safe_failure_code(error: BaseException, queue_name: QueueName) -> str:
    """Map domain errors to a closed code without retaining exception content."""

    exception_type, code = _DOMAIN_FAILURES[queue_name]
    if isinstance(error, exception_type):
        return code
    return "consumer_unexpected_error"


def validate_safe_code(value: str, *, label: str) -> None:
    """Reject values that could contain payload or credential text."""

    _validate_code(value, label=label)


def worker_log_extra(
    *,
    event: str,
    instance_id: UUID,
    queue_name: QueueName | None,
    outcome: QueueOutcome,
    duration_ms: float,
    attempt: int,
    failure_code: str | None,
) -> dict[str, object]:
    """Return the complete allowlisted fields for one Worker log event."""

    _validate_code(event, label="event")
    if not math.isfinite(duration_ms) or duration_ms < 0:
        raise ValueError("duration must be a non-negative finite number")
    if attempt < 0:
        raise ValueError("attempt must not be negative")
    if failure_code is not None:
        _validate_code(failure_code, label="failure code")
        if failure_code not in _SAFE_FAILURE_CODES:
            raise ValueError("failure code is not allowlisted")
    return {
        "event": event,
        "worker_instance_id": instance_id.hex,
        "queue_name": queue_name,
        "outcome": outcome,
        "duration_ms": round(duration_ms, 3),
        "attempt": attempt,
        "failure_code": failure_code,
    }


__all__ = (
    "HEARTBEAT_SECONDS",
    "OFFLINE_SECONDS",
    "QUEUE_NAMES",
    "REFRESH_SECONDS",
    "RETENTION_DAYS",
    "RETENTION_DELETE_LIMIT",
    "STALE_SECONDS",
    "PollOutcome",
    "QueueName",
    "QueueOutcome",
    "WorkerTelemetry",
    "safe_failure_code",
    "validate_safe_code",
    "worker_log_extra",
)
