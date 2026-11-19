# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
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
    if isinstance(error, ApiError):
        raise error
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
    code = getattr(error, "code", None)
    if code in {"production_source_invalid", "catalog_workbook_format_invalid"}:
        return ApiError(422, code, error.public_message)  # type: ignore[attr-defined]
    if code == "catalog_workbook_unsafe":
        reason = str(getattr(error, "reason", ""))
        message = {
            "ooxml_hidden_content": (
                "工作簿含隐藏行或列，请取消隐藏并核对全部内容后上传。"
            ),
            "ooxml_worksheet_unsafe_content": (
                "工作簿含公式、合并单元格、链接或嵌入内容，"
                "请使用原六表模板并粘贴明确的值。"
            ),
            "ooxml_external_relationship": (
                "工作簿含外部链接，请移除链接，保留明确文本后上传。"
            ),
            "catalog_sheet_contract_mismatch": (
                "工作簿结构或生成信息与模板不一致，"
                "请重新下载六表模板，保留表头和身份列。"
            ),
        }.get(
            reason,
            "工作簿格式未通过检查，请使用未加密的原六表XLSX模板，保留工作表名称、表头和生成信息。",
        )
        return ApiError(422, code, message)
    if code in {
        "catalog_upload_metadata_invalid",
        "catalog_workbook_capacity_exceeded",
    }:
        return ApiError(
            422,
            code,
            "文件类型、名称或容量不符合要求，请使用当前导出的XLSX模板；大批量资料请改用在线审核。",
        )
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
            "暂时无法完成商品主档操作，请保留输入并稍后重试。",
        )
    if code in _CONFLICT_CODES:
        return ApiError(409, code, "商品目录或批次已变化，请刷新核对后重试。")
    if code in _FORBIDDEN_CODES:
        return ApiError(403, code, "当前账号没有此操作权限，请联系管理员。")
    if code in _INVALID_CODES:
        return ApiError(422, code, "资料校验未通过，请核对页面标记的字段后重新提交。")
    if code.endswith("not_found"):
        return ApiError(404, code, "未找到该商品或批次，请返回列表重新选择。")
    return ApiError(409, code, "操作未完成，请保留资料，刷新核对批次状态后重试。")


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
