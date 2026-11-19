from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.catalog.approval import CatalogPublicationConflict
from app.catalog.import_repository import MySqlCatalogImportRepository
from app.catalog.production_sources import (
    ProductionSource,
    ProductionSourceRow,
    create_production_import,
)
from app.catalog.queries import MySqlCatalogQueries
from app.catalog.service import CatalogService

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import PublicationIntegrationCase
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)
from tests.integration.test_catalog_repository import (
    _prepare_ready_import,
    catalog_approval_case_fixture,  # noqa: F401
)

pytestmark = pytest.mark.mysql


def test_unlisted_reused_sku_joins_shop_only_on_approval_and_restore_is_forward(
    catalog_approval_case: PublicationIntegrationCase,
) -> None:
    case = catalog_approval_case
    runtime, import_id, preview = _prepare_ready_import(case)
    service = CatalogService(runtime)
    try:
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
        current = MySqlCatalogQueries(runtime).current_catalog(site_id=1)
        assert current is not None
        # This existing product was created without any external mapping.
        sku = next(s for s in current.skus if s.seller_sku_count == 0)
        style = next(s for s in current.styles if s.style_id == sku.style_id)
        with runtime.connect() as c:
            scope = int(
                c.scalar(
                    sa.text(
                        "SELECT id FROM report_source_scopes "
                        "WHERE site_id=1 ORDER BY id "
                        "LIMIT 1"
                    )
                )
            )
            before = int(
                c.scalar(
                    sa.text("SELECT COUNT(*) FROM product_catalog_shop_memberships")
                )
            )
        source = ProductionSource(
            source_name="Unlisted existing stock joins approved shop",
            report_source_scope_id=scope,
            channel_evidence="Explicit shop registration",
            rows=[
                ProductionSourceRow(
                    style_code=style.style_code,
                    color=sku.standard_color,
                    size=sku.standard_size,
                    selected_sku_id=sku.sku_id,
                )
            ],
        )
        created = create_production_import(
            runtime,
            site_id=1,
            actor_id=case.owner_user_id,
            token=uuid4(),
            source=source,
            expected_revision=1,
        )
        new_import = int(cast(int, created["import_id"]))
        with runtime.connect() as c:
            assert (
                int(
                    c.scalar(
                        sa.text("SELECT COUNT(*) FROM product_catalog_shop_memberships")
                    )
                )
                == before
            )
        imports = MySqlCatalogImportRepository(runtime)
        imports.validate_import(
            import_id=new_import,
            site_id=1,
            actor_user_id=case.owner_user_id,
            operation_token=uuid4(),
            expected_workflow_revision=0,
        )
        imports.transition_import(
            import_id=new_import,
            site_id=1,
            actor_user_id=case.owner_user_id,
            operation_token=uuid4(),
            expected_workflow_revision=1,
            command="submit",
        )
        now = datetime.now(UTC)
        proposed = service.preview_import(
            import_id=new_import,
            site_id=1,
            actor_user_id=case.admin_user_id,
            actor_roles=frozenset({"admin"}),
            operation_token=uuid4(),
            expected_workflow_revision=2,
            now=now,
        )
        arguments = dict(
            import_id=new_import,
            site_id=1,
            actor_user_id=case.admin_user_id,
            actor_roles=frozenset({"admin"}),
            expected_workflow_revision=2,
            projection_id=proposed.projection_id,
            projection_digest=proposed.projection_digest,
            reason="Approve shop registration, no listing",
            now=now,
        )
        with pytest.raises(CatalogPublicationConflict):
            service.approve_import(
                **arguments,
                operation_token=uuid4(),
                expected_catalog_publication_revision=0,
            )
        with runtime.connect() as c:
            assert (
                int(
                    c.scalar(
                        sa.text("SELECT COUNT(*) FROM product_catalog_shop_memberships")
                    )
                )
                == before
            )
        token = uuid4()
        approved = service.approve_import(
            **arguments, operation_token=token, expected_catalog_publication_revision=1
        )
        assert (
            service.approve_import(
                **arguments,
                operation_token=token,
                expected_catalog_publication_revision=1,
            )
            == approved
        )
        params: dict[str, Any] = {
            "v": approved.catalog_version_id,
            "sku": sku.sku_id,
            "scope": scope,
        }
        with runtime.connect() as c:
            assert (
                c.scalar(
                    sa.text(
                        "SELECT COUNT(*) FROM product_catalog_shop_memberships WHERE "
                        "site_id=1 AND catalog_version_id=:v AND sku_id=:sku AND "
                        "report_source_scope_id=:scope"
                    ),
                    params,
                )
                == 1
            )
            assert (
                c.scalar(
                    sa.text(
                        "SELECT COUNT(*) FROM product_catalog_mappings "
                        "WHERE site_id=1 AND "
                        "catalog_version_id=:v AND sku_id=:sku"
                    ),
                    params,
                )
                == 0
            )
        selected = MySqlCatalogQueries(runtime).current_catalog(
            site_id=1, report_source_scope_id=scope
        )
        assert selected and sku.sku_id in {s.sku_id for s in selected.skus}
        restored = service.restore_version(
            site_id=1,
            target_version_id=initial.catalog_version_id,
            actor_user_id=case.admin_user_id,
            actor_roles=frozenset({"admin"}),
            operation_token=uuid4(),
            expected_catalog_publication_revision=2,
            reason="Restore membership with its approved version",
            now=now,
        )
        with runtime.connect() as c:
            assert (
                c.scalar(
                    sa.text(
                        "SELECT COUNT(*) FROM product_catalog_shop_memberships WHERE "
                        "site_id=1 AND catalog_version_id=:v AND sku_id=:sku"
                    ),
                    {"v": restored.catalog_version_id, "sku": sku.sku_id},
                )
                == 0
            )
    finally:
        runtime.dispose()
