from __future__ import annotations

from datetime import date

import pytest
from app.api import dashboard
from fastapi import Response
from fastapi.testclient import TestClient

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)
from tests.integration.test_catalog_repository import (
    catalog_approval_case_fixture,  # noqa: F401
)
from tests.integration.test_style_analytics import (
    style_analytics_case_fixture,  # noqa: F401
)
from tests.integration.test_style_analytics_api import (
    _range,
    style_api_client_fixture,  # noqa: F401
)

pytestmark = pytest.mark.mysql


def test_legacy_card_success_adds_only_identity_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = object()

    class FakeQueryService:
        def __init__(self, _session: object) -> None:
            pass

        def product_card(
            self,
            style_code: str,
            from_date: date,
            to_date: date,
        ) -> object:
            assert style_code == "2301"
            assert from_date == to_date == date(2026, 8, 22)
            return expected

    monkeypatch.setattr(dashboard, "_service", lambda _session: object())
    monkeypatch.setattr(dashboard, "ProductLedgerQueryService", FakeQueryService)
    response = Response()
    result = dashboard.product_card(
        style_code="2301",
        _principal=object(),  # type: ignore[arg-type]
        database_session=object(),  # type: ignore[arg-type]
        response=response,
        from_date=date(2026, 8, 22),
        to_date=date(2026, 8, 22),
    )
    assert result is expected
    assert response.headers["X-Identity-Source"] == "legacy_parser"
    assert response.headers["X-Identity-Version"] == "seller_sku_parser_v1"


def test_legacy_ledger_and_card_keep_body_contract_and_add_identity_headers(
    style_api_client: TestClient,
) -> None:
    ledger = style_api_client.get("/api/dashboard/product-ledger", params=_range())
    assert ledger.status_code == 200, ledger.text
    assert ledger.headers["X-Identity-Source"] == "legacy_parser"
    assert ledger.headers["X-Identity-Version"] == "seller_sku_parser_v1"
    body = ledger.json()
    assert set(body) == {
        "range",
        "rows",
        "total_rows",
        "page",
        "page_size",
        "sort",
        "direction",
        "publications",
        "site_config_versions",
    }
    assert body["rows"]


def test_numeric_style_code_never_changes_the_new_style_id_path_semantics(
    style_api_client: TestClient,
) -> None:
    style_code = "23010000"
    legacy = style_api_client.get(
        f"/api/dashboard/product-card/{style_code}", params=_range()
    )
    assert legacy.status_code == 404
    assert legacy.json()["error"]["code"] == "product_not_found"

    stable = style_api_client.get(
        f"/api/dashboard/styles/{style_code}/card", params=_range()
    )
    assert stable.status_code == 404
    assert stable.json()["error"]["code"] == "catalog_style_not_found"
    assert stable.headers.get("X-Identity-Source") is None
