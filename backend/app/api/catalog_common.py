"""Shared strict catalog HTTP models, dependencies, and safe error mapping."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Never
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from app.api.dependencies import (
    SESSION_COOKIE_NAME,
    get_current_site_context,
    get_database_engine,
    require_csrf_principal,
)
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.catalog.models import StrictCatalogModel
from app.site_context import CurrentSiteContext


class CatalogMessageResponse(StrictCatalogModel):
    status: str


def catalog_write_context(
    context: Annotated[CurrentSiteContext, Depends(get_current_site_context)],
    principal: Annotated[Principal, Depends(require_csrf_principal)],
) -> CurrentSiteContext:
    if principal.user_id != context.principal_user_id:
        raise ApiError(403, "role_forbidden", "Permission was denied.")
    return context


CatalogReadContext = Annotated[CurrentSiteContext, Depends(get_current_site_context)]
CatalogWriteContext = Annotated[CurrentSiteContext, Depends(catalog_write_context)]
CatalogEngine = Annotated[Engine, Depends(get_database_engine)]
CatalogIdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


def require_catalog_session(request: Request) -> None:
    """Fail before database setup when the session cookie is absent."""

    if not request.cookies.get(SESSION_COOKIE_NAME):
        raise ApiError(401, "authentication_required", "Authentication is required.")


def require_matching_token(header_token: UUID, body_token: UUID) -> None:
    if header_token != body_token:
        raise ApiError(
            422,
            "idempotency_key_mismatch",
            "Idempotency-Key must match operation_token.",
        )


def require_catalog_manager(context: CurrentSiteContext) -> None:
    if context.principal_roles.isdisjoint({"admin", "data_manager"}):
        raise ApiError(403, "role_forbidden", "Permission was denied.")


def require_catalog_admin(context: CurrentSiteContext) -> None:
    if "admin" not in context.principal_roles:
        raise ApiError(403, "catalog_admin_required", "Permission was denied.")


def _wire(value: object) -> object:
    if isinstance(value, BaseModel):
        return _wire(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _wire(asdict(value))
    if isinstance(value, dict):
        return {str(key): _wire(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_wire(item) for item in value]
    if isinstance(value, bytes):
        return "sha256:" + value.hex()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Enum)):
        return str(value)
    return value


def catalog_json(value: object, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=_wire(value))


def raise_catalog_error(error: Exception) -> Never:
    raise catalog_error(error) from error


_CONFLICT_CODES = frozenset(
    {
        "catalog_workflow_revision_conflict",
        "catalog_publication_revision_conflict",
        "catalog_projection_stale",
        "catalog_parse_attempt_stale",
        "idempotency_key_reused",
        "outcome_unknown",
        "catalog_export_not_ready",
        "catalog_style_revision_conflict",
        "catalog_style_change_revision_conflict",
        "catalog_category_conflict",
        "catalog_draft_reservation_conflict",
    }
)
_FORBIDDEN_CODES = frozenset(
    {
        "catalog_admin_required",
        "catalog_scope_permission_denied",
        "catalog_approval_forbidden",
    }
)
_INVALID_CODES = frozenset(
    {
        "catalog_validation_failed",
        "catalog_decisions_invalid",
        "catalog_scope_confirmation_invalid",
        "catalog_category_invalid",
        "catalog_category_not_selectable",
        "catalog_style_change_invalid",
        "catalog_unmatched_range_invalid",
    }
)


def catalog_error(error: Exception) -> ApiError:
    if getattr(error, "reason", None) == "catalog_text_cell_numeric":
        return ApiError(
            422,
            "catalog_text_cell_numeric",
            "工作簿中的文本字段被保存为数字。"
            "请将款号、身份编号等字段恢复为文本后上传。不要改动身份列。",
        )
    code = getattr(error, "code", None)
    if not isinstance(code, str):
        return ApiError(
            500,
            "catalog_internal_error",
            "The catalog request could not be completed.",
        )
    if code in _CONFLICT_CODES:
        return ApiError(409, code, "The catalog resource changed; reload and retry.")
    if code in _FORBIDDEN_CODES:
        return ApiError(403, code, "Permission to perform this action was denied.")
    if code in _INVALID_CODES:
        return ApiError(422, code, "The catalog request data is invalid.")
    if code.endswith("not_found"):
        return ApiError(404, code, "The requested catalog resource was not found.")
    return ApiError(409, code, "The catalog operation could not be completed.")


__all__ = (
    "CatalogEngine",
    "CatalogIdempotencyKey",
    "CatalogMessageResponse",
    "CatalogReadContext",
    "CatalogWriteContext",
    "catalog_error",
    "catalog_json",
    "catalog_write_context",
    "raise_catalog_error",
    "require_catalog_admin",
    "require_catalog_manager",
    "require_catalog_session",
    "require_matching_token",
)
