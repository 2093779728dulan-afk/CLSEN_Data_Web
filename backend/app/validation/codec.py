"""Canonical, lossless JSON encoding for typed field values and event payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from .fields import FieldValue, FieldValueError

_TYPE_KEY = "type"
_VALUE_KEY = "value"


def encode_field_value(value: object) -> dict[str, object]:
    if value is None:
        return {_TYPE_KEY: "null", _VALUE_KEY: None}
    if isinstance(value, bool):
        raise FieldValueError("boolean is not a supported field value")
    if isinstance(value, str):
        return {_TYPE_KEY: "text", _VALUE_KEY: value}
    if isinstance(value, int):
        return {_TYPE_KEY: "integer", _VALUE_KEY: value}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise FieldValueError("decimal field value must be finite")
        return {_TYPE_KEY: "decimal", _VALUE_KEY: str(value)}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise FieldValueError("datetime field value must be timezone-aware")
        canonical = (
            value.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        return {_TYPE_KEY: "utc_datetime", _VALUE_KEY: canonical}
    raise FieldValueError("unsupported field value type")


def decode_field_value(payload: object) -> FieldValue:
    if not isinstance(payload, Mapping):
        raise FieldValueError("field value payload must be an object")
    if set(payload) != {_TYPE_KEY, _VALUE_KEY}:
        raise FieldValueError("field value payload has an invalid shape")
    kind = payload[_TYPE_KEY]
    value = payload[_VALUE_KEY]
    if kind == "null":
        if value is not None:
            raise FieldValueError("null field value must contain null")
        return None
    if kind == "text":
        if not isinstance(value, str):
            raise FieldValueError("text field value must contain text")
        return value
    if kind == "integer":
        integer_value: object = value
        if isinstance(integer_value, bool) or not isinstance(integer_value, int):
            raise FieldValueError("integer field value must contain an integer")
        return integer_value
    if kind == "decimal":
        if not isinstance(value, str):
            raise FieldValueError("decimal field value must contain text")
        try:
            parsed_decimal = Decimal(value)
        except InvalidOperation as error:
            raise FieldValueError("decimal field value is invalid") from error
        if not parsed_decimal.is_finite():
            raise FieldValueError("decimal field value must be finite")
        return parsed_decimal
    if kind == "utc_datetime":
        if not isinstance(value, str) or not value.endswith("Z"):
            raise FieldValueError("UTC datetime field value is invalid")
        try:
            parsed_datetime = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as error:
            raise FieldValueError("UTC datetime field value is invalid") from error
        return parsed_datetime.astimezone(UTC)
    raise FieldValueError("field value payload has an unsupported type")


def dumps_field_value(value: object) -> str:
    return json.dumps(
        encode_field_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FieldValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def loads_field_value(serialised: str) -> FieldValue:
    try:
        payload = json.loads(serialised, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, TypeError) as error:
        raise FieldValueError("field value is not valid JSON") from error
    return decode_field_value(cast(object, payload))
