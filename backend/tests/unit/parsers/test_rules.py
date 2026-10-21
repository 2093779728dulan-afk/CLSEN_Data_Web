from __future__ import annotations

import pytest
from app.parsers.rules import REPORT_RULES


def test_business_rule_has_the_approved_22_field_mapping() -> None:
    rule = REPORT_RULES["business_report"]

    assert rule.version == "business_report_v1"
    assert len(rule.fields) == 22
    assert tuple(field.target_name for field in rule.fields) == (
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
        "total_order_items",
        "total_order_items_b2b",
    )


def test_return_rule_has_the_approved_13_field_mapping() -> None:
    rule = REPORT_RULES["return_report"]

    assert rule.version == "return_report_v1"
    assert len(rule.fields) == 13
    assert tuple(field.target_name for field in rule.fields) == (
        "return_date",
        "order_id",
        "sku",
        "asin",
        "fnsku",
        "product_name",
        "quantity",
        "fulfillment_center_id",
        "detailed_disposition",
        "reason",
        "status",
        "license_plate_number",
        "customer_comments",
    )


def test_rule_registry_and_rules_are_immutable() -> None:
    with pytest.raises(TypeError):
        REPORT_RULES["business_report"] = REPORT_RULES["return_report"]  # type: ignore[index]

    with pytest.raises(AttributeError):
        REPORT_RULES["business_report"].version = "changed"  # type: ignore[misc]


def test_headers_are_unique_after_supported_whitespace_normalisation() -> None:
    for rule in REPORT_RULES.values():
        normalised = tuple(header.strip() for header in rule.source_header)
        assert len(normalised) == len(set(normalised))
