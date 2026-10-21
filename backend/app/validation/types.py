"""Immutable result types shared by pure validation stages and publication gates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, cast
from uuid import UUID

from app.imports.types import ReportType

from .fields import FieldValue

type ValidationStage = Literal["parse_fidelity", "draft_explainability"]
type ValidationSeverity = Literal["warning", "blocking"]
type PublicationIneligibilityReason = Literal[
    "validation_failed",
    "stale_data_revision",
    "stale_ruleset_version",
    "unacknowledged_warnings",
    "missing_required_notes",
]
type EditableVersionStatus = Literal["draft", "ready_for_publish"]
type ValidationRunStatus = Literal["succeeded", "failed"]
type ValidationRunOutcome = Literal["passed", "failed", "error"]


class ValidationPersistenceError(RuntimeError):
    """Base class for expected validation persistence failures."""


class ValidationPermissionDenied(ValidationPersistenceError):
    """The actor cannot run validation for an editable draft."""


class ValidationVersionConflict(ValidationPersistenceError):
    """The selected active version, revision, or ruleset changed."""


class ValidationOperationConflict(ValidationPersistenceError):
    """A global operation token is already bound to another command."""


class ValidationCommitOutcomeUnknown(ValidationPersistenceError):
    """Commit acknowledgement was lost without a recoverable terminal result."""


class ValidationTransactionBusy(ValidationPersistenceError):
    """MySQL locks remained unavailable after the bounded retry policy."""


class ValidationEvidenceError(ValidationPersistenceError):
    """Persisted evidence cannot be decoded without inventing data."""


def _nonnegative(value: int, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def _digest(value: str, name: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        bytes.fromhex(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from error


def _positive(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be positive")


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalised = value.strip()
    if not normalised:
        raise ValueError(f"{name} must not be blank")
    return normalised


def _utc_datetime(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    if value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _canonical_digest(payload: object) -> bytes:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).digest()


def _summary_totals(
    values: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    names = tuple(name for name, _value in values)
    if len(names) != len(set(names)):
        raise ValueError("summary totals must have unique names")
    canonical: list[tuple[str, str]] = []
    for name, value in values:
        field_name = _nonblank(name, "summary total name")
        if not isinstance(value, str):
            raise ValueError("summary total value must be text")
        try:
            decimal_value = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("summary total value must be decimal text") from error
        if not decimal_value.is_finite():
            raise ValueError("summary total value must be finite")
        canonical.append((field_name, value))
    return tuple(sorted(canonical))


def _payload_mapping(payload: object, name: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{name} must be an object")
    if not all(isinstance(key, str) for key in payload):
        raise ValueError(f"{name} keys must be text")
    return cast(Mapping[str, object], payload)


def _payload_integer(payload: object, name: str) -> int:
    if not isinstance(payload, int) or isinstance(payload, bool) or payload < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return payload


def _payload_totals(payload: object, name: str) -> tuple[tuple[str, str], ...]:
    mapping = _payload_mapping(payload, name)
    if not all(isinstance(value, str) for value in mapping.values()):
        raise ValueError(f"{name} values must be text")
    return tuple((key, cast(str, value)) for key, value in sorted(mapping.items()))


@dataclass(frozen=True, slots=True)
class RunValidationCommand:
    dataset_id: int
    version_id: int
    data_revision: int
    ruleset_version: str
    actor_user_id: int
    operation_token: UUID

    operation_kind: Literal["run_validation"] = "run_validation"

    def __post_init__(self) -> None:
        _positive(self.dataset_id, "dataset_id")
        _positive(self.version_id, "version_id")
        _nonnegative(self.data_revision, "data_revision")
        object.__setattr__(
            self,
            "ruleset_version",
            _nonblank(self.ruleset_version, "ruleset_version"),
        )
        _positive(self.actor_user_id, "actor_user_id")
        if not isinstance(self.operation_token, UUID):
            raise ValueError("operation_token must be a UUID")

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": self.operation_kind,
                "dataset_id": self.dataset_id,
                "version_id": self.version_id,
                "data_revision": self.data_revision,
                "ruleset_version": self.ruleset_version,
                "actor_user_id": self.actor_user_id,
            }
        )


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    stage: ValidationStage
    code: str
    severity: ValidationSeverity
    message: str
    requires_note: bool
    source_row_number: int | None = None
    row_id: int | None = None
    field_name: str | None = None
    source_value: FieldValue = None
    processed_value: FieldValue = None

    def __post_init__(self) -> None:
        if not self.code or self.code != self.code.strip():
            raise ValueError("validation issue code must be normalised")
        if not self.message or not self.message.strip():
            raise ValueError("validation issue message must not be blank")
        if self.source_row_number is not None and self.source_row_number < 1:
            raise ValueError("source_row_number must be positive")
        if self.row_id is not None and self.row_id < 1:
            raise ValueError("row_id must be positive")
        if self.field_name is not None and not self.field_name:
            raise ValueError("field_name must not be blank")


@dataclass(frozen=True, slots=True)
class StageValidationResult:
    stage: ValidationStage
    data_digest: str
    row_count: int
    totals: tuple[tuple[str, str], ...]
    issues: tuple[ValidationIssue, ...]

    def __post_init__(self) -> None:
        _digest(self.data_digest, "data_digest")
        _nonnegative(self.row_count, "row_count")
        names = tuple(name for name, _value in self.totals)
        if len(names) != len(set(names)):
            raise ValueError("validation totals must have unique names")
        if any(issue.stage != self.stage for issue in self.issues):
            raise ValueError("validation issue belongs to another stage")

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "blocking" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)

    @property
    def blocking_count(self) -> int:
        return sum(issue.severity == "blocking" for issue in self.issues)


@dataclass(frozen=True, slots=True)
class ValidationRunResult:
    version_id: int
    data_revision: int
    ruleset_version: str
    parse_fidelity: StageValidationResult
    draft_explainability: StageValidationResult
    data_digest: str

    def __post_init__(self) -> None:
        if self.version_id < 1:
            raise ValueError("version_id must be positive")
        _nonnegative(self.data_revision, "data_revision")
        if (
            not self.ruleset_version
            or self.ruleset_version != self.ruleset_version.strip()
        ):
            raise ValueError("ruleset_version must be normalised")
        if self.parse_fidelity.stage != "parse_fidelity":
            raise ValueError("parse_fidelity result has the wrong stage")
        if self.draft_explainability.stage != "draft_explainability":
            raise ValueError("draft_explainability result has the wrong stage")
        _digest(self.data_digest, "data_digest")

    @property
    def passed(self) -> bool:
        return self.parse_fidelity.passed and self.draft_explainability.passed

    @property
    def warning_count(self) -> int:
        return (
            self.parse_fidelity.warning_count + self.draft_explainability.warning_count
        )

    @property
    def blocking_count(self) -> int:
        return (
            self.parse_fidelity.blocking_count
            + self.draft_explainability.blocking_count
        )


@dataclass(frozen=True, slots=True)
class ValidationSummaryStage:
    data_digest: str
    row_count: int
    totals: tuple[tuple[str, str], ...]
    warning_count: int
    blocking_count: int

    def __post_init__(self) -> None:
        _digest(self.data_digest, "stage data_digest")
        _nonnegative(self.row_count, "stage row_count")
        _nonnegative(self.warning_count, "stage warning_count")
        _nonnegative(self.blocking_count, "stage blocking_count")
        object.__setattr__(self, "totals", _summary_totals(self.totals))

    def as_payload(self) -> dict[str, object]:
        return {
            "data_digest": self.data_digest,
            "row_count": self.row_count,
            "totals": dict(self.totals),
            "warning_count": self.warning_count,
            "blocking_count": self.blocking_count,
        }

    @classmethod
    def from_payload(cls, payload: object) -> ValidationSummaryStage:
        mapping = _payload_mapping(payload, "validation summary stage")
        expected = {
            "data_digest",
            "row_count",
            "totals",
            "warning_count",
            "blocking_count",
        }
        if set(mapping) != expected:
            raise ValueError("validation summary stage has an invalid shape")
        data_digest = mapping["data_digest"]
        if not isinstance(data_digest, str):
            raise ValueError("stage data_digest must be text")
        return cls(
            data_digest=data_digest,
            row_count=_payload_integer(mapping["row_count"], "stage row_count"),
            totals=_payload_totals(mapping["totals"], "stage totals"),
            warning_count=_payload_integer(
                mapping["warning_count"],
                "stage warning_count",
            ),
            blocking_count=_payload_integer(
                mapping["blocking_count"],
                "stage blocking_count",
            ),
        )


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    report_date: date
    report_type: ReportType
    row_count: int
    totals: tuple[tuple[str, str], ...]
    parse_fidelity: ValidationSummaryStage
    draft_explainability: ValidationSummaryStage

    schema_version: Literal[1] = 1

    def __post_init__(self) -> None:
        if not isinstance(self.report_date, date) or isinstance(
            self.report_date,
            datetime,
        ):
            raise ValueError("report_date must be a date")
        if self.report_type not in {"business_report", "return_report"}:
            raise ValueError("report_type is not supported")
        _nonnegative(self.row_count, "row_count")
        object.__setattr__(self, "totals", _summary_totals(self.totals))
        if not isinstance(self.parse_fidelity, ValidationSummaryStage):
            raise ValueError("parse_fidelity summary is required")
        if not isinstance(self.draft_explainability, ValidationSummaryStage):
            raise ValueError("draft_explainability summary is required")

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_date": self.report_date.isoformat(),
            "report_type": self.report_type,
            "row_count": self.row_count,
            "totals": dict(self.totals),
            "stages": {
                "parse_fidelity": self.parse_fidelity.as_payload(),
                "draft_explainability": self.draft_explainability.as_payload(),
            },
        }

    @classmethod
    def from_payload(cls, payload: object) -> ValidationSummary:
        mapping = _payload_mapping(payload, "validation summary")
        expected = {
            "schema_version",
            "report_date",
            "report_type",
            "row_count",
            "totals",
            "stages",
        }
        if set(mapping) != expected or mapping["schema_version"] != 1:
            raise ValueError("validation summary has an invalid v1 shape")
        raw_date = mapping["report_date"]
        if not isinstance(raw_date, str):
            raise ValueError("validation summary report_date must be text")
        try:
            report_date = date.fromisoformat(raw_date)
        except ValueError as error:
            raise ValueError("validation summary report_date is invalid") from error
        report_type = mapping["report_type"]
        if report_type not in {"business_report", "return_report"}:
            raise ValueError("validation summary report_type is invalid")
        stages = _payload_mapping(mapping["stages"], "validation summary stages")
        if set(stages) != {"parse_fidelity", "draft_explainability"}:
            raise ValueError("validation summary stages have an invalid shape")
        return cls(
            report_date=report_date,
            report_type=cast(ReportType, report_type),
            row_count=_payload_integer(mapping["row_count"], "row_count"),
            totals=_payload_totals(mapping["totals"], "totals"),
            parse_fidelity=ValidationSummaryStage.from_payload(
                stages["parse_fidelity"]
            ),
            draft_explainability=ValidationSummaryStage.from_payload(
                stages["draft_explainability"]
            ),
        )


@dataclass(frozen=True, slots=True)
class ValidationRunReceipt:
    operation_token: UUID
    validation_run_id: int
    dataset_id: int
    version_id: int
    version_status: EditableVersionStatus
    data_revision: int
    review_revision: int
    ruleset_version: str
    status: ValidationRunStatus
    result: ValidationRunOutcome
    data_digest: bytes
    summary: ValidationSummary
    completed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.operation_token, UUID):
            raise ValueError("operation_token must be a UUID")
        _positive(self.validation_run_id, "validation_run_id")
        _positive(self.dataset_id, "dataset_id")
        _positive(self.version_id, "version_id")
        if self.version_status not in {"draft", "ready_for_publish"}:
            raise ValueError("version_status must be editable")
        _nonnegative(self.data_revision, "data_revision")
        _nonnegative(self.review_revision, "review_revision")
        object.__setattr__(
            self,
            "ruleset_version",
            _nonblank(self.ruleset_version, "ruleset_version"),
        )
        if (self.status == "succeeded" and self.result not in {"passed", "failed"}) or (
            self.status == "failed" and self.result != "error"
        ):
            raise ValueError("validation status and result are inconsistent")
        digest = bytes(self.data_digest)
        if len(digest) != 32:
            raise ValueError("data_digest must contain 32 bytes")
        object.__setattr__(self, "data_digest", digest)
        if not isinstance(self.summary, ValidationSummary):
            raise ValueError("summary is required")
        object.__setattr__(
            self,
            "completed_at",
            _utc_datetime(self.completed_at, "completed_at"),
        )


@dataclass(frozen=True, slots=True)
class PublicationEligibility:
    validation: ValidationRunResult
    current_data_revision: int
    current_ruleset_version: str
    unacknowledged_warning_count: int
    missing_required_note_count: int

    def __post_init__(self) -> None:
        _nonnegative(self.current_data_revision, "current_data_revision")
        _nonnegative(
            self.unacknowledged_warning_count,
            "unacknowledged_warning_count",
        )
        _nonnegative(self.missing_required_note_count, "missing_required_note_count")
        if not self.current_ruleset_version:
            raise ValueError("current_ruleset_version must not be blank")

    @property
    def reasons(self) -> tuple[PublicationIneligibilityReason, ...]:
        reasons: list[PublicationIneligibilityReason] = []
        if not self.validation.passed:
            reasons.append("validation_failed")
        if self.validation.data_revision != self.current_data_revision:
            reasons.append("stale_data_revision")
        if self.validation.ruleset_version != self.current_ruleset_version:
            reasons.append("stale_ruleset_version")
        if self.unacknowledged_warning_count:
            reasons.append("unacknowledged_warnings")
        if self.missing_required_note_count:
            reasons.append("missing_required_notes")
        return tuple(reasons)

    @property
    def eligible(self) -> bool:
        return not self.reasons
