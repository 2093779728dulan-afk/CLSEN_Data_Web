import hashlib
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.api.errors import ApiError
from app.production.fba_transit_opening import (
    load_transit_opening,
    merge_transit_view,
    opening_records,
)


@pytest.fixture
def basis(tmp_path: Path) -> Any:
    raw = (
        b"snapshot-date,sku,inbound-shipped\n"
        b"2026-11-04,SKU-A,11\n2026-11-04,SKU-B,140\n"
        b"2026-11-04,SKU-Z,0\n"
    )
    (tmp_path / "source.csv").write_bytes(raw)
    scope: dict[str, Any] = {
        "id": "1",
        "warehouse_id": "2",
        "owner_id": "1",
        "report_source_scope_id": "1",
    }
    source: dict[str, Any] = {
        "schema": "fba-transit-opening-v1",
        "database": "clsen_data_test_example",
        "site_id": "1",
        "snapshot_on": "2026-11-04",
        "scope": scope,
        "source_filename": "source.csv",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "identities": [
            {"sku_id": "10", "seller_sku": "SKU-A"},
            {"sku_id": "20", "seller_sku": "SKU-B"},
        ],
    }
    (tmp_path / "fba-transit-opening.json").write_text(json.dumps(source), "utf8")
    catalog = {
        sku: {"sku_id": sku, "code": code, "style_code": style, "status": "active"}
        for sku, code, style in [("10", "SKU-A", "1101"), ("20", "SKU-B", "2201")]
    }
    settings: Any = SimpleNamespace(production_inventory_source_root=str(tmp_path))
    context: Any = SimpleNamespace(site_id=1)
    engine: Any = SimpleNamespace(
        url=SimpleNamespace(database="clsen_data_test_example")
    )
    return settings, context, engine, catalog, scope


def test_opening_reads_only_shipped_units_and_preserves_report_date(basis: Any) -> None:
    source = load_transit_opening(*basis)
    assert source is not None
    records = opening_records(source, date(2026, 11, 4))
    assert sum(int(row["remaining_units"]) for row in records) == 151
    assert {row["business_date"] for row in records} == {"2026-11-04"}
    assert all(row["source_kind"] == "TRANSIT_OPENING" for row in records)
    assert all(
        row["actual_units"] is None and row["received_units"] is None for row in records
    )


def test_opening_does_not_move_into_earlier_dates_and_remains_after_cutoff(
    basis: Any,
) -> None:
    source = load_transit_opening(*basis)
    assert opening_records(source, date(2026, 11, 3)) == []
    assert (
        sum(
            int(row["remaining_units"])
            for row in opening_records(source, date(2026, 11, 8))
        )
        == 151
    )


@pytest.mark.parametrize("change", ["database", "site", "file", "identity"])
def test_opening_rejects_changed_scope_or_unmatched_evidence(
    basis: Any, change: Any
) -> None:
    settings, context, engine, catalog, scope = basis
    if change == "database":
        engine.url.database = "different_database"
    elif change == "site":
        context.site_id = 2
    elif change == "file":
        (Path(settings.production_inventory_source_root) / "source.csv").write_text(
            "changed"
        )
    else:
        catalog["10"]["code"] = "OTHER"
    with pytest.raises(ApiError):
        load_transit_opening(settings, context, engine, catalog, scope)


def test_other_fba_scope_is_not_given_the_opening(basis: Any) -> None:
    settings, context, engine, catalog, scope = basis
    assert (
        load_transit_opening(settings, context, engine, catalog, {**scope, "id": "9"})
        is None
    )


def test_opening_and_new_shipment_quantities_are_added_without_inventing_batches(
    basis: Any,
) -> None:
    source = load_transit_opening(*basis)
    original: dict[str, Any] = {
        "items": [{"sku_id": "10", "in_transit_units": "40"}],
        "totals": {"in_transit_units": "40"},
        "stock_effect": False,
    }
    updated = merge_transit_view(
        original, source, "transport-summary", {}, date(2026, 11, 8)
    )
    assert updated["totals"]["in_transit_units"] == "191"
    assert updated["opening_scope"] == {"warehouse_id": "2", "owner_id": "1"}
    assert sum(int(row["units"]) for row in updated["opening_balances"]) == 151
    assert original["totals"]["in_transit_units"] == "40"
    page: dict[str, Any] = {"items": [], "total": 0}
    updated_page = merge_transit_view(
        page,
        source,
        "warehouse-transit",
        {"warehouse_id": "2", "direction": "incoming", "owner_id": "1"},
        date(2026, 11, 8),
    )
    assert updated_page["items"] == [] and updated_page["total"] == 0
    assert sum(int(row["units"]) for row in updated_page["opening_balances"]) == 151
    for query in [
        {"warehouse_id": "1"},
        {"warehouse_id": "2", "owner_id": "9"},
        {"warehouse_id": "2", "direction": "outgoing"},
    ]:
        assert not merge_transit_view(
            page, source, "warehouse-transit", query, date(2026, 11, 8)
        ).get("opening_balances")
