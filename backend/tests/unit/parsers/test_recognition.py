from __future__ import annotations

from datetime import date

from app.parsers.recognition import DETECTOR_VERSION, recognize_report
from app.parsers.rules import REPORT_RULES

from .conftest import csv_bytes


def test_utf8_bom_business_header_is_the_authoritative_type_evidence() -> None:
    content = csv_bytes(
        REPORT_RULES["business_report"].source_header,
        [],
        encoding="utf-8-sig",
    )

    result = recognize_report("20260801-BusinessReport-example.csv", content)

    assert result.status == "suggested"
    assert result.report_type == "business_report"
    assert result.encoding == "utf-8-sig"
    assert result.detected_report_date == date(2026, 8, 1)
    assert result.ruleset_version == "business_report_v1"


def test_recognition_allows_unique_extra_original_columns() -> None:
    header = (
        "Operator note",
        *REPORT_RULES["business_report"].source_header,
        "Custom flag",
    )
    content = csv_bytes(header, [], encoding="utf-8-sig")

    result = recognize_report("20260801-BusinessReport-extra.csv", content)

    assert result.status == "suggested"
    assert result.report_type == "business_report"
    assert result.header == header


def test_windows_1252_return_report_is_recognised_from_its_header() -> None:
    content = csv_bytes(
        REPORT_RULES["return_report"].source_header,
        [
            [
                "2026-08-01T00:00:00+00:00",
                "A",
                "S",
                "A",
                "F",
                "Buyer\u2019s item",
                "1",
                "X",
                "SELLABLE",
                "R",
                "S",
                "L",
                "OK",
            ]
        ],
        encoding="windows-1252",
    )

    result = recognize_report("亚马逊物流买家退货-20260801-example.csv", content)

    assert result.status == "suggested"
    assert result.report_type == "return_report"
    assert result.encoding == "windows-1252"


def test_utf8_return_text_is_not_misdecoded_as_windows_1252() -> None:
    content = csv_bytes(
        REPORT_RULES["return_report"].source_header,
        [["", "", "", "", "", "Café", "", "", "", "", "", "", ""]],
        encoding="utf-8",
    )

    result = recognize_report("亚马逊物流买家退货-20260801-example.csv", content)

    assert result.report_type == "return_report"
    assert result.encoding == "utf-8"
    assert DETECTOR_VERSION == "amazon_report_detector_v1"


def test_filename_conflict_does_not_override_the_header() -> None:
    content = csv_bytes(REPORT_RULES["return_report"].source_header, [])

    result = recognize_report("20260801-BusinessReport-example.csv", content)

    assert result.status == "conflict"
    assert result.report_type == "return_report"
    assert tuple(issue.code for issue in result.issues) == ("filename_type_conflict",)


def test_filename_alone_cannot_suggest_an_unsupported_header() -> None:
    content = csv_bytes(("unknown", "columns"), [])

    result = recognize_report("20260801-BusinessReport-example.csv", content)

    assert result.status == "unsupported"
    assert result.report_type is None
    assert result.ruleset_version is None
