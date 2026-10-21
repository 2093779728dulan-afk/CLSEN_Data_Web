"""Process-level schema compatibility preflight for supported launchers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.exc import SQLAlchemyError

from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.maintenance.schema_compatibility import (
    SchemaCompatibilityCode,
    SchemaCompatibilityFailure,
    assert_schema_compatible,
    schema_event,
)
from app.maintenance.schema_revision import CURRENT_SCHEMA_REVISION


def _database_settings(
    *,
    database_environment: str,
    environment_file: Path | None,
) -> DatabaseSettings:
    value = os.getenv(database_environment)
    if (value is None or not value.strip()) and environment_file is not None:
        if not environment_file.is_file():
            raise ValueError("environment file was not found")
        candidate = dotenv_values(environment_file).get(database_environment)
        value = candidate if isinstance(candidate, str) else None
    if value is None or not value.strip():
        raise ValueError("database URL must be configured")
    return DatabaseSettings.from_url(value)


def run_preflight(
    *,
    database_environment: str = "APP_DATABASE_URL",
    environment_file: Path | None = None,
    component: str,
) -> None:
    """Validate one configured database and dispose the bounded probe engine."""

    if component not in {"api", "worker"}:
        raise ValueError("component must be api or worker")
    settings = _database_settings(
        database_environment=database_environment,
        environment_file=environment_file,
    )
    try:
        engine = create_database_engine(settings)
    except SQLAlchemyError as error:
        raise SchemaCompatibilityFailure(
            code=SchemaCompatibilityCode.DATABASE_UNAVAILABLE,
            expected_revision=CURRENT_SCHEMA_REVISION,
            actual_revision=None,
            database_identity=settings.safe_url,
        ) from error
    try:
        assert_schema_compatible(engine, database_identity=settings.safe_url)
    finally:
        engine.dispose()


def _configuration_event(*, component: str) -> dict[str, str | None]:
    return {
        "event": "schema_compatibility",
        "status": "refused",
        "component": component,
        "code": "schema_configuration_invalid",
        "expected_revision": CURRENT_SCHEMA_REVISION,
        "actual_revision": None,
        "database_identity": None,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-environment",
        default="APP_DATABASE_URL",
    )
    parser.add_argument("--environment-file", type=Path)
    parser.add_argument("--component", choices=("api", "worker"), required=True)
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the preflight and emit exactly one machine-readable event."""

    options = _parser().parse_args(arguments)
    try:
        run_preflight(
            database_environment=options.database_environment,
            environment_file=options.environment_file,
            component=options.component,
        )
    except SchemaCompatibilityFailure as error:
        print(
            json.dumps(schema_event(error, component=options.component)),
            file=sys.stderr,
        )
        return 2
    except OSError, ValueError:
        print(
            json.dumps(_configuration_event(component=options.component)),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(schema_event(None, component=options.component)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
