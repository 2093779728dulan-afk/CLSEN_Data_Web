from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import cast
from unittest.mock import MagicMock

import pytest
from app.analytics.style_models import (
    AnalyticsPermissions,
    MetricTotals,
    StyleLedgerResponse,
)
from app.analytics.style_service import (
    CoverageFacts,
    MetricAggregate,
    ReconciliationError,
    StyleAnalyticsService,
    StyleLedgerQuery,
    build_metric_values,
    build_site_reconciliation,
    build_style_reconciliation,
    build_trend_point,
    stable_series_key,
)


def _permissions() -> AnalyticsPermissions:
    return AnalyticsPermissions(
        can_view_catalog_history=False,
        can_manage_catalog=False,
        can_view_evidence_history=False,
        can_download_original=False,
        can_submit=False,
        can_approve_normal=False,
        can_approve_high_risk=False,
    )


def test_application_service_delegates_the_complete_query_without_aggregation() -> None:
    repository = MagicMock()
    expected = cast(StyleLedgerResponse, object())
    repository.ledger.return_value = expected
    query = StyleLedgerQuery(
        site_id=4,
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 2),
        search="approved",
        category_id=12,
        sort="sales",
        direction="asc",
        page=2,
        page_size=25,
        catalog_version_id=9,
        fact_basis="catalog_snapshot",
        return_basis="report_date",
    )

    assert (
        StyleAnalyticsService(repository).style_ledger(
            query, permissions=_permissions()
        )
        is expected
    )
    repository.ledger.assert_called_once_with(
        site_id=4,
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 2),
        search="approved",
        category_id=12,
        sort="sales",
        direction="asc",
        page=2,
        page_size=25,
        catalog_version_id=9,
        fact_basis="catalog_snapshot",
        return_basis="report_date",
        permissions=_permissions(),
    )


def test_range_metric_matrix_keeps_negative_values_and_exact_conversion() -> None:
    metrics = build_metric_values(
        MetricAggregate(
            units=-3,
            sales=Decimal("-12.505"),
            returns=2,
            sessions=2,
            business_fact_rows=1,
            return_fact_rows=1,
        ),
        business_coverage=CoverageFacts(expected_days=2, observed_days=1),
        return_coverage=CoverageFacts(expected_days=2, observed_days=1),
        return_basis="report_date",
        unresolved_return_rows=0,
    )

    assert metrics.units.value == -3
    assert metrics.sales.value == "-12.51"
    assert metrics.sessions.value == 2
    assert metrics.conversion.value == "-1.500000"
    assert metrics.conversion.numerator == -3
    assert metrics.conversion.denominator == 2
    assert metrics.units.is_partial is True
    assert metrics.returns.value == 2


def test_range_metric_matrix_distinguishes_no_reports_and_event_date_zero() -> None:
    no_reports = CoverageFacts(expected_days=2, observed_days=0)
    aggregate = MetricAggregate()

    report_date = build_metric_values(
        aggregate,
        business_coverage=no_reports,
        return_coverage=no_reports,
        return_basis="report_date",
        unresolved_return_rows=0,
    )
    event_date = build_metric_values(
        aggregate,
        business_coverage=no_reports,
        return_coverage=no_reports,
        return_basis="event_date",
        unresolved_return_rows=0,
    )

    assert report_date.units.value is None
    assert report_date.units.null_reason == "no_observed_reports"
    assert report_date.conversion.numerator is None
    assert report_date.returns.value is None
    assert event_date.returns.value == 0
    assert event_date.returns.value_state == "zero"
    assert event_date.returns.source_completeness == "indeterminate"


def test_daily_matrix_distinguishes_observed_zero_missing_and_undefined() -> None:
    observed = build_trend_point(
        report_date=date(2026, 8, 1),
        metric="units",
        value=-1,
        contributing_rows=2,
        report_published=True,
        return_basis="report_date",
    )
    zero = build_trend_point(
        report_date=date(2026, 8, 1),
        metric="sales",
        value=Decimal(0),
        contributing_rows=0,
        report_published=True,
        return_basis="report_date",
    )
    missing = build_trend_point(
        report_date=date(2026, 8, 1),
        metric="returns",
        value=0,
        contributing_rows=0,
        report_published=False,
        return_basis="report_date",
    )
    undefined = build_trend_point(
        report_date=date(2026, 8, 1),
        metric="conversion",
        value=None,
        contributing_rows=1,
        report_published=True,
        return_basis="report_date",
        numerator=4,
        denominator=0,
    )

    assert (observed.value_state, observed.value) == ("observed", -1)
    assert (zero.value_state, zero.value) == ("zero", "0.00")
    assert (missing.value_state, missing.null_reason) == (
        "missing_report",
        "missing_report",
    )
    assert (undefined.value_state, undefined.null_reason) == (
        "undefined_denominator",
        "undefined_denominator",
    )
    assert (undefined.numerator, undefined.denominator) == (4, 0)


def _totals(
    units: int | None,
    sales: str | None,
    returns: int | None,
    sessions: int | None,
) -> MetricTotals:
    return MetricTotals(
        units=units,
        sales=sales,
        returns=returns,
        sessions=sessions,
        conversion_numerator=units,
        conversion_denominator=sessions,
    )


def test_six_bucket_reconciliation_and_business_not_applicable_buckets() -> None:
    reconciliation = build_site_reconciliation(
        source=_totals(10, "100.00", 9, 20),
        mapped=_totals(7, "70.00", 4, 14),
        unmatched=_totals(2, "20.00", 1, 4),
        excluded=_totals(1, "10.00", 1, 2),
        duplicate=_totals(None, None, 2, None),
        unresolved=_totals(None, None, 1, None),
    )

    assert reconciliation.metric_status.model_dump() == {
        "units": "evaluable",
        "sales": "evaluable",
        "returns": "evaluable",
        "sessions": "evaluable",
        "conversion": "evaluable",
    }
    with pytest.raises(ReconciliationError):
        build_site_reconciliation(
            source=_totals(11, "100.00", 9, 20),
            mapped=_totals(7, "70.00", 4, 14),
            unmatched=_totals(2, "20.00", 1, 4),
            excluded=_totals(1, "10.00", 1, 2),
            duplicate=_totals(None, None, 2, None),
            unresolved=_totals(None, None, 1, None),
        )


def test_style_reconciliation_uses_selected_color_for_size_dimension() -> None:
    whole_style = _totals(10, "100.00", 2, 20)
    selected_color = _totals(6, "60.00", 1, 12)

    result = build_style_reconciliation(
        summary=whole_style,
        variants=whole_style,
        series=selected_color,
        dimension="size",
        selected_color=selected_color,
    )

    assert result.series_scope == "selected_color"
    assert result.series_scope_totals == selected_color
    with pytest.raises(ReconciliationError):
        build_style_reconciliation(
            summary=whole_style,
            variants=whole_style,
            series=whole_style,
            dimension="size",
            selected_color=selected_color,
        )


def test_stable_series_key_is_full_unpadded_base64url_and_dimension_scoped() -> None:
    color = stable_series_key(
        catalog_version_id=9,
        style_id=12,
        dimension="color",
        normalized_value=b"black",
    )
    size = stable_series_key(
        catalog_version_id=9,
        style_id=12,
        dimension="size",
        normalized_value=b"m",
        normalized_color=b"black",
    )

    assert len(color) == 43 and "=" not in color
    assert len(size) == 43 and size != color
