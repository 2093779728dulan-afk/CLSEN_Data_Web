# ruff: noqa: RUF001 -- Chinese source diagnostics.
"""Exact SKU intake rules and current-catalog status; never creates identities."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.api.errors import ApiError
from app.catalog.source_formatting import canonical_standard_size

SKU_POLICY = "style-color-size-v1"
SIZES = {
    "XXXS",
    "XXS",
    "XS",
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "XXXL",
    "XXXXL",
    "2XL",
    "3XL",
    "4XL",
    "5XL",
    "6XL",
}


def strict_spec(raw: str) -> tuple[str, str, str] | None:
    parts = raw.split("-")
    if len(parts) != 3:
        return None
    style, color, size = parts
    if (
        not re.fullmatch(r"[0-9]+", style)
        or not re.fullmatch(r"[A-Z][a-z]*(?: [A-Z][a-z]*)*", color)
        or size not in SIZES
    ):
        return None
    return style, color, canonical_standard_size(size)


def check_source_rows(rows: list[dict[str, Any]]) -> None:
    colors = Counter(
        row["seller_sku"].split("-")[1]
        for row in rows
        if strict_spec(row["seller_sku"])
    )
    for row in rows:
        raw = row["seller_sku"]
        cell = row.get("cell_locations", {}).get("seller_sku", f"第{row['row']}行")
        row["format_issues"] = []

        def issue(
            code: str,
            message: str,
            *,
            row: dict[str, Any] = row,
            cell: str = cell,
            raw: str = raw,
        ) -> None:
            row["format_issues"].append(
                {
                    "sheet": row["sheet"],
                    "row": row["row"],
                    "cell": cell,
                    "field": "SKU",
                    "code": code,
                    "severity": "warning"
                    if code == "SKU_COLOR_SPELLING_REVIEW"
                    else "error",
                    "original": raw,
                    "message": message,
                }
            )

        if re.fullmatch(r"[0-9]+", raw) and row.get("cell_types", {}).get(
            "seller_sku"
        ) in {"s", "n"}:
            row["suggested_type"] = "parent"
            row["suggestion"] = None
            # The user explicitly treats numeric style-only lines as parent evidence.
            row["issues"] = [
                value
                for value in row["issues"]
                if not (
                    f"{cell[: -len(str(row['row']))]}列" in value and "前导零" in value
                )
            ]
            continue
        if raw != raw.strip() or any(c.isspace() and c != " " for c in raw):
            issue(
                "SKU_WHITESPACE",
                "SKU含首尾空格或不可见空白，请按原编码核对后重新输入。",
            )
        parts = raw.split("-")
        if len(parts) != 3:
            issue(
                "SKU_STRUCTURE",
                "须为款号-颜色-尺码，使用两个半角连字符，例如1101-Navy-L。",
            )
        else:
            style, color, size = parts
            if not re.fullmatch(r"[0-9]+", style):
                issue("SKU_STYLE", "款号须在第一段并为半角数字；保留前导零。")
            if color in SIZES and size not in SIZES:
                issue(
                    "SKU_COMPONENT_ORDER",
                    "颜色和尺码的顺序疑似颠倒，应为款号-颜色-尺码。",
                )
            if not re.fullmatch(r"[A-Z][a-z]*(?: [A-Z][a-z]*)*", color):
                issue(
                    "SKU_COLOR_CASE",
                    "颜色每个英文单词须首字母大写，其余小写；词间保留一个半角空格。",
                )
            if size not in SIZES:
                issue(
                    "SKU_SIZE_CASE" if size.upper() in SIZES else "SKU_SIZE_INVALID",
                    "尺码须使用明确的大写标准尺码；XLL等未确认写法不能自动纠正。",
                )
            if colors[color] == 1:
                alternatives = [
                    other
                    for other, count in colors.items()
                    if count >= 3
                    and len(other) == len(color)
                    and sum(a != b for a, b in zip(other, color, strict=True)) == 1
                ]
                if alternatives:
                    issue(
                        "SKU_COLOR_SPELLING_REVIEW",
                        f"颜色拼写疑似与本表常见写法{'、'.join(sorted(alternatives))}不一致，请核对原始商品；系统不自动改码。",
                    )
        parsed = strict_spec(raw)
        row["suggested_type"] = "variant" if parsed else "unknown"
        row["suggestion"] = (
            dict(zip(("style_code", "color", "size"), parsed, strict=True))
            if parsed
            else None
        )


def registration_status(
    rows: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    bindings: dict[str, int],
) -> list[dict[str, Any]]:
    result = []
    for raw in rows:
        row = dict(raw)
        candidates: list[dict[str, Any]]
        if any(
            i.get("severity") != "warning" for i in row.get("format_issues", [])
        ) or row.get("issues"):
            state, candidates = "error", []
        elif row.get("suggested_type") == "parent":
            state, candidates = "parent", []
        else:
            spec = dict(row.get("suggestion") or {})
            if isinstance(spec.get("size"), str):
                spec["size"] = canonical_standard_size(spec["size"])
                row["suggestion"] = spec
            matches = [
                sku
                for sku in inventory
                if sku.get("internal_display_sku") == row["seller_sku"]
                or (
                    str(sku.get("style_code")),
                    str(sku.get("standard_color")),
                    str(sku.get("standard_size")),
                )
                == (spec.get("style_code"), spec.get("color"), spec.get("size"))
            ]
            mapped = {
                str(m["sku_id"])
                for m in mappings
                if m["report_source_scope_id"] == bindings.get(row["sheet"])
                and m["seller_sku"] == row["seller_sku"]
            }
            candidates = list(
                {
                    str(sku["sku_id"]): sku
                    for sku in inventory
                    if sku in matches or str(sku["sku_id"]) in mapped
                }.values()
            )
            if len(candidates) > 1:
                state = "conflict"
            elif candidates:
                sku = candidates[0]
                actual = (
                    sku["style_code"],
                    sku["standard_color"],
                    sku["standard_size"],
                )
                expected = (spec.get("style_code"), spec.get("color"), spec.get("size"))
                state = (
                    "conflict"
                    if actual != expected
                    else "registered"
                    if sku["status"] in {"enabled", "active"}
                    else "disabled"
                )
            else:
                state = (
                    "needs_review"
                    if row.get("format_issues")
                    else "missing"
                    if spec
                    else "error"
                )
        row["registration"] = {
            "state": state,
            "sku_id": candidates[0]["sku_id"] if len(candidates) == 1 else None,
        }
        result.append(row)
    return result


def assert_strict_source(source: dict[str, Any], selections: list[Any]) -> None:
    if source.get("sku_format_policy") != SKU_POLICY:
        return
    issues = [
        issue
        for row in source["listing_rows"]
        for issue in row.get("format_issues", [])
        if issue.get("severity") != "warning"
    ]
    if issues:
        raise ApiError(
            422,
            "listing_sku_format_invalid",
            "请修改原表后重新上传：\n"
            + "\n".join(
                f"{i['sheet']}!{i['cell']}（{i['code']}）：{i['message']}"
                for i in issues[:50]
            ),
        )
    by_id = {row["row_id"]: row for row in source["listing_rows"]}
    for selection in selections:
        if not selection.include or selection.row_id not in by_id:
            continue
        raw = by_id[selection.row_id]
        if (
            any(i.get("severity") == "warning" for i in raw.get("format_issues", []))
            and not selection.note.strip()
        ):
            raise ApiError(
                422,
                "listing_sku_warning_unreviewed",
                f"{raw['sheet']}第{raw['row']}行：疑似颜色拼写请核对原表；确实无误时请记录人工核对依据，不自动改码。",
            )
        if raw.get("suggested_type") == "parent":
            valid = selection.record_type == "parent"
        else:
            spec = strict_spec(raw["seller_sku"])
            valid = selection.record_type == "variant" and spec == (
                selection.style_code,
                selection.color,
                selection.size,
            )
        if not valid:
            raise ApiError(
                422,
                "listing_sku_source_mismatch",
                f"{raw['sheet']}第{raw['row']}行：候选须与原SKU的款号、颜色、标准尺码及类型一致（XXXL按3XL）；编码错误请修改原表后重传。",
            )


def prefill_source_code(
    payload: dict[str, Any], raw: str, source_name: str
) -> dict[str, Any]:
    if payload.get("system_sku_id"):
        return payload
    return {
        **payload,
        "internal_display_sku": raw,
        "code_status": "confirmed",
        "code_evidence": f"{source_name}：原SKU经本批人工核对，批准前仍为候选。",
    }
