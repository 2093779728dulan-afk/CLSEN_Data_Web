"""Immutable commands for optimistic workbench cell mutations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.review.types import DraftHeadExpectation
from app.validation.codec import encode_field_value
from app.validation.fields import FieldValue


class WorkbenchMutationError(RuntimeError):
    """Base class for expected workbench mutation failures."""


class WorkbenchOperationConflict(WorkbenchMutationError):
    """An idempotency key is already bound to another command."""


class WorkbenchCellConflict(WorkbenchMutationError):
    """The active head or selected cell changed before the write."""


class WorkbenchColumnNotFound(WorkbenchMutationError):
    """The selected visible column does not belong to the version."""


class WorkbenchCellValueInvalid(WorkbenchMutationError):
    """The supplied cell value cannot be stored by its column contract."""


class NothingToUndo(WorkbenchMutationError):
    """The actor has no still-current cell change in this version."""


def _canonical_digest(payload: object) -> bytes:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).digest()


@dataclass(frozen=True, slots=True)
class SetWorkbenchCellCommand:
    head: DraftHeadExpectation
    row_id: int
    column_id: UUID
    value: FieldValue
    expected_cell_revision: int
    actor_user_id: int
    operation_token: UUID
    reason: str

    operation_kind: Literal["set_cell"] = "set_cell"

    def __post_init__(self) -> None:
        if not isinstance(self.head, DraftHeadExpectation):
            raise ValueError("head is required")
        if (
            not isinstance(self.row_id, int)
            or isinstance(self.row_id, bool)
            or self.row_id < 1
        ):
            raise ValueError("row_id must be positive")
        if not isinstance(self.column_id, UUID):
            raise ValueError("column_id must be a UUID")
        encode_field_value(self.value)
        if (
            not isinstance(self.expected_cell_revision, int)
            or isinstance(self.expected_cell_revision, bool)
            or self.expected_cell_revision < 0
        ):
            raise ValueError("expected_cell_revision must not be negative")
        if (
            not isinstance(self.actor_user_id, int)
            or isinstance(self.actor_user_id, bool)
            or self.actor_user_id < 1
        ):
            raise ValueError("actor_user_id must be positive")
        if not isinstance(self.operation_token, UUID):
            raise ValueError("operation_token must be a UUID")
        reason = self.reason.strip()
        if not reason:
            raise ValueError("reason must not be blank")
        object.__setattr__(self, "reason", reason)

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": "set_workbench_cell",
                "head": self.head.as_payload(),
                "row_id": self.row_id,
                "column_id": str(self.column_id),
                "value": encode_field_value(self.value),
                "expected_cell_revision": self.expected_cell_revision,
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class UndoWorkbenchCellCommand:
    head: DraftHeadExpectation
    actor_user_id: int
    operation_token: UUID
    reason: str

    operation_kind: Literal["undo_cell"] = "undo_cell"

    def __post_init__(self) -> None:
        if not isinstance(self.head, DraftHeadExpectation):
            raise ValueError("head is required")
        if (
            not isinstance(self.actor_user_id, int)
            or isinstance(self.actor_user_id, bool)
            or self.actor_user_id < 1
        ):
            raise ValueError("actor_user_id must be positive")
        if not isinstance(self.operation_token, UUID):
            raise ValueError("operation_token must be a UUID")
        reason = self.reason.strip()
        if not reason:
            raise ValueError("reason must not be blank")
        object.__setattr__(self, "reason", reason)

    @property
    def operation_digest(self) -> bytes:
        return _canonical_digest(
            {
                "command": self.operation_kind,
                "head": self.head.as_payload(),
                "actor_user_id": self.actor_user_id,
                "reason": self.reason,
            }
        )
