from __future__ import annotations

from decimal import Decimal

import pytest
from app.analytics.style_repository import MySqlStyleAnalyticsRepository

from tests.integration.test_style_analytics import (
    REPORT_DATE,
    ApprovedStyleAnalyticsCase,
    _dataset_case,  # noqa: F401
    _publication_case,  # noqa: F401
    catalog_approval_case_fixture,  # noqa: F401
    style_analytics_case_fixture,  # noqa: F401
)

pytestmark = pytest.mark.mysql


def _sum(values: list[int | Decimal | None]) -> int | Decimal:
    return sum((value for value in values if value is not None), start=0)


def test_fixed_fact_tuple_has_zero_unexplained_metric_differences(
    style_analytics_case: ApprovedStyleAnalyticsCase,
) -> None:
    response = MySqlStyleAnalyticsRepository(style_analytics_case.engine).ledger(
        site_id=1,
        from_date=REPORT_DATE,
        to_date=REPORT_DATE,
        return_basis="report_date",
    )
    totals = response.reconciliation
    assert totals.source_totals.units == _sum(
        [
            totals.mapped_totals.units,
            totals.unmatched_totals.units,
            totals.excluded_totals.units,
        ]
    )
    assert totals.source_totals.returns == _sum(
        [
            totals.mapped_totals.returns,
            totals.unmatched_totals.returns,
            totals.excluded_totals.returns,
            totals.duplicate_totals.returns,
            totals.unresolved_duplicate_totals.returns,
        ]
    )
    assert all(
        status in {"evaluable", "not_evaluable"}
        for status in totals.metric_status.model_dump().values()
    )
