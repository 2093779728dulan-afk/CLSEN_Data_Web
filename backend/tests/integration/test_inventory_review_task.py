"""Real MySQL contracts using only the inventory task's fictional schema."""

# ruff: noqa: RUF001
import hashlib
import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import httpx2
import pytest
import sqlalchemy as sa
from app.api.errors import ApiError
from app.config import Settings
from app.production import inventory_review as ir
from app.production.inventory_snapshot import inventory_snapshot
from app.site_context import CurrentSiteContext
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

TASK = Path(
    "D:/CLSEN_DeploymentPrep_20260914/development-v1.1.0-mvp-20261010/optimization-20261012/catalog-reference-20261012/inventory-reconciliation-20261013"
)

Resources = tuple[Engine, Settings, CurrentSiteContext, dict[str, Any], ir.StartReview]

pytestmark = pytest.mark.mysql


@pytest.fixture(autouse=True)
def require_task_runtime() -> None:
    if os.getenv("APP_INVENTORY_REVIEW_TASK_TESTS") != "true":
        pytest.skip("Explicit task-owned fictional MySQL runtime required")


@pytest.fixture
def resources(monkeypatch: pytest.MonkeyPatch) -> Iterator[Resources]:
    runtime_url = os.environ["APP_TEST_RUNTIME_DATABASE_URL"]
    assert (
        make_url(runtime_url).database
        == "clsen_data_test_" + os.environ["APP_TEST_RUN_ID"][:16]
    )
    engine = sa.create_engine(
        runtime_url,
        isolation_level="READ COMMITTED",
        hide_parameters=True,
    )
    with engine.connect() as c:
        actor = c.scalar(
            sa.text(
                "SELECT id FROM users "
                "WHERE username_normalized='inventory.review.admin'"
            )
        )
    context = CurrentSiteContext(
        actor,
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
    settings = Settings(
        production_demo_mode=True, production_order_draft_root=str(TASK)
    )
    snapshot = cast(dict[str, Any], inventory_snapshot(settings, context))
    snapshot["source_digest"] = hashlib.sha256(uuid4().bytes).hexdigest()
    monkeypatch.setattr(ir, "inventory_snapshot", lambda *_: deepcopy(snapshot))
    body = ir.StartReview(
        source_digest=snapshot["source_digest"],
        source_manifest_digest=snapshot["source_manifest_digest"],
    )
    yield engine, settings, context, snapshot, body
    engine.dispose()


def begin(resources: Resources) -> tuple[UUID, dict[str, Any]]:
    engine, settings, context, _snapshot, body = resources
    detail, created = ir.start(engine, settings, context, body)
    assert created
    return UUID(detail["review_id"]), detail


def command(
    detail: dict[str, Any], changes: list[dict[str, Any]], reason: str = "虚构测试依据"
) -> ir.PreviewCommand:
    return ir.PreviewCommand.model_validate(
        {
            "source_identity": detail["source_identity"],
            "expected_revision": detail["revision"],
            "changes": changes,
            "reason": reason,
        }
    )


def save(
    engine: Engine,
    context: CurrentSiteContext,
    id: UUID,
    body: ir.PreviewCommand,
    token: UUID | None = None,
) -> tuple[dict[str, Any], ir.SaveCommand]:
    preview = ir.preview(engine, context, id, body)
    payload = ir.SaveCommand(**body.model_dump(), preview_hash=preview["preview_hash"])
    return ir.save(engine, context, id, payload, token or uuid4()), payload


def test_get_no_creation_duplicate_and_concurrent_start(resources: Resources) -> None:
    engine, settings, context, _, body = resources
    assert ir.current(engine, settings, context)["review_id"] is None
    with ThreadPoolExecutor(2) as executor:
        results = list(
            executor.map(lambda _: ir.start(engine, settings, context, body), range(2))
        )
    assert results[0][0]["review_id"] == results[1][0]["review_id"]
    assert sum(created for _, created in results) == 1
    id = UUID(results[0][0]["review_id"])
    assert ir.history(engine, context, id, 999, 20)["items"] == []


def test_warehouse_atomic_save_refresh_correction_and_outside(
    resources: Resources,
) -> None:
    engine, _, context, snapshot, _ = resources
    id, detail = begin(resources)
    keys = [row["source_key"] for row in snapshot["unconfirmed_rows"]]
    body = command(
        detail,
        [
            dict(type="set_location", source_key=key, value="WAREHOUSE_1")
            for key in keys
        ],
    )
    result, _ = save(engine, context, id, body)
    assert result["after"]["warehouse_1_units"] == "23"
    now = ir.detail(engine, context, id)
    assert now["revision"] == 1 and not now["effective"]["unconfirmed_rows"]
    save(
        engine,
        context,
        id,
        command(
            now,
            [dict(type="set_location", source_key=keys[0], value="OUTSIDE_SCOPE")],
            "虚构：不属于本仓",
        ),
    )
    now = ir.detail(engine, context, id)
    assert len(now["effective"]["outside_rows"]) == 1
    save(
        engine,
        context,
        id,
        command(
            now,
            [dict(type="set_location", source_key=keys[0], value="UNCONFIRMED")],
            "更正待核",
        ),
    )
    now = ir.detail(engine, context, id)
    assert len(now["effective"]["unconfirmed_rows"]) == 1
    assert len(ir.history(engine, context, id, 999, 2)["items"]) == 2
    assert ir.history(engine, context, id, 999, 2)["next_before_revision"] == 2
    assert len(ir.history(engine, context, id, 2, 2)["items"]) == 1
    assert now["source"] == snapshot


def test_quantity_zero_unknown_total_validation_and_restore(
    resources: Resources,
) -> None:
    engine, _, context, snapshot, _ = resources
    id, detail = begin(resources)
    key = snapshot["rows"][0]["source_key"]
    bad = command(
        detail,
        [
            dict(type="set_size_quantity", source_key=key, size="XS", value="8"),
            dict(
                type="set_location",
                source_key=snapshot["unconfirmed_rows"][0]["source_key"],
                value="WAREHOUSE_1",
            ),
        ],
    )
    with pytest.raises(ApiError) as caught:
        ir.preview(engine, context, id, bad)
    assert (
        cast(dict[str, Any], caught.value.detail)["code"]
        == "inventory_review_quantity_conflict"
    )
    assert ir.detail(engine, context, id)["revision"] == 0
    good = command(
        detail,
        [
            dict(type="set_size_quantity", source_key=key, size="XS", value="8"),
            dict(type="set_reviewed_total", source_key=key, value="19"),
            dict(type="set_size_quantity", source_key=key, size="XXL", value="0"),
        ],
    )
    save(engine, context, id, good)
    now = ir.detail(engine, context, id)
    row = now["effective"]["rows"][0]
    assert row["quantities"]["XXL"]["units"] == "0"
    assert row["quantities"]["3XL"]["units"] is None
    assert row["quantities"]["XS"]["raw"] == "7"
    save(
        engine,
        context,
        id,
        command(
            now,
            [
                dict(type="restore_source_field", source_key=key, field="XS"),
                dict(
                    type="restore_source_field", source_key=key, field="reviewed_total"
                ),
            ],
        ),
    )
    now = ir.detail(engine, context, id)
    assert now["effective"]["rows"][0]["stock_units"] == "18"
    save(
        engine,
        context,
        id,
        command(now, [dict(type="set_reviewed_total", source_key=key, value=None)]),
    )
    assert (
        ir.detail(engine, context, id)["effective"]["summary"]["incomplete_total_rows"]
        == 1
    )


def test_complete_sizes_must_equal_total_and_limits(resources: Resources) -> None:
    engine, _, context, snapshot, _ = resources
    id, detail = begin(resources)
    key = snapshot["rows"][0]["source_key"]
    changes = [
        dict(type="set_size_quantity", source_key=key, size=size, value="0")
        for size in ("XXL", "3XL")
    ]
    changes.append(dict(type="set_reviewed_total", source_key=key, value="19"))
    with pytest.raises(ApiError):
        ir.preview(engine, context, id, command(detail, changes))
    for value in ("-1", "1.2", "1000000000000000000"):
        with pytest.raises(ValueError):
            command(
                detail, [dict(type="set_reviewed_total", source_key=key, value=value)]
            )
    with pytest.raises(ValueError):
        command(
            detail, [dict(type="set_location", source_key=key, value="WAREHOUSE_1")] * 2
        )
    with pytest.raises(ValueError):
        command(
            detail,
            [
                dict(type="set_location", source_key=str(i), value="WAREHOUSE_1")
                for i in range(101)
            ],
        )
    with pytest.raises(ValueError):
        command(detail, [])
    with pytest.raises(ValueError):
        command(
            detail,
            [dict(type="set_location", source_key=key, value="WAREHOUSE_1", site_id=2)],
        )


def test_date_cutoff_unknown_and_restore(resources: Resources) -> None:
    engine, _, context, _, _ = resources
    id, detail = begin(resources)
    assert detail["effective"]["stocktaken_on"] is None
    save(
        engine,
        context,
        id,
        command(
            detail,
            [
                dict(type="set_stocktake_date", value="2026-10-09"),
                dict(type="set_cutoff_note", value="虚构截止"),
            ],
        ),
    )
    now = ir.detail(engine, context, id)
    assert now["effective"]["stocktaken_on"] == "2026-10-09"
    save(
        engine, context, id, command(now, [dict(type="set_stocktake_date", value=None)])
    )
    assert ir.detail(engine, context, id)["effective"]["stocktaken_on"] is None
    assert ir.detail(engine, context, id)["effective"]["posting_enabled"] is False


def test_idempotency_receipt_source_and_cross_site(resources: Resources) -> None:
    engine, settings, context, snapshot, source_body = resources
    id, detail = begin(resources)
    body = command(detail, [dict(type="set_stocktake_date", value="2026-10-09")])
    token = uuid4()
    result, payload = save(engine, context, id, body, token)
    assert ir.save(engine, context, id, payload, token)["replayed"] is True
    assert (
        ir.operation(engine, context, id, token)["saved_revision"]
        == result["saved_revision"]
    )
    with pytest.raises(ApiError):
        ir.save(
            engine,
            context,
            id,
            payload.model_copy(update={"reason": "不同输入"}),
            token,
        )
    for action in (
        lambda: ir.detail(engine, replace(context, site_id=2), id),
        lambda: ir.operation(engine, replace(context, site_id=2), id, token),
    ):
        with pytest.raises(ApiError) as caught:
            cast(Callable[[], Any], action)()
        assert caught.value.status_code == 404
    snapshot["source_digest"] = hashlib.sha256(uuid4().bytes).hexdigest()
    new_body = source_body.model_copy(
        update={"source_digest": snapshot["source_digest"]}
    )
    new, created = ir.start(engine, settings, context, new_body)
    assert (
        created and new["revision"] == 0 and new["effective"]["stocktaken_on"] is None
    )
    assert ir.detail(engine, context, id)["revision"] == 1
    with pytest.raises(ApiError):
        ir.save(engine, context, UUID(new["review_id"]), payload, token)


def test_concurrent_version_only_one_commit(resources: Resources) -> None:
    engine, _, context, _, _ = resources
    id, detail = begin(resources)
    body = command(detail, [dict(type="set_stocktake_date", value="2026-10-09")])
    preview = ir.preview(engine, context, id, body)
    payload = ir.SaveCommand(**body.model_dump(), preview_hash=preview["preview_hash"])
    barrier = Barrier(2)

    def run(_: int) -> dict[str, Any] | int:
        barrier.wait()
        try:
            return ir.save(engine, context, id, payload, uuid4())
        except ApiError as error:
            return error.status_code

    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(run, range(2)))
    assert sum(isinstance(item, dict) for item in results) == 1
    assert 409 in results
    assert ir.detail(engine, context, id)["revision"] == 1
    assert len(ir.history(engine, context, id, 999, 20)["items"]) == 1


def test_transaction_rollback_and_database_guards(resources: Resources) -> None:
    engine, _, context, _, _ = resources
    id, detail = begin(resources)
    body = command(detail, [dict(type="set_stocktake_date", value="2026-10-09")])
    preview = ir.preview(engine, context, id, body)
    payload = ir.SaveCommand(**body.model_dump(), preview_hash=preview["preview_hash"])

    def reject(
        conn: Any, cursor: Any, statement: str, parameters: Any, ctx: Any, many: bool
    ) -> None:
        if statement.startswith("UPDATE production_inventory_reviews"):
            raise RuntimeError("injected task-only failure")

    sa.event.listen(engine, "before_cursor_execute", reject)
    try:
        with pytest.raises(RuntimeError):
            ir.save(engine, context, id, payload, uuid4())
    finally:
        sa.event.remove(engine, "before_cursor_execute", reject)
    assert ir.detail(engine, context, id)["revision"] == 0
    assert not ir.history(engine, context, id, 999, 20)["items"]
    _result, _ = save(engine, context, id, body)
    for query in (
        "UPDATE production_inventory_review_revisions "
        "SET reason='tamper' WHERE review_id=:id",
        "UPDATE production_inventory_reviews "
        "SET source_name='tamper' WHERE review_id=:id",
    ):
        with pytest.raises(DBAPIError), engine.begin() as c:
            c.execute(sa.text(query), {"id": id.bytes})
    with engine.connect() as c:
        grants = " ".join(str(row[0]) for row in c.exec_driver_sql("SHOW GRANTS"))
    assert "CREATE" not in grants and "TRIGGER" not in grants


def test_http_roles_csrf_and_strict_body() -> None:
    password = (
        (TASK / "accounts.txt")
        .read_text(encoding="utf-8")
        .split("临时密码：")[1]
        .strip()
    )
    for role in ("admin", "data_manager", "viewer"):
        with httpx2.Client(
            base_url=os.getenv(
                "APP_INVENTORY_REVIEW_HTTP_BASE_URL", "http://127.0.0.1:23022"
            ),
            trust_env=False,
        ) as client:
            token = client.get("/api/auth/csrf").json()["csrf_token"]
            response = client.post(
                "/api/auth/login",
                headers={"X-CSRF-Token": token},
                json={"username": "inventory.review." + role, "password": password},
            )
            assert response.status_code == 200
            csrf = response.json()["csrf_token"]
            source = client.get("/api/production/inventory-reviews/current").json()[
                "source"
            ]
            body = {
                key: source[key] for key in ("source_digest", "source_manifest_digest")
            }
            assert (
                client.post("/api/production/inventory-reviews", json=body).status_code
                == 403
            )
            response = client.post(
                "/api/production/inventory-reviews",
                headers={"X-CSRF-Token": csrf},
                json=body,
            )
            assert response.status_code in ((403,) if role == "viewer" else (200, 201))
            if role != "viewer":
                id = response.json()["review_id"]
                assert (
                    client.post(
                        "/api/production/inventory-reviews/" + id + "/preview",
                        headers={"X-CSRF-Token": csrf},
                        json={"site_id": 2},
                    ).status_code
                    == 422
                )


def test_effective_summary_and_unresolved_display_groups(resources: Resources) -> None:
    _, _, _, snapshot, _ = resources
    key = snapshot["rows"][0]["source_key"]
    effective = ir.effective(
        snapshot, {"rows": {key: {"XS": "8", "reviewed_total": "19"}}}
    )
    assert effective["summary"]["literal_units"] == "19"
    assert effective["summary"]["warehouse_1_literal_units"] == "19"
    first = deepcopy(snapshot["rows"][0])
    first["style_code"] = ""
    second = deepcopy(first)
    second["source_key"] = "虚构另一行"
    source = deepcopy(snapshot)
    source["rows"] = [first, second]
    result = ir.effective(source, {})
    assert result["summary"]["product_count"] == 2
    assert result["summary"]["color_count"] == 2
