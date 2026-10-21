from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from app.validation.fields import FieldValue
from app.validation.replay import (
    DataChangeEvent,
    DraftReplayEvidence,
    DraftRow,
    FieldChange,
    RestoreValueEvidence,
    RowChange,
    replay_draft_changes,
)


def _values(
    *,
    quantity: int,
    comment: str = "买家留言\n第二行",
) -> tuple[tuple[str, FieldValue], ...]:
    return (
        ("return_date", datetime(2026, 8, 8, 8, 30, tzinfo=UTC)),
        ("order_id", "ORDER-1"),
        ("sku", "SKU-1"),
        ("asin", "ASIN-1"),
        ("fnsku", "FNSKU-1"),
        ("product_name", "商品"),
        ("quantity", quantity),
        ("fulfillment_center_id", "FC-1"),
        ("detailed_disposition", "SELLABLE"),
        ("reason", "REASON"),
        ("status", "STATUS"),
        ("license_plate_number", "LPN-1"),
        ("customer_comments", comment),
    )


def _base_row() -> DraftRow:
    return DraftRow(
        row_id=1,
        logical_row_id=UUID("00000000-0000-0000-0000-000000000001"),
        row_ordinal=1,
        row_state="active",
        values=_values(quantity=2),
        base_row_id=101,
        source_parse_baseline_row_id=201,
        source_batch_id=301,
    )


def _evidence(
    *,
    events: tuple[DataChangeEvent, ...],
    current_rows: tuple[DraftRow, ...],
    data_revision: int,
    restore_values: tuple[RestoreValueEvidence, ...] = (),
) -> DraftReplayEvidence:
    return DraftReplayEvidence(
        report_type="return_report",
        ruleset_version="return_report_v1",
        base_rows=(_base_row(),),
        events=events,
        current_rows=current_rows,
        data_revision=data_revision,
        restore_values=restore_values,
    )


def test_field_change_replays_and_reports_exact_net_change() -> None:
    event = DataChangeEvent(
        event_id=11,
        sequence_number=1,
        data_revision=1,
        event_kind="field",
        change=FieldChange(
            row_id=1,
            field_name="quantity",
            operation="set",
            before_value=2,
            after_value=3,
        ),
    )
    current = replace(_base_row(), values=_values(quantity=3))

    result = replay_draft_changes(
        _evidence(events=(event,), current_rows=(current,), data_revision=1)
    )

    assert result.passed
    assert dict(result.base_totals) == {"quantity": Decimal(2)}
    assert dict(result.field_delta) == {"quantity": Decimal(1)}
    assert dict(result.row_delta) == {"quantity": Decimal(0)}
    assert dict(result.current_totals) == {"quantity": Decimal(3)}


def test_event_gap_and_wrong_before_value_are_blocking() -> None:
    event = DataChangeEvent(
        event_id=11,
        sequence_number=2,
        data_revision=2,
        event_kind="field",
        change=FieldChange(
            row_id=1,
            field_name="quantity",
            operation="set",
            before_value=999,
            after_value=3,
        ),
    )

    result = replay_draft_changes(
        _evidence(events=(event,), current_rows=(_base_row(),), data_revision=2)
    )

    assert {issue.code for issue in result.issues} >= {
        "draft.event_sequence_gap",
        "draft.before_value_mismatch",
    }
    assert not result.passed


def test_unlogged_current_value_difference_is_blocking() -> None:
    changed = replace(_base_row(), values=_values(quantity=4))

    result = replay_draft_changes(
        _evidence(events=(), current_rows=(changed,), data_revision=0)
    )

    assert "draft.current_row_mismatch" in {issue.code for issue in result.issues}
    assert not result.passed


def test_manual_row_cannot_restore_a_source_value() -> None:
    added = DraftRow(
        row_id=2,
        logical_row_id=UUID("00000000-0000-0000-0000-000000000002"),
        row_ordinal=2,
        row_state="active",
        values=_values(quantity=1, comment="人工新增"),
        base_row_id=None,
        source_parse_baseline_row_id=None,
        source_batch_id=301,
    )
    add = DataChangeEvent(
        event_id=11,
        sequence_number=1,
        data_revision=1,
        event_kind="row",
        change=RowChange(operation="add", row_id=2, before_row=None, after_row=added),
    )
    restore_source = DataChangeEvent(
        event_id=12,
        sequence_number=2,
        data_revision=2,
        event_kind="field",
        change=FieldChange(
            row_id=2,
            field_name="quantity",
            operation="restore_source",
            before_value=1,
            after_value=2,
            restored_source_row_id=999,
        ),
    )

    result = replay_draft_changes(
        _evidence(
            events=(add, restore_source),
            current_rows=(
                _base_row(),
                added,
            ),
            data_revision=2,
        )
    )

    assert "draft.restore_source_unavailable" in {issue.code for issue in result.issues}
    assert not result.passed


def test_add_exclude_restore_delete_state_machine_reconciles() -> None:
    base = _base_row()
    added = DraftRow(
        row_id=2,
        logical_row_id=UUID("00000000-0000-0000-0000-000000000002"),
        row_ordinal=2,
        row_state="active",
        values=_values(quantity=1, comment="人工新增"),
        base_row_id=None,
        source_parse_baseline_row_id=None,
        source_batch_id=301,
    )
    excluded = replace(base, row_state="excluded")
    deleted = replace(added, row_state="deleted")
    events = (
        DataChangeEvent(
            event_id=11,
            sequence_number=1,
            data_revision=1,
            event_kind="row",
            change=RowChange("add", 2, None, added),
        ),
        DataChangeEvent(
            event_id=12,
            sequence_number=2,
            data_revision=2,
            event_kind="row",
            change=RowChange("exclude", 1, base, excluded),
        ),
        DataChangeEvent(
            event_id=13,
            sequence_number=3,
            data_revision=3,
            event_kind="row",
            change=RowChange("restore", 1, excluded, base),
        ),
        DataChangeEvent(
            event_id=14,
            sequence_number=4,
            data_revision=4,
            event_kind="row",
            change=RowChange("delete", 2, added, deleted),
        ),
    )

    result = replay_draft_changes(
        _evidence(events=events, current_rows=(base, deleted), data_revision=4)
    )

    assert result.passed
    assert dict(result.row_delta) == {"quantity": Decimal(0)}
    assert dict(result.current_totals) == {"quantity": Decimal(2)}


def test_add_rejects_a_blank_required_return_field() -> None:
    invalid_values = dict(_values(quantity=1))
    invalid_values["order_id"] = "   "
    added = DraftRow(
        row_id=2,
        logical_row_id=UUID("00000000-0000-0000-0000-000000000002"),
        row_ordinal=2,
        row_state="active",
        values=tuple(invalid_values.items()),
        base_row_id=None,
        source_parse_baseline_row_id=None,
        source_batch_id=301,
    )
    add = DataChangeEvent(
        event_id=11,
        sequence_number=1,
        data_revision=1,
        event_kind="row",
        change=RowChange("add", 2, None, added),
    )

    result = replay_draft_changes(
        _evidence(
            events=(add,),
            current_rows=(_base_row(), added),
            data_revision=1,
        )
    )

    assert "draft.invalid_added_row" in {issue.code for issue in result.issues}
    assert not result.passed


def test_all_field_restore_kinds_bind_reference_row_field_and_exact_value() -> None:
    events = (
        DataChangeEvent(
            event_id=11,
            sequence_number=1,
            data_revision=1,
            event_kind="field",
            change=FieldChange(
                row_id=1,
                field_name="quantity",
                operation="set",
                before_value=2,
                after_value=3,
            ),
        ),
        DataChangeEvent(
            event_id=12,
            sequence_number=2,
            data_revision=2,
            event_kind="field",
            change=FieldChange(
                row_id=1,
                field_name="quantity",
                operation="restore_previous",
                before_value=3,
                after_value=2,
                restored_field_change_id=11,
            ),
        ),
        DataChangeEvent(
            event_id=13,
            sequence_number=3,
            data_revision=3,
            event_kind="field",
            change=FieldChange(
                row_id=1,
                field_name="quantity",
                operation="restore_parent",
                before_value=2,
                after_value=4,
                restored_parent_version_id=501,
            ),
        ),
        DataChangeEvent(
            event_id=14,
            sequence_number=4,
            data_revision=4,
            event_kind="field",
            change=FieldChange(
                row_id=1,
                field_name="quantity",
                operation="restore_source",
                before_value=4,
                after_value=2,
                restored_source_row_id=201,
            ),
        ),
    )
    restore_values = (
        RestoreValueEvidence("previous", 11, 1, "quantity", 2),
        RestoreValueEvidence("parent", 501, 1, "quantity", 4),
        RestoreValueEvidence("source", 201, 1, "quantity", 2),
    )

    result = replay_draft_changes(
        _evidence(
            events=events,
            current_rows=(_base_row(),),
            data_revision=4,
            restore_values=restore_values,
        )
    )

    assert result.passed
    assert dict(result.field_delta) == {"quantity": Decimal(0)}


def test_restore_rejects_a_reference_with_no_immutable_value_evidence() -> None:
    event = DataChangeEvent(
        event_id=11,
        sequence_number=1,
        data_revision=1,
        event_kind="field",
        change=FieldChange(
            row_id=1,
            field_name="quantity",
            operation="restore_parent",
            before_value=2,
            after_value=3,
            restored_parent_version_id=501,
        ),
    )

    result = replay_draft_changes(
        _evidence(events=(event,), current_rows=(_base_row(),), data_revision=1)
    )

    assert "draft.restore_reference_unavailable" in {
        issue.code for issue in result.issues
    }
    assert not result.passed


def test_restore_rejects_evidence_for_the_wrong_kind_row_or_field() -> None:
    event = DataChangeEvent(
        event_id=11,
        sequence_number=1,
        data_revision=1,
        event_kind="field",
        change=FieldChange(
            row_id=1,
            field_name="quantity",
            operation="restore_parent",
            before_value=2,
            after_value=3,
            restored_parent_version_id=501,
        ),
    )
    mismatched = (
        RestoreValueEvidence("source", 501, 1, "quantity", 3),
        RestoreValueEvidence("parent", 501, 999, "quantity", 3),
        RestoreValueEvidence("parent", 501, 1, "customer_comments", "3"),
    )

    result = replay_draft_changes(
        _evidence(
            events=(event,),
            current_rows=(_base_row(),),
            data_revision=1,
            restore_values=mismatched,
        )
    )

    assert "draft.restore_reference_mismatch" in {issue.code for issue in result.issues}
    assert not result.passed


def test_restore_rejects_an_after_value_different_from_immutable_evidence() -> None:
    event = DataChangeEvent(
        event_id=11,
        sequence_number=1,
        data_revision=1,
        event_kind="field",
        change=FieldChange(
            row_id=1,
            field_name="quantity",
            operation="restore_parent",
            before_value=2,
            after_value=3,
            restored_parent_version_id=501,
        ),
    )

    result = replay_draft_changes(
        _evidence(
            events=(event,),
            current_rows=(_base_row(),),
            data_revision=1,
            restore_values=(RestoreValueEvidence("parent", 501, 1, "quantity", 4),),
        )
    )

    assert "draft.restore_value_mismatch" in {issue.code for issue in result.issues}
    assert not result.passed


def test_restore_previous_requires_a_real_earlier_field_change() -> None:
    event = DataChangeEvent(
        event_id=12,
        sequence_number=1,
        data_revision=1,
        event_kind="field",
        change=FieldChange(
            row_id=1,
            field_name="quantity",
            operation="restore_previous",
            before_value=2,
            after_value=3,
            restored_field_change_id=11,
        ),
    )

    result = replay_draft_changes(
        _evidence(
            events=(event,),
            current_rows=(_base_row(),),
            data_revision=1,
            restore_values=(RestoreValueEvidence("previous", 11, 1, "quantity", 3),),
        )
    )

    assert "draft.restore_reference_unavailable" in {
        issue.code for issue in result.issues
    }
    assert not result.passed


def test_restore_previous_rejects_a_change_from_another_field() -> None:
    changed_comment = "已修改留言"
    events = (
        DataChangeEvent(
            event_id=11,
            sequence_number=1,
            data_revision=1,
            event_kind="field",
            change=FieldChange(
                row_id=1,
                field_name="customer_comments",
                operation="set",
                before_value="买家留言\n第二行",
                after_value=changed_comment,
            ),
        ),
        DataChangeEvent(
            event_id=12,
            sequence_number=2,
            data_revision=2,
            event_kind="field",
            change=FieldChange(
                row_id=1,
                field_name="quantity",
                operation="restore_previous",
                before_value=2,
                after_value=3,
                restored_field_change_id=11,
            ),
        ),
    )

    result = replay_draft_changes(
        _evidence(
            events=events,
            current_rows=(
                replace(
                    _base_row(),
                    values=_values(quantity=2, comment=changed_comment),
                ),
            ),
            data_revision=2,
            restore_values=(RestoreValueEvidence("previous", 11, 1, "quantity", 3),),
        )
    )

    assert "draft.restore_reference_mismatch" in {issue.code for issue in result.issues}
    assert not result.passed


def test_restore_source_reference_must_match_the_rows_source_provenance() -> None:
    event = DataChangeEvent(
        event_id=11,
        sequence_number=1,
        data_revision=1,
        event_kind="field",
        change=FieldChange(
            row_id=1,
            field_name="quantity",
            operation="restore_source",
            before_value=2,
            after_value=3,
            restored_source_row_id=999,
        ),
    )

    result = replay_draft_changes(
        _evidence(
            events=(event,),
            current_rows=(_base_row(),),
            data_revision=1,
            restore_values=(RestoreValueEvidence("source", 999, 1, "quantity", 3),),
        )
    )

    assert "draft.restore_reference_mismatch" in {issue.code for issue in result.issues}
    assert not result.passed


def test_field_operations_reject_the_wrong_restore_reference_column() -> None:
    events = (
        DataChangeEvent(
            event_id=11,
            sequence_number=1,
            data_revision=1,
            event_kind="field",
            change=FieldChange(
                row_id=1,
                field_name="quantity",
                operation="set",
                before_value=2,
                after_value=3,
                restored_source_row_id=201,
            ),
        ),
        DataChangeEvent(
            event_id=12,
            sequence_number=2,
            data_revision=2,
            event_kind="field",
            change=FieldChange(
                row_id=1,
                field_name="quantity",
                operation="restore_parent",
                before_value=2,
                after_value=3,
                restored_source_row_id=201,
            ),
        ),
    )

    result = replay_draft_changes(
        _evidence(events=events, current_rows=(_base_row(),), data_revision=2)
    )

    assert {issue.code for issue in result.issues} >= {
        "draft.unexpected_restore_reference",
        "draft.invalid_restore_reference",
    }
    assert not result.passed


def test_duplicate_event_identity_and_unknown_change_subtype_are_blocking() -> None:
    events = (
        DataChangeEvent(
            event_id=11,
            sequence_number=1,
            data_revision=1,
            event_kind="field",
            change=FieldChange(1, "quantity", "set", 2, 3),
        ),
        DataChangeEvent(
            event_id=11,
            sequence_number=2,
            data_revision=2,
            event_kind="field",
            change=object(),  # type: ignore[arg-type]
        ),
    )

    result = replay_draft_changes(
        _evidence(
            events=events,
            current_rows=(replace(_base_row(), values=_values(quantity=3)),),
            data_revision=2,
        )
    )

    assert {issue.code for issue in result.issues} >= {
        "draft.duplicate_event_id",
        "draft.unsupported_event_subtype",
    }
    assert not result.passed
