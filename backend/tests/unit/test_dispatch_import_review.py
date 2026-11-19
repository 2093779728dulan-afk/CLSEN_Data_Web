from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api.errors import ApiError
from app.production.dispatch_import_review import (
    DispatchReviewInput,
    save_dispatch_review,
)
from app.production.source_registry import (
    register_upload,
    uploaded_bytes,
    uploaded_review,
)
from app.production.workbench_tables import preview_dispatch


def fixture(root: Any) -> Any:
    book = openpyxl.Workbook()
    book.active.append(["SKU", "出货数量"])
    for code in ("A", "B", "C"):
        book.active.append([code, 2])
    output = BytesIO()
    book.save(output)
    book.close()
    raw = output.getvalue()
    context: Any = SimpleNamespace(
        site_id=1, principal_user_id=4, principal_roles={"admin"}
    )
    catalog = {str(i): {"code": c, "label": c} for i, c in enumerate("ABCD", 1)}
    scope: dict[str, Any] = {"warehouse_id": "1", "owner_id": "7"}
    preview = preview_dispatch(raw, "source.xlsx", scope, catalog)
    original, _ = register_upload(
        root, context, "shipments", "source.xlsx", raw, preview
    )
    return context, catalog, scope, original["sample_id"], raw


def test_review_retains_original_and_actor_scoped_snapshot(tmp_path: Path) -> None:
    context, catalog, scope, source_id, raw = fixture(tmp_path)
    body = DispatchReviewInput.model_validate(
        dict(
            source_id=source_id,
            warehouse_id="1",
            owner_id="7",
            rows=[
                {"source_row": 2, "sku_id": "2", "actual_units": "1"},
                {"source_row": 4, "sku_id": "3", "actual_units": "2"},
                {"sku_id": "4", "actual_units": "1"},
            ],
        )
    )
    saved = save_dispatch_review(tmp_path, context, body, scope, catalog)
    assert save_dispatch_review(tmp_path, context, body, scope, catalog) == saved
    review = uploaded_review(tmp_path, context, saved["review_id"])
    assert [row["sku_code"] for row in review["baseline"]["source_rows"]] == list("ABC")
    assert [row["source_row"] for row in review["rows"]] == [2, 4, None]
    assert review["rows"][0]["actual_units"] == "1"
    assert uploaded_bytes(tmp_path, context, source_id, "shipments") == raw
    for other in (
        SimpleNamespace(site_id=1, principal_user_id=5),
        SimpleNamespace(site_id=2, principal_user_id=4),
    ):
        with pytest.raises(ApiError):
            uploaded_review(tmp_path, cast(Any, other), saved["review_id"])
    path = tmp_path / "uploads/1/4/dispatch-reviews" / f"{saved['review_id']}.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ApiError):
        uploaded_review(tmp_path, context, saved["review_id"])


@pytest.mark.parametrize(
    "rows",
    [
        [{"source_row": 99, "sku_id": "1", "actual_units": "1"}],
        [{"source_row": 2, "sku_id": "99", "actual_units": "1"}],
        [{"source_row": 2, "sku_id": "1", "actual_units": "9999999999999999999"}],
        [{"source_row": 2, "sku_id": "1", "actual_units": "1"}] * 2,
    ],
)
def test_review_rejects_invalid_lineage_scope_and_quantity(
    tmp_path: Path, rows: Any
) -> None:
    context, catalog, scope, source_id, _ = fixture(tmp_path)
    body = DispatchReviewInput.model_validate(
        dict(source_id=source_id, warehouse_id="1", owner_id="7", rows=rows)
    )
    with pytest.raises(ApiError):
        save_dispatch_review(tmp_path, context, body, scope, catalog)


def test_review_api_string_ids_and_write_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import production as api

    context, catalog, scope, source_id, _ = fixture(tmp_path / "warehouse-dispatch")
    request: Any = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(production_inventory_source_root=str(tmp_path))
            )
        )
    )

    def dispatch_scope(
        request: Any, context: Any, engine: Any, warehouse: Any, owner: Any
    ) -> Any:
        assert (warehouse, owner) == (1, 7)
        return scope, catalog

    monkeypatch.setattr(api, "_dispatch_scope", dispatch_scope)
    body = DispatchReviewInput.model_validate(
        {
            "source_id": source_id,
            "warehouse_id": "1",
            "owner_id": "7",
            "rows": [{"source_row": 2, "sku_id": "1", "actual_units": "1"}],
        }
    )
    saved: Any = api.warehouse_dispatch_review_save(
        request, context, cast(Any, None), body
    )
    assert (
        cast(
            dict[str, Any],
            api.warehouse_dispatch_review_read(saved["review_id"], request, context),
        )["rows"][0]["source_row"]
        == 2
    )
    viewer: Any = SimpleNamespace(
        site_id=1, principal_user_id=4, principal_roles={"viewer"}
    )
    with pytest.raises(ApiError):
        api.warehouse_dispatch_review_save(request, viewer, cast(Any, None), body)


def multiple_sources(root: Any) -> Any:
    context, catalog, scope, first, first_raw = fixture(root)
    book = openpyxl.Workbook()
    book.active.append(["SKU", "出货数量"])
    book.active.append(["A", 4])
    output = BytesIO()
    book.save(output)
    book.close()
    raw = output.getvalue()
    preview = preview_dispatch(raw, "second.xlsx", scope, catalog)
    original, _ = register_upload(
        root, context, "shipments", "second.xlsx", raw, preview
    )
    refs: list[Any] = [
        {"source_id": first, "layout": "standard"},
        {"source_id": original["sample_id"], "layout": "standard"},
    ]
    return context, catalog, scope, refs, first_raw, raw


def test_multiple_packing_lists_keep_same_sku_rows_and_original_positions(
    tmp_path: Path,
) -> None:
    from app.production import dispatch_import_review as reviews

    context, catalog, scope, refs, _, _ = multiple_sources(tmp_path)
    body = reviews.DispatchSourcesInput.model_validate(
        {
            "warehouse_id": "1",
            "owner_id": "7",
            "sources": refs,
        }
    )
    preview = reviews.preview_dispatch_sources(
        tmp_path, context, body.sources, scope, catalog
    )
    assert preview["total_units"] == "10"
    assert [row["row"] for row in preview["source_rows"]] == [2, 3, 4, 5]
    assert preview["source_rows"][-1]["source_filename"] == "second.xlsx"
    assert preview["source_rows"][-1]["source_row"] == 2
    assert [row["sku_id"] for row in preview["source_rows"]] == ["1", "2", "3", "1"]
    assert len(preview["source_files"]) == 2
    with pytest.raises(ApiError):
        reviews.preview_dispatch_sources(
            tmp_path, context, [body.sources[0]] * 2, scope, catalog
        )


def test_multi_source_review_rebuilds_baseline_and_retains_every_original(
    tmp_path: Path,
) -> None:
    context, catalog, scope, refs, first_raw, second_raw = multiple_sources(tmp_path)
    body = DispatchReviewInput.model_validate(
        {
            "source_id": refs[0]["source_id"],
            "sources": refs,
            "warehouse_id": "1",
            "owner_id": "7",
            "rows": [
                {"source_row": 2, "sku_id": "1", "actual_units": "1"},
                {"source_row": 5, "sku_id": "1", "actual_units": "4"},
            ],
        }
    )
    saved = save_dispatch_review(tmp_path, context, body, scope, catalog)
    review = uploaded_review(tmp_path, context, saved["review_id"])
    assert review["baseline"]["source_total_units"] == "10"
    assert [row["actual_units"] for row in review["rows"]] == ["1", "4"]
    for ref, raw in zip(refs, [first_raw, second_raw], strict=True):
        assert uploaded_bytes(tmp_path, context, ref["source_id"], "shipments") == raw
    assert save_dispatch_review(tmp_path, context, body, scope, catalog) == saved


def test_multiple_sources_api_requires_manager_and_reuses_current_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import production as api
    from app.production.dispatch_import_review import DispatchSourcesInput

    context, catalog, scope, refs, _, _ = multiple_sources(
        tmp_path / "warehouse-dispatch"
    )
    request: Any = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(production_inventory_source_root=str(tmp_path))
            )
        )
    )
    monkeypatch.setattr(api, "_dispatch_scope", lambda *args: (scope, catalog))
    body = DispatchSourcesInput(warehouse_id="1", owner_id="7", sources=refs)
    result: Any = api.warehouse_dispatch_combine(
        request, context, cast(Any, None), body
    )
    assert result["source_total_units"] == "10"
    viewer: Any = SimpleNamespace(
        site_id=1, principal_user_id=4, principal_roles={"viewer"}
    )
    with pytest.raises(ApiError):
        api.warehouse_dispatch_combine(request, viewer, cast(Any, None), body)
    other: Any = SimpleNamespace(
        site_id=2, principal_user_id=4, principal_roles={"admin"}
    )
    with pytest.raises(ApiError):
        api.warehouse_dispatch_combine(request, other, cast(Any, None), body)
