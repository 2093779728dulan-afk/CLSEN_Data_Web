"""Seller-account source-scope catalog API."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field

from app.api.catalog_common import (
    CatalogEngine,
    CatalogIdempotencyKey,
    CatalogReadContext,
    CatalogWriteContext,
    catalog_error,
    require_catalog_session,
    require_matching_token,
)
from app.catalog.models import CatalogWireUuid, StrictCatalogModel
from app.catalog.scope_repository import MySqlCatalogScopeRepository
from app.catalog.scope_service import (
    CatalogScopeService,
    ConfirmScopeCommand,
)

router = APIRouter(
    prefix="/api/catalog",
    tags=["catalog"],
    dependencies=[Depends(require_catalog_session)],
)


class CatalogScopePermissionsResponse(StrictCatalogModel):
    can_confirm: bool


class CatalogScopeStatusResponse(StrictCatalogModel):
    status: Literal["unconfirmed", "confirmed"]
    report_source_scope_id: int | None
    seller_account_display_name: str | None
    marketplace_scope_code: Literal["amazon_us"]
    site_config_version_id: int
    site_config_revision: int
    permissions: CatalogScopePermissionsResponse


class ConfirmCatalogScopeRequest(StrictCatalogModel):
    operation_token: CatalogWireUuid
    expected_site_config_revision: int = Field(ge=1)
    seller_account_scope_key: str = Field(min_length=1, max_length=255)
    seller_account_display_name: str = Field(min_length=1, max_length=128)
    marketplace_scope_code: Literal["amazon_us"]
    reason: str = Field(min_length=1, max_length=1000)


def _response(value: object) -> CatalogScopeStatusResponse:
    return CatalogScopeStatusResponse.model_validate(value, from_attributes=True)


@router.get("/source-scope", response_model=CatalogScopeStatusResponse)
def get_catalog_scope(
    context: CatalogReadContext,
    engine: CatalogEngine,
) -> CatalogScopeStatusResponse:
    try:
        return _response(
            CatalogScopeService(MySqlCatalogScopeRepository(engine)).status(context)
        )
    except Exception as error:
        raise catalog_error(error) from error


@router.post("/source-scope/confirm", response_model=CatalogScopeStatusResponse)
def confirm_catalog_scope(
    request: ConfirmCatalogScopeRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> CatalogScopeStatusResponse:
    require_matching_token(idempotency_key, request.operation_token)
    try:
        value = CatalogScopeService(MySqlCatalogScopeRepository(engine)).confirm(
            context,
            ConfirmScopeCommand(**request.model_dump()),
        )
        return _response(value)
    except Exception as error:
        raise catalog_error(error) from error


__all__ = ("ConfirmCatalogScopeRequest", "router")
