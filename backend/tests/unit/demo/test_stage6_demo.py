from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from app.demo.stage6 import (
    DemoDatabaseTargets,
    Stage6DemoPreconditionError,
    Stage6DemoRunner,
    build_fixture_bytes,
    load_demo_environment,
    stable_operation_token,
)
from app.parsers.parser import parse_report
from app.parsers.types import ParseSettings
from sqlalchemy.engine import Engine

MIGRATION_URL = (
    "mysql+pymysql://stage6_migrator:secret@127.0.0.1/"
    "clsen_data_test_demo?charset=utf8mb4"
)
RUNTIME_URL = (
    "mysql+pymysql://stage6_runtime:secret@localhost/"
    "clsen_data_test_demo?charset=utf8mb4"
)
PRIMARY_DATE = date(2099, 6, 1)
ISOLATION_DATE = date(2099, 6, 2)


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "APP_TEST_DATABASE_URL": MIGRATION_URL,
        "APP_TEST_RUNTIME_DATABASE_URL": RUNTIME_URL,
    }
    values.update(overrides)
    return values


def test_database_targets_accept_only_same_local_named_test_database() -> None:
    targets = DemoDatabaseTargets.from_mapping(_environment())

    assert targets.database_name == "clsen_data_test_demo"
    assert targets.migration.url.username == "stage6_migrator"
    assert targets.runtime.url.username == "stage6_runtime"


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        (
            "APP_TEST_DATABASE_URL",
            "mysql+pymysql://user:secret@127.0.0.1/clsen_data?charset=utf8mb4",
            "must match clsen_data_test",
        ),
        (
            "APP_TEST_RUNTIME_DATABASE_URL",
            "mysql+pymysql://user:secret@db.example/clsen_data_test?charset=utf8mb4",
            "non-local",
        ),
        (
            "APP_TEST_RUNTIME_DATABASE_URL",
            "mysql+pymysql://user:secret@127.0.0.1/"
            "clsen_data_test_other?charset=utf8mb4",
            "same local test database",
        ),
        (
            "APP_TEST_RUNTIME_DATABASE_URL",
            "mysql+pymysql://stage6_migrator:other@127.0.0.1/"
            "clsen_data_test_demo?charset=utf8mb4",
            "different database accounts",
        ),
    ],
)
def test_database_targets_fail_closed_before_engine_creation(
    name: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises(Stage6DemoPreconditionError, match=message):
        DemoDatabaseTargets.from_mapping(_environment(**{name: value}))


def test_production_database_url_is_never_a_fallback() -> None:
    with pytest.raises(Stage6DemoPreconditionError, match="never falls back"):
        DemoDatabaseTargets.from_mapping(
            {
                "APP_DATABASE_URL": (
                    "mysql+pymysql://prod:secret@127.0.0.1/clsen_data?charset=utf8mb4"
                )
            }
        )


def test_runner_rejects_a_filesystem_root_before_database_use() -> None:
    targets = DemoDatabaseTargets.from_mapping(_environment())

    with pytest.raises(Stage6DemoPreconditionError, match="filesystem root"):
        Stage6DemoRunner(
            targets=targets,
            storage_root=Path(Path.cwd().anchor),
        )


class _ConnectionContext:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def __enter__(self) -> object:
        return self.connection

    def __exit__(self, *_arguments: object) -> None:
        return None


class _OldSchemaConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def scalars(self, statement: object) -> tuple[str, ...]:
        self.statements.append(str(statement))
        return ("0008",)


class _RecordingEngine:
    def __init__(self, connection: object) -> None:
        self.connection = connection
        self.connect_count = 0

    def connect(self) -> _ConnectionContext:
        self.connect_count += 1
        return _ConnectionContext(self.connection)


def test_preflight_at_0008_stops_before_runtime_connection_or_write(
    tmp_path: Path,
) -> None:
    targets = DemoDatabaseTargets.from_mapping(_environment())
    runner = Stage6DemoRunner(
        targets=targets,
        storage_root=tmp_path / "storage",
        emit=lambda _message: None,
    )
    old_connection = _OldSchemaConnection()
    migration_engine = _RecordingEngine(old_connection)
    runtime_engine = _RecordingEngine(cast(Any, object()))

    with pytest.raises(Stage6DemoPreconditionError, match="requires migration 0009"):
        runner._preflight(
            cast(Engine, migration_engine),
            cast(Engine, runtime_engine),
        )

    assert migration_engine.connect_count == 1
    assert runtime_engine.connect_count == 0
    assert old_connection.statements == ["SELECT version_num FROM alembic_version"]


def test_environment_file_loads_only_test_values_and_process_env_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_file = tmp_path / ".env"
    environment_file.write_text(
        "\n".join(
            (
                "APP_DATABASE_URL=mysql+pymysql://prod:secret@db/clsen_data",
                f"APP_TEST_DATABASE_URL={MIGRATION_URL}",
                "APP_TEST_RUNTIME_DATABASE_URL=from-file",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("APP_TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_TEST_RUNTIME_DATABASE_URL", RUNTIME_URL)

    loaded = load_demo_environment(environment_file)

    assert loaded == {
        "APP_TEST_DATABASE_URL": MIGRATION_URL,
        "APP_TEST_RUNTIME_DATABASE_URL": RUNTIME_URL,
    }
    assert "APP_DATABASE_URL" not in loaded


def test_stable_tokens_bind_database_date_pair_and_operation() -> None:
    token = stable_operation_token(
        database_name="clsen_data_test_demo",
        primary_date=PRIMARY_DATE,
        isolation_date=ISOLATION_DATE,
        operation_name="publish-initial",
    )

    assert token == stable_operation_token(
        database_name="clsen_data_test_demo",
        primary_date=PRIMARY_DATE,
        isolation_date=ISOLATION_DATE,
        operation_name="publish-initial",
    )
    assert token != stable_operation_token(
        database_name="clsen_data_test_demo",
        primary_date=PRIMARY_DATE,
        isolation_date=ISOLATION_DATE,
        operation_name="rollback-to-initial",
    )
    assert token != stable_operation_token(
        database_name="clsen_data_test_demo",
        primary_date=PRIMARY_DATE,
        isolation_date=date(2099, 6, 3),
        operation_name="publish-initial",
    )


def test_synthetic_date_fixtures_are_distinct_and_parseable() -> None:
    primary = build_fixture_bytes(
        primary_date=PRIMARY_DATE,
        isolation_date=ISOLATION_DATE,
        role="primary",
    )
    isolation = build_fixture_bytes(
        primary_date=PRIMARY_DATE,
        isolation_date=ISOLATION_DATE,
        role="isolation",
    )

    assert primary != isolation
    assert b"__SKU" not in primary
    parsed_primary = parse_report(
        primary,
        ParseSettings(report_type="business_report", encoding="utf-8-sig"),
    )
    parsed_isolation = parse_report(
        isolation,
        ParseSettings(report_type="business_report", encoding="utf-8-sig"),
    )
    assert len(parsed_primary.rows) == 2
    assert len(parsed_isolation.rows) == 2
    assert parsed_primary.rows[0].sku != parsed_isolation.rows[0].sku
