from __future__ import annotations

from datetime import date

import pytest
from app.analytics.style_repository import MySqlStyleAnalyticsRepository

from tests.integration.test_style_analytics import (
    ApprovedStyleAnalyticsCase,
    _dataset_case,  # noqa: F401
    _publication_case,  # noqa: F401
    catalog_approval_case_fixture,  # noqa: F401
    style_analytics_case_fixture,  # noqa: F401
)

pytestmark = pytest.mark.mysql


def test_event_date_includes_contributing_publication_outside_report_date_band(
    style_analytics_case: ApprovedStyleAnalyticsCase,
) -> None:
    response = MySqlStyleAnalyticsRepository(style_analytics_case.engine).ledger(
        site_id=1,
        from_date=date(2026, 7, 31),
        to_date=date(2026, 8, 1),
        return_basis="event_date",
    )

    assert response.coverage.returns.published_days == 0
    assert response.reconciliation.metric_status.returns == "evaluable"
    assert response.reconciliation.source_totals.returns == 3
    assert response.provenance.publication_refs.members[-1].report_date > date(
        2026, 8, 1
    )
    assert response.rows[0].metrics.returns.source_completeness == "indeterminate"


def test_size_series_reconciles_to_selected_color_not_whole_style(
    style_analytics_case: ApprovedStyleAnalyticsCase,
) -> None:
    repository = MySqlStyleAnalyticsRepository(style_analytics_case.engine)
    ledger = repository.ledger(
        site_id=1,
        from_date=date(2026, 8, 22),
        to_date=date(2026, 8, 22),
        return_basis="report_date",
    )
    style_id = int(ledger.rows[0].style_id)
    colors = repository.card(
        site_id=1,
        style_id=style_id,
        from_date=date(2026, 8, 22),
        to_date=date(2026, 8, 22),
        dimension="color",
        return_basis="report_date",
    )
    selected_color = colors.available_series[0].key

    sizes = repository.card(
        site_id=1,
        style_id=style_id,
        from_date=date(2026, 8, 22),
        to_date=date(2026, 8, 22),
        dimension="size",
        color_key=selected_color,
        return_basis="report_date",
    )

    assert sizes.style_reconciliation.series_scope == "selected_color"
    assert sizes.style_reconciliation.selected_color_totals is not None
    assert sizes.style_reconciliation.series_scope_totals == (
        sizes.style_reconciliation.selected_color_totals
    )
