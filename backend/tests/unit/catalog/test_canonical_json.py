from __future__ import annotations

from decimal import Decimal

import pytest
from app.catalog.canonical_json import canonical_json_bytes, canonical_sha256


def test_canonical_json_encodes_the_supported_closed_value_domain() -> None:
    value = {
        "z": [None, True, False, -12, 'x\n\t"\\\u000f'],
        "a": {"nested": 0},
    }

    assert canonical_json_bytes(value) == (
        b'{"a":{"nested":0},"z":[null,true,false,-12,"x\\n\\t\\"\\\\\\u000f"]}'
    )
    assert canonical_sha256(value).startswith("sha256:")
    assert len(canonical_sha256(value)) == 71


def test_canonical_json_sorts_object_keys_by_utf16_code_units() -> None:
    value = {"\ufffd": 4, "\U0001f600": 3, "\u20ac": 2, "a": 1}
    expected = '{"a":1,"€":2,"😀":3,"' + chr(0xFFFD) + '":4}'

    assert canonical_json_bytes(value).decode() == expected


@pytest.mark.parametrize(
    "value",
    (
        1.5,
        float("nan"),
        float("inf"),
        Decimal("1.50"),
        {"value": 1.5},
        {1: "non-string key"},
        ("tuple",),
        {"set"},
        "\ud800",
    ),
)
def test_canonical_json_rejects_values_outside_the_project_profile(
    value: object,
) -> None:
    with pytest.raises(TypeError, match="catalog_canonical_json_value_invalid"):
        canonical_json_bytes(value)


def test_decimal_values_are_encoded_as_preformatted_strings() -> None:
    assert canonical_json_bytes({"amount": "12.50"}) == b'{"amount":"12.50"}'
