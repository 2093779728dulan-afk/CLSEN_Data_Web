from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from sqlalchemy.engine import Engine

from tests.integration.historical_schema_support import (
    create_historical_schema_engine,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if "mysql" in report.keywords:
        print(
            f"MYSQL_TEST nodeid={report.nodeid} phase={report.when} "
            f"status={report.outcome} elapsed_seconds={report.duration:.3f}",
            flush=True,
        )


@pytest.fixture(scope="session")
def mysql_settings() -> DatabaseSettings:
    return DatabaseSettings.from_env("APP_TEST_DATABASE_URL", pool_size=2)


@pytest.fixture(scope="session")
def alembic_config(mysql_settings: DatabaseSettings) -> Iterator[Config]:
    previous = os.getenv("APP_MIGRATION_DATABASE_URL")
    os.environ["APP_MIGRATION_DATABASE_URL"] = mysql_settings.url.render_as_string(
        hide_password=False
    )
    configuration = Config(str(BACKEND_ROOT / "alembic.ini"))
    try:
        yield configuration
    finally:
        if previous is None:
            os.environ.pop("APP_MIGRATION_DATABASE_URL", None)
        else:
            os.environ["APP_MIGRATION_DATABASE_URL"] = previous


@pytest.fixture()
def mysql_engine(mysql_settings: DatabaseSettings) -> Iterator[Engine]:
    engine = create_database_engine(mysql_settings)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def historical_mysql_engine(
    mysql_settings: DatabaseSettings,
) -> Iterator[Engine]:
    engine = create_historical_schema_engine(mysql_settings)
    try:
        yield engine
    finally:
        engine.dispose()
