"""Publication returns after attempting the existing FBA inventory synchronization."""

from inspect import signature
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from app.api import production_fba, publications
from fastapi import BackgroundTasks


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "publish_dataset",
        "rollback_dataset",
        "finalize_published_move",
        "undo_published_move",
    ],
)
def test_publication_synchronizes_fba_before_returning(
    monkeypatch: pytest.MonkeyPatch, endpoint_name: Any
) -> None:
    events: list[Any] = []
    receipt: Any = object()
    request, context, engine = object(), object(), object()

    def publish(command: Any) -> Any:
        events.append("published")
        return receipt

    def synchronize(
        actual_request: Any, actual_context: Any, actual_engine: Any
    ) -> Any:
        assert (actual_request, actual_context, actual_engine) == (
            request,
            context,
            engine,
        )
        events.append("inventory")

    monkeypatch.setattr(publications, "_run_publication_command", publish)
    monkeypatch.setattr(production_fba, "sync_published_daily", synchronize)
    endpoint = getattr(publications, endpoint_name)
    arguments: dict[str, Any] = {
        "dataset_id": 1,
        "move_revision_operation_token": uuid4(),
        "move_command_id": 1,
        "payload": SimpleNamespace(),
        "principal": SimpleNamespace(user_id=1),
        "engine": engine,
        "operation_token": uuid4(),
        "request": request,
        "context": context,
        "background": BackgroundTasks(),
    }
    result = endpoint(
        **{name: arguments[name] for name in signature(endpoint).parameters}
    )

    assert result is receipt
    assert events == ["published", "inventory"]


def test_legacy_daily_upload_returns_review_handoff_when_dedup_staging_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from contextlib import contextmanager
    from datetime import date

    from app.api import workbench
    from app.catalog.return_dedup_repository import ReturnDedupStagingNotReady
    from app.production import fba_daily_import

    @contextmanager
    def connect() -> Any:
        yield SimpleNamespace(scalar=lambda *args: 1)

    async def upload(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            dataset_id=1,
            version_id=1,
            status="workspace_ready",
            workspace_url="/review/2026-11-07",
            batch_id=1,
        )

    def needs_staging(*args: Any) -> Any:
        raise ReturnDedupStagingNotReady()

    monkeypatch.setattr(production_fba, "require_catalog_manager", lambda context: None)
    monkeypatch.setattr(
        production_fba,
        "read",
        lambda *args: {"cutoff_on": "2026-10-01", "report_source_scope_id": "1"},
    )
    monkeypatch.setattr(workbench, "upload_workbench_import", upload)
    monkeypatch.setattr(fba_daily_import, "publish_clean_daily", needs_staging)
    result = asyncio.run(
        production_fba.upload_daily(
            cast(Any, object()),
            cast(Any, SimpleNamespace(site_id=1)),
            cast(Any, SimpleNamespace(connect=connect)),
            cast(Any, SimpleNamespace(user_id=1)),
            1,
            date(2026, 11, 7),
            uuid4(),
            "QA.csv",
        )
    )
    assert result["status"] == "review_required"
    assert result["workspace_url"] == "/review/2026-11-07"
    assert result["batch_id"] == 1


def test_one_warehouse_failure_does_not_skip_other_distinct_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.errors import ApiError

    scopes: list[Any] = [
        {"id": "1", "report_source_scope_id": "11"},
        {"id": "2", "report_source_scope_id": "12"},
    ]
    monkeypatch.setattr(production_fba, "read", lambda *args: {"items": scopes})
    calls: list[Any] = []

    def sync(request: Any, context: Any, engine: Any, scope: Any, key: Any) -> Any:
        calls.append(scope)
        if scope == "1":
            raise ApiError(409, "insufficient_available_stock", "可售不足")

    monkeypatch.setattr(production_fba, "sync_daily", sync)
    request: Any = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(production_service_url="owned-task")
            )
        )
    )
    production_fba.sync_published_daily(
        request, cast(Any, object()), cast(Any, object())
    )
    assert calls == ["1", "2"]


def test_published_inventory_status_respects_site_report_and_warehouse_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    import sqlalchemy as sa

    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE daily_datasets(id INTEGER,site_id INTEGER,"
                "report_date TEXT,report_type TEXT)"
            )
        )
        connection.execute(
            sa.text("CREATE TABLE dataset_publications(dataset_id INTEGER)")
        )
        connection.execute(
            sa.text(
                "CREATE TABLE report_dataset_scope_assignments(dataset_id INTEGER,"
                "site_id INTEGER,report_source_scope_id INTEGER)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO daily_datasets VALUES"
                "(1,7,'2026-10-30','business_report'),"
                "(2,8,'2026-10-30','business_report')"
            )
        )
        connection.execute(sa.text("INSERT INTO dataset_publications VALUES(1),(2)"))
        connection.execute(
            sa.text(
                "INSERT INTO report_dataset_scope_assignments VALUES(1,7,11),(2,8,22)"
            )
        )
    candidates: list[Any] = [
        {"id": "1", "report_source_scope_id": "11"},
        {"id": "2", "report_source_scope_id": "22"},
    ]

    def read(request: Any, context: Any, resource: Any) -> Any:
        if resource == "fba-daily-scopes":
            return {"items": candidates}
        assert resource == "fba-scopes/1"
        return {
            "id": "1",
            "warehouse_id": "3",
            "owner_id": "9",
            "cutoff_on": "2026-10-01",
        }

    monkeypatch.setattr(production_fba, "read", read)
    issues: list[Any] = []
    monkeypatch.setattr(
        production_fba,
        "state",
        lambda *args: {
            "daily": {"1": {"issues": issues}},
            "stock": {"scopes": [{"warehouse_id": "3", "warehouse_name": "美国FBA"}]},
        },
    )
    request: Any = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(production_service_url="owned-task")
            )
        )
    )

    def status() -> Any:
        return production_fba.published_daily_status(
            request,
            cast(Any, SimpleNamespace(site_id=7)),
            engine,
            date(2026, 10, 30),
            "business_report",
        )["items"]

    result = status()
    assert len(result) == 1 and result[0]["status"] == "updated"
    assert result[0]["owner_id"] == "9" and result[0]["warehouse_id"] == "3"
    issues.append({"label": "销售库存尚未更新"})
    assert status()[0]["status"] == "pending"
    candidates.append({"id": "3", "report_source_scope_id": "11"})
    monkeypatch.setattr(
        production_fba,
        "read",
        lambda request, context, resource: (
            {"items": candidates}
            if resource == "fba-daily-scopes"
            else {
                "id": resource.split("/")[-1],
                "warehouse_id": "3",
                "owner_id": "9",
                "cutoff_on": "2026-10-01",
            }
        ),
    )
    monkeypatch.setattr(
        production_fba,
        "state",
        lambda *args: {"daily": {"1": {"issues": []}, "3": {"issues": []}}},
    )
    assert all(
        not item["can_retry"] and item["status"] == "pending" for item in status()
    )
    engine.dispose()
