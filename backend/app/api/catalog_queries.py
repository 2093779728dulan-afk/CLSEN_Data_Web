"""Approved catalog, history, evidence, and resource-bound reveal routes."""

from __future__ import annotations

import base64
from datetime import UTC, date, datetime
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
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
from app.api.errors import ApiError
from app.catalog.models import CatalogWireUuid, StrictCatalogModel
from app.catalog.queries import CatalogVersionSummary, MySqlCatalogQueries
from app.catalog.report_selection import (
    ReportSelection,
    ReportSource,
    SaveReportSelection,
    preview_selection,
    save_selection,
    selection_context,
)
from app.catalog.service import CatalogService
from app.catalog.task_queries import list_tasks
from app.catalog.unmatched_repository import MySqlCatalogUnmatchedRepository

router = APIRouter(
    prefix="/api/catalog",
    tags=["catalog"],
    dependencies=[Depends(require_catalog_session)],
)


@router.get("/unmatched/selection-candidates/{import_id}/source")
def report_selection_recheck_source(
    import_id: int, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    from app.catalog.report_selection import recheck_source

    require_catalog_manager(context)
    return catalog_json(recheck_source(engine, context.site_id, import_id))


@router.post("/unmatched/selection-context")
def report_selection_context(
    body: ReportSource,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
) -> Response:
    from app.api.catalog_production_sources import require_enabled

    require_catalog_manager(context)
    require_enabled(request)
    return catalog_json(selection_context(engine, context.site_id, body))


@router.post("/unmatched/selection-preview")
def report_selection_preview(
    body: ReportSelection,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
) -> Response:
    from app.api.catalog_production_sources import require_enabled

    require_catalog_manager(context)
    require_enabled(request)
    try:
        return catalog_json(preview_selection(engine, context.site_id, body))
    except Exception as error:
        raise_catalog_error(error)


@router.post("/unmatched/selection-candidates")
def report_selection_save(
    body: SaveReportSelection,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    from app.api.catalog_production_sources import require_enabled

    require_catalog_manager(context)
    require_enabled(request)
    require_matching_token(idempotency_key, body.operation_token)
    try:
        return catalog_json(
            save_selection(engine, context.site_id, context.principal_user_id, body)
        )
    except Exception as error:
        raise_catalog_error(error)


class SensitiveSourceEncoding(StrictCatalogModel):
    code_points: str
    utf8_base64url: str


class RestoreCatalogVersionRequest(StrictCatalogModel):
    operation_token: CatalogWireUuid
    expected_catalog_publication_revision: int = Field(ge=0)
    reason: str = Field(min_length=10, max_length=1000)


def encode_sensitive_source(value: str) -> SensitiveSourceEncoding:
    return SensitiveSourceEncoding(
        code_points=" ".join(f"U+{ord(character):04X}" for character in value),
        utf8_base64url=base64.urlsafe_b64encode(value.encode("utf-8"))
        .decode("ascii")
        .rstrip("="),
    )


def _current_id(engine: CatalogEngine, site_id: int) -> int | None:
    with engine.connect() as connection:
        value = connection.scalar(
            sa.text(
                "SELECT current_catalog_version_id FROM product_catalog_publications "
                "WHERE site_id = :site_id"
            ),
            {"site_id": site_id},
        )
    return None if value is None else int(value)


def require_supported_catalog(
    catalog: CatalogVersionSummary | None, version: int
) -> None:
    if (
        catalog is not None
        and version == 1
        and any(item.internal_display_sku is None for item in catalog.skus)
    ):
        raise ApiError(
            409,
            "catalog_client_upgrade_required",
            "当前客户端不支持待补码商品，请使用新版商品入口。",  # noqa: RUF001
        )


@router.get("/styles")
def list_catalog_styles(
    context: CatalogReadContext,
    engine: CatalogEngine,
    contract_version: int = Query(default=1, ge=1, le=2),
    report_source_scope_id: int | None = Query(default=None, gt=0),
) -> Response:
    try:
        if report_source_scope_id is not None:
            with engine.connect() as connection:
                exists = connection.scalar(
                    sa.text(
                        "SELECT id FROM report_source_scopes "
                        "WHERE id=:scope AND site_id=:site"
                    ),
                    {"scope": report_source_scope_id, "site": context.site_id},
                )
            if exists is None:
                raise ApiError(404, "catalog_scope_not_found", "店铺不存在或无权访问。")
        catalog = MySqlCatalogQueries(engine).current_catalog(
            site_id=context.site_id, report_source_scope_id=report_source_scope_id
        )
        require_supported_catalog(catalog, contract_version)
        return catalog_json({"catalog": catalog, "contract_version": contract_version})
    except ApiError:
        raise
    except Exception as error:
        raise_catalog_error(error)


@router.get("/styles/{style_id}")
def get_catalog_style(
    style_id: int,
    context: CatalogReadContext,
    engine: CatalogEngine,
    contract_version: int = Query(default=1, ge=1, le=2),
    report_source_scope_id: int | None = Query(default=None, gt=0),
) -> Response:
    try:
        if report_source_scope_id is not None:
            with engine.connect() as connection:
                exists = connection.scalar(
                    sa.text(
                        "SELECT id FROM report_source_scopes "
                        "WHERE id=:scope AND site_id=:site"
                    ),
                    {"scope": report_source_scope_id, "site": context.site_id},
                )
            if exists is None:
                raise ApiError(404, "catalog_scope_not_found", "店铺不存在或无权访问。")
        catalog = MySqlCatalogQueries(engine).current_catalog(
            site_id=context.site_id, report_source_scope_id=report_source_scope_id
        )
        if catalog is None:
            raise ApiError(404, "catalog_style_not_found", "Style was not found.")
        style = next(
            (item for item in catalog.styles if item.style_id == style_id), None
        )
        if style is None:
            raise ApiError(404, "catalog_style_not_found", "Style was not found.")
        skus = tuple(item for item in catalog.skus if item.style_id == style_id)
        if contract_version == 1 and any(
            item.internal_display_sku is None for item in skus
        ):
            raise ApiError(
                409,
                "catalog_client_upgrade_required",
                "当前客户端不支持待补码商品，请使用新版商品入口。",  # noqa: RUF001
            )
        return catalog_json(
            {
                "catalog_version_id": catalog.catalog_version_id,
                "catalog_publication_revision": catalog.catalog_publication_revision,
                "permissions": {
                    "can_edit": not context.principal_roles.isdisjoint(
                        {"admin", "data_manager"}
                    ),
                    "can_manage_categories": "admin" in context.principal_roles,
                },
                "style": style,
                "skus": skus,
            }
        )
    except ApiError:
        raise
    except Exception as error:
        raise_catalog_error(error)


@router.get("/styles/{style_id}/name-suggestions")
def list_catalog_name_suggestions(
    style_id: int, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    try:
        return catalog_json(
            MySqlCatalogQueries(engine).name_suggestions(
                site_id=context.site_id, style_id=style_id
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.get("/styles/{style_id}/pending-items")
def list_catalog_style_pending_items(
    style_id: int, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    try:
        queries = MySqlCatalogQueries(engine)
        catalog = queries.current_catalog(site_id=context.site_id)
        if catalog is None or all(item.style_id != style_id for item in catalog.styles):
            raise ApiError(404, "catalog_style_not_found", "Style was not found.")
        return catalog_json(
            {
                "items": queries.style_pending_items(
                    site_id=context.site_id,
                    style_id=style_id,
                ),
                "permissions": {
                    "can_review": not context.principal_roles.isdisjoint(
                        {"admin", "data_manager"}
                    )
                },
            }
        )
    except ApiError:
        raise
    except Exception as error:
        raise_catalog_error(error)


@router.get("/variants/{sku_id}/seller-skus")
def list_catalog_variant_seller_skus(
    sku_id: int,
    context: CatalogReadContext,
    engine: CatalogEngine,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> Response:
    try:
        result = MySqlCatalogQueries(engine).variant_seller_skus(
            site_id=context.site_id,
            sku_id=sku_id,
            page=page,
            page_size=page_size,
        )
        if result is None:
            raise ApiError(404, "catalog_sku_not_found", "SKU was not found.")
        return catalog_json(result)
    except ApiError:
        raise
    except Exception as error:
        raise_catalog_error(error)


@router.get("/variants/{sku_id}/evidence")
def list_catalog_variant_evidence(
    sku_id: int,
    context: CatalogReadContext,
    engine: CatalogEngine,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> Response:
    try:
        result = MySqlCatalogQueries(engine).variant_evidence(
            site_id=context.site_id,
            sku_id=sku_id,
            page=page,
            page_size=page_size,
        )
        if result is None:
            raise ApiError(404, "catalog_sku_not_found", "SKU was not found.")
        return catalog_json(result)
    except ApiError:
        raise
    except Exception as error:
        raise_catalog_error(error)


@router.get("/report-matching/{version_id}")
def report_product_matching(
    version_id: int, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    from app.catalog.report_matching import match_report

    require_catalog_manager(context)
    with (
        engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection,
        connection.begin(),
    ):
        return catalog_json(match_report(connection, context.site_id, version_id))


@router.get("/unmatched")
def list_catalog_unmatched(
    context: CatalogReadContext,
    engine: CatalogEngine,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    return_basis: Literal["report_date", "event_date"] = "event_date",
) -> Response:
    require_catalog_manager(context)
    try:
        return catalog_json(
            MySqlCatalogUnmatchedRepository(engine).list_unmatched(
                site_id=context.site_id,
                from_date=from_date,
                to_date=to_date,
                return_basis=return_basis,
                page=page,
                page_size=page_size,
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.get("/tasks")
def list_catalog_tasks(
    context: CatalogReadContext,
    engine: CatalogEngine,
    kind: Literal["all", "review", "attention"] = "all",
    status: str | None = None,
    scope_id: int | None = Query(default=None, gt=0),
    q: str = Query(default="", max_length=128),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    updated_from: date | None = None,
    updated_to: date | None = None,
) -> Response:
    require_catalog_manager(context)
    try:
        return catalog_json(
            list_tasks(
                engine,
                site_id=context.site_id,
                kind=kind,
                status=status,
                scope_id=scope_id,
                query=q,
                page=page,
                page_size=page_size,
                updated_from=updated_from,
                updated_to=updated_to,
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.get("/versions")
def list_catalog_versions(
    context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    require_catalog_manager(context)
    with engine.connect() as connection:
        rows = (
            connection.execute(
                sa.text(
                    """
                SELECT id, version_number, base_catalog_version_id, risk,
                       approved_by_user_id, approved_at, diff_digest
                FROM product_catalog_versions
                WHERE site_id = :site_id ORDER BY version_number DESC
                """
                ),
                {"site_id": context.site_id},
            )
            .mappings()
            .all()
        )
    return catalog_json({"versions": [dict(row) for row in rows]})


@router.get("/versions/{version_id}/diff")
def get_catalog_version_diff(
    version_id: int, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    require_catalog_manager(context)
    with engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    "SELECT id, base_catalog_version_id, diff_digest, risk "
                    "FROM product_catalog_versions "
                    "WHERE id = :id AND site_id = :site_id"
                ),
                {"id": version_id, "site_id": context.site_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ApiError(404, "catalog_version_not_found", "Version was not found.")
        counts = (
            connection.execute(
                sa.text(
                    """
                SELECT
                  (SELECT COUNT(*) FROM product_catalog_style_members
                   WHERE catalog_version_id=:id) AS styles,
                  (SELECT COUNT(*) FROM product_catalog_sku_members
                   WHERE catalog_version_id=:id) AS skus,
                  (SELECT COUNT(*) FROM product_catalog_mappings
                   WHERE catalog_version_id=:id) AS mappings,
                  (SELECT COUNT(*) FROM product_catalog_exclusions
                   WHERE catalog_version_id=:id) AS exclusions
                """
                ),
                {"id": version_id},
            )
            .mappings()
            .one()
        )
    return catalog_json(
        {
            "version_id": version_id,
            "base_catalog_version_id": row["base_catalog_version_id"],
            "risk": row["risk"],
            "diff_digest": bytes(row["diff_digest"]),
            "counts": dict(counts),
        }
    )


@router.post("/versions/{version_id}/restore")
def restore_catalog_version(
    version_id: int,
    request: RestoreCatalogVersionRequest,
    http_request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_catalog_admin(context)
    require_matching_token(idempotency_key, request.operation_token)
    if not http_request.app.state.settings.catalog_production_sources_enabled:
        with engine.connect() as connection:
            source_kind = connection.scalar(
                sa.text(
                    "SELECT imports.source_kind FROM product_catalog_versions versions "
                    "JOIN catalog_imports imports "
                    "ON imports.id=versions.source_import_id "
                    "AND imports.site_id=versions.site_id "
                    "WHERE versions.id=:id AND versions.site_id=:site"
                ),
                {"id": version_id, "site": context.site_id},
            )
        if source_kind == "production":
            raise ApiError(
                403,
                "production_catalog_disabled",
                "Production catalog writes are disabled in this environment.",
            )
    try:
        return catalog_json(
            CatalogService(engine).restore_version(
                site_id=context.site_id,
                target_version_id=version_id,
                actor_user_id=context.principal_user_id,
                actor_roles=context.principal_roles,
                operation_token=request.operation_token,
                expected_catalog_publication_revision=request.expected_catalog_publication_revision,
                reason=request.reason,
                now=datetime.now(UTC),
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.get("/evidence")
def list_catalog_evidence(
    context: CatalogReadContext,
    engine: CatalogEngine,
    version_id: int | None = Query(default=None, ge=1),
    import_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> Response:
    require_catalog_manager(context)
    catalog_version_id = (
        version_id if version_id is not None else _current_id(engine, context.site_id)
    )
    with engine.connect() as connection:
        if import_id is not None:
            export_id = connection.scalar(
                sa.text(
                    "SELECT export_id FROM catalog_imports "
                    "WHERE id=:id AND site_id=:site_id"
                ),
                {"id": import_id, "site_id": context.site_id},
            )
        elif catalog_version_id is not None:
            export_id = connection.scalar(
                sa.text(
                    "SELECT imports.export_id "
                    "FROM product_catalog_versions AS versions "
                    "INNER JOIN catalog_imports AS imports "
                    "ON imports.id=versions.source_import_id "
                    "WHERE versions.id=:id AND versions.site_id=:site_id"
                ),
                {"id": catalog_version_id, "site_id": context.site_id},
            )
        else:
            export_id = None
    if export_id is None:
        return catalog_json({"items": [], "page": page, "page_size": page_size})
    with engine.connect() as connection:
        rows = (
            connection.execute(
                sa.text(
                    """
                SELECT id, source_kind, safe_preview, raw_sha256,
                       is_unsafe, is_truncated
                FROM catalog_source_refs
                WHERE site_id = :site_id AND resource_kind = 'export'
                  AND resource_id = :resource_id
                ORDER BY id LIMIT :limit OFFSET :offset
                """
                ),
                {
                    "site_id": context.site_id,
                    "resource_id": int(export_id),
                    "limit": page_size,
                    "offset": (page - 1) * page_size,
                },
            )
            .mappings()
            .all()
        )
    return catalog_json(
        {
            "items": [
                {
                    "source_ref_id": str(row["id"]),
                    "source_kind": row["source_kind"],
                    "preview": row["safe_preview"],
                    "digest": "sha256:" + bytes(row["raw_sha256"]).hex(),
                    "is_unsafe": bool(row["is_unsafe"]),
                    "is_truncated": bool(row["is_truncated"]),
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
        }
    )


def _reveal(
    engine: CatalogEngine,
    *,
    context: CatalogReadContext,
    source_ref_id: str,
    resource_kind: str,
    resource_id: int,
) -> SensitiveSourceEncoding:
    try:
        numeric_id = int(source_ref_id, 10)
    except ValueError as error:
        raise ApiError(
            404, "catalog_source_ref_not_found", "Source reference was not found."
        ) from error
    with engine.connect() as connection:
        raw = connection.scalar(
            sa.text(
                """
                SELECT raw_value FROM catalog_source_refs
                WHERE id = :id AND site_id = :site_id
                  AND resource_kind = :kind AND resource_id = :resource_id
                """
            ),
            {
                "id": numeric_id,
                "site_id": context.site_id,
                "kind": resource_kind,
                "resource_id": resource_id,
            },
        )
    if not isinstance(raw, str):
        raise ApiError(
            404, "catalog_source_ref_not_found", "Source reference was not found."
        )
    return encode_sensitive_source(raw)


@router.get("/source-identifiers/{source_ref_id}")
def reveal_approved_source(
    source_ref_id: str, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    require_catalog_manager(context)
    current = _current_id(engine, context.site_id)
    if current is None:
        raise ApiError(
            404, "catalog_source_ref_not_found", "Source reference was not found."
        )
    with engine.connect() as connection:
        export_id = connection.scalar(
            sa.text(
                "SELECT imports.export_id FROM product_catalog_versions AS versions "
                "INNER JOIN catalog_imports AS imports "
                "ON imports.id=versions.source_import_id "
                "WHERE versions.id=:id AND versions.site_id=:site_id"
            ),
            {"id": current, "site_id": context.site_id},
        )
    if export_id is None:
        raise ApiError(
            404,
            "catalog_source_ref_not_found",
            "Source reference was not found.",
        )
    result = _reveal(
        engine,
        context=context,
        source_ref_id=source_ref_id,
        resource_kind="export",
        resource_id=int(export_id),
    )
    response = catalog_json(result)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/imports/{import_id}/source-identifiers/{source_ref_id}")
def reveal_draft_source(
    import_id: int,
    source_ref_id: str,
    context: CatalogReadContext,
    engine: CatalogEngine,
    workflow_revision: int = Query(ge=0),
) -> Response:
    # Role is deliberately checked before revision or membership lookup.
    require_catalog_manager(context)
    with engine.connect() as connection:
        current_revision = connection.scalar(
            sa.text(
                "SELECT workflow_revision FROM catalog_imports "
                "WHERE id=:id AND site_id=:site_id"
            ),
            {"id": import_id, "site_id": context.site_id},
        )
    if current_revision is None:
        raise ApiError(404, "catalog_import_not_found", "Import was not found.")
    if int(current_revision) != workflow_revision:
        raise ApiError(
            409,
            "catalog_workflow_revision_conflict",
            "The import changed; reload and retry.",
        )
    with engine.connect() as connection:
        export_id = connection.scalar(
            sa.text(
                "SELECT export_id FROM catalog_imports "
                "WHERE id=:id AND site_id=:site_id"
            ),
            {"id": import_id, "site_id": context.site_id},
        )
    if export_id is None:
        raise ApiError(404, "catalog_import_not_found", "Import was not found.")
    result = _reveal(
        engine,
        context=context,
        source_ref_id=source_ref_id,
        resource_kind="export",
        resource_id=int(export_id),
    )
    response = catalog_json(result)
    response.headers["Cache-Control"] = "private, no-store"
    return response


__all__ = ("SensitiveSourceEncoding", "encode_sensitive_source", "router")
