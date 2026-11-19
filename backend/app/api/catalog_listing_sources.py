# ruff: noqa: RUF001 -- Chinese API messages.
"""Text-only Amazon listing upload and scoped comparison endpoints."""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import unquote

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, Query, Request
from starlette.responses import Response

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
from app.api.catalog_production_sources import require_enabled
from app.api.errors import ApiError
from app.catalog.listing_sources import (
    ListingPreviewRequest,
    preview_listing,
    read_listing,
    register_listing,
)
from app.catalog.listing_table import MAX_LISTING_BYTES, read_listing_workbook
from app.catalog.upload_service import parse_catalog_upload_metadata
from app.config import StorageSettings
from app.imports.storage import LocalContentStore

router = APIRouter(
    prefix="/api/catalog/listing-sources",
    tags=["catalog"],
    dependencies=[Depends(require_catalog_session)],
)


@router.post("/uploads", status_code=201)
async def upload_listing(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
    original_filename: Annotated[str, Header(alias="X-Original-Filename")],
    content_length: Annotated[str, Header(alias="Content-Length")],
    sku_policy: Literal["legacy", "style-color-size-v1"] = "legacy",
) -> Response:
    import tempfile

    require_catalog_manager(context)
    require_enabled(request)
    storage = StorageSettings.from_env()
    store = LocalContentStore(storage.root, MAX_LISTING_BYTES)
    staged = None
    try:
        try:
            metadata = parse_catalog_upload_metadata(
                idempotency_key=str(idempotency_key),
                original_filename=original_filename,
                content_type=request.headers.get("Content-Type", ""),
                content_length=content_length,
                configured_max_upload_bytes=MAX_LISTING_BYTES,
            )
        except ValueError as error:
            raise ApiError(
                422,
                "listing_file_invalid",
                "请选择64MiB以内的XLSX商品清单，文件名与文件类型须正确。",
            ) from error
        with tempfile.SpooledTemporaryFile(
            max_size=1024 * 1024, dir=str(storage.root)
        ) as spool:
            received = 0
            async for chunk in request.stream():
                received += len(chunk)
                if received > MAX_LISTING_BYTES:
                    raise ApiError(
                        413,
                        "listing_file_too_large",
                        "亚马逊商品清单最多64MiB，请缩小后上传。",
                    )
                spool.write(chunk)
            if received != metadata.declared_content_length:
                raise ApiError(
                    422,
                    "listing_upload_incomplete",
                    "文件未完整上传，请重新选择文件后重试。",
                )
            spool.seek(0)
            staged = store.write_stream(idempotency_key, spool)
        parsed = read_listing_workbook(
            staged.path, strict_skus=sku_policy == "style-color-size-v1"
        )
        stored = store.promote(staged)
        staged = None
        return catalog_json(
            register_listing(
                engine,
                site=context.site_id,
                actor=context.principal_user_id,
                token=idempotency_key,
                parsed=parsed,
                stored=stored,
                filename=unquote(original_filename),
            )
        )
    except ApiError:
        raise
    except Exception as error:
        raise_catalog_error(error)
    finally:
        if staged is not None:
            store.discard_staged(staged)


@router.get("/{import_id}")
def detail(
    import_id: int,
    context: CatalogReadContext,
    engine: CatalogEngine,
    history_page: int = Query(default=1, ge=1),
) -> Response:
    require_catalog_manager(context)
    try:
        return catalog_json(
            read_listing(
                engine,
                site=context.site_id,
                import_id=import_id,
                history_page=history_page,
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.post("/{import_id}/preview")
def preview(
    import_id: int,
    body: ListingPreviewRequest,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_catalog_manager(context)
    require_enabled(request)
    require_matching_token(idempotency_key, body.operation_token)
    try:
        return catalog_json(
            preview_listing(
                engine,
                site=context.site_id,
                actor=context.principal_user_id,
                import_id=import_id,
                command=body,
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.post("/{import_id}/compare")
def compare(
    import_id: int,
    body: dict[str, int],
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
) -> Response:
    require_catalog_manager(context)
    require_enabled(request)
    try:
        return catalog_json(
            read_listing(
                engine,
                site=context.site_id,
                import_id=import_id,
                bindings_override=body,
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.get("/styles/{style_id}/status")
def style_platform_status(
    style_id: int | None, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    require_catalog_manager(context)
    from app.catalog.platform_evidence import catalog_platform_review
    from app.catalog.production_sources import _publication

    try:
        with (
            engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection,
            connection.begin(),
        ):
            base, revision = _publication(connection, context.site_id, lock=False)
            found = connection.scalar(
                sa.text(
                    "SELECT style_id FROM product_catalog_style_members "
                    "WHERE site_id=:site AND catalog_version_id=:base "
                    "AND style_id=:style"
                ),
                {"site": context.site_id, "base": base, "style": style_id},
            )
            if (style_id is not None and not found) or base is None:
                raise ApiError(
                    404, "catalog_style_not_found", "未找到当前目录中的商品。"
                )
            result = catalog_platform_review(
                connection,
                site_id=context.site_id,
                catalog_version_id=base,
                style_id=style_id,
            )
            result.pop("blocked_keys", None)
            return catalog_json(result | {"catalog_publication_revision": revision})
    except Exception as error:
        raise_catalog_error(error)


@router.get("/platform/status")
def current_platform_status(
    context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    return style_platform_status(None, context, engine)
