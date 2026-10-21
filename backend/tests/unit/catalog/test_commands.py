from __future__ import annotations

from uuid import uuid4

import pytest
from app.catalog.canonical_json import CanonicalValue
from app.catalog.commands import (
    CatalogDecisionBatchError,
    CatalogDecisionMutation,
    semantic_command_digest,
    validate_decision_batch,
)


def test_semantic_digest_excludes_token_but_covers_semantics() -> None:
    body: dict[str, CanonicalValue] = {
        "expected_workflow_revision": 4,
        "value": "x",
    }
    first = semantic_command_digest(
        route="decisions",
        resource_id=9,
        body=body,
        operation_token=uuid4(),
    )
    second = semantic_command_digest(
        route="decisions",
        resource_id=9,
        body=body,
        operation_token=uuid4(),
    )
    assert first == second
    assert first != semantic_command_digest(
        route="decisions",
        resource_id=10,
        body=body,
        operation_token=uuid4(),
    )
    assert first != semantic_command_digest(
        route="decisions",
        resource_id=9,
        body={**body, "expected_workflow_revision": 5},
        operation_token=uuid4(),
    )


def test_decision_batches_accept_one_and_five_hundred_but_reject_zero_and_501() -> None:
    mutation = CatalogDecisionMutation(
        mutation_id=uuid4(),
        type="update_style",
        row_key="style-1",
        decision_group_key=None,
        payload={"standard_name": "Name"},
    )
    assert len(validate_decision_batch((mutation,))) == 1
    assert (
        len(
            validate_decision_batch(
                (mutation,) * 500,
                allow_repeated_for_test=True,
            )
        )
        == 500
    )
    with pytest.raises(CatalogDecisionBatchError):
        validate_decision_batch(())
    with pytest.raises(CatalogDecisionBatchError):
        validate_decision_batch((mutation,) * 501, allow_repeated_for_test=True)


def test_invalid_batch_targets_and_references_fail_atomically() -> None:
    duplicate = (
        CatalogDecisionMutation(uuid4(), "update_style", "style-1", None, {}),
        CatalogDecisionMutation(uuid4(), "update_style", "style-1", None, {}),
    )
    with pytest.raises(CatalogDecisionBatchError) as captured:
        validate_decision_batch(duplicate)
    assert captured.value.issues[0].reason_code == "duplicate_target"

    bad_ref = (
        CatalogDecisionMutation(
            uuid4(),
            "create_sku",
            "sku-new",
            None,
            {"style_row_key": "missing"},
        ),
    )
    with pytest.raises(CatalogDecisionBatchError) as captured:
        validate_decision_batch(bad_ref, existing_row_keys=frozenset())
    assert captured.value.issues[0].reason_code == "invalid_reference"

    delete = (
        CatalogDecisionMutation(uuid4(), "delete_style", "system-style", None, {}),
    )
    with pytest.raises(CatalogDecisionBatchError) as captured:
        validate_decision_batch(delete, system_row_keys=frozenset({"system-style"}))
    assert captured.value.issues[0].field is None
