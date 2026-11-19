"""Production source entry; ordinary catalog review owns all subsequent decisions."""

from __future__ import annotations

from datetime import UTC
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from app.api.catalog_common import (
    CatalogEngine,
    CatalogIdempotencyKey,
    CatalogReadContext,
    CatalogWriteContext,
    catalog_json,
    raise_catalog_error,
    require_catalog_manager,
    require_catalog_session,
    require_matching_token,
)
from app.api.errors import ApiError
from app.catalog.models import CatalogWireUuid, StrictCatalogModel
from app.catalog.production_source_table import (
    parse_production_table,
    render_production_source_template,
)
from app.catalog.production_sources import (
    ProductionSource,
    create_production_import,
    rebase_production_import,
    source_preview,
)
from app.catalog.scope_projection import SCOPES_WITH_DISPLAY_NAMES

router = APIRouter(
    prefix="/api/catalog/production-sources",
    tags=["catalog"],
    dependencies=[Depends(require_catalog_session)],
)


def require_enabled(request: Request) -> None:
    if not request.app.state.settings.catalog_production_sources_enabled:
        raise ApiError(403, "production_catalog_disabled", "当前环境尚未启用商品建档。")


class CreateProductionSource(StrictCatalogModel):
    source: ProductionSource
    operation_token: CatalogWireUuid
    expected_catalog_publication_revision: int = Field(ge=0)


class ParseProductionSource(StrictCatalogModel):
    source_name: str = Field(min_length=1, max_length=128)
    format: Literal["csv", "tsv", "xlsx"]
    content: str = Field(min_length=1, max_length=1_400_000)


class RebaseProductionSource(StrictCatalogModel):
    operation_token: CatalogWireUuid
    expected_workflow_revision: int = Field(ge=0)
    expected_catalog_publication_revision: int = Field(ge=0)


@router.get("/capabilities")
def capabilities(
    request: Request, context: CatalogReadContext, engine: CatalogEngine
) -> dict[str, object]:
    with engine.connect() as connection:
        scopes = [
            dict(row)
            for row in connection.execute(
                sa.text(
                    "SELECT id, seller_account_display_name, marketplace_scope_code"
                    f" FROM {SCOPES_WITH_DISPLAY_NAMES} AS current_scopes"
                    " WHERE site_id=:site"
                ),
                {"site": context.site_id},
            ).mappings()
        ]
    return {
        "scopes": scopes,
        "enabled": request.app.state.settings.catalog_production_sources_enabled,
        "can_manage": bool(
            not context.principal_roles.isdisjoint({"admin", "data_manager"})
        ),
        "site_code": context.site_code,
    }


@router.get("")
def recent_sources(context: CatalogReadContext, engine: CatalogEngine) -> JSONResponse:
    require_catalog_manager(context)
    from app.catalog.task_queries import IMPORT_SELECT, import_metadata

    with engine.connect() as connection:
        items = (
            connection.execute(
                sa.text(
                    IMPORT_SELECT
                    + " WHERE i.site_id=:site AND i.source_kind='production'"
                    " ORDER BY i.id DESC LIMIT 30"
                ),
                {"site": context.site_id},
            )
            .mappings()
            .all()
        )
    return catalog_json(
        {
            "items": [
                import_metadata(item)
                | {"created_at": item["created_at"].replace(tzinfo=UTC)}
                for item in items
            ]
        }
    )


@router.get("/template")
def source_template(request: Request, context: CatalogReadContext) -> Response:
    require_catalog_manager(context)
    require_enabled(request)
    return Response(
        content=render_production_source_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="product-registration.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/parse")
def parse_source(
    body: ParseProductionSource,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
) -> dict[str, object]:
    require_catalog_manager(context)
    require_enabled(request)
    try:
        source, locations = parse_production_table(
            body.source_name, body.format, body.content
        )
        checked = source_preview(engine, context.site_id, source, locations=locations)
        return source.model_dump(mode="json") | {"preview": checked}
    except Exception as error:
        raise_catalog_error(error)


@router.post("/preview")
def preview(
    body: ProductionSource,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
) -> JSONResponse:
    require_catalog_manager(context)
    require_enabled(request)
    try:
        return catalog_json(source_preview(engine, context.site_id, body))
    except Exception as error:
        raise_catalog_error(error)


@router.post("")
def create(
    body: CreateProductionSource,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> JSONResponse:
    require_catalog_manager(context)
    require_enabled(request)
    require_matching_token(idempotency_key, body.operation_token)
    try:
        return catalog_json(
            create_production_import(
                engine,
                site_id=context.site_id,
                actor_id=context.principal_user_id,
                token=body.operation_token,
                source=body.source,
                expected_revision=body.expected_catalog_publication_revision,
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.post("/{import_id}/rebase")
def rebase(
    import_id: int,
    body: RebaseProductionSource,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> JSONResponse:
    require_catalog_manager(context)
    require_enabled(request)
    require_matching_token(idempotency_key, body.operation_token)
    try:
        return catalog_json(
            rebase_production_import(
                engine,
                import_id=import_id,
                site_id=context.site_id,
                actor_id=context.principal_user_id,
                token=body.operation_token,
                expected_revision=body.expected_catalog_publication_revision,
                expected_workflow_revision=body.expected_workflow_revision,
            )
        )
    except Exception as error:
        raise_catalog_error(error)
