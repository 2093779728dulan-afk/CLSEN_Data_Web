from __future__ import annotations

import pytest
from app.workbench.repository import decode_source_mapping, decode_source_row


def test_decode_source_mapping_preserves_order_and_parser_targets() -> None:
    mapping = decode_source_mapping(
        {
            "source_header": ["SKU", "Sessions", "Operator note"],
            "fields": [
                {"source": "SKU", "target": "sku", "kind": "text"},
                {
                    "source": "Sessions",
                    "target": "sessions_total",
                    "kind": "integer",
                },
            ],
        }
    )

    assert tuple(item.source_header for item in mapping) == (
        "SKU",
        "Sessions",
        "Operator note",
    )
    assert tuple(item.standard_field_name for item in mapping) == (
        "sku",
        "sessions_total",
        None,
    )


def test_decode_source_row_preserves_empty_and_missing_values() -> None:
    values = decode_source_row(
        {
            "header": ["SKU", "Empty", "Missing"],
            "values": ["ABC", ""],
        }
    )

    assert values == {"SKU": "ABC", "Empty": "", "Missing": None}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"source_header": "SKU", "fields": []},
        {"source_header": ["SKU", "SKU"], "fields": []},
        {
            "source_header": ["SKU"],
            "fields": [{"source": "Other", "target": "sku", "kind": "text"}],
        },
    ],
)
def test_decode_source_mapping_rejects_corrupt_evidence(payload: object) -> None:
    with pytest.raises(ValueError, match="field mapping"):
        decode_source_mapping(payload)
