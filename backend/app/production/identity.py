"""Read-only SKU identity; fixed fictional fixtures cannot run on ordinary databases."""

from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.api.errors import ApiError
from app.catalog.queries import MySqlCatalogQueries
from app.config import Settings
from app.site_context import CurrentSiteContext


def configured_warehouse_product_scope(
    settings: Settings,
    context: CurrentSiteContext,
    engine: Engine,
    directory: dict[str, object],
) -> dict[str, object] | None:
    """Use an explicit local warehouse binding when source-sheet mode is absent."""
    if not settings.production_inventory_source_root:
        return None
    path = (
        Path(settings.production_inventory_source_root) / "warehouse-product-scope.json"
    )
    if not path.is_file():
        return None
    binding = json.loads(path.read_bytes())
    if str(binding.get("site_id")) != str(context.site_id):
        return None
    if str(binding["warehouse_id"]) != str(directory["id"]):
        return None
    if (
        binding.get("schema") != "warehouse-product-scope-v1"
        or binding.get("database") != engine.url.database
        or not str(engine.url.database).startswith("clsen_data_test_")
    ):
        raise ApiError(409, "warehouse_shop_scope_invalid", "仓库商品范围配置已变化。")
    if directory.get("type") != binding["warehouse_type"]:
        raise ApiError(
            409,
            "warehouse_shop_scope_invalid",
            "仓库身份已变化，请重新核对。",  # noqa: RUF001
        )
    return warehouse_product_scope(
        engine,
        context,
        warehouse_id=str(directory["id"]),
        report_source_scope_id=int(binding["report_source_scope_id"]),
    )


def warehouse_product_scope(
    engine: Engine,
    context: CurrentSiteContext,
    *,
    warehouse_id: str,
    report_source_scope_id: int,
) -> dict[str, object]:
    """Read one publication and its members in a single statement."""
    with engine.connect() as connection:
        rows = (
            connection.execute(
                sa.text(
                    "SELECT "
                    "p.current_catalog_version_id,"
                    "p.catalog_publication_revision,g.sku_id "
                    "FROM report_source_scopes s "
                    "JOIN product_catalog_publications p ON p.site_id=s.site_id "
                    "LEFT JOIN product_catalog_shop_memberships g "
                    "ON g.site_id=p.site_id "
                    "AND g.catalog_version_id=p.current_catalog_version_id "
                    "AND g.report_source_scope_id=s.id "
                    "WHERE s.id=:scope AND s.site_id=:site "
                    "AND s.marketplace_scope_code='amazon_us' ORDER BY g.sku_id"
                ),
                {"scope": report_source_scope_id, "site": context.site_id},
            )
            .mappings()
            .all()
        )
    if not rows or rows[0]["current_catalog_version_id"] is None:
        raise ApiError(409, "catalog_refresh_required", "商品目录尚未就绪，请刷新。")  # noqa: RUF001
    first = rows[0]
    return {
        "state": "ready",
        "warehouse_id": warehouse_id,
        "report_source_scope_id": str(report_source_scope_id),
        "catalog_version": (
            f"{first['current_catalog_version_id']}:"
            f"{first['catalog_publication_revision']}"
        ),
        "sku_ids": [str(row["sku_id"]) for row in rows if row["sku_id"] is not None],
    }


def catalog_for_report_scope(
    engine: Engine,
    context: CurrentSiteContext,
    catalog: dict[str, dict[str, str | None]],
    report_source_scope_id: int,
) -> dict[str, dict[str, str | None]]:
    """Select approved shop members without changing warehouse identities."""
    with engine.connect() as connection:
        scope = connection.scalar(
            sa.text(
                "SELECT id FROM report_source_scopes "
                "WHERE id=:scope AND site_id=:site "
                "AND marketplace_scope_code='amazon_us'"
            ),
            {"scope": report_source_scope_id, "site": context.site_id},
        )
        if scope is None:
            raise ApiError(404, "catalog_scope_not_found", "商品店铺范围不存在。")
        versions = {item["catalog_version"] for item in catalog.values()}
        if not versions:
            return {}
        if versions == {"DEMO_LOCAL_ONLY-v1"}:
            return catalog
        if len(versions) != 1:
            raise ApiError(409, "catalog_refresh_required", "商品目录已变化，请刷新。")  # noqa: RUF001
        version = int(str(next(iter(versions))).split(":")[0])
        members = {
            str(sku)
            for sku in connection.scalars(
                sa.text(
                    "SELECT DISTINCT sku_id FROM product_catalog_mappings "
                    "WHERE site_id=:site AND catalog_version_id=:version "
                    "AND report_source_scope_id=:scope"
                ),
                {
                    "site": context.site_id,
                    "version": version,
                    "scope": report_source_scope_id,
                },
            )
        }
    return {sku: item for sku, item in catalog.items() if sku in members}


def production_skus(
    settings: Settings, context: CurrentSiteContext, engine: Engine
) -> dict[str, dict[str, str | None]]:
    if settings.production_demo_mode:
        if (
            engine.url.database != "clsen_control_b_v1_1_0"
            or context.site_code != "DEMO_LOCAL_ONLY"
        ):
            raise ApiError(
                503,
                "demo_scope_invalid",
                "虚构样本只能用于B独立控制库和DEMO_LOCAL_ONLY站点。",
            )
        return {
            "1001": {
                "sku_id": "1001",
                "style_id": "2001",
                "standard_color": "蓝色",
                "standard_size": "M",
                "label": "DEMO-SKU-BLUE-M · 蓝色 / M",
                "code": "DEMO-SKU-BLUE-M",
                "status": "active",
                "catalog_version": "DEMO_LOCAL_ONLY-v1",
            },
            "1002": {
                "sku_id": "1002",
                "style_id": "2001",
                "standard_color": "蓝色",
                "standard_size": "L",
                "label": "DEMO-SKU-BLUE-L · 蓝色 / L",
                "code": "DEMO-SKU-BLUE-L",
                "status": "active",
                "catalog_version": "DEMO_LOCAL_ONLY-v1",
            },
            "1003": {
                "sku_id": "1003",
                "style_id": "2002",
                "standard_color": "红色",
                "standard_size": "M",
                "label": "DEMO-SKU-RED-M · 红色 / M",
                "code": "DEMO-SKU-RED-M",
                "status": "active",
                "catalog_version": "DEMO_LOCAL_ONLY-v1",
            },
        }
    if settings.production_qa_catalog_mode and (
        engine.url.database != "clsen_data_test_production_catalog_20261015"
        or context.site_code != "QA_PRODUCTION_CATALOG"
    ):
        raise ApiError(
            503,
            "qa_catalog_scope_invalid",
            "虚构目录模式只能使用本任务的独立QA库和站点。",
        )
    catalog = MySqlCatalogQueries(engine).current_catalog(site_id=context.site_id)
    if catalog is None:
        return {}
    style_status = {style.style_id: style.status for style in catalog.styles}
    style_codes = {style.style_id: style.style_code for style in catalog.styles}
    return {
        str(sku.sku_id): {
            "sku_id": str(sku.sku_id),
            "style_id": str(sku.style_id),
            "style_code": style_codes.get(sku.style_id, ""),
            "standard_color": sku.standard_color,
            "standard_size": sku.standard_size,
            "label": sku.internal_display_sku
            or (
                f"{style_codes.get(sku.style_id, '')} · "
                f"{sku.standard_color} · {sku.standard_size}"
            ),
            "code": sku.internal_display_sku,
            "code_status": sku.code_status,
            "channel_status": "bound" if sku.seller_sku_count else "pending",
            "contract_version": "2",
            "status": "active"
            if sku.status == "enabled" and style_status.get(sku.style_id) == "enabled"
            else "disabled",
            "catalog_version": (
                f"{catalog.catalog_version_id}:{catalog.catalog_publication_revision}"
            ),
        }
        for sku in catalog.skus
    }


def resolve_standard_codes(
    engine: Engine,
    context: CurrentSiteContext,
    catalog: dict[str, dict[str, str | None]],
    codes: list[str],
    *,
    demo: bool = False,
) -> dict[str, dict[str, str | None]]:
    """Resolve each literal using the shared matching rule within this site's scope."""
    import sqlalchemy as sa

    from app.catalog.normalization import seller_sku_match_v1

    result: dict[str, dict[str, str | None]] = {}
    versions = {item["catalog_version"] for item in catalog.values()}
    if len(versions) != 1:
        return result
    version = None if demo else int(str(next(iter(versions))).split(":")[0])
    with engine.connect() as connection:
        scope_ids = (
            []
            if demo
            else list(
                connection.scalars(
                    sa.text(
                        "SELECT id FROM report_source_scopes WHERE site_id=:site "
                        "AND marketplace_scope_code='amazon_us'"
                    ),
                    {"site": context.site_id},
                )
            )
        )
        if len(scope_ids) > 1:
            raise ApiError(
                422,
                "source_scope_ambiguous",
                "存在多个来源范围，请先明确账号/站点；当前标准表不能跨范围猜测SKU。",  # noqa: RUF001
            )
        mappings = (
            []
            if demo
            else connection.execute(
                sa.text(
                    "SELECT m.seller_sku_match_bytes,m.sku_id FROM "
                    "product_catalog_mappings m JOIN report_source_scopes s ON "
                    "s.id=m.report_source_scope_id AND s.site_id=m.site_id WHERE "
                    "m.site_id=:site AND m.catalog_version_id=:version AND "
                    "s.marketplace_scope_code='amazon_us'"
                ),
                {"site": context.site_id, "version": version},
            )
            .mappings()
            .all()
        )
        for code in codes:
            key = seller_sku_match_v1(code).utf8
            candidates = {
                str(row["sku_id"])
                for row in mappings
                if bytes(row["seller_sku_match_bytes"]) == key
            }
            candidates.update(
                sku_id
                for sku_id, value in catalog.items()
                if value.get("code")
                and seller_sku_match_v1(str(value["code"])).utf8 == key
            )
            if len(candidates) == 1:
                sku = catalog.get(next(iter(candidates)))
                if sku is not None and sku["status"] == "active":
                    result[code] = sku
    return result
