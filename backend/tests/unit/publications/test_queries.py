from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from app.publications.queries import _UNDOABLE_PUBLISHED_MOVES
from sqlalchemy.engine import Engine


@pytest.fixture()
def query_engine() -> Iterator[Engine]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    statements = (
        """
        CREATE TABLE publication_commands (
            id INTEGER PRIMARY KEY, operation_token BLOB, operation_kind TEXT,
            operation_digest BLOB, actor_user_id INTEGER
        )
        """,
        """
        CREATE TABLE publication_command_results (
            command_id INTEGER PRIMARY KEY, operation_token BLOB,
            operation_kind TEXT, operation_digest BLOB, actor_user_id INTEGER,
            result_kind TEXT, result_status TEXT, result_dataset_id INTEGER,
            result_version_id INTEGER, publication_event_id INTEGER,
            validation_run_id INTEGER, move_revision_operation_token BLOB,
            reversed_move_command_id INTEGER, completed_at DATETIME
        )
        """,
        """
        CREATE TABLE publication_events (
            id INTEGER PRIMARY KEY, command_id INTEGER, sequence_number INTEGER,
            event_type TEXT, dataset_id INTEGER, peer_dataset_id INTEGER,
            previous_version_id INTEGER, next_version_id INTEGER,
            occurred_at DATETIME
        )
        """,
        """
        CREATE TABLE daily_datasets (
            id INTEGER PRIMARY KEY, site_id INTEGER, report_date DATE,
            report_type TEXT
        )
        """,
        """
        CREATE TABLE dataset_versions (
            id INTEGER PRIMARY KEY, dataset_id INTEGER, report_type TEXT,
            status TEXT
        )
        """,
        """
        CREATE TABLE draft_operation_results (
            operation_token BLOB, operation_kind TEXT, result_kind TEXT,
            result_status TEXT, result_dataset_id INTEGER,
            result_version_id INTEGER, source_dataset_id INTEGER,
            source_version_id INTEGER,
            published_move_source_parent_version_id INTEGER,
            published_move_source_lineage_type TEXT
        )
        """,
        """
        CREATE TABLE dataset_publications (
            dataset_id INTEGER PRIMARY KEY, version_id INTEGER,
            version_status TEXT, published_at DATETIME
        )
        """,
        "CREATE TABLE dataset_drafts (dataset_id INTEGER PRIMARY KEY)",
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
        connection.exec_driver_sql(
            "INSERT INTO publication_commands VALUES (1, X'01', 'move', X'02', 9)"
        )
        connection.exec_driver_sql(
            """
            INSERT INTO publication_command_results VALUES (
                1, X'01', 'move', X'02', 9, 'moved', 'published',
                20, 200, 102, 300, X'03', NULL, '2026-08-10 05:00:00'
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO publication_events VALUES
                (101, 1, 1, 'moved_out', 10, 20, 100, NULL,
                 '2026-08-10 05:00:00'),
                (102, 1, 2, 'moved_in', 20, 10, NULL, 200,
                 '2026-08-10 05:00:00')
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO daily_datasets VALUES
                (10, 1, '2026-08-10', 'business_report'),
                (20, 1, '2026-08-11', 'business_report')
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO dataset_versions VALUES
                (100, 10, 'business_report', 'published'),
                (200, 20, 'business_report', 'published')
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO draft_operation_results VALUES (
                X'03', 'create_published_move_revision',
                'move_revision_created', 'draft', 20, 200, 10, 100,
                100, 'moved_source'
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO dataset_publications VALUES (
                20, 200, 'published', '2026-08-10 05:00:00'
            )
            """
        )
    try:
        yield engine
    finally:
        engine.dispose()


def _command_ids(engine: Engine) -> list[int]:
    with engine.connect() as connection:
        return [
            int(row["move_command_id"])
            for row in connection.execute(_UNDOABLE_PUBLISHED_MOVES).mappings()
        ]


def test_complete_current_move_is_returned(query_engine: Engine) -> None:
    assert _command_ids(query_engine) == [1]


@pytest.mark.parametrize("draft_dataset_id", [10, 20])
def test_move_with_an_active_draft_is_hidden(
    query_engine: Engine,
    draft_dataset_id: int,
) -> None:
    with query_engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO dataset_drafts VALUES (:dataset_id)"),
            {"dataset_id": draft_dataset_id},
        )

    assert _command_ids(query_engine) == []


@pytest.mark.parametrize(
    ("statement", "parameters"),
    [
        (
            "INSERT INTO dataset_publications VALUES "
            "(10, 100, 'published', '2026-08-10 06:00:00')",
            {},
        ),
        (
            "UPDATE dataset_publications SET version_id = 201 WHERE dataset_id = 20",
            {},
        ),
        (
            "UPDATE dataset_publications SET published_at = "
            "'2026-08-10 06:00:00' WHERE dataset_id = 20",
            {},
        ),
        (
            "UPDATE publication_events SET peer_dataset_id = 30 WHERE id = 101",
            {},
        ),
        (
            "INSERT INTO publication_events VALUES "
            "(103, 1, 3, 'moved_in', 20, 10, NULL, 200, "
            "'2026-08-10 05:00:00')",
            {},
        ),
        (
            "INSERT INTO publication_events VALUES "
            "(201, 2, 1, 'rolled_back', 20, NULL, 201, 200, "
            "'2026-08-10 06:00:00')",
            {},
        ),
    ],
)
def test_pointer_drift_or_ambiguous_events_are_hidden(
    query_engine: Engine,
    statement: str,
    parameters: dict[str, object],
) -> None:
    with query_engine.begin() as connection:
        connection.execute(sa.text(statement), parameters)

    assert _command_ids(query_engine) == []


def test_successful_reversal_hides_original_move(query_engine: Engine) -> None:
    with query_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO publication_commands VALUES "
            "(2, X'04', 'reverse_move', X'05', 9)"
        )
        connection.exec_driver_sql(
            """
            INSERT INTO publication_command_results VALUES (
                2, X'04', 'reverse_move', X'05', 9, 'move_reversed',
                'published', 10, 100, 201, NULL, NULL, 1,
                '2026-08-10 06:00:00'
            )
            """
        )

    assert _command_ids(query_engine) == []
