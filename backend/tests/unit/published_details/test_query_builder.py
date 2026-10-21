from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Literal
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from app.analytics.models import PublicationReference
from app.published_details.models import PublishedDetailColumn, PublishedDetailScope
from app.published_details.query_builder import (
    InvalidPublishedSortColumn,
    VisibleColumnResolver,
)
from app.published_details.scope import PublishedScopeCodec
from app.published_details.service import PublishedDetailQueryService
from sqlalchemy.orm import Session

_SKU = UUID("10000000-0000-0000-0000-000000000001")
_CUSTOM = UUID("10000000-0000-0000-0000-000000000002")
_ORDER_ID = UUID("10000000-0000-0000-0000-000000000003")
_LICENSE_PLATE = UUID("10000000-0000-0000-0000-000000000004")
_COMMENTS = UUID("10000000-0000-0000-0000-000000000005")


@pytest.fixture()
def builder() -> VisibleColumnResolver:
    return VisibleColumnResolver(
        "business_report",
        [
            PublishedDetailColumn(
                column_id=_SKU,
                source_header="SKU",
                display_order=1,
                value_kind="text",
                standard_field_name="sku",
                is_key=True,
                participates_in_statistics=True,
            ),
            PublishedDetailColumn(
                column_id=_CUSTOM,
                source_header="Seller note",
                display_order=2,
                value_kind="text",
                standard_field_name=None,
                is_key=False,
                participates_in_statistics=False,
            ),
        ],
        ("admin",),
    )


def test_unknown_sort_column_is_rejected(builder: VisibleColumnResolver) -> None:
    with pytest.raises(InvalidPublishedSortColumn):
        builder.order_by(UUID("00000000-0000-0000-0000-000000000001"), "asc")


def test_search_value_is_never_interpolated(builder: VisibleColumnResolver) -> None:
    sql, params = builder.search("%' OR 1=1 --")

    assert "OR 1=1" not in sql
    assert params["search"] == "%\\%' OR 1=1 --%"


def test_standard_sort_uses_the_frozen_typed_field(
    builder: VisibleColumnResolver,
) -> None:
    order = builder.order_by(_SKU, "desc")

    assert "typed.`sku`" in order.expression_sql
    assert order.expression_sql.endswith(" DESC")
    assert order.parameters == {"sort_column_id": _SKU.bytes}


def test_viewer_cannot_resolve_extension_sort_columns() -> None:
    builder = VisibleColumnResolver(
        "business_report",
        [
            PublishedDetailColumn(
                column_id=_CUSTOM,
                source_header="Seller note",
                display_order=1,
                value_kind="text",
                standard_field_name=None,
                is_key=False,
                participates_in_statistics=False,
            )
        ],
        ("viewer",),
    )

    assert builder.visible_columns == ()
    with pytest.raises(InvalidPublishedSortColumn):
        builder.order_by(_CUSTOM, "asc")


def test_viewer_search_and_sort_exclude_restricted_return_fields() -> None:
    fields = (
        (_SKU, "SKU", "sku"),
        (_ORDER_ID, "Order ID", "order_id"),
        (_LICENSE_PLATE, "License plate", "license_plate_number"),
        (_COMMENTS, "Customer comments", "customer_comments"),
        (_CUSTOM, "Private extension", None),
    )
    builder = VisibleColumnResolver(
        "return_report",
        [
            PublishedDetailColumn(
                column_id=column_id,
                source_header=header,
                display_order=index,
                value_kind="text",
                standard_field_name=field_name,
                is_key=False,
                participates_in_statistics=False,
            )
            for index, (column_id, header, field_name) in enumerate(fields, start=1)
        ],
        ("viewer",),
    )

    sql, parameters = builder.search("restricted-only-value")

    assert [column.column_id for column in builder.visible_columns] == [_SKU]
    assert "order_id" not in sql
    assert "license_plate_number" not in sql
    assert "customer_comments" not in sql
    assert "search_extension_column_ids" not in parameters
    for hidden_id in (_ORDER_ID, _LICENSE_PLATE, _COMMENTS, _CUSTOM):
        with pytest.raises(InvalidPublishedSortColumn):
            builder.order_by(hidden_id, "asc")


@pytest.mark.parametrize(
    ("value_kind", "expected_expression"),
    [
        ("text", "sort_extension_cells.current_value ASC"),
        (
            "integer",
            "CAST(sort_extension_cells.current_value AS SIGNED) ASC",
        ),
        (
            "decimal",
            "CAST(sort_extension_cells.current_value AS DECIMAL(65, 30)) ASC",
        ),
        (
            "utc_datetime",
            "CAST(sort_extension_cells.current_value AS DATETIME(6)) ASC",
        ),
    ],
)
def test_extension_sort_uses_fixed_expression_for_frozen_value_kind(
    value_kind: Literal["text", "integer", "decimal", "utc_datetime"],
    expected_expression: str,
) -> None:
    builder = VisibleColumnResolver(
        "business_report",
        [
            PublishedDetailColumn(
                column_id=_CUSTOM,
                source_header="Typed extension",
                display_order=1,
                value_kind=value_kind,
                standard_field_name=None,
                is_key=False,
                participates_in_statistics=False,
            )
        ],
        ("admin",),
    )

    order = builder.order_by(_CUSTOM, "asc")

    assert order.expression_sql == expected_expression
    assert order.parameters == {"sort_column_id": _CUSTOM.bytes}


def _result(rows: list[dict[str, object]]) -> MagicMock:
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


def test_summary_page_beyond_last_page_keeps_true_total_items() -> None:
    published_at = datetime(2026, 8, 17, 12, tzinfo=UTC)
    publications = tuple(
        PublicationReference(
            dataset_id=10 + report_date.day,
            site_id=3,
            report_date=report_date,
            report_type="business_report",
            version_id=100 + report_date.day,
            published_at=published_at,
        )
        for report_date in (date(2026, 8, 1), date(2026, 8, 2))
    )
    scope = PublishedDetailScope(
        user_id=7,
        roles=("viewer",),
        site_id=3,
        report_type="business_report",
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 2),
        issued_at=published_at,
        expires_at=published_at + timedelta(minutes=5),
        publications=publications,
    )
    pointer_rows: list[dict[str, object]] = [
        {
            "dataset_id": publication.dataset_id,
            "site_id": publication.site_id,
            "report_date": publication.report_date,
            "report_type": publication.report_type,
            "version_id": publication.version_id,
            "published_at": publication.published_at.replace(tzinfo=None),
        }
        for publication in publications
    ]
    schema_rows: list[dict[str, object]] = [
        {
            **pointer_row,
            "column_id": _SKU.bytes,
            "source_header": "SKU",
            "display_order": 1,
            "value_kind": "text",
            "standard_field_name": "sku",
            "is_key": True,
            "participates_in_statistics": True,
        }
        for pointer_row in pointer_rows
    ]
    session = MagicMock(spec=Session)
    session.execute.side_effect = [
        _result([{"site_id": 3, "current_config_version_id": 31, "config_id": 31}]),
        _result(pointer_rows),
        _result(schema_rows),
        _result([]),
    ]
    session.scalar.return_value = 2
    service = PublishedDetailQueryService(
        session,
        PublishedScopeCodec(
            secret="summary-page-unit-secret",
            clock=lambda: published_at,
            ttl=timedelta(minutes=5),
        ),
    )

    page = service.query_date_summaries(scope, None, page=3, page_size=1)

    assert page.summaries == []
    assert page.pagination.page == 3
    assert page.pagination.total_items == 2
    assert page.pagination.total_pages == 2
    assert "SELECT COUNT(*) FROM matching_day" in str(session.scalar.call_args.args[0])
