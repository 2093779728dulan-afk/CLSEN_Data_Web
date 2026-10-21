"""Execute the calendar import query against historical/new failure cases."""

import sqlite3
from datetime import date
from typing import cast

from app.api.data_calendar import _add_reviewer_calendar_signals
from sqlalchemy.orm import Session


def test_published_replacement_clears_only_older_same_scope_failure() -> None:
    statements: list[str] = []

    class EmptyResult:
        def mappings(self) -> list[object]:
            return []

    class Capture:
        def execute(self, statement: object, parameters: object) -> EmptyResult:
            del parameters
            statements.append(str(statement))
            return EmptyResult()

    _add_reviewer_calendar_signals(
        cast(Session, Capture()),
        days={},
        start_date=date(2026, 8, 2),
        end_date=date(2026, 8, 2),
    )
    query = next(q for q in statements if "AS has_failed_import" in q)
    with sqlite3.connect(":memory:") as db:
        db.executescript("""
            CREATE TABLE import_batches (site_id, report_date, status,
                raw_file_id, confirmed_at, confirmed_report_type, created_at, id);
            CREATE TABLE raw_file_integrity_statuses (raw_file_id, status);
            CREATE TABLE daily_datasets (id, site_id, report_date, report_type);
            CREATE TABLE dataset_publications (dataset_id, published_at, version_id);
            CREATE TABLE version_input_batches (version_id, batch_id);
            INSERT INTO import_batches VALUES
                (1,'2026-08-02','processing_failed',1,'2026-09-11',
                 'business_report','2026-09-11 10:00:00',1);
            INSERT INTO import_batches VALUES
                (1,'2026-08-02','staged',2,NULL,'business_report',
                 '2026-09-11 11:00:00',2);
            INSERT INTO version_input_batches VALUES (9,2);
            INSERT INTO daily_datasets VALUES (1,1,'2026-08-02','business_report');
        """)
        params = {"start_date": "2026-08-02", "end_date": "2026-08-02"}

        def blocked() -> int:
            row = db.execute(query, params).fetchone()
            assert row is not None
            return int(row[1])

        assert blocked() == 1
        db.execute(
            "INSERT INTO dataset_publications VALUES (1,'2026-09-11 11:00:00',9)"
        )
        assert blocked() == 0
        db.execute(
            "UPDATE import_batches SET created_at='2026-09-11 12:00:00' WHERE id=1"
        )
        assert blocked() == 1
        db.execute(
            "UPDATE import_batches SET created_at='2026-09-11 10:00:00' WHERE id=1"
        )
        db.execute("UPDATE daily_datasets SET site_id=2")
        assert blocked() == 1
        db.execute("UPDATE daily_datasets SET site_id=1,report_type='return_report'")
        assert blocked() == 1
        db.execute(
            "UPDATE daily_datasets SET report_type='business_report', "
            "report_date='2026-08-03'"
        )
        assert blocked() == 1
