"""Canonical JSON encoder for the project's restricted RFC 8785 profile."""

from __future__ import annotations

import hashlib
from typing import Never, cast

from app.catalog.errors import CatalogCanonicalJsonError

type CanonicalScalar = bool | int | str | None
type CanonicalValue = CanonicalScalar | list[CanonicalValue] | dict[str, CanonicalValue]

_SHORT_ESCAPES = {
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
}


def _fail() -> Never:
    raise CatalogCanonicalJsonError()


def _validate_scalar_string(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        _fail()


def _encode_string(value: str) -> str:
    _validate_scalar_string(value)
    encoded: list[str] = ['"']
    for character in value:
        codepoint = ord(character)
        if character == '"':
            encoded.append('\\"')
        elif character == "\\":
            encoded.append("\\\\")
        elif codepoint in _SHORT_ESCAPES:
            encoded.append(_SHORT_ESCAPES[codepoint])
        elif codepoint <= 0x1F:
            encoded.append(f"\\u{codepoint:04x}")
        else:
            encoded.append(character)
    encoded.append('"')
    return "".join(encoded)


def _utf16_sort_key(value: str) -> bytes:
    _validate_scalar_string(value)
    return value.encode("utf-16-be")


def _encode(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _encode_string(value)
    if type(value) is list:
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if type(value) is dict:
        mapping = value
        if not all(isinstance(key, str) for key in mapping):
            _fail()
        keys = sorted(mapping, key=_utf16_sort_key)
        return (
            "{"
            + ",".join(f"{_encode_string(key)}:{_encode(mapping[key])}" for key in keys)
            + "}"
        )
    _fail()


def canonical_json_bytes(value: object) -> bytes:
    """Encode a closed JSON value domain without floats or host JSON behavior."""

    return _encode(value).encode("utf-8")


def canonical_sha256(value: object) -> str:
    """Return the content digest used by versioned canonical payloads."""

    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def assert_canonical_value(value: object) -> CanonicalValue:
    """Validate a runtime value while retaining its precise recursive type."""

    canonical_json_bytes(value)
    return cast("CanonicalValue", value)


__all__ = (
    "CanonicalValue",
    "assert_canonical_value",
    "canonical_json_bytes",
    "canonical_sha256",
)
