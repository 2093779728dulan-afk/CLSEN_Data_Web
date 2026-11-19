from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese user-facing messages.
import base64
import io
from collections.abc import Callable
from typing import Any, cast

import pytest
from app.api.catalog_common import catalog_error
from app.catalog.inventory import CatalogIdentityInventory
from app.catalog.production_source_table import (
    HEADERS,
    parse_production_table,
    render_production_source_template,
)
from app.catalog.production_sources import (
    ProductionSource,
    ProductionSourceInputError,
    ProductionSourceRow,
    validate_production_source,
)
from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]
from openpyxl.styles import Font  # type: ignore[import-untyped]


def workbook(
    rows: list[list[object]], edit: Callable[[Any], None] = lambda ws: None
) -> str:
    book = Workbook()
    ws = book.active
    ws.title = "规格"
    for row in rows:
        ws.append(row)
    edit(ws)
    out = io.BytesIO()
    book.save(out)
    book.close()
    return base64.b64encode(out.getvalue()).decode()


def test_registration_template_is_blank_text_and_roundtrips_exact_codes() -> None:
    book = load_workbook(io.BytesIO(render_production_source_template()))
    sheet = book.active
    assert book.sheetnames == ["商品建档"]
    assert [cell.value for cell in sheet[1]] == HEADERS
    assert sheet.max_row == 1001
    assert sheet.freeze_panes == "A2"
    assert all(
        cell.value is None and cell.number_format == "@"
        for row in sheet.iter_rows(min_row=2)
        for cell in row
    )
    for cell, value in zip(sheet[2], ["0012", "Olive", "M", "00-AbC-M"], strict=True):
        cell.value = value
    output = io.BytesIO()
    book.save(output)
    book.close()
    source, locations = parse_production_table(
        "QA template", "xlsx", base64.b64encode(output.getvalue()).decode()
    )
    assert len(source.rows) == 1
    assert source.rows[0].style_code == "0012"
    assert source.rows[0].formal_sku == "00-AbC-M"
    assert locations == ["工作表“商品建档”，第2行"]


def test_keeps_leading_zeroes_and_physical_row_locations_and_accepts_font_style() -> (
    None
):
    raw = workbook(
        [["款号", "颜色", "尺码"], [], ["0012", "Olive", "M"]],
        lambda ws: setattr(ws["A3"], "font", Font(name="Arial", bold=True, size=18)),
    )
    result, places = parse_production_table("QA", "xlsx", raw)
    assert result.rows[0].style_code == "0012"
    assert places == ["工作表“规格”，第3行"]


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ([123, "Olive", "M"], "第2行A列"),
        (["=1+2", "Olive", "M"], "不允许公式"),
        (["QA", "Olive\u200b", "M"], "不可见"),
        (["QA", "Olive\ufffd", "M"], "乱码"),
        (["QA", "Olive", "/"], "C列（尺码）"),
        (["QA", "Olive", None], "C列（尺码）"),
    ],
)
def test_invalid_cells_are_located_in_chinese(row: list[object], expected: str) -> None:
    with pytest.raises(ProductionSourceInputError) as caught:
        parse_production_table("QA", "xlsx", workbook([["款号", "颜色", "尺码"], row]))
    assert expected in caught.value.public_message
    assert catalog_error(caught.value).status_code == 422


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (lambda ws: ws.merge_cells("B2:C2"), "合并区域B2:C2"),
        (lambda ws: setattr(ws.row_dimensions[2], "hidden", True), "隐藏行2"),
        (lambda ws: setattr(ws["A2"], "hyperlink", "https://example.com"), "外部链接"),
    ],
)
def test_hidden_merged_linked_content_is_blocked(
    edit: Callable[[Any], None], expected: str
) -> None:
    with pytest.raises(ProductionSourceInputError) as caught:
        parse_production_table(
            "QA",
            "xlsx",
            workbook([["款号", "颜色", "尺码"], ["QA", "Olive", "M"]], edit),
        )
    assert expected in caught.value.public_message


@pytest.mark.parametrize("kind", ["tsv", "csv"])
def test_text_header_and_multiple_cell_errors_keep_locations(kind: str) -> None:
    delimiter = "\t" if kind == "tsv" else ","
    content = "\n".join(
        delimiter.join(row) for row in [["款号", "颜色 ", "尺码"], ["QA", "Olive", "M"]]
    )
    with pytest.raises(
        ProductionSourceInputError, match="production_source_invalid"
    ) as caught:
        parse_production_table("QA", kind, content)
    assert "第1行B列" in caught.value.public_message
    assert "表头必须为“颜色”" in caught.value.public_message


def inventory() -> CatalogIdentityInventory:
    return CatalogIdentityInventory(
        (
            {
                "style_id": 1,
                "style_code": "QA",
                "standard_name": "QA",
                "status": "enabled",
            },
        ),
        (
            {
                "sku_id": 2,
                "style_id": 1,
                "style_code": "QA",
                "standard_color": "Olive",
                "standard_size": "M",
                "internal_display_sku": "QA-M",
                "code_status": "confirmed",
                "status": "enabled",
            },
        ),
    )


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"color": "olive"}, "请使用“Olive”"),
        ({"formal_sku": "OTHER"}, "主档正式编码不一致"),
        ({"color": "Sand", "formal_sku": "QA-M"}, "编码已属于其他"),
    ],
)
def test_known_identity_must_use_standard_spelling_and_code(
    row: dict[str, str], expected: str
) -> None:
    record = {"style_code": "QA", "color": "Olive", "size": "M"} | row
    source = ProductionSource(
        source_name="QA", rows=[ProductionSourceRow.model_validate(record)]
    )
    with pytest.raises(ProductionSourceInputError) as caught:
        validate_production_source(source, inventory(), ["工作表“规格”，第8行"])
    assert "第8行" in caught.value.public_message
    assert expected in caught.value.public_message


def test_new_specification_is_not_guessed_or_rejected_as_a_typo() -> None:
    source = ProductionSource(
        source_name="QA",
        rows=[ProductionSourceRow(style_code="QA", color="Light Olive", size="L")],
    )
    validate_production_source(source, inventory())
    assert source.rows[0].color == "Light Olive"


def test_duplicate_rows_cannot_hide_conflicting_codes() -> None:
    source = ProductionSource(
        source_name="QA",
        rows=[
            ProductionSourceRow(
                style_code="QA", color="Olive", size="M", formal_sku=code
            )
            for code in ["A", "B"]
        ],
    )
    with pytest.raises(ProductionSourceInputError) as caught:
        validate_production_source(source, CatalogIdentityInventory((), ()))
    assert "相同规格编码不一致" in caught.value.public_message


def test_multiple_errors_are_reported_together_without_partial_success() -> None:
    with pytest.raises(ProductionSourceInputError) as caught:
        parse_production_table(
            "QA", "tsv", "款号\t颜色\t尺码\nQA\tOlive\u200b\t/\nQA\t/\tL"
        )
    assert all(
        value in caught.value.public_message
        for value in ["第2行B列", "第2行C列", "第3行B列"]
    )


def test_corrupt_xlsx_does_not_expose_english_exception() -> None:
    with pytest.raises(ProductionSourceInputError) as caught:
        parse_production_table("QA", "xlsx", base64.b64encode(b"not a zip").decode())
    assert "文件无法读取" in caught.value.public_message
    assert "BadZipFile" not in caught.value.public_message


def test_formatting_is_accepted_without_changing_source_evidence() -> None:
    source, places = parse_production_table(
        "QA", "tsv", "款号\t颜色\t尺码\t正式SKU\n ＱＡ \t OLIVE \tｍ\t00-AbC-M"
    )
    from app.catalog.production_sources import prepare_production_source

    evidence = source.evidence()
    current = inventory()
    current.skus[0]["internal_display_sku"] = "00-AbC-M"
    prepared, adjustments = prepare_production_source(source, current, places)
    validate_production_source(prepared, current, places)
    assert (
        prepared.rows[0].style_code,
        prepared.rows[0].color,
        prepared.rows[0].size,
    ) == ("QA", "Olive", "M")
    assert prepared.rows[0].formal_sku == "00-AbC-M"
    assert source.evidence() == evidence
    assert source.rows[0].color == " OLIVE "
    assert len(adjustments) == 3
    assert adjustments[1]["location"] == "工作表“文本表格”，第2行"
    recreated = ProductionSource.model_validate(source.model_dump())
    assert prepare_production_source(recreated, current)[1] == adjustments


def test_ambiguous_catalog_format_is_blocked_before_product_projection() -> None:
    from app.catalog.production_sources import prepare_production_source

    current = inventory()
    ambiguous = CatalogIdentityInventory(
        current.styles,
        (
            current.skus[0] | {"standard_color": "Light Blue"},
            current.skus[0] | {"sku_id": 3, "standard_color": "Light  Blue"},
        ),
    )
    source = ProductionSource(
        source_name="QA",
        rows=[ProductionSourceRow(style_code="QA", color="light blue", size="M")],
    )
    with pytest.raises(ProductionSourceInputError) as caught:
        prepare_production_source(source, ambiguous)
    assert "多个主档写法" in caught.value.public_message


def test_formal_code_is_not_auto_corrected_and_legacy_source_digest_shape_stays() -> (
    None
):
    with pytest.raises(ProductionSourceInputError) as caught:
        parse_production_table(
            "QA", "tsv", "款号\t颜色\t尺码\t正式SKU\nQA\tOlive\tM\t 00-AbC-M "
        )
    assert "正式SKU" in caught.value.public_message
    source = ProductionSource(
        source_name="QA",
        rows=[ProductionSourceRow(style_code="QA", color="Olive", size="M")],
    )
    evidence_rows = source.evidence()["rows"]
    assert isinstance(evidence_rows, list) and isinstance(evidence_rows[0], dict)
    assert "source_location" not in evidence_rows[0]


def test_3xl_intake_reuses_identity_and_keeps_original_source_size() -> None:
    from app.catalog.production_sources import (
        prepare_production_source,
        project_production_source,
    )

    current = inventory()
    current.skus[0]["standard_size"] = "3XL"
    current.skus[0]["internal_display_sku"] = "00-AbC-XXXL"
    source = ProductionSource(
        source_name="QA 3XL",
        rows=[
            ProductionSourceRow(
                style_code="QA", color="Olive", size="XXXL", formal_sku="00-AbC-XXXL"
            )
        ],
    )
    prepared, adjustments = prepare_production_source(source, current)
    validate_production_source(prepared, current)
    projection, _ = project_production_source(prepared, current)
    assert source.rows[0].size == "XXXL"
    assert prepared.rows[0].size == "3XL"
    assert prepared.rows[0].formal_sku == "00-AbC-XXXL"
    assert adjustments[0]["before"] == "XXXL"
    assert adjustments[0]["after"] == "3XL"
    assert "3XL" in cast(str, adjustments[0]["reason"])
    assert len([row for row in projection.rows if row.section == "skus"]) == 1
