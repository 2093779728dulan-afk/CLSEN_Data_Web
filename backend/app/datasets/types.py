"""Immutable domain contracts for daily dataset draft operations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID

type DraftStrategy = Literal["merge", "replace"]
type MergeAction = Literal["keep_target", "keep_source", "keep_both"]
type ActiveDraftTargetAction = Literal["merge", "cancel"]
type DraftMutationStatus = Literal["draft", "discarded", "cancelled"]

_DRAFT_STRATEGIES = frozenset({"merge", "replace"})
_MERGE_ACTIONS = frozenset({"keep_target", "keep_source", "keep_both"})
_ACTIVE_TARGET_ACTIONS = frozenset({"merge", "cancel"})
_MUTATION_STATUSES = frozenset({"draft", "discarded", "cancelled"})


class DatasetError(RuntimeError):
    """Base class for expected dataset-domain failures."""


class DatasetPermissionDenied(DatasetError):
    """The authenticated actor lacks permission for the requested operation."""


class DatasetSiteConflict(DatasetError):
    """A logical daily dataset resolved to a site other than the expected one."""

    def __init__(
        self,
        message: str = "dataset site changed",
        *,
        expected_site_id: int | None = None,
        actual_site_id: int | None = None,
    ) -> None:
        super().__init__(message)
        _optional_positive(expected_site_id, "expected_site_id")
        _optional_positive(actual_site_id, "actual_site_id")
        self.expected_site_id = expected_site_id
        self.actual_site_id = actual_site_id


class BaselineNotFound(DatasetError):
    """The requested immutable parse baseline does not exist."""


class BaselineConflict(DatasetError):
    """The baseline is not eligible for the requested draft operation."""


class BaselineNotCurrent(BaselineConflict):
    """The baseline is not the batch's current successful parse result."""


class BaselineAlreadyMaterialized(BaselineConflict):
    """The same baseline has already entered a version lineage."""


class ActiveDraftConflict(DatasetError):
    """The current active-draft pointer differs from the caller's preview."""

    def __init__(
        self,
        message: str = "active draft changed",
        *,
        expected: VersionExpectation | None = None,
        actual: VersionExpectation | None = None,
    ) -> None:
        super().__init__(message)
        self.expected = expected
        self.actual = actual


class RevisionConflict(DatasetError):
    """A draft's data or review revision differs from the expected head."""

    def __init__(
        self,
        message: str = "draft revision changed",
        *,
        expected: VersionExpectation | None = None,
        actual: VersionExpectation | None = None,
    ) -> None:
        super().__init__(message)
        self.expected = expected
        self.actual = actual


class SealedVersionConflict(DatasetError):
    """A late operation attempted to mutate a terminal version."""


class MergeConflict(DatasetError):
    """Base class for invalid or incomplete merge decisions."""


class MergeDecisionRequired(MergeConflict):
    """A concrete cross-member row conflict has no explicit decision."""

    def __init__(self, *, target_row_id: int, source_row_id: int) -> None:
        super().__init__(
            "merge decision required for target row "
            f"{target_row_id} and source row {source_row_id}"
        )
        self.target_row_id = target_row_id
        self.source_row_id = source_row_id


class InvalidMergeDecision(MergeConflict):
    """A supplied decision does not bind a valid concrete conflict."""


class PublishedLineageConflict(DatasetError):
    """An unpublished-date operation encountered published ancestry."""


class TargetConflict(DatasetError):
    """The target dataset shape differs from the explicit target plan."""


class OperationConflict(DatasetError):
    """An operation token was reused with a different command digest."""


class DatasetCommitOutcomeUnknown(DatasetError):
    """A commit acknowledgement was lost and no terminal result was found."""


class DatasetTransactionBusy(DatasetError):
    """Required MySQL locks stayed unavailable after bounded retries."""


# Precise draft-operation vocabulary used by persistence adapters and reviews.
# The original names remain the same runtime classes for backwards compatibility.
DraftPointerConflict = ActiveDraftConflict
DraftRevisionConflict = RevisionConflict
DraftSealedConflict = SealedVersionConflict
PublishedLineageMoveRequired = PublishedLineageConflict
TargetDraftConflict = TargetConflict
DraftOperationConflict = OperationConflict
DraftCommitOutcomeUnknown = DatasetCommitOutcomeUnknown


def _positive(value: int, field_name: str) -> None:
    if value < 1:
        raise ValueError(f"{field_name} must be positive")


def _nonnegative(value: int, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must not be negative")


def _optional_positive(value: int | None, field_name: str) -> None:
    if value is not None:
        _positive(value, field_name)


def _normalise_reason(value: str) -> str:
    reason = value.strip()
    if not reason:
        raise ValueError("reason must not be blank")
    return reason


def _validate_actor_and_token(actor_user_id: int, operation_token: UUID) -> None:
    _positive(actor_user_id, "actor_user_id")
    if not isinstance(operation_token, UUID):
        raise ValueError("operation_token must be a UUID")


def _canonical_digest(payload: object) -> bytes:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).digest()


@dataclass(frozen=True, slots=True)
class VersionExpectation:
    """The exact editable head observed before a write command is issued."""

    version_id: int
    data_revision: int
    review_revision: int

    def __post_init__(self) -> None:
        _positive(self.version_id, "version_id")
        _nonnegative(self.data_revision, "data_revision")
        _nonnegative(self.review_revision, "review_revision")

    def as_payload(self) -> dict[str, int]:
        return {
            "version_id": self.version_id,
            "data_revision": self.data_revision,
            "review_revision": self.review_revision,
        }


@dataclass(frozen=True, slots=True)
class MergeDecision:
    """One explicit decision bound to concrete target and source row IDs."""

    target_row_id: int
    source_row_id: int
    action: MergeAction
    reason: str | None = None

    def __post_init__(self) -> None:
        _positive(self.target_row_id, "target_row_id")
        _positive(self.source_row_id, "source_row_id")
        if self.action not in _MERGE_ACTIONS:
            raise ValueError("merge action is not supported")
        if self.reason is not None:
            reason = self.reason.strip()
            if not reason:
                raise ValueError("merge decision reason must not be blank")
            object.__setattr__(self, "reason", reason)
        if self.action == "keep_both" and self.reason is None:
            raise ValueError("reason is required when keeping both rows")

    def as_payload(self) -> dict[str, object]:
        return {
            "target_row_id": self.target_row_id,
            "source_row_id": self.source_row_id,
            "action": self.action,
            "reason": self.reason,
        }


def canonical_merge_decisions(
    decisions: Iterable[MergeDecision],
) -> tuple[MergeDecision, ...]:
    """Return pair-level decisions in their stable command and audit order."""

    return tuple(
        sorted(
            decisions,
            key=lambda decision: (decision.target_row_id, decision.source_row_id),
        )
    )


@dataclass(frozen=True, slots=True)
class EmptyReassignmentTarget:
    """The caller previewed no target dataset for the selected date."""

    expected_dataset_id: None = None

    def __post_init__(self) -> None:
        if self.expected_dataset_id is not None:
            raise ValueError("empty target cannot have a dataset")

    def as_payload(self) -> dict[str, object]:
        return {
            "target_kind": "empty",
            "expected_dataset_id": self.expected_dataset_id,
            "expected_publication_version_id": None,
            "expected_active_draft": None,
            "strategy": "create",
        }


@dataclass(frozen=True, slots=True)
class PublishedReassignmentTarget:
    """The target has a publication but no active draft."""

    expected_dataset_id: int
    expected_publication_version_id: int
    strategy: DraftStrategy

    def __post_init__(self) -> None:
        _positive(self.expected_dataset_id, "expected_dataset_id")
        _positive(
            self.expected_publication_version_id,
            "expected_publication_version_id",
        )
        if self.strategy not in _DRAFT_STRATEGIES:
            raise ValueError("published target strategy is not supported")

    def as_payload(self) -> dict[str, object]:
        return {
            "target_kind": "published",
            "expected_dataset_id": self.expected_dataset_id,
            "expected_publication_version_id": (self.expected_publication_version_id),
            "expected_active_draft": None,
            "strategy": self.strategy,
        }


@dataclass(frozen=True, slots=True)
class ActiveDraftReassignmentTarget:
    """The target has an active draft that may only be merged or cancelled."""

    expected_dataset_id: int
    expected_active_draft: VersionExpectation
    expected_publication_version_id: int | None
    action: ActiveDraftTargetAction

    def __post_init__(self) -> None:
        _positive(self.expected_dataset_id, "expected_dataset_id")
        if not isinstance(self.expected_active_draft, VersionExpectation):
            raise ValueError("expected_active_draft is required")
        _optional_positive(
            self.expected_publication_version_id,
            "expected_publication_version_id",
        )
        if self.action not in _ACTIVE_TARGET_ACTIONS:
            raise ValueError("active draft target action is not supported")

    def as_payload(self) -> dict[str, object]:
        return {
            "target_kind": "active_draft",
            "expected_dataset_id": self.expected_dataset_id,
            "expected_publication_version_id": (self.expected_publication_version_id),
            "expected_active_draft": self.expected_active_draft.as_payload(),
            "strategy": self.action,
        }


type ReassignmentTarget = (
    EmptyReassignmentTarget
    | PublishedReassignmentTarget
    | ActiveDraftReassignmentTarget
)


def _decisions_payload(
    decisions: tuple[MergeDecision, ...],
) -> list[dict[str, object]]:
    return [decision.as_payload() for decision in canonical_merge_decisions(decisions)]


@dataclass(frozen=True, slots=True)
class MaterializeBaselineCommand:
    """Create or merge a draft from one current successful parse baseline."""

    batch_id: int
    parse_baseline_id: int
    report_date: date
    strategy: DraftStrategy
    expected_active_draft: VersionExpectation | None
    expected_publication_version_id: int | None
    merge_decisions: tuple[MergeDecision, ...]
    actor_user_id: int
    operation_token: UUID
    reason: str

    def __post_init__(self) -> None:
        _positive(self.batch_id, "batch_id")
        _positive(self.parse_baseline_id, "parse_baseline_id")
        if not isinstance(self.report_date, date):
            raise ValueError("report_date must be a date")
        if self.strategy not in _DRAFT_STRATEGIES:
            raise ValueError("draft strategy is not supported")
        if self.expected_active_draft is not None and not isinstance(
            self.expected_active_draft,
            VersionExpectation,
        ):
            raise ValueError("expected_active_draft must be a version expectation")
        _optional_positive(
            self.expected_publication_version_id,
            "expected_publication_version_id",
        )
        object.__setattr__(
            self,
            "merge_decisions",
            canonical_merge_decisions(self.merge_decisions),
        )
        _validate_actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", _normalise_reason(self.reason))

        if self.strategy == "replace" and self.expected_active_draft is not None:
            raise ValueError(
                "replace cannot overwrite an active draft; use force rebuild"
            )
        if self.strategy == "replace" and self.merge_decisions:
            raise ValueError("merge_decisions must be empty for replace")

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": "materialize_baseline",
                "actor_user_id": self.actor_user_id,
                "batch_id": self.batch_id,
                "parse_baseline_id": self.parse_baseline_id,
                "report_date": self.report_date.isoformat(),
                "strategy": self.strategy,
                "expected_active_draft": (
                    self.expected_active_draft.as_payload()
                    if self.expected_active_draft is not None
                    else None
                ),
                "expected_publication_version_id": (
                    self.expected_publication_version_id
                ),
                "merge_decisions": _decisions_payload(self.merge_decisions),
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class ForceRebuildDraftCommand:
    """Administrator-only intent to atomically replace an expected active draft."""

    batch_id: int
    parse_baseline_id: int
    report_date: date
    expected_active_draft: VersionExpectation
    expected_publication_version_id: int | None
    actor_user_id: int
    operation_token: UUID
    reason: str

    def __post_init__(self) -> None:
        _positive(self.batch_id, "batch_id")
        _positive(self.parse_baseline_id, "parse_baseline_id")
        if not isinstance(self.report_date, date):
            raise ValueError("report_date must be a date")
        if not isinstance(self.expected_active_draft, VersionExpectation):
            raise ValueError("expected_active_draft is required")
        _optional_positive(
            self.expected_publication_version_id,
            "expected_publication_version_id",
        )
        _validate_actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", _normalise_reason(self.reason))

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": "force_rebuild_draft",
                "actor_user_id": self.actor_user_id,
                "batch_id": self.batch_id,
                "parse_baseline_id": self.parse_baseline_id,
                "report_date": self.report_date.isoformat(),
                "strategy": "force_replace",
                "expected_active_draft": self.expected_active_draft.as_payload(),
                "expected_publication_version_id": (
                    self.expected_publication_version_id
                ),
                "merge_decisions": [],
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class DiscardDraftCommand:
    """Discard exactly the active draft revision observed by the caller."""

    dataset_id: int
    expected_active_draft: VersionExpectation
    actor_user_id: int
    operation_token: UUID
    reason: str

    def __post_init__(self) -> None:
        _positive(self.dataset_id, "dataset_id")
        if not isinstance(self.expected_active_draft, VersionExpectation):
            raise ValueError("expected_active_draft is required")
        _validate_actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", _normalise_reason(self.reason))

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": "discard_active_draft",
                "actor_user_id": self.actor_user_id,
                "dataset_id": self.dataset_id,
                "strategy": "discard",
                "expected_active_draft": self.expected_active_draft.as_payload(),
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class ReassignUnpublishedDraftDateCommand:
    """Move an unpublished draft through one explicit target-shape plan."""

    source_dataset_id: int
    source_draft: VersionExpectation
    target_report_date: date
    target: ReassignmentTarget
    merge_decisions: tuple[MergeDecision, ...]
    actor_user_id: int
    operation_token: UUID
    reason: str

    def __post_init__(self) -> None:
        _positive(self.source_dataset_id, "source_dataset_id")
        if not isinstance(self.source_draft, VersionExpectation):
            raise ValueError("source_draft is required")
        if not isinstance(self.target_report_date, date):
            raise ValueError("target_report_date must be a date")
        if not isinstance(
            self.target,
            (
                EmptyReassignmentTarget,
                PublishedReassignmentTarget,
                ActiveDraftReassignmentTarget,
            ),
        ):
            raise ValueError("target plan is not supported")
        target_dataset_id = self.target.expected_dataset_id
        if target_dataset_id == self.source_dataset_id:
            raise ValueError("target dataset must differ from source dataset")
        object.__setattr__(
            self,
            "merge_decisions",
            canonical_merge_decisions(self.merge_decisions),
        )
        _validate_actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", _normalise_reason(self.reason))

        target_is_merge = (
            isinstance(self.target, PublishedReassignmentTarget)
            and self.target.strategy == "merge"
        ) or (
            isinstance(self.target, ActiveDraftReassignmentTarget)
            and self.target.action == "merge"
        )
        if not target_is_merge and self.merge_decisions:
            raise ValueError("merge_decisions must be empty for this target choice")

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": "reassign_unpublished_draft_date",
                "actor_user_id": self.actor_user_id,
                "source_dataset_id": self.source_dataset_id,
                "source_draft": self.source_draft.as_payload(),
                "target_report_date": self.target_report_date.isoformat(),
                "target": self.target.as_payload(),
                "merge_decisions": _decisions_payload(self.merge_decisions),
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class DraftMutationResult:
    """Stable terminal identity recoverable through a draft operation token."""

    operation_token: UUID
    dataset_id: int
    version_id: int
    version_no: int
    status: DraftMutationStatus
    data_revision: int
    review_revision: int
    superseded_version_ids: tuple[int, ...] = ()
    source_dataset_id: int | None = None
    source_version_id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation_token, UUID):
            raise ValueError("operation_token must be a UUID")
        _positive(self.dataset_id, "dataset_id")
        _positive(self.version_id, "version_id")
        _positive(self.version_no, "version_no")
        if self.status not in _MUTATION_STATUSES:
            raise ValueError("draft mutation status is not supported")
        _nonnegative(self.data_revision, "data_revision")
        _nonnegative(self.review_revision, "review_revision")
        superseded = tuple(self.superseded_version_ids)
        for version_id in superseded:
            _positive(version_id, "superseded_version_id")
        if len(superseded) != len(set(superseded)):
            raise ValueError("superseded_version_ids must be unique")
        if len(superseded) > 2:
            raise ValueError("at most two superseded_version_ids are supported")
        object.__setattr__(self, "superseded_version_ids", superseded)
        if self.status == "cancelled":
            if superseded:
                raise ValueError("cancelled result cannot supersede a version")
            if self.source_dataset_id is not None or self.source_version_id is not None:
                raise ValueError("cancelled result cannot have source lineage fields")
        if (self.source_dataset_id is None) != (self.source_version_id is None):
            raise ValueError(
                "source dataset and version must be both present or absent"
            )
        _optional_positive(self.source_dataset_id, "source_dataset_id")
        _optional_positive(self.source_version_id, "source_version_id")
