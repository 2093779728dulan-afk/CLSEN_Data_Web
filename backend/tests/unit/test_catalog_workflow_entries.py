from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from app.api.catalog_imports import list_catalog_imports
from app.api.errors import ApiError
from app.catalog.production_code_evidence import (
    ProductionCodeEvidenceInvalid,
    production_source_key,
)
from app.catalog.task_queries import (
    listing_progress,
    require_review_candidate,
    select_tasks,
    unprocessed_groups,
)
from app.site_context import CurrentSiteContext


def context() -> CurrentSiteContext:
    return CurrentSiteContext(
        principal_user_id=7,
        principal_roles=frozenset({"data_manager"}),
        site_id=1,
        site_code="qa",
        site_display_name="QA",
        site_config_version_id=1,
        site_config_revision=1,
        source_timezone="UTC",
        reporting_timezone="UTC",
        currency_code="USD",
    )


def test_listing_progress_preserves_decision_order_without_database_json_sort() -> None:
    connection = MagicMock()
    checks = []
    for check_id, import_id, status in [
        (2, 7, "validated"),
        (3, 8, "withdrawn"),
        (1, 6, "validated"),
    ]:
        checks.append(
            {
                "id": check_id,
                "import_id": import_id,
                "status": status,
                "version_number": None,
                "evidence_payload_json": {
                    "production_source": {
                        "parent_import_id": 5,
                        "selections": [{"sku_row_key": "sku-1"}],
                    }
                },
                "result_json": {
                    "selections": [{"row_id": "r1", "sku_row_key": "sku-1"}]
                },
            }
        )
    connection.execute.return_value.mappings.return_value.all.return_value = checks
    result = listing_progress(connection, 1, [5])[5]
    assert result["rows"]["r1"]["import_id"] == 7
    assert [candidate["import_id"] for candidate in result["candidates"]] == [6, 7, 8]


def test_original_listing_history_opens_source_not_generic_review() -> None:
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.all.return_value = [
        {
            "import_id": 4,
            "source_kind": "production",
            "status": "validated",
            "workflow_revision": 0,
            "evidence_payload_json": {
                "production_source": {
                    "source_schema": "amazon_listing_v1",
                    "source_name": "QA.xlsx",
                    "listing_rows": [{"row_id": "r1"}],
                    "selections": [],
                }
            },
            "approved_catalog_version_number": None,
        }
    ]
    result = json.loads(bytes(list_catalog_imports(context(), engine, 1).body))
    item = result["items"][0]
    assert item["record_kind"] == "listing_source"
    assert (
        item["review_path"]
        == "/catalog/production-sources?entry=amazon-listing&listing=4"
    )
    assert "evidence_payload_json" not in item


def test_all_saved_reviews_filter_before_pagination_independent_of_styles() -> None:
    records = [
        {
            "import_id": i,
            "status": "needs_attention",
            "source_kind": "production",
            "workflow_revision": 0,
            "updated_at": f"2026-10-15T10:{i:02d}:00",
            "evidence_payload_json": {
                "production_source": {
                    "source_name": f"QA-{i}",
                    "rows": [{"style_code": "NEW" if i == 1 else "OLD"}],
                }
            },
        }
        for i in range(1, 37)
    ]
    page = select_tasks(
        records,
        kind="review",
        status=None,
        scope_id=None,
        query="",
        page=2,
        page_size=25,
    )
    assert page["total_items"] == 36 and len(page["items"]) == 11
    assert any(r["import_id"] == 1 for r in page["items"])
    assert (
        select_tasks(
            records,
            kind="review",
            status=None,
            scope_id=None,
            query="QA-1",
            page=1,
            page_size=100,
        )["total_items"]
        == 11
    )


def test_duplicate_source_rows_count_once_and_active_candidate_is_not_remaining() -> (
    None
):
    rows = [
        {"row_id": f"r{i}", "seller_sku": "QA", "sheet": "QA店", "asin": "B000000001"}
        for i in range(1, 4)
    ]
    assert unprocessed_groups(rows, {}) == 1
    assert (
        unprocessed_groups(rows, {r["row_id"]: {"state": "in_candidate"} for r in rows})
        == 0
    )


def test_unknown_report_evidence_and_original_listing_cannot_use_review_writes() -> (
    None
):
    connection = MagicMock()
    for source in [
        {"source_schema": "amazon_listing_v1", "selections": []},
        {"report_selection": {"version": 99}},
    ]:
        connection.scalar.return_value = {"production_source": source}
        with pytest.raises(ApiError):
            require_review_candidate(connection, 1, 4)
    connection.scalar.return_value = {
        "production_source": {"report_selection": {"version": 99}}
    }
    with pytest.raises(ProductionCodeEvidenceInvalid):
        production_source_key(
            connection,
            site_id=1,
            export_id=1,
            raw_sha256_ref="sha256:" + "a" * 64,
            scope_ref="1",
        )


def test_generation_jobs_are_attention_tasks_with_own_identity() -> None:
    result = select_tasks(
        [
            {
                "record_kind": "generation_job",
                "task_id": "job:7",
                "status": "failed",
                "scope_ids": [3],
                "source_name": "生成任务",
                "updated_at": "2026-10-15",
                "review_path": "/catalog/maintenance?export_id=4",
            }
        ],
        kind="attention",
        status=None,
        scope_id=3,
        query="",
        page=1,
        page_size=25,
    )
    assert result["items"][0]["task_id"] == "job:7" and result["counts"] == {
        "review": 0,
        "attention": 1,
    }


def test_name_and_category_drafts_have_their_own_tasks_and_stale_classification() -> (
    None
):
    draft = {
        "record_kind": "style_change",
        "task_id": "style-change:4",
        "status": "draft",
        "scope_ids": [],
        "source_name": "名称/分类 · QA",
        "updated_at": "2026-10-16",
        "review_path": "/catalog/styles/13?change_draft=4",
    }
    current = select_tasks(
        [draft],
        kind="review",
        status=None,
        scope_id=None,
        query="",
        page=1,
        page_size=25,
    )
    assert current["items"][0]["task_id"] == "style-change:4"
    assert (
        select_tasks(
            [draft | {"stale": True}],
            kind="attention",
            status=None,
            scope_id=None,
            query="",
            page=1,
            page_size=25,
        )["total_items"]
        == 1
    )
