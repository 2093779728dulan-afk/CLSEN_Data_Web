from pathlib import Path
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api.errors import ApiError
from app.api.production import shipment_source_save
from app.config import Settings
from app.production.shipment_source_drafts import (
    PACKING_FILENAME,
    PackingDraftLine,
    SavePackingDraft,
    packing_detail,
    read_packing_source,
    save_packing_draft,
)
from app.site_context import CurrentSiteContext
from pydantic import ValidationError


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
    (tmp_path / "inputs").mkdir()
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(["SKU", "ASIN", "FNSKU", None, "箱1", "箱2", None, "差异"])
    sheet.append(
        ["TEST-BLUE-M", "TEST-ASIN-1", "TEST-FNSKU-1", 6, 4, 2, "=SUM(E2:F2)", "=D2-G2"]
    )
    sheet.append(
        [
            "TEST-RED-L",
            "TEST-ASIN-2",
            "TEST-FNSKU-2",
            5,
            None,
            5,
            "=SUM(E3:F3)",
            "=D3-G3",
        ]
    )
    sheet.append(
        [
            None,
            None,
            None,
            "=SUM(D2:D3)",
            "=SUM(E2:E3)",
            "=SUM(F2:F3)",
            "=SUM(E4:F4)",
            "=D4-G4",
        ]
    )
    sheet.append(["重量KG", None, None, None, 21.4, 21.5])
    sheet.append(["宽", None, None, None, 100, 200])
    book.create_sheet("Sheet2").append(["辅助数据", 999])
    book.create_sheet("Sheet3")
    book.save(tmp_path / "inputs" / PACKING_FILENAME)
    book.close()
    return Settings(
        production_demo_mode=True, production_order_draft_root=str(tmp_path)
    ), tmp_path


def payload(root: Path) -> SavePackingDraft:
    source = read_packing_source(root)
    rows = cast(list[dict[str, object]], source["rows"])
    return SavePackingDraft(
        source_digest=str(source["source_digest"]),
        revision=0,
        lines=[
            PackingDraftLine(
                source_row=int(str(row["source_row"])),
                actual_units=str(row["source_units"]),
            )
            for row in rows
        ],
    )


def test_box_counts_once_and_file_date_does_not_become_actual_date(
    sample: tuple[Settings, Path],
) -> None:
    _, root = sample
    source = read_packing_source(root)
    assert source["source_units"] == "11"
    assert source["box1_units"] == "4"
    assert source["box2_units"] == "7"
    assert source["excluded_rows"] == [4, 5, 6]
    assert source["business_date"] == ""
    assert source["dispatch_status"] == "ASSUMED_DISPATCHED"
    assert source["confirmation_enabled"] is False
    assert all(
        row["sku_id"] is None and row["order_line_id"] is None
        for row in cast(list[dict[str, object]], source["rows"])
    )


def test_persist_and_replay_keep_assumption_and_unresolved_order(
    sample: tuple[Settings, Path],
) -> None:
    settings, root = sample
    body = payload(root)
    body.lines[0] = body.lines[0].model_copy(
        update={"order_reference_note": "仅候选订单X"}
    )
    key = uuid4()
    saved = save_packing_draft(settings, context("admin"), body, key)
    assert saved["draft_units"] == "11"
    assert saved["dispatch_status"] == "ASSUMED_DISPATCHED"
    assert saved["date_status"] == "UNVERIFIED"
    assert saved["order_status"] == "UNRESOLVED"
    assert save_packing_draft(settings, context("admin"), body, key) == saved
    assert packing_detail(settings, context("admin"))["saved_draft"] == saved
    assert packing_detail(settings, context("viewer", actor=2))["saved_draft"] is None
    with pytest.raises(ValidationError):
        SavePackingDraft.model_validate(
            {**body.model_dump(), "dispatch_status": "CONFIRMED"}
        )


def test_stale_revision_reused_key_and_source_rows_cannot_overwrite(
    sample: tuple[Settings, Path],
) -> None:
    settings, root = sample
    body = payload(root)
    key = uuid4()
    save_packing_draft(settings, context("admin"), body, key)
    for changed, next_key, expected in [
        (body, uuid4(), "source_draft_revision_conflict"),
        (body.model_copy(update={"notes": "different"}), key, "idempotency_key_reused"),
        (
            body.model_copy(update={"lines": body.lines[:1]}),
            uuid4(),
            "source_rows_changed",
        ),
        (
            body.model_copy(update={"source_digest": "0" * 64}),
            uuid4(),
            "source_snapshot_changed",
        ),
    ]:
        with pytest.raises(ApiError) as failure:
            save_packing_draft(settings, context("admin"), changed, next_key)
        assert cast(dict[str, object], failure.value.detail)["code"] == expected


def test_manual_date_remains_unverified(sample: tuple[Settings, Path]) -> None:
    settings, root = sample
    saved = save_packing_draft(
        settings,
        context("admin"),
        payload(root).model_copy(update={"business_date": "2026-09-04"}),
        uuid4(),
    )
    assert saved["date_status"] == "USER_ENTERED_UNVERIFIED"
    assert saved["confirmation_enabled"] is False


def test_viewer_other_scope_and_disabled_environment_cannot_write(
    sample: tuple[Settings, Path],
) -> None:
    settings, root = sample
    request = MagicMock()
    request.app.state.settings = settings
    with pytest.raises(ApiError) as forbidden:
        shipment_source_save(request, context("viewer"), payload(root), uuid4())
    assert forbidden.value.status_code == 403
    with pytest.raises(ApiError):
        packing_detail(settings, context("admin", site="OTHER"))
    with pytest.raises(ApiError):
        packing_detail(Settings(), context("admin"))


def test_formulas_in_box_counts_cannot_become_shipment_units(
    sample: tuple[Settings, Path],
) -> None:
    _, root = sample
    book = openpyxl.load_workbook(root / "inputs" / PACKING_FILENAME)
    book["Sheet1"]["E2"] = "=1+1"
    book.save(root / "inputs" / PACKING_FILENAME)
    book.close()
    with pytest.raises(ApiError) as formula:
        read_packing_source(root)
    assert cast(dict[str, object], formula.value.detail)["code"] == "invalid_box_units"
