from __future__ import annotations

from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_catalog_resources_require_authentication_before_lookup() -> None:
    app = create_app(
        settings=Settings(
            environment="test",
            log_level="CRITICAL",
            cors_allowed_origins=(),
            session_secret="catalog-security-test-secret-0000000",
            session_cookie_secure=False,
        )
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        for path in (
            "/api/catalog/styles",
            "/api/catalog/imports/999999",
            "/api/catalog/versions",
            "/api/catalog/source-identifiers/not-real",
        ):
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "authentication_required"
