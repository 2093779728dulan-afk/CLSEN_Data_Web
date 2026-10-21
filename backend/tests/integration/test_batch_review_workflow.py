from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.batch_review.repository import MySqlBatchReviewRepository
from app.batch_review.service import (
    CONFIRMATION_STATEMENT_VERSION,
    BatchReviewService,
)
from app.batch_review.types import (
    BatchReviewItemStatus,
    BatchReviewRunStatus,
    ChangeBatchReviewRunStateCommand,
    ConfirmBatchReviewCommand,
    CreatePreflightCommand,
)

from tests.integration.dataset_test_support import (
    DatasetIntegrationCase,
)
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers shared fixture
)

pytestmark = pytest.mark.mysql


def test_preflight_confirm_pause_resume_is_durable_and_never_publishes(
    dataset_case: DatasetIntegrationCase,
) -> None:
    start = date(2098, 3, 1)
    baselines = tuple(
        dataset_case.seed_baseline(
            report_date=start + timedelta(days=index),
            report_type=("business_report" if index % 2 == 0 else "return_report"),
            variant=f"batch-workflow-{index}",
            inspect_before_parse=True,
        )
        for index in range(4)
    )
    with dataset_case.migration_engine.connect() as connection:
        site_value = connection.scalar(
            sa.text("SELECT site_id FROM import_batches WHERE id = :batch_id"),
            {"batch_id": baselines[0].batch_id},
        )
        publications_before = int(
            connection.scalar(sa.text("SELECT COUNT(*) FROM dataset_publications")) or 0
        )
    assert site_value is not None
    site_id = int(site_value)
    runtime_engine = dataset_case.runtime_engine()
    run_id: int | None = None
    try:
        service = BatchReviewService(MySqlBatchReviewRepository(runtime_engine))
        preview = service.create_preflight(
            CreatePreflightCommand(
                site_id=site_id,
                actor_user_id=dataset_case.owner_user_id,
                actor_roles=frozenset({"data_manager"}),
                batch_ids=tuple(baseline.batch_id for baseline in baselines),
                operation_token=uuid4(),
            )
        )
        run_id = preview.id
        selected = tuple(
            item.id
            for item in preview.items
            if item.status is BatchReviewItemStatus.ELIGIBLE
        )
        assert len(selected) == 4, tuple(
            (
                item.batch_id,
                item.detected_report_date,
                item.detected_report_type,
                item.detected_encoding,
                item.recognition_status,
                item.status.value,
                item.reason_code,
            )
            for item in preview.items
        )

        running = service.confirm(
            ConfirmBatchReviewCommand(
                run_id=preview.id,
                site_id=site_id,
                actor_user_id=dataset_case.owner_user_id,
                expected_revision=preview.revision,
                selected_item_ids=selected,
                confirmation_accepted=True,
                confirmation_statement_version=CONFIRMATION_STATEMENT_VERSION,
                operation_token=uuid4(),
            )
        )
        assert running.status is BatchReviewRunStatus.RUNNING
        assert all(
            item.status is BatchReviewItemStatus.QUEUED for item in running.items
        )
        paused = service.pause(
            ChangeBatchReviewRunStateCommand(
                run_id=running.id,
                site_id=site_id,
                actor_user_id=dataset_case.owner_user_id,
                expected_revision=running.revision,
                action="pause",
                operation_token=uuid4(),
            )
        )
        assert paused.status is BatchReviewRunStatus.PAUSED
        resumed = service.resume(
            ChangeBatchReviewRunStateCommand(
                run_id=paused.id,
                site_id=site_id,
                actor_user_id=dataset_case.owner_user_id,
                expected_revision=paused.revision,
                action="resume",
                operation_token=uuid4(),
            )
        )
        assert resumed.status is BatchReviewRunStatus.RUNNING
        assert service.get_run(run_id, site_id).revision == resumed.revision

        with dataset_case.migration_engine.connect() as connection:
            publications_after = int(
                connection.scalar(sa.text("SELECT COUNT(*) FROM dataset_publications"))
                or 0
            )
        assert publications_after == publications_before
    finally:
        runtime_engine.dispose()
        if run_id is not None:
            with dataset_case.migration_engine.begin() as connection:
                connection.execute(
                    sa.text("DELETE FROM batch_review_commands WHERE run_id = :run_id"),
                    {"run_id": run_id},
                )
                connection.execute(
                    sa.text("DELETE FROM batch_review_runs WHERE id = :run_id"),
                    {"run_id": run_id},
                )
