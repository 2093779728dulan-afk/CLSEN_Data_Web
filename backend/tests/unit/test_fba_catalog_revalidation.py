# ruff: noqa: E501 -- Literal task schema.
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sqlalchemy as sa
from app.api import production_fba as api
from app.api.errors import ApiError


@pytest.fixture
def fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE product_catalog_mappings (site_id INTEGER,report_source_scope_id INTEGER,catalog_version_id INTEGER,seller_sku_match_bytes BLOB,sku_id INTEGER)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE product_catalog_exclusions (id INTEGER,site_id INTEGER,report_source_scope_id INTEGER,catalog_version_id INTEGER,seller_sku_match_bytes BLOB)"
            )
        )
    scope: dict[str, Any] = {
        "id": "1",
        "warehouse_id": "2",
        "report_source_scope_id": "3",
        "simulated": True,
        "seller_account": "scope:3",
        "store_evidence": "Shop",
        "catalog_version": "1:1",
    }
    identity: dict[str, Any] = {
        "scope_id": "1",
        "sku_id": "11",
        "seller_sku": "0012-Olive-M",
        "asin": "B000000001",
        "fnsku": "X000000001",
        "tracked": False,
    }
    catalog: dict[str, Any] = {
        "11": {
            "sku_id": "11",
            "style_id": "9",
            "code": identity["seller_sku"],
            "status": "active",
            "catalog_version": "2:2",
        }
    }
    products: dict[str, Any] = {
        "identities": [identity],
        "issues": [],
        "store": "Shop",
        "catalog_version": "2:2",
    }
    monkeypatch.setattr(
        api,
        "read",
        lambda request, context, resource, *args: (
            scope if resource.startswith("fba-scopes/") else {"identities": [identity]}
        ),
    )
    monkeypatch.setattr(api, "production_skus", lambda *args: catalog)
    monkeypatch.setattr(
        api, "catalog_for_report_scope", lambda engine, context, catalog, scope: catalog
    )
    monkeypatch.setattr(api, "catalog_products", lambda *args: products)
    request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=None))
    )
    context: Any = SimpleNamespace(site_id=7)
    yield (
        engine,
        scope,
        identity,
        catalog,
        products,
        lambda ids: api.receipt_product_setup(request, context, engine, "1", ids),
    )
    engine.dispose()


@pytest.mark.parametrize("simulated", [True, False])
def test_compatible_catalog_refresh_needs_no_new_sku_and_preserves_tracking(
    fixture: Any, simulated: Any
) -> None:
    _, scope, _, _, _, prepare = fixture
    scope["simulated"] = simulated
    setup = prepare(set())
    assert setup["identities"] == []
    assert setup["catalog_version"] == "2:2"
    assert setup["sku_ids"] == []
    assert setup["_fba_identities"]["11"]["seller_sku"] == "0012-Olive-M"


def test_unchanged_catalog_does_not_add_a_refresh_command(fixture: Any) -> None:
    _, scope, _, _, _, prepare = fixture
    scope["catalog_version"] = "2:2"
    assert prepare(set()) is None


def test_changed_platform_codes_require_review(fixture: Any) -> None:
    _, _, identity, _, products, prepare = fixture
    products["identities"] = [{**identity, "asin": "B000000009"}]
    with pytest.raises(ApiError) as error:
        prepare(set())
    assert cast(dict[str, str], error.value.detail)["code"] == "fba_identity_conflict"


def test_excluded_source_cannot_be_silently_reused(fixture: Any) -> None:
    engine, _, _, _, _, prepare = fixture
    with engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO product_catalog_exclusions VALUES (1,7,3,2,:key)"),
            {"key": b"0012-Olive-M"},
        )
    with pytest.raises(ApiError) as error:
        prepare(set())
    assert cast(dict[str, str], error.value.detail)["code"] == "fba_identity_conflict"


def test_mapping_to_other_stable_sku_requires_review(fixture: Any) -> None:
    engine, _, _, _, _, prepare = fixture
    with engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO product_catalog_mappings VALUES (7,3,2,:key,12)"),
            {"key": b"0012-Olive-M"},
        )
    with pytest.raises(ApiError) as error:
        prepare(set())
    assert cast(dict[str, str], error.value.detail)["code"] == "fba_identity_conflict"


@pytest.mark.parametrize(
    "command,field", [("action-reverse", "action_id"), ("batch-confirm", "batch_id")]
)
@pytest.mark.parametrize("invalid", [None, "not-an-id"])
def test_document_scope_lookup_rejects_invalid_ids_before_reading(
    command: Any, field: Any, invalid: Any
) -> None:
    from uuid import uuid4

    with pytest.raises(ApiError) as error:
        api.send(
            cast(Any, object()),
            cast(Any, object()),
            cast(Any, object()),
            command,
            {field: invalid},
            uuid4(),
        )
    assert error.value.status_code == 422
