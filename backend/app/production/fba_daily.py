"""Prepare published sales deductions and physical return updates."""

# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.catalog.normalization import seller_sku_match_v1


def report_projection(
    reports: list[dict[str, Any]],
    scope: dict[str, Any],
    identities: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Published sales deduct stock; accepted physical returns restore stock."""
    by_code = {
        seller_sku_match_v1(item["seller_sku"]).utf8: item
        for item in identities
        if str(item["scope_id"]) == str(scope["id"])
    }
    sales: dict[tuple[str, str], int] = defaultdict(int)
    sales_versions: dict[tuple[str, str], set[str]] = defaultdict(set)
    returns: dict[str, dict[str, Any]] = {}
    conflicting_returns: set[str] = set()
    issues = []
    report_ids = set()
    report_types: dict[str, set[str]] = defaultdict(set)
    report_dates = set()
    for row in reports:
        report_ids.add(str(row["version_id"]))
        report_types[row["report_type"]].add(str(row["version_id"]))
        report_dates.add(str(row["report_date"]))
        code = str(row["sku"])
        identity = by_code.get(seller_sku_match_v1(code).utf8)
        location = f"{row['report_date']} 第{row['source_row']}行"
        issue_context = {
            "seller_sku": code,
            "sku_id": str(identity["sku_id"]) if identity else None,
            "report_date": str(row["report_date"]),
            "source_row": row["source_row"],
            "report_version_id": str(row["version_id"]),
        }
        if identity is None:
            issues.append(
                issue_context
                | {
                    "code": "unmatched_product",
                    "message": "尚未匹配FBA商品",
                    "label": f"{location} {code} 尚未匹配FBA商品",
                }
            )
            continue
        if str(identity["tracked"]).lower() not in {"true", "1"}:
            issues.append(
                issue_context
                | {
                    "code": "not_tracked",
                    "message": "尚未纳入跟踪",
                    "label": f"{location} {code} 尚未纳入跟踪",
                }
            )
            continue
        sku = str(identity["sku_id"])
        if row["report_type"] == "business_report":
            amount = int(row["units_ordered"])
            if amount < 0:
                issues.append(
                    issue_context
                    | {
                        "code": "negative_sales",
                        "message": "下单数量不能为负数",
                        "label": f"{location} 下单数量不能为负数",
                    }
                )
                continue
            sales[str(row["report_date"]), sku] += amount
            sales_versions[str(row["report_date"]), sku].add(str(row["version_id"]))
            continue
        if str(row["status"]).strip().casefold() != "unit returned to inventory":
            issues.append(
                issue_context
                | {
                    "code": "return_status",
                    "message": "实物退回状态待核",
                    "label": f"{location} {code} 实物退回状态待核",
                }
            )
            continue
        has_manual_return = any(
            str(action["scope_id"]) == str(scope["id"])
            and action["kind"] == "RETURN"
            and action["status"] == "POSTED"
            and not action["payload"].get("report_return_key")
            and any(
                str(line["sku_id"]) == sku
                and line.get("customer_order_ref") == row["order_id"]
                for line in action["payload"]["lines"]
            )
            for action in actions
        )
        if has_manual_return:
            issues.append(
                issue_context
                | {
                    "code": "manual_return",
                    "message": "已有人工退回，需核对关联",
                    "label": f"{location} {code} 已有人工退回，请核对关联",
                }
            )
            continue
        if not row["license_plate_number"] or int(row["quantity"]) < 1:
            issues.append(
                issue_context
                | {
                    "code": "return_identity",
                    "message": "缺少有效退回数量或LPN",
                    "label": f"{location} {code} 缺少有效退回数量或LPN",
                }
            )
            continue
        if row["asin"] != identity["asin"] or (
            row["fnsku"] and row["fnsku"] != identity["fnsku"]
        ):
            issues.append(
                issue_context
                | {
                    "code": "platform_identity",
                    "message": "ASIN或FNSKU不一致",
                    "label": f"{location} {code} ASIN或FNSKU不一致",
                }
            )
            continue
        stamp = row["return_date"]
        if isinstance(stamp, str):
            stamp = datetime.fromisoformat(stamp)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        local = stamp.astimezone(ZoneInfo("America/Los_Angeles"))
        if local.date().isoformat() <= str(scope["cutoff_on"]):
            continue
        event = hashlib.sha256(
            json.dumps(
                [
                    row["order_id"],
                    sku,
                    row["license_plate_number"],
                    stamp.astimezone(UTC).isoformat(),
                ],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        if event in conflicting_returns:
            continue
        disposition = str(row["detailed_disposition"]).strip().upper()
        damaged = {
            "CUSTOMER_DAMAGED",
            "DEFECTIVE",
            "CARRIER_DAMAGED",
            "WAREHOUSE_DAMAGED",
            "DISTRIBUTOR_DAMAGED",
            "EXPIRED",
            "UNSELLABLE",
        }
        if disposition and disposition != "SELLABLE" and disposition not in damaged:
            issues.append(
                issue_context
                | {
                    "code": "return_disposition",
                    "message": "实物退回处置待核",
                    "label": f"{location} {code} 处置结果待核 {disposition}",
                }
            )
            continue
        primary_reasons = {
            "WAREHOUSE_DAMAGED",
            "CARRIER_DAMAGED",
            "DEFECTIVE",
            "CUSTOMER_DAMAGED",
        }
        reason_code = "UNCLASSIFIED"
        if disposition in damaged:
            reason_code = disposition if disposition in primary_reasons else "OTHER"
        item = {
            "sku_id": sku,
            "units": str(row["quantity"]),
            "quality": "DEFECTIVE" if disposition in damaged else "QUALIFIED",
            "reason_code": reason_code,
            "raw_disposition": disposition,
            "customer_order_ref": row["order_id"],
            "source_event_ref": "report-return:" + event,
            "occurred_at": local.isoformat(),
            "report_version_id": str(row["version_id"]),
        }
        prior = returns.get(event)
        if prior and any(
            prior[k] != item[k]
            for k in ("units", "quality", "reason_code", "raw_disposition")
        ):
            issues.append(
                issue_context
                | {
                    "code": "return_conflict",
                    "message": "同一退回存在不同数量或状态",
                    "label": f"{location} {code} 同一退回存在不同数量或状态",
                }
            )
            returns.pop(event)
            conflicting_returns.add(event)
            continue
        returns[event] = item
    sales_updates = []
    for (day, sku), amount in sorted(sales.items()):
        stamp = datetime.fromisoformat(day + "T23:59:59").replace(
            tzinfo=ZoneInfo("America/Los_Angeles")
        )
        sales_updates.append(
            {
                "sku_id": sku,
                "report_units": str(amount),
                "business_date": day,
                "occurred_at": stamp.isoformat(),
                "report_version_ids": sorted(sales_versions[day, sku]),
            }
        )
    manual: dict[tuple[str, str], int] = defaultdict(int)
    automatic: dict[tuple[str, str], int] = defaultdict(int)
    for action in actions:
        if (
            str(action["scope_id"]) != str(scope["id"])
            or action["status"] != "POSTED"
            or action["kind"] != "FULFILLMENT"
        ):
            continue
        day = (
            datetime.fromisoformat(action["occurred_at"])
            .astimezone(ZoneInfo("America/Los_Angeles"))
            .date()
            .isoformat()
        )
        target = automatic if action["payload"].get("report_sales_key") else manual
        for line in action["payload"]["lines"]:
            target[day, str(line["sku_id"])] += int(line["units"])
    sync_issues = []
    labels = {str(item["sku_id"]): item["seller_sku"] for item in by_code.values()}
    for key in sorted(sales.keys() | automatic.keys()):
        if key not in sales and issues:
            continue
        expected = max(0, sales.get(key, 0) - manual[key])
        if automatic[key] != expected:
            sync_issues.append(
                {
                    "code": "sales_pending",
                    "message": "销售库存待更新",
                    "sku_id": key[1],
                    "seller_sku": labels.get(key[1], key[1]),
                    "report_date": key[0],
                    "label": (
                        f"{key[0]} {labels.get(key[1], key[1])}销售库存尚未更新，"
                        "请核对可售数量后重试库存更新"
                    ),
                }
            )
    posted_returns = {
        action["payload"]["report_return_key"]: action["payload"]["lines"][0]
        for action in actions
        if str(action["scope_id"]) == str(scope["id"])
        and action["kind"] == "RETURN"
        and action["status"] == "POSTED"
        and action["payload"].get("report_return_key")
    }
    expected_returns = {item["source_event_ref"]: item for item in returns.values()}
    for key in posted_returns.keys() | expected_returns.keys():
        if key not in expected_returns and issues:
            continue
        expected_return, posted = expected_returns.get(key), posted_returns.get(key)
        if (
            expected_return is None
            or posted is None
            or any(
                str(expected_return[field]) != str(posted[field])
                for field in ("units", "quality")
            )
        ):
            item = (
                expected_return if expected_return is not None else posted_returns[key]
            )
            sync_issues.append(
                {
                    "code": "return_pending",
                    "message": "退货库存待更新",
                    "sku_id": str(item["sku_id"]),
                    "seller_sku": labels.get(str(item["sku_id"]), str(item["sku_id"])),
                    "label": (
                        f"{labels.get(str(item['sku_id']), str(item['sku_id']))}"
                        "退货库存尚未更新，请核对库存后重试"
                    ),
                }
            )
    return {
        "sales_units": str(sum(sales.values())),
        "sales": sales_updates,
        "sync_issues": sync_issues,
        "returns": list(returns.values()),
        "issues": issues,
        "report_version_ids": sorted(report_ids),
        "report_count": len(report_ids),
        "business_report_count": len(report_types["business_report"]),
        "return_report_count": len(report_types["return_report"]),
        "latest_report_on": max(report_dates) if report_dates else None,
        "return_units": str(sum(int(item["units"]) for item in returns.values())),
    }


def load_reports(
    connection: Connection, site: int, scope: dict[str, Any]
) -> list[dict[str, Any]]:
    common = """
        JOIN version_rows vr ON vr.version_id=v.id AND vr.row_state='active'
        JOIN report_dataset_scope_assignments a ON a.dataset_id=d.id
          AND a.site_id=d.site_id
        WHERE d.site_id=:site AND a.report_source_scope_id=:scope
          AND d.report_date>:cutoff
    """
    args = {
        "site": site,
        "scope": scope["report_source_scope_id"],
        "cutoff": scope["cutoff_on"],
    }
    business = (
        connection.execute(
            sa.text(
                """
        SELECT v.id version_id,d.report_date,d.report_type,vr.row_ordinal source_row,
               b.sku,b.units_ordered
        FROM daily_datasets d JOIN dataset_publications p ON p.dataset_id=d.id
        JOIN dataset_versions v ON v.id=p.version_id
        JOIN business_report_rows b ON b.version_id=v.id
    """
                + common.replace(
                    "JOIN version_rows vr ON vr.version_id=v.id",
                    "JOIN version_rows vr ON vr.id=b.version_row_id "
                    "AND vr.version_id=v.id",
                )
                + " AND d.report_type='business_report'"
            ),
            args,
        )
        .mappings()
        .all()
    )
    returned = (
        connection.execute(
            sa.text(
                """
        SELECT v.id version_id,d.report_date,d.report_type,vr.row_ordinal source_row,
               r.sku,r.return_date,r.order_id,r.asin,r.fnsku,r.quantity,
               r.detailed_disposition,r.status,r.license_plate_number
        FROM daily_datasets d JOIN dataset_publications p ON p.dataset_id=d.id
        JOIN dataset_versions v ON v.id=p.version_id
        JOIN return_report_rows r ON r.version_id=v.id
    """
                + common.replace(
                    "JOIN version_rows vr ON vr.version_id=v.id",
                    "JOIN version_rows vr ON vr.id=r.version_row_id "
                    "AND vr.version_id=v.id",
                )
                + " AND d.report_type='return_report' ORDER BY d.report_date,v.id,vr.id"
            ),
            args,
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in [*business, *returned]]
