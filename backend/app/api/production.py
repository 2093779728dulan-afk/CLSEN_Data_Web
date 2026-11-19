"""Same-origin production adapter using existing session, CSRF and site authority."""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from urllib.parse import quote
from uuid import UUID
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import Response
from openpyxl.utils.exceptions import (  # type: ignore[import-untyped]
    InvalidFileException,
)
from sqlalchemy import text as sql_text
from starlette.concurrency import run_in_threadpool

from app.api.catalog_common import (
    CatalogEngine,
    CatalogReadContext,
    CatalogWriteContext,
    require_catalog_manager,
)
from app.api.errors import ApiError
from app.api.production_fba import router as fba_router
from app.catalog.queries import MySqlCatalogQueries
from app.production import destination_receipt_files as destination_files
from app.production import inventory_review as ir
from app.production.client import production_request
from app.production.count_tables import count_template, preview_count
from app.production.dispatch_import_review import (
    DispatchReviewInput,
    DispatchSourcesInput,
    preview_dispatch_sources,
    save_dispatch_review,
)
from app.production.identity import (
    catalog_for_report_scope,
    production_skus,
    resolve_standard_codes,
)
from app.production.inventory_display import (
    filter_availability,
    require_selected,
    selected_skus,
)
from app.production.inventory_export import inventory_workbook
from app.production.inventory_product_match import product_match
from app.production.inventory_snapshot import inventory_snapshot
from app.production.order_source_drafts import (
    SAMPLES,
    SampleId,
    SaveSourceDraft,
    draft_root,
    parse_order_source,
    save_source_draft,
    source_detail,
)
from app.production.order_tables import (
    parse_order_table,
    render_order_table,
    standard_order_workbook,
)
from app.production.shipment_source_drafts import (
    PACKING_FILENAME,
    PACKING_SAMPLE,
    SavePackingDraft,
    packing_detail,
    parse_packing_source,
    save_packing_draft,
)
from app.production.source_registry import (
    MAX_UPLOAD_BYTES,
    register_upload,
    registered_sources,
    uploaded_bytes,
    uploaded_review,
    validate_upload,
)
from app.production.table_baselines import read_baseline, remember_baseline
from app.production.workbench_tables import (
    dispatch_template,
    operation_template,
    preview_dispatch,
    preview_operation,
    receipt_batch_order,
)

router = APIRouter(prefix="/api/production", tags=["production"])
router.include_router(fba_router)
Kind = Literal["orders", "shipments"]


def _source_summary(
    request: Request,
    context: CatalogReadContext,
    kind: Kind,
    source_id: str,
    filename: str,
    uploaded_at: str = "",
) -> dict[str, object]:
    settings = request.app.state.settings
    item: dict[str, object] = {
        "source_id": source_id,
        "kind": kind,
        "filename": filename,
        "origin": "UPLOAD" if uploaded_at else "SAMPLE",
        "uploaded_at": uploaded_at,
    }
    try:
        source = (
            source_detail(settings, context, source_id)
            if kind == "orders"
            else packing_detail(settings, context, source_id)
        )
    except ApiError as error:
        return {
            **item,
            "available": False,
            "error": cast(dict[str, object], cast(dict[str, str], error.detail))[
                "message"
            ],
        }
    saved = cast(dict[str, object] | None, source["saved_draft"])
    return {
        **item,
        "available": True,
        "source_units": source["source_units"],
        "row_count": len(cast(list[object], source["rows"])),
        "issue_count": len(cast(list[object], source["issues"])),
        "saved": saved is not None,
        "revision": saved["revision"] if saved else 0,
        "business_number": saved["business_number"] if saved else "",
        "business_date": saved["business_date"] if saved else source["business_date"],
        "draft_units": saved["draft_units"] if saved else None,
        "updated_at": saved["updated_at"] if saved else "",
        "confirmation_enabled": False,
    }


@router.get("/source-drafts")
def source_draft_list(request: Request, context: CatalogReadContext) -> object:
    root = draft_root(request.app.state.settings, context)
    items = [
        _source_summary(request, context, "orders", key, name)
        for key, name in SAMPLES.items()
    ]
    items.append(
        _source_summary(request, context, "shipments", PACKING_SAMPLE, PACKING_FILENAME)
    )
    for source in registered_sources(root, context):
        items.append(
            _source_summary(
                request,
                context,
                cast(Kind, source["kind"]),
                str(source["sample_id"]),
                str(source["filename"]),
                str(source["uploaded_at"]),
            )
        )
    return {"items": items, "confirmation_enabled": False}


@router.post("/source-drafts/{kind}/upload")
async def source_draft_upload(
    kind: Kind,
    request: Request,
    context: CatalogWriteContext,
    filename: Annotated[str, Query(max_length=240)] = "upload.xlsx",
) -> object:
    require_catalog_manager(context)
    root = draft_root(request.app.state.settings, context)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_UPLOAD_BYTES:
            raise ApiError(413, "file_too_large", "请选择不超过2MB的XLSX原表。")
        raw.extend(chunk)
    content = bytes(raw)
    name = validate_upload(filename, content)
    try:
        preview = await run_in_threadpool(
            parse_order_source if kind == "orders" else parse_packing_source,
            content,
            name,
        )
    except (
        BadZipFile,
        InvalidFileException,
        OSError,
        KeyError,
        ValueError,
        IndexError,
        ParseError,
    ) as error:
        raise ApiError(
            422, "invalid_workbook", "表格无法读取。请核对文件及已适配格式。"
        ) from error
    samples = SAMPLES if kind == "orders" else {PACKING_SAMPLE: PACKING_FILENAME}
    for source_id, sample_name in samples.items():
        path = root / "inputs" / sample_name
        if (
            path.is_file()
            and hashlib.sha256(path.read_bytes()).hexdigest()
            == preview["source_digest"]
        ):
            return {
                "item": _source_summary(request, context, kind, source_id, sample_name),
                "duplicate": True,
            }
    source, duplicate = await run_in_threadpool(
        register_upload, root, context, kind, name, content, preview
    )
    return {
        "item": _source_summary(
            request,
            context,
            kind,
            str(source["sample_id"]),
            str(source["filename"]),
            str(source["uploaded_at"]),
        ),
        "duplicate": duplicate,
    }


@router.get("/order-source-drafts")
def order_source_samples(request: Request, context: CatalogReadContext) -> object:
    draft_root(request.app.state.settings, context)
    return {
        "items": [{"sample_id": key, "filename": name} for key, name in SAMPLES.items()]
    }


@router.get("/order-source-drafts/{sample_id}")
def order_source_detail(
    sample_id: SampleId, request: Request, context: CatalogReadContext
) -> object:
    return source_detail(request.app.state.settings, context, sample_id)


@router.post("/order-source-drafts/{sample_id}")
def order_source_save(
    sample_id: SampleId,
    request: Request,
    context: CatalogWriteContext,
    body: SaveSourceDraft,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    require_catalog_manager(context)
    return save_source_draft(request.app.state.settings, context, sample_id, body, key)


@router.get("/shipment-source-drafts/{source_id}")
def shipment_source_detail(
    source_id: str, request: Request, context: CatalogReadContext
) -> object:
    return packing_detail(request.app.state.settings, context, source_id)


@router.post("/shipment-source-drafts/{source_id}")
def shipment_source_save(
    request: Request,
    context: CatalogWriteContext,
    body: SavePackingDraft,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
    source_id: str = PACKING_SAMPLE,
) -> object:
    require_catalog_manager(context)
    return save_packing_draft(request.app.state.settings, context, body, key, source_id)


@router.get("/inventory-snapshot")
def stocktake_snapshot(request: Request, context: CatalogReadContext) -> object:
    # Keep the original read-only source endpoint; reviews have their own root.
    return inventory_snapshot(
        replace(request.app.state.settings, production_inventory_source_root="")
        if request.app.state.settings.production_demo_mode
        else request.app.state.settings,
        context,
    )


@router.get("/inventory-reviews/current")
def inventory_current(
    request: Request, context: CatalogReadContext, engine: CatalogEngine
) -> object:
    settings = request.app.state.settings
    result = ir.storage_call(ir.current, engine, settings, context)
    result["writes_enabled"] = settings.production_inventory_review_writes_enabled
    result["can_manage"] = result["can_manage"] and result["writes_enabled"]
    result["source_view_available"] = bool(settings.production_inventory_source_root)
    return result


@router.get("/inventory-export")
def inventory_export(
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
    source_digest: Annotated[str, Query(pattern=r"^[a-f0-9]{64}$")],
    review_id: UUID | None = None,
    revision: Annotated[int | None, Query(ge=0)] = None,
    source_only: bool = False,
    q: Annotated[str, Query(max_length=240)] = "",
    focus: Literal["", "identity", "quantity", "extra"] = "",
) -> Response:
    if review_id is not None:
        fixed = ir.storage_call(ir.detail, engine, context, review_id)
        snapshot = fixed["effective"]
        if revision != fixed["revision"]:
            raise ApiError(
                409,
                "inventory_export_stale",
                "核对资料已有更新。请刷新页面后重新导出。",
            )
    else:
        settings = request.app.state.settings
        snapshot = inventory_snapshot(
            replace(settings, production_inventory_source_root="")
            if source_only and settings.production_demo_mode
            else settings,
            context,
        )
    if snapshot["source_digest"] != source_digest:
        raise ApiError(
            409, "inventory_export_stale", "库存来源已变化。请刷新页面后重新导出。"
        )
    content = inventory_workbook(
        snapshot,
        review_id=str(review_id) if review_id else "",
        revision=revision if review_id else None,
        query=q,
        focus=focus,
    )
    filename = (
        "人工库存核对-"
        if snapshot.get("source_kind") == "MANUAL"
        else "花都仓库1号-库存表-"
    ) + str(snapshot.get("stocktaken_on") or "日期待确认")
    filename += f"-修订{revision}" if review_id else "-原始来源"
    filename += "-筛选.xlsx" if q or focus else ".xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                "attachment; filename=inventory.xlsx; "
                f"filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "no-store",
        },
    )


def require_inventory_review_writes(request: Request) -> None:
    if not request.app.state.settings.production_inventory_review_writes_enabled:
        raise ApiError(
            403,
            "inventory_review_read_only",
            "此环境仅查看库存资料，资料核对写入尚未启用。",  # noqa: RUF001
        )


@router.post("/inventory-reviews")
def inventory_start(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: ir.StartReview,
    response: Response,
) -> object:
    require_catalog_manager(context)
    require_inventory_review_writes(request)
    result, created = ir.storage_call(
        ir.start, engine, request.app.state.settings, context, body
    )
    response.status_code = 201 if created else 200
    return result


@router.get("/inventory-reviews/{review_id}")
def inventory_detail(
    review_id: UUID,
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
) -> object:
    result = ir.storage_call(ir.detail, engine, context, review_id)
    result["writes_enabled"] = (
        request.app.state.settings.production_inventory_review_writes_enabled
    )
    result["can_manage"] = result["can_manage"] and result["writes_enabled"]
    result["source_view_available"] = bool(
        request.app.state.settings.production_inventory_source_root
    )
    return result


@router.get("/inventory-reviews/{review_id}/product-match")
def inventory_product_match(
    review_id: UUID,
    context: CatalogReadContext,
    engine: CatalogEngine,
    expected_revision: Annotated[int, Query(ge=0)],
    source_key: Annotated[str, Query(min_length=1, max_length=240)],
    size: Literal["XS", "S", "M", "L", "XL", "XXL", "3XL"],
) -> object:
    fixed = ir.storage_call(ir.detail, engine, context, review_id)
    if fixed["revision"] != expected_revision:
        raise ApiError(
            409,
            "inventory_match_stale",
            "库存资料已有更新。请刷新资料后重新查看商品对应。",
        )
    catalog = MySqlCatalogQueries(engine).current_catalog(site_id=context.site_id)
    return product_match(fixed["effective"], catalog, source_key, size) | {
        "review_id": str(review_id),
        "review_revision": fixed["revision"],
        "source_identity": fixed["source_identity"],
    }


@router.post("/inventory-reviews/{review_id}/preview")
def inventory_preview(
    review_id: UUID,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: ir.PreviewCommand,
) -> object:
    require_catalog_manager(context)
    require_inventory_review_writes(request)
    return ir.storage_call(ir.preview, engine, context, review_id, body)


@router.post("/inventory-reviews/{review_id}/commands")
def inventory_save(
    review_id: UUID,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: ir.SaveCommand,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    require_catalog_manager(context)
    require_inventory_review_writes(request)
    return ir.storage_call(ir.save, engine, context, review_id, body, key)


@router.get("/inventory-reviews/{review_id}/operations/{operation_id}")
def inventory_operation(
    review_id: UUID,
    operation_id: UUID,
    context: CatalogReadContext,
    engine: CatalogEngine,
) -> object:
    return ir.storage_call(ir.operation, engine, context, review_id, operation_id)


@router.get("/inventory-reviews/{review_id}/history")
def inventory_history(
    review_id: UUID,
    context: CatalogReadContext,
    engine: CatalogEngine,
    before_revision: Annotated[int, Query(ge=1)] = 2147483647,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> object:
    return ir.storage_call(
        ir.history, engine, context, review_id, before_revision, limit
    )


@router.get("/skus")
def skus(
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
    contract_version: int = Query(default=1, ge=1, le=2),
    report_source_scope_id: int | None = Query(default=None, ge=1),
) -> object:
    catalog = production_skus(request.app.state.settings, context, engine)
    if report_source_scope_id is not None:
        catalog = catalog_for_report_scope(
            engine, context, catalog, report_source_scope_id
        )
    if contract_version == 1 and any(item["code"] is None for item in catalog.values()):
        raise ApiError(
            409,
            "catalog_client_upgrade_required",
            "当前客户端不支持待补码商品，请使用新版入口。",  # noqa: RUF001
        )
    return {
        "contract_version": contract_version,
        "items": list(catalog.values()),
        "demo": request.app.state.settings.production_demo_mode
        or request.app.state.settings.production_qa_catalog_mode,
        "order_source_drafts": bool(
            request.app.state.settings.production_order_draft_root
        ),
        "shipment_source_drafts": bool(
            request.app.state.settings.production_order_draft_root
            and (
                Path(request.app.state.settings.production_order_draft_root)
                / "inputs"
                / PACKING_FILENAME
            ).is_file()
        ),
    }


def _operation_actor(context: CatalogReadContext, engine: CatalogEngine) -> str:
    with engine.connect() as connection:
        row = connection.execute(
            sql_text(
                "SELECT username_normalized AS username, display_name "
                "FROM users WHERE id=:actor"
            ),
            {"actor": context.principal_user_id},
        ).first()
    if row is None:
        raise ApiError(403, "role_forbidden", "无法核对当前操作人身份。")
    return f"{row.username} · {row.display_name}"[:255]


@router.get("/inventory/documents/{document_id}")
def stock_document(
    document_id: int, request: Request, context: CatalogReadContext
) -> object:
    return production_request(
        request.app.state.settings,
        context,
        "GET",
        f"inventory/documents/{document_id}",
    )


@router.get("/inventory/destination-receipts/{receipt_id}")
def destination_receipt(
    receipt_id: int, request: Request, context: CatalogReadContext
) -> object:
    return production_request(
        request.app.state.settings,
        context,
        "GET",
        f"inventory/destination-receipts/{receipt_id}",
    )


def _destination_state(
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
    shipment_id: int,
) -> dict[str, object]:
    state = cast(
        dict[str, object],
        production_request(
            request.app.state.settings,
            context,
            "GET",
            "inventory/destination-state",
            query=[("shipment_id", str(shipment_id))],
        ),
    )
    catalog = production_skus(request.app.state.settings, context, engine)
    for binding in cast(list[dict[str, object]], state["bindings"]):
        current = catalog.get(str(binding["sku_id"]))
        binding["source_catalog_version"] = binding.get("catalog_version")
        binding["source_sku_label"] = binding.get("sku_label")
        binding["catalog_version"] = current.get("catalog_version") if current else ""
        binding["identity_status"] = current.get("status") if current else "missing"
        if current:
            binding["sku_label"] = current.get("label")
    return state


@router.get("/inventory/destination-files/template")
def destination_template(
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
    shipment_id: int,
) -> Response:
    state = _destination_state(request, context, engine, shipment_id)
    content = destination_files.workbook(
        cast(list[dict[str, object]], state["bindings"])
    )
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                'attachment; filename="destination-receipt-template.xlsx"'
            )
        },
    )


@router.get("/inventory/destination-files/{receipt_id}/export")
def destination_export(
    receipt_id: int, request: Request, context: CatalogReadContext
) -> Response:
    receipt = cast(
        dict[str, object],
        production_request(
            request.app.state.settings,
            context,
            "GET",
            f"inventory/destination-receipts/{receipt_id}",
        ),
    )
    content = destination_files.workbook(
        cast(list[dict[str, object]], receipt["bindings"]),
        cast(list[dict[str, object]], receipt["lines"]),
    )
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                'attachment; filename="destination-receipt-export.xlsx"'
            )
        },
    )


@router.get("/inventory/destination-uploads/{upload_id}/original")
def destination_original(
    upload_id: UUID, request: Request, context: CatalogReadContext
) -> Response:
    require_catalog_manager(context)
    content = production_request(
        request.app.state.settings,
        context,
        "GET",
        f"inventory/destination-uploads/{upload_id}/original",
        binary=True,
    )
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                'attachment; filename="destination-receipt-original.xlsx"'
            )
        },
    )


@router.post("/inventory/destination-files/preview")
async def destination_preview(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    shipment_id: int,
    filename: str,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    require_catalog_manager(context)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 2_000_000:
            raise ApiError(413, "file_too_large", "请选择不超过2MB的标准XLSX文件。")
        raw.extend(chunk)
    state = await run_in_threadpool(
        _destination_state, request, context, engine, shipment_id
    )
    try:
        result = await run_in_threadpool(
            destination_files.preview,
            bytes(raw),
            cast(list[dict[str, object]], state["bindings"]),
        )
    except ValueError as error:
        raise ApiError(422, "invalid_workbook", str(error)) from error
    body: dict[str, object] = {
        "operation_token": str(key),
        "shipment_id": str(shipment_id),
        "filename": filename,
        "file_base64": base64.b64encode(raw).decode("ascii"),
    }
    stored = await run_in_threadpool(
        _stock_command, "destination-uploads", request, context, engine, body, key
    )
    return {**result, "original": stored}


def _table_baseline_root(request: Request) -> Path:
    return (
        Path(request.app.state.settings.production_inventory_source_root)
        / "editable-tables"
    )


@router.get("/table-baselines/{baseline_id}")
def table_baseline_read(
    baseline_id: str, request: Request, context: CatalogReadContext
) -> object:
    return read_baseline(_table_baseline_root(request), context, baseline_id)


@router.get("/table-baselines/{baseline_id}/original")
def table_baseline_original(
    baseline_id: str, request: Request, context: CatalogReadContext
) -> Response:
    root = _table_baseline_root(request)
    baseline = read_baseline(root, context, baseline_id)
    return Response(
        uploaded_bytes(root, context, baseline["source_id"], baseline["source_kind"]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="table-original.xlsx"'},
    )


@router.get("/inventory/count-table/template")
def inventory_count_template(
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
    warehouse_id: int,
    owner_id: int,
) -> Response:
    scope, catalog = _dispatch_scope(request, context, engine, warehouse_id, owner_id)
    return Response(
        count_template(scope, catalog),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="inventory-count.xlsx"'},
    )


@router.post("/inventory/count-table/preview")
async def inventory_count_preview(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    warehouse_id: int,
    owner_id: int,
    filename: str = "upload.xlsx",
) -> object:
    require_catalog_manager(context)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_UPLOAD_BYTES:
            raise ApiError(413, "file_too_large", "请选择不超过2MB的盘点XLSX文件。")
        raw.extend(chunk)
    scope, catalog = await run_in_threadpool(
        _dispatch_scope, request, context, engine, warehouse_id, owner_id
    )
    result = await run_in_threadpool(
        preview_count, bytes(raw), filename, scope, catalog
    )
    return await run_in_threadpool(
        remember_baseline,
        _table_baseline_root(request),
        context,
        "count",
        bytes(raw),
        result,
    )


@router.get("/inventory/overview-sheet/options")
def overview_sheet_options(
    request: Request, context: CatalogReadContext, engine: CatalogEngine
) -> object:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.production.inventory_sheet_source import load_sheet_source

    source = load_sheet_source(request.app.state.settings, context, engine)
    if source is not None:
        return {
            **source["options"],
            "default_as_of": source["stocktaken_on"],
            "today": datetime.now(ZoneInfo(context.reporting_timezone))
            .date()
            .isoformat(),
            "reporting_timezone": context.reporting_timezone,
        }

    options = cast(
        dict[str, object],
        production_request(
            request.app.state.settings,
            context,
            "GET",
            "inventory/overview-sheet-options",
        ),
    )
    return {
        **options,
        "today": datetime.now(ZoneInfo(context.reporting_timezone)).date().isoformat(),
        "reporting_timezone": context.reporting_timezone,
    }


@router.get("/inventory/overview-sheet")
def overview_sheet(
    request: Request, context: CatalogReadContext, engine: CatalogEngine
) -> object:
    from app.production.inventory_overview import read_sheet, sheet_summary

    sheet = read_sheet(
        request.app.state.settings, context, engine, dict(request.query_params)
    )
    return (
        sheet_summary(sheet, compact=request.query_params.get("compact") == "1")
        if request.query_params.get("summary") == "1"
        else sheet
    )


@router.get("/inventory/overview-sheet/details")
def overview_sheet_details(
    request: Request, context: CatalogReadContext, engine: CatalogEngine
) -> object:
    from app.production.inventory_overview import read_sheet, sheet_details

    query = dict(request.query_params)
    return sheet_details(
        read_sheet(request.app.state.settings, context, engine, query), query
    )


@router.get("/inventory/overview-sheet/export")
def overview_sheet_export(
    request: Request, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    from app.production.inventory_overview import read_sheet, sheet_workbook

    query = dict(request.query_params)
    result = read_sheet(request.app.state.settings, context, engine, query)
    filename = f"inventory-sheet-{result['as_of']}.xlsx"
    return Response(
        sheet_workbook(result, query),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/inventory/{resource}")
def stock_read(
    resource: Literal[
        "availability",
        "documents",
        "loans",
        "plans",
        "forecast",
        "history",
        "reservations",
        "holds",
        "destination-state",
        "transport-state",
        "warehouse-transit",
        "transit-batches",
        "progress-chains",
        "sku-locations",
        "transport-summary",
        "display-settings",
        "destination-shipments",
        "destination-receipts",
    ],
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
    shipment_id: Annotated[int | None, Query(gt=0)] = None,
    sku_id: Annotated[int | None, Query(gt=0)] = None,
) -> object:
    display_skus = None
    if (
        resource == "availability"
        and request.query_params.get("projection", "full") != "full"
        and (request.query_params.get("overview") == "1" or sku_id is not None)
    ):
        raise ApiError(
            422, "invalid_projection_scope", "请选择完整库存读取以使用商品筛选。"
        )
    if request.query_params.get("overview") == "1" and resource in {
        "availability",
        "sku-locations",
    }:
        display_settings = production_request(
            request.app.state.settings, context, "GET", "inventory/display-settings"
        )
        display_skus = selected_skus(
            cast(dict[str, Any], display_settings),
            production_skus(request.app.state.settings, context, engine),
        )
        if sku_id is not None:
            require_selected(str(sku_id), display_skus)
    if resource == "sku-locations" and str(sku_id) not in production_skus(
        request.app.state.settings, context, engine
    ):
        raise ApiError(409, "sku_identity_unavailable", "请选择本站已确认的稳定SKU。")
    if resource == "destination-state":
        if shipment_id is None:
            raise ApiError(422, "shipment_required", "请选择来源出货。")
        return _destination_state(request, context, engine, shipment_id)
    result = production_request(
        request.app.state.settings,
        context,
        "GET",
        f"inventory/{resource}",
        query=list(request.query_params.multi_items()),
    )
    if resource in {"transport-summary", "transit-batches", "warehouse-transit"}:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from app.production.fba_transit_opening import (
            configured_transit_scope,
            load_transit_opening,
            merge_transit_view,
        )

        settings = request.app.state.settings
        configured = configured_transit_scope(settings)
        if configured:
            scope = cast(
                dict[str, Any],
                production_request(
                    settings,
                    context,
                    "GET",
                    f"inventory/fba-scopes/{int(configured['id'])}",
                ),
            )
            catalog = catalog_for_report_scope(
                engine,
                context,
                production_skus(settings, context, engine),
                int(scope["report_source_scope_id"]),
            )
            opening = load_transit_opening(settings, context, engine, catalog, scope)
            result = merge_transit_view(
                cast(dict[str, Any], result),
                opening,
                resource,
                dict(request.query_params),
                datetime.now(ZoneInfo(context.reporting_timezone)).date(),
            )
    return (
        filter_availability(cast(dict[str, Any], result), display_skus)
        if resource == "availability" and display_skus is not None
        else result
    )


def _stock_command(
    path: str,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: dict[str, object],
    key: UUID,
) -> object:
    require_catalog_manager(context)
    if body.get("operation_token") != str(key):
        raise ApiError(422, "idempotency_key_mismatch", "操作ID必须与请求头一致。")
    payload = dict(body)
    payload["_catalog"] = production_skus(request.app.state.settings, context, engine)
    payload["_actor_name"] = _operation_actor(context, engine)
    return production_request(
        request.app.state.settings,
        context,
        "POST",
        f"inventory/{path}",
        body=payload,
        operation_key=str(key),
    )


@router.post("/inventory/{resource}")
def stock_create(
    resource: Literal[
        "display-settings",
        "documents",
        "reservations",
        "holds",
        "plans",
        "destination-bindings",
        "transport-records",
        "transport-events",
        "destination-receipts",
        "destination-settlements",
    ],
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: Annotated[dict[str, object], Body()],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    return _stock_command(resource, request, context, engine, body, key)


@router.get("/inventory/opening-table/template")
def opening_table_template(
    request: Request, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    from app.production.opening_tables import opening_template

    require_catalog_manager(context)
    return Response(
        opening_template(production_skus(request.app.state.settings, context, engine)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="opening-stock.xlsx"'},
    )


@router.post("/inventory/opening-table/parse")
async def opening_table_parse(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    filename: str = "opening.xlsx",
) -> object:
    from app.production.opening_tables import parse_opening, retain_source

    require_catalog_manager(context)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_UPLOAD_BYTES:
            raise ApiError(413, "file_too_large", "期初表不能超过2MiB。")
        raw.extend(chunk)
    catalog = await run_in_threadpool(
        production_skus, request.app.state.settings, context, engine
    )
    result = await run_in_threadpool(parse_opening, bytes(raw), filename, catalog)
    digest = await run_in_threadpool(
        retain_source,
        request.app.state.settings.production_inventory_source_root,
        context.site_id,
        context.principal_user_id,
        bytes(raw),
    )
    return {**result, "source_id": digest, "filename": filename}


@router.get("/inventory/opening-table/source/{source_id}")
def opening_table_source(
    source_id: str, request: Request, context: CatalogReadContext
) -> Response:
    from app.production.opening_tables import read_source

    require_catalog_manager(context)
    raw = read_source(
        request.app.state.settings.production_inventory_source_root,
        context.site_id,
        context.principal_user_id,
        source_id,
    )
    return Response(
        raw,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="opening-source.xlsx"'},
    )


@router.post("/inventory/openings/{action}")
def stock_opening(
    action: Literal["preview", "confirm"],
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: Annotated[dict[str, object], Body()],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    if isinstance(body.get("opening_source"), dict):
        from app.production.opening_tables import read_source

        read_source(
            request.app.state.settings.production_inventory_source_root,
            context.site_id,
            context.principal_user_id,
            str(cast(dict[str, Any], body["opening_source"]).get("source_id", "")),
        )
    return _stock_command(f"openings/{action}", request, context, engine, body, key)


@router.post("/inventory/{resource}/{document_id}/{action}")
def stock_change(
    resource: Literal[
        "documents",
        "reservations",
        "holds",
        "loans",
        "plans",
        "destination-receipts",
        "destination-settlements",
        "transport-records",
        "transport-events",
    ],
    document_id: int,
    action: str,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: Annotated[dict[str, object], Body()],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    return _stock_command(
        f"{resource}/{document_id}/{action}", request, context, engine, body, key
    )


@router.get("/summary")
def summary(request: Request, context: CatalogReadContext) -> object:
    return production_request(
        request.app.state.settings,
        context,
        "GET",
        "summary",
        query=list(request.query_params.multi_items()),
    )


@router.get("/commands/{token}")
def result(token: UUID, request: Request, context: CatalogReadContext) -> object:
    return production_request(
        request.app.state.settings, context, "GET", f"commands/{token}"
    )


def _table_order(
    request: Request,
    context: CatalogReadContext,
    document_id: int,
    expected_revision: str,
) -> dict[str, object]:
    order = cast(
        dict[str, object],
        production_request(
            request.app.state.settings, context, "GET", f"orders/{document_id}"
        ),
    )
    if str(order.get("revision")) != expected_revision:
        raise ApiError(
            409, "stale_order_revision", "生产单已更新。请刷新当前订单并重新预览表格。"
        )
    return order


def _receipt_batch(
    request: Request, context: CatalogReadContext, orders: str
) -> dict[str, object]:
    refs = orders.split(",")
    if (
        not 1 <= len(refs) <= 20
        or any(
            not re.fullmatch(r"[1-9][0-9]{0,18}:[1-9][0-9]{0,18}", ref) for ref in refs
        )
        or len({ref.split(":")[0] for ref in refs}) != len(refs)
    ):
        raise ApiError(
            422, "invalid_receipt_orders", "每批请选择1至20张不同的已确认订单。"
        )
    return receipt_batch_order(
        [
            _table_order(request, context, int(ref.split(":")[0]), ref.split(":")[1])
            for ref in refs
        ]
    )


@router.get("/receipt-batches/table/template")
def receipt_batch_template(
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
    orders: Annotated[str, Query(min_length=1, max_length=800)],
) -> Response:
    return Response(
        content=operation_template(
            _receipt_batch(request, context, orders),
            "receipt",
            production_skus(request.app.state.settings, context, engine),
        ),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                'attachment; filename="production-receipt-batch.xlsx"'
            )
        },
    )


@router.get("/receipt-batches/sources")
def receipt_batch_sources(
    request: Request,
    context: CatalogReadContext,
    orders: Annotated[str, Query(min_length=1, max_length=800)],
) -> object:
    return _receipt_batch(request, context, orders)


@router.post("/receipt-batches/table/preview")
async def receipt_batch_preview(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    orders: Annotated[str, Query(min_length=1, max_length=800)],
    filename: str = "upload.xlsx",
) -> object:
    require_catalog_manager(context)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_UPLOAD_BYTES:
            raise ApiError(413, "file_too_large", "请选择不超过2MB的标准XLSX文件。")
        raw.extend(chunk)
    order = await run_in_threadpool(_receipt_batch, request, context, orders)
    catalog = await run_in_threadpool(
        production_skus, request.app.state.settings, context, engine
    )
    result = await run_in_threadpool(
        preview_operation, bytes(raw), filename, order, "receipt", catalog
    )
    return await run_in_threadpool(
        remember_baseline,
        _table_baseline_root(request),
        context,
        "receipt",
        bytes(raw),
        result,
    )


def _dispatch_scope(
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
    warehouse_id: int,
    owner_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    state = production_request(
        request.app.state.settings,
        context,
        "GET",
        "inventory/availability",
        query=[("warehouse_id", str(warehouse_id)), ("owner_id", str(owner_id))],
    )
    scopes = [
        s
        for s in cast(dict[str, Any], state)["scopes"]
        if str(s["warehouse_id"]) == str(warehouse_id)
        and str(s["owner_id"]) == str(owner_id)
    ]
    if (
        len(scopes) != 1
        or scopes[0].get("warehouse_status") != "ACTIVE"
        or scopes[0].get("warehouse_type") not in ("OWN", "FACTORY", "THIRD_PARTY")
    ):
        raise ApiError(
            409,
            "dispatch_scope_unavailable",
            "请选择已启用、已建账的普通来源仓库与货主。FBA不能从此入口发货。",
        )
    catalog = production_skus(request.app.state.settings, context, engine)
    ids = {
        str(row["sku_id"])
        for row in cast(dict[str, Any], state)["items"]
        if str(row["warehouse_id"]) == str(warehouse_id)
        and str(row["owner_id"]) == str(owner_id)
    }
    return scopes[0], {
        key: value
        for key, value in catalog.items()
        if key in ids and value["status"] == "active"
    }


@router.get("/shipments/table/template")
def warehouse_dispatch_template(
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
    warehouse_id: int,
    owner_id: int,
) -> Response:
    scope, catalog = _dispatch_scope(request, context, engine, warehouse_id, owner_id)
    return Response(
        dispatch_template(scope, catalog),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="warehouse-dispatch.xlsx"'
        },
    )


@router.post("/shipments/table/preview")
async def warehouse_dispatch_preview(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    warehouse_id: int,
    owner_id: int,
    filename: str = "upload.xlsx",
    layout: Literal["standard", "packing_totals"] = "standard",
) -> object:
    require_catalog_manager(context)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_UPLOAD_BYTES:
            raise ApiError(413, "file_too_large", "请选择不超过2MB的XLSX出货表。")
        raw.extend(chunk)
    scope, catalog = await run_in_threadpool(
        _dispatch_scope, request, context, engine, warehouse_id, owner_id
    )
    result = await run_in_threadpool(
        preview_dispatch, bytes(raw), filename, scope, catalog, layout
    )
    original, _ = await run_in_threadpool(
        register_upload,
        Path(request.app.state.settings.production_inventory_source_root)
        / "warehouse-dispatch",
        context,
        "shipments",
        result["filename"],
        bytes(raw),
        result,
    )
    result["source_id"] = original["sample_id"]
    return result


@router.post("/shipments/table/combine")
def warehouse_dispatch_combine(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: DispatchSourcesInput,
) -> object:
    require_catalog_manager(context)
    scope, catalog = _dispatch_scope(
        request, context, engine, int(body.warehouse_id), int(body.owner_id)
    )
    root = (
        Path(request.app.state.settings.production_inventory_source_root)
        / "warehouse-dispatch"
    )
    return preview_dispatch_sources(root, context, body.sources, scope, catalog)


@router.post("/shipments/table/reviews")
def warehouse_dispatch_review_save(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: DispatchReviewInput,
) -> object:
    require_catalog_manager(context)
    scope, catalog = _dispatch_scope(
        request, context, engine, int(body.warehouse_id), int(body.owner_id)
    )
    root = (
        Path(request.app.state.settings.production_inventory_source_root)
        / "warehouse-dispatch"
    )
    return save_dispatch_review(root, context, body, scope, catalog)


@router.get("/shipments/table/reviews/{review_id}")
def warehouse_dispatch_review_read(
    review_id: str, request: Request, context: CatalogReadContext
) -> object:
    root = (
        Path(request.app.state.settings.production_inventory_source_root)
        / "warehouse-dispatch"
    )
    return uploaded_review(root, context, review_id)


@router.get("/shipments/table/sources/{source_id}")
def warehouse_dispatch_original(
    source_id: str, request: Request, context: CatalogReadContext
) -> Response:
    raw = uploaded_bytes(
        Path(request.app.state.settings.production_inventory_source_root)
        / "warehouse-dispatch",
        context,
        source_id,
        "shipments",
    )
    return Response(
        raw,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="dispatch-original.xlsx"'
        },
    )


@router.get("/orders/{document_id}/tables/{operation}/template")
def workbench_template(
    document_id: int,
    operation: Literal["receipt", "packing"],
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
    expected_revision: Annotated[str, Query(min_length=1, max_length=20)],
) -> Response:
    order = _table_order(request, context, document_id, expected_revision)
    return Response(
        content=operation_template(
            order,
            operation,
            production_skus(request.app.state.settings, context, engine)
            if operation == "receipt"
            else None,
        ),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="production-{operation}'
                f'-order-{document_id}.xlsx"'
            )
        },
    )


@router.post("/orders/{document_id}/tables/{operation}/preview")
async def workbench_table_preview(
    document_id: int,
    operation: Literal["receipt", "packing"],
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    expected_revision: Annotated[str, Query(min_length=1, max_length=20)],
    filename: str = "upload.xlsx",
) -> object:
    require_catalog_manager(context)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_UPLOAD_BYTES:
            raise ApiError(413, "file_too_large", "请选择不超过2MB的标准XLSX文件。")
        raw.extend(chunk)
    order = await run_in_threadpool(
        _table_order, request, context, document_id, expected_revision
    )
    catalog = (
        await run_in_threadpool(
            production_skus, request.app.state.settings, context, engine
        )
        if operation == "receipt"
        else None
    )
    result = await run_in_threadpool(
        preview_operation, bytes(raw), filename, order, operation, catalog
    )
    return await run_in_threadpool(
        remember_baseline,
        _table_baseline_root(request),
        context,
        operation,
        bytes(raw),
        result,
    )


@router.get("/files/{kind}/template")
def template(
    kind: Kind,
    request: Request,
    context: CatalogReadContext,
    version: Literal["v1", "v2", "v3", "v4"] = "v1",
) -> Response:
    if version == "v4" and kind != "orders":
        raise ApiError(422, "invalid_template_version", "四字段模板仅适用于下单表。")
    content = (
        render_order_table(None, {}, site_id=context.site_id)
        if version == "v4"
        else production_request(
            request.app.state.settings,
            context,
            "GET",
            f"files/{kind}/template",
            query=[("version", version)],
            binary=True,
        )
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="production-{kind}-{version}.xlsx"'
            )
        },
    )


@router.get("/orders/{order_id}/table")
def order_table_export(
    order_id: int,
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
) -> Response:
    document = cast(
        dict[str, object],
        production_request(
            request.app.state.settings, context, "GET", f"orders/{order_id}"
        ),
    )
    content = render_order_table(
        document,
        production_skus(request.app.state.settings, context, engine),
        site_id=context.site_id,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="order-{order_id}-v4.xlsx"'
        },
    )


@router.get("/files/{kind}/export")
def export(
    kind: Literal["orders", "shipments", "summary"],
    request: Request,
    context: CatalogReadContext,
) -> Response:
    content = production_request(
        request.app.state.settings,
        context,
        "GET",
        f"files/{kind}/export",
        query=list(request.query_params.multi_items()),
        binary=True,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="production-{kind}.xlsx"'
        },
    )


@router.post("/files/{kind}/preview")
async def preview(
    kind: Kind,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    mode: Literal["create", "correct"],
    filename: str = "upload.xlsx",
    target_id: str = "",
    reason: str = "",
    manual_source_note: str = "",
    overage_reason: str = "",
    workbench_order: bool = False,
    factory_id: str = "",
    receipt_warehouse_id: str = "",
    receipt_owner_id: str = "",
    destination: str = "",
    destination_id: str = "",
    destination_type: str = "",
) -> object:
    require_catalog_manager(context)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 2_000_000:
            raise ApiError(413, "file_too_large", "请选择不超过2MB的标准XLSX文件。")
        raw.extend(chunk)
    catalog = await run_in_threadpool(
        production_skus, request.app.state.settings, context, engine
    )
    body: dict[str, object] = {
        "file_base64": base64.b64encode(raw).decode("ascii"),
        "filename": filename,
        "mode": mode,
        "target_id": target_id,
        "reason": reason,
        "manual_source_note": manual_source_note,
        "overage_reason": overage_reason,
        "_catalog": catalog,
    }
    if workbench_order:
        body.update(
            workbench_order=True,
            factory_id=factory_id,
            receipt_warehouse_id=receipt_warehouse_id,
            receipt_owner_id=receipt_owner_id,
            destination=destination,
            destination_id=destination_id or None,
            destination_type=destination_type,
        )
    import io

    import openpyxl  # type: ignore[import-untyped]

    specification_ids = False
    source = None
    try:
        with ZipFile(io.BytesIO(raw)) as package:
            if (
                len(package.infolist()) > 1000
                or sum(item.file_size for item in package.infolist()) > 20_000_000
            ):
                raise ValueError("workbook size")
        if workbench_order and kind == "orders":
            source = await run_in_threadpool(parse_order_table, bytes(raw), filename)
        if source is not None:
            if mode != "create":
                raise ApiError(
                    422, "invalid_mode", "原下单表请先生成草稿。历史更正请打开原订单。"
                )
            if len(source["rows"]) > 500:
                raise ApiError(
                    422, "too_many_rows", "一份订单最多500条明细。请拆分文件。"
                )
            codes = [row["sku_code"] for row in source["rows"]]
            body["file_base64"] = base64.b64encode(
                standard_order_workbook(source)
            ).decode("ascii")
            body["_original_file_base64"] = base64.b64encode(raw).decode("ascii")
            body["_order_source"] = source
        else:
            with io.BytesIO(raw) as stream:
                book = openpyxl.load_workbook(stream, read_only=True, data_only=False)
                try:
                    if len(book.worksheets) != 1 or book.active.max_row > 501:
                        raise ValueError("workbook dimensions")
                    specification_ids = (
                        workbench_order
                        and kind == "orders"
                        and book.active.title == "预计订单_v3"
                    )
                    column = 2 if kind == "orders" else 3
                    codes = [
                        _standard_code_cell(row[column])
                        for row in book.active.iter_rows(min_row=2, max_row=501)
                        if len(row) > column and row[column].value is not None
                    ]
                finally:
                    book.close()
    except (ValueError, BadZipFile, InvalidFileException, KeyError) as error:
        raise ApiError(422, "invalid_workbook", "标准表无法读取。") from error
    if not specification_ids:
        body["_resolved_codes"] = await run_in_threadpool(
            resolve_standard_codes,
            engine,
            context,
            catalog,
            codes,
            demo=request.app.state.settings.production_demo_mode,
        )
    if source is not None:
        resolved = cast(dict[str, dict[str, str | None]], body["_resolved_codes"])
        for row in source["rows"]:
            identity = resolved.get(row["sku_code"])
            if identity:
                row["sku_id"] = identity["sku_id"]
                row["sku_label"] = identity["label"]
                row["mapping_status"] = "MATCHED"
                if identity.get("style_code") != row["style_code"]:
                    source["issues"].append(
                        {
                            "row": row["source_row"],
                            "sheet": source["sheet"],
                            "message": "原款号与该SKU在当前目录的所属款号不一致。"
                            "请核对。不会拆SKU猜归属。",
                        }
                    )
        exported = source["export_source"]
        if exported:
            if (
                exported["site_id"] != str(context.site_id)
                or not exported["order_id"].isascii()
                or not exported["order_id"].isdecimal()
            ):
                raise ApiError(
                    422,
                    "order_export_scope",
                    "导出下单表不属于当前站点或来源订单标识无效。请从原订单重新导出。",
                )
            existing = cast(
                dict[str, object],
                await run_in_threadpool(
                    production_request,
                    request.app.state.settings,
                    context,
                    "GET",
                    f"orders/{exported['order_id']}",
                ),
            )
            expected = sorted(
                (str(line["sku_id"]), str(line["expected_units"]))
                for line in cast(list[dict[str, object]], existing.get("lines", []))
            )
            actual = sorted(
                (str(row["sku_id"]), row["expected_units"]) for row in source["rows"]
            )
            if (
                source["business_date"] != existing.get("business_date")
                or actual != expected
                or exported["revision"] != str(existing.get("revision"))
                or existing.get("status") == "VOID"
            ):
                source["issues"].append(
                    {
                        "row": 0,
                        "message": "这份表来自已有订单。内容或修订已变化。"
                        "请打开原订单核对或更正。不能据此新增订单。",
                    }
                )
            return {
                "preview_id": "",
                "filename": filename,
                "rows": [],
                "issues": source["issues"],
                "command": {"business_date": source["business_date"]},
                "source_table": source,
                "duplicate_document": existing,
                "source_check": {"candidates": []},
            }
    result = await run_in_threadpool(
        production_request,
        request.app.state.settings,
        context,
        "POST",
        f"files/{kind}/preview",
        body=body,
    )
    if kind == "orders" and workbench_order:
        return await run_in_threadpool(
            remember_baseline,
            _table_baseline_root(request),
            context,
            "orders",
            bytes(raw),
            cast(dict[str, Any], result),
        )
    return result


@router.post("/files/previews/{preview_id}/confirm")
def confirm_preview(
    preview_id: UUID,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: Annotated[dict[str, object], Body()],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    require_catalog_manager(context)
    if body.get("operation_token") != str(key):
        raise ApiError(
            422, "idempotency_key_mismatch", "操作ID必须与Idempotency-Key一致。"
        )
    payload: dict[str, object] = {
        "operation_token": str(key),
        "_catalog": production_skus(request.app.state.settings, context, engine),
        "_actor_name": _operation_actor(context, engine),
    }
    return production_request(
        request.app.state.settings,
        context,
        "POST",
        f"files/previews/{preview_id}/confirm",
        body=payload,
        operation_key=str(key),
    )


@router.get("/workbench")
def workbench(request: Request, context: CatalogReadContext) -> object:
    return production_request(request.app.state.settings, context, "GET", "workbench")


@router.get("/factories")
def factories(request: Request, context: CatalogReadContext) -> object:
    return production_request(
        request.app.state.settings,
        context,
        "GET",
        "factories",
        query=list(request.query_params.multi_items()),
    )


@router.post("/factories")
def create_factory(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: Annotated[dict[str, object], Body()],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    require_catalog_manager(context)
    if str(body.get("operation_token", "")) != str(key):
        raise ApiError(
            422, "idempotency_key_mismatch", "操作ID必须与Idempotency-Key一致。"
        )
    return production_request(
        request.app.state.settings,
        context,
        "POST",
        "factories",
        body=_directory_payload(body, key, context, engine),
        operation_key=str(key),
    )


def _directory_payload(
    body: dict[str, object],
    key: UUID,
    context: CatalogWriteContext,
    engine: CatalogEngine,
) -> dict[str, object]:
    require_catalog_manager(context)
    seller = str(body.get("seller_account", ""))
    if seller.startswith("scope:"):
        scope_id = seller.removeprefix("scope:")
        with engine.connect() as connection:
            scope = connection.execute(
                sql_text(
                    "SELECT id FROM report_source_scopes "
                    "WHERE site_id=:site AND id=:id "
                    "AND marketplace_scope_code='amazon_us'"
                ),
                {
                    "site": context.site_id,
                    "id": scope_id if scope_id.isdecimal() else "0",
                },
            ).scalar()
        if scope is None or body.get("marketplace") != "US":
            raise ApiError(
                422, "warehouse_source_scope", "请选择本站点已确认的卖家店铺与站点。"
            )
    if str(body.get("operation_token", "")) != str(key):
        raise ApiError(
            422, "idempotency_key_mismatch", "操作ID必须与Idempotency-Key一致。"
        )
    fields = (
        "name",
        "status",
        "region",
        "address",
        "operator",
        "contact",
        "phone",
        "timezone",
        "seller_account",
        "marketplace",
        "notes",
        "external_code",
        "type",
        "country",
        "warehouse_ids",
        "factory_ids",
        "expected_revision",
        "reason",
    )
    return {
        **{field: body[field] for field in fields if field in body},
        "operation_token": str(key),
        "_actor_name": _operation_actor(context, engine),
    }


@router.get("/warehouses")
def warehouses(request: Request, context: CatalogReadContext) -> object:
    return production_request(
        request.app.state.settings,
        context,
        "GET",
        "warehouses",
        query=list(request.query_params.multi_items()),
    )


@router.get("/factories/{entity_id}")
@router.get("/warehouses/{entity_id}")
def directory_detail(
    entity_id: int, request: Request, context: CatalogReadContext, engine: CatalogEngine
) -> object:
    kind = request.url.path.split("/")[-2]
    result = cast(
        dict[str, Any],
        production_request(
            request.app.state.settings, context, "GET", f"{kind}/{entity_id}"
        ),
    )
    if kind == "warehouses":
        from app.production.inventory_sheet_source import (
            directory_evidence,
            load_sheet_source,
            reconcile_source_catalog,
        )

        source = load_sheet_source(request.app.state.settings, context, engine)
        if source is not None:
            source = reconcile_source_catalog(
                source,
                production_skus(request.app.state.settings, context, engine),
            )
        evidence = directory_evidence(source, result)
        if evidence is not None:
            result["source_evidence"] = evidence
            if evidence["kind"] == "domestic" and source is not None:
                from app.production.identity import warehouse_product_scope

                result["inventory_product_scope"] = warehouse_product_scope(
                    engine,
                    context,
                    warehouse_id=str(entity_id),
                    report_source_scope_id=int(source["report_source_scope_id"]),
                )
        if "inventory_product_scope" not in result:
            from app.production.identity import configured_warehouse_product_scope

            scope = configured_warehouse_product_scope(
                request.app.state.settings, context, engine, result
            )
            if scope is not None:
                result["inventory_product_scope"] = scope
    return result


@router.post("/warehouses")
@router.put("/warehouses/{entity_id}")
@router.put("/factories/{entity_id}")
def directory_save(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: Annotated[dict[str, object], Body()],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
    entity_id: int | None = None,
) -> object:
    path = request.url.path.removeprefix("/api/production/")
    return production_request(
        request.app.state.settings,
        context,
        request.method,
        path,
        body=_directory_payload(body, key, context, engine),
        operation_key=str(key),
    )


@router.get("/{kind}")
def list_documents(kind: Kind, request: Request, context: CatalogReadContext) -> object:
    return production_request(
        request.app.state.settings,
        context,
        "GET",
        kind,
        query=list(request.query_params.multi_items()),
    )


@router.get("/{kind}/{document_id}")
def document(
    kind: Kind, document_id: int, request: Request, context: CatalogReadContext
) -> object:
    return production_request(
        request.app.state.settings, context, "GET", f"{kind}/{document_id}"
    )


def send_command(
    kind: Kind,
    document_id: int | None,
    action: str,
    method: str,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: dict[str, object],
    key: UUID,
) -> object:
    require_catalog_manager(context)
    if str(body.get("operation_token", "")) != str(key):
        raise ApiError(
            422, "idempotency_key_mismatch", "操作ID必须与Idempotency-Key一致。"
        )
    settings = request.app.state.settings
    path = kind if document_id is None else f"{kind}/{document_id}"
    if action not in {"create", "update", "delete"}:
        path += f"/{action}"
    # Caller-provided identity metadata is always replaced by server authority.
    body = dict(body)
    body.pop("_source_digest", None)
    baseline_id = body.pop("_table_baseline_id", None)
    if baseline_id is not None:
        if kind != "orders" or not isinstance(baseline_id, str):
            raise ApiError(422, "invalid_baseline", "原表引用与当前业务不一致。")
        original = read_baseline(_table_baseline_root(request), context, baseline_id)
        if original["kind"] != "orders":
            raise ApiError(422, "invalid_baseline", "此原表不属于下单业务。")
        body["_source_digest"] = original["source_id"].rsplit("-", 1)[-1]
        body.update(original.get("command_source", {}))
    body["_catalog"] = production_skus(settings, context, engine)
    body["_actor_name"] = _operation_actor(context, engine)
    return production_request(
        settings, context, method, path, body=body, operation_key=str(key)
    )


@router.post("/{kind}")
def create(
    kind: Kind,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: Annotated[dict[str, object], Body()],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    return send_command(
        kind, None, "create", "POST", request, context, engine, body, key
    )


@router.post("/sources/{kind}/check")
def source_check(
    kind: Kind,
    request: Request,
    context: CatalogWriteContext,
    body: Annotated[dict[str, object], Body()],
) -> object:
    require_catalog_manager(context)
    return production_request(
        request.app.state.settings, context, "POST", f"sources/{kind}/check", body=body
    )


@router.put("/{kind}/{document_id}")
def update(
    kind: Kind,
    document_id: int,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: Annotated[dict[str, object], Body()],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    return send_command(
        kind, document_id, "update", "PUT", request, context, engine, body, key
    )


@router.delete("/{kind}/{document_id}")
def delete(
    kind: Kind,
    document_id: int,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: Annotated[dict[str, object], Body()],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    return send_command(
        kind, document_id, "delete", "DELETE", request, context, engine, body, key
    )


@router.post("/{kind}/{document_id}/{action}")
def change(
    kind: Kind,
    document_id: int,
    action: Literal[
        "confirm",
        "correct",
        "void",
        "demand-changes",
        "close-tracking",
        "reopen-tracking",
        "allocation-corrections",
        "production-progress",
        "complete-production",
        "reopen-production",
    ],
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: Annotated[dict[str, object], Body()],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    return send_command(
        kind, document_id, action, "POST", request, context, engine, body, key
    )


def _standard_code_cell(cell: object) -> str:
    """Mirror the existing Java template string/integer conversion for lookup keys."""
    value = getattr(cell, "value", None)
    if getattr(cell, "data_type", None) == "s":
        return str(value).strip("".join(chr(i) for i in range(33)))
    if (
        getattr(cell, "data_type", None) == "n"
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value == int(value)
        and abs(value) <= 9007199254740991
    ):
        return str(int(value))
    return ""  # Java reports formulas, dates and unsupported types with row context.
