"""Governed category and single-style change routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BeforeValidator, Field
from starlette.responses import Response

from app.api.catalog_common import (
    CatalogEngine,
    CatalogIdempotencyKey,
    CatalogReadContext,
    CatalogWriteContext,
    catalog_json,
    raise_catalog_error,
    require_catalog_admin,
    require_catalog_manager,
    require_catalog_session,
    require_matching_token,
)
from app.catalog.category_service import MySqlCatalogCategoryService
from app.catalog.change_service import MySqlCatalogStyleChangeService
from app.catalog.models import CatalogWireUuid, StrictCatalogModel

router = APIRouter(
    prefix="/api/catalog",
    tags=["catalog"],
    dependencies=[Depends(require_catalog_session)],
)


def _json_array_to_tuple(value: object) -> object:
    return tuple(value) if isinstance(value, list) else value


CategoryAliases = Annotated[tuple[str, ...], BeforeValidator(_json_array_to_tuple)]


class CategoryCreateRequest(StrictCatalogModel):
    parent_category_id: int | None = Field(default=None, ge=1)
    operation_token: CatalogWireUuid
    code: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    aliases: CategoryAliases = Field(default=(), max_length=30)


class CategoryUpdateRequest(StrictCatalogModel):
    parent_category_id: int | None = Field(default=None, ge=1)
    operation_token: CatalogWireUuid
    code: str | None = Field(default=None, min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    aliases: CategoryAliases = Field(default=(), max_length=30)
    status: str


class StyleChangeDraftRequest(StrictCatalogModel):
    operation_token: CatalogWireUuid
    expected_catalog_publication_revision: int = Field(ge=0)
    expected_style_revision: int = Field(ge=1)
    standard_name: str = Field(min_length=1, max_length=255)
    category_action: str
    category_id: int | None = Field(default=None, ge=1)


class StyleChangeApproveRequest(StrictCatalogModel):
    operation_token: CatalogWireUuid
    expected_draft_revision: int = Field(ge=1)
    expected_catalog_publication_revision: int = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)


@router.get("/categories")
def list_categories(context: CatalogReadContext, engine: CatalogEngine) -> Response:
    try:
        return catalog_json(
            {
                "categories": MySqlCatalogCategoryService(engine).list(
                    site_id=context.site_id
                )
            }
        )
    except Exception as error:
        raise_catalog_error(error)


@router.post("/categories")
def create_category(
    request: CategoryCreateRequest,
    idempotency_key: CatalogIdempotencyKey,
    context: CatalogWriteContext,
    engine: CatalogEngine,
) -> Response:
    require_catalog_admin(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        value = MySqlCatalogCategoryService(engine).create(
            site_id=context.site_id,
            actor_user_id=context.principal_user_id,
            operation_token=UUID(str(request.operation_token)),
            code=request.code,
            parent_category_id=request.parent_category_id,
            display_name=request.display_name,
            aliases=request.aliases,
        )
        return catalog_json(value, status_code=201)
    except Exception as error:
        raise_catalog_error(error)


@router.put("/categories/{category_id}")
def update_category(
    category_id: int,
    request: CategoryUpdateRequest,
    idempotency_key: CatalogIdempotencyKey,
    context: CatalogWriteContext,
    engine: CatalogEngine,
) -> Response:
    require_catalog_admin(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        return catalog_json(
            MySqlCatalogCategoryService(engine).update(
                site_id=context.site_id,
                category_id=category_id,
                code=request.code,
                parent_category_id=request.parent_category_id,
                update_parent="parent_category_id" in request.model_fields_set,
                actor_user_id=context.principal_user_id,
                operation_token=UUID(str(request.operation_token)),
                display_name=request.display_name,
                status=request.status,
                aliases=request.aliases,
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.post("/styles/{style_id}/change-drafts")
def create_style_change(
    style_id: int,
    request: StyleChangeDraftRequest,
    idempotency_key: CatalogIdempotencyKey,
    context: CatalogWriteContext,
    engine: CatalogEngine,
) -> Response:
    require_catalog_manager(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        result = MySqlCatalogStyleChangeService(engine).create_draft(
            site_id=context.site_id,
            style_id=style_id,
            actor_user_id=context.principal_user_id,
            operation_token=UUID(str(request.operation_token)),
            expected_catalog_publication_revision=request.expected_catalog_publication_revision,
            expected_style_revision=request.expected_style_revision,
            standard_name=request.standard_name,
            category_action=request.category_action,
            category_id=request.category_id,
        )
        return catalog_json(result, status_code=201)
    except Exception as error:
        raise_catalog_error(error)


@router.get("/style-change-drafts/{draft_id}")
def preview_style_change(
    draft_id: int, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    try:
        return catalog_json(
            MySqlCatalogStyleChangeService(engine).preview(
                site_id=context.site_id, draft_id=draft_id
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.post("/style-change-drafts/{draft_id}/approve")
def approve_style_change(
    draft_id: int,
    request: StyleChangeApproveRequest,
    idempotency_key: CatalogIdempotencyKey,
    context: CatalogWriteContext,
    engine: CatalogEngine,
) -> Response:
    require_catalog_manager(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        return catalog_json(
            MySqlCatalogStyleChangeService(engine).approve(
                site_id=context.site_id,
                draft_id=draft_id,
                actor_user_id=context.principal_user_id,
                operation_token=UUID(str(request.operation_token)),
                expected_draft_revision=request.expected_draft_revision,
                expected_catalog_publication_revision=request.expected_catalog_publication_revision,
                reason=request.reason,
            )
        )
    except Exception as error:
        raise_catalog_error(error)
