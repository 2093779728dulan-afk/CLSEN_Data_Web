"""Long-running local publication outbox worker process."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from app.catalog.export_service import (
    CatalogExportMaterializer,
    MySqlCatalogExportFinalizer,
)
from app.catalog.import_repository import MySqlCatalogImportRepository
from app.catalog.return_dedup_repository import MySqlReturnDedupRepository
from app.config import Settings, StorageSettings
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.imports.storage import LocalContentStore
from app.logging import configure_logging
from app.maintenance.schema_compatibility import (
    SchemaCompatibilityFailure,
    assert_schema_compatible,
    schema_event,
)
from app.worker.catalog_exports import CatalogExportWorker, MySqlCatalogExportWorkSource
from app.worker.catalog_imports import CatalogImportWorker
from app.worker.heartbeat import WorkerHeartbeatController, WorkerHeartbeatRepository
from app.worker.outbox import OutboxSettings, PublicationOutboxWorker
from app.worker.return_dedup import ReturnDedupWorker
from app.worker.runner import WorkerRunner

_BUILD_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}", flags=re.ASCII)


def _build_id(repository_root: Path) -> str:
    for environment_name in ("APP_BUILD_ID", "APP_RELEASE_SOURCE_SHA"):
        candidate = os.getenv(environment_name)
        if candidate is not None and _BUILD_ID_PATTERN.fullmatch(candidate):
            return candidate
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except OSError, subprocess.SubprocessError:
        return "development"
    candidate = completed.stdout.strip()
    if _BUILD_ID_PATTERN.fullmatch(candidate) is None:
        return "development"
    return candidate


def main(arguments: list[str] | None = None) -> int:
    """Poll the outbox until interrupted, or drain currently available work."""

    parser = argparse.ArgumentParser(prog="clsen-worker")
    parser.add_argument("--database-environment", default="APP_DATABASE_URL")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--stale-seconds", type=int, default=300)
    parser.add_argument("--retry-seconds", type=int, default=5)
    parser.add_argument("--drain", action="store_true")
    options = parser.parse_args(arguments)
    if not 0.1 <= options.poll_seconds <= 60:
        raise SystemExit("poll interval must be between 0.1 and 60 seconds")

    repository_root = Path(__file__).resolve().parents[3]
    load_dotenv(repository_root / ".env", override=False)
    database_settings = DatabaseSettings.from_env(
        options.database_environment,
        pool_size=2,
        max_overflow=0,
    )
    engine = create_database_engine(database_settings)
    try:
        assert_schema_compatible(
            engine,
            database_identity=database_settings.safe_url,
        )
    except SchemaCompatibilityFailure as error:
        print(
            json.dumps(schema_event(error, component="worker")),
            file=sys.stderr,
        )
        engine.dispose()
        return 2
    configure_logging(Settings())
    heartbeat = WorkerHeartbeatController(
        WorkerHeartbeatRepository(engine),
        instance_id=uuid4(),
        build_id=_build_id(repository_root),
    )
    try:
        heartbeat.start()
    except Exception:
        engine.dispose()
        return 3
    try:
        storage = StorageSettings.from_env()
        content_store = LocalContentStore(storage.root, storage.max_upload_bytes)
        runner = WorkerRunner(
            return_dedup=ReturnDedupWorker(
                MySqlReturnDedupRepository(engine),
                lease_ttl=timedelta(seconds=options.stale_seconds),
            ),
            outbox=PublicationOutboxWorker(
                engine,
                OutboxSettings(
                    worker_id=OutboxSettings.local_default().worker_id,
                    max_attempts=options.max_attempts,
                    stale_after=timedelta(seconds=options.stale_seconds),
                    base_retry_delay=timedelta(seconds=options.retry_seconds),
                ),
            ),
            catalog_exports=CatalogExportWorker(
                source=MySqlCatalogExportWorkSource(engine),
                materializer=CatalogExportMaterializer(
                    store=content_store,
                    finalizer=MySqlCatalogExportFinalizer(engine),
                ),
            ),
            catalog_imports=CatalogImportWorker(
                MySqlCatalogImportRepository(engine),
                content_store,
                lease_ttl=storage.lease_ttl,
            ),
            telemetry=heartbeat,
        )
        while True:
            worker_pass = runner.run_once()
            if not worker_pass.did_work:
                if options.drain:
                    return 0
                time.sleep(options.poll_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        heartbeat.stop()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
