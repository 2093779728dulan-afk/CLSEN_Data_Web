"""Date-isolated dataset calendar with viewer-safe visibility rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Literal, cast

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_database_session, require_principal, require_roles
from app.api.errors import ApiError
from app.auth.sessions import Principal

router = APIRouter(prefix="/api/data-calendar", tags=["data-calendar"])
_Principal = Annotated[Principal, Depends(require_principal)]
_SiteReader = Annotated[
    Principal,
    Depends(require_roles("admin", "data_manager", "viewer")),
]
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]
_CalendarStart = Annotated[date, Query(alias="from")]
_CalendarEnd = Annotated[date, Query(alias="to")]

type CalendarStatus = Literal["published", "ready_for_publish", "draft"]
type ReportType = Literal["business_report", "return_report"]
type CalendarDayStatus = Literal["red", "yellow", "blue", "green", "gray"]
type CalendarDayReason = Literal[
    "blocking_issues",
    "failed_import",
    "file_integrity_error",
    "draft",
    "warnings",
    "processing_import",
]

_REPORT_TYPE_ORDER: tuple[ReportType, ...] = (
    "business_report",
    "return_report",
)
_MAX_CALENDAR_DAYS = 366


@dataclass
class _CalendarDay:
    report_date: date
    published_report_types: set[ReportType] = field(default_factory=set)
    draft_report_types: set[ReportType] = field(default_factory=set)
    has_draft: bool = False
    has_blocking_issues: bool = False
    has_warnings: bool = False
    has_failed_import: bool = False
    has_processing_import: bool = False
    has_file_integrity_error: bool = False


def _empty_calendar_day(report_date: date) -> _CalendarDay:
    return _CalendarDay(report_date=report_date)


def _can_review_calendar(principal: Principal) -> bool:
    """Fail closed: only an explicit write role may observe pre-publication state."""

    return bool(principal.roles.intersection({"admin", "data_manager"}))


def _calendar_day_status(day: _CalendarDay) -> CalendarDayStatus:
    if day.has_blocking_issues or day.has_failed_import or day.has_file_integrity_error:
        return "red"
    if day.has_draft or day.has_warnings or day.has_processing_import:
        return "yellow"
    if len(day.published_report_types) == len(_REPORT_TYPE_ORDER):
        return "green"
    if day.published_report_types:
        return "blue"
    return "gray"


def _calendar_day_reasons(day: _CalendarDay) -> list[CalendarDayReason]:
    reasons: list[CalendarDayReason] = []
    if day.has_blocking_issues:
        reasons.append("blocking_issues")
    if day.has_failed_import:
        reasons.append("failed_import")
    if day.has_file_integrity_error:
        reasons.append("file_integrity_error")
    if day.has_draft:
        reasons.append("draft")
    if day.has_warnings:
        reasons.append("warnings")
    if day.has_processing_import:
        reasons.append("processing_import")
    return reasons


def _ordered_report_types(values: set[ReportType]) -> list[ReportType]:
    return [report_type for report_type in _REPORT_TYPE_ORDER if report_type in values]


def _validate_calendar_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise ApiError(422, "invalid_date_range", "from must not be after to")
    if (end_date - start_date).days >= _MAX_CALENDAR_DAYS:
        raise ApiError(
            422,
            "date_range_too_large",
            f"The calendar range must not exceed {_MAX_CALENDAR_DAYS} days.",
        )


class CalendarEntryResponse(BaseModel):
    dataset_id: int
    report_date: date
    report_type: Literal["business_report", "return_report"]
    status: CalendarStatus
    version_id: int
    version_no: int


class CalendarDayResponse(BaseModel):
    report_date: date
    status: CalendarDayStatus
    published_report_types: list[ReportType]
    draft_report_types: list[ReportType]
    reasons: list[CalendarDayReason]


class SiteContextResponse(BaseModel):
    site_id: int
    site_code: str
    display_name: str
    site_config_version_id: int
    source_timezone: str
    reporting_timezone: str
    currency_code: str


@router.get("/site-context", response_model=SiteContextResponse)
def get_site_context(
    _principal: _SiteReader,
    database_session: _DatabaseSession,
) -> SiteContextResponse:
    row = (
        database_session.execute(
            sa.text(
                """
                SELECT sites.id AS site_id, sites.code AS site_code,
                       sites.display_name, configs.id AS config_id,
                       configs.source_timezone, configs.reporting_timezone,
                       configs.currency_code
                FROM sites AS sites
                INNER JOIN site_current_configs AS current_configs
                    ON current_configs.site_id = sites.id
                INNER JOIN site_config_versions AS configs
                    ON configs.site_id = current_configs.site_id
                   AND configs.id = current_configs.current_config_version_id
                WHERE sites.status = 'active'
                ORDER BY sites.id
                LIMIT 1
                """
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ApiError(
            503,
            "site_context_unavailable",
            "The active site configuration is unavailable.",
        )
    return SiteContextResponse(
        site_id=int(row["site_id"]),
        site_code=str(row["site_code"]),
        display_name=str(row["display_name"]),
        site_config_version_id=int(row["config_id"]),
        source_timezone=str(row["source_timezone"]),
        reporting_timezone=str(row["reporting_timezone"]),
        currency_code=str(row["currency_code"]),
    )


@router.get("", response_model=list[CalendarEntryResponse])
def list_calendar_entries(
    principal: _Principal,
    database_session: _DatabaseSession,
    start_date: _CalendarStart,
    end_date: _CalendarEnd,
) -> list[CalendarEntryResponse]:
    _validate_calendar_range(start_date, end_date)
    published_only = not _can_review_calendar(principal)
    rows = database_session.execute(
        sa.text(
            """
            SELECT datasets.id AS dataset_id, datasets.report_date,
                   datasets.report_type, versions.id AS version_id,
                   versions.version_no, versions.status
            FROM daily_datasets AS datasets
            INNER JOIN dataset_versions AS versions
                ON versions.dataset_id = datasets.id
            LEFT JOIN dataset_publications AS publications
                ON publications.dataset_id = datasets.id
               AND publications.version_id = versions.id
            LEFT JOIN dataset_drafts AS drafts
                ON drafts.dataset_id = datasets.id
               AND drafts.version_id = versions.id
            WHERE datasets.report_date BETWEEN :start_date AND :end_date
              AND (
                    (:published_only = TRUE AND publications.version_id IS NOT NULL)
                 OR (:published_only = FALSE AND (
                        publications.version_id IS NOT NULL
                     OR drafts.version_id IS NOT NULL
                 ))
              )
            ORDER BY datasets.report_date, datasets.report_type
            """
        ),
        {
            "start_date": start_date,
            "end_date": end_date,
            "published_only": published_only,
        },
    ).mappings()
    return [
        CalendarEntryResponse(
            dataset_id=int(row["dataset_id"]),
            report_date=row["report_date"],
            report_type=cast(
                Literal["business_report", "return_report"],
                row["report_type"],
            ),
            status=cast(
                CalendarStatus,
                "published"
                if published_only or row["status"] == "published"
                else row["status"],
            ),
            version_id=int(row["version_id"]),
            version_no=int(row["version_no"]),
        )
        for row in rows
    ]


@router.get("/days", response_model=list[CalendarDayResponse])
def list_calendar_days(
    principal: _Principal,
    database_session: _DatabaseSession,
    start_date: _CalendarStart,
    end_date: _CalendarEnd,
) -> list[CalendarDayResponse]:
    """Return one safe, priority-ordered status for every requested date.

    View-only and role-less accounts are deliberately restricted to publication
    pointers.  Draft, validation, import, and file-integrity signals are queried
    only for principals with an explicit write role.
    """

    _validate_calendar_range(start_date, end_date)

    days = {
        date.fromordinal(ordinal): _empty_calendar_day(date.fromordinal(ordinal))
        for ordinal in range(start_date.toordinal(), end_date.toordinal() + 1)
    }
    publication_rows = database_session.execute(
        sa.text(
            """
            SELECT datasets.report_date, datasets.report_type
            FROM daily_datasets AS datasets
            INNER JOIN dataset_publications AS publications
                ON publications.dataset_id = datasets.id
            WHERE datasets.report_date BETWEEN :start_date AND :end_date
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings()
    for row in publication_rows:
        report_date = cast(date, row["report_date"])
        days[report_date].published_report_types.add(
            cast(ReportType, row["report_type"])
        )

    if _can_review_calendar(principal):
        _add_reviewer_calendar_signals(
            database_session,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )

    return [
        CalendarDayResponse(
            report_date=day.report_date,
            status=_calendar_day_status(day),
            published_report_types=_ordered_report_types(day.published_report_types),
            draft_report_types=_ordered_report_types(day.draft_report_types),
            reasons=_calendar_day_reasons(day),
        )
        for day in days.values()
    ]


def _add_reviewer_calendar_signals(
    database_session: Session,
    *,
    days: dict[date, _CalendarDay],
    start_date: date,
    end_date: date,
) -> None:
    parameters = {"start_date": start_date, "end_date": end_date}
    draft_rows = database_session.execute(
        sa.text(
            """
            SELECT datasets.report_date, datasets.report_type
            FROM daily_datasets AS datasets
            INNER JOIN dataset_drafts AS drafts
                ON drafts.dataset_id = datasets.id
            WHERE datasets.report_date BETWEEN :start_date AND :end_date
            """
        ),
        parameters,
    ).mappings()
    for row in draft_rows:
        day = days[cast(date, row["report_date"])]
        day.has_draft = True
        day.draft_report_types.add(cast(ReportType, row["report_type"]))

    validation_rows = database_session.execute(
        sa.text(
            """
            WITH ranked_runs AS (
                SELECT runs.id, runs.version_id, runs.data_revision,
                       ROW_NUMBER() OVER (
                           PARTITION BY runs.version_id
                           ORDER BY runs.id DESC
                       ) AS run_rank
                FROM validation_runs AS runs
                WHERE runs.run_type = 'full'
            ),
            ranked_reviews AS (
                SELECT reviews.version_id, reviews.validation_run_id,
                       reviews.validation_issue_id, reviews.event_type,
                       ROW_NUMBER() OVER (
                           PARTITION BY reviews.version_id,
                                        reviews.validation_run_id,
                                        reviews.validation_issue_id
                           ORDER BY reviews.sequence_number DESC,
                                    reviews.id DESC
                       ) AS review_rank
                FROM issue_review_events AS reviews
            )
            SELECT datasets.report_date,
                   MAX(CASE
                       WHEN issues.severity = 'blocking'
                        AND COALESCE(reviews.event_type, 'open') <> 'resolve'
                       THEN 1 ELSE 0
                   END) AS has_blocking_issues,
                   MAX(CASE
                       WHEN issues.severity = 'warning'
                        AND COALESCE(reviews.event_type, 'open') <> 'acknowledge'
                       THEN 1 ELSE 0
                   END) AS has_warnings
            FROM daily_datasets AS datasets
            INNER JOIN dataset_drafts AS drafts
                ON drafts.dataset_id = datasets.id
            INNER JOIN dataset_versions AS versions
                ON versions.id = drafts.version_id
               AND versions.dataset_id = drafts.dataset_id
            LEFT JOIN ranked_runs AS runs
                ON runs.version_id = versions.id
               AND runs.data_revision = versions.data_revision
               AND runs.run_rank = 1
            LEFT JOIN validation_issues AS issues
                ON issues.version_id = versions.id
               AND issues.validation_run_id = runs.id
            LEFT JOIN ranked_reviews AS reviews
                ON reviews.version_id = issues.version_id
               AND reviews.validation_run_id = issues.validation_run_id
               AND reviews.validation_issue_id = issues.id
               AND reviews.review_rank = 1
            WHERE datasets.report_date BETWEEN :start_date AND :end_date
            GROUP BY datasets.report_date
            """
        ),
        parameters,
    ).mappings()
    for row in validation_rows:
        day = days[cast(date, row["report_date"])]
        day.has_blocking_issues = bool(row["has_blocking_issues"])
        day.has_warnings = bool(row["has_warnings"])

    import_rows = database_session.execute(
        sa.text(
            """
            SELECT batches.report_date,
                   MAX(CASE
                        WHEN batches.status = 'processing_failed'
                         AND NOT EXISTS (
                             SELECT 1
                             FROM daily_datasets AS recovered
                             INNER JOIN dataset_publications AS published
                                 ON published.dataset_id = recovered.id
                             INNER JOIN version_input_batches AS replacement_inputs
                                 ON replacement_inputs.version_id = published.version_id
                             INNER JOIN import_batches AS replacement
                                 ON replacement.id = replacement_inputs.batch_id
                             WHERE recovered.site_id = batches.site_id
                               AND recovered.report_date = batches.report_date
                               AND recovered.report_type =
                                   batches.confirmed_report_type
                               AND replacement.created_at > batches.created_at
                         )
                       THEN 1 ELSE 0
                   END) AS has_failed_import,
                   MAX(CASE
                       WHEN batches.status IN ('uploaded', 'processing')
                       THEN 1 ELSE 0
                   END) AS has_processing_import,
                   MAX(CASE
                       WHEN integrity.status IS NOT NULL
                        AND integrity.status <> 'available'
                       THEN 1 ELSE 0
                   END) AS has_file_integrity_error
            FROM import_batches AS batches
            LEFT JOIN raw_file_integrity_statuses AS integrity
                ON integrity.raw_file_id = batches.raw_file_id
            WHERE batches.report_date BETWEEN :start_date AND :end_date
              AND batches.confirmed_at IS NOT NULL
              AND batches.confirmed_report_type IS NOT NULL
            GROUP BY batches.report_date
            """
        ),
        parameters,
    ).mappings()
    for row in import_rows:
        day = days[cast(date, row["report_date"])]
        day.has_failed_import = bool(row["has_failed_import"])
        day.has_processing_import = bool(row["has_processing_import"])
        day.has_file_integrity_error = bool(row["has_file_integrity_error"])

    current_version_integrity_rows = database_session.execute(
        sa.text(
            """
            WITH current_versions AS (
                SELECT dataset_id, version_id FROM dataset_drafts
                UNION ALL
                SELECT dataset_id, version_id FROM dataset_publications
            )
            SELECT datasets.report_date,
                   MAX(CASE
                       WHEN integrity.status <> 'available' THEN 1 ELSE 0
                   END) AS has_file_integrity_error
            FROM daily_datasets AS datasets
            INNER JOIN current_versions
                ON current_versions.dataset_id = datasets.id
            INNER JOIN version_input_batches AS inputs
                ON inputs.version_id = current_versions.version_id
            INNER JOIN import_batches AS batches
                ON batches.id = inputs.batch_id
            INNER JOIN raw_file_integrity_statuses AS integrity
                ON integrity.raw_file_id = batches.raw_file_id
            WHERE datasets.report_date BETWEEN :start_date AND :end_date
            GROUP BY datasets.report_date
            """
        ),
        parameters,
    ).mappings()
    for row in current_version_integrity_rows:
        day = days[cast(date, row["report_date"])]
        day.has_file_integrity_error = day.has_file_integrity_error or bool(
            row["has_file_integrity_error"]
        )
