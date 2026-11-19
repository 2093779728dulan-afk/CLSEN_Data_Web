from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.catalog import shop_membership
from app.catalog.commands import CatalogDecisionMutation
from app.catalog.import_repository import MySqlCatalogImportRepository
from app.catalog.normalization import seller_sku_match_v1
from app.catalog.production_sources import (
    ProductionSource,
    ProductionSourceRow,
    create_production_import,
)
from app.catalog.queries import MySqlCatalogQueries
from app.catalog.repository import load_import_rows
from app.catalog.service import CatalogService
from app.maintenance.catalog_shop_membership_backfill import backfill_shop_memberships

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)
from tests.integration.test_catalog_repository import (
    _prepare_ready_import,
    catalog_approval_case_fixture,  # noqa: F401
)

pytestmark = pytest.mark.mysql


@pytest.fixture
def history(catalog_approval_case: Any) -> Any:
    case = catalog_approval_case
    runtime, import_id, preview = _prepare_ready_import(case)
    service = CatalogService(runtime)
    initial = service.approve_import(
        import_id=import_id,
        site_id=1,
        actor_user_id=case.owner_user_id,
        actor_roles=frozenset({"data_manager"}),
        operation_token=uuid4(),
        expected_workflow_revision=2,
        expected_catalog_publication_revision=0,
        projection_id=preview.projection_id,
        projection_digest=preview.projection_digest,
        reason="Initial approved catalog",
        now=datetime(2026, 8, 21, 15, 5, tzinfo=UTC),
    )
    catalog = MySqlCatalogQueries(runtime).current_catalog(site_id=1)
    assert catalog is not None
    sku = next(s for s in catalog.skus if s.seller_sku_count == 0)
    style = next(s for s in catalog.styles if s.style_id == sku.style_id)
    with runtime.connect() as c:
        scope = int(
            c.scalar(
                sa.text(
                    "SELECT id FROM report_source_scopes "
                    "WHERE site_id=1 ORDER BY id LIMIT 1"
                )
            )
        )
    try:
        yield case, runtime, service, initial, sku, style, scope
    finally:
        runtime.dispose()


def register(
    history: Any,
    revision: Any,
    *,
    scoped: bool = True,
    excluded: bool = False,
    legacy: bool = True,
) -> Any:
    case, runtime, service, _, sku, style, scope = history
    source = ProductionSource(
        source_name=f"Legacy scoped={scoped} excluded={excluded} revision={revision}",
        report_source_scope_id=scope if scoped else None,
        channel_evidence="Explicit approved shop" if scoped else None,
        rows=[
            ProductionSourceRow(
                style_code=style.style_code,
                color=sku.standard_color,
                size=sku.standard_size,
                selected_sku_id=sku.sku_id,
                formal_sku=sku.internal_display_sku if excluded else None,
            )
        ],
    )
    result = create_production_import(
        runtime,
        site_id=1,
        actor_id=case.owner_user_id,
        token=uuid4(),
        source=source,
        expected_revision=revision,
    )
    import_id = int(cast(int, result["import_id"]))
    imports = MySqlCatalogImportRepository(runtime)
    workflow = 0
    if excluded:
        with runtime.connect() as c:
            row = next(
                r
                for r in load_import_rows(c, import_id=import_id, workflow_revision=0)
                if r.section == "mappings"
            )
        imports.apply_decisions(
            import_id=import_id,
            site_id=1,
            actor_user_id=case.admin_user_id,
            operation_token=uuid4(),
            expected_workflow_revision=0,
            mutations=(
                CatalogDecisionMutation(
                    uuid4(),
                    "exclude_seller_sku",
                    None,
                    row.row_key,
                    {
                        "change_reason": "Explicit source exclusion",
                        "exclusion_reason": "Product belongs to another shop",
                    },
                ),
            ),
        )
        workflow = 1
    imports.validate_import(
        import_id=import_id,
        site_id=1,
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
        expected_workflow_revision=workflow,
    )
    imports.transition_import(
        import_id=import_id,
        site_id=1,
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
        expected_workflow_revision=workflow + 1,
        command="submit",
    )
    now = datetime.now(UTC)
    preview = service.preview_import(
        import_id=import_id,
        site_id=1,
        actor_user_id=case.admin_user_id,
        actor_roles=frozenset({"admin"}),
        operation_token=uuid4(),
        expected_workflow_revision=workflow + 2,
        now=now,
    )
    args = dict(
        import_id=import_id,
        site_id=1,
        actor_user_id=case.admin_user_id,
        actor_roles=frozenset({"admin"}),
        operation_token=uuid4(),
        expected_workflow_revision=workflow + 2,
        expected_catalog_publication_revision=revision,
        projection_id=preview.projection_id,
        projection_digest=preview.projection_digest,
        reason="Approve source while preserving shop and product identity",
        now=now,
    )
    if legacy:
        with (
            patch.object(shop_membership, "record_shop_memberships"),
            patch.object(shop_membership, "copy_shop_memberships"),
        ):
            approved = service.approve_import(**args)
    else:
        approved = service.approve_import(**args)
    return approved, import_id


def count(history: Any, version: Any) -> Any:
    _, runtime, _, _, sku, _, scope = history
    with runtime.connect() as c:
        return c.scalar(
            sa.text(
                "SELECT COUNT(*) FROM product_catalog_shop_memberships WHERE site_id=1 "
                "AND catalog_version_id=:v AND report_source_scope_id=:scope "
                "AND sku_id=:sku"
            ),
            {"v": version, "scope": scope, "sku": sku.sku_id},
        )


def backfill(history: Any) -> Any:
    case = history[0]
    with case.dataset_case.migration_engine.begin() as c:
        backfill_shop_memberships(c)


def test_prior_unlisted_shop_membership_survives_unscoped_successor_and_replay(
    history: Any,
) -> None:
    old, _ = register(history, 1)
    current, _ = register(history, 2, scoped=False)
    backfill(history)
    assert count(history, old.catalog_version_id) == 1
    assert count(history, current.catalog_version_id) == 1
    backfill(history)
    assert count(history, current.catalog_version_id) == 1


@pytest.mark.parametrize("restore_registered", [False, True])
def test_restore_inherits_target_membership_instead_of_previous_head(
    history: Any, restore_registered: Any
) -> None:
    case, _, service, initial, _, _, _ = history
    registered, _ = register(history, 1)
    current, _ = register(history, 2, scoped=False)
    target = registered if restore_registered else initial
    with patch.object(shop_membership, "copy_shop_memberships"):
        restored = service.restore_version(
            site_id=1,
            target_version_id=target.catalog_version_id,
            actor_user_id=case.admin_user_id,
            actor_roles=frozenset({"admin"}),
            operation_token=uuid4(),
            expected_catalog_publication_revision=3,
            reason="Restore the exact previously approved target",
            now=datetime.now(UTC),
        )
    backfill(history)
    assert count(history, current.catalog_version_id) == 1
    assert count(history, restored.catalog_version_id) == int(restore_registered)


def test_excluded_source_does_not_resurrect_removed_shop_mapping(history: Any) -> None:
    case, _, _, initial, sku, _, scope = history
    key = seller_sku_match_v1(sku.internal_display_sku)
    with case.dataset_case.migration_engine.begin() as c:
        c.execute(
            sa.text("""
            INSERT INTO product_catalog_mappings
              (catalog_version_id,site_id,report_source_scope_id,marketplace_scope_code,
               seller_sku_match_sha256,seller_sku_match_bytes,sku_id,decision_source,
               actor_user_id,evidence_digest)
            VALUES(:v,1,:scope,'amazon_us',:sha,:raw,:sku,'catalog_import',:actor,:digest)
        """),
            {
                "v": initial.catalog_version_id,
                "scope": scope,
                "sha": key.sha256,
                "raw": key.utf8,
                "sku": sku.sku_id,
                "actor": case.owner_user_id,
                "digest": hashlib.sha256(b"original mapping").digest(),
            },
        )
    excluded, import_id = register(history, 1, excluded=True)
    later, _ = register(history, 2, scoped=False)
    # Reproduce the already-applied 0036 projection error, then repair it.
    with case.dataset_case.migration_engine.begin() as c:
        c.execute(
            sa.text("""
            INSERT INTO product_catalog_shop_memberships
              (site_id,catalog_version_id,report_source_scope_id,sku_id,
               source_import_id,source_row_key,evidence_digest)
            VALUES(1,:v,:scope,:sku,:imp,:key,:digest)
        """),
            {
                "v": excluded.catalog_version_id,
                "scope": scope,
                "sku": sku.sku_id,
                "imp": import_id,
                "key": f"sku-{sku.sku_id}",
                "digest": hashlib.sha256(b"old 0036 source error").digest(),
            },
        )
    backfill(history)
    assert count(history, initial.catalog_version_id) == 1
    assert count(history, excluded.catalog_version_id) == 0
    assert count(history, later.catalog_version_id) == 0


def test_seller_sku_exclusion_does_not_remove_independent_shop_registration(
    history: Any,
) -> None:
    registered, _ = register(history, 1)
    excluded, _ = register(history, 2, excluded=True)
    backfill(history)
    assert count(history, registered.catalog_version_id) == 1
    assert count(history, excluded.catalog_version_id) == 1


def test_new_excluded_source_is_not_a_new_shop_registration(history: Any) -> None:
    excluded, _ = register(history, 1, excluded=True, legacy=False)
    assert count(history, excluded.catalog_version_id) == 0
