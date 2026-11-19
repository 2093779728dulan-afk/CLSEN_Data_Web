# ruff: noqa: RUF001, E501 -- Chinese reconciliation messages.
"""Scoped official observations and immutable evidence fingerprints for listings."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.api.errors import ApiError
from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.errors import CatalogNormalizationError
from app.catalog.normalization import seller_sku_match_v1
from app.catalog.scope_projection import SCOPES_WITH_DISPLAY_NAMES


def _listing_match(raw: str) -> bytes:
    try:
        return seller_sku_match_v1(raw).utf8
    except CatalogNormalizationError:
        return b""


def lock_platform_scopes(
    connection: Connection, site_id: int, scope_ids: list[int]
) -> None:
    scopes = sorted(set(scope_ids))
    if not scopes:
        return
    # Source confirmation and return initialization already serialize on this
    # mutable pointer. Keep the same exclusive boundary without requiring an
    # UPDATE grant on immutable source history for MySQL locking reads.
    pointer = connection.scalar(
        sa.text(
            "SELECT site_id FROM site_current_configs WHERE site_id=:site FOR UPDATE"
        ),
        {"site": site_id},
    )
    if pointer is None:
        raise ApiError(403, "listing_scope_forbidden", "当前工作区尚未就绪。")
    for scope in scopes:
        found = connection.scalar(
            sa.text(
                "SELECT id FROM report_source_scopes WHERE site_id=:site AND id=:scope"
            ),
            {"site": site_id, "scope": scope},
        )
        if found is None:
            raise ApiError(
                403,
                "listing_scope_forbidden",
                "店铺账号或站点不属于当前工作区，请重新选择。",
            )


def official_evidence(
    connection: Connection,
    site_id: int,
    bindings: dict[str, int],
    seller_skus: list[str],
) -> dict[str, Any]:
    scopes = sorted(set(bindings.values()))
    if not scopes:
        return {
            "digest": hashlib.sha256(b"[]").hexdigest(),
            "members": [],
            "observations": [],
            "scope_ids": [],
        }
    valid = (
        connection.execute(
            sa.text(
                f"SELECT id,seller_account_display_name,marketplace_scope_code FROM {SCOPES_WITH_DISPLAY_NAMES} AS current_scopes WHERE site_id=:site AND id IN :scopes"
            ).bindparams(sa.bindparam("scopes", expanding=True)),
            {"site": site_id, "scopes": scopes},
        )
        .mappings()
        .all()
    )
    if {int(r["id"]) for r in valid} != set(scopes) or any(
        r["marketplace_scope_code"] != "amazon_us" for r in valid
    ):
        raise ApiError(
            403, "listing_scope_forbidden", "请选择当前工作区可用的亚马逊账号和站点。"
        )
    members = [
        dict(r)
        for r in connection.execute(
            sa.text("""
        SELECT a.report_source_scope_id,d.id AS dataset_id,d.report_type,d.report_date,
               p.version_id,v.data_revision,r.publication_revision
        FROM report_dataset_scope_assignments a
        JOIN daily_datasets d ON d.id=a.dataset_id AND d.site_id=a.site_id
        JOIN report_publication_revisions r ON r.dataset_id=d.id AND r.site_id=a.site_id
             AND r.report_source_scope_id=a.report_source_scope_id
        LEFT JOIN dataset_publications p ON p.dataset_id=d.id
        LEFT JOIN dataset_versions v ON v.id=p.version_id AND v.dataset_id=d.id
        WHERE a.site_id=:site AND a.report_source_scope_id IN :scopes
          AND p.version_id IS NOT NULL AND v.status='published'
        ORDER BY a.report_source_scope_id,d.id
        """).bindparams(sa.bindparam("scopes", expanding=True)),
            {"site": site_id, "scopes": scopes},
        ).mappings()
    ]
    for m in members:
        m["report_date"] = str(m["report_date"])
    hashes = list({seller_sku_match_v1(raw).sha256 for raw in seller_skus if raw})
    observations = []
    if hashes:
        for kind, table, fields in [
            (
                "business_report",
                "business_report_rows",
                "f.parent_asin,f.child_asin,NULL AS fnsku,NULL AS event_date",
            ),
            (
                "return_report",
                "return_report_rows",
                "NULL AS parent_asin,f.asin AS child_asin,f.fnsku,f.return_date AS event_date",
            ),
        ]:
            query = sa.text(f"""
                SELECT k.report_source_scope_id,k.seller_sku_match_bytes,k.source_row_id,
                       d.id AS dataset_id,d.report_date,p.version_id,{fields}
                FROM report_source_keys k
                JOIN report_dataset_scope_assignments a ON a.dataset_id=k.dataset_id AND a.site_id=k.site_id AND a.report_source_scope_id=k.report_source_scope_id
                JOIN daily_datasets d ON d.id=k.dataset_id AND d.site_id=k.site_id
                JOIN dataset_publications p ON p.dataset_id=d.id AND p.version_id=k.version_id
                JOIN dataset_versions v ON v.id=p.version_id AND v.dataset_id=d.id AND v.status='published'
                JOIN version_rows vr ON vr.id=k.source_row_id AND vr.version_id=k.version_id AND vr.row_state='active'
                JOIN {table} f ON f.version_row_id=vr.id AND f.version_id=vr.version_id
                WHERE k.site_id=:site AND k.report_source_scope_id IN :scopes
                  AND k.report_type=:kind AND k.seller_sku_match_sha256 IN :hashes
                ORDER BY k.report_source_scope_id,d.id,k.source_row_id LIMIT 10001
                """).bindparams(
                sa.bindparam("scopes", expanding=True),
                sa.bindparam("hashes", expanding=True),
            )
            records = (
                connection.execute(
                    query,
                    {"site": site_id, "scopes": scopes, "kind": kind, "hashes": hashes},
                )
                .mappings()
                .all()
            )
            if len(records) > 10000:
                raise ApiError(
                    422,
                    "listing_evidence_capacity",
                    "本批官方观测超过10000条，请减少本次核对的SKU范围。",
                )
            wanted = {_listing_match(raw) for raw in seller_skus if raw}
            for record in records:
                item = dict(record)
                raw = bytes(item.pop("seller_sku_match_bytes"))
                if raw not in wanted:
                    continue
                item.update(
                    seller_sku=raw.decode("utf-8"),
                    report_type=kind,
                    report_date=str(item["report_date"]),
                    event_date=str(item["event_date"]) if item["event_date"] else None,
                )
                observations.append(item)
    # Scope metadata is part of the snapshot: scope corrections also invalidate it.
    manifest = {"members": members, "scopes": [dict(r) for r in valid]}
    return {
        "digest": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
        "members": members,
        "observations": observations,
        "scope_ids": scopes,
        "scopes": [dict(r) for r in valid],
    }


def compare_listing(
    rows: list[dict[str, Any]], bindings: dict[str, int], evidence: dict[str, Any]
) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for obs in evidence["observations"]:
        groups[
            (
                int(obs["report_source_scope_id"]),
                seller_sku_match_v1(obs["seller_sku"]).utf8,
            )
        ].append(obs)
    own = defaultdict(set)
    duplicates = defaultdict(list)
    for row in rows:
        scope = bindings.get(row["sheet"])
        raw = row.get("seller_sku", "")
        if scope and raw:
            key = (scope, raw)
            own[key].add(
                (
                    row.get("asin", ""),
                    row.get("child_asin", ""),
                    row.get("parent_asin", ""),
                    row.get("fnsku", ""),
                )
            )
            duplicates[
                (
                    scope,
                    raw,
                    *(
                        row.get(f, "")
                        for f in ("asin", "child_asin", "parent_asin", "fnsku")
                    ),
                )
            ].append(row["row_id"])
    result = []
    for row in rows:
        scope = bindings.get(row["sheet"])
        raw = row.get("seller_sku", "")
        values = groups.get((scope, _listing_match(raw)), []) if scope and raw else []
        asins = sorted({v["child_asin"] for v in values if v["child_asin"]})
        parents = sorted({v["parent_asin"] for v in values if v["parent_asin"]})
        fnskus = sorted({v["fnsku"] for v in values if v["fnsku"]})
        types = sorted({v["report_type"] for v in values})
        incoming = row.get("child_asin") or row.get("asin") or ""
        changed = bool(len(asins) == 1 and incoming and incoming != asins[0])
        fnsku_changed = bool(
            len(fnskus) == 1 and row.get("fnsku") and row["fnsku"] != fnskus[0]
        )
        if not scope:
            state, message = "scope_required", "请先为此工作表选择店铺账号和站点。"
        elif len(own[(scope, raw)]) > 1:
            state, message = (
                "source_conflict",
                "本表同一店铺的Seller SKU对应不同平台编码，请核对来源行，不能取最后一行。",
            )
        elif len(asins) > 1:
            state, message = (
                "official_conflict",
                "官方子ASIN存在多个值，请核对来源期间、父子层级及商品历史，不能自动取最新值。",
            )
        elif not asins:
            state, message = (
                "no_official",
                "店铺Seller SKU可随建档确认关联，ASIN、FNSKU待报表核对。",
            )
        elif changed or fnsku_changed:
            state, message = (
                "source_difference",
                "清单与官方记录不同，请查看双方来源并明确采用官方依据；原表值仍保留。",
            )
        else:
            state, message = (
                "consistent",
                "本次已发布证据范围内一致。"
                if len(types) == 2
                else "仅单一官方来源已核对，另一类报告尚无可比记录。",
            )
        dupe = duplicates.get(
            (
                scope,
                raw,
                *(
                    row.get(f, "")
                    for f in ("asin", "child_asin", "parent_asin", "fnsku")
                ),
            ),
            [row["row_id"]],
        )
        result.append(
            {
                "row_id": row["row_id"],
                "state": state,
                "message": message,
                "scope_id": scope,
                "official_asins": asins,
                "official_parent_asins": parents,
                "official_fnskus": fnskus,
                "report_types": types,
                "observations": values,
                "duplicate_rows": dupe,
                "primary_row": dupe[0],
                "can_map": bool(
                    scope
                    and raw
                    and state
                    not in {"source_conflict", "official_conflict", "scope_required"}
                ),
                "fnsku_notice": "官方FNSKU存在多值，需单独核对履约/历史；不据此改变内部商品。"
                if len(fnskus) > 1
                else None,
            }
        )
    return result


def listing_payload(
    connection: Connection, site_id: int, import_id: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    row = (
        connection.execute(
            sa.text(
                "SELECT i.id,i.export_id,i.status,i.workflow_revision,i.base_catalog_version_id,i.owner_user_id,p.evidence_payload_json FROM catalog_imports i JOIN catalog_export_payloads p ON p.export_id=i.export_id AND p.site_id=i.site_id WHERE i.id=:id AND i.site_id=:site AND i.source_kind='production'"
            ),
            {"id": import_id, "site": site_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ApiError(404, "listing_not_found", "未找到当前工作区的商品清单批次。")
    value = (
        json.loads(row["evidence_payload_json"])
        if isinstance(row["evidence_payload_json"], str)
        else row["evidence_payload_json"]
    )
    source = value.get("production_source", {})
    if source.get("source_schema") != "amazon_listing_v1":
        raise ApiError(
            404, "listing_not_found", "此批次不是亚马逊商品清单，请返回原商品建档入口。"
        )
    return dict(row), source


def catalog_platform_review(
    connection: Connection,
    *,
    site_id: int,
    catalog_version_id: int,
    scope_id: int | None = None,
    style_id: int | None = None,
) -> dict[str, Any]:
    """Check mapped external keys without modifying their historical ownership."""
    parameters = {
        "site": site_id,
        "version": catalog_version_id,
        "scope": scope_id,
        "style": style_id,
    }
    keys = [
        dict(row)
        for row in connection.execute(
            sa.text("""
        SELECT m.report_source_scope_id,m.seller_sku_match_bytes,m.sku_id,sm.style_id
        FROM product_catalog_mappings m
        JOIN product_catalog_sku_members sm ON sm.catalog_version_id=m.catalog_version_id AND sm.site_id=m.site_id AND sm.sku_id=m.sku_id
        WHERE m.site_id=:site AND m.catalog_version_id=:version
          AND (:scope IS NULL OR m.report_source_scope_id=:scope)
          AND (:style IS NULL OR sm.style_id=:style)
        ORDER BY m.report_source_scope_id,m.sku_id LIMIT 1001
        """),
            parameters,
        ).mappings()
    ]
    if len(keys) > 1000:
        return {
            "state": "incomplete",
            "message": "本次平台标识核对超过1000个键，请缩小商品范围；原分析仍按已批准映射解释。",
            "conflicts": [],
            "blocked_keys": [],
            "checked_keys": 0,
        }
    bindings = {
        str(r["report_source_scope_id"]): int(r["report_source_scope_id"]) for r in keys
    }
    evidence = official_evidence(
        connection,
        site_id,
        bindings,
        [bytes(r["seller_sku_match_bytes"]).decode() for r in keys],
    )
    groups = defaultdict(set)
    for obs in evidence["observations"]:
        if obs.get("child_asin"):
            groups[
                (
                    int(obs["report_source_scope_id"]),
                    seller_sku_match_v1(obs["seller_sku"]).utf8,
                )
            ].add(obs["child_asin"])
    conflicts, blocked = [], []
    for row in keys:
        raw = bytes(row["seller_sku_match_bytes"])
        asins = groups[(int(row["report_source_scope_id"]), raw)]
        if len(asins) > 1:
            blocked.append(f"{row['report_source_scope_id']}:{raw.hex().upper()}")
            conflicts.append(
                {
                    "sku_id": str(row["sku_id"]),
                    "style_id": str(row["style_id"]),
                    "scope_id": str(row["report_source_scope_id"]),
                    "asin_count": len(asins),
                    "seller_sku": raw.decode(),
                    "official_asins": sorted(asins),
                }
            )
    has_evidence = bool(evidence["observations"])
    return {
        "state": "pending"
        if conflicts
        else "observed"
        if has_evidence
        else "no_official",
        "message": "官方来源出现多个子ASIN，受影响关联列入待核，当前单品指标暂不计入这些事实；原报告及历史映射保留。"
        if conflicts
        else "当前已发布证据暂未发现多子ASIN冲突；商品归属仍以已批准映射为依据，缺少的来源不视为已核实。"
        if has_evidence
        else "当前已批准关联尚无可比较的官方子ASIN证据。",
        "conflicts": conflicts,
        "blocked_keys": blocked,
        "checked_keys": len(keys),
        "evidence_digest": evidence["digest"],
    }
