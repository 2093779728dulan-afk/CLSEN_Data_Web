from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from app.validation.codec import (
    decode_field_value,
    dumps_field_value,
    encode_field_value,
    loads_field_value,
)
from app.validation.fields import (
    FieldValueError,
    field_value_to_database,
    get_field_contract,
    get_report_field_contract,
    validate_added_row_values,
    validate_field_value,
    validate_row_values,
)


def test_report_contract_is_frozen_and_matches_supported_fields() -> None:
    contract = get_report_field_contract("business_report", "business_report_v1")

    assert contract.field_names == (
        "parent_asin",
        "child_asin",
        "title",
        "sku",
        "sessions_total",
        "sessions_b2b",
        "conversion_rate_total",
        "session_percentage_b2b",
        "page_views_total",
        "page_views_b2b",
        "page_view_percentage_total",
        "page_view_percentage_b2b",
        "featured_offer_percentage",
        "featured_offer_percentage_b2b",
        "units_ordered",
        "units_ordered_b2b",
        "unit_session_percentage",
        "unit_session_percentage_b2b",
        "ordered_product_sales",
        "ordered_product_sales_b2b",
        "currency_code",
        "total_order_items",
        "total_order_items_b2b",
    )
    assert (
        get_field_contract(
            "business_report", "business_report_v1", "currency_code"
        ).editable
        is False
    )

    with pytest.raises(TypeError):
        contract.fields[0] = contract.fields[0]  # type: ignore[index]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("quantity", True),
        ("quantity", 2**63),
        ("order_id", "x" * 129),
        ("return_date", datetime(2026, 8, 8, 8, 0)),
    ],
)
def test_field_validation_rejects_values_that_cannot_be_stored(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(FieldValueError):
        validate_field_value("return_report", "return_report_v1", field_name, value)


def test_decimal_validation_is_exact_and_enforces_database_scale() -> None:
    accepted = validate_field_value(
        "business_report",
        "business_report_v1",
        "ordered_product_sales",
        Decimal("12345678901234.123456"),
    )
    assert accepted == Decimal("12345678901234.123456")

    with pytest.raises(FieldValueError, match="scale"):
        validate_field_value(
            "business_report",
            "business_report_v1",
            "ordered_product_sales",
            Decimal("1.0000001"),
        )


def test_datetime_is_normalised_to_utc_and_database_value_is_naive_utc() -> None:
    source = datetime(
        2026,
        8,
        8,
        16,
        30,
        12,
        345678,
        tzinfo=timezone(timedelta(hours=8)),
    )

    validated = validate_field_value(
        "return_report", "return_report_v1", "return_date", source
    )

    assert validated == datetime(2026, 8, 8, 8, 30, 12, 345678, tzinfo=UTC)
    assert field_value_to_database(validated) == datetime(2026, 8, 8, 8, 30, 12, 345678)


@pytest.mark.parametrize(
    "value",
    [
        None,
        '买家留言,第一行\r\nsecond line says "quoted"',
        -42,
        Decimal("-0.0012300"),
        datetime(2026, 8, 8, 8, 30, 12, 345678, tzinfo=UTC),
    ],
)
def test_field_value_codec_round_trips_without_loss(value: object) -> None:
    encoded = encode_field_value(value)
    serialised = dumps_field_value(value)

    assert decode_field_value(encoded) == value
    assert loads_field_value(serialised) == value
    assert "买家留言" in serialised if isinstance(value, str) else True


def test_row_validation_requires_exact_whitelisted_fields() -> None:
    with pytest.raises(FieldValueError, match="missing"):
        validate_row_values(
            "return_report",
            "return_report_v1",
            (("quantity", 1),),
            require_all=True,
        )

    with pytest.raises(FieldValueError, match="unknown"):
        validate_row_values(
            "return_report",
            "return_report_v1",
            (("not_a_column", "value"),),
            require_all=False,
        )


def test_added_row_validation_rejects_blank_required_business_fields() -> None:
    contract = get_report_field_contract("business_report", "business_report_v1")
    values: dict[str, object] = {field.name: None for field in contract.fields}
    values.update(
        {
            "child_asin": "   ",
            "sku": "SKU-1",
            "currency_code": "USD",
        }
    )

    with pytest.raises(FieldValueError, match="child_asin"):
        validate_added_row_values(
            "business_report",
            "business_report_v1",
            values,
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("return_date", None),
        ("order_id", ""),
        ("sku", "   "),
        ("asin", None),
        ("quantity", 0),
        ("detailed_disposition", ""),
        ("reason", None),
        ("status", ""),
    ],
)
def test_added_return_row_requires_all_publishable_identity_fields(
    field_name: str,
    invalid_value: object,
) -> None:
    values: dict[str, object] = {
        "return_date": datetime(2026, 8, 8, 8, 30, tzinfo=UTC),
        "order_id": "ORDER-1",
        "sku": "SKU-1",
        "asin": "ASIN-1",
        "fnsku": None,
        "product_name": None,
        "quantity": 1,
        "fulfillment_center_id": None,
        "detailed_disposition": "SELLABLE",
        "reason": "REASON",
        "status": "STATUS",
        "license_plate_number": None,
        "customer_comments": None,
    }
    values[field_name] = invalid_value

    with pytest.raises(FieldValueError, match=field_name):
        validate_added_row_values(
            "return_report",
            "return_report_v1",
            values,
        )
