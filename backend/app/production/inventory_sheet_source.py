# ruff: noqa: RUF001
"""Authorized local inventory evidence with unknown opening stock."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.api.errors import ApiError
from app.catalog.normalization import catalog_identity_key_v1
from app.config import Settings
from app.site_context import CurrentSiteContext


def load_sheet_source(
    settings: Settings, context: CurrentSiteContext, engine: Engine
) -> dict[str, Any] | None:
    if not settings.production_inventory_source_root:
        return None
    root = Path(settings.production_inventory_source_root)
    path = root / "inventory-sheet-source.json"
    if not path.is_file():
        return None
    raw = path.read_bytes()
    source = cast(dict[str, Any], json.loads(raw))
    if (
        source.get("schema") != "inventory-sheet-source-v1"
        or source.get("database") != engine.url.database
        or str(source.get("site_id")) != str(context.site_id)
        or not str(engine.url.database).startswith("clsen_data_test_")
    ):
        raise ApiError(
            409, "sheet_source_scope_invalid", "资料核对范围与当前本地站点不一致。"
        )
    with engine.connect() as connection:
        scope = connection.execute(
            sa.text(
                "SELECT id FROM report_source_scopes WHERE site_id=:site "
                "AND id=:scope AND marketplace_scope_code='amazon_us'"
            ),
            {"site": context.site_id, "scope": source["report_source_scope_id"]},
        ).scalar_one_or_none()
    if scope is None:
        raise ApiError(
            409, "sheet_source_scope_invalid", "资料对应的美国站报告范围已变化。"
        )
    for item in source["inputs"]:
        filename = item["local_name"]
        if Path(filename).name != filename:
            raise ApiError(422, "sheet_source_invalid", "资料文件名无效。")
        if (
            hashlib.sha256((root / "inputs" / filename).read_bytes()).hexdigest()
            != item["sha256"]
        ):
            raise ApiError(
                409, "sheet_source_changed", "核对资料已变化，请重新准备来源并刷新。"
            )
    source["digest"] = hashlib.sha256(raw).hexdigest()
    return source


def source_facts(source: dict[str, Any], query: dict[str, str]) -> dict[str, Any]:
    scope = source["resolved_scope"]
    expected = {
        "domestic_warehouse_id": scope["domestic"]["warehouse_id"],
        "domestic_owner_id": scope["domestic"]["owner_id"],
        "fba_scope_id": scope["fba"]["id"],
    }
    if any(query.get(key) != value for key, value in expected.items()):
        raise ApiError(
            409, "sheet_source_scope_invalid", "请选择当前资料已核准的仓库与FBA范围。"
        )
    return {
        "resolved_scope": scope,
        "report_scope_count": 1,
        "settings": {
            "revision": "0",
            "style_ids": [],
            "sku_alert_settings": {},
            "can_manage": False,
        },
        "orders": [],
        "order_shipments": [],
        "production_revisions": [],
        "events": [],
        "stock_sources": [],
        "shipment_sources": [],
        "identity_changes": [],
        "occupancy_history": [],
        "transit": [],
        "domestic_stock": {"items": []},
        "fba_state": {"stock": {"items": []}, "identities": [], "actions": []},
    }


def reconcile_source_catalog(
    source: dict[str, Any], catalog: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Keep proven bindings across catalog revisions and isolate identity changes."""
    versions = {row.get("catalog_version") for row in catalog.values()}
    if versions == {source["catalog_version"]}:
        return source
    snapshot = source.get("catalog_identity_snapshot", {})
    bound = {
        sku
        for sku in source["stock_rows"] | source["packing_rows"]
        if not sku.startswith("source:")
    }
    members = snapshot.get("members", {})
    if (
        len(versions) != 1
        or snapshot.get("catalog_version") != source["catalog_version"]
        or not bound.issubset(members)
    ):
        raise ApiError(
            409,
            "sheet_source_catalog_changed",
            "资料缺少原商品身份依据，请重新核对来源。",
        )
    result = deepcopy(source)
    version = next(iter(versions))
    result["catalog_version"] = version
    result["resolved_scope"]["fba"]["catalog_version"] = version
    fields = ("style_id", "style_code", "standard_color", "standard_size")
    for sku in sorted(bound):
        previous, current = members[sku], catalog.get(sku)
        if current and all(
            catalog_identity_key_v1(str(previous[field])).utf8
            == catalog_identity_key_v1(str(current[field])).utf8
            for field in fields
        ):
            continue
        pending = f"source:catalog:{sku}"
        reason = "目录中的原商品身份已变化或移除，原表关联需重新核对。"
        result["pending_identities"][pending] = {
            **previous,
            "sku_id": pending,
            "style_id": f"source:catalog:style:{previous['style_id']}",
            "style_code": previous["style_code"] + "（目录身份待核）",
            "label": (previous.get("code") or previous["label"]) + "（目录身份待核）",
            "status": "pending",
        }
        source_refs: set[str] = set()
        stock = result["stock_rows"].pop(sku, None)
        if stock is not None:
            stock.update(identity_pending=True, reason=reason)
            result["stock_rows"][pending] = stock
            units = int(stock["units"] or "0")
            review = result["review"]
            review["stock_matched_units"] = str(
                int(review["stock_matched_units"]) - units
            )
            review["stock_pending_units"] = str(
                int(review["stock_pending_units"]) + units
            )
            source_refs.update(
                row["filename"] + "!" + row["cell"] for row in stock["records"]
            )
        packing = result["packing_rows"].pop(sku, None)
        if packing is not None:
            result["packing_rows"][pending] = packing
            source_refs.update(f"{row['filename']}!A{row['row']}" for row in packing)
        batches = result.get("fba_batch_rows", {}).pop(sku, None)
        if batches is not None:
            result["fba_batch_rows"][pending] = batches
        result["review"].setdefault("issues", []).append(f"原SKU {sku}：{reason}")
        evidence = result.get("directory_evidence")
        if evidence:
            for row in evidence["domestic"]["rows"] + [
                row for batch in evidence["fba"]["packings"] for row in batch["rows"]
            ]:
                if row["source"] in source_refs:
                    row["status"] = reason
            evidence["domestic"]["matched_units"] = result["review"][
                "stock_matched_units"
            ]
            evidence["domestic"]["pending_units"] = result["review"][
                "stock_pending_units"
            ]
    for pending in result["pending_identities"].values():
        pending["catalog_version"] = version
    return result


def directory_evidence(
    source: dict[str, Any] | None, directory: dict[str, Any]
) -> dict[str, Any] | None:
    if source is None or not source.get("directory_evidence"):
        return None
    evidence = source["directory_evidence"]
    binding = evidence["bindings"]
    warehouse = str(directory["id"])
    if warehouse == binding["domestic_warehouse_id"]:
        if (
            directory.get("type") != "FACTORY"
            or directory.get("name") != binding["domestic_name"]
        ):
            raise ApiError(
                409,
                "sheet_directory_changed",
                "盘点资料对应的仓库身份已变化，请重新核对。",
            )
        return {
            "kind": "domestic",
            "stock_date": source["stocktaken_on"],
            **evidence["domestic"],
        }
    if warehouse == binding["fba_warehouse_id"]:
        if (
            directory.get("type") != "FBA"
            or directory.get("seller_account")
            != f"scope:{source['report_source_scope_id']}"
            or directory.get("marketplace") != "US"
        ):
            raise ApiError(
                409,
                "sheet_directory_changed",
                "FBA资料对应的卖家或站点已变化，请重新核对。",
            )
        return {"kind": "fba", **evidence["fba"]}
    return None


def apply_source_row(
    source: dict[str, Any],
    sku: str,
    as_of: date,
    values: dict[str, Any],
    records: dict[str, Any],
) -> None:
    from app.production.inventory_overview import PRODUCTION_KEYS, quantity

    stock_date = source["stocktaken_on"]
    entry = source["stock_rows"].get(sku)
    if entry:
        known = entry["units"]
        if entry.get("identity_pending"):
            value = quantity(
                state="identity_pending",
                known_units=known or "0",
                unknown_count=1,
                reason="原表规格尚未关联当前目录。" + entry["reason"],
            )
        elif as_of.isoformat() != stock_date:
            value = quantity(
                state="history_unavailable",
                known_units=known or "0",
                unknown_count=1,
                reason=f"仅有{stock_date}盘点，所选日期的库存变动资料待补。",
            )
        elif known is None:
            value = quantity(
                state="not_ready",
                unknown_count=1,
                known_units="0",
                reason=entry["reason"],
            )
        else:
            quality = source.get("review", {}).get("stock_quality_basis", "质量待核")
            value = quantity(known, reason=f"{stock_date}盘点原表；{quality}。")
        records["source_stock"] = entry["records"]
    else:
        value = quantity(state="not_ready", reason="该规格未在本次盘点表中提供数量。")
        records["source_stock"] = []
    values["domestic"] = value
    for key in PRODUCTION_KEYS:
        values[key] = quantity(
            state="not_ready", reason="当前服务器备份及用户资料未提供生产订单进度。"
        )
    if not source.get("fba_ledger"):
        for key in ["available", "fba", "unsellable"]:
            values[key] = quantity(
                state="not_ready",
                reason="FBA期初及当前结存未知，当前资料只支持核对装箱与接收。",
            )
    values["transit"] = quantity(
        state="not_ready", reason="实际发货日期、运输状态及后两批接收证据待补。"
    )
    packed = sum(
        int(row["units"])
        for row in source["packing_rows"].get(sku, [])
        if row["batch_date"] <= as_of.isoformat()
    )
    values["dispatched"] = quantity(
        state="not_ready",
        known_units=str(packed),
        unknown_count=1,
        reason=f"范围内装箱{packed}件；实际发货状态及日期待核。",
    )
    batches = [
        row
        for row in source.get("fba_batch_rows", {}).get(sku, [])
        if row["batch_date"] <= as_of.isoformat()
    ]
    records["source_fba"] = []
    for batch in batches:
        receipts = [
            row for row in batch["receipts"] if row["date"] <= as_of.isoformat()
        ]
        received = sum(int(row["units"]) for row in receipts)
        records["source_fba"].append(
            {
                **batch,
                "received_units": str(received) if receipts else None,
                "remaining_units": str(max(int(batch["packed_units"]) - received, 0)),
                "receipts": receipts,
            }
        )
    received = sum(int(row["received_units"] or "0") for row in records["source_fba"])
    if received and not source.get("fba_ledger"):
        values["available"]["evidence"] = {"label": "接收累计", "units": str(received)}
        values["available"]["reason"] += (
            f"本批资料接收累计{received}件，当前可售结存仍需库存依据。"
        )
    if source.get("shipping_confirmation", {}).get("confirmed") and batches:
        remaining = sum(int(row["remaining_units"]) for row in records["source_fba"])
        values["transit"] = quantity(
            state="not_ready",
            reason=f"用户确认已发出，按装箱批次资料待核接收{remaining}件。实际发出日期、后续验收及差异结清待补。",
            evidence={"label": "待核接收", "units": str(remaining)},
        )
        values["dispatched"]["reason"] = (
            f"用户确认这些批次已发出，装箱{packed}件。按文件批次标签归集，实际发出日期待补。"
        )
        values["dispatched"]["evidence"] = {"label": "已发资料", "units": str(packed)}
    if sku.startswith("source:"):
        for key in values:
            if key != "domestic":
                values[key] = quantity(
                    state="identity_pending", reason="该原表规格的目录关联待核。"
                )
