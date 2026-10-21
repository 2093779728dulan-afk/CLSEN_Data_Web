"""Immutable domain contracts for the batch-review workflow."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from app.imports.types import ReportType
from app.parsers.types import SupportedEncoding

type TargetKey = tuple[date, ReportType]


class BatchReviewError(RuntimeError):
    """Base class for expected batch-review failures."""


class BatchReviewNotFound(BatchReviewError):
    """The run or item is not visible to the current site."""


class BatchReviewPermissionDenied(BatchReviewError):
    """The actor cannot read or mutate this batch-review run."""


class BatchReviewRevisionConflict(BatchReviewError):
    """The run changed after the client read it."""


class BatchReviewOperationConflict(BatchReviewError):
    """An idempotency key is bound to different command semantics."""


class BatchReviewBusy(BatchReviewError):
    """A non-expired item lease already owns the requested work."""


class BatchReviewOutcomeUnknown(BatchReviewError):
    """Commit acknowledgement was lost; callers must reload server state."""


class BatchReviewStateConflict(BatchReviewError):
    """A requested run or item transition is invalid."""


class BatchReviewReasonCode(StrEnum):
    RECOGNITION_UNCERTAIN = "recognition_uncertain"
    SOURCE_UNAVAILABLE = "source_unavailable"
    BATCH_STATE_CONFLICT = "batch_state_conflict"
    DUPLICATE_TARGET_IN_RUN = "duplicate_target_in_run"
    ACTIVE_DRAFT_EXISTS = "active_draft_exists"
    PUBLICATION_EXISTS = "publication_exists"
    ALREADY_MATERIALIZED = "already_materialized"
    PERMISSION_DENIED = "permission_denied"
    VALIDATION_WARNING = "validation_warning"
    VALIDATION_BLOCKING = "validation_blocking"
    TARGET_CHANGED = "target_changed"
    RETRYABLE_FAILURE = "retryable_failure"
    OUTCOME_UNKNOWN = "outcome_unknown"


class BatchReviewRunStatus(StrEnum):
    PREVIEW = "preview"
    CONFIRMED = "confirmed"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    COMPLETED_WITH_EXCEPTIONS = "completed_with_exceptions"


class BatchReviewItemStatus(StrEnum):
    ELIGIBLE = "eligible"
    SKIPPED = "skipped"
    QUEUED = "queued"
    PARSING = "parsing"
    MATERIALIZING = "materializing"
    VALIDATING = "validating"
    READY_FOR_PUBLISH = "ready_for_publish"
    MANUAL_REVIEW = "manual_review"
    FAILED = "failed"


_RUN_TRANSITIONS: dict[BatchReviewRunStatus, frozenset[BatchReviewRunStatus]] = {
    BatchReviewRunStatus.PREVIEW: frozenset({BatchReviewRunStatus.CONFIRMED}),
    BatchReviewRunStatus.CONFIRMED: frozenset({BatchReviewRunStatus.RUNNING}),
    BatchReviewRunStatus.RUNNING: frozenset(
        {
            BatchReviewRunStatus.PAUSED,
            BatchReviewRunStatus.COMPLETED,
            BatchReviewRunStatus.COMPLETED_WITH_EXCEPTIONS,
        }
    ),
    BatchReviewRunStatus.PAUSED: frozenset({BatchReviewRunStatus.RUNNING}),
    BatchReviewRunStatus.COMPLETED: frozenset(),
    BatchReviewRunStatus.COMPLETED_WITH_EXCEPTIONS: frozenset(),
}

_ITEM_TRANSITIONS: dict[BatchReviewItemStatus, frozenset[BatchReviewItemStatus]] = {
    BatchReviewItemStatus.ELIGIBLE: frozenset(
        {
            BatchReviewItemStatus.SKIPPED,
            BatchReviewItemStatus.QUEUED,
            BatchReviewItemStatus.MANUAL_REVIEW,
        }
    ),
    BatchReviewItemStatus.SKIPPED: frozenset(),
    BatchReviewItemStatus.QUEUED: frozenset(
        {
            BatchReviewItemStatus.PARSING,
            BatchReviewItemStatus.MANUAL_REVIEW,
            BatchReviewItemStatus.FAILED,
        }
    ),
    BatchReviewItemStatus.PARSING: frozenset(
        {
            BatchReviewItemStatus.MATERIALIZING,
            BatchReviewItemStatus.MANUAL_REVIEW,
            BatchReviewItemStatus.FAILED,
        }
    ),
    BatchReviewItemStatus.MATERIALIZING: frozenset(
        {
            BatchReviewItemStatus.VALIDATING,
            BatchReviewItemStatus.MANUAL_REVIEW,
            BatchReviewItemStatus.FAILED,
        }
    ),
    BatchReviewItemStatus.VALIDATING: frozenset(
        {
            BatchReviewItemStatus.READY_FOR_PUBLISH,
            BatchReviewItemStatus.MANUAL_REVIEW,
            BatchReviewItemStatus.FAILED,
        }
    ),
    BatchReviewItemStatus.READY_FOR_PUBLISH: frozenset(),
    BatchReviewItemStatus.MANUAL_REVIEW: frozenset(),
    BatchReviewItemStatus.FAILED: frozenset(),
}


def _positive(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be positive")


def _nonnegative(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must not be negative")


def _uuid4(value: UUID, field_name: str = "operation_token") -> None:
    if not isinstance(value, UUID) or value.version != 4:
        raise ValueError(f"{field_name} must be a UUID v4")


def _normalised(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value.strip()


def _positive_unique(values: tuple[int, ...], field_name: str) -> tuple[int, ...]:
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    for value in values:
        _positive(value, field_name)
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must contain unique IDs")
    return tuple(sorted(values))


def canonical_digest(payload: object) -> bytes:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).digest()


@dataclass(frozen=True, slots=True)
class BatchReviewCandidate:
    batch_id: int
    site_id: int
    filename: str
    report_date: date | None
    report_type: ReportType | None
    encoding: SupportedEncoding | None
    recognition_status: str
    source_available: bool
    batch_status: str
    already_materialized: bool
    actor_roles: frozenset[str]

    def __post_init__(self) -> None:
        _positive(self.batch_id, "batch_id")
        _positive(self.site_id, "site_id")
        object.__setattr__(self, "filename", _normalised(self.filename, "filename"))
        object.__setattr__(
            self,
            "recognition_status",
            _normalised(self.recognition_status, "recognition_status"),
        )
        object.__setattr__(
            self, "batch_status", _normalised(self.batch_status, "batch_status")
        )
        if self.report_type not in {None, "business_report", "return_report"}:
            raise ValueError("unsupported report_type")
        if self.report_date is not None and (
            not isinstance(self.report_date, date)
            or isinstance(self.report_date, datetime)
        ):
            raise ValueError("report_date must be a date")
        if self.encoding not in {None, "utf-8-sig", "utf-8", "windows-1252"}:
            raise ValueError("unsupported encoding")

    @property
    def target_key(self) -> TargetKey | None:
        if self.report_date is None or self.report_type is None:
            return None
        return (self.report_date, self.report_type)

    @property
    def manual_review_url(self) -> str:
        if self.report_date is None:
            return "/review"
        suffix = "" if self.report_type is None else f"?report_type={self.report_type}"
        return f"/review/{self.report_date.isoformat()}{suffix}"


@dataclass(frozen=True, slots=True)
class BatchReviewTargetState:
    active_draft_exists: bool = False
    publication_exists: bool = False


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    eligible: bool
    target_key: TargetKey | None
    reason_code: BatchReviewReasonCode | None
    reason_message: str
    manual_review_url: str


@dataclass(frozen=True, slots=True)
class CreatePreflightCommand:
    site_id: int
    actor_user_id: int
    actor_roles: frozenset[str]
    batch_ids: tuple[int, ...]
    operation_token: UUID

    def __post_init__(self) -> None:
        _positive(self.site_id, "site_id")
        _positive(self.actor_user_id, "actor_user_id")
        object.__setattr__(self, "actor_roles", frozenset(self.actor_roles))
        object.__setattr__(
            self, "batch_ids", _positive_unique(self.batch_ids, "batch_ids")
        )
        _uuid4(self.operation_token)

    @property
    def operation_digest(self) -> bytes:
        return canonical_digest(
            {
                "kind": "create_preflight",
                "site_id": self.site_id,
                "actor_user_id": self.actor_user_id,
                "batch_ids": self.batch_ids,
            }
        )


@dataclass(frozen=True, slots=True)
class ConfirmBatchReviewCommand:
    run_id: int
    site_id: int
    actor_user_id: int
    expected_revision: int
    selected_item_ids: tuple[int, ...]
    confirmation_accepted: bool
    confirmation_statement_version: str
    operation_token: UUID

    def __post_init__(self) -> None:
        _positive(self.run_id, "run_id")
        _positive(self.site_id, "site_id")
        _positive(self.actor_user_id, "actor_user_id")
        _nonnegative(self.expected_revision, "expected_revision")
        object.__setattr__(
            self,
            "selected_item_ids",
            _positive_unique(self.selected_item_ids, "selected_item_ids"),
        )
        if self.confirmation_accepted is not True:
            raise ValueError("confirmation must be accepted")
        object.__setattr__(
            self,
            "confirmation_statement_version",
            _normalised(
                self.confirmation_statement_version,
                "confirmation statement version",
            ),
        )
        _uuid4(self.operation_token)

    @property
    def operation_digest(self) -> bytes:
        return canonical_digest(
            {
                "kind": "confirm",
                "run_id": self.run_id,
                "site_id": self.site_id,
                "actor_user_id": self.actor_user_id,
                "expected_revision": self.expected_revision,
                "selected_item_ids": self.selected_item_ids,
                "confirmation_statement_version": self.confirmation_statement_version,
            }
        )


@dataclass(frozen=True, slots=True)
class AdvanceBatchReviewItemCommand:
    run_id: int
    item_id: int
    site_id: int
    actor_user_id: int
    operation_token: UUID

    def __post_init__(self) -> None:
        for field_name in ("run_id", "item_id", "site_id", "actor_user_id"):
            _positive(getattr(self, field_name), field_name)
        _uuid4(self.operation_token)

    @property
    def operation_digest(self) -> bytes:
        return canonical_digest(
            {
                "kind": "advance_item",
                "run_id": self.run_id,
                "item_id": self.item_id,
                "site_id": self.site_id,
                "actor_user_id": self.actor_user_id,
            }
        )


@dataclass(frozen=True, slots=True)
class ChangeBatchReviewRunStateCommand:
    run_id: int
    site_id: int
    actor_user_id: int
    expected_revision: int
    action: Literal["pause", "resume"]
    operation_token: UUID

    def __post_init__(self) -> None:
        for field_name in ("run_id", "site_id", "actor_user_id"):
            _positive(getattr(self, field_name), field_name)
        _nonnegative(self.expected_revision, "expected_revision")
        if self.action not in {"pause", "resume"}:
            raise ValueError("unsupported run state action")
        _uuid4(self.operation_token)

    @property
    def operation_digest(self) -> bytes:
        return canonical_digest(
            {
                "kind": self.action,
                "run_id": self.run_id,
                "site_id": self.site_id,
                "actor_user_id": self.actor_user_id,
                "expected_revision": self.expected_revision,
            }
        )


@dataclass(frozen=True, slots=True)
class RetryBatchReviewItemCommand:
    run_id: int
    item_id: int
    site_id: int
    actor_user_id: int
    expected_revision: int
    operation_token: UUID

    def __post_init__(self) -> None:
        for field_name in ("run_id", "item_id", "site_id", "actor_user_id"):
            _positive(getattr(self, field_name), field_name)
        _nonnegative(self.expected_revision, "expected_revision")
        _uuid4(self.operation_token)

    @property
    def operation_digest(self) -> bytes:
        return canonical_digest(
            {
                "kind": "retry_item",
                "run_id": self.run_id,
                "item_id": self.item_id,
                "site_id": self.site_id,
                "actor_user_id": self.actor_user_id,
                "expected_revision": self.expected_revision,
            }
        )


def ensure_run_transition(
    current: BatchReviewRunStatus,
    target: BatchReviewRunStatus,
) -> BatchReviewRunStatus:
    if target not in _RUN_TRANSITIONS[current]:
        raise BatchReviewStateConflict(f"cannot move run from {current} to {target}")
    return target


def ensure_item_transition(
    current: BatchReviewItemStatus,
    target: BatchReviewItemStatus,
    *,
    retry_allowed: bool = False,
) -> BatchReviewItemStatus:
    if (
        current is BatchReviewItemStatus.FAILED
        and target is BatchReviewItemStatus.QUEUED
        and retry_allowed
    ):
        return target
    if target not in _ITEM_TRANSITIONS[current]:
        raise BatchReviewStateConflict(f"cannot move item from {current} to {target}")
    return target


def aggregate_run_status(
    statuses: tuple[BatchReviewItemStatus, ...],
) -> BatchReviewRunStatus:
    if not statuses:
        return BatchReviewRunStatus.COMPLETED_WITH_EXCEPTIONS
    active = {
        BatchReviewItemStatus.ELIGIBLE,
        BatchReviewItemStatus.QUEUED,
        BatchReviewItemStatus.PARSING,
        BatchReviewItemStatus.MATERIALIZING,
        BatchReviewItemStatus.VALIDATING,
    }
    if any(status in active for status in statuses):
        return BatchReviewRunStatus.RUNNING
    exceptional = {BatchReviewItemStatus.MANUAL_REVIEW, BatchReviewItemStatus.FAILED}
    if any(status in exceptional for status in statuses):
        return BatchReviewRunStatus.COMPLETED_WITH_EXCEPTIONS
    return BatchReviewRunStatus.COMPLETED
