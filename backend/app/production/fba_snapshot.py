"""Report-backed FBA opening; original bytes remain actor and shop scoped."""

# ruff: noqa: RUF001
import csv
import re
from datetime import date
from io import StringIO
from typing import Any

from app.api.errors import ApiError
from app.catalog.normalization import seller_sku_match_v1


def parse_snapshot(raw: bytes, products: dict[str, Any]) -> dict[str, Any]:
    if not raw or len(raw) > 2_000_000:
        raise ApiError(422, "fba_snapshot_invalid", "请选择2MB以内的库存CSV。")
    identities = products["identities"]
    by_code = {seller_sku_match_v1(p["seller_sku"]).utf8: p for p in identities}
    if len(by_code) != len(identities):
        raise ApiError(409, "fba_snapshot_identity", "当前店铺商品编码不唯一。")
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_fnskus: set[str] = set()
    dates: set[str] = set()
    try:
        reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")), strict=True)
        required = {
            "snapshot-date",
            "sku",
            "fnsku",
            "asin",
            "available",
            "inbound-shipped",
        }
        if not required.issubset(reader.fieldnames or []) or any(
            (reader.fieldnames or []).count(k) != 1 for k in required
        ):
            raise ValueError("headers")
        for row in reader:
            location = f"CSV第{reader.line_num}行"
            product = by_code.get(seller_sku_match_v1(row.get("sku", "")).utf8)
            if (
                not product
                and row.get("available") == "0"
                and row.get("inbound-shipped") == "0"
            ):
                excluded.append(
                    {
                        "source_row": str(reader.line_num),
                        "seller_sku": row.get("sku", ""),
                        "reason": "当前店铺未建档；零可售、零在途，保留原表隔离",
                    }
                )
                dates.add(date.fromisoformat(row["snapshot-date"]).isoformat())
                continue
            if (
                None in row
                or not product
                or product["sku_id"] in seen
                or row["fnsku"] in seen_fnskus
                or any(row[k] != product[k] for k in ("asin", "fnsku"))
            ):
                raise ApiError(
                    422,
                    "fba_snapshot_identity",
                    location + "：商品不属于当前店铺、重复或平台编码不符。",
                )
            day = date.fromisoformat(row["snapshot-date"]).isoformat()
            if any(
                not re.fullmatch(r"0|[1-9][0-9]{0,8}", row[k])
                for k in ("available", "inbound-shipped")
            ):
                raise ApiError(
                    422,
                    "fba_snapshot_quantity",
                    location + "：可售和已发在途须为非负整数。",
                )
            dates.add(day)
            seen.add(product["sku_id"])
            seen_fnskus.add(row["fnsku"])
            rows.append(
                {
                    "sku_id": product["sku_id"],
                    "seller_sku": product["seller_sku"],
                    "units": row["available"],
                    "transit_units": row["inbound-shipped"],
                    "asin": row["asin"],
                    "fnsku": row["fnsku"],
                    "source_row": str(reader.line_num),
                }
            )
            if len(rows) > 5000:
                raise ValueError("rows")
        if not rows or len(dates) != 1:
            raise ValueError("dates")
    except (UnicodeError, csv.Error, ValueError, KeyError, TypeError) as error:
        raise ApiError(
            422, "fba_snapshot_invalid", "请上传同一日期的亚马逊物流库存原始UTF-8 CSV。"
        ) from error
    return {
        "snapshot_on": next(iter(dates)),
        "rows": rows,
        "identities": identities,
        "catalog_version": products["catalog_version"],
        "available_units": str(sum(int(r["units"]) for r in rows)),
        "transit_units": str(sum(int(r["transit_units"]) for r in rows)),
        "missing_skus": len(identities) - len(seen),
        "excluded_rows": excluded,
    }


def snapshot_products(
    raw: bytes, products: dict[str, Any], catalog: dict[str, Any]
) -> dict[str, Any]:
    """Complete missing platform codes from the report within existing membership."""
    if not raw or len(raw) > 2_000_000:
        raise ApiError(422, "fba_snapshot_invalid", "请选择2MB以内的库存CSV。")
    result = {
        **products,
        "identities": list(products["identities"]),
        "source_identity_sku_ids": [],
    }
    ready = {str(p["sku_id"]) for p in result["identities"]}
    codes = {
        p["code"]: p
        for p in catalog.values()
        if p.get("status") == "active" and p.get("code")
    }
    try:
        for n, r in enumerate(
            csv.DictReader(StringIO(raw.decode("utf-8-sig")), strict=True), 2
        ):
            p = codes.get(r.get("sku", ""))
            if (
                p
                and str(p["sku_id"]) not in ready
                and all(
                    re.fullmatch(r"[A-Z0-9]{10}", r.get(k, ""))
                    for k in ("asin", "fnsku")
                )
            ):
                result["identities"].append(
                    {
                        "sku_id": str(p["sku_id"]),
                        "seller_sku": r["sku"],
                        "asin": r["asin"],
                        "fnsku": r["fnsku"],
                        "store": products["store"],
                        "reason": f"库存快照原行{n}提供平台编码；"
                        "正式SKU与店铺范围核对一致",
                    }
                )
                result["source_identity_sku_ids"].append(str(p["sku_id"]))
                ready.add(str(p["sku_id"]))
    except (UnicodeError, csv.Error, TypeError) as error:
        raise ApiError(
            422, "fba_snapshot_invalid", "请上传亚马逊物流库存原始UTF-8 CSV。"
        ) from error
    return result
