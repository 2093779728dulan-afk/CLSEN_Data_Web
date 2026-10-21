from __future__ import annotations

from types import TracebackType
from typing import Any, cast

import pytest
from app.imports.repository import MySqlIngestRepository
from sqlalchemy.engine import Engine


class _InjectedLockBoundary(BaseException):
    """Represent an interruption outside SQLAlchemy's normal Exception path."""


class _RecordingConnection:
    def __init__(self, *, fail_statement: str) -> None:
        self.fail_statement = fail_statement
        self.invalidated = False
        self.commits = 0

    def scalar(self, statement: Any, _parameters: object) -> int:
        if self.fail_statement in str(statement):
            raise _InjectedLockBoundary(f"injected {self.fail_statement} failure")
        return 1

    def commit(self) -> None:
        self.commits += 1

    def in_transaction(self) -> bool:
        return False

    def rollback(self) -> None:
        pytest.fail("no transaction should require rollback in this test")

    def invalidate(self) -> None:
        self.invalidated = True


class _ConnectionContext:
    def __init__(self, connection: _RecordingConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _RecordingConnection:
        return self.connection

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None


class _RecordingEngine:
    def __init__(self, connection: _RecordingConnection) -> None:
        self.connection = connection

    def connect(self) -> _ConnectionContext:
        return _ConnectionContext(self.connection)


def _repository(connection: _RecordingConnection) -> MySqlIngestRepository:
    engine = cast(Engine, _RecordingEngine(connection))
    return MySqlIngestRepository(engine, lock_timeout_seconds=0)


def test_get_lock_result_uncertainty_explicitly_invalidates_connection() -> None:
    connection = _RecordingConnection(fail_statement="GET_LOCK")

    with (
        pytest.raises(_InjectedLockBoundary, match="GET_LOCK failure"),
        _repository(connection).digest_lock("ab" * 32),
    ):
        pytest.fail("an uncertain GET_LOCK result must not yield")

    assert connection.invalidated is True


def test_release_lock_base_exception_invalidates_before_propagating() -> None:
    connection = _RecordingConnection(fail_statement="RELEASE_LOCK")

    with (
        pytest.raises(_InjectedLockBoundary, match="RELEASE_LOCK failure"),
        _repository(connection).digest_lock("cd" * 32),
    ):
        pass

    assert connection.invalidated is True
