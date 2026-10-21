from __future__ import annotations

from datetime import UTC, datetime

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


def test_task6_payload_projects_to_complete_round_trip_rows() -> None:
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
                "standard_name": "Existing style",
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
    assert parsed.rows["款式主档"][0][9:11] == (
        "2026-01-01",
        "2026-01-02",
    )
    assert parsed.rows["生成信息"][0][1] == "product_catalog_workbook_v2"
    assert parsed.rows["款式主档"][0][4:6] == ("保持原值", None)
    assert parsed.rows["款式主档"][0][1:4] == ("7", "100", "Existing style")
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
