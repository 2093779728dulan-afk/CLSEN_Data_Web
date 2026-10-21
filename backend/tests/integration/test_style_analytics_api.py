from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.config import Settings
from app.db.session import create_session_factory
from app.main import create_app
from fastapi.testclient import TestClient

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)
from tests.integration.test_authentication_api import _create_user, _login
from tests.integration.test_catalog_repository import (
    catalog_approval_case_fixture,  # noqa: F401
)
from tests.integration.test_style_analytics import (
    REPORT_DATE,
    ApprovedStyleAnalyticsCase,
    style_analytics_case_fixture,  # noqa: F401
)

pytestmark = pytest.mark.mysql


@pytest.fixture(name="style_api_client")
def style_api_client_fixture(
    style_analytics_case: ApprovedStyleAnalyticsCase,
) -> Iterator[TestClient]:
    _, username = _create_user(
        style_analytics_case.engine,
        role="data_manager",
        password="style analytics password",
    )
    settings = Settings(
        environment="test",
        log_level="WARNING",
        cors_allowed_origins=(),
        session_secret="style-analytics-api-secret-000000000000",
        session_cookie_secure=False,
    )
    with TestClient(
        create_app(
            settings=settings,
            session_factory=create_session_factory(style_analytics_case.engine),
        )
    ) as client:
        _login(
            client,
            username=username,
            password="style analytics password",
        )
        yield client


def _range() -> dict[str, str]:
    value = REPORT_DATE.isoformat()
    return {"from": value, "to": value, "return_basis": "report_date"}


def test_new_style_endpoints_return_p0_body_and_matching_identity_headers(
    style_api_client: TestClient,
) -> None:
    ledger = style_api_client.get("/api/dashboard/style-ledger", params=_range())
    assert ledger.status_code == 200, ledger.text
    body = ledger.json()
    assert ledger.headers["X-Identity-Source"] == "p0_catalog"
    assert (
        ledger.headers["X-Identity-Version"] == body["provenance"]["catalog_version_id"]
    )
    assert body["provenance"]["identity_source"] == "p0_catalog"
    assert (
        body["provenance"]["identity_version_id"]
        == body["provenance"]["catalog_version_id"]
    )
    assert all(isinstance(row["style_id"], str) for row in body["rows"])
    assert body["rows"]

    style_id = body["rows"][0]["style_id"]
    card = style_api_client.get(
        f"/api/dashboard/styles/{style_id}/card",
        params={**_range(), "metric": "conversion", "dimension": "total"},
    )
    assert card.status_code == 200, card.text
    card_body = card.json()
    assert card.headers["X-Identity-Source"] == "p0_catalog"
    assert (
        card.headers["X-Identity-Version"]
        == card_body["provenance"]["catalog_version_id"]
    )
    assert card_body["style"]["style_id"] == style_id
    assert card_body["trend_effective_return_basis"] is None
    assert card_body["style_reconciliation"]["selected_color_totals"] is None
    assert all(isinstance(item["sku_id"], str) for item in card_body["variants"])


def test_style_api_uses_the_frozen_safe_error_table(
    style_api_client: TestClient,
) -> None:
    cases = [
        (
            "/api/dashboard/style-ledger",
            {"from": "invalid", "to": REPORT_DATE.isoformat()},
            422,
            "analytics_date_range_invalid",
        ),
        (
            "/api/dashboard/style-ledger",
            {**_range(), "page_size": "101"},
            422,
            "analytics_parameter_invalid",
        ),
        (
            "/api/dashboard/style-ledger",
            {**_range(), "fact_basis": "catalog_snapshot"},
            422,
            "analytics_catalog_version_required",
        ),
        (
            "/api/dashboard/style-ledger",
            {**_range(), "catalog_version": "999999"},
            409,
            "analytics_identity_fact_combination_invalid",
        ),
        (
            "/api/dashboard/styles/999999/card",
            _range(),
            404,
            "catalog_style_not_found",
        ),
        (
            "/api/dashboard/styles/1/card",
            {**_range(), "dimension": "size"},
            422,
            "analytics_dimension_parameter_invalid",
        ),
        (
            "/api/dashboard/styles/1/card",
            {**_range(), "dimension": "total", "color_key": "unknown"},
            422,
            "analytics_dimension_parameter_invalid",
        ),
        (
            "/api/dashboard/styles/1/card",
            {**_range(), "series": ""},
            422,
            "analytics_series_invalid",
        ),
        (
            "/api/dashboard/styles/1/card",
            {**_range(), "metric": "unknown"},
            422,
            "analytics_parameter_invalid",
        ),
    ]
    for path, params, status, code in cases:
        response = style_api_client.get(path, params=params)
        assert response.status_code == status, response.text
        assert response.json()["error"]["code"] == code


def test_unknown_color_and_series_are_never_retried_against_legacy_identity(
    style_api_client: TestClient,
) -> None:
    ledger = style_api_client.get("/api/dashboard/style-ledger", params=_range()).json()
    style_id = ledger["rows"][0]["style_id"]
    color = style_api_client.get(
        f"/api/dashboard/styles/{style_id}/card",
        params={**_range(), "dimension": "size", "color_key": "unknown"},
    )
    assert color.status_code == 404
    assert color.json()["error"]["code"] == "catalog_color_not_found"

    series = style_api_client.get(
        f"/api/dashboard/styles/{style_id}/card",
        params={**_range(), "series": "unknown"},
    )
    assert series.status_code == 422
    assert series.json()["error"]["code"] == "analytics_series_invalid"
