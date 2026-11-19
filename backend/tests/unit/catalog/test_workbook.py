from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from app.catalog.ooxml import CatalogWorkbookUnsafeError
from app.catalog.workbook import (
    SHEET_HEADERS,
    SHEET_NAMES,
    CatalogWorkbookData,
    CatalogWorkbookRowLimitError,
    parse_catalog_workbook,
    render_catalog_workbook,
    workbook_from_export_payload,
)


@pytest.mark.parametrize(
    ("sheet", "cell", "value", "position", "message"),
    [
        ("款式主档", "C1", "款号 ", "第1行C列", "表头"),
        ("款式主档", "C2", 100, "第2行C列", "文本"),
        ("款式主档", "C2", " 100", "第2行C列", "空格"),
        ("款式主档", "C2", "=100", "C2", "公式"),
    ],
)
def test_bad_cells_report_safe_template_location(
    sheet: str, cell: str, value: str | int, position: str, message: str
) -> None:
    import io

    from app.api.catalog_common import catalog_error
    from openpyxl import load_workbook  # type: ignore[import-untyped]

    book = load_workbook(io.BytesIO(render_catalog_workbook(_workbook())))
    book[sheet][cell] = value
    out = io.BytesIO()
    book.save(out)
    book.close()
    with pytest.raises(CatalogWorkbookUnsafeError) as caught:
        parse_catalog_workbook(out.getvalue())
    error = catalog_error(caught.value)
    assert error.status_code == 422
    assert all(
        text in cast(dict[str, str], error.detail)["message"]
        for text in [sheet, position, message]
    )


def _workbook() -> CatalogWorkbookData:
    metadata = (
        ("模板版本", "product_catalog_workbook_v1"),
        ("目录导出ID", "export-1"),
        ("站点代码", "CN"),
        ("Seller Account", "seller"),
        ("Marketplace", "amazon_us"),
        ("基础目录版本", None),
        ("来源快照摘要", "sha256:" + "0" * 64),
        ("规范化规则版本", "catalog_identity_key_v1"),
        ("生成时间", datetime(2026, 8, 21, 0, 0, tzinfo=UTC)),
    )
    return CatalogWorkbookData(
        rows={
            "生成信息": metadata,
            "款式主档": (
                (
                    "style-1",
                    None,
                    "100",
                    None,
                    "enabled",
                    1,
                    1,
                    "2026-01-01",
                    "2026-01-02",
                    None,
                ),
            ),
            "SKU变体": (),
            "SellerSKU映射": (),
            "待处理异常": (),
            "来源证据": (),
        }
    )


def test_six_sheet_generator_round_trips_through_same_safe_parser() -> None:
    source = _workbook()
    archive = render_catalog_workbook(source)
    parsed = parse_catalog_workbook(archive)

    assert tuple(parsed.rows) == SHEET_NAMES
    assert parsed.rows["生成信息"][0] == (
        "模板版本",
        "product_catalog_workbook_v1",
    )
    assert parsed.rows["生成信息"][-1][1] == "2026-08-21T00:00:00Z"
    assert parsed.rows["款式主档"] == source.rows["款式主档"]


def test_headers_are_exact_and_formula_is_rejected_before_business_parse() -> None:
    render_catalog_workbook(_workbook())
    assert SHEET_HEADERS["生成信息"] == ("字段", "值")

    # The renderer must never create formulas even when text begins with '='.
    data = _workbook()
    rows = dict(data.rows)
    style = list(rows["款式主档"][0])
    style[3] = "=1+1"
    rows["款式主档"] = (tuple(style),)
    parsed = parse_catalog_workbook(
        render_catalog_workbook(CatalogWorkbookData(rows=rows))
    )
    assert parsed.rows["款式主档"][0][3] == "=1+1"


def test_invalid_cell_type_and_row_capacity_are_rejected() -> None:
    rows = dict(_workbook().rows)
    style = list(rows["款式主档"][0])
    style[5] = "1"
    rows["款式主档"] = (tuple(style),)
    with pytest.raises(CatalogWorkbookUnsafeError):
        render_catalog_workbook(CatalogWorkbookData(rows=rows))

    rows = dict(_workbook().rows)
    rows["款式主档"] = tuple(rows["款式主档"]) * 30_001
    with pytest.raises(CatalogWorkbookRowLimitError) as captured:
        render_catalog_workbook(CatalogWorkbookData(rows=rows))
    assert captured.value.violations[0].code == "sheet_row_limit"


def test_sheets_and_metadata_are_exact() -> None:
    rows = dict(_workbook().rows)
    rows.pop("来源证据")
    with pytest.raises(CatalogWorkbookUnsafeError):
        render_catalog_workbook(CatalogWorkbookData(rows=rows))


def test_report_projection_preserves_formal_products_without_report_observations() -> (
    None
):
    from app.catalog.import_service import project_catalog_workbook

    workbook = workbook_from_export_payload(
        export_id=41,
        site_code="QA",
        seller_account_display_name="QA",
        base_catalog_version_id=1,
        snapshot_digest=b"s" * 32,
        normalization_manifest_id="manifest-v1",
        generated_at=datetime(2026, 8, 21, tzinfo=UTC),
        candidates={
            "styles": [],
            "variants": [],
            "mappings": [],
            "exclusions": [],
            "exceptions": [],
        },
        evidence={"summaries": []},
        existing_styles=(
            {
                "style_id": 7,
                "style_code": "QA-FACTORY",
                "standard_name": "QA product",
                "status": "enabled",
            },
        ),
        existing_skus=(
            {
                "sku_id": 9,
                "style_code": "QA-FACTORY",
                "internal_display_sku": "QA-OLIVE-M",
                "standard_color": "Olive",
                "standard_size": "M",
                "status": "enabled",
            },
        ),
    )
    projection = project_catalog_workbook(
        parse_catalog_workbook(render_catalog_workbook(workbook))
    )
    assert {(row.section, row.projection_state) for row in projection.rows} == {
        ("styles", "included"),
        ("skus", "included"),
    }
    assert not projection.issues


@pytest.mark.parametrize("standard_name", ["Existing style", ""])
def test_task6_payload_projects_to_complete_round_trip_rows(standard_name: str) -> None:
    seller = {
        "source_ref_id": "src_1",
        "preview": "100-Red-S",
        "sha256": "sha256:" + "1" * 64,
        "is_unsafe": False,
        "is_truncated": False,
    }
    workbook = workbook_from_export_payload(
        export_id=41,
        site_code="US",
        seller_account_display_name="seller",
        base_catalog_version_id=None,
        snapshot_digest=b"s" * 32,
        normalization_manifest_id="manifest-v1",
        generated_at=datetime(2026, 8, 21, tzinfo=UTC),
        candidates={
            "styles": [
                {
                    "row_key": "style_1",
                    "style_code": "100",
                    "standard_name": None,
                    "candidate_seller_sku_count": 1,
                    "source_title_count": 1,
                }
            ],
            "variants": [
                {
                    "row_key": "variant_1",
                    "style_row_key": "style_1",
                    "style_code": "100",
                    "source_color": "Red",
                    "source_size": "S",
                    "observed_seller_sku_count": 1,
                }
            ],
            "mappings": [
                {
                    "row_key": "mapping_1",
                    "seller_sku": seller,
                    "report_types": ["business_report"],
                    "candidate_variant_row_key": "variant_1",
                    "target_sku_id": 9,
                }
            ],
            "exclusions": [],
            "exceptions": [],
        },
        evidence={
            "summaries": [
                {
                    "report_source_scope_id": 1,
                    "report_type": "business_report",
                    "source_key_ids": [1],
                    "seller_sku": seller,
                    "first_seen_date": "2026-01-01",
                    "latest_seen_date": "2026-01-02",
                    "occurrence_count": 2,
                    "title_distinct_count": 1,
                    "parent_asin_distinct_count": 1,
                    "child_asin_distinct_count": 1,
                    "fnsku_distinct_count": 1,
                    "latest_title": None,
                    "evidence_set_digest": "sha256:" + "2" * 64,
                }
            ]
        },
        existing_styles=(
            {
                "style_id": 7,
                "style_code": "\uff11\uff10\uff10",
                "standard_name": standard_name,
                "status": "enabled",
            },
        ),
        existing_skus=(
            {
                "sku_id": 9,
                "style_code": "100",
                "internal_display_sku": "100-RED-S",
                "standard_color": "RED",
                "standard_size": "S",
                "status": "enabled",
            },
        ),
    )

    parsed = parse_catalog_workbook(render_catalog_workbook(workbook))
    assert parsed.rows == workbook.rows
    assert parsed.rows["款式主档"][0][3] == (standard_name or None)
    assert parsed.rows["款式主档"][0][9:11] == (
        "2026-01-01",
        "2026-01-02",
    )
    assert parsed.rows["生成信息"][0][1] == "product_catalog_workbook_v2"
    assert parsed.rows["款式主档"][0][4:6] == ("保持原值", None)
    assert parsed.rows["款式主档"][0][1:4] == ("7", "100", standard_name or None)
    assert parsed.rows["SKU变体"][0][1:7] == (
        "9",
        "style_1",
        "100-RED-S",
        "RED",
        "S",
        "enabled",
    )
    assert parsed.rows["SellerSKU映射"][0][10:12] == (2, 0)
    assert parsed.rows["SellerSKU映射"][0][5:7] == ("mapped", "variant_1")
    assert len(parsed.rows["来源证据"]) == 1

    rows = dict(_workbook().rows)
    rows["生成信息"] = rows["生成信息"][:-1]
    with pytest.raises(CatalogWorkbookUnsafeError):
        render_catalog_workbook(CatalogWorkbookData(rows=rows))
