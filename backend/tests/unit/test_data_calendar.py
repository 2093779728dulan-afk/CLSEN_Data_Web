from datetime import date
from typing import cast

import pytest
from app.api.data_calendar import (
    _calendar_day_status,
    _can_review_calendar,
    _empty_calendar_day,
    get_site_context,
    list_calendar_days,
    list_calendar_entries,
)
from app.api.errors import ApiError
from app.auth.sessions import Principal
from sqlalchemy.orm import Session


def _principal(*roles: str) -> Principal:
    return Principal(
        user_id=1,
        username="calendar-user",
        display_name="Calendar user",
        roles=frozenset(roles),
        session_id=1,
        csrf_token_hash=b"calendar-csrf",
    )


def test_calendar_access_fails_closed_for_accounts_without_a_write_role() -> None:
    assert _can_review_calendar(_principal("admin")) is True
    assert _can_review_calendar(_principal("data_manager")) is True
    assert _can_review_calendar(_principal("viewer")) is False
    assert _can_review_calendar(_principal()) is False


def test_site_context_returns_the_current_versioned_timezones() -> None:
    class _Result:
        def mappings(self) -> _Result:
            return self

        def first(self) -> dict[str, object]:
            return {
                "site_id": 1,
                "site_code": "amazon_us",
                "display_name": "Amazon US",
                "config_id": 8,
                "source_timezone": "America/New_York",
                "reporting_timezone": "Asia/Shanghai",
                "currency_code": "USD",
            }

    class _Session:
        def execute(self, _statement: object) -> _Result:
            return _Result()

    response = get_site_context(
        _principal("viewer"),
        cast(Session, _Session()),
    )

    assert response.site_config_version_id == 8
    assert response.source_timezone == "America/New_York"
    assert response.reporting_timezone == "Asia/Shanghai"


def test_roleless_entry_query_enables_the_published_only_filter() -> None:
    class _EmptyRows:
        def mappings(self) -> list[object]:
            return []

    class _RecordingSession:
        parameters: dict[str, object] | None = None

        def execute(
            self,
            _statement: object,
            parameters: dict[str, object],
        ) -> _EmptyRows:
            self.parameters = parameters
            return _EmptyRows()

    session = _RecordingSession()
    assert (
        list_calendar_entries(
            _principal(),
            cast(Session, session),
            date(2026, 8, 1),
            date(2026, 8, 31),
        )
        == []
    )
    assert session.parameters is not None
    assert session.parameters["published_only"] is True


def test_calendar_day_status_uses_red_yellow_blue_green_gray_priority() -> None:
    day = _empty_calendar_day(date(2026, 8, 10))
    assert _calendar_day_status(day) == "gray"

    day.published_report_types.add("business_report")
    assert _calendar_day_status(day) == "blue"

    day.published_report_types.add("return_report")
    assert _calendar_day_status(day) == "green"

    day.has_draft = True
    assert _calendar_day_status(day) == "yellow"

    day.has_blocking_issues = True
    assert _calendar_day_status(day) == "red"


def test_calendar_signals_override_complete_publication() -> None:
    day = _empty_calendar_day(date(2026, 8, 10))
    day.published_report_types.update({"business_report", "return_report"})

    day.has_processing_import = True
    assert _calendar_day_status(day) == "yellow"

    day.has_failed_import = True
    assert _calendar_day_status(day) == "red"

    day.has_failed_import = False
    day.has_file_integrity_error = True
    assert _calendar_day_status(day) == "red"


def test_daily_calendar_rejects_more_than_366_inclusive_days_before_querying() -> None:
    with pytest.raises(ApiError) as error:
        list_calendar_days(
            _principal("data_manager"),
            cast(Session, object()),
            date(2025, 1, 1),
            date(2026, 1, 2),
        )

    assert error.value.status_code == 422
    detail = cast(dict[str, object], error.value.detail)
    assert detail["code"] == "date_range_too_large"
