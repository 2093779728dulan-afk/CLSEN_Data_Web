"""Published-only dashboard HTTP routes with stable, redacted contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Never
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.analytics.daily_ledger import compose_daily_ledger
from app.analytics.errors import (
    AnalyticsDateRangeTooLarge,
    InvalidAnalyticsDateRange,
    InvalidReturnBasis,
    InvalidSiteConfiguration,
    MissingSiteConfiguration,
)
from app.analytics.models import (
    DailyLedgerResponse,
    DashboardSummary,
    ProductCardResponse,
    ProductDashboard,
    ProductLedgerResponse,
    ProductLedgerSort,
    ReturnDashboard,
    SortDirection,
)
from app.analytics.product_ledger import ProductLedgerQueryService
from app.analytics.service import (
    MAX_ANALYTICS_DATE_RANGE_DAYS,
    PublishedAnalyticsQueryService,
)
from app.api.data_calendar import get_site_context, list_calendar_days
from app.api.dependencies import get_database_session, require_roles
from app.api.errors import ApiError
from app.auth.sessions import Principal

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
_Principal = Annotated[
    Principal,
    Depends(require_roles("admin", "data_manager", "viewer")),
]
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]
_FromDate = Annotated[date, Query(alias="from")]
_ToDate = Annotated[date, Query(alias="to")]
_ProductLimit = Annotated[int, Query(ge=1, le=200)]
_Page = Annotated[int, Query(ge=1)]
_PageSize = Annotated[int, Query(ge=1, le=200)]


def _service(database_session: Session) -> PublishedAnalyticsQueryService:
    # Authentication already performed a read on this request-scoped session.
    # End that read-only transaction before selecting a stronger isolation level.
    database_session.rollback()
    # A dashboard response performs several SELECTs. Pin them to one repeatable
    # snapshot so a publication pointer cannot switch halfway through a response.
    database_session.connection(
        execution_options={"isolation_level": "REPEATABLE READ"}
    )
    return PublishedAnalyticsQueryService(database_session)


def _raise_api_error(error: Exception) -> Never:
    if isinstance(error, InvalidAnalyticsDateRange):
        raise ApiError(
            422,
            "invalid_date_range",
            "from must not be after to.",
        ) from error
    if isinstance(error, AnalyticsDateRangeTooLarge):
        raise ApiError(
            422,
            "date_range_too_large",
            (
                "Date range must not exceed "
                f"{MAX_ANALYTICS_DATE_RANGE_DAYS} calendar days."
            ),
        ) from error
    if isinstance(error, InvalidReturnBasis):
        raise ApiError(
            422,
            "invalid_return_basis",
            "basis must be report_date or event_date.",
        ) from error
    if isinstance(error, MissingSiteConfiguration):
        raise ApiError(
            409,
            "missing_site_configuration",
            "A published dataset has no current reporting timezone.",
        ) from error
    if isinstance(error, InvalidSiteConfiguration):
        raise ApiError(
            409,
            "invalid_site_configuration",
            "The current reporting timezone is invalid.",
        ) from error
    raise error


@router.get("/summary", response_model=DashboardSummary)
def summary(
    _principal: _Principal,
    database_session: _DatabaseSession,
    from_date: _FromDate,
    to_date: _ToDate,
) -> DashboardSummary:
    try:
        return _service(database_session).summary(from_date, to_date)
    except (
        AnalyticsDateRangeTooLarge,
        InvalidAnalyticsDateRange,
        MissingSiteConfiguration,
        InvalidSiteConfiguration,
    ) as error:
        _raise_api_error(error)


@router.get("/daily-ledger", response_model=DailyLedgerResponse)
def daily_ledger(
    principal: _Principal,
    database_session: _DatabaseSession,
    from_date: _FromDate,
    to_date: _ToDate,
) -> DailyLedgerResponse:
    try:
        service = _service(database_session)
        summary_result = service.summary(from_date, to_date)
        calendar_days = list_calendar_days(
            principal,
            database_session,
            from_date,
            to_date,
        )
        site_context = get_site_context(principal, database_session)
        today = datetime.now(ZoneInfo(site_context.reporting_timezone)).date()
        return compose_daily_ledger(summary_result, calendar_days, today=today)
    except (
        AnalyticsDateRangeTooLarge,
        InvalidAnalyticsDateRange,
        MissingSiteConfiguration,
        InvalidSiteConfiguration,
    ) as error:
        _raise_api_error(error)


@router.get("/products", response_model=ProductDashboard)
def products(
    _principal: _Principal,
    database_session: _DatabaseSession,
    from_date: _FromDate,
    to_date: _ToDate,
    limit: _ProductLimit = 25,
) -> ProductDashboard:
    try:
        return _service(database_session).products(
            from_date,
            to_date,
            limit=limit,
        )
    except (
        AnalyticsDateRangeTooLarge,
        InvalidAnalyticsDateRange,
        MissingSiteConfiguration,
        InvalidSiteConfiguration,
    ) as error:
        _raise_api_error(error)


@router.get("/product-ledger", response_model=ProductLedgerResponse)
def product_ledger(
    _principal: _Principal,
    database_session: _DatabaseSession,
    response: Response,
    from_date: _FromDate,
    to_date: _ToDate,
    search: str | None = Query(default=None, max_length=200),
    sort: ProductLedgerSort = "sales",
    direction: SortDirection = "desc",
    page: _Page = 1,
    page_size: _PageSize = 25,
) -> ProductLedgerResponse:
    response.headers["X-Identity-Source"] = "legacy_parser"
    response.headers["X-Identity-Version"] = "seller_sku_parser_v1"
    try:
        _service(database_session)
        return ProductLedgerQueryService(database_session).ledger(
            from_date,
            to_date,
            search=search,
            sort=sort,
            direction=direction,
            page=page,
            page_size=page_size,
        )
    except (
        AnalyticsDateRangeTooLarge,
        InvalidAnalyticsDateRange,
        MissingSiteConfiguration,
        InvalidSiteConfiguration,
    ) as error:
        _raise_api_error(error)
    except ValueError as error:
        raise ApiError(422, "invalid_product_query", str(error)) from error


@router.get("/product-card/{style_code}", response_model=ProductCardResponse)
def product_card(
    style_code: str,
    _principal: _Principal,
    database_session: _DatabaseSession,
    response: Response,
    from_date: _FromDate,
    to_date: _ToDate,
) -> ProductCardResponse:
    response.headers["X-Identity-Source"] = "legacy_parser"
    response.headers["X-Identity-Version"] = "seller_sku_parser_v1"
    try:
        _service(database_session)
        result = ProductLedgerQueryService(database_session).product_card(
            style_code,
            from_date,
            to_date,
        )
    except (
        AnalyticsDateRangeTooLarge,
        InvalidAnalyticsDateRange,
        MissingSiteConfiguration,
        InvalidSiteConfiguration,
    ) as error:
        _raise_api_error(error)
    except ValueError as error:
        raise ApiError(422, "invalid_style_code", str(error)) from error
    if result is None:
        raise ApiError(404, "product_not_found", "The requested product was not found.")
    return result


@router.get("/returns", response_model=ReturnDashboard)
def returns(
    _principal: _Principal,
    database_session: _DatabaseSession,
    from_date: _FromDate,
    to_date: _ToDate,
    basis: Literal["report_date", "event_date"] = "report_date",
) -> ReturnDashboard:
    try:
        return _service(database_session).returns(
            from_date,
            to_date,
            basis=basis,
        )
    except (
        AnalyticsDateRangeTooLarge,
        InvalidAnalyticsDateRange,
        InvalidReturnBasis,
        MissingSiteConfiguration,
        InvalidSiteConfiguration,
    ) as error:
        _raise_api_error(error)
