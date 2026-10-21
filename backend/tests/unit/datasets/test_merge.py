from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from app.datasets.merge import (
    MergeRow,
    SnapshotMember,
    canonical_snapshot_digest,
    merge_conflict_pairs,
    merge_rows,
    order_snapshot_members,
)
from app.datasets.types import (
    InvalidMergeDecision,
    MergeDecision,
    MergeDecisionRequired,
)

TARGET_LOGICAL_ID = UUID("11111111-1111-1111-1111-111111111111")
SOURCE_LOGICAL_ID = UUID("22222222-2222-2222-2222-222222222222")
SECOND_SOURCE_LOGICAL_ID = UUID("33333333-3333-3333-3333-333333333333")
SECOND_TARGET_LOGICAL_ID = UUID("44444444-4444-4444-4444-444444444444")


def _target_row(
    *,
    row_id: int = 101,
    source_ordinal: int = 1,
    logical_row_id: UUID = TARGET_LOGICAL_ID,
    conflict_key: str | None = "same",
) -> MergeRow:
    return MergeRow(
        member_ordinal=1,
        source_row_id=row_id,
        source_ordinal=source_ordinal,
        logical_row_id=logical_row_id,
        row_state="active",
        conflict_key=conflict_key,
        values=(("sku", "SKU-1"), ("quantity", 1)),
    )


def _source_row(
    *,
    row_id: int = 201,
    source_ordinal: int = 1,
    conflict_key: str | None = "same",
) -> MergeRow:
    return MergeRow(
        member_ordinal=2,
        source_row_id=row_id,
        source_ordinal=source_ordinal,
        logical_row_id=None,
        row_state="active",
        conflict_key=conflict_key,
        values=(("sku", "SKU-1"), ("quantity", 1)),
    )


def _source_id_factory(row: MergeRow) -> UUID:
    if row.source_row_id == 201:
        return SOURCE_LOGICAL_ID
    return SECOND_SOURCE_LOGICAL_ID


def test_snapshot_members_have_a_fixed_semantic_order() -> None:
    members = (
        SnapshotMember("parse_baseline", "parse_input", 31),
        SnapshotMember("dataset_version", "moved_source", 23),
        SnapshotMember("dataset_version", "merge_target", 19),
        SnapshotMember("dataset_version", "draft_predecessor", 17),
    )

    ordered = order_snapshot_members(members)

    assert [member.member_role for member in ordered] == [
        "merge_target",
        "draft_predecessor",
        "moved_source",
        "parse_input",
    ]
    with pytest.raises(ValueError, match="duplicate snapshot member"):
        order_snapshot_members((members[0], members[0]))


@pytest.mark.parametrize(
    ("action", "expected_origins", "expected_ids"),
    [
        ("keep_target", ["target"], [TARGET_LOGICAL_ID]),
        ("keep_source", ["source"], [SOURCE_LOGICAL_ID]),
        (
            "keep_both",
            ["target", "source"],
            [TARGET_LOGICAL_ID, SOURCE_LOGICAL_ID],
        ),
    ],
)
def test_merge_actions_preserve_target_ids_and_allocate_source_ids(
    action: str,
    expected_origins: list[str],
    expected_ids: list[UUID],
) -> None:
    decision = MergeDecision(
        target_row_id=101,
        source_row_id=201,
        action=action,  # type: ignore[arg-type]
        reason="Both source rows are valid" if action == "keep_both" else None,
    )

    merged = merge_rows(
        target_rows=(_target_row(),),
        source_rows=(_source_row(),),
        decisions=(decision,),
        source_logical_id_factory=_source_id_factory,
    )

    assert [row.origin for row in merged] == expected_origins
    assert [row.logical_row_id for row in merged] == expected_ids
    assert [row.row_ordinal for row in merged] == list(range(1, len(merged) + 1))


def test_nonconflicting_rows_are_kept_in_fixed_member_and_source_order() -> None:
    target = _target_row(conflict_key="target-only")
    later_source = replace(
        _source_row(row_id=202, conflict_key="source-two"),
        source_ordinal=2,
    )
    earlier_source = _source_row(conflict_key="source-one")

    merged = merge_rows(
        target_rows=(target,),
        source_rows=(later_source, earlier_source),
        decisions=(),
        source_logical_id_factory=_source_id_factory,
    )

    assert [row.source_row_id for row in merged] == [101, 201, 202]
    assert [row.logical_row_id for row in merged] == [
        TARGET_LOGICAL_ID,
        SOURCE_LOGICAL_ID,
        SECOND_SOURCE_LOGICAL_ID,
    ]


def test_missing_conflict_decision_is_rejected() -> None:
    with pytest.raises(MergeDecisionRequired) as captured:
        merge_rows(
            target_rows=(_target_row(),),
            source_rows=(_source_row(),),
            decisions=(),
            source_logical_id_factory=_source_id_factory,
        )

    assert captured.value.target_row_id == 101
    assert captured.value.source_row_id == 201


def test_decision_must_bind_existing_conflicting_row_ids() -> None:
    with pytest.raises(InvalidMergeDecision, match="unknown row pair"):
        merge_rows(
            target_rows=(_target_row(),),
            source_rows=(_source_row(),),
            decisions=(
                MergeDecision(
                    target_row_id=999,
                    source_row_id=201,
                    action="keep_target",
                ),
            ),
            source_logical_id_factory=_source_id_factory,
        )

    with pytest.raises(InvalidMergeDecision, match="does not describe a conflict"):
        merge_rows(
            target_rows=(_target_row(conflict_key="one"),),
            source_rows=(_source_row(conflict_key="two"),),
            decisions=(
                MergeDecision(
                    target_row_id=101,
                    source_row_id=201,
                    action="keep_target",
                ),
            ),
            source_logical_id_factory=_source_id_factory,
        )


def test_many_to_one_conflict_requires_a_decision_for_every_concrete_pair() -> None:
    first_target = _target_row()
    second_target = _target_row(
        row_id=102,
        source_ordinal=2,
        logical_row_id=SECOND_TARGET_LOGICAL_ID,
    )
    source = _source_row()

    with pytest.raises(MergeDecisionRequired) as captured:
        merge_rows(
            target_rows=(second_target, first_target),
            source_rows=(source,),
            decisions=(
                MergeDecision(
                    target_row_id=102,
                    source_row_id=201,
                    action="keep_target",
                ),
            ),
            source_logical_id_factory=_source_id_factory,
        )

    assert captured.value.target_row_id == 101
    assert captured.value.source_row_id == 201


def test_conflict_preview_returns_the_complete_sorted_pair_matrix() -> None:
    targets = (
        _target_row(
            row_id=102,
            source_ordinal=2,
            logical_row_id=SECOND_TARGET_LOGICAL_ID,
        ),
        _target_row(),
    )
    sources = (
        _source_row(row_id=202, source_ordinal=2),
        _source_row(),
    )

    pairs = merge_conflict_pairs(target_rows=targets, source_rows=sources)

    assert [
        (target.source_row_id, source.source_row_id) for target, source in pairs
    ] == [(101, 201), (101, 202), (102, 201), (102, 202)]


@pytest.mark.parametrize(
    ("action", "expected_source_row_ids"),
    [
        ("keep_target", [101, 102]),
        ("keep_source", [201, 202]),
        ("keep_both", [101, 102, 201, 202]),
    ],
)
def test_many_to_many_conflict_uses_a_complete_deterministic_pair_matrix(
    action: str,
    expected_source_row_ids: list[int],
) -> None:
    first_target = _target_row()
    second_target = _target_row(
        row_id=102,
        source_ordinal=2,
        logical_row_id=SECOND_TARGET_LOGICAL_ID,
    )
    first_source = _source_row()
    second_source = _source_row(row_id=202, source_ordinal=2)
    decisions = tuple(
        MergeDecision(
            target_row_id=target_row_id,
            source_row_id=source_row_id,
            action=action,  # type: ignore[arg-type]
            reason=(
                "All four concrete rows describe valid activity"
                if action == "keep_both"
                else None
            ),
        )
        for target_row_id, source_row_id in (
            (102, 202),
            (101, 201),
            (102, 201),
            (101, 202),
        )
    )

    merged = merge_rows(
        target_rows=(second_target, first_target),
        source_rows=(second_source, first_source),
        decisions=decisions,
        source_logical_id_factory=_source_id_factory,
    )

    assert [row.source_row_id for row in merged] == expected_source_row_ids
    assert [row.row_ordinal for row in merged] == list(range(1, len(merged) + 1))


def test_many_to_many_mixed_decisions_are_independent_of_input_order() -> None:
    first_target = _target_row()
    second_target = _target_row(
        row_id=102,
        source_ordinal=2,
        logical_row_id=SECOND_TARGET_LOGICAL_ID,
    )
    first_source = _source_row()
    second_source = _source_row(row_id=202, source_ordinal=2)
    decisions = (
        MergeDecision(101, 201, "keep_both", "Both rows are valid"),
        MergeDecision(101, 202, "keep_both", "Both rows are valid"),
        MergeDecision(102, 201, "keep_source"),
        MergeDecision(102, 202, "keep_source"),
    )

    canonical = merge_rows(
        target_rows=(first_target, second_target),
        source_rows=(first_source, second_source),
        decisions=decisions,
        source_logical_id_factory=_source_id_factory,
    )
    reordered = merge_rows(
        target_rows=(second_target, first_target),
        source_rows=(second_source, first_source),
        decisions=tuple(reversed(decisions)),
        source_logical_id_factory=_source_id_factory,
    )

    assert reordered == canonical
    assert [row.source_row_id for row in canonical] == [101, 201, 202]


def test_pair_matrix_cannot_both_select_and_exclude_one_concrete_row() -> None:
    second_target = _target_row(
        row_id=102,
        source_ordinal=2,
        logical_row_id=SECOND_TARGET_LOGICAL_ID,
    )
    second_source = _source_row(row_id=202, source_ordinal=2)

    with pytest.raises(InvalidMergeDecision, match="source row 201"):
        merge_rows(
            target_rows=(_target_row(), second_target),
            source_rows=(_source_row(),),
            decisions=(
                MergeDecision(101, 201, "keep_target"),
                MergeDecision(102, 201, "keep_both", "Both rows are valid"),
            ),
            source_logical_id_factory=_source_id_factory,
        )

    with pytest.raises(InvalidMergeDecision, match="target row 101"):
        merge_rows(
            target_rows=(_target_row(),),
            source_rows=(_source_row(), second_source),
            decisions=(
                MergeDecision(101, 201, "keep_source"),
                MergeDecision(101, 202, "keep_both", "Both rows are valid"),
            ),
            source_logical_id_factory=_source_id_factory,
        )


def test_keep_both_requires_a_nonblank_reason() -> None:
    with pytest.raises(ValueError, match="reason is required"):
        MergeDecision(
            target_row_id=101,
            source_row_id=201,
            action="keep_both",
        )


def test_snapshot_digest_is_canonical_and_includes_row_state() -> None:
    rows = merge_rows(
        target_rows=(_target_row(conflict_key=None),),
        source_rows=(
            replace(
                _source_row(conflict_key=None),
                values=(
                    ("recorded_at", datetime(2026, 8, 7, 1, 2, 3, tzinfo=UTC)),
                    ("amount", Decimal("1.2300")),
                ),
            ),
        ),
        decisions=(),
        source_logical_id_factory=_source_id_factory,
    )

    digest = canonical_snapshot_digest(
        report_type="return_report",
        ruleset_version="return_report_v1",
        rows=rows,
    )
    reordered_values = replace(
        rows[1],
        values=tuple(reversed(rows[1].values)),
    )
    same_content = canonical_snapshot_digest(
        report_type="return_report",
        ruleset_version="return_report_v1",
        rows=(reordered_values, rows[0]),
    )
    excluded = canonical_snapshot_digest(
        report_type="return_report",
        ruleset_version="return_report_v1",
        rows=(replace(rows[0], row_state="excluded"), rows[1]),
    )

    assert len(digest) == 32
    assert same_content == digest
    assert excluded != digest


def test_snapshot_digest_rejects_duplicate_ordinals() -> None:
    rows = merge_rows(
        target_rows=(_target_row(conflict_key=None),),
        source_rows=(_source_row(conflict_key=None),),
        decisions=(),
        source_logical_id_factory=_source_id_factory,
    )

    with pytest.raises(ValueError, match="row ordinals must be unique"):
        canonical_snapshot_digest(
            report_type="business_report",
            ruleset_version="business_report_v1",
            rows=(rows[0], replace(rows[1], row_ordinal=rows[0].row_ordinal)),
        )
