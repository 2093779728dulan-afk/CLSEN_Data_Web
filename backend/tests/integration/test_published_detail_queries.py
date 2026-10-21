from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from app.auth.sessions import Principal
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import MaterializeBaselineCommand
from app.published_details.models import PublishedDetailRow
from app.published_details.scope import PublishedScopeCodec
from app.published_details.service import (
    InvalidPublishedReportDate,
    PublishedDetailQueryService,
    PublishedRowsPage,
)
from sqlalchemy.orm import Session

from tests.integration.dataset_test_support import NOW, DatasetIntegrationCase
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers shared fixture
)

pytestmark = pytest.mark.mysql


def _isolated_date() -> date:
    return date(2220, 1, 1) + timedelta(days=uuid4().int % 20000)


def _principal(case: DatasetIntegrationCase, *roles: str) -> Principal:
    return Principal(
        user_id=case.owner_user_id,
        username="published-detail-query-user",
        display_name="Published detail query user",
        roles=frozenset(roles),
        session_id=1,
        csrf_token_hash=b"published-detail-query-csrf",
    )


def _codec() -> PublishedScopeCodec:
    return PublishedScopeCodec(
        secret="published-detail-query-integration-secret",
        clock=lambda: NOW,
        ttl=timedelta(minutes=5),
    )


def _materialize(
    case: DatasetIntegrationCase,
    *,
    report_date: date,
    report_type: str,
    variant: str,
    extra_columns: tuple[tuple[str, str], ...] = (),
) -> tuple[int, int]:
    baseline = case.seed_baseline(
        report_date=report_date,
        report_type=report_type,
        variant=variant,
        extra_columns=extra_columns,
    )
    result = DatasetService(
        repository=MySqlDatasetRepository(case.migration_engine),
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
            actor_user_id=case.owner_user_id,
            operation_token=uuid4(),
            reason="Seed a published-detail query integration version",
        )
    )
    return result.dataset_id, result.version_id


def _set_extension_kind_and_values(
    case: DatasetIntegrationCase,
    *,
    version_id: int,
    source_header: str,
    value_kind: str,
    values_by_ordinal: dict[int, str],
) -> None:
    column_rows = case.rows(
        """
        SELECT column_id
        FROM version_table_columns
        WHERE version_id = :version_id AND source_header = :source_header
        """,
        {"version_id": version_id, "source_header": source_header},
    )
    assert len(column_rows) == 1
    column_id = column_rows[0]["column_id"]
    row_records = case.rows(
        """
        SELECT id, row_ordinal
        FROM version_rows
        WHERE version_id = :version_id
        ORDER BY row_ordinal
        """,
        {"version_id": version_id},
    )
    assert {int(row["row_ordinal"]) for row in row_records} == set(values_by_ordinal)
    with case.migration_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                UPDATE version_table_columns
                SET value_kind = :value_kind
                WHERE version_id = :version_id AND column_id = :column_id
                """
            ),
            {
                "version_id": version_id,
                "column_id": column_id,
                "value_kind": value_kind,
            },
        )
        for row in row_records:
            value = values_by_ordinal[int(row["row_ordinal"])]
            connection.execute(
                sa.text(
                    """
                    UPDATE version_extension_cells
                    SET base_value = :value, current_value = :value
                    WHERE version_id = :version_id
                      AND row_id = :row_id
                      AND column_id = :column_id
                    """
                ),
                {
                    "version_id": version_id,
                    "row_id": int(row["id"]),
                    "column_id": column_id,
                    "value": value,
                },
            )


def _column_id(page: PublishedRowsPage, field_name: str) -> UUID:
    return next(
        column.column_id
        for column in page.columns
        if column.standard_field_name == field_name
    )


def _cell_value(row: PublishedDetailRow, column_id: UUID) -> object:
    return next(cell.value for cell in row.cells if cell.column_id == column_id)


def test_summary_counts_search_matches_but_keeps_full_day_business_metrics(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    dataset_id, version_id = _materialize(
        dataset_case,
        report_date=report_date,
        report_type="business_report",
        variant="summary-blue",
    )
    dataset_case.mark_published(dataset_id, version_id)

    with Session(dataset_case.migration_engine) as session:
        service = PublishedDetailQueryService(session, _codec())
        scope = service.resolve_publication_scope(
            _principal(dataset_case, "viewer"),
            "business_report",
            report_date,
            report_date,
        )
        page = service.query_date_summaries(scope, "BLUE", 1, 100)

    assert page.pagination.total_items == 1
    assert len(page.summaries) == 1
    summary = page.summaries[0]
    assert summary.report_date == report_date
    assert summary.version_id == version_id
    assert summary.total_row_count == 2
    assert summary.matching_row_count == 1
    assert summary.metric_scope == "full_day"
    assert Decimal(summary.sales or "0") == Decimal("169.97")
    assert summary.units_ordered == 3
    assert summary.sessions == 15
    assert summary.return_quantity is None


def test_return_summary_uses_full_day_return_quantity_after_a_public_search(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    dataset_id, version_id = _materialize(
        dataset_case,
        report_date=report_date,
        report_type="return_report",
        variant="return-blue",
        extra_columns=(("Private extension", "VIEWER-HIDDEN-EXTENSION"),),
    )
    dataset_case.mark_published(dataset_id, version_id)

    with Session(dataset_case.migration_engine) as session:
        service = PublishedDetailQueryService(session, _codec())
        scope = service.resolve_publication_scope(
            _principal(dataset_case, "viewer"),
            "return_report",
            report_date,
            report_date,
        )
        complete_schema = service.compose_published_schema(scope)
        page = service.query_date_summaries(scope, "BLUE", 1, 100)
        viewer_rows = service.query_published_rows(
            scope,
            None,
            None,
            "asc",
            1,
            100,
        )
        private_search_results = [
            (
                service.query_date_summaries(scope, term, 1, 100),
                service.query_published_rows(
                    scope,
                    term,
                    None,
                    "asc",
                    1,
                    100,
                ),
            )
            for term in (
                "000-0000000-return-blue0",
                "LPNSYNTH001",
                "Fabric felt",
                "VIEWER-HIDDEN-EXTENSION",
            )
        ]

    assert len(page.summaries) == 1
    summary = page.summaries[0]
    assert summary.total_row_count == 2
    assert summary.matching_row_count == 1
    assert summary.metric_scope == "full_day"
    assert summary.sales is None
    assert summary.units_ordered is None
    assert summary.sessions is None
    assert summary.return_quantity == 3
    restricted_fields = {
        "order_id",
        "license_plate_number",
        "customer_comments",
    }
    hidden_ids = {
        column.column_id
        for column in complete_schema
        if column.standard_field_name in restricted_fields
        or column.standard_field_name is None
    }
    assert restricted_fields <= {
        column.standard_field_name
        for column in complete_schema
        if column.standard_field_name is not None
    }
    assert any(column.standard_field_name is None for column in complete_schema)
    assert hidden_ids.isdisjoint(column.column_id for column in viewer_rows.columns)
    assert all(
        hidden_ids.isdisjoint(cell.column_id for cell in row.cells)
        for row in viewer_rows.rows
    )
    for private_summary, private_rows in private_search_results:
        assert private_summary.summaries == []
        assert private_summary.pagination.total_items == 0
        assert private_rows.rows == []
        assert private_rows.pagination.total_items == 0


def test_rows_use_union_order_null_missing_values_and_bounded_stable_pages(
    dataset_case: DatasetIntegrationCase,
) -> None:
    day_one = _isolated_date()
    day_two = day_one + timedelta(days=1)
    dataset_one, version_one = _materialize(
        dataset_case,
        report_date=day_one,
        report_type="business_report",
        variant="union-one",
    )
    dataset_case.mark_published(dataset_one, version_one)
    dataset_two, version_two = _materialize(
        dataset_case,
        report_date=day_two,
        report_type="business_report",
        variant="union-two",
        extra_columns=(("Seller note", "Day two public extension"),),
    )
    dataset_case.mark_published(dataset_two, version_two)

    with Session(dataset_case.migration_engine) as session:
        service = PublishedDetailQueryService(session, _codec())
        scope = service.resolve_publication_scope(
            _principal(dataset_case, "data_manager"),
            "business_report",
            day_one,
            day_two,
        )
        page = service.query_published_rows(
            scope,
            None,
            None,
            "asc",
            1,
            100,
        )
        custom_id = next(
            column.column_id
            for column in page.columns
            if column.source_header == "Seller note"
        )
        filtered = service.query_published_rows(
            scope,
            "Day two public extension",
            None,
            "asc",
            1,
            100,
            report_date=day_two,
        )
        day_one_only = service.query_published_rows(
            scope,
            None,
            None,
            "asc",
            1,
            100,
            report_date=day_one,
        )
        with pytest.raises(ValueError, match="page_size"):
            service.query_published_rows(scope, None, None, "asc", 1, 101)
        with pytest.raises(InvalidPublishedReportDate):
            service.query_published_rows(
                scope,
                None,
                None,
                "asc",
                1,
                100,
                report_date=day_one - timedelta(days=1),
            )

    assert [(row.report_date, row.row_ordinal) for row in page.rows] == [
        (day_two, 1),
        (day_two, 2),
        (day_one, 1),
        (day_one, 2),
    ]
    assert page.pagination.total_items == 4
    assert page.pagination.total_pages == 1
    assert all(_cell_value(row, custom_id) is None for row in day_one_only.rows)
    assert {_cell_value(row, custom_id) for row in filtered.rows} == {
        "Day two public extension"
    }


def test_sort_uses_report_date_and_row_ordinal_as_tiebreakers(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    dataset_id, version_id = _materialize(
        dataset_case,
        report_date=report_date,
        report_type="return_report",
        variant="sort-status",
    )
    dataset_case.mark_published(dataset_id, version_id)

    with Session(dataset_case.migration_engine) as session:
        service = PublishedDetailQueryService(session, _codec())
        scope = service.resolve_publication_scope(
            _principal(dataset_case, "data_manager"),
            "return_report",
            report_date,
            report_date,
        )
        unsorted_page = service.query_published_rows(
            scope,
            None,
            None,
            "asc",
            1,
            100,
        )
        status_column_id = _column_id(unsorted_page, "status")
        sorted_page = service.query_published_rows(
            scope,
            None,
            status_column_id,
            "asc",
            1,
            100,
        )

    assert [_cell_value(row, status_column_id) for row in sorted_page.rows] == [
        "Unit returned to inventory",
        "Unit returned to inventory",
    ]
    assert [(row.report_date, row.row_ordinal) for row in sorted_page.rows] == [
        (report_date, 1),
        (report_date, 2),
    ]


def test_integer_extension_sort_uses_numeric_order_instead_of_longtext_order(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    dataset_id, version_id = _materialize(
        dataset_case,
        report_date=report_date,
        report_type="business_report",
        variant="sort-numeric-extension",
        extra_columns=(("Numeric extension", "0"),),
    )
    _set_extension_kind_and_values(
        dataset_case,
        version_id=version_id,
        source_header="Numeric extension",
        value_kind="integer",
        values_by_ordinal={1: "10", 2: "2"},
    )
    dataset_case.mark_published(dataset_id, version_id)

    with Session(dataset_case.migration_engine) as session:
        service = PublishedDetailQueryService(session, _codec())
        scope = service.resolve_publication_scope(
            _principal(dataset_case, "data_manager"),
            "business_report",
            report_date,
            report_date,
        )
        page = service.query_published_rows(
            scope,
            None,
            None,
            "asc",
            1,
            100,
        )
        numeric_column_id = next(
            column.column_id
            for column in page.columns
            if column.source_header == "Numeric extension"
        )
        sorted_page = service.query_published_rows(
            scope,
            None,
            numeric_column_id,
            "asc",
            1,
            100,
        )

    assert [row.row_ordinal for row in sorted_page.rows] == [2, 1]
    assert [_cell_value(row, numeric_column_id) for row in sorted_page.rows] == [2, 10]
