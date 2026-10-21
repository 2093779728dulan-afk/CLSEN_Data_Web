from __future__ import annotations

from datetime import date
from typing import Literal

import pytest
from app.agent_tools.service import PublishedDateRange, ReadOnlyAgentTools
from app.analytics.models import (
    DashboardSummary,
    DateRange,
    ProductDashboard,
    ProductMetric,
    ReturnDashboard,
)


class _Reader:
    def summary(self, from_date: date, to_date: date) -> DashboardSummary:
        return DashboardSummary(
            range=DateRange(from_date=from_date, to_date=to_date),
            metrics=[],
            publications=[],
            site_config_versions=[],
        )

    def products(
        self,
        from_date: date,
        to_date: date,
        *,
        limit: int,
    ) -> ProductDashboard:
        return ProductDashboard(
            range=DateRange(from_date=from_date, to_date=to_date),
            rows=[
                ProductMetric(
                    sku=f"limit-{limit}",
                    asin=None,
                    sales="0",
                    units_ordered=0,
                    sessions=0,
                    conversion_rate=None,
                )
            ],
            publications=[],
            site_config_versions=[],
        )

    def returns(
        self,
        from_date: date,
        to_date: date,
        *,
        basis: Literal["report_date", "event_date"],
    ) -> ReturnDashboard:
        return ReturnDashboard(
            basis=basis,
            range=DateRange(from_date=from_date, to_date=to_date),
            rows=[],
            publications=[],
            site_config_versions=[],
        )


def test_read_only_tools_delegate_only_whitelisted_published_queries() -> None:
    tools = ReadOnlyAgentTools(_Reader())
    requested_range = PublishedDateRange(date(2026, 8, 1), date(2026, 8, 2))

    assert tools.published_summary(requested_range)["range"] == {
        "from_date": "2026-08-01",
        "to_date": "2026-08-02",
    }
    assert tools.product_performance(requested_range, limit=12)["rows"] == [
        {
            "asin": None,
            "conversion_rate": None,
            "sales": "0",
            "sessions": 0,
            "sku": "limit-12",
            "units_ordered": 0,
        }
    ]
    assert tools.return_breakdown(requested_range, basis="event_date")["basis"] == (
        "event_date"
    )


def test_agent_boundary_exposes_no_sql_or_mutation_method() -> None:
    public_methods = {
        name for name in dir(ReadOnlyAgentTools) if not name.startswith("_")
    }

    assert public_methods == {
        "product_performance",
        "published_summary",
        "return_breakdown",
    }


@pytest.mark.parametrize("basis", ["raw_sql", "draft"])
def test_read_only_tools_reject_unapproved_query_shapes(basis: str) -> None:
    tools = ReadOnlyAgentTools(_Reader())
    requested_range = PublishedDateRange(date(2026, 8, 1), date(2026, 8, 2))

    with pytest.raises(ValueError, match="basis"):
        # Deliberately cross the static Literal boundary to verify runtime defense.
        tools.return_breakdown(requested_range, basis=basis)  # type: ignore[arg-type]
