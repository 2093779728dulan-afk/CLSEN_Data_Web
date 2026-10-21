from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(
        environment="test",
        log_level="WARNING",
        cors_allowed_origins=("https://review.example.test",),
    )
    with TestClient(create_app(settings=settings)) as test_client:
        yield test_client


@pytest.mark.parametrize("path", ["/api/health/live", "/api/health/ready"])
def test_health_endpoint_is_available(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert UUID(response.headers["X-Request-ID"]).version == 4


def test_valid_request_id_is_propagated(client: TestClient) -> None:
    request_id = "daily-review_2026.08.06:health"

    response = client.get(
        "/api/health/live",
        headers={"X-Request-ID": request_id},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id


@pytest.mark.parametrize("request_id", [None, "contains spaces", "x" * 129])
def test_missing_or_invalid_request_id_is_replaced(
    client: TestClient,
    request_id: str | None,
) -> None:
    headers = {} if request_id is None else {"X-Request-ID": request_id}

    response = client.get("/api/health/live", headers=headers)

    generated_request_id = response.headers["X-Request-ID"]
    assert generated_request_id != request_id
    assert UUID(generated_request_id).version == 4


def test_not_found_uses_the_shared_error_contract(client: TestClient) -> None:
    request_id = "missing-resource-test"

    response = client.get(
        "/api/does-not-exist",
        headers={"X-Request-ID": request_id},
    )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == request_id
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "The requested resource was not found.",
            "request_id": request_id,
        }
    }


def test_cors_only_allows_configured_origins(client: TestClient) -> None:
    allowed = client.options(
        "/api/health/live",
        headers={
            "Origin": "https://review.example.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    denied = client.options(
        "/api/health/live",
        headers={
            "Origin": "https://untrusted.example.test",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == (
        "https://review.example.test"
    )
    assert "Access-Control-Allow-Origin" not in denied.headers
    assert denied.json() == {
        "error": {
            "code": "cors_preflight_denied",
            "message": "The CORS preflight request was denied.",
            "request_id": denied.headers["X-Request-ID"],
        }
    }


def test_unexpected_errors_use_contract_without_hiding_test_failures() -> None:
    application = create_app(
        settings=Settings(
            environment="test",
            log_level="WARNING",
            cors_allowed_origins=("https://review.example.test",),
        )
    )

    @application.get("/api/testing/unexpected-error")
    def raise_unexpected_error() -> None:
        raise RuntimeError("private diagnostic detail")

    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get(
            "/api/testing/unexpected-error",
            headers={
                "Origin": "https://review.example.test",
                "X-Request-ID": "unexpected-error-test",
            },
        )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "unexpected-error-test"
    assert response.headers["Access-Control-Allow-Origin"] == (
        "https://review.example.test"
    )
    assert response.json() == {
        "error": {
            "code": "internal_server_error",
            "message": "An unexpected error occurred.",
            "request_id": "unexpected-error-test",
        }
    }
    assert "private diagnostic detail" not in response.text

    with (
        TestClient(application) as strict_test_client,
        pytest.raises(RuntimeError, match="private diagnostic detail"),
    ):
        strict_test_client.get("/api/testing/unexpected-error")
