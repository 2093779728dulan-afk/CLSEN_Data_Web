"""One-at-a-time materialization of frozen building catalog exports."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.catalog.export_service import (
    CatalogExportCommand,
    CatalogExportResult,
)
from app.catalog.inventory import load_catalog_identity_inventory
from app.catalog.workbook import workbook_from_export_payload


class CatalogExportWorkSource(Protocol):
    def claim_next(self) -> CatalogExportCommand | None: ...

    def renew(self, command: CatalogExportCommand) -> CatalogExportCommand: ...

    def fail_retryable(self, command: CatalogExportCommand, *, reason: str) -> None: ...


class CatalogExportWorkMaterializer(Protocol):
    def materialize(self, command: CatalogExportCommand) -> CatalogExportResult: ...


MAX_EXPORT_ATTEMPTS = 3
EXPORT_LEASE_SECONDS = 300


def retry_delay_seconds(attempt_count: int) -> int:
    if attempt_count < 1:
        raise ValueError("attempt_count must be positive")
    return min(300, 5 * (1 << (attempt_count - 1)))


class MySqlCatalogExportWorkSource:
    """Read only the immutable export payload; never reread current pointers."""

    def __init__(
        self, engine: Engine, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self._engine = engine
        self._clock = clock or (lambda: datetime.now(UTC))

    def claim_next(self) -> CatalogExportCommand | None:
        now = self._clock()
        lease_token = UUID(bytes=os.urandom(16), version=4)
        lease_expires_at = now + timedelta(seconds=EXPORT_LEASE_SECONDS)
        with self._engine.begin() as connection:
            # Keep queue discovery narrow. Selecting the JSON payload before
            # ORDER BY made MySQL sort off-page JSON values and exhausted the
            # per-thread sort buffer for large evidence snapshots.
            export_id = connection.scalar(
                sa.text(
                    """
                    SELECT jobs.id
                    FROM catalog_jobs AS jobs
                    WHERE jobs.job_kind = 'catalog_export'
                      AND jobs.resource_kind = 'catalog_export'
                      AND (
                        (jobs.status = 'queued' AND (
                          jobs.next_attempt_at IS NULL OR jobs.next_attempt_at <= :now
                        )) OR (
                          jobs.status = 'running' AND jobs.lease_expires_at <= :now
                        )
                      )
                      AND EXISTS (
                        SELECT 1
                        FROM catalog_exports AS exports
                        WHERE exports.id = jobs.resource_id
                          AND exports.site_id = jobs.site_id
                          AND exports.export_status = 'building'
                      )
                    ORDER BY COALESCE(jobs.next_attempt_at, jobs.created_at), jobs.id
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                ),
                {"now": now.replace(tzinfo=None)},
            )
            if export_id is None:
                return None
            claimed = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_jobs
                    SET status = 'running', job_revision = job_revision + 1,
                        lease_token = :lease_token,
                        fencing_token = fencing_token + 1,
                        lease_expires_at = :lease_expires_at,
                        attempt_count = attempt_count + 1,
                        next_attempt_at = NULL,
                        execution_phase = 'materializing',
                        last_attempt_started_at = :now,
                        retry_allowed = FALSE,
                        failure_reason_code = NULL
                    WHERE id = :job_id
                    """
                ),
                {
                    "job_id": int(export_id),
                    "lease_token": lease_token.bytes,
                    "lease_expires_at": lease_expires_at.replace(tzinfo=None),
                    "now": now.replace(tzinfo=None),
                },
            )
            if claimed.rowcount != 1:
                return None
            row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT exports.id, exports.site_id, exports.operation_token,
                               jobs.id AS job_id, jobs.job_revision,
                               jobs.lease_token, jobs.fencing_token,
                               jobs.attempt_count,
                               exports.base_catalog_version_id,
                               exports.normalization_manifest_id,
                               exports.created_at,
                               payloads.candidate_payload_json,
                               JSON_EXTRACT(
                                   payloads.evidence_payload_json,
                                   '$.summaries'
                               ) AS evidence_summaries_json,
                               payloads.payload_digest,
                               snapshots.snapshot_digest,
                               sites.code AS site_code,
                               scopes.seller_account_display_name
                        FROM catalog_exports AS exports
                        INNER JOIN catalog_jobs AS jobs
                            ON jobs.resource_id = exports.id
                           AND jobs.site_id = exports.site_id
                           AND jobs.job_kind = 'catalog_export'
                           AND jobs.resource_kind = 'catalog_export'
                        INNER JOIN catalog_export_payloads AS payloads
                            ON payloads.export_id = exports.id
                           AND payloads.site_id = exports.site_id
                        INNER JOIN fact_snapshot_tuples AS tuples
                            ON tuples.id = exports.fact_snapshot_tuple_id
                           AND tuples.site_id = exports.site_id
                        INNER JOIN publication_snapshots AS snapshots
                            ON snapshots.id = tuples.publication_snapshot_id
                           AND snapshots.site_id = tuples.site_id
                        INNER JOIN report_source_scopes AS scopes
                            ON scopes.id = tuples.report_source_scope_id
                           AND scopes.site_id = tuples.site_id
                        INNER JOIN sites ON sites.id = exports.site_id
                        WHERE jobs.id = :job_id
                          AND exports.export_status = 'building'
                          AND jobs.status = 'running'
                          AND jobs.lease_token = :lease_token
                          AND snapshots.status = 'building'
                          AND tuples.status = 'building'
                        """
                    ),
                    {"job_id": int(export_id), "lease_token": lease_token.bytes},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            with self._engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        UPDATE catalog_jobs
                        SET status = 'superseded', job_revision = job_revision + 1,
                            lease_token = NULL, lease_expires_at = NULL,
                            execution_phase = 'failed', retry_allowed = FALSE,
                            failure_reason_code = 'catalog_export_state_conflict'
                        WHERE id = :job_id AND status = 'running'
                          AND lease_token = :lease_token
                        """
                    ),
                    {"job_id": int(export_id), "lease_token": lease_token.bytes},
                )
            return None
        candidates = row["candidate_payload_json"]
        evidence_summaries = row["evidence_summaries_json"]
        if isinstance(candidates, str):
            candidates = json.loads(candidates)
        if isinstance(evidence_summaries, str):
            evidence_summaries = json.loads(evidence_summaries)
        if not isinstance(candidates, dict) or not isinstance(evidence_summaries, list):
            raise RuntimeError("catalog export payload JSON is invalid")
        evidence = {"summaries": evidence_summaries}
        generated_at = row["created_at"]
        if not isinstance(generated_at, datetime):
            raise RuntimeError("catalog export timestamp is invalid")
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=UTC)
        base_catalog_version_id = (
            None
            if row["base_catalog_version_id"] is None
            else int(row["base_catalog_version_id"])
        )
        with self._engine.connect() as connection:
            inventory = load_catalog_identity_inventory(
                connection,
                site_id=int(row["site_id"]),
                catalog_version_id=base_catalog_version_id,
            )
        workbook = workbook_from_export_payload(
            export_id=int(row["id"]),
            site_code=str(row["site_code"]),
            seller_account_display_name=str(row["seller_account_display_name"]),
            base_catalog_version_id=base_catalog_version_id,
            snapshot_digest=bytes(row["snapshot_digest"]),
            normalization_manifest_id=str(row["normalization_manifest_id"]),
            generated_at=generated_at,
            candidates=candidates,
            evidence=evidence,
            existing_styles=inventory.styles,
            existing_skus=inventory.skus,
        )
        return CatalogExportCommand(
            export_id=int(row["id"]),
            operation_token=UUID(bytes=bytes(row["operation_token"])),
            payload_digest=bytes(row["payload_digest"]),
            workbook=workbook,
            job_id=int(row["job_id"]),
            job_revision=int(row["job_revision"]),
            lease_token=UUID(bytes=bytes(row["lease_token"])),
            fencing_token=int(row["fencing_token"]),
            attempt_count=int(row["attempt_count"]),
        )

    def next_building(self) -> CatalogExportCommand | None:
        """Compatibility alias for focused integration helpers."""
        return self.claim_next()

    def renew(self, command: CatalogExportCommand) -> CatalogExportCommand:
        if command.job_id is None or command.lease_token is None:
            raise RuntimeError("catalog export command is not leased")
        expires_at = self._clock() + timedelta(seconds=EXPORT_LEASE_SECONDS)
        with self._engine.begin() as connection:
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_jobs
                    SET lease_expires_at = :expires_at,
                        job_revision = job_revision + 1
                    WHERE id = :job_id AND status = 'running'
                      AND lease_token = :lease_token
                      AND fencing_token = :fencing_token
                      AND job_revision = :job_revision
                    """
                ),
                {
                    "expires_at": expires_at.replace(tzinfo=None),
                    "job_id": command.job_id,
                    "lease_token": command.lease_token.bytes,
                    "fencing_token": command.fencing_token,
                    "job_revision": command.job_revision,
                },
            )
        if updated.rowcount != 1:
            raise RuntimeError("catalog export lease was lost")
        return replace(command, job_revision=command.job_revision + 1)

    def fail_retryable(self, command: CatalogExportCommand, *, reason: str) -> None:
        if command.job_id is None or command.lease_token is None:
            raise RuntimeError("catalog export command is not leased")
        terminal = command.attempt_count >= MAX_EXPORT_ATTEMPTS
        next_attempt_at = None
        if not terminal:
            next_attempt_at = self._clock() + timedelta(
                seconds=retry_delay_seconds(command.attempt_count)
            )
        with self._engine.begin() as connection:
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_jobs
                    SET status = :status, job_revision = job_revision + 1,
                        lease_token = NULL, lease_expires_at = NULL,
                        next_attempt_at = :next_attempt_at,
                        execution_phase = :phase,
                        retry_allowed = :retry_allowed,
                        failure_reason_code = :reason,
                        last_attempt_completed_at = :completed_at
                    WHERE id = :job_id AND status = 'running'
                      AND lease_token = :lease_token
                      AND fencing_token = :fencing_token
                      AND job_revision = :job_revision
                    """
                ),
                {
                    "status": "failed" if terminal else "queued",
                    "next_attempt_at": (
                        None
                        if next_attempt_at is None
                        else next_attempt_at.replace(tzinfo=None)
                    ),
                    "phase": (
                        "awaiting_manual_recovery" if terminal else "retry_scheduled"
                    ),
                    "retry_allowed": terminal,
                    "reason": reason,
                    "completed_at": self._clock().replace(tzinfo=None),
                    "job_id": command.job_id,
                    "lease_token": command.lease_token.bytes,
                    "fencing_token": command.fencing_token,
                    "job_revision": command.job_revision,
                },
            )
        if updated.rowcount != 1:
            raise RuntimeError("catalog export lease was lost")


class CatalogExportWorker:
    def __init__(
        self,
        *,
        source: CatalogExportWorkSource,
        materializer: CatalogExportWorkMaterializer,
    ) -> None:
        self._source = source
        self._materializer = materializer

    def run_once(self) -> CatalogExportResult | None:
        command = self._source.claim_next()
        if command is None:
            return None
        command = self._source.renew(command)
        try:
            return self._materializer.materialize(command)
        except Exception:
            self._source.fail_retryable(command, reason="catalog_export_worker_error")
            raise


__all__ = (
    "MAX_EXPORT_ATTEMPTS",
    "CatalogExportWorker",
    "MySqlCatalogExportWorkSource",
    "retry_delay_seconds",
)
