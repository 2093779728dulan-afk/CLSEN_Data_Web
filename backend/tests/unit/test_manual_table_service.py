from __future__ import annotations

# ruff: noqa: RUF001 -- Intentional fullwidth test input and Chinese messages.
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from app.api.errors import ApiError
from app.config import Settings
from app.manual_tables.comparison import compare
from app.manual_tables.examples import example
from app.manual_tables.handoff import inventory_snapshot
from app.manual_tables.schemas import Kind, Options
from app.manual_tables.service import ManualTables
from app.site_context import CurrentSiteContext
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine


def context() -> CurrentSiteContext:
    return CurrentSiteContext(
        1, frozenset({"data_manager"}), 1, "QA", "QA", 1, 1, "UTC", "UTC", "USD"
    )


def test_receipt_lookup_uses_shared_lock_with_append_only_privileges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = service(monkeypatch)
    connection = Mock()
    connection.execute.return_value.mappings.return_value.first.return_value = None

    assert svc.replay(connection, str(uuid4()), "request-hash") is None

    statement = connection.execute.call_args.args[0]
    sql = str(statement.compile(dialect=mysql.dialect()))
    assert "LOCK IN SHARE MODE" in sql
    assert "FOR UPDATE" not in sql


def service(monkeypatch: pytest.MonkeyPatch) -> ManualTables:
    svc = ManualTables(
        cast(Engine, None),
        Settings(
            manual_tables_enabled=True,
            manual_tables_root=str(Path(__file__).parent / "unused"),
        ),
        context(),
    )
    products = [
        {
            "sku_id": "31",
            "style_id": "21",
            "style": "99001",
            "color": "Blue",
            "size": "M",
            "code": None,
            "active": True,
            "catalog_version": "7:2",
        }
    ]
    monkeypatch.setattr(svc, "catalog", lambda connection=None: products)
    return svc


def test_formatting_retains_originals_and_matches_only_same_catalog_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.test_manual_table_extraction import workbook

    result = service(monkeypatch).analyze(
        workbook(
            [
                ["款号", "颜色", "尺码", "数量", "SKU"],
                [" ９９００１ ", " BLUE ", "ｍ", 3, "00-AbC-M"],
            ]
        ),
        "inventory",
        Options(),
    )
    row = result["rows"][0]
    assert (row["style"], row["color"], row["size"]) == ("99001", "Blue", "M")
    assert row["match"]["sku_id"] == "31"
    assert row["raw"]["color"] == " BLUE "
    assert row["code"] == "00-AbC-M"
    assert row["units"] == "3"
    assert len(row["format_adjustments"]) == 3
    assert not any(i["blocking"] for i in result["issues"])


def test_formatting_collisions_remain_duplicate_rows_not_summed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.test_manual_table_extraction import workbook

    result = service(monkeypatch).analyze(
        workbook(
            [
                ["款号", "颜色", "尺码", "数量"],
                ["99001", "Blue", "M", 3],
                ["99001", " BLUE ", "ｍ", 4],
            ]
        ),
        "inventory",
        Options(),
    )
    assert result["state"] == "NEEDS_REVIEW"
    assert len(result["rows"]) == 2
    assert result["total_units"] == "7"
    assert any(
        i["code"] == "duplicate_spec" and i["blocking"] for i in result["issues"]
    )


def test_ambiguous_legacy_color_requires_explicit_product_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.test_manual_table_extraction import workbook

    svc = service(monkeypatch)
    products = svc.catalog()
    products[0]["color"] = "Light Blue"
    products.append(products[0] | {"sku_id": "32", "color": "Light  Blue"})
    raw = workbook([["款号", "颜色", "尺码", "数量"], ["99001", "light blue", "M", 3]])
    result = svc.analyze(raw, "inventory", Options())
    assert result["state"] == "NEEDS_REVIEW"
    assert result["rows"][0]["match"]["sku_id"] is None
    assert any(i["code"] == "identity_format" for i in result["issues"])
    chosen = svc.analyze(
        raw,
        "inventory",
        Options(
            decisions={
                "库存!2:M": {
                    "sku_id": "32",
                    "color": "Light  Blue",
                    "reason": "按原物料记录选择第二个商品",
                },
            }
        ),
    )
    assert chosen["rows"][0]["match"]["sku_id"] == "32"
    assert chosen["rows"][0]["raw"]["color"] == "light blue"
    assert chosen["state"] == "READY"


@pytest.mark.parametrize("field", ["style", "color", "size"])
def test_invisible_characters_stay_reviewable_not_matched_or_deleted(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    from tests.unit.test_manual_table_extraction import workbook

    values = {"style": "99001", "color": "Blue", "size": "M"}
    values[field] += "\u200b"
    result = service(monkeypatch).analyze(
        workbook([["款号", "颜色", "尺码", "数量"], [*values.values(), 2]]),
        "inventory",
        Options(),
    )
    assert result["state"] == "NEEDS_REVIEW"
    assert result["rows"][0][field] == values[field]
    assert result["rows"][0]["match"]["sku_id"] is None


def test_invalid_identity_with_selected_sku_has_chinese_input_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.test_manual_table_extraction import workbook

    with pytest.raises(ApiError) as caught:
        service(monkeypatch).analyze(
            workbook(
                [["款号", "颜色", "尺码", "数量"], ["99001", "Blue\u200b", "M", 3]]
            ),
            "inventory",
            Options(decisions={"库存!2:M": {"sku_id": "31", "reason": "保留待核输入"}}),
        )
    assert caught.value.status_code == 422


def test_format_issue_is_not_duplicated_by_extraction_and_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.test_manual_table_extraction import workbook

    result = service(monkeypatch).analyze(
        workbook([["款号", "颜色", "尺码", "数量"], ["99001", "Blue\u200b", "M", 3]]),
        "inventory",
        Options(),
    )
    assert len([i for i in result["issues"] if i["code"] == "identity_format"]) == 1


def test_export_preserves_format_audit_and_reimports_same_quantities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from io import BytesIO

    import openpyxl  # type: ignore[import-untyped]
    from app.manual_tables.exports import render, semantic
    from tests.unit.test_manual_table_extraction import workbook

    svc = service(monkeypatch)
    raw = workbook([["款号", "颜色", "尺码", "数量"], ["99001", " BLUE ", "ｍ", 3]])
    result = svc.analyze(raw, "inventory", Options())
    output = render(
        {
            "id": "qa",
            "revision": 1,
            "kind": "inventory",
            "filename": "qa.xlsx",
            "source_digest": "a" * 64,
            "result": result,
        },
        "standard",
    )
    book = openpyxl.load_workbook(BytesIO(output))
    assert book["格式整理"].cell(2, 4).value == " BLUE "
    assert book["格式整理"].cell(2, 5).value == "Blue"
    book.close()
    assert semantic(svc.analyze(output, "inventory", Options())) == semantic(result)


@pytest.mark.parametrize("box", ["", "箱1"])
def test_packing_formatting_keeps_exact_platform_identifiers_on_export(
    monkeypatch: pytest.MonkeyPatch, box: str
) -> None:
    from app.manual_tables.exports import render, semantic
    from tests.unit.test_manual_table_extraction import workbook

    svc = service(monkeypatch)
    raw = workbook(
        [
            ["款号", "颜色", "尺码", "数量", "SKU", "ASIN", "FNSKU", "箱号"],
            ["99001", " BLUE ", "ｍ", 3, "00-AbC-M", "00-ASIN", "00-FNSKU", box],
        ]
    )
    result = svc.analyze(raw, "packing", Options())
    row = result["rows"][0]
    assert (row["code"], row["asin"], row["fnsku"]) == (
        "00-AbC-M",
        "00-ASIN",
        "00-FNSKU",
    )
    output = render(
        {
            "id": "qa",
            "revision": 1,
            "kind": "packing",
            "filename": "qa.xlsx",
            "source_digest": "a" * 64,
            "result": result,
        },
        "standard",
    )
    again = svc.analyze(output, "packing", Options())
    assert semantic(again) == semantic(result)
    again["rows"][0]["units"] = "4"
    assert semantic(again) != semantic(result)
    again["rows"][0]["units"] = "3"
    if box:
        again["rows"][0]["boxes"] = {"其他箱": "3"}
        assert semantic(again) != semantic(result)


def test_shipment_fulfillment_modes_accept_only_explicit_supported_values() -> None:
    value = Options(
        context={"fulfillment_modes": json.dumps({"31": "PRODUCTION_DIRECT"})}
    )
    assert json.loads(value.context["fulfillment_modes"]) == {"31": "PRODUCTION_DIRECT"}
    with pytest.raises(ValueError, match="出货来源"):
        Options(context={"fulfillment_modes": json.dumps({"31": "UNKNOWN"})})


@pytest.mark.parametrize("kind", ["inventory", "orders", "packing"])
def test_preparation_only_hides_handoff_capabilities_and_rejects_before_locking(
    monkeypatch: pytest.MonkeyPatch, kind: Kind
) -> None:
    from app.manual_tables.handoff import handoff_batch
    from app.manual_tables.schemas import Command

    svc = service(monkeypatch)
    svc.settings = replace(svc.settings, manual_tables_handoff_enabled=False)
    result = svc.analyze(example(kind), kind, Options())
    assert result["capabilities"]["can_export"]
    assert not any(
        result["capabilities"][key]
        for key in (
            "can_create_inventory_review",
            "can_create_order_draft",
            "can_create_shipment_draft",
        )
    )
    # No engine is installed: reaching a batch write/lock would fail this test.
    with pytest.raises(ApiError) as caught:
        handoff_batch(
            svc,
            "unused",
            Command(
                expected_revision=0,
                operation_token="00000000-0000-4000-8000-000000000000",
            ),
        )
    assert caught.value.status_code == 403
    assert (
        cast(dict[str, str], caught.value.detail)["code"] == "manual_handoff_disabled"
    )


@pytest.mark.parametrize("preview_only", [False, True])
def test_inventory_handoff_switch_rejects_before_locking(
    monkeypatch: pytest.MonkeyPatch, preview_only: bool
) -> None:
    from app.manual_tables.handoff import handoff_batch
    from app.manual_tables.schemas import Command

    svc = service(monkeypatch)
    svc.settings = replace(svc.settings, manual_tables_inventory_handoff_enabled=False)
    result = svc.analyze(example("inventory"), "inventory", Options())
    assert result["capabilities"]["can_export"]
    assert not result["capabilities"]["can_create_inventory_review"]
    monkeypatch.setattr(svc, "get", lambda batch_id: {"kind": "inventory"})
    with pytest.raises(ApiError) as caught:
        handoff_batch(
            svc,
            "unused",
            Command(
                expected_revision=0,
                operation_token="00000000-0000-4000-8000-000000000000",
            ),
            preview_only=preview_only,
        )
    assert caught.value.status_code == 403
    assert (
        cast(dict[str, str], caught.value.detail)["code"]
        == "manual_inventory_handoff_disabled"
    )


def test_capabilities_can_enable_business_drafts_without_inventory_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import Mock

    from app.api.manual_tables import capabilities

    settings = replace(
        service(monkeypatch).settings, manual_tables_inventory_handoff_enabled=False
    )
    request = Mock()
    request.app.state.settings = settings
    result = capabilities(request, context())
    assert result["enabled"] and result["handoff_enabled"]
    assert not result["inventory_handoff_enabled"]


def test_entity_match_uses_stable_id_and_zero_does_not_invent_sku(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = service(monkeypatch).analyze(example("inventory"), "inventory", Options())
    matched = next(
        r for r in result["rows"] if r["style"] == "99001" and r["size"] == "M"
    )
    assert matched["match"]["sku_id"] == "31"
    assert matched["match"]["catalog_version"] == "7:2"
    zeros = [r for r in result["rows"] if r["units"] == "0"]
    assert all(r["match"]["sku_id"] is None for r in zeros)


def test_conflicting_product_selection_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = service(monkeypatch)
    with pytest.raises(ApiError) as error:
        svc.analyze(
            example("inventory"),
            "inventory",
            Options(decisions={"库存!3:M": {"sku_id": "999", "reason": "选择"}}),
        )
    assert error.value.status_code == 422


def test_viewer_and_disabled_module_cannot_read_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = service(monkeypatch)
    svc.context = replace(svc.context, principal_roles=frozenset({"viewer"}))
    with pytest.raises(ApiError):
        svc.require()
    svc.context = context()
    svc.settings = Settings(manual_tables_enabled=False)
    with pytest.raises(ApiError):
        svc.require()


def test_inventory_reference_preserves_unknown_and_original_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = service(monkeypatch)
    options = Options(context={"warehouse": "人工表格虚构体验仓"})
    result = svc.analyze(example("inventory"), "inventory", options)
    batch = {
        "id": "qa",
        "revision": 2,
        "kind": "inventory",
        "result": result,
        "options": options.model_dump(),
        "filename": "qa.xlsx",
        "source_digest": "0" * 64,
    }
    snapshot = inventory_snapshot(batch)
    assert snapshot["summary"]["warehouse_1_units"] == "23"
    assert snapshot["rows"][0]["manual_sources"][0]["sheet"] == "库存"
    assert snapshot["rows"][0]["warehouse_display"] == "人工表格虚构体验仓"
    assert not snapshot["posting_enabled"]


def test_inventory_unknown_quantity_does_not_become_a_known_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.test_manual_table_extraction import workbook

    svc = service(monkeypatch)
    options = Options(context={"warehouse": "QA"})
    result = svc.analyze(
        workbook([["款号", "颜色", "M", "L"], ["99001", "Blue", 2, "/"]]),
        "inventory",
        options,
    )
    snapshot = inventory_snapshot(
        {
            "id": "qa",
            "revision": 1,
            "result": result,
            "options": options.model_dump(),
            "filename": "qa.xlsx",
            "source_digest": "a" * 64,
        }
    )
    row = snapshot["rows"][0]
    assert row["source_total"]["units"] is None
    assert row["quantities"]["L"]["units"] is None
    assert row["literal_units"] == "2"


def test_manual_review_export_preserves_warehouse_and_source_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from io import BytesIO

    import openpyxl
    from app.production.inventory_export import inventory_workbook

    svc = service(monkeypatch)
    options = Options(context={"warehouse": "人工表格虚构体验仓"})
    result = svc.analyze(example("inventory"), "inventory", options)
    snapshot = inventory_snapshot(
        {
            "id": "qa",
            "revision": 1,
            "result": result,
            "options": options.model_dump(),
            "filename": "qa.xlsx",
            "source_digest": "a" * 64,
        }
    )
    book = openpyxl.load_workbook(BytesIO(inventory_workbook(snapshot)))
    notes = {r[0].value: r[1].value for r in book["导出说明"]}
    assert notes["仓库"] == "人工表格虚构体验仓"
    assert notes["来源人工整理批次"] == "qa"
    assert book["库存表"].cell(2, 11).value == "人工表格虚构体验仓"


def test_comparison_does_not_infer_missing_specs_or_stock_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = service(monkeypatch)
    tables: dict[str, Any] = {}
    for kind in ("inventory", "orders", "packing"):
        result = svc.analyze(
            example(kind),
            kind,
            Options(columns={"code": 1} if kind == "packing" else {}),
        )
        tables[kind] = {
            "id": kind,
            "revision": 1,
            "kind": kind,
            "result": result,
            "options": {"context": {}},
        }
    monkeypatch.setattr(svc, "get", lambda batch_id: tables[batch_id])
    result = compare(svc, {k: {"id": k, "revision": 1} for k in tables})
    blue_l = next(
        r for r in result["rows"] if r["style"] == "99001" and r["size"] == "L"
    )
    assert blue_l["packing"] is None
    assert blue_l["unexplained_difference"] is None
    assert any("仓库" in w for w in result["warnings"])
    with pytest.raises(ApiError):
        compare(svc, {"orders": {"id": "orders", "revision": 0}})
