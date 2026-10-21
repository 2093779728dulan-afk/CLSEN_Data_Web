"""Administrator-only account, site configuration, and audit APIs."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_database_session,
    require_roles,
    require_write_roles,
)
from app.api.errors import ApiError
from app.auth.passwords import hash_password
from app.auth.sessions import Principal
from app.cli import normalise_username

router = APIRouter(prefix="/api/admin", tags=["admin"])
_Admin = Annotated[Principal, Depends(require_roles("admin"))]
_WritingAdmin = Annotated[Principal, Depends(require_write_roles("admin"))]
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]
_IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]
_UserStatus = Literal["active", "disabled", "locked"]
_AdminOperationKind = Literal[
    "create_user",
    "update_user",
    "create_site_config_version",
]
_ROLE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,31}", flags=re.ASCII)
_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}", flags=re.ASCII)
_SECRET_NOT_STORED = "$secret-not-stored$v1$"


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserResponse(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None
    status: _UserStatus
    roles: list[str]
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CreateUserRequest(_RequestModel):
    username: str = Field(min_length=1, max_length=191)
    display_name: str = Field(min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=12, max_length=4096)
    roles: list[str] = Field(min_length=1, max_length=32)
    status: _UserStatus = "active"

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("display_name must not be blank")
        return stripped

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().casefold()
        return stripped or None

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, value: list[str]) -> list[str]:
        normalised: list[str] = []
        for role in value:
            candidate = role.strip()
            if _ROLE_CODE_PATTERN.fullmatch(candidate) is None:
                raise ValueError("role codes must use lower-case identifier syntax")
            normalised.append(candidate)
        if len(set(normalised)) != len(normalised):
            raise ValueError("role codes must be unique")
        return normalised


class UpdateUserRequest(_RequestModel):
    expected_updated_at: datetime
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    status: _UserStatus | None = None
    roles: list[str] | None = Field(default=None, min_length=1, max_length=32)
    new_password: str | None = Field(default=None, min_length=12, max_length=4096)

    @field_validator("expected_updated_at")
    @classmethod
    def require_aware_updated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expected_updated_at must include a timezone offset")
        return value.astimezone(UTC)

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("display_name must not be blank")
        return stripped

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().casefold()
        return stripped or None

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalised: list[str] = []
        for role in value:
            candidate = role.strip()
            if _ROLE_CODE_PATTERN.fullmatch(candidate) is None:
                raise ValueError("role codes must use lower-case identifier syntax")
            normalised.append(candidate)
        if len(set(normalised)) != len(normalised):
            raise ValueError("role codes must be unique")
        return normalised

    @model_validator(mode="after")
    def require_change(self) -> Self:
        changes = self.model_fields_set - {"expected_updated_at"}
        if not changes:
            raise ValueError("at least one user change must be supplied")
        for field_name in ("display_name", "status", "roles", "new_password"):
            if field_name in changes and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} must not be null")
        return self


class SiteConfigVersionResponse(BaseModel):
    id: int
    site_id: int
    site_code: str
    site_display_name: str
    version_number: int
    source_timezone: str
    reporting_timezone: str
    currency_code: str
    effective_at: datetime
    change_reason: str | None
    created_by_user_id: int | None
    created_at: datetime
    is_current: bool


class CreateSiteConfigVersionRequest(_RequestModel):
    site_id: int = Field(ge=1)
    source_timezone: str = Field(min_length=1, max_length=64)
    reporting_timezone: str = Field(min_length=1, max_length=64)
    currency_code: str = Field(min_length=3, max_length=3)
    effective_at: datetime
    change_reason: str = Field(min_length=1, max_length=4096)

    @field_validator("source_timezone", "reporting_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        candidate = value.strip()
        try:
            timezone = ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("timezone must be a known IANA timezone") from error
        return timezone.key

    @field_validator("currency_code")
    @classmethod
    def normalise_currency(cls, value: str) -> str:
        candidate = value.strip().upper()
        if _CURRENCY_PATTERN.fullmatch(candidate) is None:
            raise ValueError("currency_code must contain three ASCII letters")
        return candidate

    @field_validator("effective_at")
    @classmethod
    def require_aware_effective_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("effective_at must include a timezone offset")
        return value.astimezone(UTC)

    @field_validator("change_reason")
    @classmethod
    def strip_change_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("change_reason must not be blank")
        return stripped


class AuditEventResponse(BaseModel):
    id: int
    site_id: int | None
    actor_user_id: int | None
    actor_username: str | None
    event_type: str
    object_type: str
    object_id: str | None
    request_id: str | None
    redacted_payload: dict[str, object]
    occurred_at: datetime


class AuditEventPageResponse(BaseModel):
    items: list[AuditEventResponse]
    total: int
    limit: int
    offset: int
    next_offset: int | None


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("database returned an invalid timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    return _timestamp(value)


def _json_object(value: object) -> dict[str, object]:
    candidate: object = value
    if isinstance(value, str):
        candidate = json.loads(value)
    if not isinstance(candidate, dict):
        raise RuntimeError("database returned an invalid JSON object")
    return {str(key): item for key, item in candidate.items()}


def _binary(value: object, *, length: int) -> bytes:
    if isinstance(value, memoryview):
        raw = value.tobytes()
    elif isinstance(value, bytearray):
        raw = bytes(value)
    elif isinstance(value, bytes):
        raw = value
    else:
        raise RuntimeError("database returned an invalid binary value")
    if len(raw) != length:
        raise RuntimeError("database returned an invalid binary value length")
    return raw


def _command_digest(
    operation_kind: _AdminOperationKind,
    command: dict[str, object],
) -> bytes:
    encoded = json.dumps(
        {"operation_kind": operation_kind, "command": command},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).digest()


def _idempotency_conflict() -> ApiError:
    return ApiError(
        409,
        "idempotency_conflict",
        "The idempotency key is already bound to a different command or actor.",
    )


def _load_admin_operation(
    database_session: Session,
    *,
    operation_token: bytes,
) -> sa.RowMapping | None:
    return (
        database_session.execute(
            sa.text(
                """
                SELECT tokens.operation_kind, tokens.operation_digest,
                       tokens.actor_user_id,
                       results.response_schema_version,
                       results.response_status_code, results.response_payload
                FROM admin_operation_tokens AS tokens
                LEFT JOIN admin_operation_results AS results
                    ON results.operation_token = tokens.operation_token
                   AND results.operation_kind = tokens.operation_kind
                   AND results.operation_digest = tokens.operation_digest
                   AND results.actor_user_id = tokens.actor_user_id
                WHERE tokens.operation_token = :operation_token
                """
            ),
            {"operation_token": operation_token},
        )
        .mappings()
        .first()
    )


def _begin_admin_operation(
    database_session: Session,
    *,
    operation_token: UUID,
    operation_kind: _AdminOperationKind,
    operation_digest: bytes,
    actor_user_id: int,
    contains_secret: bool,
    expected_status_code: int,
) -> dict[str, object] | None:
    secret_marker = _SECRET_NOT_STORED if contains_secret else None
    inserted = database_session.execute(
        sa.text(
            """
            INSERT IGNORE INTO admin_operation_tokens (
                operation_token, operation_kind, operation_digest,
                actor_user_id, secret_verifier, registered_at
            ) VALUES (
                :operation_token, :operation_kind, :operation_digest,
                :actor_user_id, :secret_verifier, UTC_TIMESTAMP(6)
            )
            """
        ),
        {
            "operation_token": operation_token.bytes,
            "operation_kind": operation_kind,
            "operation_digest": operation_digest,
            "actor_user_id": actor_user_id,
            "secret_verifier": secret_marker,
        },
    )
    cursor_result = cast(CursorResult[Any], inserted)
    if cursor_result.rowcount == 1:
        return None

    # INSERT IGNORE waits for the unique token's owning transaction to finish.
    # Its committed token/result are immutable; a locking read would require
    # mutation privileges that the append-only runtime contract forbids.
    existing = _load_admin_operation(
        database_session,
        operation_token=operation_token.bytes,
    )
    if existing is None:
        raise RuntimeError("administrator operation token insertion was ignored")
    if (
        str(existing["operation_kind"]) != operation_kind
        or _binary(existing["operation_digest"], length=32) != operation_digest
        or int(existing["actor_user_id"]) != actor_user_id
    ):
        raise _idempotency_conflict()

    if existing["response_payload"] is None:
        raise RuntimeError("administrator operation has no frozen result")
    if (
        int(existing["response_schema_version"]) != 1
        or int(existing["response_status_code"]) != expected_status_code
    ):
        raise RuntimeError("administrator operation has an invalid frozen result")
    return _json_object(existing["response_payload"])


def _finish_admin_operation(
    database_session: Session,
    *,
    operation_token: UUID,
    operation_kind: _AdminOperationKind,
    operation_digest: bytes,
    actor_user_id: int,
    response_status_code: int,
    response: BaseModel,
) -> None:
    database_session.execute(
        sa.text(
            """
            INSERT INTO admin_operation_results (
                operation_token, operation_kind, operation_digest,
                actor_user_id, response_schema_version,
                response_status_code, response_payload, completed_at
            ) VALUES (
                :operation_token, :operation_kind, :operation_digest,
                :actor_user_id, 1, :response_status_code,
                :response_payload, UTC_TIMESTAMP(6)
            )
            """
        ),
        {
            "operation_token": operation_token.bytes,
            "operation_kind": operation_kind,
            "operation_digest": operation_digest,
            "actor_user_id": actor_user_id,
            "response_status_code": response_status_code,
            "response_payload": json.dumps(
                response.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
        },
    )


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if not isinstance(value, str):
        raise RuntimeError("request context has no request ID")
    return value


def _insert_audit_event(
    database_session: Session,
    *,
    request: Request,
    principal: Principal,
    event_type: str,
    object_type: str,
    object_id: int,
    site_id: int | None,
    payload: dict[str, object],
) -> None:
    database_session.execute(
        sa.text(
            """
            INSERT INTO audit_events (
                site_id, actor_user_id, event_type, object_type, object_id,
                request_id, redacted_payload, occurred_at
            ) VALUES (
                :site_id, :actor_user_id, :event_type, :object_type, :object_id,
                :request_id, :redacted_payload, UTC_TIMESTAMP(6)
            )
            """
        ),
        {
            "site_id": site_id,
            "actor_user_id": principal.user_id,
            "event_type": event_type,
            "object_type": object_type,
            "object_id": str(object_id),
            "request_id": _request_id(request),
            "redacted_payload": json.dumps(payload, sort_keys=True),
        },
    )


def _user_response(row: sa.RowMapping, roles: list[str]) -> UserResponse:
    return UserResponse(
        id=int(row["id"]),
        username=str(row["username_normalized"]),
        display_name=str(row["display_name"]),
        email=str(row["email"]) if row["email"] is not None else None,
        status=cast(_UserStatus, row["status"]),
        roles=roles,
        last_login_at=_optional_timestamp(row["last_login_at"]),
        created_at=_timestamp(row["created_at"]),
        updated_at=_timestamp(row["updated_at"]),
    )


def _site_config_response(row: sa.RowMapping) -> SiteConfigVersionResponse:
    return SiteConfigVersionResponse(
        id=int(row["id"]),
        site_id=int(row["site_id"]),
        site_code=str(row["site_code"]),
        site_display_name=str(row["site_display_name"]),
        version_number=int(row["version_number"]),
        source_timezone=str(row["source_timezone"]),
        reporting_timezone=str(row["reporting_timezone"]),
        currency_code=str(row["currency_code"]),
        effective_at=_timestamp(row["effective_at"]),
        change_reason=(
            str(row["change_reason"]) if row["change_reason"] is not None else None
        ),
        created_by_user_id=(
            int(row["created_by_user_id"])
            if row["created_by_user_id"] is not None
            else None
        ),
        created_at=_timestamp(row["created_at"]),
        is_current=bool(row["is_current"]),
    )


def _load_role_rows(
    database_session: Session,
    role_codes: list[str],
) -> list[sa.RowMapping]:
    statement = sa.text(
        "SELECT id, code FROM roles WHERE code IN :role_codes ORDER BY id"
    ).bindparams(sa.bindparam("role_codes", expanding=True))
    rows = list(
        database_session.execute(
            statement,
            {"role_codes": role_codes},
        )
        .mappings()
        .all()
    )
    if {str(row["code"]) for row in rows} != set(role_codes):
        raise ApiError(422, "invalid_roles", "One or more roles are invalid.")
    return rows


def _load_user_response(
    database_session: Session,
    *,
    user_id: int,
    roles: list[str],
) -> UserResponse:
    row = (
        database_session.execute(
            sa.text(
                """
                SELECT id, username_normalized, display_name, email, status,
                       last_login_at, created_at, updated_at
                FROM users
                WHERE id = :user_id
                """
            ),
            {"user_id": user_id},
        )
        .mappings()
        .one()
    )
    return _user_response(row, roles)


@router.get("/users", response_model=list[UserResponse])
def list_users(
    _principal: _Admin,
    database_session: _DatabaseSession,
) -> list[UserResponse]:
    user_rows = (
        database_session.execute(
            sa.text(
                """
            SELECT id, username_normalized, display_name, email, status,
                   last_login_at, created_at, updated_at
            FROM users
            ORDER BY id
            """
            )
        )
        .mappings()
        .all()
    )
    role_rows = database_session.execute(
        sa.text(
            """
            SELECT assignments.user_id, roles.code
            FROM user_roles AS assignments
            INNER JOIN roles ON roles.id = assignments.role_id
            ORDER BY assignments.user_id, roles.id
            """
        )
    ).mappings()
    roles_by_user: defaultdict[int, list[str]] = defaultdict(list)
    for role_row in role_rows:
        roles_by_user[int(role_row["user_id"])].append(str(role_row["code"]))
    return [_user_response(row, roles_by_user[int(row["id"])]) for row in user_rows]


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: CreateUserRequest,
    request: Request,
    principal: _WritingAdmin,
    database_session: _DatabaseSession,
    idempotency_key: _IdempotencyKey,
) -> UserResponse:
    try:
        username = normalise_username(payload.username)
    except ValueError as error:
        raise ApiError(422, "invalid_username", "The username is invalid.") from error
    operation_kind: _AdminOperationKind = "create_user"
    operation_digest = _command_digest(
        operation_kind,
        {
            "username": username,
            "display_name": payload.display_name,
            "email": payload.email,
            "roles": sorted(payload.roles),
            "status": payload.status,
            "password_present": True,
        },
    )
    replay = _begin_admin_operation(
        database_session,
        operation_token=idempotency_key,
        operation_kind=operation_kind,
        operation_digest=operation_digest,
        actor_user_id=principal.user_id,
        contains_secret=True,
        expected_status_code=status.HTTP_201_CREATED,
    )
    if replay is not None:
        return UserResponse.model_validate(replay)
    password_hash = hash_password(payload.password)

    role_rows = _load_role_rows(database_session, payload.roles)

    existing_user = database_session.execute(
        sa.text(
            """
            SELECT id
            FROM users
            WHERE username_normalized = :username
               OR (:email IS NOT NULL AND email = :email)
            LIMIT 1
            """
        ),
        {"username": username, "email": payload.email},
    ).first()
    if existing_user is not None:
        raise ApiError(
            409,
            "user_conflict",
            "An account with this username or email already exists.",
        )

    try:
        result = database_session.execute(
            sa.text(
                """
                INSERT INTO users (
                    username_normalized, display_name, email, password_hash,
                    status, created_at, updated_at
                ) VALUES (
                    :username, :display_name, :email, :password_hash,
                    :status, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                )
                """
            ),
            {
                "username": username,
                "display_name": payload.display_name,
                "email": payload.email,
                "password_hash": password_hash,
                "status": payload.status,
            },
        )
        cursor_result = cast(CursorResult[Any], result)
        if cursor_result.lastrowid is None:
            raise RuntimeError("database did not return the created user ID")
        user_id = int(cursor_result.lastrowid)
        database_session.execute(
            sa.text(
                """
                INSERT INTO user_roles (
                    user_id, role_id, assigned_by, assigned_at
                ) VALUES (
                    :user_id, :role_id, :assigned_by, UTC_TIMESTAMP(6)
                )
                """
            ),
            [
                {
                    "user_id": user_id,
                    "role_id": int(row["id"]),
                    "assigned_by": principal.user_id,
                }
                for row in role_rows
            ],
        )
    except IntegrityError as error:
        raise ApiError(
            409,
            "user_conflict",
            "The account conflicts with an existing user.",
        ) from error

    assigned_roles = [str(row["code"]) for row in role_rows]
    _insert_audit_event(
        database_session,
        request=request,
        principal=principal,
        event_type="admin.user_created",
        object_type="user",
        object_id=user_id,
        site_id=None,
        payload={
            "username": username,
            "roles": assigned_roles,
            "status": payload.status,
            "email_present": payload.email is not None,
        },
    )
    response = _load_user_response(
        database_session,
        user_id=user_id,
        roles=assigned_roles,
    )
    _finish_admin_operation(
        database_session,
        operation_token=idempotency_key,
        operation_kind=operation_kind,
        operation_digest=operation_digest,
        actor_user_id=principal.user_id,
        response_status_code=status.HTTP_201_CREATED,
        response=response,
    )
    return response


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    request: Request,
    principal: _WritingAdmin,
    database_session: _DatabaseSession,
    idempotency_key: _IdempotencyKey,
) -> UserResponse:
    changed_fields = payload.model_fields_set - {"expected_updated_at"}
    canonical_changes: dict[str, object] = {}
    if "display_name" in changed_fields:
        canonical_changes["display_name"] = payload.display_name
    if "email" in changed_fields:
        canonical_changes["email"] = payload.email
    if "status" in changed_fields:
        canonical_changes["status"] = payload.status
    if "roles" in changed_fields:
        canonical_changes["roles"] = sorted(payload.roles or [])
    if "new_password" in changed_fields:
        canonical_changes["password_reset"] = True

    operation_kind: _AdminOperationKind = "update_user"
    operation_digest = _command_digest(
        operation_kind,
        {
            "user_id": user_id,
            "expected_updated_at": payload.expected_updated_at.isoformat(
                timespec="microseconds"
            ),
            "changes": canonical_changes,
        },
    )
    supplied_secret = payload.new_password if "new_password" in changed_fields else None

    # Roles are read-only seed data for the runtime account. Serialize updates
    # on the mutable administrator records before locking a target or inserting
    # the operation token (whose actor FK also locks a users record).
    admin_role_id = database_session.scalar(
        sa.text("SELECT id FROM roles WHERE code = 'admin'")
    )
    if admin_role_id is None:
        raise RuntimeError("the administrator role is unavailable")
    active_admin_ids = tuple(
        int(value)
        for value in database_session.scalars(
            sa.text(
                """
                SELECT users.id
                FROM users
                INNER JOIN user_roles AS assignments
                    ON assignments.user_id = users.id
                WHERE assignments.role_id = :admin_role_id
                  AND users.status = 'active'
                ORDER BY users.id
                FOR UPDATE
                """
            ),
            {"admin_role_id": int(admin_role_id)},
        )
    )
    replay = _begin_admin_operation(
        database_session,
        operation_token=idempotency_key,
        operation_kind=operation_kind,
        operation_digest=operation_digest,
        actor_user_id=principal.user_id,
        contains_secret=supplied_secret is not None,
        expected_status_code=status.HTTP_200_OK,
    )
    if replay is not None:
        return UserResponse.model_validate(replay)
    new_password_hash = (
        hash_password(supplied_secret) if supplied_secret is not None else None
    )

    target = (
        database_session.execute(
            sa.text(
                """
                SELECT id, username_normalized, display_name, email,
                       password_hash, status, last_login_at,
                       created_at, updated_at
                FROM users
                WHERE id = :user_id
                FOR UPDATE
                """
            ),
            {"user_id": user_id},
        )
        .mappings()
        .first()
    )
    if target is None:
        raise ApiError(404, "user_not_found", "The requested user was not found.")
    if _timestamp(target["updated_at"]) != payload.expected_updated_at:
        raise ApiError(
            409,
            "user_version_conflict",
            "The user changed after it was loaded. Refresh and retry.",
        )

    current_role_rows = list(
        database_session.execute(
            sa.text(
                """
                SELECT roles.id, roles.code
                FROM user_roles AS assignments
                INNER JOIN roles ON roles.id = assignments.role_id
                WHERE assignments.user_id = :user_id
                ORDER BY roles.id
                """
            ),
            {"user_id": user_id},
        )
        .mappings()
        .all()
    )
    current_roles = [str(row["code"]) for row in current_role_rows]
    if "roles" in changed_fields:
        assert payload.roles is not None
        assigned_role_rows = _load_role_rows(database_session, payload.roles)
    else:
        assigned_role_rows = current_role_rows
    assigned_roles = [str(row["code"]) for row in assigned_role_rows]

    new_status = payload.status if "status" in changed_fields else str(target["status"])
    was_active_admin = str(target["status"]) == "active" and "admin" in current_roles
    remains_active_admin = new_status == "active" and "admin" in assigned_roles
    if was_active_admin and not remains_active_admin and active_admin_ids == (user_id,):
        raise ApiError(
            409,
            "last_active_admin",
            "The final active administrator cannot be disabled or demoted.",
        )

    new_display_name = (
        payload.display_name
        if "display_name" in changed_fields
        else str(target["display_name"])
    )
    new_email = payload.email if "email" in changed_fields else target["email"]
    password_hash = (
        new_password_hash
        if "new_password" in changed_fields
        else str(target["password_hash"])
    )
    assert new_display_name is not None
    assert new_status in {"active", "disabled", "locked"}
    assert password_hash is not None
    expected_updated_at = payload.expected_updated_at.replace(tzinfo=None)
    try:
        updated = database_session.execute(
            sa.text(
                """
                UPDATE users
                SET display_name = :display_name,
                    email = :email,
                    password_hash = :password_hash,
                    status = :status,
                    updated_at = GREATEST(
                        UTC_TIMESTAMP(6),
                        TIMESTAMPADD(MICROSECOND, 1, updated_at)
                    )
                WHERE id = :user_id
                  AND updated_at = :expected_updated_at
                """
            ),
            {
                "display_name": new_display_name,
                "email": new_email,
                "password_hash": password_hash,
                "status": new_status,
                "user_id": user_id,
                "expected_updated_at": expected_updated_at,
            },
        )
        if cast(CursorResult[Any], updated).rowcount != 1:
            raise ApiError(
                409,
                "user_version_conflict",
                "The user changed after it was loaded. Refresh and retry.",
            )
        if "roles" in changed_fields:
            database_session.execute(
                sa.text("DELETE FROM user_roles WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            database_session.execute(
                sa.text(
                    """
                    INSERT INTO user_roles (
                        user_id, role_id, assigned_by, assigned_at
                    ) VALUES (
                        :user_id, :role_id, :assigned_by, UTC_TIMESTAMP(6)
                    )
                    """
                ),
                [
                    {
                        "user_id": user_id,
                        "role_id": int(row["id"]),
                        "assigned_by": principal.user_id,
                    }
                    for row in assigned_role_rows
                ],
            )
    except IntegrityError as error:
        raise ApiError(
            409,
            "user_conflict",
            "The account conflicts with an existing user.",
        ) from error

    password_was_reset = "new_password" in changed_fields
    if password_was_reset or new_status != "active":
        database_session.execute(
            sa.text(
                """
                UPDATE auth_sessions
                SET revoked_at = UTC_TIMESTAMP(6),
                    revoked_reason = 'administrator_user_update'
                WHERE user_id = :user_id
                  AND revoked_at IS NULL
                """
            ),
            {"user_id": user_id},
        )

    audit_payload: dict[str, object] = {
        "changed_fields": sorted(
            "password" if field_name == "new_password" else field_name
            for field_name in changed_fields
        ),
        "password_reset": password_was_reset,
    }
    if "email" in changed_fields:
        audit_payload["email_present"] = new_email is not None
    if "status" in changed_fields:
        audit_payload["status"] = new_status
    if "roles" in changed_fields:
        audit_payload["roles"] = assigned_roles
    _insert_audit_event(
        database_session,
        request=request,
        principal=principal,
        event_type="admin.user_updated",
        object_type="user",
        object_id=user_id,
        site_id=None,
        payload=audit_payload,
    )
    response = _load_user_response(
        database_session,
        user_id=user_id,
        roles=assigned_roles,
    )
    _finish_admin_operation(
        database_session,
        operation_token=idempotency_key,
        operation_kind=operation_kind,
        operation_digest=operation_digest,
        actor_user_id=principal.user_id,
        response_status_code=status.HTTP_200_OK,
        response=response,
    )
    return response


@router.get(
    "/site-config-versions",
    response_model=list[SiteConfigVersionResponse],
)
def list_site_config_versions(
    _principal: _Admin,
    database_session: _DatabaseSession,
    site_id: Annotated[int | None, Query(ge=1)] = None,
) -> list[SiteConfigVersionResponse]:
    rows = database_session.execute(
        sa.text(
            """
            SELECT configs.id, configs.site_id, sites.code AS site_code,
                   sites.display_name AS site_display_name,
                   configs.version_number, configs.source_timezone,
                   configs.reporting_timezone, configs.currency_code,
                   configs.effective_at, configs.change_reason,
                   configs.created_by_user_id, configs.created_at,
                   current.current_config_version_id = configs.id AS is_current
            FROM site_config_versions AS configs
            INNER JOIN sites ON sites.id = configs.site_id
            LEFT JOIN site_current_configs AS current
                ON current.site_id = configs.site_id
            WHERE (:site_id IS NULL OR configs.site_id = :site_id)
            ORDER BY configs.site_id, configs.version_number DESC
            """
        ),
        {"site_id": site_id},
    ).mappings()
    return [_site_config_response(row) for row in rows]


@router.post(
    "/site-config-versions",
    response_model=SiteConfigVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_site_config_version(
    payload: CreateSiteConfigVersionRequest,
    request: Request,
    principal: _WritingAdmin,
    database_session: _DatabaseSession,
    idempotency_key: _IdempotencyKey,
) -> SiteConfigVersionResponse:
    operation_kind: _AdminOperationKind = "create_site_config_version"
    operation_digest = _command_digest(
        operation_kind,
        {
            "site_id": payload.site_id,
            "source_timezone": payload.source_timezone,
            "reporting_timezone": payload.reporting_timezone,
            "currency_code": payload.currency_code,
            "effective_at": payload.effective_at.isoformat(timespec="microseconds"),
            "change_reason": payload.change_reason,
        },
    )
    replay = _begin_admin_operation(
        database_session,
        operation_token=idempotency_key,
        operation_kind=operation_kind,
        operation_digest=operation_digest,
        actor_user_id=principal.user_id,
        contains_secret=False,
        expected_status_code=status.HTTP_201_CREATED,
    )
    if replay is not None:
        return SiteConfigVersionResponse.model_validate(replay)

    site = (
        database_session.execute(
            sa.text(
                """
            SELECT id, code, display_name
            FROM sites
            WHERE id = :site_id
            FOR UPDATE
            """
            ),
            {"site_id": payload.site_id},
        )
        .mappings()
        .first()
    )
    if site is None:
        raise ApiError(404, "site_not_found", "The requested site was not found.")

    current_version_number = database_session.scalar(
        sa.text(
            """
            SELECT COALESCE(MAX(version_number), 0)
            FROM site_config_versions
            WHERE site_id = :site_id
            """
        ),
        {"site_id": payload.site_id},
    )
    version_number = int(current_version_number or 0) + 1
    try:
        result = database_session.execute(
            sa.text(
                """
                INSERT INTO site_config_versions (
                    site_id, version_number, source_timezone,
                    reporting_timezone, currency_code, effective_at,
                    change_reason, created_by_user_id, created_at
                ) VALUES (
                    :site_id, :version_number, :source_timezone,
                    :reporting_timezone, :currency_code, :effective_at,
                    :change_reason, :created_by_user_id, UTC_TIMESTAMP(6)
                )
                """
            ),
            {
                "site_id": payload.site_id,
                "version_number": version_number,
                "source_timezone": payload.source_timezone,
                "reporting_timezone": payload.reporting_timezone,
                "currency_code": payload.currency_code,
                "effective_at": payload.effective_at.replace(tzinfo=None),
                "change_reason": payload.change_reason,
                "created_by_user_id": principal.user_id,
            },
        )
        cursor_result = cast(CursorResult[Any], result)
        if cursor_result.lastrowid is None:
            raise RuntimeError("database did not return the site configuration ID")
        config_id = int(cursor_result.lastrowid)
        database_session.execute(
            sa.text(
                """
                INSERT INTO site_current_configs (
                    site_id, current_config_version_id,
                    updated_by_user_id, updated_at
                ) VALUES (
                    :site_id, :config_id, :actor_user_id, UTC_TIMESTAMP(6)
                )
                ON DUPLICATE KEY UPDATE
                    current_config_version_id = VALUES(current_config_version_id),
                    updated_by_user_id = VALUES(updated_by_user_id),
                    updated_at = UTC_TIMESTAMP(6)
                """
            ),
            {
                "site_id": payload.site_id,
                "config_id": config_id,
                "actor_user_id": principal.user_id,
            },
        )
    except IntegrityError as error:
        raise ApiError(
            409,
            "site_config_conflict",
            "The site configuration conflicts with current state.",
        ) from error

    _insert_audit_event(
        database_session,
        request=request,
        principal=principal,
        event_type="admin.site_config_created",
        object_type="site_config_version",
        object_id=config_id,
        site_id=payload.site_id,
        payload={
            "version_number": version_number,
            "source_timezone": payload.source_timezone,
            "reporting_timezone": payload.reporting_timezone,
            "currency_code": payload.currency_code,
            "effective_at": payload.effective_at.isoformat(),
            "change_reason": payload.change_reason,
        },
    )
    row = (
        database_session.execute(
            sa.text(
                """
            SELECT configs.id, configs.site_id, sites.code AS site_code,
                   sites.display_name AS site_display_name,
                   configs.version_number, configs.source_timezone,
                   configs.reporting_timezone, configs.currency_code,
                   configs.effective_at, configs.change_reason,
                   configs.created_by_user_id, configs.created_at,
                   current.current_config_version_id = configs.id AS is_current
            FROM site_config_versions AS configs
            INNER JOIN sites ON sites.id = configs.site_id
            INNER JOIN site_current_configs AS current
                ON current.site_id = configs.site_id
            WHERE configs.id = :config_id
            """
            ),
            {"config_id": config_id},
        )
        .mappings()
        .one()
    )
    response = _site_config_response(row)
    _finish_admin_operation(
        database_session,
        operation_token=idempotency_key,
        operation_kind=operation_kind,
        operation_digest=operation_digest,
        actor_user_id=principal.user_id,
        response_status_code=status.HTTP_201_CREATED,
        response=response,
    )
    return response


@router.get("/audit-events", response_model=AuditEventPageResponse)
def list_audit_events(
    _principal: _Admin,
    database_session: _DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    event_type: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    actor_user_id: Annotated[int | None, Query(ge=1)] = None,
    site_id: Annotated[int | None, Query(ge=1)] = None,
) -> AuditEventPageResponse:
    filters = {
        "event_type": event_type,
        "actor_user_id": actor_user_id,
        "site_id": site_id,
    }
    where_clause = """
        WHERE (:event_type IS NULL OR events.event_type = :event_type)
          AND (:actor_user_id IS NULL OR events.actor_user_id = :actor_user_id)
          AND (:site_id IS NULL OR events.site_id = :site_id)
    """
    total = int(
        database_session.scalar(
            sa.text(f"SELECT COUNT(*) FROM audit_events AS events {where_clause}"),
            filters,
        )
        or 0
    )
    rows = database_session.execute(
        sa.text(
            f"""
            SELECT events.id, events.site_id, events.actor_user_id,
                   users.username_normalized AS actor_username,
                   events.event_type, events.object_type, events.object_id,
                   events.request_id, events.redacted_payload,
                   events.occurred_at
            FROM audit_events AS events
            LEFT JOIN users ON users.id = events.actor_user_id
            {where_clause}
            ORDER BY events.occurred_at DESC, events.id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {**filters, "limit": limit, "offset": offset},
    ).mappings()
    items = [
        AuditEventResponse(
            id=int(row["id"]),
            site_id=int(row["site_id"]) if row["site_id"] is not None else None,
            actor_user_id=(
                int(row["actor_user_id"]) if row["actor_user_id"] is not None else None
            ),
            actor_username=(
                str(row["actor_username"])
                if row["actor_username"] is not None
                else None
            ),
            event_type=str(row["event_type"]),
            object_type=str(row["object_type"]),
            object_id=(str(row["object_id"]) if row["object_id"] is not None else None),
            request_id=(
                str(row["request_id"]) if row["request_id"] is not None else None
            ),
            redacted_payload=_json_object(row["redacted_payload"]),
            occurred_at=_timestamp(row["occurred_at"]),
        )
        for row in rows
    ]
    next_offset = offset + len(items) if offset + len(items) < total else None
    return AuditEventPageResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
