from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import (
    EmptyReassignmentTarget,
    ForceRebuildDraftCommand,
    MaterializeBaselineCommand,
    PublishedLineageConflict,
    ReassignUnpublishedDraftDateCommand,
    VersionExpectation,
)
from app.publications.commands import (
    CreatePublishedMoveRevisionCommand,
    CreateRevisionCommand,
    EmptyMoveTarget,
    FinalizePublishedMoveCommand,
    PublicationPointerExpectation,
    PublishCommand,
    PublishedMoveTarget,
    RollbackCommand,
    UndoPublishedMoveCommand,
)
from app.publications.queries import (
    UndoablePublishedMove,
    UndoablePublishedMoveQueryService,
)
from app.publications.repository import (
    MySqlPublicationRepository,
    PublicationCommitOutcomeUnknown,
    PublicationOperationConflict,
    PublicationPermissionDenied,
    PublicationStateConflict,
    PublicationTransactionBusy,
)
from app.publications.results import DraftCommandResult, PublicationCommandResult
from app.publications.service import PublicationService
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.dataset_test_support import NOW
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers the shared fixture
)
from tests.integration.publication_test_support import (
    PublicationIntegrationCase,
    PublishedDataset,
    ReadyPublicationDraft,
)
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401 - registers fixture
)

pytestmark = pytest.mark.mysql


def _isolated_date() -> date:
    return date(2300, 1, 1) + timedelta(days=uuid4().int % 30000)


def _service(engine: Engine) -> PublicationService:
    return PublicationService(
        repository=MySqlPublicationRepository(
            engine,
            retry_waiter=lambda _attempt: None,
        ),
        clock=lambda: NOW,
    )


class _LegacySuccessorDatasetRepository(MySqlDatasetRepository):
    """Reproduce successors written before the pending-move lineage guard."""

    @staticmethod
    def _assert_no_unfinalized_published_move_ancestry(
        _connection: Connection,
        *,
        version_id: int,
    ) -> None:
        del version_id


def _publish_command(
    ready: ReadyPublicationDraft,
    *,
    actor_user_id: int,
    expected_publication: PublicationPointerExpectation | None = None,
    operation_token: UUID | None = None,
    reason: str = "Publish the reviewed daily dataset",
) -> PublishCommand:
    return PublishCommand(
        dataset_id=ready.dataset_id,
        expected_draft=ready.expectation,
        expected_publication=(
            expected_publication or PublicationPointerExpectation(None, None)
        ),
        validation=ready.validation,
        confirmation=ready.confirmation,
        actor_user_id=actor_user_id,
        operation_token=operation_token or uuid4(),
        reason=reason,
    )


def _publish_direct(
    case: PublicationIntegrationCase,
    ready: ReadyPublicationDraft,
    *,
    expected_publication: PublicationPointerExpectation | None = None,
    actor_user_id: int | None = None,
) -> tuple[PublishCommand, PublicationCommandResult]:
    command = _publish_command(
        ready,
        actor_user_id=actor_user_id or case.owner_user_id,
        expected_publication=expected_publication,
    )
    engine = case.dataset_case.runtime_engine()
    try:
        result = _service(engine).publish(command)
    finally:
        engine.dispose()
    return command, result


def _create_ready_revision(
    case: PublicationIntegrationCase,
    published: PublishedDataset,
    *,
    actor_user_id: int | None = None,
) -> tuple[CreateRevisionCommand, DraftCommandResult, ReadyPublicationDraft]:
    actor_id = actor_user_id or case.owner_user_id
    command = CreateRevisionCommand(
        dataset_id=published.dataset_id,
        expected_publication=published.publication,
        actor_user_id=actor_id,
        operation_token=uuid4(),
        reason="Correct the current publication through an audited revision",
    )
    engine = case.dataset_case.runtime_engine()
    try:
        result = _service(engine).create_revision(command)
    finally:
        engine.dispose()
    ready = case.mark_ready(
        dataset_id=result.dataset_id,
        version_id=result.version_id,
        actor_user_id=actor_id,
    )
    return command, result, ready


def _create_replaced_publication(
    case: PublicationIntegrationCase,
) -> tuple[PublishedDataset, PublishedDataset]:
    report_date = _isolated_date()
    _baseline, first = case.create_published_dataset(
        report_date=report_date,
        variant="rollback-first",
    )
    _revision_command, _revision, ready = _create_ready_revision(case, first)
    replacement = case.publish(ready, expected_publication=first.publication)
    return first, replacement


def _create_move_revision(
    case: PublicationIntegrationCase,
    command: CreatePublishedMoveRevisionCommand,
) -> DraftCommandResult:
    engine = case.dataset_case.runtime_engine()
    try:
        return _service(engine).create_published_move_revision(command)
    finally:
        engine.dispose()


def _finalize_published_move(
    case: PublicationIntegrationCase,
    command: FinalizePublishedMoveCommand,
) -> PublicationCommandResult:
    engine = case.dataset_case.runtime_engine()
    try:
        return _service(engine).finalize_published_move(command)
    finally:
        engine.dispose()


def _undo_published_move(
    case: PublicationIntegrationCase,
    command: UndoPublishedMoveCommand,
) -> PublicationCommandResult:
    engine = case.dataset_case.runtime_engine()
    try:
        return _service(engine).undo_published_move(command)
    finally:
        engine.dispose()


def _undoable_published_moves(
    case: PublicationIntegrationCase,
) -> list[UndoablePublishedMove]:
    engine = case.dataset_case.runtime_engine()
    try:
        with Session(engine) as database_session:
            return UndoablePublishedMoveQueryService(database_session).list_moves()
    finally:
        engine.dispose()


def test_first_publish_create_revision_and_replacement_are_frozen_and_auditable(
    publication_case: PublicationIntegrationCase,
) -> None:
    case = publication_case
    report_date = _isolated_date()
    _baseline, draft = case.materialize_baseline(
        report_date=report_date,
        variant="ordinary-first",
    )
    ready = case.mark_ready(
        dataset_id=draft.dataset_id,
        version_id=draft.version_id,
    )
    first_command, first_result = _publish_direct(case, ready)

    recovery_engine = case.dataset_case.runtime_engine()
    try:
        recovered_first = _service(recovery_engine).publish(first_command)
        first_publication = case.publication_pointer(draft.dataset_id)
        first = PublishedDataset(
            dataset_id=draft.dataset_id,
            version_id=draft.version_id,
            version_no=draft.version_no,
            report_date=report_date,
            report_type="business_report",
            publication=first_publication,
            result=first_result,
        )
        revision_command, revision, ready_revision = _create_ready_revision(case, first)
        recovered_revision = _service(recovery_engine).create_revision(revision_command)
    finally:
        recovery_engine.dispose()

    replacement_command, replacement_result = _publish_direct(
        case,
        ready_revision,
        expected_publication=first.publication,
    )

    assert recovered_first == first_result
    assert recovered_revision == revision
    assert first_result.command_type == "publish"
    assert first_result.transitions[0].event_type == "published"
    assert first_result.transitions[0].previous_version_id is None
    assert first_result.transitions[0].next_version_id == draft.version_id
    assert revision.source_dataset_id == draft.dataset_id
    assert revision.source_version_id == draft.version_id
    assert revision.version_no == draft.version_no + 1
    assert replacement_result.transitions[0].event_type == "replaced"
    assert replacement_result.transitions[0].previous_version_id == draft.version_id
    assert replacement_result.transitions[0].next_version_id == revision.version_id
    assert case.publication_pointer(draft.dataset_id).version_id == revision.version_id

    graph = case.dataset_case.dataset_graph((report_date,))
    assert graph["drafts"] == []
    assert [(row["id"], row["status"]) for row in graph["versions"]] == [
        (draft.version_id, "published"),
        (revision.version_id, "published"),
    ]
    revision_parents = [
        row
        for row in graph["parents"]
        if row["child_version_id"] == revision.version_id
    ]
    assert len(revision_parents) == 1
    assert revision_parents[0]["parent_version_id"] == draft.version_id
    assert revision_parents[0]["lineage_type"] == "base"

    events = case.dataset_case.rows(
        """
        SELECT commands.operation_token, events.sequence_number,
               events.event_type, events.previous_version_id,
               events.next_version_id
        FROM publication_events AS events
        INNER JOIN publication_commands AS commands ON commands.id = events.command_id
        WHERE events.dataset_id = :dataset_id
        ORDER BY events.id
        """,
        {"dataset_id": draft.dataset_id},
    )
    assert [row["event_type"] for row in events] == ["published", "replaced"]
    assert [row["sequence_number"] for row in events] == [1, 1]
    assert {bytes(row["operation_token"]) for row in events} == {
        first_command.operation_token.bytes,
        replacement_command.operation_token.bytes,
    }
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_outbox WHERE publication_event_id IN ("
            "SELECT id FROM publication_events WHERE dataset_id = :dataset_id)",
            {"dataset_id": draft.dataset_id},
        )
        == 2
    )
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_command_results WHERE command_id IN ("
            "SELECT id FROM publication_commands WHERE actor_user_id = :actor_id)",
            {"actor_id": case.owner_user_id},
        )
        == 2
    )


def test_admin_can_review_finalize_and_reverse_a_cross_date_published_move(
    publication_case: PublicationIntegrationCase,
) -> None:
    """The source pointer changes only during finalization, never during review."""

    case = publication_case
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    _baseline, source = case.create_published_dataset(
        report_date=source_date,
        variant="cross-date-source",
    )
    move_review = CreatePublishedMoveRevisionCommand(
        source_dataset_id=source.dataset_id,
        expected_source_publication=source.publication,
        target_report_date=target_date,
        target=EmptyMoveTarget(),
        merge_decisions=(),
        actor_user_id=case.admin_user_id,
        operation_token=uuid4(),
        reason="Review a published report under its corrected report date",
    )

    move_draft = _create_move_revision(case, move_review)
    recovered_move_draft = _create_move_revision(case, move_review)
    assert recovered_move_draft == move_draft
    assert move_draft.result_kind == "published_move_revision_created"
    assert move_draft.source_dataset_id == source.dataset_id
    assert move_draft.source_version_id == source.version_id
    assert case.publication_pointer(source.dataset_id) == source.publication
    assert case.publication_pointer(
        move_draft.dataset_id
    ) == PublicationPointerExpectation(None, None)

    reviewed_target = case.mark_ready(
        dataset_id=move_draft.dataset_id,
        version_id=move_draft.version_id,
        actor_user_id=case.admin_user_id,
    )
    finalize = FinalizePublishedMoveCommand(
        move_revision_operation_token=move_review.operation_token,
        source_dataset_id=source.dataset_id,
        expected_source_publication=source.publication,
        target_dataset_id=move_draft.dataset_id,
        expected_target_draft=reviewed_target.expectation,
        expected_target_publication=PublicationPointerExpectation(None, None),
        validation=reviewed_target.validation,
        confirmation=reviewed_target.confirmation,
        actor_user_id=case.admin_user_id,
        operation_token=uuid4(),
        reason="Finalize the reviewed cross-date correction",
    )
    moved = _finalize_published_move(case, finalize)
    recovered_moved = _finalize_published_move(case, finalize)
    assert recovered_moved == moved
    assert moved.command_type == "move"
    assert [transition.event_type for transition in moved.transitions] == [
        "moved_out",
        "moved_in",
    ]
    assert moved.transitions[0].previous_version_id == source.version_id
    assert moved.transitions[0].next_version_id is None
    assert moved.transitions[1].previous_version_id is None
    assert moved.transitions[1].next_version_id == move_draft.version_id
    assert case.publication_pointer(source.dataset_id) == PublicationPointerExpectation(
        None,
        None,
    )
    target_publication = case.publication_pointer(move_draft.dataset_id)
    assert target_publication.version_id == move_draft.version_id

    candidates = _undoable_published_moves(case)
    candidate = next(
        item for item in candidates if item.move_command_id == moved.command_id
    )
    assert candidate.source_dataset_id == source.dataset_id
    assert candidate.source_report_date == source_date
    assert candidate.restore_source_version_id == source.version_id
    assert candidate.source_current_publication.version_id is None
    assert candidate.source_current_publication.published_at is None
    assert candidate.target_dataset_id == move_draft.dataset_id
    assert candidate.target_report_date == target_date
    assert candidate.restore_target_version_id is None
    assert (
        candidate.target_current_publication.version_id == target_publication.version_id
    )
    assert (
        candidate.target_current_publication.published_at
        == target_publication.published_at
    )
    assert candidate.moved_target_version_id == move_draft.version_id
    assert candidate.report_type == source.report_type

    undo = UndoPublishedMoveCommand(
        move_command_id=moved.command_id,
        source_dataset_id=source.dataset_id,
        expected_source_publication=PublicationPointerExpectation(None, None),
        restore_source_version_id=source.version_id,
        target_dataset_id=move_draft.dataset_id,
        expected_target_publication=target_publication,
        restore_target_version_id=None,
        actor_user_id=case.admin_user_id,
        operation_token=uuid4(),
        reason="Reverse the just-completed cross-date correction",
    )
    reversed_move = _undo_published_move(case, undo)
    assert _undo_published_move(case, undo) == reversed_move
    assert reversed_move.command_type == "reverse_move"
    assert [transition.event_type for transition in reversed_move.transitions] == [
        "move_reversed",
        "move_reversed",
    ]
    assert case.publication_pointer(source.dataset_id).version_id == source.version_id
    assert case.publication_pointer(
        move_draft.dataset_id
    ) == PublicationPointerExpectation(None, None)
    assert all(
        item.move_command_id != moved.command_id
        for item in _undoable_published_moves(case)
    )
    assert case.dataset_case.rows(
        """
        SELECT event_type, previous_version_id, next_version_id
        FROM publication_events
        WHERE command_id IN (:move_command_id, :reverse_command_id)
        ORDER BY command_id, sequence_number
        """,
        {
            "move_command_id": moved.command_id,
            "reverse_command_id": reversed_move.command_id,
        },
    ) == [
        {
            "event_type": "moved_out",
            "previous_version_id": source.version_id,
            "next_version_id": None,
        },
        {
            "event_type": "moved_in",
            "previous_version_id": None,
            "next_version_id": move_draft.version_id,
        },
        {
            "event_type": "move_reversed",
            "previous_version_id": None,
            "next_version_id": source.version_id,
        },
        {
            "event_type": "move_reversed",
            "previous_version_id": move_draft.version_id,
            "next_version_id": None,
        },
    ]


def test_undoable_move_query_preserves_an_existing_target_publication(
    publication_case: PublicationIntegrationCase,
) -> None:
    case = publication_case
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    _source_baseline, source = case.create_published_dataset(
        report_date=source_date,
        variant="undo-query-source",
    )
    _target_baseline, target = case.create_published_dataset(
        report_date=target_date,
        variant="undo-query-existing-target",
    )
    move_review = CreatePublishedMoveRevisionCommand(
        source_dataset_id=source.dataset_id,
        expected_source_publication=source.publication,
        target_report_date=target_date,
        target=PublishedMoveTarget(
            dataset_id=target.dataset_id,
            publication=target.publication,
            strategy="replace",
        ),
        merge_decisions=(),
        actor_user_id=case.admin_user_id,
        operation_token=uuid4(),
        reason="Move the source while preserving the existing target pointer",
    )
    move_draft = _create_move_revision(case, move_review)
    reviewed_target = case.mark_ready(
        dataset_id=move_draft.dataset_id,
        version_id=move_draft.version_id,
        actor_user_id=case.admin_user_id,
    )
    moved = _finalize_published_move(
        case,
        FinalizePublishedMoveCommand(
            move_revision_operation_token=move_review.operation_token,
            source_dataset_id=source.dataset_id,
            expected_source_publication=source.publication,
            target_dataset_id=target.dataset_id,
            expected_target_draft=reviewed_target.expectation,
            expected_target_publication=target.publication,
            validation=reviewed_target.validation,
            confirmation=reviewed_target.confirmation,
            actor_user_id=case.admin_user_id,
            operation_token=uuid4(),
            reason="Finalize the reviewed replacement move",
        ),
    )

    candidate = next(
        item
        for item in _undoable_published_moves(case)
        if item.move_command_id == moved.command_id
    )
    assert candidate.restore_source_version_id == source.version_id
    assert candidate.restore_target_version_id == target.version_id
    assert candidate.target_current_publication.version_id == move_draft.version_id
    assert candidate.target_current_publication.published_at == (
        case.publication_pointer(target.dataset_id).published_at
    )


@pytest.mark.parametrize(
    "target_has_publication",
    [False, True],
    ids=["ordinary-publish", "ordinary-replace"],
)
def test_ordinary_publish_rejects_a_reviewed_published_move_without_side_effects(
    publication_case: PublicationIntegrationCase,
    *,
    target_has_publication: bool,
) -> None:
    case = publication_case
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    _baseline, source = case.create_published_dataset(
        report_date=source_date,
        variant=f"guard-source-{target_has_publication}",
    )

    move_target: PublishedMoveTarget | EmptyMoveTarget
    if target_has_publication:
        _target_baseline, target = case.create_published_dataset(
            report_date=target_date,
            variant="guard-existing-target",
        )
        move_target = PublishedMoveTarget(
            dataset_id=target.dataset_id,
            publication=target.publication,
            strategy="replace",
        )
        expected_target_publication = target.publication
    else:
        move_target = EmptyMoveTarget()
        expected_target_publication = PublicationPointerExpectation(None, None)

    move_revision_command = CreatePublishedMoveRevisionCommand(
        source_dataset_id=source.dataset_id,
        expected_source_publication=source.publication,
        target_report_date=target_date,
        target=move_target,
        merge_decisions=(),
        actor_user_id=case.admin_user_id,
        operation_token=uuid4(),
        reason="Create a reviewed cross-date move that requires atomic finalization",
    )
    move_draft = _create_move_revision(case, move_revision_command)
    ready = case.mark_ready(
        dataset_id=move_draft.dataset_id,
        version_id=move_draft.version_id,
        actor_user_id=case.admin_user_id,
    )
    ordinary_publish = _publish_command(
        ready,
        actor_user_id=case.admin_user_id,
        expected_publication=expected_target_publication,
        reason="This ordinary publication path must be rejected",
    )
    before_draft = case.dataset_case.rows(
        """
        SELECT drafts.version_id, drafts.version_status, drafts.pointed_at,
               versions.status, versions.sealed_at
        FROM dataset_drafts AS drafts
        INNER JOIN dataset_versions AS versions
            ON versions.dataset_id = drafts.dataset_id
           AND versions.id = drafts.version_id
        WHERE drafts.dataset_id = :dataset_id
        """,
        {"dataset_id": move_draft.dataset_id},
    )
    before_event_count = int(
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_events "
            "WHERE dataset_id IN (:source_dataset_id, :target_dataset_id)",
            {
                "source_dataset_id": source.dataset_id,
                "target_dataset_id": move_draft.dataset_id,
            },
        )
        or 0
    )

    engine = case.dataset_case.runtime_engine()
    try:
        with pytest.raises(PublicationStateConflict, match="published move"):
            _service(engine).publish(ordinary_publish)
    finally:
        engine.dispose()

    assert case.publication_pointer(source.dataset_id) == source.publication
    assert (
        case.publication_pointer(move_draft.dataset_id) == expected_target_publication
    )
    assert (
        case.dataset_case.rows(
            """
        SELECT drafts.version_id, drafts.version_status, drafts.pointed_at,
               versions.status, versions.sealed_at
        FROM dataset_drafts AS drafts
        INNER JOIN dataset_versions AS versions
            ON versions.dataset_id = drafts.dataset_id
           AND versions.id = drafts.version_id
        WHERE drafts.dataset_id = :dataset_id
        """,
            {"dataset_id": move_draft.dataset_id},
        )
        == before_draft
    )
    assert before_draft == [
        {
            **before_draft[0],
            "version_id": move_draft.version_id,
            "version_status": "ready_for_publish",
            "status": "ready_for_publish",
            "sealed_at": None,
        }
    ]
    assert (
        int(
            case.dataset_case.scalar(
                "SELECT COUNT(*) FROM publication_events "
                "WHERE dataset_id IN (:source_dataset_id, :target_dataset_id)",
                {
                    "source_dataset_id": source.dataset_id,
                    "target_dataset_id": move_draft.dataset_id,
                },
            )
            or 0
        )
        == before_event_count
    )
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_commands "
            "WHERE operation_token = :operation_token",
            {"operation_token": ordinary_publish.operation_token.bytes},
        )
        == 0
    )


def test_data_manager_cannot_publish_a_legacy_successor_of_a_published_move(
    publication_case: PublicationIntegrationCase,
) -> None:
    """Ordinary publication must inspect the complete pending-move ancestry."""

    case = publication_case
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    _source_baseline, source = case.create_published_dataset(
        report_date=source_date,
        variant=f"lineage-guard-source-{uuid4().hex[:12]}",
    )
    move_revision_command = CreatePublishedMoveRevisionCommand(
        source_dataset_id=source.dataset_id,
        expected_source_publication=source.publication,
        target_report_date=target_date,
        target=EmptyMoveTarget(),
        merge_decisions=(),
        actor_user_id=case.admin_user_id,
        operation_token=uuid4(),
        reason="Create an administrator-only cross-date move review",
    )
    move_draft = _create_move_revision(case, move_revision_command)

    incoming = case.dataset_case.seed_baseline(
        report_date=target_date,
        variant=f"legacy-move-successor-{uuid4().hex[:12]}",
        actor_user_id=case.owner_user_id,
    )
    legacy_engine = case.dataset_case.runtime_engine()
    try:
        successor = DatasetService(
            repository=_LegacySuccessorDatasetRepository(legacy_engine),
            clock=lambda: NOW,
        ).force_rebuild_draft(
            ForceRebuildDraftCommand(
                batch_id=incoming.batch_id,
                parse_baseline_id=incoming.parse_baseline_id,
                report_date=target_date,
                expected_active_draft=VersionExpectation(
                    move_draft.version_id,
                    move_draft.data_revision,
                    move_draft.review_revision,
                ),
                expected_publication_version_id=None,
                actor_user_id=case.admin_user_id,
                operation_token=uuid4(),
                reason="Reproduce a successor created before the lineage fix",
            )
        )
        with case.dataset_case.migration_engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO version_parent_versions (
                        child_version_id, parent_version_id, parent_ordinal,
                        lineage_type, report_type, created_at
                    ) VALUES (
                        :child_version_id, :parent_version_id, 1,
                        'draft_predecessor', 'business_report', :created_at
                    )
                    """
                ),
                {
                    "child_version_id": successor.version_id,
                    "parent_version_id": move_draft.version_id,
                    "created_at": NOW,
                },
            )
    finally:
        legacy_engine.dispose()

    assert case.dataset_case.rows(
        "SELECT parent_version_id, lineage_type "
        "FROM version_parent_versions WHERE child_version_id = :version_id",
        {"version_id": successor.version_id},
    ) == [
        {
            "parent_version_id": move_draft.version_id,
            "lineage_type": "draft_predecessor",
        }
    ]
    ready = case.mark_ready(
        dataset_id=successor.dataset_id,
        version_id=successor.version_id,
        actor_user_id=case.owner_user_id,
    )
    command = _publish_command(
        ready,
        actor_user_id=case.owner_user_id,
        reason="A data manager must not publish a hidden move successor",
    )

    engine = case.dataset_case.runtime_engine()
    try:
        with pytest.raises(PublicationStateConflict, match="published move"):
            _service(engine).publish(command)
    finally:
        engine.dispose()

    assert case.publication_pointer(source.dataset_id) == source.publication
    assert case.publication_pointer(successor.dataset_id) == (
        PublicationPointerExpectation(None, None)
    )
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_commands "
            "WHERE operation_token = :operation_token",
            {"operation_token": command.operation_token.bytes},
        )
        == 0
    )


def test_pending_published_move_cannot_be_materialized_and_remains_finalizable(
    publication_case: PublicationIntegrationCase,
) -> None:
    """Reject context-losing successors while preserving the atomic admin path."""

    case = publication_case
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    _source_baseline, source = case.create_published_dataset(
        report_date=source_date,
        variant=f"preserve-move-source-{uuid4().hex[:12]}",
    )
    move_revision_command = CreatePublishedMoveRevisionCommand(
        source_dataset_id=source.dataset_id,
        expected_source_publication=source.publication,
        target_report_date=target_date,
        target=EmptyMoveTarget(),
        merge_decisions=(),
        actor_user_id=case.admin_user_id,
        operation_token=uuid4(),
        reason="Create the move draft whose atomic context must be preserved",
    )
    move_draft = _create_move_revision(case, move_revision_command)
    incoming = case.dataset_case.seed_baseline(
        report_date=target_date,
        variant=f"blocked-move-successor-{uuid4().hex[:12]}",
        actor_user_id=case.owner_user_id,
    )
    merge_command = MaterializeBaselineCommand(
        batch_id=incoming.batch_id,
        parse_baseline_id=incoming.parse_baseline_id,
        report_date=target_date,
        strategy="merge",
        expected_active_draft=VersionExpectation(
            move_draft.version_id,
            move_draft.data_revision,
            move_draft.review_revision,
        ),
        expected_publication_version_id=None,
        merge_decisions=(),
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
        reason="This merge would discard the administrator move context",
    )

    engine = case.dataset_case.runtime_engine()
    try:
        with pytest.raises(PublishedLineageConflict, match="published move"):
            DatasetService(
                repository=MySqlDatasetRepository(engine),
                clock=lambda: NOW,
            ).materialize_baseline(merge_command)
    finally:
        engine.dispose()

    assert (
        case.dataset_case.scalar(
            "SELECT version_id FROM dataset_drafts WHERE dataset_id = :dataset_id",
            {"dataset_id": move_draft.dataset_id},
        )
        == move_draft.version_id
    )
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_tokens "
            "WHERE operation_token = :operation_token",
            {"operation_token": merge_command.operation_token.bytes},
        )
        == 0
    )

    reviewed = case.mark_ready(
        dataset_id=move_draft.dataset_id,
        version_id=move_draft.version_id,
        actor_user_id=case.admin_user_id,
    )
    moved = _finalize_published_move(
        case,
        FinalizePublishedMoveCommand(
            move_revision_operation_token=move_revision_command.operation_token,
            source_dataset_id=source.dataset_id,
            expected_source_publication=source.publication,
            target_dataset_id=move_draft.dataset_id,
            expected_target_draft=reviewed.expectation,
            expected_target_publication=PublicationPointerExpectation(None, None),
            validation=reviewed.validation,
            confirmation=reviewed.confirmation,
            actor_user_id=case.admin_user_id,
            operation_token=uuid4(),
            reason="Finalize the preserved cross-date move atomically",
        ),
    )
    assert [transition.event_type for transition in moved.transitions] == [
        "moved_out",
        "moved_in",
    ]

    moved_publication = PublishedDataset(
        dataset_id=move_draft.dataset_id,
        version_id=move_draft.version_id,
        version_no=move_draft.version_no,
        report_date=target_date,
        report_type=source.report_type,
        publication=case.publication_pointer(move_draft.dataset_id),
        result=moved,
    )
    _revision_command, _revision, ordinary_revision = _create_ready_revision(
        case,
        moved_publication,
        actor_user_id=case.owner_user_id,
    )
    replacement = case.publish(
        ordinary_revision,
        expected_publication=moved_publication.publication,
        actor_user_id=case.owner_user_id,
        reason="Publish a genuine ordinary revision after the completed move",
    )
    assert replacement.result.transitions[0].event_type == "replaced"


def test_ordinary_publish_allows_an_unpublished_date_reassignment_with_moved_source(
    publication_case: PublicationIntegrationCase,
) -> None:
    case = publication_case
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    _baseline, source = case.materialize_baseline(
        report_date=source_date,
        variant=f"unpublished-reassignment-{uuid4().hex[:12]}",
    )
    reassign = ReassignUnpublishedDraftDateCommand(
        source_dataset_id=source.dataset_id,
        source_draft=VersionExpectation(
            source.version_id,
            source.data_revision,
            source.review_revision,
        ),
        target_report_date=target_date,
        target=EmptyReassignmentTarget(),
        merge_decisions=(),
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
        reason="Correct an unpublished upload date before ordinary publication",
    )
    engine = case.dataset_case.runtime_engine()
    try:
        moved = DatasetService(
            repository=MySqlDatasetRepository(engine),
            clock=lambda: NOW,
        ).reassign_unpublished_draft_date(reassign)
    finally:
        engine.dispose()

    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM version_parent_versions "
            "WHERE child_version_id = :version_id "
            "AND lineage_type = 'moved_source'",
            {"version_id": moved.version_id},
        )
        == 1
    )
    ready = case.mark_ready(
        dataset_id=moved.dataset_id,
        version_id=moved.version_id,
    )
    published = case.publish(ready)

    assert published.dataset_id == moved.dataset_id
    assert published.version_id == moved.version_id
    assert case.publication_pointer(moved.dataset_id).version_id == moved.version_id


def test_only_admin_can_rollback_to_a_previously_published_same_dataset_version(
    publication_case: PublicationIntegrationCase,
) -> None:
    case = publication_case
    first, replacement = _create_replaced_publication(case)
    denied = RollbackCommand(
        dataset_id=replacement.dataset_id,
        expected_publication=replacement.publication,
        target_version_id=first.version_id,
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
        reason="A data manager must not roll back publications",
    )
    engine = case.dataset_case.runtime_engine()
    try:
        with pytest.raises(PublicationPermissionDenied):
            _service(engine).rollback(denied)
        assert (
            case.publication_pointer(replacement.dataset_id) == replacement.publication
        )

        command = replace(
            denied,
            actor_user_id=case.admin_user_id,
            operation_token=uuid4(),
            reason="Restore the last known good publication",
        )
        rolled_back = _service(engine).rollback(command)
        recovered = _service(engine).rollback(command)
    finally:
        engine.dispose()

    assert recovered == rolled_back
    assert rolled_back.command_type == "rollback"
    assert len(rolled_back.transitions) == 1
    transition = rolled_back.transitions[0]
    assert transition.event_type == "rolled_back"
    assert transition.dataset_id == first.dataset_id == replacement.dataset_id
    assert transition.previous_version_id == replacement.version_id
    assert transition.next_version_id == first.version_id
    assert case.publication_pointer(first.dataset_id).version_id == first.version_id
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_outbox "
            "WHERE publication_event_id = :event_id",
            {"event_id": transition.event_id},
        )
        == 1
    )
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_commands "
            "WHERE operation_token = :operation_token",
            {"operation_token": denied.operation_token.bytes},
        )
        == 0
    )


class _LostPublishAcknowledgementRepository(MySqlPublicationRepository):
    def publish(
        self,
        command: PublishCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult:
        super().publish(command, occurred_at=occurred_at)
        raise PublicationCommitOutcomeUnknown("injected response loss after commit")


def test_publish_retry_recovers_the_committed_frozen_result_after_response_loss(
    publication_case: PublicationIntegrationCase,
) -> None:
    case = publication_case
    report_date = _isolated_date()
    _baseline, draft = case.materialize_baseline(
        report_date=report_date,
        variant="publish-ack-loss",
    )
    ready = case.mark_ready(dataset_id=draft.dataset_id, version_id=draft.version_id)
    command = _publish_command(ready, actor_user_id=case.owner_user_id)
    engine = case.dataset_case.runtime_engine()
    try:
        lost_service = PublicationService(
            repository=_LostPublishAcknowledgementRepository(engine),
            clock=lambda: NOW,
        )
        with pytest.raises(PublicationCommitOutcomeUnknown, match="response loss"):
            lost_service.publish(command)
        recovered = _service(engine).publish(command)
        with pytest.raises(PublicationOperationConflict):
            _service(engine).publish(
                replace(command, reason="Reuse the token for a changed request")
            )
    finally:
        engine.dispose()

    assert recovered.operation_token == command.operation_token
    assert recovered.transitions[0].next_version_id == draft.version_id
    assert case.publication_pointer(draft.dataset_id).version_id == draft.version_id
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_commands "
            "WHERE operation_token = :operation_token",
            {"operation_token": command.operation_token.bytes},
        )
        == 1
    )
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_events WHERE command_id = :command_id",
            {"command_id": recovered.command_id},
        )
        == 1
    )
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_outbox "
            "WHERE publication_event_id = :event_id",
            {"event_id": recovered.transitions[0].event_id},
        )
        == 1
    )


class _InjectedMySqlFailure(RuntimeError):
    pass


class _FailAfterDraftDelete:
    def __init__(self, *, error_code: int, failures: int) -> None:
        self.error_code = error_code
        self.failures = failures
        self.delete_attempts = 0

    def __call__(
        self,
        _connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalised = " ".join(statement.split()).casefold()
        if not normalised.startswith("delete from dataset_drafts"):
            return
        self.delete_attempts += 1
        if self.delete_attempts <= self.failures:
            raise DBAPIError(
                statement="injected publication transaction",
                params=None,
                orig=_InjectedMySqlFailure(
                    self.error_code,
                    "injected MySQL lock failure",
                ),
                connection_invalidated=False,
            )


@pytest.mark.parametrize("error_code", [1205, 1213], ids=["lock-timeout", "deadlock"])
def test_retryable_mysql_error_restarts_the_complete_publish_transaction(
    error_code: int,
    publication_case: PublicationIntegrationCase,
) -> None:
    case = publication_case
    report_date = _isolated_date()
    _baseline, draft = case.materialize_baseline(
        report_date=report_date,
        variant=f"retry-once-{error_code}",
    )
    ready = case.mark_ready(dataset_id=draft.dataset_id, version_id=draft.version_id)
    command = _publish_command(ready, actor_user_id=case.owner_user_id)
    engine = case.dataset_case.runtime_engine()
    injector = _FailAfterDraftDelete(error_code=error_code, failures=1)
    waits: list[int] = []
    sa.event.listen(engine, "after_cursor_execute", injector)
    try:
        result = PublicationService(
            repository=MySqlPublicationRepository(engine, retry_waiter=waits.append),
            clock=lambda: NOW,
        ).publish(command)
    finally:
        sa.event.remove(engine, "after_cursor_execute", injector)
        engine.dispose()

    assert injector.delete_attempts == 2
    assert waits == [1]
    assert result.transitions[0].next_version_id == draft.version_id
    assert case.publication_pointer(draft.dataset_id).version_id == draft.version_id
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_commands "
            "WHERE operation_token = :operation_token",
            {"operation_token": command.operation_token.bytes},
        )
        == 1
    )
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_events WHERE command_id = :command_id",
            {"command_id": result.command_id},
        )
        == 1
    )


@pytest.mark.parametrize("error_code", [1205, 1213], ids=["lock-timeout", "deadlock"])
def test_retryable_mysql_errors_stop_at_four_without_partial_publication_state(
    error_code: int,
    publication_case: PublicationIntegrationCase,
) -> None:
    case = publication_case
    report_date = _isolated_date()
    _baseline, draft = case.materialize_baseline(
        report_date=report_date,
        variant=f"retry-exhausted-{error_code}",
    )
    ready = case.mark_ready(dataset_id=draft.dataset_id, version_id=draft.version_id)
    command = _publish_command(ready, actor_user_id=case.owner_user_id)
    before = case.dataset_case.dataset_graph((report_date,))
    engine = case.dataset_case.runtime_engine()
    injector = _FailAfterDraftDelete(error_code=error_code, failures=4)
    waits: list[int] = []
    sa.event.listen(engine, "after_cursor_execute", injector)
    try:
        service = PublicationService(
            repository=MySqlPublicationRepository(engine, retry_waiter=waits.append),
            clock=lambda: NOW,
        )
        with pytest.raises(PublicationTransactionBusy, match="4 attempts"):
            service.publish(command)
    finally:
        sa.event.remove(engine, "after_cursor_execute", injector)
        engine.dispose()

    assert injector.delete_attempts == 4
    assert waits == [1, 2, 3]
    assert case.dataset_case.dataset_graph((report_date,)) == before
    assert case.publication_pointer(draft.dataset_id) == PublicationPointerExpectation(
        None,
        None,
    )
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_commands "
            "WHERE operation_token = :operation_token",
            {"operation_token": command.operation_token.bytes},
        )
        == 0
    )
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_command_results "
            "WHERE operation_token = :operation_token",
            {"operation_token": command.operation_token.bytes},
        )
        == 0
    )
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_events WHERE command_id IN ("
            "SELECT id FROM publication_commands "
            "WHERE operation_token = :operation_token)",
            {"operation_token": command.operation_token.bytes},
        )
        == 0
    )
