"""Immutable command contracts for publication and published-date moves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.datasets.types import MergeDecision, canonical_merge_decisions
from app.imports.types import ReportType

from ._common import (
    nonnegative,
    normalise_reason,
    normalise_timestamp,
    optional_positive,
    positive,
    require_nonblank,
    require_sha256,
    require_uuid,
    sha256_digest,
    timestamp_payload,
)

type EditableVersionStatus = Literal["draft", "ready_for_publish"]
type PublishedTargetStrategy = Literal["merge", "replace"]
type ActiveTargetAction = Literal["merge", "cancel", "force_rebuild"]

_EDITABLE_STATUSES = frozenset({"draft", "ready_for_publish"})
_PUBLISHED_TARGET_STRATEGIES = frozenset({"merge", "replace"})
_ACTIVE_TARGET_ACTIONS = frozenset({"merge", "cancel", "force_rebuild"})
_REPORT_TYPES = frozenset({"business_report", "return_report"})


@dataclass(frozen=True, slots=True)
class PublicationPointerExpectation:
    """An exact current-publication pointer, including its ABA timestamp."""

    version_id: int | None
    published_at: datetime | None

    def __post_init__(self) -> None:
        if (self.version_id is None) != (self.published_at is None):
            raise ValueError(
                "publication version and timestamp must be both present or both absent"
            )
        optional_positive(self.version_id, "publication version_id")
        if self.published_at is not None:
            object.__setattr__(
                self,
                "published_at",
                normalise_timestamp(self.published_at, "published_at"),
            )

    @property
    def is_present(self) -> bool:
        return self.version_id is not None

    def as_payload(self) -> dict[str, object]:
        return {
            "version_id": self.version_id,
            "published_at": (
                timestamp_payload(self.published_at)
                if self.published_at is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class DraftPointerExpectation:
    """The exact editable head and pointer timestamp observed by a caller."""

    version_id: int
    status: EditableVersionStatus
    data_revision: int
    review_revision: int
    pointed_at: datetime

    def __post_init__(self) -> None:
        positive(self.version_id, "draft version_id")
        if self.status not in _EDITABLE_STATUSES:
            raise ValueError("draft status must be draft or ready_for_publish")
        nonnegative(self.data_revision, "data_revision")
        nonnegative(self.review_revision, "review_revision")
        object.__setattr__(
            self,
            "pointed_at",
            normalise_timestamp(self.pointed_at, "pointed_at"),
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "version_id": self.version_id,
            "status": self.status,
            "data_revision": self.data_revision,
            "review_revision": self.review_revision,
            "pointed_at": timestamp_payload(self.pointed_at),
        }


@dataclass(frozen=True, slots=True)
class ValidationExpectation:
    """The exact successful validation result confirmed for publication."""

    run_id: int
    version_id: int
    data_revision: int
    ruleset_version: str
    data_digest: bytes

    def __post_init__(self) -> None:
        positive(self.run_id, "validation run_id")
        positive(self.version_id, "validation version_id")
        nonnegative(self.data_revision, "validation data_revision")
        object.__setattr__(
            self,
            "ruleset_version",
            require_nonblank(self.ruleset_version, "ruleset_version"),
        )
        require_sha256(self.data_digest, "validation data_digest")

    def as_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "version_id": self.version_id,
            "data_revision": self.data_revision,
            "ruleset_version": self.ruleset_version,
            "data_digest": self.data_digest.hex(),
        }


def _canonical_totals(
    values: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    canonical: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_name, raw_value in values:
        name = require_nonblank(raw_name, "total field_name")
        value = require_nonblank(raw_value, "total value")
        if name in seen:
            raise ValueError("totals contain a duplicate field")
        seen.add(name)
        canonical.append((name, value))
    return tuple(sorted(canonical))


@dataclass(frozen=True, slots=True)
class PublicationConfirmation:
    """The exact human-confirmed report summary approved for publication."""

    confirmed_report_date: date
    report_type: ReportType
    row_count: int
    totals: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if type(self.confirmed_report_date) is not date:
            raise ValueError("confirmed_report_date must be a date")
        if self.report_type not in _REPORT_TYPES:
            raise ValueError("report_type is not supported")
        nonnegative(self.row_count, "row_count")
        object.__setattr__(self, "totals", _canonical_totals(self.totals))

    def as_payload(self) -> dict[str, object]:
        return {
            "confirmed_report_date": self.confirmed_report_date.isoformat(),
            "report_type": self.report_type,
            "row_count": self.row_count,
            "totals": self.totals,
        }


def _validate_actor_and_token(actor_user_id: int, operation_token: UUID) -> None:
    positive(actor_user_id, "actor_user_id")
    require_uuid(operation_token)


def _validate_ready_validation(
    draft: DraftPointerExpectation,
    validation: ValidationExpectation,
) -> None:
    if draft.status != "ready_for_publish":
        raise ValueError("publication requires a ready_for_publish draft")
    if draft.version_id != validation.version_id:
        raise ValueError("validation version must match the draft")
    if draft.data_revision != validation.data_revision:
        raise ValueError("validation data revision must match the draft")


@dataclass(frozen=True, slots=True)
class CreateRevisionCommand:
    dataset_id: int
    expected_publication: PublicationPointerExpectation
    actor_user_id: int
    operation_token: UUID
    reason: str

    def __post_init__(self) -> None:
        positive(self.dataset_id, "dataset_id")
        if not self.expected_publication.is_present:
            raise ValueError("create revision requires a current publication")
        _validate_actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", normalise_reason(self.reason))

    @property
    def operation_digest(self) -> bytes:
        return sha256_digest(
            {
                "command": "create_revision",
                "dataset_id": self.dataset_id,
                "expected_publication": self.expected_publication.as_payload(),
                "expected_active_draft": None,
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class PublishCommand:
    dataset_id: int
    expected_draft: DraftPointerExpectation
    expected_publication: PublicationPointerExpectation
    validation: ValidationExpectation
    confirmation: PublicationConfirmation
    actor_user_id: int
    operation_token: UUID
    reason: str

    def __post_init__(self) -> None:
        positive(self.dataset_id, "dataset_id")
        _validate_ready_validation(self.expected_draft, self.validation)
        if not isinstance(self.confirmation, PublicationConfirmation):
            raise ValueError("confirmation is required")
        _validate_actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", normalise_reason(self.reason))

    @property
    def operation_digest(self) -> bytes:
        return sha256_digest(
            {
                "command": "publish",
                "dataset_id": self.dataset_id,
                "expected_draft": self.expected_draft.as_payload(),
                "expected_publication": self.expected_publication.as_payload(),
                "validation": self.validation.as_payload(),
                "confirmation": self.confirmation.as_payload(),
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class RollbackCommand:
    dataset_id: int
    expected_publication: PublicationPointerExpectation
    target_version_id: int
    actor_user_id: int
    operation_token: UUID
    reason: str

    def __post_init__(self) -> None:
        positive(self.dataset_id, "dataset_id")
        if not self.expected_publication.is_present:
            raise ValueError("rollback requires a current publication")
        positive(self.target_version_id, "target_version_id")
        if self.target_version_id == self.expected_publication.version_id:
            raise ValueError("rollback target must differ from the current publication")
        _validate_actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", normalise_reason(self.reason))

    @property
    def operation_digest(self) -> bytes:
        return sha256_digest(
            {
                "command": "rollback",
                "dataset_id": self.dataset_id,
                "expected_publication": self.expected_publication.as_payload(),
                "target_version_id": self.target_version_id,
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class EmptyMoveTarget:
    dataset_id: None = None

    def __post_init__(self) -> None:
        if self.dataset_id is not None:
            raise ValueError("empty move target cannot have a dataset")

    def as_payload(self) -> dict[str, object]:
        return {
            "target_kind": "empty",
            "dataset_id": None,
            "publication": PublicationPointerExpectation(None, None).as_payload(),
            "draft": None,
            "strategy": "create",
        }


@dataclass(frozen=True, slots=True)
class PublishedMoveTarget:
    dataset_id: int
    publication: PublicationPointerExpectation
    strategy: PublishedTargetStrategy

    def __post_init__(self) -> None:
        positive(self.dataset_id, "target dataset_id")
        if not self.publication.is_present:
            raise ValueError("published move target requires a publication")
        if self.strategy not in _PUBLISHED_TARGET_STRATEGIES:
            raise ValueError("published move target strategy is not supported")

    def as_payload(self) -> dict[str, object]:
        return {
            "target_kind": "published",
            "dataset_id": self.dataset_id,
            "publication": self.publication.as_payload(),
            "draft": None,
            "strategy": self.strategy,
        }


@dataclass(frozen=True, slots=True)
class ActiveDraftMoveTarget:
    dataset_id: int
    draft: DraftPointerExpectation
    publication: PublicationPointerExpectation
    action: ActiveTargetAction
    rebuild_strategy: PublishedTargetStrategy | None = None

    def __post_init__(self) -> None:
        positive(self.dataset_id, "target dataset_id")
        if self.action not in _ACTIVE_TARGET_ACTIONS:
            raise ValueError("active draft target action is not supported")
        if self.action == "force_rebuild":
            if self.rebuild_strategy not in _PUBLISHED_TARGET_STRATEGIES:
                raise ValueError("rebuild_strategy is required for force_rebuild")
            if self.rebuild_strategy == "merge" and not self.publication.is_present:
                raise ValueError("force_rebuild merge requires a target publication")
        elif self.rebuild_strategy is not None:
            raise ValueError("rebuild_strategy is only valid for force_rebuild")

    def as_payload(self) -> dict[str, object]:
        return {
            "target_kind": "active_draft",
            "dataset_id": self.dataset_id,
            "publication": self.publication.as_payload(),
            "draft": self.draft.as_payload(),
            "strategy": self.action,
            "rebuild_strategy": self.rebuild_strategy,
        }


type PublishedMoveTargetExpectation = (
    EmptyMoveTarget | PublishedMoveTarget | ActiveDraftMoveTarget
)


def _merge_decisions_payload(
    decisions: tuple[MergeDecision, ...],
) -> list[dict[str, object]]:
    return [decision.as_payload() for decision in canonical_merge_decisions(decisions)]


@dataclass(frozen=True, slots=True)
class CreatePublishedMoveRevisionCommand:
    source_dataset_id: int
    expected_source_publication: PublicationPointerExpectation
    target_report_date: date
    target: PublishedMoveTargetExpectation
    merge_decisions: tuple[MergeDecision, ...]
    actor_user_id: int
    operation_token: UUID
    reason: str

    def __post_init__(self) -> None:
        positive(self.source_dataset_id, "source_dataset_id")
        if not self.expected_source_publication.is_present:
            raise ValueError("published move requires a source publication")
        if type(self.target_report_date) is not date:
            raise ValueError("target_report_date must be a date")
        target_dataset_id = self.target.dataset_id
        if target_dataset_id == self.source_dataset_id:
            raise ValueError("target dataset must differ from source dataset")
        decisions = canonical_merge_decisions(self.merge_decisions)
        object.__setattr__(self, "merge_decisions", decisions)
        target_is_merge = (
            isinstance(self.target, PublishedMoveTarget)
            and self.target.strategy == "merge"
        ) or (
            isinstance(self.target, ActiveDraftMoveTarget)
            and (
                self.target.action == "merge"
                or (
                    self.target.action == "force_rebuild"
                    and self.target.rebuild_strategy == "merge"
                )
            )
        )
        if decisions and not target_is_merge:
            raise ValueError("merge decisions must be empty for this target choice")
        _validate_actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", normalise_reason(self.reason))

    @property
    def operation_digest(self) -> bytes:
        return sha256_digest(
            {
                "command": "create_published_move_revision",
                "source_dataset_id": self.source_dataset_id,
                "expected_source_publication": (
                    self.expected_source_publication.as_payload()
                ),
                "expected_source_active_draft": None,
                "target_report_date": self.target_report_date.isoformat(),
                "target": self.target.as_payload(),
                "merge_decisions": _merge_decisions_payload(self.merge_decisions),
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class FinalizePublishedMoveCommand:
    move_revision_operation_token: UUID
    source_dataset_id: int
    expected_source_publication: PublicationPointerExpectation
    target_dataset_id: int
    expected_target_draft: DraftPointerExpectation
    expected_target_publication: PublicationPointerExpectation
    validation: ValidationExpectation
    confirmation: PublicationConfirmation
    actor_user_id: int
    operation_token: UUID
    reason: str

    def __post_init__(self) -> None:
        require_uuid(
            self.move_revision_operation_token,
            "move_revision_operation_token",
        )
        positive(self.source_dataset_id, "source_dataset_id")
        positive(self.target_dataset_id, "target_dataset_id")
        if self.source_dataset_id == self.target_dataset_id:
            raise ValueError("target dataset must differ from source dataset")
        if not self.expected_source_publication.is_present:
            raise ValueError("published move requires a source publication")
        _validate_ready_validation(self.expected_target_draft, self.validation)
        if not isinstance(self.confirmation, PublicationConfirmation):
            raise ValueError("confirmation is required")
        _validate_actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", normalise_reason(self.reason))

    @property
    def operation_digest(self) -> bytes:
        return sha256_digest(
            {
                "command": "finalize_published_move",
                "move_revision_operation_token": str(
                    self.move_revision_operation_token
                ),
                "source_dataset_id": self.source_dataset_id,
                "expected_source_publication": (
                    self.expected_source_publication.as_payload()
                ),
                "expected_source_active_draft": None,
                "target_dataset_id": self.target_dataset_id,
                "expected_target_draft": self.expected_target_draft.as_payload(),
                "expected_target_publication": (
                    self.expected_target_publication.as_payload()
                ),
                "validation": self.validation.as_payload(),
                "confirmation": self.confirmation.as_payload(),
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class UndoPublishedMoveCommand:
    move_command_id: int
    source_dataset_id: int
    expected_source_publication: PublicationPointerExpectation
    restore_source_version_id: int
    target_dataset_id: int
    expected_target_publication: PublicationPointerExpectation
    restore_target_version_id: int | None
    actor_user_id: int
    operation_token: UUID
    reason: str

    def __post_init__(self) -> None:
        positive(self.move_command_id, "move_command_id")
        positive(self.source_dataset_id, "source_dataset_id")
        positive(self.target_dataset_id, "target_dataset_id")
        if self.source_dataset_id == self.target_dataset_id:
            raise ValueError("target dataset must differ from source dataset")
        if self.expected_source_publication.is_present:
            raise ValueError("source publication must be absent before move undo")
        if not self.expected_target_publication.is_present:
            raise ValueError("target publication must be present before move undo")
        positive(self.restore_source_version_id, "restore_source_version_id")
        optional_positive(
            self.restore_target_version_id,
            "restore_target_version_id",
        )
        _validate_actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", normalise_reason(self.reason))

    @property
    def operation_digest(self) -> bytes:
        return sha256_digest(
            {
                "command": "undo_published_move",
                "move_command_id": self.move_command_id,
                "source_dataset_id": self.source_dataset_id,
                "expected_source_publication": (
                    self.expected_source_publication.as_payload()
                ),
                "restore_source_version_id": self.restore_source_version_id,
                "target_dataset_id": self.target_dataset_id,
                "expected_target_publication": (
                    self.expected_target_publication.as_payload()
                ),
                "restore_target_version_id": self.restore_target_version_id,
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )
