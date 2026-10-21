from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.parsers.converters import (
    parse_event_datetime,
    parse_integer,
    parse_percentage,
    parse_usd,
)
from app.parsers.types import ParseError


def test_decimal_converters_do_not_pass_through_float() -> None:
    assert parse_usd(" US$111.98 ") == Decimal("111.98")
    assert parse_percentage("15.90%") == Decimal("0.159")
    assert parse_integer("2") == 2


@pytest.mark.parametrize("value", ["US$1,23.45", "US$12,34.56", "US$1,234,56"])
def test_usd_rejects_invalid_thousands_grouping(value: str) -> None:
    with pytest.raises(ParseError) as captured:
        parse_usd(value)

    assert captured.value.code == "invalid_usd"


def test_usd_fits_decimal_20_6_without_database_rounding() -> None:
    assert parse_usd("US$99,999,999,999,999.999999") == Decimal("99999999999999.999999")

    for value in ("US$100,000,000,000,000", "US$1.0000001"):
        with pytest.raises(ParseError) as captured:
            parse_usd(value)
        assert captured.value.code == "invalid_usd"


def test_percentage_ratio_fits_decimal_12_9_without_database_rounding() -> None:
    assert parse_percentage("99999.9999999%") == Decimal("999.999999999")

    for value in ("100000%", "0.00000001%"):
        with pytest.raises(ParseError) as captured:
            parse_percentage(value)
        assert captured.value.code == "invalid_percentage"


@pytest.mark.parametrize("value", ["NaN%", "Infinity%", "12.5"])
def test_invalid_percentages_are_rejected(value: str) -> None:
    with pytest.raises(ParseError, match="percentage"):
        parse_percentage(value)


def test_timestamp_with_offset_is_normalised_to_utc() -> None:
    assert parse_event_datetime(
        "2026-08-01T01:15:00+01:00",
        source_timezone=None,
    ) == datetime(2026, 8, 1, 0, 15, tzinfo=UTC)


def test_timestamp_utc_overflow_is_a_blocking_parse_error() -> None:
    with pytest.raises(ParseError) as captured:
        parse_event_datetime(
            "9999-12-31T23:59:59-01:00",
            source_timezone=None,
        )

    assert captured.value.code == "invalid_datetime"


def test_naive_timestamp_uses_the_explicit_source_timezone() -> None:
    assert parse_event_datetime(
        "2026-07-31T17:15:00",
        source_timezone="America/Los_Angeles",
    ) == datetime(2026, 8, 1, 0, 15, tzinfo=UTC)


def test_naive_timestamp_without_source_timezone_is_blocking() -> None:
    with pytest.raises(ParseError) as captured:
        parse_event_datetime("2026-07-31T17:15:00", source_timezone=None)

    assert captured.value.code == "missing_source_timezone"


def test_invalid_source_timezone_key_is_a_blocking_parse_error() -> None:
    with pytest.raises(ParseError) as captured:
        parse_event_datetime(
            "2026-07-31T17:15:00",
            source_timezone="../UTC",
        )

    assert captured.value.code == "invalid_source_timezone"


@pytest.mark.parametrize(
    ("value", "source_timezone"),
    [
        ("9999-12-31T23:59:59", "America/Los_Angeles"),
        ("0001-01-01T00:00:00", "Asia/Shanghai"),
    ],
)
def test_naive_timestamp_utc_overflow_is_a_blocking_parse_error(
    value: str,
    source_timezone: str,
) -> None:
    with pytest.raises(ParseError) as captured:
        parse_event_datetime(value, source_timezone=source_timezone)

    assert captured.value.code == "invalid_datetime"


@pytest.mark.parametrize(
    ("value", "expected_code"),
    [
        ("2026-11-01T01:30:00", "ambiguous_local_time"),
        ("2026-03-08T02:30:00", "nonexistent_local_time"),
    ],
)
def test_dst_ambiguous_and_nonexistent_local_times_are_rejected(
    value: str,
    expected_code: str,
) -> None:
    with pytest.raises(ParseError) as captured:
        parse_event_datetime(value, source_timezone="America/Los_Angeles")

    assert captured.value.code == expected_code
