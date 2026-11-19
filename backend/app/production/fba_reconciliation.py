"""Read-only reconstruction from confirmed FBA events, never an inventory writer."""

# ruff: noqa: RUF001 -- Chinese export labels.
from datetime import datetime
from io import BytesIO
from typing import Any, cast
from zoneinfo import ZoneInfo

from openpyxl import Workbook  # type: ignore[import-untyped]

from app.api.errors import ApiError


def receipt_before(event: dict[str, Any], cutoff: datetime) -> bool:
    if event.get("occurred_at"):
        return datetime.fromisoformat(event["occurred_at"]) <= cutoff
    return (
        cast(str, event["business_date"])
        < cutoff.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
    )


def inventory_view(
    state: dict[str, Any], scope_id: str, view: dict[str, Any]
) -> dict[str, Any]:
    """Read-only stock presentation; report links never create events."""
    identities = [i for i in state["identities"] if str(i["scope_id"]) == scope_id]
    scope = next(s for s in state["scopes"] if str(s["id"]) == scope_id)
    movements: list[dict[str, Any]] = []
    for event in state["events"]:
        if str(event["scope_id"]) == scope_id:
            movements.append(
                {
                    "id": f"receipt:{event['id']}",
                    "sku_id": str(event["sku_id"]),
                    "kind": "RECEIPT",
                    "units": str(event["units"]),
                    "occurred_at": event.get("occurred_at") or event["occurred_local"],
                    "reference": event["event_key"],
                    "reason": event["evidence"],
                    "batch_id": str(event["batch_id"]),
                    "quality": event.get("quality", "QUALIFIED"),
                    "report_version_ids": [],
                }
            )
    for action in state["actions"]:
        if (
            str(action["scope_id"]) != scope_id
            or action["status"] != "POSTED"
            or action["kind"] == "OBSERVATION"
        ):
            continue
        for index, line in enumerate(action["payload"]["lines"]):
            units = int(line["units"]) * (-1 if action["kind"] == "FULFILLMENT" else 1)
            if not units:
                continue
            movements.append(
                {
                    "id": f"action:{action['id']}:{index}",
                    "sku_id": str(line["sku_id"]),
                    "kind": action["kind"],
                    "units": str(units),
                    "occurred_at": action["payload"]
                    .get("report_sales", {})
                    .get("occurred_at", action["occurred_at"]),
                    "reference": action["event_key"],
                    "reason": action["payload"]["reason"],
                    "batch_id": None,
                    "quality": line.get("quality"),
                    "report_version_ids": action["payload"].get(
                        "report_version_ids", []
                    ),
                }
            )

    for event in state.get("stocktakes", []):
        if str(event["scope_id"]) != scope_id or not int(event["units"]):
            continue
        movements.append(
            {
                "id": f"count:{event['id']}",
                "sku_id": str(event["sku_id"]),
                "kind": "COUNT",
                "units": str(event["units"]),
                "occurred_at": datetime.fromisoformat(event["business_date"])
                .replace(tzinfo=ZoneInfo("America/Los_Angeles"))
                .isoformat(),
                "time_precision": "date",
                "reference": f"COUNT-{event['document_id']}",
                "reason": event["reason"],
                "batch_id": None,
                "quality": event["quality"],
                "report_version_ids": [],
            }
        )

    def movement_order(movement: dict[str, Any]) -> str:
        value = datetime.fromisoformat(movement["occurred_at"])
        if value.tzinfo is not None:
            value = value.astimezone(ZoneInfo("America/Los_Angeles"))
        return value.isoformat()

    movements.sort(key=movement_order, reverse=True)
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for identity in identities:
        sku = str(identity["sku_id"])
        fact = next(r for r in view["rows"] if r["sku_id"] == sku)
        stock = next(
            i
            for i in state["stock"]["items"]
            if str(i["sku_id"]) == sku and str(i["owner_id"]) == str(scope["owner_id"])
        )
        items.append(
            {
                "sku_id": sku,
                "style_id": str(identity.get("style_id") or f"sku:{sku}"),
                "seller_sku": identity["seller_sku"],
                "on_hand": fact["on_hand"],
                "available": stock["free_available_units"],
                "received": fact["receipt_net"],
                "fulfilled": fact["fulfilled"],
                "counted": fact["counted"],
                "returned": fact["returned"],
            }
        )
        if fact["stock_matches"] is not True:
            issues.append(
                {
                    "id": f"stock:{sku}",
                    "sku_id": sku,
                    "label": "库存数量待核",
                    "view": "history",
                }
            )
        if any(
            identity.get(k) is None or int(identity[k]) > 0
            for k in ("pending_units", "unassessed_units")
        ):
            issues.append(
                {
                    "id": f"quality:{sku}",
                    "sku_id": sku,
                    "label": "库存质量待核",
                    "view": "returns",
                }
            )
        observation = fact["observation"]
        if fact.get("observation_precision_pending"):
            issues.append(
                {
                    "id": f"precision:{sku}",
                    "sku_id": sku,
                    "label": "当日接收仅记录日期，平台时点对账待核",
                    "view": "observation",
                }
            )
        if observation and any(
            int(observation[k]) != 0
            for k in (
                "sellable_difference",
                "unsellable_difference",
                "reserved_difference",
                "held_difference",
            )
        ):
            issues.append(
                {
                    "id": f"observation:{sku}",
                    "sku_id": sku,
                    "label": "平台观察有差异",
                    "view": "observation",
                }
            )
    for batch in state.get("batches", []):
        if str(batch["scope_id"]) == scope_id and batch["status"] in (
            "DRAFT",
            "PARTIAL",
        ):
            issues.append(
                {
                    "id": f"batch:{batch['id']}",
                    "sku_id": None,
                    "label": "接收草稿待处理"
                    if batch.get("source_kind") == "MANUAL"
                    else "接收报告待处理",
                    "view": "receipts",
                    "batch_id": str(batch["id"]),
                }
            )

    def total(rows: list[dict[str, Any]], field: str) -> str | None:
        return (
            None
            if any(r[field] is None for r in rows)
            else str(sum(int(r[field]) for r in rows))
        )

    groups = []
    for style in dict.fromkeys(i["style_id"] for i in items):
        variants = [i for i in items if i["style_id"] == style]
        groups.append(
            {
                "style_id": style,
                "on_hand": total(variants, "on_hand"),
                "items": variants,
            }
        )
    return {
        "on_hand": total(items, "on_hand"),
        "available": total(items, "available"),
        "latest_movement_at": movements[0]["occurred_at"] if movements else None,
        "groups": groups,
        "movements": movements,
        "issues": issues,
        "stock_effect": False,
    }


def reconcile(state: dict[str, Any], scope_id: str) -> dict[str, Any]:
    scope = next((s for s in state["scopes"] if str(s["id"]) == scope_id), None)
    if scope is None:
        raise ApiError(404, "fba_scope_conflict", "当前账号范围不存在。")
    identities = [i for i in state["identities"] if str(i["scope_id"]) == scope_id]
    events = [e for e in state["events"] if str(e["scope_id"]) == scope_id]
    actions = [
        a
        for a in state["actions"]
        if str(a["scope_id"]) == scope_id and a["status"] == "POSTED"
    ]
    observations = sorted(
        (a for a in actions if a["kind"] == "OBSERVATION"),
        key=lambda a: (datetime.fromisoformat(a["occurred_at"]), int(a["id"])),
        reverse=True,
    )
    rows = []
    for identity in identities:
        sku = str(identity["sku_id"])
        stock = next(
            i
            for i in state["stock"]["items"]
            if str(i["sku_id"]) == sku and str(i["owner_id"]) == str(scope["owner_id"])
        )
        receipt = sum(int(e["units"]) for e in events if str(e["sku_id"]) == sku)
        lines = [
            (a, line)
            for a in actions
            for line in a["payload"]["lines"]
            if str(line["sku_id"]) == sku
        ]
        fulfilled = sum(
            int(line["units"]) for a, line in lines if a["kind"] == "FULFILLMENT"
        )
        returned = sum(int(line["units"]) for a, line in lines if a["kind"] == "RETURN")
        counts = [
            event
            for event in state.get("stocktakes", [])
            if str(event["scope_id"]) == scope_id and str(event["sku_id"]) == sku
        ]
        counted = sum(int(event["units"]) for event in counts)
        expected = receipt - fulfilled + returned + counted
        observation = next(
            (
                a
                for a in observations
                if any(str(line["sku_id"]) == sku for line in a["payload"]["lines"])
            ),
            None,
        )
        comparison = None
        precision_pending = observation is not None and any(
            str(event["sku_id"]) == sku
            and not event.get("occurred_at")
            and event["business_date"]
            == datetime.fromisoformat(observation["occurred_at"])
            .astimezone(ZoneInfo("America/Los_Angeles"))
            .date()
            .isoformat()
            for event in events
        )
        if observation is not None:
            observed_date = (
                datetime.fromisoformat(observation["occurred_at"])
                .astimezone(ZoneInfo("America/Los_Angeles"))
                .date()
                .isoformat()
            )
            precision_pending = precision_pending or any(
                cast(str, event["business_date"]) == observed_date for event in counts
            )
        if observation is not None and not precision_pending:
            cutoff = datetime.fromisoformat(observation["occurred_at"])

            observed = next(
                line
                for line in observation["payload"]["lines"]
                if str(line["sku_id"]) == sku
            )
            qualified = sum(
                int(e["units"])
                for e in events
                if str(e["sku_id"]) == sku
                and e.get("quality", "QUALIFIED") == "QUALIFIED"
                and receipt_before(e, cutoff)
            )
            unsellable = sum(
                int(e["units"])
                for e in events
                if str(e["sku_id"]) == sku
                and e.get("quality") == "DEFECTIVE"
                and receipt_before(e, cutoff)
            )
            pending = sum(
                int(e["units"])
                for e in events
                if str(e["sku_id"]) == sku
                and e.get("quality") == "PENDING"
                and receipt_before(e, cutoff)
            )
            for event in state.get("quality_events", []):
                if (
                    str(event["scope_id"]) != scope_id
                    or str(event["sku_id"]) != sku
                    or datetime.fromisoformat(event["occurred_at"]) > cutoff
                ):
                    continue
                if event["quality"] == "QUALIFIED":
                    qualified += int(event["units"])
                elif event["quality"] == "DEFECTIVE":
                    unsellable += int(event["units"])
                else:
                    pending += int(event["units"])
            qualified += sum(
                int(event["units"])
                for event in counts
                if event["business_date"]
                < cutoff.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
            )
            for action, line in lines:
                if datetime.fromisoformat(action["occurred_at"]) > cutoff:
                    continue
                if action["kind"] == "FULFILLMENT":
                    qualified -= int(line["units"])
                elif action["kind"] == "RETURN":
                    quality = line["quality"]
                    if quality == "QUALIFIED":
                        qualified += int(line["units"])
                    elif quality == "DEFECTIVE":
                        unsellable += int(line["units"])
                    else:
                        pending += int(line["units"])
            comparison = {
                "occurred_at": observation["occurred_at"],
                "source": observation["payload"]["reason"],
                "book_sellable": str(qualified),
                "book_unsellable": str(unsellable),
                "book_pending": str(pending),
                "observed": {
                    k: str(observed[k])
                    for k in ("sellable", "reserved", "unsellable", "held")
                },
                "sellable_difference": str(int(observed["sellable"]) - qualified),
                "unsellable_difference": str(int(observed["unsellable"]) - unsellable),
                "reserved_difference": str(observed["reserved"]),
                "held_difference": str(observed["held"]),
                "basis": "当前有效事实按观察时点重建；观察不入账",
            }
        rows.append(
            {
                "sku_id": sku,
                "seller_sku": identity["seller_sku"],
                "receipt_net": str(receipt),
                "fulfilled": str(fulfilled),
                "returned": str(returned),
                "counted": str(counted),
                "expected_on_hand": str(expected),
                "on_hand": stock["on_hand_units"],
                "stock_matches": None
                if stock["on_hand_units"] is None
                else expected == int(stock["on_hand_units"]),
                "observation": comparison,
                "observation_precision_pending": precision_pending,
            }
        )
    sources = [
        s for s in state.get("shipment_totals", []) if str(s["scope_id"]) == scope_id
    ]
    return {
        "scope_id": scope_id,
        "rows": rows,
        "unreceived_units": str(
            sum(int(s["shipped_units"]) - int(s["received_units"]) for s in sources)
        )
        if sources
        else None,
        "platform_observation_is_stock_fact": False,
    }


def export_reconciliation(state: dict[str, Any], scope_id: str) -> bytes:
    view = reconcile(state, scope_id)
    scope = next(s for s in state["scopes"] if str(s["id"]) == scope_id)
    book = Workbook()
    info = book.active
    info.title = "范围与口径"
    for pair in [
        ("模板版本", "fba_reconciliation_view_v2"),
        ("用途", "汇总查看，不可直接作为业务明细导入"),
        ("卖家账号", scope["seller_account"]),
        ("站点", scope["marketplace"]),
        ("货权", scope["owner_id"]),
        ("目录版本", scope["catalog_version"]),
        ("期初截止", scope["cutoff_on"]),
        ("期初依据", scope["opening_basis"]),
        ("资料性质", "SIMULATED" if scope["simulated"] else "已确认事件"),
        (
            "未收待核",
            view["unreceived_units"]
            if view["unreceived_units"] is not None
            else "未知",
        ),
        ("快照处理", "只读对比，不叠加入账"),
    ]:
        info.append(pair)
    balances = book.create_sheet("库存对账")
    balances.append(
        (
            "稳定SKUID",
            "MSKU",
            "ASIN",
            "FNSKU",
            "跟踪",
            "净接收件数",
            "销售出库件数",
            "实物退回件数",
            "盘点调整件数",
            "在库件数",
            "当前可发件数",
            "可售件数",
            "不可售件数",
            "待检件数",
            "预留件数",
            "冻结件数",
            "事件对账",
            "观察时点",
            "观察可售",
            "观察不可售",
            "可售差额",
            "不可售差额",
        )
    )
    for row in view["rows"]:
        identity = next(
            i
            for i in state["identities"]
            if str(i["scope_id"]) == scope_id and str(i["sku_id"]) == row["sku_id"]
        )
        stock = next(
            i
            for i in state["stock"]["items"]
            if str(i["sku_id"]) == row["sku_id"]
            and str(i["owner_id"]) == str(scope["owner_id"])
        )
        observation = row["observation"]
        balances.append(
            (
                row["sku_id"],
                identity["seller_sku"],
                identity["asin"],
                identity["fnsku"],
                "已跟踪" if identity["tracked"] else "未跟踪",
                row["receipt_net"],
                row["fulfilled"],
                row["returned"],
                row["counted"],
                stock["on_hand_units"],
                stock["free_available_units"],
                identity["sellable"],
                identity["unsellable"],
                identity["pending_units"],
                stock["reserved_units"],
                stock["held_units"],
                "未知"
                if row["stock_matches"] is None
                else "一致"
                if row["stock_matches"]
                else "有差异",
                observation["occurred_at"] if observation else "未知",
                observation["observed"]["sellable"] if observation else "未知",
                observation["observed"]["unsellable"] if observation else "未知",
                observation["sellable_difference"] if observation else "未知",
                observation["unsellable_difference"] if observation else "未知",
            )
        )
    events = book.create_sheet("接收事件")
    events.append(
        (
            "事件ID",
            "人工核对引用",
            "稳定SKUID",
            "原件批次",
            "原表行",
            "带符号件数",
            "原发生时间",
            "FC来源码",
            "更正原事件",
            "依据",
            "库存状态",
        )
    )
    for e in state["events"]:
        if str(e["scope_id"]) == scope_id:
            events.append(
                (
                    e["id"],
                    e["event_key"],
                    e["sku_id"],
                    e["batch_id"],
                    e["source_row"],
                    e["units"],
                    e["occurred_local"],
                    e["fulfillment_center"],
                    e["correction_of"],
                    e["evidence"],
                    e.get("quality", "QUALIFIED"),
                )
            )
    physical = book.create_sheet("履约与实物退回")
    physical.append(
        (
            "批次引用",
            "类型",
            "状态",
            "发生时间UTC",
            "稳定SKUID",
            "件数",
            "质量",
            "来源事件引用",
            "客户订单引用",
            "关联报表版本",
            "依据",
        )
    )
    for action in state["actions"]:
        if str(action["scope_id"]) == scope_id and action["kind"] != "OBSERVATION":
            for line in action["payload"]["lines"]:
                physical.append(
                    (
                        action["event_key"],
                        action["kind"],
                        action["status"],
                        action["occurred_at"],
                        line["sku_id"],
                        line["units"],
                        line.get("quality", "QUALIFIED"),
                        line.get("source_event_ref", "未知"),
                        line.get(
                            "customer_order_ref",
                            "不适用"
                            if action["payload"].get("report_sales_key")
                            else "未知",
                        ),
                        ",".join(
                            str(i)
                            for i in action["payload"].get("report_version_ids", [])
                        ),
                        action["payload"]["reason"],
                    )
                )
    counts = book.create_sheet("盘点调整")
    counts.append(
        ("事件ID", "盘点单", "稳定SKUID", "盘点日期", "库存状态", "调整件数", "依据")
    )
    for event in state.get("stocktakes", []):
        if str(event["scope_id"]) == scope_id:
            counts.append(
                tuple(
                    event[key]
                    for key in (
                        "id",
                        "document_id",
                        "sku_id",
                        "business_date",
                        "quality",
                        "units",
                        "reason",
                    )
                )
            )
    for sheet in book:
        sheet.freeze_panes = "A2"
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 24
            for cell in column:
                if cell.value is not None:
                    cell.value = str(cell.value)
                    cell.data_type = "s"
                    cell.number_format = "@"
    out = BytesIO()
    book.save(out)
    book.close()
    return out.getvalue()
