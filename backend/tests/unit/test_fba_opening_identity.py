import csv
from io import StringIO
from pathlib import Path
from typing import Any, cast

import pytest
from app.api.errors import ApiError
from app.catalog.normalization import seller_sku_match_v1
from app.production.fba_opening_identity import (
    parse_identity_source,
    read_identity_source,
    retain_identity_source,
    verify_identity,
)


def source(sku: str = "1112-Black-L") -> Any:
    out = StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["Seller SKU", "ASIN", "FNSKU", "来源店铺"])
    writer.writerow([sku, "B000000001", "X000000001", "SIM store"])
    return out.getvalue().encode("utf-8-sig")


CATALOG = {"3": {"code": "1112-Black-L", "status": "active"}}


def test_no_report_mapping_can_be_explicitly_confirmed_for_exact_catalog_code() -> None:
    row = parse_identity_source(source())[0]
    result = verify_identity(row | {"sku_id": "3"}, CATALOG, [])
    assert result["basis"] == "confirmed_fba_identity_source"
    assert result["seller_sku"] == "1112-Black-L"


def test_approved_platform_alias_remains_supported() -> None:
    row = parse_identity_source(source("AMAZON-ALIAS"))[0]
    result = verify_identity(row | {"sku_id": "3"}, CATALOG, ["3"])
    assert result["basis"] == "approved_catalog_mapping"


@pytest.mark.parametrize("sku", ["1112-black-L", "1112-Black-M", "1112-Black-L "])
def test_missing_platform_mapping_does_not_guess_similar_or_normalized_codes(
    sku: Any,
) -> None:
    row = parse_identity_source(source(sku))[0]
    with pytest.raises(ApiError):
        verify_identity(row | {"sku_id": "3"}, CATALOG, [])


def test_known_platform_mapping_to_other_sku_is_not_overridden_by_exact_code() -> None:
    row = parse_identity_source(source())[0]
    with pytest.raises(ApiError):
        verify_identity(row | {"sku_id": "3"}, CATALOG, ["4"])


def test_duplicate_formal_code_and_disabled_sku_cannot_be_confirmed() -> None:
    row = parse_identity_source(source())[0] | {"sku_id": "3"}
    for catalog in [
        CATALOG | {"4": CATALOG["3"]},
        {"3": CATALOG["3"] | {"status": "disabled"}},
    ]:
        with pytest.raises(ApiError):
            verify_identity(row, catalog, [])


@pytest.mark.parametrize(
    "raw",
    [
        b"PK-fake.xlsx",
        b"Seller SKU,ASIN\ninvalid,none",
        source() + source().splitlines(keepends=True)[1],
    ],
)
def test_invalid_file_or_duplicate_identity_is_rejected(raw: Any) -> None:
    with pytest.raises(ApiError) as exc:
        parse_identity_source(raw)
    assert (
        "第" in cast(dict[str, str], exc.value.detail)["message"]
        or "CSV" in cast(dict[str, str], exc.value.detail)["message"]
    )


def test_source_bytes_are_immutable_and_scoped_to_site_actor_and_account(
    tmp_path: Path,
) -> None:
    raw = source()
    digest = retain_identity_source(str(tmp_path), 1, 2, 3, raw)
    assert read_identity_source(str(tmp_path), 1, 2, 3, digest) == raw
    assert retain_identity_source(str(tmp_path), 1, 2, 3, raw) == digest
    for site, actor, account in [(2, 2, 3), (1, 3, 3), (1, 2, 4)]:
        with pytest.raises(ApiError):
            read_identity_source(str(tmp_path), site, actor, account, digest)
    with pytest.raises(ApiError):
        read_identity_source(str(tmp_path), 1, 2, 3, "../secret")


@pytest.fixture
def opening_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    import hashlib
    from types import SimpleNamespace
    from unittest.mock import Mock

    import sqlalchemy as sa
    from app.api import production_fba as api

    engine = sa.create_engine("sqlite://")
    with engine.begin() as con:
        con.execute(
            sa.text(
                "CREATE TABLE report_source_scopes (id INTEGER, site_id INTEGER, "
                "seller_account_scope_key BLOB, marketplace_scope_code TEXT)"
            )
        )
        con.execute(
            sa.text("INSERT INTO report_source_scopes VALUES (1,1,:key,'amazon_us')"),
            {"key": hashlib.sha256(b"SIM-ACCOUNT").digest()},
        )
        con.execute(
            sa.text(
                "CREATE TABLE product_catalog_mappings (sku_id INTEGER, "
                "site_id INTEGER, "
                "report_source_scope_id INTEGER, catalog_version_id INTEGER, "
                "seller_sku_match_bytes BLOB)"
            )
        )
    context: Any = SimpleNamespace(
        site_id=1, principal_user_id=1, principal_roles={"admin"}
    )
    settings: Any = SimpleNamespace(production_inventory_source_root=str(tmp_path))
    request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings))
    )
    catalog = {key: row | {"catalog_version": "1:1"} for key, row in CATALOG.items()}
    monkeypatch.setattr(api, "production_skus", lambda *args: catalog)
    sent = Mock(
        side_effect=lambda request, context, engine, command, payload, key: payload
    )
    monkeypatch.setattr(api, "send", sent)
    digest = retain_identity_source(str(tmp_path), 1, 1, 1, source())
    body = {
        "seller_account": "SIM-ACCOUNT",
        "report_source_scope_id": "1",
        "simulated": True,
        "explicit_zero_opening": True,
        "identities_confirmed": True,
        "identity_source": {"source_id": digest},
        "identities": [parse_identity_source(source())[0] | {"sku_id": "3"}],
    }
    yield api, request, context, engine, body, sent
    engine.dispose()


def call_opening(fixture: Any) -> Any:
    from uuid import uuid4

    api, request, context, engine, body, _ = fixture
    return api.command("scopes", request, context, engine, body, uuid4())


def test_auto_opening_uses_reviewed_codes_instead_of_client_values(
    opening_api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, _request, _context, _engine, body, _sent = opening_api
    row = body["identities"][0] | {"store": "SIM store", "reason": "approved source"}
    monkeypatch.setattr(
        api,
        "catalog_products",
        lambda *args: {
            "identities": [row],
            "issues": [],
            "store": "SIM store",
            "catalog_version": "1:1",
        },
    )
    body.pop("identity_source")
    body.update(
        identity_mode="catalog", catalog_version="1:1", identities_confirmed=False
    )
    body["identities"] = [{"sku_id": "3", "asin": "CLIENT-FORGED"}]
    payload = call_opening(opening_api)
    assert payload["identities"][0]["asin"] == "B000000001"
    assert payload["identities_confirmed"] is True
    assert payload["_fba_identities"]["3"]["basis"] == "approved_catalog_source"


@pytest.mark.parametrize("change", ["stale", "missing"])
def test_auto_opening_rechecks_current_approved_source(
    opening_api: Any, monkeypatch: pytest.MonkeyPatch, change: Any
) -> None:
    api, _request, _context, _engine, body, sent = opening_api
    monkeypatch.setattr(
        api,
        "catalog_products",
        lambda *args: {
            "identities": [] if change == "missing" else body["identities"],
            "store": "SIM store",
            "catalog_version": "2:2",
        },
    )
    body.pop("identity_source")
    body.update(identity_mode="catalog", catalog_version="1:1")
    with pytest.raises(ApiError):
        call_opening(opening_api)
    sent.assert_not_called()


def test_confirmation_without_reports_preserves_source_and_does_not_publish_global_map(
    opening_api: Any,
) -> None:
    import sqlalchemy as sa

    payload = call_opening(opening_api)
    assert payload["store_evidence"] == parse_identity_source(source())[0]["store"]
    assert payload["_fba_identities"]["3"]["basis"] == "confirmed_fba_identity_source"
    assert "CSV第2行" in payload["identities"][0]["reason"]
    assert (
        opening_api[4]["identity_source"]["source_id"]
        in payload["identities"][0]["reason"]
    )
    with opening_api[3].connect() as con:
        assert con.scalar(sa.text("SELECT COUNT(*) FROM product_catalog_mappings")) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("asin", "B000000009"),
        ("fnsku", "X000000009"),
        ("seller_sku", "1112-Black-M"),
        ("store", "other"),
        ("source_row", 3),
    ],
)
def test_confirmation_rejects_changed_original_cells(
    opening_api: Any, field: Any, value: Any
) -> None:
    opening_api[4]["identities"][0][field] = value
    with pytest.raises(ApiError):
        call_opening(opening_api)
    opening_api[5].assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        "no-source",
        "wrong-account",
        "not-confirmed",
        "not-zero",
        "missing-row",
        "viewer",
    ],
)
def test_confirmation_boundaries_do_not_reach_inventory_writer(
    opening_api: Any, change: Any
) -> None:
    _, _, context, _, body, sent = opening_api
    if change == "no-source":
        body.pop("identity_source")
    elif change == "wrong-account":
        body["seller_account"] = "OTHER"
    elif change == "not-confirmed":
        body["identities_confirmed"] = False
    elif change == "not-zero":
        body["explicit_zero_opening"] = False
    elif change == "missing-row":
        body["identities"] = []
    else:
        context.principal_roles = {"viewer"}
    with pytest.raises(ApiError):
        call_opening(opening_api)
    sent.assert_not_called()


def test_existing_platform_mapping_path_remains_compatible_without_new_source(
    opening_api: Any,
) -> None:
    import sqlalchemy as sa
    from app.catalog.normalization import seller_sku_match_v1

    with opening_api[3].begin() as con:
        con.execute(
            sa.text("INSERT INTO product_catalog_mappings VALUES (3,1,1,1,:match)"),
            {"match": seller_sku_match_v1("1112-Black-L").utf8},
        )
    opening_api[4].pop("identity_source")
    assert (
        call_opening(opening_api)["_fba_identities"]["3"]["basis"]
        == "approved_catalog_mapping"
    )


@pytest.mark.parametrize("conflict", [False, True])
def test_reconfirm_catalog_rechecks_original_scope_and_all_stable_identities(
    opening_api: Any, monkeypatch: pytest.MonkeyPatch, conflict: Any
) -> None:
    from uuid import uuid4

    import sqlalchemy as sa

    api, request, context, engine, _body, sent = opening_api
    original = parse_identity_source(source())[0] | {"sku_id": "3", "scope_id": "7"}
    scope = {"id": "7", "warehouse_id": "2", "report_source_scope_id": "1"}
    reads = []

    def read(request: Any, context: Any, resource: Any, query: Any = None) -> Any:
        reads.append((resource, query))
        return scope if resource == "fba-scopes/7" else {"identities": [original]}

    monkeypatch.setattr(api, "read", read)
    with engine.begin() as con:
        con.execute(
            sa.text("INSERT INTO product_catalog_mappings VALUES (:sku,1,1,1,:key)"),
            {
                "sku": 4 if conflict else 3,
                "key": seller_sku_match_v1(original["seller_sku"]).utf8,
            },
        )
    values = {
        "scope_id": "7",
        "reconfirm_catalog": True,
        "_fba_identities": {"3": {"seller_sku": "FORGED"}},
    }
    if conflict:
        with pytest.raises(ApiError, match="已有店铺商品关联"):
            api.command("tracking", request, context, engine, values, uuid4())
        sent.assert_not_called()
    else:
        payload = api.command("tracking", request, context, engine, values, uuid4())
        assert payload["_fba_identities"]["3"]["seller_sku"] == original["seller_sku"]
        assert payload["_fba_identities"]["3"]["basis"] == "approved_catalog_mapping"
        assert reads == [("fba-scopes/7", None), ("fba-state", [("warehouse_id", "2")])]


@pytest.mark.parametrize("wrong_store", [False, True])
def test_connect_existing_sku_reuses_source_verification(
    opening_api: Any, monkeypatch: pytest.MonkeyPatch, wrong_store: Any
) -> None:
    from uuid import uuid4

    api, request, context, engine, body, sent = opening_api
    scope = {
        "id": "7",
        "warehouse_id": "3",
        "owner_id": "1",
        "seller_account": "SIM-ACCOUNT",
        "marketplace": "amazon_us",
        "report_source_scope_id": "1",
        "store_evidence": "OTHER" if wrong_store else "SIM store",
        "cutoff_on": "2026-10-01",
        "simulated": True,
    }
    monkeypatch.setattr(api, "read", lambda *args: scope)
    payload = body | {
        "scope_id": "7",
        "expected_revision": "2",
        "seller_account": "CLIENT-FORGED",
    }
    if wrong_store:
        with pytest.raises(ApiError, match="店铺与当前FBA范围不一致"):
            api.command("extend-identities", request, context, engine, payload, uuid4())
        sent.assert_not_called()
    else:
        result = api.command(
            "extend-identities", request, context, engine, payload, uuid4()
        )
        assert result["seller_account"] == "SIM-ACCOUNT"
        assert result["expected_revision"] == "2"
        assert (
            result["_fba_identities"]["3"]["basis"] == "confirmed_fba_identity_source"
        )
        assert result["identities"][0]["sku_id"] == "3"
