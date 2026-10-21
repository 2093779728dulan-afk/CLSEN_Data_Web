"""Session-cookie authentication routes."""

from __future__ import annotations

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_DESCRIPTION,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    get_database_session,
    get_session_service,
    require_csrf_principal,
    require_principal,
)
from app.api.errors import ApiError
from app.auth.sessions import (
    BootstrapCsrfTokens,
    LoginRateLimiter,
    Principal,
    SessionService,
)
from app.cli import normalise_username

router = APIRouter(prefix="/api/auth", tags=["auth"])
_BOOTSTRAP_CSRF_COOKIE_NAME = "clsen_login_csrf"
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]
_SessionService = Annotated[SessionService, Depends(get_session_service)]
_Principal = Annotated[Principal, Depends(require_principal)]
_CsrfPrincipal = Annotated[Principal, Depends(require_csrf_principal)]


class CsrfTokenResponse(BaseModel):
    csrf_token: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=191)
    password: str = Field(min_length=1, max_length=4096)


class CurrentUserResponse(BaseModel):
    id: int
    username: str
    display_name: str
    roles: list[str]


class LoginResponse(BaseModel):
    user: CurrentUserResponse
    csrf_token: str
    expires_at: str


def _set_cookie(
    response: Response,
    *,
    key: str,
    value: str,
    max_age: int,
    http_only: bool,
    secure: bool,
) -> None:
    response.set_cookie(
        key=key,
        value=value,
        max_age=max_age,
        httponly=http_only,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _principal_response(principal: Principal) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=principal.user_id,
        username=principal.username,
        display_name=principal.display_name,
        roles=sorted(principal.roles),
    )


def _rate_limit_keys(request: Request, username: str) -> tuple[str, str]:
    remote_host = request.client.host if request.client is not None else "unknown"
    try:
        username_normalised = normalise_username(username)
    except ValueError:
        # All usernames rejected by the account lookup normaliser intentionally
        # share one non-account bucket instead of creating attacker-controlled keys.
        username_normalised = ""
    return f"{remote_host}:{username_normalised}", remote_host


@router.get("/csrf", response_model=CsrfTokenResponse)
def issue_login_csrf_token(request: Request, response: Response) -> CsrfTokenResponse:
    settings = request.app.state.settings
    token_service: BootstrapCsrfTokens = request.app.state.bootstrap_csrf_tokens
    csrf_token = token_service.issue()
    _set_cookie(
        response,
        key=_BOOTSTRAP_CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=int(settings.bootstrap_csrf_ttl.total_seconds()),
        http_only=False,
        secure=bool(settings.session_cookie_secure),
    )
    return CsrfTokenResponse(csrf_token=csrf_token)


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    database_session: _DatabaseSession,
    service: _SessionService,
    supplied_csrf_token: Annotated[
        str | None,
        Header(
            alias=CSRF_HEADER_NAME,
            description=CSRF_HEADER_DESCRIPTION,
        ),
    ] = None,
) -> LoginResponse:
    cookie_csrf_token = request.cookies.get(_BOOTSTRAP_CSRF_COOKIE_NAME)
    token_service: BootstrapCsrfTokens = request.app.state.bootstrap_csrf_tokens
    if (
        not supplied_csrf_token
        or not cookie_csrf_token
        or supplied_csrf_token != cookie_csrf_token
        or not token_service.is_valid(supplied_csrf_token)
    ):
        raise ApiError(403, "csrf_invalid", "A valid CSRF token is required.")

    rate_limiter: LoginRateLimiter = request.app.state.login_rate_limiter
    rate_limit_key, source_key = _rate_limit_keys(request, payload.username)
    if not rate_limiter.is_allowed(rate_limit_key, source_key=source_key):
        retry_after = rate_limiter.retry_after_seconds(
            rate_limit_key,
            source_key=source_key,
        )
        error = ApiError(
            429,
            "login_rate_limited",
            "Too many login attempts. Try again later.",
        )
        error.headers = {"Retry-After": str(retry_after)}
        raise error

    result = service.authenticate(
        database_session,
        username=payload.username,
        password=payload.password,
        request_id=request.state.request_id,
    )
    if result is None:
        rate_limiter.record_failure(rate_limit_key, source_key=source_key)
        raise ApiError(401, "invalid_credentials", "Invalid username or password.")
    rate_limiter.reset(rate_limit_key)

    settings = request.app.state.settings
    session_max_age = int(settings.session_ttl.total_seconds())
    _set_cookie(
        response,
        key=SESSION_COOKIE_NAME,
        value=result.session_token,
        max_age=session_max_age,
        http_only=True,
        secure=bool(settings.session_cookie_secure),
    )
    _set_cookie(
        response,
        key=CSRF_COOKIE_NAME,
        value=result.csrf_token,
        max_age=session_max_age,
        http_only=False,
        secure=bool(settings.session_cookie_secure),
    )
    response.delete_cookie(_BOOTSTRAP_CSRF_COOKIE_NAME, path="/")
    return LoginResponse(
        user=_principal_response(result.principal),
        csrf_token=result.csrf_token,
        expires_at=result.expires_at.replace(tzinfo=UTC).isoformat(),
    )


@router.get("/me", response_model=CurrentUserResponse)
def current_user(principal: _Principal) -> CurrentUserResponse:
    return _principal_response(principal)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    principal: _CsrfPrincipal,
    database_session: _DatabaseSession,
    service: _SessionService,
) -> Response:
    service.revoke(
        database_session,
        principal=principal,
        request_id=request.state.request_id,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return response
