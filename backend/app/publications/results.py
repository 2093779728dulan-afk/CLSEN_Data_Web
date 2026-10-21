"""Immutable result snapshots and publication event-shape validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from ._common import (
    nonnegative,
    normalise_timestamp,
    optional_positive,
    positive,
    require_uuid,
)

type PublicationEventType = Literal[
    "published",
    "replaced",
    "rolled_back",
    "moved_out",
    "moved_in",
    "move_reversed",
]
type PublicationCommandType = Literal["publish", "rollback", "move", "reverse_move"]
type DraftResultKind = Literal[
    "revision_created",
    "published_move_revision_created",
    "published_move_revision_cancelled",
]
type DraftResultStatus = Literal["draft", "cancelled"]

_EVENT_TYPES = frozenset(
    {
        "published",
        "replaced",
        "rolled_back",
        "moved_out",
        "moved_in",
        "move_reversed",
    }
)
_COMMAND_TYPES = frozenset({"publish", "rollback", "move", "reverse_move"})
_DRAFT_RESULT_KINDS = frozenset(
    {
        "revision_created",
        "published_move_revision_created",
        "published_move_revision_cancelled",
    }
)


@dataclass(frozen=True, slots=True)
class PublicationTransition:
    event_id: int
    sequence_number: int
    event_type: PublicationEventType
    dataset_id: int
    peer_dataset_id: int | None
    previous_version_id: int | None
    next_version_id: int | None

    def __post_init__(self) -> None:
        positive(self.event_id, "event_id")
        positive(self.sequence_number, "sequence_number")
        if self.event_type not in _EVENT_TYPES:
            raise ValueError("publication event type is not supported")
        positive(self.dataset_id, "dataset_id")
        optional_positive(self.peer_dataset_id, "peer_dataset_id")
        optional_positive(self.previous_version_id, "previous_version_id")
        optional_positive(self.next_version_id, "next_version_id")
        if self.peer_dataset_id == self.dataset_id:
            raise ValueError("publication event peer dataset must differ")
        if self.previous_version_id is None and self.next_version_id is None:
            raise ValueError("publication event must contain a version")


def _shape_error() -> ValueError:
    return ValueError("publication event shape does not match command")


def validate_publication_event_shape(
    command_type: PublicationCommandType,
    transitions: tuple[PublicationTransition, ...],
) -> None:
    if command_type not in _COMMAND_TYPES:
        raise ValueError("publication command type is not supported")
    if tuple(item.sequence_number for item in transitions) != tuple(
        range(1, len(transitions) + 1)
    ):
        raise _shape_error()
    if len({item.event_id for item in transitions}) != len(transitions):
        raise _shape_error()

    if command_type == "publish":
        if len(transitions) != 1:
            raise _shape_error()
        event = transitions[0]
        first_publication = (
            event.event_type == "published"
            and event.previous_version_id is None
            and event.next_version_id is not None
            and event.peer_dataset_id is None
        )
        replacement = (
            event.event_type == "replaced"
            and event.previous_version_id is not None
            and event.next_version_id is not None
            and event.previous_version_id != event.next_version_id
            and event.peer_dataset_id is None
        )
        if not first_publication and not replacement:
            raise _shape_error()
        return

    if command_type == "rollback":
        if len(transitions) != 1:
            raise _shape_error()
        event = transitions[0]
        if not (
            event.event_type == "rolled_back"
            and event.previous_version_id is not None
            and event.next_version_id is not None
            and event.previous_version_id != event.next_version_id
            and event.peer_dataset_id is None
        ):
            raise _shape_error()
        return

    if len(transitions) != 2:
        raise _shape_error()
    source, target = transitions
    reciprocal = (
        source.dataset_id != target.dataset_id
        and source.peer_dataset_id == target.dataset_id
        and target.peer_dataset_id == source.dataset_id
    )
    if not reciprocal:
        raise _shape_error()

    if command_type == "move":
        if not (
            source.event_type == "moved_out"
            and source.previous_version_id is not None
            and source.next_version_id is None
            and target.event_type == "moved_in"
            and target.next_version_id is not None
            and (
                target.previous_version_id is None
                or target.previous_version_id != target.next_version_id
            )
        ):
            raise _shape_error()
        return

    if not (
        source.event_type == "move_reversed"
        and source.previous_version_id is None
        and source.next_version_id is not None
        and target.event_type == "move_reversed"
        and target.previous_version_id is not None
        and (
            target.next_version_id is None
            or target.next_version_id != target.previous_version_id
        )
    ):
        raise _shape_error()


@dataclass(frozen=True, slots=True)
class PublicationCommandResult:
    operation_token: UUID
    command_id: int
    command_type: PublicationCommandType
    transitions: tuple[PublicationTransition, ...]
    completed_at: datetime

    def __post_init__(self) -> None:
        require_uuid(self.operation_token)
        positive(self.command_id, "command_id")
        frozen_transitions = tuple(self.transitions)
        validate_publication_event_shape(self.command_type, frozen_transitions)
        object.__setattr__(self, "transitions", frozen_transitions)
        object.__setattr__(
            self,
            "completed_at",
            normalise_timestamp(self.completed_at, "completed_at"),
        )


@dataclass(frozen=True, slots=True)
class DraftCommandResult:
    operation_token: UUID
    result_kind: DraftResultKind
    dataset_id: int
    version_id: int
    version_no: int
    status: DraftResultStatus
    data_revision: int
    review_revision: int
    source_dataset_id: int | None
    source_version_id: int | None
    completed_at: datetime

    def __post_init__(self) -> None:
        require_uuid(self.operation_token)
        if self.result_kind not in _DRAFT_RESULT_KINDS:
            raise ValueError("draft command result kind is not supported")
        positive(self.dataset_id, "dataset_id")
        positive(self.version_id, "version_id")
        positive(self.version_no, "version_no")
        nonnegative(self.data_revision, "data_revision")
        nonnegative(self.review_revision, "review_revision")
        if (self.source_dataset_id is None) != (self.source_version_id is None):
            raise ValueError(
                "source dataset and version must be both present or absent"
            )
        optional_positive(self.source_dataset_id, "source_dataset_id")
        optional_positive(self.source_version_id, "source_version_id")
        expected_status = (
            "cancelled"
            if self.result_kind == "published_move_revision_cancelled"
            else "draft"
        )
        if self.status != expected_status:
            raise ValueError("draft command result status does not match its kind")
        object.__setattr__(
            self,
            "completed_at",
            normalise_timestamp(self.completed_at, "completed_at"),
        )
