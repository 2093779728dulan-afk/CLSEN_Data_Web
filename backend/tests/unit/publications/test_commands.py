from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from app.datasets.types import MergeDecision
from app.publications import (
    ActiveDraftMoveTarget,
    CreatePublishedMoveRevisionCommand,
    CreateRevisionCommand,
    DraftPointerExpectation,
    FinalizePublishedMoveCommand,
    PublicationConfirmation,
    PublicationPointerExpectation,
    PublishCommand,
    PublishedMoveTarget,
    RollbackCommand,
    UndoPublishedMoveCommand,
    ValidationExpectation,
)

TOKEN = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_TOKEN = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
PUBLISHED_AT = datetime(2026, 8, 8, 1, 2, 3, 456789, tzinfo=UTC)
POINTED_AT = datetime(2026, 8, 8, 2, 3, 4, 567890, tzinfo=UTC)
SOURCE_PUBLICATION = PublicationPointerExpectation(17, PUBLISHED_AT)
EMPTY_PUBLICATION = PublicationPointerExpectation(None, None)
READY_DRAFT = DraftPointerExpectation(
    version_id=23,
    status="ready_for_publish",
    data_revision=4,
    review_revision=7,
    pointed_at=POINTED_AT,
)
VALIDATION = ValidationExpectation(
    run_id=31,
    version_id=23,
    data_revision=4,
    ruleset_version="rules-v3",
    data_digest=bytes.fromhex("11" * 32),
)
CONFIRMATION = PublicationConfirmation(
    confirmed_report_date=date(2026, 8, 8),
    report_type="business_report",
    row_count=2,
    totals=(("units_ordered", "3"), ("gross_sales", "19.98")),
)
DECISION = MergeDecision(101, 201, "keep_target")


def _create_revision() -> CreateRevisionCommand:
    return CreateRevisionCommand(
        dataset_id=5,
        expected_publication=SOURCE_PUBLICATION,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Correct an already published report",
    )


def _publish() -> PublishCommand:
    return PublishCommand(
        dataset_id=5,
        expected_draft=READY_DRAFT,
        expected_publication=SOURCE_PUBLICATION,
        validation=VALIDATION,
        confirmation=CONFIRMATION,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Publish the reviewed data",
    )


def _rollback() -> RollbackCommand:
    return RollbackCommand(
        dataset_id=5,
        expected_publication=SOURCE_PUBLICATION,
        target_version_id=13,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Restore the last known-good publication",
    )


def _create_move_revision() -> CreatePublishedMoveRevisionCommand:
    return CreatePublishedMoveRevisionCommand(
        source_dataset_id=5,
        expected_source_publication=SOURCE_PUBLICATION,
        target_report_date=date(2026, 8, 9),
        target=PublishedMoveTarget(
            dataset_id=6,
            publication=PublicationPointerExpectation(
                19,
                datetime(2026, 8, 8, 3, 4, 5, 678901, tzinfo=UTC),
            ),
            strategy="merge",
        ),
        merge_decisions=(DECISION,),
        actor_user_id=9,
        operation_token=TOKEN,
        reason="The published report belongs to the next day",
    )


def _finalize_move() -> FinalizePublishedMoveCommand:
    return FinalizePublishedMoveCommand(
        move_revision_operation_token=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        source_dataset_id=5,
        expected_source_publication=SOURCE_PUBLICATION,
        target_dataset_id=6,
        expected_target_draft=READY_DRAFT,
        expected_target_publication=PublicationPointerExpectation(
            19,
            datetime(2026, 8, 8, 3, 4, 5, 678901, tzinfo=UTC),
        ),
        validation=VALIDATION,
        confirmation=CONFIRMATION,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Activate the reviewed cross-date move",
    )


def _undo_move() -> UndoPublishedMoveCommand:
    return UndoPublishedMoveCommand(
        move_command_id=41,
        source_dataset_id=5,
        expected_source_publication=EMPTY_PUBLICATION,
        restore_source_version_id=17,
        target_dataset_id=6,
        expected_target_publication=PublicationPointerExpectation(
            23,
            datetime(2026, 8, 8, 4, 5, 6, 789012, tzinfo=UTC),
        ),
        restore_target_version_id=19,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Reverse the most recent cross-date move",
    )


@pytest.mark.parametrize(
    "command",
    [
        _create_revision(),
        _publish(),
        _rollback(),
        _create_move_revision(),
        _finalize_move(),
        _undo_move(),
    ],
)
def test_every_command_requires_a_caller_supplied_uuid_and_no_is_admin_field(
    command: Any,
) -> None:
    assert "is_admin" not in {field.name for field in fields(command)}
    with pytest.raises(ValueError, match="operation_token must be a UUID"):
        replace(command, operation_token=None)


@pytest.mark.parametrize(
    "command",
    [
        _create_revision(),
        _publish(),
        _rollback(),
        _create_move_revision(),
        _finalize_move(),
        _undo_move(),
    ],
)
def test_digest_is_stable_sha256_and_excludes_only_the_operation_token(
    command: Any,
) -> None:
    assert len(command.operation_digest) == 32
    assert command.operation_digest == command.operation_digest
    assert (
        replace(command, operation_token=OTHER_TOKEN).operation_digest
        == command.operation_digest
    )
    assert (
        replace(command, actor_user_id=10).operation_digest != command.operation_digest
    )
    assert replace(command, reason=f"{command.reason} changed").operation_digest != (
        command.operation_digest
    )


def test_publication_pointer_requires_an_exact_version_timestamp_pair() -> None:
    with pytest.raises(ValueError, match="both present or both absent"):
        PublicationPointerExpectation(17, None)
    with pytest.raises(ValueError, match="both present or both absent"):
        PublicationPointerExpectation(None, PUBLISHED_AT)
    with pytest.raises(ValueError, match="timezone-aware"):
        PublicationPointerExpectation(17, PUBLISHED_AT.replace(tzinfo=None))


def test_equivalent_timestamp_offsets_have_one_canonical_digest() -> None:
    offset = timezone(timedelta(hours=8))
    equivalent = PUBLISHED_AT.astimezone(offset)

    first = _create_revision()
    second = replace(
        first,
        expected_publication=PublicationPointerExpectation(17, equivalent),
    )

    assert first.operation_digest == second.operation_digest


def test_publication_confirmation_is_frozen_and_canonicalises_totals() -> None:
    confirmation = PublicationConfirmation(
        confirmed_report_date=date(2026, 8, 8),
        report_type="business_report",
        row_count=2,
        totals=((" units_ordered ", " 3 "), ("gross_sales", "19.98")),
    )

    assert confirmation.totals == (
        ("gross_sales", "19.98"),
        ("units_ordered", "3"),
    )
    with pytest.raises(FrozenInstanceError):
        confirmation.row_count = 3  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"confirmed_report_date": POINTED_AT}, "confirmed_report_date"),
        ({"report_type": "unsupported"}, "report_type"),
        ({"row_count": -1}, "row_count"),
        ({"totals": (("units_ordered", ""),)}, "total value"),
        (
            {"totals": (("units_ordered", "3"), (" units_ordered ", "4"))},
            "duplicate field",
        ),
    ],
)
def test_publication_confirmation_rejects_invalid_values(
    changes: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(CONFIRMATION, **changes)


@pytest.mark.parametrize("command", [_publish(), _finalize_move()])
def test_publish_commands_require_confirmation(command: Any) -> None:
    with pytest.raises(ValueError, match="confirmation is required"):
        replace(command, confirmation=None)


@pytest.mark.parametrize("command", [_publish(), _finalize_move()])
def test_publish_command_digest_binds_every_confirmation_value(command: Any) -> None:
    changed_confirmations = (
        replace(CONFIRMATION, confirmed_report_date=date(2026, 8, 9)),
        replace(CONFIRMATION, report_type="return_report"),
        replace(CONFIRMATION, row_count=3),
        replace(CONFIRMATION, totals=(("units_ordered", "4"),)),
    )

    for confirmation in changed_confirmations:
        assert (
            replace(command, confirmation=confirmation).operation_digest
            != command.operation_digest
        )


@pytest.mark.parametrize("command", [_publish(), _finalize_move()])
def test_canonical_confirmation_total_order_has_one_digest(command: Any) -> None:
    reordered = PublicationConfirmation(
        confirmed_report_date=CONFIRMATION.confirmed_report_date,
        report_type=CONFIRMATION.report_type,
        row_count=CONFIRMATION.row_count,
        totals=tuple(reversed(CONFIRMATION.totals)),
    )

    assert (
        replace(command, confirmation=reordered).operation_digest
        == command.operation_digest
    )


def test_every_expected_pointer_timestamp_is_bound_against_aba() -> None:
    publication_changed = replace(
        SOURCE_PUBLICATION,
        published_at=PUBLISHED_AT + timedelta(microseconds=1),
    )
    draft_changed = replace(
        READY_DRAFT,
        pointed_at=READY_DRAFT.pointed_at + timedelta(microseconds=1),
    )

    assert (
        replace(
            _create_revision(),
            expected_publication=publication_changed,
        ).operation_digest
        != _create_revision().operation_digest
    )
    assert (
        replace(_publish(), expected_draft=draft_changed).operation_digest
        != _publish().operation_digest
    )
    assert (
        replace(_rollback(), expected_publication=publication_changed).operation_digest
        != _rollback().operation_digest
    )
    assert (
        replace(_publish(), expected_publication=publication_changed).operation_digest
        != _publish().operation_digest
    )
    assert (
        replace(
            _create_move_revision(),
            expected_source_publication=publication_changed,
        ).operation_digest
        != _create_move_revision().operation_digest
    )
    create_move = _create_move_revision()
    assert isinstance(create_move.target, PublishedMoveTarget)
    target_publication = create_move.target.publication
    target_published_at = target_publication.published_at
    assert target_published_at is not None
    changed_move_target = replace(
        create_move.target,
        publication=replace(
            target_publication,
            published_at=target_published_at + timedelta(microseconds=1),
        ),
    )
    assert (
        replace(create_move, target=changed_move_target).operation_digest
        != create_move.operation_digest
    )
    assert (
        replace(
            _finalize_move(),
            expected_target_draft=draft_changed,
        ).operation_digest
        != _finalize_move().operation_digest
    )
    finalize = _finalize_move()
    assert (
        replace(
            finalize,
            expected_source_publication=publication_changed,
        ).operation_digest
        != finalize.operation_digest
    )
    finalize_target_at = finalize.expected_target_publication.published_at
    assert finalize_target_at is not None
    changed_finalize_target = replace(
        finalize.expected_target_publication,
        published_at=finalize_target_at + timedelta(microseconds=1),
    )
    assert (
        replace(
            finalize,
            expected_target_publication=changed_finalize_target,
        ).operation_digest
        != finalize.operation_digest
    )
    undo = _undo_move()
    target_published_at = undo.expected_target_publication.published_at
    assert target_published_at is not None
    target_changed = replace(
        undo.expected_target_publication,
        published_at=target_published_at + timedelta(microseconds=1),
    )
    assert (
        replace(
            _undo_move(),
            expected_target_publication=target_changed,
        ).operation_digest
        != _undo_move().operation_digest
    )


def test_publish_and_finalize_require_ready_matching_validation() -> None:
    with pytest.raises(ValueError, match="ready_for_publish"):
        replace(_publish(), expected_draft=replace(READY_DRAFT, status="draft"))
    with pytest.raises(ValueError, match="data revision"):
        replace(_publish(), validation=replace(VALIDATION, data_revision=5))
    with pytest.raises(ValueError, match="version"):
        replace(_publish(), validation=replace(VALIDATION, version_id=24))
    with pytest.raises(ValueError, match="ready_for_publish"):
        replace(
            _finalize_move(),
            expected_target_draft=replace(READY_DRAFT, status="draft"),
        )
    with pytest.raises(ValueError, match="version"):
        replace(_finalize_move(), validation=replace(VALIDATION, version_id=24))


def test_validation_identity_and_move_revision_token_are_digest_bound() -> None:
    publish = _publish()
    next_version_publish = replace(
        publish,
        expected_draft=replace(READY_DRAFT, version_id=24),
        validation=replace(VALIDATION, version_id=24),
    )
    assert next_version_publish.operation_digest != publish.operation_digest
    assert (
        replace(
            publish,
            validation=replace(VALIDATION, run_id=32),
        ).operation_digest
        != publish.operation_digest
    )
    assert (
        replace(
            publish,
            validation=replace(VALIDATION, ruleset_version="rules-v4"),
        ).operation_digest
        != publish.operation_digest
    )
    finalize = _finalize_move()
    assert (
        replace(
            finalize,
            move_revision_operation_token=UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
        ).operation_digest
        != finalize.operation_digest
    )


def test_move_commands_reject_same_dataset_and_invalid_target_decisions() -> None:
    with pytest.raises(ValueError, match="target dataset must differ"):
        replace(_finalize_move(), target_dataset_id=5)

    active_target = ActiveDraftMoveTarget(
        dataset_id=6,
        draft=replace(READY_DRAFT, status="draft"),
        publication=EMPTY_PUBLICATION,
        action="cancel",
    )
    with pytest.raises(ValueError, match="merge decisions must be empty"):
        replace(
            _create_move_revision(),
            target=active_target,
            merge_decisions=(DECISION,),
        )


def test_force_rebuild_requires_an_explicit_target_publication_strategy() -> None:
    active_target = ActiveDraftMoveTarget(
        dataset_id=6,
        draft=replace(READY_DRAFT, status="draft"),
        publication=PublicationPointerExpectation(
            19,
            datetime(2026, 8, 8, 3, 4, 5, 678901, tzinfo=UTC),
        ),
        action="force_rebuild",
        rebuild_strategy="merge",
    )
    command = replace(
        _create_move_revision(),
        target=active_target,
        merge_decisions=(DECISION,),
    )

    assert command.merge_decisions == (DECISION,)

    without_decisions = replace(command, merge_decisions=())
    assert (
        replace(
            without_decisions,
            target=replace(active_target, rebuild_strategy="replace"),
        ).operation_digest
        != without_decisions.operation_digest
    )
    with pytest.raises(ValueError, match="rebuild_strategy is required"):
        replace(active_target, rebuild_strategy=None)
    with pytest.raises(ValueError, match="only valid for force_rebuild"):
        replace(active_target, action="merge", rebuild_strategy="merge")
    with pytest.raises(ValueError, match="requires a target publication"):
        replace(
            active_target,
            publication=EMPTY_PUBLICATION,
            rebuild_strategy="merge",
        )


def test_undo_requires_absent_source_and_present_target_pointer() -> None:
    with pytest.raises(ValueError, match="source publication must be absent"):
        replace(_undo_move(), expected_source_publication=SOURCE_PUBLICATION)
    with pytest.raises(ValueError, match="target publication must be present"):
        replace(_undo_move(), expected_target_publication=EMPTY_PUBLICATION)
