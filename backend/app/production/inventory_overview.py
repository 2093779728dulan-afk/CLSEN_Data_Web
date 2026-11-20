# ruff: noqa: RUF001
"""Inventory sheet read model. Source modules retain every quantity writer."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import cmp_to_key
from io import BytesIO
from typing import Any, cast
from zoneinfo import ZoneInfo

from openpyxl import Workbook  # type: ignore[import-untyped]
from openpyxl.comments import Comment  # type: ignore[import-untyped]
from openpyxl.styles import Alignment, Font, PatternFill  # type: ignore[import-untyped]

from app.analytics.style_repository import (
    MySqlStyleAnalyticsRepository,
    StyleAnalyticsError,
)
from app.api.errors import ApiError
from app.production.client import production_request
from app.production.fba_transit_opening import load_transit_opening, opening_records
from app.production.identity import catalog_for_report_scope, production_skus
from app.production.inventory_sheet_source import (
    apply_source_row,
    load_sheet_source,
    reconcile_source_catalog,
    source_facts,
)
from app.production.inventory_workbook_metrics import (
    load_workbook_metrics,
    merge_workbook_reports,
    workbook_adjustments,
    workbook_quantity,
)

type Quantity = dict[str, Any]

STATES = {
    "ready": "完整",
    "partial": "部分数据",
    "indeterminate": "退货发生日完整性未定",
    "missing_report": "缺报/未发布",
    "history_unavailable": "历史不可用",
    "not_ready": "未建账/待核",
    "identity_pending": "商品身份待核",
    "not_connected": "未接入/无可靠来源",
    "shortage": "库存占用缺口",
}
PRODUCTION_KEYS = {
    "production.pending": "待生产",
    "production.pendingReceipt": "待入库",
    "production.ordered": "下单数量",
    "production.completed": "已生产",
    "production.received": "已入库",
}
STOCK_KEYS = {
    "domestic": "广州成品仓",
    "available": "美国FBA可售",
    "transit": "美国FBA在途",
    "unsellable": "美国FBA不可售",
    "fba": "美国FBA实际在库",
}
ADJUSTMENTS = {
    "removed": None,
    "warehouseDamaged": "WAREHOUSE_DAMAGED",
    "warehouseLost": None,
    "carrierDamaged": "CARRIER_DAMAGED",
    "unreceivedReturn": None,
    "defective": "DEFECTIVE",
    "customerDamaged": "CUSTOMER_DAMAGED",
    "shipmentDifference": None,
}
ADJUSTMENT_LABELS = dict(
    zip(
        ADJUSTMENTS,
        [
            "移除订单",
            "仓库损坏",
            "仓库丢失",
            "承运商损坏",
            "未收到退货",
            "缺陷",
            "客户损坏",
            "货件差异",
        ],
        strict=True,
    )
)


def quantity(
    value: object = None, state: str = "ready", *, reason: str = "", **extra: Any
) -> Quantity:
    return {
        "value": None if value is None else str(value),
        "state": state,
        "partial": state != "ready",
        "reason": reason,
        **extra,
    }


def sum_quantities(items: list[Quantity]) -> Quantity:
    known = sum(
        int(v["value"]) if v["value"] is not None else int(v.get("known_units", 0))
        for v in items
    )
    unknown = sum(int(v.get("unknown_count", v["value"] is None)) for v in items)
    states = list(dict.fromkeys(v["state"] for v in items if v["state"] != "ready"))
    state = states[0] if len(states) == 1 else "partial" if states else "ready"
    result = quantity(
        None if unknown else known,
        state,
        known_units=str(known),
        unknown_count=unknown,
        reason="；".join(
            dict.fromkeys(v.get("reason", "") for v in items if v.get("reason"))
        ),
    )
    evidence = [item["evidence"] for item in items if item.get("evidence")]
    labels = {item["label"] for item in evidence}
    if len(labels) == 1:
        result["evidence"] = {
            "label": next(iter(labels)),
            "units": str(sum(int(item["units"]) for item in evidence)),
        }
    return result


def periods(as_of: date) -> dict[str, dict[str, dict[str, str]]]:
    def span(start: date, end: date) -> dict[str, str]:
        return {"start": start.isoformat(), "end": end.isoformat()}

    week = as_of - timedelta(days=as_of.weekday())
    result = {
        "week": {
            "current": span(week, as_of),
            "previous": span(week - timedelta(days=7), as_of - timedelta(days=7)),
        }
    }
    for name, months in [("month", 1), ("quarter", 3), ("year", 12)]:
        first = as_of.year * 12 + ((as_of.month - 1) // months) * months
        next_first = date((first + months) // 12, (first + months) % 12 + 1, 1)
        if next_first - timedelta(days=1) > as_of:
            first -= months
        start = date(first // 12, first % 12 + 1, 1)
        end = date((first + months) // 12, (first + months) % 12 + 1, 1) - timedelta(
            days=1
        )
        prior = date((first - months) // 12, (first - months) % 12 + 1, 1)
        result[name] = {
            "current": span(start, end),
            "previous": span(prior, start - timedelta(days=1)),
        }
    return result


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _effective_events(
    facts: dict[str, Any],
) -> tuple[list[dict[str, Any]], set[tuple[str, str, str]]]:
    """Re-date corrected sources using their current effective contributions."""
    sources = {("stock", str(row["id"])): row for row in facts["stock_sources"]}
    sources.update(
        {("shipments", str(row["id"])): row for row in facts["shipment_sources"]}
    )
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    effective, unavailable = [], set()
    for row in facts["events"]:
        if (
            row["document_kind"] == "stock"
            and str(row["delta_units"]) == "0"
            and row.get("reason") == "新规格首次入库，原库存默认为0"
        ):
            effective.append({**row, "document_kind": "stock_initialization"})
        source = sources.get((row["document_kind"], str(row["document_id"])))
        if source:
            grouped[
                (
                    row["document_kind"],
                    str(row["document_id"]),
                    str(row["warehouse_id"]),
                    str(row["owner_id"]),
                    str(row["sku_id"]),
                    row["quality"],
                )
            ].append(row)
        elif row["document_kind"] in {
            "opening",
            "destination",
            "fba_receipt",
            "fba_fulfillment",
            "fba_return",
            "fba_quality",
        }:
            effective.append(dict(row))
        else:
            unavailable.add(
                (str(row["warehouse_id"]), str(row["owner_id"]), str(row["sku_id"]))
            )
    for key, members in grouped.items():
        source = sources[(key[0], key[1])]
        net = sum(int(row["delta_units"]) for row in members)
        if net:
            effective.append(
                {
                    **members[-1],
                    "delta_units": str(net),
                    "business_date": str(source["business_date"]),
                    "revision": source["revision"],
                    "reason": "当前有效来源，更正日期已归位",
                }
            )
    if facts["identity_changes"]:
        # Legacy rebindings have no proven SKU-effective business date.
        for revision in facts["identity_changes"]:
            payload = _json(revision["after_value"])
            mappings = payload.get("mappings", []) if isinstance(payload, dict) else []
            affected = {str(m["target_sku_id"]) for m in mappings}
            for balance in payload.get("balances", []):
                if str(balance["sku_id"]) in affected:
                    unavailable.add(
                        (
                            str(balance["warehouse_id"]),
                            str(balance["owner_id"]),
                            str(balance["sku_id"]),
                        )
                    )
            if not mappings:
                unavailable.update(
                    (str(row["warehouse_id"]), str(row["owner_id"]), str(row["sku_id"]))
                    for row in facts["events"]
                    if str(row["warehouse_id"]) == str(revision["document_id"])
                )
    receipt_movements: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in facts["events"]:
        if event["document_kind"] == "fba_receipt":
            receipt_movements[str(event["document_id"])].append(event)
    dated_receipts = set()
    for receipt in facts["fba_state"].get("events", []):
        movements = receipt_movements[str(receipt["id"])]
        if (
            (
                receipt.get("source_kind") == "REPORT"
                or (
                    receipt.get("source_kind") == "MANUAL"
                    and receipt.get("time_precision") == "TIMESTAMP"
                )
            )
            and receipt.get("occurred_at")
            and len(movements) == 1
            and str(movements[0]["business_date"]) == str(receipt.get("business_date"))
            and int(movements[0]["delta_units"]) == int(receipt["units"])
        ):
            dated_receipts.add(str(receipt["id"]))
    # Legacy corrections still require a proven date for both signed events.
    for row in facts["fba_state"].get("events", []):
        if row.get("correction_of"):
            if {str(row["id"]), str(row["correction_of"])} <= dated_receipts:
                continue
            scope = next(
                v
                for v in facts["fba_state"]["scopes"]
                if str(v["id"]) == str(row["scope_id"])
            )
            unavailable.add(
                (str(scope["warehouse_id"]), str(scope["owner_id"]), str(row["sku_id"]))
            )
    return effective, unavailable


def _historical_stock(
    facts: dict[str, Any],
    stock: dict[str, Any],
    scope: dict[str, Any],
    sku: str,
    as_of: date,
    today: date,
    effective: list[dict[str, Any]],
    unavailable: set[tuple[str, str, str]],
    *,
    catalog_default_zero: bool = False,
) -> tuple[dict[str, Quantity], list[dict[str, Any]]]:
    original = next(
        (
            row
            for row in stock["items"]
            if str(row["sku_id"]) == sku
            and str(row["owner_id"]) == str(scope["owner_id"])
        ),
        None,
    )
    fields = [
        "on_hand_units",
        "free_available_units",
        "defective_units",
        "qualified_units",
        "pending_units",
        "unassessed_units",
        "held_units",
        "reserved_units",
    ]
    all_records = [
        row
        for row in effective
        if str(row["sku_id"]) == sku
        and str(row["warehouse_id"]) == str(scope["warehouse_id"])
        and str(row["owner_id"]) == str(scope["owner_id"])
    ]
    records = [
        row for row in all_records if str(row["business_date"]) <= as_of.isoformat()
    ]
    if original is None:
        if catalog_default_zero:
            has_history = bool(all_records)
            if (
                as_of.isoformat() < str(scope["cutoff_on"])
                or has_history
                or (str(scope["warehouse_id"]), str(scope["owner_id"]), sku)
                in unavailable
            ):
                return {
                    key: quantity(
                        state="history_unavailable", reason="该日期缺少可靠库存依据"
                    )
                    for key in fields
                }, records
            return {
                key: quantity("0", reason="已建档规格，无库存记录按0展示")
                for key in fields
            }, []
        return {
            key: quantity(state="not_ready", reason="该仓库/货主/SKU未建账")
            for key in fields
        }, []
    if as_of == today and len(records) == len(all_records):
        return {
            key: quantity(
                original.get(key),
                original["state"] if original.get(key) is None else "ready",
                reason=original.get("missing", ""),
            )
            for key in fields
        }, records
    cutoff = str(scope["cutoff_on"])
    first = min((str(row["business_date"]) for row in records), default=None)
    explicit_fba_zero = str(scope.get("simulated", "")).lower() in {
        "true",
        "1",
    } and any(
        str(row["sku_id"]) == sku and str(row["scope_id"]) == str(scope.get("id"))
        for row in facts["fba_state"].get("identities", [])
    )
    if explicit_fba_zero:
        first = cutoff
    if (
        (str(scope["warehouse_id"]), str(scope["owner_id"]), sku) in unavailable
        or as_of.isoformat() < cutoff
        or first is None
    ):
        return {
            key: quantity(
                state="history_unavailable",
                reason="早于可靠建账/首次入库，或来源身份/更正有效日不可证明",
            )
            for key in fields
        }, records
    buckets = {
        q: sum(int(row["delta_units"]) for row in records if row["quality"] == q)
        for q in ["QUALIFIED", "PENDING", "DEFECTIVE", "UNASSESSED"]
    }
    reconciled = original.get("on_hand_units") is not None and sum(
        int(row["delta_units"]) for row in all_records
    ) == int(original["on_hand_units"])
    if not reconciled or min(buckets.values()) < 0:
        return {
            key: quantity(
                state="history_unavailable",
                reason="有效来源历史与当前余额未守恒，需核对来源",
            )
            for key in fields
        }, records
    result = {
        "on_hand_units": quantity(sum(buckets.values())),
        "qualified_units": quantity(buckets["QUALIFIED"]),
        "defective_units": quantity(buckets["DEFECTIVE"]),
        "pending_units": quantity(buckets["PENDING"]),
        "unassessed_units": quantity(buckets["UNASSESSED"]),
    }
    # Occupancy revisions do not retain a reliable effective business date.
    occupied = int(original.get("held_units", 0)) + int(
        original.get("reserved_units", 0)
    )
    for revision in facts.get("occupancy_history", []):
        prior = _json(revision["after_value"])
        if (
            str(prior.get("sku_id")) == sku
            and str(prior.get("warehouse_id")) == str(scope["warehouse_id"])
            and str(prior.get("owner_id")) == str(scope["owner_id"])
        ):
            occupied = max(occupied, 1)
    for key in ["free_available_units", "held_units", "reserved_units"]:
        result[key] = (
            quantity(state="history_unavailable", reason="历史冻结/预留有效日不可证明")
            if occupied
            else quantity(buckets["QUALIFIED"] if key == "free_available_units" else 0)
        )
    if buckets["UNASSESSED"]:
        result["free_available_units"] = quantity(
            state="not_ready", reason="历史质量尚未核定"
        )
    return result, records


def _production(
    facts: dict[str, Any], sku: str, as_of: date, today: date
) -> tuple[dict[str, Quantity], list[dict[str, Any]]]:
    rows = []
    history_unknown = False
    for order in facts["orders"]:
        if (
            order.get("receipt_warehouse_id") is None
            or order.get("receipt_owner_id") is None
        ):
            continue
        revisions = [
            r
            for r in facts["production_revisions"]
            if str(r["document_id"]) == str(order["id"])
        ]
        undated_decisions = {
            "CLOSE_TRACKING",
            "REOPEN_TRACKING",
            "COMPLETE_PRODUCTION",
            "REOPEN_PRODUCTION",
        }
        if as_of != today and any(
            r["operation_kind"] in undated_decisions for r in revisions
        ):
            if any(str(line["sku_id"]) == sku for line in order["lines"]):
                history_unknown = True
            continue
        if order.get("production_completion_state") == "COMPLETED":
            continue
        for line in order["lines"]:
            if str(line["sku_id"]) != sku:
                continue
            progress = line
            if as_of != today:
                snapshots = [
                    _json(r["after_value"])
                    for r in revisions
                    if r["operation_kind"] in {"CONFIRM", "CREATE_CONFIRMED"}
                ]
                for revision in revisions:
                    if (
                        revision["operation_kind"]
                        in {"PRODUCTION_PROGRESS", "DEMAND_CHANGE"}
                        and revision.get("effective_date")
                        and str(revision["effective_date"]) <= as_of.isoformat()
                    ):
                        snapshots.append(_json(revision["after_value"]))
                progress = next(
                    (
                        v
                        for snapshot in reversed(snapshots)
                        for v in snapshot.get("lines", [])
                        if str(v["sku_id"]) == sku
                    ),
                    {},
                )
                if not progress:
                    history_unknown = True
                    continue
            expected = int(progress["expected_units"])
            received = sum(
                int(allocation["units"])
                for document in facts["stock_sources"]
                if document["status"] == "POSTED"
                and document["kind"] == "IN"
                and str(document["business_date"]) <= as_of.isoformat()
                for receipt in _json(document["line_items"])
                if receipt.get("purpose") == "PRODUCTION_RECEIPT"
                for allocation in receipt.get("production_allocations", [])
                if str(allocation["order_line_id"]) == str(line["id"])
            )
            direct = sum(
                int(v["units"])
                for v in facts["order_shipments"]
                if str(v["order_line_id"]) == str(line["id"])
                and str(v["business_date"]) <= as_of.isoformat()
            )
            produced = (
                int(progress["produced_units"])
                if progress.get("produced_units") is not None
                else None
            )
            pending = (
                0
                if line["tracking_state"] == "CLOSED"
                else max(expected - produced, 0)
                if produced is not None
                else None
            )
            intake = (
                max(produced - received - direct, 0) if produced is not None else None
            )
            if pending == 0 and intake == 0:
                continue
            notes = []
            if produced is not None and produced > expected:
                notes.append(f"超产{produced - expected}件，保留原数量")
            if produced is not None and received + direct > produced:
                excess = received + direct - produced
                notes.append(f"入库与直发合计超生产进度{excess}件，待入库下限0")
            if received > expected:
                notes.append(f"超收{received - expected}件，保留原数量")
            rows.append(
                {
                    "id": str(line["id"]),
                    "order_id": str(order["id"]),
                    "sku_id": sku,
                    "business_number": order["business_number"],
                    "business_date": str(order["business_date"]),
                    "factory": order.get("factory_name"),
                    "due_on": str(line.get("due_on") or ""),
                    "tracking_state": line["tracking_state"],
                    "revision": str(order["revision"]),
                    "production.ordered": str(expected),
                    "production.completed": None if produced is None else str(produced),
                    "production.received": str(received),
                    "production.pending": None if pending is None else str(pending),
                    "production.pendingReceipt": None
                    if intake is None
                    else str(intake),
                    "production_direct_units": str(direct),
                    "progress_note": "；".join(notes),
                    "production_status": line.get("production_status", ""),
                }
            )
    if history_unknown:
        return {
            key: quantity(
                state="history_unavailable",
                reason="订单跟进/完成决定缺少可靠历史生效日",
            )
            for key in PRODUCTION_KEYS
        }, rows
    return {
        key: sum_quantities(
            [
                quantity(
                    row[key],
                    "not_ready" if row[key] is None else "ready",
                    reason="生产进度未知" if row[key] is None else "",
                )
                for row in rows
            ]
        )
        for key in PRODUCTION_KEYS
    }, rows


def _report_coverage(
    report: dict[str, Any], span: dict[str, str], metric: str
) -> tuple[bool, int, int]:
    kind = "business_report" if metric == "units" else "return_report"
    published = {
        str(row["report_date"])
        for row in report["members"]
        if row["report_type"] == kind and row["report_status"] == "published"
    }
    count = sum(span["start"] <= day <= span["end"] for day in published)
    expected = (
        date.fromisoformat(span["end"]) - date.fromisoformat(span["start"])
    ).days + 1
    return bool(published), count, expected


def _report_quantity(
    report: dict[str, Any],
    days: dict[tuple[str, str], dict[str, int]],
    sku: str,
    span: dict[str, str],
    metric: str,
    *,
    coverage: tuple[bool, int, int] | None = None,
) -> Quantity:
    if report["state"] != "ready":
        return quantity(
            state="not_ready", reason=report.get("reason", "报表读取前置未就绪")
        )
    manual = workbook_quantity(report, days, sku, span, metric)
    if manual is not None:
        return manual
    published, count, expected = (
        coverage if coverage is not None else _report_coverage(report, span, metric)
    )
    value = sum(
        row[metric]
        for (row_sku, day), row in days.items()
        if row_sku == sku and span["start"] <= day <= span["end"]
    )
    if sku in report.get("blocked_sku_ids", []):
        return quantity(
            state="identity_pending",
            reason="当前平台资料与已发布报告不一致，需在原商品关联中核对",
            known_units=str(value),
            unknown_count=1,
        )
    unresolved = sum(
        int(row["unresolved_rows"])
        for row in report.get("unresolved", [])
        if str(row["sku_id"]) == sku
        and span["start"] <= str(row["metric_date"]) <= span["end"]
    )
    if metric == "returns" and unresolved:
        return quantity(
            state="not_ready",
            reason=f"存在{unresolved}行退货去重待核",
            known_units=str(value),
            unknown_count=unresolved,
        )
    if not published or (metric == "units" and count == 0):
        return quantity(
            state="missing_report",
            reason="所选期间没有有效已发布报告",
            observed_days=count,
            expected_days=expected,
        )
    if metric == "returns":
        return quantity(
            value,
            "indeterminate",
            reason="退货按站点时区发生日；晚报、未映射与去重待核可影响完整性",
            observed_days=count,
            expected_days=expected,
        )
    platform_incomplete = report.get("platform", {}).get("state") == "incomplete"
    return quantity(
        value,
        "partial" if count < expected or platform_incomplete else "ready",
        reason=("期间有缺报/未发布/撤回日期" if count < expected else "")
        + ("；平台标识核对未覆盖全部键" if platform_incomplete else ""),
        observed_days=count,
        expected_days=expected,
    )


def _net(units: Quantity, returns: Quantity) -> Quantity:
    if units["value"] is None or returns["value"] is None:
        missing = units if units["value"] is None else returns
        return quantity(
            state=missing["state"], reason="净销量不可完整计算；" + missing["reason"]
        )
    state = (
        "indeterminate"
        if returns["state"] == "indeterminate"
        else "partial"
        if units["partial"] or returns["partial"]
        else "ready"
    )
    return quantity(
        int(units["value"]) - int(returns["value"]),
        state,
        reason="；".join(v["reason"] for v in [units, returns] if v["reason"]),
    )


def _unavailable_reports(reason: str) -> dict[str, Any]:
    return {
        "state": "not_ready",
        "reason": reason,
        "members": [],
        "business": [],
        "returns": [],
        "provenance": {},
        "coverage": [],
        "daily": {"issues": [{"label": reason}]},
    }


def read_sheet(
    settings: Any, context: Any, engine: Any, query: dict[str, str]
) -> dict[str, Any]:
    try:
        as_of = date.fromisoformat(query["as_of"])
    except (ValueError, KeyError) as error:
        raise ApiError(422, "sheet_date_invalid", "请选择有效统计截止日期。") from error
    today = datetime.now(ZoneInfo(context.reporting_timezone)).date()
    if as_of < date(1900, 1, 1) or as_of > today:
        raise ApiError(
            422, "sheet_date_invalid", "截止日期须在1900年起至站点当天范围内。"
        )
    scope_query = [
        (k, query.get(k, ""))
        for k in ["as_of", "domestic_warehouse_id", "domestic_owner_id", "fba_scope_id"]
    ]
    source = load_sheet_source(settings, context, engine)
    catalog = production_skus(settings, context, engine)
    if source is not None:
        source = reconcile_source_catalog(source, catalog)
    facts = (
        source_facts(source, query)
        if source is not None
        else cast(
            dict[str, Any],
            production_request(
                settings, context, "GET", "inventory/overview-sheet", query=scope_query
            ),
        )
    )
    if source is not None:
        ledger = source.get("fba_ledger")
        if ledger:
            facts = cast(
                dict[str, Any],
                production_request(
                    settings,
                    context,
                    "GET",
                    "inventory/overview-sheet",
                    query=[
                        ("as_of", query["as_of"]),
                        ("domestic_warehouse_id", ledger["domestic_warehouse_id"]),
                        ("domestic_owner_id", ledger["domestic_owner_id"]),
                        ("fba_scope_id", ledger["scope_id"]),
                    ],
                ),
            )
            if str(facts["resolved_scope"]["fba"]["warehouse_id"]) != str(
                source["directory_evidence"]["bindings"]["fba_warehouse_id"]
            ):
                raise ApiError(
                    409, "sheet_source_scope_invalid", "FBA账簿与资料仓库不一致。"
                )
        display = cast(
            dict[str, Any],
            production_request(settings, context, "GET", "inventory/display-settings"),
        )
        facts["settings"] = {
            **display,
            "can_manage": False,
            "can_manage_styles": display["can_manage"],
        }
    fba = facts["resolved_scope"]["fba"]
    if source is None:
        catalog = catalog_for_report_scope(
            engine, context, catalog, int(fba["report_source_scope_id"])
        )
    transit_scope = next(
        (
            row
            for row in facts["fba_state"].get("scopes", [])
            if str(row["id"]) == str(fba["id"])
        ),
        fba,
    )
    transit_opening = load_transit_opening(
        settings, context, engine, catalog, transit_scope
    )
    opening_by_sku = {
        row["sku_id"]: row for row in opening_records(transit_opening, as_of)
    }
    ranges = periods(as_of)
    if facts["report_scope_count"] != 1:
        reports = _unavailable_reports(
            "同一报表来源绑定多个FBA范围，请先在原范围资料中核对归属。"
        )
    else:
        try:
            reports = MySqlStyleAnalyticsRepository(engine).inventory_days(
                site_id=context.site_id,
                scope=fba,
                from_date=date.fromisoformat(ranges["year"]["previous"]["start"]),
                to_date=as_of,
                fba_state=(
                    None
                    if source is not None and not source.get("fba_ledger")
                    else facts["fba_state"]
                ),
            )
        except StyleAnalyticsError as error:
            reports = _unavailable_reports(
                "报表目录/发布/去重前置待核（" + error.code + "）"
            )
    workbook_metrics = load_workbook_metrics(settings, context, engine, catalog, fba)
    reports = merge_workbook_reports(reports, workbook_metrics, as_of)
    timezone = reports.get("provenance", {}).get(
        "reporting_timezone", context.reporting_timezone
    )
    today = datetime.now(ZoneInfo(timezone)).date()
    if as_of > today or as_of < date(1900, 1, 1):
        raise ApiError(
            422, "sheet_date_invalid", "截止日期须在1900年起至站点当天范围内。"
        )
    catalog_versions = {row.get("catalog_version") for row in catalog.values()}
    report_catalog = reports.get("provenance", {}).get("catalog_version_id")
    report_config = reports.get("provenance", {}).get("site_config_version_id")
    if report_config and str(report_config) != str(context.site_config_version_id):
        raise ApiError(
            409, "sheet_refresh_required", "站点配置在读取期间已变化，请刷新总表。"
        )
    if report_catalog and not all(
        str(v).split(":")[0] == str(report_catalog) for v in catalog_versions
    ):
        raise ApiError(
            409, "sheet_refresh_required", "目录在读取期间已变化，请刷新总表。"
        )
    days: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"units": 0, "returns": 0}
    )
    for metric, fact_source in [("units", "business"), ("returns", "returns")]:
        for row in reports[fact_source]:
            days[str(row["sku_id"]), str(row["metric_date"])][metric] += int(
                row[metric]
            )
    days_by_sku: dict[str, dict[tuple[str, str], dict[str, int]]] = defaultdict(dict)
    for day_key, day_values in days.items():
        days_by_sku[day_key[0]][day_key] = day_values
    unresolved_by_sku: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in reports.get("unresolved", []):
        unresolved_by_sku[str(row["sku_id"])].append(row)
    spans = {
        "": {
            "start": reports.get("read_from") or as_of.isoformat(),
            "end": as_of.isoformat(),
        }
    }
    for period, pair in ranges.items():
        spans[period + "."] = pair["current"]
        spans[period + ".previous."] = pair["previous"]
    day = date.fromisoformat(ranges["week"]["current"]["start"])
    while day <= as_of:
        spans[f"day.{day}."] = {"start": day.isoformat(), "end": day.isoformat()}
        day += timedelta(days=1)
    report_coverage = {
        (prefix, metric): _report_coverage(reports, span, metric)
        for prefix, span in spans.items()
        for metric in ("units", "returns")
    }
    effective, unavailable = _effective_events(facts)
    identities = {
        str(row["sku_id"]): row
        for row in facts["fba_state"].get("identities", [])
        if str(row["scope_id"]) == str(fba["id"])
    }
    historic = {
        str(row["sku_id"]): row
        for row in facts["domestic_stock"]["items"]
        + facts["fba_state"]["stock"]["items"]
    }
    selected_styles = set(map(str, facts["settings"]["style_ids"]))
    result_rows: list[dict[str, Any]] = []
    for sku in sorted(set(catalog) | set(historic), key=lambda value: value.zfill(20)):
        identity = catalog.get(sku)
        if identity is None:
            continue
        style = str(identity["style_id"] or f"sku-{sku}")
        if selected_styles and style not in selected_styles:
            continue
        values, records = {}, {}
        production, records["production"] = _production(facts, sku, as_of, today)
        values.update(production)
        domestic, records["domestic"] = _historical_stock(
            facts,
            facts["domestic_stock"],
            facts["resolved_scope"]["domestic"],
            sku,
            as_of,
            today,
            effective,
            unavailable,
            catalog_default_zero=identity.get("status") == "active",
        )
        fbastock, records["stock"] = _historical_stock(
            facts,
            facts["fba_state"]["stock"],
            fba,
            sku,
            as_of,
            today,
            effective,
            unavailable,
            catalog_default_zero=identity.get("status") == "active",
        )
        values.update(
            {
                "domestic": domestic["on_hand_units"],
                "available": fbastock["free_available_units"],
                "fba": fbastock["on_hand_units"],
                "unsellable": fbastock["defective_units"],
            }
        )
        transit = [row for row in facts["transit"] if str(row["sku_id"]) == sku]
        records["transit"] = [
            {
                **row,
                "remaining_units": str(
                    int(row["actual_units"])
                    - int(row["received_units"])
                    - int(row["settled_units"])
                )
                if row["actual_units"] == row["mapped"]
                else None,
            }
            for row in transit
        ]
        values["transit"] = sum_quantities(
            [
                quantity(
                    row["remaining_units"],
                    "not_ready" if row["remaining_units"] is None else "ready",
                    reason="出货binding未完整登记"
                    if row["remaining_units"] is None
                    else "",
                )
                for row in records["transit"]
            ]
        )
        if as_of != today and any(
            int(row.get("settlement_history", 0)) for row in transit
        ):
            values["transit"] = quantity(
                state="history_unavailable",
                reason="该出货有结清决定，缺少可靠历史生效日",
            )
        values["dispatched"] = quantity(
            sum(int(row["actual_units"]) for row in transit),
            history_from=str(fba["cutoff_on"]),
        )
        records["shipments"] = transit
        if sku in opening_by_sku:
            opening = opening_by_sku[sku]
            records["transit"].append(opening)
            values["transit"] = sum_quantities(
                [values["transit"], quantity(opening["remaining_units"])]
            )
        classification = (
            facts["fba_state"].get("classification_summary", {}).get(str(fba["id"]), {})
        )
        records["adjustments"] = [
            row for row in classification.get("items", []) if str(row["sku_id"]) == sku
        ]
        for key, code in ADJUSTMENTS.items():
            if code is None:
                values[key] = quantity(
                    state="not_connected", reason="未接入/无可靠来源"
                )
            elif as_of != today:
                values[key] = quantity(
                    state="history_unavailable", reason="原因分类只提供当前有效余额"
                )
            elif sku not in identities:
                values[key] = quantity(
                    state="not_ready", reason="该SKU尚未关联所选FBA范围"
                )
            elif not classification.get("ready"):
                values[key] = quantity(
                    state="not_ready",
                    reason=str(classification.get("issue") or "分类待核"),
                )
            else:
                values[key] = quantity(
                    sum(
                        int(row["units"])
                        for row in records["adjustments"]
                        if row.get("reason_code") == code
                    )
                )
        workbook_adjustments(workbook_metrics, sku, as_of, values, records)
        sku_report = {**reports, "unresolved": unresolved_by_sku.get(sku, [])}
        sku_days = days_by_sku.get(sku, {})
        for prefix, span in spans.items():
            units = _report_quantity(
                sku_report,
                sku_days,
                sku,
                span,
                "units",
                coverage=report_coverage[prefix, "units"],
            )
            returns = _report_quantity(
                sku_report,
                sku_days,
                sku,
                span,
                "returns",
                coverage=report_coverage[prefix, "returns"],
            )
            values.update(
                {
                    prefix + "units": units,
                    prefix + "returns": returns,
                    prefix + "net": _net(units, returns),
                }
            )
        if identity.get("status") == "pending":
            values = {
                key: quantity(v["value"], "identity_pending", reason="历史身份待核")
                for key, v in values.items()
            }
        if source is not None:
            apply_source_row(source, sku, as_of, values, records)
            domestic["on_hand_units"] = values["domestic"]
        alert = (
            facts["settings"]
            .get("sku_alert_settings", {})
            .get(str(fba["id"]), {})
            .get(sku, {"threshold": "20", "replenish": True})
        )
        available = values["available"]["value"]
        level = (
            "unknown"
            if available is None
            else ("empty" if alert["replenish"] else "sold-out")
            if int(available) <= 0
            else "low"
            if alert["replenish"] and int(available) <= int(alert["threshold"])
            else "normal"
        )
        result_rows.append(
            {
                **identity,
                "sku_id": sku,
                "style_id": style,
                "sku": identity.get("code") or identity["label"],
                "values": values,
                "records": records,
                "production_statuses": [
                    {
                        "order_id": item["order_id"],
                        "order_number": item["business_number"],
                        "status": item["production_status"],
                    }
                    for item in records["production"]
                    if item.get("production_status")
                ],
                "stock_explanation": {"domestic": domestic, "fba": fbastock},
                "alert": {
                    **alert,
                    "level": level,
                    "configurable": sku in identities
                    and identity.get("status") == "active",
                },
                "history_from": {
                    "domestic": facts["resolved_scope"]["domestic"]["cutoff_on"],
                    "fba": fba["cutoff_on"],
                },
            }
        )
    search = query.get("q", "").strip().casefold()
    stock_filter = query.get("stock_filter", "all")
    rows = [
        row
        for row in result_rows
        if (
            not search
            or search
            in " ".join(
                str(row.get(k) or "")
                for k in ["sku", "style_code", "standard_color", "standard_size"]
            ).casefold()
        )
        and (
            stock_filter == "all"
            or (stock_filter == "stopped" and not row["alert"]["replenish"])
            or stock_filter == row["alert"]["level"]
        )
    ]
    if stock_filter not in {"all", "empty", "low", "stopped"}:
        raise ApiError(422, "invalid_stock_filter", "请选择有效库存状态。")
    totals = (
        {
            key: sum_quantities([row["values"][key] for row in rows])
            for key in rows[0]["values"]
        }
        if rows
        else {}
    )
    display_styles: dict[str, dict[str, Any]] = {}
    for entry in catalog.values():
        if entry.get("status") == "active":
            style = str(entry["style_id"])
            item = display_styles.setdefault(
                style, {"id": style, "style_code": entry["style_code"], "sku_count": 0}
            )
            item["sku_count"] += 1
    # Source revisions and publication membership form the version identity.
    reference = {
        "stock_display_policy": "catalog_missing_stock_zero_v1",
        "scope": facts["resolved_scope"],
        "report_scope_count": facts["report_scope_count"],
        "catalog": sorted(str(v) for v in catalog_versions),
        "settings": facts["settings"],
        "events": facts["events"],
        "orders": facts["orders"],
        "domestic_stock": facts["domestic_stock"],
        "fba_stock": facts["fba_state"].get("stock"),
        "production_revisions": facts["production_revisions"],
        "transit": facts["transit"],
        "transit_opening": transit_opening["digest"] if transit_opening else None,
        "reports": reports.get("provenance"),
        "platform": reports.get("platform"),
        "members": reports["members"],
        "fba_actions": facts["fba_state"].get("actions"),
        "classification": facts["fba_state"].get("classification_summary"),
        "source_review": source["digest"] if source is not None else None,
    }
    version = hashlib.sha256(
        json.dumps(reference, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()
    if query.get("version") and query["version"] != version:
        raise ApiError(
            409,
            "sheet_refresh_required",
            "来源已更新，请刷新总表后继续；提醒草稿已保留。",
        )
    return {
        "application_version": "1.1.0-SNAPSHOT",
        "transit_opening": {
            name: transit_opening[name]
            for name in (
                "snapshot_on",
                "source_filename",
                "source_sha256",
                "digest",
                "scope",
            )
        }
        if transit_opening
        else None,
        "source_review": {
            **source["review"],
            "fba_ledger": source.get("fba_ledger"),
            "report_known_units": totals.get("units", {}).get("known_units", "0"),
            "report_known_returns": totals.get("returns", {}).get("known_units", "0"),
            "report_known_net": totals.get("net", {}).get("known_units", "0"),
            "pending_identity_count": len(source["pending_identities"]),
        }
        if source is not None
        else None,
        "version": version,
        "as_of": as_of.isoformat(),
        "today": today.isoformat(),
        "reporting_timezone": timezone,
        "resolved_scope": {
            name: {
                key: value
                for key, value in scope.items()
                if key
                in {
                    "id",
                    "site_id",
                    "warehouse_id",
                    "owner_id",
                    "warehouse_name",
                    "owner_name",
                    "marketplace",
                    "report_source_scope_id",
                    "catalog_version",
                    "cutoff_on",
                    "simulated",
                    "revision",
                    "type",
                    "status",
                }
            }
            for name, scope in facts["resolved_scope"].items()
        },
        "catalog_version": sorted(str(v) for v in catalog_versions),
        "periods": ranges,
        "rows": rows,
        "totals": totals,
        "settings": facts["settings"],
        "display_styles": sorted(
            display_styles.values(), key=lambda item: item["style_code"]
        ),
        "report_provenance": reports.get("provenance", {}),
        "coverage": reports["coverage"],
        "daily": reports["daily"],
        "issues": (
            [{"label": "存在未指定成品仓/货主的订单，未计入当前范围"}]
            if any(
                o.get("receipt_warehouse_id") is None
                or o.get("receipt_owner_id") is None
                for o in facts["orders"]
            )
            else []
        )
        + reports["daily"].get("issues", [])
        + (
            [{"label": "退货存在去重待核记录，受影响SKU保留未知，已知部分单独记录。"}]
            if reports.get("unresolved")
            else []
        )
        + (
            [{"label": reports["platform"]["message"]}]
            if reports.get("platform", {}).get("state") in {"pending", "incomplete"}
            else []
        ),
        "platform": reports.get("platform", {}),
        "daily_rows": [
            {
                "sku_id": sku,
                "date": day,
                "units": str(v["units"]),
                "returns": str(v["returns"]),
            }
            for (sku, day), v in days.items()
        ],
        "cumulative_from": reports.get("read_from"),
        "filter": {"q": search, "stock_filter": stock_filter},
        "total_skus": len(result_rows),
    }


def sheet_summary(sheet: dict[str, Any], *, compact: bool = False) -> dict[str, Any]:
    """The list keeps quantities and versions; details and exports read full facts."""
    result = {
        key: value
        for key, value in sheet.items()
        if key
        not in {"report_provenance", "coverage", "daily", "platform", "daily_rows"}
    }
    result["rows"] = [
        {
            key: value
            for key, value in row.items()
            if key not in {"records", "stock_explanation", "history_from"}
        }
        for row in sheet["rows"]
    ]
    if compact:
        pool: list[Quantity] = []
        indices: dict[str, int] = {}

        def index(value: Quantity) -> int:
            key = json.dumps(value, sort_keys=True, ensure_ascii=False)
            position = indices.get(key)
            if position is None:
                position = len(pool)
                indices[key] = position
                pool.append(value)
            return position

        for row in result["rows"]:
            row["values"] = {key: index(value) for key, value in row["values"].items()}
        result["totals"] = {key: index(value) for key, value in sheet["totals"].items()}
        result["quantity_pool"] = pool
    return result


def metric_quantity(values: dict[str, Quantity], key: str) -> Quantity:
    if key.endswith("Mom"):
        parts = key.removesuffix("Mom").split(".")
        if (
            len(parts) != 2
            or parts[0] not in {"week", "month", "quarter", "year"}
            or parts[1] not in {"units", "returns", "net"}
        ):
            raise ApiError(422, "sheet_metric_invalid", "请选择总表已有比较指标。")
        period, metric = parts
        current, previous = (
            values[f"{period}.{metric}"],
            values[f"{period}.previous.{metric}"],
        )
        if current["value"] is None or previous["value"] is None:
            return quantity(state="missing_report", reason="本期或上期缺数，不可比较")
        return quantity(
            int(current["value"]) - int(previous["value"]),
            "partial" if current["partial"] or previous["partial"] else "ready",
            reason=f"本期{current['value']}；上期{previous['value']}。"
            + current["reason"]
            + previous["reason"],
        )
    if key not in values:
        raise ApiError(422, "sheet_metric_invalid", "请选择总表已有指标。")
    return values[key]


def sheet_details(sheet: dict[str, Any], query: dict[str, str]) -> dict[str, Any]:
    key = query.get("metric", "")
    rows = [
        row
        for row in sheet["rows"]
        if (not query.get("style_id") or row["style_id"] == query["style_id"])
        and (not query.get("sku_id") or row["sku_id"] == query["sku_id"])
    ]
    if not rows:
        raise ApiError(
            404, "sheet_identity_unavailable", "所选商品不在当前总表筛选范围，请刷新。"
        )
    quantities = [metric_quantity(row["values"], key) for row in rows]
    total = sum_quantities(quantities)
    try:
        page, size = int(query.get("page", "1")), int(query.get("page_size", "20"))
        if page < 1 or not 1 <= size <= 100:
            raise ValueError
    except ValueError as error:
        raise ApiError(
            422, "sheet_page_invalid", "明细页码须为正整数，每页最多100行。"
        ) from error
    if key.endswith("Mom"):
        period, metric = key.removesuffix("Mom").split(".")
        current = [row["values"][f"{period}.{metric}"] for row in rows]
        previous = [row["values"][f"{period}.previous.{metric}"] for row in rows]
        entries = [
            {
                "sku_id": row["sku_id"],
                "cells": [row["sku"], now["value"], prior["value"], delta["value"]],
                "quantity": delta,
            }
            for row, now, prior, delta in zip(
                rows, current, previous, quantities, strict=True
            )
            if now["value"] is None
            or prior["value"] is None
            or int(now["value"]) != 0
            or int(prior["value"]) != 0
        ]
        return {
            "version": sheet["version"],
            "grouped": not bool(query.get("sku_id")),
            "columns": ["SKU", "本期", "上期", "增减"],
            "rows": entries[(page - 1) * size : page * size],
            "total": total,
            "comparison_totals": [
                sum_quantities(current),
                sum_quantities(previous),
                total,
            ],
            "total_rows": len(entries),
            "page": page,
            "page_size": size,
            "report_provenance": sheet["report_provenance"],
        }
    if not query.get("sku_id"):
        return {
            "version": sheet["version"],
            "grouped": True,
            "columns": ["SKU", "数量", "状态"]
            + (["生产状态"] if key in PRODUCTION_KEYS else []),
            "rows": [
                {
                    "sku_id": row["sku_id"],
                    "cells": [
                        row["sku"],
                        value["value"],
                        STATES.get(value["state"], value["state"]),
                        *(
                            [
                                " / ".join(
                                    dict.fromkeys(
                                        item["status"]
                                        for item in row.get("production_statuses", [])
                                    )
                                )
                            ]
                            if key in PRODUCTION_KEYS
                            else []
                        ),
                    ],
                    "quantity": value,
                }
                for row, value in list(zip(rows, quantities, strict=True))[
                    (page - 1) * size : page * size
                ]
            ],
            "total": total,
            "total_rows": len(rows),
            "page": page,
            "page_size": size,
            "report_provenance": sheet["report_provenance"],
        }
    row = rows[0]
    records = row["records"]
    if key in PRODUCTION_KEYS:
        columns = [
            "订单",
            "订单日期",
            "工厂",
            "下单",
            "已生产",
            "实收入库",
            "工厂直发",
            "待生产",
            "待入库",
            "跟进",
            "修订",
            "说明",
            "生产状态",
        ]
        entries = [
            {
                "sku_id": row["sku_id"],
                "cells": [
                    v["business_number"],
                    v["business_date"],
                    v["factory"],
                    v["production.ordered"],
                    v["production.completed"],
                    v["production.received"],
                    v["production_direct_units"],
                    v["production.pending"],
                    v["production.pendingReceipt"],
                    v["tracking_state"],
                    v["revision"],
                    v.get("progress_note", ""),
                    v.get("production_status", ""),
                ],
            }
            for v in records["production"]
            if v[key] != "0"
        ]
    elif sheet.get("source_review") and key == "domestic":
        columns = ["盘点日", "来源", "单元格", "原文", "盘点数量", "说明"]
        entries = [
            {
                "sku_id": row["sku_id"],
                "cells": [
                    v["date"],
                    v["filename"],
                    v["cell"],
                    v["raw"],
                    v["units"],
                    v["reason"],
                ],
            }
            for v in records["source_stock"]
        ]
    elif (
        sheet.get("source_review")
        and not sheet["source_review"].get("fba_ledger")
        and key in {"available", "fba"}
    ):
        columns = ["接收日期", "货件", "接收数量", "ASIN", "FNSKU", "来源", "说明"]
        entries = [
            {
                "sku_id": row["sku_id"],
                "cells": [
                    receipt["date"],
                    receipt["reference"],
                    receipt["units"],
                    receipt["asin"],
                    receipt["fnsku"],
                    receipt["source"],
                    "原始接收流水，保留负数更正；当前可售待核",
                ],
            }
            for entry in records.get("source_fba", [])
            for receipt in entry["receipts"]
        ]
    elif sheet.get("source_review") and key in {"transit", "dispatched"}:
        columns = [
            "批次标签",
            "已确认货件",
            "装箱已发",
            "接收累计",
            "待核接收",
            "发出日期",
            "验收状态",
        ]
        entries = [
            {
                "sku_id": row["sku_id"],
                "cells": [
                    entry["batch_date"],
                    entry["reference"] or "货件待补",
                    entry["packed_units"],
                    entry["received_units"],
                    entry["remaining_units"],
                    "实际日期待补",
                    "含已提供接收流水，差异保留"
                    if entry["received_units"] is not None
                    else "验收尚未核对",
                ],
            }
            for entry in records.get("source_fba", [])
        ]
    elif key in STOCK_KEYS and key != "transit":
        columns = ["业务日", "来源", "单据ID", "质量", "有效增减", "修订", "说明"]
        source = records["domestic"] if key == "domestic" else records["stock"]
        entries = [
            {
                "sku_id": row["sku_id"],
                "cells": [
                    v["business_date"],
                    v["document_kind"],
                    v["document_id"],
                    v["quality"],
                    v["delta_units"],
                    v["revision"],
                    v["reason"],
                ],
            }
            for v in source
        ]
    elif key in {"transit", "dispatched"}:
        has_opening = key == "transit" and any(
            item.get("source_kind") == "TRANSIT_OPENING" for item in records["transit"]
        )
        columns = [
            "来源" if has_opening else "出货单",
            "日期" if has_opening else "发货日",
            "来源行",
            "已发",
            "已接收",
            "已结清",
            "未收未结",
            "运输阶段",
            "修订",
        ]
        entries = [
            {
                "sku_id": row["sku_id"],
                "cells": [
                    v["business_number"],
                    v["business_date"],
                    v["source_line_id"],
                    v["actual_units"],
                    v["received_units"],
                    v["settled_units"],
                    v.get("remaining_units"),
                    v["transport_status"],
                    v["revision"],
                ],
            }
            for v in records["shipments" if key == "dispatched" else "transit"]
            if key == "dispatched" or v.get("remaining_units") != "0"
        ]
    elif key in ADJUSTMENTS and "workbook_adjustments" in records:
        columns = ["截止日", "项目", "数量", "来源", "单元格"]
        entries = [
            {
                "sku_id": row["sku_id"],
                "cells": [
                    v["date"],
                    v["heading"],
                    v["units"],
                    v["source"],
                    v["sheet"] + "!" + v["cell"],
                ],
            }
            for v in records["workbook_adjustments"]
            if v["metric"] == key
        ]
    elif key in ADJUSTMENTS:
        columns = [
            "业务日",
            "原因分类",
            "当前余额",
            "来源",
            "来源单据",
            "报告版本",
            "说明",
        ]
        entries = [
            {
                "sku_id": row["sku_id"],
                "cells": [
                    v["business_date"],
                    v["reason_code"],
                    v["units"],
                    v["source_kind"],
                    v.get("document_id"),
                    v.get("report_version_id"),
                    v.get("note"),
                ],
            }
            for v in records["adjustments"]
            if v["reason_code"] == ADJUSTMENTS[key]
        ]
    else:
        metric = key.split(".")[-1]
        if metric not in {"units", "returns", "net"}:
            raise ApiError(422, "sheet_metric_invalid", "请选择销量/退货/净销量指标。")
        if key.startswith("day."):
            start = end = key.split(".")[1]
        elif "." in key:
            pair = sheet["periods"][key.split(".")[0]]
            span = pair["previous" if ".previous." in key else "current"]
            start, end = span["start"], span["end"]
        else:
            start, end = sheet["cumulative_from"] or sheet["as_of"], sheet["as_of"]
        columns = (
            ["发生日", "销量", "退货", "净销量", "口径"]
            if metric == "net"
            else ["发生日", "销量" if metric == "units" else "退货", "口径"]
        )
        entries = []
        for v in sheet["daily_rows"]:
            if v["sku_id"] == row["sku_id"] and start <= v["date"] <= end:
                cells = (
                    [
                        v["date"],
                        v["units"],
                        v["returns"],
                        str(int(v["units"]) - int(v["returns"])),
                    ]
                    if metric == "net"
                    else [v["date"], v[metric]]
                )
                entries.append(
                    {
                        "sku_id": row["sku_id"],
                        "cells": [
                            *cells,
                            "销量按报告日；退货按站点时区发生日，完整性未定",
                        ],
                    }
                )
    return {
        "version": sheet["version"],
        "grouped": False,
        "columns": columns,
        "rows": entries[(page - 1) * size : page * size],
        "total": total,
        "total_rows": len(entries),
        "page": page,
        "page_size": size,
        "stock_explanation": row["stock_explanation"][
            "domestic" if key == "domestic" else "fba"
        ],
        "report_provenance": sheet["report_provenance"],
    }


def _evidence_column_label(sheet: dict[str, Any], key: str) -> str | None:
    if key not in {"available", "transit", "dispatched"}:
        return None
    values = [row["values"][key] for row in sheet["rows"]]
    labels = {value["evidence"]["label"] for value in values if value.get("evidence")}
    if len(labels) != 1 or any(int(value["value"] or 0) for value in values):
        return None
    return "装箱已发" if key == "dispatched" else next(iter(labels))


def _column_title(sheet: dict[str, Any], key: str) -> str:
    if key == "sku":
        return "款号 / SKU"
    evidence_label = _evidence_column_label(sheet, key)
    if evidence_label:
        return evidence_label
    if key in PRODUCTION_KEYS | STOCK_KEYS | ADJUSTMENT_LABELS:
        return (PRODUCTION_KEYS | STOCK_KEYS | ADJUSTMENT_LABELS)[key]
    if key == "dispatched":
        return "累计发货"
    metric = key.removesuffix("Mom").split(".")[-1]
    label = {"units": "销量", "returns": "退货", "net": "净销量"}.get(metric)
    if label is None:
        raise ApiError(422, "sheet_metric_invalid", "导出列无效。")
    if key.startswith("day."):
        return key.split(".")[1] + " " + label
    if "." not in key:
        return "累计" + label
    period = key.split(".")[0]
    if period not in sheet["periods"]:
        raise ApiError(422, "sheet_metric_invalid", "请选择总表已有周期指标。")
    span = sheet["periods"][period]["previous" if ".previous." in key else "current"]
    return f"{span['start']}—{span['end']} {label}" + (
        " 对比上一周期" if key.endswith("Mom") else ""
    )


def _sheet_headers(sheet: dict[str, Any], key: str) -> tuple[str, str, str]:
    _column_title(sheet, key)
    as_of = sheet["as_of"].replace("-", "/")
    if key == "sku":
        return "款号 / SKU", "", ""
    if key in PRODUCTION_KEYS:
        return "未完成订单", f"截至 {as_of}", PRODUCTION_KEYS[key]
    if key == "domestic":
        return f"库存 {as_of}", "成品仓库存", "广州成品仓"
    if key in STOCK_KEYS:
        return (
            "美国FBA",
            as_of,
            _evidence_column_label(sheet, key)
            or {
                "available": "可售",
                "transit": "在途",
                "fba": "实际在库",
                "unsellable": "不可售",
            }[key],
        )
    if key in ADJUSTMENT_LABELS:
        return "库存明细", "库存调整", ADJUSTMENT_LABELS[key]
    if "." not in key:
        start = sheet["cumulative_from"] or sheet["as_of"]
        return "累计销售与退货", f"{start}—{sheet['as_of']}", _column_title(sheet, key)
    metric = key.removesuffix("Mom").split(".")[-1]
    metric_label = {"units": "销量", "returns": "退货", "net": "净销量"}[metric]
    period = "week" if key.startswith("day.") else key.split(".")[0]
    if period == "week":
        week_start = date.fromisoformat(sheet["periods"]["week"]["current"]["start"])

        def month_week(day: date, year: bool) -> str:
            number = (day.day - 1 + day.replace(day=1).weekday()) // 7 + 1
            return f"{str(day.year) + '年' if year else ''}{day.month}月第{number}周"

        week_end = date.fromisoformat(sheet["as_of"])
        heading = month_week(week_start, True)
        if week_start.month != week_end.month or week_start.year != week_end.year:
            heading += " / " + month_week(week_end, week_start.year != week_end.year)
        label = (
            "对比上周"
            if key.endswith("Mom")
            else key.split(".")[1][5:].replace("-", "/")
            if key.startswith("day.")
            else "本周净销量"
            if metric == "net"
            else "本周合计"
        )
        return f"{metric_label} {heading}", label, ""
    current = date.fromisoformat(sheet["periods"][period]["current"]["start"])

    def period_label(day: date) -> str:
        if period == "month":
            return f"{day.year}年{day.month}月"
        if period == "quarter":
            return f"{day.year}年第{(day.month - 1) // 3 + 1}季度"
        return f"{day.year}年"

    span = sheet["periods"][period]["previous" if ".previous." in key else "current"]
    heading = (
        {"month": "对比上月", "quarter": "对比上季度", "year": "对比上年"}[period]
        if key.endswith("Mom")
        else period_label(date.fromisoformat(span["start"]))
    )
    return (
        {"month": "月度", "quarter": "季度", "year": "年度"}[period]
        + " "
        + period_label(current),
        heading,
        metric_label + ("变化" if key.endswith("Mom") else ""),
    )


def sheet_workbook(sheet: dict[str, Any], query: dict[str, str]) -> bytes:
    keys = query.get(
        "columns",
        "production.pending,production.pendingReceipt,domestic,available,transit,sku,week.units,week.returns,month.net,quarter.net,year.net,dispatched,units,returns,net",
    ).split(",")
    if len(keys) > 150 or len(keys) != len(set(keys)) or "sku" not in keys:
        raise ApiError(422, "sheet_columns_invalid", "请提供有效且不重复的总表列。")
    headers = [_sheet_headers(sheet, key) for key in keys]
    for row in sheet["rows"]:
        for key in keys:
            if key != "sku":
                metric_quantity(row["values"], key)
    workbook = Workbook()
    ws = workbook.active
    ws.title = "库存变动总表"
    for level in range(3):
        ws.append([column[level] for column in headers])
    for level in range(3):
        start = 0
        while start < len(keys):
            end = start + 1
            while (
                end < len(keys)
                and headers[end][: level + 1] == headers[start][: level + 1]
                and headers[start][level]
            ):
                end += 1
            if end - start > 1:
                ws.merge_cells(
                    start_row=level + 1,
                    start_column=start + 1,
                    end_row=level + 1,
                    end_column=end,
                )
            start = end
    for index, column in enumerate(headers, 1):
        if keys[index - 1] == "sku":
            ws.merge_cells(start_row=1, end_row=3, start_column=index, end_column=index)
        elif not column[2]:
            ws.merge_cells(start_row=2, end_row=3, start_column=index, end_column=index)
        for level in range(1, 4):
            cell = ws.cell(level, index)
            cell.font = Font(bold=True, color="29445A")
            color = (
                "E8DEF3"
                if keys[index - 1] in PRODUCTION_KEYS
                else "DDEDE5"
                if keys[index - 1] in STOCK_KEYS
                else "F6E9C8"
                if "returns" in keys[index - 1]
                else "DCEAF7"
            )
            cell.fill = PatternFill("solid", fgColor=color)
            cell.alignment = Alignment(horizontal="center", vertical="center")
    by_style: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sheet["rows"]:
        by_style[row["style_id"]].append(row)
    sort_key = query.get("sort", "sku")
    direction = query.get("direction", "0")
    if direction not in {"-1", "0", "1"}:
        raise ApiError(422, "sheet_sort_invalid", "请选择有效排序方向。")

    def compare(a: dict[str, Any], b: dict[str, Any]) -> int:
        if sort_key == "sku" or direction == "0":
            left_name, right_name = str(a["sku"]), str(b["sku"])
            return (left_name > right_name) - (left_name < right_name)
        left, right = (
            metric_quantity(a["values"], sort_key)["value"],
            metric_quantity(b["values"], sort_key)["value"],
        )
        if left is None or right is None:
            return (left is None) - (right is None)
        return ((int(left) > int(right)) - (int(left) < int(right))) * int(direction)

    def grouped(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "sku": label,
            "values": {
                key: sum_quantities([r["values"][key] for r in rows])
                for key in rows[0]["values"]
            },
        }

    groups: list[tuple[dict[str, Any], list[dict[str, Any]]]] = [
        (grouped(rows[0]["style_code"], rows), rows) for rows in by_style.values()
    ]
    sort_value = cmp_to_key(compare)
    groups.sort(key=lambda group: sort_value(group[0]))
    style_order = (
        query.get("style_order", "").split(",") if query.get("style_order") else []
    )
    sku_order = query.get("sku_order", "").split(",") if query.get("sku_order") else []
    if style_order:
        if sorted(style_order) != sorted(by_style):
            raise ApiError(
                409, "sheet_refresh_required", "筛选款号已变化，请刷新后导出。"
            )
        groups.sort(key=lambda group: style_order.index(group[1][0]["style_id"]))
    if sku_order and sorted(sku_order) != sorted(
        row["sku_id"] for row in sheet["rows"]
    ):
        raise ApiError(409, "sheet_refresh_required", "筛选SKU已变化，请刷新后导出。")
    expanded = set(query.get("expanded_styles", "").split(","))

    def append(row: dict[str, Any], *, summary: bool, hidden: bool = False) -> None:
        values = [
            row["sku"] if key == "sku" else metric_quantity(row["values"], key)["value"]
            for key in keys
        ]
        ws.append(values)
        for index, key in enumerate(keys, 1):
            cell = ws.cell(ws.max_row, index)
            if key != "sku":
                item = metric_quantity(row["values"], key)
                value = item["value"]
                if value is not None and len(value.lstrip("-")) <= 15:
                    cell.value = int(value)
                else:
                    if value is None:
                        evidence = item.get("evidence")
                        if evidence and (
                            int(evidence["units"]) or _evidence_column_label(sheet, key)
                        ):
                            cell.value = (
                                int(evidence["units"])
                                if len(evidence["units"].lstrip("-")) <= 15
                                else evidence["units"]
                            )
                            cell.number_format = "#,##0;-#,##0;;@"
                        else:
                            cell.value = None
                    if not isinstance(cell.value, int):
                        cell.data_type = "s"
                cell.number_format = "#,##0;-#,##0;;@"
                if key.endswith("Mom"):
                    cell.number_format = '"↑ "#,##0;"↓ "#,##0;;@'
                if item["partial"] or item["value"] is None:
                    cell.comment = Comment(
                        str(STATES.get(item["state"], item["state"]))
                        + " "
                        + item.get("reason", ""),
                        "CLSEN",
                    )
            else:
                cell.data_type = "s"
            cell.alignment = Alignment(horizontal="center", vertical="center")
            if summary:
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="EEF2F7")
            if key == "available":
                alerts = row.get("alerts", [row.get("alert", {})])
                empty = sum(alert.get("level") == "empty" for alert in alerts)
                low = sum(alert.get("level") == "low" for alert in alerts)
                if not summary and (empty or low):
                    cell.font = Font(color="B03B3B" if empty else "AD6810")
            elif key.endswith("Mom") and item["value"] is not None:
                change = int(item["value"])
                tone = -change if "returns" in key else change
                cell.font = Font(
                    bold=summary,
                    color="287A50" if tone > 0 else "B03B3B" if tone < 0 else "526171",
                )
            elif (
                key.endswith("net")
                and item["value"] is not None
                and int(item["value"]) < 0
            ):
                cell.font = Font(bold=summary, color="B03B3B")
        if hidden:
            ws.row_dimensions[ws.max_row].hidden = True
            ws.row_dimensions[ws.max_row].outlineLevel = 1

    for summary, rows in groups:
        summary["alerts"] = [row["alert"] for row in rows]
        append(summary, summary=True)
        for row in (
            sorted(rows, key=lambda row: sku_order.index(row["sku_id"]))
            if sku_order
            else sorted(rows, key=cmp_to_key(compare))
        ):
            append(row, summary=False, hidden=row["style_id"] not in expanded)
    if sheet["rows"]:
        append(
            {
                "sku": "合计",
                "values": sheet["totals"],
                "alerts": [row["alert"] for row in sheet["rows"]],
            },
            summary=True,
        )
    ws.freeze_panes = f"{ws.cell(4, keys.index('sku') + 2).column_letter}4"
    for column in ws.columns:
        ws.column_dimensions[ws.cell(4, column[0].column).column_letter].width = 22
    notes = workbook.create_sheet("范围与缺数说明")
    for label, value in [
        ("用途", "汇总查看，不可直接回导入账"),
        ("应用版本", sheet["application_version"]),
        ("截止日", sheet["as_of"]),
        ("站点报告时区", sheet["reporting_timezone"]),
        ("读取版本", sheet["version"]),
        ("筛选", sheet["filter"]),
        ("范围", sheet["resolved_scope"]),
        *(
            [("资料核对来源", sheet["source_review"])]
            if sheet.get("source_review")
            else []
        ),
        ("目录", sheet["catalog_version"]),
        *(
            ([("在途期初来源", sheet["transit_opening"])])
            if sheet.get("transit_opening")
            else []
        ),
        ("发布与去重引用", sheet["report_provenance"]),
        ("覆盖", sheet["coverage"]),
        (
            "说明",
            "0留白；缺数以批注及下面逐SKU状态表示。净销量沿退货发生日完整性未定。",
        ),
        ("当前提醒设置", sheet["settings"]["sku_alert_settings"]),
    ]:
        notes.append(
            [
                label,
                json.dumps(value, ensure_ascii=False, default=str)
                if isinstance(value, (dict, list))
                else value,
            ]
        )
    states = workbook.create_sheet("SKU身份与状态")
    states.append(
        [
            "style_id",
            "sku_id",
            "SKU",
            "指标",
            "数量",
            "状态",
            "已知部分",
            "未知项",
            "原因",
            "资料数量",
            "资料口径",
        ]
    )
    for row in sheet["rows"]:
        for key in keys:
            if key == "sku":
                continue
            value = metric_quantity(row["values"], key)
            states.append(
                [
                    row["style_id"],
                    row["sku_id"],
                    row["sku"],
                    key,
                    value["value"],
                    value["state"],
                    value.get("known_units"),
                    value.get("unknown_count"),
                    value.get("reason"),
                    value.get("evidence", {}).get("units"),
                    value.get("evidence", {}).get("label"),
                ]
            )
    for page in [notes, states]:
        page.freeze_panes = "A2"
        for row in page:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
