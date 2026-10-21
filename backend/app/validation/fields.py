"""Frozen typed-field contracts shared by validation and review commands."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from app.imports.types import ReportType
from app.parsers.rules import REPORT_RULES

type FieldValue = str | int | Decimal | datetime | None

_MIN_SIGNED_BIGINT = -(2**63)
_MAX_SIGNED_BIGINT = 2**63 - 1


class FieldContractError(ValueError):
    """A report, ruleset, or field has no supported frozen contract."""


class FieldValueError(ValueError):
    """A typed value cannot be represented by its frozen field contract."""


class FieldValueKind(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    UTC_DATETIME = "utc_datetime"


@dataclass(frozen=True, slots=True)
class FieldContract:
    name: str
    kind: FieldValueKind
    nullable: bool = True
    editable: bool = True
    required_on_add: bool = False
    included_in_totals: bool = False
    max_length: int | None = None
    precision: int | None = None
    scale: int | None = None
    ascii_only: bool = False

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise ValueError("field contract name must be normalised")
        if self.max_length is not None and self.max_length < 1:
            raise ValueError("max_length must be positive")
        if (self.precision is None) != (self.scale is None):
            raise ValueError("decimal precision and scale must be provided together")
        if self.precision is not None:
            if self.kind is not FieldValueKind.DECIMAL:
                raise ValueError("only decimal fields may define precision")
            assert self.scale is not None
            if self.precision < 1 or self.scale < 0 or self.scale > self.precision:
                raise ValueError("invalid decimal precision or scale")


@dataclass(frozen=True, slots=True)
class ReportFieldContract:
    report_type: ReportType
    ruleset_version: str
    fields: tuple[FieldContract, ...]

    def __post_init__(self) -> None:
        if (
            not self.ruleset_version
            or self.ruleset_version != self.ruleset_version.strip()
        ):
            raise ValueError("ruleset_version must be normalised")
        names = tuple(field.name for field in self.fields)
        if not names or len(names) != len(set(names)):
            raise ValueError("report field names must be non-empty and unique")

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    def field(self, field_name: str) -> FieldContract:
        for contract in self.fields:
            if contract.name == field_name:
                return contract
        raise FieldContractError(
            f"unknown field {field_name!r} for report type {self.report_type!r}"
        )


def _text(
    name: str,
    max_length: int | None,
    *,
    editable: bool = True,
    ascii_only: bool = False,
    required_on_add: bool = False,
) -> FieldContract:
    return FieldContract(
        name=name,
        kind=FieldValueKind.TEXT,
        max_length=max_length,
        editable=editable,
        ascii_only=ascii_only,
        required_on_add=required_on_add,
    )


def _integer(name: str, *, required_on_add: bool = False) -> FieldContract:
    return FieldContract(
        name=name,
        kind=FieldValueKind.INTEGER,
        included_in_totals=True,
        required_on_add=required_on_add,
    )


def _decimal(
    name: str,
    *,
    precision: int,
    scale: int,
    included_in_totals: bool,
) -> FieldContract:
    return FieldContract(
        name=name,
        kind=FieldValueKind.DECIMAL,
        precision=precision,
        scale=scale,
        included_in_totals=included_in_totals,
    )


_BUSINESS_FIELDS = (
    _text("parent_asin", 32),
    _text("child_asin", 32, required_on_add=True),
    _text("title", None),
    _text("sku", 255, required_on_add=True),
    _integer("sessions_total"),
    _integer("sessions_b2b"),
    _decimal(
        "conversion_rate_total",
        precision=12,
        scale=9,
        included_in_totals=False,
    ),
    _decimal(
        "session_percentage_b2b",
        precision=12,
        scale=9,
        included_in_totals=False,
    ),
    _integer("page_views_total"),
    _integer("page_views_b2b"),
    _decimal(
        "page_view_percentage_total",
        precision=12,
        scale=9,
        included_in_totals=False,
    ),
    _decimal(
        "page_view_percentage_b2b",
        precision=12,
        scale=9,
        included_in_totals=False,
    ),
    _decimal(
        "featured_offer_percentage",
        precision=12,
        scale=9,
        included_in_totals=False,
    ),
    _decimal(
        "featured_offer_percentage_b2b",
        precision=12,
        scale=9,
        included_in_totals=False,
    ),
    _integer("units_ordered"),
    _integer("units_ordered_b2b"),
    _decimal(
        "unit_session_percentage",
        precision=12,
        scale=9,
        included_in_totals=False,
    ),
    _decimal(
        "unit_session_percentage_b2b",
        precision=12,
        scale=9,
        included_in_totals=False,
    ),
    _decimal(
        "ordered_product_sales",
        precision=20,
        scale=6,
        included_in_totals=True,
    ),
    _decimal(
        "ordered_product_sales_b2b",
        precision=20,
        scale=6,
        included_in_totals=True,
    ),
    _text("currency_code", 3, editable=False, ascii_only=True),
    _integer("total_order_items"),
    _integer("total_order_items_b2b"),
)

_RETURN_FIELDS = (
    FieldContract(
        "return_date",
        FieldValueKind.UTC_DATETIME,
        required_on_add=True,
    ),
    _text("order_id", 128, required_on_add=True),
    _text("sku", 255, required_on_add=True),
    _text("asin", 32, required_on_add=True),
    _text("fnsku", 64),
    _text("product_name", None),
    _integer("quantity", required_on_add=True),
    _text("fulfillment_center_id", 64),
    _text("detailed_disposition", 128, required_on_add=True),
    _text("reason", 255, required_on_add=True),
    _text("status", 128, required_on_add=True),
    _text("license_plate_number", 255),
    _text("customer_comments", None),
)


def _assert_parser_contracts_match() -> None:
    business_source_fields = tuple(
        field.target_name for field in REPORT_RULES["business_report"].fields
    )
    business_typed_fields = tuple(
        name
        for name in (field.name for field in _BUSINESS_FIELDS)
        if name != "currency_code"
    )
    return_source_fields = tuple(
        field.target_name for field in REPORT_RULES["return_report"].fields
    )
    if business_source_fields != business_typed_fields:
        raise RuntimeError("business validation fields drifted from parser rules")
    if return_source_fields != tuple(field.name for field in _RETURN_FIELDS):
        raise RuntimeError("return validation fields drifted from parser rules")


_assert_parser_contracts_match()

_REPORT_FIELD_CONTRACTS: Final[dict[tuple[ReportType, str], ReportFieldContract]] = {
    ("business_report", REPORT_RULES["business_report"].version): ReportFieldContract(
        report_type="business_report",
        ruleset_version=REPORT_RULES["business_report"].version,
        fields=_BUSINESS_FIELDS,
    ),
    ("return_report", REPORT_RULES["return_report"].version): ReportFieldContract(
        report_type="return_report",
        ruleset_version=REPORT_RULES["return_report"].version,
        fields=_RETURN_FIELDS,
    ),
}
REPORT_FIELD_CONTRACTS: Final[Mapping[tuple[ReportType, str], ReportFieldContract]] = (
    MappingProxyType(_REPORT_FIELD_CONTRACTS)
)


def get_report_field_contract(
    report_type: ReportType,
    ruleset_version: str,
) -> ReportFieldContract:
    try:
        return REPORT_FIELD_CONTRACTS[(report_type, ruleset_version)]
    except KeyError as error:
        raise FieldContractError(
            "unsupported report type and ruleset contract: "
            f"{report_type!r}, {ruleset_version!r}"
        ) from error


def get_field_contract(
    report_type: ReportType,
    ruleset_version: str,
    field_name: str,
) -> FieldContract:
    return get_report_field_contract(report_type, ruleset_version).field(field_name)


def _validate_decimal(value: Decimal, contract: FieldContract) -> Decimal:
    if not value.is_finite():
        raise FieldValueError(f"{contract.name} must be a finite decimal")
    assert contract.precision is not None
    assert contract.scale is not None
    integer_limit = Decimal(10) ** (contract.precision - contract.scale)
    if abs(value) >= integer_limit:
        raise FieldValueError(f"{contract.name} exceeds database precision")

    _sign, raw_digits, raw_exponent = value.as_tuple()
    if not isinstance(raw_exponent, int):
        raise FieldValueError(f"{contract.name} must be a finite decimal")
    digits = list(raw_digits)
    exponent = raw_exponent
    while exponent < 0 and digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    if -exponent > contract.scale:
        raise FieldValueError(f"{contract.name} exceeds database scale")
    return value


def _validate_against_contract(
    contract: FieldContract,
    value: object,
) -> FieldValue:
    if value is None:
        if not contract.nullable:
            raise FieldValueError(f"{contract.name} must not be null")
        return None
    if contract.kind is FieldValueKind.TEXT:
        if not isinstance(value, str):
            raise FieldValueError(f"{contract.name} must be text")
        if contract.max_length is not None and len(value) > contract.max_length:
            raise FieldValueError(f"{contract.name} exceeds maximum length")
        if contract.ascii_only:
            try:
                value.encode("ascii")
            except UnicodeEncodeError as error:
                raise FieldValueError(f"{contract.name} must be ASCII") from error
        return value
    if contract.kind is FieldValueKind.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise FieldValueError(f"{contract.name} must be an integer")
        if not _MIN_SIGNED_BIGINT <= value <= _MAX_SIGNED_BIGINT:
            raise FieldValueError(f"{contract.name} is outside signed BIGINT")
        return value
    if contract.kind is FieldValueKind.DECIMAL:
        if not isinstance(value, Decimal):
            raise FieldValueError(f"{contract.name} must be a Decimal")
        return _validate_decimal(value, contract)
    if not isinstance(value, datetime):
        raise FieldValueError(f"{contract.name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise FieldValueError(f"{contract.name} must be timezone-aware")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise FieldValueError(f"{contract.name} is outside datetime range") from error


def validate_field_value(
    report_type: ReportType,
    ruleset_version: str,
    field_name: str,
    value: object,
) -> FieldValue:
    """Validate storage shape and return its canonical in-process value.

    Editability is exposed on :class:`FieldContract` and is intentionally checked by
    the review command boundary, because validation must also read derived fields.
    """

    contract = get_field_contract(report_type, ruleset_version, field_name)
    return _validate_against_contract(contract, value)


def validate_row_values(
    report_type: ReportType,
    ruleset_version: str,
    values: Mapping[str, object] | Iterable[tuple[str, object]],
    *,
    require_all: bool,
) -> tuple[tuple[str, FieldValue], ...]:
    contract = get_report_field_contract(report_type, ruleset_version)
    items = tuple(values.items()) if isinstance(values, Mapping) else tuple(values)
    names = tuple(name for name, _value in items)
    if len(names) != len(set(names)):
        raise FieldValueError("row contains duplicate field names")
    unknown = sorted(set(names) - set(contract.field_names))
    if unknown:
        raise FieldValueError(f"row contains unknown fields: {', '.join(unknown)}")
    if require_all:
        missing = sorted(set(contract.field_names) - set(names))
        if missing:
            raise FieldValueError(f"row is missing fields: {', '.join(missing)}")

    by_name = dict(items)
    return tuple(
        (
            field.name,
            _validate_against_contract(field, by_name[field.name]),
        )
        for field in contract.fields
        if field.name in by_name
    )


def validate_added_row_values(
    report_type: ReportType,
    ruleset_version: str,
    values: Mapping[str, object] | Iterable[tuple[str, object]],
) -> tuple[tuple[str, FieldValue], ...]:
    """Validate the stricter structural contract for a manually added row."""

    contract = get_report_field_contract(report_type, ruleset_version)
    validated = validate_row_values(
        report_type,
        ruleset_version,
        values,
        require_all=True,
    )
    by_name = dict(validated)
    for field in contract.fields:
        if not field.required_on_add:
            continue
        value = by_name[field.name]
        if value is None or (isinstance(value, str) and not value.strip()):
            raise FieldValueError(
                f"{field.name} must not be empty on a manually added row"
            )
    if report_type == "return_report":
        quantity = by_name["quantity"]
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise FieldValueError(
                "quantity must be a positive integer on a manually added row"
            )
    return validated


def field_value_to_database(value: FieldValue) -> object:
    """Convert a canonical field value to the representation used by MySQL."""

    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None or value.utcoffset() is None:
        raise FieldValueError("database datetime value must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def as_field_value(value: object) -> FieldValue:
    """Narrow an already validated value for adapters with object-typed rows."""

    if value is None or isinstance(value, (str, Decimal, datetime)):
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        raise FieldValueError("object is not a supported field value")
    return value
