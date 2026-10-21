from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_admin_management_api import (
    AdminApiContext,
    _create_user,
    _login,
)
from tests.integration.test_admin_management_api import admin_api as admin_api_fixture

admin_api = admin_api_fixture
pytestmark = pytest.mark.mysql


def test_worker_observability_response_is_admin_only(
    admin_api: AdminApiContext,
) -> None:
    with TestClient(admin_api.client.app) as anonymous_client:
        anonymous = anonymous_client.get("/api/admin/maintenance")

    user_id, username = _create_user(
        admin_api.engine,
        role="viewer",
        password="correct horse battery staple",
    )
    admin_api.created_user_ids.append(user_id)
    with TestClient(admin_api.client.app) as viewer_client:
        _login(
            viewer_client,
            username=username,
            password="correct horse battery staple",
        )
        forbidden = viewer_client.get("/api/admin/maintenance")

    assert anonymous.status_code == 401
    assert forbidden.status_code == 403


def test_worker_observability_response_is_ordered_and_not_cached(
    admin_api: AdminApiContext,
) -> None:
    response = admin_api.client.get("/api/admin/maintenance")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    payload = response.json()
    assert list(payload) == [
        "backups",
        "restores",
        "outbox",
        "write_lock",
        "observed_at",
        "maintenance_active",
        "worker",
        "queues",
    ]
    assert [queue["queue_name"] for queue in payload["queues"]] == [
        "return_dedup",
        "publication_outbox",
        "catalog_export",
        "catalog_import",
    ]
