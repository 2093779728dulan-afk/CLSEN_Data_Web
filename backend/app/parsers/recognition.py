"""Deterministic report suggestions where the decoded header is authoritative."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Final, Literal

from app.imports.types import ReportType
from app.parsers.csv_reader import CsvDocument, read_csv_document
from app.parsers.rules import REPORT_RULES, ReportRule
from app.parsers.types import (
    ParseError,
    RecognitionIssue,
    RecognitionResult,
    SupportedEncoding,
)

_UTF8_BOM: Final = b"\xef\xbb\xbf"
DETECTOR_VERSION: Final = "amazon_report_detector_v1"
_BUSINESS_FILENAME: Final = re.compile(
    r"^(?P<date>\d{8})-BusinessReport-.+\.csv$",
    re.IGNORECASE,
)
_RETURN_FILENAME: Final = re.compile(
    r"^亚马逊物流买家退货-(?P<date>\d{8})-.+\.csv$",
    re.IGNORECASE,
)


def _normalise_header(header: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value.strip() for value in header)


def _matching_rule(document: CsvDocument) -> ReportRule | None:
    normalised = _normalise_header(document.header)
    if len(normalised) != len(set(normalised)):
        return None
    available = set(normalised)
    matches = [
        rule
        for rule in REPORT_RULES.values()
        if set(rule.normalised_header) <= available
    ]
    return matches[0] if len(matches) == 1 else None


def _filename_evidence(
    filename: str,
) -> tuple[ReportType | None, date | None, tuple[RecognitionIssue, ...]]:
    patterns: tuple[tuple[ReportType, re.Pattern[str]], ...] = (
        ("business_report", _BUSINESS_FILENAME),
        ("return_report", _RETURN_FILENAME),
    )
    for report_type, pattern in patterns:
        match = pattern.fullmatch(filename)
        if match is None:
            continue
        try:
            detected_date = datetime.strptime(match.group("date"), "%Y%m%d").date()
        except ValueError:
            return (
                report_type,
                None,
                (
                    RecognitionIssue(
                        code="invalid_filename_date",
                        message="filename contains an invalid report date",
                    ),
                ),
            )
        return report_type, detected_date, ()
    return None, None, ()


def _candidate_documents(
    content: bytes,
) -> tuple[tuple[SupportedEncoding, CsvDocument, ReportRule], ...]:
    encodings: tuple[SupportedEncoding, ...]
    if content.startswith(_UTF8_BOM):
        encodings = ("utf-8-sig",)
    else:
        encodings = ("utf-8", "windows-1252")

    candidates: list[tuple[SupportedEncoding, CsvDocument, ReportRule]] = []
    for encoding in encodings:
        try:
            document = read_csv_document(content, encoding=encoding)
        except ParseError:
            continue
        rule = _matching_rule(document)
        if rule is not None:
            candidates.append((encoding, document, rule))
    return tuple(candidates)


def _select_candidate(
    content: bytes,
    candidates: tuple[tuple[SupportedEncoding, CsvDocument, ReportRule], ...],
) -> tuple[SupportedEncoding, CsvDocument, ReportRule] | None:
    if not candidates:
        return None
    report_types = {candidate[2].report_type for candidate in candidates}
    if len(report_types) != 1:
        return None

    rule = candidates[0][2]
    if any(byte >= 0x80 for byte in content):
        preferred = "utf-8"
    elif rule.report_type == "return_report":
        preferred = "windows-1252"
    else:
        preferred = rule.preferred_encoding
    return next(
        (candidate for candidate in candidates if candidate[0] == preferred),
        candidates[0],
    )


def recognize_report(filename: str, content: bytes) -> RecognitionResult:
    """Return a suggestion; callers must still obtain explicit human confirmation."""

    filename_type, detected_date, issues = _filename_evidence(filename)
    candidate = _select_candidate(content, _candidate_documents(content))
    if candidate is None:
        return RecognitionResult(
            status="unsupported",
            report_type=None,
            detected_report_date=detected_date,
            encoding=None,
            ruleset_version=None,
            header=None,
            issues=(
                *issues,
                RecognitionIssue(
                    code="unsupported_header_or_encoding",
                    message="content does not match a supported report header",
                ),
            ),
        )

    encoding, document, rule = candidate
    if filename_type is not None and filename_type != rule.report_type:
        issues += (
            RecognitionIssue(
                code="filename_type_conflict",
                message="filename and authoritative header suggest different types",
            ),
        )
        status: Literal["suggested", "conflict"] = "conflict"
    else:
        status = "suggested"
    return RecognitionResult(
        status=status,
        report_type=rule.report_type,
        detected_report_date=detected_date,
        encoding=encoding,
        ruleset_version=rule.version,
        header=document.header,
        issues=issues,
    )
