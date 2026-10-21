from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import (
    ActiveDraftReassignmentTarget,
    DatasetError,
    DraftMutationResult,
    DraftStrategy,
    EmptyReassignmentTarget,
    MaterializeBaselineCommand,
    PublishedLineageConflict,
    PublishedReassignmentTarget,
    ReassignmentTarget,
    ReassignUnpublishedDraftDateCommand,
    TargetConflict,
    VersionExpectation,
)
from sqlalchemy.engine import Connection, Engine

from tests.integration.dataset_test_support import (
    NOW,
    DatasetIntegrationCase,
    SeededBaseline,
)
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers the shared fixture
)

pytestmark = pytest.mark.mysql


def _isolated_date() -> date:
    return date(2200, 1, 1) + timedelta(days=uuid4().int % 30000)


def _service(engine: Engine) -> DatasetService:
    return DatasetService(
        repository=MySqlDatasetRepository(engine),
        clock=lambda: NOW,
    )


def _expectation(result: DraftMutationResult) -> VersionExpectation:
    return VersionExpectation(
        result.version_id,
        result.data_revision,
        result.review_revision,
    )


def _materialize_command(
    case: DatasetIntegrationCase,
    baseline: SeededBaseline,
    *,
    strategy: DraftStrategy = "replace",
    expected_active_draft: VersionExpectation | None = None,
    expected_publication_version_id: int | None = None,
) -> MaterializeBaselineCommand:
    return MaterializeBaselineCommand(
        batch_id=baseline.batch_id,
        parse_baseline_id=baseline.parse_baseline_id,
        report_date=baseline.report_date,
        strategy=strategy,
        expected_active_draft=expected_active_draft,
        expected_publication_version_id=expected_publication_version_id,
        merge_decisions=(),
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
        reason="Materialize a fixture draft for date reassignment",
    )


def _reassign_command(
    case: DatasetIntegrationCase,
    source: DraftMutationResult,
    *,
    target_report_date: date,
    target: ReassignmentTarget,
    operation_token: UUID | None = None,
) -> ReassignUnpublishedDraftDateCommand:
    return ReassignUnpublishedDraftDateCommand(
        source_dataset_id=source.dataset_id,
        source_draft=_expectation(source),
        target_report_date=target_report_date,
        target=target,
        merge_decisions=(),
        actor_user_id=case.owner_user_id,
        operation_token=operation_token or uuid4(),
        reason="Correct the report date after reviewing the source upload",
    )


def _physical_connection_id(connection: Connection) -> int:
    driver_connection: Any = connection.connection.driver_connection
    return int(driver_connection.thread_id())


def _is_dataset_insert(statement: str) -> bool:
    normalised = " ".join(statement.split()).casefold()
    return normalised.startswith("insert into daily_datasets")


def _is_operation_result_insert(statement: str) -> bool:
    normalised = " ".join(statement.split()).casefold()
    return normalised.startswith("insert into draft_operation_results")


def _audit_reason(
    case: DatasetIntegrationCase,
    operation_token: UUID,
    *,
    event_type: str,
) -> object:
    return case.scalar(
        """
        SELECT JSON_UNQUOTE(JSON_EXTRACT(redacted_payload, '$.reason'))
        FROM audit_events
        WHERE request_id = :request_id
          AND event_type = :event_type
        """,
        {
            "request_id": str(operation_token),
            "event_type": event_type,
        },
    )


def test_reassign_to_empty_date_creates_new_version_without_rewriting_history(
    dataset_case: DatasetIntegrationCase,
) -> None:
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    dataset_case.track_dates(target_date)
    baseline = dataset_case.seed_baseline(
        report_date=source_date,
        variant="moveempty",
    )
    engine = dataset_case.runtime_engine()
    try:
        source = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, baseline)
        )
        original_dataset_id = dataset_case.scalar(
            "SELECT dataset_id FROM dataset_versions WHERE id = :version_id",
            {"version_id": source.version_id},
        )
        command = _reassign_command(
            dataset_case,
            source,
            target_report_date=target_date,
            target=EmptyReassignmentTarget(),
        )
        moved = _service(engine).reassign_unpublished_draft_date(command)
        recovered = _service(engine).reassign_unpublished_draft_date(command)
    finally:
        engine.dispose()

    assert recovered == moved
    assert moved.dataset_id != source.dataset_id
    assert moved.source_dataset_id == source.dataset_id
    assert moved.source_version_id == source.version_id
    assert moved.superseded_version_ids == (source.version_id,)
    assert moved.version_no == 1
    graph = dataset_case.dataset_graph((source_date, target_date))
    assert len(graph["datasets"]) == 2
    assert [(row["id"], row["status"]) for row in graph["versions"]] == [
        (source.version_id, "discarded"),
        (moved.version_id, "draft"),
    ]
    assert [row["dataset_id"] for row in graph["drafts"]] == [moved.dataset_id]
    assert [row["version_id"] for row in graph["drafts"]] == [moved.version_id]
    assert (
        dataset_case.scalar(
            "SELECT dataset_id FROM dataset_versions WHERE id = :version_id",
            {"version_id": source.version_id},
        )
        == original_dataset_id
    )
    assert (
        dataset_case.scalar(
            "SELECT report_date FROM import_batches WHERE id = :batch_id",
            {"batch_id": baseline.batch_id},
        )
        == source_date
    )
    assert (
        dataset_case.scalar(
            "SELECT report_date FROM daily_datasets WHERE id = :dataset_id",
            {"dataset_id": moved.dataset_id},
        )
        == target_date
    )
    assert {
        row["batch_id"]
        for row in graph["inputs"]
        if row["version_id"] == moved.version_id
    } == {baseline.batch_id}
    parents = [
        row for row in graph["parents"] if row["child_version_id"] == moved.version_id
    ]
    assert len(parents) == 1
    assert parents[0]["parent_version_id"] == source.version_id
    assert parents[0]["lineage_type"] == "moved_source"
    source_event = [
        row for row in graph["dispositions"] if row["version_id"] == source.version_id
    ]
    assert len(source_event) == 1
    assert source_event[0]["event_type"] == "date_reassigned"
    assert source_event[0]["successor_dataset_id"] == moved.dataset_id
    assert source_event[0]["successor_version_id"] == moved.version_id
    assert (
        _audit_reason(
            dataset_case,
            command.operation_token,
            event_type="draft_date_reassigned",
        )
        == command.reason
    )


@pytest.mark.parametrize("strategy", ["merge", "replace"])
def test_reassign_to_published_target_preserves_publication_and_explicit_strategy(
    strategy: DraftStrategy,
    dataset_case: DatasetIntegrationCase,
) -> None:
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    source_baseline = dataset_case.seed_baseline(
        report_date=source_date,
        variant=f"pubsource{strategy}",
    )
    target_baseline = dataset_case.seed_baseline(
        report_date=target_date,
        variant=f"pubtarget{strategy}",
    )
    engine = dataset_case.runtime_engine()
    try:
        source = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, source_baseline)
        )
        published = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, target_baseline)
        )
        dataset_case.mark_published(published.dataset_id, published.version_id)
        command = _reassign_command(
            dataset_case,
            source,
            target_report_date=target_date,
            target=PublishedReassignmentTarget(
                expected_dataset_id=published.dataset_id,
                expected_publication_version_id=published.version_id,
                strategy=strategy,
            ),
        )
        moved = _service(engine).reassign_unpublished_draft_date(command)
    finally:
        engine.dispose()

    assert moved.dataset_id == published.dataset_id
    assert moved.version_no == published.version_no + 1
    graph = dataset_case.dataset_graph((source_date, target_date))
    assert graph["publications"][0]["dataset_id"] == published.dataset_id
    assert graph["publications"][0]["version_id"] == published.version_id
    published_row = next(
        row for row in graph["versions"] if row["id"] == published.version_id
    )
    assert published_row["status"] == "published"
    assert [row["version_id"] for row in graph["drafts"]] == [moved.version_id]
    moved_inputs = {
        row["batch_id"]
        for row in graph["inputs"]
        if row["version_id"] == moved.version_id
    }
    expected_inputs = {source_baseline.batch_id}
    if strategy == "merge":
        expected_inputs.add(target_baseline.batch_id)
    assert moved_inputs == expected_inputs
    parent_types = {
        row["lineage_type"]
        for row in graph["parents"]
        if row["child_version_id"] == moved.version_id
    }
    assert "moved_source" in parent_types
    if strategy == "merge":
        assert "merge_target" in parent_types
    else:
        assert "merge_target" not in parent_types
    assert (
        dataset_case.scalar(
            "SELECT report_date FROM import_batches WHERE id = :batch_id",
            {"batch_id": source_baseline.batch_id},
        )
        == source_date
    )
    assert (
        dataset_case.scalar(
            "SELECT dataset_id FROM dataset_versions WHERE id = :version_id",
            {"version_id": source.version_id},
        )
        == source.dataset_id
    )


def test_reassign_to_active_target_merges_both_drafts_into_one_successor(
    dataset_case: DatasetIntegrationCase,
) -> None:
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    source_baseline = dataset_case.seed_baseline(
        report_date=source_date,
        variant="activesource",
    )
    target_baseline = dataset_case.seed_baseline(
        report_date=target_date,
        variant="activetarget",
    )
    engine = dataset_case.runtime_engine()
    try:
        source = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, source_baseline)
        )
        target = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, target_baseline)
        )
        command = _reassign_command(
            dataset_case,
            source,
            target_report_date=target_date,
            target=ActiveDraftReassignmentTarget(
                expected_dataset_id=target.dataset_id,
                expected_active_draft=_expectation(target),
                expected_publication_version_id=None,
                action="merge",
            ),
        )
        merged = _service(engine).reassign_unpublished_draft_date(command)
        recovered = _service(engine).reassign_unpublished_draft_date(command)
    finally:
        engine.dispose()

    assert recovered == merged
    assert merged.dataset_id == target.dataset_id
    assert set(merged.superseded_version_ids) == {
        source.version_id,
        target.version_id,
    }
    graph = dataset_case.dataset_graph((source_date, target_date))
    status_by_id = {row["id"]: row["status"] for row in graph["versions"]}
    assert status_by_id == {
        source.version_id: "discarded",
        target.version_id: "discarded",
        merged.version_id: "draft",
    }
    assert [row["version_id"] for row in graph["drafts"]] == [merged.version_id]
    assert {
        row["batch_id"]
        for row in graph["inputs"]
        if row["version_id"] == merged.version_id
    } == {source_baseline.batch_id, target_baseline.batch_id}
    event_by_version = {row["version_id"]: row for row in graph["dispositions"]}
    assert event_by_version[source.version_id]["event_type"] == "date_reassigned"
    assert event_by_version[target.version_id]["event_type"] == "superseded"
    assert {
        event_by_version[source.version_id]["successor_version_id"],
        event_by_version[target.version_id]["successor_version_id"],
    } == {merged.version_id}


def test_active_target_cancel_is_idempotent_and_changes_no_business_graph(
    dataset_case: DatasetIntegrationCase,
) -> None:
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    source_baseline = dataset_case.seed_baseline(
        report_date=source_date,
        variant="cancelsource",
    )
    target_baseline = dataset_case.seed_baseline(
        report_date=target_date,
        variant="canceltarget",
    )
    engine = dataset_case.runtime_engine()
    try:
        source = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, source_baseline)
        )
        target = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, target_baseline)
        )
        command = _reassign_command(
            dataset_case,
            source,
            target_report_date=target_date,
            target=ActiveDraftReassignmentTarget(
                expected_dataset_id=target.dataset_id,
                expected_active_draft=_expectation(target),
                expected_publication_version_id=None,
                action="cancel",
            ),
        )
        before = dataset_case.dataset_graph((source_date, target_date))
        cancelled = _service(engine).reassign_unpublished_draft_date(command)
        recovered = _service(engine).reassign_unpublished_draft_date(command)
    finally:
        engine.dispose()

    assert recovered == cancelled
    assert cancelled.status == "cancelled"
    assert cancelled.dataset_id == source.dataset_id
    assert cancelled.version_id == source.version_id
    assert cancelled.superseded_version_ids == ()
    assert cancelled.source_dataset_id is None
    assert cancelled.source_version_id is None
    assert dataset_case.dataset_graph((source_date, target_date)) == before
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_results "
            "WHERE operation_token = :token AND result_kind = 'cancelled'",
            {"token": command.operation_token.bytes},
        )
        == 1
    )
    assert (
        _audit_reason(
            dataset_case,
            command.operation_token,
            event_type="draft_date_reassignment_cancelled",
        )
        == command.reason
    )


def test_active_target_cancel_retry_ignores_incoming_disposition_history(
    dataset_case: DatasetIntegrationCase,
) -> None:
    original_date = _isolated_date()
    source_date = original_date + timedelta(days=1)
    target_date = original_date + timedelta(days=2)
    dataset_case.track_dates(source_date)
    original_baseline = dataset_case.seed_baseline(
        report_date=original_date,
        variant="incominghistory",
    )
    target_baseline = dataset_case.seed_baseline(
        report_date=target_date,
        variant="incomingtarget",
    )
    engine = dataset_case.runtime_engine()
    try:
        original = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, original_baseline)
        )
        source = _service(engine).reassign_unpublished_draft_date(
            _reassign_command(
                dataset_case,
                original,
                target_report_date=source_date,
                target=EmptyReassignmentTarget(),
            )
        )
        target = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, target_baseline)
        )
        command = _reassign_command(
            dataset_case,
            source,
            target_report_date=target_date,
            target=ActiveDraftReassignmentTarget(
                expected_dataset_id=target.dataset_id,
                expected_active_draft=_expectation(target),
                expected_publication_version_id=None,
                action="cancel",
            ),
        )

        cancelled = _service(engine).reassign_unpublished_draft_date(command)
        recovered = _service(engine).reassign_unpublished_draft_date(command)
    finally:
        engine.dispose()

    incoming = dataset_case.rows(
        """
        SELECT version_id, successor_dataset_id, successor_version_id
        FROM draft_disposition_events
        WHERE successor_dataset_id = :dataset_id
          AND successor_version_id = :version_id
        """,
        {"dataset_id": source.dataset_id, "version_id": source.version_id},
    )
    assert incoming == [
        {
            "version_id": original.version_id,
            "successor_dataset_id": source.dataset_id,
            "successor_version_id": source.version_id,
        }
    ]
    assert recovered == cancelled
    assert cancelled.status == "cancelled"
    assert cancelled.dataset_id == source.dataset_id
    assert cancelled.version_id == source.version_id
    assert cancelled.superseded_version_ids == ()


def test_unpublished_reassignment_rejects_a_draft_with_published_lineage(
    dataset_case: DatasetIntegrationCase,
) -> None:
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    dataset_case.track_dates(target_date)
    published_baseline = dataset_case.seed_baseline(
        report_date=source_date,
        variant="lineagepublished",
    )
    new_baseline = dataset_case.seed_baseline(
        report_date=source_date,
        variant="lineagedraft",
    )
    engine = dataset_case.runtime_engine()
    try:
        published = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, published_baseline)
        )
        dataset_case.mark_published(published.dataset_id, published.version_id)
        draft = _service(engine).materialize_baseline(
            _materialize_command(
                dataset_case,
                new_baseline,
                strategy="merge",
                expected_publication_version_id=published.version_id,
            )
        )
        before = dataset_case.dataset_graph((source_date, target_date))
        command = _reassign_command(
            dataset_case,
            draft,
            target_report_date=target_date,
            target=EmptyReassignmentTarget(),
        )
        with pytest.raises(PublishedLineageConflict):
            _service(engine).reassign_unpublished_draft_date(command)
    finally:
        engine.dispose()

    assert dataset_case.dataset_graph((source_date, target_date)) == before
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM daily_datasets WHERE report_date = :report_date",
            {"report_date": target_date},
        )
        == 0
    )
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_tokens "
            "WHERE operation_token = :token",
            {"token": command.operation_token.bytes},
        )
        == 0
    )


def test_two_sources_racing_into_previewed_empty_target_move_only_one(
    dataset_case: DatasetIntegrationCase,
) -> None:
    first_source_date = _isolated_date()
    second_source_date = first_source_date + timedelta(days=1)
    target_date = first_source_date + timedelta(days=2)
    dataset_case.track_dates(target_date)
    first_baseline = dataset_case.seed_baseline(
        report_date=first_source_date,
        variant="moveone",
    )
    second_baseline = dataset_case.seed_baseline(
        report_date=second_source_date,
        variant="movetwo",
    )
    setup_engine = dataset_case.runtime_engine()
    try:
        first_source = _service(setup_engine).materialize_baseline(
            _materialize_command(dataset_case, first_baseline)
        )
        second_source = _service(setup_engine).materialize_baseline(
            _materialize_command(dataset_case, second_baseline)
        )
    finally:
        setup_engine.dispose()

    commands = (
        _reassign_command(
            dataset_case,
            first_source,
            target_report_date=target_date,
            target=EmptyReassignmentTarget(),
        ),
        _reassign_command(
            dataset_case,
            second_source,
            target_report_date=target_date,
            target=EmptyReassignmentTarget(),
        ),
    )
    first_engine = dataset_case.runtime_engine()
    second_engine = dataset_case.runtime_engine()
    insert_barrier = Barrier(2)
    connection_ids: dict[str, int] = {}
    callback_seen: set[str] = set()

    def pause_target_insert(
        label: str,
    ) -> Callable[[Connection, object, str, object, object, bool], None]:
        def callback(
            connection: Connection,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            if _is_dataset_insert(statement) and label not in callback_seen:
                callback_seen.add(label)
                connection_ids[label] = _physical_connection_id(connection)
                insert_barrier.wait(timeout=10)

        return callback

    first_callback = pause_target_insert("first")
    second_callback = pause_target_insert("second")
    sa.event.listen(first_engine, "before_cursor_execute", first_callback)
    sa.event.listen(second_engine, "before_cursor_execute", second_callback)

    def move(
        engine: Engine,
        command: ReassignUnpublishedDraftDateCommand,
    ) -> DraftMutationResult | DatasetError:
        try:
            return _service(engine).reassign_unpublished_draft_date(command)
        except DatasetError as error:
            return error

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(move, first_engine, commands[0]),
                executor.submit(move, second_engine, commands[1]),
            )
            outcomes = [future.result(timeout=25) for future in futures]
    finally:
        insert_barrier.abort()
        sa.event.remove(first_engine, "before_cursor_execute", first_callback)
        sa.event.remove(second_engine, "before_cursor_execute", second_callback)
        first_engine.dispose()
        second_engine.dispose()

    moved = [item for item in outcomes if isinstance(item, DraftMutationResult)]
    conflicts = [item for item in outcomes if isinstance(item, TargetConflict)]
    assert connection_ids["first"] != connection_ids["second"]
    assert len(moved) == 1
    assert len(conflicts) == 1
    graph = dataset_case.dataset_graph(
        (first_source_date, second_source_date, target_date)
    )
    assert len(graph["datasets"]) == 3
    assert len(graph["versions"]) == 3
    assert len(graph["drafts"]) == 2
    assert moved[0].dataset_id in {row["dataset_id"] for row in graph["drafts"]}
    source_statuses = {
        row["id"]: row["status"]
        for row in graph["versions"]
        if row["id"] in {first_source.version_id, second_source.version_id}
    }
    assert sorted(source_statuses.values()) == ["discarded", "draft"]
    successful_source_id = moved[0].source_dataset_id
    assert successful_source_id in {first_source.dataset_id, second_source.dataset_id}
    losing_index = 1 if successful_source_id == first_source.dataset_id else 0
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_tokens "
            "WHERE operation_token = :token",
            {"token": commands[losing_index].operation_token.bytes},
        )
        == 0
    )


class _InjectedTransactionTailFailure(RuntimeError):
    pass


def test_tail_failure_rolls_back_both_sides_and_new_target_dataset(
    dataset_case: DatasetIntegrationCase,
) -> None:
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    dataset_case.track_dates(target_date)
    baseline = dataset_case.seed_baseline(
        report_date=source_date,
        variant="rollback",
    )
    engine = dataset_case.runtime_engine()
    try:
        source = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, baseline)
        )
        before = dataset_case.dataset_graph((source_date, target_date))
        command = _reassign_command(
            dataset_case,
            source,
            target_report_date=target_date,
            target=EmptyReassignmentTarget(),
        )
        injected = EventOnce()

        def fail_after_terminal_result(
            _connection: Connection,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            if _is_operation_result_insert(statement) and injected.take():
                raise _InjectedTransactionTailFailure(
                    "injected failure after terminal result insert"
                )

        sa.event.listen(
            engine,
            "after_cursor_execute",
            fail_after_terminal_result,
        )
        try:
            with pytest.raises(
                _InjectedTransactionTailFailure,
                match="terminal result",
            ):
                _service(engine).reassign_unpublished_draft_date(command)
        finally:
            sa.event.remove(
                engine,
                "after_cursor_execute",
                fail_after_terminal_result,
            )
    finally:
        engine.dispose()

    assert dataset_case.dataset_graph((source_date, target_date)) == before
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM daily_datasets WHERE report_date = :report_date",
            {"report_date": target_date},
        )
        == 0
    )
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_tokens "
            "WHERE operation_token = :token",
            {"token": command.operation_token.bytes},
        )
        == 0
    )
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_results "
            "WHERE operation_token = :token",
            {"token": command.operation_token.bytes},
        )
        == 0
    )


class EventOnce:
    """Thread-safe enough for one engine callback executed by one test thread."""

    def __init__(self) -> None:
        self._seen = False

    def take(self) -> bool:
        if self._seen:
            return False
        self._seen = True
        return True
