"""Warehouse table reads retain originals and never invoke business writers."""

import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api import production as api
from app.api.errors import ApiError


@pytest.mark.parametrize("layout", ["standard", "packing_totals"])
def test_scope_and_original_authority_before_dispatch_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: Any
) -> None:
    context: Any = SimpleNamespace(
        site_id=1, principal_user_id=4, principal_roles={"admin"}
    )
    settings: Any = SimpleNamespace(production_inventory_source_root=str(tmp_path))
    book = openpyxl.Workbook()
    if layout == "standard":
        book.active.append(["SKU", "出货数量"])
        book.active.append(["1112-Black-L", 1])
    else:
        book.active.append([None, None, None, "总数量", "箱1"])
        book.active.append(["1112-Black-L", "B0TEST", "XTEST", 1, 1])
        book.create_sheet("Sheet2")
    output = BytesIO()
    book.save(output)
    book.close()
    raw = output.getvalue()

    async def stream() -> Any:
        yield raw

    request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)), stream=stream
    )
    stock: dict[str, Any] = {
        "scopes": [
            {
                "warehouse_id": "1",
                "owner_id": "7",
                "warehouse_status": "ACTIVE",
                "warehouse_type": "OWN",
            }
        ],
        "items": [{"warehouse_id": "1", "owner_id": "7", "sku_id": "3"}],
    }
    monkeypatch.setattr(api, "production_request", lambda *args, **kwargs: stock)
    monkeypatch.setattr(
        api,
        "production_skus",
        lambda *args: {
            "3": {
                "code": "1112-Black-L",
                "label": "1112-Black-L",
                "style_code": "1112",
                "status": "active",
            }
        },
    )
    monkeypatch.setattr(
        api,
        "_stock_command",
        lambda *args, **kwargs: pytest.fail("preview must not create a business fact"),
    )
    result: Any = asyncio.run(
        api.warehouse_dispatch_preview(
            request, context, cast(Any, None), 1, 7, "stock.xlsx", layout
        )
    )
    assert result["issues"] == [] and result["total_units"] == "1"
    assert (
        api.warehouse_dispatch_original(result["source_id"], request, context).body
        == raw
    )
    other: Any = SimpleNamespace(
        site_id=1, principal_user_id=5, principal_roles={"admin"}
    )
    with pytest.raises(ApiError):
        api.warehouse_dispatch_original(result["source_id"], request, other)
    for warehouse, owner in [(2, 7), (1, 8)]:
        with pytest.raises(ApiError):
            api._dispatch_scope(request, context, cast(Any, None), warehouse, owner)
    stock["scopes"][0]["warehouse_type"] = "FBA"
    with pytest.raises(ApiError):
        api._dispatch_scope(request, context, cast(Any, None), 1, 7)
    stock["scopes"][0]["warehouse_type"] = "OWN"
    stock["scopes"][0]["warehouse_status"] = "INACTIVE"
    with pytest.raises(ApiError):
        api._dispatch_scope(request, context, cast(Any, None), 1, 7)
    viewer: Any = SimpleNamespace(
        site_id=1, principal_user_id=4, principal_roles={"viewer"}
    )
    with pytest.raises(ApiError):
        asyncio.run(
            api.warehouse_dispatch_preview(
                request, viewer, cast(Any, None), 1, 7, "stock.xlsx"
            )
        )
