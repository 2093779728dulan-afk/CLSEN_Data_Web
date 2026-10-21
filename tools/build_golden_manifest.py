"""Build a deterministic, privacy-preserving manifest for the source CSV files.

This module deliberately depends only on Python's standard library and must not
import the application's future report parsers. It is the independent baseline
against which those parsers will be tested.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION: Final = 1
TOOL_VERSION: Final = "1.0.0"

BUSINESS_REPORT_HEADERS: Final = (
    "（父）ASIN",
    "（子）ASIN",
    "标题",
    "SKU",
    "会话数 - 总计",
    "会话 - 总计 - B2B",
    "转化率 - 总计",
    "会话百分比 - 总计 - B2B",
    "页面浏览量 - 总计 ",
    "页面浏览量 - 总计 - B2B",
    "页面浏览量百分比 - 总计",
    "页面浏览量百分比 - 总计 - B2B",
    "推荐报价（推荐报价展示位）百分比 ",
    "推荐报价（推荐报价展示位）百分比 - B2B",
    "已订购商品数量",
    "已订购商品数量 - B2B",
    "商品会话百分比",
    "商品会话百分比 - B2B",
    "已订购商品销售额",
    "已订购商品销售额 - B2B",
    "订单商品总数",
    "订单商品总数 - B2B",
)

RETURN_REPORT_HEADERS: Final = (
    "return-date",
    "order-id",
    "sku",
    "asin",
    "fnsku",
    "product-name",
    "quantity",
    "fulfillment-center-id",
    "detailed-disposition",
    "reason",
    "status",
    "license-plate-number",
    "customer-comments",
)

BUSINESS_NUMERIC_FIELDS: Final = {
    "会话数 - 总计": ("sessions_total", "integer"),
    "会话 - 总计 - B2B": ("sessions_b2b", "integer"),
    "页面浏览量 - 总计 ": ("page_views_total", "integer"),
    "页面浏览量 - 总计 - B2B": ("page_views_b2b", "integer"),
    "已订购商品数量": ("units_ordered_total", "integer"),
    "已订购商品数量 - B2B": ("units_ordered_b2b", "integer"),
    "已订购商品销售额": ("ordered_product_sales_total", "usd"),
    "已订购商品销售额 - B2B": ("ordered_product_sales_b2b", "usd"),
    "订单商品总数": ("order_items_total", "integer"),
    "订单商品总数 - B2B": ("order_items_b2b", "integer"),
}

BUSINESS_PERCENTAGE_FIELDS: Final = {
    "转化率 - 总计": "conversion_rate_total",
    "会话百分比 - 总计 - B2B": "sessions_percentage_b2b",
    "页面浏览量百分比 - 总计": "page_views_percentage_total",
    "页面浏览量百分比 - 总计 - B2B": "page_views_percentage_b2b",
    "推荐报价（推荐报价展示位）百分比 ": "featured_offer_percentage_total",
    "推荐报价（推荐报价展示位）百分比 - B2B": "featured_offer_percentage_b2b",
    "商品会话百分比": "unit_session_percentage_total",
    "商品会话百分比 - B2B": "unit_session_percentage_b2b",
}

RETURN_NUMERIC_FIELDS: Final = {
    "quantity": ("quantity", "integer"),
}

BUSINESS_IDENTITY_FIELDS: Final = ("（父）ASIN", "（子）ASIN", "SKU")
RETURN_IDENTITY_FIELDS: Final = (
    "return-date",
    "order-id",
    "sku",
    "asin",
    "fnsku",
    "quantity",
    "license-plate-number",
)

BUSINESS_TEXT_FIELDS: Final = ("标题",)
RETURN_TEXT_FIELDS: Final = ("product-name", "customer-comments")

BUSINESS_FILENAME = re.compile(r"^(?P<date>\d{8})-BusinessReport-.+\.csv$", re.IGNORECASE)
RETURN_FILENAME = re.compile(r"^亚马逊物流买家退货-(?P<date>\d{8})-.+\.csv$", re.IGNORECASE)


class ManifestError(ValueError):
    """Raised when the source files cannot form a trustworthy manifest."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sequence_digest(values: Iterable[Any]) -> str:
    digest = hashlib.sha256()
    for value in values:
        encoded = _canonical_json_bytes(value)
        digest.update(len(encoded).to_bytes(8, byteorder="big"))
        digest.update(encoded)
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _detect_encoding(path: Path, report_type: str) -> str:
    prefix = path.read_bytes()[:3]
    if prefix == b"\xef\xbb\xbf":
        encoding = "utf-8-sig"
    elif report_type == "return_report":
        # Amazon's buyer-return export is Windows-1252. Files containing only
        # ASCII bytes are still part of the same export family and use the same
        # declared encoding.
        encoding = "windows-1252"
    else:
        encoding = "utf-8"
    try:
        path.read_text(encoding=encoding)
    except UnicodeDecodeError as error:
        raise ManifestError(f"{path}: source is not valid {encoding}") from error
    return encoding


def _classify_filename(filename: str) -> tuple[str, date]:
    for report_type, pattern in (
        ("business_report", BUSINESS_FILENAME),
        ("return_report", RETURN_FILENAME),
    ):
        match = pattern.fullmatch(filename)
        if match:
            try:
                report_date = datetime.strptime(match.group("date"), "%Y%m%d").date()
            except ValueError as error:
                raise ManifestError(f"Invalid report date in filename: {filename}") from error
            return report_type, report_date
    raise ManifestError(f"Unsupported CSV filename: {filename}")


def _read_csv(path: Path, encoding: str) -> tuple[tuple[str, ...], list[tuple[str, ...]]]:
    with path.open("r", encoding=encoding, newline="") as source:
        reader = csv.reader(source, strict=True)
        try:
            header = tuple(next(reader))
        except StopIteration as error:
            raise ManifestError(f"{path}: CSV is empty") from error
        except csv.Error as error:
            raise ManifestError(f"{path}: invalid CSV header: {error}") from error

        rows: list[tuple[str, ...]] = []
        try:
            for row_number, raw_row in enumerate(reader, start=2):
                row = tuple(raw_row)
                if len(row) != len(header):
                    raise ManifestError(
                        f"{path}: row {row_number} has {len(row)} fields; "
                        f"expected {len(header)}"
                    )
                rows.append(row)
        except csv.Error as error:
            raise ManifestError(f"{path}: invalid CSV content: {error}") from error
    return header, rows


def _header_indices(header: Sequence[str]) -> dict[str, int]:
    if len(set(header)) != len(header):
        raise ManifestError("CSV contains duplicate header names")
    return {name: index for index, name in enumerate(header)}


def _parse_integer(raw_value: str, *, context: str) -> Decimal:
    try:
        value = Decimal(raw_value.strip())
    except InvalidOperation as error:
        raise ManifestError(f"{context}: invalid integer value {raw_value!r}") from error
    if not value.is_finite():
        raise ManifestError(f"{context}: non-finite integer value {raw_value!r}")
    if value != value.to_integral_value():
        raise ManifestError(f"{context}: non-integral value {raw_value!r}")
    return value


def _parse_usd(raw_value: str, *, context: str) -> Decimal:
    normalized = raw_value.strip()
    if not normalized.startswith("US$"):
        raise ManifestError(f"{context}: expected an US$ amount, got {raw_value!r}")
    try:
        value = Decimal(normalized.removeprefix("US$").replace(",", ""))
    except InvalidOperation as error:
        raise ManifestError(f"{context}: invalid US$ amount {raw_value!r}") from error
    if not value.is_finite():
        raise ManifestError(f"{context}: non-finite US$ amount {raw_value!r}")
    return value


def _parse_percentage(raw_value: str, *, context: str) -> Decimal:
    normalized = raw_value.strip()
    if not normalized.endswith("%"):
        raise ManifestError(f"{context}: expected a percentage, got {raw_value!r}")
    try:
        percentage = Decimal(normalized.removesuffix("%").strip())
    except InvalidOperation as error:
        raise ManifestError(f"{context}: invalid percentage {raw_value!r}") from error
    if not percentage.is_finite():
        raise ManifestError(f"{context}: non-finite percentage {raw_value!r}")
    return percentage / Decimal(100)


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _numeric_totals(
    rows: Sequence[Sequence[str]],
    indices: dict[str, int],
    definitions: dict[str, tuple[str, str]],
    *,
    context: str,
) -> dict[str, str]:
    parsers: dict[str, Callable[..., Decimal]] = {
        "integer": _parse_integer,
        "usd": _parse_usd,
    }
    totals: dict[str, Decimal] = {}
    for source_name, (logical_name, kind) in definitions.items():
        total = Decimal(0)
        for data_row_number, row in enumerate(rows, start=1):
            total += parsers[kind](
                row[indices[source_name]],
                context=f"{context}, data row {data_row_number}, field {source_name}",
            )
        totals[logical_name] = total
    return {name: _decimal_string(totals[name]) for name in sorted(totals)}


def _percentage_metrics(
    rows: Sequence[Sequence[str]],
    indices: dict[str, int],
    definitions: dict[str, str],
    *,
    context: str,
) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for source_name, logical_name in definitions.items():
        ratios = [
            _parse_percentage(
                row[indices[source_name]],
                context=f"{context}, data row {data_row_number}, field {source_name}",
            )
            for data_row_number, row in enumerate(rows, start=1)
        ]
        canonical_ratios = [_decimal_string(value) for value in ratios]
        metrics[logical_name] = {
            "parsed_count": len(ratios),
            "min_ratio": _decimal_string(min(ratios)) if ratios else None,
            "max_ratio": _decimal_string(max(ratios)) if ratios else None,
            "ordered_ratios_sha256": _sequence_digest(canonical_ratios),
        }
    return {name: metrics[name] for name in sorted(metrics)}


def _text_field_metrics(
    rows: Sequence[Sequence[str]],
    indices: dict[str, int],
    field_names: Sequence[str],
) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for field_name in field_names:
        values = [row[indices[field_name]] for row in rows]
        longest_index = max(range(len(values)), key=lambda index: len(values[index]), default=None)
        longest_value = values[longest_index] if longest_index is not None else ""
        metrics[field_name] = {
            "ordered_values_sha256": _sequence_digest(values),
            "non_empty_count": sum(bool(value) for value in values),
            "max_length": len(longest_value),
            "longest_value_sha256": hashlib.sha256(longest_value.encode("utf-8")).hexdigest(),
            "longest_data_row_number": longest_index + 1 if longest_index is not None else None,
        }
    return metrics


def _parse_aware_datetime(raw_value: str, *, context: str) -> datetime:
    candidate = raw_value.strip().replace("Z", "+00:00")
    try:
        value = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise ManifestError(f"{context}: invalid ISO-8601 timestamp {raw_value!r}") from error
    if value.tzinfo is None or value.utcoffset() is None:
        raise ManifestError(f"{context}: timestamp has no UTC offset: {raw_value!r}")
    return value


def _report_entry(source_root: Path, path: Path) -> dict[str, Any]:
    report_type, report_date = _classify_filename(path.name)
    encoding = _detect_encoding(path, report_type)
    header, rows = _read_csv(path, encoding)

    expected_header = (
        BUSINESS_REPORT_HEADERS if report_type == "business_report" else RETURN_REPORT_HEADERS
    )
    if header != expected_header:
        raise ManifestError(
            f"{path}: header does not match the supported {report_type} schema"
        )

    indices = _header_indices(header)
    numeric_definitions = (
        BUSINESS_NUMERIC_FIELDS
        if report_type == "business_report"
        else RETURN_NUMERIC_FIELDS
    )
    identity_fields = (
        BUSINESS_IDENTITY_FIELDS
        if report_type == "business_report"
        else RETURN_IDENTITY_FIELDS
    )
    text_fields = (
        BUSINESS_TEXT_FIELDS if report_type == "business_report" else RETURN_TEXT_FIELDS
    )

    identity_values = sorted(
        tuple(row[indices[field_name]] for field_name in identity_fields) for row in rows
    )
    relative_path = path.relative_to(source_root).as_posix()
    entry: dict[str, Any] = {
        "path": relative_path,
        "report_type": report_type,
        "detected_report_date": report_date.isoformat(),
        "sha256": _file_sha256(path),
        "byte_size": path.stat().st_size,
        "encoding": encoding,
        "column_count": len(header),
        "header": list(header),
        "header_sha256": _sequence_digest([header]),
        "row_count": len(rows),
        "parsed_rows_sha256": _sequence_digest(rows),
        "identity_set_sha256": _sequence_digest(identity_values),
        "numeric_totals": _numeric_totals(
            rows,
            indices,
            numeric_definitions,
            context=relative_path,
        ),
        "text_fields": _text_field_metrics(rows, indices, text_fields),
    }

    if report_type == "business_report":
        entry["percentage_fields"] = _percentage_metrics(
            rows,
            indices,
            BUSINESS_PERCENTAGE_FIELDS,
            context=relative_path,
        )

    if report_type == "return_report":
        event_dates: list[str] = []
        mismatch_count = 0
        return_date_index = indices["return-date"]
        for data_row_number, row in enumerate(rows, start=1):
            timestamp = _parse_aware_datetime(
                row[return_date_index],
                context=f"{relative_path}, data row {data_row_number}, field return-date",
            )
            event_date = timestamp.astimezone(UTC).date()
            event_dates.append(event_date.isoformat())
            mismatch_count += event_date != report_date
        entry["event_dates_utc"] = sorted(set(event_dates))
        entry["event_date_mismatch_count"] = mismatch_count

    return entry


def build_manifest(source_root: Path | str) -> dict[str, Any]:
    """Build a deterministic manifest without exposing row-level identifiers."""

    root = Path(source_root).resolve()
    if not root.is_dir():
        raise ManifestError(f"Source directory does not exist: {root}")

    csv_files = sorted(
        (path for path in root.rglob("*.csv") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix().casefold(),
    )
    if not csv_files:
        raise ManifestError(f"No CSV files found below: {root}")

    entries = [_report_entry(root, path) for path in csv_files]
    report_types: dict[str, dict[str, int]] = {}
    for report_type in sorted({entry["report_type"] for entry in entries}):
        matching = [entry for entry in entries if entry["report_type"] == report_type]
        report_types[report_type] = {
            "file_count": len(matching),
            "row_count": sum(entry["row_count"] for entry in matching),
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "summary": {
            "file_count": len(entries),
            "row_count": sum(entry["row_count"] for entry in entries),
            "event_date_mismatch_count": sum(
                entry.get("event_date_mismatch_count", 0) for entry in entries
            ),
            "report_types": report_types,
        },
        "files": entries,
    }


def add_canary_scope(
    manifest: dict[str, Any], source_root: Path, *, site_id: int, start: date, end: date
) -> None:
    """Bind an explicitly approved daily scope to an independent CSV oracle.

    SKU classification here is deliberately independent of application code.
    This oracle supports printable ASCII SKU inputs; other inputs need a reviewed
    oracle rather than silently inheriting the host's Unicode normalization.
    """
    if type(site_id) is not int or site_id < 1 or end < start:
        raise ManifestError("Invalid approved canary scope")
    dates = [
        (start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)
    ]
    expected_pairs = {
        (kind, day) for kind in ("business_report", "return_report") for day in dates
    }
    entries = manifest["files"]
    actual_pairs = [
        (entry["report_type"], entry["detected_report_date"]) for entry in entries
    ]
    if len(actual_pairs) != len(expected_pairs) or set(actual_pairs) != expected_pairs:
        raise ManifestError(
            "Corpus must contain exactly one report of each type per approved day"
        )
    by_report: dict[str, set[str]] = {"business_report": set(), "return_report": set()}
    for entry in entries:
        header, rows = _read_csv(source_root / entry["path"], entry["encoding"])
        sku_index = header.index(
            "SKU" if entry["report_type"] == "business_report" else "sku"
        )
        by_report[entry["report_type"]].update(row[sku_index] for row in rows)
    combined = by_report["business_report"] | by_report["return_report"]
    if any(not sku or any(not 32 <= ord(c) <= 126 for c in sku) for sku in combined):
        raise ManifestError(
            "Canary SKU oracle requires reviewed printable ASCII inputs"
        )
    strict = {
        sku
        for sku in combined
        if len(sku) <= 255
        and re.fullmatch(r"[0-9]+-[^-]+-[^-]+", sku)
        and all(len(part) <= 128 for part in sku.split("-"))
    }
    manifest["approved_scope"] = {
        "site_id": site_id,
        "report_dates": dates,
        "report_types": ["business_report", "return_report"],
    }
    manifest["canary_expected"] = {
        "oracle": "stdlib_csv_ascii_sku_v1",
        "candidate_style_count": len({sku.split("-", 1)[0] for sku in strict}),
        "distinct_seller_sku_count": len(combined),
        "strict_seller_sku_count": len(strict),
        "anomaly_count": len(combined - strict),
        "report_membership_counts": {
            "business_only": len(
                by_report["business_report"] - by_report["return_report"]
            ),
            "returns_only": len(
                by_report["return_report"] - by_report["business_report"]
            ),
            "both": len(by_report["business_report"] & by_report["return_report"]),
        },
        "seller_sku_sets_sha256": {
            kind: _sequence_digest(sorted(values)) for kind, values in by_report.items()
        },
    }


def write_manifest(
    source_root: Path | str,
    output_path: Path | str,
    *,
    site_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """Build and atomically write the manifest as deterministic UTF-8 JSON."""

    manifest = build_manifest(source_root)
    if any(value is not None for value in (site_id, start, end)):
        if site_id is None or start is None or end is None:
            raise ManifestError("Canary scope requires site-id, start and end together")
        add_canary_scope(
            manifest, Path(source_root), site_id=site_id, start=start, end=end
        )
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_name(f".{destination.name}.tmp")
    serialized = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    temporary_path.write_text(serialized, encoding="utf-8", newline="\n")
    temporary_path.replace(destination)
    return manifest


def _create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a deterministic golden manifest for Amazon report CSV files."
    )
    parser.add_argument(
        "--source", required=True, type=Path, help="Root directory of CSV files"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Manifest JSON output path"
    )
    parser.add_argument(
        "--site-id", type=int, help="Approved database site, required with start/end"
    )
    parser.add_argument(
        "--start", type=date.fromisoformat, help="First approved report day"
    )
    parser.add_argument(
        "--end", type=date.fromisoformat, help="Last approved report day"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _create_argument_parser().parse_args(argv)
    try:
        manifest = write_manifest(
            args.source,
            args.output,
            site_id=args.site_id,
            start=args.start,
            end=args.end,
        )
    except (ManifestError, OSError) as error:
        print(f"golden manifest build failed: {error}", file=sys.stderr)
        return 2

    summary = manifest["summary"]
    print(
        "golden manifest written: "
        f"{summary['file_count']} files, {summary['row_count']} rows, "
        f"{summary['event_date_mismatch_count']} return-date/report-date mismatches"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
