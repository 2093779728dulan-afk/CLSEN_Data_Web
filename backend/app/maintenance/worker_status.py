"""Database-authoritative Worker and native queue status aggregation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.engine import Engine, RowMapping

from app.worker.observability import (
    HEARTBEAT_SECONDS,
    OFFLINE_SECONDS,
    QUEUE_NAMES,
    REFRESH_SECONDS,
    STALE_SECONDS,
    QueueName,
)

HeartbeatStatus = Literal["online", "stale", "offline", "stopped", "unknown"]
ConsumerHealth = Literal["healthy", "failing", "unknown", "not_observed"]

_OUTBOX_STALE_SECONDS = 300
_QUEUE_FAILURE_CODES: dict[QueueName, str] = {
    "return_dedup": "return_dedup_query_failed",
    "publication_outbox": "publication_outbox_query_failed",
    "catalog_export": "catalog_export_query_failed",
    "catalog_import": "catalog_import_query_failed",
}


class HeartbeatThresholdsResponse(BaseModel):
    heartbeat_seconds: Literal[10]
    stale_seconds: Literal[30]
    offline_seconds: Literal[60]
    refresh_seconds: Literal[15]


class WorkerConsumerStatusResponse(BaseModel):
    queue_name: QueueName
    consumer_health: ConsumerHealth
    last_poll_started_at: datetime | None
    last_poll_completed_at: datetime | None
    last_poll_succeeded_at: datetime | None
    last_poll_failed_at: datetime | None
    consecutive_failures: int
    failure_code: str | None


class WorkerInstanceStatusResponse(BaseModel):
    instance_id: str
    role: str
    build_id: str
    supported_queues: list[QueueName]
    lifecycle_status: Literal["running", "stopped"]
    heartbeat_status: HeartbeatStatus
    heartbeat_sequence: int
    last_heartbeat_at: datetime | None
    heartbeat_age_seconds: float | None
    last_result_code: str | None
    consumers: list[WorkerConsumerStatusResponse]


class WorkerFleetStatusResponse(BaseModel):
    query_health: Literal["healthy", "unknown"]
    failure_code: str | None
    thresholds: HeartbeatThresholdsResponse
    instances: list[WorkerInstanceStatusResponse]


class QueueCapabilitiesResponse(BaseModel):
    actionable: bool
    in_flight: bool
    retry_wait: bool
    stale: bool
    stuck: bool


class QueueStatusResponse(BaseModel):
    queue_name: QueueName
    query_health: Literal["healthy", "unknown"]
    consumer_health: ConsumerHealth
    failure_code: str | None
    native_status_counts: dict[str, int] | None
    actionable: int | None
    in_flight: int | None
    retry_wait: int | None
    stale: int | None
    stuck: int | None
    failed: int | None
    unresolved_building: int | None
    oldest_work_at: datetime | None
    next_retry_at: datetime | None
    last_succeeded_at: datetime | None
    last_failed_at: datetime | None
    consecutive_failures: int | None
    capabilities: QueueCapabilitiesResponse


@dataclass(frozen=True, slots=True)
class _ConsumerSummary:
    health: ConsumerHealth = "not_observed"
    last_succeeded_at: datetime | None = None
    last_failed_at: datetime | None = None
    consecutive_failures: int | None = None
    failure_code: str | None = None


_CAPABILITIES: dict[QueueName, dict[str, bool]] = {
    "return_dedup": {
        "actionable": True,
        "in_flight": True,
        "retry_wait": False,
        "stale": True,
        "stuck": False,
    },
    "publication_outbox": {
        "actionable": True,
        "in_flight": True,
        "retry_wait": True,
        "stale": True,
        "stuck": False,
    },
    "catalog_export": {
        "actionable": False,
        "in_flight": False,
        "retry_wait": False,
        "stale": False,
        "stuck": False,
    },
    "catalog_import": {
        "actionable": True,
        "in_flight": True,
        "retry_wait": False,
        "stale": False,
        "stuck": True,
    },
}


def _thresholds() -> HeartbeatThresholdsResponse:
    return HeartbeatThresholdsResponse(
        heartbeat_seconds=cast(Literal[10], HEARTBEAT_SECONDS),
        stale_seconds=cast(Literal[30], STALE_SECONDS),
        offline_seconds=cast(Literal[60], OFFLINE_SECONDS),
        refresh_seconds=cast(Literal[15], REFRESH_SECONDS),
    )


def _utc(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise RuntimeError("Worker status timestamp has an invalid database type")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_utc(value: object) -> datetime:
    resolved = _utc(value)
    if resolved is None:
        raise RuntimeError("Worker status observed time is unavailable")
    return resolved


def _mysql_datetime(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(cast(int, value))


def _native_counts(value: object) -> dict[str, int]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError("native queue status counts have an invalid database type")
    return {str(key): int(cast(int, count or 0)) for key, count in value.items()}


def classify_heartbeat(
    *,
    age_seconds: float | None,
    lifecycle_status: str,
) -> HeartbeatStatus:
    """Classify a persisted heartbeat at the approved exact boundaries."""

    if lifecycle_status == "stopped":
        return "stopped"
    if lifecycle_status != "running" or age_seconds is None:
        return "unknown"
    if age_seconds < STALE_SECONDS:
        return "online"
    if age_seconds < OFFLINE_SECONDS:
        return "stale"
    return "offline"


def _queue_status_from_row(
    queue_name: QueueName,
    row: RowMapping | dict[str, object],
    consumer: _ConsumerSummary | None = None,
) -> QueueStatusResponse:
    summary = consumer or _ConsumerSummary()
    return QueueStatusResponse(
        queue_name=queue_name,
        query_health="healthy",
        consumer_health=summary.health,
        failure_code=summary.failure_code,
        native_status_counts=_native_counts(row["native_status_counts"]),
        actionable=_optional_int(row["actionable"]),
        in_flight=_optional_int(row["in_flight"]),
        retry_wait=_optional_int(row["retry_wait"]),
        stale=_optional_int(row["stale"]),
        stuck=_optional_int(row["stuck"]),
        failed=_optional_int(row["failed"]),
        unresolved_building=_optional_int(row["unresolved_building"]),
        oldest_work_at=_utc(row["oldest_work_at"]),
        next_retry_at=_utc(row["next_retry_at"]),
        last_succeeded_at=summary.last_succeeded_at,
        last_failed_at=summary.last_failed_at,
        consecutive_failures=summary.consecutive_failures,
        capabilities=QueueCapabilitiesResponse(**_CAPABILITIES[queue_name]),
    )


def _unknown_queue_status(
    queue_name: QueueName,
    *,
    failure_code: str,
    consumer: _ConsumerSummary | None = None,
) -> QueueStatusResponse:
    summary = consumer or _ConsumerSummary(health="unknown")
    return QueueStatusResponse(
        queue_name=queue_name,
        query_health="unknown",
        consumer_health=summary.health,
        failure_code=failure_code,
        native_status_counts=None,
        actionable=None,
        in_flight=None,
        retry_wait=None,
        stale=None,
        stuck=None,
        failed=None,
        unresolved_building=None,
        oldest_work_at=None,
        next_retry_at=None,
        last_succeeded_at=summary.last_succeeded_at,
        last_failed_at=summary.last_failed_at,
        consecutive_failures=summary.consecutive_failures,
        capabilities=QueueCapabilitiesResponse(**_CAPABILITIES[queue_name]),
    )


_WORKER_SQL = sa.text(
    """
    SELECT LOWER(HEX(instances.instance_id)) AS instance_id,
           instances.role, instances.build_id, instances.supported_queues,
           instances.lifecycle_status, instances.heartbeat_sequence,
           instances.last_heartbeat_at, instances.last_result_code,
           consumers.queue_name, consumers.last_poll_started_at,
           consumers.last_poll_completed_at, consumers.last_poll_succeeded_at,
           consumers.last_poll_failed_at, consumers.consecutive_failures,
           consumers.last_failure_code
    FROM worker_instances AS instances
    LEFT JOIN worker_consumer_states AS consumers
      ON consumers.worker_instance_id = instances.instance_id
    ORDER BY instances.started_at DESC, instances.instance_id,
             FIELD(consumers.queue_name, 'return_dedup', 'publication_outbox',
                   'catalog_export', 'catalog_import')
    """
)

_QUEUE_SQL: dict[QueueName, sa.TextClause] = {
    "publication_outbox": sa.text(
        """
        SELECT JSON_OBJECT(
                   'pending', COALESCE(SUM(status='pending'), 0),
                   'processing', COALESCE(SUM(status='processing'), 0),
                   'completed', COALESCE(SUM(status='completed'), 0),
                   'failed', COALESCE(SUM(status='failed'), 0)
               ) AS native_status_counts,
               COALESCE(SUM(status='pending' AND available_at <= :observed_at), 0)
                   AS actionable,
               COALESCE(SUM(status='processing' AND locked_at >= TIMESTAMPADD(
                   SECOND, -:outbox_stale_seconds, :observed_at)), 0) AS in_flight,
               COALESCE(SUM(status='pending' AND available_at > :observed_at), 0)
                   AS retry_wait,
               COALESCE(SUM(status='processing' AND (
                   locked_at IS NULL OR locked_at < TIMESTAMPADD(
                       SECOND, -:outbox_stale_seconds, :observed_at))), 0) AS stale,
               NULL AS stuck,
               COALESCE(SUM(status='failed'), 0) AS failed,
               NULL AS unresolved_building,
               MIN(CASE WHEN status IN ('pending','processing')
                        THEN created_at END) AS oldest_work_at,
               MIN(CASE WHEN status='pending' AND available_at > :observed_at
                        THEN available_at END) AS next_retry_at
        FROM publication_outbox
        """
    ),
    "return_dedup": sa.text(
        """
        SELECT JSON_OBJECT(
                   'building', COALESCE(SUM(status='building'), 0),
                   'ready', COALESCE(SUM(status='ready'), 0),
                   'failed', COALESCE(SUM(status='failed'), 0),
                   'superseded', COALESCE(SUM(status='superseded'), 0)
               ) AS native_status_counts,
               COALESCE(SUM(status='building' AND (
                   lease_token IS NULL OR lease_expires_at <= :observed_at)), 0)
                   AS actionable,
               COALESCE(SUM(status='building' AND lease_token IS NOT NULL
                   AND lease_expires_at > :observed_at), 0) AS in_flight,
               NULL AS retry_wait,
               COALESCE(SUM(status='building' AND lease_token IS NOT NULL
                   AND lease_expires_at <= :observed_at), 0) AS stale,
               NULL AS stuck,
               COALESCE(SUM(status='failed'), 0) AS failed,
               NULL AS unresolved_building,
               MIN(CASE WHEN status='building' THEN created_at END)
                   AS oldest_work_at,
               NULL AS next_retry_at
        FROM return_dedup_staging_jobs
        """
    ),
    "catalog_export": sa.text(
        """
        SELECT JSON_OBJECT(
                   'building', COALESCE(SUM(export_status='building'), 0),
                   'ready', COALESCE(SUM(export_status='ready'), 0),
                   'failed', COALESCE(SUM(export_status='failed'), 0)
               ) AS native_status_counts,
               NULL AS actionable,
               NULL AS in_flight,
               NULL AS retry_wait,
               NULL AS stale,
               NULL AS stuck,
               COALESCE(SUM(export_status='failed'), 0) AS failed,
               COALESCE(SUM(export_status='building'), 0) AS unresolved_building,
               MIN(CASE WHEN export_status='building' THEN created_at END)
                   AS oldest_work_at,
               NULL AS next_retry_at
        FROM catalog_exports
        """
    ),
    "catalog_import": sa.text(
        """
        SELECT JSON_OBJECT(
                   'uploaded', COALESCE(SUM(imports.status='uploaded'), 0),
                   'parsing', COALESCE(SUM(imports.status='parsing'), 0),
                   'parse_failed', COALESCE(SUM(imports.status='parse_failed'), 0),
                   'needs_attention',
                       COALESCE(SUM(imports.status='needs_attention'), 0),
                   'validated', COALESCE(SUM(imports.status='validated'), 0),
                   'ready_for_approval',
                       COALESCE(SUM(imports.status='ready_for_approval'), 0),
                   'approved', COALESCE(SUM(imports.status='approved'), 0),
                   'rejected', COALESCE(SUM(imports.status='rejected'), 0),
                   'withdrawn', COALESCE(SUM(imports.status='withdrawn'), 0),
                   'superseded', COALESCE(SUM(imports.status='superseded'), 0)
               ) AS native_status_counts,
               COALESCE(SUM(imports.status='uploaded'), 0) AS actionable,
               COALESCE(SUM(imports.status='parsing' AND latest.status='running'
                   AND latest.lease_expires_at > :observed_at), 0) AS in_flight,
               NULL AS retry_wait,
               NULL AS stale,
               COALESCE(SUM(imports.status='parsing' AND latest.status='running'
                   AND latest.lease_expires_at <= :observed_at), 0) AS stuck,
               COALESCE(SUM(imports.status='parse_failed'), 0) AS failed,
               NULL AS unresolved_building,
               MIN(CASE WHEN imports.status IN ('uploaded','parsing')
                        THEN imports.created_at END) AS oldest_work_at,
               NULL AS next_retry_at
        FROM catalog_imports AS imports
        LEFT JOIN catalog_parse_attempts AS latest
          ON latest.import_id = imports.id
         AND latest.attempt_revision = imports.parse_attempt_revision
        """
    ),
}


def _supported_queues(value: object) -> list[QueueName]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or tuple(value) != QUEUE_NAMES:
        raise RuntimeError("Worker supported queue set is invalid")
    return [cast(QueueName, item) for item in value]


def _consumer_from_row(row: RowMapping) -> WorkerConsumerStatusResponse:
    failures = int(row["consecutive_failures"])
    last_succeeded_at = _utc(row["last_poll_succeeded_at"])
    if failures > 0:
        health: ConsumerHealth = "failing"
    elif last_succeeded_at is not None:
        health = "healthy"
    else:
        health = "not_observed"
    return WorkerConsumerStatusResponse(
        queue_name=cast(QueueName, str(row["queue_name"])),
        consumer_health=health,
        last_poll_started_at=_utc(row["last_poll_started_at"]),
        last_poll_completed_at=_utc(row["last_poll_completed_at"]),
        last_poll_succeeded_at=last_succeeded_at,
        last_poll_failed_at=_utc(row["last_poll_failed_at"]),
        consecutive_failures=failures,
        failure_code=(
            None if row["last_failure_code"] is None else str(row["last_failure_code"])
        ),
    )


def _read_workers(
    engine: Engine,
    *,
    observed_at: datetime,
) -> WorkerFleetStatusResponse:
    with engine.connect() as connection:
        rows = list(connection.execute(_WORKER_SQL).mappings())

    instances: list[WorkerInstanceStatusResponse] = []
    current_id: str | None = None
    current_rows: list[RowMapping] = []

    def append_instance(instance_rows: list[RowMapping]) -> None:
        if not instance_rows:
            return
        first = instance_rows[0]
        heartbeat_at = _utc(first["last_heartbeat_at"])
        age_seconds = (
            None
            if heartbeat_at is None
            else max(0.0, (observed_at - heartbeat_at).total_seconds())
        )
        lifecycle_status = cast(
            Literal["running", "stopped"], str(first["lifecycle_status"])
        )
        consumers = [
            _consumer_from_row(row)
            for row in instance_rows
            if row["queue_name"] is not None
        ]
        instances.append(
            WorkerInstanceStatusResponse(
                instance_id=str(first["instance_id"]),
                role=str(first["role"]),
                build_id=str(first["build_id"]),
                supported_queues=_supported_queues(first["supported_queues"]),
                lifecycle_status=lifecycle_status,
                heartbeat_status=classify_heartbeat(
                    age_seconds=age_seconds,
                    lifecycle_status=lifecycle_status,
                ),
                heartbeat_sequence=int(first["heartbeat_sequence"]),
                last_heartbeat_at=heartbeat_at,
                heartbeat_age_seconds=(
                    None if age_seconds is None else round(age_seconds, 3)
                ),
                last_result_code=(
                    None
                    if first["last_result_code"] is None
                    else str(first["last_result_code"])
                ),
                consumers=consumers,
            )
        )

    for row in rows:
        instance_id = str(row["instance_id"])
        if current_id is not None and instance_id != current_id:
            append_instance(current_rows)
            current_rows = []
        current_id = instance_id
        current_rows.append(row)
    append_instance(current_rows)

    return WorkerFleetStatusResponse(
        query_health="healthy",
        failure_code=None,
        thresholds=_thresholds(),
        instances=instances,
    )


def _consumer_summaries(
    fleet: WorkerFleetStatusResponse,
) -> dict[QueueName, _ConsumerSummary]:
    if fleet.query_health == "unknown":
        return {
            queue_name: _ConsumerSummary(health="unknown") for queue_name in QUEUE_NAMES
        }
    summaries: dict[QueueName, _ConsumerSummary] = {}
    for queue_name in QUEUE_NAMES:
        consumers = [
            consumer
            for instance in fleet.instances
            if instance.heartbeat_status == "online"
            for consumer in instance.consumers
            if consumer.queue_name == queue_name
        ]
        if not consumers:
            summaries[queue_name] = _ConsumerSummary()
            continue
        highest_failures = max(item.consecutive_failures for item in consumers)
        if highest_failures > 0:
            health: ConsumerHealth = "failing"
            failure_code = next(
                (
                    item.failure_code
                    for item in consumers
                    if item.consecutive_failures == highest_failures
                    and item.failure_code is not None
                ),
                None,
            )
        elif any(item.consumer_health == "healthy" for item in consumers):
            health = "healthy"
            failure_code = None
        else:
            health = "not_observed"
            failure_code = None
        succeeded = [
            item.last_poll_succeeded_at
            for item in consumers
            if item.last_poll_succeeded_at is not None
        ]
        failed = [
            item.last_poll_failed_at
            for item in consumers
            if item.last_poll_failed_at is not None
        ]
        summaries[queue_name] = _ConsumerSummary(
            health=health,
            last_succeeded_at=max(succeeded) if succeeded else None,
            last_failed_at=max(failed) if failed else None,
            consecutive_failures=highest_failures,
            failure_code=failure_code,
        )
    return summaries


def _read_queue(
    engine: Engine,
    *,
    queue_name: QueueName,
    observed_at: datetime,
    consumer: _ConsumerSummary,
) -> QueueStatusResponse:
    parameters: dict[str, object] = {"observed_at": _mysql_datetime(observed_at)}
    if queue_name == "publication_outbox":
        parameters["outbox_stale_seconds"] = _OUTBOX_STALE_SECONDS
    with engine.connect() as connection:
        row = connection.execute(_QUEUE_SQL[queue_name], parameters).mappings().one()
    return _queue_status_from_row(queue_name, row, consumer)


def read_worker_observability(
    engine: Engine,
    *,
    maintenance_active: bool,
) -> tuple[datetime, WorkerFleetStatusResponse, list[QueueStatusResponse]]:
    """Read one fleet snapshot and four independently isolated native queues."""

    del maintenance_active  # Maintenance state is deliberately orthogonal to health.
    with engine.connect() as connection:
        observed_at = _required_utc(
            connection.scalar(sa.text("SELECT UTC_TIMESTAMP(6)"))
        )

    try:
        fleet = _read_workers(engine, observed_at=observed_at)
    except Exception:
        fleet = WorkerFleetStatusResponse(
            query_health="unknown",
            failure_code="worker_fleet_query_failed",
            thresholds=_thresholds(),
            instances=[],
        )

    consumer_summaries = _consumer_summaries(fleet)
    queues: list[QueueStatusResponse] = []
    for queue_name in QUEUE_NAMES:
        try:
            queue = _read_queue(
                engine,
                queue_name=queue_name,
                observed_at=observed_at,
                consumer=consumer_summaries[queue_name],
            )
        except Exception:
            queue = _unknown_queue_status(
                queue_name,
                failure_code=_QUEUE_FAILURE_CODES[queue_name],
                consumer=consumer_summaries[queue_name],
            )
        queues.append(queue)
    return observed_at, fleet, queues


__all__ = (
    "HeartbeatThresholdsResponse",
    "QueueCapabilitiesResponse",
    "QueueStatusResponse",
    "WorkerConsumerStatusResponse",
    "WorkerFleetStatusResponse",
    "WorkerInstanceStatusResponse",
    "classify_heartbeat",
    "read_worker_observability",
)
