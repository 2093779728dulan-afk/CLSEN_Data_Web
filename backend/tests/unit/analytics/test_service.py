from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from app.analytics.errors import AnalyticsDateRangeTooLarge
from app.analytics.service import (
    MAX_ANALYTICS_DATE_RANGE_DAYS,
    PublishedAnalyticsQueryService,
    _date_range,
    _event_date_utc_bounds,
)
from sqlalchemy.orm import Session


@pytest.mark.parametrize("query_name", ["summary", "products", "returns"])
def test_queries_reject_more_than_366_calendar_days_before_database_access(
    query_name: str,
) -> None:
    database_session = MagicMock(spec=Session)
    service = PublishedAnalyticsQueryService(database_session)

    with pytest.raises(AnalyticsDateRangeTooLarge):
        if query_name == "summary":
            service.summary(date(2024, 1, 1), date(2025, 1, 1))
        elif query_name == "products":
            service.products(
                date(2024, 1, 1),
                date(2025, 1, 1),
                limit=25,
            )
        else:
            service.returns(
                date(2024, 1, 1),
                date(2025, 1, 1),
                basis="event_date",
            )

    database_session.execute.assert_not_called()


def test_exactly_366_calendar_days_are_accepted() -> None:
    requested_range = _date_range(date(2024, 1, 1), date(2024, 12, 31))

    assert MAX_ANALYTICS_DATE_RANGE_DAYS == 366
    assert requested_range.from_date == date(2024, 1, 1)
    assert requested_range.to_date == date(2024, 12, 31)


@pytest.mark.parametrize(
    ("local_date", "expected_from", "expected_to"),
    [
        (
            date(2026, 3, 8),
            datetime(2026, 3, 8, 8, 0),
            datetime(2026, 3, 9, 7, 0),
        ),
        (
            date(2026, 11, 1),
            datetime(2026, 11, 1, 7, 0),
            datetime(2026, 11, 2, 8, 0),
        ),
    ],
)
def test_event_date_utc_bounds_follow_spring_and_fall_dst(
    local_date: date,
    expected_from: datetime,
    expected_to: datetime,
) -> None:
    assert _event_date_utc_bounds(
        local_date,
        local_date,
        ZoneInfo("America/Los_Angeles"),
    ) == (expected_from, expected_to)
