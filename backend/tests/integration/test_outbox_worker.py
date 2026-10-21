from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.worker.outbox import OutboxSettings, PublicationOutboxWorker
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.mysql


@pytest.fixture()
def runtime_engine(
    mysql_settings: DatabaseSettings,
    request: pytest.FixtureRequest,
) -> Iterator[Engine]:
    value = os.getenv("APP_TEST_RUNTIME_DATABASE_URL")
    if value is None or not value.strip():
        if request.config.getoption("--require-mysql"):
            raise pytest.UsageError("APP_TEST_RUNTIME_DATABASE_URL is required")
        pytest.skip("APP_TEST_RUNTIME_DATABASE_URL is not configured")
    settings = DatabaseSettings.from_url(value, pool_size=2, max_overflow=0)
    assert settings.url.database == mysql_settings.url.database
    assert settings.url.username != mysql_settings.url.username
    engine = create_database_engine(settings)
    try:
        yield engine
    finally:
        engine.dispose()


def _insert_outbox(
    engine: Engine,
    *,
    topic: str,
    status: str = "pending",
    attempt_count: int = 0,
    stale: bool = False,
) -> int:
    with engine.begin() as connection:
        config_id = int(
            connection.scalar(
                sa.text("SELECT id FROM site_config_versions ORDER BY id LIMIT 1")
            )
        )
        result = connection.execute(
            sa.text(
                """
                INSERT INTO publication_outbox (
                    publication_event_id, site_config_version_id, topic,
                    dedupe_key, redacted_payload, status, attempt_count,
                    available_at, locked_at, locked_by, processed_at,
                    last_error, created_at, updated_at
                ) VALUES (
                    NULL, :config_id, :topic, :dedupe_key, :payload,
                    :status, :attempt_count, UTC_TIMESTAMP(6),
                    CASE WHEN :stale = 1
                         THEN UTC_TIMESTAMP(6) - INTERVAL 10 MINUTE
                         ELSE NULL END,
                    CASE WHEN :stale = 1 THEN 'crashed-worker' ELSE NULL END,
                    NULL, NULL, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                )
                """
            ),
            {
                "config_id": config_id,
                "topic": topic,
                "dedupe_key": f"worker-test:{uuid4().hex}",
                "payload": json.dumps({"site_config_version_id": config_id}),
                "status": status,
                "attempt_count": attempt_count,
                "stale": 1 if stale else 0,
            },
        )
        return int(result.lastrowid)


def _row(engine: Engine, item_id: int) -> sa.RowMapping:
    with engine.connect() as connection:
        return (
            connection.execute(
                sa.text(
                    """
                SELECT status, attempt_count, locked_at, locked_by,
                       processed_at, last_error
                FROM publication_outbox
                WHERE id = :item_id
                """
                ),
                {"item_id": item_id},
            )
            .mappings()
            .one()
        )


def _drain_existing(worker: PublicationOutboxWorker) -> None:
    for _ in range(100):
        if worker.run_once() is None:
            return
    raise AssertionError("existing outbox did not drain within 100 items")


def test_outbox_worker_completes_once_and_does_not_redeliver(
    alembic_config: Config,
    mysql_engine: Engine,
    runtime_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    worker = PublicationOutboxWorker(
        runtime_engine,
        OutboxSettings(worker_id="integration-worker"),
    )
    _drain_existing(worker)
    item_id = _insert_outbox(mysql_engine, topic="site_config.changed")
    try:
        claimed = worker.run_once()
        assert claimed is not None and claimed.item_id == item_id
        completed = _row(mysql_engine, item_id)
        assert completed["status"] == "completed"
        assert completed["attempt_count"] == 1
        assert completed["locked_at"] is None
        assert completed["locked_by"] is None
        assert completed["processed_at"] is not None

        assert worker.run_once() is None
        assert _row(mysql_engine, item_id)["attempt_count"] == 1
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM publication_outbox WHERE id = :item_id"),
                {"item_id": item_id},
            )


def test_outbox_worker_reclaims_a_stale_processing_attempt(
    alembic_config: Config,
    mysql_engine: Engine,
    runtime_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    worker = PublicationOutboxWorker(
        runtime_engine,
        OutboxSettings(
            worker_id="recovery-worker",
            stale_after=timedelta(seconds=1),
        ),
    )
    _drain_existing(worker)
    item_id = _insert_outbox(
        mysql_engine,
        topic="site_config.changed",
        status="processing",
        attempt_count=1,
        stale=True,
    )
    try:
        claimed = worker.run_once()
        assert claimed is not None and claimed.item_id == item_id
        completed = _row(mysql_engine, item_id)
        assert completed["status"] == "completed"
        assert completed["attempt_count"] == 2
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM publication_outbox WHERE id = :item_id"),
                {"item_id": item_id},
            )


def test_outbox_worker_retries_then_quarantines_an_unknown_topic(
    alembic_config: Config,
    mysql_engine: Engine,
    runtime_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    worker = PublicationOutboxWorker(
        runtime_engine,
        OutboxSettings(
            worker_id="retry-worker",
            max_attempts=2,
            base_retry_delay=timedelta(seconds=1),
        ),
    )
    _drain_existing(worker)
    item_id = _insert_outbox(mysql_engine, topic="unsupported.topic")
    try:
        worker.run_once()
        retry = _row(mysql_engine, item_id)
        assert retry["status"] == "pending"
        assert retry["attempt_count"] == 1
        assert "unsupported outbox topic" in str(retry["last_error"])

        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE publication_outbox
                    SET available_at = UTC_TIMESTAMP(6)
                    WHERE id = :item_id
                    """
                ),
                {"item_id": item_id},
            )
        worker.run_once()
        failed = _row(mysql_engine, item_id)
        assert failed["status"] == "failed"
        assert failed["attempt_count"] == 2
        assert failed["locked_by"] is None
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM publication_outbox WHERE id = :item_id"),
                {"item_id": item_id},
            )
