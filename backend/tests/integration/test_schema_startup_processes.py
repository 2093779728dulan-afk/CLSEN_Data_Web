from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import pytest
import sqlalchemy as sa
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.maintenance.schema_revision import CURRENT_SCHEMA_REVISION
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.mysql

BACKEND_ROOT = Path(__file__).resolve().parents[2]
_QUEUE_TABLES = (
    "return_dedup_staging_jobs",
    "publication_outbox",
    "catalog_exports",
    "catalog_imports",
)


def _runtime_settings(mysql_settings: DatabaseSettings) -> DatabaseSettings:
    settings = DatabaseSettings.from_env(
        "APP_TEST_RUNTIME_DATABASE_URL",
        pool_size=1,
        max_overflow=0,
    )
    assert settings.url.database == mysql_settings.url.database
    assert settings.url.username != mysql_settings.url.username
    return settings


@pytest.fixture()
def process_engines(
    mysql_settings: DatabaseSettings,
) -> Iterator[tuple[Engine, DatabaseSettings]]:
    assert mysql_settings.url.database is not None
    assert mysql_settings.url.database.startswith("clsen_data_test_")
    migration_engine = create_database_engine(mysql_settings)
    runtime_settings = _runtime_settings(mysql_settings)
    with migration_engine.connect() as connection:
        original_rows = tuple(
            str(value)
            for value in connection.scalars(
                sa.text("SELECT version_num FROM alembic_version")
            )
        )
    assert original_rows == (CURRENT_SCHEMA_REVISION,)
    try:
        yield migration_engine, runtime_settings
    finally:
        with migration_engine.begin() as connection:
            connection.execute(sa.text("DELETE FROM alembic_version"))
            for revision in original_rows:
                connection.execute(
                    sa.text(
                        "INSERT INTO alembic_version (version_num) VALUES (:revision)"
                    ),
                    {"revision": revision},
                )
        migration_engine.dispose()


def _process_environment(
    runtime_settings: DatabaseSettings,
    storage_root: Path,
) -> dict[str, str]:
    environment = dict(os.environ)
    runtime_url = runtime_settings.url.render_as_string(hide_password=False)
    environment.update(
        {
            "APP_DATABASE_URL": runtime_url,
            "APP_TEST_RUNTIME_DATABASE_URL": runtime_url,
            "APP_ENVIRONMENT": "test",
            "APP_LOG_LEVEL": "CRITICAL",
            "APP_SESSION_SECRET": "schema-process-test-secret-00000000",
            "APP_SESSION_COOKIE_SECURE": "false",
            "APP_CORS_ALLOWED_ORIGINS": "http://127.0.0.1:5173",
            "APP_STORAGE_ROOT": os.fspath(storage_root),
            "APP_STORAGE_MAX_UPLOAD_BYTES": "1048576",
            "APP_STORAGE_LEASE_TTL_SECONDS": "300",
            "APP_STORAGE_LEASE_RENEW_INTERVAL_SECONDS": "60",
            "APP_STORAGE_ORPHAN_AGE_SECONDS": "86400",
        }
    )
    return environment


def _snapshot(engine: Engine) -> dict[str, str]:
    result: dict[str, str] = {}
    with engine.connect() as connection:
        for table in _QUEUE_TABLES:
            rows = connection.exec_driver_sql(f"SELECT * FROM `{table}` ORDER BY id")
            digest = hashlib.sha256()
            for row in rows:
                digest.update(repr(tuple(row)).encode("utf-8"))
                digest.update(b"\n")
            result[table] = digest.hexdigest()
        revisions = tuple(
            str(value)
            for value in connection.scalars(
                sa.text("SELECT version_num FROM alembic_version")
            )
        )
    result["alembic_version"] = repr(revisions)
    return result


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _port_is_bound(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _run(
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str],
    timeout: float = 20,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


@pytest.mark.parametrize(
    "role",
    ("preflight", "uvicorn", "worker"),
)
def test_mismatched_process_refuses_without_queue_or_revision_changes(
    role: str,
    process_engines: tuple[Engine, DatabaseSettings],
    tmp_path: Path,
) -> None:
    migration_engine, runtime_settings = process_engines
    with migration_engine.begin() as connection:
        connection.execute(sa.text("UPDATE alembic_version SET version_num = '0021'"))
    before = _snapshot(migration_engine)
    environment = _process_environment(runtime_settings, tmp_path)
    port = _free_port()
    arguments = {
        "preflight": ["-m", "app.schema_preflight", "--component", "api"],
        "uvicorn": [
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--lifespan",
            "on",
        ],
        "worker": ["-m", "app.worker.cli", "--drain"],
    }[role]

    completed = _run(arguments, environment=environment)

    output = completed.stdout + completed.stderr
    runtime_password = runtime_settings.url.password
    assert isinstance(runtime_password, str)
    assert completed.returncode != 0
    assert "schema_revision_older" in output
    assert runtime_password not in output
    assert not _port_is_bound(port)
    assert _snapshot(migration_engine) == before
    assert "CLSEN worker ready." not in output


def test_matching_preflight_and_worker_drain_succeed(
    process_engines: tuple[Engine, DatabaseSettings],
    tmp_path: Path,
) -> None:
    migration_engine, runtime_settings = process_engines
    environment = _process_environment(runtime_settings, tmp_path)
    before = _snapshot(migration_engine)

    preflight = _run(
        ["-m", "app.schema_preflight", "--component", "api"],
        environment=environment,
    )
    worker = _run(
        ["-m", "app.worker.cli", "--drain"],
        environment=environment,
    )

    assert preflight.returncode == 0
    assert json.loads(preflight.stdout)["status"] == "compatible"
    assert worker.returncode == 0
    assert _snapshot(migration_engine) == before


def test_matching_uvicorn_becomes_ready(
    process_engines: tuple[Engine, DatabaseSettings],
    tmp_path: Path,
) -> None:
    _, runtime_settings = process_engines
    environment = _process_environment(runtime_settings, tmp_path)
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--lifespan",
            "on",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        deadline = time.monotonic() + 20
        response_body: bytes | None = None
        while time.monotonic() < deadline and process.poll() is None:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/health/ready",
                    timeout=0.5,
                ) as response:
                    response_body = response.read()
                    break
            except OSError:
                time.sleep(0.1)
        assert response_body == b'{"status":"ok"}'
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
