"""Business preview must never claim an operation or create a document."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from app.api.errors import ApiError
from app.manual_tables.handoff import handoff_batch
from app.manual_tables.schemas import Command, HandoffCommand, Kind, Options
from app.manual_tables.service import ManualTables, digest
from tests.unit.test_manual_table_extraction import workbook
from tests.unit.test_manual_table_service import service


def prepared(
    monkeypatch: pytest.MonkeyPatch,
    kind: Kind = "orders",
    context: dict[str, str] | None = None,
) -> tuple[ManualTables, dict[str, Any], dict[str, Any], Mock, Command]:
    svc = service(monkeypatch)
    if kind == "inventory":
        svc.settings = replace(
            svc.settings,
            production_inventory_review_writes_enabled=True,
            production_inventory_source_root=str(Path(__file__).parent),
        )
    options = Options(
        context=context or {"date": "2026-10-19", "source_note": "独立虚构下单资料"}
    )
    raw = workbook([["款号", "颜色", "尺码", "数量"], ["99001", "Blue", "M", 3]])
    result = svc.analyze(raw, kind, options)
    batch = {
        "id": str(uuid4()),
        "kind": kind,
        "revision": 2,
        "filename": "虚构.xlsx",
        "source_digest": "a" * 64,
        "options": options.model_dump(),
        "result": result,
        "target": None,
    }
    row = {"revision": 2, "target_json": None}
    connection = Mock()
    connection.execute.side_effect = AssertionError("preview attempted a write")

    @contextmanager
    def begin() -> Iterator[Mock]:
        yield connection

    svc.engine = Mock()
    svc.engine.begin = begin
    monkeypatch.setattr(svc, "get", lambda _: batch)
    monkeypatch.setattr(svc, "load", lambda *args, **kwargs: row)
    monkeypatch.setattr(svc, "source", lambda _: raw)
    monkeypatch.setattr(svc, "replay", lambda *args: None)
    monkeypatch.setattr(
        "app.manual_tables.handoff.production_skus",
        lambda *args: {"31": {"catalog_version": "7:2"}},
    )
    monkeypatch.setattr("app.api.production._operation_actor", lambda *args: "虚构用户")
    command = Command(
        expected_revision=2,
        operation_token=str(uuid4()),
        options=options,
        target=cast(
            Literal["order", "shipment", "inventory_review"],
            {
                "orders": "order",
                "packing": "shipment",
                "inventory": "inventory_review",
            }[kind],
        ),
        reason="人工表格核对与整理",
    )
    return svc, batch, row, connection, command


def test_order_preview_reports_similar_records_without_creating_or_claiming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, batch, row, con, command = prepared(monkeypatch)
    calls = []

    def gateway(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((args[2:4], kwargs))
        return {
            "candidates": [
                {"id": "7", "system_number": "PO-QA-7", "status": "CONFIRMED"}
            ]
        }

    monkeypatch.setattr("app.manual_tables.handoff.production_request", gateway)
    preview = handoff_batch(svc, batch["id"], command, preview_only=True)
    assert preview["target_kind"] == "order"
    assert preview["total_units"] == "3" and preview["sku_count"] == 1
    assert preview["inventory_effect_units"] == "0"
    assert preview["candidates"][0]["url"] == "/production/orders/7"
    assert len(preview["handoff_preview_hash"]) == 64
    assert calls[0][0] == ("POST", "sources/orders/check")
    con.execute.assert_not_called()
    assert row["target_json"] is None


def test_inventory_preview_is_only_source_review_and_never_calls_java(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, batch, _, con, command = prepared(monkeypatch, "inventory")
    gateway = Mock(side_effect=AssertionError("inventory source preview called Java"))
    monkeypatch.setattr("app.manual_tables.handoff.production_request", gateway)
    value = handoff_batch(svc, batch["id"], command, preview_only=True)
    assert value["target_kind"] == "inventory_review"
    assert value["inventory_effect_units"] == "0" and value["candidates"] == []
    con.execute.assert_not_called()


def test_preview_reuses_business_context_validation_before_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, batch, _, con, command = prepared(
        monkeypatch, context={"source_note": "无日期"}
    )
    with pytest.raises(ApiError) as failure:
        handoff_batch(svc, batch["id"], command, preview_only=True)
    assert cast(dict[str, str], failure.value.detail)["code"] == "manual_date_required"
    con.execute.assert_not_called()


def test_stale_business_preview_rejected_without_claiming_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, batch, _, con, command = prepared(monkeypatch)
    monkeypatch.setattr(
        "app.manual_tables.handoff.production_request",
        lambda *args, **kwargs: {"candidates": []},
    )
    command = command.model_copy(update={"handoff_preview_hash": "0" * 64})
    with pytest.raises(ApiError) as failure:
        handoff_batch(svc, batch["id"], command)
    assert (
        cast(dict[str, str], failure.value.detail)["code"]
        == "manual_handoff_preview_stale"
    )
    con.execute.assert_not_called()


def test_legacy_handoff_request_keeps_its_original_idempotency_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, batch, _, con, legacy = prepared(monkeypatch)
    command = HandoffCommand(**legacy.model_dump())
    expected = digest(["handoff", batch["id"], legacy.model_dump()])
    replay = Mock(return_value={"target": {"id": "old-target"}})
    monkeypatch.setattr(svc, "replay", replay)
    assert handoff_batch(svc, batch["id"], command)["target"]["id"] == "old-target"
    assert replay.call_args.args[2] == expected
    con.execute.assert_not_called()


def test_changed_same_token_intent_is_rechecked_inside_final_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, batch, row, con, command = prepared(monkeypatch)
    changed = row | {
        "target_json": {
            "token": command.operation_token,
            "request_hash": "different request",
            "actor_id": "1",
        }
    }
    monkeypatch.setattr(svc, "load", Mock(side_effect=[row, changed]))
    with pytest.raises(ApiError) as failure:
        handoff_batch(svc, batch["id"], command)
    assert (
        cast(dict[str, str], failure.value.detail)["code"] == "manual_handoff_conflict"
    )
    con.execute.assert_not_called()
