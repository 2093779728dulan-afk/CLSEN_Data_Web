from dataclasses import replace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.api import publications
from app.api.dependencies import (
    get_current_site_context,
    get_database_engine,
    get_session_service,
    require_principal,
)
from app.auth.sessions import Principal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.unit.test_catalog_api import _context


def test_initialization_http_roles_csrf_and_site_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(publications.router)
    principal = Principal(
        user_id=1,
        username="manager",
        display_name="Manager",
        roles=frozenset({"data_manager"}),
        session_id=1,
        csrf_token_hash=b"x" * 32,
    )
    app.dependency_overrides[require_principal] = lambda: principal
    app.dependency_overrides[get_current_site_context] = lambda: _context(
        "data_manager"
    )
    app.dependency_overrides[get_database_engine] = lambda: MagicMock()
    service = MagicMock()
    service.csrf_matches.return_value = True
    app.dependency_overrides[get_session_service] = lambda: service
    repository = MagicMock()
    repository.initialization_preview.return_value = dict(
        dataset_id=1,
        proposed_version_id=2,
        expected_publication_revision=0,
        expected_dedup_publication_revision=0,
        initialization_revision=3,
        expected_set_digest="a" * 64,
        published_return_reports=1,
        coverage_from="2026-08-06",
        coverage_to="2026-08-06",
    )
    monkeypatch.setattr(
        publications, "MySqlReturnDedupRepository", lambda _engine: repository
    )
    with TestClient(app) as client:
        path = "/api/publications/return-initialization"
        assert client.get(path).status_code == 200
        body = {
            **repository.initialization_preview.return_value,
            "operation_token": str(uuid4()),
        }
        for field in ("published_return_reports", "coverage_from", "coverage_to"):
            body.pop(field)
        assert (
            client.post(
                path, json=body, headers={"Idempotency-Key": body["operation_token"]}
            ).status_code
            == 403
        )
        repository.create_staging.assert_not_called()
        principal = replace(principal, roles=frozenset({"viewer"}))
        assert client.get(path).status_code == 403
