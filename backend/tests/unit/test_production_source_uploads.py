"""Local raw-table uploads stay scoped, resumable and unposted."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Literal, cast
from unittest.mock import MagicMock
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api.errors import ApiError
from app.api.production import source_draft_list, source_draft_upload
from app.config import Settings
from app.production.order_source_drafts import (
    SAMPLES,
    SaveSourceDraft,
    SourceDraftLine,
    save_source_draft,
    source_detail,
)
from app.production.shipment_source_drafts import (
    PackingDraftLine,
    SavePackingDraft,
    packing_detail,
    save_packing_draft,
)
from app.production.source_registry import validate_upload
from app.site_context import CurrentSiteContext


def context(
    *,
    actor: int = 1,
    site_id: int = 1,
    role: str = "admin",
    site: str = "DEMO_LOCAL_ONLY",
) -> CurrentSiteContext:
    return CurrentSiteContext(
        principal_user_id=actor,
        principal_roles=frozenset({role}),
        site_id=site_id,
        site_code=site,
        site_display_name="Local",
        site_config_version_id=1,
        site_config_revision=1,
        source_timezone="UTC",
        reporting_timezone="UTC",
        currency_code="USD",
    )


def workbook(kind: str = "orders") -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    if kind == "orders":
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
                datetime(2026, 9, 13),
                None,
                "虚构验证",
                "QA",
                "蓝",
                "QA-BLUE-S",
                None,
                7,
                "原备注",
            ]
        )
    else:
        sheet.title = "Sheet1"
        sheet.append(["SKU", "ASIN", "FNSKU", None, "箱1", "箱2", None, "差异"])
        sheet.append(
            ["QA-BLUE-S", "QA-ASIN", "QA-FNSKU", 7, 4, 3, "=SUM(E2:F2)", "=D2-G2"]
        )
        sheet.append(
            [
                None,
                None,
                None,
                "=SUM(D2:D2)",
                "=SUM(E2:E2)",
                "=SUM(F2:F2)",
                "=SUM(E3:F3)",
                "=D3-G3",
            ]
        )
        sheet.append(["重量", None, None, None, 99, 99])
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def request(root: Path, raw: bytes = b"") -> MagicMock:
    req = MagicMock()
    req.app.state.settings = Settings(
        production_demo_mode=True, production_order_draft_root=str(root)
    )

    async def stream() -> AsyncIterator[bytes]:
        yield raw[:100]
        yield raw[100:]

    req.stream = stream
    return req


def upload(
    root: Path,
    kind: Literal["orders", "shipments"] = "orders",
    raw: bytes | None = None,
    actor: int = 1,
) -> dict[str, object]:
    return cast(
        dict[str, object],
        asyncio.run(
            source_draft_upload(
                kind,
                request(root, raw if raw is not None else workbook(kind)),
                context(actor=actor),
                filename="虚构核对.xlsx",
            )
        ),
    )


def test_upload_duplicate_returns_same_source_without_overwriting_draft(
    tmp_path: Path,
) -> None:
    raw = workbook()
    first = upload(tmp_path, raw=raw)
    item = cast(dict[str, object], first["item"])
    source_id = str(item["source_id"])
    settings = request(tmp_path).app.state.settings
    source = source_detail(settings, context(), source_id)
    body = SaveSourceDraft(
        source_digest=str(source["source_digest"]),
        revision=0,
        business_date="2026-09-13",
        lines=[
            SourceDraftLine(source_row=2, expected_units="9", review_note="核对说明")
        ],
    )
    saved = save_source_draft(settings, context(), source_id, body, uuid4())
    second = upload(tmp_path, raw=raw)
    assert second["duplicate"] is True
    assert cast(dict[str, object], second["item"])["revision"] == 1
    assert source_detail(settings, context(), source_id)["saved_draft"] == saved
    assert item["source_units"] == "7" and saved["draft_units"] == "9"
    assert source["confirmation_enabled"] is False
    assert len(list((tmp_path / "uploads" / "1" / "1").glob("upload-*"))) == 1
    original_rows = saved["original_rows"]
    assert isinstance(original_rows, list) and isinstance(original_rows[0], dict)
    assert original_rows[0]["sku_id"] is None
    with pytest.raises(ApiError) as stale:
        save_source_draft(settings, context(), source_id, body, uuid4())
    assert stale.value.status_code == 409


def test_existing_authorized_file_returns_legacy_id_and_preserves_old_storage(
    tmp_path: Path,
) -> None:
    raw = workbook()
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / SAMPLES["september-11"]).write_bytes(raw)
    result = upload(tmp_path, raw=raw)
    assert result["duplicate"] is True
    assert cast(dict[str, object], result["item"])["source_id"] == "september-11"
    assert not (tmp_path / "uploads").exists()


def test_upload_and_draft_are_isolated_by_actor_and_site(tmp_path: Path) -> None:
    result = upload(tmp_path)
    source_id = str(cast(dict[str, object], result["item"])["source_id"])
    settings = request(tmp_path).app.state.settings
    for other in [context(actor=2), context(site_id=2)]:
        with pytest.raises(ApiError) as missing:
            source_detail(settings, other, source_id)
        assert missing.value.status_code == 404
        listed = cast(dict[str, object], source_draft_list(request(tmp_path), other))
        listed_items = listed["items"]
        assert isinstance(listed_items, list)
        assert all(
            isinstance(item, dict) and item["source_id"] != source_id
            for item in listed_items
        )
    assert upload(tmp_path, actor=2)["duplicate"] is False


def test_packing_upload_retains_counts_and_unverified_dispatch(tmp_path: Path) -> None:
    result = upload(tmp_path, "shipments")
    source_id = str(cast(dict[str, object], result["item"])["source_id"])
    settings = request(tmp_path).app.state.settings
    source = packing_detail(settings, context(), source_id)
    assert source["source_units"] == "7" and source["filename_date_hint"] == ""
    body = SavePackingDraft(
        source_digest=str(source["source_digest"]),
        revision=0,
        business_date="2026-09-13",
        lines=[PackingDraftLine(source_row=2, actual_units="5")],
    )
    saved = save_packing_draft(settings, context(), body, uuid4(), source_id)
    assert saved["sample_id"] == source_id and saved["draft_units"] == "5"
    assert saved["dispatch_status"] == "ASSUMED_DISPATCHED"
    assert (
        saved["date_status"] == "USER_ENTERED_UNVERIFIED"
        and saved["confirmation_enabled"] is False
    )
    original_rows = saved["original_rows"]
    assert isinstance(original_rows, list) and isinstance(original_rows[0], dict)
    assert original_rows[0]["order_line_id"] is None
    with pytest.raises(ApiError):
        source_detail(settings, context(), source_id)


@pytest.mark.parametrize(
    "kind,raw",
    [
        ("orders", b"not a workbook"),
        ("orders", workbook("shipments")),
        ("shipments", workbook()),
        ("orders", b"x" * 2_000_001),
    ],
    ids=["invalid-file", "wrong-order-format", "wrong-packing-format", "oversize"],
)
def test_invalid_upload_never_registers_source(
    tmp_path: Path, kind: Literal["orders", "shipments"], raw: bytes
) -> None:
    with pytest.raises(ApiError) as rejected:
        upload(tmp_path, kind, raw)
    assert rejected.value.status_code in {413, 422}
    assert not (tmp_path / "uploads").exists()


def test_viewer_and_disabled_scope_cannot_upload(tmp_path: Path) -> None:
    for ctx, expected in [(context(role="viewer"), 403), (context(site="OTHER"), 404)]:
        with pytest.raises(ApiError) as rejected:
            asyncio.run(
                source_draft_upload(
                    "orders", request(tmp_path, workbook()), ctx, "x.xlsx"
                )
            )
        assert rejected.value.status_code == expected
    assert not (tmp_path / "uploads").exists()


def test_arbitrary_paths_and_tampered_source_cannot_read_or_save(
    tmp_path: Path,
) -> None:
    raw = workbook()
    result = upload(tmp_path, raw=raw)
    source_id = str(cast(dict[str, object], result["item"])["source_id"])
    settings = request(tmp_path).app.state.settings
    for value in ["../september-11", "upload-orders-invalid"]:
        with pytest.raises(ApiError) as rejected:
            source_detail(settings, context(), value)
        assert rejected.value.status_code == 404
    source_file = tmp_path / "uploads" / "1" / "1" / source_id / "source.xlsx"
    source_file.write_bytes(b"changed")
    with pytest.raises(ApiError) as changed:
        source_detail(settings, context(), source_id)
    assert changed.value.status_code == 409
    assert source_id.endswith(hashlib.sha256(raw).hexdigest())


def test_zip_expansion_is_bounded_before_excel_parsing() -> None:
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as book:
        book.writestr("xl/workbook.xml", b"x" * 30_000_001)
    with pytest.raises(ApiError) as oversized:
        validate_upload("x.xlsx", stream.getvalue())
    assert oversized.value.status_code == 413
