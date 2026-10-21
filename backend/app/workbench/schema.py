"""Compose stable versioned table schemas from immutable parser mappings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from unicodedata import normalize
from uuid import UUID, uuid5

from app.imports.types import ReportType
from app.validation.fields import FieldContractError, get_report_field_contract

from .types import TableColumn, TableSchema, TableValueKind

type SourceValueKind = Literal[
    "text",
    "integer",
    "percentage",
    "usd",
    "event_datetime",
    "decimal",
    "utc_datetime",
]

_COLUMN_NAMESPACE = UUID("e88da32a-c824-4cac-87bc-3dc47f042ceb")


@dataclass(frozen=True, slots=True)
class SourceColumnMapping:
    source_header: str
    standard_field_name: str | None
    source_kind: SourceValueKind

    def __post_init__(self) -> None:
        header = normalize("NFC", self.source_header)
        if not header.strip():
            raise ValueError("source header must not be blank")
        object.__setattr__(self, "source_header", header)
        if self.standard_field_name is not None and (
            not self.standard_field_name
            or self.standard_field_name != self.standard_field_name.strip()
        ):
            raise ValueError("standard field name must be normalised")
        if self.source_kind not in {
            "text",
            "integer",
            "percentage",
            "usd",
            "event_datetime",
            "decimal",
            "utc_datetime",
        }:
            raise ValueError("unsupported source value kind")


def _table_kind(source_kind: SourceValueKind) -> TableValueKind:
    if source_kind in {"percentage", "usd", "decimal"}:
        return "decimal"
    if source_kind in {"event_datetime", "utc_datetime"}:
        return "utc_datetime"
    if source_kind == "integer":
        return "integer"
    return "text"


def _column_id(report_type: ReportType, header: str) -> UUID:
    return uuid5(_COLUMN_NAMESPACE, f"{report_type}\0{header}")


def compose_table_schema(
    report_type: ReportType,
    ruleset_version: str,
    sources: tuple[tuple[SourceColumnMapping, ...], ...],
) -> TableSchema:
    """Return the first-seen union of source mappings with stable identities."""

    if not sources:
        raise ValueError("at least one source mapping is required")
    contract = get_report_field_contract(report_type, ruleset_version)
    mappings: dict[str, SourceColumnMapping] = {}
    ordered_headers: list[str] = []
    for source in sources:
        seen_in_source: set[str] = set()
        for mapping in source:
            header = mapping.source_header
            if header in seen_in_source:
                raise ValueError(f"duplicate source header: {header!r}")
            seen_in_source.add(header)
            previous = mappings.get(header)
            if previous is not None:
                if (
                    previous.standard_field_name != mapping.standard_field_name
                    or _table_kind(previous.source_kind)
                    != _table_kind(mapping.source_kind)
                ):
                    raise ValueError(f"conflicting source mapping: {header!r}")
                continue
            if mapping.standard_field_name is not None:
                try:
                    contract.field(mapping.standard_field_name)
                except FieldContractError as error:
                    raise ValueError(
                        f"unknown standard field: {mapping.standard_field_name!r}"
                    ) from error
            mappings[header] = mapping
            ordered_headers.append(header)

    columns: list[TableColumn] = []
    for display_order, header in enumerate(ordered_headers, start=1):
        mapping = mappings[header]
        field = (
            contract.field(mapping.standard_field_name)
            if mapping.standard_field_name is not None
            else None
        )
        columns.append(
            TableColumn(
                column_id=_column_id(report_type, header),
                source_header=header,
                display_order=display_order,
                value_kind=_table_kind(mapping.source_kind),
                standard_field_name=mapping.standard_field_name,
                is_key=field.required_on_add if field is not None else False,
                participates_in_statistics=field is not None,
            )
        )
    return TableSchema(
        report_type=report_type,
        ruleset_version=ruleset_version,
        columns=tuple(columns),
    )
