from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.analytics.readiness import read_readiness
from app.analytics.style_repository import MySqlStyleAnalyticsRepository
from app.catalog.return_dedup_repository import (
    CreateReturnDedupStaging,
    MySqlReturnDedupRepository,
    ReturnDedupNotFound,
    ReturnDedupPermissionDenied,
    ReturnDedupPublicationRevisionConflict,
    ReturnDedupStagingConflict,
    ReturnDedupStagingJob,
    build_frozen_groups,
)
from app.catalog.service import CatalogService
from app.site_context import CurrentSiteContext

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import (
    PublicationIntegrationCase,
)
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)
from tests.integration.test_catalog_repository import (
    _cleanup_catalog,
    _prepare_ready_import,
)
from tests.integration.test_return_dedup import (
    NOW,
    _cleanup,
    _confirm_scope,
    _context,
    _current_return_publication_digest,
    _current_return_snapshot_digest,
    _materialize_return,
)

REPORT_DATE = date(2026, 8, 22)

pytestmark = pytest.mark.mysql


def _command(
    repo: MySqlReturnDedupRepository, context: CurrentSiteContext
) -> CreateReturnDedupStaging:
    preview = repo.initialization_preview(context)
    return CreateReturnDedupStaging(
        operation_token=uuid4(),
        dataset_id=preview["dataset_id"],
        proposed_version_id=preview["proposed_version_id"],
        expected_publication_revision=preview["expected_publication_revision"],
        expected_dedup_publication_revision=0,
        initialization_revision=preview["initialization_revision"],
        expected_set_digest=bytes.fromhex(preview["expected_set_digest"]),
    )


def _finish(
    repo: MySqlReturnDedupRepository, job: ReturnDedupStagingJob
) -> ReturnDedupStagingJob:
    lease = repo.claim(
        job_id=job.job_id,
        expected_job_revision=job.job_revision,
        lease_token=uuid4(),
        occurred_at=NOW + timedelta(seconds=1),
        lease_ttl=timedelta(minutes=1),
    )
    frozen = repo.load_frozen_input(lease)
    return repo.complete(
        lease,
        frozen=frozen,
        groups=build_frozen_groups(frozen),
        occurred_at=NOW + timedelta(seconds=2),
    )


def _delete_jobs(case: PublicationIntegrationCase) -> None:
    with case.dataset_case.migration_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM return_dedup_staging_members"))
        conn.execute(sa.text("DELETE FROM return_dedup_staging_jobs"))


def test_initialization_identity_trigger_rejects_revision_change(
    publication_case: PublicationIntegrationCase,
) -> None:
    case = publication_case
    _cleanup(case)
    engine = case.dataset_case.runtime_engine()
    try:
        _confirm_scope(case)
        dataset, version = _materialize_return(case, date(2097, 1, 1))
        case.dataset_case.mark_published(dataset, version)
        repo = MySqlReturnDedupRepository(engine)
        context = _context(case)
        job = repo.create_staging(
            context,
            _command(repo, context),
            occurred_at=NOW,
        )
        assert job.initialization_revision is not None

        with (
            pytest.raises(
                sa.exc.DatabaseError, match="initialization identity is immutable"
            ),
            case.dataset_case.migration_engine.begin() as connection,
        ):
            connection.execute(
                sa.text(
                    """
                    UPDATE return_dedup_staging_jobs
                    SET initialization_revision = :revision
                    WHERE id = :job_id
                    """
                ),
                {
                    "revision": int(job.initialization_revision) + 1,
                    "job_id": job.job_id,
                },
            )

        assert (
            case.dataset_case.scalar(
                "SELECT initialization_revision FROM return_dedup_staging_jobs "
                "WHERE id = :job_id",
                {"job_id": job.job_id},
            )
            == job.initialization_revision
        )
    finally:
        engine.dispose()
        _delete_jobs(case)
        _cleanup(case)


def test_late_source_confirmation_to_snapshot_catalog_and_analysis(
    publication_case: PublicationIntegrationCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = publication_case
    _cleanup_catalog(case)
    runtime = None
    monkeypatch.setattr(
        "tests.integration.test_catalog_export_finalization.REPORT_DATE", REPORT_DATE
    )

    def initialize_instead_of_seed(
        case: PublicationIntegrationCase, **_kwargs: object
    ) -> int | None:
        engine = case.dataset_case.runtime_engine()
        try:
            repo = MySqlReturnDedupRepository(engine)
            context = _context(case)
            before = _current_return_publication_digest(case)
            cmd = _command(repo, context)
            job = repo.create_staging(context, cmd, occurred_at=NOW)
            assert repo.initialization_preview(context)["existing_job_id"] == job.job_id
            assert (
                repo.create_staging(context, cmd, occurred_at=NOW).job_id == job.job_id
            )
            with pytest.raises(ReturnDedupStagingConflict):
                repo.create_staging(
                    context, replace(cmd, operation_token=uuid4()), occurred_at=NOW
                )
            completed = _finish(repo, job)
            assert completed.status == "ready"
            assert repo.create_staging(context, cmd, occurred_at=NOW).status == "ready"
            assert _current_return_publication_digest(case) == before
            assert _current_return_snapshot_digest(case) == before
            with pytest.raises(ReturnDedupPublicationRevisionConflict):
                repo.initialization_preview(context)
            return completed.result_snapshot_id
        finally:
            engine.dispose()

    monkeypatch.setattr(
        "tests.integration.test_catalog_export_finalization._seed_ready_dedup",
        initialize_instead_of_seed,
    )
    try:
        runtime, import_id, preview = _prepare_ready_import(case)
        result = CatalogService(runtime).approve_import(
            import_id=import_id,
            site_id=1,
            actor_user_id=case.owner_user_id,
            actor_roles=frozenset({"data_manager"}),
            operation_token=uuid4(),
            expected_workflow_revision=2,
            expected_catalog_publication_revision=0,
            projection_id=preview.projection_id,
            projection_digest=preview.projection_digest,
            reason="Synthetic initialization path",
            now=NOW + timedelta(minutes=5),
        )
        assert result.catalog_version_number == 1
        ledger = MySqlStyleAnalyticsRepository(runtime).ledger(
            site_id=1,
            from_date=REPORT_DATE,
            to_date=REPORT_DATE,
            return_basis="report_date",
            sort="units",
            direction="desc",
        )
        assert ledger.total_rows > 0
        assert (
            ledger.coverage.business.published_days
            == ledger.coverage.returns.published_days
            == 1
        )
        totals = ledger.reconciliation
        assert totals.source_totals.units == sum(
            v
            for v in (
                totals.mapped_totals.units,
                totals.unmatched_totals.units,
                totals.excluded_totals.units,
            )
            if v is not None
        )
        assert totals.source_totals.returns == sum(
            v
            for v in (
                totals.mapped_totals.returns,
                totals.unmatched_totals.returns,
                totals.excluded_totals.returns,
                totals.duplicate_totals.returns,
                totals.unresolved_duplicate_totals.returns,
            )
            if v is not None
        )
        with runtime.connect() as conn:
            readiness = read_readiness(conn, 1)
            assert readiness.prerequisites_present
            assert (
                readiness.published_business_reports
                == readiness.published_return_reports
                == 1
            )
            assert (
                conn.scalar(
                    sa.text(
                        """
                        SELECT COUNT(*) FROM catalog_audit_events WHERE
                        event_kind='catalog.return_snapshot_initialized'
                        """
                    )
                )
                == 1
            )
    finally:
        if runtime:
            runtime.dispose()
        _delete_jobs(case)
        _cleanup_catalog(case)
        _cleanup(case)


@pytest.mark.parametrize("drift", ["digest", "publication", "config", "empty"])
def test_initialization_guards_and_empty_reports(
    publication_case: PublicationIntegrationCase, drift: str
) -> None:
    case = publication_case
    _cleanup(case)
    engine = case.dataset_case.runtime_engine()
    try:
        _confirm_scope(case)
        context = _context(case)
        repo = MySqlReturnDedupRepository(engine)
        with pytest.raises(ReturnDedupNotFound):
            repo.initialization_preview(context)
        dataset, version = _materialize_return(case, date(2097, 1, 1))
        case.dataset_case.mark_published(dataset, version)
        cmd = _command(repo, context)
        if drift == "digest":
            with pytest.raises(ReturnDedupPublicationRevisionConflict):
                repo.create_staging(
                    context,
                    replace(cmd, expected_set_digest=b"x" * 32),
                    occurred_at=NOW,
                )
            with pytest.raises(ReturnDedupPermissionDenied):
                repo.initialization_preview(
                    replace(context, principal_roles=frozenset({"viewer"}))
                )
            return
        if drift == "empty":
            with case.dataset_case.migration_engine.begin() as conn:
                conn.execute(
                    sa.text(
                        """
                        UPDATE version_rows SET row_state='deleted' WHERE
                        version_id=:version
                        """
                    ),
                    {"version": version},
                )
        job = repo.create_staging(context, cmd, occurred_at=NOW)
        if drift == "publication":
            other, other_version = _materialize_return(case, date(2097, 1, 2))
            case.dataset_case.mark_published(other, other_version)
        if drift == "config":
            with case.dataset_case.migration_engine.begin() as conn:
                conn.execute(
                    sa.text(
                        """
                        UPDATE site_current_configs SET current_config_version_id=1
                        WHERE site_id=1
                        """
                    )
                )
        completed = _finish(repo, job)
        assert completed.status == ("ready" if drift == "empty" else "superseded")
        with engine.connect() as conn:
            assert (
                conn.scalar(
                    sa.text(
                        """
                        SELECT current_snapshot_id FROM return_dedup_publications
                        WHERE site_id=1
                        """
                    )
                )
                is not None
            ) == (drift == "empty")
    finally:
        engine.dispose()
        _cleanup(case)
