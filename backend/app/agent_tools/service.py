"""A narrow, database-free boundary for future read-only agents.

The agent process is intentionally given a query service, never a SQL connection or
any domain mutation service.  Human review remains the only path to a correction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol, cast

from app.analytics.models import DashboardSummary, ProductDashboard, ReturnDashboard


@dataclass(frozen=True, slots=True)
class PublishedDateRange:
    from_date: date
    to_date: date

    def __post_init__(self) -> None:
        if self.from_date > self.to_date:
            raise ValueError("from_date must not be after to_date")


class PublishedAnalyticsReader(Protocol):
    """Queries that are already filtered to current published versions."""

    def summary(self, from_date: date, to_date: date) -> DashboardSummary: ...

    def products(
        self,
        from_date: date,
        to_date: date,
        *,
        limit: int,
    ) -> ProductDashboard: ...

    def returns(
        self,
        from_date: date,
        to_date: date,
        *,
        basis: Literal["report_date", "event_date"],
    ) -> ReturnDashboard: ...


class ReadOnlyAgentTools:
    """Whitelisted data lookups safe to expose to a future agent runtime."""

    def __init__(self, reader: PublishedAnalyticsReader) -> None:
        self._reader = reader

    def published_summary(
        self,
        requested_range: PublishedDateRange,
    ) -> dict[str, object]:
        result = self._reader.summary(
            requested_range.from_date,
            requested_range.to_date,
        )
        return cast(dict[str, object], result.model_dump(mode="json"))

    def product_performance(
        self,
        requested_range: PublishedDateRange,
        *,
        limit: int = 25,
    ) -> dict[str, object]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        result = self._reader.products(
            requested_range.from_date,
            requested_range.to_date,
            limit=limit,
        )
        return cast(dict[str, object], result.model_dump(mode="json"))

    def return_breakdown(
        self,
        requested_range: PublishedDateRange,
        *,
        basis: Literal["report_date", "event_date"] = "report_date",
    ) -> dict[str, object]:
        if basis not in {"report_date", "event_date"}:
            raise ValueError("basis must be report_date or event_date")
        result = self._reader.returns(
            requested_range.from_date,
            requested_range.to_date,
            basis=basis,
        )
        return cast(dict[str, object], result.model_dump(mode="json"))
