from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.catalog.export_jobs import (
    CatalogExportJobNotRecoverable,
    CatalogExportJobRevisionConflict,
    MySqlCatalogExportJobRepository,
)
from app.catalog.export_service import (
    CatalogExportCommand,
    CatalogExportFinalizationError,
    MySqlCatalogExportFinalizer,
)
from app.catalog.ooxml import CapacityViolation
from app.catalog.snapshots import (
    MySqlCatalogSnapshotCoordinator,
    MySqlCatalogSnapshotWriter,
)
from app.catalog.workbook import CatalogWorkbookData
from app.imports.storage import StoredContent
from app.worker.catalog_exports import MySqlCatalogExportWorkSource
from sqlalchemy.engine import Engine

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import PublicationIntegrationCase
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)
from tests.integration.test_catalog_snapshot_consistency import (
    CUTOFF,
    REPORT_DATE,
    _cleanup,
    _confirm_scope,
    _seed_ready_dedup,
)

pytestmark = pytest.mark.mysql


@pytest.fixture(name="catalog_export_case")
def catalog_export_case_fixture(
    publication_case: PublicationIntegrationCase,
) -> Iterator[PublicationIntegrationCase]:
    _cleanup(publication_case)
    try:
        yield publication_case
    finally:
        _cleanup(publication_case)


def _building_export(
    case: PublicationIntegrationCase,
) -> tuple[CatalogExportCommand, Engine]:
    _baseline, business = case.materialize_baseline(
        report_date=REPORT_DATE,
        variant="export-finalizer-business",
        report_type="business_report",
    )
    _return_baseline, returns = case.materialize_baseline(
        report_date=REPORT_DATE,
        variant="export-finalizer-returns",
        report_type="return_report",
    )
    case.dataset_case.mark_published(business.dataset_id, business.version_id)
    case.dataset_case.mark_published(returns.dataset_id, returns.version_id)
    scope_id = _confirm_scope(case)
    _seed_ready_dedup(
        case,
        scope_id=scope_id,
        return_dataset_id=returns.dataset_id,
        return_version_id=returns.version_id,
    )
    runtime = case.dataset_case.runtime_engine()
    frozen = MySqlCatalogSnapshotCoordinator(runtime).freeze(
        site_id=1,
        fact_cutoff_at=CUTOFF,
    )
    token = uuid4()
    created = MySqlCatalogSnapshotWriter(runtime).persist_building(
        frozen,
        operation_token=token,
        created_by_user_id=case.owner_user_id,
    )
    command = CatalogExportCommand(
        export_id=created.export_id,
        operation_token=token,
        payload_digest=created.payload_digest,
        workbook=CatalogWorkbookData(rows={}),
    )
    return command, runtime


@pytest.mark.parametrize("capacity", [False, True])
def test_ready_finalization_atomically_advances_frozen_group(
    catalog_export_case: PublicationIntegrationCase,
    capacity: bool,
) -> None:
    command, runtime = _building_export(catalog_export_case)
    try:
        finalizer = MySqlCatalogExportFinalizer(runtime)
        violations: tuple[CapacityViolation, ...]
        if capacity:
            artifact = None
            violations = (
                CapacityViolation(
                    "sheet_row_limit", "来源证据", "30001", "30000", "rows"
                ),
            )
        else:
            artifact = StoredContent(
                "sha256/aa/" + "a" * 64,
                "a" * 64,
                123,
                False,
            )
            violations = ()
        finalizer.finalize_ready(
            command,
            artifact=artifact,
            capacity_violations=violations,
        )
        # Exact retry is idempotent and does not advance any current pointer.
        finalizer.finalize_ready(
            command,
            artifact=artifact,
            capacity_violations=violations,
        )
        row = catalog_export_case.dataset_case.rows(
            """
            SELECT exports.export_status, exports.workbook_status,
                   JSON_LENGTH(exports.capacity_violations) AS violation_count,
                   exports.artifact_storage_key,
                   snapshots.status AS snapshot_status,
                   tuples.status AS tuple_status
            FROM catalog_exports AS exports
            INNER JOIN fact_snapshot_tuples AS tuples
                ON tuples.id = exports.fact_snapshot_tuple_id
            INNER JOIN publication_snapshots AS snapshots
                ON snapshots.id = tuples.publication_snapshot_id
            WHERE exports.id = :export_id
            """,
            {"export_id": command.export_id},
        )[0]
        assert row["export_status"] == "ready"
        assert row["snapshot_status"] == "ready"
        assert row["tuple_status"] == "ready"
        assert row["workbook_status"] == ("capacity_exceeded" if capacity else "ready")
        assert int(row["violation_count"]) == (1 if capacity else 0)
        assert (row["artifact_storage_key"] is None) is capacity
        assert (
            catalog_export_case.dataset_case.scalar(
                "SELECT COALESCE(MAX(catalog_publication_revision), 0) "
                "FROM product_catalog_publications WHERE site_id = 1"
            )
            == 0
        )
    finally:
        runtime.dispose()


def test_failure_finalization_advances_whole_group_to_failed(
    catalog_export_case: PublicationIntegrationCase,
) -> None:
    command, runtime = _building_export(catalog_export_case)
    try:
        finalizer = MySqlCatalogExportFinalizer(runtime)
        finalizer.finalize_failed(command, reason="ooxml_part_not_allowed")
        finalizer.finalize_failed(command, reason="ooxml_part_not_allowed")
        rows = catalog_export_case.dataset_case.rows(
            """
            SELECT exports.export_status, exports.failure_reason_code,
                   snapshots.status AS snapshot_status,
                   tuples.status AS tuple_status
            FROM catalog_exports AS exports
            INNER JOIN fact_snapshot_tuples AS tuples
                ON tuples.id = exports.fact_snapshot_tuple_id
            INNER JOIN publication_snapshots AS snapshots
                ON snapshots.id = tuples.publication_snapshot_id
            WHERE exports.id = :export_id
            """,
            {"export_id": command.export_id},
        )
        assert rows == [
            {
                "export_status": "failed",
                "failure_reason_code": "ooxml_part_not_allowed",
                "snapshot_status": "failed",
                "tuple_status": "failed",
            }
        ]
    finally:
        runtime.dispose()


def test_export_job_retries_recovers_and_fences_expired_worker(
    catalog_export_case: PublicationIntegrationCase,
) -> None:
    created, runtime = _building_export(catalog_export_case)
    now = datetime.now(UTC)
    source = MySqlCatalogExportWorkSource(runtime, clock=lambda: now)
    try:
        for expected_attempt, delay in ((1, 5), (2, 10)):
            lease = source.claim_next()
            assert lease is not None
            assert lease.export_id == created.export_id
            assert lease.attempt_count == expected_attempt
            if expected_attempt == 1:
                with pytest.raises(CatalogExportJobNotRecoverable):
                    MySqlCatalogExportJobRepository(runtime).resume(
                        export_id=created.export_id,
                        site_id=1,
                        actor_user_id=catalog_export_case.owner_user_id,
                        operation_token=uuid4(),
                        expected_job_revision=lease.job_revision,
                    )
            lease = source.renew(lease)
            source.fail_retryable(lease, reason="catalog_export_worker_error")
            row = catalog_export_case.dataset_case.rows(
                """
                SELECT status, retry_allowed, attempt_count, next_attempt_at
                FROM catalog_jobs
                WHERE resource_kind = 'catalog_export'
                  AND resource_id = :export_id
                """,
                {"export_id": created.export_id},
            )[0]
            assert row["status"] == "queued"
            assert not bool(row["retry_allowed"])
            assert int(row["attempt_count"]) == expected_attempt
            assert row["next_attempt_at"] == (now + timedelta(seconds=delay)).replace(
                tzinfo=None
            )
            now += timedelta(seconds=delay)

        terminal = source.claim_next()
        assert terminal is not None and terminal.attempt_count == 3
        terminal = source.renew(terminal)
        source.fail_retryable(terminal, reason="catalog_export_worker_error")
        failed = catalog_export_case.dataset_case.rows(
            """
            SELECT job_revision, status, retry_allowed, execution_phase
            FROM catalog_jobs
            WHERE resource_kind = 'catalog_export' AND resource_id = :export_id
            """,
            {"export_id": created.export_id},
        )[0]
        assert failed["status"] == "failed"
        assert bool(failed["retry_allowed"])
        assert failed["execution_phase"] == "awaiting_manual_recovery"

        recovery_token = uuid4()
        repository = MySqlCatalogExportJobRepository(runtime)
        with pytest.raises(CatalogExportJobRevisionConflict):
            repository.resume(
                export_id=created.export_id,
                site_id=1,
                actor_user_id=catalog_export_case.owner_user_id,
                operation_token=uuid4(),
                expected_job_revision=int(failed["job_revision"]) - 1,
            )
        recovered = repository.resume(
            export_id=created.export_id,
            site_id=1,
            actor_user_id=catalog_export_case.owner_user_id,
            operation_token=recovery_token,
            expected_job_revision=int(failed["job_revision"]),
        )
        assert (
            repository.resume(
                export_id=created.export_id,
                site_id=1,
                actor_user_id=catalog_export_case.owner_user_id,
                operation_token=recovery_token,
                expected_job_revision=int(failed["job_revision"]),
            )
            == recovered
        )

        stale = source.claim_next()
        assert stale is not None and stale.attempt_count == 1
        now += timedelta(seconds=301)
        replacement = source.claim_next()
        assert replacement is not None
        assert replacement.fencing_token == stale.fencing_token + 1
        artifact = StoredContent("sha256/bb/" + "b" * 64, "b" * 64, 12, False)
        with pytest.raises(CatalogExportFinalizationError):
            MySqlCatalogExportFinalizer(runtime).finalize_ready(
                stale,
                artifact=artifact,
                capacity_violations=(),
            )
        assert (
            catalog_export_case.dataset_case.scalar(
                "SELECT COUNT(*) FROM catalog_audit_events "
                "WHERE event_kind = 'catalog_export_resumed' "
                "AND resource_id = :export_id",
                {"export_id": created.export_id},
            )
            == 1
        )
    finally:
        runtime.dispose()
