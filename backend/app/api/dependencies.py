"""Request-scoped database, authentication, CSRF, and RBAC dependencies."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Generator
from typing import Annotated, Any, cast

from fastapi import Depends, Header, Request, Security
from fastapi.security import APIKeyCookie
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.auth.sessions import Principal, SessionService
from app.db.session import SessionFactory
from app.site_context import CurrentSiteContext, resolve_current_site_context

SESSION_COOKIE_NAME = "clsen_session"
CSRF_COOKIE_NAME = "clsen_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_HEADER_DESCRIPTION = (
    "CSRF proof required for state-changing requests; missing or invalid values "
    "return HTTP 403."
)

_SESSION_COOKIE = APIKeyCookie(
    name=SESSION_COOKIE_NAME,
    scheme_name="SessionCookie",
    description="HttpOnly same-origin application session cookie.",
    auto_error=False,
)


def get_session_factory(request: Request) -> SessionFactory:
    factory = cast(
        SessionFactory | None,
        getattr(request.app.state, "session_factory", None),
    )
    if factory is None:
        raise RuntimeError("application database session factory is unavailable")
    return factory


def get_database_engine(request: Request) -> Engine:
    engine = getattr(request.app.state, "database_engine", None)
    if isinstance(engine, Engine):
        return engine
    factory = get_session_factory(request)
    bound_engine = factory.kw.get("bind")
    if not isinstance(bound_engine, Engine):
        raise RuntimeError("application database session factory is not engine-bound")
    request.app.state.database_engine = bound_engine
    return bound_engine


def get_database_session(
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> Generator[Session]:
    with factory() as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


def get_session_service(request: Request) -> SessionService:
    return SessionService(request.app.state.settings)


def _authenticated_principal(
    request: Request,
    database_session: Session,
    service: SessionService,
    session_token: str | None,
) -> Principal:
    """Resolve the existing cookie proof against the caller-owned Session."""

    # Keep request in this shared boundary so both FastAPI dependencies retain
    # the same explicit request/authentication contract.
    del request
    if not session_token:
        raise ApiError(401, "authentication_required", "Authentication is required.")
    principal = service.get_principal(
        database_session,
        session_token=session_token,
    )
    if principal is None:
        raise ApiError(401, "session_invalid", "Authentication is required.")
    return principal


def require_principal(
    request: Request,
    database_session: Annotated[
        Session,
        Depends(get_database_session, scope="function"),
    ],
    service: Annotated[SessionService, Depends(get_session_service)],
    session_token: Annotated[str | None, Security(_SESSION_COOKIE)],
) -> Principal:
    return _authenticated_principal(
        request,
        database_session,
        service,
        session_token,
    )


def require_request_principal(
    request: Request,
    database_session: Annotated[
        Session,
        Depends(get_database_session, scope="request"),
    ],
    service: Annotated[SessionService, Depends(get_session_service)],
    session_token: Annotated[str | None, Security(_SESSION_COOKIE)],
) -> Principal:
    """Authenticate through a Session that must survive response streaming."""

    return _authenticated_principal(
        request,
        database_session,
        service,
        session_token,
    )


def require_csrf_principal(
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    service: Annotated[SessionService, Depends(get_session_service)],
    supplied_token: Annotated[
        str | None,
        Header(
            alias=CSRF_HEADER_NAME,
            description=CSRF_HEADER_DESCRIPTION,
        ),
    ] = None,
) -> Principal:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if (
        not supplied_token
        or not cookie_token
        or not secrets.compare_digest(supplied_token, cookie_token)
        or not service.csrf_matches(principal, supplied_token)
    ):
        raise ApiError(403, "csrf_invalid", "A valid CSRF token is required.")
    return principal


def require_roles(*allowed_roles: str) -> Callable[..., Principal]:
    """Return a dependency that enforces one of the named server-side roles."""

    allowed = frozenset(allowed_roles)

    def dependency(
        principal: Annotated[Principal, Depends(require_principal)],
    ) -> Principal:
        return _principal_with_roles(principal, allowed)

    metadata = cast(Any, dependency)
    metadata.required_roles = allowed
    return dependency


def require_request_roles(*allowed_roles: str) -> Callable[..., Principal]:
    """Enforce roles while retaining one request-scoped authentication Session."""

    allowed = frozenset(allowed_roles)

    def dependency(
        principal: Annotated[Principal, Depends(require_request_principal)],
    ) -> Principal:
        return _principal_with_roles(principal, allowed)

    metadata = cast(Any, dependency)
    metadata.required_roles = allowed
    return dependency


def require_write_roles(*allowed_roles: str) -> Callable[..., Principal]:
    allowed = frozenset(allowed_roles)

    def dependency(
        principal: Annotated[Principal, Depends(require_csrf_principal)],
    ) -> Principal:
        return _principal_with_roles(principal, allowed)

    metadata = cast(Any, dependency)
    metadata.required_roles = allowed
    return dependency


def _principal_with_roles(
    principal: Principal,
    allowed: frozenset[str],
) -> Principal:
    if principal.roles.isdisjoint(allowed):
        raise ApiError(
            403,
            "role_forbidden",
            "Permission to perform this action was denied.",
        )
    return principal


def get_current_site_context(
    database_session: Annotated[
        Session,
        Depends(get_database_session, scope="function"),
    ],
    principal: Annotated[Principal, Depends(require_principal)],
) -> CurrentSiteContext:
    """Bind the authenticated caller to the server's sole active site."""

    return resolve_current_site_context(database_session, principal)
