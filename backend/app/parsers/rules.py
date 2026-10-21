"""Frozen, versioned source schemas for the two supported report families."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from app.imports.types import ReportType
from app.parsers.types import FieldKind, SupportedEncoding


@dataclass(frozen=True, slots=True)
class FieldRule:
    source_name: str
    target_name: str
    kind: FieldKind


@dataclass(frozen=True, slots=True)
class ReportRule:
    report_type: ReportType
    version: str
    preferred_encoding: SupportedEncoding
    fields: tuple[FieldRule, ...]

    @property
    def source_header(self) -> tuple[str, ...]:
        return tuple(field.source_name for field in self.fields)

    @property
    def normalised_header(self) -> tuple[str, ...]:
        return tuple(name.strip() for name in self.source_header)


_BUSINESS_RULE = ReportRule(
    report_type="business_report",
    version="business_report_v1",
    preferred_encoding="utf-8-sig",
    fields=(
        FieldRule("（父）ASIN", "parent_asin", FieldKind.TEXT),  # noqa: RUF001
        FieldRule("（子）ASIN", "child_asin", FieldKind.TEXT),  # noqa: RUF001
        FieldRule("标题", "title", FieldKind.TEXT),
        FieldRule("SKU", "sku", FieldKind.TEXT),
        FieldRule("会话数 - 总计", "sessions_total", FieldKind.INTEGER),
        FieldRule("会话 - 总计 - B2B", "sessions_b2b", FieldKind.INTEGER),
        FieldRule(
            "转化率 - 总计",
            "conversion_rate_total",
            FieldKind.PERCENTAGE,
        ),
        FieldRule(
            "会话百分比 - 总计 - B2B",
            "session_percentage_b2b",
            FieldKind.PERCENTAGE,
        ),
        FieldRule("页面浏览量 - 总计 ", "page_views_total", FieldKind.INTEGER),
        FieldRule("页面浏览量 - 总计 - B2B", "page_views_b2b", FieldKind.INTEGER),
        FieldRule(
            "页面浏览量百分比 - 总计",
            "page_view_percentage_total",
            FieldKind.PERCENTAGE,
        ),
        FieldRule(
            "页面浏览量百分比 - 总计 - B2B",
            "page_view_percentage_b2b",
            FieldKind.PERCENTAGE,
        ),
        FieldRule(
            "推荐报价（推荐报价展示位）百分比 ",  # noqa: RUF001
            "featured_offer_percentage",
            FieldKind.PERCENTAGE,
        ),
        FieldRule(
            "推荐报价（推荐报价展示位）百分比 - B2B",  # noqa: RUF001
            "featured_offer_percentage_b2b",
            FieldKind.PERCENTAGE,
        ),
        FieldRule("已订购商品数量", "units_ordered", FieldKind.INTEGER),
        FieldRule("已订购商品数量 - B2B", "units_ordered_b2b", FieldKind.INTEGER),
        FieldRule(
            "商品会话百分比",
            "unit_session_percentage",
            FieldKind.PERCENTAGE,
        ),
        FieldRule(
            "商品会话百分比 - B2B",
            "unit_session_percentage_b2b",
            FieldKind.PERCENTAGE,
        ),
        FieldRule("已订购商品销售额", "ordered_product_sales", FieldKind.USD),
        FieldRule(
            "已订购商品销售额 - B2B",
            "ordered_product_sales_b2b",
            FieldKind.USD,
        ),
        FieldRule("订单商品总数", "total_order_items", FieldKind.INTEGER),
        FieldRule("订单商品总数 - B2B", "total_order_items_b2b", FieldKind.INTEGER),
    ),
)

_RETURN_RULE = ReportRule(
    report_type="return_report",
    version="return_report_v1",
    preferred_encoding="windows-1252",
    fields=(
        FieldRule("return-date", "return_date", FieldKind.EVENT_DATETIME),
        FieldRule("order-id", "order_id", FieldKind.TEXT),
        FieldRule("sku", "sku", FieldKind.TEXT),
        FieldRule("asin", "asin", FieldKind.TEXT),
        FieldRule("fnsku", "fnsku", FieldKind.TEXT),
        FieldRule("product-name", "product_name", FieldKind.TEXT),
        FieldRule("quantity", "quantity", FieldKind.INTEGER),
        FieldRule(
            "fulfillment-center-id",
            "fulfillment_center_id",
            FieldKind.TEXT,
        ),
        FieldRule(
            "detailed-disposition",
            "detailed_disposition",
            FieldKind.TEXT,
        ),
        FieldRule("reason", "reason", FieldKind.TEXT),
        FieldRule("status", "status", FieldKind.TEXT),
        FieldRule(
            "license-plate-number",
            "license_plate_number",
            FieldKind.TEXT,
        ),
        FieldRule("customer-comments", "customer_comments", FieldKind.TEXT),
    ),
)

REPORT_RULES: Final[Mapping[ReportType, ReportRule]] = MappingProxyType(
    {
        "business_report": _BUSINESS_RULE,
        "return_report": _RETURN_RULE,
    }
)
