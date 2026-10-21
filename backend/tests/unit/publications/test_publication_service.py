from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from app.publications.commands import (
    CreatePublishedMoveRevisionCommand,
    CreateRevisionCommand,
    DraftPointerExpectation,
    EmptyMoveTarget,
    FinalizePublishedMoveCommand,
    PublicationConfirmation,
    PublicationPointerExpectation,
    PublishCommand,
    RollbackCommand,
    UndoPublishedMoveCommand,
    ValidationExpectation,
)
from app.publications.results import (
    DraftCommandResult,
    PublicationCommandResult,
    PublicationTransition,
)
from app.publications.service import PublicationService

TOKEN = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
NOW = datetime(2026, 8, 8, 5, 6, 7, 890123, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 8, 7, 5, 6, 7, 890123, tzinfo=UTC)


def _publish_command() -> PublishCommand:
    return PublishCommand(
        dataset_id=5,
        expected_draft=DraftPointerExpectation(
            version_id=23,
            status="ready_for_publish",
            data_revision=4,
            review_revision=7,
            pointed_at=NOW,
        ),
        expected_publication=PublicationPointerExpectation(None, None),
        validation=ValidationExpectation(
            run_id=31,
            version_id=23,
            data_revision=4,
            ruleset_version="rules-v3",
            data_digest=bytes.fromhex("11" * 32),
        ),
        confirmation=PublicationConfirmation(
            confirmed_report_date=date(2026, 8, 8),
            report_type="business_report",
            row_count=2,
            totals=(("units_ordered", "3"),),
        ),
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Publish reviewed data",
    )


def _rollback_command() -> RollbackCommand:
    return RollbackCommand(
        dataset_id=5,
        expected_publication=PublicationPointerExpectation(23, PUBLISHED_AT),
        target_version_id=17,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Restore the previous publication",
    )


def _create_revision_command() -> CreateRevisionCommand:
    return CreateRevisionCommand(
        dataset_id=5,
        expected_publication=PublicationPointerExpectation(17, PUBLISHED_AT),
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Create an editable revision",
    )


def _create_move_revision_command() -> CreatePublishedMoveRevisionCommand:
    return CreatePublishedMoveRevisionCommand(
        source_dataset_id=5,
        expected_source_publication=PublicationPointerExpectation(17, PUBLISHED_AT),
        target_report_date=date(2026, 8, 9),
        target=EmptyMoveTarget(),
        merge_decisions=(),
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Create a reviewed move revision",
    )


def _finalize_move_command() -> FinalizePublishedMoveCommand:
    publish = _publish_command()
    return FinalizePublishedMoveCommand(
        move_revision_operation_token=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        source_dataset_id=5,
        expected_source_publication=PublicationPointerExpectation(17, PUBLISHED_AT),
        target_dataset_id=6,
        expected_target_draft=publish.expected_draft,
        expected_target_publication=PublicationPointerExpectation(None, None),
        validation=publish.validation,
        confirmation=publish.confirmation,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Activate the reviewed move",
    )


def _undo_move_command() -> UndoPublishedMoveCommand:
    return UndoPublishedMoveCommand(
        move_command_id=37,
        source_dataset_id=5,
        expected_source_publication=PublicationPointerExpectation(None, None),
        restore_source_version_id=17,
        target_dataset_id=6,
        expected_target_publication=PublicationPointerExpectation(23, PUBLISHED_AT),
        restore_target_version_id=None,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Reverse the move",
    )


def _draft_result() -> DraftCommandResult:
    return DraftCommandResult(
        operation_token=TOKEN,
        result_kind="revision_created",
        dataset_id=5,
        version_id=23,
        version_no=4,
        status="draft",
        data_revision=0,
        review_revision=0,
        source_dataset_id=5,
        source_version_id=17,
        completed_at=NOW,
    )


def _result(command_type: str) -> PublicationCommandResult:
    transition = PublicationTransition(
        event_id=41,
        sequence_number=1,
        event_type="published" if command_type == "publish" else "rolled_back",
        dataset_id=5,
        peer_dataset_id=None,
        previous_version_id=None if command_type == "publish" else 23,
        next_version_id=23 if command_type == "publish" else 17,
    )
    return PublicationCommandResult(
        operation_token=TOKEN,
        command_id=37,
        command_type=command_type,  # type: ignore[arg-type]
        transitions=(transition,),
        completed_at=NOW,
    )


def _move_result(command_type: str) -> PublicationCommandResult:
    if command_type == "move":
        transitions = (
            PublicationTransition(41, 1, "moved_out", 5, 6, 17, None),
            PublicationTransition(42, 2, "moved_in", 6, 5, None, 23),
        )
    else:
        transitions = (
            PublicationTransition(43, 1, "move_reversed", 5, 6, None, 17),
            PublicationTransition(44, 2, "move_reversed", 6, 5, 23, None),
        )
    return PublicationCommandResult(
        operation_token=TOKEN,
        command_id=37,
        command_type=command_type,  # type: ignore[arg-type]
        transitions=transitions,
        completed_at=NOW,
    )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, datetime]] = []

    def publish(
        self,
        command: PublishCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult:
        self.calls.append(("publish", command, occurred_at))
        return _result("publish")

    def create_revision(
        self,
        command: CreateRevisionCommand,
        *,
        occurred_at: datetime,
    ) -> DraftCommandResult:
        self.calls.append(("create_revision", command, occurred_at))
        return _draft_result()

    def rollback(
        self,
        command: RollbackCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult:
        self.calls.append(("rollback", command, occurred_at))
        return _result("rollback")

    def create_published_move_revision(
        self,
        command: CreatePublishedMoveRevisionCommand,
        *,
        occurred_at: datetime,
    ) -> DraftCommandResult:
        self.calls.append(("create_published_move_revision", command, occurred_at))
        return DraftCommandResult(
            operation_token=TOKEN,
            result_kind="published_move_revision_created",
            dataset_id=6,
            version_id=23,
            version_no=1,
            status="draft",
            data_revision=0,
            review_revision=0,
            source_dataset_id=5,
            source_version_id=17,
            completed_at=NOW,
        )

    def finalize_published_move(
        self,
        command: FinalizePublishedMoveCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult:
        self.calls.append(("finalize_published_move", command, occurred_at))
        return _move_result("move")

    def undo_published_move(
        self,
        command: UndoPublishedMoveCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult:
        self.calls.append(("undo_published_move", command, occurred_at))
        return _move_result("reverse_move")


def test_service_attaches_one_clock_value_to_each_atomic_command() -> None:
    repository = _Repository()
    clock_calls: list[None] = []

    def clock() -> datetime:
        clock_calls.append(None)
        return NOW

    service = PublicationService(repository=repository, clock=clock)
    create_revision = _create_revision_command()
    create_move_revision = _create_move_revision_command()
    finalize_move = _finalize_move_command()
    undo_move = _undo_move_command()
    publish = _publish_command()
    rollback = _rollback_command()

    assert service.create_revision(create_revision) == _draft_result()
    assert service.publish(publish) == _result("publish")
    assert service.rollback(rollback) == _result("rollback")
    assert (
        service.create_published_move_revision(create_move_revision).result_kind
        == "published_move_revision_created"
    )
    assert service.finalize_published_move(finalize_move) == _move_result("move")
    assert service.undo_published_move(undo_move) == _move_result("reverse_move")
    assert repository.calls == [
        ("create_revision", create_revision, NOW),
        ("publish", publish, NOW),
        ("rollback", rollback, NOW),
        ("create_published_move_revision", create_move_revision, NOW),
        ("finalize_published_move", finalize_move, NOW),
        ("undo_published_move", undo_move, NOW),
    ]
    assert len(clock_calls) == 6
