"""A writable fictional review must not replace the original source viewer."""

import hashlib
import json
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from app.api.errors import ApiError
from app.config import Settings
from app.production import inventory_review as ir
from app.production.inventory_snapshot import (
    INVENTORY_TABLE_FILENAME,
    inventory_snapshot,
)
from app.site_context import CurrentSiteContext


def source(root: Path, kind: str, style: str, units: int) -> None:
    (root / "inputs").mkdir(parents=True)
    content = (
        "新款号   COLOR   XS   S   M   L   XL   XXL   3XL   合计   库位\n"
        f"{style}   NAVY   {units}   0   0   0   0   0   0   {units}   新仓库\n"
    ).encode()
    (root / "inputs" / INVENTORY_TABLE_FILENAME).write_bytes(content)
    (root / "inventory-source.json").write_text(
        json.dumps(
            {
                "schema": "production-inventory-source-v1",
                "consumer_site_id": "1",
                "source_format": "pasted_table",
                "source_kind": kind,
                "source_digest": hashlib.sha256(content).hexdigest(),
                "organized_on": None,
                "stocktaken_on": None,
            }
        ),
        encoding="utf-8",
    )


def test_explicit_inventory_root_keeps_original_source_and_rejects_real_start(
    tmp_path: Path,
) -> None:
    original, fictional = tmp_path / "original", tmp_path / "fictional"
    source(original, "REAL_SOURCE", "REAL-REFERENCE", 5)
    source(fictional, "FICTIONAL", "QA-REVIEW", 3)
    context = CurrentSiteContext(
        1,
        frozenset({"admin"}),
        1,
        "DEMO_LOCAL_ONLY",
        "Fictional",
        1,
        1,
        "UTC",
        "UTC",
        "USD",
    )
    settings = Settings(
        production_demo_mode=True,
        production_order_draft_root=str(original),
        production_inventory_source_root=str(fictional),
        production_inventory_review_writes_enabled=True,
    )
    active = inventory_snapshot(settings, context)
    assert active["source_kind"] == "FICTIONAL"
    assert cast(dict[str, object], active["summary"])["warehouse_1_units"] == "3"
    from dataclasses import replace

    real = inventory_snapshot(
        replace(settings, production_inventory_source_root=""), context
    )
    assert real["source_kind"] == "REAL_SOURCE"
    assert cast(dict[str, object], real["summary"])["warehouse_1_units"] == "5"
    assert real["read_only"] is True and real["posting_enabled"] is False
    engine = Mock()
    with pytest.raises(ApiError) as raised:
        ir.start(
            engine,
            settings,
            context,
            ir.StartReview(
                source_digest=cast(str, real["source_digest"]),
                source_manifest_digest=cast(str, real["source_manifest_digest"]),
            ),
        )
    assert raised.value.status_code == 409
    assert (
        cast(dict[str, str], raised.value.detail)["code"]
        == "inventory_review_source_mismatch"
    )
    engine.begin.assert_not_called()


def test_registered_local_inventory_source_supports_real_site(tmp_path: Path) -> None:
    from dataclasses import replace

    from app.api.production import stocktake_snapshot

    source(tmp_path, "REAL_SOURCE", "REAL-REFERENCE", 5)
    settings = Settings(
        production_inventory_source_root=str(tmp_path),
        production_inventory_review_writes_enabled=True,
    )
    context = CurrentSiteContext(
        1,
        frozenset({"admin"}),
        1,
        "amazon_us",
        "Local trial",
        1,
        1,
        "UTC",
        "UTC",
        "USD",
    )
    value = inventory_snapshot(settings, context)
    assert value["source_kind"] == "REAL_SOURCE"
    assert value["posting_enabled"] is False
    request = Mock()
    request.app.state.settings = settings
    readonly = stocktake_snapshot(request, context)
    assert isinstance(readonly, dict)
    assert readonly["source_digest"] == value["source_digest"]
    with pytest.raises(ApiError) as raised:
        inventory_snapshot(settings, replace(context, site_id=2))
    assert raised.value.status_code == 404
    with pytest.raises(ApiError):
        inventory_snapshot(Settings(), context)


def test_inventory_root_stays_local_and_explicit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit absolute inventory root"):
        Settings(production_inventory_source_root="relative")
    settings = Settings(
        environment="production",
        session_secret="p" * 64,
        production_inventory_source_root=str(tmp_path),
    )
    assert settings.production_inventory_source_root == str(tmp_path)


def test_versioned_real_source_keeps_fictional_review_source(tmp_path: Path) -> None:
    from dataclasses import replace

    original, fictional = tmp_path / "original", tmp_path / "fictional"
    source(original, "REAL_SOURCE", "OLD", 5)
    source(fictional, "FICTIONAL", "QA-REVIEW", 3)
    new_filename = "花都仓库1号-用户核对表-20261014.txt"
    content = (
        "新款号   COLOR   XS   S   M   L   XL   XXL   3XL   合计   库位\n"
        "NEW   NAVY   7   0   0   0   0   0   0   7   新仓库\n"
    ).encode()
    (original / "inputs" / new_filename).write_bytes(content)
    path = original / "inventory-source.json"
    metadata = json.loads(path.read_bytes()) | {
        "source_filename": new_filename,
        "source_digest": hashlib.sha256(content).hexdigest(),
    }
    path.write_text(json.dumps(metadata), encoding="utf-8")
    context = CurrentSiteContext(
        1,
        frozenset({"admin"}),
        1,
        "DEMO_LOCAL_ONLY",
        "Fictional",
        1,
        1,
        "UTC",
        "UTC",
        "USD",
    )
    settings = Settings(
        production_demo_mode=True,
        production_order_draft_root=str(original),
        production_inventory_source_root=str(fictional),
        production_inventory_review_writes_enabled=True,
    )
    real = inventory_snapshot(
        replace(settings, production_inventory_source_root=""), context
    )
    qa = inventory_snapshot(settings, context)
    assert real["filename"] == new_filename
    assert cast(dict[str, object], real["summary"])["warehouse_1_units"] == "7"
    assert qa["filename"] == INVENTORY_TABLE_FILENAME
    assert cast(dict[str, object], qa["summary"])["warehouse_1_units"] == "3"

    metadata["source_filename"] = "../outside.txt"
    path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ApiError) as raised:
        inventory_snapshot(
            replace(settings, production_inventory_source_root=""), context
        )
    assert raised.value.status_code == 422
