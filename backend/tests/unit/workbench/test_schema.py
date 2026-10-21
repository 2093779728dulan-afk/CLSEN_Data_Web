from __future__ import annotations

from uuid import UUID

import pytest
from app.workbench.schema import SourceColumnMapping, compose_table_schema


def test_schema_preserves_first_seen_union_and_stable_column_ids() -> None:
    first = (
        SourceColumnMapping("SKU", "sku", "text"),
        SourceColumnMapping("Sessions", "sessions_total", "integer"),
        SourceColumnMapping("Merchant note", None, "text"),
    )
    second = (
        SourceColumnMapping("SKU", "sku", "text"),
        SourceColumnMapping("Custom flag", None, "text"),
        SourceColumnMapping("Sessions", "sessions_total", "integer"),
    )

    schema = compose_table_schema(
        "business_report",
        "business_report_v1",
        (first, second),
    )

    assert tuple(column.source_header for column in schema.columns) == (
        "SKU",
        "Sessions",
        "Merchant note",
        "Custom flag",
    )
    assert tuple(column.display_order for column in schema.columns) == (1, 2, 3, 4)
    assert all(isinstance(column.column_id, UUID) for column in schema.columns)
    repeated = compose_table_schema(
        "business_report",
        "business_report_v1",
        (first,),
    )
    assert repeated.columns[0].column_id == schema.columns[0].column_id
    assert repeated.columns[1].column_id == schema.columns[1].column_id


def test_schema_marks_standard_key_and_statistical_columns() -> None:
    schema = compose_table_schema(
        "return_report",
        "return_report_v1",
        (
            (
                SourceColumnMapping("Order ID", "order_id", "text"),
                SourceColumnMapping("Quantity", "quantity", "integer"),
                SourceColumnMapping("Operator note", None, "text"),
            ),
        ),
    )

    order, quantity, note = schema.columns
    assert order.is_key is True
    assert order.participates_in_statistics is True
    assert quantity.is_key is True
    assert quantity.value_kind == "integer"
    assert note.standard_field_name is None
    assert note.is_key is False
    assert note.participates_in_statistics is False


def test_schema_normalises_unicode_before_generating_identity() -> None:
    composed = "Caf\N{LATIN SMALL LETTER E WITH ACUTE}"
    decomposed = "Cafe\N{COMBINING ACUTE ACCENT}"
    left = compose_table_schema(
        "business_report",
        "business_report_v1",
        ((SourceColumnMapping(composed, None, "text"),),),
    )
    right = compose_table_schema(
        "business_report",
        "business_report_v1",
        ((SourceColumnMapping(decomposed, None, "text"),),),
    )

    assert left.columns[0].source_header == composed
    assert right.columns[0].source_header == composed
    assert left.columns[0].column_id == right.columns[0].column_id


@pytest.mark.parametrize("source_kind", ["percentage", "usd"])
def test_schema_accepts_compatible_decimal_source_kinds(source_kind: str) -> None:
    schema = compose_table_schema(
        "business_report",
        "business_report_v1",
        (
            (SourceColumnMapping("Metric", None, source_kind),),  # type: ignore[arg-type]
            (SourceColumnMapping("Metric", None, "decimal"),),
        ),
    )

    assert schema.columns[0].value_kind == "decimal"


@pytest.mark.parametrize(
    "second_mapping",
    [
        SourceColumnMapping("SKU", None, "text"),
        SourceColumnMapping("SKU", "sku", "integer"),
    ],
)
def test_schema_rejects_incompatible_repeated_source_mappings(
    second_mapping: SourceColumnMapping,
) -> None:
    with pytest.raises(ValueError, match="conflicting source mapping"):
        compose_table_schema(
            "business_report",
            "business_report_v1",
            (
                (SourceColumnMapping("SKU", "sku", "text"),),
                (second_mapping,),
            ),
        )


@pytest.mark.parametrize(
    ("sources", "message"),
    [
        (
            ((SourceColumnMapping("SKU", "sku", "text"),) * 2,),
            "duplicate source header",
        ),
        (
            ((SourceColumnMapping("Unknown", "not_a_field", "text"),),),
            "unknown standard field",
        ),
        (
            (
                (SourceColumnMapping("SKU", "sku", "text"),),
                (SourceColumnMapping("SKU", None, "text"),),
            ),
            "conflicting source mapping",
        ),
    ],
)
def test_schema_rejects_ambiguous_or_invalid_columns(
    sources: tuple[tuple[SourceColumnMapping, ...], ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        compose_table_schema("business_report", "business_report_v1", sources)


def test_source_mapping_rejects_a_blank_header() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        SourceColumnMapping("", None, "text")
