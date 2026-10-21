from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from app.validation.types import RunValidationCommand

TOKEN = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _command(**overrides: object) -> RunValidationCommand:
    values: dict[str, object] = {
        "dataset_id": 5,
        "version_id": 23,
        "data_revision": 4,
        "ruleset_version": "return_report_v1",
        "actor_user_id": 9,
        "operation_token": TOKEN,
    }
    values.update(overrides)
    return RunValidationCommand(**values)  # type: ignore[arg-type]


def test_run_validation_digest_binds_the_complete_full_run_scope() -> None:
    command = _command()

    assert command.operation_kind == "run_validation"
    assert len(command.operation_digest) == 32
    for changed in (
        replace(command, dataset_id=6),
        replace(command, version_id=24),
        replace(command, data_revision=5),
        replace(command, ruleset_version="return_report_v2"),
        replace(command, actor_user_id=10),
    ):
        assert changed.operation_digest != command.operation_digest


def test_run_validation_digest_does_not_depend_on_retry_token() -> None:
    command = _command()
    retried_with_another_token = replace(
        command,
        operation_token=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    )

    assert retried_with_another_token.operation_digest == command.operation_digest


def test_run_validation_command_rejects_invalid_scope() -> None:
    for overrides in (
        {"dataset_id": 0},
        {"version_id": True},
        {"data_revision": -1},
        {"ruleset_version": "   "},
        {"operation_token": "not-a-uuid"},
    ):
        try:
            _command(**overrides)
        except ValueError:
            pass
        else:  # pragma: no cover - keeps all malformed cases visible in one test
            raise AssertionError(f"invalid command was accepted: {overrides}")
