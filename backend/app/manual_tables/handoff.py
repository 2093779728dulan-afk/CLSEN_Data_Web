# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
"""Thin handoff to existing authorities; never post stock from a cleaned file."""

import json
from typing import Any, cast

from app.api.errors import ApiError
from app.manual_tables.models import batches
from app.manual_tables.schemas import SIZES, Command, Kind
from app.manual_tables.service import ManualTables, digest, now
from app.production.client import production_request
from app.production.identity import production_skus


def inventory_snapshot(batch: dict[str, Any]) -> dict[str, Any]:
    from app.catalog.normalization import catalog_identity_key_v1
    from app.production.inventory_snapshot import _quantity, warehouse_1_view

    context = batch["options"]["context"]
    groups: dict[Any, list[dict[str, Any]]] = {}
    for row in batch["result"]["rows"]:
        if row["excluded"]:
            continue
        if not row["style"] or not row["color"] or row["size"] not in SIZES:
            raise ApiError(
                422,
                "manual_inventory_identity",
                "请先核对款号、颜色及尺码；未知数量和未建档商品可以保留为资料。",
            )
        key = tuple(row[k] for k in ("style", "color", "warehouse"))
        if not batch["options"].get("aggregate_duplicates"):
            key = (row["source_ref"]["row"], *key)
        groups.setdefault(key, []).append(row)
    parsed_rows = []
    for rows in groups.values():
        first = rows[0]
        quantities = {}
        for size in SIZES:
            values = [r for r in rows if r["size"] == size]
            amount = (
                str(sum(int(r["units"]) for r in values))
                if values and all(r["units"] is not None for r in values)
                else None
            )
            if amount is not None and len(amount) > 18:
                raise ApiError(
                    422, "manual_inventory_limit", "规格汇总超过18位数量上限，请核对。"
                )
            quantities[size] = _quantity(
                amount, values[0]["source_ref"]["cell"] if values else ""
            )
        literal = sum(
            int(str(q["units"])) for q in quantities.values() if q["units"] is not None
        )
        warehouse = first["warehouse"]
        in_scope = bool(
            warehouse
            and context.get("warehouse")
            and catalog_identity_key_v1(warehouse).text
            == catalog_identity_key_v1(context["warehouse"]).text
        )
        parsed_rows.append(
            {
                "source_key": first["source_line_key"],
                "sheet": first["source_ref"]["sheet"],
                "source_row": first["source_ref"]["row"],
                "style_code": first["style"],
                "color": first["color"],
                "old_style_code": "",
                "source_sku": first["code"],
                "color_note": "",
                "location": warehouse,
                "warehouse_display": warehouse,
                "location_group": "WAREHOUSE_1" if in_scope else "UNCONFIRMED",
                "quantities": quantities,
                "literal_units": str(literal),
                "formula_units": "0",
                "unknown_cells": sum(q["units"] is None for q in quantities.values()),
                "source_total": _quantity(
                    None if any(r["units"] is None for r in rows) else str(literal), ""
                ),
                "notes": [],
                "issues": [],
                "sku_id": None,
                "manual_sources": [r["source_ref"] for r in rows],
            }
        )
    result = warehouse_1_view(
        {
            "rows": parsed_rows,
            "defects": [],
            "defect_period_note": "",
            "summary": {"defect_literal_units": "0"},
        },
        "SIZE_LITERALS",
    )
    return result | {
        "filename": batch["filename"],
        "source_digest": batch["source_digest"],
        "source_manifest_digest": digest(
            [batch["id"], batch["revision"], batch["result"]]
        ),
        "source_format": "manual_table_v1",
        "source_kind": "MANUAL",
        "organized_on": None,
        "stocktaken_on": context.get("date") or None,
        "warehouse_note": context.get("warehouse") or "人工资料仓库待核",
        "read_only": True,
        "posting_enabled": False,
        "historical_shipments_deducted": False,
        "cutoff_note": "人工表格整理来源；结存口径："
        + (context.get("basis") or "待确认"),
        "manual_batch_id": batch["id"],
        "manual_batch_revision": batch["revision"],
    }


def business_payload(
    svc: ManualTables,
    batch: dict[str, Any],
    fresh: dict[str, Any],
    command: Command,
    fulfillment_modes: dict[str, str],
) -> tuple[str, dict[str, Any]]:
    """Build the same draft for preview and handoff; never call a writer."""
    batch_id = batch["id"]
    context = command.options.context
    token = svc._token(command.operation_token)
    from app.api.production import _operation_actor

    identities = production_skus(svc.settings, svc.context, svc.engine)
    effective = [
        r for r in fresh["rows"] if not r["excluded"] and r["units"] not in (None, "0")
    ]
    if any(
        identities.get(r["match"]["sku_id"], {}).get("catalog_version")
        != r["match"]["catalog_version"]
        for r in effective
    ):
        raise ApiError(
            409,
            "manual_handoff_catalog_changed",
            "移交期间商品目录已变化，请重新预览并保存后再移交。",
        )
    payload: dict[str, Any] = {
        "operation_token": token,
        "business_date": context["date"],
        "save_mode": "draft",
        "business_number": context.get("number", ""),
        "notes": (
            f"人工资料批次{batch_id}，修订{batch['revision']}；"
            f"原件{batch['source_digest']}"
        ),
        "manual_source_note": context.get("source_note", ""),
        "_catalog": identities,
        "_actor_name": _operation_actor(svc.context, svc.engine),
    }
    grouped: dict[str, dict[str, Any]] = {}
    for row in effective:
        sku_id = row["match"]["sku_id"]
        item = grouped.setdefault(sku_id, {**row, "units": "0"})
        item["units"] = str(int(item["units"]) + int(row["units"]))
    effective = list(grouped.values())
    if batch["kind"] == "orders":
        payload["lines"] = [
            {"sku_id": r["match"]["sku_id"], "expected_units": r["units"]}
            for r in effective
        ]
        path = "orders"
    else:
        order_lines = context.get("order_lines", "")
        try:
            allocations = __import__("json").loads(order_lines)
        except (ValueError, TypeError) as error:
            raise ApiError(
                422,
                "manual_order_allocation",
                "请在出货归属中选择对应订单明细与数量。",
            ) from error
        if not isinstance(allocations, dict):
            raise ApiError(
                422,
                "manual_order_allocation",
                "订单归属格式无效，请重新选择订单明细。",
            )
        payload.update(
            dispatch_purpose="OUTWARD_ORDER",
            sources=[
                {
                    "sku_id": r["match"]["sku_id"],
                    "actual_units": r["units"],
                    "fulfillment_mode": fulfillment_modes[str(r["match"]["sku_id"])],
                    "allocations": allocations.get(r["match"]["sku_id"], []),
                }
                for r in effective
            ],
        )
        if any(mode == "WAREHOUSE_STOCK" for mode in fulfillment_modes.values()):
            payload.update(
                warehouse_id=context["warehouse_id"],
                owner_id=context["owner_id"],
            )
        path = "shipments"
    return path, payload


def handoff_batch(
    svc: ManualTables, batch_id: str, command: Command, *, preview_only: bool = False
) -> dict[str, Any]:
    svc.require()
    if not svc.settings.manual_tables_handoff_enabled:
        raise ApiError(
            403,
            "manual_handoff_disabled",
            "当前环境仅开放资料整理、保存和导出，尚未开放移交业务；不会创建订单、出货或库存核对单。",
        )
    batch = svc.get(batch_id)
    if (
        batch["kind"] == "inventory"
        and not svc.settings.manual_tables_inventory_handoff_enabled
    ):
        raise ApiError(
            403,
            "manual_inventory_handoff_disabled",
            "当前库存资料仅供整理、核对和导出，尚未开放移交库存业务；不会创建库存核对单。",
        )
    token = svc._token(command.operation_token)
    command_value = command.model_dump()
    if not getattr(command, "handoff_preview_hash", ""):
        command_value.pop("handoff_preview_hash", None)
    request_hash = digest(["handoff", batch_id, command_value])
    with svc.engine.begin() as con:
        row = svc.load(con, batch_id, lock=True)
        replay = None if preview_only else svc.replay(con, token, request_hash)
        if replay:
            return replay
        if row["revision"] != command.expected_revision:
            raise ApiError(
                409, "manual_revision_conflict", "资料修订已变化，请刷新后移交。"
            )
        if preview_only and row["target_json"]:
            raise ApiError(
                409,
                "manual_already_handed_off",
                "该批次已有移交操作，请查询原操作或打开原目标，不要再次预览新目标。",
            )
        if row["target_json"]:
            old = row["target_json"]
            if (
                old["token"] != token
                or old.get("request_hash", request_hash) != request_hash
                or old.get("actor_id", str(svc.context.principal_user_id))
                != str(svc.context.principal_user_id)
            ):
                raise ApiError(
                    409,
                    "manual_already_handed_off",
                    "该批次已有移交操作，请查询原操作或打开原目标。",
                )
    if (
        row["target_json"]
        and batch["kind"] in {"orders", "packing"}
        and command.options.context.get("already_in_snapshot") != "true"
    ):
        try:
            receipt = cast(
                dict[str, Any],
                production_request(
                    svc.settings, svc.context, "GET", f"commands/{token}"
                ),
            )
        except ApiError as error:
            if error.status_code != 404:
                raise
        else:
            path = "orders" if batch["kind"] == "orders" else "shipments"
            target = {
                "kind": "order" if path == "orders" else "shipment",
                "id": receipt["id"],
                "url": f"/production/{path}/{receipt['id']}",
            }
            return complete_handoff(svc, batch_id, command, request_hash, target)
    fresh = svc.analyze(svc.source(row), cast(Kind, batch["kind"]), command.options)
    if command.options.model_dump() != batch["options"] or fresh != batch["result"]:
        raise ApiError(
            409,
            "manual_handoff_stale",
            "资料、字段或商品目录已变化，请重新预览并保存。",
        )
    expected_target = {
        "inventory": "inventory_review",
        "orders": "order",
        "packing": "shipment",
    }[batch["kind"]]
    if command.target != expected_target:
        raise ApiError(422, "manual_wrong_target", "移交目标与资料类型不一致。")
    if not fresh["rows"] or (
        batch["kind"] != "inventory" and fresh["state"] != "READY"
    ):
        raise ApiError(
            422, "manual_not_ready", "仍有字段、数量或商品待核，请先处理问题清单。"
        )
    if batch["kind"] == "inventory" and any(
        p["blocking"] and p["code"] not in {"quantity_unknown", "sku_unresolved"}
        for p in fresh["issues"]
    ):
        raise ApiError(
            422,
            "manual_inventory_not_ready",
            "请先处理结构、公式、重复或数量冲突；未知数量及未建档商品可保留在库存资料核对中。",
        )
    context = command.options.context
    active_rows = [r for r in fresh["rows"] if not r["excluded"] and r["units"] != "0"]
    fulfillment_modes: dict[str, str] = {}
    if batch["kind"] == "packing" and context.get("already_in_snapshot") != "true":
        try:
            fulfillment_modes = json.loads(context.get("fulfillment_modes", ""))
        except (TypeError, ValueError) as error:
            raise ApiError(
                422,
                "manual_fulfillment_modes",
                "请为每个出货SKU选择仓库库存出货或生产完成后直接出货。",
            ) from error
        sku_ids = {
            str(r["match"]["sku_id"])
            for r in active_rows
            if r.get("match") and r["match"].get("sku_id")
        }
        if (
            not isinstance(fulfillment_modes, dict)
            or set(fulfillment_modes) != sku_ids
            or any(
                mode not in {"WAREHOUSE_STOCK", "PRODUCTION_DIRECT"}
                for mode in fulfillment_modes.values()
            )
        ):
            raise ApiError(
                422,
                "manual_fulfillment_modes",
                "请为每个出货SKU选择仓库库存出货或生产完成后直接出货。",
            )
    if context.get("date") and any(
        r["date"] and r["date"] != context["date"] for r in active_rows
    ):
        raise ApiError(
            422,
            "manual_mixed_dates",
            "原行日期与本次业务日期不同，请选择同一日期区域；若原日期列错误，先明确忽略该列并补充正确日期。",
        )
    if (
        batch["kind"] == "packing"
        and context.get("warehouse")
        and any(
            r["warehouse"] and r["warehouse"] != context["warehouse"]
            for r in active_rows
        )
    ):
        raise ApiError(
            422,
            "manual_mixed_warehouses",
            "原行仓库与本次发货仓库不同，请先核对或分开选择业务区域。",
        )
    historical = (
        batch["kind"] == "packing" and context.get("already_in_snapshot") == "true"
    )
    if historical and context.get("fulfillment_modes"):
        try:
            historical_modes = json.loads(context["fulfillment_modes"])
        except (TypeError, ValueError) as error:
            raise ApiError(
                422, "manual_fulfillment_modes", "出货来源选择无效，请重新选择。"
            ) from error
        if (
            isinstance(historical_modes, dict)
            and "PRODUCTION_DIRECT" in historical_modes.values()
        ):
            raise ApiError(
                422,
                "manual_direct_shipment_requires_draft",
                "生产直发仍需形成实际出货并计入订单履约，请取消“已包含在库存结存中”后移交；系统不会扣仓库库存。",
            )
    covered = None
    if historical:
        from app.manual_tables.comparison import selected, totals

        try:
            reference = {
                "inventory": {
                    "id": context["inventory_batch_id"],
                    "revision": int(context["inventory_batch_revision"]),
                }
            }
        except (KeyError, ValueError) as error:
            raise ApiError(
                422,
                "manual_coverage_reference",
                "请明确选择已包含本次出货的库存资料及修订。",
            ) from error
        covered = selected(svc, reference)["inventory"]
        inventory_keys = set(totals(covered))
        dispatched_keys = {k for k, v in totals(batch).items() if v["units"] > 0}
        if not dispatched_keys <= inventory_keys:
            raise ApiError(
                422,
                "manual_coverage_spec",
                "所选库存资料未列出本次出货的全部规格，不能据此确认覆盖关系。请先核对缺失规格。",
            )
        stock_context = covered["options"]["context"]
        if (
            stock_context.get("basis") != "出货后结存"
            or not stock_context.get("warehouse")
            or stock_context.get("warehouse") != context.get("warehouse")
            or not context.get("date")
            or not stock_context.get("date")
            or context["date"] > stock_context["date"]
            or not command.reason.strip()
            or context.get("dispatched") != "true"
        ):
            raise ApiError(
                422,
                "manual_coverage_scope",
                "请核对同一仓库、库存为出货后结存、出货日期不晚于库存日期，并填写覆盖依据。",
            )
    if batch["kind"] == "inventory":
        if not svc.settings.production_inventory_review_writes_enabled:
            raise ApiError(
                403,
                "manual_inventory_review_disabled",
                "此环境未开放库存资料核对写入；可以继续整理和导出。",
            )
    elif not historical:
        if not context.get("date"):
            raise ApiError(
                422,
                "manual_date_required",
                "请补充真实业务日期；文件日期或DELIVERY不能代替。",
            )
        if not context.get("source_note", "").strip():
            raise ApiError(
                422,
                "manual_source_note_required",
                "请填写这次下单或出货的来源说明，用于区别真实独立事件。",
            )
        warehouse_fulfillment = any(
            mode == "WAREHOUSE_STOCK" for mode in fulfillment_modes.values()
        )
        if batch["kind"] == "packing" and (
            context.get("dispatched") != "true"
            or (
                warehouse_fulfillment
                and (not context.get("warehouse_id") or not context.get("owner_id"))
            )
        ):
            raise ApiError(
                422,
                "manual_dispatch_context",
                "移交实际出货草稿需要确认已发、仓库和库存范围。",
            )
    path, payload = (
        ("", None)
        if batch["kind"] == "inventory" or historical
        else business_payload(svc, batch, fresh, command, fulfillment_modes)
    )
    expected_preview = getattr(command, "handoff_preview_hash", "")
    if preview_only or expected_preview:
        candidates = []
        if payload is not None:
            check = cast(
                dict[str, Any],
                production_request(
                    svc.settings,
                    svc.context,
                    "POST",
                    f"sources/{path}/check",
                    body=payload,
                ),
            )
            matches = list(check.get("candidates", []))
            if check.get("duplicate_document"):
                matches.append(check["duplicate_document"])
            for item in matches:
                candidates.append(
                    {
                        field: item.get(field)
                        for field in (
                            "id",
                            "system_number",
                            "business_number",
                            "business_date",
                            "status",
                        )
                    }
                    | {"url": f"/production/{path}/{item['id']}"}
                )
        summary = {
            "batch_id": batch_id,
            "source_revision": batch["revision"],
            "target_kind": "historical_reference" if historical else expected_target,
            "business_date": context.get("date") or None,
            "warehouse": context.get("warehouse") or None,
            "total_units": fresh["total_units"],
            "sku_count": len(
                {
                    r["match"]["sku_id"]
                    for r in active_rows
                    if r.get("match", {}).get("sku_id")
                }
            ),
            "source_row_count": sum(not r["excluded"] for r in fresh["rows"]),
            "excluded_row_count": sum(r["excluded"] for r in fresh["rows"]),
            "inventory_effect_units": "0",
            "catalog_version": fresh["catalog_version"],
            "candidates": candidates,
        }
        preview_hash = digest(
            [
                "manual-handoff-preview-v1",
                command.target,
                command.reason,
                svc.context.site_id,
                svc.context.principal_user_id,
                batch_id,
                batch["revision"],
                fresh,
                summary,
            ]
        )
        if expected_preview and expected_preview != preview_hash:
            raise ApiError(
                409,
                "manual_handoff_preview_stale",
                "资料、商品目录或相似单据在业务预览后已变化，请重新预览业务衔接；本次未创建目标。",
            )
        if preview_only:
            return summary | {"handoff_preview_hash": preview_hash}
    # Lock this batch to one logical command before calling the other service.
    with svc.engine.begin() as con:
        current = svc.load(con, batch_id, lock=True)
        if current["revision"] != command.expected_revision or (
            current["target_json"]
            and (
                current["target_json"]["token"] != token
                or current["target_json"].get("request_hash", request_hash)
                != request_hash
                or current["target_json"].get(
                    "actor_id", str(svc.context.principal_user_id)
                )
                != str(svc.context.principal_user_id)
            )
        ):
            raise ApiError(
                409, "manual_handoff_conflict", "资料已有更新或另一个移交操作。"
            )
        if covered:
            locked_stock = svc.load(con, covered["id"], lock=True)
            if locked_stock["revision"] != covered["revision"]:
                raise ApiError(
                    409,
                    "manual_coverage_stale",
                    "库存资料已有新修订，请重新核对覆盖关系。",
                )
        con.execute(
            batches.update()
            .where(batches.c.id == batch_id)
            .values(
                target_json={
                    "token": token,
                    "kind": expected_target,
                    "state": "HANDOFF_PENDING",
                    "request_hash": request_hash,
                    "actor_id": str(svc.context.principal_user_id),
                    "command": command.model_dump(),
                },
                updated_at=now(),
            )
        )
    try:
        if batch["kind"] == "inventory":
            from app.production.inventory_review import start_from_manual_snapshot

            result = start_from_manual_snapshot(
                svc.engine, svc.context, inventory_snapshot(batch)
            )
            target = {
                "kind": expected_target,
                "id": result["review_id"],
                "url": "/production/inventory?review=" + result["review_id"],
            }
        elif historical and covered:
            target = {
                "kind": "historical_reference",
                "id": covered["id"],
                "url": (covered["target"] or {}).get("url")
                or f"/production/manual-tables/{covered['id']}",
                "inventory_revision": covered["revision"],
                "units": fresh["total_units"],
                "basis": command.reason,
                "inventory_posted": False,
                "shipment_created": False,
            }
        else:
            assert payload is not None
            result = cast(
                dict[str, Any],
                production_request(
                    svc.settings,
                    svc.context,
                    "POST",
                    path,
                    body=payload,
                    operation_key=token,
                ),
            )
            target = {
                "kind": expected_target,
                "id": result["id"],
                "url": f"/production/{path}/{result['id']}",
            }
    except ApiError as error:
        # An explicit rejection has no unknown effect; transport failures retain intent.
        if error.status_code < 500:
            with svc.engine.begin() as con:
                current = svc.load(con, batch_id, lock=True)
                if current["target_json"] and current["target_json"]["token"] == token:
                    con.execute(
                        batches.update()
                        .where(batches.c.id == batch_id)
                        .values(target_json=None)
                    )
        raise
    return complete_handoff(svc, batch_id, command, request_hash, target)


def complete_handoff(
    svc: ManualTables,
    batch_id: str,
    command: Command,
    request_hash: str,
    target: dict[str, Any],
) -> dict[str, Any]:
    token = svc._token(command.operation_token)
    with svc.engine.begin() as con:
        current = svc.load(con, batch_id, lock=True)
        replay = svc.replay(con, token, request_hash)
        if replay:
            return replay
        target.update(token=token, state="HANDED_OFF")
        con.execute(
            batches.update()
            .where(batches.c.id == batch_id)
            .values(target_json=target, updated_at=now())
        )
        result = {"id": batch_id, "revision": current["revision"], "target": target}
        svc.record(
            con, token, batch_id, "HANDOFF", request_hash, result, command.reason
        )
        return result
