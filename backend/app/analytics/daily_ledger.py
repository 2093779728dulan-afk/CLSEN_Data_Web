"""Composition of calendar state and current-publication daily metrics."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Protocol, cast

from app.analytics.models import (
    DailyLedgerResponse,
    DailyLedgerRow,
    DashboardSummary,
    LedgerReason,
    OverallLedgerStatus,
    ReportLedgerStatus,
)

_REPORT_TYPES = ("business_report", "return_report")
_BLOCKING_REASONS = frozenset(
    {"blocking_issues", "failed_import", "file_integrity_error"}
)


class CalendarDayLike(Protocol):
    @property
    def report_date(self) -> date: ...

    @property
    def published_report_types(self) -> Sequence[str]: ...

    @property
    def draft_report_types(self) -> Sequence[str]: ...

    @property
    def reasons(self) -> Sequence[str]: ...


def _report_status(
    report_type: str,
    *,
    future: bool,
    published: set[str],
    drafts: set[str],
    reasons: set[str],
) -> ReportLedgerStatus:
    if future:
        return "future"
    if report_type in published:
        return "published"
    if "file_integrity_error" in reasons or "blocking_issues" in reasons:
        return "blocked"
    if "failed_import" in reasons:
        return "failed"
    if report_type in drafts or "draft" in reasons or "warnings" in reasons:
        return "draft"
    if "processing_import" in reasons:
        return "processing"
    return "missing"


def _overall_status(
    *,
    future: bool,
    published: set[str],
    drafts: set[str],
    reasons: set[str],
) -> OverallLedgerStatus:
    if future:
        return "future"
    if reasons.intersection(_BLOCKING_REASONS):
        return "blocked"
    if len(published) == len(_REPORT_TYPES):
        return "complete"
    if published:
        return "partial"
    if drafts or reasons:
        return "review"
    return "empty"


def _pending_summary(
    overall_status: OverallLedgerStatus,
    business_status: ReportLedgerStatus,
    return_status: ReportLedgerStatus,
) -> str | None:
    if overall_status == "complete":
        return None
    if overall_status == "future":
        return "未来日期"
    if overall_status == "empty":
        return "暂无数据"
    if overall_status == "blocked":
        return "存在阻断，请进入日期处理"  # noqa: RUF001
    missing: list[str] = []
    if business_status != "published":
        missing.append("经营报告")
    if return_status != "published":
        missing.append("退货报告")
    return f"仍需处理：{'、'.join(missing)}" if missing else "仍需处理"  # noqa: RUF001


def compose_daily_ledger(
    summary: DashboardSummary,
    calendar_days: Iterable[CalendarDayLike],
    *,
    today: date,
) -> DailyLedgerResponse:
    """Build one role-safe row per date from one request snapshot."""

    metrics = {metric.report_date: metric for metric in summary.metrics}
    days = {day.report_date: day for day in calendar_days}
    rows: list[DailyLedgerRow] = []
    for ordinal in range(
        summary.range.from_date.toordinal(),
        summary.range.to_date.toordinal() + 1,
    ):
        report_date = date.fromordinal(ordinal)
        day = days[report_date]
        metric = metrics[report_date]
        future = report_date > today
        published = set(day.published_report_types)
        drafts = set(day.draft_report_types)
        raw_reasons = set(day.reasons)
        reasons = cast(list[LedgerReason], list(day.reasons))
        business_status = _report_status(
            "business_report",
            future=future,
            published=published,
            drafts=drafts,
            reasons=raw_reasons,
        )
        return_status = _report_status(
            "return_report",
            future=future,
            published=published,
            drafts=drafts,
            reasons=raw_reasons,
        )
        overall_status = _overall_status(
            future=future,
            published=published,
            drafts=drafts,
            reasons=raw_reasons,
        )
        has_activity = bool(published or drafts or raw_reasons)
        rows.append(
            DailyLedgerRow(
                report_date=report_date,
                business_status=business_status,
                return_status=return_status,
                overall_status=overall_status,
                sales=metric.sales if metric.business_version_id is not None else None,
                units_ordered=(
                    metric.units_ordered
                    if metric.business_version_id is not None
                    else None
                ),
                sessions=(
                    metric.sessions if metric.business_version_id is not None else None
                ),
                conversion_rate=(
                    metric.conversion_rate
                    if metric.business_version_id is not None
                    else None
                ),
                return_quantity=(
                    metric.return_quantity
                    if metric.return_version_id is not None
                    else None
                ),
                pending_summary=_pending_summary(
                    overall_status,
                    business_status,
                    return_status,
                ),
                reasons=reasons,
                counts_as_incomplete=(
                    not future
                    and has_activity
                    and overall_status not in {"complete", "empty"}
                ),
            )
        )
    return DailyLedgerResponse(
        range=summary.range,
        rows=rows,
        publications=summary.publications,
        site_config_versions=summary.site_config_versions,
    )
