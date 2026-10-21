from __future__ import annotations

import pytest
from app.analytics.product_identity import (
    SELLER_SKU_PATTERN_TEXT,
    parse_seller_sku,
)


@pytest.mark.parametrize(
    ("seller_sku", "style_code", "color", "size"),
    [
        ("2301-White-S", "2301", "White", "S"),
        ("2301-Black-M", "2301", "Black", "M"),
        ("0012-Sand-XL", "0012", "Sand", "XL"),
    ],
)
def test_parse_seller_sku_uses_style_color_size_contract(
    seller_sku: str,
    style_code: str,
    color: str,
    size: str,
) -> None:
    identity = parse_seller_sku(seller_sku)

    assert identity is not None
    assert identity.seller_sku == seller_sku
    assert identity.style_code == style_code
    assert identity.color == color
    assert identity.size == size


@pytest.mark.parametrize(
    "seller_sku",
    [
        None,
        "",
        "2301",
        "2301-White",
        "2301-White-S-Extra",
        "AB-White-S",
        "2301--S",
        "2301-White-",
    ],
)
def test_parse_seller_sku_rejects_unclassified_values(
    seller_sku: str | None,
) -> None:
    assert parse_seller_sku(seller_sku) is None


def test_sql_and_python_parser_share_one_pattern() -> None:
    assert SELLER_SKU_PATTERN_TEXT == r"^[0-9]+-[^-]+-[^-]+$"
