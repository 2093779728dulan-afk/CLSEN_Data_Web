"""Inventory uses the existing authenticated site and server-owned SKU authority."""

import base64
import subprocess
import sys
import tomllib
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx2
import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api import production
from app.api.catalog_common import catalog_write_context
from app.api.dependencies import get_current_site_context, get_database_engine
from app.api.errors import ApiError
from app.config import Settings
from app.production import client as production_client
from app.site_context import CurrentSiteContext
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_application_import_uses_declared_runtime_http_dependency() -> None:
    backend = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.abc
import sys

class NoLegacyHttpx(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'httpx' or fullname.startswith('httpx.'):
            raise ModuleNotFoundError('Legacy httpx is not a locked dependency')

sys.meta_path.insert(0, NoLegacyHttpx())
import app.main
""",
        ],
        cwd=backend,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    metadata = tomllib.loads((backend / "pyproject.toml").read_text(encoding="utf-8"))
    assert "httpx2>=2.9,<3" in metadata["project"]["dependencies"]


@pytest.mark.parametrize("binary", [False, True])
def test_production_transport_preserves_request_contract(
    monkeypatch: pytest.MonkeyPatch, binary: bool
) -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        assert request.extensions["timeout"] == {
            "connect": 3,
            "read": 15,
            "write": 15,
            "pool": 15,
        }
        assert request.headers["Authorization"] == "Bearer " + "fictional-token-" * 3
        assert request.headers["X-Production-Site"] == "1"
        assert request.headers["X-Production-Actor"] == "4"
        assert request.headers["X-Production-Roles"] == "admin,viewer"
        assert request.headers["Idempotency-Key"] == "fictional-operation"
        assert (
            base64.urlsafe_b64decode(request.headers["X-Production-Actor-Name"]).decode(
                "utf-8"
            )
            == "fictional-actor"
        )
        assert request.url.path == "/internal/production/inventory/documents"
        assert request.url.params.multi_items() == [("tag", "one"), ("tag", "two")]
        assert request.read() == b'{"_actor_name":"fictional-actor"}'
        return (
            httpx2.Response(200, content=b"fictional-export")
            if binary
            else httpx2.Response(200, json={"id": "81"})
        )

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:1")
    monkeypatch.setattr(
        httpx2,
        "Client",
        partial(httpx2.Client, transport=httpx2.MockTransport(respond)),
    )
    context = CurrentSiteContext(
        4,
        frozenset({"viewer", "admin"}),
        1,
        "DEMO_LOCAL_ONLY",
        "Fake",
        1,
        1,
        "UTC",
        "UTC",
        "USD",
    )
    result = production_client.production_request(
        Settings(
            production_service_url="https://production.invalid/",
            production_service_token="fictional-token-" * 3,
        ),
        context,
        "POST",
        "inventory/documents",
        body={"_actor_name": "fictional-actor"},
        query=[("tag", "one"), ("tag", "two")],
        operation_key="fictional-operation",
        binary=binary,
    )
    assert result == (b"fictional-export" if binary else {"id": "81"})
    assert len(requests) == 1


def test_production_transport_timeout_does_not_retry_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx2.Request] = []

    def timeout(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        raise httpx2.ReadTimeout("Fictional lost response", request=request)

    monkeypatch.setattr(
        httpx2,
        "Client",
        partial(httpx2.Client, transport=httpx2.MockTransport(timeout)),
    )
    context = CurrentSiteContext(
        4, frozenset({"admin"}), 1, "DEMO_LOCAL_ONLY", "Fake", 1, 1, "UTC", "UTC", "USD"
    )
    with pytest.raises(ApiError) as caught:
        production_client.production_request(
            Settings(
                production_service_url="https://production.invalid",
                production_service_token="fictional-token-" * 3,
            ),
            context,
            "POST",
            "inventory/documents/81/confirm",
            operation_key="fictional-operation",
        )
    assert caught.value.status_code == 503
    assert cast(dict[str, object], cast(dict[str, str], caught.value.detail))[
        "code"
    ] == ("production_result_unknown")
    assert len(requests) == 1


@pytest.fixture
def gateway(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[TestClient, list[dict[str, Any]], FastAPI]:
    app = FastAPI()
    app.include_router(production.router)
    app.state.settings = Settings(production_inventory_source_root=str(tmp_path))
    context = CurrentSiteContext(
        4, frozenset({"admin"}), 1, "DEMO_LOCAL_ONLY", "Fake", 1, 1, "UTC", "UTC", "USD"
    )
    app.dependency_overrides[get_current_site_context] = lambda: context
    app.dependency_overrides[catalog_write_context] = lambda: context
    app.dependency_overrides[get_database_engine] = lambda: object()
    calls: list[dict[str, Any]] = []

    def send(*args: Any, **kwargs: Any) -> object:
        calls.append({"args": args, **kwargs})
        return {"id": "81", "items": []}

    monkeypatch.setattr(production, "production_request", send)
    monkeypatch.setattr(
        production,
        "production_skus",
        lambda *args: {
            "1001": {"status": "active", "catalog_version": "DEMO_LOCAL_ONLY-v1"}
        },
    )
    monkeypatch.setattr(
        production, "_operation_actor", lambda *args: "qa.admin · 虚构管理员"
    )
    return TestClient(app), calls, app


@pytest.mark.parametrize("kind", ["receipt", "packing"])
def test_operation_tables_are_bound_to_the_current_order_and_preview_only_reads(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:

    import openpyxl

    client, calls, _ = gateway
    order = {
        "id": "81",
        "system_number": "QA-81",
        "revision": "6",
        "status": "CONFIRMED",
        "lines": [{"id": "101", "sku_id": "1001", "sku_label": "QA-M"}],
    }

    def send(*args: Any, **kwargs: Any) -> object:
        calls.append({"args": args, **kwargs})
        return order

    monkeypatch.setattr(production, "production_request", send)
    monkeypatch.setattr(
        production,
        "production_skus",
        lambda *args: {"1001": {"style_code": "2301", "code": "2301-Blue-M"}},
    )
    path = f"/api/production/orders/81/tables/{kind}"
    response = client.get(path + "/template?expected_revision=6")
    assert response.status_code == 200
    book = openpyxl.load_workbook(BytesIO(response.content))
    sheet = book.worksheets[0]
    if kind == "receipt":
        sheet.cell(2, 4, 3)
    else:
        sheet.cell(2, 1, "QA-BOX")
        sheet.cell(2, 4, "3")
    output = BytesIO()
    book.save(output)
    result = client.post(
        path + "/preview?expected_revision=6&filename=qa.xlsx",
        content=output.getvalue(),
    )
    assert result.status_code == 200, result.text
    assert result.json()["total_units"] == "3"
    assert result.json()["issues"] == []
    assert all(call["args"][2:4] == ("GET", "orders/81") for call in calls)
    assert (
        client.post(
            path + "/preview?expected_revision=5", content=output.getvalue()
        ).status_code
        == 409
    )
    book.close()


def test_operation_table_preview_requires_manager_role(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
) -> None:
    client, calls, app = gateway
    viewer = CurrentSiteContext(
        4,
        frozenset({"viewer"}),
        1,
        "DEMO_LOCAL_ONLY",
        "Fake",
        1,
        1,
        "UTC",
        "UTC",
        "USD",
    )
    app.dependency_overrides[catalog_write_context] = lambda: viewer
    assert (
        client.post(
            "/api/production/orders/81/tables/receipt/preview?expected_revision=1",
            content=b"x",
        ).status_code
        == 403
    )
    assert calls == []


def test_latest_order_preview_preserves_original_and_checks_catalog_style(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.production.order_tables import render_order_table

    client, calls, _ = gateway
    catalog = {
        "1001": {
            "sku_id": "1001",
            "label": "QA Blue M",
            "status": "active",
            "style_code": "0012",
            "code": "0012-sand beige-M",
        }
    }
    monkeypatch.setattr(production, "production_skus", lambda *a: catalog)
    monkeypatch.setattr(
        production,
        "resolve_standard_codes",
        lambda *a, **k: {"0012-sand beige-M": catalog["1001"]},
    )
    raw = render_order_table(
        {
            "id": "81",
            "revision": "2",
            "business_date": "2026-10-30",
            "lines": [{"sku_id": "1001", "expected_units": "7"}],
        },
        catalog,
        site_id=1,
    )
    import io

    book = openpyxl.load_workbook(io.BytesIO(raw))
    del book["说明"]
    book.create_sheet("Sheet1").append(["old stock", -999])
    out = io.BytesIO()
    book.save(out)
    book.close()
    raw = out.getvalue()
    response = client.post(
        "/api/production/files/orders/preview?mode=create&workbench_order=true&filename=qa.xlsx",
        content=raw,
    )
    assert response.status_code == 200, response.text
    body = calls[-1]["body"]
    assert base64.b64decode(body["_original_file_base64"]) == raw
    assert body["_order_source"]["source_units"] == "7"
    assert body["_order_source"]["rows"][0]["source_ref"]["cells"]["sku_code"] == "C2"
    assert body["_order_source"]["issues"] == []
    normalized = openpyxl.load_workbook(
        io.BytesIO(base64.b64decode(body["file_base64"]))
    )
    assert normalized.active.title == "预计订单_v1"
    assert normalized.active["C2"].value == "0012-sand beige-M"
    normalized.close()
    catalog["1001"]["style_code"] = "OTHER"
    assert (
        client.post(
            "/api/production/files/orders/preview?mode=create&workbench_order=true&filename=qa.xlsx",
            content=raw,
        ).status_code
        == 200
    )
    assert "所属款号" in calls[-1]["body"]["_order_source"]["issues"][0]["message"]


@pytest.mark.parametrize("changed", [False, True])
def test_exported_order_reimport_reads_original_without_writing_a_second_preview(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
    monkeypatch: pytest.MonkeyPatch,
    changed: bool,
) -> None:
    from app.production.order_tables import render_order_table

    client, calls, _ = gateway
    document = {
        "id": "81",
        "revision": "2",
        "business_date": "2026-10-30",
        "status": "CONFIRMED",
        "lines": [{"sku_id": "1001", "expected_units": "7"}],
    }
    catalog = {
        "1001": {
            "sku_id": "1001",
            "label": "QA Blue M",
            "status": "active",
            "style_code": "0012",
            "code": "0012-sand beige-M",
        }
    }
    monkeypatch.setattr(production, "production_skus", lambda *a: catalog)
    monkeypatch.setattr(
        production,
        "resolve_standard_codes",
        lambda *a, **k: {"0012-sand beige-M": catalog["1001"]},
    )

    def send(*args: Any, **kwargs: Any) -> object:
        calls.append({"args": args, **kwargs})
        return document

    monkeypatch.setattr(production, "production_request", send)
    raw = render_order_table(document, catalog, site_id=1)
    if changed:
        document["revision"] = "3"
    response = client.post(
        "/api/production/files/orders/preview?mode=create&workbench_order=true&filename=qa.xlsx",
        content=raw,
    )
    assert response.status_code == 200, response.text
    assert response.json()["duplicate_document"]["id"] == "81"
    assert bool(response.json()["issues"]) == changed
    assert response.json()["preview_id"] == ""
    assert [c["args"][2:] for c in calls] == [("GET", "orders/81")]


def test_order_table_preview_forwards_explicit_context_without_trusting_authority(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io

    client, calls, _ = gateway
    monkeypatch.setattr(production, "resolve_standard_codes", lambda *a, **k: {})
    book = openpyxl.Workbook()
    book.active.title = "预计订单_v1"
    book.active.append(["业务订单号（可选）", "下单日期", "SKU", "预计数量", "备注"])  # noqa: RUF001 - exact template header
    book.active.append(["QA-ONLY", "2026-10-23", "DEMO-SKU", "12", "fictional"])
    output = io.BytesIO()
    book.save(output)
    book.close()
    response = client.post(
        "/api/production/files/orders/preview",
        params={
            "mode": "create",
            "workbench_order": "true",
            "factory_id": "3",
            "receipt_warehouse_id": "900",
            "receipt_owner_id": "2",
            "destination": "QA destination",
            "destination_id": "10",
            "destination_type": "WAREHOUSE",
            "site_id": "999",
            "_catalog": "forged",
        },
        content=output.getvalue(),
    )
    assert response.status_code == 200, response.text
    body = calls[-1]["body"]
    assert body["workbench_order"] is True
    assert (
        body["factory_id"],
        body["receipt_warehouse_id"],
        body["receipt_owner_id"],
    ) == ("3", "900", "2")
    assert body["destination_id"] == "10"
    assert body["_catalog"] != "forged"
    assert "site_id" not in body
    legacy = client.post(
        "/api/production/files/orders/preview?mode=create", content=output.getvalue()
    )
    assert legacy.status_code == 200
    assert "workbench_order" not in calls[-1]["body"]
    book = openpyxl.Workbook()
    book.active.title = "预计订单_v3"
    book.active.append(["业务订单号", "下单日期", "商品规格ID", "预计数量", "备注"])
    book.active.append(["QA-V3", "2026-10-23", "1001", "12", "fictional"])
    output = io.BytesIO()
    book.save(output)
    book.close()

    def reject_code_resolution(*args: Any, **kwargs: Any) -> object:
        raise AssertionError("Spec IDs must not enter seller-SKU matching")

    monkeypatch.setattr(production, "resolve_standard_codes", reject_code_resolution)
    assert (
        client.post(
            "/api/production/files/orders/preview?mode=create&workbench_order=true&factory_id=3&receipt_warehouse_id=900&receipt_owner_id=2",
            content=output.getvalue(),
        ).status_code
        == 200
    )
    assert "_resolved_codes" not in calls[-1]["body"]


@pytest.mark.parametrize(
    "path",
    [
        "documents",
        "openings/confirm",
        "documents/81/confirm",
        "reservations",
        "holds/81/release",
        "loans/81/settle",
        "plans/81/cancel",
    ],
)
def test_inventory_commands_replace_untrusted_identity_and_name(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI], path: str
) -> None:
    client, calls, _ = gateway
    token = str(uuid4())
    response = client.post(
        f"/api/production/inventory/{path}",
        headers={"Idempotency-Key": token},
        json={
            "operation_token": token,
            "_catalog": {"forged": True},
            "_actor_name": "forged",
            "site_id": "9",
        },
    )
    assert response.status_code == 200
    sent = calls[0]
    assert sent["args"][1].site_id == 1
    assert sent["body"]["_catalog"] == {
        "1001": {"status": "active", "catalog_version": "DEMO_LOCAL_ONLY-v1"}
    }
    assert sent["body"]["_actor_name"] == "qa.admin · 虚构管理员"
    assert sent["operation_key"] == token


def test_inventory_read_routes_preserve_filters_and_fixed_id(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
) -> None:
    client, calls, _ = gateway
    assert (
        client.get(
            "/api/production/inventory/history?actor_id=4&from=2026-10-14"
        ).status_code
        == 200
    )
    assert calls[-1]["args"][3] == "inventory/history"
    assert calls[-1]["query"] == [("actor_id", "4"), ("from", "2026-10-14")]
    assert client.get("/api/production/inventory/documents/81").status_code == 200
    assert calls[-1]["args"][3] == "inventory/documents/81"


def test_transit_batch_read_preserves_explicit_batch_and_sku_filter(
    gateway: Any,
) -> None:
    client, calls, _ = gateway
    response = client.get(
        "/api/production/inventory/transit-batches?shipment_id=77&sku_id=1001&page=2&page_size=5"
    )
    assert response.status_code == 200
    assert calls[-1]["args"][2:4] == ("GET", "inventory/transit-batches")
    assert calls[-1]["args"][1].site_id == 1
    assert calls[-1]["query"] == [
        ("shipment_id", "77"),
        ("sku_id", "1001"),
        ("page", "2"),
        ("page_size", "5"),
    ]
    calls.clear()
    assert (
        client.get(
            "/api/production/inventory/transit-batches?shipment_id=0"
        ).status_code
        == 422
    )
    assert calls == []


def test_mismatched_operation_cannot_reach_stock_service(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
) -> None:
    client, calls, _ = gateway
    assert (
        client.post(
            "/api/production/inventory/documents",
            headers={"Idempotency-Key": str(uuid4())},
            json={"operation_token": str(uuid4())},
        ).status_code
        == 422
    )
    assert calls == []


def test_workbench_routes_keep_server_context_and_replace_actor(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
) -> None:
    client, calls, _ = gateway
    assert client.get("/api/production/workbench").status_code == 200
    assert client.get("/api/production/factories?q=QA&page=2").status_code == 200
    token = str(uuid4())
    response = client.post(
        "/api/production/factories",
        headers={"Idempotency-Key": token},
        json={
            "operation_token": token,
            "name": "QA Factory",
            "site_id": "999",
            "_actor_name": "forged",
        },
    )
    assert response.status_code == 200
    assert calls[-1]["args"][1].site_id == 1
    assert calls[-1]["body"] == {
        "operation_token": token,
        "name": "QA Factory",
        "_actor_name": "qa.admin · 虚构管理员",
    }
    response = client.post(
        "/api/production/orders/81/production-progress",
        headers={"Idempotency-Key": token},
        json={
            "operation_token": token,
            "expected_revision": "2",
            "lines": [],
            "_catalog": {"forged": {}},
        },
    )
    assert response.status_code == 200
    assert calls[-1]["args"][3] == "orders/81/production-progress"
    assert "1001" in calls[-1]["body"]["_catalog"]


def test_viewer_cannot_create_factory(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
) -> None:
    client, calls, app = gateway
    viewer = CurrentSiteContext(
        6,
        frozenset({"viewer"}),
        1,
        "DEMO_LOCAL_ONLY",
        "Fake",
        1,
        1,
        "UTC",
        "UTC",
        "USD",
    )
    app.dependency_overrides[catalog_write_context] = lambda: viewer
    token = str(uuid4())
    assert (
        client.post(
            "/api/production/factories",
            headers={"Idempotency-Key": token},
            json={"operation_token": token, "name": "QA"},
        ).status_code
        == 403
    )
    assert calls == []


@pytest.mark.parametrize("kind", ["factories", "warehouses"])
def test_directory_routes_preserve_profile_and_strip_authority(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
    kind: str,
) -> None:
    client, calls, _ = gateway
    assert client.get(f"/api/production/{kind}/81").status_code == 200
    token = str(uuid4())
    fields = {
        "name": "QA profile",
        "region": "QA",
        "warehouse_ids": ["1"],
        "type": "FBA",
        "country": "US",
        "seller_account": "QA account",
        "marketplace": "US",
        "status": "INACTIVE",
        "expected_revision": "1",
        "reason": "QA change",
    }
    result = client.put(
        f"/api/production/{kind}/81",
        headers={"Idempotency-Key": token},
        json={
            **fields,
            "operation_token": token,
            "site_id": "999",
            "_actor_name": "forged",
            "_catalog": {"forged": {}},
        },
    )
    assert result.status_code == 200
    assert calls[-1]["args"][3] == f"{kind}/81"
    assert calls[-1]["body"] == {
        **fields,
        "operation_token": token,
        "_actor_name": "qa.admin · 虚构管理员",
    }


def test_viewer_cannot_reach_write_proxy(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
) -> None:
    client, calls, app = gateway
    viewer = CurrentSiteContext(
        6,
        frozenset({"viewer"}),
        1,
        "DEMO_LOCAL_ONLY",
        "Fake",
        1,
        1,
        "UTC",
        "UTC",
        "USD",
    )
    app.dependency_overrides[catalog_write_context] = lambda: viewer
    token = str(uuid4())
    assert (
        client.post(
            "/api/production/inventory/documents",
            headers={"Idempotency-Key": token},
            json={"operation_token": token},
        ).status_code
        == 403
    )
    assert calls == []


def test_destination_state_reports_current_and_original_catalog_versions(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = gateway
    monkeypatch.setattr(
        production,
        "production_request",
        lambda *args, **kwargs: {
            "bindings": [
                {"sku_id": "1001", "sku_label": "Old", "catalog_version": "1:1"}
            ]
        },
    )
    monkeypatch.setattr(
        production,
        "production_skus",
        lambda *args: {
            "1001": {"status": "active", "catalog_version": "2:2", "label": "New"}
        },
    )
    response = client.get("/api/production/inventory/destination-state?shipment_id=3")
    assert response.status_code == 200
    item = response.json()["bindings"][0]
    assert item["source_catalog_version"] == "1:1"
    assert item["catalog_version"] == "2:2"
    assert item["source_sku_label"] == "Old"
    assert item["sku_label"] == "New"


def test_receipt_batch_routes_revalidate_each_order_in_session_scope(
    gateway: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from io import BytesIO

    import openpyxl

    client, calls, _ = gateway
    source = {
        "id": "10",
        "system_number": "QA-SYSTEM-10",
        "revision": "2",
        "status": "CONFIRMED",
        "business_number": "QA-10",
        "lines": [{"id": "101", "sku_id": "1001", "sku_label": "QA-M"}],
    }

    def send(*args: Any, **kwargs: Any) -> Any:
        calls.append({"args": args, **kwargs})
        assert args[1].site_id == 1
        if args[3] == "orders/11":
            return {
                **source,
                "id": "11",
                "system_number": "QA-SYSTEM-11",
                "lines": [{"id": "102", "sku_id": "1001", "sku_label": "QA-M"}],
            }
        return source

    monkeypatch.setattr(production, "production_request", send)
    monkeypatch.setattr(
        production,
        "production_skus",
        lambda *args: {"1001": {"style_code": "2301", "code": "2301-Blue-M"}},
    )
    scope = "orders=10%3A2%2C11%3A2"
    response = client.get("/api/production/receipt-batches/sources?" + scope)
    assert response.status_code == 200 and len(response.json()["lines"]) == 2
    template = client.get("/api/production/receipt-batches/table/template?" + scope)
    assert template.status_code == 200
    book = openpyxl.load_workbook(BytesIO(template.content))
    book.worksheets[0]["D2"] = 3
    book.worksheets[0]["D3"] = 2
    output = BytesIO()
    book.save(output)
    book.close()
    result = client.post(
        "/api/production/receipt-batches/table/preview?"
        + scope
        + "&filename=batch.xlsx",
        content=output.getvalue(),
    )
    assert result.status_code == 200 and result.json()["total_units"] == "5"
    assert [(r["order_line_id"], r["sku_id"]) for r in result.json()["rows"]] == [
        ("101", "1001"),
        ("102", "1001"),
    ]
    assert all(c["args"][2] == "GET" for c in calls)
    assert (
        client.get("/api/production/receipt-batches/sources?orders=10:1").status_code
        == 409
    )
    assert (
        client.get(
            "/api/production/receipt-batches/sources?orders=10:2,10:2"
        ).status_code
        == 422
    )


def test_receipt_batch_viewer_cannot_preview(gateway: Any) -> None:
    client, calls, app = gateway
    viewer = CurrentSiteContext(
        6,
        frozenset({"viewer"}),
        1,
        "DEMO_LOCAL_ONLY",
        "Fake",
        1,
        1,
        "UTC",
        "UTC",
        "USD",
    )
    app.dependency_overrides[catalog_write_context] = lambda: viewer
    response = client.post(
        "/api/production/receipt-batches/table/preview?orders=10:2",
        content=b"not-a-book",
    )
    assert response.status_code == 403 and calls == []


@pytest.mark.parametrize("action", ["complete-production", "reopen-production"])
def test_production_completion_commands_keep_server_identity(
    gateway: Any, action: Any
) -> None:
    client, calls, _ = gateway
    token = str(uuid4())
    response = client.post(
        f"/api/production/orders/81/{action}",
        headers={"Idempotency-Key": token},
        json={
            "operation_token": token,
            "expected_revision": "2",
            "_actor_name": "forged",
            "_catalog": {"forged": {}},
        },
    )
    assert response.status_code == 200
    assert calls[-1]["args"][3] == f"orders/81/{action}"
    assert calls[-1]["args"][1].site_id == 1
    assert calls[-1]["body"]["_actor_name"] == "qa.admin · 虚构管理员"
    assert "1001" in calls[-1]["body"]["_catalog"]
    assert "forged" not in calls[-1]["body"]["_catalog"]


def test_editable_count_import_and_original_routes_precede_generic_documents(
    gateway: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, calls, _app = gateway
    scope = {"warehouse_id": "1", "owner_id": "7"}
    catalog = {"1001": {"label": "SIM-M", "status": "active"}}
    monkeypatch.setattr(production, "_dispatch_scope", lambda *args: (scope, catalog))
    template = client.get(
        "/api/production/inventory/count-table/template?warehouse_id=1&owner_id=7"
    )
    assert template.status_code == 200
    book = openpyxl.load_workbook(BytesIO(template.content))
    book.worksheets[0]["D2"] = 0
    output = BytesIO()
    book.save(output)
    book.close()
    response = client.post(
        "/api/production/inventory/count-table/preview?warehouse_id=1&owner_id=7&filename=sim.xlsx",
        content=output.getvalue(),
    )
    assert response.status_code == 200, response.text
    baseline = response.json()["table_baseline"]
    assert baseline["rows"][0]["values"]["实盘总数"] == "0"
    assert (
        client.get(f"/api/production/table-baselines/{baseline['id']}").json()
        == baseline
    )
    original = client.get(f"/api/production/table-baselines/{baseline['id']}/original")
    assert original.status_code == 200 and original.content == output.getvalue()
    assert not calls


def test_order_editable_import_restores_server_owned_file_identity(
    gateway: Any,
) -> None:
    from app.production.table_baselines import remember_baseline

    client, calls, app = gateway
    context = app.dependency_overrides[get_current_site_context]()
    book = openpyxl.Workbook()
    book.active.append(["SKU", "数量"])
    book.active.append(["SIM", 2])
    output = BytesIO()
    book.save(output)
    book.close()
    original = remember_baseline(
        production._table_baseline_root(type("R", (), {"app": app})()),
        context,
        "orders",
        output.getvalue(),
        {
            "filename": "sim.xlsx",
            "issues": [],
            "rows": [{"sku_id": "1001", "sku_label": "SIM", "expected_units": "2"}],
            "command": {
                "source_system": "SIM-SOURCE",
                "source_event_kind": "ORDER",
                "external_event_id": "EV-2",
                "source_batch": "B-1",
            },
        },
    )["table_baseline"]
    key = str(uuid4())
    response = client.post(
        "/api/production/orders",
        headers={"Idempotency-Key": key},
        json={
            "operation_token": key,
            "_table_baseline_id": original["id"],
            "_source_digest": "forged",
            "source_system": "forged",
            "lines": [{"sku_id": "1001", "expected_units": "3"}],
        },
    )
    assert response.status_code == 200, response.text
    body = calls[-1]["body"]
    assert body["_source_digest"] == original["source_id"].rsplit("-", 1)[-1]
    assert body["source_system"] == "SIM-SOURCE"
    assert body["lines"][0]["expected_units"] == "3"
    assert "_table_baseline_id" not in body


@pytest.mark.parametrize("overview", [True, False])
def test_shared_display_filters_overview_and_preserves_other_stock_reads(
    gateway: Any, monkeypatch: pytest.MonkeyPatch, overview: Any
) -> None:
    client, calls, _ = gateway
    monkeypatch.setattr(
        production,
        "production_skus",
        lambda *args: {
            "1001": {"style_id": "2001"},
            "1002": {"style_id": "2001"},
            "1003": {"style_id": "2002"},
        },
    )

    def send(*args: Any, **kwargs: Any) -> Any:
        calls.append({"args": args, **kwargs})
        return (
            {"style_ids": ["2001"], "revision": "1"}
            if args[3] == "inventory/display-settings"
            else {
                "items": [{"sku_id": key} for key in ["1001", "1002", "1003"]],
                "scopes": [],
            }
        )

    monkeypatch.setattr(production, "production_request", send)
    response = client.get(
        "/api/production/inventory/availability" + ("?overview=1" if overview else "")
    )
    assert response.status_code == 200
    assert [item["sku_id"] for item in response.json()["items"]] == (
        ["1001", "1002"] if overview else ["1001", "1002", "1003"]
    )


@pytest.mark.parametrize("resource", ["availability", "sku-locations"])
def test_shared_display_refuses_out_of_scope_detail_links(
    gateway: Any, monkeypatch: pytest.MonkeyPatch, resource: Any
) -> None:
    client, _calls, _ = gateway
    monkeypatch.setattr(
        production,
        "production_skus",
        lambda *args: {"1001": {"style_id": "2001"}, "1003": {"style_id": "2002"}},
    )
    monkeypatch.setattr(
        production,
        "production_request",
        lambda *args, **kwargs: {"style_ids": ["2001"], "revision": "1"},
    )
    response = client.get(
        f"/api/production/inventory/{resource}?overview=1&sku_id=1003"
    )
    assert response.status_code == 403
    assert "inventory_display_forbidden" in response.text


def test_shared_display_uses_server_catalog_and_requires_manager(
    gateway: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, calls, app = gateway
    key = str(uuid4())
    response = client.post(
        "/api/production/inventory/display-settings",
        headers={"Idempotency-Key": key},
        json={
            "operation_token": key,
            "expected_revision": "0",
            "style_ids": [],
            "_catalog": {"spoofed": {}},
        },
    )
    assert response.status_code == 200
    assert calls[-1]["body"]["_catalog"] == {
        "1001": {"status": "active", "catalog_version": "DEMO_LOCAL_ONLY-v1"}
    }
    viewer = CurrentSiteContext(
        4,
        frozenset({"viewer"}),
        1,
        "DEMO_LOCAL_ONLY",
        "Fake",
        1,
        1,
        "UTC",
        "UTC",
        "USD",
    )
    app.dependency_overrides[catalog_write_context] = lambda: viewer
    response = client.post(
        "/api/production/inventory/display-settings",
        headers={"Idempotency-Key": key},
        json={"operation_token": key, "expected_revision": "0", "style_ids": []},
    )
    assert response.status_code == 403
    assert len(calls) == 1


@pytest.mark.parametrize("projection", ["scopes", "summary"])
def test_light_availability_preserves_scope_query_and_rejects_sku_projection(
    gateway: tuple[TestClient, list[dict[str, Any]], FastAPI],
    projection: str,
) -> None:
    client, calls, _ = gateway
    base = f"/api/production/inventory/availability?projection={projection}"
    response = client.get(base + "&warehouse_id=2&owner_id=1")
    assert response.status_code == 200
    assert calls[-1]["query"] == [
        ("projection", projection),
        ("warehouse_id", "2"),
        ("owner_id", "1"),
    ]
    before = len(calls)
    assert client.get(base + "&sku_id=1001").status_code == 422
    assert client.get(base + "&overview=1").status_code == 422
    assert len(calls) == before


def test_explicit_first_transit_page_does_not_receive_unbound_opening(
    gateway: Any,
) -> None:
    client, calls, _ = gateway
    response = client.get(
        "/api/production/inventory/transit-batches?shipment_id=77&sku_id=1001&page=1&page_size=5"
    )
    assert response.status_code == 200
    assert calls[-1]["args"][2:4] == ("GET", "inventory/transit-batches")
    assert not response.json().get("opening_balances")
