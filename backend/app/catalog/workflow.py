"""Pure catalog-import state and current-role authorization rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

_STATUSES: Final = frozenset(
    {
        "uploaded",
        "parsing",
        "parse_failed",
        "needs_attention",
        "validated",
        "ready_for_approval",
        "approved",
        "rejected",
        "withdrawn",
        "superseded",
    }
)
_TERMINAL: Final = frozenset({"approved", "withdrawn", "superseded"})


class CatalogStateTransitionError(ValueError):
    code = "catalog_state_transition_invalid"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class WorkflowActor:
    user_id: int
    roles: frozenset[str]

    @property
    def is_system(self) -> bool:
        return "system" in self.roles

    @property
    def is_manager(self) -> bool:
        return "data_manager" in self.roles

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


@dataclass(frozen=True, slots=True)
class CatalogWorkflowState:
    status: str
    source_kind: str
    owner_user_id: int
    submitted_by_user_id: int | None = None
    recoverable: bool = False
    active_parse_lease: bool = False
    risk: str = "normal"

    def __post_init__(self) -> None:
        if self.status not in _STATUSES or self.source_kind not in {"xlsx", "online"}:
            raise ValueError("invalid catalog workflow state")
        if self.risk not in {"normal", "high"}:
            raise ValueError("invalid catalog workflow risk")


@dataclass(frozen=True, slots=True)
class CatalogImportPermissions:
    can_view: bool
    can_edit: bool
    can_validate: bool
    can_submit: bool
    can_preview: bool
    can_approve_normal: bool
    can_approve_high_risk: bool
    can_reject: bool
    can_withdraw: bool
    can_rebase: bool
    can_download_original: bool

    def as_tuple(self) -> tuple[bool, ...]:
        return (
            self.can_view,
            self.can_edit,
            self.can_validate,
            self.can_submit,
            self.can_preview,
            self.can_approve_normal,
            self.can_approve_high_risk,
            self.can_reject,
            self.can_withdraw,
            self.can_rebase,
            self.can_download_original,
        )


def _reason_valid(reason: str | None) -> bool:
    return reason is not None and len(reason.strip()) >= 10


def transition_target(
    state: CatalogWorkflowState,
    command: str,
    actor: WorkflowActor,
    *,
    reason: str | None = None,
) -> str:
    if state.status in _TERMINAL:
        raise CatalogStateTransitionError()
    manager_or_admin = actor.is_manager or actor.is_admin
    owner_manager = actor.is_manager and actor.user_id == state.owner_user_id
    submitted_manager = actor.is_manager and actor.user_id == state.submitted_by_user_id

    if command == "claim_parse":
        if (
            state.status == "uploaded"
            and actor.is_system
            and not state.active_parse_lease
        ):
            return "parsing"
    elif command in {
        "parse_succeeded_clean",
        "parse_succeeded_with_issues",
        "parse_failed",
    }:
        if state.status == "parsing" and actor.is_system and state.active_parse_lease:
            return {
                "parse_succeeded_clean": "validated",
                "parse_succeeded_with_issues": "needs_attention",
                "parse_failed": "parse_failed",
            }[command]
    elif command == "resume":
        if (
            state.status == "parse_failed"
            and state.source_kind == "xlsx"
            and state.recoverable
            and (owner_manager or actor.is_admin)
        ):
            return "parsing"
    elif command == "decisions":
        if (
            state.status in {"needs_attention", "validated", "ready_for_approval"}
            and manager_or_admin
        ):
            return "needs_attention"
    elif command in {"validate_passed", "validate_failed"}:
        if state.status in {"needs_attention", "validated"} and manager_or_admin:
            return "validated" if command == "validate_passed" else "needs_attention"
    elif command == "submit":
        if state.status == "validated" and manager_or_admin:
            return "ready_for_approval"
    elif command == "approval_preview":
        if state.status == "ready_for_approval" and (
            submitted_manager or actor.is_admin
        ):
            return state.status
    elif command == "approve":
        allowed = (
            actor.is_admin
            if state.risk == "high"
            else submitted_manager or actor.is_admin
        )
        if (
            state.status == "ready_for_approval"
            and allowed
            and (state.risk != "high" or (actor.is_admin and _reason_valid(reason)))
        ):
            return "approved"
    elif command == "reject":
        if (
            state.status == "ready_for_approval"
            and actor.is_admin
            and _reason_valid(reason)
        ):
            return "rejected"
    elif command == "withdraw":
        if (
            state.status
            in {
                "uploaded",
                "parse_failed",
                "needs_attention",
                "validated",
                "ready_for_approval",
            }
            and not state.active_parse_lease
            and (owner_manager or (actor.is_admin and _reason_valid(reason)))
        ):
            return "withdrawn"
    elif command == "rebase" and (
        state.status
        in {"needs_attention", "validated", "ready_for_approval", "rejected"}
        and (owner_manager or actor.is_admin)
    ):
        return "superseded"
    raise CatalogStateTransitionError()


def permissions_for(
    state: CatalogWorkflowState,
    actor: WorkflowActor,
) -> CatalogImportPermissions:
    if not (actor.is_manager or actor.is_admin):
        return CatalogImportPermissions(
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )
    editable = state.status in {"needs_attention", "validated", "ready_for_approval"}
    can_validate = state.status in {"needs_attention", "validated"}
    submitted = state.status == "ready_for_approval" and (
        actor.is_admin
        or (actor.is_manager and actor.user_id == state.submitted_by_user_id)
    )
    withdraw = (
        state.status
        in {
            "uploaded",
            "parse_failed",
            "needs_attention",
            "validated",
            "ready_for_approval",
        }
        and not state.active_parse_lease
        and (actor.is_admin or actor.user_id == state.owner_user_id)
    )
    rebase = state.status in {
        "needs_attention",
        "validated",
        "ready_for_approval",
        "rejected",
    } and (actor.is_admin or actor.user_id == state.owner_user_id)
    return CatalogImportPermissions(
        can_view=True,
        can_edit=editable,
        can_validate=can_validate,
        can_submit=state.status == "validated",
        can_preview=submitted,
        can_approve_normal=submitted,
        can_approve_high_risk=state.status == "ready_for_approval" and actor.is_admin,
        can_reject=state.status == "ready_for_approval" and actor.is_admin,
        can_withdraw=withdraw,
        can_rebase=rebase,
        can_download_original=state.source_kind == "xlsx",
    )


__all__ = (
    "CatalogImportPermissions",
    "CatalogStateTransitionError",
    "CatalogWorkflowState",
    "WorkflowActor",
    "permissions_for",
    "transition_target",
)
