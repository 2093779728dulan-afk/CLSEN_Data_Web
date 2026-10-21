from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from app.parsers.repository import MySqlParseRepository
from app.parsers.workflow import ParseWorkflow
from app.workbench.import_orchestration import (
    MySqlWorkbenchImportRepository,
    OrchestrateImportCommand,
    WorkbenchImportOrchestrator,
    WorkbenchImportResult,
)

from tests.integration.dataset_test_support import DatasetIntegrationCase
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers the shared fixture
)

pytestmark = pytest.mark.mysql


def _isolated_date() -> date:
    return date(2240, 1, 1) + timedelta(days=uuid4().int % 20000)


def _orchestrator(case: DatasetIntegrationCase) -> WorkbenchImportOrchestrator:
    return WorkbenchImportOrchestrator(
        case.migration_engine,
        workflow=ParseWorkflow(
            repository=MySqlParseRepository(case.migration_engine),
            store=case.store,
        ),
    )


def test_runtime_account_can_register_and_recover_import_operation(
    dataset_case: DatasetIntegrationCase,
) -> None:
    baseline = dataset_case.seed_baseline(
        report_date=_isolated_date(),
        variant="runtime-orchestration-token",
    )
    runtime_engine = dataset_case.runtime_engine()
    try:
        repository = MySqlWorkbenchImportRepository(runtime_engine)
        command = OrchestrateImportCommand(
            batch_id=baseline.batch_id,
            sha256_hex=repository.sha256_hex(baseline.batch_id),
            actor_user_id=dataset_case.owner_user_id,
            operation_token=uuid4(),
            requested_report_date=baseline.report_date,
        )
        result = WorkbenchImportResult(
            batch_id=baseline.batch_id,
            status="confirmation_required",
            stage="recognition",
            report_date=baseline.report_date,
            report_type="business_report",
            encoding="utf-8-sig",
        )

        assert repository.register_or_recover(command) is None
        assert repository.finish(command, result) == result
        assert repository.register_or_recover(command) == result
    finally:
        runtime_engine.dispose()


def test_certain_import_is_materialized_once_and_retry_recovers(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="orchestration-ready",
    )
    repository = MySqlWorkbenchImportRepository(dataset_case.migration_engine)
    command = OrchestrateImportCommand(
        batch_id=baseline.batch_id,
        sha256_hex=repository.sha256_hex(baseline.batch_id),
        actor_user_id=dataset_case.owner_user_id,
        operation_token=uuid4(),
        requested_report_date=report_date,
    )

    first = _orchestrator(dataset_case).run(command)
    recovered = _orchestrator(dataset_case).run(command)

    assert recovered == first
    assert first.status == "workspace_ready"
    assert first.report_date == report_date
    assert first.report_type == "business_report"
    assert first.version_id is not None
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM dataset_versions WHERE dataset_id = :dataset_id",
            {"dataset_id": first.dataset_id},
        )
        == 1
    )
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM workbench_operation_results "
            "WHERE operation_token = :operation_token",
            {"operation_token": command.operation_token.bytes},
        )
        == 1
    )


def test_existing_target_stops_before_materializing_second_import(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    first_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="orchestration-first",
    )
    repository = MySqlWorkbenchImportRepository(dataset_case.migration_engine)
    first = _orchestrator(dataset_case).run(
        OrchestrateImportCommand(
            batch_id=first_baseline.batch_id,
            sha256_hex=repository.sha256_hex(first_baseline.batch_id),
            actor_user_id=dataset_case.owner_user_id,
            operation_token=uuid4(),
            requested_report_date=report_date,
        )
    )
    assert first.status == "workspace_ready"

    second_baseline = dataset_case.seed_baseline(
        report_date=report_date,
        variant="orchestration-second",
    )
    conflict = _orchestrator(dataset_case).run(
        OrchestrateImportCommand(
            batch_id=second_baseline.batch_id,
            sha256_hex=repository.sha256_hex(second_baseline.batch_id),
            actor_user_id=dataset_case.owner_user_id,
            operation_token=uuid4(),
            requested_report_date=report_date,
        )
    )

    assert conflict.status == "conflict_required"
    assert conflict.stage == "target_conflict"
    assert conflict.workspace_url is not None
    assert (
        dataset_case.scalar(
            "SELECT COUNT(*) FROM version_input_batches WHERE batch_id = :batch_id",
            {"batch_id": second_baseline.batch_id},
        )
        == 0
    )
