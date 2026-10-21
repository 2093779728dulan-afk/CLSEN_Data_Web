from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PRIVATE_SOURCE_ROOT = REPOSITORY_ROOT / "表格"
GOLDEN_MANIFEST_PATH = REPOSITORY_ROOT / "data" / "golden" / "golden-manifest.json"
PRIVATE_MANIFEST_ENV = "APP_PRODUCT_CATALOG_PRIVATE_MANIFEST"
PRIVATE_CORPUS_ENV = "APP_PRODUCT_CATALOG_PRIVATE_CORPUS_ROOT"
REQUIRE_PRIVATE_ENV = "APP_REQUIRE_PRIVATE_CSV_REGRESSION"
SYNTHETIC_ONLY_ENV = "APP_PROJECT_OPTIMIZATION_SYNTHETIC_ONLY"
SOURCE_TIMEZONE = "America/Los_Angeles"

BUSINESS_NUMERIC_FIELDS = {
    "sessions_total": "sessions_total",
    "sessions_b2b": "sessions_b2b",
    "page_views_total": "page_views_total",
    "page_views_b2b": "page_views_b2b",
    "units_ordered_total": "units_ordered",
    "units_ordered_b2b": "units_ordered_b2b",
    "ordered_product_sales_total": "ordered_product_sales",
    "ordered_product_sales_b2b": "ordered_product_sales_b2b",
    "order_items_total": "total_order_items",
    "order_items_b2b": "total_order_items_b2b",
}

BUSINESS_PERCENTAGE_FIELDS = {
    "conversion_rate_total": "conversion_rate_total",
    "sessions_percentage_b2b": "session_percentage_b2b",
    "page_views_percentage_total": "page_view_percentage_total",
    "page_views_percentage_b2b": "page_view_percentage_b2b",
    "featured_offer_percentage_total": "featured_offer_percentage",
    "featured_offer_percentage_b2b": "featured_offer_percentage_b2b",
    "unit_session_percentage_total": "unit_session_percentage",
    "unit_session_percentage_b2b": "unit_session_percentage_b2b",
}

BUSINESS_IDENTITY_FIELDS = ("parent_asin", "child_asin", "sku")
RETURN_TEXT_IDENTITY_FIELDS = (
    "order_id",
    "sku",
    "asin",
    "fnsku",
    "license_plate_number",
)
TEXT_FIELD_MAPPINGS = {
    "business_report": {"标题": "title"},
    "return_report": {
        "product-name": "product_name",
        "customer-comments": "customer_comments",
    },
}


class PrivateRegressionMismatch(AssertionError):
    """A mismatch whose message is safe to expose in test output."""


@dataclass(frozen=True, slots=True)
class PrivateCase:
    case_id: str
    source_path: Path
    expected: dict[str, Any]


def _private_data_unavailable(reason: str) -> None:
    message = f"private CSV regression data unavailable: {reason}"
    if os.getenv(REQUIRE_PRIVATE_ENV) == "1":
        pytest.fail(message, pytrace=False)
    pytest.skip(message)


def _load_manifest() -> dict[str, Any]:
    if os.getenv(SYNTHETIC_ONLY_ENV) == "1":
        _private_data_unavailable("approved manifest is missing")
    manifest_path = Path(os.getenv(PRIVATE_MANIFEST_ENV, str(GOLDEN_MANIFEST_PATH)))
    if not manifest_path.is_file():
        _private_data_unavailable("approved manifest is missing")

    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        pytest.fail("private CSV regression manifest is unreadable", pytrace=False)

    if not isinstance(loaded, dict):
        pytest.fail(
            "private CSV regression manifest has an invalid root",
            pytrace=False,
        )
    return loaded


def _manifest_cases(manifest: dict[str, Any]) -> tuple[PrivateCase, ...]:
    raw_entries = manifest.get("files")
    if not isinstance(raw_entries, list) or not raw_entries:
        pytest.fail(
            "private CSV regression manifest has no file entries",
            pytrace=False,
        )

    source_root = Path(
        os.getenv(PRIVATE_CORPUS_ENV, str(PRIVATE_SOURCE_ROOT))
    ).resolve()
    seen_paths: set[Path] = set()
    cases: list[PrivateCase] = []
    for ordinal, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            pytest.fail(
                "private CSV regression manifest entry is invalid",
                pytrace=False,
            )

        relative_value = raw_entry.get("path")
        expected_sha256 = raw_entry.get("sha256")
        if not isinstance(relative_value, str) or not isinstance(expected_sha256, str):
            pytest.fail(
                "private CSV regression manifest entry is incomplete",
                pytrace=False,
            )

        relative_path = PurePosixPath(relative_value)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            pytest.fail("private CSV regression manifest path is unsafe", pytrace=False)

        source_path = (source_root / Path(*relative_path.parts)).resolve()
        try:
            source_path.relative_to(source_root)
        except ValueError:
            pytest.fail(
                "private CSV regression manifest path escapes its root",
                pytrace=False,
            )

        if source_path in seen_paths:
            pytest.fail(
                "private CSV regression manifest has a duplicate path",
                pytrace=False,
            )
        seen_paths.add(source_path)

        case_id = f"manifest[{ordinal}]#{expected_sha256[:12]}"
        cases.append(
            PrivateCase(
                case_id=case_id,
                source_path=source_path,
                expected=raw_entry,
            )
        )

    summary = manifest.get("summary")
    if not isinstance(summary, dict) or summary.get("file_count") != len(cases):
        pytest.fail(
            "private CSV regression manifest summary is inconsistent",
            pytrace=False,
        )
    scope = manifest.get("approved_scope")
    if (
        not isinstance(scope, dict)
        or type(scope.get("site_id")) is not int
        or scope["site_id"] < 1
    ):
        pytest.fail(
            "private CSV regression requires an approved site/date scope", pytrace=False
        )
    dates = scope.get("report_dates")
    if (
        not isinstance(dates, list)
        or not dates
        or any(not isinstance(day, str) for day in dates)
    ):
        pytest.fail("private CSV regression approved dates are invalid", pytrace=False)
    try:
        valid_dates = all(date.fromisoformat(day).isoformat() == day for day in dates)
    except ValueError:
        valid_dates = False
    if (
        not valid_dates
        or len(set(dates)) != len(dates)
        or scope.get("report_types") != ["business_report", "return_report"]
    ):
        pytest.fail("private CSV regression approved scope is invalid", pytrace=False)
    expected_pairs = {(kind, day) for kind in scope["report_types"] for day in dates}
    actual_pairs = [
        (case.expected.get("report_type"), case.expected.get("detected_report_date"))
        for case in cases
    ]
    if len(actual_pairs) != len(expected_pairs) or set(actual_pairs) != expected_pairs:
        pytest.fail(
            "private CSV regression files do not match the approved scope",
            pytrace=False,
        )
    report_types = summary.get("report_types")
    actual_report_counts = (
        {
            report_type: details.get("file_count")
            for report_type, details in report_types.items()
            if isinstance(report_type, str) and isinstance(details, dict)
        }
        if isinstance(report_types, dict)
        else {}
    )
    if actual_report_counts != {kind: len(dates) for kind in scope["report_types"]}:
        pytest.fail(
            "private CSV regression report counts do not match the approved scope",
            pytrace=False,
        )
    return tuple(cases)


def _require_complete_private_corpus(cases: Sequence[PrivateCase]) -> None:
    private_source_root = Path(os.getenv(PRIVATE_CORPUS_ENV, str(PRIVATE_SOURCE_ROOT)))
    if not private_source_root.is_dir():
        _private_data_unavailable("source directory is missing")

    expected_paths = {case.source_path for case in cases}
    actual_paths = {
        path.resolve()
        for path in private_source_root.rglob("*")
        if path.is_file() and path.suffix.casefold() == ".csv"
    }
    if actual_paths != expected_paths:
        _private_data_unavailable(
            "source corpus is incomplete "
            f"(expected {len(expected_paths)} files, found {len(actual_paths)})"
        )


def _expect_equal(case_id: str, field_name: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise PrivateRegressionMismatch(f"{case_id}: {field_name} changed")


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


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _raw_rows(parsed: Any, case_id: str) -> tuple[tuple[str, ...], ...]:
    source_rows = getattr(parsed, "source_rows", None)
    if not isinstance(source_rows, Sequence):
        raise PrivateRegressionMismatch(f"{case_id}: source rows are unavailable")

    raw_rows: list[tuple[str, ...]] = []
    for source_row in source_rows:
        raw_values = getattr(source_row, "raw_values", None)
        if (
            not isinstance(raw_values, Sequence)
            or isinstance(raw_values, (str, bytes))
            or not all(isinstance(value, str) for value in raw_values)
        ):
            raise PrivateRegressionMismatch(
                f"{case_id}: decoded source row shape changed"
            )
        raw_rows.append(tuple(raw_values))
    return tuple(raw_rows)


def _numeric_value(row: Any, field_name: str, case_id: str) -> Decimal:
    value = getattr(row, field_name, None)
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise PrivateRegressionMismatch(
            f"{case_id}: typed numeric field {field_name} changed"
        )
    return Decimal(value)


def _text_value(row: Any, field_name: str, case_id: str) -> str:
    value = getattr(row, field_name, None)
    if not isinstance(value, str):
        raise PrivateRegressionMismatch(
            f"{case_id}: typed text field {field_name} changed"
        )
    return value


def _identity_set_digest(
    report_type: str,
    rows: Sequence[Any],
    case_id: str,
) -> str:
    identities: list[tuple[str, ...]] = []
    for row in rows:
        if report_type == "business_report":
            identity = tuple(
                _text_value(row, field_name, case_id)
                for field_name in BUSINESS_IDENTITY_FIELDS
            )
        else:
            return_date = getattr(row, "return_date", None)
            quantity = getattr(row, "quantity", None)
            if not isinstance(return_date, datetime):
                raise PrivateRegressionMismatch(
                    f"{case_id}: typed identity field return_date changed"
                )
            if isinstance(quantity, bool) or not isinstance(quantity, int):
                raise PrivateRegressionMismatch(
                    f"{case_id}: typed identity field quantity changed"
                )
            identity = (
                return_date.isoformat(),
                *(
                    _text_value(row, field_name, case_id)
                    for field_name in RETURN_TEXT_IDENTITY_FIELDS[:-1]
                ),
                str(quantity),
                _text_value(row, RETURN_TEXT_IDENTITY_FIELDS[-1], case_id),
            )
        identities.append(identity)
    return _sequence_digest(sorted(identities))


def _text_field_metrics(
    report_type: str,
    rows: Sequence[Any],
    case_id: str,
) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for logical_name, field_name in TEXT_FIELD_MAPPINGS[report_type].items():
        values = [_text_value(row, field_name, case_id) for row in rows]
        longest_index = max(
            range(len(values)),
            key=lambda index: len(values[index]),
            default=None,
        )
        longest_value = values[longest_index] if longest_index is not None else ""
        metrics[logical_name] = {
            "ordered_values_sha256": _sequence_digest(values),
            "non_empty_count": sum(bool(value) for value in values),
            "max_length": len(longest_value),
            "longest_value_sha256": hashlib.sha256(
                longest_value.encode("utf-8")
            ).hexdigest(),
            "longest_data_row_number": (
                longest_index + 1 if longest_index is not None else None
            ),
        }
    return metrics


def _numeric_totals(
    report_type: str,
    rows: Sequence[Any],
    case_id: str,
) -> dict[str, str]:
    definitions = (
        BUSINESS_NUMERIC_FIELDS
        if report_type == "business_report"
        else {"quantity": "quantity"}
    )
    totals: dict[str, str] = {}
    for logical_name, field_name in definitions.items():
        total = sum(
            (_numeric_value(row, field_name, case_id) for row in rows),
            start=Decimal(0),
        )
        totals[logical_name] = _decimal_string(total)
    return {name: totals[name] for name in sorted(totals)}


def _percentage_metrics(
    rows: Sequence[Any],
    case_id: str,
) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for logical_name, field_name in BUSINESS_PERCENTAGE_FIELDS.items():
        values: list[Decimal] = []
        for row in rows:
            value = getattr(row, field_name, None)
            if not isinstance(value, Decimal):
                raise PrivateRegressionMismatch(
                    f"{case_id}: typed percentage field {field_name} changed"
                )
            values.append(value)

        canonical_values = [_decimal_string(value) for value in values]
        metrics[logical_name] = {
            "parsed_count": len(values),
            "min_ratio": _decimal_string(min(values)) if values else None,
            "max_ratio": _decimal_string(max(values)) if values else None,
            "ordered_ratios_sha256": _sequence_digest(canonical_values),
        }
    return {name: metrics[name] for name in sorted(metrics)}


def _return_event_metrics(
    rows: Sequence[Any],
    report_date: date,
    case_id: str,
) -> tuple[list[str], int]:
    event_dates: list[str] = []
    mismatch_count = 0
    for row in rows:
        value = getattr(row, "return_date", None)
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
            or value.utcoffset() != timedelta(0)
        ):
            raise PrivateRegressionMismatch(
                f"{case_id}: return_date is not an aware UTC datetime"
            )
        event_date = value.astimezone(UTC).date()
        event_dates.append(event_date.isoformat())
        mismatch_count += event_date != report_date
    return sorted(set(event_dates)), mismatch_count


def _compare_case(
    case: PrivateCase,
    *,
    recognize_report: Any,
    parse_report: Any,
    parse_settings_type: Any,
    report_rules: Any,
) -> None:
    expected = case.expected
    content = case.source_path.read_bytes()
    _expect_equal(
        case.case_id,
        "file SHA-256",
        hashlib.sha256(content).hexdigest(),
        expected.get("sha256"),
    )

    recognition = recognize_report(case.source_path.name, content)
    expected_report_type = expected.get("report_type")
    if not isinstance(expected_report_type, str) or expected_report_type not in {
        "business_report",
        "return_report",
    }:
        raise PrivateRegressionMismatch(
            f"{case.case_id}: manifest report type is invalid"
        )
    _expect_equal(case.case_id, "recognition status", recognition.status, "suggested")
    _expect_equal(
        case.case_id,
        "report type",
        recognition.report_type,
        expected_report_type,
    )
    _expect_equal(
        case.case_id,
        "encoding",
        recognition.encoding,
        expected.get("encoding"),
    )
    expected_report_date = date.fromisoformat(expected["detected_report_date"])
    _expect_equal(
        case.case_id,
        "detected report date",
        recognition.detected_report_date,
        expected_report_date,
    )

    rule = report_rules[expected_report_type]
    expected_header = tuple(expected.get("header", ()))
    _expect_equal(
        case.case_id,
        "recognized exact ordered header",
        recognition.header,
        expected_header,
    )
    _expect_equal(
        case.case_id,
        "versioned exact ordered header",
        tuple(rule.source_header),
        expected_header,
    )

    settings = parse_settings_type(
        report_type=expected_report_type,
        encoding=recognition.encoding,
        source_timezone=SOURCE_TIMEZONE,
    )
    parsed = parse_report(content, settings=settings)
    rows = tuple(parsed.rows)
    raw_rows = _raw_rows(parsed, case.case_id)
    _expect_equal(
        case.case_id,
        "parsed exact ordered header",
        parsed.header,
        expected_header,
    )
    _expect_equal(case.case_id, "typed row count", len(rows), expected.get("row_count"))
    _expect_equal(
        case.case_id,
        "source row count",
        len(raw_rows),
        expected.get("row_count"),
    )
    _expect_equal(
        case.case_id,
        "summary row count",
        parsed.summary.row_count,
        expected.get("row_count"),
    )
    _expect_equal(
        case.case_id,
        "ordered decoded source digest",
        _sequence_digest(raw_rows),
        expected.get("parsed_rows_sha256"),
    )
    _expect_equal(
        case.case_id,
        "typed identity set digest",
        _identity_set_digest(expected_report_type, rows, case.case_id),
        expected.get("identity_set_sha256"),
    )
    _expect_equal(
        case.case_id,
        "typed text field metrics",
        _text_field_metrics(expected_report_type, rows, case.case_id),
        expected.get("text_fields"),
    )
    _expect_equal(
        case.case_id,
        "numeric totals",
        _numeric_totals(expected_report_type, rows, case.case_id),
        expected.get("numeric_totals"),
    )

    if expected_report_type == "business_report":
        _expect_equal(
            case.case_id,
            "percentage metrics",
            _percentage_metrics(rows, case.case_id),
            expected.get("percentage_fields"),
        )
    else:
        event_dates, mismatch_count = _return_event_metrics(
            rows,
            expected_report_date,
            case.case_id,
        )
        _expect_equal(
            case.case_id,
            "UTC event dates",
            event_dates,
            expected.get("event_dates_utc"),
        )
        _expect_equal(
            case.case_id,
            "UTC event/report date mismatch count",
            mismatch_count,
            expected.get("event_date_mismatch_count"),
        )


def test_private_real_csv_matches_approved_golden_manifest() -> None:
    manifest = _load_manifest()
    cases = _manifest_cases(manifest)
    _require_complete_private_corpus(cases)

    # Delayed imports allow ordinary source distributions to skip cleanly when
    # the ignored private corpus is not installed.
    from app.parsers.parser import parse_report
    from app.parsers.recognition import recognize_report
    from app.parsers.rules import REPORT_RULES
    from app.parsers.types import ParseSettings

    for case in cases:
        failure: str | None = None
        try:
            _compare_case(
                case,
                recognize_report=recognize_report,
                parse_report=parse_report,
                parse_settings_type=ParseSettings,
                report_rules=REPORT_RULES,
            )
        except PrivateRegressionMismatch as error:
            failure = str(error)
        except Exception as error:  # pragma: no cover - privacy boundary
            failure = f"{case.case_id}: parser raised {type(error).__name__}"

        if failure is not None:
            pytest.fail(failure, pytrace=False)
