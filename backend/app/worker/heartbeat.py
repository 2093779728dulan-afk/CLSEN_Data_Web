"""Database-backed Worker lifecycle, heartbeat, and consumer telemetry."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, RLock, Thread
from time import monotonic as system_monotonic
from time import perf_counter
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.worker.observability import (
    HEARTBEAT_SECONDS,
    QUEUE_NAMES,
    RETENTION_DAYS,
    RETENTION_DELETE_LIMIT,
    PollOutcome,
    QueueName,
    QueueOutcome,
    validate_safe_code,
    worker_log_extra,
)

logger = logging.getLogger("app.worker.heartbeat")

_BUILD_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}", flags=re.ASCII)


class WorkerHeartbeatWriteError(RuntimeError):
    """A heartbeat row could not be changed under its lifecycle contract."""


def _required_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise WorkerHeartbeatWriteError("worker timestamp is unavailable")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_changed(rowcount: int, operation: str) -> None:
    if rowcount != 1:
        raise WorkerHeartbeatWriteError(f"worker {operation} lost instance ownership")


class WorkerHeartbeatRepository:
    """Persist Worker observations with one bounded transaction per operation."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def register(
        self,
        *,
        instance_id: UUID,
        role: str,
        build_id: str,
        supported_queues: tuple[QueueName, ...],
    ) -> datetime:
        if role != "local_worker":
            raise ValueError("worker role must be local_worker")
        if _BUILD_ID_PATTERN.fullmatch(build_id) is None:
            raise ValueError("worker build ID is invalid")
        if supported_queues != QUEUE_NAMES:
            raise ValueError("worker queue set does not match the frozen contract")
        with self._engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO worker_instances (
                        instance_id, role, build_id, supported_queues,
                        lifecycle_status, heartbeat_sequence,
                        started_at, last_heartbeat_at, stopped_at,
                        last_result_code
                    ) VALUES (
                        :instance_id, :role, :build_id, :supported_queues,
                        'running', 0, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6),
                        NULL, 'worker_started'
                    )
                    """
                ),
                {
                    "instance_id": instance_id.bytes,
                    "role": role,
                    "build_id": build_id,
                    "supported_queues": json.dumps(supported_queues),
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO worker_consumer_states (
                        worker_instance_id, queue_name
                    ) VALUES (:instance_id, :queue_name)
                    """
                ),
                [
                    {"instance_id": instance_id.bytes, "queue_name": queue_name}
                    for queue_name in supported_queues
                ],
            )
            started_at = connection.scalar(
                sa.text(
                    """
                    SELECT started_at
                    FROM worker_instances
                    WHERE instance_id = :instance_id
                    """
                ),
                {"instance_id": instance_id.bytes},
            )
        return _required_utc(started_at)

    def heartbeat(
        self,
        *,
        instance_id: UUID,
        sequence: int,
        result_code: str,
    ) -> datetime:
        if sequence < 1:
            raise ValueError("heartbeat sequence must be positive")
        validate_safe_code(result_code, label="result code")
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.text(
                    """
                    UPDATE worker_instances
                    SET heartbeat_sequence = :sequence,
                        last_heartbeat_at = UTC_TIMESTAMP(6),
                        last_result_code = :result_code
                    WHERE instance_id = :instance_id
                      AND lifecycle_status = 'running'
                      AND heartbeat_sequence < :sequence
                    """
                ),
                {
                    "instance_id": instance_id.bytes,
                    "sequence": sequence,
                    "result_code": result_code,
                },
            )
            _require_changed(result.rowcount, "heartbeat")
            heartbeat_at = connection.scalar(
                sa.text(
                    """
                    SELECT last_heartbeat_at
                    FROM worker_instances
                    WHERE instance_id = :instance_id
                    """
                ),
                {"instance_id": instance_id.bytes},
            )
        return _required_utc(heartbeat_at)

    def poll_started(
        self,
        *,
        instance_id: UUID,
        queue_name: QueueName,
    ) -> datetime:
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.text(
                    """
                    UPDATE worker_consumer_states AS consumers
                    INNER JOIN worker_instances AS instances
                        ON instances.instance_id = consumers.worker_instance_id
                    SET consumers.last_poll_started_at = UTC_TIMESTAMP(6)
                    WHERE consumers.worker_instance_id = :instance_id
                      AND consumers.queue_name = :queue_name
                      AND instances.lifecycle_status = 'running'
                    """
                ),
                {"instance_id": instance_id.bytes, "queue_name": queue_name},
            )
            _require_changed(result.rowcount, "poll start")
            started_at = connection.scalar(
                sa.text(
                    """
                    SELECT last_poll_started_at
                    FROM worker_consumer_states
                    WHERE worker_instance_id = :instance_id
                      AND queue_name = :queue_name
                    """
                ),
                {"instance_id": instance_id.bytes, "queue_name": queue_name},
            )
        return _required_utc(started_at)

    def poll_succeeded(
        self,
        *,
        instance_id: UUID,
        queue_name: QueueName,
        result_code: str,
    ) -> datetime:
        validate_safe_code(result_code, label="result code")
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.text(
                    """
                    UPDATE worker_consumer_states
                    SET last_poll_completed_at = UTC_TIMESTAMP(6),
                        last_poll_succeeded_at = UTC_TIMESTAMP(6),
                        consecutive_failures = 0,
                        last_result_code = :result_code,
                        last_failure_code = NULL
                    WHERE worker_instance_id = :instance_id
                      AND queue_name = :queue_name
                    """
                ),
                {
                    "instance_id": instance_id.bytes,
                    "queue_name": queue_name,
                    "result_code": result_code,
                },
            )
            _require_changed(result.rowcount, "poll success")
            completed_at = connection.scalar(
                sa.text(
                    """
                    SELECT last_poll_completed_at
                    FROM worker_consumer_states
                    WHERE worker_instance_id = :instance_id
                      AND queue_name = :queue_name
                    """
                ),
                {"instance_id": instance_id.bytes, "queue_name": queue_name},
            )
        return _required_utc(completed_at)

    def poll_failed(
        self,
        *,
        instance_id: UUID,
        queue_name: QueueName,
        failure_code: str,
    ) -> datetime:
        validate_safe_code(failure_code, label="failure code")
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.text(
                    """
                    UPDATE worker_consumer_states
                    SET last_poll_completed_at = UTC_TIMESTAMP(6),
                        last_poll_failed_at = UTC_TIMESTAMP(6),
                        consecutive_failures = consecutive_failures + 1,
                        last_failure_code = :failure_code
                    WHERE worker_instance_id = :instance_id
                      AND queue_name = :queue_name
                    """
                ),
                {
                    "instance_id": instance_id.bytes,
                    "queue_name": queue_name,
                    "failure_code": failure_code,
                },
            )
            _require_changed(result.rowcount, "poll failure")
            completed_at = connection.scalar(
                sa.text(
                    """
                    SELECT last_poll_completed_at
                    FROM worker_consumer_states
                    WHERE worker_instance_id = :instance_id
                      AND queue_name = :queue_name
                    """
                ),
                {"instance_id": instance_id.bytes, "queue_name": queue_name},
            )
        return _required_utc(completed_at)

    def stop(self, *, instance_id: UUID, result_code: str) -> datetime:
        validate_safe_code(result_code, label="result code")
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.text(
                    """
                    UPDATE worker_instances
                    SET lifecycle_status = 'stopped',
                        last_heartbeat_at = UTC_TIMESTAMP(6),
                        stopped_at = UTC_TIMESTAMP(6),
                        last_result_code = :result_code
                    WHERE instance_id = :instance_id
                      AND lifecycle_status = 'running'
                    """
                ),
                {"instance_id": instance_id.bytes, "result_code": result_code},
            )
            _require_changed(result.rowcount, "stop")
            stopped_at = connection.scalar(
                sa.text(
                    """
                    SELECT stopped_at
                    FROM worker_instances
                    WHERE instance_id = :instance_id
                    """
                ),
                {"instance_id": instance_id.bytes},
            )
        return _required_utc(stopped_at)

    def prune(
        self,
        *,
        retention_days: int = RETENTION_DAYS,
        limit: int = RETENTION_DELETE_LIMIT,
    ) -> int:
        if retention_days < 1:
            raise ValueError("retention days must be positive")
        if not 1 <= limit <= RETENTION_DELETE_LIMIT:
            raise ValueError("prune limit must be between 1 and 500")
        with self._engine.begin() as connection:
            instance_ids = list(
                connection.scalars(
                    sa.text(
                        """
                        SELECT instance_id
                        FROM worker_instances
                        WHERE COALESCE(stopped_at, last_heartbeat_at) <
                              TIMESTAMPADD(DAY, -:retention_days, UTC_TIMESTAMP(6))
                        ORDER BY COALESCE(stopped_at, last_heartbeat_at), instance_id
                        LIMIT :limit
                        """
                    ),
                    {"retention_days": retention_days, "limit": limit},
                )
            )
            if not instance_ids:
                return 0
            statement = sa.text(
                "DELETE FROM worker_instances WHERE instance_id IN :instance_ids"
            ).bindparams(sa.bindparam("instance_ids", expanding=True))
            result = connection.execute(statement, {"instance_ids": instance_ids})
            if result.rowcount < 0 or result.rowcount > limit:
                raise WorkerHeartbeatWriteError("worker prune exceeded its bound")
            return result.rowcount


class WorkerHeartbeatController:
    """Schedule heartbeats independently and gate the start of new queue work."""

    def __init__(
        self,
        repository: WorkerHeartbeatRepository,
        *,
        instance_id: UUID,
        build_id: str,
        monotonic: Callable[[], float] = system_monotonic,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        self._repository = repository
        self._instance_id = instance_id
        self._build_id = build_id
        self._monotonic = monotonic
        self._stop_event = Event()
        self._wait = wait or self._stop_event.wait
        self._state_lock = RLock()
        self._last_success_monotonic: float | None = None
        self._sequence = 0
        self._started = False
        self._stopping = False
        self._thread: Thread | None = None

    def _extra(
        self,
        *,
        event: str,
        outcome: QueueOutcome,
        duration_ms: float,
        attempt: int,
        failure_code: str | None,
        queue_name: QueueName | None = None,
    ) -> dict[str, object]:
        return worker_log_extra(
            event=event,
            instance_id=self._instance_id,
            queue_name=queue_name,
            outcome=outcome,
            duration_ms=duration_ms,
            attempt=attempt,
            failure_code=failure_code,
        )

    def start(self) -> None:
        with self._state_lock:
            if self._started:
                raise RuntimeError("worker heartbeat controller already started")
        started = perf_counter()
        try:
            self._repository.register(
                instance_id=self._instance_id,
                role="local_worker",
                build_id=self._build_id,
                supported_queues=QUEUE_NAMES,
            )
        except Exception:
            logger.error(
                "Worker registration failed.",
                extra=self._extra(
                    event="worker_registration_failed",
                    outcome="failed",
                    duration_ms=(perf_counter() - started) * 1000,
                    attempt=0,
                    failure_code="worker_registration_failed",
                ),
            )
            raise
        with self._state_lock:
            self._last_success_monotonic = self._monotonic()
            self._started = True
        logger.info(
            "Worker registered.",
            extra=self._extra(
                event="worker_registered",
                outcome="succeeded",
                duration_ms=(perf_counter() - started) * 1000,
                attempt=0,
                failure_code=None,
            ),
        )
        try:
            self._repository.prune()
        except Exception:
            logger.error(
                "Worker retention prune failed.",
                extra=self._extra(
                    event="worker_retention_prune_failed",
                    outcome="failed",
                    duration_ms=0,
                    attempt=0,
                    failure_code="retention_cleanup_failed",
                ),
            )
        self._thread = Thread(
            target=self._run,
            name=f"worker-heartbeat-{self._instance_id.hex[:8]}",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        while True:
            if self._wait(HEARTBEAT_SECONDS):
                return
            with self._state_lock:
                if self._stopping:
                    return
                self._sequence += 1
                sequence = self._sequence
            started = perf_counter()
            try:
                self._repository.heartbeat(
                    instance_id=self._instance_id,
                    sequence=sequence,
                    result_code="heartbeat_succeeded",
                )
            except Exception:
                with self._state_lock:
                    self._last_success_monotonic = None
                logger.error(
                    "Worker heartbeat write failed.",
                    extra=self._extra(
                        event="worker_heartbeat_failed",
                        outcome="failed",
                        duration_ms=(perf_counter() - started) * 1000,
                        attempt=sequence,
                        failure_code="heartbeat_write_failed",
                    ),
                )
                continue
            with self._state_lock:
                self._last_success_monotonic = self._monotonic()
            logger.info(
                "Worker heartbeat succeeded.",
                extra=self._extra(
                    event="worker_heartbeat_succeeded",
                    outcome="succeeded",
                    duration_ms=(perf_counter() - started) * 1000,
                    attempt=sequence,
                    failure_code=None,
                ),
            )

    def can_claim(self) -> bool:
        with self._state_lock:
            if self._stopping or self._last_success_monotonic is None:
                return False
            return self._monotonic() - self._last_success_monotonic <= HEARTBEAT_SECONDS

    def poll_started(self, queue_name: QueueName) -> None:
        if not self.can_claim():
            raise WorkerHeartbeatWriteError("worker heartbeat claim gate is closed")
        self._repository.poll_started(
            instance_id=self._instance_id,
            queue_name=queue_name,
        )

    def poll_succeeded(self, queue_name: QueueName, outcome: PollOutcome) -> None:
        self._repository.poll_succeeded(
            instance_id=self._instance_id,
            queue_name=queue_name,
            result_code=outcome.result_code,
        )

    def poll_failed(self, queue_name: QueueName, failure_code: str) -> None:
        validate_safe_code(failure_code, label="failure code")
        self._repository.poll_failed(
            instance_id=self._instance_id,
            queue_name=queue_name,
            failure_code=failure_code,
        )

    def stop(self, *, result_code: str = "worker_stopped") -> None:
        with self._state_lock:
            if not self._started or self._stopping:
                return
            self._stopping = True
            self._last_success_monotonic = None
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=HEARTBEAT_SECONDS + 1)
        started = perf_counter()
        try:
            self._repository.stop(
                instance_id=self._instance_id,
                result_code=result_code,
            )
        except Exception:
            logger.error(
                "Worker stop write failed.",
                extra=self._extra(
                    event="worker_stop_failed",
                    outcome="failed",
                    duration_ms=(perf_counter() - started) * 1000,
                    attempt=self._sequence,
                    failure_code="worker_stop_write_failed",
                ),
            )
            return
        logger.info(
            "Worker stopped.",
            extra=self._extra(
                event="worker_stopped",
                outcome="succeeded",
                duration_ms=(perf_counter() - started) * 1000,
                attempt=self._sequence,
                failure_code=None,
            ),
        )


__all__ = (
    "WorkerHeartbeatController",
    "WorkerHeartbeatRepository",
    "WorkerHeartbeatWriteError",
)
