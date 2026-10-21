"""Pure deterministic planning for immutable version base snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.imports.types import ReportType

from .types import InvalidMergeDecision, MergeDecision, MergeDecisionRequired

type SnapshotMemberType = Literal["parse_baseline", "dataset_version"]
type SnapshotMemberRole = Literal[
    "base",
    "parse_input",
    "draft_predecessor",
    "merge_target",
    "merge_source",
    "moved_source",
]
type RowState = Literal["active", "excluded", "deleted"]
type RowOrigin = Literal["target", "source"]
type SnapshotScalar = bool | int | str | Decimal | date | datetime | UUID | None

_MEMBER_TYPES = frozenset({"parse_baseline", "dataset_version"})
_MEMBER_ROLES = frozenset(
    {
        "base",
        "parse_input",
        "draft_predecessor",
        "merge_target",
        "merge_source",
        "moved_source",
    }
)
_MEMBER_ROLE_ORDER: dict[SnapshotMemberRole, int] = {
    "base": 0,
    "merge_target": 1,
    "draft_predecessor": 2,
    "merge_source": 3,
    "moved_source": 4,
    "parse_input": 5,
}
_ROW_STATES = frozenset({"active", "excluded", "deleted"})


def _positive(value: int, field_name: str) -> None:
    if value < 1:
        raise ValueError(f"{field_name} must be positive")


def _normalise_values(
    values: Iterable[tuple[str, SnapshotScalar]],
) -> tuple[tuple[str, SnapshotScalar], ...]:
    normalised = tuple(values)
    names: list[str] = []
    for field_name, value in normalised:
        name = field_name.strip()
        if not name:
            raise ValueError("snapshot field name must not be blank")
        if name != field_name:
            raise ValueError("snapshot field names must already be normalised")
        if (
            not isinstance(
                value,
                (bool, int, str, Decimal, date, UUID),
            )
            and value is not None
        ):
            raise ValueError("snapshot value type is not supported")
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("snapshot field names must be unique")
    return normalised


@dataclass(frozen=True, slots=True)
class SnapshotMember:
    member_type: SnapshotMemberType
    member_role: SnapshotMemberRole
    source_id: int

    def __post_init__(self) -> None:
        if self.member_type not in _MEMBER_TYPES:
            raise ValueError("snapshot member type is not supported")
        if self.member_role not in _MEMBER_ROLES:
            raise ValueError("snapshot member role is not supported")
        _positive(self.source_id, "source_id")


def order_snapshot_members(
    members: Iterable[SnapshotMember],
) -> tuple[SnapshotMember, ...]:
    """Return one stable semantic order independent of caller iteration order."""

    frozen = tuple(members)
    identities = [(member.member_type, member.source_id) for member in frozen]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate snapshot member")
    return tuple(
        sorted(
            frozen,
            key=lambda member: (
                _MEMBER_ROLE_ORDER[member.member_role],
                member.member_type,
                member.source_id,
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class MergeRow:
    """One target or incoming row considered by the pure merge planner."""

    member_ordinal: int
    source_row_id: int
    source_ordinal: int
    logical_row_id: UUID | None
    row_state: RowState
    conflict_key: str | None
    values: tuple[tuple[str, SnapshotScalar], ...]

    def __post_init__(self) -> None:
        _positive(self.member_ordinal, "member_ordinal")
        _positive(self.source_row_id, "source_row_id")
        _positive(self.source_ordinal, "source_ordinal")
        if self.logical_row_id is not None and not isinstance(
            self.logical_row_id,
            UUID,
        ):
            raise ValueError("logical_row_id must be a UUID")
        if self.row_state not in _ROW_STATES:
            raise ValueError("row_state is not supported")
        if self.conflict_key is not None and not self.conflict_key:
            raise ValueError("conflict_key must not be blank")
        object.__setattr__(self, "values", _normalise_values(self.values))


@dataclass(frozen=True, slots=True)
class MergedSnapshotRow:
    """One deterministically ordered row ready for snapshot persistence."""

    row_ordinal: int
    member_ordinal: int
    source_row_id: int
    source_ordinal: int
    origin: RowOrigin
    logical_row_id: UUID
    row_state: RowState
    values: tuple[tuple[str, SnapshotScalar], ...]

    def __post_init__(self) -> None:
        _positive(self.row_ordinal, "row_ordinal")
        _positive(self.member_ordinal, "member_ordinal")
        _positive(self.source_row_id, "source_row_id")
        _positive(self.source_ordinal, "source_ordinal")
        if self.origin not in {"target", "source"}:
            raise ValueError("row origin is not supported")
        if not isinstance(self.logical_row_id, UUID):
            raise ValueError("logical_row_id must be a UUID")
        if self.row_state not in _ROW_STATES:
            raise ValueError("row_state is not supported")
        object.__setattr__(self, "values", _normalise_values(self.values))


def _index_rows(rows: tuple[MergeRow, ...], *, label: str) -> dict[int, MergeRow]:
    indexed = {row.source_row_id: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"{label} source row IDs must be unique")
    return indexed


def _required_conflicts(
    target_rows: tuple[MergeRow, ...],
    source_rows: tuple[MergeRow, ...],
) -> set[tuple[int, int]]:
    target_groups: dict[str, list[MergeRow]] = {}
    source_groups: dict[str, list[MergeRow]] = {}
    for row in target_rows:
        if row.conflict_key is not None:
            target_groups.setdefault(row.conflict_key, []).append(row)
    for row in source_rows:
        if row.conflict_key is not None:
            source_groups.setdefault(row.conflict_key, []).append(row)

    required: set[tuple[int, int]] = set()
    for key in sorted(target_groups.keys() & source_groups.keys()):
        required.update(
            (target.source_row_id, source.source_row_id)
            for target in target_groups[key]
            for source in source_groups[key]
        )
    return required


def merge_conflict_pairs(
    *,
    target_rows: Iterable[MergeRow],
    source_rows: Iterable[MergeRow],
) -> tuple[tuple[MergeRow, MergeRow], ...]:
    """Return the complete deterministic target-by-source conflict matrix."""

    targets = tuple(target_rows)
    sources = tuple(source_rows)
    target_by_id = _index_rows(targets, label="target")
    source_by_id = _index_rows(sources, label="source")
    return tuple(
        (target_by_id[target_row_id], source_by_id[source_row_id])
        for target_row_id, source_row_id in sorted(
            _required_conflicts(targets, sources)
        )
    )


def _require_consistent_selection(
    selections: dict[int, bool],
    *,
    row_id: int,
    selected: bool,
    origin: RowOrigin,
) -> None:
    previous = selections.get(row_id)
    if previous is not None and previous != selected:
        raise InvalidMergeDecision(
            f"inconsistent merge decisions for {origin} row {row_id}"
        )
    selections[row_id] = selected


def merge_rows(
    *,
    target_rows: Iterable[MergeRow],
    source_rows: Iterable[MergeRow],
    decisions: Iterable[MergeDecision],
    source_logical_id_factory: Callable[[MergeRow], UUID],
) -> tuple[MergedSnapshotRow, ...]:
    """Validate concrete decisions and produce one deterministic row sequence."""

    targets = tuple(target_rows)
    sources = tuple(source_rows)
    target_by_id = _index_rows(targets, label="target")
    source_by_id = _index_rows(sources, label="source")
    for row in targets:
        if row.logical_row_id is None:
            raise ValueError("target rows must already have logical row IDs")

    required = _required_conflicts(targets, sources)
    decision_by_pair: dict[tuple[int, int], MergeDecision] = {}
    for decision in decisions:
        pair = (decision.target_row_id, decision.source_row_id)
        if pair in decision_by_pair:
            raise InvalidMergeDecision("duplicate decision for one row pair")
        target = target_by_id.get(decision.target_row_id)
        source = source_by_id.get(decision.source_row_id)
        if target is None or source is None:
            raise InvalidMergeDecision("merge decision references an unknown row pair")
        if (
            target.conflict_key is None
            or source.conflict_key is None
            or target.conflict_key != source.conflict_key
        ):
            raise InvalidMergeDecision("merge decision does not describe a conflict")
        decision_by_pair[pair] = decision

    extra = decision_by_pair.keys() - required
    if extra:
        raise InvalidMergeDecision("merge decision does not bind a required conflict")
    missing = sorted(required - decision_by_pair.keys())
    if missing:
        target_row_id, source_row_id = missing[0]
        raise MergeDecisionRequired(
            target_row_id=target_row_id,
            source_row_id=source_row_id,
        )

    target_selections: dict[int, bool] = {}
    source_selections: dict[int, bool] = {}
    for pair in sorted(decision_by_pair):
        decision = decision_by_pair[pair]
        _require_consistent_selection(
            target_selections,
            row_id=decision.target_row_id,
            selected=decision.action != "keep_source",
            origin="target",
        )
        _require_consistent_selection(
            source_selections,
            row_id=decision.source_row_id,
            selected=decision.action != "keep_target",
            origin="source",
        )

    excluded_targets = {
        row_id for row_id, selected in target_selections.items() if not selected
    }
    excluded_sources = {
        row_id for row_id, selected in source_selections.items() if not selected
    }

    selected: list[tuple[RowOrigin, MergeRow]] = [
        ("target", row) for row in targets if row.source_row_id not in excluded_targets
    ]
    selected.extend(
        ("source", row) for row in sources if row.source_row_id not in excluded_sources
    )
    selected.sort(
        key=lambda item: (
            item[1].member_ordinal,
            item[1].source_ordinal,
            item[1].source_row_id,
            0 if item[0] == "target" else 1,
        )
    )

    merged: list[MergedSnapshotRow] = []
    allocated_ids: set[UUID] = set()
    for row_ordinal, (origin, row) in enumerate(selected, start=1):
        if origin == "target":
            logical_row_id = row.logical_row_id
            assert logical_row_id is not None
        else:
            logical_row_id = source_logical_id_factory(row)
            if not isinstance(logical_row_id, UUID):
                raise ValueError("source logical ID factory must return a UUID")
        if logical_row_id in allocated_ids:
            raise ValueError("logical row IDs must be unique in a snapshot")
        allocated_ids.add(logical_row_id)
        merged.append(
            MergedSnapshotRow(
                row_ordinal=row_ordinal,
                member_ordinal=row.member_ordinal,
                source_row_id=row.source_row_id,
                source_ordinal=row.source_ordinal,
                origin=origin,
                logical_row_id=logical_row_id,
                row_state=row.row_state,
                values=row.values,
            )
        )
    return tuple(merged)


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _canonical_value(value: SnapshotScalar) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("snapshot datetimes must be timezone-aware")
        return (
            value.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise ValueError("snapshot value type is not supported")


def canonical_snapshot_digest(
    *,
    report_type: ReportType,
    ruleset_version: str,
    rows: Iterable[MergedSnapshotRow],
) -> bytes:
    """Hash ordered typed values, logical identity, and base row state."""

    if report_type not in {"business_report", "return_report"}:
        raise ValueError("report_type is not supported")
    ruleset = ruleset_version.strip()
    if not ruleset:
        raise ValueError("ruleset_version must not be blank")
    frozen_rows = tuple(rows)
    ordinals = [row.row_ordinal for row in frozen_rows]
    if len(ordinals) != len(set(ordinals)):
        raise ValueError("snapshot row ordinals must be unique")
    ordered_rows = sorted(frozen_rows, key=lambda row: row.row_ordinal)
    payload = {
        "digest_version": "dataset_snapshot_v1",
        "report_type": report_type,
        "ruleset_version": ruleset,
        "rows": [
            {
                "row_ordinal": row.row_ordinal,
                "logical_row_id": str(row.logical_row_id),
                "row_state": row.row_state,
                "values": {
                    name: _canonical_value(value) for name, value in sorted(row.values)
                },
            }
            for row in ordered_rows
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).digest()
