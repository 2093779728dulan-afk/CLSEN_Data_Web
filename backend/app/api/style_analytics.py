"""Stable style analytics HTTP routes with explicit P0 catalog identity."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Literal, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.analytics.readiness import AnalyticsReadiness, read_readiness
from app.analytics.style_models import (
    AnalyticsPermissions,
    FactBasis,
    MetricName,
    ReturnBasis,
    SeriesDimension,
    StyleCardResponse,
    StyleLedgerResponse,
)
from app.analytics.style_repository import (
    AnalyticsCatalogRequired,
    AnalyticsCatalogVersionRequired,
    AnalyticsDateRangeInvalid,
    AnalyticsDimensionParameterInvalid,
    AnalyticsIdentityFactCombinationInvalid,
    AnalyticsReturnSnapshotRequired,
    AnalyticsSeriesInvalid,
    AnalyticsSnapshotStale,
    AnalyticsSourceScopeRequired,
    CatalogColorNotFound,
    CatalogSnapshotRangeOutOfBounds,
    CatalogStyleNotFound,
    MySqlStyleAnalyticsRepository,
    StyleAnalyticsError,
)
from app.analytics.style_service import (
    StyleAnalyticsRepository,
    StyleAnalyticsService,
    StyleCardQuery,
    StyleLedgerQuery,
)
from app.api.catalog_common import CatalogEngine
from app.api.dependencies import (
    get_database_session,
    require_principal,
    require_roles,
)
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.site_context import CurrentSiteContext, resolve_current_site_context

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_Principal = Annotated[
    Principal,
    Depends(require_roles("admin", "data_manager", "viewer")),
]


def _style_context(
    database_session: Annotated[
        Session,
        Depends(get_database_session, scope="function"),
    ],
    principal: Annotated[Principal, Depends(require_principal)],
) -> CurrentSiteContext:
    """Resolve identity, then release the auth connection before RR analytics."""

    context = resolve_current_site_context(database_session, principal)
    database_session.rollback()
    database_session.close()
    return context


StyleContext = Annotated[CurrentSiteContext, Depends(_style_context)]
_LEDGER_SORTS = frozenset(
    {
        "style_code",
        "standard_name",
        "units",
        "sales",
        "returns",
        "sessions",
        "conversion",
    }
)
_DIRECTIONS = frozenset({"asc", "desc"})
_FACT_BASES = frozenset({"current", "catalog_snapshot"})
_RETURN_BASES = frozenset({"event_date", "report_date"})
_METRICS = frozenset({"units", "sales", "returns", "sessions", "conversion"})
_DIMENSIONS = frozenset({"total", "color", "size", "sku"})
LedgerSort = Literal[
    "style_code",
    "standard_name",
    "units",
    "sales",
    "returns",
    "sessions",
    "conversion",
]
Direction = Literal["asc", "desc"]


def _error(status: int, code: str, message: str) -> ApiError:
    return ApiError(status, code, message)


def _parameter_error() -> ApiError:
    return _error(
        422,
        "analytics_parameter_invalid",
        "The analytics query parameter is invalid.",
    )


def _date_error() -> ApiError:
    return _error(
        422,
        "analytics_date_range_invalid",
        "The analytics date range is invalid.",
    )


def _positive_integer(value: str | int | None, *, required: bool = False) -> int | None:
    if value is None:
        if required:
            raise _parameter_error()
        return None
    text = str(value)
    if not text.isascii() or not text.isdecimal() or text.startswith("0"):
        raise _parameter_error()
    parsed = int(text)
    if parsed < 1:
        raise _parameter_error()
    return parsed


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise _date_error() from error
    if parsed.isoformat() != value:
        raise _date_error()
    return parsed


def _date_range(
    context: CurrentSiteContext,
    from_value: str | date | None,
    to_value: str | date | None,
) -> tuple[date, date]:
    today = date.today()
    try:
        today = datetime.now(ZoneInfo(context.reporting_timezone)).date()
    except Exception as error:
        raise _date_error() from error
    to_date = today if to_value is None else _parse_date(to_value)
    from_date = (
        to_date - timedelta(days=30) if from_value is None else _parse_date(from_value)
    )
    span = (to_date - from_date).days + 1
    if span < 1 or span > 366 or to_date > today:
        raise _date_error()
    return from_date, to_date


def _analytics_permissions(context: CurrentSiteContext) -> AnalyticsPermissions:
    manager = not context.principal_roles.isdisjoint({"admin", "data_manager"})
    admin = "admin" in context.principal_roles
    return AnalyticsPermissions(
        can_view_catalog_history=manager,
        can_manage_catalog=manager,
        can_view_evidence_history=manager,
        can_download_original=manager,
        can_submit=manager,
        can_approve_normal=manager,
        can_approve_high_risk=admin,
    )


def _fact_parameters(
    *,
    context: CurrentSiteContext,
    catalog_version: str | int | None,
    fact_basis: str,
    return_basis: str,
) -> tuple[int | None, FactBasis, ReturnBasis]:
    if fact_basis not in _FACT_BASES or return_basis not in _RETURN_BASES:
        raise _parameter_error()
    catalog_version_id = _positive_integer(catalog_version)
    if fact_basis == "catalog_snapshot" and catalog_version_id is None:
        raise _error(
            422,
            "analytics_catalog_version_required",
            "catalog_version is required for catalog_snapshot facts.",
        )
    if (
        fact_basis == "catalog_snapshot"
        and not _analytics_permissions(context).can_view_catalog_history
    ):
        raise _error(
            403,
            "catalog_history_forbidden",
            "Permission to read catalog history was denied.",
        )
    return (
        catalog_version_id,
        cast(FactBasis, fact_basis),
        cast(ReturnBasis, return_basis),
    )


def _parse_ledger_query(
    *,
    context: CurrentSiteContext,
    from_value: str | date | None,
    to_value: str | date | None,
    category_id: int | None = None,
    search: str | None = None,
    sort: str = "units",
    direction: str = "desc",
    page: str | int = "1",
    page_size: str | int = "50",
    catalog_version: str | int | None = None,
    fact_basis: str = "current",
    return_basis: str = "event_date",
) -> StyleLedgerQuery:
    from_date, to_date = _date_range(context, from_value, to_value)
    normalized_search = None if search is None else search.strip()
    if normalized_search == "":
        normalized_search = None
    if normalized_search is not None and len(normalized_search) > 100:
        raise _parameter_error()
    if sort not in _LEDGER_SORTS or direction not in _DIRECTIONS:
        raise _parameter_error()
    parsed_page = _positive_integer(page, required=True)
    parsed_page_size = _positive_integer(page_size, required=True)
    assert parsed_page is not None and parsed_page_size is not None
    if parsed_page_size > 100:
        raise _parameter_error()
    catalog_version_id, parsed_fact_basis, parsed_return_basis = _fact_parameters(
        context=context,
        catalog_version=catalog_version,
        fact_basis=fact_basis,
        return_basis=return_basis,
    )
    return StyleLedgerQuery(
        site_id=context.site_id,
        from_date=from_date,
        to_date=to_date,
        category_id=category_id,
        search=normalized_search,
        sort=cast(LedgerSort, sort),
        direction=cast(Direction, direction),
        page=parsed_page,
        page_size=parsed_page_size,
        catalog_version_id=catalog_version_id,
        fact_basis=parsed_fact_basis,
        return_basis=parsed_return_basis,
    )


def _parse_series(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    items = tuple(item.strip() for item in value.split(","))
    if (
        not 1 <= len(items) <= 8
        or any(not item for item in items)
        or len(set(items)) != len(items)
    ):
        raise _error(
            422,
            "analytics_series_invalid",
            "The requested analytics series is invalid.",
        )
    return items


def _parse_card_query(
    *,
    context: CurrentSiteContext,
    style_id: str,
    from_value: str | date | None,
    to_value: str | date | None,
    metric: str = "units",
    dimension: str = "color",
    color_key: str | None = None,
    series: str | None = None,
    catalog_version: str | int | None = None,
    fact_basis: str = "current",
    return_basis: str = "event_date",
) -> StyleCardQuery:
    from_date, to_date = _date_range(context, from_value, to_value)
    parsed_style_id = _positive_integer(style_id, required=True)
    assert parsed_style_id is not None
    if metric not in _METRICS or dimension not in _DIMENSIONS:
        raise _parameter_error()
    if (dimension == "size") != (color_key is not None and color_key != ""):
        raise _error(
            422,
            "analytics_dimension_parameter_invalid",
            "The analytics dimension parameters are invalid.",
        )
    catalog_version_id, parsed_fact_basis, parsed_return_basis = _fact_parameters(
        context=context,
        catalog_version=catalog_version,
        fact_basis=fact_basis,
        return_basis=return_basis,
    )
    return StyleCardQuery(
        site_id=context.site_id,
        style_id=parsed_style_id,
        from_date=from_date,
        to_date=to_date,
        metric=cast(MetricName, metric),
        dimension=cast(SeriesDimension, dimension),
        color_key=color_key,
        series=_parse_series(series),
        catalog_version_id=catalog_version_id,
        fact_basis=parsed_fact_basis,
        return_basis=parsed_return_basis,
    )


def _analytics_error(error: Exception) -> ApiError:
    mappings: tuple[tuple[type[Exception], int, str, str], ...] = (
        (
            AnalyticsSourceScopeRequired,
            409,
            "analytics_source_scope_required",
            "Confirm the report source scope before using product analytics.",
        ),
        (
            AnalyticsCatalogRequired,
            409,
            "analytics_catalog_required",
            "Review and approve the first catalog before using product analytics.",
        ),
        (
            AnalyticsReturnSnapshotRequired,
            409,
            "analytics_return_snapshot_required",
            "Prepare the return deduplication snapshot before using product analytics.",
        ),
        (
            AnalyticsSnapshotStale,
            409,
            "analytics_snapshot_stale",
            "The return snapshot no longer matches the published reports.",
        ),
        (
            AnalyticsDateRangeInvalid,
            422,
            "analytics_date_range_invalid",
            "The analytics date range is invalid.",
        ),
        (
            AnalyticsCatalogVersionRequired,
            422,
            "analytics_catalog_version_required",
            "catalog_version is required for catalog_snapshot facts.",
        ),
        (
            AnalyticsIdentityFactCombinationInvalid,
            409,
            "analytics_identity_fact_combination_invalid",
            "The catalog identity and fact basis cannot be combined.",
        ),
        (
            CatalogSnapshotRangeOutOfBounds,
            409,
            "catalog_snapshot_range_out_of_bounds",
            "The catalog snapshot does not cover the requested range.",
        ),
        (
            CatalogStyleNotFound,
            404,
            "catalog_style_not_found",
            "The requested style was not found.",
        ),
        (
            AnalyticsDimensionParameterInvalid,
            422,
            "analytics_dimension_parameter_invalid",
            "The analytics dimension parameters are invalid.",
        ),
        (
            CatalogColorNotFound,
            404,
            "catalog_color_not_found",
            "The requested catalog color was not found.",
        ),
        (
            AnalyticsSeriesInvalid,
            422,
            "analytics_series_invalid",
            "The requested analytics series is invalid.",
        ),
    )
    for error_type, status, code, message in mappings:
        if isinstance(error, error_type):
            return _error(status, code, message)
    if isinstance(error, StyleAnalyticsError):
        return _error(
            409,
            error.code,
            "The style analytics result is temporarily unavailable.",
        )
    return _error(500, "analytics_internal_error", "The analytics request failed.")


def _service(engine: Engine) -> StyleAnalyticsService:
    repository = cast(
        StyleAnalyticsRepository,
        MySqlStyleAnalyticsRepository(engine),
    )
    return StyleAnalyticsService(repository)


def _identity_headers(
    response: Response, result: StyleLedgerResponse | StyleCardResponse
) -> None:
    response.headers["X-Identity-Source"] = result.provenance.identity_source
    response.headers["X-Identity-Version"] = result.provenance.identity_version_id


@router.get("/style-readiness", response_model=AnalyticsReadiness)
def style_readiness(
    _principal: _Principal,
    context: StyleContext,
    engine: CatalogEngine,
) -> AnalyticsReadiness:
    # Same read-only consistent snapshot as analytics; no caller-supplied site ID.
    repository = MySqlStyleAnalyticsRepository(engine)
    connection = repository._begin()
    try:
        return read_readiness(connection, context.site_id)
    finally:
        connection.rollback()
        connection.close()


@router.get(
    "/style-ledger",
    response_model=StyleLedgerResponse,
    responses={
        200: {
            "headers": {
                "X-Identity-Source": {
                    "schema": {"type": "string", "const": "p0_catalog"}
                },
                "X-Identity-Version": {"schema": {"type": "string"}},
            }
        }
    },
)
def style_ledger(
    _principal: _Principal,
    context: StyleContext,
    engine: CatalogEngine,
    response: Response,
    from_value: Annotated[date | None, Query(alias="from")] = None,
    to_value: Annotated[date | None, Query(alias="to")] = None,
    category_id: Annotated[int | None, Query(ge=1)] = None,
    search: Annotated[str | None, Query()] = None,
    sort: Annotated[LedgerSort, Query()] = "units",
    direction: Annotated[Direction, Query()] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    catalog_version: Annotated[str | None, Query()] = None,
    fact_basis: Annotated[FactBasis, Query()] = "current",
    return_basis: Annotated[ReturnBasis, Query()] = "event_date",
) -> StyleLedgerResponse:
    query = _parse_ledger_query(
        context=context,
        from_value=from_value,
        to_value=to_value,
        category_id=category_id,
        search=search,
        sort=sort,
        direction=direction,
        page=page,
        page_size=page_size,
        catalog_version=catalog_version,
        fact_basis=fact_basis,
        return_basis=return_basis,
    )
    try:
        result = _service(engine).style_ledger(
            query,
            permissions=_analytics_permissions(context),
        )
    except StyleAnalyticsError as error:
        raise _analytics_error(error) from error
    _identity_headers(response, result)
    return result


@router.get(
    "/styles/{style_id}/card",
    response_model=StyleCardResponse,
    responses={
        200: {
            "headers": {
                "X-Identity-Source": {
                    "schema": {"type": "string", "const": "p0_catalog"}
                },
                "X-Identity-Version": {"schema": {"type": "string"}},
            }
        }
    },
)
def style_card(
    style_id: str,
    _principal: _Principal,
    context: StyleContext,
    engine: CatalogEngine,
    response: Response,
    from_value: Annotated[date | None, Query(alias="from")] = None,
    to_value: Annotated[date | None, Query(alias="to")] = None,
    metric: Annotated[MetricName, Query()] = "units",
    dimension: Annotated[SeriesDimension, Query()] = "color",
    color_key: Annotated[str | None, Query()] = None,
    series: Annotated[str | None, Query()] = None,
    catalog_version: Annotated[str | None, Query()] = None,
    fact_basis: Annotated[FactBasis, Query()] = "current",
    return_basis: Annotated[ReturnBasis, Query()] = "event_date",
) -> StyleCardResponse:
    query = _parse_card_query(
        context=context,
        style_id=style_id,
        from_value=from_value,
        to_value=to_value,
        metric=metric,
        dimension=dimension,
        color_key=color_key,
        series=series,
        catalog_version=catalog_version,
        fact_basis=fact_basis,
        return_basis=return_basis,
    )
    try:
        result = _service(engine).style_card(
            query,
            permissions=_analytics_permissions(context),
        )
    except StyleAnalyticsError as error:
        raise _analytics_error(error) from error
    _identity_headers(response, result)
    return result


__all__ = ("router",)
