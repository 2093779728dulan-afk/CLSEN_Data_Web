from datetime import datetime
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api.errors import ApiError
from app.api.production import order_source_save
from app.config import Settings
from app.production.order_source_drafts import (
    SAMPLES,
    SaveSourceDraft,
    SourceDraftLine,
    draft_root,
    read_source,
    save_source_draft,
    source_detail,
)
from app.site_context import CurrentSiteContext


def context(
    *roles: str, actor: int = 1, site: str = "DEMO_LOCAL_ONLY"
) -> CurrentSiteContext:
    return CurrentSiteContext(
        principal_user_id=actor,
        principal_roles=frozenset(roles),
        site_id=1,
        site_code=site,
        site_display_name="Local",
        site_config_version_id=1,
        site_config_revision=1,
        source_timezone="UTC",
        reporting_timezone="UTC",
        currency_code="USD",
    )


@pytest.fixture
def sample(tmp_path: Path) -> tuple[Settings, Path]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "9月底发货"
    sheet.append(
        [
            "下单日期",
            "出货日期",
            "品名",
            "款号",
            "颜色",
            "SKU",
            "IMAGE",
            "订单数量",
            "备注",
        ]
    )
    sheet.append(
        [
            datetime(2026, 9, 11),
            None,
            "虚构样表",
            "TEST",
            "蓝",
            "TEST-BLUE-S",
            None,
            7,
            "原备注",
        ]
    )
    sheet.append(
        [datetime(2026, 9, 11), None, "虚构样表", "TEST", "蓝", "XTEST-BLUE-M", None, 9]
    )
    sheet.append(
        [datetime(2026, 9, 7), None, None, None, None, None, None, "=SUM(H2:H3)"]
    )
    book.create_sheet("Sheet1").append(["不属于本次范围", 999])
    book.save(inputs / SAMPLES["september-11"])
    book.close()
    return Settings(
        production_demo_mode=True, production_order_draft_root=str(tmp_path)
    ), tmp_path


def payload(root: Path) -> SaveSourceDraft:
    source = read_source(root, "september-11")
    return SaveSourceDraft(
        source_digest=str(source["source_digest"]),
        revision=0,
        business_date="2026-09-11",
        business_number="LOCAL-TEST",
        lines=[
            SourceDraftLine(
                source_row=int(str(row["source_row"])),
                expected_units=str(row["expected_units"]),
            )
            for row in cast(list[dict[str, object]], source["rows"])
        ],
    )


def test_business_rows_exclude_auxiliary_and_footer_dates(
    sample: tuple[Settings, Path],
) -> None:
    _, root = sample
    source = read_source(root, "september-11")
    assert source["source_units"] == "16"
    assert source["business_date"] == "2026-09-11"
    assert source["excluded_rows"] == [4]
    assert source["excluded_sheets"] == ["Sheet1"]
    rows = cast(list[dict[str, object]], source["rows"])
    issues = cast(list[dict[str, object]], source["issues"])
    assert rows[1]["sku_code"] == "XTEST-BLUE-M"
    assert issues[0]["row"] == 3
    assert all(row["sku_id"] is None for row in rows)
    assert source["confirmation_enabled"] is False


def test_draft_persists_original_values_and_replay_without_new_revision(
    sample: tuple[Settings, Path],
) -> None:
    settings, root = sample
    body = payload(root)
    changed = body.model_copy(update={"notes": "仅核对数量"})
    key = uuid4()
    saved = save_source_draft(settings, context("admin"), "september-11", changed, key)
    assert saved["status"] == "IMPORT_DRAFT"
    assert saved["revision"] == 1
    assert (
        cast(list[dict[str, object]], saved["original_rows"])[1]["sku_code"]
        == "XTEST-BLUE-M"
    )
    assert (
        save_source_draft(settings, context("admin"), "september-11", changed, key)
        == saved
    )
    assert (
        source_detail(settings, context("admin"), "september-11")["saved_draft"]
        == saved
    )
    assert (
        source_detail(settings, context("admin", actor=2), "september-11")[
            "saved_draft"
        ]
        is None
    )


def test_stale_or_reused_operation_cannot_overwrite_draft(
    sample: tuple[Settings, Path],
) -> None:
    settings, root = sample
    body = payload(root)
    key = uuid4()
    save_source_draft(settings, context("admin"), "september-11", body, key)
    with pytest.raises(ApiError) as stale:
        save_source_draft(settings, context("admin"), "september-11", body, uuid4())
    assert stale.value.status_code == 409
    with pytest.raises(ApiError) as reused:
        save_source_draft(
            settings,
            context("admin"),
            "september-11",
            body.model_copy(update={"notes": "different"}),
            key,
        )
    assert (
        cast(dict[str, object], reused.value.detail)["code"] == "idempotency_key_reused"
    )


def test_cannot_drop_raw_rows_or_change_source_identity(
    sample: tuple[Settings, Path],
) -> None:
    settings, root = sample
    body = payload(root)
    with pytest.raises(ApiError) as dropped:
        save_source_draft(
            settings,
            context("admin"),
            "september-11",
            body.model_copy(update={"lines": body.lines[:1]}),
            uuid4(),
        )
    assert (
        cast(dict[str, object], dropped.value.detail)["code"] == "source_rows_changed"
    )
    with pytest.raises(ApiError) as replaced:
        save_source_draft(
            settings,
            context("admin"),
            "september-11",
            body.model_copy(update={"source_digest": "0" * 64}),
            uuid4(),
        )
    assert (
        cast(dict[str, object], replaced.value.detail)["code"]
        == "source_snapshot_changed"
    )


def test_viewer_and_other_scope_cannot_save_real_source_drafts(
    sample: tuple[Settings, Path],
) -> None:
    settings, root = sample
    request = MagicMock()
    request.app.state.settings = settings
    with pytest.raises(ApiError) as forbidden:
        order_source_save(
            "september-11", request, context("viewer"), payload(root), uuid4()
        )
    assert forbidden.value.status_code == 403
    with pytest.raises(ApiError) as scope:
        draft_root(settings, context("admin", site="OTHER"))
    assert scope.value.status_code == 404


def test_real_source_drafts_default_closed_and_local_only(tmp_path: Path) -> None:
    with pytest.raises(ApiError):
        draft_root(Settings(), context("admin"))
    with pytest.raises(ValueError, match="explicit local demo root"):
        Settings(production_order_draft_root=str(tmp_path))
