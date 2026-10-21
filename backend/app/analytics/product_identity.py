"""Canonical Seller SKU parsing for style and variant analytics."""

from __future__ import annotations

import re
from dataclasses import dataclass

SELLER_SKU_PATTERN_TEXT = r"^[0-9]+-[^-]+-[^-]+$"
_SELLER_SKU_PATTERN = re.compile(SELLER_SKU_PATTERN_TEXT, re.ASCII)


@dataclass(frozen=True, slots=True)
class SellerSkuIdentity:
    seller_sku: str
    style_code: str
    color: str
    size: str


def parse_seller_sku(value: str | None) -> SellerSkuIdentity | None:
    """Return the strict ``style-color-size`` identity or ``None``."""

    if value is None or _SELLER_SKU_PATTERN.fullmatch(value) is None:
        return None
    style_code, color, size = value.split("-", maxsplit=2)
    return SellerSkuIdentity(
        seller_sku=value,
        style_code=style_code,
        color=color,
        size=size,
    )
