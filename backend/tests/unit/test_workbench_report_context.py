from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from app.workbench.import_orchestration import (
    MySqlWorkbenchImportRepository,
    OrchestrateImportCommand,
    WorkbenchImportOrchestrator,
)


def test_report_type_conflict_stops_before_parsing_or_materializing() -> None:
    repository = Mock(spec=MySqlWorkbenchImportRepository)
    repository.register_or_recover.return_value = None
    repository.batch_state.return_value = {}
    repository.finish.side_effect = lambda command, result: result
    workflow = Mock()
    workflow.inspect.return_value = SimpleNamespace(
        status="suggested",
        report_type="business_report",
        detected_report_date=date(2026, 8, 13),
        encoding="utf-8-sig",
        issues=(),
    )
    orchestrator = WorkbenchImportOrchestrator(
        Mock(), workflow=workflow, repository=repository
    )
    result = orchestrator.run(
        OrchestrateImportCommand(
            batch_id=1,
            sha256_hex="a" * 64,
            actor_user_id=1,
            operation_token=uuid4(),
            requested_report_date=date(2026, 8, 13),
            requested_report_type="return_report",
        )
    )
    assert result.status == "confirmation_required"
    assert result.report_type == "business_report"
    assert result.issue_codes == ("selected_type_conflict",)
    repository.target_has_workspace.assert_not_called()
    workflow.confirm_and_parse.assert_not_called()


@pytest.mark.parametrize("selected", [None, "business_report"])
def test_matching_or_legacy_type_does_not_add_a_type_conflict(
    selected: str | None,
) -> None:
    from typing import cast

    from app.imports.types import ReportType

    repository = Mock(spec=MySqlWorkbenchImportRepository)
    repository.register_or_recover.return_value = None
    repository.batch_state.return_value = {"site_id": 1}
    repository.target_has_workspace.return_value = True
    repository.finish.side_effect = lambda command, result: result
    workflow = Mock()
    workflow.inspect.return_value = SimpleNamespace(
        status="suggested",
        report_type="business_report",
        detected_report_date=date(2026, 8, 13),
        encoding="utf-8-sig",
        issues=(),
    )
    result = WorkbenchImportOrchestrator(
        Mock(), workflow=workflow, repository=repository
    ).run(
        OrchestrateImportCommand(
            batch_id=1,
            sha256_hex="a" * 64,
            actor_user_id=1,
            operation_token=uuid4(),
            requested_report_date=date(2026, 8, 13),
            requested_report_type=cast(ReportType | None, selected),
        )
    )
    assert result.status == "conflict_required"
    assert "selected_type_conflict" not in result.issue_codes


def test_report_type_is_part_of_operation_identity() -> None:
    token = uuid4()
    business = OrchestrateImportCommand(
        batch_id=1,
        sha256_hex="a" * 64,
        actor_user_id=1,
        operation_token=token,
        requested_report_type="business_report",
    )
    returns = OrchestrateImportCommand(
        batch_id=1,
        sha256_hex="a" * 64,
        actor_user_id=1,
        operation_token=token,
        requested_report_type="return_report",
    )
    assert business.operation_digest != returns.operation_digest
