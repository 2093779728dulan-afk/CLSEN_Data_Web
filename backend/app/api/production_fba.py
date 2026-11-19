"""Dedicated FBA adaptation; source parsing never posts stock by itself."""

# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
import base64
import hashlib
import logging
from collections.abc import Collection
from datetime import date
from typing import Annotated, Any, Literal, cast
from urllib.parse import unquote
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.engine import Engine
from starlette.concurrency import run_in_threadpool

from app.api.catalog_common import (
    CatalogEngine,
    CatalogReadContext,
    CatalogWriteContext,
    require_catalog_manager,
)
from app.api.dependencies import require_write_roles
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.catalog.normalization import seller_sku_match_v1
from app.production.client import production_request
from app.production.fba_catalog_products import catalog_products
from app.production.fba_daily import load_reports, report_projection
from app.production.fba_opening_identity import (
    parse_identity_source,
    read_identity_source,
    retain_identity_source,
    verify_identity,
)
from app.production.fba_receipts import (
    export_batch,
    parse_receipts,
    parse_review_payload,
    prepare_receipt_decisions,
)
from app.production.fba_reconciliation import (
    export_reconciliation,
    inventory_view,
    reconcile,
)
from app.production.identity import catalog_for_report_scope, production_skus
from app.site_context import CurrentSiteContext

router = APIRouter(prefix="/fba", tags=["production-fba"])


def child_stock_key(key: UUID, stage: str) -> UUID:
    # The Java command contract requires version 4, including derived stages.
    return UUID(bytes=uuid5(key, stage).bytes, version=4)


Command = Literal[
    "scopes",
    "extend-identities",
    "tracking",
    "references",
    "unified-save",
    "unified-confirm",
    "batch-save",
    "batch-confirm",
    "batch-abandon",
    "actions",
    "action-reverse",
    "quality",
    "classification-correct",
    "stocktake",
]


async def upload_bytes(request: Request) -> bytes:
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 2_000_000:
            raise ApiError(413, "fba_file_too_large", "文件不能超过2MB。")
    return bytes(content)


def read(
    request: Request,
    context: CatalogReadContext,
    resource: str,
    query: list[tuple[str, str]] | None = None,
) -> Any:
    return production_request(
        request.app.state.settings, context, "GET", "inventory/" + resource, query=query
    )


def send(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    command: str,
    body: dict[str, Any],
    key: UUID,
) -> Any:
    from app.api.production import _stock_command

    payload = dict(body)
    if command in {"action-reverse", "batch-confirm"}:
        reference_field = "action_id" if command == "action-reverse" else "batch_id"
        reference = str(payload.get(reference_field, ""))
        if (
            not reference.isdecimal()
            or len(reference) > 19
            or not 0 < int(reference) <= 9223372036854775807
        ):
            raise ApiError(422, "invalid_source", "请选择有效的原记录。")
    if command == "action-reverse":
        source_scope = cast(
            dict[str, Any],
            read(
                request,
                context,
                f"fba-action-scopes/{int(payload.get('action_id', 0))}",
            ),
        )
        payload["scope_id"] = source_scope["id"]
    if command == "batch-confirm":
        batch = cast(
            dict[str, Any],
            read(request, context, f"fba-batches/{int(payload.get('batch_id', 0))}"),
        )
        payload["scope_id"] = batch["scope_id"]
    if (
        command
        in {
            "actions",
            "action-reverse",
            "report-sync",
            "quality",
            "classification-correct",
            "stocktake",
            "unified-save",
            "unified-confirm",
            "batch-confirm",
        }
        and payload.get("scope_id")
        and "_auto_setup" not in payload
    ):
        setup = receipt_product_setup(
            request, context, engine, payload["scope_id"], set()
        )
        if setup:
            payload["_auto_setup"] = setup
    return _stock_command("fba-" + command, request, context, engine, payload, key)


def receipt_product_setup(
    request: Request,
    context: CurrentSiteContext,
    engine: Engine,
    scope_id: int | str,
    sku_ids: Collection[str],
) -> dict[str, Any] | None:
    """Prepare metadata for Java's atomic receipt and product setup transaction."""
    if not str(scope_id).isdecimal() or int(scope_id) <= 0:
        raise ApiError(422, "invalid_scope", "请选择有效的FBA仓库范围。")
    scope = cast(
        dict[str, Any],
        read(request, context, f"fba-scopes/{int(scope_id)}"),
    )
    current = cast(
        dict[str, Any],
        read(
            request,
            context,
            "fba-state",
            [("warehouse_id", str(scope["warehouse_id"]))],
        ),
    )
    existing = [
        item for item in current["identities"] if str(item["scope_id"]) == str(scope_id)
    ]
    missing = {str(value) for value in sku_ids} - {
        str(item["sku_id"]) for item in existing
    }
    if missing and not scope["simulated"]:
        return None
    catalog = production_skus(request.app.state.settings, context, engine)
    versions = {str(item["catalog_version"]) for item in catalog.values()}
    if not missing and versions == {str(scope["catalog_version"])}:
        return None
    with engine.connect() as connection:
        products = catalog_products(
            connection,
            context.site_id,
            int(scope["report_source_scope_id"]),
            catalog_for_report_scope(
                engine, context, catalog, int(scope["report_source_scope_id"])
            ),
        )
        if products["store"] != scope["store_evidence"]:
            raise ApiError(
                409, "fba_scope_conflict", "店铺资料已变化，请先核对本仓店铺。"
            )
        identities = [
            item for item in products["identities"] if item["sku_id"] in missing
        ]
        if not identities and not existing:
            return None
        approved = {item["sku_id"]: item for item in products["identities"]}
        conflicts = {
            item["sku_id"]
            for item in products["issues"]
            if item["code"] in {"platform_identity_conflict", "fnsku_conflict"}
        }
        verified = {}
        for item in existing + identities:
            sku_id = str(item["sku_id"])
            latest = approved.get(sku_id)
            if sku_id in conflicts or (
                latest
                and any(
                    latest[field] != item[field]
                    for field in ("seller_sku", "asin", "fnsku")
                )
            ):
                raise ApiError(
                    409,
                    "fba_identity_conflict",
                    f"{item['seller_sku']}的平台身份已变化，请核对商品资料后继续。",
                )
            excluded = connection.scalar(
                text(
                    "SELECT id FROM product_catalog_exclusions WHERE site_id=:site "
                    "AND catalog_version_id=:version "
                    "AND report_source_scope_id=:scope "
                    "AND seller_sku_match_bytes=:match"
                ),
                {
                    "site": context.site_id,
                    "version": int(products["catalog_version"].split(":")[0]),
                    "scope": scope["report_source_scope_id"],
                    "match": seller_sku_match_v1(item["seller_sku"]).utf8,
                },
            )
            if excluded:
                raise ApiError(
                    409,
                    "fba_identity_conflict",
                    f"{item['seller_sku']}已有排除决定，请核对商品关联。",
                )
            mappings = (
                connection.execute(
                    text(
                        "SELECT sku_id FROM product_catalog_mappings "
                        "WHERE site_id=:site "
                        "AND report_source_scope_id=:scope "
                        "AND catalog_version_id=:version "
                        "AND seller_sku_match_bytes=:match"
                    ),
                    {
                        "site": context.site_id,
                        "scope": scope["report_source_scope_id"],
                        "version": int(products["catalog_version"].split(":")[0]),
                        "match": seller_sku_match_v1(item["seller_sku"]).utf8,
                    },
                )
                .scalars()
                .all()
            )
            verified[str(item["sku_id"])] = verify_identity(
                item, catalog, [str(key) for key in mappings]
            )
    return {
        "identities": identities,
        "catalog_version": products["catalog_version"],
        "identities_confirmed": True,
        "explicit_zero_opening": True,
        "scope_id": str(scope_id),
        "store_evidence": scope["store_evidence"],
        "reason": "自动核对当前目录与本仓已确认商品身份，保留原跟踪状态及库存事实",
        "_fba_scope": {
            "id": str(scope["report_source_scope_id"]),
            "seller_account": scope["seller_account"],
        },
        "_fba_identities": verified,
        "sku_ids": [
            str(item["sku_id"])
            for item in existing
            if str(item["tracked"]).lower() in {"true", "1"}
        ],
        "reconfirm_catalog": True,
    }


@router.get("/state")
def state(
    request: Request,
    context: CatalogReadContext,
    warehouse_id: int,
    engine: CatalogEngine,
) -> Any:
    result = cast(
        dict[str, Any],
        read(request, context, "fba-state", [("warehouse_id", str(warehouse_id))]),
    )
    if result.get("initialized"):
        result["reconciliation"] = {
            str(s["id"]): reconcile(result, str(s["id"])) for s in result["scopes"]
        }
        result["inventory_view"] = {
            str(s["id"]): inventory_view(
                result, str(s["id"]), result["reconciliation"][str(s["id"])]
            )
            for s in result["scopes"]
        }
        result["daily"] = {}
        with engine.connect() as connection:
            for scope in result["scopes"]:
                projection = report_projection(
                    load_reports(connection, context.site_id, scope),
                    scope,
                    result["identities"],
                    result["actions"],
                )
                projection["issues"].extend(projection.pop("sync_issues"))
                result["daily"][str(scope["id"])] = projection
    return result


def sync_daily(
    request: Request,
    context: CurrentSiteContext,
    engine: Engine,
    scope_id: int,
    key: UUID,
    derive_key: bool = False,
) -> dict[str, Any]:
    lock_name = f"fba-daily:{context.site_id}:{scope_id}"
    with engine.connect() as connection:
        acquired = connection.scalar(
            text("SELECT GET_LOCK(:name,5)"), {"name": lock_name}
        )
        if acquired != 1:
            raise ApiError(409, "fba_daily_busy", "本仓日报正在更新，请稍后重试。")
        try:
            return _sync_daily_locked(
                request, context, engine, scope_id, key, derive_key
            )
        finally:
            connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})


def _sync_daily_locked(
    request: Request,
    context: CurrentSiteContext,
    engine: Engine,
    scope_id: int,
    key: UUID,
    derive_key: bool,
) -> dict[str, Any]:
    scope = cast(dict[str, Any], read(request, context, f"fba-scopes/{scope_id}"))
    current = cast(
        dict[str, Any],
        read(
            request,
            context,
            "fba-state",
            [("warehouse_id", str(scope["warehouse_id"]))],
        ),
    )
    with engine.connect() as connection:
        projection = report_projection(
            load_reports(connection, context.site_id, scope),
            scope,
            current["identities"],
            current["actions"],
        )
    sync_key = (
        child_stock_key(key, "daily:" + ",".join(projection["report_version_ids"]))
        if derive_key
        else key
    )
    result = send(
        request,
        context,
        engine,
        "report-sync",
        {
            "operation_token": str(sync_key),
            "scope_id": str(scope_id),
            "_report_source_scope_id": str(scope["report_source_scope_id"]),
            "_trusted_report_returns": projection["returns"],
            "_trusted_report_sales": projection["sales"],
            "_report_set_complete": not projection["issues"],
            "report_version_ids": projection["report_version_ids"],
            "reason": "已发布日报自动更新FBA，保留报告版本及原始商品依据",
        },
        sync_key,
    )
    return {"updated": result, "issues": projection["issues"]}


@router.post("/daily/sync")
def update_daily(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    scope_id: int,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    require_catalog_manager(context)
    return sync_daily(request, context, engine, scope_id, key)


@router.post("/daily/uploads")
async def upload_daily(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    principal: Annotated[
        Principal, Depends(require_write_roles("admin", "data_manager"))
    ],
    scope_id: int,
    report_date: date,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
    filename: Annotated[str, Header(alias="X-Original-Filename")],
) -> dict[str, Any]:
    from app.api.workbench import upload_workbench_import
    from app.catalog.return_dedup_repository import ReturnDedupError
    from app.production.fba_daily_import import publish_clean_daily

    require_catalog_manager(context)
    scope = cast(dict[str, Any], read(request, context, f"fba-scopes/{scope_id}"))
    if report_date.isoformat() <= str(scope["cutoff_on"]):
        raise ApiError(409, "fba_report_cutoff", "日报日期须晚于本仓期初截止日期。")
    result = await upload_workbench_import(
        request,
        principal,
        engine,
        key,
        report_date=report_date,
        original_filename=filename,
    )
    if (
        result.dataset_id
        and result.version_id
        and result.status in {"workspace_ready", "duplicate"}
    ):
        with engine.connect() as connection:
            assigned = connection.scalar(
                text(
                    "SELECT report_source_scope_id "
                    "FROM report_dataset_scope_assignments "
                    "WHERE dataset_id=:dataset AND site_id=:site"
                ),
                {"dataset": result.dataset_id, "site": context.site_id},
            )
        if str(assigned) != str(scope["report_source_scope_id"]):
            raise ApiError(
                409,
                "fba_report_scope_mismatch",
                "报告所属店铺与本仓不一致，请核对报告来源。",
            )
        try:
            await run_in_threadpool(
                publish_clean_daily,
                engine,
                result.dataset_id,
                result.version_id,
                principal.user_id,
                key,
            )
        except ApiError as error:
            return {
                "status": "review_required",
                "message": cast(dict[str, str], error.detail)["message"],
                "workspace_url": result.workspace_url,
                "batch_id": result.batch_id,
            }
        except ReturnDedupError:
            return {
                "status": "review_required",
                "message": "退货报告需要完成去重核对，请继续原报告审核发布。",
                "workspace_url": result.workspace_url,
                "batch_id": result.batch_id,
            }
        try:
            update = await run_in_threadpool(
                sync_daily, request, context, engine, scope_id, key, True
            )
        except ApiError as error:
            return {
                "status": "inventory_pending",
                "message": "日报已发布，库存更新待重试。"
                + cast(dict[str, str], error.detail)["message"],
                "batch_id": result.batch_id,
            }
        return {
            "status": "partial" if update["issues"] else "updated",
            "message": f"日报已处理，另有{len(update['issues'])}项需要核对"
            if update["issues"]
            else "日报已处理，FBA库存及预计库存已更新",
            "batch_id": result.batch_id,
        }
    return {
        "status": "review_required",
        "message": result.message or "日报需要继续核对",
        "workspace_url": result.workspace_url,
        "batch_id": result.batch_id,
    }


def sync_published_daily(
    request: Request, context: CurrentSiteContext, engine: Engine
) -> None:
    """Keep publication durable and attempt each unambiguous warehouse separately."""
    if not request.app.state.settings.production_service_url:
        return
    try:
        scopes = cast(dict[str, Any], read(request, context, "fba-daily-scopes"))[
            "items"
        ]
    except ApiError as error:
        logging.getLogger(__name__).warning(
            "FBA daily update pending: %s", cast(dict[str, str], error.detail)["code"]
        )
        return
    for scope in scopes:
        if (
            sum(
                s["report_source_scope_id"] == scope["report_source_scope_id"]
                for s in scopes
            )
            != 1
        ):
            continue
        try:
            sync_daily(request, context, engine, scope["id"], uuid4())
        except ApiError as error:
            logging.getLogger(__name__).warning(
                "FBA daily update pending: %s",
                cast(dict[str, str], error.detail)["code"],
            )


@router.get("/daily/status")
def published_daily_status(
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
    report_date: date,
    report_type: Literal["business_report", "return_report"],
) -> Any:
    """Read actual report-to-stock results without repeating publication or writes."""
    if not request.app.state.settings.production_service_url:
        return {"items": []}
    with engine.connect() as connection:
        report_scopes = set(
            connection.execute(
                text("""
            SELECT DISTINCT a.report_source_scope_id
            FROM daily_datasets d
            JOIN dataset_publications p ON p.dataset_id=d.id
            JOIN report_dataset_scope_assignments a
              ON a.dataset_id=d.id AND a.site_id=d.site_id
            WHERE d.site_id=:site AND d.report_date=:day AND d.report_type=:kind
        """),
                {"site": context.site_id, "day": report_date, "kind": report_type},
            ).scalars()
        )
    scopes = cast(dict[str, Any], read(request, context, "fba-daily-scopes"))["items"]
    items = []
    for candidate in scopes:
        if int(candidate["report_source_scope_id"]) not in report_scopes:
            continue
        scope = cast(
            dict[str, Any], read(request, context, f"fba-scopes/{candidate['id']}")
        )
        if str(report_date) <= str(scope["cutoff_on"]):
            continue
        warehouse = str(scope["warehouse_id"])
        result = cast(dict[str, Any], state(request, context, int(warehouse), engine))
        issues = list(result["daily"][str(scope["id"])]["issues"])
        ambiguous = (
            sum(
                s["report_source_scope_id"] == candidate["report_source_scope_id"]
                for s in scopes
            )
            != 1
        )
        if ambiguous:
            issues.insert(
                0, {"label": "本店铺关联多个FBA仓库，请到库存页核对本次销售与退货归属"}
            )
        name = next(
            (
                s.get("warehouse_name")
                for s in result.get("stock", {}).get("scopes", [])
                if str(s.get("warehouse_id")) == warehouse
            ),
            None,
        )
        items.append(
            {
                "scope_id": str(scope["id"]),
                "warehouse_id": warehouse,
                "owner_id": str(scope["owner_id"]),
                "warehouse_name": name or "FBA库存",
                "status": "pending" if issues else "updated",
                "issues": issues,
                "can_retry": not ambiguous,
            }
        )
    return {"items": items}


@router.get("/reconciliation/export")
def reconciliation_export(
    request: Request, context: CatalogReadContext, warehouse_id: int, scope_id: int
) -> Response:
    data = cast(
        dict[str, Any],
        read(request, context, "fba-state", [("warehouse_id", str(warehouse_id))]),
    )
    return Response(
        export_reconciliation(data, str(scope_id)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="fba-reconciliation-view.xlsx"'
        },
    )


@router.get("/batches/{batch_id}")
def batch(batch_id: int, request: Request, context: CatalogReadContext) -> Any:
    return read(request, context, f"fba-batches/{batch_id}")


@router.get("/classifications")
def classifications(
    request: Request,
    context: CatalogReadContext,
    scope_id: int,
    view: str = "current",
    reason_code: str = "",
    sku_id: str = "",
    page: int = 1,
    page_size: int = 20,
    from_: Annotated[str, Query(alias="from")] = "",
    to: str = "",
) -> Any:
    return read(
        request,
        context,
        "fba-classifications",
        [
            ("scope_id", str(scope_id)),
            ("view", view),
            ("reason_code", reason_code),
            ("sku_id", sku_id),
            ("page", str(page)),
            ("page_size", str(page_size)),
            ("from", from_),
            ("to", to),
        ],
    )


@router.get("/batches/{batch_id}/original")
def original(batch_id: int, request: Request, context: CatalogReadContext) -> Response:
    require_catalog_manager(context)
    metadata = cast(dict[str, Any], read(request, context, f"fba-batches/{batch_id}"))
    content = production_request(
        request.app.state.settings,
        context,
        "GET",
        f"inventory/fba-batches/{batch_id}/original",
        binary=True,
    )
    return Response(
        content,
        media_type="application/json"
        if metadata.get("source_kind") == "MANUAL"
        else "text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="fba-manual-original.json"'
            if metadata.get("source_kind") == "MANUAL"
            else 'attachment; filename="fba-receipts-original.csv"'
        },
    )


@router.get("/batches/{batch_id}/export")
def export(batch_id: int, request: Request, context: CatalogReadContext) -> Response:
    data = cast(dict[str, Any], read(request, context, f"fba-batches/{batch_id}"))
    return Response(
        export_batch(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="fba-receipts-review.xlsx"'
        },
    )


@router.post("/batches/{batch_id}/reimport")
async def reimport(
    batch_id: int,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> Any:
    require_catalog_manager(context)
    raw = await upload_bytes(request)
    data = cast(
        dict[str, Any],
        await run_in_threadpool(read, request, context, f"fba-batches/{batch_id}"),
    )
    review = await run_in_threadpool(parse_review_payload, raw, data)
    if data.get("source_kind") == "MANUAL":
        return await run_in_threadpool(
            send,
            request,
            context,
            engine,
            "unified-save",
            {
                "operation_token": str(key),
                "batch_id": str(batch_id),
                "scope_id": str(data["scope_id"]),
                "shipment_id": str(data["shipment_id"]),
                "expected_revision": review["expected_revision"],
                "expected_shipment_revision": review["draft_payload"][
                    "shipment_revision"
                ],
                "draft_payload": review["draft_payload"],
                "source_review_sha256": hashlib.sha256(raw).hexdigest(),
            },
            key,
        )
    return await run_in_threadpool(
        send,
        request,
        context,
        engine,
        "batch-save",
        {
            "operation_token": str(key),
            "batch_id": str(batch_id),
            "expected_revision": review["expected_revision"],
            "decisions": review["decisions"],
            "source_review_sha256": hashlib.sha256(raw).hexdigest(),
            "reason": "系统标准核对明细回导；保留原批次和原件，不增加库存事实",
        },
        key,
    )


@router.post("/uploads")
async def upload(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    scope_id: int,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
    filename: Annotated[str, Header(alias="X-Original-Filename")],
    prepare: bool = False,
    shipment_id: int | None = None,
) -> Any:
    require_catalog_manager(context)
    raw = await upload_bytes(request)
    parsed = await run_in_threadpool(parse_receipts, raw)
    for row in parsed["rows"]:
        row["seller_match"] = base64.b64encode(
            seller_sku_match_v1(row["raw"]["MSKU"]).utf8
        ).decode("ascii")
    if shipment_id:
        scope = cast(
            dict[str, Any],
            await run_in_threadpool(read, request, context, f"fba-scopes/{scope_id}"),
        )
        current = cast(
            dict[str, Any],
            await run_in_threadpool(
                read,
                request,
                context,
                "fba-state",
                [("warehouse_id", str(scope["warehouse_id"]))],
            ),
        )
        references = {row["raw"]["Reference ID"] for row in parsed["rows"]}
        if len(references) == 1:
            reference = next(iter(references))
            matching = [
                r
                for r in current["references"]
                if str(r["scope_id"]) == str(scope_id)
                and r["reference_id"] == reference
            ]
            if matching and str(matching[0]["shipment_id"]) != str(shipment_id):
                raise ApiError(
                    409, "fba_source_conflict", "报告货件号已关联另一批出货，请核对。"
                )
            if not matching:
                shipment = cast(
                    dict[str, Any],
                    await run_in_threadpool(
                        production_request,
                        request.app.state.settings,
                        context,
                        "GET",
                        f"shipments/{shipment_id}",
                    ),
                )
                revision = shipment["revision"]
                link_key = child_stock_key(key, "reference")
                await run_in_threadpool(
                    send,
                    request,
                    context,
                    engine,
                    "references",
                    {
                        "operation_token": str(link_key),
                        "scope_id": str(scope_id),
                        "shipment_id": str(shipment_id),
                        "expected_shipment_revision": str(revision),
                        "reference_id": reference,
                        "reason": "从本批到仓核验上传原报告，采用文件明确货件号",
                    },
                    link_key,
                )
    setup = None
    if shipment_id:
        products = await run_in_threadpool(
            approved_products,
            request,
            context,
            engine,
            int(scope["report_source_scope_id"]),
        )
        wanted = {
            item["sku_id"]
            for item in products["identities"]
            if any(
                row["raw"].get("MSKU") == item["seller_sku"]
                and row["raw"].get("ASIN") == item["asin"]
                and row["raw"].get("FNSKU") == item["fnsku"]
                and row["raw"].get("Store") == item["store"]
                for row in parsed["rows"]
            )
        }
        setup = await run_in_threadpool(
            receipt_product_setup,
            request,
            context,
            engine,
            scope_id,
            wanted,
        )
    result = await run_in_threadpool(
        send,
        request,
        context,
        engine,
        "uploads",
        {
            "operation_token": str(key),
            "scope_id": str(scope_id),
            "filename": unquote(filename),
            "file_base64": base64.b64encode(raw).decode("ascii"),
            "_parsed": parsed,
            **({"_auto_setup": setup} if setup else {}),
        },
        key,
    )
    if (
        prepare
        and isinstance(result, dict)
        and result.get("status") in {"DRAFT", "PARTIAL"}
    ):
        return await run_in_threadpool(
            prepare_batch,
            int(result["id"]),
            request,
            context,
            engine,
            child_stock_key(key, "prepare"),
        )
    return result


@router.post("/batches/{batch_id}/prepare")
def prepare_batch(
    batch_id: int,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    require_catalog_manager(context)
    data = cast(dict[str, Any], read(request, context, f"fba-batches/{batch_id}"))
    decisions = prepare_receipt_decisions(data)
    if decisions == data["decisions"]:
        return data
    return cast(
        dict[str, Any],
        send(
            request,
            context,
            engine,
            "batch-save",
            {
                "operation_token": str(key),
                "batch_id": str(batch_id),
                "expected_revision": data["revision"],
                "decisions": decisions,
                "reason": "整批接收预览，填入唯一来源候选，等待用户确认入库",
            },
            key,
        ),
    )


@router.post("/mapping-preview")
async def mapping_preview(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    report_source_scope_id: int | None = None,
) -> Any:
    """The selected master excerpt is evidence for mapping, never a stock input."""
    require_catalog_manager(context)
    raw = await upload_bytes(request)
    rows = parse_identity_source(raw)
    with engine.connect() as connection:
        scopes = (
            connection.execute(
                text(
                    "SELECT id FROM report_source_scopes WHERE site_id=:site "
                    "AND marketplace_scope_code='amazon_us'"
                ),
                {"site": context.site_id},
            )
            .scalars()
            .all()
        )
    if report_source_scope_id is None and len(scopes) == 1:
        report_source_scope_id = scopes[0]
    if report_source_scope_id not in scopes:
        raise ApiError(
            409,
            "fba_scope_conflict",
            "请先确认本次使用的店铺美国站，不能跨账号读取身份文件。",
        )
    source_id = retain_identity_source(
        request.app.state.settings.production_inventory_source_root,
        context.site_id,
        context.principal_user_id,
        cast(int, report_source_scope_id),
        raw,
    )
    catalog = production_skus(request.app.state.settings, context, engine)
    # Exact catalog suggestions remain provisional until the explicit FBA confirmation.
    candidates = []
    for row in rows:
        found = [
            s
            for s in catalog.values()
            if s.get("code")
            and seller_sku_match_v1(str(s["code"])).utf8
            == seller_sku_match_v1(row["seller_sku"]).utf8
        ]
        candidates.append(
            {
                **row,
                "sku_id": found[0]["sku_id"] if len(found) == 1 else "",
                "reason": f"商品身份核对CSV第{row['source_row']}行，待人工确认FBA范围",
            }
        )
    return {
        "identities": candidates,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "stock_effect": False,
        "source_id": source_id,
        "report_source_scope_id": str(report_source_scope_id),
    }


@router.get("/catalog-products")
def approved_products(
    request: Request,
    context: CatalogReadContext,
    engine: CatalogEngine,
    report_source_scope_id: int,
) -> Any:
    catalog = production_skus(request.app.state.settings, context, engine)
    with engine.connect() as connection:
        return catalog_products(
            connection,
            context.site_id,
            report_source_scope_id,
            catalog_for_report_scope(engine, context, catalog, report_source_scope_id),
        )


@router.get("/mapping-source/{source_id}")
def identity_original(
    source_id: str,
    report_source_scope_id: int,
    request: Request,
    context: CatalogReadContext,
) -> Response:
    require_catalog_manager(context)
    raw = read_identity_source(
        request.app.state.settings.production_inventory_source_root,
        context.site_id,
        context.principal_user_id,
        report_source_scope_id,
        source_id,
    )
    return Response(
        raw,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="fba-identity-source.csv"',
        },
    )


@router.post("/commands/{command}")
def command(
    command: Command,
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    body: Annotated[dict[str, Any], Body()],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> Any:
    require_catalog_manager(context)
    payload = {
        k: v
        for k, v in body.items()
        if not k.startswith("_") and k not in {"report_sales_key", "report_sales"}
    }
    catalog = production_skus(request.app.state.settings, context, engine)
    if command == "stocktake":
        scope_id = payload.get("scope_id")
        if not str(scope_id).isdecimal() or int(str(scope_id)) <= 0:
            raise ApiError(422, "invalid_scope", "请选择有效的FBA仓库范围。")
        count_scope = cast(
            dict[str, Any], read(request, context, f"fba-scopes/{scope_id}")
        )
        shop_catalog = catalog_for_report_scope(
            engine, context, catalog, int(count_scope["report_source_scope_id"])
        )
        lines = payload.get("lines")
        if not isinstance(lines, list) or not lines:
            raise ApiError(422, "invalid_lines", "请选择盘点规格。")
        if any(
            not isinstance(line, dict) or str(line.get("sku_id")) not in shop_catalog
            for line in lines
        ):
            raise ApiError(409, "fba_scope_conflict", "盘点商品不属于本仓店铺。")
    if command in {"unified-save", "unified-confirm"}:
        batch = (
            payload
            if command == "unified-save"
            else cast(
                dict[str, Any],
                read(
                    request, context, f"fba-batches/{int(payload.get('batch_id', 0))}"
                ),
            )
        )
        draft = batch.get("draft_payload")
        if not isinstance(draft, dict) or not isinstance(draft.get("lines"), list):
            raise ApiError(422, "fba_row_coverage", "请保存完整的接收商品表。")
        if any(
            not isinstance(line, dict) or not line.get("sku_id")
            for line in draft["lines"]
        ):
            raise ApiError(422, "fba_row_coverage", "接收商品行缺少有效商品规格。")
        wanted = {str(line["sku_id"]) for line in draft["lines"]}
        setup = receipt_product_setup(
            request, context, engine, batch["scope_id"], wanted
        )
        if setup:
            payload["_auto_setup"] = setup
    existing_scope = None
    if command == "extend-identities":
        existing_scope = cast(
            dict[str, Any],
            read(request, context, f"fba-scopes/{int(payload.get('scope_id', 0))}"),
        )
        for field in (
            "warehouse_id",
            "owner_id",
            "seller_account",
            "marketplace",
            "report_source_scope_id",
            "store_evidence",
            "cutoff_on",
            "simulated",
        ):
            payload[field] = existing_scope[field]
    if command in {"scopes", "extend-identities"}:
        scope_id = payload.get("report_source_scope_id")
        with engine.connect() as connection:
            scope = (
                connection.execute(
                    text(
                        "SELECT id,seller_account_scope_key,marketplace_scope_code "
                        "FROM report_source_scopes WHERE site_id=:site AND id=:id"
                    ),
                    {"site": context.site_id, "id": scope_id},
                )
                .mappings()
                .one_or_none()
            )
            if (
                scope is None
                or (
                    str(payload.get("seller_account", "")) != f"scope:{scope_id}"
                    and bytes(scope["seller_account_scope_key"])
                    != hashlib.sha256(
                        str(payload.get("seller_account", "")).strip().encode()
                    ).digest()
                )
                or scope["marketplace_scope_code"] != "amazon_us"
            ):
                raise ApiError(
                    409,
                    "fba_scope_conflict",
                    "卖家账号必须与该站点已确认报表范围一致；空Store不能推测账号。",
                )
            payload["_fba_scope"] = {
                "id": str(scope["id"]),
                "seller_account": payload["seller_account"],
                "marketplace": "amazon_us",
            }
            identities = payload.get("identities")
            if not isinstance(identities, list) or not identities:
                raise ApiError(
                    422, "fba_identity_required", "请先导入并确认规格身份核对证据。"
                )
            verified = {}
            source = payload.get("identity_source")
            source_meta = cast(dict[str, Any], source)
            source_rows = {}
            automatic = payload.get("identity_mode") == "catalog"
            if automatic:
                products = catalog_products(
                    connection,
                    context.site_id,
                    int(cast(str | int, scope_id)),
                    catalog_for_report_scope(
                        engine, context, catalog, int(cast(str | int, scope_id))
                    ),
                )
                wanted = {
                    str(line.get("sku_id"))
                    for line in identities
                    if isinstance(line, dict)
                }
                identities = [
                    line for line in products["identities"] if line["sku_id"] in wanted
                ]
                if not wanted or {line["sku_id"] for line in identities} != wanted:
                    raise ApiError(
                        409,
                        "fba_catalog_identity_missing",
                        "商品资料已变化或尚未补齐，请刷新核对后继续。",
                    )
                if payload.get("catalog_version") != products["catalog_version"]:
                    raise ApiError(
                        409,
                        "fba_catalog_conflict",
                        "商品目录已更新，请刷新后继续，当前填写已保留。",
                    )
                payload["store_evidence"] = products["store"]
                payload["identities_confirmed"] = True
            if isinstance(source, dict):
                raw = read_identity_source(
                    request.app.state.settings.production_inventory_source_root,
                    context.site_id,
                    context.principal_user_id,
                    int(cast(str | int, scope_id)),
                    str(source.get("source_id", "")),
                )
                source_rows = {
                    str(row["source_row"]): row for row in parse_identity_source(raw)
                }
                if (
                    existing_scope is None and len(source_rows) != len(identities)
                ) or payload.get("identities_confirmed") is not True:
                    raise ApiError(
                        409,
                        "fba_identity_source_changed",
                        "请完整核对原表商品后勾选身份确认，不能遗漏原表行。",
                    )
            if source_rows:
                payload["store_confirmation_reason"] = payload.get("store_evidence", "")
                payload["store_evidence"] = next(iter(source_rows.values()))["store"]
            confirmed_lines = []
            seen_rows = set()
            seen_skus = set()
            for line in identities:
                if not isinstance(line, dict):
                    raise ApiError(
                        422,
                        "fba_identity_required",
                        "商品身份格式无效，请重新读取CSV。",
                    )
                sku = catalog.get(str(line.get("sku_id")))
                if (
                    sku is None
                    or not isinstance(line.get("seller_sku"), str)
                    or not line["seller_sku"]
                ):
                    raise ApiError(
                        409,
                        "fba_identity_unmatched",
                        "所选规格尚未匹配当前已批准目录。",
                    )
                match = seller_sku_match_v1(line["seller_sku"]).utf8
                mappings = (
                    connection.execute(
                        text(
                            "SELECT sku_id,seller_sku_match_bytes FROM "
                            "product_catalog_mappings WHERE site_id=:site "
                            "AND report_source_scope_id=:scope "
                            "AND catalog_version_id=:version "
                            "AND seller_sku_match_bytes=:match"
                        ),
                        {
                            "site": context.site_id,
                            "scope": scope_id,
                            "version": int(str(sku["catalog_version"]).split(":")[0]),
                            "match": match,
                        },
                    )
                    .mappings()
                    .all()
                )
                row_number, sku_id = (
                    str(line.get("source_row", "")),
                    str(line["sku_id"]),
                )
                if source_rows:
                    original = source_rows.get(row_number)
                    if (
                        not original
                        or any(
                            line.get(field) != original[field]
                            for field in ("seller_sku", "asin", "fnsku", "store")
                        )
                        or row_number in seen_rows
                    ):
                        raise ApiError(
                            409,
                            "fba_identity_source_changed",
                            f"CSV第{row_number}行与原表不一致，请重新读取核对。",
                        )
                    seen_rows.add(row_number)
                elif not mappings and not automatic:
                    raise ApiError(
                        409,
                        "fba_identity_source_required",
                        "请重新点击“读取身份核对文件”，保留原表后即可确认，无需先导入经营报告。",
                    )
                if sku_id in seen_skus:
                    raise ApiError(
                        409,
                        "fba_identity_conflict",
                        f"CSV第{row_number}行：同一规格不能重复确认。",
                    )
                seen_skus.add(sku_id)
                trusted = verify_identity(
                    line, catalog, [str(m["sku_id"]) for m in mappings]
                )
                if automatic:
                    trusted["basis"] = "approved_catalog_source"
                if trusted["basis"] == "confirmed_fba_identity_source" and (
                    payload.get("simulated") is not True
                    or payload.get("explicit_zero_opening") is not True
                ):
                    raise ApiError(
                        409,
                        "fba_zero_opening_required",
                        "当前仅支持明确的模拟零期初，不可用身份资料推断真实库存为零。",
                    )
                verified[sku_id] = trusted
                confirmed_lines.append(
                    line
                    | {
                        "reason": (
                            f"FBA本地身份人工确认；账号范围{scope_id}；{trusted['basis']}；"
                            f"原表sha256={source_meta.get('source_id')}；"
                            f"CSV第{row_number}行；来源店铺={line.get('store')}"
                        )
                    }
                    if source_rows
                    else line
                )
            payload["identities"] = confirmed_lines
            payload["_fba_identities"] = verified
            if (
                existing_scope is not None
                and payload.get("store_evidence") != existing_scope["store_evidence"]
            ):
                raise ApiError(
                    409,
                    "fba_scope_conflict",
                    "身份文件的店铺与当前FBA范围不一致，请核对来源店铺。",
                )
            if automatic and existing_scope is not None:
                setup = receipt_product_setup(
                    request, context, engine, existing_scope["id"], seen_skus
                )
                if setup:
                    payload["_auto_setup"] = setup
    if command == "tracking" and payload.get("reconfirm_catalog") is True:
        fba_scope = cast(
            dict[str, Any],
            read(request, context, f"fba-scopes/{int(payload.get('scope_id', 0))}"),
        )
        current = cast(
            dict[str, Any],
            read(
                request,
                context,
                "fba-state",
                [("warehouse_id", str(fba_scope["warehouse_id"]))],
            ),
        )
        identities = [
            line
            for line in current["identities"]
            if str(line["scope_id"]) == str(fba_scope["id"])
        ]
        verified = {}
        with engine.connect() as connection:
            for line in identities:
                sku_id = str(line["sku_id"])
                sku = catalog.get(sku_id)
                if sku is None:
                    raise ApiError(
                        409,
                        "fba_identity_unmatched",
                        "当前目录已停用或缺失原FBA规格，请先核对商品身份。",
                    )
                mappings = (
                    connection.execute(
                        text(
                            "SELECT sku_id FROM product_catalog_mappings "
                            "WHERE site_id=:site "
                            "AND report_source_scope_id=:scope "
                            "AND catalog_version_id=:version "
                            "AND seller_sku_match_bytes=:match"
                        ),
                        {
                            "site": context.site_id,
                            "scope": fba_scope["report_source_scope_id"],
                            "version": int(str(sku["catalog_version"]).split(":")[0]),
                            "match": seller_sku_match_v1(line["seller_sku"]).utf8,
                        },
                    )
                    .mappings()
                    .all()
                )
                verified[sku_id] = verify_identity(
                    line, catalog, [str(m["sku_id"]) for m in mappings]
                )
        payload["_fba_identities"] = verified
    if command == "actions":
        refs = payload.get("report_version_ids", [])
        if not isinstance(refs, list):
            raise ApiError(
                422, "fba_report_reference_invalid", "关联报表版本格式无效。"
            )
        fba_scope = cast(
            dict[str, Any],
            read(request, context, f"fba-scopes/{int(payload.get('scope_id', 0))}"),
        )
        with engine.connect() as connection:
            for version in refs:
                exists = connection.execute(
                    text(
                        "SELECT a.report_source_scope_id FROM dataset_versions v "
                        "JOIN report_dataset_scope_assignments a "
                        "ON a.dataset_id=v.dataset_id JOIN dataset_publications p "
                        "ON p.dataset_id=a.dataset_id AND p.version_id=v.id "
                        "WHERE v.id=:id AND a.site_id=:site"
                    ),
                    {"id": version, "site": context.site_id},
                ).first()
                if exists is None or str(exists[0]) != str(
                    fba_scope["report_source_scope_id"]
                ):
                    raise ApiError(
                        409,
                        "fba_report_reference_invalid",
                        "仅能关联同站点当前已发布报表；报表不会直接扣增库存。",
                    )
        payload["_report_source_scope_id"] = str(fba_scope["report_source_scope_id"])
    return send(request, context, engine, command, payload, key)
