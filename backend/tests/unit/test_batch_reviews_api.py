from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from app.api.batch_reviews import (
    CONFIRMATION_STATEMENT_VERSION,
    ConfirmRequest,
    PreflightRequest,
    RevisionRequest,
    _advance_principal,
    router,
)
from app.api.errors import ApiError
from pydantic import ValidationError


def test_inactive_site_does_not_commit_authentication_or_start_advance() -> None:
    session = MagicMock()
    engine = MagicMock()
    principal = MagicMock()
    with (
        patch(
            "app.api.batch_reviews._site_id",
            side_effect=ApiError(503, "site_unavailable", "Unavailable"),
        ),
        pytest.raises(ApiError),
    ):
        _advance_principal(principal, session, engine)
    session.commit.assert_not_called()
    session.close.assert_not_called()


def test_batch_review_router_exposes_all_eight_operations() -> None:
    methods = {
        (getattr(route, "path", None), method)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }
    assert methods == {
        ("/api/imports/batch-reviews", "GET"),
        ("/api/imports/batch-reviews/preflight", "POST"),
        ("/api/imports/batch-reviews/{run_id}", "GET"),
        ("/api/imports/batch-reviews/{run_id}/confirm", "POST"),
        ("/api/imports/batch-reviews/{run_id}/items/{item_id}/advance", "POST"),
        ("/api/imports/batch-reviews/{run_id}/pause", "POST"),
        ("/api/imports/batch-reviews/{run_id}/resume", "POST"),
        ("/api/imports/batch-reviews/{run_id}/items/{item_id}/retry", "POST"),
    }


def test_request_models_reject_duplicates_unknown_fields_and_negative_revision() -> (
    None
):
    with pytest.raises(ValidationError):
        PreflightRequest(batch_ids=[1, 1])
    with pytest.raises(ValidationError):
        RevisionRequest(expected_revision=-1)
    with pytest.raises(ValidationError):
        RevisionRequest(expected_revision=0, extra=True)  # type: ignore[call-arg]


def test_confirmation_requires_literal_acceptance_and_current_version() -> None:
    request = ConfirmRequest(
        expected_revision=0,
        selected_item_ids=[1],
        confirmation_accepted=True,
        confirmation_statement_version=CONFIRMATION_STATEMENT_VERSION,
    )
    assert request.confirmation_accepted is True
    with pytest.raises(ValidationError):
        ConfirmRequest(
            expected_revision=0,
            selected_item_ids=[1],
            confirmation_accepted=False,  # type: ignore[arg-type]
            confirmation_statement_version=CONFIRMATION_STATEMENT_VERSION,
        )
