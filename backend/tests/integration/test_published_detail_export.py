from __future__ import annotations

import codecs
import csv
from datetime import date, timedelta
from io import StringIO
from uuid import uuid4

import app.published_details.csv_export as csv_export
import pytest
import sqlalchemy as sa
from app.auth.sessions import Principal
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import MaterializeBaselineCommand
from app.published_details.csv_export import PublishedCsvExporter, PublishedExportQuery
from app.published_details.scope import PublishedScopeCodec
from app.published_details.service import PublishedDetailQueryService
from sqlalchemy.orm import Session

from tests.integration.dataset_test_support import NOW, DatasetIntegrationCase
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers shared fixture
)

pytestmark = pytest.mark.mysql


def test_export_matches_rows_filters_and_current_publication_only(
    dataset_case: DatasetIntegrationCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A skipped-on-default MySQL proof for cursor-safe L3/L4 equivalence."""

    day_one = _isolated_date()
    day_two = day_one + timedelta(days=1)
    dataset_id, old_version_id = _materialize(
        dataset_case,
        day_one,
        "export-old-marker",
        expected_publication_version_id=None,
        extra_columns=(("Export score", "0"),),
    )
    dataset_case.mark_published(dataset_id, old_version_id)
    revised_dataset_id, current_version_id = _materialize(
        dataset_case,
        day_one,
        "export-current-marker",
        expected_publication_version_id=old_version_id,
        extra_columns=(("Export score", "0"),),
    )
    assert revised_dataset_id == dataset_id
    _set_extension_kind_and_values(
        dataset_case,
        version_id=current_version_id,
        source_header="Export score",
        values_by_ordinal={1: "10", 2: "2"},
    )
    _repoint_publication(dataset_case, dataset_id, current_version_id)
    day_two_dataset_id, day_two_version_id = _materialize(
        dataset_case,
        day_two,
        "export-day-two-marker",
        expected_publication_version_id=None,
        extra_columns=(("Export score", "0"),),
    )
    _set_extension_kind_and_values(
        dataset_case,
        version_id=day_two_version_id,
        source_header="Export score",
        values_by_ordinal={1: "4", 2: "3"},
    )
    dataset_case.mark_published(day_two_dataset_id, day_two_version_id)
    monkeypatch.setattr(csv_export, "_CSV_STREAM_BATCH_SIZE", 1)

    with Session(dataset_case.migration_engine) as session:
        service = PublishedDetailQueryService(session, _codec())
        scope = service.resolve_publication_scope(
            _principal(dataset_case), "business_report", day_one, day_two
        )
        schema_page = service.query_published_rows(
            scope, "SYN", None, "asc", page=1, page_size=100
        )
        score_column_id = next(
            column.column_id
            for column in schema_page.columns
            if column.source_header == "Export score"
        )
        page = service.query_published_rows(
            scope,
            "SYN",
            score_column_id,
            "asc",
            page=1,
            page_size=100,
        )
        payload = b"".join(
            PublishedCsvExporter(service).stream_published_csv(
                scope,
                PublishedExportQuery(
                    search="SYN",
                    sort_column_id=score_column_id,
                    direction="asc",
                ),
                [column.column_id for column in page.columns],
            )
        )

    assert payload.startswith(codecs.BOM_UTF8)
    csv_rows = list(csv.reader(StringIO(payload.decode("utf-8-sig"))))
    assert len(csv_rows) == len(page.rows) + 1
    exported = "\n".join(",".join(row) for row in csv_rows)
    assert "export-old-marker" not in exported
    assert "export-current-marker" in exported
    assert "export-day-two-marker" in exported
    assert {str(current_version_id), str(day_two_version_id)}.isdisjoint(
        {str(cell) for row in csv_rows[1:] for cell in row}
    )
    assert {row.report_date.isoformat() for row in page.rows} == {
        row[0] for row in csv_rows[1:]
    }
    score_index = csv_rows[0].index("Export score")
    assert [int(row[score_index]) for row in csv_rows[1:]] == [2, 3, 4, 10]
    assert [(row.report_date.isoformat(), row.row_ordinal) for row in page.rows] == [
        (row[0], int(row[2])) for row in csv_rows[1:]
    ]


def _isolated_date() -> date:
    return date(2220, 1, 1) + timedelta(days=uuid4().int % 20000)


def _principal(case: DatasetIntegrationCase) -> Principal:
    return Principal(
        user_id=case.owner_user_id,
        username="published-export-user",
        display_name="Published export user",
        roles=frozenset({"data_manager"}),
        session_id=1,
        csrf_token_hash=b"published-export-csrf",
    )


def _codec() -> PublishedScopeCodec:
    return PublishedScopeCodec(
        secret="published-detail-export-integration-secret",
        clock=lambda: NOW,
        ttl=timedelta(minutes=5),
    )


def _materialize(
    case: DatasetIntegrationCase,
    report_date: date,
    variant: str,
    *,
    expected_publication_version_id: int | None,
    extra_columns: tuple[tuple[str, str], ...] = (),
) -> tuple[int, int]:
    baseline = case.seed_baseline(
        report_date=report_date,
        report_type="business_report",
        variant=variant,
        extra_columns=extra_columns,
    )
    result = DatasetService(
        repository=MySqlDatasetRepository(case.migration_engine),
        clock=lambda: NOW,
    ).materialize_baseline(
        MaterializeBaselineCommand(
            batch_id=baseline.batch_id,
            parse_baseline_id=baseline.parse_baseline_id,
            report_date=report_date,
            strategy="replace",
            expected_active_draft=None,
            expected_publication_version_id=expected_publication_version_id,
            merge_decisions=(),
            actor_user_id=case.owner_user_id,
            operation_token=uuid4(),
            reason="Seed a published-detail CSV export version",
        )
    )
    return result.dataset_id, result.version_id


def _set_extension_kind_and_values(
    case: DatasetIntegrationCase,
    *,
    version_id: int,
    source_header: str,
    values_by_ordinal: dict[int, str],
) -> None:
    column_rows = case.rows(
        """
        SELECT column_id
        FROM version_table_columns
        WHERE version_id = :version_id AND source_header = :source_header
        """,
        {"version_id": version_id, "source_header": source_header},
    )
    assert len(column_rows) == 1
    column_id = column_rows[0]["column_id"]
    row_records = case.rows(
        """
        SELECT id, row_ordinal
        FROM version_rows
        WHERE version_id = :version_id
        ORDER BY row_ordinal
        """,
        {"version_id": version_id},
    )
    assert {int(row["row_ordinal"]) for row in row_records} == set(values_by_ordinal)
    with case.migration_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                UPDATE version_table_columns
                SET value_kind = 'integer'
                WHERE version_id = :version_id AND column_id = :column_id
                """
            ),
            {"version_id": version_id, "column_id": column_id},
        )
        for row in row_records:
            value = values_by_ordinal[int(row["row_ordinal"])]
            connection.execute(
                sa.text(
                    """
                    UPDATE version_extension_cells
                    SET base_value = :value, current_value = :value
                    WHERE version_id = :version_id
                      AND row_id = :row_id
                      AND column_id = :column_id
                    """
                ),
                {
                    "version_id": version_id,
                    "row_id": int(row["id"]),
                    "column_id": column_id,
                    "value": value,
                },
            )


def _repoint_publication(
    case: DatasetIntegrationCase,
    dataset_id: int,
    version_id: int,
) -> None:
    published_at = NOW + timedelta(minutes=1)
    with case.migration_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                DELETE FROM dataset_drafts
                WHERE dataset_id = :dataset_id AND version_id = :version_id
                """
            ),
            {"dataset_id": dataset_id, "version_id": version_id},
        )
        connection.execute(
            sa.text(
                """
                UPDATE dataset_versions
                SET status = 'published', sealed_at = :published_at
                WHERE dataset_id = :dataset_id AND id = :version_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "version_id": version_id,
                "published_at": published_at.replace(tzinfo=None),
            },
        )
        connection.execute(
            sa.text(
                """
                UPDATE dataset_publications
                SET version_id = :version_id, published_at = :published_at
                WHERE dataset_id = :dataset_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "version_id": version_id,
                "published_at": published_at.replace(tzinfo=None),
            },
        )
