from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.maintenance.health import MaintenanceLockMonitor, probe_maintenance_lock
from app.maintenance.schema_compatibility import (
    SchemaCompatibilityCode,
    SchemaCompatibilityFailure,
    assert_schema_compatible,
)
from app.maintenance.schema_revision import CURRENT_SCHEMA_REVISION
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.mysql

_VERSION_TABLE = "alembic_version"
_SAVED_VERSION_TABLE = "alembic_version_stage1_saved"


@dataclass(frozen=True, slots=True)
class _SchemaCase:
    migration_engine: Engine
    runtime_engine: Engine
    runtime_identity: str


def _runtime_settings(mysql_settings: DatabaseSettings) -> DatabaseSettings:
    value = os.environ["APP_TEST_RUNTIME_DATABASE_URL"]
    settings = DatabaseSettings.from_url(value, pool_size=1, max_overflow=0)
    assert settings.url.database == mysql_settings.url.database
    assert settings.url.username != mysql_settings.url.username
    return settings


@pytest.fixture()
def schema_case(mysql_settings: DatabaseSettings) -> Iterator[_SchemaCase]:
    assert mysql_settings.url.database is not None
    assert mysql_settings.url.database.startswith("clsen_data_test_")
    migration_engine = create_database_engine(mysql_settings)
    runtime_settings = _runtime_settings(mysql_settings)
    runtime_engine = create_database_engine(runtime_settings)
    with migration_engine.connect() as connection:
        saved_exists = int(
            connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name = :table"
                ),
                {"table": _SAVED_VERSION_TABLE},
            )
            or 0
        )
        original_rows = tuple(
            str(value)
            for value in connection.scalars(
                sa.text("SELECT version_num FROM alembic_version")
            )
        )
    assert saved_exists == 0
    assert original_rows == (CURRENT_SCHEMA_REVISION,)
    try:
        yield _SchemaCase(
            migration_engine=migration_engine,
            runtime_engine=runtime_engine,
            runtime_identity=runtime_settings.safe_url,
        )
    finally:
        with migration_engine.begin() as connection:
            tables = frozenset(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = DATABASE() "
                        "AND table_name IN (:current, :saved)"
                    ),
                    {"current": _VERSION_TABLE, "saved": _SAVED_VERSION_TABLE},
                )
            )
            if _SAVED_VERSION_TABLE in tables:
                if _VERSION_TABLE in tables:
                    connection.exec_driver_sql("DROP TABLE alembic_version")
                connection.exec_driver_sql(
                    "RENAME TABLE alembic_version_stage1_saved TO alembic_version"
                )
            connection.execute(sa.text("DELETE FROM alembic_version"))
            for revision in original_rows:
                connection.execute(
                    sa.text(
                        "INSERT INTO alembic_version (version_num) VALUES (:revision)"
                    ),
                    {"revision": revision},
                )
        runtime_engine.dispose()
        migration_engine.dispose()


def test_runtime_identity_can_probe_maintenance_lock(
    schema_case: _SchemaCase,
) -> None:
    status = probe_maintenance_lock(
        schema_case.runtime_engine,
        MaintenanceLockMonitor(),
    )

    assert status.held is False
    assert status.owner_connection_id is None
    assert status.warning is False


def _assert_failure(
    case: _SchemaCase,
    code: SchemaCompatibilityCode,
    *,
    actual_revision: str | None = None,
) -> None:
    with pytest.raises(SchemaCompatibilityFailure) as captured:
        assert_schema_compatible(
            case.runtime_engine,
            database_identity=case.runtime_identity,
        )
    assert captured.value.code is code
    assert captured.value.actual_revision == actual_revision


def test_current_mysql_schema_is_compatible(schema_case: _SchemaCase) -> None:
    assert_schema_compatible(
        schema_case.runtime_engine,
        database_identity=schema_case.runtime_identity,
    )


def test_missing_mysql_version_table_refuses(schema_case: _SchemaCase) -> None:
    with schema_case.migration_engine.begin() as connection:
        connection.exec_driver_sql(
            "RENAME TABLE alembic_version TO alembic_version_stage1_saved"
        )

    _assert_failure(schema_case, SchemaCompatibilityCode.VERSION_TABLE_MISSING)


@pytest.mark.parametrize(
    ("revisions", "code", "actual"),
    (
        ((), SchemaCompatibilityCode.VERSION_ROW_MISSING, None),
        (
            (CURRENT_SCHEMA_REVISION, "0021"),
            SchemaCompatibilityCode.VERSION_ROWS_MULTIPLE,
            None,
        ),
        (("0021",), SchemaCompatibilityCode.REVISION_OLDER, "0021"),
        (("0031",), SchemaCompatibilityCode.REVISION_NEWER, "0031"),
        (("branch-head",), SchemaCompatibilityCode.REVISION_UNKNOWN, "branch-head"),
    ),
    ids=("zero", "multiple", "older", "newer", "unknown"),
)
def test_mysql_revision_shape_refuses(
    schema_case: _SchemaCase,
    revisions: tuple[str, ...],
    code: SchemaCompatibilityCode,
    actual: str | None,
) -> None:
    with schema_case.migration_engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM alembic_version"))
        for revision in revisions:
            connection.execute(
                sa.text("INSERT INTO alembic_version (version_num) VALUES (:value)"),
                {"value": revision},
            )

    _assert_failure(schema_case, code, actual_revision=actual)


def test_insufficient_mysql_version_permission_refuses(
    mysql_settings: DatabaseSettings,
) -> None:
    settings = DatabaseSettings.from_env(
        "APP_TEST_SCHEMA_UNREADABLE_DATABASE_URL",
        pool_size=1,
        max_overflow=0,
    )
    assert settings.url.database == mysql_settings.url.database
    assert settings.url.username != mysql_settings.url.username
    engine = create_database_engine(settings)
    try:
        with pytest.raises(SchemaCompatibilityFailure) as captured:
            assert_schema_compatible(engine, database_identity=settings.safe_url)
        assert captured.value.code is SchemaCompatibilityCode.VERSION_UNREADABLE
    finally:
        engine.dispose()


def test_unavailable_mysql_endpoint_refuses(mysql_settings: DatabaseSettings) -> None:
    unavailable_url = mysql_settings.url.set(port=1)
    unavailable = create_database_engine(
        DatabaseSettings(
            url=unavailable_url,
            pool_size=1,
            max_overflow=0,
        )
    )
    try:
        with pytest.raises(SchemaCompatibilityFailure) as captured:
            assert_schema_compatible(
                unavailable,
                database_identity=unavailable_url.render_as_string(hide_password=True),
            )
        assert captured.value.code is SchemaCompatibilityCode.DATABASE_UNAVAILABLE
    finally:
        unavailable.dispose()
