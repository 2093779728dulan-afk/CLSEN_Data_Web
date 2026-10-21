"""Strict response and value models for stable P0 style analytics."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.catalog.canonical_json import canonical_json_bytes

type ReportType = Literal["business_report", "return_report"]
type ReportStatus = Literal["published", "missing"]
type ValueState = Literal["observed", "zero", "missing_report", "undefined_denominator"]
type NullReason = Literal[
    "missing_report", "undefined_denominator", "no_observed_reports"
]
type SourceCompleteness = Literal["complete", "partial", "indeterminate"]
type CoverageStatus = Literal["not_applicable", "partial", "complete"]
type MetricStatus = Literal["evaluable", "not_evaluable"]
type FactBasis = Literal["current", "catalog_snapshot"]
type ReturnBasis = Literal["event_date", "report_date"]
type MetricName = Literal["units", "sales", "returns", "sessions", "conversion"]
type SeriesDimension = Literal["total", "color", "size", "sku"]

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]

_MONEY = re.compile(r"^-?(?:0|[1-9][0-9]*)\.[0-9]{2}$")
_SIX_PLACES = re.compile(r"^-?(?:0|[1-9][0-9]*)\.[0-9]{6}$")
_RATE = re.compile(r"^(?:0\.[0-9]{6}|1\.000000)$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_serialization_defaults_required=True,
    )


class MetricValue(_StrictModel):
    value: int | str | None
    value_state: ValueState
    null_reason: NullReason | None
    is_partial: bool
    observed_days: NonNegativeInt
    expected_days: PositiveInt
    source_completeness: SourceCompleteness
    numerator: int | None
    denominator: int | None

    @model_validator(mode="after")
    def _state_is_consistent(self) -> Self:
        if self.observed_days > self.expected_days:
            raise ValueError("observed days exceed expected days")
        if self.value_state in {"observed", "zero"}:
            if self.value is None or self.null_reason is not None:
                raise ValueError("numeric metric states require a value")
        elif self.value is not None or self.null_reason is None:
            raise ValueError("null metric states require a reason")
        if self.null_reason == "missing_report":
            raise ValueError("daily-only missing_report reason is invalid for a range")
        if isinstance(self.value, str) and not (
            _MONEY.fullmatch(self.value) or _SIX_PLACES.fullmatch(self.value)
        ):
            raise ValueError("decimal metric value has a non-canonical scale")
        if (self.numerator is None) != (self.denominator is None):
            raise ValueError("conversion numerator and denominator are paired")
        if self.value_state == "missing_report" and (
            self.numerator is not None or self.denominator is not None
        ):
            raise ValueError("missing range conversion has no operands")
        return self


class TrendPoint(_StrictModel):
    date: date
    value: int | str | None
    value_state: ValueState
    null_reason: NullReason | None
    source_completeness: SourceCompleteness
    numerator: int | None
    denominator: int | None

    @model_validator(mode="after")
    def _state_is_consistent(self) -> Self:
        if self.value_state in {"observed", "zero"}:
            if self.value is None or self.null_reason is not None:
                raise ValueError("numeric trend states require a value")
        elif self.value is not None or self.null_reason is None:
            raise ValueError("null trend states require a reason")
        if isinstance(self.value, str) and not (
            _MONEY.fullmatch(self.value) or _SIX_PLACES.fullmatch(self.value)
        ):
            raise ValueError("decimal trend value has a non-canonical scale")
        if (self.numerator is None) != (self.denominator is None):
            raise ValueError("conversion operands are paired")
        return self


class MetricValues(_StrictModel):
    units: MetricValue
    sales: MetricValue
    returns: MetricValue
    sessions: MetricValue
    conversion: MetricValue


class PublicationDay(_StrictModel):
    report_type: ReportType
    report_date: date
    report_status: ReportStatus
    dataset_id: str | None
    published_version_id: str | None
    snapshot_member_id: str | None
    pointer_revision: NonNegativeInt | None

    @model_validator(mode="after")
    def _identity_matches_status(self) -> Self:
        published = self.report_status == "published"
        if published != (self.dataset_id is not None):
            raise ValueError("publication status and dataset identity disagree")
        if published != (self.published_version_id is not None):
            raise ValueError("publication status and version identity disagree")
        return self

    def digest_payload(self) -> dict[str, str | int | None]:
        return {
            "report_type": self.report_type,
            "report_date": self.report_date.isoformat(),
            "report_status": self.report_status,
            "dataset_id": self.dataset_id,
            "published_version_id": self.published_version_id,
            "snapshot_member_id": self.snapshot_member_id,
            "pointer_revision": self.pointer_revision,
        }


def _nullable_sort(value: str | int | None) -> tuple[int, bytes | int]:
    if value is None:
        return (0, b"")
    if isinstance(value, int):
        return (1, value)
    return (1, value.encode("utf-8"))


def _publication_sort_key(day: PublicationDay) -> tuple[tuple[int, bytes | int], ...]:
    payload = day.digest_payload()
    return tuple(
        _nullable_sort(payload[name])
        for name in (
            "report_type",
            "report_date",
            "report_status",
            "dataset_id",
            "published_version_id",
            "snapshot_member_id",
            "pointer_revision",
        )
    )


class PublicationRefs(_StrictModel):
    mode: FactBasis
    snapshot_id: str | None
    members_digest_version: Literal["publication_refs_jcs_v1"]
    members_digest: str
    members: list[PublicationDay]

    @classmethod
    def build(
        cls,
        *,
        mode: FactBasis,
        snapshot_id: int | str | None,
        members: list[PublicationDay],
    ) -> Self:
        ordered = sorted(members, key=_publication_sort_key)
        digest = (
            "sha256:"
            + hashlib.sha256(
                canonical_json_bytes([member.digest_payload() for member in ordered])
            ).hexdigest()
        )
        return cls(
            mode=mode,
            snapshot_id=None if snapshot_id is None else str(snapshot_id),
            members_digest_version="publication_refs_jcs_v1",
            members_digest=digest,
            members=ordered,
        )

    @model_validator(mode="after")
    def _digest_is_valid(self) -> Self:
        if not _DIGEST.fullmatch(self.members_digest):
            raise ValueError("publication member digest is invalid")
        if self.mode == "current" and self.snapshot_id is not None:
            raise ValueError("current publication refs cannot name a snapshot")
        if self.mode == "catalog_snapshot" and self.snapshot_id is None:
            raise ValueError("snapshot publication refs require a snapshot")
        return self


class CoverageBlock(_StrictModel):
    report_type: ReportType
    coverage_from: date
    coverage_to: date
    expected_days: PositiveInt
    published_days: NonNegativeInt
    missing_days: NonNegativeInt
    eligible_rows: NonNegativeInt
    mapped_rows: NonNegativeInt
    unmatched_rows: NonNegativeInt
    excluded_rows: NonNegativeInt
    unique_rows: NonNegativeInt | None
    confirmed_distinct_rows: NonNegativeInt | None
    duplicate_of_rows: NonNegativeInt | None
    unresolved_rows: NonNegativeInt | None
    report_coverage_rate: str | None
    identity_decision_rate: str | None
    mapping_rate: str | None
    dedup_decision_rate: str | None
    identity_status: CoverageStatus
    dedup_status: CoverageStatus

    @model_validator(mode="after")
    def _coverage_is_consistent(self) -> Self:
        if self.coverage_from > self.coverage_to:
            raise ValueError("coverage is inverted")
        if self.published_days + self.missing_days != self.expected_days:
            raise ValueError("report day counts do not reconcile")
        identity_rows = self.mapped_rows + self.unmatched_rows + self.excluded_rows
        if identity_rows != self.eligible_rows:
            raise ValueError("identity row counts do not reconcile")
        for rate in (
            self.report_coverage_rate,
            self.identity_decision_rate,
            self.mapping_rate,
            self.dedup_decision_rate,
        ):
            if rate is not None and not _RATE.fullmatch(rate):
                raise ValueError("coverage rate has a non-canonical scale")
        dedup_counts = (
            self.unique_rows,
            self.confirmed_distinct_rows,
            self.duplicate_of_rows,
            self.unresolved_rows,
        )
        if self.report_type == "business_report":
            if any(value is not None for value in dedup_counts):
                raise ValueError("business dedup counts are not applicable")
            if (
                self.dedup_decision_rate is not None
                or self.dedup_status != "not_applicable"
            ):
                raise ValueError("business dedup coverage is not applicable")
        elif any(value is None for value in dedup_counts):
            raise ValueError("return dedup counts are required")
        return self


class SiteCoverage(_StrictModel):
    scope: Literal["site"] = "site"
    business: CoverageBlock
    returns: CoverageBlock


class MetricTotals(_StrictModel):
    units: int | None
    sales: str | None
    returns: NonNegativeInt | None
    sessions: int | None
    conversion_numerator: int | None
    conversion_denominator: int | None

    @model_validator(mode="after")
    def _decimal_and_operands_are_valid(self) -> Self:
        if self.sales is not None and not _MONEY.fullmatch(self.sales):
            raise ValueError("sales total must have two decimal places")
        if (self.conversion_numerator is None) != (self.conversion_denominator is None):
            raise ValueError("conversion operands are paired")
        return self


class MetricEvaluability(_StrictModel):
    units: MetricStatus
    sales: MetricStatus
    returns: MetricStatus
    sessions: MetricStatus
    conversion: MetricStatus


class SiteReconciliation(_StrictModel):
    scope: Literal["site"] = "site"
    metric_status: MetricEvaluability
    source_totals: MetricTotals
    mapped_totals: MetricTotals
    unmatched_totals: MetricTotals
    excluded_totals: MetricTotals
    duplicate_totals: MetricTotals
    unresolved_duplicate_totals: MetricTotals


class StyleReconciliation(_StrictModel):
    scope: Literal["style"] = "style"
    metric_status: MetricEvaluability
    series_scope: Literal["style", "selected_color"]
    summary_totals: MetricTotals
    variant_totals: MetricTotals
    series_scope_totals: MetricTotals
    selected_color_totals: MetricTotals | None


class SourceReportCoverage(_StrictModel):
    coverage_from: date
    coverage_to: date
    days: list[PublicationDay]
    contributing_report_date_from: date | None
    contributing_report_date_to: date | None


class AnalyticsPermissions(_StrictModel):
    can_view_catalog_history: bool
    can_manage_catalog: bool
    can_view_evidence_history: bool
    can_download_original: bool
    can_submit: bool
    can_approve_normal: bool
    can_approve_high_risk: bool


class AnalyticsProvenance(_StrictModel):
    catalog_version_id: str
    catalog_version: PositiveInt
    fact_basis: FactBasis
    identity_source: Literal["p0_catalog"] = "p0_catalog"
    identity_version_id: str
    publication_refs: PublicationRefs
    return_dedup_snapshot_id: str
    site_config_version_id: str
    reporting_timezone: str
    consistent_as_of: datetime
    fact_cutoff_at: datetime
    from_date: date = Field(serialization_alias="from")
    to_date: date = Field(serialization_alias="to")
    return_basis: ReturnBasis
    effective_return_basis: ReturnBasis
    trend_effective_return_basis: ReturnBasis | None


class StyleLedgerRow(_StrictModel):
    style_id: str
    style_code: str
    standard_name: str
    status: Literal["enabled", "disabled"]
    sku_count: NonNegativeInt
    color_count: NonNegativeInt
    size_count: NonNegativeInt
    source_title_count: NonNegativeInt
    latest_report_date: date | None
    metrics: MetricValues


class StyleLedgerResponse(_StrictModel):
    # Search-filtered, before pagination; null when unavailable.
    filtered_sales_total: str | None = None
    rows: list[StyleLedgerRow]
    total_rows: NonNegativeInt
    page: PositiveInt
    page_size: PositiveInt
    sort: Literal[
        "style_code",
        "standard_name",
        "units",
        "sales",
        "returns",
        "sessions",
        "conversion",
    ]
    direction: Literal["asc", "desc"]
    coverage: SiteCoverage
    reconciliation: SiteReconciliation
    provenance: AnalyticsProvenance
    permissions: AnalyticsPermissions


class StyleIdentity(_StrictModel):
    style_id: str
    style_code: str
    standard_name: str
    status: Literal["enabled", "disabled"]
    sku_count: NonNegativeInt
    color_count: NonNegativeInt
    size_count: NonNegativeInt


class StyleSummary(_StrictModel):
    metrics: MetricValues


class SafeSourceRef(_StrictModel):
    source_ref_id: str
    preview: str
    sha256: str
    is_unsafe: bool
    is_truncated: bool


class StyleVariant(_StrictModel):
    sku_id: str
    standard_color: str
    standard_size: str
    internal_display_sku: str
    status: Literal["enabled", "disabled"]
    seller_sku_aliases: list[SafeSourceRef]
    metrics: MetricValues


class AvailableSeries(_StrictModel):
    key: str
    label: str
    dimension: SeriesDimension
    total: MetricValue
    active: bool
    sort_order: PositiveInt


class TrendSeries(_StrictModel):
    key: str
    points: list[TrendPoint]


class StyleCardResponse(_StrictModel):
    style: StyleIdentity
    summary: StyleSummary
    available_series: list[AvailableSeries]
    series: list[TrendSeries]
    variants: list[StyleVariant]
    effective_return_basis: ReturnBasis
    trend_effective_return_basis: ReturnBasis | None
    source_report_coverage: SourceReportCoverage
    style_reconciliation: StyleReconciliation
    provenance: AnalyticsProvenance
    permissions: AnalyticsPermissions


__all__ = (
    "AnalyticsPermissions",
    "AnalyticsProvenance",
    "AvailableSeries",
    "CoverageBlock",
    "FactBasis",
    "MetricEvaluability",
    "MetricName",
    "MetricTotals",
    "MetricValue",
    "MetricValues",
    "PublicationDay",
    "PublicationRefs",
    "ReturnBasis",
    "SafeSourceRef",
    "SeriesDimension",
    "SiteCoverage",
    "SiteReconciliation",
    "SourceReportCoverage",
    "StyleCardResponse",
    "StyleIdentity",
    "StyleLedgerResponse",
    "StyleLedgerRow",
    "StyleReconciliation",
    "StyleSummary",
    "StyleVariant",
    "TrendPoint",
    "TrendSeries",
)
