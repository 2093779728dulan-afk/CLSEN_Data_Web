from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.parsers.parser import parse_report
from app.parsers.rules import REPORT_RULES
from app.parsers.types import (
    BusinessReportRow,
    ParseError,
    ParseSettings,
    ReturnReportRow,
)

from .conftest import csv_bytes

BUSINESS_VALUES = (
    "PARENT",
    "CHILD",
    "  Title is preserved  ",
    "SKU-1",
    "10",
    "2",
    "15.90%",
    "10.00%",
    "15",
    "3",
    "30.00%",
    "15.00%",
    "100.00%",
    "100.00%",
    "2",
    "1",
    "20.00%",
    "50.00%",
    "US$111.98",
    "US$59.99",
    "2",
    "1",
)


def test_business_report_maps_all_fields_and_preserves_source_strings() -> None:
    content = csv_bytes(
        REPORT_RULES["business_report"].source_header,
        [BUSINESS_VALUES],
        encoding="utf-8-sig",
    )

    parsed = parse_report(
        content,
        ParseSettings(report_type="business_report", encoding="utf-8-sig"),
    )

    row = parsed.rows[0]
    assert isinstance(row, BusinessReportRow)
    assert row.source.raw_values == BUSINESS_VALUES
    assert row.title == "  Title is preserved  "
    assert row.sessions_total == 10
    assert row.conversion_rate_total == Decimal("0.159")
    assert row.ordered_product_sales == Decimal("111.98")
    assert row.currency_code == "USD"
    assert parsed.summary.row_count == 1
    assert dict(parsed.summary.totals)["ordered_product_sales"] == "111.98"


def test_parser_preserves_extra_original_columns_without_mapping_them() -> None:
    header = (
        "Operator note",
        *REPORT_RULES["business_report"].source_header,
        "Custom flag",
    )
    values = ("keep me", *BUSINESS_VALUES, "Y")
    content = csv_bytes(header, [values], encoding="utf-8-sig")

    parsed = parse_report(
        content,
        ParseSettings(report_type="business_report", encoding="utf-8-sig"),
    )

    row = parsed.rows[0]
    assert isinstance(row, BusinessReportRow)
    assert parsed.header == header
    assert row.source.raw_values == values
    assert row.sku == "SKU-1"
    assert row.sessions_total == 10


def test_return_csv_semantics_preserve_commas_quotes_newlines_and_raw_values() -> None:
    comment = 'first line, with comma\r\nsecond line says "quoted"'
    values = (
        "2026-08-01T00:15:00+00:00",
        "ORDER",
        "SKU",
        "ASIN",
        "FNSKU",
        "Product, with comma",
        "2",
        "FC",
        "SELLABLE",
        "REASON",
        "STATUS",
        "LPN",
        comment,
    )
    content = csv_bytes(
        REPORT_RULES["return_report"].source_header,
        [values],
        encoding="windows-1252",
    )

    parsed = parse_report(
        content,
        ParseSettings(report_type="return_report", encoding="windows-1252"),
    )

    row = parsed.rows[0]
    assert isinstance(row, ReturnReportRow)
    assert row.source.raw_values == values
    assert row.product_name == "Product, with comma"
    assert row.customer_comments == comment
    assert row.return_date == datetime(2026, 8, 1, 0, 15, tzinfo=UTC)
    assert row.quantity == 2


def test_explicit_timezone_is_independent_of_process_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = (
        "2026-07-31T17:15:00",
        "ORDER",
        "SKU",
        "ASIN",
        "FNSKU",
        "Product",
        "1",
        "FC",
        "SELLABLE",
        "REASON",
        "STATUS",
        "LPN",
        "Comment",
    )
    content = csv_bytes(REPORT_RULES["return_report"].source_header, [values])
    settings = ParseSettings(
        report_type="return_report",
        encoding="utf-8",
        source_timezone="America/Los_Angeles",
    )
    monkeypatch.setenv("TZ", "Asia/Shanghai")

    first = parse_report(content, settings)
    monkeypatch.setenv("TZ", "UTC")
    second = parse_report(content, settings)

    first_row = first.rows[0]
    second_row = second.rows[0]
    assert isinstance(first_row, ReturnReportRow)
    assert isinstance(second_row, ReturnReportRow)
    assert first_row.return_date == second_row.return_date
    assert first.summary.data_digest == second.summary.data_digest


def test_confirmed_type_must_match_the_authoritative_header() -> None:
    content = csv_bytes(REPORT_RULES["return_report"].source_header, [])

    with pytest.raises(ParseError) as captured:
        parse_report(
            content,
            ParseSettings(report_type="business_report", encoding="utf-8"),
        )

    assert captured.value.code == "header_mismatch"
    assert captured.value.decoded_header == REPORT_RULES["return_report"].source_header
    assert captured.value.decoded_rows == ()


def test_strict_csv_rejects_unterminated_quoted_field() -> None:
    header = ",".join(REPORT_RULES["return_report"].source_header)
    content = f'{header}\r\n"unterminated'.encode()

    with pytest.raises(ParseError) as captured:
        parse_report(
            content,
            ParseSettings(report_type="return_report", encoding="utf-8"),
        )

    assert captured.value.code == "invalid_csv"
    assert captured.value.decoded_header is None
    assert captured.value.decoded_rows == ()


def test_row_with_wrong_column_count_is_rejected() -> None:
    content = csv_bytes(
        REPORT_RULES["return_report"].source_header,
        [["only-one-field"]],
    )

    with pytest.raises(ParseError) as captured:
        parse_report(
            content,
            ParseSettings(report_type="return_report", encoding="utf-8"),
        )

    assert captured.value.code == "column_count_mismatch"
    assert captured.value.source_row_number == 2
    assert captured.value.decoded_header == REPORT_RULES["return_report"].source_header
    assert captured.value.decoded_rows == (("only-one-field",),)


def test_conversion_failure_carries_rows_without_value_leak() -> None:
    values = (*BUSINESS_VALUES[:4], "not-an-integer", *BUSINESS_VALUES[5:])
    content = csv_bytes(REPORT_RULES["business_report"].source_header, [values])

    with pytest.raises(ParseError) as captured:
        parse_report(
            content,
            ParseSettings(report_type="business_report", encoding="utf-8"),
        )

    assert captured.value.code == "invalid_integer"
    assert captured.value.decoded_rows == (values,)
    assert "not-an-integer" not in str(captured.value)


def test_long_text_is_not_truncated_by_the_csv_module_default_limit() -> None:
    comment = "x" * 150_000
    values = (
        "2026-08-01T00:15:00+00:00",
        "ORDER",
        "SKU",
        "ASIN",
        "FNSKU",
        "Product",
        "1",
        "FC",
        "SELLABLE",
        "REASON",
        "STATUS",
        "LPN",
        comment,
    )
    content = csv_bytes(REPORT_RULES["return_report"].source_header, [values])

    parsed = parse_report(
        content,
        ParseSettings(report_type="return_report", encoding="utf-8"),
    )

    row = parsed.rows[0]
    assert isinstance(row, ReturnReportRow)
    assert row.customer_comments == comment


def test_digest_is_deterministic_and_changes_with_exact_source_text() -> None:
    header = REPORT_RULES["business_report"].source_header
    content = csv_bytes(header, [BUSINESS_VALUES])
    settings = ParseSettings(report_type="business_report", encoding="utf-8")

    first = parse_report(content, settings)
    second = parse_report(content, settings)
    changed_values = (*BUSINESS_VALUES[:2], "Title changed", *BUSINESS_VALUES[3:])
    changed = parse_report(csv_bytes(header, [changed_values]), settings)

    assert first.summary.data_digest == second.summary.data_digest
    assert len(first.summary.data_digest) == 64
    assert first.rows[0].typed_digest == second.rows[0].typed_digest
    assert len(first.rows[0].typed_digest) == 64
    assert first.source_rows[0].row_digest != changed.source_rows[0].row_digest
    assert first.rows[0].typed_digest != changed.rows[0].typed_digest
    assert first.summary.data_digest != changed.summary.data_digest


def test_typed_digest_ignores_equivalent_source_number_formatting() -> None:
    header = REPORT_RULES["business_report"].source_header
    settings = ParseSettings(report_type="business_report", encoding="utf-8")
    equivalent_values = (
        *BUSINESS_VALUES[:6],
        "15.900%",
        *BUSINESS_VALUES[7:],
    )

    original = parse_report(csv_bytes(header, [BUSINESS_VALUES]), settings)
    equivalent = parse_report(csv_bytes(header, [equivalent_values]), settings)

    assert original.rows[0].typed_digest == equivalent.rows[0].typed_digest
    assert original.source_rows[0].row_digest != equivalent.source_rows[0].row_digest
