"""Pure source-row to typed-baseline fidelity reconciliation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields

from app.imports.types import ReportType
from app.parsers.parser import PARSER_VERSION, parse_decoded_report
from app.parsers.rules import REPORT_RULES
from app.parsers.types import FieldKind, ParsedRow, ParseError, ParseSettings

from .fields import (
    FieldValue,
    FieldValueError,
    as_field_value,
    get_report_field_contract,
    validate_row_values,
)
from .types import StageValidationResult, ValidationIssue


class UnsupportedFidelityContract(RuntimeError):
    """The historical parser/ruleset implementation is not available."""


@dataclass(frozen=True, slots=True)
class SourceRowEvidence:
    source_row_id: int
    source_row_number: int
    raw_values: tuple[str, ...]
    row_digest: str


@dataclass(frozen=True, slots=True)
class BaselineRowEvidence:
    baseline_row_id: int
    source_row_id: int
    row_ordinal: int
    values: tuple[tuple[str, object], ...]
    row_digest: str


@dataclass(frozen=True, slots=True)
class SourceFieldMappingEvidence:
    source_name: str
    target_name: str
    kind: FieldKind


@dataclass(frozen=True, slots=True)
class FieldMappingEvidence:
    source_header: tuple[str, ...]
    fields: tuple[SourceFieldMappingEvidence, ...]


@dataclass(frozen=True, slots=True)
class ParseFidelityEvidence:
    report_type: ReportType
    parser_version: str
    ruleset_version: str
    settings: ParseSettings
    header: tuple[str, ...]
    source_rows: tuple[SourceRowEvidence, ...]
    baseline_rows: tuple[BaselineRowEvidence, ...]
    field_mapping: FieldMappingEvidence
    stored_source_row_count: int
    stored_baseline_row_count: int
    stored_totals: tuple[tuple[str, str], ...]
    stored_data_digest: str


def _issue(
    code: str,
    message: str,
    *,
    source_row_number: int | None = None,
    row_id: int | None = None,
    field_name: str | None = None,
    source_value: FieldValue = None,
    processed_value: FieldValue = None,
) -> ValidationIssue:
    return ValidationIssue(
        stage="parse_fidelity",
        code=code,
        severity="blocking",
        message=message,
        requires_note=False,
        source_row_number=source_row_number,
        row_id=row_id,
        field_name=field_name,
        source_value=source_value,
        processed_value=processed_value,
    )


def _typed_values(row: ParsedRow) -> tuple[tuple[str, FieldValue], ...]:
    return tuple(
        (field.name, as_field_value(getattr(row, field.name)))
        for field in dataclass_fields(row)
        if field.name not in {"source", "typed_digest"}
    )


def _fallback_digest(evidence: ParseFidelityEvidence) -> str:
    payload = {
        "header": evidence.header,
        "rows": [
            {
                "source_row_number": row.source_row_number,
                "raw_values": row.raw_values,
            }
            for row in evidence.source_rows
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_supported(evidence: ParseFidelityEvidence) -> None:
    if evidence.settings.report_type != evidence.report_type:
        raise UnsupportedFidelityContract(
            "parse settings report type differs from fidelity evidence"
        )
    expected_rule = REPORT_RULES.get(evidence.report_type)
    if expected_rule is None:
        raise UnsupportedFidelityContract("report type is not supported")
    if evidence.parser_version != PARSER_VERSION:
        raise UnsupportedFidelityContract(
            f"parser version {evidence.parser_version!r} is not registered"
        )
    if evidence.ruleset_version != expected_rule.version:
        raise UnsupportedFidelityContract(
            f"ruleset version {evidence.ruleset_version!r} is not registered"
        )
    get_report_field_contract(evidence.report_type, evidence.ruleset_version)


def validate_parse_fidelity(
    evidence: ParseFidelityEvidence,
) -> StageValidationResult:
    """Re-run the frozen conversion and compare every persisted evidence layer."""

    _assert_supported(evidence)
    issues: list[ValidationIssue] = []
    source_rows = tuple(
        sorted(
            evidence.source_rows,
            key=lambda row: (row.source_row_number, row.source_row_id),
        )
    )
    baseline_rows = tuple(
        sorted(
            evidence.baseline_rows,
            key=lambda row: (row.row_ordinal, row.baseline_row_id),
        )
    )

    source_ids = tuple(row.source_row_id for row in source_rows)
    baseline_ids = tuple(row.baseline_row_id for row in baseline_rows)
    baseline_source_ids = tuple(row.source_row_id for row in baseline_rows)
    if len(source_ids) != len(set(source_ids)):
        issues.append(_issue("parse.duplicate_source_row", "source row IDs repeat"))
    if len(baseline_ids) != len(set(baseline_ids)):
        issues.append(_issue("parse.duplicate_baseline_row", "baseline row IDs repeat"))
    if len(baseline_source_ids) != len(set(baseline_source_ids)):
        issues.append(
            _issue(
                "parse.duplicate_baseline_source",
                "multiple baseline rows reference the same source row",
            )
        )

    if evidence.stored_source_row_count != len(source_rows):
        issues.append(
            _issue(
                "parse.attempt_source_count_mismatch",
                "parse attempt source count differs from persisted source rows",
            )
        )
    if evidence.stored_baseline_row_count != len(baseline_rows):
        issues.append(
            _issue(
                "parse.baseline_row_count_mismatch",
                "parse baseline count differs from persisted typed rows",
            )
        )
    if len(source_rows) != len(baseline_rows):
        issues.append(
            _issue(
                "parse.source_baseline_count_mismatch",
                "persisted source and typed baseline row counts differ",
            )
        )

    expected_numbers = tuple(range(2, 2 + len(source_rows)))
    if tuple(row.source_row_number for row in source_rows) != expected_numbers:
        issues.append(
            _issue(
                "parse.source_row_number_mismatch",
                "source row numbers are not contiguous from the CSV header",
            )
        )
    expected_ordinals = tuple(range(1, 1 + len(baseline_rows)))
    if tuple(row.row_ordinal for row in baseline_rows) != expected_ordinals:
        issues.append(
            _issue(
                "parse.baseline_ordinal_mismatch",
                "baseline row ordinals are not contiguous",
            )
        )
    if baseline_source_ids != source_ids:
        issues.append(
            _issue(
                "parse.baseline_source_order_mismatch",
                "baseline ordinal does not follow persisted source row order",
            )
        )

    expected_mapping = FieldMappingEvidence(
        source_header=evidence.header,
        fields=tuple(
            SourceFieldMappingEvidence(
                source_name=field.source_name,
                target_name=field.target_name,
                kind=field.kind,
            )
            for field in REPORT_RULES[evidence.report_type].fields
        ),
    )
    if evidence.field_mapping != expected_mapping:
        issues.append(
            _issue(
                "parse.field_mapping_mismatch",
                "persisted field mapping differs from the frozen parser rule",
            )
        )

    try:
        reparsed = parse_decoded_report(
            evidence.header,
            tuple(row.raw_values for row in source_rows),
            evidence.settings,
        )
    except ParseError as error:
        issues.append(
            _issue(
                "parse.reconversion_failed",
                f"persisted source snapshot no longer satisfies its parser contract: "
                f"{error.code}",
                source_row_number=error.source_row_number,
                field_name=error.field_name,
            )
        )
        return StageValidationResult(
            stage="parse_fidelity",
            data_digest=_fallback_digest(evidence),
            row_count=len(source_rows),
            totals=(),
            issues=tuple(issues),
        )

    baseline_by_source = {row.source_row_id: row for row in baseline_rows}
    source_id_set = set(source_ids)
    for source, calculated_source, calculated_row in zip(
        source_rows,
        reparsed.source_rows,
        reparsed.rows,
        strict=True,
    ):
        if source.row_digest != calculated_source.row_digest:
            issues.append(
                _issue(
                    "parse.source_digest_mismatch",
                    "persisted source row digest does not match decoded fields",
                    source_row_number=source.source_row_number,
                    source_value=source.row_digest,
                    processed_value=calculated_source.row_digest,
                )
            )
        baseline = baseline_by_source.get(source.source_row_id)
        if baseline is None:
            issues.append(
                _issue(
                    "parse.missing_baseline_row",
                    "source row has no corresponding typed baseline row",
                    source_row_number=source.source_row_number,
                )
            )
            continue
        try:
            stored_values = validate_row_values(
                evidence.report_type,
                evidence.ruleset_version,
                baseline.values,
                require_all=True,
            )
        except FieldValueError as error:
            issues.append(
                _issue(
                    "parse.invalid_baseline_value",
                    f"baseline row cannot satisfy its typed contract: {error}",
                    source_row_number=source.source_row_number,
                    row_id=baseline.baseline_row_id,
                )
            )
            continue
        calculated_values = dict(_typed_values(calculated_row))
        for field_name, stored_value in stored_values:
            calculated_value = calculated_values[field_name]
            if stored_value != calculated_value:
                issues.append(
                    _issue(
                        "parse.value_mismatch",
                        "typed baseline value differs from deterministic conversion",
                        source_row_number=source.source_row_number,
                        row_id=baseline.baseline_row_id,
                        field_name=field_name,
                        source_value=calculated_value,
                        processed_value=stored_value,
                    )
                )
        if baseline.row_digest != calculated_row.typed_digest:
            issues.append(
                _issue(
                    "parse.typed_digest_mismatch",
                    "typed baseline row digest does not match converted values",
                    source_row_number=source.source_row_number,
                    row_id=baseline.baseline_row_id,
                    source_value=calculated_row.typed_digest,
                    processed_value=baseline.row_digest,
                )
            )

    for baseline in baseline_rows:
        if baseline.source_row_id not in source_id_set:
            issues.append(
                _issue(
                    "parse.extra_baseline_row",
                    "typed baseline row references no persisted source row",
                    row_id=baseline.baseline_row_id,
                )
            )

    if tuple(evidence.stored_totals) != reparsed.summary.totals:
        issues.append(
            _issue(
                "parse.total_mismatch",
                "stored baseline totals differ from deterministic conversion",
            )
        )
    if evidence.stored_data_digest != reparsed.summary.data_digest:
        issues.append(
            _issue(
                "parse.data_digest_mismatch",
                "stored baseline digest differs from deterministic conversion",
                source_value=reparsed.summary.data_digest,
                processed_value=evidence.stored_data_digest,
            )
        )

    return StageValidationResult(
        stage="parse_fidelity",
        data_digest=reparsed.summary.data_digest,
        row_count=reparsed.summary.row_count,
        totals=reparsed.summary.totals,
        issues=tuple(issues),
    )
