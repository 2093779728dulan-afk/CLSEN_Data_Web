from __future__ import annotations

from datetime import date, datetime
from typing import cast
from unittest.mock import MagicMock

from app.analytics.product_ledger import ProductLedgerQueryService
from sqlalchemy.orm import Session


def _service() -> ProductLedgerQueryService:
    database_session = MagicMock(spec=Session)
    business_result = MagicMock()
    business_result.mappings.return_value = [
        {
            "report_date": date(2026, 8, 10),
            "published_at": datetime(2026, 8, 10, 9, 0),
            "sku": "2301-White-S",
            "asin": "B0STYLE001",
            "product_name": "棉质上衣",
            "sales": "10.00",
            "units_ordered": 1,
            "sessions": 10,
        },
        {
            "report_date": date(2026, 8, 11),
            "published_at": datetime(2026, 8, 11, 9, 0),
            "sku": "2301-White-M",
            "asin": "B0STYLE002",
            "product_name": "棉质上衣",
            "sales": "20.00",
            "units_ordered": 2,
            "sessions": 20,
        },
        {
            "report_date": date(2026, 8, 11),
            "published_at": datetime(2026, 8, 11, 9, 0),
            "sku": "BROKEN",
            "asin": "B0BROKEN01",
            "product_name": "异常行",
            "sales": "5.00",
            "units_ordered": 1,
            "sessions": 2,
        },
    ]
    return_result = MagicMock()
    return_result.mappings.return_value = [
        {
            "report_date": date(2026, 8, 11),
            "published_at": datetime(2026, 8, 11, 10, 0),
            "sku": "2301-White-S",
            "asin": "B0STYLE001",
            "fnsku": "X0STYLE001",
            "product_name": "棉质上衣",
            "quantity": 1,
        }
    ]
    database_session.execute.side_effect = [business_result, return_result]
    service = ProductLedgerQueryService(cast(Session, database_session))
    service._references = lambda _from, _to: ([], [])  # type: ignore[assignment]
    return service


def test_product_ledger_groups_variants_by_style_and_keeps_bad_sku_separate() -> None:
    result = _service().ledger(
        date(2026, 8, 1),
        date(2026, 8, 31),
        search=None,
        sort="sales",
        direction="desc",
        page=1,
        page_size=25,
    )

    product, unclassified = result.rows
    assert product.style_code == "2301"
    assert product.variant_count == 2
    assert product.color_count == 1
    assert product.size_count == 2
    assert product.sales == "30.00"
    assert product.return_quantity == 1
    assert product.published_days == 2
    assert unclassified.row_kind == "unclassified"
    assert unclassified.style_code is None
    assert unclassified.unclassified_sku == "BROKEN"


def test_product_ledger_searches_external_variant_identifiers() -> None:
    result = _service().ledger(
        date(2026, 8, 1),
        date(2026, 8, 31),
        search="x0style001",
        sort="style_code",
        direction="asc",
        page=1,
        page_size=25,
    )

    assert [row.style_code for row in result.rows] == ["2301"]


def test_product_card_returns_all_variants_and_daily_trend() -> None:
    result = _service().product_card(
        "2301",
        date(2026, 8, 10),
        date(2026, 8, 11),
    )

    assert result is not None
    assert result.name_status == "available"
    assert result.product_name == "棉质上衣"
    assert result.summary.sales == "30.00"
    assert len(result.variants) == 2
    assert result.variants[0].asins
    assert {item.report_date for item in result.trend} == {
        date(2026, 8, 10),
        date(2026, 8, 11),
    }
