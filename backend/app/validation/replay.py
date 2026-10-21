"""Pure replay of append-only draft changes against an immutable base snapshot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from app.imports.types import ReportType

from .codec import encode_field_value
from .fields import (
    FieldValue,
    FieldValueError,
    as_field_value,
    get_field_contract,
    get_report_field_contract,
    validate_added_row_values,
    validate_field_value,
    validate_row_values,
)
from .types import StageValidationResult, ValidationIssue

type RowState = Literal["active", "excluded", "deleted"]
type FieldOperation = Literal[
    "set",
    "restore_source",
    "restore_parent",
    "restore_previous",
]
type RowOperation = Literal["add", "exclude", "restore", "delete"]
type EventKind = Literal["field", "row"]
type RestoreValueKind = Literal["previous", "parent", "source"]

_ROW_STATES = frozenset({"active", "excluded", "deleted"})
_FIELD_OPERATIONS = frozenset(
    {"set", "restore_source", "restore_parent", "restore_previous"}
)
_ROW_OPERATIONS = frozenset({"add", "exclude", "restore", "delete"})
_RESTORE_VALUE_KINDS = frozenset({"previous", "parent", "source"})


@dataclass(frozen=True, slots=True)
class DraftRow:
    row_id: int
    logical_row_id: UUID
    row_ordinal: int
    row_state: RowState
    values: tuple[tuple[str, object], ...]
    base_row_id: int | None
    source_parse_baseline_row_id: int | None
    source_batch_id: int | None
    # The source row ID is retained in source_parse_baseline_row_id for the
    # existing draft-event contract.  This separate value identifies the
    # immutable parse-baseline row and is used only to attach parse-fidelity
    # findings to the materialised version row.
    parse_baseline_row_id: int | None = None


@dataclass(frozen=True, slots=True)
class FieldChange:
    row_id: int
    field_name: str
    operation: FieldOperation
    before_value: object
    after_value: object
    restored_field_change_id: int | None = None
    restored_parent_version_id: int | None = None
    restored_source_row_id: int | None = None


@dataclass(frozen=True, slots=True)
class RowChange:
    operation: RowOperation
    row_id: int
    before_row: DraftRow | None
    after_row: DraftRow | None


type ChangePayload = FieldChange | RowChange | None


@dataclass(frozen=True, slots=True)
class DataChangeEvent:
    event_id: int
    sequence_number: int
    data_revision: int
    event_kind: EventKind
    change: ChangePayload


@dataclass(frozen=True, slots=True)
class RestoreValueEvidence:
    """A value read from one immutable, explicitly identified restore source."""

    kind: RestoreValueKind
    reference_id: int
    row_id: int
    field_name: str
    value: object


@dataclass(frozen=True, slots=True)
class DraftReplayEvidence:
    report_type: ReportType
    ruleset_version: str
    base_rows: tuple[DraftRow, ...]
    events: tuple[DataChangeEvent, ...]
    current_rows: tuple[DraftRow, ...]
    data_revision: int
    restore_values: tuple[RestoreValueEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class DraftReplayResult:
    validation: StageValidationResult
    rows: tuple[DraftRow, ...]
    base_totals: tuple[tuple[str, Decimal], ...]
    field_delta: tuple[tuple[str, Decimal], ...]
    row_delta: tuple[tuple[str, Decimal], ...]
    current_totals: tuple[tuple[str, Decimal], ...]

    @property
    def passed(self) -> bool:
        return self.validation.passed

    @property
    def issues(self) -> tuple[ValidationIssue, ...]:
        return self.validation.issues


def _issue(
    code: str,
    message: str,
    *,
    row_id: int | None = None,
    field_name: str | None = None,
    source_value: FieldValue = None,
    processed_value: FieldValue = None,
) -> ValidationIssue:
    return ValidationIssue(
        stage="draft_explainability",
        code=code,
        severity="blocking",
        message=message,
        requires_note=False,
        row_id=row_id,
        field_name=field_name,
        source_value=source_value,
        processed_value=processed_value,
    )


def _validated_row(
    row: DraftRow,
    *,
    evidence: DraftReplayEvidence,
    issues: list[ValidationIssue],
    code: str,
) -> DraftRow | None:
    if row.row_id < 1 or row.row_ordinal < 1:
        issues.append(_issue(code, "row identity or ordinal is not positive"))
        return None
    logical_row_id: object = row.logical_row_id
    if not isinstance(logical_row_id, UUID):
        issues.append(
            _issue(code, "logical row identity is not a UUID", row_id=row.row_id)
        )
        return None
    if row.row_state not in _ROW_STATES:
        issues.append(_issue(code, "row state is not supported", row_id=row.row_id))
        return None
    for identity in (
        row.base_row_id,
        row.source_parse_baseline_row_id,
        row.source_batch_id,
    ):
        if identity is not None and identity < 1:
            issues.append(
                _issue(code, "row provenance ID is not positive", row_id=row.row_id)
            )
            return None
    try:
        values = validate_row_values(
            evidence.report_type,
            evidence.ruleset_version,
            row.values,
            require_all=True,
        )
    except FieldValueError as error:
        issues.append(
            _issue(
                code,
                f"row values do not satisfy the frozen field contract: {error}",
                row_id=row.row_id,
            )
        )
        return None
    return replace(row, values=cast(tuple[tuple[str, object], ...], values))


def _validated_rows(
    rows: tuple[DraftRow, ...],
    *,
    evidence: DraftReplayEvidence,
    issues: list[ValidationIssue],
    code: str,
) -> dict[int, DraftRow]:
    result: dict[int, DraftRow] = {}
    logical_ids: set[UUID] = set()
    ordinals: set[int] = set()
    for row in rows:
        validated = _validated_row(
            row,
            evidence=evidence,
            issues=issues,
            code=code,
        )
        if validated is None:
            continue
        if validated.row_id in result:
            issues.append(_issue(code, "row ID repeats", row_id=validated.row_id))
            continue
        if validated.logical_row_id in logical_ids:
            issues.append(
                _issue(code, "logical row ID repeats", row_id=validated.row_id)
            )
            continue
        if validated.row_ordinal in ordinals:
            issues.append(_issue(code, "row ordinal repeats", row_id=validated.row_id))
            continue
        result[validated.row_id] = validated
        logical_ids.add(validated.logical_row_id)
        ordinals.add(validated.row_ordinal)
    return result


def _total_names(evidence: DraftReplayEvidence) -> tuple[str, ...]:
    contract = get_report_field_contract(evidence.report_type, evidence.ruleset_version)
    return tuple(field.name for field in contract.fields if field.included_in_totals)


def _zero_totals(evidence: DraftReplayEvidence) -> dict[str, Decimal]:
    return {name: Decimal(0) for name in _total_names(evidence)}


def _numeric(value: object, *, field_name: str) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise FieldValueError(f"total field {field_name} is not numeric")
    return Decimal(value)


def _row_contribution(
    row: DraftRow | None,
    evidence: DraftReplayEvidence,
) -> dict[str, Decimal]:
    result = _zero_totals(evidence)
    if row is None or row.row_state != "active":
        return result
    values = dict(row.values)
    for name in result:
        result[name] = _numeric(values[name], field_name=name)
    return result


def _totals(
    rows: dict[int, DraftRow],
    evidence: DraftReplayEvidence,
) -> dict[str, Decimal]:
    result = _zero_totals(evidence)
    for row in rows.values():
        contribution = _row_contribution(row, evidence)
        for name, value in contribution.items():
            result[name] += value
    return result


def _add_delta(
    target: dict[str, Decimal],
    before: dict[str, Decimal],
    after: dict[str, Decimal],
) -> None:
    for name in target:
        target[name] += after[name] - before[name]


def _same_row(left: DraftRow, right: DraftRow) -> bool:
    # Parse-baseline row lineage is loaded from immutable database joins, not
    # from the historical row-event payload.  It must not make a faithfully
    # replayed event differ from its stored current-row image.
    return replace(left, parse_baseline_row_id=None) == replace(
        right,
        parse_baseline_row_id=None,
    )


type RestoreValueKey = tuple[RestoreValueKind, int, int, str]


def _is_positive_identifier(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _same_field_value(left: FieldValue, right: FieldValue) -> bool:
    return encode_field_value(left) == encode_field_value(right)


def _validated_restore_values(
    evidence: DraftReplayEvidence,
    issues: list[ValidationIssue],
) -> dict[RestoreValueKey, FieldValue]:
    result: dict[RestoreValueKey, FieldValue] = {}
    for item in evidence.restore_values:
        if item.kind not in _RESTORE_VALUE_KINDS:
            issues.append(
                _issue(
                    "draft.invalid_restore_evidence",
                    "restore value evidence has an unsupported source kind",
                    row_id=item.row_id
                    if _is_positive_identifier(item.row_id)
                    else None,
                )
            )
            continue
        if not _is_positive_identifier(
            item.reference_id
        ) or not _is_positive_identifier(item.row_id):
            issues.append(
                _issue(
                    "draft.invalid_restore_evidence",
                    "restore value evidence has a non-positive identity",
                    row_id=item.row_id
                    if _is_positive_identifier(item.row_id)
                    else None,
                )
            )
            continue
        if not isinstance(item.field_name, str) or not item.field_name:
            issues.append(
                _issue(
                    "draft.invalid_restore_evidence",
                    "restore value evidence has no field name",
                    row_id=item.row_id,
                )
            )
            continue
        try:
            contract = get_field_contract(
                evidence.report_type,
                evidence.ruleset_version,
                item.field_name,
            )
            if not contract.editable:
                raise FieldValueError("field is derived and not editable")
            value = validate_field_value(
                evidence.report_type,
                evidence.ruleset_version,
                item.field_name,
                item.value,
            )
        except (FieldValueError, ValueError) as error:
            issues.append(
                _issue(
                    "draft.invalid_restore_evidence",
                    f"restore value evidence does not satisfy its contract: {error}",
                    row_id=item.row_id,
                    field_name=item.field_name,
                )
            )
            continue
        key = (item.kind, item.reference_id, item.row_id, item.field_name)
        if key in result:
            issues.append(
                _issue(
                    "draft.duplicate_restore_evidence",
                    "restore value evidence repeats the same source and field",
                    row_id=item.row_id,
                    field_name=item.field_name,
                )
            )
            continue
        result[key] = value
    return result


def _validated_restore_reference(
    change: FieldChange,
    *,
    issues: list[ValidationIssue],
) -> tuple[bool, tuple[RestoreValueKind, int] | None]:
    references = (
        change.restored_field_change_id,
        change.restored_parent_version_id,
        change.restored_source_row_id,
    )
    if change.operation == "set":
        if any(reference is not None for reference in references):
            issues.append(
                _issue(
                    "draft.unexpected_restore_reference",
                    "a set field change must not carry a restore reference",
                    row_id=change.row_id,
                    field_name=change.field_name,
                )
            )
            return False, None
        return True, None

    kind: RestoreValueKind
    reference_id: int | None
    other_references: tuple[int | None, int | None]
    if change.operation == "restore_previous":
        kind = "previous"
        reference_id = change.restored_field_change_id
        other_references = (
            change.restored_parent_version_id,
            change.restored_source_row_id,
        )
    elif change.operation == "restore_parent":
        kind = "parent"
        reference_id = change.restored_parent_version_id
        other_references = (
            change.restored_field_change_id,
            change.restored_source_row_id,
        )
    else:
        kind = "source"
        reference_id = change.restored_source_row_id
        other_references = (
            change.restored_field_change_id,
            change.restored_parent_version_id,
        )

    if not _is_positive_identifier(reference_id) or any(
        reference is not None for reference in other_references
    ):
        issues.append(
            _issue(
                "draft.invalid_restore_reference",
                "a restore field change must carry exactly its matching reference ID",
                row_id=change.row_id,
                field_name=change.field_name,
            )
        )
        return False, None
    return True, (kind, cast(int, reference_id))


def _validate_restore_binding(
    row: DraftRow,
    change: FieldChange,
    after_value: FieldValue,
    *,
    evidence: DraftReplayEvidence,
    issues: list[ValidationIssue],
    restore_values: dict[RestoreValueKey, FieldValue],
    prior_field_changes: dict[int, FieldChange],
) -> bool:
    valid, source = _validated_restore_reference(change, issues=issues)
    if not valid:
        return False
    if source is None:
        return True

    kind, reference_id = source
    if kind == "source":
        if row.source_parse_baseline_row_id is None:
            issues.append(
                _issue(
                    "draft.restore_source_unavailable",
                    "a manually added row has no source value to restore",
                    row_id=row.row_id,
                    field_name=change.field_name,
                )
            )
            return False
        if row.source_parse_baseline_row_id != reference_id:
            issues.append(
                _issue(
                    "draft.restore_reference_mismatch",
                    "source restore reference does not match the row provenance",
                    row_id=row.row_id,
                    field_name=change.field_name,
                )
            )
            return False

    referenced_change: FieldChange | None = None
    if kind == "previous":
        referenced_change = prior_field_changes.get(reference_id)
        if referenced_change is None:
            issues.append(
                _issue(
                    "draft.restore_reference_unavailable",
                    "previous restore reference is not an earlier field change",
                    row_id=row.row_id,
                    field_name=change.field_name,
                )
            )
            return False
        if (
            referenced_change.row_id != row.row_id
            or referenced_change.field_name != change.field_name
        ):
            issues.append(
                _issue(
                    "draft.restore_reference_mismatch",
                    "previous restore reference belongs to another row or field",
                    row_id=row.row_id,
                    field_name=change.field_name,
                )
            )
            return False

    key = (kind, reference_id, row.row_id, change.field_name)
    restore_value = restore_values.get(key)
    if restore_value is None and key not in restore_values:
        same_reference_exists = any(
            candidate[1] == reference_id for candidate in restore_values
        )
        issues.append(
            _issue(
                (
                    "draft.restore_reference_mismatch"
                    if same_reference_exists
                    else "draft.restore_reference_unavailable"
                ),
                (
                    "restore reference belongs to another source, row, or field"
                    if same_reference_exists
                    else "restore reference has no immutable value evidence"
                ),
                row_id=row.row_id,
                field_name=change.field_name,
            )
        )
        return False

    if referenced_change is not None:
        try:
            referenced_before = validate_field_value(
                evidence.report_type,
                evidence.ruleset_version,
                change.field_name,
                referenced_change.before_value,
            )
        except FieldValueError, ValueError:
            issues.append(
                _issue(
                    "draft.restore_reference_mismatch",
                    "previous restore reference has no valid before value",
                    row_id=row.row_id,
                    field_name=change.field_name,
                )
            )
            return False
        if not _same_field_value(restore_value, referenced_before):
            issues.append(
                _issue(
                    "draft.restore_evidence_mismatch",
                    "previous restore evidence differs from its field change",
                    row_id=row.row_id,
                    field_name=change.field_name,
                    source_value=referenced_before,
                    processed_value=restore_value,
                )
            )
            return False

    if not _same_field_value(after_value, restore_value):
        issues.append(
            _issue(
                "draft.restore_value_mismatch",
                "restored after value differs from its immutable source value",
                row_id=row.row_id,
                field_name=change.field_name,
                source_value=restore_value,
                processed_value=after_value,
            )
        )
        return False
    return True


def _apply_field_change(
    state: dict[int, DraftRow],
    change: FieldChange,
    *,
    evidence: DraftReplayEvidence,
    issues: list[ValidationIssue],
    field_delta: dict[str, Decimal],
    restore_values: dict[RestoreValueKey, FieldValue],
    prior_field_changes: dict[int, FieldChange],
) -> None:
    if change.operation not in _FIELD_OPERATIONS:
        issues.append(
            _issue(
                "draft.unsupported_field_operation",
                "field change operation is not supported",
                row_id=change.row_id,
                field_name=change.field_name,
            )
        )
        return
    row = state.get(change.row_id)
    if row is None:
        issues.append(
            _issue(
                "draft.unknown_field_row",
                "field change references an unknown row",
                row_id=change.row_id,
                field_name=change.field_name,
            )
        )
        return
    if row.row_state != "active":
        issues.append(
            _issue(
                "draft.field_on_inactive_row",
                "field changes require an active row",
                row_id=row.row_id,
                field_name=change.field_name,
            )
        )
        return
    try:
        contract = get_field_contract(
            evidence.report_type,
            evidence.ruleset_version,
            change.field_name,
        )
        if not contract.editable:
            raise FieldValueError("field is derived and not editable")
        before_value = validate_field_value(
            evidence.report_type,
            evidence.ruleset_version,
            change.field_name,
            change.before_value,
        )
        after_value = validate_field_value(
            evidence.report_type,
            evidence.ruleset_version,
            change.field_name,
            change.after_value,
        )
    except (FieldValueError, ValueError) as error:
        issues.append(
            _issue(
                "draft.invalid_field_change",
                f"field change does not satisfy its contract: {error}",
                row_id=row.row_id,
                field_name=change.field_name,
            )
        )
        return
    current_value = as_field_value(dict(row.values)[change.field_name])
    if current_value != before_value:
        issues.append(
            _issue(
                "draft.before_value_mismatch",
                "field change before value does not match replay head",
                row_id=row.row_id,
                field_name=change.field_name,
                source_value=current_value,
                processed_value=before_value,
            )
        )
        return
    if not _validate_restore_binding(
        row,
        change,
        after_value,
        evidence=evidence,
        issues=issues,
        restore_values=restore_values,
        prior_field_changes=prior_field_changes,
    ):
        return

    changed_values = dict(row.values)
    changed_values[change.field_name] = after_value
    validated_values = validate_row_values(
        evidence.report_type,
        evidence.ruleset_version,
        changed_values,
        require_all=True,
    )
    changed_row = replace(
        row,
        values=cast(tuple[tuple[str, object], ...], validated_values),
    )
    if contract.included_in_totals:
        field_delta[change.field_name] += _numeric(
            after_value,
            field_name=change.field_name,
        ) - _numeric(before_value, field_name=change.field_name)
    state[row.row_id] = changed_row


def _apply_row_change(
    state: dict[int, DraftRow],
    change: RowChange,
    *,
    evidence: DraftReplayEvidence,
    issues: list[ValidationIssue],
    row_delta: dict[str, Decimal],
) -> None:
    if change.operation not in _ROW_OPERATIONS:
        issues.append(
            _issue(
                "draft.unsupported_row_operation",
                "row change operation is not supported",
                row_id=change.row_id,
            )
        )
        return
    before = (
        _validated_row(
            change.before_row,
            evidence=evidence,
            issues=issues,
            code="draft.invalid_event_row",
        )
        if change.before_row is not None
        else None
    )
    after = (
        _validated_row(
            change.after_row,
            evidence=evidence,
            issues=issues,
            code="draft.invalid_event_row",
        )
        if change.after_row is not None
        else None
    )
    if (change.before_row is not None and before is None) or (
        change.after_row is not None and after is None
    ):
        return
    current = state.get(change.row_id)

    if change.operation == "add":
        if before is not None or after is None:
            issues.append(
                _issue(
                    "draft.invalid_add_transition",
                    "row add requires no before row and one after row",
                    row_id=change.row_id,
                )
            )
            return
        if current is not None or after.row_id != change.row_id:
            issues.append(
                _issue(
                    "draft.invalid_add_transition",
                    "row add identity already exists or does not match its event",
                    row_id=change.row_id,
                )
            )
            return
        if (
            after.row_state != "active"
            or after.base_row_id is not None
            or after.source_parse_baseline_row_id is not None
            or after.source_batch_id is None
        ):
            issues.append(
                _issue(
                    "draft.invalid_add_transition",
                    "manual row add has invalid state or provenance",
                    row_id=change.row_id,
                )
            )
            return
        try:
            added_values = validate_added_row_values(
                evidence.report_type,
                evidence.ruleset_version,
                after.values,
            )
        except FieldValueError as error:
            issues.append(
                _issue(
                    "draft.invalid_added_row",
                    f"manual row does not satisfy its required fields: {error}",
                    row_id=change.row_id,
                )
            )
            return
        after = replace(
            after,
            values=cast(tuple[tuple[str, object], ...], added_values),
        )
        if any(
            existing.logical_row_id == after.logical_row_id
            or existing.row_ordinal == after.row_ordinal
            for existing in state.values()
        ):
            issues.append(
                _issue(
                    "draft.invalid_add_transition",
                    "manual row add duplicates logical identity or ordinal",
                    row_id=change.row_id,
                )
            )
            return
        _add_delta(
            row_delta,
            _row_contribution(None, evidence),
            _row_contribution(after, evidence),
        )
        state[change.row_id] = after
        return

    if current is None or before is None or after is None:
        issues.append(
            _issue(
                "draft.invalid_row_transition",
                "row state change requires an existing before and after row",
                row_id=change.row_id,
            )
        )
        return
    if not _same_row(current, before):
        issues.append(
            _issue(
                "draft.before_row_mismatch",
                "row change before image does not match replay head",
                row_id=change.row_id,
            )
        )
        return

    expected_after: DraftRow
    if change.operation == "exclude":
        if current.row_state != "active":
            issues.append(
                _issue(
                    "draft.invalid_exclude_transition",
                    "only an active row may be excluded",
                    row_id=change.row_id,
                )
            )
            return
        expected_after = replace(current, row_state="excluded")
    elif change.operation == "restore":
        if current.row_state not in {"excluded", "deleted"}:
            issues.append(
                _issue(
                    "draft.invalid_restore_transition",
                    "only an excluded or deleted row may be restored",
                    row_id=change.row_id,
                )
            )
            return
        if current.row_state == "deleted" and current.base_row_id is not None:
            issues.append(
                _issue(
                    "draft.invalid_restore_transition",
                    "source-derived rows cannot have a deleted state",
                    row_id=change.row_id,
                )
            )
            return
        expected_after = replace(current, row_state="active")
    else:
        if current.base_row_id is not None:
            issues.append(
                _issue(
                    "draft.invalid_delete_transition",
                    "source-derived rows must be excluded rather than deleted",
                    row_id=change.row_id,
                )
            )
            return
        if current.row_state not in {"active", "excluded"}:
            issues.append(
                _issue(
                    "draft.invalid_delete_transition",
                    "only an active or excluded manual row may be deleted",
                    row_id=change.row_id,
                )
            )
            return
        expected_after = replace(current, row_state="deleted")

    if not _same_row(after, expected_after):
        issues.append(
            _issue(
                "draft.after_row_mismatch",
                "row change after image modifies more than the allowed state",
                row_id=change.row_id,
            )
        )
        return
    _add_delta(
        row_delta,
        _row_contribution(current, evidence),
        _row_contribution(after, evidence),
    )
    state[change.row_id] = after


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _rows_digest(rows: dict[int, DraftRow]) -> str:
    payload = [
        {
            "row_id": row.row_id,
            "logical_row_id": str(row.logical_row_id),
            "row_ordinal": row.row_ordinal,
            "row_state": row.row_state,
            "base_row_id": row.base_row_id,
            "source_parse_baseline_row_id": row.source_parse_baseline_row_id,
            "source_batch_id": row.source_batch_id,
            "values": {name: encode_field_value(value) for name, value in row.values},
        }
        for row in sorted(
            rows.values(),
            key=lambda item: (item.row_ordinal, item.row_id),
        )
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _frozen_totals(values: dict[str, Decimal]) -> tuple[tuple[str, Decimal], ...]:
    return tuple((name, values[name]) for name in sorted(values))


def replay_draft_changes(evidence: DraftReplayEvidence) -> DraftReplayResult:
    """Replay all events and prove the materialised draft has no unexplained delta."""

    if evidence.data_revision < 0:
        raise ValueError("data_revision must not be negative")
    get_report_field_contract(evidence.report_type, evidence.ruleset_version)
    issues: list[ValidationIssue] = []
    state = _validated_rows(
        evidence.base_rows,
        evidence=evidence,
        issues=issues,
        code="draft.invalid_base_row",
    )
    base_totals = _totals(state, evidence)
    field_delta = _zero_totals(evidence)
    row_delta = _zero_totals(evidence)
    restore_values = _validated_restore_values(evidence, issues)
    seen_event_ids: set[int] = set()
    prior_field_changes: dict[int, FieldChange] = {}

    events = tuple(
        sorted(
            evidence.events,
            key=lambda event: (event.sequence_number, event.data_revision),
        )
    )
    for expected_revision, event in enumerate(events, start=1):
        event_identity_is_unique = True
        if not _is_positive_identifier(event.event_id):
            issues.append(
                _issue(
                    "draft.invalid_event_id",
                    "data change event ID is not positive",
                )
            )
            event_identity_is_unique = False
        elif event.event_id in seen_event_ids:
            issues.append(
                _issue(
                    "draft.duplicate_event_id",
                    "data change event ID repeats",
                )
            )
            event_identity_is_unique = False
        else:
            seen_event_ids.add(event.event_id)
        if event.sequence_number != expected_revision:
            issues.append(
                _issue(
                    "draft.event_sequence_gap",
                    "data change event sequence is not contiguous",
                )
            )
        if event.data_revision != expected_revision:
            issues.append(
                _issue(
                    "draft.event_revision_gap",
                    "data change event revision is not contiguous",
                )
            )
        if event.change is None:
            issues.append(
                _issue(
                    "draft.missing_event_subtype",
                    "data change event has no subtype record",
                )
            )
            continue
        change: object = event.change
        if isinstance(change, FieldChange):
            if event.event_kind != "field":
                issues.append(
                    _issue(
                        "draft.event_kind_mismatch",
                        "field subtype is attached to a non-field event",
                        row_id=change.row_id,
                    )
                )
                continue
            _apply_field_change(
                state,
                change,
                evidence=evidence,
                issues=issues,
                field_delta=field_delta,
                restore_values=restore_values,
                prior_field_changes=prior_field_changes,
            )
            if event_identity_is_unique:
                prior_field_changes[event.event_id] = change
        elif isinstance(change, RowChange):
            if event.event_kind != "row":
                issues.append(
                    _issue(
                        "draft.event_kind_mismatch",
                        "row subtype is attached to a non-row event",
                        row_id=change.row_id,
                    )
                )
                continue
            _apply_row_change(
                state,
                change,
                evidence=evidence,
                issues=issues,
                row_delta=row_delta,
            )
        else:
            issues.append(
                _issue(
                    "draft.unsupported_event_subtype",
                    "data change event has an unsupported subtype record",
                )
            )

    if evidence.data_revision != len(events):
        issues.append(
            _issue(
                "draft.head_revision_mismatch",
                "draft data revision differs from its event history",
            )
        )

    replay_totals = _totals(state, evidence)
    reconciled_totals = {
        name: base_totals[name] + field_delta[name] + row_delta[name]
        for name in base_totals
    }
    if replay_totals != reconciled_totals:
        issues.append(
            _issue(
                "draft.net_change_mismatch",
                "replayed totals do not equal base plus audited net changes",
            )
        )

    current = _validated_rows(
        evidence.current_rows,
        evidence=evidence,
        issues=issues,
        code="draft.invalid_current_row",
    )
    for row_id, replayed in state.items():
        materialised = current.get(row_id)
        if materialised is None:
            issues.append(
                _issue(
                    "draft.missing_current_row",
                    "replayed row is missing from the materialised draft",
                    row_id=row_id,
                )
            )
        elif not _same_row(replayed, materialised):
            issues.append(
                _issue(
                    "draft.current_row_mismatch",
                    "materialised draft row differs from event replay",
                    row_id=row_id,
                )
            )
    for row_id in current.keys() - state.keys():
        issues.append(
            _issue(
                "draft.unexplained_current_row",
                "materialised draft contains a row with no base or add event",
                row_id=row_id,
            )
        )

    current_totals = _totals(current, evidence)
    if current_totals != reconciled_totals:
        issues.append(
            _issue(
                "draft.current_total_mismatch",
                "materialised totals do not equal base plus audited net changes",
            )
        )

    validation = StageValidationResult(
        stage="draft_explainability",
        data_digest=_rows_digest(state),
        row_count=len(state),
        totals=tuple(
            (name, _canonical_decimal(value))
            for name, value in sorted(replay_totals.items())
        ),
        issues=tuple(issues),
    )
    return DraftReplayResult(
        validation=validation,
        rows=tuple(
            sorted(state.values(), key=lambda row: (row.row_ordinal, row.row_id))
        ),
        base_totals=_frozen_totals(base_totals),
        field_delta=_frozen_totals(field_delta),
        row_delta=_frozen_totals(row_delta),
        current_totals=_frozen_totals(current_totals),
    )
