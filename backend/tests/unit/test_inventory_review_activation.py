"""Installing the review schema must not grant source write authority."""

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.api import production
from app.api.catalog_common import catalog_write_context
from app.api.dependencies import get_current_site_context, get_database_engine
from app.config import Settings
from app.production import inventory_review as ir
from app.site_context import CurrentSiteContext
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_review_writes_require_explicit_local_activation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("APP_PRODUCTION_INVENTORY_REVIEW_WRITES_ENABLED", raising=False)
    assert Settings().production_inventory_review_writes_enabled is False
    monkeypatch.setenv("APP_PRODUCTION_INVENTORY_REVIEW_WRITES_ENABLED", "true")
    with pytest.raises(ValueError, match="explicit local demo root"):
        Settings()
    settings = Settings(
        production_demo_mode=True, production_order_draft_root=str(tmp_path)
    )
    assert settings.production_inventory_review_writes_enabled is True


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[FastAPI, list[str]]:
    app = FastAPI()
    app.include_router(production.router)
    app.state.settings = Settings(
        production_demo_mode=True,
        production_order_draft_root=str(tmp_path),
        production_inventory_review_writes_enabled=False,
    )
    context = CurrentSiteContext(
        1,
        frozenset({"admin"}),
        1,
        "DEMO_LOCAL_ONLY",
        "Fictional",
        1,
        1,
        "UTC",
        "UTC",
        "USD",
    )
    app.dependency_overrides[get_current_site_context] = lambda: context
    app.dependency_overrides[catalog_write_context] = lambda: context
    app.dependency_overrides[get_database_engine] = lambda: object()
    calls: list[str] = []

    def start(*_: object) -> tuple[dict[str, object], bool]:
        calls.append("start")
        return {"review_id": str(uuid4())}, True

    def preview(*_: object) -> dict[str, object]:
        calls.append("preview")
        return {"preview_hash": "a" * 64}

    def save(*_: object) -> dict[str, object]:
        calls.append("save")
        return {"revision": 1}

    monkeypatch.setattr(ir, "start", start)
    monkeypatch.setattr(ir, "preview", preview)
    monkeypatch.setattr(ir, "save", save)
    return app, calls


def request(client: TestClient, action: str) -> Any:
    if action == "start":
        return client.post(
            "/api/production/inventory-reviews",
            json={"source_digest": "a" * 64, "source_manifest_digest": "b" * 64},
        )
    payload: dict[str, object] = {
        "source_identity": "c" * 64,
        "expected_revision": 0,
        "changes": [{"type": "set_cutoff_note", "value": "fictional"}],
        "reason": "fictional check",
    }
    if action == "save":
        payload["preview_hash"] = "a" * 64
    return client.post(
        f"/api/production/inventory-reviews/{uuid4()}/"
        + ("commands" if action == "save" else "preview"),
        json=payload,
        headers={"Idempotency-Key": str(uuid4())},
    )


@pytest.mark.parametrize("action", ["start", "preview", "save"])
def test_disabled_writes_fail_before_review_storage(
    api: tuple[FastAPI, list[str]], action: str
) -> None:
    app, calls = api
    with TestClient(app) as client:
        response = request(client, action)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "inventory_review_read_only"
    assert calls == []


@pytest.mark.parametrize("action", ["start", "preview", "save"])
def test_enabled_writes_preserve_existing_manager_path(
    api: tuple[FastAPI, list[str]], action: str
) -> None:
    app, calls = api
    app.state.settings = replace(
        app.state.settings, production_inventory_review_writes_enabled=True
    )
    with TestClient(app) as client:
        response = request(client, action)
    assert response.status_code == (201 if action == "start" else 200)
    assert calls == [action]


def test_activation_does_not_grant_viewer_write_permission(
    api: tuple[FastAPI, list[str]],
) -> None:
    app, calls = api
    app.state.settings = replace(
        app.state.settings, production_inventory_review_writes_enabled=True
    )
    context = CurrentSiteContext(
        1,
        frozenset({"viewer"}),
        1,
        "DEMO_LOCAL_ONLY",
        "Fictional",
        1,
        1,
        "UTC",
        "UTC",
        "USD",
    )
    app.dependency_overrides[catalog_write_context] = lambda: context
    with TestClient(app) as client:
        for action in ("start", "preview", "save"):
            response = request(client, action)
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "role_forbidden"
    assert calls == []


def test_disabled_writes_keep_saved_review_and_receipts_readable(
    api: tuple[FastAPI, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _ = api
    review_id, operation_id = uuid4(), uuid4()
    monkeypatch.setattr(
        ir,
        "current",
        lambda *_: {
            "review_id": str(review_id),
            "source": {},
            "can_manage": True,
        },
    )
    monkeypatch.setattr(
        ir,
        "detail",
        lambda *_: {
            "review_id": str(review_id),
            "revision": 3,
            "can_manage": True,
        },
    )
    monkeypatch.setattr(ir, "history", lambda *_: {"items": [{"revision": 3}]})
    monkeypatch.setattr(ir, "operation", lambda *_: {"revision": 3})
    with TestClient(app) as client:
        current = client.get("/api/production/inventory-reviews/current").json()
        assert current["writes_enabled"] is False
        assert current["can_manage"] is False
        assert current["review_id"] == str(review_id)
        detail = client.get(f"/api/production/inventory-reviews/{review_id}").json()
        assert detail["can_manage"] is False and detail["revision"] == 3
        assert client.get(
            f"/api/production/inventory-reviews/{review_id}/history"
        ).json()["items"] == [{"revision": 3}]
        assert client.get(
            f"/api/production/inventory-reviews/{review_id}/operations/{operation_id}"
        ).json() == {"revision": 3}
