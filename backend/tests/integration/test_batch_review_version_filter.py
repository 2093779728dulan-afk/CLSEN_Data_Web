from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa
from app.api.versions import list_versions
from app.auth.sessions import Principal
from sqlalchemy.orm import Session

from tests.integration.dataset_test_support import (
    DatasetIntegrationCase,
)
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers shared fixture
)

pytestmark = pytest.mark.mysql


def _manager(user_id: int) -> Principal:
    return Principal(
        user_id=user_id,
        username="batch-filter-manager",
        display_name="Batch Filter Manager",
        roles=frozenset({"data_manager"}),
        session_id=1,
        csrf_token_hash=b"csrf",
    )


def test_batch_review_filter_reads_only_linked_ready_version(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = date(2098, 2, 3)
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="batch-filter",
    )

    with dataset_case.migration_engine.connect() as connection:
        transaction = connection.begin()
        try:
            publications_before = int(
                connection.scalar(sa.text("SELECT COUNT(*) FROM dataset_publications"))
                or 0
            )
            site_value = connection.scalar(
                sa.text("SELECT site_id FROM import_batches WHERE id = :batch_id"),
                {"batch_id": baseline.batch_id},
            )
            assert site_value is not None
            site_id = int(site_value)
            dataset_result = connection.execute(
                sa.text(
                    """
                    INSERT INTO daily_datasets (site_id, report_date, report_type)
                    VALUES (:site_id, :report_date, 'business_report')
                    """
                ),
                {"site_id": site_id, "report_date": report_date},
            )
            assert dataset_result.lastrowid is not None
            dataset_id = int(dataset_result.lastrowid)
            version_result = connection.execute(
                sa.text(
                    """
                    INSERT INTO dataset_versions (
                        dataset_id, report_type, version_no, status,
                        ruleset_version, created_by
                    ) VALUES (
                        :dataset_id, 'business_report', 1, 'ready_for_publish',
                        'business_report_v1', :created_by
                    )
                    """
                ),
                {"dataset_id": dataset_id, "created_by": dataset_case.owner_user_id},
            )
            assert version_result.lastrowid is not None
            version_id = int(version_result.lastrowid)
            run_result = connection.execute(
                sa.text(
                    """
                    INSERT INTO batch_review_runs (
                        site_id, created_by_user_id, status, revision
                    ) VALUES (:site_id, :created_by, 'completed', 1)
                    """
                ),
                {"site_id": site_id, "created_by": dataset_case.owner_user_id},
            )
            assert run_result.lastrowid is not None
            run_id = int(run_result.lastrowid)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO batch_review_items (
                        run_id, site_id, batch_id, filename,
                        detected_report_date, detected_report_type,
                        detected_encoding, recognition_status,
                        target_report_date, target_report_type,
                        selected, status, dataset_id, version_id
                    ) VALUES (
                        :run_id, :site_id, :batch_id, 'synthetic.csv',
                        :report_date, 'business_report', 'utf-8-sig', 'recognized',
                        :report_date, 'business_report',
                        TRUE, 'ready_for_publish', :dataset_id, :version_id
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "site_id": site_id,
                    "batch_id": baseline.batch_id,
                    "report_date": report_date,
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                },
            )

            session = Session(bind=connection)
            try:
                result = list_versions(
                    principal=_manager(dataset_case.owner_user_id),
                    database_session=session,
                    batch_review_run_id=run_id,
                )
            finally:
                session.close()

            assert [version.version_id for version in result] == [version_id]
            assert result[0].status == "ready_for_publish"
            assert (
                int(
                    connection.scalar(
                        sa.text("SELECT COUNT(*) FROM dataset_publications")
                    )
                    or 0
                )
                == publications_before
            )
        finally:
            transaction.rollback()
