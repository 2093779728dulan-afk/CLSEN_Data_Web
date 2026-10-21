from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import NoReturn, cast

import pytest
from app.api import review as review_api
from app.api.dependencies import get_database_engine, require_csrf_principal
from app.auth.sessions import Principal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

_HEADERS = {"Idempotency-Key": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}


@dataclass(slots=True)
class _BoundaryCalls:
    service: int = 0
    repository: int = 0


def _principal() -> Principal:
    return Principal(
        user_id=13,
        username="operator",
        display_name="Operator",
        roles=frozenset({"data_manager"}),
        session_id=17,
        csrf_token_hash=b"x" * 32,
    )


def _head(*, status: str = "draft") -> dict[str, object]:
    return {
        "dataset_id": 7,
        "status": status,
        "data_revision": 2,
        "review_revision": 3,
        "pointed_at": "2026-08-10T08:30:00+08:00",
    }


def _set_field(**overrides: object) -> dict[str, object]:
    payload = {
        **_head(),
        "row_id": 11,
        "field_name": "sku",
        "value": {"type": "text", "value": "SKU-1"},
        "reason": "Correct the imported value.",
    }
    payload.update(overrides)
    return payload


def _restore_field(**overrides: object) -> dict[str, object]:
    payload = {
        **_head(),
        "row_id": 11,
        "source_kind": "previous",
        "field_change_id": 19,
        "reason": "Restore the previous value.",
    }
    payload.update(overrides)
    return payload


def _add_row(**overrides: object) -> dict[str, object]:
    payload = {
        **_head(),
        "source_batch_id": 5,
        "values": {"sku": {"type": "text", "value": "SKU-1"}},
        "reason": "Add a missing source row.",
    }
    payload.update(overrides)
    return payload


def _row_state(**overrides: object) -> dict[str, object]:
    payload = {
        **_head(),
        "operation": "exclude",
        "reason": "Exclude an incorrectly parsed row.",
    }
    payload.update(overrides)
    return payload


def _note(**overrides: object) -> dict[str, object]:
    payload = {
        "expected_review_revision": 3,
        "target_type": "version",
        "body": "Checked against the source file.",
        "visibility": "internal",
    }
    payload.update(overrides)
    return payload


def _revised_note(**overrides: object) -> dict[str, object]:
    payload = {
        **_note(),
        "expected_note_id": 23,
        "expected_revision_number": 1,
    }
    payload.update(overrides)
    return payload


def _batch_note(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "body": "The imported headings were checked manually.",
        "visibility": "internal",
    }
    payload.update(overrides)
    return payload


def _revised_batch_note(**overrides: object) -> dict[str, object]:
    payload = {
        **_batch_note(),
        "expected_note_id": 23,
        "expected_revision_number": 1,
    }
    payload.update(overrides)
    return payload


def _issue_review(**overrides: object) -> dict[str, object]:
    payload = {
        **_head(),
        "validation_run_id": 29,
        "issue_severity": "warning",
        "issue_requires_note": False,
        "action": "acknowledge",
        "comment": "Checked against the original workbook.",
    }
    payload.update(overrides)
    return payload


def _mark_ready(**overrides: object) -> dict[str, object]:
    payload = {
        **_head(),
        "validation_run_id": 29,
        "validation_data_digest": "ab" * 32,
        "ruleset_version": "business-v1",
        "confirmed_report_date": "2026-08-10",
        "confirmed_report_type": "business_report",
        "confirmed_row_count": 1,
        "confirmed_totals": {"units_ordered": "2"},
        "reason": "The source and calculated totals match.",
    }
    payload.update(overrides)
    return payload


def _return_to_draft(**overrides: object) -> dict[str, object]:
    payload = {
        **_head(status="ready_for_publish"),
        "reason": "A further source correction is required.",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def boundary_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, _BoundaryCalls]]:
    calls = _BoundaryCalls()
    engine = cast(Engine, object())

    def forbidden_service(_engine: Engine) -> NoReturn:
        calls.service += 1
        raise AssertionError("invalid requests must not allocate the review service")

    def forbidden_repository(_engine: Engine) -> NoReturn:
        calls.repository += 1
        raise AssertionError("invalid requests must not allocate the repository")

    monkeypatch.setattr(review_api, "_service", forbidden_service)
    monkeypatch.setattr(review_api, "MySqlReviewRepository", forbidden_repository)

    application = FastAPI()
    application.include_router(review_api.router)
    application.dependency_overrides[require_csrf_principal] = _principal
    application.dependency_overrides[get_database_engine] = lambda: engine

    with TestClient(application) as client:
        yield client, calls


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        pytest.param("/api/drafts/0/fields", _set_field(), id="version-id"),
        pytest.param(
            "/api/drafts/17/fields",
            _set_field(dataset_id=0),
            id="dataset-id",
        ),
        pytest.param(
            "/api/drafts/17/fields",
            _set_field(data_revision=-1),
            id="data-revision",
        ),
        pytest.param(
            "/api/drafts/17/fields",
            _set_field(review_revision=-1),
            id="review-revision",
        ),
        pytest.param(
            "/api/drafts/17/fields",
            _set_field(pointed_at="2026-08-10T08:30:00"),
            id="naive-pointed-at",
        ),
        pytest.param(
            "/api/drafts/17/fields",
            _set_field(pointed_at="0001-01-01T00:00:00+23:59"),
            id="overflowing-pointed-at",
        ),
        pytest.param(
            "/api/drafts/17/fields",
            _set_field(dataset_id=True),
            id="boolean-id",
        ),
        pytest.param(
            "/api/drafts/17/fields",
            _set_field(row_id=0),
            id="field-row-id",
        ),
        pytest.param(
            "/api/drafts/17/fields",
            _set_field(field_name="  "),
            id="field-name",
        ),
        pytest.param(
            "/api/drafts/17/fields",
            _set_field(reason="\t"),
            id="field-reason",
        ),
        pytest.param(
            "/api/drafts/17/fields",
            _set_field(value={"type": "null", "value": "not-null"}),
            id="typed-null-shape",
        ),
        pytest.param(
            "/api/drafts/17/fields",
            _set_field(value={"type": "integer", "value": True}),
            id="typed-boolean-integer",
        ),
        pytest.param(
            "/api/drafts/17/fields/%20/restore",
            _restore_field(),
            id="restore-field-name",
        ),
        pytest.param(
            "/api/drafts/17/fields/sku/restore",
            _restore_field(field_change_id=None),
            id="restore-previous-id",
        ),
        pytest.param(
            "/api/drafts/17/fields/sku/restore",
            _restore_field(
                source_kind="source",
                field_change_id=None,
                source_batch_id=5,
            ),
            id="restore-source-row-id",
        ),
        pytest.param(
            "/api/drafts/17/rows",
            _add_row(source_batch_id=0),
            id="add-row-batch-id",
        ),
        pytest.param(
            "/api/drafts/17/rows",
            _add_row(values={}),
            id="add-row-empty-values",
        ),
        pytest.param(
            "/api/drafts/17/rows",
            _add_row(values={" ": {"type": "text", "value": "x"}}),
            id="add-row-field-name",
        ),
        pytest.param(
            "/api/drafts/17/rows/0/state",
            _row_state(),
            id="row-state-row-id",
        ),
        pytest.param(
            "/api/imports/0/notes",
            _batch_note(),
            id="batch-note-batch-id",
        ),
        pytest.param(
            "/api/imports/5/notes",
            _batch_note(body="  "),
            id="batch-note-body",
        ),
        pytest.param(
            "/api/imports/5/notes",
            _batch_note(visibility="viewer_visible"),
            id="batch-note-internal-only",
        ),
        pytest.param(
            "/api/imports/5/notes/%20/revisions",
            _revised_batch_note(),
            id="batch-note-key-blank",
        ),
        pytest.param(
            f"/api/imports/5/notes/{'x' * 65}/revisions",
            _revised_batch_note(),
            id="batch-note-key-length",
        ),
        pytest.param(
            "/api/drafts/0/notes",
            _note(),
            id="note-version-id",
        ),
        pytest.param(
            "/api/drafts/17/notes",
            _note(expected_review_revision=-1),
            id="note-review-revision",
        ),
        pytest.param(
            "/api/drafts/17/notes",
            _note(target_type="row"),
            id="row-note-row-id",
        ),
        pytest.param(
            "/api/drafts/17/notes",
            _note(target_type="field", row_id=11),
            id="field-note-field-name",
        ),
        pytest.param(
            "/api/drafts/17/notes",
            _note(body="\n"),
            id="note-body",
        ),
        pytest.param(
            "/api/drafts/17/notes/note-1/revisions",
            _revised_note(expected_note_id=0),
            id="note-revision-id",
        ),
        pytest.param(
            "/api/drafts/17/issues/0/review",
            _issue_review(),
            id="issue-id",
        ),
        pytest.param(
            "/api/drafts/17/issues/31/review",
            _issue_review(validation_run_id=0),
            id="issue-validation-run-id",
        ),
        pytest.param(
            "/api/drafts/17/issues/31/review",
            _issue_review(issue_severity="blocking"),
            id="acknowledge-blocking",
        ),
        pytest.param(
            "/api/drafts/17/issues/31/review",
            _issue_review(issue_severity="warning", action="resolve"),
            id="resolve-warning",
        ),
        pytest.param(
            "/api/drafts/17/issues/31/review",
            _issue_review(issue_requires_note=True, comment=None),
            id="acknowledge-required-comment",
        ),
        pytest.param(
            "/api/drafts/17/issues/31/review",
            _issue_review(
                issue_severity="blocking",
                action="resolve",
                comment=None,
            ),
            id="resolve-required-comment",
        ),
        pytest.param(
            "/api/drafts/17/issues/31/review",
            _issue_review(
                issue_severity="blocking",
                action="reopen",
                comment="  ",
            ),
            id="blank-optional-comment",
        ),
        pytest.param(
            "/api/drafts/17/mark-ready",
            _mark_ready(status="ready_for_publish"),
            id="mark-ready-status",
        ),
        pytest.param(
            "/api/drafts/17/mark-ready",
            _mark_ready(validation_run_id=0),
            id="mark-ready-validation-run-id",
        ),
        pytest.param(
            "/api/drafts/17/mark-ready",
            _mark_ready(ruleset_version=" "),
            id="mark-ready-ruleset",
        ),
        pytest.param(
            "/api/drafts/17/mark-ready",
            _mark_ready(confirmed_totals={" ": "2"}),
            id="mark-ready-total-name",
        ),
        pytest.param(
            "/api/drafts/17/mark-ready",
            _mark_ready(confirmed_totals={"units_ordered": " "}),
            id="mark-ready-total-value",
        ),
        pytest.param(
            "/api/drafts/17/mark-ready",
            _mark_ready(reason="  "),
            id="mark-ready-reason",
        ),
        pytest.param(
            "/api/drafts/17/return-to-draft",
            _return_to_draft(status="draft"),
            id="return-to-draft-status",
        ),
        pytest.param(
            "/api/drafts/17/return-to-draft",
            _return_to_draft(reason="\t"),
            id="return-to-draft-reason",
        ),
    ],
)
def test_invalid_review_requests_return_422_before_service_or_repository(
    boundary_client: tuple[TestClient, _BoundaryCalls],
    path: str,
    payload: dict[str, object],
) -> None:
    client, calls = boundary_client

    response = client.post(path, json=payload, headers=_HEADERS)

    assert response.status_code == 422, response.text
    assert calls == _BoundaryCalls()


def test_domain_constructor_value_error_is_mapped_before_service_allocation(
    boundary_client: tuple[TestClient, _BoundaryCalls],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, calls = boundary_client

    def reject_command(**_arguments: object) -> NoReturn:
        raise ValueError("simulated domain invariant")

    monkeypatch.setattr(review_api, "SetFieldValueCommand", reject_command)

    response = client.post(
        "/api/drafts/17/fields",
        json=_set_field(),
        headers=_HEADERS,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_review_request"
    assert calls == _BoundaryCalls()
