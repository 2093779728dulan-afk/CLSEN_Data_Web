from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.analytics.daily_ledger import compose_daily_ledger
from app.analytics.models import DashboardMetric, DashboardSummary, DateRange


def _summary() -> DashboardSummary:
    return DashboardSummary(
        range=DateRange(from_date=date(2026, 8, 13), to_date=date(2026, 8, 15)),
        metrics=[
            DashboardMetric(
                report_date=date(2026, 8, 13),
                sales="12.50",
                units_ordered=2,
                sessions=10,
                conversion_rate="0.2",
                return_quantity=0,
                business_version_id=11,
                return_version_id=None,
            ),
            DashboardMetric(
                report_date=date(2026, 8, 14),
                sales="0",
                units_ordered=0,
                sessions=0,
                conversion_rate=None,
                return_quantity=0,
                business_version_id=None,
                return_version_id=None,
            ),
            DashboardMetric(
                report_date=date(2026, 8, 15),
                sales="0",
                units_ordered=0,
                sessions=0,
                conversion_rate=None,
                return_quantity=0,
                business_version_id=None,
                return_version_id=None,
            ),
        ],
        publications=[],
        site_config_versions=[],
    )


def test_daily_ledger_distinguishes_partial_empty_and_future_dates() -> None:
    result = compose_daily_ledger(
        _summary(),
        [
            SimpleNamespace(
                report_date=date(2026, 8, 13),
                published_report_types=["business_report"],
                draft_report_types=[],
                reasons=[],
            ),
            SimpleNamespace(
                report_date=date(2026, 8, 14),
                published_report_types=[],
                draft_report_types=[],
                reasons=[],
            ),
            SimpleNamespace(
                report_date=date(2026, 8, 15),
                published_report_types=[],
                draft_report_types=[],
                reasons=[],
            ),
        ],
        today=date(2026, 8, 14),
    )

    partial, empty, future = result.rows
    assert partial.overall_status == "partial"
    assert partial.sales == "12.50"
    assert partial.return_quantity is None
    assert partial.counts_as_incomplete is True
    assert empty.overall_status == "empty"
    assert empty.sales is None
    assert empty.counts_as_incomplete is False
    assert future.overall_status == "future"
    assert future.counts_as_incomplete is False


def test_daily_ledger_prioritizes_blockers_without_hiding_published_values() -> None:
    summary = _summary().model_copy(
        update={
            "range": DateRange(
                from_date=date(2026, 8, 13),
                to_date=date(2026, 8, 13),
            ),
            "metrics": [_summary().metrics[0]],
        }
    )
    result = compose_daily_ledger(
        summary,
        [
            SimpleNamespace(
                report_date=date(2026, 8, 13),
                published_report_types=["business_report"],
                draft_report_types=["return_report"],
                reasons=["blocking_issues"],
            )
        ],
        today=date(2026, 8, 14),
    )

    row = result.rows[0]
    assert row.overall_status == "blocked"
    assert row.business_status == "published"
    assert row.return_status == "blocked"
    assert row.reasons == ["blocking_issues"]
