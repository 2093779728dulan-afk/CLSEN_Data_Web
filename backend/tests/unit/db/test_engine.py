from __future__ import annotations

from typing import Any

from app.db.engine import configure_mysql_connection, create_database_engine
from app.db.settings import DatabaseSettings
from sqlalchemy.exc import DBAPIError


class RecordingCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.closed = False

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def close(self) -> None:
        self.closed = True


class RecordingConnection:
    def __init__(self) -> None:
        self.recording_cursor = RecordingCursor()

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor


def test_each_mysql_connection_is_explicitly_set_to_utc() -> None:
    connection = RecordingConnection()

    configure_mysql_connection(connection, None)

    assert connection.recording_cursor.statements == ["SET time_zone = '+00:00'"]
    assert connection.recording_cursor.closed


def test_engine_uses_bounded_sync_pool_and_read_committed(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    sentinel = object()

    def fake_create_engine(*args: Any, **kwargs: Any) -> object:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return sentinel

    def fake_listen(*args: Any, **kwargs: Any) -> None:
        captured["listener"] = (args, kwargs)

    def fake_install_barrier(engine: object) -> None:
        captured["barrier_engine"] = engine

    monkeypatch.setattr("app.db.engine.sa.create_engine", fake_create_engine)
    monkeypatch.setattr("app.db.engine.sa.event.listen", fake_listen)
    monkeypatch.setattr(
        "app.db.engine.install_maintenance_write_barrier",
        fake_install_barrier,
    )
    settings = DatabaseSettings.from_url(
        "mysql+pymysql://clsen_app:secret@127.0.0.1:3306/clsen_data?charset=utf8mb4",
        pool_size=10,
        max_overflow=20,
    )

    engine = create_database_engine(settings)

    assert engine is sentinel
    assert captured["args"] == (settings.url,)
    assert captured["kwargs"] == {
        "hide_parameters": True,
        "isolation_level": "READ COMMITTED",
        "max_overflow": 20,
        "pool_pre_ping": True,
        "pool_size": 10,
    }
    assert captured["listener"] == (
        (sentinel, "connect", configure_mysql_connection),
        {},
    )
    assert captured["barrier_engine"] is sentinel


def test_hidden_database_parameters_do_not_leak_business_values() -> None:
    error = DBAPIError(
        statement="INSERT INTO parsed_source_rows VALUES (:decoded_fields)",
        params={"decoded_fields": "sensitive-order-and-comment"},
        orig=RuntimeError("injected database failure"),
        hide_parameters=True,
    )

    rendered = str(error)

    assert "sensitive-order-and-comment" not in rendered
    assert "SQL parameters hidden" in rendered
