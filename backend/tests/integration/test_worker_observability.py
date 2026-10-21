from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.maintenance import worker_status
from app.worker.heartbeat import WorkerHeartbeatRepository
from app.worker.observability import QUEUE_NAMES, QueueName
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.mysql


@pytest.fixture()
def worker_runtime_engine(
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


@pytest.fixture(autouse=True)
def clean_worker_observations(
    alembic_config: Config,
    mysql_engine: Engine,
) -> Iterator[None]:
    command.upgrade(alembic_config, "head")
    with mysql_engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM worker_instances"))
    yield
    with mysql_engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM worker_instances"))


def _row(engine: Engine, instance_id: UUID) -> sa.RowMapping:
    with engine.connect() as connection:
        return (
            connection.execute(
                sa.text(
                    """
                    SELECT role, build_id, supported_queues, lifecycle_status,
                           heartbeat_sequence, started_at, last_heartbeat_at,
                           stopped_at, last_result_code
                    FROM worker_instances
                    WHERE instance_id = :instance_id
                    """
                ),
                {"instance_id": instance_id.bytes},
            )
            .mappings()
            .one()
        )


def test_repository_registers_with_database_time_and_monotonic_sequence(
    worker_runtime_engine: Engine,
) -> None:
    repository = WorkerHeartbeatRepository(worker_runtime_engine)
    instance_id = uuid4()
    with worker_runtime_engine.connect() as connection:
        before = connection.scalar(sa.text("SELECT UTC_TIMESTAMP(6)"))

    registered_at = repository.register(
        instance_id=instance_id,
        role="local_worker",
        build_id="integration-build",
        supported_queues=QUEUE_NAMES,
    )
    first_heartbeat_at = repository.heartbeat(
        instance_id=instance_id,
        sequence=1,
        result_code="heartbeat_succeeded",
    )
    with worker_runtime_engine.connect() as connection:
        after = connection.scalar(sa.text("SELECT UTC_TIMESTAMP(6)"))

    assert isinstance(before, datetime)
    assert isinstance(after, datetime)
    assert before.replace(tzinfo=UTC) <= registered_at <= after.replace(tzinfo=UTC)
    assert first_heartbeat_at >= registered_at
    row = _row(worker_runtime_engine, instance_id)
    assert row["heartbeat_sequence"] == 1
    supported = row["supported_queues"]
    if isinstance(supported, str):
        supported = json.loads(supported)
    assert tuple(supported) == QUEUE_NAMES


def test_repository_tracks_failure_recovery_and_normal_stop(
    worker_runtime_engine: Engine,
) -> None:
    repository = WorkerHeartbeatRepository(worker_runtime_engine)
    instance_id = uuid4()
    repository.register(
        instance_id=instance_id,
        role="local_worker",
        build_id="integration-build",
        supported_queues=QUEUE_NAMES,
    )

    repository.poll_started(instance_id=instance_id, queue_name="catalog_import")
    repository.poll_failed(
        instance_id=instance_id,
        queue_name="catalog_import",
        failure_code="consumer_unexpected_error",
    )
    repository.poll_started(instance_id=instance_id, queue_name="catalog_import")
    repository.poll_succeeded(
        instance_id=instance_id,
        queue_name="catalog_import",
        result_code="queue_idle",
    )
    stopped_at = repository.stop(
        instance_id=instance_id,
        result_code="worker_stopped",
    )

    with worker_runtime_engine.connect() as connection:
        consumer = (
            connection.execute(
                sa.text(
                    """
                    SELECT last_poll_started_at, last_poll_completed_at,
                           last_poll_succeeded_at, last_poll_failed_at,
                           consecutive_failures, last_result_code,
                           last_failure_code
                    FROM worker_consumer_states
                    WHERE worker_instance_id = :instance_id
                      AND queue_name = 'catalog_import'
                    """
                ),
                {"instance_id": instance_id.bytes},
            )
            .mappings()
            .one()
        )
    assert consumer["last_poll_started_at"] is not None
    assert consumer["last_poll_completed_at"] is not None
    assert consumer["last_poll_succeeded_at"] is not None
    assert consumer["last_poll_failed_at"] is not None
    assert consumer["consecutive_failures"] == 0
    assert consumer["last_result_code"] == "queue_idle"
    assert consumer["last_failure_code"] is None
    row = _row(worker_runtime_engine, instance_id)
    assert row["lifecycle_status"] == "stopped"
    assert row["last_result_code"] == "worker_stopped"
    assert row["stopped_at"].replace(tzinfo=UTC) == stopped_at


def test_one_failing_consumer_does_not_hide_running_worker_or_other_successes(
    worker_runtime_engine: Engine,
) -> None:
    repository = WorkerHeartbeatRepository(worker_runtime_engine)
    instance_id = uuid4()
    repository.register(
        instance_id=instance_id,
        role="local_worker",
        build_id="integration-build",
        supported_queues=QUEUE_NAMES,
    )
    repository.heartbeat(
        instance_id=instance_id,
        sequence=1,
        result_code="heartbeat_succeeded",
    )

    for queue_name in QUEUE_NAMES:
        repository.poll_started(instance_id=instance_id, queue_name=queue_name)
        if queue_name == "catalog_import":
            repository.poll_failed(
                instance_id=instance_id,
                queue_name=queue_name,
                failure_code="consumer_unexpected_error",
            )
            repository.poll_started(instance_id=instance_id, queue_name=queue_name)
            repository.poll_failed(
                instance_id=instance_id,
                queue_name=queue_name,
                failure_code="consumer_unexpected_error",
            )
        else:
            repository.poll_succeeded(
                instance_id=instance_id,
                queue_name=queue_name,
                result_code="queue_idle",
            )

    with worker_runtime_engine.connect() as connection:
        instance = (
            connection.execute(
                sa.text(
                    """
                    SELECT lifecycle_status, heartbeat_sequence, last_heartbeat_at
                    FROM worker_instances
                    WHERE instance_id = :instance_id
                    """
                ),
                {"instance_id": instance_id.bytes},
            )
            .mappings()
            .one()
        )
        consumers = list(
            connection.execute(
                sa.text(
                    """
                    SELECT queue_name, last_poll_succeeded_at,
                           consecutive_failures, last_failure_code
                    FROM worker_consumer_states
                    WHERE worker_instance_id = :instance_id
                    ORDER BY FIELD(
                        queue_name,
                        'return_dedup',
                        'publication_outbox',
                        'catalog_export',
                        'catalog_import'
                    )
                    """
                ),
                {"instance_id": instance_id.bytes},
            ).mappings()
        )

    assert instance["lifecycle_status"] == "running"
    assert instance["heartbeat_sequence"] == 1
    assert instance["last_heartbeat_at"] is not None
    assert [row["queue_name"] for row in consumers] == list(QUEUE_NAMES)
    for consumer in consumers[:-1]:
        assert consumer["last_poll_succeeded_at"] is not None
        assert consumer["consecutive_failures"] == 0
        assert consumer["last_failure_code"] is None
    failing = consumers[-1]
    assert failing["last_poll_succeeded_at"] is None
    assert failing["consecutive_failures"] == 2
    assert failing["last_failure_code"] == "consumer_unexpected_error"


def test_aggregator_reconciles_native_counts_and_online_consumers(
    worker_runtime_engine: Engine,
) -> None:
    repository = WorkerHeartbeatRepository(worker_runtime_engine)
    instance_id = uuid4()
    repository.register(
        instance_id=instance_id,
        role="local_worker",
        build_id="integration-build",
        supported_queues=QUEUE_NAMES,
    )
    for queue_name in QUEUE_NAMES:
        repository.poll_started(instance_id=instance_id, queue_name=queue_name)
        repository.poll_succeeded(
            instance_id=instance_id,
            queue_name=queue_name,
            result_code="queue_idle",
        )

    observed_at, fleet, queues = worker_status.read_worker_observability(
        worker_runtime_engine,
        maintenance_active=True,
    )

    assert observed_at.tzinfo == UTC
    assert fleet.query_health == "healthy"
    assert fleet.instances[0].instance_id == instance_id.hex
    assert fleet.instances[0].heartbeat_status == "online"
    assert [queue.queue_name for queue in queues] == list(QUEUE_NAMES)
    assert all(queue.query_health == "healthy" for queue in queues)
    assert all(queue.consumer_health == "healthy" for queue in queues)

    table_status_columns: dict[QueueName, tuple[str, str]] = {
        "return_dedup": ("return_dedup_staging_jobs", "status"),
        "publication_outbox": ("publication_outbox", "status"),
        "catalog_export": ("catalog_exports", "export_status"),
        "catalog_import": ("catalog_imports", "status"),
    }
    with worker_runtime_engine.connect() as connection:
        for queue in queues:
            table_name, status_column = table_status_columns[queue.queue_name]
            direct = {
                str(row["native_status"]): int(row["native_count"])
                for row in connection.execute(
                    sa.text(
                        f"SELECT {status_column} AS native_status, "
                        f"COUNT(*) AS native_count FROM {table_name} "
                        f"GROUP BY {status_column}"
                    )
                ).mappings()
            }
            assert queue.native_status_counts is not None
            assert queue.native_status_counts == {
                status: direct.get(status, 0) for status in queue.native_status_counts
            }


def test_one_native_query_failure_does_not_poison_other_queues(
    worker_runtime_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = worker_status._read_queue

    def fail_catalog_import(
        engine: Engine,
        *,
        queue_name: QueueName,
        observed_at: datetime,
        consumer: object,
    ) -> object:
        if queue_name == "catalog_import":
            raise RuntimeError("synthetic catalog import query failure")
        return original(
            engine,
            queue_name=queue_name,
            observed_at=observed_at,
            consumer=consumer,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(worker_status, "_read_queue", fail_catalog_import)

    _, fleet, queues = worker_status.read_worker_observability(
        worker_runtime_engine,
        maintenance_active=False,
    )

    assert fleet.query_health == "healthy"
    assert [queue.query_health for queue in queues] == [
        "healthy",
        "healthy",
        "healthy",
        "unknown",
    ]
    failed = queues[-1]
    assert failed.failure_code == "catalog_import_query_failed"
    assert failed.native_status_counts is None
    assert failed.actionable is None
    assert failed.in_flight is None
    assert failed.stuck is None


def test_repository_pruning_is_bounded_to_five_hundred_parent_rows(
    mysql_engine: Engine,
    worker_runtime_engine: Engine,
) -> None:
    supported_queues = json.dumps(QUEUE_NAMES)
    instance_ids = [uuid4().bytes for _ in range(501)]
    with mysql_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO worker_instances (
                    instance_id, role, build_id, supported_queues,
                    lifecycle_status, heartbeat_sequence, started_at,
                    last_heartbeat_at, stopped_at, last_result_code
                ) VALUES (
                    :instance_id, 'local_worker', 'retention-fixture',
                    :supported_queues, 'stopped', 1,
                    UTC_TIMESTAMP(6) - INTERVAL 31 DAY,
                    UTC_TIMESTAMP(6) - INTERVAL 31 DAY,
                    UTC_TIMESTAMP(6) - INTERVAL 31 DAY, 'worker_stopped'
                )
                """
            ),
            [
                {"instance_id": instance_id, "supported_queues": supported_queues}
                for instance_id in instance_ids
            ],
        )

    repository = WorkerHeartbeatRepository(worker_runtime_engine)
    assert repository.prune() == 500
    with mysql_engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM worker_instances")) == 1
    assert repository.prune() == 1
