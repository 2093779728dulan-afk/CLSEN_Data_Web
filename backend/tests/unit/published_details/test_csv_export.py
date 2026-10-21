from __future__ import annotations

import codecs
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from app.analytics.models import PublicationReference
from app.published_details.csv_export import (
    InvalidPublishedExportColumn,
    PublishedCsvExporter,
    PublishedExportQuery,
    csv_safe_text,
    published_csv_content_disposition,
)
from app.published_details.models import (
    PublishedDetailCell,
    PublishedDetailColumn,
    PublishedDetailRow,
    PublishedDetailScope,
)
from app.published_details.scope import PublishedScopeCodec
from app.published_details.service import PublishedDetailQueryService
from sqlalchemy.orm import Session

_KEY = UUID("10000000-0000-0000-0000-000000000001")
_VISIBLE = UUID("10000000-0000-0000-0000-000000000002")
_HIDDEN = UUID("10000000-0000-0000-0000-000000000003")
_EXTENSION = UUID("10000000-0000-0000-0000-000000000004")


@pytest.mark.parametrize("value", ["=1+1", " +SUM(A1:A2)", "\t@cmd", "\x00-2"])
def test_csv_safe_text_prefixes_formula_candidates(value: str) -> None:
    safe = csv_safe_text(value)

    assert safe.startswith("'")


def test_csv_safe_text_removes_only_leading_disallowed_c0_controls() -> None:
    assert csv_safe_text("\x00\x1fhello\x00") == "hello\x00"
    assert csv_safe_text("\t\r\ntext") == "\t\r\ntext"


def test_stream_starts_with_bom_and_quotes_newlines() -> None:
    exporter = PublishedCsvExporter(_FakePublishedRowsService())

    payload = b"".join(
        exporter.stream_published_csv(
            _scope(),
            PublishedExportQuery(),
            [_VISIBLE],
        )
    )

    assert payload.startswith(codecs.BOM_UTF8)
    assert b'"line 1\nline ""2"""' in payload
    assert "中文".encode() in payload


def test_export_forces_missing_key_columns_then_preserves_requested_order() -> None:
    service = _FakePublishedRowsService()
    exporter = PublishedCsvExporter(service)
    query = PublishedExportQuery(search="needle", direction="desc")

    payload = b"".join(
        exporter.stream_published_csv(_scope(), query, [_VISIBLE])
    ).decode("utf-8-sig")

    assert payload.splitlines()[0] == "报告日期,发布版本,行号,SKU,Public note"
    assert service.call == (_scope(), query.search, None, query.direction, None)


@pytest.mark.parametrize("column_ids", [[_HIDDEN], [_VISIBLE, _VISIBLE]])
def test_export_rejects_unknown_or_repeated_columns(column_ids: list[UUID]) -> None:
    service = _EventRecordingRowsService()
    exporter = PublishedCsvExporter(service)

    with pytest.raises(InvalidPublishedExportColumn):
        exporter.stream_published_csv(_scope(), PublishedExportQuery(), column_ids)

    assert service.events == ["prepared"]


def test_export_close_before_first_resume_never_acquires_source() -> None:
    service = _EventRecordingRowsService()
    iterator = PublishedCsvExporter(service).stream_published_csv(
        _scope(),
        PublishedExportQuery(),
        [_VISIBLE],
    )

    iterator.close()

    assert service.events == ["prepared"]


def test_export_closes_source_created_on_first_resume() -> None:
    service = _EventRecordingRowsService()
    iterator = PublishedCsvExporter(service).stream_published_csv(
        _scope(),
        PublishedExportQuery(),
        [_VISIBLE],
    )

    assert next(iterator) == codecs.BOM_UTF8
    assert service.events == ["prepared", "source"]
    iterator.close()

    assert service.events == ["prepared", "source", "source_closed"]


def test_export_closes_source_iterator_when_download_is_cancelled() -> None:
    service = _ClosingPublishedRowsService()
    iterator = PublishedCsvExporter(service).stream_published_csv(
        _scope(),
        PublishedExportQuery(),
        [_VISIBLE],
    )

    next(iterator)
    next(iterator)
    next(iterator)
    iterator.close()

    assert service.closed is True


def test_service_stream_closes_the_sqlalchemy_result_when_cancelled() -> None:
    scope = _scope()
    publication = scope.publications[0]
    pointer_row = {
        "dataset_id": publication.dataset_id,
        "site_id": publication.site_id,
        "report_date": publication.report_date,
        "report_type": publication.report_type,
        "version_id": publication.version_id,
        "published_at": publication.published_at.replace(tzinfo=None),
    }
    schema_row = {
        **pointer_row,
        "column_id": _KEY.bytes,
        "source_header": "SKU",
        "display_order": 1,
        "value_kind": "text",
        "standard_field_name": "sku",
        "is_key": True,
        "participates_in_statistics": True,
    }
    cursor_result = MagicMock()
    mappings = cursor_result.mappings.return_value
    mappings.yield_per.return_value = mappings
    mappings.fetchmany.side_effect = [
        [
            {
                "report_date": publication.report_date,
                "version_id": publication.version_id,
                "version_no": 4,
                "published_at": publication.published_at.replace(tzinfo=None),
                "row_id": 81,
                "row_ordinal": 1,
                "standard_value_0": "SKU-1",
            }
        ],
        [],
    ]
    session = MagicMock(spec=Session)
    session.execute.side_effect = [
        _all_result([{"site_id": 3, "current_config_version_id": 31, "config_id": 31}]),
        _all_result([pointer_row]),
        _all_result([schema_row]),
        cursor_result,
    ]
    service = PublishedDetailQueryService(session, _codec())

    _, rows = service.stream_published_rows(scope, None, None, "asc", batch_size=2)
    assert next(rows).row_ordinal == 1
    rows.close()

    assert cursor_result.close.called


def test_service_stream_reads_extension_values_without_a_second_statement() -> None:
    scope = _scope()
    publication = scope.publications[0]
    pointer_row = _pointer_row(scope)
    extension_schema_row = {
        **pointer_row,
        "column_id": _EXTENSION.bytes,
        "source_header": "Numeric extension",
        "display_order": 2,
        "value_kind": "integer",
        "standard_field_name": None,
        "is_key": False,
        "participates_in_statistics": False,
    }
    cursor_result = MagicMock()
    mappings = cursor_result.mappings.return_value
    mappings.yield_per.return_value = mappings
    mappings.fetchmany.side_effect = [
        [
            {
                "report_date": publication.report_date,
                "version_id": publication.version_id,
                "version_no": 4,
                "published_at": publication.published_at.replace(tzinfo=None),
                "row_id": 81,
                "row_ordinal": 1,
                "standard_value_0": "SKU-1",
                "extension_values_json": ('{"' + _EXTENSION.hex.upper() + '": "10"}'),
            }
        ],
        [],
    ]
    session = MagicMock(spec=Session)
    session.execute.side_effect = [
        _all_result([{"site_id": 3, "current_config_version_id": 31, "config_id": 31}]),
        _all_result([pointer_row]),
        _all_result([_standard_schema_row(pointer_row), extension_schema_row]),
        cursor_result,
    ]
    service = PublishedDetailQueryService(session, _codec())

    _, rows = service.stream_published_rows(scope, None, None, "asc", batch_size=1)
    assert session.execute.call_count == 3
    row = next(rows)

    assert [cell.value for cell in row.cells] == ["SKU-1", 10]
    assert session.execute.call_count == 4
    assert "JSON_OBJECTAGG" in str(session.execute.call_args.args[0])
    assert session.execute.call_args.args[1]["selected_extension_column_ids"] == (
        _EXTENSION.bytes,
    )
    rows.close()


def test_existing_paged_rows_keep_the_shared_query_plan_semantics() -> None:
    scope = _scope()
    publication = scope.publications[0]
    pointer_row = _pointer_row(scope)
    schema_row = _standard_schema_row(pointer_row)
    extension_schema_row = {
        **pointer_row,
        "column_id": _EXTENSION.bytes,
        "source_header": "Numeric extension",
        "display_order": 2,
        "value_kind": "integer",
        "standard_field_name": None,
        "is_key": False,
        "participates_in_statistics": False,
    }
    page_result = _all_result(
        [
            {
                "report_date": publication.report_date,
                "version_id": publication.version_id,
                "version_no": 4,
                "published_at": publication.published_at.replace(tzinfo=None),
                "row_id": 81,
                "row_ordinal": 1,
                "standard_value_0": "SKU-1",
                "extension_values_json": ('{"' + _EXTENSION.hex.upper() + '": "10"}'),
            }
        ]
    )
    session = MagicMock(spec=Session)
    session.execute.side_effect = [
        _all_result([{"site_id": 3, "current_config_version_id": 31, "config_id": 31}]),
        _all_result([pointer_row]),
        _all_result([schema_row, extension_schema_row]),
        page_result,
    ]
    session.scalar.return_value = 1
    service = PublishedDetailQueryService(session, _codec())

    page = service.query_published_rows(scope, "SKU", None, "asc", 1, 10)

    assert [row.row_ordinal for row in page.rows] == [1]
    assert [cell.value for cell in page.rows[0].cells] == ["SKU-1", 10]
    statement = str(session.execute.call_args_list[-1].args[0])
    parameters = session.execute.call_args_list[-1].args[1]
    assert (
        "ORDER BY datasets.report_date DESC, row_records.row_ordinal ASC" in statement
    )
    assert "LIMIT :limit OFFSET :offset" in statement
    assert "JSON_OBJECTAGG" in statement
    assert parameters["limit"] == 10
    assert parameters["offset"] == 0
    assert parameters["search"] == "%SKU%"
    assert parameters["selected_extension_column_ids"] == (_EXTENSION.bytes,)
    assert session.execute.call_count == 4


def test_content_disposition_has_ascii_fallback_and_utf8_metadata() -> None:
    disposition = published_csv_content_disposition(_scope())

    assert (
        'filename="published-details-site-3-business-report-2026-08-01-to-2026-08-02.csv"'
        in disposition
    )
    assert "filename*=UTF-8''" in disposition
    assert "%E7%AB%99%E7%82%B93" in disposition


class _FakePublishedRowsService:
    def __init__(self) -> None:
        self.call: tuple[object, ...] | None = None

    def prepare_published_rows(
        self,
        scope: PublishedDetailScope,
        search: str | None,
        sort_column_id: UUID | None,
        direction: str,
        report_date: date | None = None,
        *,
        batch_size: int = 100,
    ) -> tuple[
        tuple[PublishedDetailColumn, ...],
        Callable[[], Iterator[PublishedDetailRow]],
    ]:
        del batch_size
        self.call = (scope, search, sort_column_id, direction, report_date)
        return _columns(), lambda: iter([_row()])


class _ClosingPublishedRowsService(_FakePublishedRowsService):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    def prepare_published_rows(
        self,
        scope: PublishedDetailScope,
        search: str | None,
        sort_column_id: UUID | None,
        direction: str,
        report_date: date | None = None,
        *,
        batch_size: int = 100,
    ) -> tuple[
        tuple[PublishedDetailColumn, ...],
        Callable[[], Iterator[PublishedDetailRow]],
    ]:
        columns, _ = super().prepare_published_rows(
            scope,
            search,
            sort_column_id,
            direction,
            report_date,
            batch_size=batch_size,
        )

        def _rows() -> Iterator[PublishedDetailRow]:
            try:
                yield _row()
                yield _row()
            finally:
                self.closed = True

        return columns, _rows


class _EventRecordingRowsService:
    def __init__(self) -> None:
        self.events: list[str] = []

    def prepare_published_rows(
        self,
        scope: PublishedDetailScope,
        search: str | None,
        sort_column_id: UUID | None,
        direction: str,
        report_date: date | None = None,
        *,
        batch_size: int = 100,
    ) -> tuple[
        tuple[PublishedDetailColumn, ...],
        Callable[[], Iterator[PublishedDetailRow]],
    ]:
        del scope, search, sort_column_id, direction, report_date, batch_size
        self.events.append("prepared")
        return _columns(), self._source

    def _source(self) -> Iterator[PublishedDetailRow]:
        self.events.append("source")
        return _ClosingIterator(self.events)


class _ClosingIterator:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._rows = iter([_row()])

    def __iter__(self) -> _ClosingIterator:
        return self

    def __next__(self) -> PublishedDetailRow:
        return next(self._rows)

    def close(self) -> None:
        self._events.append("source_closed")


def _columns() -> tuple[PublishedDetailColumn, ...]:
    return (
        PublishedDetailColumn(
            column_id=_KEY,
            source_header="SKU",
            display_order=1,
            value_kind="text",
            standard_field_name="sku",
            is_key=True,
            participates_in_statistics=True,
        ),
        PublishedDetailColumn(
            column_id=_VISIBLE,
            source_header="Public note",
            display_order=2,
            value_kind="text",
            standard_field_name="note",
            is_key=False,
            participates_in_statistics=False,
        ),
    )


def _row() -> PublishedDetailRow:
    return PublishedDetailRow(
        report_date=date(2026, 8, 1),
        version_id=100,
        version_no=4,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        row_ordinal=7,
        cells=[
            PublishedDetailCell(column_id=_KEY, value="中文"),
            PublishedDetailCell(column_id=_VISIBLE, value='line 1\nline "2"'),
        ],
    )


def _scope() -> PublishedDetailScope:
    issued_at = datetime(2026, 8, 17, 12, tzinfo=UTC)
    return PublishedDetailScope(
        user_id=7,
        roles=("admin",),
        site_id=3,
        report_type="business_report",
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 2),
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=5),
        publications=(
            PublicationReference(
                dataset_id=10,
                site_id=3,
                report_date=date(2026, 8, 1),
                report_type="business_report",
                version_id=100,
                published_at=datetime(2026, 8, 1, tzinfo=UTC),
            ),
        ),
    )


def _codec() -> PublishedScopeCodec:
    return PublishedScopeCodec(
        secret="csv-export-unit-secret",
        clock=lambda: datetime(2026, 8, 17, 12, tzinfo=UTC),
        ttl=timedelta(minutes=5),
    )


def _all_result(rows: list[dict[str, object]]) -> MagicMock:
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


def _pointer_row(scope: PublishedDetailScope) -> dict[str, object]:
    publication = scope.publications[0]
    return {
        "dataset_id": publication.dataset_id,
        "site_id": publication.site_id,
        "report_date": publication.report_date,
        "report_type": publication.report_type,
        "version_id": publication.version_id,
        "published_at": publication.published_at.replace(tzinfo=None),
    }


def _standard_schema_row(pointer_row: dict[str, object]) -> dict[str, object]:
    return {
        **pointer_row,
        "column_id": _KEY.bytes,
        "source_header": "SKU",
        "display_order": 1,
        "value_kind": "text",
        "standard_field_name": "sku",
        "is_key": True,
        "participates_in_statistics": True,
    }
