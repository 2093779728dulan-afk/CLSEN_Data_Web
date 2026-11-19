"""Reuse approved listing evidence within the current catalog's ancestry and shop."""

# ruff: noqa: RUF001 -- Chinese product setup messages.
import json
import re
from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.api.errors import ApiError
from app.catalog.normalization import seller_sku_match_v1
from app.catalog.scope_projection import SCOPES_WITH_DISPLAY_NAMES


def catalog_products(
    connection: Connection, site: int, scope: int, catalog: dict[str, Any]
) -> dict[str, Any]:
    shop = connection.execute(
        text(
            f"SELECT seller_account_display_name FROM {SCOPES_WITH_DISPLAY_NAMES} "
            "s WHERE site_id=:site AND id=:scope "
            "AND marketplace_scope_code='amazon_us'"
        ),
        {"site": site, "scope": scope},
    ).scalar_one_or_none()
    if shop is None:
        raise ApiError(409, "fba_scope_conflict", "请先确认本仓使用的美国站店铺。")
    versions = {str(item["catalog_version"]) for item in catalog.values()}
    if not versions:
        return {"identities": [], "issues": [], "store": shop, "catalog_version": ""}
    if len(versions) != 1:
        raise ApiError(409, "fba_catalog_conflict", "商品目录已变化，请刷新后继续。")
    version = next(iter(versions))
    params = {"site": site, "scope": scope, "version": int(version.split(":")[0])}
    sources = (
        connection.execute(
            text("""
        WITH RECURSIVE lineage AS (
            SELECT id,base_catalog_version_id,source_import_id,0 AS depth
            FROM product_catalog_versions WHERE site_id=:site AND id=:version
            UNION ALL
            SELECT v.id,v.base_catalog_version_id,v.source_import_id,l.depth+1
            FROM product_catalog_versions v JOIN lineage l
              ON v.id=l.base_catalog_version_id AND v.site_id=:site
        )
        SELECT l.source_import_id,p.evidence_payload_json
        FROM lineage l JOIN catalog_imports i
          ON i.id=l.source_import_id AND i.site_id=:site AND i.status='approved'
        JOIN catalog_export_payloads p ON p.export_id=i.export_id
          AND p.site_id=i.site_id
        ORDER BY l.depth
    """),
            params,
        )
        .mappings()
        .all()
    )
    mappings = (
        connection.execute(
            text(
                "SELECT seller_sku_match_bytes,sku_id FROM product_catalog_mappings "
                "WHERE site_id=:site AND catalog_version_id=:version "
                "AND report_source_scope_id=:scope"
            ),
            params,
        )
        .mappings()
        .all()
    )
    owners = defaultdict(set)
    for row in mappings:
        owners[bytes(row["seller_sku_match_bytes"])].add(str(row["sku_id"]))
    # Keep all rows in the newest approved source for a key so conflicting codes
    # cannot be resolved by taking whichever row happens to appear last.
    evidence: dict[bytes, list[tuple[Any, Any, str]]] = {}
    for record in sources:
        payload = record["evidence_payload_json"]
        payload = json.loads(payload) if isinstance(payload, str) else payload
        source = payload.get("production_source", {})
        if source.get("source_schema") != "amazon_listing_v1":
            continue
        raw_rows = {row["row_id"]: row for row in source.get("listing_rows", [])}
        batch = defaultdict(list)
        for choice in source.get("selections", []):
            if choice.get("record_type") != "variant" or str(
                choice.get("scope_id")
            ) != str(scope):
                continue
            raw = raw_rows.get(choice["row_id"])
            if not raw or raw.get("issues"):
                continue
            key = seller_sku_match_v1(raw["seller_sku"]).utf8
            batch[key].append((raw, choice, str(record["source_import_id"])))
        for key, rows in batch.items():
            evidence.setdefault(key, rows)
    candidates = defaultdict(list)
    for key, rows in evidence.items():
        for raw, choice, import_id in rows:
            matched = owners.get(key) or {
                sku_id
                for sku_id, item in catalog.items()
                if item.get("code") == raw["seller_sku"]
                and item.get("style_code") == choice.get("style_code")
                and item.get("standard_color") == choice.get("color")
                and item.get("standard_size") == choice.get("size")
            }
            for sku_id in matched:
                item = catalog.get(sku_id)
                if (
                    item is None
                    or item.get("status") != "active"
                    or any(
                        item.get(field) != choice.get(selected)
                        for field, selected in (
                            ("style_code", "style_code"),
                            ("standard_color", "color"),
                            ("standard_size", "size"),
                        )
                    )
                    or choice.get("selected_sku_id") not in (None, int(sku_id))
                ):
                    continue
                asin = (
                    ""
                    if choice.get("use_official")
                    else raw.get("child_asin") or raw.get("asin") or ""
                )
                fnsku = "" if choice.get("use_official") else raw.get("fnsku") or ""
                candidates[sku_id].append(
                    {
                        "sku_id": sku_id,
                        "seller_sku": raw["seller_sku"],
                        "asin": asin,
                        "fnsku": fnsku,
                        "store": shop,
                        "reason": (
                            f"复用已审核商品表；审核批次{import_id}；当前目录{version}"
                        ),
                    }
                )
    identities: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for sku_id, item in catalog.items():
        if item.get("status") != "active":
            continue
        product_rows = candidates[sku_id]
        tuples = {
            (row["seller_sku"], row["asin"], row["fnsku"]) for row in product_rows
        }
        if len(tuples) == 1 and all(
            re.fullmatch(r"[A-Z0-9]{10}", product_rows[0][field])
            for field in ("asin", "fnsku")
        ):
            identities.append(product_rows[0])
        else:
            issues.append(
                {
                    "sku_id": sku_id,
                    "label": item.get("code") or item["label"],
                    "code": "platform_identity_conflict"
                    if len(tuples) > 1
                    else "platform_identity_missing",
                    "message": "平台编码存在冲突，请核对商品资料"
                    if len(tuples) > 1
                    else "请补齐本店铺的Seller SKU、ASIN和FNSKU",
                }
            )
    by_fnsku = defaultdict(list)
    for identity in identities:
        by_fnsku[identity["fnsku"]].append(identity["sku_id"])
    duplicates = {sku for skus in by_fnsku.values() if len(skus) > 1 for sku in skus}
    issues.extend(
        {
            "sku_id": sku,
            "label": catalog[sku].get("code") or sku,
            "code": "fnsku_conflict",
            "message": "FNSKU对应多个商品，请核对商品资料",
        }
        for sku in duplicates
    )
    return {
        "identities": [row for row in identities if row["sku_id"] not in duplicates],
        "issues": issues,
        "store": shop,
        "catalog_version": version,
    }
