"""Pure domain contracts for versioned table schemas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.imports.types import ReportType

type TableValueKind = Literal["text", "integer", "decimal", "utc_datetime"]


@dataclass(frozen=True, slots=True)
class TableColumn:
    column_id: UUID
    source_header: str
    display_order: int
    value_kind: TableValueKind
    standard_field_name: str | None
    is_key: bool
    participates_in_statistics: bool

    def __post_init__(self) -> None:
        if not isinstance(self.column_id, UUID):
            raise ValueError("column_id must be a UUID")
        if not self.source_header.strip():
            raise ValueError("source_header must not be blank")
        if self.display_order < 1:
            raise ValueError("display_order must be positive")
        if self.value_kind not in {"text", "integer", "decimal", "utc_datetime"}:
            raise ValueError("unsupported table value kind")
        if self.standard_field_name is not None and (
            not self.standard_field_name
            or self.standard_field_name != self.standard_field_name.strip()
        ):
            raise ValueError("standard_field_name must be normalised")
        if self.standard_field_name is None and (
            self.is_key or self.participates_in_statistics
        ):
            raise ValueError("extension columns cannot be key/statistics columns")


@dataclass(frozen=True, slots=True)
class TableSchema:
    report_type: ReportType
    ruleset_version: str
    columns: tuple[TableColumn, ...]

    def __post_init__(self) -> None:
        if self.report_type not in {"business_report", "return_report"}:
            raise ValueError("unsupported report_type")
        if (
            not self.ruleset_version
            or self.ruleset_version != self.ruleset_version.strip()
        ):
            raise ValueError("ruleset_version must be normalised")
        if not self.columns:
            raise ValueError("table schema must contain at least one column")
        column_ids = tuple(column.column_id for column in self.columns)
        headers = tuple(column.source_header for column in self.columns)
        orders = tuple(column.display_order for column in self.columns)
        if len(column_ids) != len(set(column_ids)):
            raise ValueError("table column IDs must be unique")
        if len(headers) != len(set(headers)):
            raise ValueError("table source headers must be unique")
        if orders != tuple(range(1, len(self.columns) + 1)):
            raise ValueError("table display order must be contiguous")
