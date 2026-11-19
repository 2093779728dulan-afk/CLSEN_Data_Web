"""Shared inventory-table selection, using the existing stock settings authority."""
# ruff: noqa: RUF001 -- Chinese user-facing validation.

from __future__ import annotations

from typing import Any

from app.api.errors import ApiError


def selected_skus(
    settings: dict[str, Any], catalog: dict[str, dict[str, Any]]
) -> set[str]:
    selected = set(settings["style_ids"])
    allowed = {
        sku_id
        for sku_id, sku in catalog.items()
        if (sku.get("style_id") or f"sku-{sku_id}") in selected
    }
    allowed.update(
        value.removeprefix("history:")
        for value in selected
        if value.startswith("history:")
    )
    return allowed


def filter_availability(value: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    if "sku_id" in value:
        require_selected(str(value["sku_id"]), allowed)
        return value
    return {
        **value,
        "items": [item for item in value["items"] if str(item["sku_id"]) in allowed],
    }


def require_selected(sku_id: str, allowed: set[str]) -> None:
    if sku_id not in allowed:
        raise ApiError(
            403,
            "inventory_display_forbidden",
            "该商品不在当前库存总览展示范围，请刷新或联系管理员设置款号。",
        )
