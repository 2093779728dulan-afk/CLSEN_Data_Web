"""FastAPI application factory and process entry point."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from http import HTTPStatus
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import Lifespan

from app.api.errors import ApiErrorResponse
from app.auth.sessions import BootstrapCsrfTokens, LoginRateLimiter
from app.config import Settings
from app.db.engine import create_database_engine
from app.db.session import SessionFactory, create_session_factory
from app.db.settings import DatabaseSettings
from app.logging import configure_logging, request_id_context
from app.maintenance.health import MaintenanceLockMonitor, probe_maintenance_lock
from app.maintenance.schema_compatibility import assert_schema_compatible

_REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}", flags=re.ASCII)
_LOGGER = logging.getLogger("app.request")

_HTTP_ERROR_DETAILS: dict[int, tuple[str, str]] = {
    HTTPStatus.BAD_REQUEST: ("bad_request", "The request could not be understood."),
    HTTPStatus.UNAUTHORIZED: ("unauthorized", "Authentication is required."),
    HTTPStatus.FORBIDDEN: (
        "forbidden",
        "Permission to perform this action was denied.",
    ),
    HTTPStatus.NOT_FOUND: ("not_found", "The requested resource was not found."),
    HTTPStatus.METHOD_NOT_ALLOWED: (
        "method_not_allowed",
        "The request method is not allowed for this resource.",
    ),
    HTTPStatus.CONFLICT: ("conflict", "The request conflicts with current state."),
    HTTPStatus.UNPROCESSABLE_ENTITY: (
        "validation_error",
        "The request data is invalid.",
    ),
}


def _request_id(request: Request) -> str:
    candidate = request.headers.get(_REQUEST_ID_HEADER)
    if candidate is not None and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return str(uuid4())


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
            }
        },
        headers=headers,
    )


def _http_error_detail(status_code: int) -> tuple[str, str]:
    detail = _HTTP_ERROR_DETAILS.get(status_code)
    if detail is not None:
        return detail

    try:
        phrase = HTTPStatus(status_code).phrase.lower().replace(" ", "_")
    except ValueError:
        phrase = "http_error"
    return phrase, "The request could not be completed."


def _cors_error_headers(
    request: Request,
    settings: Settings,
    request_id: str,
) -> dict[str, str]:
    headers = {_REQUEST_ID_HEADER: request_id}
    origin = request.headers.get("Origin")
    if origin in settings.cors_allowed_origins:
        headers.update(
            {
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Expose-Headers": _REQUEST_ID_HEADER,
                "Vary": "Origin",
            }
        )
    return headers


def _build_app(
    resolved_settings: Settings,
    *,
    session_factory: SessionFactory | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    configure_logging(resolved_settings)

    application = FastAPI(
        title="Daily Data Review API",
        version="0.1.0",
        responses={
            HTTPStatus.UNPROCESSABLE_ENTITY: {
                "model": ApiErrorResponse,
                "description": "The request data or requested operation is invalid.",
            }
        },
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.session_factory = session_factory
    application.state.database_engine = None
    application.state.login_rate_limiter = LoginRateLimiter(
        maximum_attempts=resolved_settings.login_rate_limit_attempts,
        window=resolved_settings.login_rate_limit_window,
    )
    application.state.bootstrap_csrf_tokens = BootstrapCsrfTokens(
        secret=resolved_settings.session_secret,
        ttl=resolved_settings.bootstrap_csrf_ttl,
    )
    application.state.maintenance_lock_monitor = MaintenanceLockMonitor()

    @application.exception_handler(StarletteHTTPException)
    def handle_http_exception(
        request: Request,
        exception: StarletteHTTPException,
    ) -> JSONResponse:
        detail: object = exception.detail
        if isinstance(detail, dict):
            code = detail.get("code")
            message = detail.get("message")
            if not isinstance(code, str) or not isinstance(message, str):
                code, message = _http_error_detail(exception.status_code)
        else:
            code, message = _http_error_detail(exception.status_code)
        return _error_response(
            status_code=exception.status_code,
            code=code,
            message=message,
            request_id=request.state.request_id,
            headers=exception.headers,
        )

    @application.exception_handler(RequestValidationError)
    def handle_validation_exception(
        request: Request,
        exception: RequestValidationError,
    ) -> JSONResponse:
        code, message = _HTTP_ERROR_DETAILS[HTTPStatus.UNPROCESSABLE_ENTITY]
        if request.url.path == "/api/dashboard/style-ledger" or (
            request.url.path.startswith("/api/dashboard/styles/")
            and request.url.path.endswith("/card")
        ):
            invalid_fields = {
                str(error.get("loc", (None, None))[-1]) for error in exception.errors()
            }
            if invalid_fields & {"from", "to"}:
                code = "analytics_date_range_invalid"
                message = "The analytics date range is invalid."
            else:
                code = "analytics_parameter_invalid"
                message = "The analytics query parameter is invalid."
        return _error_response(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            code=code,
            message=message,
            request_id=request.state.request_id,
        )

    @application.exception_handler(Exception)
    def handle_unexpected_error(
        request: Request,
        exception: Exception,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", _request_id(request))
        _LOGGER.error(
            "Unhandled request error",
            exc_info=(type(exception), exception, exception.__traceback__),
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )
        return _error_response(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            code="internal_server_error",
            message="An unexpected error occurred.",
            request_id=request_id,
            headers=_cors_error_headers(request, resolved_settings, request_id),
        )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-CSRF-Token",
            "X-Original-Filename",
            _REQUEST_ID_HEADER,
        ],
        expose_headers=[_REQUEST_ID_HEADER],
    )

    async def add_request_context(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = _request_id(request)
        request.state.request_id = request_id
        context_token = request_id_context.set(request_id)
        started_at = perf_counter()

        try:
            response = await call_next(request)
            if (
                response.status_code == HTTPStatus.BAD_REQUEST
                and request.method == "OPTIONS"
                and "Origin" in request.headers
                and "Access-Control-Request-Method" in request.headers
            ):
                response = _error_response(
                    status_code=HTTPStatus.BAD_REQUEST,
                    code="cors_preflight_denied",
                    message="The CORS preflight request was denied.",
                    request_id=request_id,
                )
            response.headers[_REQUEST_ID_HEADER] = request_id
            _LOGGER.info(
                "Request completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                },
            )
            return response
        finally:
            request_id_context.reset(context_token)

    application.middleware("http")(add_request_context)

    from app.api.admin import router as admin_router
    from app.api.admin_management import router as admin_management_router
    from app.api.auth import router as auth_router
    from app.api.batch_reviews import router as batch_reviews_router
    from app.api.catalog_admin import router as catalog_admin_router
    from app.api.catalog_changes import router as catalog_changes_router
    from app.api.catalog_dedup import router as catalog_dedup_router
    from app.api.catalog_exports import router as catalog_exports_router
    from app.api.catalog_imports import router as catalog_imports_router
    from app.api.catalog_queries import router as catalog_queries_router
    from app.api.dashboard import router as dashboard_router
    from app.api.data_calendar import router as data_calendar_router
    from app.api.datasets import router as datasets_router
    from app.api.drafts import router as drafts_router
    from app.api.imports import router as imports_router
    from app.api.maintenance import router as maintenance_router
    from app.api.publications import router as publications_router
    from app.api.published_details import router as published_details_router
    from app.api.raw_files import router as raw_files_router
    from app.api.review import router as review_router
    from app.api.review_workspace import router as review_workspace_router
    from app.api.style_analytics import router as style_analytics_router
    from app.api.validation_runs import router as validation_runs_router
    from app.api.versions import router as versions_router
    from app.api.workbench import router as workbench_router

    application.include_router(auth_router)
    application.include_router(batch_reviews_router)
    application.include_router(catalog_admin_router)
    application.include_router(catalog_changes_router)
    application.include_router(catalog_dedup_router)
    application.include_router(catalog_exports_router)
    application.include_router(catalog_imports_router)
    application.include_router(catalog_queries_router)
    application.include_router(admin_router)
    application.include_router(admin_management_router)
    application.include_router(data_calendar_router)
    application.include_router(dashboard_router)
    application.include_router(datasets_router)
    application.include_router(drafts_router)
    application.include_router(imports_router)
    application.include_router(maintenance_router)
    application.include_router(publications_router)
    application.include_router(published_details_router)
    application.include_router(raw_files_router)
    application.include_router(review_router)
    application.include_router(review_workspace_router)
    application.include_router(style_analytics_router)
    application.include_router(validation_runs_router)
    application.include_router(versions_router)
    application.include_router(workbench_router)

    @application.get("/api/health/live", tags=["health"])
    def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/health/ready", tags=["health"], response_model=None)
    def health_ready() -> dict[str, str] | JSONResponse:
        engine = getattr(application.state, "database_engine", None)
        monitor = application.state.maintenance_lock_monitor
        if (
            isinstance(engine, Engine)
            and engine.dialect.name == "mysql"
            and isinstance(monitor, MaintenanceLockMonitor)
        ):
            try:
                lock = probe_maintenance_lock(engine, monitor)
            except SQLAlchemyError:
                return JSONResponse(
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                    content={
                        "status": "unavailable",
                        "reason": "database_unavailable",
                    },
                )
            if lock.warning:
                return JSONResponse(
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                    content={
                        "status": "degraded",
                        "reason": "maintenance_write_lock_held",
                    },
                )
        return {"status": "ok"}

    return application


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: SessionFactory | None = None,
) -> FastAPI:
    """Build an offline application with optional injected persistence."""

    return _build_app(
        settings or Settings(),
        session_factory=session_factory,
    )


def create_runtime_app(settings: Settings | None = None) -> FastAPI:
    """Build the mandatory schema-guarded application used by real servers."""

    resolved_settings = settings or Settings()

    @asynccontextmanager
    async def runtime_lifespan(application: FastAPI) -> AsyncIterator[None]:
        database_settings = DatabaseSettings.from_env()
        engine = create_database_engine(database_settings)
        try:
            assert_schema_compatible(
                engine,
                database_identity=database_settings.safe_url,
            )
            application.state.database_engine = engine
            application.state.session_factory = create_session_factory(engine)
            yield
        finally:
            application.state.session_factory = None
            application.state.database_engine = None
            engine.dispose()

    return _build_app(resolved_settings, lifespan=runtime_lifespan)


app = create_runtime_app()
