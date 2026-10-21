"""Database-scoped MySQL write barrier used by backups and application writers."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

_LOGGER = logging.getLogger("app.maintenance.barrier")
_LOCK_HELD_INFO_KEY = "clsen_maintenance_write_lock_held"
_WRITER_LOCK_STATE = "writer"
_MAINTENANCE_LOCK_STATE = "maintenance"
_LOCK_NAME_SQL = "CONCAT('clsen:maintenance-write:', DATABASE())"
_BARRIER_ROW_SQL = "SELECT id FROM maintenance_write_barrier WHERE id = 1"
MAINTENANCE_WRITE_LOCK_TIMEOUT_OPTION = "clsen_maintenance_write_lock_timeout_seconds"
_WRITE_PREFIX = re.compile(
    r"^\s*(?:/\*.*?\*/\s*)*(?:INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|"
    r"TRUNCATE|RENAME)\b",
    flags=re.IGNORECASE | re.DOTALL,
)


class MaintenanceBarrierError(RuntimeError):
    """The write barrier could not establish or release a safe lock state."""


class MaintenanceBarrierTimeout(MaintenanceBarrierError):
    """Another maintenance operation held the database write barrier too long."""


@dataclass(frozen=True, slots=True)
class MaintenanceBarrierSettings:
    """Bounded wait settings shared by writers and backup orchestration."""

    write_timeout_seconds: int = 30

    def __post_init__(self) -> None:
        if not 0 <= self.write_timeout_seconds <= 300:
            raise ValueError("maintenance write lock timeout must be between 0 and 300")

    @classmethod
    def from_env(cls) -> MaintenanceBarrierSettings:
        raw_value = os.getenv("APP_MAINTENANCE_WRITE_LOCK_TIMEOUT_SECONDS", "30")
        try:
            timeout = int(raw_value)
        except ValueError as error:
            raise ValueError(
                "APP_MAINTENANCE_WRITE_LOCK_TIMEOUT_SECONDS must be an integer"
            ) from error
        return cls(write_timeout_seconds=timeout)


def _is_write_statement(statement: str, context: Any) -> bool:
    if any(
        bool(getattr(context, attribute, False))
        for attribute in ("isinsert", "isupdate", "isdelete")
    ):
        return True
    return _WRITE_PREFIX.match(statement) is not None


def _acquire_before_write(
    connection: Connection,
    _cursor: Any,
    statement: str,
    _parameters: Any,
    context: Any,
    _executemany: bool,
    *,
    timeout_seconds: int,
) -> None:
    if connection.info.get(_LOCK_HELD_INFO_KEY) or not _is_write_statement(
        statement, context
    ):
        return

    execution_options = getattr(context, "execution_options", {})
    statement_timeout = execution_options.get(
        MAINTENANCE_WRITE_LOCK_TIMEOUT_OPTION,
        timeout_seconds,
    )
    if type(statement_timeout) is not int or not 0 <= statement_timeout <= 300:
        raise MaintenanceBarrierError(
            "the statement maintenance lock timeout is invalid"
        )

    _acquire_barrier_row(
        connection,
        timeout_seconds=statement_timeout,
        lock_clause="FOR SHARE",
    )
    connection.info[_LOCK_HELD_INFO_KEY] = _WRITER_LOCK_STATE


def _is_lock_timeout(error: BaseException) -> bool:
    arguments = getattr(error, "args", ())
    error_code = next(iter(arguments), None)
    return error_code in {1205, 3572}


def _acquire_barrier_row(
    connection: Connection,
    *,
    timeout_seconds: int,
    lock_clause: str,
) -> None:
    if lock_clause not in {"FOR SHARE", "FOR UPDATE"}:
        raise ValueError("unsupported maintenance barrier row lock")
    cursor = connection.connection.cursor()
    previous_timeout: int | None = None
    acquisition_error: BaseException | None = None
    try:
        if timeout_seconds == 0:
            cursor.execute(f"{_BARRIER_ROW_SQL} {lock_clause} NOWAIT")
        else:
            cursor.execute("SELECT @@SESSION.innodb_lock_wait_timeout")
            timeout_row = cursor.fetchone()
            if timeout_row is None or type(timeout_row[0]) is not int:
                raise MaintenanceBarrierError(
                    "the database lock wait timeout is unavailable"
                )
            previous_timeout = timeout_row[0]
            cursor.execute(
                "SET SESSION innodb_lock_wait_timeout = %s",
                (max(1, timeout_seconds),),
            )
            cursor.execute(f"{_BARRIER_ROW_SQL} {lock_clause}")
        row = cursor.fetchone()
    except BaseException as error:
        acquisition_error = error
        if _is_lock_timeout(error):
            raise MaintenanceBarrierTimeout(
                "the database maintenance write barrier remained busy"
            ) from error
        connection.invalidate()
        raise
    finally:
        if previous_timeout is not None and not connection.invalidated:
            try:
                cursor.execute(
                    "SET SESSION innodb_lock_wait_timeout = %s",
                    (previous_timeout,),
                )
            except BaseException as error:
                connection.invalidate()
                if acquisition_error is None:
                    raise MaintenanceBarrierError(
                        "the database lock wait timeout could not be restored"
                    ) from error
                _LOGGER.exception(
                    "Lock timeout restoration failed after barrier acquisition failure"
                )
        cursor.close()
    if row is None or row[0] != 1:
        connection.invalidate()
        raise MaintenanceBarrierError(
            "the immutable maintenance barrier row is missing"
        )


def _clear_writer_state(connection: Connection) -> None:
    # SQLAlchemy cannot expose ``Connection.info`` after a DBAPI connection was
    # invalidated while its transaction is still being unwound.  The pool check-in
    # listener clears the connection-record state, and the severed database session
    # has already released its transactional row lock.
    if connection.invalidated:
        return
    if connection.info.get(_LOCK_HELD_INFO_KEY) == _WRITER_LOCK_STATE:
        connection.info.pop(_LOCK_HELD_INFO_KEY, None)


def _release_on_checkin(dbapi_connection: Any, connection_record: Any) -> None:
    state = connection_record.info.pop(_LOCK_HELD_INFO_KEY, None)
    if dbapi_connection is None or state != _MAINTENANCE_LOCK_STATE:
        return

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"SELECT RELEASE_LOCK({_LOCK_NAME_SQL})")
        row = cursor.fetchone()
        if row is None or row[0] != 1:
            raise MaintenanceBarrierError(
                "the database maintenance write barrier was not owned on check-in"
            )
    except BaseException:
        _LOGGER.exception(
            "Maintenance lock release failed; closing the physical connection"
        )
        dbapi_connection.close()
    finally:
        cursor.close()


def install_maintenance_write_barrier(
    engine: Engine,
    settings: MaintenanceBarrierSettings | None = None,
) -> None:
    """Protect all DML/DDL issued through one application engine."""

    resolved = settings or MaintenanceBarrierSettings.from_env()

    def acquire_listener(
        connection: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        _acquire_before_write(
            connection,
            cursor,
            statement,
            parameters,
            context,
            executemany,
            timeout_seconds=resolved.write_timeout_seconds,
        )

    sa.event.listen(engine, "before_cursor_execute", acquire_listener)
    sa.event.listen(engine, "commit", _clear_writer_state)
    sa.event.listen(engine, "rollback", _clear_writer_state)
    sa.event.listen(engine.pool, "checkin", _release_on_checkin)


@contextmanager
def hold_maintenance_write_barrier(
    engine: Engine,
    *,
    timeout_seconds: int = 30,
) -> Iterator[Connection]:
    """Hold the database-scoped barrier on one dedicated backup connection."""

    if not 0 <= timeout_seconds <= 300:
        raise ValueError("maintenance lock timeout must be between 0 and 300")

    with engine.connect() as connection:
        try:
            acquired = connection.scalar(
                sa.text(f"SELECT GET_LOCK({_LOCK_NAME_SQL}, :timeout_seconds)"),
                {"timeout_seconds": timeout_seconds},
            )
            connection.commit()
        except BaseException:
            connection.invalidate()
            raise
        if acquired != 1:
            raise MaintenanceBarrierTimeout(
                "the database maintenance write barrier remained busy"
            )

        connection.info[_LOCK_HELD_INFO_KEY] = _MAINTENANCE_LOCK_STATE
        try:
            _acquire_barrier_row(
                connection,
                timeout_seconds=timeout_seconds,
                lock_clause="FOR UPDATE",
            )
            yield connection
            connection.commit()
        except BaseException:
            if connection.in_transaction():
                connection.rollback()
            raise
        finally:
            if connection.in_transaction():
                connection.rollback()
            if not connection.invalidated:
                try:
                    released = connection.scalar(
                        sa.text(f"SELECT RELEASE_LOCK({_LOCK_NAME_SQL})")
                    )
                    connection.commit()
                except BaseException:
                    connection.invalidate()
                    raise
                finally:
                    connection.info.pop(_LOCK_HELD_INFO_KEY, None)
                if released != 1:
                    connection.invalidate()
                    raise MaintenanceBarrierError(
                        "the database maintenance write barrier could not be released"
                    )
