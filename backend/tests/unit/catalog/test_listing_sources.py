from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import IO, Any, cast

# ruff: noqa: RUF001 -- Literal Chinese workbook headings.
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest
from app.api.errors import ApiError
from app.catalog.listing_registration import (
    SKU_POLICY,
    assert_strict_source,
    registration_status,
)
from app.catalog.listing_sources import ListingSelection
from app.catalog.listing_table import read_listing_workbook
from app.catalog.platform_evidence import compare_listing, lock_platform_scopes
from app.catalog.production_sources import ProductionSourceInputError
from openpyxl import Workbook  # type: ignore[import-untyped]
from sqlalchemy.engine import Connection


@pytest.mark.parametrize(
    "raw,code",
    [
        ("0012-navy-M", "SKU_COLOR_CASE"),
        ("0012-Navy-m", "SKU_SIZE_CASE"),
        ("0012-Navy-XLL", "SKU_SIZE_INVALID"),
        ("0012-M-Navy", "SKU_COMPONENT_ORDER"),
        ("0012—Navy—M", "SKU_STRUCTURE"),
        ("0012-Navy-M ", "SKU_WHITESPACE"),
    ],
)
def test_strict_product_sku_errors_keep_exact_cell_and_original(
    tmp_path: Path, raw: str, code: str
) -> None:
    parsed = read_listing_workbook(
        save(tmp_path, [[None, raw, None, None]]), strict_skus=True
    )
    row = parsed["listing_rows"][0]
    assert row["seller_sku"] == raw
    assert any(
        i["code"] == code and i["cell"] == "B4" and i["sheet"] == "店铺甲"
        for i in row["format_issues"]
    )
    with pytest.raises(ApiError) as caught:
        assert_strict_source(parsed, [])
    assert (
        cast(dict[str, str], caught.value.detail)["code"]
        == "listing_sku_format_invalid"
    )


def test_strict_parent_rows_are_not_inventory_variants_and_sku_only_is_supported(
    tmp_path: Path,
) -> None:
    def edit(sheet: Any) -> None:
        sheet.delete_cols(3, 2)
        sheet["B3"] = "SKU"

    parsed = read_listing_workbook(
        save(tmp_path, [[None, 12], [None, "0012-Navy-M"]], edit), strict_skus=True
    )
    parent, variant = parsed["listing_rows"]
    assert parsed["sku_format_policy"] == SKU_POLICY
    assert parent["suggested_type"] == "parent" and parent["issues"] == []
    assert parent["suggestion"] is None and parent["seller_sku"] == "12"
    assert variant["suggestion"] == {"style_code": "0012", "color": "Navy", "size": "M"}
    assert variant["seller_sku"] == "0012-Navy-M"


def test_suspected_spelling_is_not_silently_corrected_or_certified(
    tmp_path: Path,
) -> None:
    parsed = read_listing_workbook(
        save(
            tmp_path,
            [[None, f"0012-Blue-{size}", None, None] for size in ["S", "M", "L"]]
            + [[None, "0012-Bluw-XL", None, None]],
        ),
        strict_skus=True,
    )
    row = parsed["listing_rows"][-1]
    assert row["suggestion"]["color"] == "Bluw"
    assert row["format_issues"][0]["severity"] == "warning"
    selection = ListingSelection(
        row_id=row["row_id"],
        include=True,
        record_type="variant",
        style_code="0012",
        color="Bluw",
        size="XL",
    )
    with pytest.raises(ApiError):
        assert_strict_source(parsed, [selection])
    assert_strict_source(
        parsed, [selection.model_copy(update={"note": "已核对真实商品，原拼写无误"})]
    )


def test_catalog_status_is_exact_and_scoped_and_never_uses_similar_names(
    tmp_path: Path,
) -> None:
    parsed = read_listing_workbook(save(tmp_path), strict_skus=True)
    sku: dict[str, Any] = {
        "sku_id": 21,
        "style_id": 1,
        "style_code": "0012",
        "standard_color": "Olive",
        "standard_size": "M",
        "internal_display_sku": "0012-Olive-M",
        "status": "enabled",
    }
    rows = parsed["listing_rows"]
    assert registration_status(rows, [sku], [], {})[0]["registration"] == {
        "state": "registered",
        "sku_id": 21,
    }
    assert (
        registration_status(rows, [{**sku, "status": "disabled"}], [], {})[0][
            "registration"
        ]["state"]
        == "disabled"
    )
    other: dict[str, Any] = {
        **sku,
        "sku_id": 22,
        "standard_size": "L",
        "internal_display_sku": "0012-Olive-L",
    }
    assert (
        registration_status(
            rows,
            [other],
            [{"report_source_scope_id": 7, "seller_sku": "0012-Olive-M", "sku_id": 22}],
            {"店铺甲": 8},
        )[0]["registration"]["state"]
        == "missing"
    )
    assert (
        registration_status(
            rows,
            [other],
            [{"report_source_scope_id": 7, "seller_sku": "0012-Olive-M", "sku_id": 22}],
            {"店铺甲": 7},
        )[0]["registration"]["state"]
        == "conflict"
    )


def test_strict_candidate_cannot_override_the_original_parts(tmp_path: Path) -> None:
    parsed = read_listing_workbook(save(tmp_path), strict_skus=True)
    wrong = ListingSelection(
        row_id="s1-r4",
        include=True,
        record_type="variant",
        style_code="0012",
        color="Blue",
        size="M",
    )
    with pytest.raises(ApiError):
        assert_strict_source(parsed, [wrong])
    assert_strict_source(parsed, [wrong.model_copy(update={"color": "Olive"})])


def test_source_prefill_is_ready_and_preserves_existing() -> None:
    from app.catalog.import_service import validate_draft_rows
    from app.catalog.inventory import CatalogIdentityInventory
    from app.catalog.listing_registration import prefill_source_code
    from app.catalog.production_sources import (
        ProductionSource,
        _row,
        project_production_source,
    )

    source = ProductionSource.model_validate(
        {
            "source_name": "已人工核对的产品表",
            "rows": [
                {
                    "style_code": "0012",
                    "color": "Navy",
                    "size": "M",
                    "formal_sku": "0012-Navy-M",
                }
            ],
        }
    )
    projection, _ = project_production_source(source, CatalogIdentityInventory((), ()))
    rows = tuple(
        _row(
            row.section,
            row.row_key,
            prefill_source_code(dict(row.payload), "0012-Navy-M", source.source_name),
        )
        if row.section == "skus"
        else row
        for row in projection.rows
    )
    ready = validate_draft_rows(rows)
    assert not ready.issues
    sku = next(row for row in ready.rows if row.section == "skus")
    assert sku.payload["internal_display_sku"] == "0012-Navy-M"
    existing: dict[str, Any] = {
        "system_sku_id": "12",
        "internal_display_sku": "ORIGINAL",
        "code_status": "legacy",
    }
    assert prefill_source_code(existing, "0012-Navy-M", source.source_name) == existing


@pytest.mark.parametrize("scope_exists", [True, False])
def test_platform_scope_lock_preserves_insert_only_history(scope_exists: bool) -> None:
    queries: list[str] = []

    class RuntimeConnection:
        def scalar(self, statement: object, parameters: dict[str, int]) -> int | None:
            sql = " ".join(str(statement).split())
            queries.append(sql)
            assert parameters["site"] == 1
            if "FROM site_current_configs" in sql:
                assert "FOR UPDATE" in sql
                return 1
            assert "FROM report_source_scopes" in sql
            assert "FOR UPDATE" not in sql
            return 7 if scope_exists else None

    connection = cast(Connection, RuntimeConnection())
    if scope_exists:
        lock_platform_scopes(connection, 1, [7, 7])
    else:
        with pytest.raises(ApiError) as caught:
            lock_platform_scopes(connection, 1, [7])
        assert caught.value.status_code == 403
    assert len(queries) == 2
    assert "FROM site_current_configs" in queries[0]


def save(
    tmp_path: Path,
    rows: list[list[Any]] | None = None,
    edit: Callable[[Any], None] | None = None,
) -> Path:
    book = Workbook()
    w = book.active
    w.title = "店铺甲"
    w.append(["产品类型"])
    w.append([])
    w.append(["商品图片", "卖家SKU", "ASIN", "FNSKU"])
    for row in rows or [[None, "0012-Olive-M", "B000000001", "X004000001"]]:
        w.append(row)
    if edit:
        edit(w)
    path = tmp_path / "listing.xlsx"
    book.save(path)
    book.close()
    return path


def test_raw_codes_locations_and_display_merge(tmp_path: Path) -> None:
    row = read_listing_workbook(save(tmp_path, edit=lambda w: w.merge_cells("A4:A5")))[
        "listing_rows"
    ][0]
    assert row["seller_sku"] == "0012-Olive-M" and row["row_id"] == "s1-r4"
    assert (
        row["suggestion"] == {"style_code": "0012", "color": "Olive", "size": "M"}
        and not row["issues"]
    )


def test_title_merge_before_detected_header_is_allowed(tmp_path: Path) -> None:
    rows = read_listing_workbook(save(tmp_path, edit=lambda w: w.merge_cells("A1:D1")))[
        "listing_rows"
    ]
    assert len(rows) == 1 and rows[0]["seller_sku"] == "0012-Olive-M"


def test_merge_spanning_detected_header_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProductionSourceInputError) as caught:
        read_listing_workbook(save(tmp_path, edit=lambda w: w.merge_cells("E1:F3")))
    assert "涉及表头或业务数据" in caught.value.public_message


@pytest.mark.parametrize(
    "edit,expected",
    [
        (lambda w: w.merge_cells("B4:C4"), "合并"),
        (lambda w: setattr(w.row_dimensions[4], "hidden", True), "隐藏"),
    ],
)
def test_unsafe_business_structure(
    tmp_path: Path, edit: Callable[[Any], None], expected: str
) -> None:
    with pytest.raises(ProductionSourceInputError) as caught:
        read_listing_workbook(save(tmp_path, edit=edit))
    assert expected in caught.value.public_message


def test_display_hyperlink_is_ignored_and_cell_text_is_preserved(
    tmp_path: Path,
) -> None:
    rows = read_listing_workbook(
        save(
            tmp_path,
            edit=lambda w: setattr(w["B4"], "hyperlink", "https://example.com"),
        )
    )["listing_rows"]
    assert len(rows) == 1 and rows[0]["seller_sku"] == "0012-Olive-M"


def test_formula_numeric_and_typo_are_actionable(tmp_path: Path) -> None:
    rows = read_listing_workbook(
        save(
            tmp_path,
            [
                [None, 12, "B000000001", None],
                [None, "0012-Olive-XLL", "B000000002", "=1+2"],
            ],
        )
    )["listing_rows"]
    assert (
        rows[0]["cell_types"]["seller_sku"] == "n" and "前导零" in rows[0]["issues"][0]
    )
    assert (
        any("XLL" in issue for issue in rows[1]["issues"])
        and rows[1]["fnsku"] == "=1+2"
    )


def test_media_never_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = save(tmp_path)
    with ZipFile(path, "a", compression=ZIP_STORED) as z:
        z.writestr("xl/media/qa-image.bin", b"Q" * (2 * 1024 * 1024))
    original = ZipFile.open

    def checked(
        self: ZipFile, name: str | ZipInfo, *args: Any, **kwargs: Any
    ) -> IO[bytes]:
        assert not str(getattr(name, "filename", name)).startswith("xl/media/")
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(ZipFile, "open", checked)
    assert len(read_listing_workbook(path)["listing_rows"]) == 1


@pytest.mark.parametrize("kind", ["renamed", "zip", "macro", "dtd", "worksheet_bin"])
def test_rejects_disguised_or_active_package_before_excel_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    path = save(tmp_path)
    with ZipFile(path) as original:
        parts = {name: original.read(name) for name in original.namelist()}
    if kind == "renamed":
        path.write_bytes(b"<html><script>alert(1)</script></html>")
    else:
        if kind == "zip":
            parts = {"not-a-workbook.txt": b"test"}
        elif kind == "macro":
            parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
                b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
                b"application/vnd.ms-excel.sheet.macroEnabled.main+xml",
            )
        elif kind == "dtd":
            parts["xl/worksheets/sheet1.xml"] = (
                b'<!DOCTYPE worksheet [<!ENTITY xxe SYSTEM "file:///NOT-A-REAL-RESOURCE">]><worksheet>&xxe;</worksheet>'
            )
        else:
            parts["xl/_rels/workbook.xml.rels"] = parts[
                "xl/_rels/workbook.xml.rels"
            ].replace(b"sheet1.xml", b"sheet1.bin")
        with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
            for name, body in parts.items():
                archive.writestr(name, body)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Unsafe package reached the business workbook reader")

    monkeypatch.setattr("app.catalog.listing_table.openpyxl.load_workbook", forbidden)
    with pytest.raises(ProductionSourceInputError):
        read_listing_workbook(path, strict_skus=True)


def test_all_xml_budgets_checked_before_decompression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = save(tmp_path)
    with ZipFile(path, "a", compression=ZIP_DEFLATED) as archive:
        archive.writestr("xl/media/disguised.XML", b"Q" * (32 * 1024 * 1024))

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Package decompressed before the directory budget check")

    monkeypatch.setattr(ZipFile, "read", forbidden)
    with pytest.raises(ProductionSourceInputError) as caught:
        read_listing_workbook(path, strict_skus=True)
    assert "32MiB" in caught.value.public_message


def obs(
    child: str = "B000000001",
    scope: int = 1,
    kind: str = "business_report",
    fnsku: str | None = None,
) -> dict[str, Any]:
    return {
        "report_source_scope_id": scope,
        "seller_sku": "0012-Olive-M",
        "child_asin": child,
        "parent_asin": "B000000009",
        "fnsku": fnsku,
        "report_type": kind,
        "report_date": "2026-10-14",
    }


@pytest.mark.parametrize(
    "observations,state,can_map",
    [
        ([], "no_official", True),
        ([obs()], "consistent", True),
        ([obs("B000000002")], "source_difference", True),
        ([obs(), obs("B000000002", kind="return_report")], "official_conflict", False),
        ([obs(scope=2)], "no_official", True),
        ([obs(), obs(kind="return_report", fnsku="X004000001")], "consistent", True),
    ],
)
def test_official_precedence_scope_and_conflicts(
    observations: list[dict[str, Any]], state: str, can_map: bool
) -> None:
    row: dict[str, Any] = {
        "row_id": "a",
        "sheet": "甲",
        "seller_sku": "0012-Olive-M",
        "asin": "B000000001",
        "fnsku": "X004000001",
    }
    r = compare_listing([row], {"甲": 1}, {"observations": observations})[0]
    assert (
        r["state"] == state and r["can_map"] is can_map and row["asin"] == "B000000001"
    )


def test_duplicate_and_conflicting_source_rows() -> None:
    a: dict[str, Any] = {
        "row_id": "a",
        "sheet": "甲",
        "seller_sku": "0012-Olive-M",
        "asin": "B000000001",
    }
    b = a | {"row_id": "b"}
    r = compare_listing([a, b], {"甲": 1}, {"observations": [obs()]})
    assert r[1]["primary_row"] == "a" and r[1]["duplicate_rows"] == ["a", "b"]
    r = compare_listing(
        [a, b | {"asin": "B000000002"}], {"甲": 1}, {"observations": [obs()]}
    )
    assert all(x["state"] == "source_conflict" for x in r)


def test_named_standard_columns_do_not_rewrite_seller_sku(tmp_path: Path) -> None:
    book = Workbook()
    sheet = book.active
    sheet.append(
        ["Seller SKU（卖家SKU）", "子ASIN", "标准颜色", "标准尺码", "款号", "记录类型"]
    )
    sheet.append(["00-AbC-XXXL", "B000000001", "Olive", "3XL", "0012", "具体商品规格"])
    sheet.append(["0012", "B000000009", None, None, None, "父级／款式记录"])
    path = tmp_path / "named.xlsx"
    book.save(path)
    book.close()
    rows = read_listing_workbook(path)["listing_rows"]
    assert rows[0]["seller_sku"] == "00-AbC-XXXL"
    assert rows[0]["suggestion"] == {
        "style_code": "0012",
        "color": "Olive",
        "size": "3XL",
    }
    assert rows[1]["suggested_type"] == "parent"


def test_combined_record_limit_is_not_per_sheet(tmp_path: Path) -> None:
    book = Workbook()
    for sheet in (book.active, book.create_sheet("QA2")):
        sheet.append(["卖家SKU", "ASIN", "FNSKU"])
        for number in range(501):
            sheet.append([f"0012-{number}-M", "B000000001", None])
    path = tmp_path / "too-many.xlsx"
    book.save(path)
    book.close()
    with pytest.raises(ProductionSourceInputError) as caught:
        read_listing_workbook(path)
    assert "1000" in caught.value.public_message


def test_xxxl_source_keeps_original_code_and_uses_confirmed_3xl(tmp_path: Path) -> None:
    parsed = read_listing_workbook(
        save(tmp_path, [[None, "1115-Navy-XXXL", None, None]]), strict_skus=True
    )
    row = parsed["listing_rows"][0]
    assert row["seller_sku"] == "1115-Navy-XXXL"
    assert row["suggestion"] == {"style_code": "1115", "color": "Navy", "size": "3XL"}
    selected = ListingSelection(
        row_id=row["row_id"],
        include=True,
        record_type="variant",
        style_code="1115",
        color="Navy",
        size="3XL",
    )
    assert_strict_source(parsed, [selected])
    existing: dict[str, Any] = {
        "sku_id": 529,
        "style_code": "1115",
        "standard_color": "Navy",
        "standard_size": "3XL",
        "internal_display_sku": "1115-Navy-XXXL",
        "status": "disabled",
    }
    status = registration_status([row], [existing], [], {})[0]["registration"]
    assert status == {"state": "disabled", "sku_id": 529}
    with pytest.raises(ApiError, match="listing_sku_source_mismatch"):
        assert_strict_source(parsed, [selected.model_copy(update={"size": "XXXL"})])
