"""Public, redacted response models for current published analytics."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class DateRange(BaseModel):
    from_date: date
    to_date: date


class PublicationReference(BaseModel):
    """The exact publication pointer consumed by one analytics response."""

    dataset_id: int
    site_id: int
    report_date: date
    report_type: Literal["business_report", "return_report"]
    version_id: int
    published_at: datetime


class SiteConfigurationReference(BaseModel):
    """The current versioned site configuration used for query semantics."""

    site_id: int
    site_code: str
    site_config_version_id: int
    source_timezone: str
    reporting_timezone: str
    currency_code: str


class DashboardMetric(BaseModel):
    report_date: date
    sales: str
    units_ordered: int
    sessions: int
    conversion_rate: str | None
    return_quantity: int
    business_version_id: int | None
    return_version_id: int | None


class DashboardSummary(BaseModel):
    range: DateRange
    metrics: list[DashboardMetric]
    publications: list[PublicationReference]
    site_config_versions: list[SiteConfigurationReference]


class ProductMetric(BaseModel):
    sku: str | None
    asin: str | None
    sales: str
    units_ordered: int
    sessions: int
    conversion_rate: str | None


class ProductDashboard(BaseModel):
    range: DateRange
    rows: list[ProductMetric]
    publications: list[PublicationReference]
    site_config_versions: list[SiteConfigurationReference]


class ReturnBreakdown(BaseModel):
    bucket_date: date
    sku: str | None
    asin: str | None
    reason: str | None
    disposition: str | None
    quantity: int
    reporting_timezone: str
    site_config_version_id: int


class ReturnDashboard(BaseModel):
    basis: Literal["report_date", "event_date"]
    range: DateRange
    rows: list[ReturnBreakdown]
    publications: list[PublicationReference]
    site_config_versions: list[SiteConfigurationReference]


type ReportLedgerStatus = Literal[
    "published",
    "draft",
    "processing",
    "failed",
    "blocked",
    "missing",
    "future",
]
type OverallLedgerStatus = Literal[
    "complete",
    "partial",
    "review",
    "blocked",
    "empty",
    "future",
]
type LedgerReason = Literal[
    "blocking_issues",
    "failed_import",
    "file_integrity_error",
    "draft",
    "warnings",
    "processing_import",
]


class DailyLedgerRow(BaseModel):
    report_date: date
    business_status: ReportLedgerStatus
    return_status: ReportLedgerStatus
    overall_status: OverallLedgerStatus
    sales: str | None
    units_ordered: int | None
    sessions: int | None
    conversion_rate: str | None
    return_quantity: int | None
    pending_summary: str | None
    reasons: list[LedgerReason]
    counts_as_incomplete: bool


class DailyLedgerResponse(BaseModel):
    range: DateRange
    rows: list[DailyLedgerRow]
    publications: list[PublicationReference]
    site_config_versions: list[SiteConfigurationReference]


type ProductNameStatus = Literal["available", "multiple", "missing"]
type ProductRowKind = Literal["product", "unclassified"]
type ProductLedgerSort = Literal[
    "sales",
    "units_ordered",
    "sessions",
    "conversion_rate",
    "return_quantity",
    "published_days",
    "latest_published_date",
    "style_code",
    "product_name",
]
type SortDirection = Literal["asc", "desc"]


class ProductLedgerRow(BaseModel):
    row_kind: ProductRowKind
    style_code: str | None
    unclassified_sku: str | None
    product_name: str | None
    name_status: ProductNameStatus
    variant_count: int
    color_count: int
    size_count: int
    sales: str
    units_ordered: int
    sessions: int
    conversion_rate: str | None
    return_quantity: int
    published_days: int
    latest_published_date: date | None


class ProductLedgerResponse(BaseModel):
    range: DateRange
    rows: list[ProductLedgerRow]
    total_rows: int
    page: int
    page_size: int
    sort: ProductLedgerSort
    direction: SortDirection
    publications: list[PublicationReference]
    site_config_versions: list[SiteConfigurationReference]


class ProductVariant(BaseModel):
    seller_sku: str
    color: str
    size: str
    product_name: str | None
    asins: list[str]
    fnskus: list[str]


class ProductTrendPoint(BaseModel):
    report_date: date
    sales: str
    units_ordered: int
    sessions: int
    conversion_rate: str | None
    return_quantity: int


class ProductCardSummary(BaseModel):
    sales: str
    units_ordered: int
    sessions: int
    conversion_rate: str | None
    return_quantity: int
    published_days: int


class ProductCardResponse(BaseModel):
    range: DateRange
    style_code: str
    product_name: str | None
    name_status: ProductNameStatus
    summary: ProductCardSummary
    latest_published_date: date | None
    trend: list[ProductTrendPoint]
    variants: list[ProductVariant]
    publications: list[PublicationReference]
    site_config_versions: list[SiteConfigurationReference]
