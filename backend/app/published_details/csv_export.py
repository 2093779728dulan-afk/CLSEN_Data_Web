"""Safe, bounded CSV export for the published-detail read model.

This module deliberately owns no database configuration.  The caller injects a
``PublishedDetailQueryService`` so scope revalidation, schema resolution, and
the server-side result cursor remain in the caller's existing Session and
transaction snapshot.
"""

from __future__ import annotations

import codecs
import csv
from collections.abc import Callable, Generator, Iterator, Sequence
from datetime import date, datetime
from io import StringIO
from typing import Literal, Protocol
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.published_details.models import (
    PublishedDetailColumn,
    PublishedDetailRow,
    PublishedDetailScope,
)

_SYSTEM_HEADERS: tuple[str, ...] = ("报告日期", "发布版本", "行号")
_FORMULA_PREFIXES = frozenset({"=", "+", "-", "@"})
_PRESERVED_C0 = frozenset({"\t", "\r", "\n"})
_CSV_STREAM_BATCH_SIZE = 100


class InvalidPublishedExportColumn(ValueError):
    """A caller requested a duplicate, unknown, or role-hidden CSV column."""

    code = "invalid_published_export_column"

    def __init__(self) -> None:
        super().__init__("column_id must be a unique visible published column")


class PublishedExportQuery(BaseModel):
    """CSV's unpaged subset of the same filters used by published row pages."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    search: str | None = None
    sort_column_id: UUID | None = None
    direction: Literal["asc", "desc"] = "asc"
    report_date: date | None = None


class PublishedRowsStreamer(Protocol):
    """The narrow L3 dependency required by the CSV boundary."""

    def prepare_published_rows(
        self,
        scope: PublishedDetailScope,
        search: str | None,
        sort_column_id: UUID | None,
        direction: Literal["asc", "desc"],
        report_date: date | None = None,
        *,
        batch_size: int = 100,
    ) -> tuple[
        tuple[PublishedDetailColumn, ...],
        Callable[[], Iterator[PublishedDetailRow]],
    ]: ...


class PublishedCsvExporter:
    """Render one L3 published-row stream as a safe UTF-8 CSV download."""

    def __init__(self, query_service: PublishedRowsStreamer) -> None:
        self._query_service = query_service

    def stream_published_csv(
        self,
        scope: PublishedDetailScope,
        query: PublishedExportQuery,
        visible_column_ids: Sequence[UUID],
    ) -> Generator[bytes]:
        """Return a cancellable stream using L3's scope/search/sort semantics.

        Column validation finishes before the source factory is called.  The
        underlying row iterator is acquired only on this generator's first
        resume and its ``close`` is propagated when the download is cancelled.
        """

        if not isinstance(scope, PublishedDetailScope):
            raise TypeError("scope must be a PublishedDetailScope")
        if not isinstance(query, PublishedExportQuery):
            raise TypeError("query must be a PublishedExportQuery")
        columns, row_source = self._query_service.prepare_published_rows(
            scope,
            query.search,
            query.sort_column_id,
            query.direction,
            query.report_date,
            batch_size=_CSV_STREAM_BATCH_SIZE,
        )
        selected_columns = _select_columns(columns, visible_column_ids)
        return _stream_csv_rows(selected_columns, row_source)


def csv_safe_text(value: object | None) -> str:
    """Normalise one CSV cell without allowing spreadsheet formula execution."""

    if value is None:
        return ""
    text = value.isoformat() if isinstance(value, (datetime, date)) else str(value)
    text = _strip_leading_c0_controls(text)
    index = 0
    while index < len(text) and _is_ignored_leading_character(text[index]):
        index += 1
    if index < len(text) and text[index] in _FORMULA_PREFIXES:
        return "'" + text
    return text


def published_csv_content_disposition(scope: PublishedDetailScope) -> str:
    """Build attachment metadata with a safe ASCII fallback and UTF-8 filename."""

    if not isinstance(scope, PublishedDetailScope):
        raise TypeError("scope must be a PublishedDetailScope")
    report_type = scope.report_type.replace("_", "-")
    date_range = f"{scope.from_date.isoformat()}-to-{scope.to_date.isoformat()}"
    fallback = f"published-details-site-{scope.site_id}-{report_type}-{date_range}.csv"
    utf8_name = f"站点{scope.site_id}-{report_type}-{date_range}.csv"
    return (
        f'attachment; filename="{fallback}"; '
        f"filename*=UTF-8''{quote(utf8_name, safe='')}"
    )


def _select_columns(
    columns: Sequence[PublishedDetailColumn],
    requested_ids: Sequence[UUID] | str | bytes | bytearray,
) -> tuple[PublishedDetailColumn, ...]:
    if isinstance(requested_ids, (str, bytes, bytearray)):
        raise TypeError("visible_column_ids must be a sequence of UUID values")
    visible_by_id = {column.column_id: column for column in columns}
    selected: list[PublishedDetailColumn] = []
    requested_set: set[UUID] = set()
    for column_id in requested_ids:
        if not isinstance(column_id, UUID) or column_id in requested_set:
            raise InvalidPublishedExportColumn()
        try:
            column = visible_by_id[column_id]
        except KeyError as error:
            raise InvalidPublishedExportColumn() from error
        requested_set.add(column_id)
        selected.append(column)
    required_keys = tuple(
        column
        for column in columns
        if column.is_key and column.column_id not in requested_set
    )
    return required_keys + tuple(selected)


def _stream_csv_rows(
    columns: Sequence[PublishedDetailColumn],
    row_source: Callable[[], Iterator[PublishedDetailRow]],
) -> Generator[bytes]:
    rows: Iterator[PublishedDetailRow] | None = None
    try:
        rows = row_source()
        yield codecs.BOM_UTF8
        yield _csv_row_bytes(
            [*_SYSTEM_HEADERS, *(column.source_header for column in columns)]
        )
        for row in rows:
            cell_values = {cell.column_id: cell.value for cell in row.cells}
            yield _csv_row_bytes(
                [
                    row.report_date,
                    row.version_no,
                    row.row_ordinal,
                    *(cell_values.get(column.column_id) for column in columns),
                ]
            )
    finally:
        if rows is not None:
            close = getattr(rows, "close", None)
            if callable(close):
                close()


def _csv_row_bytes(values: Sequence[object | None]) -> bytes:
    target = StringIO(newline="")
    writer = csv.writer(target, lineterminator="\r\n")
    writer.writerow([csv_safe_text(value) for value in values])
    return target.getvalue().encode("utf-8")


def _strip_leading_c0_controls(text: str) -> str:
    index = 0
    while (
        index < len(text)
        and ord(text[index]) < 0x20
        and text[index] not in _PRESERVED_C0
    ):
        index += 1
    return text[index:]


def _is_ignored_leading_character(value: str) -> bool:
    return value.isspace() or ord(value) < 0x20
