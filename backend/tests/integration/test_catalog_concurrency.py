from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.catalog.approval import CatalogPublicationConflict
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


def test_two_approvals_with_same_catalog_counter_have_one_cas_winner(
    catalog_approval_case: PublicationIntegrationCase,
) -> None:
    runtime, import_id, preview = _prepare_ready_import(catalog_approval_case)
    try:
        service = CatalogService(runtime)
        token = uuid4()
        first = service.approve_import(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_approval_case.owner_user_id,
            actor_roles=frozenset({"data_manager"}),
            operation_token=token,
            expected_workflow_revision=2,
            expected_catalog_publication_revision=0,
            projection_id=preview.projection_id,
            projection_digest=preview.projection_digest,
            reason="Initial product catalog approval",
            now=datetime(2026, 8, 21, 15, 5, tzinfo=UTC),
        )
        assert first.catalog_publication_revision == 1
        replay = service.approve_import(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_approval_case.owner_user_id,
            actor_roles=frozenset({"data_manager"}),
            operation_token=token,
            expected_workflow_revision=2,
            expected_catalog_publication_revision=0,
            projection_id=preview.projection_id,
            projection_digest=preview.projection_digest,
            reason="Initial product catalog approval",
            now=datetime(2026, 8, 21, 15, 7, tzinfo=UTC),
        )
        assert replay == first
        with pytest.raises(CatalogPublicationConflict):
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
                now=datetime(2026, 8, 21, 15, 6, tzinfo=UTC),
            )
    finally:
        runtime.dispose()
