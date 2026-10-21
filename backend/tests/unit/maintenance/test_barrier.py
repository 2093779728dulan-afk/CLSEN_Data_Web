from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from app.maintenance.barrier import (
    MaintenanceBarrierError,
    MaintenanceBarrierSettings,
    MaintenanceBarrierTimeout,
    _acquire_before_write,
    _clear_writer_state,
    _release_on_checkin,
)


class _MySqlError(RuntimeError):
    pass


class _Cursor:
    def __init__(self, owner: _DbApiConnection) -> None:
        self._owner = owner

    def execute(self, statement: str, parameters: object = None) -> None:
        self._owner.executions.append((statement, parameters))
        if self._owner.errors:
            error = self._owner.errors.pop(0)
            if error is not None:
                raise error

    def fetchone(self) -> tuple[int] | None:
        return self._owner.rows.pop(0)

    def close(self) -> None:
        pass


class _DbApiConnection:
    def __init__(
        self,
        *rows: tuple[int] | None,
        errors: list[BaseException | None] | None = None,
    ) -> None:
        self.rows = list(rows)
        self.errors = list(errors or [])
        self.executions: list[tuple[str, object]] = []
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def close(self) -> None:
        self.closed = True


class _Connection:
    def __init__(self, dbapi: _DbApiConnection) -> None:
        self.connection = dbapi
        self.info: dict[str, object] = {}
        self.invalidated = False

    def invalidate(self) -> None:
        self.invalidated = True


def _acquire(
    connection: _Connection,
    statement: str,
    *,
    context: object | None = None,
) -> None:
    _acquire_before_write(
        connection,  # type: ignore[arg-type]
        None,
        statement,
        None,
        context or SimpleNamespace(),
        False,
        timeout_seconds=7,
    )


def test_settings_reject_unbounded_or_invalid_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_MAINTENANCE_WRITE_LOCK_TIMEOUT_SECONDS", "301")
    with pytest.raises(ValueError, match="between 0 and 300"):
        MaintenanceBarrierSettings.from_env()

    monkeypatch.setenv("APP_MAINTENANCE_WRITE_LOCK_TIMEOUT_SECONDS", "later")
    with pytest.raises(ValueError, match="must be an integer"):
        MaintenanceBarrierSettings.from_env()


def test_select_does_not_acquire_the_write_barrier() -> None:
    dbapi = _DbApiConnection()
    connection = _Connection(dbapi)

    _acquire(connection, "SELECT * FROM dataset_versions")

    assert dbapi.executions == []
    assert connection.info == {}


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO notes VALUES (1)",
        " UPDATE notes SET revision = 2",
        "/* retry */ DELETE FROM auth_sessions WHERE id = 1",
        "CREATE TEMPORARY TABLE backup_probe (id BIGINT)",
    ],
)
def test_write_transaction_acquires_one_shared_barrier_row_lock(
    statement: str,
) -> None:
    dbapi = _DbApiConnection((50,), (1,))
    connection = _Connection(dbapi)

    _acquire(connection, statement)
    _acquire(connection, "UPDATE notes SET revision = 3")

    assert [item[0] for item in dbapi.executions] == [
        "SELECT @@SESSION.innodb_lock_wait_timeout",
        "SET SESSION innodb_lock_wait_timeout = %s",
        "SELECT id FROM maintenance_write_barrier WHERE id = 1 FOR SHARE",
        "SET SESSION innodb_lock_wait_timeout = %s",
    ]
    assert dbapi.executions[1][1] == (7,)
    assert dbapi.executions[3][1] == (50,)
    assert connection.info == {"clsen_maintenance_write_lock_held": "writer"}


def test_sqlalchemy_dml_context_acquires_even_without_a_text_prefix() -> None:
    dbapi = _DbApiConnection((50,), (1,))
    connection = _Connection(dbapi)

    _acquire(
        connection,
        "WITH source AS (SELECT 1) INSERT INTO notes SELECT * FROM source",
        context=SimpleNamespace(isinsert=True),
    )

    assert "FOR SHARE" in dbapi.executions[2][0]


def test_statement_can_request_a_nonblocking_barrier_probe() -> None:
    dbapi = _DbApiConnection((1,))
    connection = _Connection(dbapi)

    _acquire(
        connection,
        "UPDATE auth_sessions SET last_seen_at = UTC_TIMESTAMP(6)",
        context=SimpleNamespace(
            execution_options={"clsen_maintenance_write_lock_timeout_seconds": 0}
        ),
    )

    assert dbapi.executions == [
        (
            "SELECT id FROM maintenance_write_barrier WHERE id = 1 FOR SHARE NOWAIT",
            None,
        )
    ]


@pytest.mark.parametrize("error_code", [1205, 3572])
def test_busy_barrier_rejects_write_without_invalidating_connection(
    error_code: int,
) -> None:
    dbapi = _DbApiConnection(errors=[_MySqlError(error_code, "barrier row is locked")])
    connection = _Connection(dbapi)

    with pytest.raises(MaintenanceBarrierTimeout, match="remained busy"):
        _acquire(
            connection,
            "INSERT INTO notes VALUES (1)",
            context=SimpleNamespace(
                execution_options={"clsen_maintenance_write_lock_timeout_seconds": 0}
            ),
        )

    assert connection.invalidated is False
    assert connection.info == {}


def test_uncertain_acquire_invalidates_the_connection() -> None:
    dbapi = _DbApiConnection(errors=[RuntimeError("connection lost during row lock")])
    connection = _Connection(dbapi)

    with pytest.raises(RuntimeError, match="connection lost"):
        _acquire(connection, "UPDATE notes SET revision = 2")

    assert connection.invalidated is True


def test_timeout_restoration_failure_invalidates_the_connection() -> None:
    dbapi = _DbApiConnection(
        (50,),
        (1,),
        errors=[None, None, None, RuntimeError("session state unavailable")],
    )
    connection = _Connection(dbapi)

    with pytest.raises(MaintenanceBarrierError, match="could not be restored"):
        _acquire(connection, "UPDATE notes SET revision = 2")

    assert connection.invalidated is True
    assert connection.info == {}


@pytest.mark.parametrize("transaction_event", ["commit", "rollback"])
def test_transaction_end_clears_writer_state(transaction_event: str) -> None:
    connection = _Connection(_DbApiConnection())
    connection.info["clsen_maintenance_write_lock_held"] = "writer"

    _clear_writer_state(connection)  # type: ignore[arg-type]

    assert transaction_event in {"commit", "rollback"}
    assert connection.info == {}


def test_invalidated_transaction_end_does_not_revalidate_connection() -> None:
    class InvalidatedConnection:
        invalidated = True

        @property
        def info(self) -> dict[str, object]:
            pytest.fail("invalidated connection info must not be accessed")

    _clear_writer_state(InvalidatedConnection())  # type: ignore[arg-type]


def test_checkin_only_clears_writer_state() -> None:
    dbapi = _DbApiConnection()
    record = SimpleNamespace(info={"clsen_maintenance_write_lock_held": "writer"})

    _release_on_checkin(dbapi, record)

    assert dbapi.executions == []
    assert record.info == {}
    assert dbapi.closed is False


def test_checkin_releases_a_maintenance_named_lock() -> None:
    dbapi = _DbApiConnection((1,))
    record = SimpleNamespace(info={"clsen_maintenance_write_lock_held": "maintenance"})

    _release_on_checkin(dbapi, record)

    assert "RELEASE_LOCK" in dbapi.executions[0][0]
    assert record.info == {}
    assert dbapi.closed is False


def test_failed_maintenance_release_discards_the_physical_connection() -> None:
    dbapi = _DbApiConnection((0,))
    record: Any = SimpleNamespace(
        info={"clsen_maintenance_write_lock_held": "maintenance"}
    )

    _release_on_checkin(dbapi, record)

    assert dbapi.closed is True
