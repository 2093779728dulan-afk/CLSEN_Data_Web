from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
from threading import Barrier, Event
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from app.api.datasets import preview_merge_conflicts
from app.auth.sessions import Principal
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import (
    ActiveDraftConflict,
    DatasetCommitOutcomeUnknown,
    DatasetError,
    DatasetPermissionDenied,
    DiscardDraftCommand,
    DraftMutationResult,
    DraftStrategy,
    ForceRebuildDraftCommand,
    MaterializeBaselineCommand,
    MergeDecision,
    OperationConflict,
    VersionExpectation,
)
from app.parsers.repository import MySqlParseRepository
from app.parsers.workflow import ConfirmAndParseCommand, ParseWorkflow, SuccessfulParse
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
    return date(2100, 1, 1) + timedelta(days=uuid4().int % 30000)


def _service(engine: Engine) -> DatasetService:
    return DatasetService(
        repository=MySqlDatasetRepository(engine),
        clock=lambda: NOW,
    )


def _expectation(result: DraftMutationResult) -> VersionExpectation:
    return VersionExpectation(
        version_id=result.version_id,
        data_revision=result.data_revision,
        review_revision=result.review_revision,
    )


def _materialize_command(
    case: DatasetIntegrationCase,
    baseline: SeededBaseline,
    *,
    operation_token: UUID | None = None,
    strategy: DraftStrategy = "replace",
    expected_active_draft: VersionExpectation | None = None,
    expected_publication_version_id: int | None = None,
    merge_decisions: tuple[MergeDecision, ...] = (),
    actor_user_id: int | None = None,
    reason: str = "Materialize the reviewed parse baseline",
) -> MaterializeBaselineCommand:
    return MaterializeBaselineCommand(
        batch_id=baseline.batch_id,
        parse_baseline_id=baseline.parse_baseline_id,
        report_date=baseline.report_date,
        strategy=strategy,
        expected_active_draft=expected_active_draft,
        expected_publication_version_id=expected_publication_version_id,
        merge_decisions=merge_decisions,
        actor_user_id=actor_user_id or case.owner_user_id,
        operation_token=operation_token or uuid4(),
        reason=reason,
    )


def _physical_connection_id(connection: Connection) -> int:
    driver_connection: Any = connection.connection.driver_connection
    return int(driver_connection.thread_id())


def _normalise_sql(statement: str) -> str:
    return " ".join(statement.split()).casefold()


def _is_dataset_insert(statement: str) -> bool:
    return _normalise_sql(statement).startswith("insert into daily_datasets")


def _is_operation_token_insert(statement: str) -> bool:
    return _normalise_sql(statement).startswith("insert into draft_operation_tokens")


def _is_dataset_lock(statement: str) -> bool:
    normalised = _normalise_sql(statement)
    return (
        normalised.startswith("update daily_dataset_locks")
        and "set lock_revision" in normalised
    )


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


def test_first_baseline_materialization_builds_one_isolated_draft_graph(
    dataset_case: DatasetIntegrationCase,
) -> None:
    primary_date = _isolated_date()
    sentinel_date = primary_date + timedelta(days=1)
    primary = dataset_case.seed_baseline(
        report_date=primary_date,
        variant="primary",
    )
    sentinel = dataset_case.seed_baseline(
        report_date=sentinel_date,
        report_type="return_report",
        variant="sentinel",
    )
    engine = dataset_case.runtime_engine()
    try:
        sentinel_result = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, sentinel)
        )
        sentinel_before = dataset_case.dataset_graph((sentinel_date,))

        command = _materialize_command(
            dataset_case,
            primary,
            reason="  Create the first reviewed daily draft  ",
        )
        result = _service(engine).materialize_baseline(command)
    finally:
        engine.dispose()

    assert result.status == "draft"
    assert result.version_no == 1
    assert result.data_revision == 0
    assert result.review_revision == 0
    assert command.reason == "Create the first reviewed daily draft"
    assert (
        _audit_reason(
            dataset_case,
            command.operation_token,
            event_type="draft_materialized",
        )
        == command.reason
    )
    assert sentinel_result.dataset_id != result.dataset_id
    assert dataset_case.dataset_graph((sentinel_date,)) == sentinel_before

    graph = dataset_case.dataset_graph((primary_date,))
    assert len(graph["datasets"]) == 1
    assert graph["dataset_locks"] == [{"dataset_id": result.dataset_id}]
    assert [row["id"] for row in graph["versions"]] == [result.version_id]
    assert graph["versions"][0]["status"] == "draft"
    assert len(graph["drafts"]) == 1
    assert graph["drafts"][0]["dataset_id"] == result.dataset_id
    assert graph["drafts"][0]["version_id"] == result.version_id
    assert graph["drafts"][0]["version_status"] == "draft"
    assert graph["publications"] == []
    assert len(graph["snapshots"]) == 1
    assert graph["snapshots"][0]["snapshot_kind"] == "replacement"
    assert graph["snapshots"][0]["row_count"] == 2
    assert len(graph["members"]) == 1
    assert graph["members"][0]["member_type"] == "parse_baseline"
    assert graph["members"][0]["member_role"] == "parse_input"
    assert graph["members"][0]["parse_baseline_id"] == primary.parse_baseline_id
    assert len(graph["base_rows"]) == 2
    assert len(graph["version_rows"]) == 2
    assert len(graph["business_rows"]) == 2
    assert graph["return_rows"] == []
    assert {row["batch_id"] for row in graph["inputs"]} == {primary.batch_id}
    assert {row["row_state"] for row in graph["base_rows"]} == {"active"}
    assert {row["row_state"] for row in graph["version_rows"]} == {"active"}
    assert (
        dataset_case.scalar(
            "SELECT report_date FROM import_batches WHERE id = :batch_id",
            {"batch_id": primary.batch_id},
        )
        == primary_date
    )

    baseline_values = dataset_case.rows(
        """
        SELECT typed.sku, typed.title, typed.units_ordered,
               typed.ordered_product_sales
        FROM business_parse_baseline_rows AS typed
        INNER JOIN parse_baseline_rows AS source_rows
            ON source_rows.id = typed.parse_baseline_row_id
        WHERE source_rows.parse_baseline_id = :baseline_id
        ORDER BY source_rows.row_ordinal
        """,
        {"baseline_id": primary.parse_baseline_id},
    )
    draft_values = dataset_case.rows(
        """
        SELECT typed.sku, typed.title, typed.units_ordered,
               typed.ordered_product_sales
        FROM business_report_rows AS typed
        INNER JOIN version_rows AS version_row_records
            ON version_row_records.id = typed.version_row_id
        WHERE version_row_records.version_id = :version_id
        ORDER BY version_row_records.row_ordinal
        """,
        {"version_id": result.version_id},
    )
    assert draft_values == baseline_values


def test_merge_preview_api_reads_the_complete_mysql_conflict_matrix(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="preview",
    )
    engine = dataset_case.runtime_engine()
    try:
        target = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, baseline)
        )
        response = preview_merge_conflicts(
            target_version_id=target.version_id,
            source_kind="parse_baseline",
            source_id=baseline.parse_baseline_id,
            _principal=Principal(
                user_id=dataset_case.owner_user_id,
                username="merge-preview-owner",
                display_name="Merge preview owner",
                roles=frozenset({"data_manager"}),
                session_id=1,
                csrf_token_hash=b"merge-preview-csrf",
            ),
            engine=engine,
        )
    finally:
        engine.dispose()

    assert response.report_type == "business_report"
    assert response.target_version_id == target.version_id
    assert response.source_kind == "parse_baseline"
    assert response.source_id == baseline.parse_baseline_id
    assert len(response.conflicts) == 2
    assert [item.target_row_ordinal for item in response.conflicts] == [1, 2]
    assert [item.source_row_ordinal for item in response.conflicts] == [1, 2]
    assert all(
        item.target_values["sku"] == item.source_values["sku"]
        for item in response.conflicts
    )


def test_discarded_draft_source_batch_can_be_reparsed_without_rewriting_history(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="discard-reparse",
    )
    engine = dataset_case.runtime_engine()
    try:
        draft = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, baseline)
        )
        discarded = _service(engine).discard_active_draft(
            DiscardDraftCommand(
                dataset_id=draft.dataset_id,
                expected_active_draft=_expectation(draft),
                actor_user_id=dataset_case.owner_user_id,
                operation_token=uuid4(),
                reason="Discard the draft before correcting the parse",
            )
        )
        reparsed = ParseWorkflow(
            repository=MySqlParseRepository(engine),
            store=dataset_case.store,
            clock=lambda: NOW,
        ).confirm_and_parse(
            ConfirmAndParseCommand(
                batch_id=baseline.batch_id,
                report_type="business_report",
                report_date=report_date,
                encoding="utf-8-sig",
                site_config_version_id=1,
                actor_user_id=dataset_case.owner_user_id,
                operation_token=uuid4(),
            )
        )
    finally:
        engine.dispose()

    assert discarded.status == "discarded"
    assert isinstance(reparsed, SuccessfulParse)
    assert reparsed.parse_attempt_id != baseline.parse_attempt_id
    assert reparsed.parse_baseline_id != baseline.parse_baseline_id
    assert (
        dataset_case.scalar(
            "SELECT status FROM dataset_versions WHERE id = :version_id",
            {"version_id": draft.version_id},
        )
        == "discarded"
    )
    assert (
        dataset_case.scalar(
            """
            SELECT parse_baseline_id
            FROM version_base_snapshot_members
            WHERE snapshot_id = (
                SELECT id FROM version_base_snapshots
                WHERE version_id = :version_id
            )
              AND member_type = 'parse_baseline'
            """,
            {"version_id": draft.version_id},
        )
        == baseline.parse_baseline_id
    )
    assert (
        dataset_case.scalar(
            """
            SELECT current_successful_parse_attempt_id
            FROM import_batches WHERE id = :batch_id
            """,
            {"batch_id": baseline.batch_id},
        )
        == reparsed.parse_attempt_id
    )


def test_merging_into_active_draft_creates_a_complete_successor(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    first_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="first",
    )
    second_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="second",
    )
    engine = dataset_case.runtime_engine()
    try:
        first = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, first_baseline)
        )
        with dataset_case.migration_engine.begin() as connection:
            first_row_id = connection.scalar(
                sa.text(
                    "SELECT id FROM version_rows "
                    "WHERE version_id = :version_id AND row_ordinal = 1"
                ),
                {"version_id": first.version_id},
            )
            excluded_row_id = connection.scalar(
                sa.text(
                    "SELECT id FROM version_rows "
                    "WHERE version_id = :version_id AND row_ordinal = 2"
                ),
                {"version_id": first.version_id},
            )
            assert first_row_id is not None and excluded_row_id is not None
            connection.execute(
                sa.text(
                    "UPDATE business_report_rows "
                    "SET title = 'Human corrected title' "
                    "WHERE version_id = :version_id "
                    "AND version_row_id = :row_id"
                ),
                {"version_id": first.version_id, "row_id": first_row_id},
            )
            connection.execute(
                sa.text(
                    "UPDATE version_rows SET row_state = 'excluded' "
                    "WHERE version_id = :version_id AND id = :row_id"
                ),
                {"version_id": first.version_id, "row_id": excluded_row_id},
            )
            connection.execute(
                sa.text(
                    "UPDATE dataset_versions SET data_revision = 2 "
                    "WHERE id = :version_id"
                ),
                {"version_id": first.version_id},
            )

        successor = _service(engine).materialize_baseline(
            _materialize_command(
                dataset_case,
                second_baseline,
                strategy="merge",
                expected_active_draft=VersionExpectation(first.version_id, 2, 0),
            )
        )
    finally:
        engine.dispose()

    assert successor.dataset_id == first.dataset_id
    assert successor.version_no == first.version_no + 1
    assert successor.superseded_version_ids == (first.version_id,)
    graph = dataset_case.dataset_graph((report_date,))
    assert [(row["id"], row["status"]) for row in graph["versions"]] == [
        (first.version_id, "discarded"),
        (successor.version_id, "draft"),
    ]
    assert graph["versions"][0]["sealed_at"] is not None
    assert [row["version_id"] for row in graph["drafts"]] == [successor.version_id]
    successor_parents = [
        row
        for row in graph["parents"]
        if row["child_version_id"] == successor.version_id
    ]
    assert len(successor_parents) == 1
    assert successor_parents[0]["parent_version_id"] == first.version_id
    assert successor_parents[0]["lineage_type"] == "draft_predecessor"
    successor_inputs = [
        row for row in graph["inputs"] if row["version_id"] == successor.version_id
    ]
    assert [row["batch_id"] for row in successor_inputs] == [
        first_baseline.batch_id,
        second_baseline.batch_id,
    ]
    successor_rows = [
        row
        for row in graph["version_rows"]
        if row["version_id"] == successor.version_id
    ]
    assert len(successor_rows) == 4
    assert [row["row_state"] for row in successor_rows].count("excluded") == 1
    successor_titles = {
        row["title"]
        for row in graph["business_rows"]
        if row["version_id"] == successor.version_id
    }
    assert "Human corrected title" in successor_titles
    events = [
        row for row in graph["dispositions"] if row["version_id"] == first.version_id
    ]
    assert len(events) == 1
    assert events[0]["event_type"] == "superseded"
    assert events[0]["successor_version_id"] == successor.version_id
    assert events[0]["terminal_data_revision"] == 2


def test_merge_resolves_every_pair_when_target_has_a_duplicate_fingerprint(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    first_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="duplicate-target",
    )
    incoming_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="duplicate-source",
    )
    engine = dataset_case.runtime_engine()
    try:
        first = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, first_baseline)
        )
        with dataset_case.migration_engine.begin() as connection:
            target_rows = (
                connection.execute(
                    sa.text(
                        """
                        SELECT row_records.id, row_records.row_ordinal,
                               typed.child_asin, typed.sku
                        FROM version_rows AS row_records
                        INNER JOIN business_report_rows AS typed
                            ON typed.version_row_id = row_records.id
                           AND typed.version_id = row_records.version_id
                        WHERE row_records.version_id = :version_id
                        ORDER BY row_records.row_ordinal, row_records.id
                        """
                    ),
                    {"version_id": first.version_id},
                )
                .mappings()
                .all()
            )
            assert len(target_rows) == 2
            canonical_target, duplicate_target = target_rows
            incoming_conflict_row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT source_rows.id, typed.child_asin, typed.sku
                        FROM parse_baseline_rows AS source_rows
                        INNER JOIN business_parse_baseline_rows AS typed
                            ON typed.parse_baseline_row_id = source_rows.id
                        WHERE source_rows.parse_baseline_id = :baseline_id
                          AND source_rows.row_ordinal = 1
                        """
                    ),
                    {"baseline_id": incoming_baseline.parse_baseline_id},
                )
                .mappings()
                .one()
            )
            conflict_child_asin = str(incoming_conflict_row["child_asin"])
            conflict_sku = str(incoming_conflict_row["sku"])
            connection.execute(
                sa.text(
                    """
                        UPDATE business_report_rows
                        SET child_asin = :child_asin, sku = :sku
                        WHERE version_id = :version_id
                        """
                ),
                {
                    "child_asin": conflict_child_asin,
                    "sku": conflict_sku,
                    "version_id": first.version_id,
                },
            )
            revised_data_revision = first.data_revision + 1
            connection.execute(
                sa.text(
                    "UPDATE dataset_versions SET data_revision = :data_revision "
                    "WHERE id = :version_id"
                ),
                {
                    "data_revision": revised_data_revision,
                    "version_id": first.version_id,
                },
            )
            incoming_conflict_row_id = int(incoming_conflict_row["id"])

        successor = _service(engine).materialize_baseline(
            _materialize_command(
                dataset_case,
                incoming_baseline,
                strategy="merge",
                expected_active_draft=VersionExpectation(
                    first.version_id,
                    revised_data_revision,
                    first.review_revision,
                ),
                merge_decisions=(
                    MergeDecision(
                        target_row_id=int(duplicate_target["id"]),
                        source_row_id=incoming_conflict_row_id,
                        action="keep_target",
                    ),
                    MergeDecision(
                        target_row_id=int(canonical_target["id"]),
                        source_row_id=incoming_conflict_row_id,
                        action="keep_target",
                    ),
                ),
            )
        )
    finally:
        engine.dispose()

    graph = dataset_case.dataset_graph((report_date,))
    successor_rows = [
        row
        for row in graph["version_rows"]
        if row["version_id"] == successor.version_id
    ]
    successor_base_rows = [
        row for row in graph["base_rows"] if row["version_id"] == successor.version_id
    ]
    successor_business_rows = [
        row
        for row in graph["business_rows"]
        if row["version_id"] == successor.version_id
    ]

    assert len(successor_rows) == 3
    assert [row["merge_action"] for row in successor_base_rows] == [
        "keep_target",
        "keep_target",
        None,
    ]
    assert [row["sku"] for row in successor_business_rows].count(conflict_sku) == 2
    assert {
        row["batch_id"]
        for row in graph["inputs"]
        if row["version_id"] == successor.version_id
    } == {first_baseline.batch_id, incoming_baseline.batch_id}


def test_owner_discard_is_idempotent_and_other_manager_is_denied(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="discard",
    )
    engine = dataset_case.runtime_engine()
    try:
        created = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, baseline)
        )
        expected = _expectation(created)
        denied = DiscardDraftCommand(
            dataset_id=created.dataset_id,
            expected_active_draft=expected,
            actor_user_id=dataset_case.other_manager_user_id,
            operation_token=uuid4(),
            reason="Attempt to discard another manager's draft",
        )
        before_denied = dataset_case.dataset_graph((report_date,))
        with pytest.raises(DatasetPermissionDenied):
            _service(engine).discard_active_draft(denied)
        assert dataset_case.dataset_graph((report_date,)) == before_denied

        command = DiscardDraftCommand(
            dataset_id=created.dataset_id,
            expected_active_draft=expected,
            actor_user_id=dataset_case.owner_user_id,
            operation_token=uuid4(),
            reason="The imported draft is not usable",
        )
        discarded = _service(engine).discard_active_draft(command)
        recovered = _service(engine).discard_active_draft(command)
    finally:
        engine.dispose()

    assert recovered == discarded
    assert discarded.status == "discarded"
    assert discarded.version_id == created.version_id
    graph = dataset_case.dataset_graph((report_date,))
    assert graph["drafts"] == []
    assert graph["versions"][0]["status"] == "discarded"
    assert graph["versions"][0]["sealed_at"] is not None
    events = [
        row for row in graph["dispositions"] if row["version_id"] == created.version_id
    ]
    assert len(events) == 1
    assert events[0]["event_type"] == "discarded"
    assert events[0]["successor_version_id"] is None
    assert (
        _audit_reason(
            dataset_case,
            command.operation_token,
            event_type="draft_discarded",
        )
        == command.reason
    )
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_results "
            "WHERE operation_token = :token",
            {"token": command.operation_token.bytes},
        )
        == 1
    )


def test_only_admin_can_force_rebuild_an_active_draft(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    first_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="forceold",
    )
    replacement_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="forcenew",
    )
    engine = dataset_case.runtime_engine()
    try:
        first = _service(engine).materialize_baseline(
            _materialize_command(dataset_case, first_baseline)
        )
        denied = ForceRebuildDraftCommand(
            batch_id=replacement_baseline.batch_id,
            parse_baseline_id=replacement_baseline.parse_baseline_id,
            report_date=report_date,
            expected_active_draft=_expectation(first),
            expected_publication_version_id=None,
            actor_user_id=dataset_case.owner_user_id,
            operation_token=uuid4(),
            reason="A data manager must not force rebuild",
        )
        with pytest.raises(DatasetPermissionDenied):
            _service(engine).force_rebuild_draft(denied)

        command = replace(
            denied,
            actor_user_id=dataset_case.admin_user_id,
            operation_token=uuid4(),
            reason="Administrator approved a complete rebuild",
        )
        rebuilt = _service(engine).force_rebuild_draft(command)
        recovered = _service(engine).force_rebuild_draft(command)
    finally:
        engine.dispose()

    assert recovered == rebuilt
    assert rebuilt.superseded_version_ids == (first.version_id,)
    graph = dataset_case.dataset_graph((report_date,))
    assert [row["version_id"] for row in graph["drafts"]] == [rebuilt.version_id]
    assert [(row["id"], row["status"]) for row in graph["versions"]] == [
        (first.version_id, "discarded"),
        (rebuilt.version_id, "draft"),
    ]
    events = [
        row for row in graph["dispositions"] if row["version_id"] == first.version_id
    ]
    assert len(events) == 1
    assert events[0]["event_type"] == "force_rebuilt"
    assert events[0]["successor_version_id"] == rebuilt.version_id
    assert (
        _audit_reason(
            dataset_case,
            command.operation_token,
            event_type="draft_force_rebuilt",
        )
        == command.reason
    )
    rebuilt_inputs = [
        row for row in graph["inputs"] if row["version_id"] == rebuilt.version_id
    ]
    assert [row["batch_id"] for row in rebuilt_inputs] == [
        replacement_baseline.batch_id
    ]


def test_materialize_token_retry_recovers_without_allocating_another_version(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="retry",
    )
    command = _materialize_command(dataset_case, baseline, operation_token=uuid4())
    engine = dataset_case.runtime_engine()
    try:
        first = _service(engine).materialize_baseline(command)
        before_retry = dataset_case.dataset_graph((report_date,))
        second = _service(engine).materialize_baseline(command)
        with pytest.raises(OperationConflict):
            _service(engine).materialize_baseline(
                replace(command, reason="Reuse the token with changed command data")
            )
    finally:
        engine.dispose()

    assert second == first
    assert dataset_case.dataset_graph((report_date,)) == before_retry
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_tokens "
            "WHERE operation_token = :token",
            {"token": command.operation_token.bytes},
        )
        == 1
    )
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_results "
            "WHERE operation_token = :token",
            {"token": command.operation_token.bytes},
        )
        == 1
    )


def test_materialize_retry_returns_frozen_result_after_version_state_changes(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="frozensnapshot",
    )
    command = _materialize_command(dataset_case, baseline, operation_token=uuid4())
    engine = dataset_case.runtime_engine()
    try:
        first = _service(engine).materialize_baseline(command)
        with dataset_case.migration_engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE dataset_versions
                    SET data_revision = 3, review_revision = 2
                    WHERE id = :version_id
                    """
                ),
                {"version_id": first.version_id},
            )
        dataset_case.mark_published(first.dataset_id, first.version_id)

        recovered = _service(engine).materialize_baseline(command)
    finally:
        engine.dispose()

    assert recovered == first
    assert first.status == "draft"
    assert first.data_revision == 0
    assert first.review_revision == 0
    assert dataset_case.rows(
        """
        SELECT status, data_revision, review_revision
        FROM dataset_versions
        WHERE id = :version_id
        """,
        {"version_id": first.version_id},
    ) == [
        {
            "status": "published",
            "data_revision": 3,
            "review_revision": 2,
        }
    ]


class _LostMaterializeAcknowledgementRepository(MySqlDatasetRepository):
    def materialize_baseline(
        self,
        command: MaterializeBaselineCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult:
        super().materialize_baseline(command, occurred_at=occurred_at)
        raise DatasetCommitOutcomeUnknown("injected response loss after commit")


def test_retry_recovers_after_materialize_commit_response_loss(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="ackloss",
    )
    command = _materialize_command(dataset_case, baseline)
    engine = dataset_case.runtime_engine()
    try:
        lost_service = DatasetService(
            repository=_LostMaterializeAcknowledgementRepository(engine),
            clock=lambda: NOW,
        )
        with pytest.raises(DatasetCommitOutcomeUnknown, match="response loss"):
            lost_service.materialize_baseline(command)
        recovered = _service(engine).materialize_baseline(command)
    finally:
        engine.dispose()

    assert recovered.operation_token == command.operation_token
    graph = dataset_case.dataset_graph((report_date,))
    assert len(graph["versions"]) == 1
    assert len(graph["drafts"]) == 1
    assert len(graph["snapshots"]) == 1


def test_two_connections_creating_the_same_empty_date_leave_one_draft(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    first_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="raceone",
    )
    second_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="racetwo",
    )
    first_engine = dataset_case.runtime_engine()
    second_engine = dataset_case.runtime_engine()
    insert_barrier = Barrier(2)
    connection_ids: dict[str, int] = {}
    callback_seen: set[str] = set()

    def pause_before_insert(
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

    first_callback = pause_before_insert("first")
    second_callback = pause_before_insert("second")
    sa.event.listen(first_engine, "before_cursor_execute", first_callback)
    sa.event.listen(second_engine, "before_cursor_execute", second_callback)

    def create(
        engine: Engine,
        baseline: SeededBaseline,
    ) -> DraftMutationResult | DatasetError:
        try:
            return _service(engine).materialize_baseline(
                _materialize_command(dataset_case, baseline)
            )
        except DatasetError as error:
            return error

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(create, first_engine, first_baseline),
                executor.submit(create, second_engine, second_baseline),
            )
            outcomes = [future.result(timeout=25) for future in futures]
    finally:
        insert_barrier.abort()
        sa.event.remove(first_engine, "before_cursor_execute", first_callback)
        sa.event.remove(second_engine, "before_cursor_execute", second_callback)
        first_engine.dispose()
        second_engine.dispose()

    created = [item for item in outcomes if isinstance(item, DraftMutationResult)]
    conflicts = [item for item in outcomes if isinstance(item, ActiveDraftConflict)]
    assert connection_ids["first"] != connection_ids["second"]
    assert len(created) == 1
    assert len(conflicts) == 1
    graph = dataset_case.dataset_graph((report_date,))
    assert len(graph["datasets"]) == 1
    assert len(graph["versions"]) == 1
    assert len(graph["snapshots"]) == 1
    assert len(graph["drafts"]) == 1
    assert len(graph["inputs"]) == 1
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_results "
            "WHERE result_dataset_id = :dataset_id",
            {"dataset_id": created[0].dataset_id},
        )
        == 1
    )


def test_two_connections_with_same_token_recover_the_same_result(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="sametoken",
    )
    command = _materialize_command(dataset_case, baseline)
    first_engine = dataset_case.runtime_engine()
    second_engine = dataset_case.runtime_engine()
    token_barrier = Barrier(2)
    connection_ids: dict[str, int] = {}
    callback_seen: set[str] = set()

    def pause_before_token(
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
            if _is_operation_token_insert(statement) and label not in callback_seen:
                callback_seen.add(label)
                connection_ids[label] = _physical_connection_id(connection)
                token_barrier.wait(timeout=10)

        return callback

    first_callback = pause_before_token("first")
    second_callback = pause_before_token("second")
    sa.event.listen(first_engine, "before_cursor_execute", first_callback)
    sa.event.listen(second_engine, "before_cursor_execute", second_callback)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(_service(first_engine).materialize_baseline, command),
                executor.submit(_service(second_engine).materialize_baseline, command),
            )
            first = futures[0].result(timeout=25)
            second = futures[1].result(timeout=25)
    finally:
        token_barrier.abort()
        sa.event.remove(first_engine, "before_cursor_execute", first_callback)
        sa.event.remove(second_engine, "before_cursor_execute", second_callback)
        first_engine.dispose()
        second_engine.dispose()

    assert connection_ids["first"] != connection_ids["second"]
    assert first == second
    graph = dataset_case.dataset_graph((report_date,))
    assert len(graph["versions"]) == 1
    assert len(graph["drafts"]) == 1
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_tokens "
            "WHERE operation_token = :token",
            {"token": command.operation_token.bytes},
        )
        == 1
    )
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_results "
            "WHERE operation_token = :token",
            {"token": command.operation_token.bytes},
        )
        == 1
    )


def test_late_successor_write_against_sealed_revision_has_no_partial_records(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    initial_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="latebase",
    )
    winning_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="latewin",
    )
    losing_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="latelose",
    )
    setup_engine = dataset_case.runtime_engine()
    try:
        initial = _service(setup_engine).materialize_baseline(
            _materialize_command(dataset_case, initial_baseline)
        )
    finally:
        setup_engine.dispose()

    expected = _expectation(initial)
    winning_command = _materialize_command(
        dataset_case,
        winning_baseline,
        strategy="merge",
        expected_active_draft=expected,
    )
    losing_command = _materialize_command(
        dataset_case,
        losing_baseline,
        strategy="merge",
        expected_active_draft=expected,
    )
    first_engine = dataset_case.runtime_engine()
    second_engine = dataset_case.runtime_engine()
    first_locked = Event()
    second_reached_lock = Event()
    allow_first_to_finish = Event()
    connection_ids: dict[str, int] = {}
    callback_seen: set[str] = set()

    def pause_first_after_lock(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_dataset_lock(statement) and "first" not in callback_seen:
            callback_seen.add("first")
            connection_ids["first"] = _physical_connection_id(connection)
            first_locked.set()
            assert allow_first_to_finish.wait(timeout=10)

    def record_second_before_lock(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_dataset_lock(statement) and "second" not in callback_seen:
            callback_seen.add("second")
            connection_ids["second"] = _physical_connection_id(connection)
            second_reached_lock.set()

    sa.event.listen(
        first_engine,
        "after_cursor_execute",
        pause_first_after_lock,
    )
    sa.event.listen(
        second_engine,
        "before_cursor_execute",
        record_second_before_lock,
    )
    first_future: Future[DraftMutationResult] | None = None
    second_future: Future[DraftMutationResult] | None = None
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                _service(first_engine).materialize_baseline,
                winning_command,
            )
            assert first_locked.wait(timeout=10)
            second_future = executor.submit(
                _service(second_engine).materialize_baseline,
                losing_command,
            )
            assert second_reached_lock.wait(timeout=10)
            allow_first_to_finish.set()
            winner = first_future.result(timeout=25)
            with pytest.raises(ActiveDraftConflict):
                second_future.result(timeout=25)
    finally:
        allow_first_to_finish.set()
        sa.event.remove(
            first_engine,
            "after_cursor_execute",
            pause_first_after_lock,
        )
        sa.event.remove(
            second_engine,
            "before_cursor_execute",
            record_second_before_lock,
        )
        first_engine.dispose()
        second_engine.dispose()

    assert first_future is not None and second_future is not None
    assert connection_ids["first"] != connection_ids["second"]
    graph = dataset_case.dataset_graph((report_date,))
    assert [(row["id"], row["status"]) for row in graph["versions"]] == [
        (initial.version_id, "discarded"),
        (winner.version_id, "draft"),
    ]
    assert [row["version_id"] for row in graph["drafts"]] == [winner.version_id]
    winning_inputs = {
        row["batch_id"]
        for row in graph["inputs"]
        if row["version_id"] == winner.version_id
    }
    assert winning_inputs == {initial_baseline.batch_id, winning_baseline.batch_id}
    assert losing_baseline.batch_id not in {row["batch_id"] for row in graph["inputs"]}
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM draft_operation_tokens "
            "WHERE operation_token = :token",
            {"token": losing_command.operation_token.bytes},
        )
        == 0
    )
