"""Pure deterministic conversion from confirmed CSV bytes to typed baselines."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, cast

from app.parsers.converters import (
    parse_event_datetime,
    parse_integer,
    parse_percentage,
    parse_usd,
)
from app.parsers.csv_reader import read_csv_document
from app.parsers.rules import REPORT_RULES, FieldRule, ReportRule
from app.parsers.types import (
    BusinessReportRow,
    FieldKind,
    ParsedReport,
    ParsedRow,
    ParseError,
    ParseSettings,
    ParseSummary,
    ReturnReportRow,
    SourceRow,
)

PARSER_VERSION: Final = "amazon_csv_parser_v1"
type ConvertedValue = str | int | Decimal | datetime


def _normalise_header(header: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value.strip() for value in header)


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _canonical_value(value: ConvertedValue) -> str | int:
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC)
        return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return value


def _json_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _convert(
    raw_value: str,
    field: FieldRule,
    settings: ParseSettings,
) -> ConvertedValue:
    if field.kind is FieldKind.TEXT:
        return raw_value
    if field.kind is FieldKind.INTEGER:
        return parse_integer(raw_value)
    if field.kind is FieldKind.PERCENTAGE:
        return parse_percentage(raw_value)
    if field.kind is FieldKind.USD:
        return parse_usd(raw_value)
    return parse_event_datetime(raw_value, source_timezone=settings.source_timezone)


def _typed_digest(
    rule: ReportRule,
    converted: dict[str, ConvertedValue],
) -> str:
    return _json_digest(
        {
            "report_type": rule.report_type,
            "ruleset_version": rule.version,
            "typed_values": {
                name: _canonical_value(value)
                for name, value in sorted(converted.items())
            },
        }
    )


def _convert_row(
    values: tuple[str, ...],
    *,
    field_indexes: tuple[int, ...],
    source_row_number: int,
    rule: ReportRule,
    settings: ParseSettings,
) -> tuple[SourceRow, ParsedRow, dict[str, ConvertedValue]]:
    source = SourceRow(
        source_row_number=source_row_number,
        raw_values=values,
        row_digest=_json_digest(
            {
                "source_row_number": source_row_number,
                "raw_values": values,
            }
        ),
    )
    converted: dict[str, ConvertedValue] = {}
    for field, field_index in zip(rule.fields, field_indexes, strict=True):
        raw_value = values[field_index]
        try:
            converted[field.target_name] = _convert(raw_value, field, settings)
        except ParseError as error:
            raise ParseError(
                str(error),
                code=error.code,
                source_row_number=source_row_number,
                field_name=field.source_name,
            ) from error

    if rule.report_type == "business_report":
        row: ParsedRow = BusinessReportRow(
            source=source,
            typed_digest=_typed_digest(rule, converted),
            parent_asin=cast(str, converted["parent_asin"]),
            child_asin=cast(str, converted["child_asin"]),
            title=cast(str, converted["title"]),
            sku=cast(str, converted["sku"]),
            sessions_total=cast(int, converted["sessions_total"]),
            sessions_b2b=cast(int, converted["sessions_b2b"]),
            conversion_rate_total=cast(Decimal, converted["conversion_rate_total"]),
            session_percentage_b2b=cast(Decimal, converted["session_percentage_b2b"]),
            page_views_total=cast(int, converted["page_views_total"]),
            page_views_b2b=cast(int, converted["page_views_b2b"]),
            page_view_percentage_total=cast(
                Decimal, converted["page_view_percentage_total"]
            ),
            page_view_percentage_b2b=cast(
                Decimal, converted["page_view_percentage_b2b"]
            ),
            featured_offer_percentage=cast(
                Decimal, converted["featured_offer_percentage"]
            ),
            featured_offer_percentage_b2b=cast(
                Decimal, converted["featured_offer_percentage_b2b"]
            ),
            units_ordered=cast(int, converted["units_ordered"]),
            units_ordered_b2b=cast(int, converted["units_ordered_b2b"]),
            unit_session_percentage=cast(Decimal, converted["unit_session_percentage"]),
            unit_session_percentage_b2b=cast(
                Decimal, converted["unit_session_percentage_b2b"]
            ),
            ordered_product_sales=cast(Decimal, converted["ordered_product_sales"]),
            ordered_product_sales_b2b=cast(
                Decimal, converted["ordered_product_sales_b2b"]
            ),
            currency_code="USD",
            total_order_items=cast(int, converted["total_order_items"]),
            total_order_items_b2b=cast(int, converted["total_order_items_b2b"]),
        )
    else:
        row = ReturnReportRow(
            source=source,
            typed_digest=_typed_digest(rule, converted),
            return_date=cast(datetime, converted["return_date"]),
            order_id=cast(str, converted["order_id"]),
            sku=cast(str, converted["sku"]),
            asin=cast(str, converted["asin"]),
            fnsku=cast(str, converted["fnsku"]),
            product_name=cast(str, converted["product_name"]),
            quantity=cast(int, converted["quantity"]),
            fulfillment_center_id=cast(str, converted["fulfillment_center_id"]),
            detailed_disposition=cast(str, converted["detailed_disposition"]),
            reason=cast(str, converted["reason"]),
            status=cast(str, converted["status"]),
            license_plate_number=cast(str, converted["license_plate_number"]),
            customer_comments=cast(str, converted["customer_comments"]),
        )
    return source, row, converted


def _totals(
    converted_rows: tuple[dict[str, ConvertedValue], ...],
    rule: ReportRule,
) -> tuple[tuple[str, str], ...]:
    total_fields = (
        field
        for field in rule.fields
        if field.kind in {FieldKind.INTEGER, FieldKind.USD}
    )
    totals: list[tuple[str, str]] = []
    for field in total_fields:
        total = Decimal(0)
        for row in converted_rows:
            value = row[field.target_name]
            if isinstance(value, int):
                total += Decimal(value)
            else:
                total += cast(Decimal, value)
        totals.append((field.target_name, _canonical_decimal(total)))
    return tuple(sorted(totals))


def _report_digest(
    *,
    rule: ReportRule,
    header: tuple[str, ...],
    source_rows: tuple[SourceRow, ...],
    converted_rows: tuple[dict[str, ConvertedValue], ...],
    totals: tuple[tuple[str, str], ...],
) -> str:
    rows = []
    for source, converted in zip(source_rows, converted_rows, strict=True):
        rows.append(
            {
                "source_row_number": source.source_row_number,
                "raw_values": source.raw_values,
                "typed_values": {
                    name: _canonical_value(value)
                    for name, value in sorted(converted.items())
                },
            }
        )
    return _json_digest(
        {
            "report_type": rule.report_type,
            "ruleset_version": rule.version,
            "header": header,
            "rows": rows,
            "totals": totals,
        }
    )


def parse_decoded_report(
    header: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    settings: ParseSettings,
) -> ParsedReport:
    """Apply the frozen parser contract to an immutable decoded CSV snapshot."""

    rule = REPORT_RULES[settings.report_type]
    normalised_header = _normalise_header(header)
    if len(normalised_header) != len(set(normalised_header)):
        raise ParseError(
            "CSV contains duplicate headers",
            code="duplicate_header",
            decoded_header=header,
            decoded_rows=rows,
        )
    header_indexes = {name: index for index, name in enumerate(normalised_header)}
    if not set(rule.normalised_header) <= set(header_indexes):
        raise ParseError(
            "CSV header does not match the confirmed report type",
            code="header_mismatch",
            decoded_header=header,
            decoded_rows=rows,
        )

    sources: list[SourceRow] = []
    parsed_rows: list[ParsedRow] = []
    converted_rows: list[dict[str, ConvertedValue]] = []
    for source_row_number, values in enumerate(rows, start=2):
        if len(values) != len(header):
            raise ParseError(
                "CSV row has an unexpected number of columns",
                code="column_count_mismatch",
                source_row_number=source_row_number,
                decoded_header=header,
                decoded_rows=rows,
            )
        try:
            source, row, converted = _convert_row(
                values,
                field_indexes=tuple(
                    header_indexes[field_name] for field_name in rule.normalised_header
                ),
                source_row_number=source_row_number,
                rule=rule,
                settings=settings,
            )
        except ParseError as error:
            raise ParseError(
                str(error),
                code=error.code,
                source_row_number=error.source_row_number,
                field_name=error.field_name,
                decoded_header=header,
                decoded_rows=rows,
            ) from error
        sources.append(source)
        parsed_rows.append(row)
        converted_rows.append(converted)

    frozen_sources = tuple(sources)
    frozen_converted = tuple(converted_rows)
    totals = _totals(frozen_converted, rule)
    summary = ParseSummary(
        row_count=len(parsed_rows),
        totals=totals,
        data_digest=_report_digest(
            rule=rule,
            header=header,
            source_rows=frozen_sources,
            converted_rows=frozen_converted,
            totals=totals,
        ),
    )
    return ParsedReport(
        report_type=rule.report_type,
        parser_version=PARSER_VERSION,
        ruleset_version=rule.version,
        encoding=settings.encoding,
        delimiter=settings.delimiter,
        header=header,
        source_rows=frozen_sources,
        rows=tuple(parsed_rows),
        summary=summary,
    )


def parse_report(content: bytes, settings: ParseSettings) -> ParsedReport:
    """Parse bytes using explicit human-confirmed settings without I/O side effects."""

    document = read_csv_document(
        content,
        encoding=settings.encoding,
        delimiter=settings.delimiter,
    )
    return parse_decoded_report(document.header, document.rows, settings)
