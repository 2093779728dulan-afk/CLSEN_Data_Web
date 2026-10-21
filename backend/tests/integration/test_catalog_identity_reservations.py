from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.catalog.approval import CatalogReservationConflict
from app.catalog.commands import CatalogDecisionMutation
from app.catalog.import_repository import (
    CatalogDraftReservationConflict,
    MySqlCatalogImportRepository,
)
from app.catalog.repository import MySqlCatalogRepository
from app.catalog.service import CatalogService

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import PublicationIntegrationCase
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)
from tests.integration.test_catalog_import_workflow import ready_export_projection
from tests.integration.test_catalog_repository import (
    _prepare_ready_import,
    catalog_approval_case_fixture,  # noqa: F401
)

pytestmark = pytest.mark.mysql


def test_exclusion_reserves_identity_and_explicit_restore_releases_it(
    catalog_approval_case: PublicationIntegrationCase,
) -> None:
    from app.catalog.identity_conflicts import identity_owners
    from app.catalog.import_repository import CatalogImportRepositoryError

    runtime, command, _workbook, projection = ready_export_projection(
        catalog_approval_case
    )
    try:
        repository = MySqlCatalogImportRepository(runtime)
        imports = [
            repository.create_online_from_export(
                site_id=1,
                owner_user_id=catalog_approval_case.owner_user_id,
                operation_token=uuid4(),
                export_id=command.export_id,
                expected_catalog_publication_revision=0,
                projection=projection,
            )
            for _ in range(2)
        ]
        mapping = next(row for row in projection.rows if row.section == "mappings")

        def decide(import_id: int, revision: int, action: str, reason: str) -> None:
            repository.apply_decisions(
                import_id=import_id,
                site_id=1,
                actor_user_id=catalog_approval_case.owner_user_id,
                operation_token=uuid4(),
                expected_workflow_revision=revision,
                mutations=(
                    CatalogDecisionMutation(
                        uuid4(),
                        action,
                        None,
                        mapping.row_key,
                        {"exclusion_reason": reason, "change_reason": reason},
                    ),
                ),
            )

        decide(imports[0], 0, "exclude_seller_sku", "Confirmed irrelevant source")
        with pytest.raises(CatalogDraftReservationConflict):
            decide(imports[1], 0, "exclude_seller_sku", "Another draft exclusion")
        owners = identity_owners(
            runtime, site_id=1, import_id=imports[1], row_key=mapping.row_key
        )
        assert owners["drafts"] == [
            {
                "import_id": imports[0],
                "decision_kind": "excluded",
                "target_sku_row_key": None,
            }
        ]
        with pytest.raises(CatalogImportRepositoryError):
            decide(imports[0], 1, "restore_seller_sku_review", "")
        decide(
            imports[0], 1, "restore_seller_sku_review", "New evidence requires review"
        )
        decide(imports[1], 0, "exclude_seller_sku", "Another draft exclusion")
        with pytest.raises(CatalogImportRepositoryError):
            identity_owners(
                runtime, site_id=999, import_id=imports[1], row_key=mapping.row_key
            )
    finally:
        runtime.dispose()


def test_audit_only_rows_create_no_identity_revision_member_or_reservation(
    catalog_approval_case: PublicationIntegrationCase,
) -> None:
    runtime, import_id, preview = _prepare_ready_import(catalog_approval_case)
    try:
        repository = MySqlCatalogRepository(runtime)
        before = repository.identity_counts(site_id=1)
        result = CatalogService(runtime).approve_import(
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
        after = repository.identity_counts(site_id=1)
        assert result.audit_only_row_count == 2
        assert after.styles - before.styles == result.created_style_count
        assert after.skus - before.skus == result.created_sku_count
        assert (
            after.reservations - before.reservations == result.created_reservation_count
        )
    finally:
        runtime.dispose()


def test_reservation_is_permanent_and_cannot_be_reassigned(
    catalog_approval_case: PublicationIntegrationCase,
) -> None:
    runtime, import_id, preview = _prepare_ready_import(catalog_approval_case)
    try:
        service = CatalogService(runtime)
        first = service.approve_import(
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
        repository = MySqlCatalogRepository(runtime)
        reservation = repository.first_reservation(site_id=1, key_kind="style_code")
        assert reservation is not None
        repository.assert_reservation_owner(
            site_id=1,
            key_kind="style_code",
            key_sha256=reservation.key_sha256,
            key_bytes=reservation.key_bytes,
            style_id=reservation.style_id,
            sku_id=None,
        )
        with pytest.raises(CatalogReservationConflict):
            repository.assert_reservation_owner(
                site_id=1,
                key_kind="style_code",
                key_sha256=reservation.key_sha256,
                key_bytes=reservation.key_bytes,
                style_id=first.catalog_version_id + 10_000,
                sku_id=None,
            )
    finally:
        runtime.dispose()


def test_draft_seller_sku_reservation_is_unique_and_clear_releases_it(
    catalog_approval_case: PublicationIntegrationCase,
) -> None:
    runtime, command, _workbook, projection = ready_export_projection(
        catalog_approval_case
    )
    try:
        repository = MySqlCatalogImportRepository(runtime)
        first_import = repository.create_online_from_export(
            site_id=1,
            owner_user_id=catalog_approval_case.owner_user_id,
            operation_token=uuid4(),
            export_id=command.export_id,
            expected_catalog_publication_revision=0,
            projection=projection,
        )
        second_import = repository.create_online_from_export(
            site_id=1,
            owner_user_id=catalog_approval_case.owner_user_id,
            operation_token=uuid4(),
            export_id=command.export_id,
            expected_catalog_publication_revision=0,
            projection=projection,
        )
        mapping = next(row for row in projection.rows if row.section == "mappings")
        style_key = "draft-reservation-style"
        target = "draft-reservation-sku"

        def map_candidate(import_id: int) -> None:
            repository.apply_decisions(
                import_id=import_id,
                site_id=1,
                actor_user_id=catalog_approval_case.owner_user_id,
                operation_token=uuid4(),
                expected_workflow_revision=0,
                mutations=(
                    CatalogDecisionMutation(
                        uuid4(),
                        "create_style",
                        style_key,
                        None,
                        {
                            "style_code": "DRAFT-RESERVATION-STYLE",
                            "standard_name": "Draft reservation style",
                            "status": "enabled",
                            "change_reason": "Create target style for reservation",
                        },
                    ),
                    CatalogDecisionMutation(
                        uuid4(),
                        "create_sku",
                        target,
                        None,
                        {
                            "style_row_key": style_key,
                            "internal_display_sku": "DRAFT-RESERVATION-SKU",
                            "standard_color": "Black",
                            "standard_size": "M",
                            "status": "enabled",
                            "change_reason": "Create target SKU for reservation",
                        },
                    ),
                    CatalogDecisionMutation(
                        uuid4(),
                        "map_seller_sku",
                        None,
                        mapping.row_key,
                        {
                            "target_sku_row_key": target,
                            "change_reason": "Confirm observed Seller SKU",
                        },
                    ),
                ),
            )

        map_candidate(first_import)
        with pytest.raises(CatalogDraftReservationConflict):
            map_candidate(second_import)

        repository.apply_decisions(
            import_id=first_import,
            site_id=1,
            actor_user_id=catalog_approval_case.owner_user_id,
            operation_token=uuid4(),
            expected_workflow_revision=1,
            mutations=(
                CatalogDecisionMutation(
                    uuid4(),
                    "clear_seller_sku_decision",
                    None,
                    mapping.row_key,
                    {"change_reason": "Return candidate to review"},
                ),
            ),
        )
        map_candidate(second_import)
    finally:
        runtime.dispose()
