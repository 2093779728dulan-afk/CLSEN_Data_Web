"""Domain types shared by deterministic report recognition and parsing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from app.imports.types import ReportType

type SupportedEncoding = Literal["utf-8-sig", "utf-8", "windows-1252"]
type ParseErrorCode = Literal[
    "ambiguous_local_time",
    "column_count_mismatch",
    "duplicate_header",
    "empty_csv",
    "header_mismatch",
    "invalid_csv",
    "invalid_datetime",
    "invalid_encoding",
    "invalid_integer",
    "invalid_percentage",
    "invalid_source_timezone",
    "invalid_usd",
    "missing_source_timezone",
    "nonexistent_local_time",
]


class FieldKind(StrEnum):
    """Supported deterministic source-to-baseline conversions."""

    TEXT = "text"
    INTEGER = "integer"
    PERCENTAGE = "percentage"
    USD = "usd"
    EVENT_DATETIME = "event_datetime"


class ParseError(ValueError):
    """A blocking, expected failure while decoding or converting a report."""

    def __init__(
        self,
        message: str,
        *,
        code: ParseErrorCode,
        source_row_number: int | None = None,
        field_name: str | None = None,
        decoded_header: tuple[str, ...] | None = None,
        decoded_rows: tuple[tuple[str, ...], ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.source_row_number = source_row_number
        self.field_name = field_name
        self.decoded_header = decoded_header
        self.decoded_rows = decoded_rows


@dataclass(frozen=True, slots=True)
class ParseSettings:
    """Human-confirmed settings frozen for one parse operation."""

    report_type: ReportType
    encoding: SupportedEncoding
    source_timezone: str | None = None
    delimiter: Literal[","] = ","

    def __post_init__(self) -> None:
        if self.report_type not in {"business_report", "return_report"}:
            raise ValueError("report_type is not supported")
        if self.encoding not in {"utf-8-sig", "utf-8", "windows-1252"}:
            raise ValueError("encoding is not supported")
        if self.source_timezone is not None:
            timezone_name = self.source_timezone.strip()
            if not timezone_name:
                raise ValueError("source_timezone must not be blank")
            object.__setattr__(self, "source_timezone", timezone_name)


@dataclass(frozen=True, slots=True)
class RecognitionIssue:
    """Stable machine-readable evidence requiring human attention."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    """A non-authoritative suggestion derived from the uploaded content."""

    status: Literal["suggested", "conflict", "unsupported"]
    report_type: ReportType | None
    detected_report_date: date | None
    encoding: SupportedEncoding | None
    ruleset_version: str | None
    header: tuple[str, ...] | None
    issues: tuple[RecognitionIssue, ...]


@dataclass(frozen=True, slots=True)
class SourceRow:
    """One decoded logical CSV record with every source string preserved."""

    source_row_number: int
    raw_values: tuple[str, ...]
    row_digest: str


@dataclass(frozen=True, slots=True)
class BusinessReportRow:
    source: SourceRow
    typed_digest: str
    parent_asin: str
    child_asin: str
    title: str
    sku: str
    sessions_total: int
    sessions_b2b: int
    conversion_rate_total: Decimal
    session_percentage_b2b: Decimal
    page_views_total: int
    page_views_b2b: int
    page_view_percentage_total: Decimal
    page_view_percentage_b2b: Decimal
    featured_offer_percentage: Decimal
    featured_offer_percentage_b2b: Decimal
    units_ordered: int
    units_ordered_b2b: int
    unit_session_percentage: Decimal
    unit_session_percentage_b2b: Decimal
    ordered_product_sales: Decimal
    ordered_product_sales_b2b: Decimal
    currency_code: Literal["USD"]
    total_order_items: int
    total_order_items_b2b: int


@dataclass(frozen=True, slots=True)
class ReturnReportRow:
    source: SourceRow
    typed_digest: str
    return_date: datetime
    order_id: str
    sku: str
    asin: str
    fnsku: str
    product_name: str
    quantity: int
    fulfillment_center_id: str
    detailed_disposition: str
    reason: str
    status: str
    license_plate_number: str
    customer_comments: str


type ParsedRow = BusinessReportRow | ReturnReportRow


@dataclass(frozen=True, slots=True)
class ParseSummary:
    row_count: int
    totals: tuple[tuple[str, str], ...]
    data_digest: str


@dataclass(frozen=True, slots=True)
class ParsedReport:
    """Complete immutable output ready for transactional persistence."""

    report_type: ReportType
    parser_version: str
    ruleset_version: str
    encoding: SupportedEncoding
    delimiter: Literal[","]
    header: tuple[str, ...]
    source_rows: tuple[SourceRow, ...]
    rows: tuple[ParsedRow, ...]
    summary: ParseSummary
