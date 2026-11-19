# ruff: noqa: RUF001
"""Local report-backed transit opening; existing transactions keep all writers."""

from __future__ import annotations

import csv
import hashlib
import json
from copy import deepcopy
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Any

from app.api.errors import ApiError
from app.catalog.normalization import seller_sku_match_v1


def configured_transit_scope(settings: Any) -> dict[str, Any] | None:
    if not settings.production_inventory_source_root:
        return None
    path = Path(settings.production_inventory_source_root) / "fba-transit-opening.json"
    return json.loads(path.read_bytes())["scope"] if path.is_file() else None


def load_transit_opening(
    settings: Any,
    context: Any,
    engine: Any,
    catalog: dict[str, Any],
    scope: dict[str, Any],
) -> dict[str, Any] | None:
    if not settings.production_inventory_source_root:
        return None
    root = Path(settings.production_inventory_source_root)
    path = root / "fba-transit-opening.json"
    if not path.is_file():
        return None
    metadata = path.read_bytes()
    source = json.loads(metadata)
    if (
        source.get("schema") != "fba-transit-opening-v1"
        or source.get("database") != engine.url.database
        or not str(engine.url.database).startswith("clsen_data_test_")
        or str(source.get("site_id")) != str(context.site_id)
    ):
        raise ApiError(
            409, "transit_opening_scope_invalid", "在途期初与当前本地站点不一致。"
        )
    if any(
        str(source["scope"][key]) != str(scope[key])
        for key in ("id", "warehouse_id", "owner_id", "report_source_scope_id")
    ):
        return None
    filename = source["source_filename"]
    if Path(filename).name != filename:
        raise ApiError(
            422, "transit_opening_source_invalid", "在途期初来源文件名无效。"
        )
    raw = (root / filename).read_bytes()
    if hashlib.sha256(raw).hexdigest() != source["source_sha256"]:
        raise ApiError(
            409, "transit_opening_source_changed", "在途期初原表已变化，请重新核对。"
        )
    snapshot = date.fromisoformat(source["snapshot_on"])
    mappings = {
        seller_sku_match_v1(item["seller_sku"]).utf8: str(item["sku_id"])
        for item in source["identities"]
    }
    if len(mappings) != len(source["identities"]):
        raise ApiError(
            409, "transit_opening_identity_invalid", "在途期初商品身份重复。"
        )
    rows, seen = [], set()
    for line_number, line in enumerate(
        csv.DictReader(StringIO(raw.decode("utf-8-sig"))), 2
    ):
        if line["snapshot-date"] != snapshot.isoformat():
            raise ApiError(
                409, "transit_opening_date_invalid", "在途期初原表日期不一致。"
            )
        value = line["inbound-shipped"]
        if not value.isascii() or not value.isdecimal() or len(value) > 18:
            raise ApiError(
                422, "transit_opening_quantity_invalid", "在途期初数量须为非负整数。"
            )
        if not int(value):
            continue
        match = seller_sku_match_v1(line["sku"]).utf8
        sku = mappings.get(match)
        identity = catalog.get(sku or "")
        if (
            identity is None
            or identity.get("status") != "active"
            or not identity.get("code")
            or seller_sku_match_v1(identity["code"]).utf8 != match
            or sku in seen
        ):
            raise ApiError(
                409,
                "transit_opening_identity_invalid",
                "在途期初商品与当前店铺目录不一致。",
            )
        seen.add(sku)
        rows.append(
            {
                "sku_id": sku,
                "sku_label": identity["code"],
                "style_code": identity["style_code"],
                "units": str(int(value)),
                "source_row": str(line_number),
                "snapshot_on": snapshot.isoformat(),
                "source_filename": filename,
            }
        )
    if seen != set(mappings.values()):
        raise ApiError(
            409,
            "transit_opening_identity_invalid",
            "在途期初映射与原表非零规格不一致。",
        )
    return {
        **source,
        "rows": rows,
        "digest": hashlib.sha256(metadata + raw).hexdigest(),
    }


def opening_records(
    opening: dict[str, Any] | None, as_of: date
) -> list[dict[str, Any]]:
    if opening is None or as_of < date.fromisoformat(opening["snapshot_on"]):
        return []
    return [
        {
            **row,
            "source_kind": "TRANSIT_OPENING",
            "source_version": opening["digest"],
            "business_number": "平台在途期初",
            "business_date": row["snapshot_on"],
            "source_line_id": row["source_row"],
            "actual_units": None,
            "received_units": None,
            "settled_units": None,
            "remaining_units": row["units"],
            "transport_status": "平台已发",
            "revision": opening["digest"],
        }
        for row in opening["rows"]
    ]


def merge_transit_view(
    result: dict[str, Any],
    opening: dict[str, Any] | None,
    resource: str,
    query: dict[str, str],
    as_of: date,
) -> dict[str, Any]:
    rows = opening_records(opening, as_of)
    if not rows or opening is None:
        return result
    scope = opening["scope"]
    if (query.get("owner_id") and query["owner_id"] != str(scope["owner_id"])) or (
        query.get("node") not in {None, "", "IN_TRANSIT", "DISPATCHED"}
    ):
        return result
    if resource == "warehouse-transit" and (
        query.get("warehouse_id") != str(scope["warehouse_id"])
        or query.get("direction", "incoming") != "incoming"
    ):
        return result
    if resource != "transport-summary" and query.get("page", "1") != "1":
        return result
    rows = [
        row
        for row in rows
        if (not query.get("sku_id") or query["sku_id"] == row["sku_id"])
        and (not query.get("q") or query["q"].casefold() in row["sku_label"].casefold())
    ]
    updated = deepcopy(result)
    updated["opening_balances"] = rows
    updated["opening_version"] = opening["digest"]
    updated["opening_scope"] = {
        "warehouse_id": str(scope["warehouse_id"]),
        "owner_id": str(scope["owner_id"]),
    }
    if resource == "transport-summary":
        by_sku = {str(row["sku_id"]): row for row in updated["items"]}
        for row in rows:
            item = by_sku.get(row["sku_id"])
            if item is None:
                item = {
                    "sku_id": row["sku_id"],
                    "in_transit_units": "0",
                    "arrival_check_units": "0",
                    "exception_units": "0",
                    "unregistered_units": "0",
                    "unknown_sources": 0,
                }
                updated["items"].append(item)
                by_sku[row["sku_id"]] = item
            if item["in_transit_units"] is not None:
                item["in_transit_units"] = str(
                    int(item["in_transit_units"]) + int(row["units"])
                )
        current = updated["totals"]["in_transit_units"]
        if current is not None:
            updated["totals"]["in_transit_units"] = str(
                int(current) + sum(int(row["units"]) for row in rows)
            )
    return updated
