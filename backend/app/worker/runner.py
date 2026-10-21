"""One bounded pass over each local background-work queue."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import TypeVar

from app.catalog.export_service import CatalogExportResult
from app.catalog.return_dedup_repository import ReturnDedupStagingJob
from app.worker.catalog_exports import CatalogExportWorker
from app.worker.catalog_imports import CatalogImportWorker, CatalogImportWorkerResult
from app.worker.observability import (
    PollOutcome,
    QueueName,
    QueueOutcome,
    WorkerTelemetry,
    safe_failure_code,
)
from app.worker.outbox import ClaimedOutboxItem, PublicationOutboxWorker
from app.worker.return_dedup import ReturnDedupWorker

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class WorkerPass:
    return_dedup: ReturnDedupStagingJob | None
    outbox: ClaimedOutboxItem | None
    catalog_export: CatalogExportResult | None = None
    catalog_import: CatalogImportWorkerResult | None = None

    @property
    def did_work(self) -> bool:
        return (
            self.return_dedup is not None
            or self.catalog_export is not None
            or self.catalog_import is not None
            or self.outbox is not None
        )


class WorkerRunner:
    def __init__(
        self,
        *,
        return_dedup: ReturnDedupWorker,
        outbox: PublicationOutboxWorker,
        catalog_exports: CatalogExportWorker | None = None,
        catalog_imports: CatalogImportWorker | None = None,
        telemetry: WorkerTelemetry,
    ) -> None:
        self._return_dedup = return_dedup
        self._outbox = outbox
        self._catalog_exports = catalog_exports
        self._catalog_imports = catalog_imports
        self._telemetry = telemetry

    @staticmethod
    def _log_extra(
        *,
        event: str,
        queue_name: QueueName,
        outcome: QueueOutcome,
        duration_ms: float,
        failure_code: str,
    ) -> dict[str, object]:
        return {
            "event": event,
            "worker_instance_id": None,
            "queue_name": queue_name,
            "outcome": outcome,
            "duration_ms": round(duration_ms, 3),
            "attempt": 0,
            "failure_code": failure_code,
        }

    def _log_state_write_failure(
        self,
        *,
        queue_name: QueueName,
        started: float,
        outcome: QueueOutcome,
    ) -> None:
        logger.error(
            "Worker consumer state write failed.",
            extra=self._log_extra(
                event="worker_consumer_state_write_failed",
                queue_name=queue_name,
                outcome=outcome,
                duration_ms=(perf_counter() - started) * 1000,
                failure_code="consumer_state_write_failed",
            ),
        )

    def _run_consumer(
        self,
        queue_name: QueueName,
        operation: Callable[[], T | None],
    ) -> T | None:
        if not self._telemetry.can_claim():
            return None

        started = perf_counter()
        try:
            self._telemetry.poll_started(queue_name)
        except Exception:
            self._log_state_write_failure(
                queue_name=queue_name,
                started=started,
                outcome="skipped",
            )
            return None

        try:
            result = operation()
        except Exception as error:
            failure_code = safe_failure_code(error, queue_name)
            try:
                self._telemetry.poll_failed(queue_name, failure_code)
            except Exception:
                self._log_state_write_failure(
                    queue_name=queue_name,
                    started=started,
                    outcome="failed",
                )
            logger.exception(
                "Worker consumer failed.",
                extra=self._log_extra(
                    event="worker_consumer_failed",
                    queue_name=queue_name,
                    outcome="failed",
                    duration_ms=(perf_counter() - started) * 1000,
                    failure_code=failure_code,
                ),
            )
            return None

        outcome = PollOutcome(
            result_code=(
                "queue_work_completed" if result is not None else "queue_idle"
            ),
            did_work=result is not None,
        )
        try:
            self._telemetry.poll_succeeded(queue_name, outcome)
        except Exception:
            self._log_state_write_failure(
                queue_name=queue_name,
                started=started,
                outcome="succeeded",
            )
        return result

    def run_once(self) -> WorkerPass:
        return_dedup = self._run_consumer(
            "return_dedup",
            self._return_dedup.run_once,
        )
        outbox = self._run_consumer(
            "publication_outbox",
            self._outbox.run_once,
        )
        catalog_export = None
        if self._catalog_exports is not None:
            catalog_export = self._run_consumer(
                "catalog_export",
                self._catalog_exports.run_once,
            )
        catalog_import = None
        if self._catalog_imports is not None:
            catalog_import = self._run_consumer(
                "catalog_import",
                self._catalog_imports.run_once,
            )
        return WorkerPass(
            return_dedup=return_dedup,
            outbox=outbox,
            catalog_export=catalog_export,
            catalog_import=catalog_import,
        )


__all__ = ("WorkerPass", "WorkerRunner")
