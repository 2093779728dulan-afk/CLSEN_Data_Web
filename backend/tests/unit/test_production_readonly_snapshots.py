"""Read-only local evidence keeps quantity, identity and scope boundaries."""
# ruff: noqa: RUF001 -- Original-style Chinese source fixture punctuation.

import hashlib
import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import cast

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api.errors import ApiError
from app.config import Settings
from app.production.catalog_reference import catalog_reference, source_product_hint
from app.production.inventory_snapshot import (
    INVENTORY_FILENAME,
    INVENTORY_TABLE_FILENAME,
    SIZES,
    inventory_snapshot,
    parse_inventory,
    parse_inventory_table,
    warehouse_1_view,
)
from app.site_context import CurrentSiteContext


def context(site: int = 1, code: str = "DEMO_LOCAL_ONLY") -> CurrentSiteContext:
    return CurrentSiteContext(
        principal_user_id=1,
        principal_roles=frozenset({"viewer"}),
        site_id=site,
        site_code=code,
        site_display_name="Local",
        site_config_version_id=1,
        site_config_revision=1,
        source_timezone="UTC",
        reporting_timezone="UTC",
        currency_code="USD",
    )


def workbook(*, formula: str = "=11+14+10", broken_header: bool = False) -> bytes:
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name in ("主销款", "滞销款", "处理款", "Sheet1", "次品数量"):
        sheet = book.create_sheet(name)
        if name == "Sheet1":
            continue
        if name == "次品数量":
            sheet.append(["虚构历史次品"])
            sheet.append([])
            sheet.append(["款号", "颜色", "尺码", "数量", "备注"])
            sheet.append(["QA-HISTORY", "蓝", "S", 1, "历史"])
            sheet.append([None, None, "M", 2, None])
            sheet.append([None, None, "L", 3, None])
            sheet.merge_cells("A4:A5")
            sheet.merge_cells("B4:B5")
            continue
        start = 4 if name == "主销款" else 13
        for i, size in enumerate(SIZES[: 7 if name == "主销款" else 6]):
            sheet.cell(2, start + i, "BROKEN" if broken_header and i == 0 else size)
        if name == "主销款":
            sheet.cell(3, 1, "QA-MAIN")
            sheet.cell(3, 3, "blue")
            sheet.cell(3, 4, 5)
            sheet.cell(3, 5, 0)
            sheet.cell(3, 6, "/")
            sheet.cell(3, 11, "=SUM(D3:J3)")
            sheet.cell(3, 12, "新仓库")
            sheet.cell(4, 11, "=SUM(K3:K3)")
        elif name == "滞销款":
            sheet.cell(3, 4, "QA\n改QA-2")
            sheet.cell(3, 10, "navy大货\n实际是ARMY军绿")
            sheet.cell(3, 13, 7)
            sheet.cell(3, 19, 7)
            sheet.cell(3, 22, "另有7件没有车主唛，不知码数")
        else:
            sheet.cell(3, 4, "无款号")
            sheet.cell(3, 6, "QA25O2-Black")
            sheet.cell(3, 15, formula)
            sheet.cell(3, 19, 35)
            sheet.cell(3, 21, "尾部+宿舍")
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def prepare(tmp_path: Path) -> tuple[Settings, bytes]:
    content = workbook()
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / INVENTORY_FILENAME).write_bytes(content)
    (tmp_path / "inventory-source.json").write_text(
        json.dumps(
            {
                "schema": "production-inventory-source-v1",
                "consumer_site_id": "1",
                "source_digest": hashlib.sha256(content).hexdigest(),
                "organized_on": "2026-10-10",
                "stocktaken_on": None,
            }
        )
    )
    return Settings(
        production_demo_mode=True, production_order_draft_root=str(tmp_path)
    ), content


def test_inventory_counts_only_size_literals_and_separates_formula_and_defects() -> (
    None
):
    parsed = parse_inventory(workbook())
    summary = cast(dict[str, object], parsed["summary"])
    assert summary["row_count"] == 3
    assert summary["literal_units"] == "12"
    assert summary["warehouse_1_literal_units"] == "5"
    assert summary["location_unconfirmed_literal_units"] == "7"
    assert summary["formula_units"] == "35"
    assert summary["defect_literal_units"] == "6"
    assert summary["additional_note_rows"] == 1


def test_inventory_zero_blank_slash_and_raw_identity_are_distinct() -> None:
    rows = cast(list[dict[str, object]], parse_inventory(workbook())["rows"])
    cells = cast(dict[str, dict[str, object]], rows[0]["quantities"])
    assert cells["S"]["state"] == "LITERAL" and cells["S"]["units"] == "0"
    assert cells["M"]["raw"] == "/" and cells["M"]["units"] is None
    assert cells["L"]["raw"] == "" and cells["L"]["units"] is None
    assert rows[1]["style_code"] == "QA\n改QA-2"
    assert rows[2]["source_sku"] == "QA25O2-Black"
    assert rows[2]["location_group"] == "UNCONFIRMED"
    assert all(row["sku_id"] is None for row in rows)


@pytest.mark.parametrize(
    "formula",
    [
        "=SUM(A1:A2)",
        '=WEBSERVICE("https://invalid")',
        "=11-4",
        "=__import__('os')",
        "-1",
        "1.5",
        True,
    ],
)
def test_inventory_does_not_execute_formulas_or_invent_quantities(
    formula: object,
) -> None:
    content = workbook(formula=cast(str, formula))
    rows = cast(list[dict[str, object]], parse_inventory(content)["rows"])
    cell = cast(dict[str, dict[str, object]], rows[2]["quantities"])["M"]
    assert cell["units"] is None and cell["state"] == "UNSUPPORTED"
    assert rows[2]["formula_units"] == "0"


def test_inventory_merge_inheritance_stops_at_real_merge_boundary() -> None:
    defects = cast(list[dict[str, object]], parse_inventory(workbook())["defects"])
    assert defects[1]["style_code"] == "QA-HISTORY"
    assert defects[1]["inherited_cells"] == {"A5": "A4", "B5": "B4"}
    assert defects[2]["style_code"] == "" and defects[2]["identity_unresolved"]


def test_inventory_local_snapshot_preserves_unknown_date_and_original_bytes(
    tmp_path: Path,
) -> None:
    settings, content = prepare(tmp_path)
    value = inventory_snapshot(settings, context())
    assert value["stocktaken_on"] is None and value["organized_on"] == "2026-10-10"
    assert (
        value["posting_enabled"] is False
        and value["historical_shipments_deducted"] is False
    )
    assert (tmp_path / "inputs" / INVENTORY_FILENAME).read_bytes() == content


@pytest.mark.parametrize("site,code", [(2, "DEMO_LOCAL_ONLY"), (1, "amazon_us")])
def test_inventory_is_scoped_to_explicit_local_site(
    tmp_path: Path, site: int, code: str
) -> None:
    settings, _ = prepare(tmp_path)
    with pytest.raises(ApiError) as caught:
        inventory_snapshot(settings, context(site, code))
    assert caught.value.status_code == 404


def test_inventory_changed_source_or_metadata_is_refused(tmp_path: Path) -> None:
    settings, _ = prepare(tmp_path)
    (tmp_path / "inputs" / INVENTORY_FILENAME).write_bytes(workbook(formula="=1+2"))
    with pytest.raises(ApiError) as caught:
        inventory_snapshot(settings, context())
    assert caught.value.status_code == 422
    (tmp_path / "inventory-source.json").write_text("invalid json")
    with pytest.raises(ApiError) as caught:
        inventory_snapshot(settings, context())
    assert caught.value.status_code == 422


def test_inventory_uninitialized_and_changed_headers_are_refused(
    tmp_path: Path,
) -> None:
    settings = Settings(
        production_demo_mode=True, production_order_draft_root=str(tmp_path)
    )
    with pytest.raises(ApiError) as caught:
        inventory_snapshot(settings, context())
    assert caught.value.status_code == 404
    with pytest.raises(ValueError, match="header"):
        parse_inventory(workbook(broken_header=True))


def pasted_table() -> bytes:
    fields = [
        ["新款号", "COLOR", *SIZES, "合计", "库位"],
        ["QA-100", "navy", "5", "0", "/", "", "", "", "", "5", "新仓库"],
        ["QA-100", "NAVY", "", "7", "", "", "", "", "", "7", "新仓库"],
        ["QA-100", "navy", "3", "", "", "", "", "", "", "3"],
    ]
    return "\n".join("   ".join(row) for row in fields).encode("utf-8")


def test_inventory_replacement_preserves_fixed_columns_and_declared_totals() -> None:
    parsed = parse_inventory_table(pasted_table())
    rows = cast(list[dict[str, object]], parsed["rows"])
    assert [row["source_key"] for row in rows] == [
        "用户核对表!2",
        "用户核对表!3",
        "用户核对表!4",
    ]
    cells = cast(dict[str, dict[str, object]], rows[0]["quantities"])
    assert cells["XS"]["units"] == "5" and cells["XS"]["cell"] == "C2"
    assert cells["S"]["units"] == "0" and cells["S"]["state"] == "LITERAL"
    assert cells["M"]["raw"] == "/" and cells["M"]["units"] is None
    assert cells["L"]["raw"] == "" and cells["L"]["units"] is None
    before = deepcopy(parsed)
    view = warehouse_1_view(parsed, "DECLARED_TOTAL")
    assert parsed == before
    scoped = cast(list[dict[str, object]], view["rows"])
    assert [(row["color"], row["stock_units"]) for row in scoped] == [
        ("navy", "5"),
        ("NAVY", "7"),
    ]
    summary = cast(dict[str, object], view["summary"])
    assert summary["source_row_count"] == 3 and summary["row_count"] == 2
    assert summary["product_count"] == 1 and summary["warehouse_1_units"] == "12"
    assert summary["location_unconfirmed_units"] == "3"
    assert view["quantity_basis"] == "DECLARED_TOTAL" and view["defects"] == []
    assert all(row["sku_id"] is None for row in scoped)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not a table",
        b"\xff",
        pasted_table().replace(b"   COLOR   ", b"  COLOR  "),
        pasted_table().replace(b"   5   0   ", b"   5   "),
        pasted_table().replace(b"   5   0   ", b"   5   0   0   "),
        pasted_table().replace(b"   5   0   ", b"   -5   0   "),
        pasted_table().replace(b"   5   0   ", b"   5.5   0   "),
        pasted_table().replace(b"   5   0   ", b"   =2+3   0   "),
        pasted_table().replace(b"   5   0   ", b"   4   0   "),
    ],
)
def test_inventory_replacement_refuses_unpositioned_or_unverified_data(
    content: bytes,
) -> None:
    with pytest.raises(ValueError):
        parse_inventory_table(content)


def test_inventory_replacement_manifest_selects_one_source_and_preserves_old_copy(
    tmp_path: Path,
) -> None:
    settings, old_content = prepare(tmp_path)
    new_content = pasted_table()
    (tmp_path / "inputs" / INVENTORY_TABLE_FILENAME).write_bytes(new_content)
    path = tmp_path / "inventory-source.json"
    metadata = json.loads(path.read_bytes()) | {
        "source_format": "pasted_table",
        "organized_on": None,
        "source_digest": hashlib.sha256(new_content).hexdigest(),
    }
    path.write_text(json.dumps(metadata))
    value = inventory_snapshot(settings, context())
    assert value["filename"] == INVENTORY_TABLE_FILENAME
    assert value["source_format"] == "pasted_table" and value["organized_on"] is None
    assert value["stocktaken_on"] is None
    assert len(cast(list[dict[str, object]], value["rows"])) == 2
    assert len(cast(list[dict[str, object]], value["unconfirmed_rows"])) == 1
    assert (
        value["posting_enabled"] is False
        and value["historical_shipments_deducted"] is False
    )
    assert (tmp_path / "inputs" / INVENTORY_FILENAME).read_bytes() == old_content
    (tmp_path / "inputs" / INVENTORY_TABLE_FILENAME).write_bytes(
        new_content + b"changed"
    )
    with pytest.raises(ApiError) as caught:
        inventory_snapshot(settings, context())
    assert caught.value.status_code == 422


def reference() -> dict[str, object]:
    return {
        "schema": "production-catalog-reference-v1",
        "consumer_site_id": "1",
        "source_digests": ["a" * 64],
        "source": {
            "origin": "A_LOCAL_PUBLISHED_CATALOG",
            "source_run_id": "a" * 32,
            "site_id": "1",
            "site_code": "amazon_us",
            "catalog_version_id": "35",
            "catalog_publication_revision": "35",
            "version_number": "35",
            "checked_at": "2026-10-12T06:00:00Z",
            "display_match_version": "catalog_identity_key_v1",
            "seller_match_version": "seller_sku_match_v1",
        },
        "matches": {},
    }


@pytest.mark.parametrize(
    "line,expected",
    [
        ({"style_code": "9911", "sku_code": "9922-Blue-M"}, ("9911", "SOURCE_COLUMN")),
        ({"sku_code": "009911-Blue-M"}, ("009911", "SKU_PREFIX_HINT")),
        ({"sku_code": "QA-9911-Blue-M"}, None),
        ({"sku_code": "9911"}, None),
    ],
)
def test_source_product_hint_is_only_a_locator_and_preserves_original(
    line: dict[str, object], expected: object
) -> None:
    before = deepcopy(line)
    assert source_product_hint(line) == expected
    assert line == before


def test_catalog_reference_product_lookup_does_not_promote_product_to_sku(
    tmp_path: Path,
) -> None:
    snapshot = reference()
    product = {
        "style_id": "9007199254740995",
        "style_revision": "2",
        "code": "QA-100",
        "name": "Fictional product",
        "status": "enabled",
        "skus": [
            {
                "sku_id": "9007199254740993",
                "sku_revision": "3",
                "code": "QA-BLUE-M",
                "color": "Blue",
                "size": "M",
                "status": "disabled",
            }
        ],
    }
    snapshot["products"] = {"QA-100": [product], "QA-MISSING": []}
    (tmp_path / "catalog-reference.json").write_text(json.dumps(snapshot))
    source: dict[str, object] = {
        "source_digest": "a" * 64,
        "rows": [
            {
                "source_row": 2,
                "style_code": "QA-100",
                "sku_code": "OTHER-CODE",
                "sku_id": None,
            },
            {"source_row": 3, "style_code": "QA-MISSING", "sku_code": "MISSING"},
            {"source_row": 4, "style_code": "OUTSIDE", "sku_code": "OUTSIDE"},
        ],
    }
    before = deepcopy(source)
    value = catalog_reference(tmp_path, source, context())
    rows = cast(list[dict[str, object]], value["rows"])
    lookup = cast(dict[str, object], rows[0]["product_lookup"])
    assert lookup["candidates"] == [product]
    assert rows[0]["status"] == "UNMATCHED" and rows[0]["candidates"] == []
    assert cast(dict[str, object], rows[1]["product_lookup"])["checked"] is True
    assert cast(dict[str, object], rows[2]["product_lookup"])["checked"] is False
    assert source == before and value["confirmation_enabled"] is False
    assert value["counts"] == {"UNMATCHED": 3}


@pytest.mark.parametrize(
    "status", ["UNMATCHED", "UNIQUE_CANDIDATE", "AMBIGUOUS", "DISABLED", "EXCLUDED"]
)
def test_catalog_reference_keeps_snapshot_status_scope_and_large_ids_without_binding(
    tmp_path: Path, status: str
) -> None:
    snapshot = reference()
    candidate = {
        "sku_id": "9007199254740993",
        "style_id": "9007199254740995",
        "sku_revision": "2",
        "code": "QA-BLUE-M",
        "color": "blue",
        "size": "M",
        "status": "disabled" if status == "DISABLED" else "enabled",
        "style_status": "enabled",
        "match_routes": ["SELLER_MAPPING"],
        "source_scopes": [
            {"report_source_scope_id": "2", "marketplace_scope_code": "QA"}
        ],
    }
    candidates = (
        [candidate] if status in ("UNIQUE_CANDIDATE", "DISABLED", "AMBIGUOUS") else []
    )
    if status == "AMBIGUOUS":
        candidates.append(candidate | {"sku_id": "9007199254740994"})
    snapshot["matches"] = {
        "QA-BLUE-M": {
            "status": status,
            "candidates": candidates,
            "excluded_scopes": [
                {"report_source_scope_id": "3", "marketplace_scope_code": "QA"}
            ]
            if status == "EXCLUDED"
            else [],
        }
    }
    (tmp_path / "catalog-reference.json").write_text(json.dumps(snapshot))
    source: dict[str, object] = {
        "source_digest": "a" * 64,
        "rows": [
            {
                "source_row": 2,
                "sku_code": "QA-BLUE-M",
                "sku_id": None,
                "expected_units": "7",
            }
        ],
    }
    before = deepcopy(source)
    value = catalog_reference(tmp_path, source, context())
    assert source == before and value["confirmation_enabled"] is False
    assert value["counts"] == {status: 1}
    row = cast(list[dict[str, object]], value["rows"])[0]
    assert row["status"] == status
    if candidates:
        assert (
            cast(list[dict[str, object]], row["candidates"])[0]["sku_id"]
            == "9007199254740993"
        )


@pytest.mark.parametrize("site,digest", [(2, "a" * 64), (1, "b" * 64)])
def test_catalog_reference_cannot_expand_approved_site_or_source(
    tmp_path: Path, site: int, digest: str
) -> None:
    (tmp_path / "catalog-reference.json").write_text(json.dumps(reference()))
    assert (
        catalog_reference(
            tmp_path, {"source_digest": digest, "rows": []}, context(site)
        )["status"]
        == "OUTSIDE_SCOPE"
    )


def test_catalog_reference_missing_corrupt_or_unknown_code_is_explicit(
    tmp_path: Path,
) -> None:
    source: dict[str, object] = {
        "source_digest": "a" * 64,
        "rows": [{"source_row": 2, "sku_code": "QA-UNKNOWN"}],
    }
    assert catalog_reference(tmp_path, source, context())["status"] == "NOT_CONFIGURED"
    (tmp_path / "catalog-reference.json").write_text("invalid json")
    assert catalog_reference(tmp_path, source, context())["status"] == "UNAVAILABLE"
    (tmp_path / "catalog-reference.json").write_text(json.dumps(reference()))
    value = catalog_reference(tmp_path, source, context())
    assert value["counts"] == {"UNMATCHED": 1}
    assert value["confirmation_enabled"] is False
