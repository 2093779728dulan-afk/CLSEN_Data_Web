# ruff: noqa: RUF001
"""Task-owned manual workbook metrics; original reports and stock keep their writers."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, cast

from app.api.errors import ApiError
from app.catalog.normalization import catalog_identity_key_v1


def load_workbook_metrics(
    settings: Any,
    context: Any,
    engine: Any,
    catalog: dict[str, Any],
    scope: dict[str, Any],
) -> dict[str, Any] | None:
    if not settings.production_inventory_source_root:
        return None
    path = (
        Path(settings.production_inventory_source_root) / "inventory-metric-source.json"
    )
    if not path.is_file():
        return None
    raw = path.read_bytes()
    source = cast(dict[str, Any], json.loads(raw))
    if (
        source.get("schema") != "inventory-metric-source-v1"
        or source.get("database") != engine.url.database
        or not str(engine.url.database).startswith("clsen_data_test_")
        or str(source.get("site_id")) != str(context.site_id)
    ):
        raise ApiError(409, "sheet_source_scope_invalid", "总表资料与本地站点不一致。")
    if any(str(source["scope"][key]) != str(scope[key]) for key in source["scope"]):
        return None
    for sku, row in source["rows"].items():
        current = catalog.get(sku)
        if current is None:
            continue
        if current.get("status") != "active" or any(
            catalog_identity_key_v1(str(current[key])).utf8
            != catalog_identity_key_v1(str(value)).utf8
            for key, value in row["identity"].items()
        ):
            raise ApiError(
                409,
                "sheet_source_catalog_changed",
                "总表资料中的商品身份已变化，请重新核对。",
            )
    source["rows"] = {k: v for k, v in source["rows"].items() if k in catalog}
    source["digest"] = hashlib.sha256(raw).hexdigest()
    source["_dates"] = {
        k: {day for day in v if day <= source["cutoff_on"]}
        for k, v in source["calendar"].items()
    }
    source["_coverage"] = {}
    return source


def merge_workbook_reports(
    reports: dict[str, Any],
    source: dict[str, Any] | None,
    as_of: date,
) -> dict[str, Any]:
    if source is None:
        return reports
    result = dict(reports)
    for kind, metric in [("business", "units"), ("returns", "returns")]:
        dates = source["_dates"][metric]
        result[kind] = [
            r
            for r in reports[kind]
            if not (
                str(r["sku_id"]) in source["rows"] and str(r["metric_date"]) in dates
            )
        ]
        result[kind].extend(
            {"sku_id": sku, "metric_date": day, metric: values[metric]}
            for sku, row in source["rows"].items()
            for day, values in row["daily"].items()
            if day in dates and day <= as_of.isoformat() and values[metric]
        )
    result["unresolved"] = [
        r
        for r in reports.get("unresolved", [])
        if not (
            str(r["sku_id"]) in source["rows"]
            and str(r["metric_date"]) in source["_dates"]["returns"]
        )
    ]
    result["_workbook_metrics"] = source
    result["provenance"] = {
        **reports.get("provenance", {}),
        "manual_workbook": {
            k: source[k]
            for k in (
                "source_filename",
                "source_sha256",
                "sheet",
                "cutoff_on",
                "digest",
                "source_kind",
            )
        },
    }
    covered = [
        day
        for days in source["calendar"].values()
        for day in days
        if day <= as_of.isoformat()
    ]
    if covered:
        result["read_from"] = min(
            str(reports.get("read_from") or min(covered)), min(covered)
        )
    return result


def workbook_quantity(
    report: dict[str, Any],
    days: dict[tuple[str, str], dict[str, int]],
    sku: str,
    span: dict[str, str],
    metric: str,
) -> dict[str, Any] | None:
    source = report.get("_workbook_metrics")
    if (
        source is None
        or sku not in source["rows"]
        or sku in report.get("blocked_sku_ids", [])
    ):
        return None
    key = (span["start"], span["end"], metric)
    coverage = source["_coverage"]
    if key not in coverage:
        kind = "business_report" if metric == "units" else "return_report"
        dates = source["_dates"][metric] | {
            str(r["report_date"])
            for r in report["members"]
            if r["report_type"] == kind and r["report_status"] == "published"
        }
        count = sum(span["start"] <= day <= span["end"] for day in dates)
        expected = (
            date.fromisoformat(span["end"]) - date.fromisoformat(span["start"])
        ).days + 1
        coverage[key] = (count, expected)
    count, expected = coverage[key]
    value = sum(
        v[metric]
        for (row_sku, day), v in days.items()
        if row_sku == sku and span["start"] <= day <= span["end"]
    )
    state = (
        "missing_report"
        if count == 0
        else "indeterminate"
        if metric == "returns"
        else "partial"
        if count < expected
        else "ready"
    )
    return {
        "value": str(value) if count else None,
        "state": state,
        "partial": state != "ready",
        "reason": (
            "人工总表按列日期替换同SKU同日数量，保留原始来源；"
            "不等同日报发布或实物退回入账"
        ),
        "observed_days": count,
        "expected_days": expected,
    }


def workbook_adjustments(
    source: dict[str, Any] | None,
    sku: str,
    as_of: date,
    values: dict[str, Any],
    records: dict[str, Any],
) -> None:
    if (
        source is None
        or as_of.isoformat() < source["cutoff_on"]
        or sku not in source["rows"]
    ):
        return
    row = source["rows"][sku]
    for key, value in row["adjustments"].items():
        values[key] = {
            "value": str(value),
            "state": "ready",
            "partial": False,
            "reason": "人工总表截至"
            + source["cutoff_on"]
            + "的累计调整；未新增库存事务",
        }
    records["workbook_adjustments"] = [
        {
            **r,
            "date": source["cutoff_on"],
            "source": source["source_filename"],
            "sheet": source["sheet"],
        }
        for r in row["adjustment_records"]
    ]
