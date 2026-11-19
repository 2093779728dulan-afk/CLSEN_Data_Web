"""Source cell comparison with approved physical product identities."""

from __future__ import annotations

from typing import Any

from app.api.errors import ApiError
from app.catalog.normalization import catalog_identity_key_v1
from app.catalog.queries import CatalogVersionSummary


def product_match(
    snapshot: dict[str, Any],
    catalog: CatalogVersionSummary | None,
    source_key: str,
    size: str,
) -> dict[str, Any]:
    rows = (
        snapshot["rows"]
        + snapshot["unconfirmed_rows"]
        + snapshot.get("outside_rows", [])
    )
    row = next((row for row in rows if row["source_key"] == source_key), None)
    if row is None:
        raise ApiError(
            404, "inventory_match_source_not_found", "此核对单没有所选来源行。"
        )
    color = row["color"] or row["color_note"]
    quantity = row["quantities"].get(size)
    saved = row.get("product_links", {}).get(size)
    result: dict[str, Any] = {
        "source": {
            "source_key": source_key,
            "cell": quantity["cell"] if quantity else "",
            "style_code": row["style_code"],
            "color": color,
            "size": size,
            "units": quantity["units"]
            if quantity and quantity["state"] == "LITERAL"
            else None,
        },
        "catalog_version_id": str(catalog.catalog_version_id) if catalog else None,
        "catalog_publication_revision": str(catalog.catalog_publication_revision)
        if catalog
        else None,
        "association_saved": bool(saved),
        "saved_association": saved,
        "association_current": False,
        "posting_enabled": False,
        "candidates": [],
    }
    style_code = row["style_code"]
    if (
        not style_code
        or style_code == "无款号"
        or any(c in style_code for c in ("改", "\n"))
        or not color
        or any(c in color for c in ("\n", "/"))
    ):
        return result | {"status": "source_incomplete"}
    try:
        style_key = catalog_identity_key_v1(style_code).utf8
        color_key = catalog_identity_key_v1(color).utf8
        size_key = catalog_identity_key_v1(size).utf8
    except ValueError:
        return result | {"status": "source_incomplete"}
    if catalog is None:
        return result | {"status": "catalog_unavailable"}
    styles = {
        style.style_id: style
        for style in catalog.styles
        if catalog_identity_key_v1(style.style_code).utf8 == style_key
    }
    candidates = []
    for sku in catalog.skus:
        style = styles.get(sku.style_id)
        if (
            style is None
            or catalog_identity_key_v1(sku.standard_color).utf8 != color_key
            or catalog_identity_key_v1(sku.standard_size).utf8 != size_key
        ):
            continue
        candidates.append(
            {
                "style_id": str(style.style_id),
                "sku_id": str(sku.sku_id),
                "style_code": style.style_code,
                "standard_name": style.standard_name,
                "standard_color": sku.standard_color,
                "standard_size": sku.standard_size,
                "code": sku.internal_display_sku,
                "active": style.status == "enabled" and sku.status == "enabled",
            }
        )
    status = "not_found"
    if len(candidates) > 1:
        status = "ambiguous"
    elif candidates:
        status = "matched" if candidates[0]["active"] else "disabled"
    return result | {
        "status": status,
        "candidates": candidates,
        "association_current": bool(
            saved and status == "matched" and saved["sku_id"] == candidates[0]["sku_id"]
        ),
    }
