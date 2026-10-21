from __future__ import annotations

import pytest
from app.catalog.workflow import (
    CatalogStateTransitionError,
    CatalogWorkflowState,
    WorkflowActor,
    permissions_for,
    transition_target,
)


@pytest.mark.parametrize(
    ("status", "command", "target"),
    [
        ("uploaded", "claim_parse", "parsing"),
        ("parsing", "parse_succeeded_clean", "validated"),
        ("parsing", "parse_succeeded_with_issues", "needs_attention"),
        ("parsing", "parse_failed", "parse_failed"),
        ("parse_failed", "resume", "parsing"),
        ("needs_attention", "decisions", "needs_attention"),
        ("validated", "decisions", "needs_attention"),
        ("ready_for_approval", "decisions", "needs_attention"),
        ("needs_attention", "validate_passed", "validated"),
        ("needs_attention", "validate_failed", "needs_attention"),
        ("validated", "validate_passed", "validated"),
        ("validated", "submit", "ready_for_approval"),
        ("ready_for_approval", "approval_preview", "ready_for_approval"),
        ("ready_for_approval", "approve", "approved"),
        ("ready_for_approval", "reject", "rejected"),
        ("uploaded", "withdraw", "withdrawn"),
        ("parse_failed", "withdraw", "withdrawn"),
        ("needs_attention", "withdraw", "withdrawn"),
        ("validated", "withdraw", "withdrawn"),
        ("ready_for_approval", "withdraw", "withdrawn"),
        ("rejected", "rebase", "superseded"),
    ],
)
def test_complete_legal_transition_table(
    status: str, command: str, target: str
) -> None:
    state = CatalogWorkflowState(
        status=status,
        source_kind="xlsx",
        owner_user_id=7,
        submitted_by_user_id=7 if status == "ready_for_approval" else None,
        recoverable=status == "parse_failed",
        active_parse_lease=status == "parsing",
        risk="normal",
    )
    actor = WorkflowActor(7, frozenset({"data_manager"}))
    if command in {
        "claim_parse",
        "parse_succeeded_clean",
        "parse_succeeded_with_issues",
        "parse_failed",
    }:
        actor = WorkflowActor(0, frozenset({"system"}))
    if command == "reject":
        actor = WorkflowActor(8, frozenset({"admin"}))

    assert transition_target(state, command, actor, reason="valid reason") == target


@pytest.mark.parametrize("terminal", ["approved", "withdrawn", "superseded"])
def test_terminal_states_reject_every_command(terminal: str) -> None:
    state = CatalogWorkflowState(terminal, "online", 7)
    actor = WorkflowActor(7, frozenset({"admin"}))
    for command in (
        "resume",
        "decisions",
        "validate_passed",
        "submit",
        "approval_preview",
        "approve",
        "reject",
        "withdraw",
        "rebase",
    ):
        with pytest.raises(CatalogStateTransitionError):
            transition_target(state, command, actor, reason="valid reason")


def test_role_owner_submitter_risk_and_active_lease_are_enforced() -> None:
    viewer = WorkflowActor(7, frozenset({"viewer"}))
    manager = WorkflowActor(7, frozenset({"data_manager"}))
    other_manager = WorkflowActor(8, frozenset({"data_manager"}))
    admin = WorkflowActor(8, frozenset({"admin"}))

    failed = CatalogWorkflowState("parse_failed", "xlsx", 7, recoverable=True)
    with pytest.raises(CatalogStateTransitionError):
        transition_target(failed, "resume", viewer)
    with pytest.raises(CatalogStateTransitionError):
        transition_target(failed, "resume", other_manager)
    assert transition_target(failed, "resume", manager) == "parsing"
    assert transition_target(failed, "resume", admin) == "parsing"

    high = CatalogWorkflowState(
        "ready_for_approval", "online", 7, submitted_by_user_id=7, risk="high"
    )
    with pytest.raises(CatalogStateTransitionError):
        transition_target(high, "approve", manager)
    assert (
        transition_target(high, "approve", admin, reason="valid reason") == "approved"
    )

    parsing = CatalogWorkflowState("parsing", "xlsx", 7, active_parse_lease=True)
    with pytest.raises(CatalogStateTransitionError):
        transition_target(parsing, "withdraw", admin, reason="valid reason")


def test_permissions_use_current_roles_and_never_historical_role() -> None:
    state = CatalogWorkflowState(
        "ready_for_approval",
        "xlsx",
        7,
        submitted_by_user_id=7,
        risk="normal",
    )
    manager = permissions_for(state, WorkflowActor(7, frozenset({"data_manager"})))
    assert manager.can_preview and manager.can_approve_normal
    assert not manager.can_approve_high_risk
    assert manager.can_download_original

    downgraded = permissions_for(state, WorkflowActor(7, frozenset({"viewer"})))
    assert not any(downgraded.as_tuple())
