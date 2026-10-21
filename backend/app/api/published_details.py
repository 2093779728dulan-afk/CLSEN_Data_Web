"""Read-only HTTP boundary for the current published-detail ledger."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal, Never
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from anyio import CancelScope, to_thread
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.types import Receive, Scope, Send

from app.api.data_calendar import SiteContextResponse, get_site_context
from app.api.dependencies import get_database_session, require_request_roles
from app.api.errors import ApiError, ApiErrorResponse
from app.auth.sessions import Principal
from app.imports.types import ReportType
from app.published_details.csv_export import (
    InvalidPublishedExportColumn,
    PublishedCsvExporter,
    PublishedExportQuery,
    published_csv_content_disposition,
)
from app.published_details.models import (
    PublishedDetailPermissions,
    PublishedDetailQuery,
    PublishedDetailRange,
    PublishedDetailScope,
    PublishedRangeResponse,
    PublishedRowsResponse,
    PublishedSummaryResponse,
)
from app.published_details.query_builder import (
    InvalidPublishedSortColumn,
    InvalidPublishedSortDirection,
    PublishedColumnResolutionError,
)
from app.published_details.scope import (
    PublishedScopeCodec,
    PublishedScopeExpired,
    PublishedScopeInvalid,
)
from app.published_details.service import (
    InvalidPublishedReportDate,
    PublicationScopeChanged,
    PublishedDetailQueryService,
    PublishedSchemaIntegrityError,
    PublishedSiteConfigurationError,
)

router = APIRouter(prefix="/api/published-details", tags=["published-details"])

_SCOPE_TTL = timedelta(minutes=5)
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {
        "model": ApiErrorResponse,
        "description": "The requested published field is not visible.",
    },
    409: {
        "model": ApiErrorResponse,
        "description": "The publication scope is invalid or changed.",
    },
    500: {
        "model": ApiErrorResponse,
        "description": "Published data failed an integrity check.",
    },
}

_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="request"),
]
_Reader = Annotated[
    Principal,
    Depends(require_request_roles("admin", "data_manager", "viewer")),
]
_ReportType = Annotated[ReportType, Query()]
_FromDate = Annotated[date, Query(alias="from")]
_ToDate = Annotated[date, Query(alias="to")]
_Search = Annotated[str | None, Query(max_length=200)]
_Page = Annotated[int, Query(ge=1)]
_PageSize = Annotated[int, Query(ge=1, le=100)]
_ScopeToken = Annotated[
    str | None,
    Query(),
]
_RequiredScopeToken = Annotated[
    str,
    Query(),
]
_SortColumnId = Annotated[UUID | None, Query()]
_Direction = Annotated[Literal["asc", "desc"], Query()]
_ReportDate = Annotated[date | None, Query()]
_ColumnIds = Annotated[list[UUID], Query(alias="column_id")]


class _ClosingStreamingResponse(StreamingResponse):
    """Always release the owned sync iterator on completion or disconnect."""

    def __init__(
        self,
        content: Generator[bytes],
        *,
        media_type: str,
        headers: Mapping[str, str],
    ) -> None:
        self._owned_stream = content
        super().__init__(content, media_type=media_type, headers=headers)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # The iterator may own a server-side result.  Closing can reach the
            # DBAPI driver, so keep it off the event loop and shield the await
            # until cleanup completes before request dependencies tear down.
            with CancelScope(shield=True):
                await to_thread.run_sync(self._owned_stream.close)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _site_context(
    principal: Principal,
    database_session: Session,
) -> SiteContextResponse:
    try:
        return get_site_context(principal, database_session)
    except ApiError as error:
        if error.status_code == 503:
            raise PublishedSiteConfigurationError() from error
        raise


def _service(
    request: Request,
    database_session: Session,
) -> tuple[PublishedDetailQueryService, PublishedScopeCodec]:
    # Authentication has already read and touched last_seen_at through this
    # same route-owned Session.  Preserve that telemetry, then start the
    # multi-statement business response in its own repeatable-read snapshot.
    database_session.commit()
    database_session.connection(
        execution_options={"isolation_level": "REPEATABLE READ"}
    )
    codec = PublishedScopeCodec(
        secret=request.app.state.settings.session_secret,
        clock=_utc_now,
        ttl=_SCOPE_TTL,
    )
    return PublishedDetailQueryService(database_session, codec), codec


def _validate_range(from_date: date, to_date: date) -> None:
    if from_date > to_date:
        raise ApiError(
            422,
            "invalid_date_range",
            "from must not be after to.",
        )


def _scope_for_request(
    *,
    service: PublishedDetailQueryService,
    codec: PublishedScopeCodec,
    principal: Principal,
    database_session: Session,
    report_type: ReportType,
    from_date: date,
    to_date: date,
    scope_token: str | None,
) -> tuple[PublishedDetailScope, str]:
    if scope_token is None:
        scope = service.resolve_publication_scope(
            principal,
            report_type,
            from_date,
            to_date,
        )
        return scope, codec.encode(scope)

    try:
        site_context = _site_context(principal, database_session)
    except PublishedSiteConfigurationError as error:
        raise PublicationScopeChanged() from error
    expected_query = PublishedDetailQuery(
        site_id=site_context.site_id,
        report_type=report_type,
        from_date=from_date,
        to_date=to_date,
    )
    return codec.decode(scope_token, principal, expected_query), scope_token


def _permissions() -> PublishedDetailPermissions:
    return PublishedDetailPermissions(can_export=True)


def _raise_api_error(error: Exception) -> Never:
    if isinstance(error, PublishedScopeExpired):
        raise ApiError(
            409,
            "published_scope_expired",
            "The publication scope expired; resolve a new scope.",
        ) from error
    if isinstance(error, PublishedScopeInvalid):
        raise ApiError(
            409,
            "published_scope_invalid",
            "The publication scope is invalid; resolve a new scope.",
        ) from error
    if isinstance(error, PublicationScopeChanged):
        raise ApiError(409, error.code, error.message) from error
    if isinstance(error, InvalidPublishedReportDate):
        raise ApiError(422, error.code, error.message) from error
    if isinstance(error, InvalidPublishedSortDirection):
        raise ApiError(
            422,
            error.code,
            "direction must be asc or desc.",
        ) from error
    if isinstance(error, InvalidPublishedSortColumn):
        raise ApiError(
            403,
            error.code,
            "The requested sort column is not visible.",
        ) from error
    if isinstance(error, InvalidPublishedExportColumn):
        raise ApiError(
            403,
            error.code,
            "A requested export column is not visible.",
        ) from error
    if isinstance(error, PublishedSiteConfigurationError):
        raise ApiError(409, error.code, error.message) from error
    if isinstance(
        error,
        (PublishedSchemaIntegrityError, PublishedColumnResolutionError),
    ):
        raise ApiError(
            500,
            "published_data_integrity_error",
            "Published data failed an integrity check.",
        ) from error
    raise error


@router.get(
    "/range",
    response_model=PublishedRangeResponse,
    responses=_ERROR_RESPONSES,
)
def published_details_range(
    database_session: _DatabaseSession,
    principal: _Reader,
    request: Request,
    report_type: _ReportType,
) -> PublishedRangeResponse:
    try:
        service, _codec = _service(request, database_session)
        site_context = _site_context(principal, database_session)
        try:
            timezone = ZoneInfo(site_context.reporting_timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ApiError(
                409,
                "invalid_site_configuration",
                "The current reporting timezone is invalid.",
            ) from error
        today = _utc_now().astimezone(timezone).date()
        return service.resolve_full_range(principal, report_type, today)
    except (
        PublicationScopeChanged,
        PublishedSchemaIntegrityError,
        PublishedSiteConfigurationError,
        PublishedColumnResolutionError,
    ) as error:
        _raise_api_error(error)


@router.get(
    "/summaries",
    response_model=PublishedSummaryResponse,
    responses=_ERROR_RESPONSES,
)
def published_detail_summaries(
    database_session: _DatabaseSession,
    principal: _Reader,
    request: Request,
    report_type: _ReportType,
    from_date: _FromDate,
    to_date: _ToDate,
    search: _Search = None,
    page: _Page = 1,
    page_size: _PageSize = 50,
    scope_token: _ScopeToken = None,
) -> PublishedSummaryResponse:
    _validate_range(from_date, to_date)
    try:
        service, codec = _service(request, database_session)
        scope, response_token = _scope_for_request(
            service=service,
            codec=codec,
            principal=principal,
            database_session=database_session,
            report_type=report_type,
            from_date=from_date,
            to_date=to_date,
            scope_token=scope_token,
        )
        result = service.query_date_summaries(scope, search, page, page_size)
        return PublishedSummaryResponse(
            range=PublishedDetailRange(
                from_date=scope.from_date,
                to_date=scope.to_date,
            ),
            summaries=result.summaries,
            publications=list(scope.publications),
            permissions=_permissions(),
            pagination=result.pagination,
            scope_token=response_token,
        )
    except (
        InvalidPublishedSortColumn,
        InvalidPublishedSortDirection,
        PublicationScopeChanged,
        PublishedColumnResolutionError,
        PublishedSchemaIntegrityError,
        PublishedScopeExpired,
        PublishedScopeInvalid,
        PublishedSiteConfigurationError,
    ) as error:
        _raise_api_error(error)


@router.get(
    "/rows",
    response_model=PublishedRowsResponse,
    responses=_ERROR_RESPONSES,
)
def published_detail_rows(
    database_session: _DatabaseSession,
    principal: _Reader,
    request: Request,
    report_type: _ReportType,
    from_date: _FromDate,
    to_date: _ToDate,
    search: _Search = None,
    sort_column_id: _SortColumnId = None,
    direction: _Direction = "asc",
    page: _Page = 1,
    page_size: _PageSize = 50,
    scope_token: _ScopeToken = None,
    report_date: _ReportDate = None,
) -> PublishedRowsResponse:
    _validate_range(from_date, to_date)
    try:
        service, codec = _service(request, database_session)
        scope, response_token = _scope_for_request(
            service=service,
            codec=codec,
            principal=principal,
            database_session=database_session,
            report_type=report_type,
            from_date=from_date,
            to_date=to_date,
            scope_token=scope_token,
        )
        result = service.query_published_rows(
            scope,
            search,
            sort_column_id,
            direction,
            page,
            page_size,
            report_date,
        )
        return PublishedRowsResponse(
            range=PublishedDetailRange(
                from_date=scope.from_date,
                to_date=scope.to_date,
            ),
            columns=result.columns,
            rows=result.rows,
            publications=list(scope.publications),
            permissions=_permissions(),
            pagination=result.pagination,
            scope_token=response_token,
        )
    except (
        InvalidPublishedReportDate,
        InvalidPublishedSortColumn,
        InvalidPublishedSortDirection,
        PublicationScopeChanged,
        PublishedColumnResolutionError,
        PublishedSchemaIntegrityError,
        PublishedScopeExpired,
        PublishedScopeInvalid,
        PublishedSiteConfigurationError,
    ) as error:
        _raise_api_error(error)


@router.get(
    "/export.csv",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Formula-safe UTF-8 CSV stream.",
            "content": {
                "text/csv": {
                    "schema": {"type": "string", "format": "binary"},
                }
            },
        },
        **_ERROR_RESPONSES,
    },
)
def export_published_details(
    database_session: _DatabaseSession,
    principal: _Reader,
    request: Request,
    report_type: _ReportType,
    from_date: _FromDate,
    to_date: _ToDate,
    scope_token: _RequiredScopeToken,
    column_id: _ColumnIds,
    search: _Search = None,
    sort_column_id: _SortColumnId = None,
    direction: _Direction = "asc",
    report_date: _ReportDate = None,
) -> StreamingResponse:
    _validate_range(from_date, to_date)
    try:
        service, codec = _service(request, database_session)
        scope, _response_token = _scope_for_request(
            service=service,
            codec=codec,
            principal=principal,
            database_session=database_session,
            report_type=report_type,
            from_date=from_date,
            to_date=to_date,
            scope_token=scope_token,
        )
        stream = PublishedCsvExporter(service).stream_published_csv(
            scope,
            PublishedExportQuery(
                search=search,
                sort_column_id=sort_column_id,
                direction=direction,
                report_date=report_date,
            ),
            column_id,
        )
        return _ClosingStreamingResponse(
            stream,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": published_csv_content_disposition(scope),
            },
        )
    except (
        InvalidPublishedExportColumn,
        InvalidPublishedReportDate,
        InvalidPublishedSortColumn,
        InvalidPublishedSortDirection,
        PublicationScopeChanged,
        PublishedColumnResolutionError,
        PublishedSchemaIntegrityError,
        PublishedScopeExpired,
        PublishedScopeInvalid,
        PublishedSiteConfigurationError,
    ) as error:
        _raise_api_error(error)
