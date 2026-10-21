"""Immutable command contracts for draft edits and human review."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, cast
from uuid import UUID

from app.imports.types import ReportType
from app.validation.codec import encode_field_value
from app.validation.fields import FieldValue

type EditableVersionStatus = Literal["draft", "ready_for_publish"]
type RestoreSourceKind = Literal["previous", "parent", "source"]
type RowChangeOperation = Literal["exclude", "restore", "delete"]
type NoteVisibility = Literal["internal", "viewer_visible"]
type IssueSeverity = Literal["warning", "blocking"]
type IssueReviewAction = Literal["acknowledge", "resolve", "reopen"]

_EDITABLE_STATUSES = frozenset({"draft", "ready_for_publish"})
_ROW_OPERATIONS = frozenset({"exclude", "restore", "delete"})
_VISIBILITIES = frozenset({"internal", "viewer_visible"})
_ISSUE_SEVERITIES = frozenset({"warning", "blocking"})
_ISSUE_ACTIONS = frozenset({"acknowledge", "resolve", "reopen"})


class ReviewError(RuntimeError):
    """Base class for expected review-domain failures."""


class ReviewPermissionDenied(ReviewError):
    """The actor cannot review or mutate this draft."""


class VersionNotEditable(ReviewError):
    """The requested version is no longer an active editable draft."""


class DraftPointerConflict(ReviewError):
    """The active pointer differs from the caller's exact expectation."""


class ReviewRevisionConflict(ReviewError):
    """A data or review revision changed before the command executed."""


class RowNotFound(ReviewError):
    """The requested processed row does not belong to this version."""


class RowStateConflict(ReviewError):
    """The requested row-state transition is invalid from the current state."""


class FieldNotEditable(ReviewError):
    """The field is unknown or intentionally read-only."""


class FieldValueInvalid(ReviewError):
    """The supplied value cannot be represented by the field contract."""


class RestoreValueUnavailable(ReviewError):
    """The explicitly selected previous, parent, or source value is unavailable."""


class StaleValidationRun(ReviewError):
    """The selected validation run no longer qualifies the draft."""


class IssueReviewConflict(ReviewError):
    """The issue shape or current review state differs from the command."""


class NoteRevisionConflict(ReviewError):
    """The note thread changed before a new revision could be appended."""


class ReviewOperationConflict(ReviewError):
    """An operation token is already bound to another command."""


class ReviewCommitOutcomeUnknown(ReviewError):
    """Commit acknowledgement was lost without a recoverable terminal result."""


class ReviewTransactionBusy(ReviewError):
    """MySQL locks remained unavailable after the bounded retry policy."""


def _positive(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be positive")


def _nonnegative(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must not be negative")


def _nonblank(value: str, field_name: str, *, preserve: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalised = value.strip()
    if not normalised:
        raise ValueError(f"{field_name} must not be blank")
    return value if preserve else normalised


def _actor_and_token(actor_user_id: int, operation_token: UUID) -> None:
    _positive(actor_user_id, "actor_user_id")
    if not isinstance(operation_token, UUID):
        raise ValueError("operation_token must be a UUID")


def _utc_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return (
        value.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace(
            "+00:00",
            "Z",
        )
    )


def _canonical_digest(payload: object) -> bytes:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).digest()


@dataclass(frozen=True, slots=True)
class DraftHeadExpectation:
    """Exact active-draft head, including pointer time to prevent ABA writes."""

    dataset_id: int
    version_id: int
    status: EditableVersionStatus
    data_revision: int
    review_revision: int
    pointed_at: datetime

    def __post_init__(self) -> None:
        _positive(self.dataset_id, "dataset_id")
        _positive(self.version_id, "version_id")
        if self.status not in _EDITABLE_STATUSES:
            raise ValueError("status must be editable")
        _nonnegative(self.data_revision, "data_revision")
        _nonnegative(self.review_revision, "review_revision")
        object.__setattr__(
            self,
            "pointed_at",
            _utc_datetime(self.pointed_at, "pointed_at"),
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "version_id": self.version_id,
            "status": self.status,
            "data_revision": self.data_revision,
            "review_revision": self.review_revision,
            "pointed_at": _utc_text(self.pointed_at),
        }


@dataclass(frozen=True, slots=True)
class PreviousValueSource:
    field_change_id: int
    kind: Literal["previous"] = "previous"

    def __post_init__(self) -> None:
        _positive(self.field_change_id, "field_change_id")

    def as_payload(self) -> dict[str, object]:
        return {"kind": self.kind, "field_change_id": self.field_change_id}


@dataclass(frozen=True, slots=True)
class ParentValueSource:
    parent_version_id: int
    kind: Literal["parent"] = "parent"

    def __post_init__(self) -> None:
        _positive(self.parent_version_id, "parent_version_id")

    def as_payload(self) -> dict[str, object]:
        return {"kind": self.kind, "parent_version_id": self.parent_version_id}


@dataclass(frozen=True, slots=True)
class SourceFileValueSource:
    source_batch_id: int
    parsed_source_row_id: int
    kind: Literal["source"] = "source"

    def __post_init__(self) -> None:
        _positive(self.source_batch_id, "source_batch_id")
        _positive(self.parsed_source_row_id, "parsed_source_row_id")

    def as_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "source_batch_id": self.source_batch_id,
            "parsed_source_row_id": self.parsed_source_row_id,
        }


type FieldRestoreSource = (
    PreviousValueSource | ParentValueSource | SourceFileValueSource
)


@dataclass(frozen=True, slots=True)
class SetFieldValueCommand:
    head: DraftHeadExpectation
    row_id: int
    field_name: str
    value: FieldValue
    actor_user_id: int
    operation_token: UUID
    reason: str

    operation_kind: Literal["set_field"] = "set_field"

    def __post_init__(self) -> None:
        if not isinstance(self.head, DraftHeadExpectation):
            raise ValueError("head is required")
        _positive(self.row_id, "row_id")
        object.__setattr__(self, "field_name", _nonblank(self.field_name, "field_name"))
        encode_field_value(self.value)
        _actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", _nonblank(self.reason, "reason"))

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": self.operation_kind,
                "head": self.head.as_payload(),
                "row_id": self.row_id,
                "field_name": self.field_name,
                "value": encode_field_value(self.value),
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class RestoreFieldValueCommand:
    head: DraftHeadExpectation
    row_id: int
    field_name: str
    source: FieldRestoreSource
    actor_user_id: int
    operation_token: UUID
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.head, DraftHeadExpectation):
            raise ValueError("head is required")
        _positive(self.row_id, "row_id")
        object.__setattr__(self, "field_name", _nonblank(self.field_name, "field_name"))
        if not isinstance(
            self.source,
            (PreviousValueSource, ParentValueSource, SourceFileValueSource),
        ):
            raise ValueError("source is not supported")
        _actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", _nonblank(self.reason, "reason"))

    @property
    def operation_kind(self) -> str:
        return f"restore_{self.source.kind}_field"

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": self.operation_kind,
                "head": self.head.as_payload(),
                "row_id": self.row_id,
                "field_name": self.field_name,
                "source": self.source.as_payload(),
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class AddRowCommand:
    head: DraftHeadExpectation
    source_batch_id: int
    values: Mapping[str, FieldValue] | tuple[tuple[str, FieldValue], ...]
    actor_user_id: int
    operation_token: UUID
    reason: str

    operation_kind: Literal["add_row"] = "add_row"

    def __post_init__(self) -> None:
        if not isinstance(self.head, DraftHeadExpectation):
            raise ValueError("head is required")
        _positive(self.source_batch_id, "source_batch_id")
        items = self.values.items() if isinstance(self.values, Mapping) else self.values
        canonical: list[tuple[str, FieldValue]] = []
        seen: set[str] = set()
        for raw_name, value in items:
            name = _nonblank(raw_name, "field_name")
            if name in seen:
                raise ValueError("row values contain a duplicate field")
            encode_field_value(value)
            seen.add(name)
            canonical.append((name, value))
        if not canonical:
            raise ValueError("row values must not be empty")
        object.__setattr__(self, "values", tuple(sorted(canonical)))
        _actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", _nonblank(self.reason, "reason"))

    @property
    def operation_digest(self) -> bytes:
        values = cast(tuple[tuple[str, FieldValue], ...], self.values)
        return _canonical_digest(
            {
                "command": self.operation_kind,
                "head": self.head.as_payload(),
                "source_batch_id": self.source_batch_id,
                "values": [
                    {"field_name": name, "value": encode_field_value(value)}
                    for name, value in values
                ],
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class ChangeRowStateCommand:
    head: DraftHeadExpectation
    row_id: int
    operation: RowChangeOperation
    actor_user_id: int
    operation_token: UUID
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.head, DraftHeadExpectation):
            raise ValueError("head is required")
        _positive(self.row_id, "row_id")
        if self.operation not in _ROW_OPERATIONS:
            raise ValueError("row operation is not supported")
        _actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", _nonblank(self.reason, "reason"))

    @property
    def operation_kind(self) -> str:
        return f"{self.operation}_row"

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": self.operation_kind,
                "head": self.head.as_payload(),
                "row_id": self.row_id,
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class ImportBatchNoteTarget:
    import_batch_id: int

    def __post_init__(self) -> None:
        _positive(self.import_batch_id, "import_batch_id")

    def as_payload(self) -> dict[str, object]:
        return {"target_type": "import_batch", "import_batch_id": self.import_batch_id}


@dataclass(frozen=True, slots=True)
class VersionNoteTarget:
    version_id: int

    def __post_init__(self) -> None:
        _positive(self.version_id, "version_id")

    def as_payload(self) -> dict[str, object]:
        return {"target_type": "version", "version_id": self.version_id}


@dataclass(frozen=True, slots=True)
class RowNoteTarget:
    version_id: int
    row_id: int

    def __post_init__(self) -> None:
        _positive(self.version_id, "version_id")
        _positive(self.row_id, "row_id")

    def as_payload(self) -> dict[str, object]:
        return {
            "target_type": "row",
            "version_id": self.version_id,
            "row_id": self.row_id,
        }


@dataclass(frozen=True, slots=True)
class FieldNoteTarget:
    version_id: int
    row_id: int
    field_name: str

    def __post_init__(self) -> None:
        _positive(self.version_id, "version_id")
        _positive(self.row_id, "row_id")
        object.__setattr__(self, "field_name", _nonblank(self.field_name, "field_name"))

    def as_payload(self) -> dict[str, object]:
        return {
            "target_type": "field",
            "version_id": self.version_id,
            "row_id": self.row_id,
            "field_name": self.field_name,
        }


type NoteTarget = (
    ImportBatchNoteTarget | VersionNoteTarget | RowNoteTarget | FieldNoteTarget
)


@dataclass(frozen=True, slots=True)
class CreateNoteCommand:
    target: NoteTarget
    expected_review_revision: int | None
    body: str
    actor_user_id: int
    operation_token: UUID
    visibility: NoteVisibility = "internal"

    operation_kind: Literal["create_note"] = "create_note"

    def __post_init__(self) -> None:
        if not isinstance(
            self.target,
            (ImportBatchNoteTarget, VersionNoteTarget, RowNoteTarget, FieldNoteTarget),
        ):
            raise ValueError("note target is not supported")
        if isinstance(self.target, ImportBatchNoteTarget):
            if self.expected_review_revision is not None:
                raise ValueError("batch note cannot carry a review_revision")
        elif self.expected_review_revision is None:
            raise ValueError("version note requires expected review_revision")
        else:
            _nonnegative(self.expected_review_revision, "review_revision")
        object.__setattr__(self, "body", _nonblank(self.body, "body", preserve=True))
        if self.visibility not in _VISIBILITIES:
            raise ValueError("note visibility is not supported")
        _actor_and_token(self.actor_user_id, self.operation_token)

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": self.operation_kind,
                "target": self.target.as_payload(),
                "expected_review_revision": self.expected_review_revision,
                "visibility": self.visibility,
                "body": self.body,
                "actor_user_id": self.actor_user_id,
            }
        )


@dataclass(frozen=True, slots=True)
class ReviseNoteCommand:
    note_key: str
    expected_note_id: int
    expected_revision_number: int
    target: NoteTarget
    expected_review_revision: int | None
    body: str
    actor_user_id: int
    operation_token: UUID
    visibility: NoteVisibility = "internal"

    operation_kind: Literal["revise_note"] = "revise_note"

    def __post_init__(self) -> None:
        object.__setattr__(self, "note_key", _nonblank(self.note_key, "note_key"))
        if len(self.note_key) > 64:
            raise ValueError("note_key exceeds maximum length")
        _positive(self.expected_note_id, "expected_note_id")
        _positive(self.expected_revision_number, "expected_revision_number")
        if not isinstance(
            self.target,
            (ImportBatchNoteTarget, VersionNoteTarget, RowNoteTarget, FieldNoteTarget),
        ):
            raise ValueError("note target is not supported")
        if isinstance(self.target, ImportBatchNoteTarget):
            if self.expected_review_revision is not None:
                raise ValueError("batch note cannot carry a review_revision")
        elif self.expected_review_revision is None:
            raise ValueError("version note requires expected review_revision")
        else:
            _nonnegative(self.expected_review_revision, "review_revision")
        object.__setattr__(self, "body", _nonblank(self.body, "body", preserve=True))
        if self.visibility not in _VISIBILITIES:
            raise ValueError("note visibility is not supported")
        _actor_and_token(self.actor_user_id, self.operation_token)

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": self.operation_kind,
                "note_key": self.note_key,
                "expected_note_id": self.expected_note_id,
                "expected_revision_number": self.expected_revision_number,
                "target": self.target.as_payload(),
                "expected_review_revision": self.expected_review_revision,
                "visibility": self.visibility,
                "body": self.body,
                "actor_user_id": self.actor_user_id,
            }
        )


@dataclass(frozen=True, slots=True)
class ReviewIssueCommand:
    head: DraftHeadExpectation
    validation_run_id: int
    validation_issue_id: int
    issue_severity: IssueSeverity
    issue_requires_note: bool
    action: IssueReviewAction
    comment: str | None
    actor_user_id: int
    operation_token: UUID

    operation_kind: Literal["review_issue"] = "review_issue"

    def __post_init__(self) -> None:
        if not isinstance(self.head, DraftHeadExpectation):
            raise ValueError("head is required")
        _positive(self.validation_run_id, "validation_run_id")
        _positive(self.validation_issue_id, "validation_issue_id")
        if self.issue_severity not in _ISSUE_SEVERITIES:
            raise ValueError("issue severity is not supported")
        if self.action not in _ISSUE_ACTIONS:
            raise ValueError("issue review action is not supported")
        if self.action == "acknowledge" and self.issue_severity != "warning":
            raise ValueError("acknowledge is only valid for a warning")
        if self.action in {"resolve", "reopen"} and self.issue_severity != "blocking":
            raise ValueError("resolve and reopen are only valid for blocking issues")
        comment = self.comment
        if comment is not None:
            comment = _nonblank(comment, "comment", preserve=True)
            object.__setattr__(self, "comment", comment)
        if (
            self.action == "resolve"
            or (self.action == "acknowledge" and self.issue_requires_note)
        ) and comment is None:
            raise ValueError("comment is required for this issue review")
        _actor_and_token(self.actor_user_id, self.operation_token)

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": self.operation_kind,
                "head": self.head.as_payload(),
                "validation_run_id": self.validation_run_id,
                "validation_issue_id": self.validation_issue_id,
                "issue_severity": self.issue_severity,
                "issue_requires_note": self.issue_requires_note,
                "action": self.action,
                "comment": self.comment,
                "actor_user_id": self.actor_user_id,
            }
        )


def _canonical_totals(
    values: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    canonical: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_name, raw_value in values:
        name = _nonblank(raw_name, "total field_name")
        value = _nonblank(raw_value, "total value")
        if name in seen:
            raise ValueError("confirmed_totals contain a duplicate field")
        seen.add(name)
        canonical.append((name, value))
    return tuple(sorted(canonical))


@dataclass(frozen=True, slots=True)
class MarkReadyCommand:
    head: DraftHeadExpectation
    validation_run_id: int
    validation_data_digest: bytes
    ruleset_version: str
    confirmed_report_date: date
    confirmed_report_type: ReportType
    confirmed_row_count: int
    confirmed_totals: tuple[tuple[str, str], ...]
    actor_user_id: int
    operation_token: UUID
    reason: str

    operation_kind: Literal["mark_ready"] = "mark_ready"

    def __post_init__(self) -> None:
        if not isinstance(self.head, DraftHeadExpectation):
            raise ValueError("head is required")
        if self.head.status != "draft":
            raise ValueError("only a draft can be marked ready")
        _positive(self.validation_run_id, "validation_run_id")
        digest = bytes(self.validation_data_digest)
        if len(digest) != 32:
            raise ValueError("validation_data_digest must contain 32 bytes")
        object.__setattr__(self, "validation_data_digest", digest)
        object.__setattr__(
            self,
            "ruleset_version",
            _nonblank(self.ruleset_version, "ruleset_version"),
        )
        if type(self.confirmed_report_date) is not date:
            raise ValueError("confirmed_report_date must be a date")
        if self.confirmed_report_type not in {"business_report", "return_report"}:
            raise ValueError("confirmed_report_type is not supported")
        _nonnegative(self.confirmed_row_count, "confirmed_row_count")
        object.__setattr__(
            self,
            "confirmed_totals",
            _canonical_totals(self.confirmed_totals),
        )
        _actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", _nonblank(self.reason, "reason"))

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": self.operation_kind,
                "head": self.head.as_payload(),
                "validation_run_id": self.validation_run_id,
                "validation_data_digest": self.validation_data_digest.hex(),
                "ruleset_version": self.ruleset_version,
                "confirmed_report_date": self.confirmed_report_date.isoformat(),
                "confirmed_report_type": self.confirmed_report_type,
                "confirmed_row_count": self.confirmed_row_count,
                "confirmed_totals": self.confirmed_totals,
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class ReturnToDraftCommand:
    head: DraftHeadExpectation
    actor_user_id: int
    operation_token: UUID
    reason: str

    operation_kind: Literal["return_to_draft"] = "return_to_draft"

    def __post_init__(self) -> None:
        if not isinstance(self.head, DraftHeadExpectation):
            raise ValueError("head is required")
        if self.head.status != "ready_for_publish":
            raise ValueError("only a ready version can return to draft")
        _actor_and_token(self.actor_user_id, self.operation_token)
        object.__setattr__(self, "reason", _nonblank(self.reason, "reason"))

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": self.operation_kind,
                "head": self.head.as_payload(),
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class ReviewMutationResult:
    """Frozen first result recovered through a review operation token."""

    operation_token: UUID
    operation_kind: str
    dataset_id: int | None
    version_id: int | None
    status: EditableVersionStatus | None
    data_revision: int | None
    review_revision: int | None
    import_batch_id: int | None = None
    affected_row_id: int | None = None
    data_change_event_id: int | None = None
    issue_review_event_id: int | None = None
    validation_run_id: int | None = None
    version_review_event_id: int | None = None
    note_id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation_token, UUID):
            raise ValueError("operation_token must be a UUID")
        object.__setattr__(
            self,
            "operation_kind",
            _nonblank(self.operation_kind, "operation_kind"),
        )
        version_fields = (
            self.dataset_id,
            self.version_id,
            self.status,
            self.data_revision,
            self.review_revision,
        )
        if any(value is None for value in version_fields) and not all(
            value is None for value in version_fields
        ):
            raise ValueError("version result fields must be all present or all absent")
        if self.dataset_id is not None:
            _positive(self.dataset_id, "dataset_id")
            _positive(cast(int, self.version_id), "version_id")
            if self.status not in _EDITABLE_STATUSES:
                raise ValueError("result status must be editable")
            _nonnegative(cast(int, self.data_revision), "data_revision")
            _nonnegative(cast(int, self.review_revision), "review_revision")
        if self.import_batch_id is not None:
            _positive(self.import_batch_id, "import_batch_id")
        if (self.import_batch_id is None) == (self.dataset_id is None):
            raise ValueError(
                "result must identify exactly one import batch or dataset version"
            )
        if self.import_batch_id is not None and any(
            value is not None
            for value in (
                self.affected_row_id,
                self.data_change_event_id,
                self.issue_review_event_id,
                self.validation_run_id,
                self.version_review_event_id,
            )
        ):
            raise ValueError("batch note result cannot contain version event fields")
        for field_name in (
            "affected_row_id",
            "data_change_event_id",
            "issue_review_event_id",
            "validation_run_id",
            "version_review_event_id",
            "note_id",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _positive(value, field_name)
