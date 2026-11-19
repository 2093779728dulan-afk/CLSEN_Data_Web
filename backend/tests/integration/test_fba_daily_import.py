from datetime import date, timedelta
from uuid import uuid4

import pytest
from app.parsers.repository import MySqlParseRepository
from app.parsers.workflow import ParseWorkflow
from app.production.fba_daily import load_reports
from app.production.fba_daily_import import publish_clean_daily
from app.workbench.import_orchestration import (
    MySqlWorkbenchImportRepository,
    OrchestrateImportCommand,
    WorkbenchImportOrchestrator,
)

from tests.integration.dataset_test_support import DatasetIntegrationCase
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import _cleanup_publication_records

pytestmark = pytest.mark.mysql


def test_clean_daily_uses_real_validation_review_publication_and_can_replay(
    dataset_case: DatasetIntegrationCase,
) -> None:
    case = dataset_case
    baseline = case.seed_baseline(
        report_date=date(2240, 1, 1) + timedelta(days=uuid4().int % 20000),
        variant="fba-auto-daily-" + uuid4().hex,
    )
    repository = MySqlWorkbenchImportRepository(case.migration_engine)
    result = WorkbenchImportOrchestrator(
        case.migration_engine,
        workflow=ParseWorkflow(
            repository=MySqlParseRepository(case.migration_engine), store=case.store
        ),
    ).run(
        OrchestrateImportCommand(
            batch_id=baseline.batch_id,
            sha256_hex=repository.sha256_hex(baseline.batch_id),
            actor_user_id=case.owner_user_id,
            operation_token=uuid4(),
            requested_report_date=baseline.report_date,
        )
    )
    assert result.status == "workspace_ready"
    assert result.dataset_id is not None and result.version_id is not None
    runtime = case.runtime_engine()
    try:
        key = uuid4()
        publish_clean_daily(
            runtime, result.dataset_id, result.version_id, case.owner_user_id, key
        )
        publish_clean_daily(
            runtime, result.dataset_id, result.version_id, case.owner_user_id, key
        )
        assert (
            case.scalar(
                "SELECT version_id FROM dataset_publications WHERE dataset_id=:id",
                {"id": result.dataset_id},
            )
            == result.version_id
        )
        with runtime.connect() as connection:
            assert (
                load_reports(
                    connection,
                    1,
                    {"report_source_scope_id": 999999, "cutoff_on": "2026-10-01"},
                )
                == []
            )
    finally:
        runtime.dispose()
        _cleanup_publication_records(case)
