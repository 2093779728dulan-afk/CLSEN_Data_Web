from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.catalog.approval import CatalogApprovalForbidden, CatalogProjectionStale
from app.catalog.category_service import MySqlCatalogCategoryService
from app.catalog.change_service import MySqlCatalogStyleChangeService
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


def test_projection_expiry_and_high_risk_require_admin(
    catalog_approval_case: PublicationIntegrationCase,
) -> None:
    runtime, import_id, preview = _prepare_ready_import(catalog_approval_case)
    try:
        service = CatalogService(runtime)
        with pytest.raises(CatalogProjectionStale):
            service.approve_import(
                import_id=import_id,
                site_id=1,
                actor_user_id=catalog_approval_case.owner_user_id,
                actor_roles=frozenset({"data_manager"}),
                operation_token=uuid4(),
                expected_workflow_revision=2,
                expected_catalog_publication_revision=0,
                projection_id=preview.projection_id,
                projection_digest=preview.projection_digest,
                reason="Initial product catalog approval",
                now=datetime(2026, 8, 21, 15, 31, tzinfo=UTC),
            )

        with pytest.raises(CatalogApprovalForbidden):
            service.assert_approval_permission(
                risk="high",
                actor_roles=frozenset({"data_manager"}),
                submitted_by_user_id=catalog_approval_case.owner_user_id,
                actor_user_id=catalog_approval_case.owner_user_id,
                reason="Identity correction requiring administrator approval",
            )
        service.assert_approval_permission(
            risk="high",
            actor_roles=frozenset({"admin"}),
            submitted_by_user_id=catalog_approval_case.owner_user_id,
            actor_user_id=catalog_approval_case.admin_user_id,
            reason="Identity correction requiring administrator approval",
        )
    finally:
        runtime.dispose()


def test_restore_creates_forward_version_with_target_ready_fact_tuple(
    catalog_approval_case: PublicationIntegrationCase,
) -> None:
    runtime, import_id, preview = _prepare_ready_import(catalog_approval_case)
    try:
        service = CatalogService(runtime)
        approved = service.approve_import(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_approval_case.owner_user_id,
            actor_roles=frozenset({"data_manager"}),
            operation_token=uuid4(),
            expected_workflow_revision=2,
            expected_catalog_publication_revision=0,
            projection_id=preview.projection_id,
            projection_digest=preview.projection_digest,
            reason="Initial product catalog approval",
            now=datetime(2026, 8, 21, 15, 5, tzinfo=UTC),
        )
        token = uuid4()
        restored = service.restore_version(
            site_id=1,
            target_version_id=approved.catalog_version_id,
            actor_user_id=catalog_approval_case.admin_user_id,
            actor_roles=frozenset({"admin"}),
            operation_token=token,
            expected_catalog_publication_revision=1,
            reason="Restore the approved catalog as a forward version",
            now=datetime(2026, 8, 21, 15, 10, tzinfo=UTC),
        )
        replay = service.restore_version(
            site_id=1,
            target_version_id=approved.catalog_version_id,
            actor_user_id=catalog_approval_case.admin_user_id,
            actor_roles=frozenset({"admin"}),
            operation_token=token,
            expected_catalog_publication_revision=1,
            reason="Restore the approved catalog as a forward version",
            now=datetime(2026, 8, 21, 15, 20, tzinfo=UTC),
        )
        assert replay == restored
        assert restored.catalog_version_id != approved.catalog_version_id
        assert restored.catalog_version_number == 2
        assert restored.catalog_publication_revision == 2
        current = MySqlCatalogQueries(runtime).current_catalog(site_id=1)
        assert current is not None
        assert current.catalog_version_id == restored.catalog_version_id
    finally:
        runtime.dispose()


def test_single_style_change_is_isolated_idempotent_and_snapshots_category(
    catalog_approval_case: PublicationIntegrationCase,
) -> None:
    runtime, import_id, preview = _prepare_ready_import(catalog_approval_case)
    try:
        initial = CatalogService(runtime).approve_import(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_approval_case.owner_user_id,
            actor_roles=frozenset({"data_manager"}),
            operation_token=uuid4(),
            expected_workflow_revision=2,
            expected_catalog_publication_revision=0,
            projection_id=preview.projection_id,
            projection_digest=preview.projection_digest,
            reason="Initial product catalog approval",
            now=datetime(2026, 8, 21, 15, 5, tzinfo=UTC),
        )
        current = MySqlCatalogQueries(runtime).current_catalog(site_id=1)
        assert current is not None
        style = current.styles[0]
        categories = MySqlCatalogCategoryService(runtime).list(site_id=1)
        shirt = next(item for item in categories if item.code == "SHIRT")
        category_service = MySqlCatalogCategoryService(runtime)
        parent = category_service.create(
            site_id=1,
            actor_user_id=catalog_approval_case.admin_user_id,
            operation_token=uuid4(),
            code="TOPS",
            display_name="上装",
            aliases=(),
        )
        category_service.update(
            site_id=1,
            category_id=shirt.category_id,
            actor_user_id=catalog_approval_case.admin_user_id,
            operation_token=uuid4(),
            display_name=shirt.display_name,
            status="enabled",
            aliases=(),
            parent_category_id=parent.category_id,
            update_parent=True,
        )
        changes = MySqlCatalogStyleChangeService(runtime)
        created = changes.create_draft(
            site_id=1,
            style_id=style.style_id,
            actor_user_id=catalog_approval_case.owner_user_id,
            operation_token=uuid4(),
            expected_catalog_publication_revision=1,
            expected_style_revision=style.revision,
            standard_name="Approved shirt name",
            category_action="set",
            category_id=shirt.category_id,
        )
        draft_id_value = created["draft_id"]
        assert (
            isinstance(draft_id_value, (int, str))
            and not isinstance(draft_id_value, bool)
            and str(draft_id_value).isdigit()
        )
        draft_id = int(draft_id_value)
        change_preview = changes.preview(site_id=1, draft_id=draft_id)
        token = uuid4()
        approved = changes.approve(
            site_id=1,
            draft_id=draft_id,
            actor_user_id=catalog_approval_case.owner_user_id,
            operation_token=token,
            expected_draft_revision=1,
            expected_catalog_publication_revision=1,
            reason="Maintain product name and category",
        )
        replay = changes.approve(
            site_id=1,
            draft_id=draft_id,
            actor_user_id=catalog_approval_case.owner_user_id,
            operation_token=token,
            expected_draft_revision=1,
            expected_catalog_publication_revision=1,
            reason="Maintain product name and category",
        )
        assert replay == approved
        before = change_preview["before"]
        assert isinstance(before, dict)
        category = before["category"]
        assert isinstance(category, dict)
        assert category["category_id"] is None
        with runtime.connect() as connection:
            old_members = connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM product_catalog_style_members "
                    "WHERE catalog_version_id=:id"
                ),
                {"id": initial.catalog_version_id},
            )
            new_members = connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM product_catalog_style_members "
                    "WHERE catalog_version_id=:id"
                ),
                {"id": approved["catalog_version_id"]},
            )
        assert new_members == old_members
        MySqlCatalogCategoryService(runtime).update(
            site_id=1,
            category_id=shirt.category_id,
            actor_user_id=catalog_approval_case.admin_user_id,
            operation_token=uuid4(),
            code="SHIRT_RENAMED",
            display_name="衬衫 new dictionary name",
            status="enabled",
            aliases=(),
        )
        category_service.update(
            site_id=1,
            category_id=parent.category_id,
            actor_user_id=catalog_approval_case.admin_user_id,
            operation_token=uuid4(),
            code="TOPS_NEW",
            display_name="新上装",
            status="enabled",
            aliases=(),
        )
        latest = MySqlCatalogQueries(runtime).current_catalog(site_id=1)
        assert latest is not None
        assert latest.styles[0].standard_name == "Approved shirt name"
        assert latest.styles[0].category_id == shirt.category_id
        assert latest.styles[0].category_code == "SHIRT"
        assert latest.styles[0].category_parent == {
            "id": parent.category_id,
            "code": "TOPS",
            "display_name": "上装",
        }
        renamed = next(
            item
            for item in MySqlCatalogCategoryService(runtime).list(site_id=1)
            if item.category_id == shirt.category_id
        )
        assert renamed.code == "SHIRT_RENAMED"
        assert latest.styles[0].category_name == "衬衫"
        assert latest.styles[0].category_recorded is True
        from datetime import date

        from app.analytics.style_repository import MySqlStyleAnalyticsRepository

        repo = MySqlStyleAnalyticsRepository(runtime)
        root_result = repo.ledger(
            site_id=1,
            from_date=date(2026, 8, 22),
            to_date=date(2026, 8, 22),
            category_id=parent.category_id,
        )
        child_result = repo.ledger(
            site_id=1,
            from_date=date(2026, 8, 22),
            to_date=date(2026, 8, 22),
            category_id=shirt.category_id,
        )
        assert root_result.total_rows == child_result.total_rows == 1
        assert root_result.filtered_sales_total == child_result.filtered_sales_total
        assert root_result.rows == child_result.rows

    finally:
        with runtime.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM catalog_style_change_drafts WHERE site_id = 1")
            )
            connection.execute(
                sa.text(
                    "UPDATE product_categories SET created_by_user_id=NULL, "
                    "updated_by_user_id=NULL WHERE site_id=1"
                )
            )
        runtime.dispose()
