"""Transactional claiming and idempotent publication outbox consumption."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine


class OutboxError(RuntimeError):
    """An outbox item could not be processed safely."""


@dataclass(frozen=True, slots=True)
class OutboxSettings:
    """Bounded retry and stale-claim settings for one worker process."""

    worker_id: str
    max_attempts: int = 5
    stale_after: timedelta = timedelta(minutes=5)
    base_retry_delay: timedelta = timedelta(seconds=5)

    def __post_init__(self) -> None:
        if not self.worker_id.strip() or len(self.worker_id) > 128:
            raise ValueError("worker ID must be between 1 and 128 characters")
        if self.max_attempts < 1 or self.max_attempts > 100:
            raise ValueError("max attempts must be between 1 and 100")
        if not timedelta(seconds=1) <= self.stale_after <= timedelta(hours=24):
            raise ValueError("stale claim age must be between 1 second and 24 hours")
        if not timedelta(seconds=1) <= self.base_retry_delay <= timedelta(hours=1):
            raise ValueError("retry delay must be between 1 second and 1 hour")

    @classmethod
    def local_default(cls) -> OutboxSettings:
        """Create a host- and process-distinct local worker identity."""

        import os

        return cls(worker_id=f"{socket.gethostname()}:{os.getpid()}")


@dataclass(frozen=True, slots=True)
class ClaimedOutboxItem:
    """One exclusively claimed delivery attempt."""

    item_id: int
    topic: str
    dedupe_key: str
    payload: dict[str, Any]
    publication_event_id: int | None
    site_config_version_id: int | None
    attempt_count: int


def _payload(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        payload = value
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as error:
            raise OutboxError("outbox payload is invalid JSON") from error
        if not isinstance(decoded, dict):
            raise OutboxError("outbox payload must be a JSON object")
        payload = decoded
    else:
        raise OutboxError("outbox payload has an unsupported database type")
    if any(not isinstance(key, str) for key in payload):
        raise OutboxError("outbox payload keys must be strings")
    return payload


class PublicationOutboxWorker:
    """Consume invalidation events without exposing arbitrary task execution."""

    def __init__(self, engine: Engine, settings: OutboxSettings | None = None) -> None:
        self._engine = engine
        self._settings = settings or OutboxSettings.local_default()

    def _claim_one(self) -> ClaimedOutboxItem | None:
        stale_seconds = int(self._settings.stale_after.total_seconds())
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                    SELECT id, publication_event_id, site_config_version_id,
                           topic, dedupe_key, redacted_payload, attempt_count
                    FROM publication_outbox
                    WHERE (
                        status = 'pending' AND available_at <= UTC_TIMESTAMP(6)
                    ) OR (
                        status = 'processing'
                        AND locked_at < TIMESTAMPADD(
                            SECOND, -:stale_seconds, UTC_TIMESTAMP(6)
                        )
                    )
                    ORDER BY id
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                    ),
                    {"stale_seconds": stale_seconds},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            item_id = int(row["id"])
            attempt_count = int(row["attempt_count"]) + 1
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE publication_outbox
                    SET status = 'processing', attempt_count = :attempt_count,
                        locked_at = UTC_TIMESTAMP(6), locked_by = :worker_id,
                        processed_at = NULL, last_error = NULL,
                        updated_at = UTC_TIMESTAMP(6)
                    WHERE id = :item_id
                    """
                ),
                {
                    "item_id": item_id,
                    "attempt_count": attempt_count,
                    "worker_id": self._settings.worker_id,
                },
            )
            if updated.rowcount != 1:
                raise OutboxError("claimed outbox row could not be locked")
            publication_event_id = row["publication_event_id"]
            site_config_version_id = row["site_config_version_id"]
            return ClaimedOutboxItem(
                item_id=item_id,
                topic=str(row["topic"]),
                dedupe_key=str(row["dedupe_key"]),
                payload=_payload(row["redacted_payload"]),
                publication_event_id=(
                    None if publication_event_id is None else int(publication_event_id)
                ),
                site_config_version_id=(
                    None
                    if site_config_version_id is None
                    else int(site_config_version_id)
                ),
                attempt_count=attempt_count,
            )

    @staticmethod
    def _apply(connection: Connection, item: ClaimedOutboxItem) -> None:
        # Stage 9 analytics query current publication/configuration pointers directly.
        # Consumption therefore validates the durable source and acknowledges the
        # invalidation. Future materialized summaries can replace this operation while
        # retaining the same dedupe key and claim protocol.
        if item.topic == "publication.event":
            if (
                item.publication_event_id is None
                or item.site_config_version_id is not None
            ):
                raise OutboxError("publication event outbox source is invalid")
            exists = connection.scalar(
                sa.text("SELECT COUNT(*) FROM publication_events WHERE id = :id"),
                {"id": item.publication_event_id},
            )
        elif item.topic == "site_config.changed":
            if (
                item.site_config_version_id is None
                or item.publication_event_id is not None
            ):
                raise OutboxError("site configuration outbox source is invalid")
            exists = connection.scalar(
                sa.text("SELECT COUNT(*) FROM site_config_versions WHERE id = :id"),
                {"id": item.site_config_version_id},
            )
        else:
            raise OutboxError(f"unsupported outbox topic: {item.topic}")
        if int(exists or 0) != 1:
            raise OutboxError("outbox source record is missing")

    def _complete(self, item: ClaimedOutboxItem) -> None:
        with self._engine.begin() as connection:
            self._apply(connection, item)
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE publication_outbox
                    SET status = 'completed', processed_at = UTC_TIMESTAMP(6),
                        locked_at = NULL, locked_by = NULL, last_error = NULL,
                        updated_at = UTC_TIMESTAMP(6)
                    WHERE id = :item_id AND status = 'processing'
                      AND locked_by = :worker_id
                      AND attempt_count = :attempt_count
                    """
                ),
                {
                    "item_id": item.item_id,
                    "worker_id": self._settings.worker_id,
                    "attempt_count": item.attempt_count,
                },
            )
            if updated.rowcount != 1:
                raise OutboxError("outbox completion lost ownership of its claim")

    def _retry_or_fail(self, item: ClaimedOutboxItem, error: Exception) -> None:
        message = f"{type(error).__name__}: {error}"[:4000]
        terminal = item.attempt_count >= self._settings.max_attempts
        retry_seconds = min(
            3600,
            int(self._settings.base_retry_delay.total_seconds())
            * (2 ** max(0, item.attempt_count - 1)),
        )
        with self._engine.begin() as connection:
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE publication_outbox
                    SET status = :status,
                        available_at = CASE
                            WHEN :terminal = 1 THEN available_at
                            ELSE UTC_TIMESTAMP(6) + INTERVAL :retry_seconds SECOND
                        END,
                        locked_at = NULL, locked_by = NULL,
                        last_error = :last_error,
                        updated_at = UTC_TIMESTAMP(6)
                    WHERE id = :item_id AND status = 'processing'
                      AND locked_by = :worker_id
                      AND attempt_count = :attempt_count
                    """
                ),
                {
                    "status": "failed" if terminal else "pending",
                    "terminal": 1 if terminal else 0,
                    "retry_seconds": retry_seconds,
                    "last_error": message,
                    "item_id": item.item_id,
                    "worker_id": self._settings.worker_id,
                    "attempt_count": item.attempt_count,
                },
            )
            if updated.rowcount != 1:
                raise OutboxError("outbox failure handling lost ownership of its claim")

    def run_once(self) -> ClaimedOutboxItem | None:
        """Process at most one item; return None when no work is currently ready."""

        item = self._claim_one()
        if item is None:
            return None
        try:
            self._complete(item)
        except Exception as error:
            self._retry_or_fail(item, error)
        return item
