"""Read-only runtime compatibility check for the database schema head."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.maintenance.schema_revision import CURRENT_SCHEMA_REVISION

_REVISION_QUERY = "SELECT version_num FROM alembic_version"
_VERSION_TABLE_MISSING_MYSQL_CODES = frozenset({1146})
_DATABASE_UNAVAILABLE_MYSQL_CODES = frozenset(
    {
        1040,  # Too many connections.
        1042,  # Unable to resolve host.
        1043,  # Bad handshake.
        1129,  # Host blocked.
        1130,  # Host not allowed to connect.
        2002,  # Local connection failed.
        2003,  # Remote connection failed.
        2006,  # Server went away.
        2013,  # Connection lost during query.
        2055,  # Lost connection during handshake.
    }
)


class SchemaCompatibilityCode(StrEnum):
    """Closed schema-startup failure codes safe for logs and automation."""

    DATABASE_UNAVAILABLE = "schema_database_unavailable"
    VERSION_TABLE_MISSING = "schema_version_table_missing"
    VERSION_UNREADABLE = "schema_version_unreadable"
    VERSION_ROW_MISSING = "schema_version_row_missing"
    VERSION_ROWS_MULTIPLE = "schema_version_rows_multiple"
    REVISION_OLDER = "schema_revision_older"
    REVISION_NEWER = "schema_revision_newer"
    REVISION_UNKNOWN = "schema_revision_unknown"


@dataclass(frozen=True, slots=True)
class SchemaCompatibilityFailure(RuntimeError):
    """A safe, structured refusal to start against an incompatible schema."""

    code: SchemaCompatibilityCode
    expected_revision: str
    actual_revision: str | None
    database_identity: str

    def __str__(self) -> str:
        actual = (
            f", found {self.actual_revision}"
            if self.actual_revision is not None
            else ""
        )
        return (
            f"{self.code.value}: expected schema revision "
            f"{self.expected_revision}{actual} at {self.database_identity}"
        )


_FROZEN_EXCEPTION_SETATTR = SchemaCompatibilityFailure.__setattr__


def _set_schema_failure_attribute(
    error: SchemaCompatibilityFailure,
    name: str,
    value: object,
) -> None:
    """Let Python manage traceback state without making failure fields mutable."""

    if name in {
        "__cause__",
        "__context__",
        "__suppress_context__",
        "__traceback__",
    }:
        BaseException.__setattr__(error, name, value)
        return
    _FROZEN_EXCEPTION_SETATTR(error, name, value)


SchemaCompatibilityFailure.__setattr__ = _set_schema_failure_attribute  # type: ignore[assignment]


def classify_revision(
    actual_revision: str,
    *,
    expected_revision: str,
) -> SchemaCompatibilityCode:
    """Classify a non-matching revision under the four-digit revision contract."""

    if actual_revision == expected_revision:
        raise ValueError("matching revisions have no failure classification")
    if not (
        len(actual_revision) == 4
        and actual_revision.isascii()
        and actual_revision.isdigit()
        and len(expected_revision) == 4
        and expected_revision.isascii()
        and expected_revision.isdigit()
    ):
        return SchemaCompatibilityCode.REVISION_UNKNOWN
    if int(actual_revision) < int(expected_revision):
        return SchemaCompatibilityCode.REVISION_OLDER
    return SchemaCompatibilityCode.REVISION_NEWER


def _mysql_error_code(error: DBAPIError) -> int | None:
    arguments = getattr(error.orig, "args", ())
    if arguments and isinstance(arguments[0], int):
        return arguments[0]
    return None


def _query_failure_code(
    error: SQLAlchemyError,
    *,
    connection_established: bool,
) -> SchemaCompatibilityCode:
    if not connection_established:
        return SchemaCompatibilityCode.DATABASE_UNAVAILABLE
    if isinstance(error, DBAPIError):
        mysql_code = _mysql_error_code(error)
        if mysql_code in _VERSION_TABLE_MISSING_MYSQL_CODES:
            return SchemaCompatibilityCode.VERSION_TABLE_MISSING
        if error.connection_invalidated or (
            mysql_code in _DATABASE_UNAVAILABLE_MYSQL_CODES
        ):
            return SchemaCompatibilityCode.DATABASE_UNAVAILABLE
    return SchemaCompatibilityCode.VERSION_UNREADABLE


def _failure(
    code: SchemaCompatibilityCode,
    *,
    database_identity: str,
    actual_revision: str | None = None,
) -> SchemaCompatibilityFailure:
    return SchemaCompatibilityFailure(
        code=code,
        expected_revision=CURRENT_SCHEMA_REVISION,
        actual_revision=actual_revision,
        database_identity=database_identity,
    )


def assert_schema_compatible(
    engine: Engine,
    *,
    database_identity: str,
) -> None:
    """Require exactly one current Alembic head using one read-only query."""

    connection_established = False
    try:
        with engine.connect() as connection:
            connection_established = True
            rows = connection.execute(sa.text(_REVISION_QUERY)).all()
    except SQLAlchemyError as error:
        raise _failure(
            _query_failure_code(
                error,
                connection_established=connection_established,
            ),
            database_identity=database_identity,
        ) from error

    if not rows:
        raise _failure(
            SchemaCompatibilityCode.VERSION_ROW_MISSING,
            database_identity=database_identity,
        )
    if len(rows) != 1:
        raise _failure(
            SchemaCompatibilityCode.VERSION_ROWS_MULTIPLE,
            database_identity=database_identity,
        )

    try:
        raw_revision = rows[0][0]
    except (IndexError, TypeError) as error:
        raise _failure(
            SchemaCompatibilityCode.VERSION_UNREADABLE,
            database_identity=database_identity,
        ) from error
    actual_revision = raw_revision if isinstance(raw_revision, str) else None
    if actual_revision == CURRENT_SCHEMA_REVISION:
        return
    code = (
        classify_revision(
            actual_revision,
            expected_revision=CURRENT_SCHEMA_REVISION,
        )
        if actual_revision is not None
        else SchemaCompatibilityCode.REVISION_UNKNOWN
    )
    raise _failure(
        code,
        database_identity=database_identity,
        actual_revision=actual_revision,
    )


def schema_event(
    error: SchemaCompatibilityFailure | None,
    *,
    component: str,
) -> dict[str, str | None]:
    """Return the stable, secret-safe event emitted by guarded processes."""

    return {
        "event": "schema_compatibility",
        "status": "compatible" if error is None else "refused",
        "component": component,
        "code": None if error is None else error.code.value,
        "expected_revision": (
            CURRENT_SCHEMA_REVISION if error is None else error.expected_revision
        ),
        "actual_revision": (
            CURRENT_SCHEMA_REVISION if error is None else error.actual_revision
        ),
        "database_identity": None if error is None else error.database_identity,
    }


__all__ = (
    "SchemaCompatibilityCode",
    "SchemaCompatibilityFailure",
    "assert_schema_compatible",
    "classify_revision",
    "schema_event",
)
