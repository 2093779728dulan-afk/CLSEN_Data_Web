# ruff: noqa: RUF001 -- Chinese user-facing messages.
"""Formatting proposals for product labels, never for formal platform codes."""

import re
import unicodedata
from collections.abc import Iterable

from app.catalog.errors import CatalogNormalizationError
from app.catalog.normalization import catalog_identity_key_v1

FORMAT_REASON = "整理空格、全角英数字及大小写；已有主档优先沿用原标准写法。"


def canonical_standard_size(value: str) -> str:
    """Apply only the user-confirmed XXXL/3XL standard, without changing codes."""
    return "3XL" if value == "XXXL" else value


def _formatted(value: str, field: str) -> str:
    # Only width variants of ASCII and space separators; not arbitrary NFKC
    # compatibility characters. Controls remain for the input validator to reject.
    value = "".join(
        chr(ord(c) - 0xFEE0)
        if 0xFF01 <= ord(c) <= 0xFF5E
        else " "
        if unicodedata.category(c) == "Zs"
        else c
        for c in value
    )
    value = re.sub(" +", " ", value.strip(" "))
    if field == "color":
        return re.sub(r"[A-Za-z]+", lambda m: m[0].capitalize(), value)
    if field == "size":
        return canonical_standard_size(re.sub(r"[a-z]", lambda m: m[0].upper(), value))
    return value


def format_identity_field(
    value: str, field: str, known: Iterable[str] = ()
) -> tuple[str, str | None]:
    """Prefer a unique catalog spelling; ambiguous legacy identities need review."""
    if "\ufffd" in value:
        return value, "文字出现乱码，请核对原件或使用UTF-8编码。"
    if any(unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} for c in value):
        return value, "含换行、制表符或不可见字符，请核对原文后修改。"
    proposed = _formatted(value, field)
    try:
        key = catalog_identity_key_v1(proposed or "?").utf8
    except CatalogNormalizationError:
        return value, "含不支持的字符，请核对原始文字。"
    candidates = [
        v
        for v in known
        if catalog_identity_key_v1(_formatted(v, field) or "?").utf8 == key
    ]
    if len({catalog_identity_key_v1(v).utf8 for v in candidates}) > 1:
        return (
            value,
            "格式整理后对应多个主档写法，请核对原文并明确选择商品，不会自动合并。",
        )
    if field == "size" and "XXXL" in candidates:
        return value, "主档尺码仍为XXXL，请先按原SKU更正为3XL后再建档。"
    return (candidates[0] if candidates else proposed), None
