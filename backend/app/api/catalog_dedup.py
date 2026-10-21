"""Return-dedup review routes used by catalog preparation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
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
from app.catalog.return_dedup_repository import (
    DecideReturnDedupGroup,
    MySqlReturnDedupRepository,
)

router = APIRouter(
    prefix="/api/catalog",
    tags=["catalog"],
    dependencies=[Depends(require_catalog_session)],
)


class DedupDecisionRequest(StrictCatalogModel):
    operation_token: CatalogWireUuid
    expected_group_revision: int = Field(ge=1)
    expected_dedup_publication_revision: int = Field(ge=0)
    decision: Literal["confirmed_distinct", "duplicate_of"]
    canonical_member_id: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=10, max_length=500)


class DedupPayloadResponse(StrictCatalogModel):
    payload: str


@router.get("/return-dedup/groups", response_model=DedupPayloadResponse)
def list_dedup_groups(
    context: CatalogReadContext,
    engine: CatalogEngine,
    status: Literal["unresolved", "resolved", "all"] = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> DedupPayloadResponse:
    try:
        value = MySqlReturnDedupRepository(engine).list_groups(
            context,
            status=status,
            page=page,
            page_size=page_size,
        )
        return DedupPayloadResponse(payload=repr(value))
    except Exception as error:
        raise catalog_error(error) from error


@router.post(
    "/return-dedup/groups/{group_id}/decision",
    response_model=DedupPayloadResponse,
)
def decide_dedup_group(
    group_id: str,
    request: DedupDecisionRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> DedupPayloadResponse:
    require_matching_token(idempotency_key, request.operation_token)
    try:
        command = DecideReturnDedupGroup(
            group_id=group_id,
            **request.model_dump(),
        )
        value = MySqlReturnDedupRepository(engine).decide_group(
            context,
            command,
            occurred_at=datetime.now(tz=UTC),
        )
        return DedupPayloadResponse(payload=repr(value))
    except Exception as error:
        raise catalog_error(error) from error


__all__ = ("router",)
