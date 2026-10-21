"""Composition of parse-fidelity and draft-replay validation for one full run."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.imports.types import ReportType

from .fidelity import ParseFidelityEvidence, validate_parse_fidelity
from .replay import DraftReplayEvidence, replay_draft_changes
from .types import (
    EditableVersionStatus,
    StageValidationResult,
    ValidationIssue,
    ValidationRunResult,
    ValidationSummary,
    ValidationSummaryStage,
)


@dataclass(frozen=True, slots=True)
class ParseFidelityInput:
    import_batch_id: int
    parse_attempt_id: int
    parse_baseline_id: int
    evidence: ParseFidelityEvidence

    def __post_init__(self) -> None:
        for name, value in (
            ("import_batch_id", self.import_batch_id),
            ("parse_attempt_id", self.parse_attempt_id),
            ("parse_baseline_id", self.parse_baseline_id),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be positive")
        if not isinstance(self.evidence, ParseFidelityEvidence):
            raise ValueError("parse fidelity evidence is required")


@dataclass(frozen=True, slots=True)
class FullValidationEvidence:
    dataset_id: int
    version_id: int
    version_status: EditableVersionStatus
    data_revision: int
    review_revision: int
    report_date: date
    report_type: ReportType
    ruleset_version: str
    parse_inputs: tuple[ParseFidelityInput, ...]
    draft: DraftReplayEvidence

    def __post_init__(self) -> None:
        for name, value in (
            ("dataset_id", self.dataset_id),
            ("version_id", self.version_id),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be positive")
        for name, value in (
            ("data_revision", self.data_revision),
            ("review_revision", self.review_revision),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.version_status not in {"draft", "ready_for_publish"}:
            raise ValueError("version_status must be editable")
        if not isinstance(self.report_date, date):
            raise ValueError("report_date must be a date")
        if self.report_type not in {"business_report", "return_report"}:
            raise ValueError("report_type is not supported")
        if (
            not self.ruleset_version
            or self.ruleset_version != self.ruleset_version.strip()
        ):
            raise ValueError("ruleset_version must be normalised")
        if self.draft.report_type != self.report_type:
            raise ValueError("draft evidence report type differs from the version")
        if self.draft.ruleset_version != self.ruleset_version:
            raise ValueError("draft evidence ruleset differs from the version")
        if self.draft.data_revision != self.data_revision:
            raise ValueError("draft evidence revision differs from the version")
        if any(
            item.evidence.report_type != self.report_type for item in self.parse_inputs
        ):
            raise ValueError("parse evidence report type differs from the version")


@dataclass(frozen=True, slots=True)
class PersistableValidationIssue:
    issue: ValidationIssue
    version_row_id: int | None = None
    import_batch_id: int | None = None
    parse_attempt_id: int | None = None
    parsed_source_row_id: int | None = None
    parse_baseline_id: int | None = None
    parse_baseline_row_id: int | None = None


@dataclass(frozen=True, slots=True)
class FullValidationEvaluation:
    result: ValidationRunResult
    summary: ValidationSummary
    issues: tuple[PersistableValidationIssue, ...]


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _combined_totals(
    results: tuple[StageValidationResult, ...],
) -> tuple[tuple[str, str], ...]:
    combined: dict[str, Decimal] = {}
    for result in results:
        for name, value in result.totals:
            combined[name] = combined.get(name, Decimal(0)) + Decimal(value)
    return tuple(
        (name, _canonical_decimal(value)) for name, value in sorted(combined.items())
    )


def _parse_stage_digest(
    inputs: tuple[ParseFidelityInput, ...],
    results: tuple[StageValidationResult, ...],
) -> str:
    payload = [
        {
            "import_batch_id": item.import_batch_id,
            "parse_attempt_id": item.parse_attempt_id,
            "parse_baseline_id": item.parse_baseline_id,
            "data_digest": result.data_digest,
            "row_count": result.row_count,
            "totals": dict(result.totals),
        }
        for item, result in zip(inputs, results, strict=True)
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _parse_issue_lineage(
    item: ParseFidelityInput,
    issue: ValidationIssue,
    *,
    version_row_ids_by_baseline_row: dict[int, int],
    version_row_ids_by_source_row: dict[int, int],
) -> PersistableValidationIssue:
    baseline_by_id = {row.baseline_row_id: row for row in item.evidence.baseline_rows}
    source_by_number = {
        row.source_row_number: row.source_row_id for row in item.evidence.source_rows
    }
    issue_row_id = issue.row_id
    baseline_row = (
        baseline_by_id.get(issue_row_id) if issue_row_id is not None else None
    )
    issue_source_row_number = issue.source_row_number
    parsed_source_row_id = (
        baseline_row.source_row_id
        if baseline_row is not None
        else (
            source_by_number.get(issue_source_row_number)
            if issue_source_row_number is not None
            else None
        )
    )
    return PersistableValidationIssue(
        issue=issue,
        # ``validation_issues.row_id`` is constrained to a row in the version
        # being validated.  Parse-fidelity issues are expressed in immutable
        # baseline IDs, so translate their baseline lineage back to the
        # corresponding materialised version row before persisting them.
        version_row_id=(
            version_row_ids_by_baseline_row.get(baseline_row.baseline_row_id)
            if baseline_row is not None
            else (
                version_row_ids_by_source_row.get(parsed_source_row_id)
                if parsed_source_row_id is not None
                else None
            )
        ),
        import_batch_id=item.import_batch_id,
        parse_attempt_id=item.parse_attempt_id,
        parsed_source_row_id=parsed_source_row_id,
        parse_baseline_id=item.parse_baseline_id,
        parse_baseline_row_id=(
            baseline_row.baseline_row_id if baseline_row is not None else None
        ),
    )


def _summary_stage(result: StageValidationResult) -> ValidationSummaryStage:
    return ValidationSummaryStage(
        data_digest=result.data_digest,
        row_count=result.row_count,
        totals=result.totals,
        warning_count=result.warning_count,
        blocking_count=result.blocking_count,
    )


def evaluate_full_validation(
    evidence: FullValidationEvidence,
) -> FullValidationEvaluation:
    """Run both pure stages and freeze their publication-facing summary."""

    parse_results = tuple(
        validate_parse_fidelity(item.evidence) for item in evidence.parse_inputs
    )
    baseline_row_to_version_rows: dict[int, list[int]] = {}
    source_row_to_version_rows: dict[int, list[int]] = {}
    for row in evidence.draft.current_rows:
        baseline_row_id = row.parse_baseline_row_id
        if baseline_row_id is not None:
            baseline_row_to_version_rows.setdefault(baseline_row_id, []).append(
                row.row_id
            )
        source_row_id = row.source_parse_baseline_row_id
        if source_row_id is not None:
            source_row_to_version_rows.setdefault(source_row_id, []).append(row.row_id)
    # Do not manufacture a row association if malformed draft evidence maps a
    # source row to more than one current row.  Replay validation reports that
    # condition independently; keeping this nullable preserves the audit
    # record while satisfying the version-scoped foreign key.
    version_row_ids_by_baseline_row = {
        baseline_row_id: row_ids[0]
        for baseline_row_id, row_ids in baseline_row_to_version_rows.items()
        if len(row_ids) == 1
    }
    version_row_ids_by_source_row = {
        source_row_id: row_ids[0]
        for source_row_id, row_ids in source_row_to_version_rows.items()
        if len(row_ids) == 1
    }
    parse_issues = tuple(
        _parse_issue_lineage(
            item,
            issue,
            version_row_ids_by_baseline_row=version_row_ids_by_baseline_row,
            version_row_ids_by_source_row=version_row_ids_by_source_row,
        )
        for item, result in zip(evidence.parse_inputs, parse_results, strict=True)
        for issue in result.issues
    )
    combined_parse = StageValidationResult(
        stage="parse_fidelity",
        data_digest=_parse_stage_digest(evidence.parse_inputs, parse_results),
        row_count=sum(result.row_count for result in parse_results),
        totals=_combined_totals(parse_results),
        issues=tuple(issue.issue for issue in parse_issues),
    )

    replay = replay_draft_changes(evidence.draft)
    draft_issues = tuple(
        PersistableValidationIssue(issue=issue, version_row_id=issue.row_id)
        for issue in replay.issues
    )
    result = ValidationRunResult(
        version_id=evidence.version_id,
        data_revision=evidence.data_revision,
        ruleset_version=evidence.ruleset_version,
        parse_fidelity=combined_parse,
        draft_explainability=replay.validation,
        data_digest=replay.validation.data_digest,
    )
    active_row_count = sum(row.row_state == "active" for row in replay.rows)
    current_totals = tuple(
        (name, _canonical_decimal(value)) for name, value in replay.current_totals
    )
    summary = ValidationSummary(
        report_date=evidence.report_date,
        report_type=evidence.report_type,
        row_count=active_row_count,
        totals=current_totals,
        parse_fidelity=_summary_stage(combined_parse),
        draft_explainability=_summary_stage(replay.validation),
    )
    return FullValidationEvaluation(
        result=result,
        summary=summary,
        issues=parse_issues + draft_issues,
    )
