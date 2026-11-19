"""Read draft or published report products against the scoped approved catalog."""

# ruff: noqa: RUF001 -- Chinese report matching messages.
from collections import defaultdict
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.api.errors import ApiError
from app.catalog.inventory import load_catalog_identity_inventory
from app.catalog.normalization import seller_sku_match_v1
from app.catalog.platform_evidence import compare_listing, official_evidence
from app.catalog.production_sources import _publication


def match_report(connection: Connection, site: int, version_id: int) -> dict[str, Any]:
    report = (
        connection.execute(
            sa.text("""
        SELECT d.report_type,a.report_source_scope_id
        FROM dataset_versions v JOIN daily_datasets d ON d.id=v.dataset_id
        LEFT JOIN report_dataset_scope_assignments a ON a.dataset_id=d.id
          AND a.site_id=d.site_id
        WHERE v.id=:version AND d.site_id=:site
    """),
            {"version": version_id, "site": site},
        )
        .mappings()
        .one_or_none()
    )
    if report is None:
        raise ApiError(404, "report_not_found", "未找到本工作区的报告。")
    scope = report["report_source_scope_id"]
    kind = report["report_type"]
    if kind not in {"business_report", "return_report"}:
        raise ApiError(422, "report_type_invalid", "当前报告类型不支持商品关联。")
    table = (
        "business_report_rows" if kind == "business_report" else "return_report_rows"
    )
    fields = (
        "f.child_asin,NULL AS fnsku"
        if kind == "business_report"
        else "f.asin AS child_asin,f.fnsku"
    )
    rows = (
        connection.execute(
            sa.text(f"""
        SELECT DISTINCT f.sku,{fields} FROM version_rows vr
        JOIN {table} f ON f.version_row_id=vr.id AND f.version_id=vr.version_id
        WHERE vr.version_id=:version AND vr.row_state='active'
    """),
            {"version": version_id},
        )
        .mappings()
        .all()
    )
    base, revision = _publication(connection, site, lock=False)
    mappings = (
        connection.execute(
            sa.text("""
        SELECT seller_sku_match_bytes,sku_id FROM product_catalog_mappings
        WHERE site_id=:site AND catalog_version_id=:base
          AND report_source_scope_id=:scope
    """),
            {"site": site, "base": base, "scope": scope},
        )
        .mappings()
        .all()
    )
    excluded = set(
        connection.execute(
            sa.text("""
        SELECT seller_sku_match_bytes FROM product_catalog_exclusions
        WHERE site_id=:site AND catalog_version_id=:base
          AND report_source_scope_id=:scope
    """),
            {"site": site, "base": base, "scope": scope},
        ).scalars()
    )
    owners = defaultdict(set)
    for row in mappings:
        owners[bytes(row["seller_sku_match_bytes"])].add(int(cast(int, row["sku_id"])))
    inventory = load_catalog_identity_inventory(
        connection, site_id=site, catalog_version_id=base
    )
    active_styles = {
        int(cast(int, row["style_id"]))
        for row in inventory.styles
        if row["status"] == "enabled"
    }
    active = {
        int(cast(int, row["sku_id"]))
        for row in inventory.skus
        if row["status"] == "enabled"
        and int(cast(int, row["style_id"])) in active_styles
    }
    source = [
        {
            "row_id": str(index),
            "sheet": "本报告",
            "seller_sku": row["sku"] or "",
            "child_asin": row["child_asin"] or "",
            "fnsku": row["fnsku"] or "",
        }
        for index, row in enumerate(rows)
    ]
    evidence = (
        official_evidence(
            connection,
            site,
            {"本报告": int(scope)},
            [row["seller_sku"] for row in source],
        )
        if scope
        else {"observations": []}
    )
    assessments = compare_listing(
        source, {"本报告": int(scope)} if scope else {}, evidence
    )
    grouped = defaultdict(list)
    for report_row, assessment in zip(source, assessments, strict=True):
        grouped[seller_sku_match_v1(report_row["seller_sku"]).utf8].append(
            (report_row, assessment)
        )
    matched, ignored, issues = 0, 0, []
    for key, values in grouped.items():
        raw = values[0][0]["seller_sku"]
        targets = owners[key]
        problem = ""
        if not scope:
            problem = "请确认报告所属店铺"
        elif len(targets) > 1 or any(
            check["state"]
            in {"source_conflict", "official_conflict", "source_difference"}
            or check.get("fnsku_notice")
            for _, check in values
        ):
            problem = "平台身份有冲突，请核对来源"
        elif key in excluded and not targets:
            ignored += 1
            continue
        elif key in excluded:
            problem = "关联与排除决定冲突"
        elif not targets:
            problem = "尚未关联本店商品"
        elif not targets.issubset(active):
            problem = "商品已停用，请核对"
        else:
            matched += 1
            continue
        issues.append({"seller_sku": raw, "message": problem})
    return {
        "catalog_publication_revision": revision,
        "matched": matched,
        "excluded": ignored,
        "total": len(grouped),
        "issues": issues,
    }
