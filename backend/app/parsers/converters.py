"""Strict scalar conversions used by report parsing."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.parsers.types import ParseError, ParseErrorCode

_HUNDRED = Decimal(100)
_MIN_SIGNED_BIGINT = -(2**63)
_MAX_SIGNED_BIGINT = 2**63 - 1
_USD_PATTERN = re.compile(
    r"US\$(?P<amount>[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?)\Z",
    re.ASCII,
)


def _decimal(value: str, *, label: str, code: ParseErrorCode) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ParseError(
            f"invalid {label}",
            code=code,
        ) from error
    if not parsed.is_finite():
        raise ParseError(
            f"invalid {label}: value must be finite",
            code=code,
        )
    return parsed


def _ensure_decimal_fits(
    value: Decimal,
    *,
    precision: int,
    scale: int,
    label: str,
    code: ParseErrorCode,
) -> Decimal:
    integer_limit = Decimal(10) ** (precision - scale)
    if abs(value) >= integer_limit:
        raise ParseError(
            f"invalid {label}: value exceeds database precision",
            code=code,
        )

    _sign, raw_digits, raw_exponent = value.as_tuple()
    if not isinstance(raw_exponent, int):
        raise AssertionError("a finite Decimal must have an integer exponent")
    digits = list(raw_digits)
    exponent = raw_exponent
    while exponent < 0 and digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    if -exponent > scale:
        raise ParseError(
            f"invalid {label}: value exceeds database scale",
            code=code,
        )
    return value


def parse_integer(raw_value: str) -> int:
    value = _decimal(raw_value.strip(), label="integer", code="invalid_integer")
    if value != value.to_integral_value():
        raise ParseError(
            "invalid integer: value is not integral",
            code="invalid_integer",
        )
    parsed = int(value)
    if not _MIN_SIGNED_BIGINT <= parsed <= _MAX_SIGNED_BIGINT:
        raise ParseError(
            "invalid integer: value is outside BIGINT",
            code="invalid_integer",
        )
    return parsed


def parse_usd(raw_value: str) -> Decimal:
    normalised = raw_value.strip()
    match = _USD_PATTERN.fullmatch(normalised)
    if match is None:
        raise ParseError(
            "invalid USD amount or thousands grouping",
            code="invalid_usd",
        )
    return _ensure_decimal_fits(
        _decimal(
            match.group("amount").replace(",", ""),
            label="USD amount",
            code="invalid_usd",
        ),
        precision=20,
        scale=6,
        label="USD amount",
        code="invalid_usd",
    )


def parse_percentage(raw_value: str) -> Decimal:
    normalised = raw_value.strip()
    if not normalised.endswith("%"):
        raise ParseError(
            "invalid percentage: percent suffix is required",
            code="invalid_percentage",
        )
    percentage = _decimal(
        normalised.removesuffix("%").strip(),
        label="percentage",
        code="invalid_percentage",
    )
    return _ensure_decimal_fits(
        percentage / _HUNDRED,
        precision=12,
        scale=9,
        label="percentage ratio",
        code="invalid_percentage",
    )


def _resolve_local_time(value: datetime, timezone: ZoneInfo) -> datetime:
    utc_candidates: set[datetime] = set()
    for fold in (0, 1):
        try:
            candidate = value.replace(tzinfo=timezone, fold=fold).astimezone(UTC)
            round_trip = candidate.astimezone(timezone).replace(tzinfo=None)
        except (OverflowError, ValueError) as error:
            raise ParseError(
                "invalid event datetime",
                code="invalid_datetime",
            ) from error
        if round_trip == value:
            utc_candidates.add(candidate)

    if not utc_candidates:
        raise ParseError(
            "event datetime is a nonexistent local time",
            code="nonexistent_local_time",
        )
    if len(utc_candidates) > 1:
        raise ParseError(
            "event datetime is an ambiguous local time",
            code="ambiguous_local_time",
        )
    return utc_candidates.pop()


def parse_event_datetime(
    raw_value: str,
    *,
    source_timezone: str | None,
) -> datetime:
    candidate = raw_value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise ParseError("invalid event datetime", code="invalid_datetime") from error

    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        try:
            return parsed.astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise ParseError(
                "invalid event datetime",
                code="invalid_datetime",
            ) from error
    if source_timezone is None:
        raise ParseError(
            "event datetime has no offset and no source timezone",
            code="missing_source_timezone",
        )
    try:
        timezone = ZoneInfo(source_timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ParseError(
            "source timezone is not a known IANA timezone",
            code="invalid_source_timezone",
        ) from error
    return _resolve_local_time(parsed, timezone)
