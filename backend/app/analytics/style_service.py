"""Exact metric-state and reconciliation logic for stable style analytics."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, Protocol, cast

from app.analytics.style_models import (
    AnalyticsPermissions,
    FactBasis,
    MetricEvaluability,
    MetricName,
    MetricTotals,
    MetricValue,
    MetricValues,
    ReturnBasis,
    SeriesDimension,
    SiteReconciliation,
    StyleCardResponse,
    StyleLedgerResponse,
    StyleReconciliation,
    TrendPoint,
)

_MONEY_QUANTUM = Decimal("0.01")
_RATIO_QUANTUM = Decimal("0.000001")


class ReconciliationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StyleLedgerQuery:
    site_id: int
    from_date: date
    to_date: date
    category_id: int | None = None
    search: str | None = None
    sort: Literal[
        "style_code",
        "standard_name",
        "units",
        "sales",
        "returns",
        "sessions",
        "conversion",
    ] = "units"
    direction: Literal["asc", "desc"] = "desc"
    page: int = 1
    page_size: int = 50
    catalog_version_id: int | None = None
    fact_basis: FactBasis = "current"
    return_basis: ReturnBasis = "event_date"


@dataclass(frozen=True, slots=True)
class StyleCardQuery:
    site_id: int
    style_id: int
    from_date: date
    to_date: date
    metric: MetricName = "units"
    dimension: SeriesDimension = "color"
    color_key: str | None = None
    series: Sequence[str] | None = None
    catalog_version_id: int | None = None
    fact_basis: FactBasis = "current"
    return_basis: ReturnBasis = "event_date"


class StyleAnalyticsRepository(Protocol):
    def ledger(self, **kwargs: Any) -> StyleLedgerResponse: ...

    def card(self, **kwargs: Any) -> StyleCardResponse: ...


class StyleAnalyticsService:
    """Thin application service shared by the HTTP layer and integration jobs."""

    def __init__(self, repository: StyleAnalyticsRepository) -> None:
        self._repository = repository

    def style_ledger(
        self,
        query: StyleLedgerQuery,
        *,
        permissions: AnalyticsPermissions,
    ) -> StyleLedgerResponse:
        return self._repository.ledger(
            site_id=query.site_id,
            from_date=query.from_date,
            to_date=query.to_date,
            search=query.search,
            category_id=query.category_id,
            sort=query.sort,
            direction=query.direction,
            page=query.page,
            page_size=query.page_size,
            catalog_version_id=query.catalog_version_id,
            fact_basis=query.fact_basis,
            return_basis=query.return_basis,
            permissions=permissions,
        )

    def style_card(
        self,
        query: StyleCardQuery,
        *,
        permissions: AnalyticsPermissions,
    ) -> StyleCardResponse:
        return self._repository.card(
            site_id=query.site_id,
            style_id=query.style_id,
            from_date=query.from_date,
            to_date=query.to_date,
            metric=query.metric,
            dimension=query.dimension,
            color_key=query.color_key,
            series=query.series,
            catalog_version_id=query.catalog_version_id,
            fact_basis=query.fact_basis,
            return_basis=query.return_basis,
            permissions=permissions,
        )


@dataclass(frozen=True, slots=True)
class CoverageFacts:
    expected_days: int
    observed_days: int

    def __post_init__(self) -> None:
        if self.expected_days < 1 or not 0 <= self.observed_days <= self.expected_days:
            raise ValueError("invalid coverage facts")

    @property
    def is_partial(self) -> bool:
        return self.observed_days < self.expected_days

    @property
    def completeness(self) -> str:
        return "partial" if self.is_partial else "complete"


@dataclass(frozen=True, slots=True)
class MetricAggregate:
    units: int = 0
    sales: Decimal = Decimal(0)
    returns: int = 0
    sessions: int = 0
    business_fact_rows: int = 0
    return_fact_rows: int = 0

    def __post_init__(self) -> None:
        if self.returns < 0:
            raise ValueError("return quantity must be nonnegative")
        if self.business_fact_rows < 0 or self.return_fact_rows < 0:
            raise ValueError("fact row counts must be nonnegative")


def money_text(value: Decimal | int | str) -> str:
    return format(Decimal(value).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP), "f")


def ratio_text(numerator: int, denominator: int) -> str | None:
    if denominator <= 0:
        return None
    return format(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            _RATIO_QUANTUM,
            rounding=ROUND_HALF_UP,
        ),
        "f",
    )


def rate_text(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    if not 0 <= numerator <= denominator:
        raise ValueError("coverage rate operands are invalid")
    return ratio_text(numerator, denominator)


def _range_additive(
    *,
    value: int | Decimal,
    fact_rows: int,
    coverage: CoverageFacts,
    formatter: object | None = None,
    event_date_returns: bool = False,
    unresolved: bool = False,
) -> MetricValue:
    completeness = "indeterminate" if event_date_returns else coverage.completeness
    partial = coverage.is_partial or unresolved
    if coverage.observed_days == 0 and not event_date_returns:
        return MetricValue(
            value=None,
            value_state="missing_report",
            null_reason="no_observed_reports",
            is_partial=True,
            observed_days=0,
            expected_days=coverage.expected_days,
            source_completeness="partial",
            numerator=None,
            denominator=None,
        )
    rendered: int | str = money_text(value) if formatter is money_text else int(value)
    return MetricValue(
        value=rendered,
        value_state="observed" if fact_rows > 0 else "zero",
        null_reason=None,
        is_partial=partial,
        observed_days=coverage.observed_days,
        expected_days=coverage.expected_days,
        source_completeness=completeness,  # type: ignore[arg-type]
        numerator=None,
        denominator=None,
    )


def _range_conversion(
    aggregate: MetricAggregate,
    coverage: CoverageFacts,
) -> MetricValue:
    if coverage.observed_days == 0:
        return MetricValue(
            value=None,
            value_state="missing_report",
            null_reason="no_observed_reports",
            is_partial=True,
            observed_days=0,
            expected_days=coverage.expected_days,
            source_completeness="partial",
            numerator=None,
            denominator=None,
        )
    value = ratio_text(aggregate.units, aggregate.sessions)
    return MetricValue(
        value=value,
        value_state=("observed" if value is not None else "undefined_denominator"),
        null_reason=None if value is not None else "undefined_denominator",
        is_partial=coverage.is_partial,
        observed_days=coverage.observed_days,
        expected_days=coverage.expected_days,
        source_completeness=coverage.completeness,  # type: ignore[arg-type]
        numerator=aggregate.units,
        denominator=aggregate.sessions,
    )


def build_metric_values(
    aggregate: MetricAggregate,
    *,
    business_coverage: CoverageFacts,
    return_coverage: CoverageFacts,
    return_basis: ReturnBasis,
    unresolved_return_rows: int,
) -> MetricValues:
    if unresolved_return_rows < 0:
        raise ValueError("unresolved row count must be nonnegative")
    return MetricValues(
        units=_range_additive(
            value=aggregate.units,
            fact_rows=aggregate.business_fact_rows,
            coverage=business_coverage,
        ),
        sales=_range_additive(
            value=aggregate.sales,
            fact_rows=aggregate.business_fact_rows,
            coverage=business_coverage,
            formatter=money_text,
        ),
        returns=_range_additive(
            value=aggregate.returns,
            fact_rows=aggregate.return_fact_rows,
            coverage=return_coverage,
            event_date_returns=return_basis == "event_date",
            unresolved=unresolved_return_rows > 0,
        ),
        sessions=_range_additive(
            value=aggregate.sessions,
            fact_rows=aggregate.business_fact_rows,
            coverage=business_coverage,
        ),
        conversion=_range_conversion(aggregate, business_coverage),
    )


def build_trend_point(
    *,
    report_date: date,
    metric: MetricName,
    value: int | Decimal | None,
    contributing_rows: int,
    report_published: bool,
    return_basis: ReturnBasis,
    numerator: int | None = None,
    denominator: int | None = None,
) -> TrendPoint:
    if contributing_rows < 0:
        raise ValueError("contributing rows must be nonnegative")
    event_return = metric == "returns" and return_basis == "event_date"
    completeness = (
        "indeterminate"
        if event_return
        else ("complete" if report_published else "partial")
    )
    if not report_published and not event_return:
        return TrendPoint(
            date=report_date,
            value=None,
            value_state="missing_report",
            null_reason="missing_report",
            source_completeness="partial",
            numerator=None,
            denominator=None,
        )
    if metric == "conversion":
        if numerator is None or denominator is None:
            raise ValueError("conversion trend requires operands")
        rendered = ratio_text(numerator, denominator)
        return TrendPoint(
            date=report_date,
            value=rendered,
            value_state=(
                "observed" if rendered is not None else "undefined_denominator"
            ),
            null_reason=(None if rendered is not None else "undefined_denominator"),
            source_completeness=completeness,  # type: ignore[arg-type]
            numerator=numerator,
            denominator=denominator,
        )
    if value is None:
        raise ValueError("additive trend requires a value")
    rendered_value: int | str = money_text(value) if metric == "sales" else int(value)
    return TrendPoint(
        date=report_date,
        value=rendered_value,
        value_state="observed" if contributing_rows > 0 else "zero",
        null_reason=None,
        source_completeness=completeness,  # type: ignore[arg-type]
        numerator=None,
        denominator=None,
    )


def _status(
    values: list[object | None],
    *,
    not_applicable_tail: int = 0,
) -> str:
    if all(value is None for value in values):
        return "not_evaluable"
    evaluable = values[:-not_applicable_tail] if not_applicable_tail else values
    tail = values[-not_applicable_tail:] if not_applicable_tail else []
    if any(value is None for value in evaluable) or any(
        value is not None for value in tail
    ):
        raise ReconciliationError("metric buckets mix evaluability states")
    return "evaluable"


def _sum_equal(source: int | str, parts: list[int | str]) -> bool:
    if isinstance(source, str):
        return Decimal(source) == sum(
            (Decimal(str(value)) for value in parts),
            Decimal(0),
        )
    return source == sum(int(value) for value in parts)


def build_site_reconciliation(
    *,
    source: MetricTotals,
    mapped: MetricTotals,
    unmatched: MetricTotals,
    excluded: MetricTotals,
    duplicate: MetricTotals,
    unresolved: MetricTotals,
) -> SiteReconciliation:
    buckets = [mapped, unmatched, excluded, duplicate, unresolved]
    statuses: dict[str, str] = {}
    for field in ("units", "sales", "returns", "sessions"):
        source_value = getattr(source, field)
        values = [getattr(bucket, field) for bucket in buckets]
        not_applicable_tail = 0 if field == "returns" else 2
        statuses[field] = _status(
            [source_value, *values],
            not_applicable_tail=not_applicable_tail,
        )
        if statuses[field] == "evaluable":
            applicable = cast(
                list[int | str],
                [value for value in values if value is not None],
            )
            if source_value is None or not _sum_equal(
                cast(int | str, source_value), applicable
            ):
                raise ReconciliationError(f"{field} buckets do not reconcile")
    conversion_values: list[object | None] = []
    for totals in [source, *buckets]:
        conversion_values.extend(
            [totals.conversion_numerator, totals.conversion_denominator]
        )
    statuses["conversion"] = _status(
        conversion_values,
        not_applicable_tail=4,
    )
    if statuses["conversion"] == "evaluable":
        for field in ("conversion_numerator", "conversion_denominator"):
            source_value = getattr(source, field)
            values = [getattr(bucket, field) for bucket in buckets]
            applicable = cast(
                list[int | str],
                [value for value in values if value is not None],
            )
            if source_value is None or not _sum_equal(
                cast(int | str, source_value), applicable
            ):
                raise ReconciliationError(f"{field} buckets do not reconcile")
    return SiteReconciliation(
        metric_status=MetricEvaluability(**statuses),  # type: ignore[arg-type]
        source_totals=source,
        mapped_totals=mapped,
        unmatched_totals=unmatched,
        excluded_totals=excluded,
        duplicate_totals=duplicate,
        unresolved_duplicate_totals=unresolved,
    )


def _metric_status(totals: MetricTotals) -> MetricEvaluability:
    return MetricEvaluability(
        units="evaluable" if totals.units is not None else "not_evaluable",
        sales="evaluable" if totals.sales is not None else "not_evaluable",
        returns="evaluable" if totals.returns is not None else "not_evaluable",
        sessions="evaluable" if totals.sessions is not None else "not_evaluable",
        conversion=(
            "evaluable" if totals.conversion_numerator is not None else "not_evaluable"
        ),
    )


def build_style_reconciliation(
    *,
    summary: MetricTotals,
    variants: MetricTotals,
    series: MetricTotals,
    dimension: SeriesDimension,
    selected_color: MetricTotals | None,
) -> StyleReconciliation:
    if summary != variants:
        raise ReconciliationError("summary and variants do not reconcile")
    if dimension == "size":
        if selected_color is None or series != selected_color:
            raise ReconciliationError("size series must equal the selected color")
        scope: Literal["style", "selected_color"] = "selected_color"
    else:
        if selected_color is not None or series != summary:
            raise ReconciliationError("whole-style series do not reconcile")
        scope = "style"
    return StyleReconciliation(
        metric_status=_metric_status(summary),
        series_scope=scope,
        summary_totals=summary,
        variant_totals=variants,
        series_scope_totals=series,
        selected_color_totals=selected_color,
    )


def stable_series_key(
    *,
    catalog_version_id: int,
    style_id: int,
    dimension: SeriesDimension,
    normalized_value: bytes,
    normalized_color: bytes | None = None,
) -> str:
    if catalog_version_id < 1 or style_id < 1 or not normalized_value:
        raise ValueError("series key tuple is invalid")
    if dimension == "size" and not normalized_color:
        raise ValueError("size series requires a color")
    if dimension != "size" and normalized_color is not None:
        raise ValueError("only size series accepts a color")
    payload = (
        str(catalog_version_id).encode("ascii")
        + b"\0"
        + str(style_id).encode("ascii")
        + b"\0"
        + dimension.encode("ascii")
        + b"\0"
        + normalized_value
    )
    if normalized_color is not None:
        payload += b"\0" + normalized_color
    return (
        base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
        .rstrip(b"=")
        .decode("ascii")
    )


__all__ = (
    "CoverageFacts",
    "MetricAggregate",
    "ReconciliationError",
    "StyleAnalyticsService",
    "StyleCardQuery",
    "StyleLedgerQuery",
    "build_metric_values",
    "build_site_reconciliation",
    "build_style_reconciliation",
    "build_trend_point",
    "money_text",
    "rate_text",
    "ratio_text",
    "stable_series_key",
)
