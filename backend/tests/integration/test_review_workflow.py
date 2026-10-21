from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import MaterializeBaselineCommand
from app.review.repository import MySqlReviewRepository
from app.review.service import ReviewService
from app.review.types import (
    AddRowCommand,
    ChangeRowStateCommand,
    CreateNoteCommand,
    DraftHeadExpectation,
    MarkReadyCommand,
    RestoreFieldValueCommand,
    ReturnToDraftCommand,
    ReviewMutationResult,
    SetFieldValueCommand,
    SourceFileValueSource,
    StaleValidationRun,
    VersionNoteTarget,
)
from app.validation.fields import FieldValue
from app.validation.repository import MySqlValidationRepository
from app.validation.service import ValidationService
from app.validation.types import RunValidationCommand, ValidationRunReceipt
from sqlalchemy.engine import Engine

from tests.integration.dataset_test_support import (
    NOW,
    DatasetIntegrationCase,
    SeededBaseline,
)
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers the shared fixture
)

pytestmark = pytest.mark.mysql


@dataclass(frozen=True, slots=True)
class _PersistedHead:
    head: DraftHeadExpectation
    ruleset_version: str


@dataclass(slots=True)
class _WorkflowCase:
    dataset_case: DatasetIntegrationCase
    baseline: SeededBaseline
    review_engine: Engine
    validation_engine: Engine
    head: DraftHeadExpectation
    ruleset_version: str

    @property
    def review(self) -> ReviewService:
        return ReviewService(
            repository=MySqlReviewRepository(self.review_engine),
            clock=lambda: NOW,
        )

    @property
    def validation(self) -> ValidationService:
        return ValidationService(
            repository=MySqlValidationRepository(self.validation_engine),
            clock=lambda: NOW,
        )


def _isolated_date() -> date:
    return date(2100, 1, 1) + timedelta(days=uuid4().int % 30000)


def _database_utc(value: object) -> datetime:
    assert isinstance(value, datetime)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    assert value.utcoffset() is not None
    return value.astimezone(UTC)


def _read_head(
    case: DatasetIntegrationCase,
    *,
    dataset_id: int,
    version_id: int,
) -> _PersistedHead:
    rows = case.rows(
        """
        SELECT drafts.dataset_id, drafts.version_id,
               drafts.version_status, drafts.pointed_at,
               versions.status, versions.data_revision,
               versions.review_revision, versions.ruleset_version,
               versions.sealed_at
        FROM dataset_drafts AS drafts
        INNER JOIN dataset_versions AS versions
            ON versions.dataset_id = drafts.dataset_id
           AND versions.id = drafts.version_id
           AND versions.status = drafts.version_status
        WHERE drafts.dataset_id = :dataset_id
          AND drafts.version_id = :version_id
        """,
        {"dataset_id": dataset_id, "version_id": version_id},
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] in {"draft", "ready_for_publish"}
    assert row["version_status"] == row["status"]
    assert row["sealed_at"] is None
    ruleset_version = str(row["ruleset_version"])
    return _PersistedHead(
        head=DraftHeadExpectation(
            dataset_id=int(row["dataset_id"]),
            version_id=int(row["version_id"]),
            status=cast(Any, row["status"]),
            data_revision=int(row["data_revision"]),
            review_revision=int(row["review_revision"]),
            pointed_at=_database_utc(row["pointed_at"]),
        ),
        ruleset_version=ruleset_version,
    )


def _head_after(
    prior: DraftHeadExpectation,
    result: ReviewMutationResult,
) -> DraftHeadExpectation:
    assert result.dataset_id == prior.dataset_id
    assert result.version_id == prior.version_id
    assert result.status in {"draft", "ready_for_publish"}
    assert result.data_revision is not None
    assert result.review_revision is not None
    return DraftHeadExpectation(
        dataset_id=prior.dataset_id,
        version_id=prior.version_id,
        status=result.status,
        data_revision=result.data_revision,
        review_revision=result.review_revision,
        pointed_at=prior.pointed_at,
    )


def _run_validation(
    workflow: _WorkflowCase,
    *,
    operation_token: UUID | None = None,
) -> tuple[RunValidationCommand, ValidationRunReceipt]:
    command = RunValidationCommand(
        dataset_id=workflow.head.dataset_id,
        version_id=workflow.head.version_id,
        data_revision=workflow.head.data_revision,
        ruleset_version=workflow.ruleset_version,
        actor_user_id=workflow.dataset_case.owner_user_id,
        operation_token=operation_token or uuid4(),
    )
    return command, workflow.validation.run_validation(command)


def _mark_ready_command(
    workflow: _WorkflowCase,
    receipt: ValidationRunReceipt,
    *,
    operation_token: UUID | None = None,
) -> MarkReadyCommand:
    return MarkReadyCommand(
        head=workflow.head,
        validation_run_id=receipt.validation_run_id,
        validation_data_digest=receipt.data_digest,
        ruleset_version=receipt.ruleset_version,
        confirmed_report_date=receipt.summary.report_date,
        confirmed_report_type=receipt.summary.report_type,
        confirmed_row_count=receipt.summary.row_count,
        confirmed_totals=receipt.summary.totals,
        actor_user_id=workflow.dataset_case.owner_user_id,
        operation_token=operation_token or uuid4(),
        reason="Validation and human review are complete",
    )


def _manual_business_row() -> dict[str, FieldValue]:
    return {
        "parent_asin": "B0MANUALP01",
        "child_asin": "B0MANUAL001",
        "title": "Manually reconstructed synthetic row",
        "sku": f"MANUAL-{uuid4().hex[:12]}",
        "sessions_total": 2,
        "sessions_b2b": 0,
        "conversion_rate_total": Decimal("0.500000000"),
        "session_percentage_b2b": Decimal("0.000000000"),
        "page_views_total": 2,
        "page_views_b2b": 0,
        "page_view_percentage_total": Decimal("0.500000000"),
        "page_view_percentage_b2b": Decimal("0.000000000"),
        "featured_offer_percentage": Decimal("1.000000000"),
        "featured_offer_percentage_b2b": Decimal("0.000000000"),
        "units_ordered": 1,
        "units_ordered_b2b": 0,
        "unit_session_percentage": Decimal("0.500000000"),
        "unit_session_percentage_b2b": Decimal("0.000000000"),
        "ordered_product_sales": Decimal("19.990000"),
        "ordered_product_sales_b2b": Decimal("0.000000"),
        "currency_code": "USD",
        "total_order_items": 1,
        "total_order_items_b2b": 0,
    }


def _cleanup_review_records(
    case: DatasetIntegrationCase,
    *,
    version_id: int,
) -> None:
    """Remove immutable stage-six records before the shared stage-five cleanup."""

    parameters = {
        "version_id": version_id,
        "user_ids": case.user_ids,
    }
    with case.migration_engine.begin() as connection:
        connection.execute(
            sa.text(
                "DELETE FROM review_operation_results "
                "WHERE result_version_id = :version_id "
                "OR actor_user_id IN :user_ids"
            ).bindparams(sa.bindparam("user_ids", expanding=True)),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM version_review_events WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM issue_review_events WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM validation_issues WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM validation_runs WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text(
                "DELETE FROM notes WHERE note_key IN ("
                "SELECT note_key FROM note_threads WHERE version_id = :version_id)"
            ),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM note_threads WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM field_changes WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM row_changes WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM data_change_events WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text(
                "DELETE FROM review_operation_tokens WHERE actor_user_id IN :user_ids"
            ).bindparams(sa.bindparam("user_ids", expanding=True)),
            parameters,
        )


@pytest.fixture(name="review_workflow")
def review_workflow(
    dataset_case: DatasetIntegrationCase,
) -> Iterator[_WorkflowCase]:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant=uuid4().hex[:12],
    )
    materialize_engine = dataset_case.runtime_engine()
    try:
        materialized = DatasetService(
            repository=MySqlDatasetRepository(materialize_engine),
            clock=lambda: NOW,
        ).materialize_baseline(
            MaterializeBaselineCommand(
                batch_id=baseline.batch_id,
                parse_baseline_id=baseline.parse_baseline_id,
                report_date=report_date,
                strategy="replace",
                expected_active_draft=None,
                expected_publication_version_id=None,
                merge_decisions=(),
                actor_user_id=dataset_case.owner_user_id,
                operation_token=uuid4(),
                reason="Materialize a real parsed baseline for review",
            )
        )
    finally:
        materialize_engine.dispose()

    persisted = _read_head(
        dataset_case,
        dataset_id=materialized.dataset_id,
        version_id=materialized.version_id,
    )
    assert persisted.head.status == "draft"
    assert persisted.head.data_revision == 0
    assert persisted.head.review_revision == 0

    review_engine = dataset_case.runtime_engine()
    validation_engine = dataset_case.runtime_engine()
    with (
        review_engine.connect() as review_connection,
        validation_engine.connect() as validation_connection,
    ):
        assert review_connection.scalar(sa.text("SELECT CONNECTION_ID()")) != (
            validation_connection.scalar(sa.text("SELECT CONNECTION_ID()"))
        )
    workflow = _WorkflowCase(
        dataset_case=dataset_case,
        baseline=baseline,
        review_engine=review_engine,
        validation_engine=validation_engine,
        head=persisted.head,
        ruleset_version=persisted.ruleset_version,
    )
    try:
        yield workflow
    finally:
        review_engine.dispose()
        validation_engine.dispose()
        _cleanup_review_records(
            dataset_case,
            version_id=materialized.version_id,
        )


def test_real_mysql_review_and_validation_workflow_is_auditable_and_idempotent(
    review_workflow: _WorkflowCase,
) -> None:
    workflow = review_workflow
    case = workflow.dataset_case
    initial_pointer = workflow.head.pointed_at
    initial_rows = case.rows(
        """
        SELECT version_row.id, version_row.original_parsed_source_row_id,
               version_row.row_state, typed.title
        FROM version_rows AS version_row
        INNER JOIN business_report_rows AS typed
            ON typed.version_id = version_row.version_id
           AND typed.version_row_id = version_row.id
        WHERE version_row.version_id = :version_id
        ORDER BY version_row.row_ordinal, version_row.id
        """,
        {"version_id": workflow.head.version_id},
    )
    assert len(initial_rows) == 2
    source_row = initial_rows[0]
    source_row_id = int(source_row["id"])
    parsed_source_row_id = int(source_row["original_parsed_source_row_id"])
    original_title = str(source_row["title"])

    initial_validation_command, initial_validation = _run_validation(workflow)
    assert initial_validation.status == "succeeded"
    assert initial_validation.result == "passed"
    assert initial_validation.data_revision == 0
    assert workflow.validation.run_validation(initial_validation_command) == (
        initial_validation
    )
    assert (
        case.scalar(
            "SELECT COUNT(*) FROM validation_runs WHERE version_id = :version_id",
            {"version_id": workflow.head.version_id},
        )
        == 1
    )

    set_command = SetFieldValueCommand(
        head=workflow.head,
        row_id=source_row_id,
        field_name="title",
        value="Corrected synthetic title",
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
        reason="Correct a deliberately selected field",
    )
    set_result = workflow.review.set_field_value(set_command)
    workflow.head = _head_after(workflow.head, set_result)
    assert workflow.head.data_revision == 1
    assert workflow.head.review_revision == 0
    assert workflow.review.set_field_value(set_command) == set_result

    stale_ready = _mark_ready_command(workflow, initial_validation)
    state_before_rejection = _read_head(
        case,
        dataset_id=workflow.head.dataset_id,
        version_id=workflow.head.version_id,
    ).head
    with pytest.raises(StaleValidationRun, match="validation"):
        workflow.review.mark_ready(stale_ready)
    assert (
        _read_head(
            case,
            dataset_id=workflow.head.dataset_id,
            version_id=workflow.head.version_id,
        ).head
        == state_before_rejection
    )
    assert (
        case.scalar(
            "SELECT COUNT(*) FROM review_operation_tokens "
            "WHERE operation_token = :operation_token",
            {"operation_token": stale_ready.operation_token.bytes},
        )
        == 0
    )

    restore_command = RestoreFieldValueCommand(
        head=workflow.head,
        row_id=source_row_id,
        field_name="title",
        source=SourceFileValueSource(
            source_batch_id=workflow.baseline.batch_id,
            parsed_source_row_id=parsed_source_row_id,
        ),
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
        reason="Restore the explicitly selected source-file value",
    )
    restore_result = workflow.review.restore_field_value(restore_command)
    workflow.head = _head_after(workflow.head, restore_result)
    assert workflow.head.data_revision == 2
    assert (
        case.scalar(
            "SELECT title FROM business_report_rows "
            "WHERE version_id = :version_id AND version_row_id = :row_id",
            {"version_id": workflow.head.version_id, "row_id": source_row_id},
        )
        == original_title
    )

    add_command = AddRowCommand(
        head=workflow.head,
        source_batch_id=workflow.baseline.batch_id,
        values=_manual_business_row(),
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
        reason="Add a processed-only correction row",
    )
    add_result = workflow.review.add_row(add_command)
    workflow.head = _head_after(workflow.head, add_result)
    assert add_result.affected_row_id is not None
    manual_row_id = add_result.affected_row_id

    row_commands: list[tuple[str, ChangeRowStateCommand]] = []
    for operation in ("exclude", "restore", "delete"):
        command = ChangeRowStateCommand(
            head=workflow.head,
            row_id=manual_row_id,
            operation=cast(Any, operation),
            actor_user_id=case.owner_user_id,
            operation_token=uuid4(),
            reason=f"Exercise the audited {operation} row transition",
        )
        result = workflow.review.change_row_state(command)
        workflow.head = _head_after(workflow.head, result)
        row_commands.append((operation, command))

    assert workflow.head.data_revision == 6
    assert workflow.head.review_revision == 0
    assert (
        case.scalar(
            "SELECT row_state FROM version_rows "
            "WHERE version_id = :version_id AND id = :row_id",
            {"version_id": workflow.head.version_id, "row_id": manual_row_id},
        )
        == "deleted"
    )

    fresh_validation_command, fresh_validation = _run_validation(workflow)
    assert fresh_validation.status == "succeeded"
    assert fresh_validation.result == "passed"
    assert fresh_validation.data_revision == 6
    assert fresh_validation.summary.row_count == 2
    assert fresh_validation.validation_run_id != (initial_validation.validation_run_id)

    note_command = CreateNoteCommand(
        target=VersionNoteTarget(version_id=workflow.head.version_id),
        expected_review_revision=workflow.head.review_revision,
        body="Reviewed the source restoration and all manual row transitions.",
        visibility="viewer_visible",
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
    )
    note_result = workflow.review.create_note(note_command)
    workflow.head = _head_after(workflow.head, note_result)
    assert workflow.head.data_revision == 6
    assert workflow.head.review_revision == 1
    assert note_result.note_id is not None

    mark_ready_command = _mark_ready_command(workflow, fresh_validation)
    ready_result = workflow.review.mark_ready(mark_ready_command)
    workflow.head = _head_after(workflow.head, ready_result)
    assert workflow.head.status == "ready_for_publish"
    assert workflow.head.data_revision == 6
    assert workflow.head.review_revision == 2
    persisted_ready = _read_head(
        case,
        dataset_id=workflow.head.dataset_id,
        version_id=workflow.head.version_id,
    ).head
    assert persisted_ready == workflow.head
    assert persisted_ready.pointed_at == initial_pointer

    return_command = ReturnToDraftCommand(
        head=workflow.head,
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
        reason="Return the reviewed version for one more draft pass",
    )
    returned_result = workflow.review.return_to_draft(return_command)
    workflow.head = _head_after(workflow.head, returned_result)
    assert workflow.head.status == "draft"
    assert workflow.head.data_revision == 6
    assert workflow.head.review_revision == 3
    persisted_draft = _read_head(
        case,
        dataset_id=workflow.head.dataset_id,
        version_id=workflow.head.version_id,
    ).head
    assert persisted_draft == workflow.head
    assert persisted_draft.pointed_at == initial_pointer

    # Retry after later state transitions: every repository must recover the frozen
    # first result instead of re-running against the current draft head.
    assert workflow.review.set_field_value(set_command) == set_result
    assert workflow.review.restore_field_value(restore_command) == restore_result
    assert workflow.review.add_row(add_command) == add_result
    for operation, command in row_commands:
        recovered = workflow.review.change_row_state(command)
        assert recovered.operation_kind == f"{operation}_row"
    assert workflow.validation.run_validation(fresh_validation_command) == (
        fresh_validation
    )
    assert workflow.review.create_note(note_command) == note_result
    assert workflow.review.mark_ready(mark_ready_command) == ready_result
    assert workflow.review.return_to_draft(return_command) == returned_result

    assert (
        case.scalar(
            "SELECT COUNT(*) FROM data_change_events WHERE version_id = :version_id",
            {"version_id": workflow.head.version_id},
        )
        == 6
    )
    assert case.rows(
        "SELECT operation FROM field_changes "
        "WHERE version_id = :version_id ORDER BY id",
        {"version_id": workflow.head.version_id},
    ) == [{"operation": "set"}, {"operation": "restore_source"}]
    assert case.rows(
        "SELECT operation FROM row_changes WHERE version_id = :version_id ORDER BY id",
        {"version_id": workflow.head.version_id},
    ) == [
        {"operation": "add"},
        {"operation": "exclude"},
        {"operation": "restore"},
        {"operation": "delete"},
    ]
    assert case.rows(
        "SELECT data_revision, status, result FROM validation_runs "
        "WHERE version_id = :version_id ORDER BY id",
        {"version_id": workflow.head.version_id},
    ) == [
        {"data_revision": 0, "status": "succeeded", "result": "passed"},
        {"data_revision": 6, "status": "succeeded", "result": "passed"},
    ]
    assert case.rows(
        "SELECT notes.visibility, notes.body "
        "FROM notes INNER JOIN note_threads "
        "ON note_threads.note_key = notes.note_key "
        "WHERE note_threads.version_id = :version_id",
        {"version_id": workflow.head.version_id},
    ) == [
        {
            "visibility": "viewer_visible",
            "body": ("Reviewed the source restoration and all manual row transitions."),
        }
    ]
    assert case.rows(
        "SELECT from_status, to_status, data_revision, "
        "from_review_revision, to_review_revision "
        "FROM version_review_events "
        "WHERE version_id = :version_id ORDER BY id",
        {"version_id": workflow.head.version_id},
    ) == [
        {
            "from_status": "draft",
            "to_status": "ready_for_publish",
            "data_revision": 6,
            "from_review_revision": 1,
            "to_review_revision": 2,
        },
        {
            "from_status": "ready_for_publish",
            "to_status": "draft",
            "data_revision": 6,
            "from_review_revision": 2,
            "to_review_revision": 3,
        },
    ]
    assert (
        case.scalar(
            "SELECT COUNT(*) FROM review_operation_results "
            "WHERE result_version_id = :version_id",
            {"version_id": workflow.head.version_id},
        )
        == 11
    )
    assert (
        case.scalar(
            "SELECT COUNT(*) FROM dataset_drafts WHERE dataset_id = :dataset_id",
            {"dataset_id": workflow.head.dataset_id},
        )
        == 1
    )
