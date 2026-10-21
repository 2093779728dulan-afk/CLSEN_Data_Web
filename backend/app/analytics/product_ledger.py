"""Published-only product ledger grouped by strict style code."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, cast

import sqlalchemy as sa
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.analytics.models import (
    ProductCardResponse,
    ProductCardSummary,
    ProductLedgerResponse,
    ProductLedgerRow,
    ProductLedgerSort,
    ProductNameStatus,
    ProductTrendPoint,
    ProductVariant,
    SortDirection,
)
from app.analytics.product_identity import parse_seller_sku
from app.analytics.service import PublishedAnalyticsQueryService, _date_range


@dataclass(slots=True)
class _VariantAccumulator:
    seller_sku: str
    color: str
    size: str
    asins: set[str] = field(default_factory=set)
    fnskus: set[str] = field(default_factory=set)
    latest_name: tuple[date, datetime, str] | None = None

    def add_name(
        self, report_date: date, published_at: datetime, value: object
    ) -> None:
        name = _optional_text(value)
        if name is None:
            return
        candidate = (report_date, published_at, name)
        if self.latest_name is None or candidate[:2] > self.latest_name[:2]:
            self.latest_name = candidate


@dataclass(slots=True)
class _TrendAccumulator:
    sales: Decimal = Decimal(0)
    units_ordered: int = 0
    sessions: int = 0
    return_quantity: int = 0


@dataclass(slots=True)
class _ProductAccumulator:
    row_kind: Literal["product", "unclassified"]
    style_code: str | None
    unclassified_sku: str | None
    sales: Decimal = Decimal(0)
    units_ordered: int = 0
    sessions: int = 0
    return_quantity: int = 0
    published_days: set[date] = field(default_factory=set)
    latest_published_date: date | None = None
    variants: dict[str, _VariantAccumulator] = field(default_factory=dict)
    trend: dict[date, _TrendAccumulator] = field(
        default_factory=lambda: defaultdict(_TrendAccumulator)
    )

    def touch_date(self, report_date: date) -> None:
        self.published_days.add(report_date)
        if (
            self.latest_published_date is None
            or report_date > self.latest_published_date
        ):
            self.latest_published_date = report_date


class ProductLedgerQueryService:
    """Aggregate product styles from current business and return publications."""

    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session
        self._published = PublishedAnalyticsQueryService(database_session)

    def ledger(
        self,
        from_date: date,
        to_date: date,
        *,
        search: str | None,
        sort: ProductLedgerSort,
        direction: SortDirection,
        page: int,
        page_size: int,
    ) -> ProductLedgerResponse:
        requested_range = _date_range(from_date, to_date)
        if page < 1 or not 1 <= page_size <= 200:
            raise ValueError("invalid product ledger page")
        products = self._load_products(from_date, to_date)
        rows = [self._to_row(product) for product in products.values()]
        needle = (search or "").strip().casefold()
        if needle:
            rows = [
                row
                for row in rows
                if needle in self._search_text(products[_row_key(row)])
            ]
        rows.sort(key=lambda row: _stable_row_key(row))
        rows.sort(
            key=lambda row: _sort_value(row, sort),
            reverse=direction == "desc",
        )
        total_rows = len(rows)
        start = (page - 1) * page_size
        publications, site_configs = self._references(from_date, to_date)
        return ProductLedgerResponse(
            range=requested_range,
            rows=rows[start : start + page_size],
            total_rows=total_rows,
            page=page,
            page_size=page_size,
            sort=sort,
            direction=direction,
            publications=publications,
            site_config_versions=site_configs,
        )

    def product_card(
        self,
        style_code: str,
        from_date: date,
        to_date: date,
    ) -> ProductCardResponse | None:
        requested_range = _date_range(from_date, to_date)
        if not style_code.isascii() or not style_code.isdigit():
            raise ValueError("style_code must contain only ASCII digits")
        product = self._load_products(from_date, to_date).get(("product", style_code))
        if product is None:
            return None
        names = _variant_names(product)
        product_name, name_status = _name_result(names)
        variants = [
            ProductVariant(
                seller_sku=variant.seller_sku,
                color=variant.color,
                size=variant.size,
                product_name=(
                    variant.latest_name[2] if variant.latest_name is not None else None
                ),
                asins=sorted(variant.asins),
                fnskus=sorted(variant.fnskus),
            )
            for variant in sorted(
                product.variants.values(),
                key=lambda item: (
                    item.color.casefold(),
                    item.size.casefold(),
                    item.seller_sku,
                ),
            )
        ]
        trend = []
        for ordinal in range(from_date.toordinal(), to_date.toordinal() + 1):
            report_date = date.fromordinal(ordinal)
            value = product.trend.get(report_date, _TrendAccumulator())
            trend.append(
                ProductTrendPoint(
                    report_date=report_date,
                    sales=_decimal_text(value.sales),
                    units_ordered=value.units_ordered,
                    sessions=value.sessions,
                    conversion_rate=_conversion(value.units_ordered, value.sessions),
                    return_quantity=value.return_quantity,
                )
            )
        publications, site_configs = self._references(from_date, to_date)
        return ProductCardResponse(
            range=requested_range,
            style_code=style_code,
            product_name=product_name,
            name_status=name_status,
            summary=ProductCardSummary(
                sales=_decimal_text(product.sales),
                units_ordered=product.units_ordered,
                sessions=product.sessions,
                conversion_rate=_conversion(product.units_ordered, product.sessions),
                return_quantity=product.return_quantity,
                published_days=len(product.published_days),
            ),
            latest_published_date=product.latest_published_date,
            trend=trend,
            variants=variants,
            publications=publications,
            site_config_versions=site_configs,
        )

    def _load_products(
        self,
        from_date: date,
        to_date: date,
    ) -> dict[tuple[str, str], _ProductAccumulator]:
        products: dict[tuple[str, str], _ProductAccumulator] = {}
        parameters = {"from_date": from_date, "to_date": to_date}
        business_rows = self._database_session.execute(
            sa.text(
                """
                SELECT datasets.report_date, publications.published_at,
                       report_rows.sku, report_rows.child_asin AS asin,
                       report_rows.title AS product_name,
                       report_rows.ordered_product_sales AS sales,
                       report_rows.units_ordered, report_rows.sessions_total AS sessions
                FROM daily_datasets AS datasets
                INNER JOIN dataset_publications AS publications
                    ON publications.dataset_id = datasets.id
                INNER JOIN version_rows AS version_rows
                    ON version_rows.version_id = publications.version_id
                   AND version_rows.row_state = 'active'
                INNER JOIN business_report_rows AS report_rows
                    ON report_rows.version_row_id = version_rows.id
                   AND report_rows.version_id = publications.version_id
                WHERE datasets.report_type = 'business_report'
                  AND datasets.report_date BETWEEN :from_date AND :to_date
                """
            ),
            parameters,
        ).mappings()
        for row in business_rows:
            product, variant = self._resolve_product(products, row)
            report_date = cast(date, row["report_date"])
            product.touch_date(report_date)
            product.sales += Decimal(str(row["sales"] or 0))
            product.units_ordered += int(row["units_ordered"] or 0)
            product.sessions += int(row["sessions"] or 0)
            day = product.trend[report_date]
            day.sales += Decimal(str(row["sales"] or 0))
            day.units_ordered += int(row["units_ordered"] or 0)
            day.sessions += int(row["sessions"] or 0)
            if variant is not None:
                _add_optional(variant.asins, row["asin"])
                variant.add_name(
                    report_date,
                    cast(datetime, row["published_at"]),
                    row["product_name"],
                )

        return_rows = self._database_session.execute(
            sa.text(
                """
                SELECT datasets.report_date, publications.published_at,
                       report_rows.sku, report_rows.asin, report_rows.fnsku,
                       report_rows.product_name, report_rows.quantity
                FROM daily_datasets AS datasets
                INNER JOIN dataset_publications AS publications
                    ON publications.dataset_id = datasets.id
                INNER JOIN version_rows AS version_rows
                    ON version_rows.version_id = publications.version_id
                   AND version_rows.row_state = 'active'
                INNER JOIN return_report_rows AS report_rows
                    ON report_rows.version_row_id = version_rows.id
                   AND report_rows.version_id = publications.version_id
                WHERE datasets.report_type = 'return_report'
                  AND datasets.report_date BETWEEN :from_date AND :to_date
                """
            ),
            parameters,
        ).mappings()
        for row in return_rows:
            product, variant = self._resolve_product(products, row)
            report_date = cast(date, row["report_date"])
            product.touch_date(report_date)
            quantity = int(row["quantity"] or 0)
            product.return_quantity += quantity
            product.trend[report_date].return_quantity += quantity
            if variant is not None:
                _add_optional(variant.asins, row["asin"])
                _add_optional(variant.fnskus, row["fnsku"])
                variant.add_name(
                    report_date,
                    cast(datetime, row["published_at"]),
                    row["product_name"],
                )
        return products

    @staticmethod
    def _resolve_product(
        products: dict[tuple[str, str], _ProductAccumulator],
        row: RowMapping,
    ) -> tuple[_ProductAccumulator, _VariantAccumulator | None]:
        seller_sku = _optional_text(row["sku"])
        identity = parse_seller_sku(seller_sku)
        if identity is None:
            identifier = seller_sku or "<missing>"
            key = ("unclassified", identifier)
            return products.setdefault(
                key,
                _ProductAccumulator(
                    row_kind="unclassified",
                    style_code=None,
                    unclassified_sku=seller_sku,
                ),
            ), None
        key = ("product", identity.style_code)
        product = products.setdefault(
            key,
            _ProductAccumulator(
                row_kind="product",
                style_code=identity.style_code,
                unclassified_sku=None,
            ),
        )
        variant = product.variants.setdefault(
            identity.seller_sku,
            _VariantAccumulator(
                seller_sku=identity.seller_sku,
                color=identity.color,
                size=identity.size,
            ),
        )
        return product, variant

    def _references(
        self, from_date: date, to_date: date
    ) -> tuple[list[Any], list[Any]]:
        publications = self._published.publication_references(
            from_date,
            to_date,
            report_types=("business_report", "return_report"),
        )
        site_configs = self._published.site_configuration_references(
            {reference.site_id for reference in publications}
        )
        return publications, site_configs

    @staticmethod
    def _to_row(product: _ProductAccumulator) -> ProductLedgerRow:
        names = _variant_names(product)
        product_name, name_status = _name_result(names)
        return ProductLedgerRow(
            row_kind=product.row_kind,
            style_code=product.style_code,
            unclassified_sku=product.unclassified_sku,
            product_name=product_name,
            name_status=name_status,
            variant_count=len(product.variants),
            color_count=len({item.color for item in product.variants.values()}),
            size_count=len({item.size for item in product.variants.values()}),
            sales=_decimal_text(product.sales),
            units_ordered=product.units_ordered,
            sessions=product.sessions,
            conversion_rate=_conversion(product.units_ordered, product.sessions),
            return_quantity=product.return_quantity,
            published_days=len(product.published_days),
            latest_published_date=product.latest_published_date,
        )

    @staticmethod
    def _search_text(product: _ProductAccumulator) -> str:
        values = [product.style_code or "", product.unclassified_sku or ""]
        for variant in product.variants.values():
            values.extend((variant.seller_sku, variant.color, variant.size))
            values.extend(variant.asins)
            values.extend(variant.fnskus)
            if variant.latest_name is not None:
                values.append(variant.latest_name[2])
        return "\n".join(values).casefold()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _add_optional(target: set[str], value: object) -> None:
    text = _optional_text(value)
    if text is not None:
        target.add(text)


def _variant_names(product: _ProductAccumulator) -> set[str]:
    return {
        item.latest_name[2]
        for item in product.variants.values()
        if item.latest_name is not None
    }


def _name_result(names: set[str]) -> tuple[str | None, ProductNameStatus]:
    if not names:
        return None, "missing"
    if len(names) > 1:
        return None, "multiple"
    return next(iter(names)), "available"


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _conversion(units: int, sessions: int) -> str | None:
    return _decimal_text(Decimal(units) / Decimal(sessions)) if sessions else None


def _row_key(row: ProductLedgerRow) -> tuple[str, str]:
    return (
        row.row_kind,
        row.style_code or row.unclassified_sku or "<missing>",
    )


def _stable_row_key(row: ProductLedgerRow) -> tuple[int, str]:
    return (
        0 if row.row_kind == "product" else 1,
        (row.style_code or row.unclassified_sku or "").casefold(),
    )


def _sort_value(row: ProductLedgerRow, sort: ProductLedgerSort) -> Any:
    values: dict[ProductLedgerSort, Any] = {
        "sales": Decimal(row.sales),
        "units_ordered": row.units_ordered,
        "sessions": row.sessions,
        "conversion_rate": (
            Decimal(row.conversion_rate)
            if row.conversion_rate is not None
            else Decimal(-1)
        ),
        "return_quantity": row.return_quantity,
        "published_days": row.published_days,
        "latest_published_date": row.latest_published_date or date.min,
        "style_code": (row.style_code or row.unclassified_sku or "").casefold(),
        "product_name": (row.product_name or "").casefold(),
    }
    return values[sort]
