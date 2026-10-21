from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Literal, cast
from uuid import uuid4

import pytest
from app.api.workbench import (
    CreateWorkbenchRevisionRequest,
    create_workbench_revision,
)
from app.auth.sessions import Principal
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import MaterializeBaselineCommand
from app.review.types import DraftHeadExpectation
from app.workbench.commands import SetWorkbenchCellCommand, UndoWorkbenchCellCommand
from app.workbench.queries import DateWorkbenchQueryService
from app.workbench.repository import (
    MySqlWorkbenchMutationRepository,
    WorkbenchMutationHead,
)
from app.workbench.service import WorkbenchCellMutationService
from sqlalchemy.orm import Session

from tests.integration.dataset_test_support import NOW, DatasetIntegrationCase
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers the shared fixture
)

pytestmark = pytest.mark.mysql


def _isolated_date() -> date:
    return date(2180, 1, 1) + timedelta(days=uuid4().int % 20000)


def test_materialization_versions_extra_original_columns_and_values(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="extra-columns",
        extra_columns=(("Operator note", "keep me"), ("Custom flag", "Y")),
    )
    result = DatasetService(
        repository=MySqlDatasetRepository(dataset_case.migration_engine),
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
            reason="Open the original columns in the editable workbench",
        )
    )

    columns = dataset_case.rows(
        """
        SELECT source_header, display_order, standard_field_name
        FROM version_table_columns
        WHERE version_id = :version_id
        ORDER BY display_order
        """,
        {"version_id": result.version_id},
    )
    assert columns[-2:] == [
        {
            "source_header": "Operator note",
            "display_order": 23,
            "standard_field_name": None,
        },
        {
            "source_header": "Custom flag",
            "display_order": 24,
            "standard_field_name": None,
        },
    ]
    cells = dataset_case.rows(
        """
        SELECT columns.source_header, cells.base_value, cells.current_value,
               cells.cell_revision
        FROM version_extension_cells AS cells
        INNER JOIN version_table_columns AS columns
            ON columns.version_id = cells.version_id
           AND columns.column_id = cells.column_id
        WHERE cells.version_id = :version_id
        ORDER BY cells.row_id, columns.display_order
        """,
        {"version_id": result.version_id},
    )
    assert cells
    assert {item["source_header"] for item in cells} == {
        "Operator note",
        "Custom flag",
    }
    assert all(item["cell_revision"] == 0 for item in cells)
    assert {item["current_value"] for item in cells} == {"keep me", "Y"}


def test_date_workbench_combines_standard_and_extension_cells_with_bounded_pages(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="extra-columns",
        extra_columns=(("Operator note", "find this"), ("Custom flag", "Y")),
    )
    materialized = DatasetService(
        repository=MySqlDatasetRepository(dataset_case.migration_engine),
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
            reason="Open a bounded aggregate workbench page",
        )
    )
    principal = Principal(
        user_id=dataset_case.owner_user_id,
        username="workbench-owner",
        display_name="Workbench owner",
        roles=frozenset({"data_manager"}),
        session_id=1,
        csrf_token_hash=b"workbench-csrf",
    )

    with Session(dataset_case.migration_engine) as session:
        response = DateWorkbenchQueryService(session).get(
            principal=principal,
            report_date=report_date,
            report_type="business_report",
            page=1,
            page_size=1,
            search="find this",
            sort_column_id=None,
            direction="asc",
            changed_only=False,
        )

    assert response.source == "draft"
    assert response.head is not None
    assert response.head.version_id == materialized.version_id
    assert response.permissions.can_edit is True
    assert response.permissions.can_undo is False

    def can_undo_for(actor_user_id: int) -> bool:
        with Session(dataset_case.migration_engine) as session:
            return (
                DateWorkbenchQueryService(session)
                .get(
                    principal=replace(principal, user_id=actor_user_id),
                    report_date=report_date,
                    report_type="business_report",
                    page=1,
                    page_size=1,
                    search=None,
                    sort_column_id=None,
                    direction="asc",
                    changed_only=False,
                )
                .permissions.can_undo
            )

    assert response.pagination.page_size == 1
    assert response.pagination.total_rows >= 1
    assert len(response.rows) == 1
    assert [column.source_header for column in response.columns][-2:] == [
        "Operator note",
        "Custom flag",
    ]
    operator_column = next(
        column for column in response.columns if column.source_header == "Operator note"
    )
    operator_cell = next(
        cell
        for cell in response.rows[0].cells
        if cell.column_id == operator_column.column_id
    )
    assert operator_cell.current == "find this"
    assert operator_cell.base == "find this"
    assert operator_cell.cell_revision == 0
    assert response.head.status in {"draft", "ready_for_publish"}
    head_status = cast(
        Literal["draft", "ready_for_publish"],
        response.head.status,
    )

    operation_token = uuid4()
    mutation_command = SetWorkbenchCellCommand(
        head=DraftHeadExpectation(
            dataset_id=response.head.dataset_id,
            version_id=response.head.version_id,
            status=head_status,
            data_revision=response.head.data_revision,
            review_revision=response.head.review_revision,
            pointed_at=response.head.pointed_at,
        ),
        row_id=response.rows[0].row_id,
        column_id=operator_column.column_id,
        value="updated note",
        expected_cell_revision=0,
        actor_user_id=dataset_case.owner_user_id,
        operation_token=operation_token,
        reason="Verify optimistic extension autosave",
    )
    mutations = MySqlWorkbenchMutationRepository(dataset_case.migration_engine)
    first_result = mutations.set_extension_cell(
        mutation_command,
        occurred_at=NOW,
    )
    recovered_result = mutations.set_extension_cell(
        mutation_command,
        occurred_at=NOW,
    )

    assert recovered_result == first_result
    assert first_result.cell.current == "updated note"
    assert first_result.cell.base == "find this"
    assert first_result.cell.cell_revision == 1
    assert first_result.head.data_revision == response.head.data_revision + 1
    assert can_undo_for(dataset_case.owner_user_id) is True
    assert can_undo_for(dataset_case.other_manager_user_id) is False
    ledger = dataset_case.rows(
        """
        SELECT data_revision, cell_revision, operation, before_value,
               after_value, actor_user_id
        FROM extension_cell_changes
        WHERE operation_token = :operation_token
        """,
        {"operation_token": operation_token.bytes},
    )
    assert ledger == [
        {
            "data_revision": first_result.head.data_revision,
            "cell_revision": 1,
            "operation": "set",
            "before_value": "find this",
            "after_value": "updated note",
            "actor_user_id": dataset_case.owner_user_id,
        }
    ]

    title_column = next(
        column for column in response.columns if column.standard_field_name == "title"
    )
    title_cell = next(
        cell
        for cell in response.rows[0].cells
        if cell.column_id == title_column.column_id
    )
    standard_token = uuid4()
    standard_command = SetWorkbenchCellCommand(
        head=DraftHeadExpectation(
            dataset_id=first_result.head.dataset_id,
            version_id=first_result.head.version_id,
            status=first_result.head.status,
            data_revision=first_result.head.data_revision,
            review_revision=first_result.head.review_revision,
            pointed_at=first_result.head.pointed_at,
        ),
        row_id=response.rows[0].row_id,
        column_id=title_column.column_id,
        value="Updated workbench title",
        expected_cell_revision=title_cell.cell_revision,
        actor_user_id=dataset_case.owner_user_id,
        operation_token=standard_token,
        reason="Verify standard cell delegation",
    )
    standard_mutations = WorkbenchCellMutationService(
        dataset_case.migration_engine,
        clock=lambda: NOW,
    )
    standard_result = standard_mutations.set_cell(standard_command)
    recovered_standard = standard_mutations.set_cell(standard_command)

    assert recovered_standard == standard_result
    assert standard_result.cell.current == "Updated workbench title"
    assert standard_result.cell.cell_revision == standard_result.head.data_revision
    assert standard_result.head.data_revision == first_result.head.data_revision + 1

    undo_standard = UndoWorkbenchCellCommand(
        head=DraftHeadExpectation(
            dataset_id=standard_result.head.dataset_id,
            version_id=standard_result.head.version_id,
            status=standard_result.head.status,
            data_revision=standard_result.head.data_revision,
            review_revision=standard_result.head.review_revision,
            pointed_at=standard_result.head.pointed_at,
        ),
        actor_user_id=dataset_case.owner_user_id,
        operation_token=uuid4(),
        reason="Undo the latest standard cell edit",
    )
    standard_undo_result = standard_mutations.undo_latest_cell(undo_standard)
    assert standard_undo_result.cell.column_id == title_column.column_id
    assert standard_undo_result.cell.current == title_cell.current
    assert can_undo_for(dataset_case.owner_user_id) is True

    undo_extension = UndoWorkbenchCellCommand(
        head=DraftHeadExpectation(
            dataset_id=standard_undo_result.head.dataset_id,
            version_id=standard_undo_result.head.version_id,
            status=standard_undo_result.head.status,
            data_revision=standard_undo_result.head.data_revision,
            review_revision=standard_undo_result.head.review_revision,
            pointed_at=standard_undo_result.head.pointed_at,
        ),
        actor_user_id=dataset_case.owner_user_id,
        operation_token=uuid4(),
        reason="Undo the latest extension cell edit",
    )
    extension_undo_result = standard_mutations.undo_latest_cell(undo_extension)
    assert extension_undo_result.cell.column_id == operator_column.column_id
    assert extension_undo_result.cell.current == "find this"
    assert extension_undo_result.cell.cell_revision == 2
    assert can_undo_for(dataset_case.owner_user_id) is False

    def expectation(head: WorkbenchMutationHead) -> DraftHeadExpectation:
        return DraftHeadExpectation(
            dataset_id=head.dataset_id,
            version_id=head.version_id,
            status=head.status,
            data_revision=head.data_revision,
            review_revision=head.review_revision,
            pointed_at=head.pointed_at,
        )

    owner_set = standard_mutations.set_cell(
        replace(
            standard_command,
            head=expectation(extension_undo_result.head),
            expected_cell_revision=standard_undo_result.cell.cell_revision,
            operation_token=uuid4(),
            value="Owner current title",
        )
    )
    other_set = standard_mutations.set_cell(
        replace(
            standard_command,
            head=expectation(owner_set.head),
            expected_cell_revision=owner_set.cell.cell_revision,
            operation_token=uuid4(),
            actor_user_id=dataset_case.other_manager_user_id,
            value="Other current title",
        )
    )
    assert can_undo_for(dataset_case.owner_user_id) is False
    assert can_undo_for(dataset_case.other_manager_user_id) is True
    reverted = standard_mutations.undo_latest_cell(
        replace(
            undo_standard,
            head=expectation(other_set.head),
            actor_user_id=dataset_case.other_manager_user_id,
            operation_token=uuid4(),
        )
    )
    assert reverted.cell.current == "Owner current title"
    assert can_undo_for(dataset_case.owner_user_id) is False
    assert can_undo_for(dataset_case.other_manager_user_id) is False


def test_first_edit_revision_is_idempotent_and_copies_extension_snapshot(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="revision-extra-columns",
        extra_columns=(("Operator note", "preserve across revision"),),
    )
    published = DatasetService(
        repository=MySqlDatasetRepository(dataset_case.migration_engine),
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
            reason="Create the version that will be published",
        )
    )
    dataset_case.mark_published(published.dataset_id, published.version_id)
    principal = Principal(
        user_id=dataset_case.owner_user_id,
        username="workbench-owner",
        display_name="Workbench owner",
        roles=frozenset({"data_manager"}),
        session_id=1,
        csrf_token_hash=b"workbench-csrf",
    )
    payload = CreateWorkbenchRevisionRequest(
        published_version_id=published.version_id,
        reason="Edit the published table from the date workbench",
    )
    operation_token = uuid4()

    first = create_workbench_revision(
        report_date,
        "business_report",
        payload,
        principal,
        dataset_case.migration_engine,
        operation_token,
    )
    recovered = create_workbench_revision(
        report_date,
        "business_report",
        payload,
        principal,
        dataset_case.migration_engine,
        operation_token,
    )

    assert first.result_kind == "revision_created"
    assert recovered.result_kind == "existing_revision"
    assert recovered.version_id == first.version_id
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM dataset_versions WHERE dataset_id = :dataset_id",
            {"dataset_id": published.dataset_id},
        )
        == 2
    )
    copied = dataset_case.rows(
        """
        SELECT columns.source_header, cells.base_value, cells.current_value
        FROM version_extension_cells AS cells
        INNER JOIN version_table_columns AS columns
            ON columns.version_id = cells.version_id
           AND columns.column_id = cells.column_id
        WHERE cells.version_id = :version_id
        """,
        {"version_id": first.version_id},
    )
    assert copied
    assert all(
        item
        == {
            "source_header": "Operator note",
            "base_value": "preserve across revision",
            "current_value": "preserve across revision",
        }
        for item in copied
    )
