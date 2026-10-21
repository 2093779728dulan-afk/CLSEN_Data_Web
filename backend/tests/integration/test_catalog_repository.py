from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.catalog.approval import CatalogApprovalPreview
from app.catalog.canonical_json import CanonicalValue, canonical_json_bytes
from app.catalog.import_repository import MySqlCatalogImportRepository
from app.catalog.import_service import DraftProjection, DraftRow
from app.catalog.queries import MySqlCatalogQueries
from app.catalog.service import CatalogService
from sqlalchemy.engine import Engine

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import PublicationIntegrationCase
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)
from tests.integration.test_catalog_import_workflow import (
    _cleanup_imports,
    ready_export_projection,
)
from tests.integration.test_catalog_snapshot_consistency import _cleanup

pytestmark = pytest.mark.mysql


def _cleanup_catalog(case: PublicationIntegrationCase) -> None:
    with case.dataset_case.migration_engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE catalog_imports SET base_catalog_version_id = NULL, "
                "validation_run_id = NULL, superseded_by_id = NULL WHERE site_id = 1"
            )
        )
        connection.execute(
            sa.text(
                "UPDATE product_catalog_publications "
                "SET current_catalog_version_id = NULL WHERE site_id = 1"
            )
        )
        connection.execute(
            sa.text(
                "UPDATE product_catalog_versions "
                "SET base_catalog_version_id = NULL WHERE site_id = 1"
            )
        )
        for statement in (
            "DELETE FROM catalog_audit_events WHERE site_id = 1",
            "DELETE FROM product_catalog_publication_events WHERE site_id = 1",
            "DELETE FROM product_catalog_mappings WHERE site_id = 1",
            "DELETE FROM product_catalog_exclusions WHERE site_id = 1",
            "DELETE FROM product_catalog_sku_members WHERE site_id = 1",
            "DELETE FROM product_catalog_style_members WHERE site_id = 1",
            "DELETE FROM product_catalog_versions WHERE site_id = 1",
            "DELETE FROM product_identity_key_reservations WHERE site_id = 1",
            "DELETE FROM product_sku_revisions WHERE site_id = 1",
            "DELETE FROM product_skus WHERE site_id = 1",
            "DELETE FROM product_style_revisions WHERE site_id = 1",
            "DELETE FROM product_styles WHERE site_id = 1",
            "DELETE FROM product_catalog_publications WHERE site_id = 1",
        ):
            connection.execute(sa.text(statement))
    _cleanup_imports(case)
    _cleanup(case)


@pytest.fixture(name="catalog_approval_case")
def catalog_approval_case_fixture(
    publication_case: PublicationIntegrationCase,
) -> Iterator[PublicationIntegrationCase]:
    _cleanup_catalog(publication_case)
    try:
        yield publication_case
    finally:
        _cleanup_catalog(publication_case)


def _draft_row(row: DraftRow, payload: dict[str, CanonicalValue]) -> DraftRow:
    return replace(
        row,
        payload=payload,
        payload_digest=hashlib.sha256(canonical_json_bytes(payload)).digest(),
    )


def _completed_projection(source: DraftProjection) -> DraftProjection:
    sku_index = 0
    result: list[DraftRow] = []
    for row in source.rows:
        payload = dict(row.payload)
        if row.section == "styles":
            payload["standard_name"] = f"Standard {payload['style_code']}"
        elif row.section == "skus":
            sku_index += 1
            payload["internal_display_sku"] = f"DISPLAY-{sku_index}"
            payload["standard_color"] = payload.get("standard_color") or "Black"
            payload["standard_size"] = payload.get("standard_size") or "M"
        elif row.section == "mappings":
            target = payload.get("target_sku_row_key")
            if isinstance(target, str):
                payload["identity_decision"] = "mapped"
                payload["exclusion_reason"] = None
            else:
                payload["identity_decision"] = "excluded"
                payload["exclusion_reason"] = "Excluded by integration fixture"
        elif row.section == "exceptions":
            target = payload.get("target_sku_row_key")
            payload["action"] = "map_existing" if isinstance(target, str) else "exclude"
            if payload["action"] == "exclude":
                payload["exclusion_reason"] = "Excluded by integration fixture"
        result.append(_draft_row(row, payload))
    style_payload: dict[str, CanonicalValue] = {
        "row_key": "approval-user-style",
        "system_style_id": None,
        "style_code": "USER-STYLE-APPROVAL",
        "standard_name": "User created approval style",
        "status": "enabled",
        "candidate_seller_sku_count": None,
        "source_title_count": None,
        "first_seen_date": None,
        "latest_seen_date": None,
        "change_reason": "Create a user-owned catalog identity",
    }
    sku_payload: dict[str, CanonicalValue] = {
        "row_key": "approval-user-sku",
        "system_sku_id": None,
        "style_row_key": "approval-user-style",
        "internal_display_sku": "USER-DISPLAY-APPROVAL",
        "standard_color": "Black",
        "standard_size": "M",
        "status": "enabled",
        "source_color_preview": None,
        "source_color_set_sha256": None,
        "source_size_preview": None,
        "source_size_set_sha256": None,
        "first_seen_date": None,
        "latest_seen_date": None,
        "change_reason": "Create a user-owned catalog variant",
    }
    audit_style_payload: dict[str, CanonicalValue] = {
        "row_key": "audit-system-style",
        "system_style_id": None,
        "style_code": "AUDIT-SYSTEM-STYLE",
        "standard_name": None,
        "status": "enabled",
        "candidate_seller_sku_count": 0,
        "source_title_count": 0,
        "first_seen_date": None,
        "latest_seen_date": None,
        "change_reason": None,
    }
    audit_sku_payload: dict[str, CanonicalValue] = {
        "row_key": "audit-system-sku",
        "system_sku_id": None,
        "style_row_key": "audit-system-style",
        "internal_display_sku": None,
        "standard_color": None,
        "standard_size": None,
        "status": "enabled",
        "source_color_preview": None,
        "source_color_set_sha256": "sha256:" + "0" * 64,
        "source_size_preview": None,
        "source_size_set_sha256": "sha256:" + "0" * 64,
        "first_seen_date": None,
        "latest_seen_date": None,
        "change_reason": None,
    }
    for section, key, payload in (
        ("styles", "approval-user-style", style_payload),
        ("skus", "approval-user-sku", sku_payload),
    ):
        result.append(
            DraftRow(
                section,
                key,
                "user_created",
                "included",
                payload,
                hashlib.sha256(canonical_json_bytes(payload)).digest(),
            )
        )
    for section, key, payload in (
        ("styles", "audit-system-style", audit_style_payload),
        ("skus", "audit-system-sku", audit_sku_payload),
    ):
        result.append(
            DraftRow(
                section,
                key,
                "system",
                "audit_only",
                payload,
                hashlib.sha256(canonical_json_bytes(payload)).digest(),
            )
        )
    result.sort(key=lambda row: (row.section.encode(), row.row_key.encode()))
    return DraftProjection(tuple(result), (), "validated")


def _prepare_ready_import(
    case: PublicationIntegrationCase,
) -> tuple[Engine, int, CatalogApprovalPreview]:
    runtime, command, _workbook, source = ready_export_projection(case)
    projection = _completed_projection(source)
    imports = MySqlCatalogImportRepository(runtime)
    import_id = imports.create_online_from_export(
        site_id=1,
        owner_user_id=case.owner_user_id,
        operation_token=uuid4(),
        export_id=command.export_id,
        expected_catalog_publication_revision=0,
        projection=projection,
    )
    validated = imports.validate_import(
        import_id=import_id,
        site_id=1,
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
        expected_workflow_revision=0,
    )
    assert validated.safe_result["status"] == "validated"
    submitted = imports.transition_import(
        import_id=import_id,
        site_id=1,
        actor_user_id=case.owner_user_id,
        operation_token=uuid4(),
        expected_workflow_revision=1,
        command="submit",
    )
    assert submitted.safe_result["workflow_revision"] == 2
    preview = CatalogService(runtime).preview_import(
        import_id=import_id,
        site_id=1,
        actor_user_id=case.owner_user_id,
        actor_roles=frozenset({"data_manager"}),
        operation_token=uuid4(),
        expected_workflow_revision=2,
        now=datetime(2026, 8, 21, 15, 0, tzinfo=UTC),
    )
    return runtime, import_id, preview


def test_first_approval_allocates_database_ids_and_immutable_version(
    catalog_approval_case: PublicationIntegrationCase,
) -> None:
    runtime, import_id, preview = _prepare_ready_import(catalog_approval_case)
    try:
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
        assert result.catalog_version_number == 1
        assert result.catalog_publication_revision == 1
        assert result.workflow_revision == 3
        assert result.audit_only_row_count == 2

        current = MySqlCatalogQueries(runtime).current_catalog(site_id=1)
        assert current is not None
        assert current.catalog_version_id == result.catalog_version_id
        assert current.version_number == 1
        assert current.styles
        assert all(
            style.style_id > 0 and style.revision >= 1 for style in current.styles
        )
        assert all(sku.sku_id > 0 and sku.revision >= 1 for sku in current.skus)
        assert all(str(style.style_id) != style.style_code for style in current.styles)
        assert sum(style.variant_count for style in current.styles) == len(current.skus)
        target_sku_id = current.skus[0].sku_id
        with runtime.begin() as connection:
            source_keys = (
                connection.execute(
                    sa.text(
                        """
                        SELECT DISTINCT source_keys.report_source_scope_id,
                               source_keys.seller_sku_match_sha256,
                               source_keys.seller_sku_match_bytes
                        FROM report_source_keys AS source_keys
                        INNER JOIN catalog_source_evidence AS evidence
                          ON evidence.source_key_id = source_keys.id
                        WHERE source_keys.site_id = 1
                        ORDER BY source_keys.report_source_scope_id,
                                 source_keys.seller_sku_match_sha256
                        LIMIT 2
                        """
                    )
                )
                .mappings()
                .all()
            )
            assert len(source_keys) == 2
            for index, source_key in enumerate(source_keys):
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO product_catalog_mappings (
                            catalog_version_id, site_id,
                            report_source_scope_id, marketplace_scope_code,
                            seller_sku_match_sha256, seller_sku_match_bytes,
                            sku_id, decision_source, actor_user_id,
                            evidence_digest
                        ) VALUES (
                            :version_id, 1, :scope_id, 'amazon_us',
                            :match_sha, :match_bytes, :sku_id,
                            'catalog_import', :actor_user_id, :evidence_digest
                        )
                        """
                    ),
                    {
                        "version_id": result.catalog_version_id,
                        "scope_id": int(source_key["report_source_scope_id"]),
                        "match_sha": bytes(source_key["seller_sku_match_sha256"]),
                        "match_bytes": bytes(source_key["seller_sku_match_bytes"]),
                        "sku_id": target_sku_id,
                        "actor_user_id": catalog_approval_case.owner_user_id,
                        "evidence_digest": hashlib.sha256(
                            f"catalog-card-alias-{index}".encode()
                        ).digest(),
                    },
                )
        current = MySqlCatalogQueries(runtime).current_catalog(site_id=1)
        assert current is not None
        mapped_sku = next(sku for sku in current.skus if sku.seller_sku_count > 0)
        aliases = MySqlCatalogQueries(runtime).variant_seller_skus(
            site_id=1, sku_id=mapped_sku.sku_id, page=1, page_size=50
        )
        assert aliases is not None
        assert aliases.total_items == mapped_sku.seller_sku_count
        assert aliases.items
        assert all(item.mapping_status == "mapped" for item in aliases.items)
        evidence = MySqlCatalogQueries(runtime).variant_evidence(
            site_id=1, sku_id=mapped_sku.sku_id, page=1, page_size=50
        )
        assert evidence is not None
        assert evidence.total_items >= len(evidence.items) > 0
        assert all(item.seller_sku["preview"] for item in evidence.items)
    finally:
        runtime.dispose()
