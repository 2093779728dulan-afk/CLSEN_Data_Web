"""Fictional export contracts: source columns, saved decisions and read scope."""

# ruff: noqa: RUF001
from copy import deepcopy
from io import BytesIO
from typing import Any
from uuid import uuid4

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api import production
from app.api.dependencies import get_current_site_context, get_database_engine
from app.api.errors import ApiError
from app.config import Settings
from app.production import inventory_review as ir
from app.production.inventory_export import HEADERS, export_rows, inventory_workbook
from app.production.inventory_snapshot import parse_inventory_table, warehouse_1_view
from app.site_context import CurrentSiteContext
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def snapshot() -> dict[str, Any]:
    lines = [
        list(HEADERS),
        ["0011", "Navy", "", "2", "0", "/", "", "", "", "2", "新仓库"],
        ["0011", "Black", "1", "0", "0", "0", "0", "0", "0", "1", "新仓库"],
        ["QA-2", "Olive", "4", "0", "0", "0", "0", "0", "0", "4", ""],
        ["QA-3", "Red", "3", "0", "0", "0", "0", "0", "0", "3", "新仓库"],
    ]
    content = ("\n".join("   ".join(line) for line in lines) + "\n").encode()
    return dict(
        warehouse_1_view(parse_inventory_table(content), "DECLARED_TOTAL"),
        filename="虚构库存.txt",
        source_digest="a" * 64,
        stocktaken_on="2026-10-14",
        cutoff_note="总负责人：虚构负责人",
    )


def read(content: bytes) -> Any:
    return openpyxl.load_workbook(BytesIO(content), data_only=False)


def test_original_columns_text_codes_zero_unknown_and_no_mutation(
    snapshot: dict[str, Any],
) -> None:
    before = deepcopy(snapshot)
    book = read(inventory_workbook(snapshot, review_id="QA", revision=2))
    sheet = book["库存表"]
    assert tuple(cell.value for cell in sheet[1]) == HEADERS
    assert sheet.max_row == 5 and sheet.max_column == 11
    assert list(sheet.values)[1] == (
        "0011",
        "Navy",
        None,
        2,
        0,
        "/",
        None,
        None,
        None,
        2,
        "新仓库",
    )
    assert sheet["A2"].data_type == "s" and sheet["E2"].data_type == "n"
    assert list(book["导出说明"].values)[8] == ("已保存修订", 2)
    assert "虚构负责人" in str(book["导出说明"]["B5"].value)
    assert snapshot == before


def test_saved_zero_and_total_take_precedence_over_original_raw(
    snapshot: dict[str, Any],
) -> None:
    row = snapshot["rows"][0]
    row["quantities"]["L"] |= {"state": "LITERAL", "units": "0"}
    row["reviewed_total"] = "9"
    sheet = read(inventory_workbook(snapshot))["库存表"]
    assert sheet["F2"].value == 0 and sheet["J2"].value == 9
    row["quantities"]["S"] |= {"state": "UNKNOWN", "units": None}
    row["reviewed_total"] = None
    sheet = read(inventory_workbook(snapshot))["库存表"]
    assert sheet["D2"].value == "待核" and sheet["J2"].value == "待核"


def test_filters_whole_product_all_colors_and_pending_rows(
    snapshot: dict[str, Any],
) -> None:
    assert [row["color"] for row in export_rows(snapshot, " navy ")] == [
        "Navy",
        "Black",
    ]
    assert len(export_rows(snapshot, "0011", "quantity")) == 2
    assert export_rows(snapshot, "Olive")[0]["location_group"] == "UNCONFIRMED"
    assert len(export_rows(snapshot)) == 4
    with pytest.raises(ApiError, match="没有可导出"):
        inventory_workbook(snapshot, query="no-match")


def test_formula_text_and_large_quantities_are_not_changed_by_excel(
    snapshot: dict[str, Any],
) -> None:
    row = snapshot["rows"][0]
    row["color"] = "=1+1"
    row["quantities"]["L"] = {
        "state": "ADDITION_REFERENCE",
        "raw": "=2+3",
        "units": "5",
    }
    row["quantities"]["M"] = {
        "state": "LITERAL",
        "raw": "123456789012345678",
        "units": "123456789012345678",
    }
    sheet = read(inventory_workbook(snapshot))["库存表"]
    assert sheet["B2"].value == "=1+1" and sheet["B2"].data_type == "s"
    assert sheet["F2"].value == "=2+3" and sheet["F2"].data_type == "s"
    assert sheet["E2"].value == "123456789012345678" and sheet["E2"].data_type == "s"


@pytest.fixture
def api(
    snapshot: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, str, list[int]]:
    app = FastAPI()
    app.include_router(production.router)
    app.state.settings = Settings()
    context = CurrentSiteContext(
        1, frozenset({"viewer"}), 1, "QA", "QA", 1, 1, "UTC", "UTC", "USD"
    )
    app.dependency_overrides[get_current_site_context] = lambda: context
    app.dependency_overrides[get_database_engine] = lambda: object()
    calls: list[int] = []
    identifier = str(uuid4())

    def detail(
        _engine: object, scope: CurrentSiteContext, _id: object
    ) -> dict[str, Any]:
        calls.append(scope.site_id)
        return {"effective": snapshot, "revision": 2}

    monkeypatch.setattr(ir, "detail", detail)
    monkeypatch.setattr(production, "inventory_snapshot", lambda *_: snapshot)
    return TestClient(app), identifier, calls


def test_read_only_viewer_export_fixed_revision_and_filter(
    api: tuple[TestClient, str, list[int]],
) -> None:
    client, identifier, calls = api
    response = client.get(
        "/api/production/inventory-export",
        params={
            "review_id": identifier,
            "revision": 2,
            "source_digest": "a" * 64,
            "q": "Navy",
        },
    )
    assert response.status_code == 200 and calls == [1]
    assert response.headers["cache-control"] == "no-store"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert read(response.content)["库存表"].max_row == 3


@pytest.mark.parametrize("changes", [{"revision": 1}, {"source_digest": "b" * 64}])
def test_rejects_stale_page(
    api: tuple[TestClient, str, list[int]], changes: dict[str, Any]
) -> None:
    client, identifier, _ = api
    params: dict[str, Any] = (
        dict(review_id=identifier, revision=2, source_digest="a" * 64) | changes
    )
    response = client.get("/api/production/inventory-export", params=params)
    assert response.status_code == 409
    assert "刷新" in response.json()["detail"]["message"]


def test_original_source_export_does_not_create_review(
    api: tuple[TestClient, str, list[int]],
) -> None:
    client, _, calls = api
    response = client.get(
        "/api/production/inventory-export",
        params={"source_digest": "a" * 64, "source_only": True},
    )
    assert response.status_code == 200 and not calls
    assert read(response.content)["库存表"]["F2"].value == "/"
