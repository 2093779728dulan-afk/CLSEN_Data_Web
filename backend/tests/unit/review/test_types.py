from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from app.review.types import (
    AddRowCommand,
    ChangeRowStateCommand,
    CreateNoteCommand,
    DraftHeadExpectation,
    FieldNoteTarget,
    ImportBatchNoteTarget,
    MarkReadyCommand,
    ParentValueSource,
    PreviousValueSource,
    RestoreFieldValueCommand,
    ReviewIssueCommand,
    ReviewMutationResult,
    ReviseNoteCommand,
    SetFieldValueCommand,
    SourceFileValueSource,
    VersionNoteTarget,
)

TOKEN = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
POINTED_AT = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)


def _head(**overrides: object) -> DraftHeadExpectation:
    values: dict[str, object] = {
        "dataset_id": 11,
        "version_id": 22,
        "status": "draft",
        "data_revision": 3,
        "review_revision": 4,
        "pointed_at": POINTED_AT,
    }
    values.update(overrides)
    return DraftHeadExpectation(**values)  # type: ignore[arg-type]


def test_draft_head_requires_editable_status_and_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="editable"):
        _head(status="published")
    with pytest.raises(ValueError, match="timezone-aware"):
        _head(pointed_at=datetime(2026, 8, 8, 8, 0))


def test_integer_identifiers_reject_booleans() -> None:
    with pytest.raises(ValueError, match="dataset_id"):
        _head(dataset_id=True)


def test_draft_head_normalises_pointer_timestamp_to_utc() -> None:
    local = timezone(timedelta(hours=8))
    head = _head(pointed_at=datetime(2026, 8, 8, 16, 0, tzinfo=local))

    assert head.pointed_at == POINTED_AT
    assert head.as_payload()["pointed_at"] == "2026-08-08T08:00:00.000000Z"


def test_set_field_digest_binds_actor_head_field_typed_value_and_reason() -> None:
    command = SetFieldValueCommand(
        head=_head(),
        row_id=7,
        field_name="ordered_product_sales",
        value=Decimal("10.500000"),
        actor_user_id=5,
        operation_token=TOKEN,
        reason="修正导入错误",
    )
    same = SetFieldValueCommand(
        head=_head(),
        row_id=7,
        field_name="ordered_product_sales",
        value=Decimal("10.500000"),
        actor_user_id=5,
        operation_token=TOKEN,
        reason="修正导入错误",
    )
    changed_value = SetFieldValueCommand(
        head=_head(),
        row_id=7,
        field_name="ordered_product_sales",
        value=Decimal("10.500001"),
        actor_user_id=5,
        operation_token=TOKEN,
        reason="修正导入错误",
    )

    assert command.operation_kind == "set_field"
    assert command.operation_digest == same.operation_digest
    assert len(command.operation_digest) == 32
    assert command.operation_digest != changed_value.operation_digest


@pytest.mark.parametrize(
    ("source", "source_kind"),
    [
        (PreviousValueSource(field_change_id=31), "previous"),
        (ParentValueSource(parent_version_id=8), "parent"),
        (
            SourceFileValueSource(
                source_batch_id=9,
                parsed_source_row_id=10,
            ),
            "source",
        ),
    ],
)
def test_restore_field_digest_binds_explicit_restore_source(
    source: object,
    source_kind: str,
) -> None:
    command = RestoreFieldValueCommand(
        head=_head(),
        row_id=7,
        field_name="sku",
        source=source,  # type: ignore[arg-type]
        actor_user_id=5,
        operation_token=TOKEN,
        reason="恢复已核对值",
    )

    assert command.operation_kind == f"restore_{source_kind}_field"
    assert len(command.operation_digest) == 32


def test_add_row_digest_is_independent_of_mapping_insertion_order() -> None:
    first = AddRowCommand(
        head=_head(),
        source_batch_id=12,
        values={"sku": "SYN-1", "quantity": 2},
        actor_user_id=5,
        operation_token=TOKEN,
        reason="补录解析器遗漏行",
    )
    reordered = AddRowCommand(
        head=_head(),
        source_batch_id=12,
        values={"quantity": 2, "sku": "SYN-1"},
        actor_user_id=5,
        operation_token=TOKEN,
        reason="补录解析器遗漏行",
    )

    assert first.values == (("quantity", 2), ("sku", "SYN-1"))
    assert first.operation_digest == reordered.operation_digest


@pytest.mark.parametrize("operation", ["exclude", "restore", "delete"])
def test_row_state_command_supports_explicit_row_operations(operation: str) -> None:
    command = ChangeRowStateCommand(
        head=_head(),
        row_id=7,
        operation=operation,  # type: ignore[arg-type]
        actor_user_id=5,
        operation_token=TOKEN,
        reason="人工复核行状态",
    )

    assert command.operation_kind == f"{operation}_row"


def test_note_defaults_to_internal_and_binds_exact_target() -> None:
    command = CreateNoteCommand(
        target=FieldNoteTarget(version_id=22, row_id=7, field_name="sku"),
        expected_review_revision=4,
        body="与原表逐项核对",
        actor_user_id=5,
        operation_token=TOKEN,
    )

    assert command.visibility == "internal"
    assert command.operation_kind == "create_note"
    assert command.target.as_payload() == {
        "target_type": "field",
        "version_id": 22,
        "row_id": 7,
        "field_name": "sku",
    }


def test_note_revision_binds_expected_thread_head_and_target() -> None:
    command = ReviseNoteCommand(
        note_key="review-note-1",
        expected_note_id=40,
        expected_revision_number=2,
        target=FieldNoteTarget(version_id=22, row_id=7, field_name="sku"),
        expected_review_revision=4,
        body="第二次复核后的说明",
        visibility="viewer_visible",
        actor_user_id=5,
        operation_token=TOKEN,
    )

    assert command.operation_kind == "revise_note"
    assert len(command.operation_digest) == 32


def test_batch_note_result_has_batch_identity_without_version_identity() -> None:
    command = CreateNoteCommand(
        target=ImportBatchNoteTarget(import_batch_id=9),
        expected_review_revision=None,
        body="原始文件备注",
        actor_user_id=5,
        operation_token=TOKEN,
    )
    result = ReviewMutationResult(
        operation_token=TOKEN,
        operation_kind=command.operation_kind,
        import_batch_id=9,
        dataset_id=None,
        version_id=None,
        status=None,
        data_revision=None,
        review_revision=None,
        note_id=41,
    )

    assert result.import_batch_id == 9


def test_version_note_requires_expected_review_revision() -> None:
    with pytest.raises(ValueError, match="review_revision"):
        CreateNoteCommand(
            target=VersionNoteTarget(version_id=22),
            expected_review_revision=-1,
            body="发布说明",
            actor_user_id=5,
            operation_token=TOKEN,
        )


def test_issue_review_enforces_severity_action_and_required_comment() -> None:
    with pytest.raises(ValueError, match="warning"):
        ReviewIssueCommand(
            head=_head(),
            validation_run_id=6,
            validation_issue_id=7,
            issue_severity="blocking",
            issue_requires_note=False,
            action="acknowledge",
            comment="已查看",
            actor_user_id=5,
            operation_token=TOKEN,
        )
    with pytest.raises(ValueError, match="comment"):
        ReviewIssueCommand(
            head=_head(),
            validation_run_id=6,
            validation_issue_id=7,
            issue_severity="warning",
            issue_requires_note=True,
            action="acknowledge",
            comment=None,
            actor_user_id=5,
            operation_token=TOKEN,
        )


def test_mark_ready_binds_validation_and_human_confirmation() -> None:
    command = MarkReadyCommand(
        head=_head(),
        validation_run_id=6,
        validation_data_digest=bytes.fromhex("11" * 32),
        ruleset_version="business_report_v1",
        confirmed_report_date=date(2026, 8, 8),
        confirmed_report_type="business_report",
        confirmed_row_count=2,
        confirmed_totals=(("units_ordered", "3"),),
        actor_user_id=5,
        operation_token=TOKEN,
        reason="完成审核",
    )

    assert command.operation_kind == "mark_ready"
    assert command.confirmed_totals == (("units_ordered", "3"),)
    assert len(command.operation_digest) == 32


def test_mark_ready_requires_a_date_not_a_datetime() -> None:
    with pytest.raises(ValueError, match="confirmed_report_date"):
        MarkReadyCommand(
            head=_head(),
            validation_run_id=6,
            validation_data_digest=bytes.fromhex("11" * 32),
            ruleset_version="business_report_v1",
            confirmed_report_date=POINTED_AT,
            confirmed_report_type="business_report",
            confirmed_row_count=2,
            confirmed_totals=(("units_ordered", "3"),),
            actor_user_id=5,
            operation_token=TOKEN,
            reason="完成审核",
        )
