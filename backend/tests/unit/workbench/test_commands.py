from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.review.types import DraftHeadExpectation
from app.workbench.commands import SetWorkbenchCellCommand


def _command() -> SetWorkbenchCellCommand:
    return SetWorkbenchCellCommand(
        head=DraftHeadExpectation(
            dataset_id=10,
            version_id=20,
            status="draft",
            data_revision=3,
            review_revision=4,
            pointed_at=datetime(2026, 8, 14, 8, 0, tzinfo=UTC),
        ),
        row_id=30,
        column_id=UUID("70e31e94-aa21-5d1f-a406-7567d0d969dc"),
        value="before",
        expected_cell_revision=2,
        actor_user_id=40,
        operation_token=uuid4(),
        reason="Correct the source value",
    )


def test_cell_command_digest_binds_value_reason_head_and_cell_revision() -> None:
    command = _command()
    changed_commands = (
        replace(command, value="after"),
        replace(command, reason="A different reason"),
        replace(command, expected_cell_revision=3),
        replace(
            command,
            head=DraftHeadExpectation(
                dataset_id=10,
                version_id=20,
                status="draft",
                data_revision=4,
                review_revision=4,
                pointed_at=datetime(2026, 8, 14, 8, 0, tzinfo=UTC),
            ),
        ),
    )

    assert all(
        changed.operation_digest != command.operation_digest
        for changed in changed_commands
    )


def test_transport_operation_token_is_not_part_of_command_digest() -> None:
    command = _command()

    assert replace(command, operation_token=uuid4()).operation_digest == (
        command.operation_digest
    )
