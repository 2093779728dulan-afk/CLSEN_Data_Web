"""Safe SQL fragments for the published-detail read model.

Only frozen schema metadata is allowed to choose a SQL expression here.  Request
values are always values bound by SQLAlchemy, never identifiers interpolated into
the query text.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal
from uuid import UUID

from app.imports.types import ReportType
from app.published_details.models import PublishedDetailColumn
from app.validation.fields import REPORT_FIELD_CONTRACTS

type SortDirection = Literal["asc", "desc"]

_IDENTIFIER: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9_]*", re.ASCII)
_ROW_TABLES: Final[MappingProxyType[ReportType, str]] = MappingProxyType(
    {
        "business_report": "business_report_rows",
        "return_report": "return_report_rows",
    }
)
_WRITE_ROLES: Final[frozenset[str]] = frozenset({"admin", "data_manager"})
_VIEWER_REDACTED_FIELDS: Final[MappingProxyType[ReportType, frozenset[str]]] = (
    MappingProxyType(
        {
            "business_report": frozenset(),
            "return_report": frozenset(
                {"order_id", "license_plate_number", "customer_comments"}
            ),
        }
    )
)
_EXTENSION_ORDER_EXPRESSIONS: Final[MappingProxyType[str, str]] = MappingProxyType(
    {
        "text": "sort_extension_cells.current_value",
        "integer": "CAST(sort_extension_cells.current_value AS SIGNED)",
        "decimal": "CAST(sort_extension_cells.current_value AS DECIMAL(65, 30))",
        "utc_datetime": "CAST(sort_extension_cells.current_value AS DATETIME(6))",
    }
)


class InvalidPublishedSortColumn(ValueError):
    """A requested stable column ID is not visible in this publication scope."""

    code = "invalid_published_sort_column"

    def __init__(self) -> None:
        super().__init__("sort_column_id is not visible in this publication scope")


class InvalidPublishedSortDirection(ValueError):
    """A requested sort direction cannot be represented by the fixed allow-list."""

    code = "invalid_published_sort_direction"

    def __init__(self) -> None:
        super().__init__("direction must be 'asc' or 'desc'")


class PublishedColumnResolutionError(RuntimeError):
    """Frozen metadata cannot safely resolve to the current typed row contract."""


@dataclass(frozen=True, slots=True)
class PublishedOrder:
    """A fixed order expression and any trusted extension-cell join it needs."""

    expression_sql: str
    join_sql: str
    parameters: dict[str, object]


class VisibleColumnResolver:
    """Map visible, stable column IDs to fixed typed or extension SQL fragments.

    A standard field is only usable after it has been checked against the frozen
    report-field contracts.  Extension values are always read through the
    versioned cell snapshot table and never become SQL identifiers.
    """

    def __init__(
        self,
        report_type: ReportType,
        columns: Sequence[PublishedDetailColumn],
        roles: Iterable[str],
    ) -> None:
        if report_type not in _ROW_TABLES:
            raise ValueError("unsupported report type")
        self.report_type = report_type
        self.typed_table = _ROW_TABLES[report_type]
        self._roles = frozenset(roles)
        self._allowed_standard_fields = _contract_fields(report_type)
        self._columns_by_id: dict[UUID, PublishedDetailColumn] = {}
        visible_columns: list[PublishedDetailColumn] = []
        for column in columns:
            if column.column_id in self._columns_by_id:
                raise PublishedColumnResolutionError(
                    "The publication schema contains a repeated stable column ID."
                )
            self._columns_by_id[column.column_id] = column
            if column.standard_field_name is not None:
                self._assert_standard_column(column)
            if self._is_visible(column):
                visible_columns.append(column)
        self.visible_columns = tuple(visible_columns)
        self._visible_by_id = {
            column.column_id: column for column in self.visible_columns
        }
        self.standard_columns = tuple(
            column
            for column in self.visible_columns
            if column.standard_field_name is not None
        )
        self.extension_columns = tuple(
            column
            for column in self.visible_columns
            if column.standard_field_name is None
        )

    def search(
        self,
        value: str,
        *,
        dataset_alias: str = "datasets",
        row_alias: str = "row_records",
        typed_alias: str = "typed",
    ) -> tuple[str, dict[str, object]]:
        """Return the one parameterized search predicate shared by both queries."""

        if not isinstance(value, str):
            raise TypeError("search value must be a string")
        parameters: dict[str, object] = {"search": _escaped_search(value)}
        parts = [
            f"CAST({dataset_alias}.report_date AS CHAR) LIKE :search ESCAPE '\\\\'"
        ]
        for index, column in enumerate(self.standard_columns):
            expression, expression_parameters = self.typed_value_expression(
                column.column_id,
                bind_name=f"search_standard_column_{index}",
                row_alias=row_alias,
                typed_alias=typed_alias,
            )
            parameters.update(expression_parameters)
            parts.append(f"CAST({expression} AS CHAR) LIKE :search ESCAPE '\\\\'")
        if self.extension_columns:
            parameters["search_extension_column_ids"] = tuple(
                column.column_id.bytes for column in self.extension_columns
            )
            parts.append(
                "EXISTS ("
                "SELECT 1 FROM version_extension_cells AS search_extension_cells "
                f"WHERE search_extension_cells.version_id = {row_alias}.version_id "
                f"AND search_extension_cells.row_id = {row_alias}.id "
                "AND search_extension_cells.column_id "
                "IN :search_extension_column_ids "
                "AND search_extension_cells.current_value "
                "LIKE :search ESCAPE '\\\\'"
                ")"
            )
        return "(" + " OR ".join(parts) + ")", parameters

    def order_by(
        self,
        column_id: UUID,
        direction: SortDirection | str,
        *,
        row_alias: str = "row_records",
        typed_alias: str = "typed",
    ) -> PublishedOrder:
        """Resolve an allow-listed stable ID to a fixed order expression."""

        if not isinstance(column_id, UUID) or column_id not in self._visible_by_id:
            raise InvalidPublishedSortColumn()
        if direction not in {"asc", "desc"}:
            raise InvalidPublishedSortDirection()
        column = self._visible_by_id[column_id]
        order_direction = "ASC" if direction == "asc" else "DESC"
        if column.standard_field_name is not None:
            expression, parameters = self.typed_value_expression(
                column_id,
                bind_name="sort_column_id",
                row_alias=row_alias,
                typed_alias=typed_alias,
            )
            return PublishedOrder(
                expression_sql=f"{expression} {order_direction}",
                join_sql="",
                parameters=parameters,
            )
        try:
            extension_expression = _EXTENSION_ORDER_EXPRESSIONS[column.value_kind]
        except KeyError as error:
            raise PublishedColumnResolutionError(
                "A frozen extension column has an unsupported value kind."
            ) from error
        return PublishedOrder(
            expression_sql=f"{extension_expression} {order_direction}",
            join_sql=(
                "LEFT JOIN version_extension_cells AS sort_extension_cells "
                f"ON sort_extension_cells.version_id = {row_alias}.version_id "
                f"AND sort_extension_cells.row_id = {row_alias}.id "
                "AND sort_extension_cells.column_id = :sort_column_id"
            ),
            parameters={"sort_column_id": column_id.bytes},
        )

    def typed_value_expression(
        self,
        column_id: UUID,
        *,
        bind_name: str,
        row_alias: str = "row_records",
        typed_alias: str = "typed",
    ) -> tuple[str, dict[str, object]]:
        """Return a typed value, or ``NULL`` when that version lacks the column."""

        column = self._visible_by_id.get(column_id)
        if column is None or column.standard_field_name is None:
            raise InvalidPublishedSortColumn()
        field_name = _safe_standard_field(
            column.standard_field_name,
            self._allowed_standard_fields,
        )
        return (
            "CASE WHEN EXISTS ("
            "SELECT 1 FROM version_table_columns AS available_columns "
            f"WHERE available_columns.version_id = {row_alias}.version_id "
            f"AND available_columns.column_id = :{bind_name}"
            f") THEN {typed_alias}.`{field_name}` ELSE NULL END",
            {bind_name: column.column_id.bytes},
        )

    def _assert_standard_column(self, column: PublishedDetailColumn) -> None:
        assert column.standard_field_name is not None
        _safe_standard_field(column.standard_field_name, self._allowed_standard_fields)

    def _is_visible(self, column: PublishedDetailColumn) -> bool:
        if not self._roles.isdisjoint(_WRITE_ROLES):
            return True
        field_name = column.standard_field_name
        if field_name is None:
            return False
        return field_name not in _VIEWER_REDACTED_FIELDS[self.report_type]


def _contract_fields(report_type: ReportType) -> frozenset[str]:
    fields = frozenset(
        field.name
        for (contract_report_type, _ruleset_version), contract in (
            REPORT_FIELD_CONTRACTS.items()
        )
        if contract_report_type == report_type
        for field in contract.fields
    )
    if not fields:
        raise PublishedColumnResolutionError(
            "The report type has no frozen typed-field contract."
        )
    return fields


def _safe_standard_field(value: str, allowed_fields: frozenset[str]) -> str:
    if value not in allowed_fields or _IDENTIFIER.fullmatch(value) is None:
        raise PublishedColumnResolutionError(
            "A frozen standard field is not part of the typed row contract."
        )
    return value


def _escaped_search(value: str) -> str:
    return (
        "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    )
