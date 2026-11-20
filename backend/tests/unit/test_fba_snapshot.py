from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.api.errors import ApiError
from app.production.fba_opening_identity import retain_identity_source
from app.production.fba_snapshot import parse_snapshot
from app.production.fba_transit_opening import load_transit_opening, opening_records

RAW = (
    b"snapshot-date,sku,asin,fnsku,available,inbound-shipped\n"
    b"2026-11-04,SKU-A,B000000001,X000000001,10,7\n"
)
PRODUCTS = {
    "identities": [
        {
            "sku_id": "11",
            "seller_sku": "SKU-A",
            "asin": "B000000001",
            "fnsku": "X000000001",
        },
        {
            "sku_id": "12",
            "seller_sku": "SKU-B",
            "asin": "B000000002",
            "fnsku": "X000000002",
        },
    ],
    "catalog_version": "48:48",
}


def test_snapshot_reads_available_and_shipped_separately() -> None:
    result = parse_snapshot(RAW, PRODUCTS)
    assert result["available_units"] == "10"
    assert result["transit_units"] == "7"
    assert result["snapshot_on"] == "2026-11-04"
    assert result["missing_skus"] == 1


@pytest.mark.parametrize(
    "raw",
    [
        RAW.replace(b",10,7", b",-1,7"),
        RAW.replace(b",10,7", b",10,-7"),
        RAW.replace(b"SKU-A", b"OTHER"),
        RAW.replace(b"B000000001", b"B000000999"),
        RAW + RAW.split(b"\n")[1] + b"\n",
        RAW + RAW.split(b"\n")[1].replace(b"2026-11-04", b"2026-11-05") + b"\n",
        b"sku,available\nSKU-A,10\n",
    ],
)
def test_snapshot_rejects_wrong_identity_date_or_quantity(raw: bytes) -> None:
    with pytest.raises(ApiError):
        parse_snapshot(raw, PRODUCTS)


def basis(
    tmp_path: Path,
) -> tuple[
    SimpleNamespace,
    SimpleNamespace,
    SimpleNamespace,
    dict[str, dict[str, str]],
    dict[str, Any],
]:
    digest = retain_identity_source(str(tmp_path), 1, 2, 3, RAW)
    snapshot = {
        "source_kind": "REAL_SOURCE",
        "source_id": digest,
        "source_actor_id": "2",
        "site_id": "1",
        "database": "clsen_data",
        "report_source_scope_id": "3",
        "snapshot_on": "2026-11-04",
        "rows": parse_snapshot(RAW, PRODUCTS)["rows"],
    }
    scope = {
        "id": "4",
        "warehouse_id": "5",
        "owner_id": "6",
        "report_source_scope_id": "3",
        "simulated": False,
        "cutoff_on": "2026-11-04",
        "catalog_version": "48:48",
        "opening_metadata": {
            "quantity_basis": "FBA_REAL_SNAPSHOT",
            "snapshot": snapshot,
        },
    }
    return (
        SimpleNamespace(production_inventory_source_root=str(tmp_path)),
        SimpleNamespace(site_id=1),
        SimpleNamespace(url=SimpleNamespace(database="clsen_data")),
        {"11": {"code": "SKU-A", "status": "active", "style_code": "1101"}},
        scope,
    )


def test_real_production_transit_uses_committed_snapshot_and_keeps_date(
    tmp_path: Path,
) -> None:
    opening = load_transit_opening(*basis(tmp_path))
    assert opening_records(opening, date(2026, 11, 3)) == []
    assert opening_records(opening, date(2026, 11, 14))[0]["remaining_units"] == "7"


@pytest.mark.parametrize(
    "change", ["database", "site", "shop", "simulated", "date", "sku", "source"]
)
def test_real_transit_does_not_bypass_production_scope_or_original(
    tmp_path: Path, change: str
) -> None:
    settings, context, engine, catalog, scope = basis(tmp_path)
    scope = deepcopy(scope)
    if change == "database":
        engine.url.database = "another_database"
    elif change == "site":
        context.site_id = 9
    elif change == "shop":
        scope["report_source_scope_id"] = "99"
    elif change == "simulated":
        scope["simulated"] = True
    elif change == "date":
        scope["cutoff_on"] = "2026-11-05"
    elif change == "sku":
        catalog["11"]["code"] = "OTHER"
    else:
        scope["opening_metadata"]["snapshot"]["rows"][0]["transit_units"] = "8"
    with pytest.raises(ApiError):
        load_transit_opening(settings, context, engine, catalog, scope)


def test_snapshot_can_complete_codes_only_for_an_existing_scoped_sku() -> None:
    from app.production.fba_snapshot import snapshot_products

    products = {"identities": [], "store": "GZ", "catalog_version": "48:48"}
    catalog = {"11": {"sku_id": "11", "code": "SKU-A", "status": "active"}}
    prepared = snapshot_products(RAW, products, catalog)
    assert prepared["source_identity_sku_ids"] == ["11"]
    assert parse_snapshot(RAW, prepared)["available_units"] == "10"
    with pytest.raises(ApiError):
        parse_snapshot(RAW, snapshot_products(RAW, products, {}))


def test_snapshot_retains_zero_unregistered_rows_as_excluded_evidence() -> None:
    raw = RAW + b"2026-11-04,UNREGISTERED,B000000099,X000000099,0,0\n"
    result = parse_snapshot(raw, PRODUCTS)
    assert result["available_units"] == "10"
    assert result["excluded_rows"][0]["seller_sku"] == "UNREGISTERED"


@pytest.mark.parametrize(
    "raw",
    [
        b"snapshot-date,sku,asin,fnsku,available,inbound-shipped\n2026-11-04,SKU-A,B000000001,X000000001\n",
        b"snapshot-date,sku,asin,fnsku,available,inbound-shipped,available\n2026-11-04,SKU-A,B000000001,X000000001,10,7,99\n",
    ],
)
def test_snapshot_rejects_short_rows_and_duplicate_quantity_headers(raw: bytes) -> None:
    with pytest.raises(ApiError):
        parse_snapshot(raw, PRODUCTS)
