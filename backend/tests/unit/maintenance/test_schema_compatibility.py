from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import pytest
import sqlalchemy as sa
from app.maintenance.schema_compatibility import (
    SchemaCompatibilityCode,
    SchemaCompatibilityFailure,
    assert_schema_compatible,
    classify_revision,
    schema_event,
)
from app.maintenance.schema_revision import CURRENT_SCHEMA_REVISION
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError


class _MySqlError(RuntimeError):
    pass


class _Result:
    def __init__(self, rows: Sequence[tuple[object, ...]]) -> None:
        self._rows = rows

    def all(self) -> Sequence[tuple[object, ...]]:
        return self._rows


class _Connection:
    def __init__(
        self,
        *,
        rows: Sequence[tuple[object, ...]] = (),
        execute_error: BaseException | None = None,
    ) -> None:
        self._rows = rows
        self._execute_error = execute_error
        self.statements: list[str] = []

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *arguments: object) -> None:
        del arguments

    def execute(self, statement: object) -> _Result:
        self.statements.append(str(statement))
        if self._execute_error is not None:
            raise self._execute_error
        return _Result(self._rows)


class _Engine:
    def __init__(
        self,
        *,
        rows: Sequence[tuple[object, ...]] = (),
        connect_error: BaseException | None = None,
        execute_error: BaseException | None = None,
    ) -> None:
        self.connection = _Connection(rows=rows, execute_error=execute_error)
        self._connect_error = connect_error
        self.connect_count = 0

    def connect(self) -> _Connection:
        self.connect_count += 1
        if self._connect_error is not None:
            raise self._connect_error
        return self.connection


def _engine(
    *,
    rows: Sequence[tuple[object, ...]] = (),
    connect_error: BaseException | None = None,
    execute_error: BaseException | None = None,
) -> tuple[Engine, _Engine]:
    fake = _Engine(
        rows=rows,
        connect_error=connect_error,
        execute_error=execute_error,
    )
    return cast(Engine, fake), fake


def _database_error(
    error_type: type[DBAPIError],
    code: int,
    message: str,
    *,
    connection_invalidated: bool = False,
) -> DBAPIError:
    return error_type(
        statement="sensitive statement",
        params={"password": "do-not-log-me"},
        orig=_MySqlError(code, message),
        hide_parameters=True,
        connection_invalidated=connection_invalidated,
    )


def _assert_failure(
    engine: Engine,
    expected_code: SchemaCompatibilityCode,
    *,
    actual_revision: str | None = None,
) -> SchemaCompatibilityFailure:
    with pytest.raises(SchemaCompatibilityFailure) as captured:
        assert_schema_compatible(
            engine,
            database_identity="mysql+pymysql://app:***@db/schema",
        )
    assert captured.value.code is expected_code
    assert captured.value.expected_revision == CURRENT_SCHEMA_REVISION
    assert captured.value.actual_revision == actual_revision
    return captured.value


def test_current_revision_executes_one_read_only_observation() -> None:
    engine, fake = _engine(rows=[(CURRENT_SCHEMA_REVISION,)])

    assert_schema_compatible(
        engine,
        database_identity="mysql+pymysql://app:***@db/schema",
    )

    assert fake.connect_count == 1
    assert fake.connection.statements == ["SELECT version_num FROM alembic_version"]
    statement = fake.connection.statements[0].upper()
    assert "LIMIT" not in statement
    for forbidden in ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"):
        assert forbidden not in statement


@pytest.mark.parametrize(
    ("rows", "expected_code", "actual_revision"),
    (
        ((), SchemaCompatibilityCode.VERSION_ROW_MISSING, None),
        (
            ((CURRENT_SCHEMA_REVISION,), (CURRENT_SCHEMA_REVISION,)),
            SchemaCompatibilityCode.VERSION_ROWS_MULTIPLE,
            None,
        ),
        ((("0021",),), SchemaCompatibilityCode.REVISION_OLDER, "0021"),
        ((("0031",),), SchemaCompatibilityCode.REVISION_NEWER, "0031"),
        ((("branch-head",),), SchemaCompatibilityCode.REVISION_UNKNOWN, "branch-head"),
        (((None,),), SchemaCompatibilityCode.REVISION_UNKNOWN, None),
    ),
)
def test_revision_failures_are_closed_and_exact(
    rows: Sequence[tuple[object, ...]],
    expected_code: SchemaCompatibilityCode,
    actual_revision: str | None,
) -> None:
    engine, _ = _engine(rows=rows)

    _assert_failure(engine, expected_code, actual_revision=actual_revision)


def test_missing_version_table_has_a_distinct_failure_code() -> None:
    database_error = _database_error(
        ProgrammingError,
        1146,
        "Table 'private.alembic_version' doesn't exist",
    )
    engine, _ = _engine(execute_error=database_error)

    failure = _assert_failure(
        engine,
        SchemaCompatibilityCode.VERSION_TABLE_MISSING,
    )

    assert failure.__cause__ is database_error


def test_unreadable_version_table_has_a_distinct_failure_code() -> None:
    database_error = _database_error(
        ProgrammingError,
        1142,
        "SELECT denied for secret-user@private-host",
    )
    engine, _ = _engine(execute_error=database_error)

    failure = _assert_failure(engine, SchemaCompatibilityCode.VERSION_UNREADABLE)

    assert failure.__cause__ is database_error


@pytest.mark.parametrize(
    "database_error",
    (
        _database_error(
            OperationalError,
            2003,
            "Can't connect to MySQL server at private-host",
        ),
        _database_error(
            OperationalError,
            2013,
            "Lost connection to MySQL server",
            connection_invalidated=True,
        ),
    ),
)
def test_database_unavailable_is_closed(database_error: DBAPIError) -> None:
    engine, _ = _engine(connect_error=database_error)

    failure = _assert_failure(
        engine,
        SchemaCompatibilityCode.DATABASE_UNAVAILABLE,
    )

    assert failure.__cause__ is database_error


def test_non_database_query_failure_is_reported_as_unreadable() -> None:
    raw_error = sa.exc.SQLAlchemyError("private implementation detail")
    engine, _ = _engine(execute_error=raw_error)

    failure = _assert_failure(engine, SchemaCompatibilityCode.VERSION_UNREADABLE)

    assert failure.__cause__ is raw_error


@pytest.mark.parametrize(
    ("actual", "expected", "classification"),
    (
        ("0009", "0010", SchemaCompatibilityCode.REVISION_OLDER),
        ("0010", "0009", SchemaCompatibilityCode.REVISION_NEWER),
        ("9", "0010", SchemaCompatibilityCode.REVISION_UNKNOWN),
        ("0010-extra", "0010", SchemaCompatibilityCode.REVISION_UNKNOWN),
        ("ABCD", "0010", SchemaCompatibilityCode.REVISION_UNKNOWN),
    ),
)
def test_revision_classifier_uses_the_four_digit_numeric_contract(
    actual: str,
    expected: str,
    classification: SchemaCompatibilityCode,
) -> None:
    assert classify_revision(actual, expected_revision=expected) is classification


def test_backup_reader_compatibility_does_not_relax_runtime_startup() -> None:
    engine, _ = _engine(rows=[("0021",)])

    _assert_failure(
        engine,
        SchemaCompatibilityCode.REVISION_OLDER,
        actual_revision="0021",
    )


def test_failure_string_and_event_do_not_expose_raw_database_details() -> None:
    database_error = _database_error(
        ProgrammingError,
        1142,
        "SELECT denied for secret-user@private-host",
    )
    engine, _ = _engine(execute_error=database_error)
    failure = _assert_failure(engine, SchemaCompatibilityCode.VERSION_UNREADABLE)

    rendered = str(failure)
    event = schema_event(failure, component="api")

    assert rendered == (
        "schema_version_unreadable: expected schema revision "
        f"{CURRENT_SCHEMA_REVISION} at mysql+pymysql://app:***@db/schema"
    )
    assert event == {
        "event": "schema_compatibility",
        "status": "refused",
        "component": "api",
        "code": "schema_version_unreadable",
        "expected_revision": CURRENT_SCHEMA_REVISION,
        "actual_revision": None,
        "database_identity": "mysql+pymysql://app:***@db/schema",
    }
    rendered_event = repr(event)
    for secret in (
        "do-not-log-me",
        "secret-user",
        "private-host",
        "sensitive statement",
    ):
        assert secret not in rendered
        assert secret not in rendered_event


def test_success_event_is_stable_and_contains_no_database_identity() -> None:
    assert schema_event(None, component="worker") == {
        "event": "schema_compatibility",
        "status": "compatible",
        "component": "worker",
        "code": None,
        "expected_revision": CURRENT_SCHEMA_REVISION,
        "actual_revision": CURRENT_SCHEMA_REVISION,
        "database_identity": None,
    }
