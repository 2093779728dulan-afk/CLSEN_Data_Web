"""Public contracts for deterministic Amazon report parsing."""

from app.parsers.parser import PARSER_VERSION, parse_report
from app.parsers.recognition import DETECTOR_VERSION, recognize_report
from app.parsers.rules import REPORT_RULES
from app.parsers.types import (
    BusinessReportRow,
    ParsedReport,
    ParseError,
    ParseSettings,
    RecognitionResult,
    ReturnReportRow,
)

__all__ = [
    "DETECTOR_VERSION",
    "PARSER_VERSION",
    "REPORT_RULES",
    "BusinessReportRow",
    "ParseError",
    "ParseSettings",
    "ParsedReport",
    "RecognitionResult",
    "ReturnReportRow",
    "parse_report",
    "recognize_report",
]
