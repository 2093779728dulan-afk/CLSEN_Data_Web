from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.auth.sessions import Principal
from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.return_dedup_repository import (
    FrozenPublicationMember,
    publication_set_digest,
)
from app.catalog.scope_repository import MySqlCatalogScopeRepository
from app.catalog.scope_service import CatalogScopeService, ConfirmScopeCommand
from app.catalog.snapshots import (
    MySqlCatalogSnapshotCoordinator,
    MySqlCatalogSnapshotWriter,
)
from app.site_context import resolve_current_site_context
from sqlalchemy.orm import Session

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import PublicationIntegrationCase
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)

pytestmark = pytest.mark.mysql

REPORT_DATE = date(2098, 7, 17)
CUTOFF = datetime(2098, 7, 18, 12, 0, tzinfo=UTC)


def _cleanup(case: PublicationIntegrationCase) -> None:
    with case.dataset_case.migration_engine.begin() as connection:
        for statement in (
            "DELETE FROM catalog_source_evidence WHERE site_id = 1",
            "DELETE FROM catalog_source_refs WHERE site_id = 1",
            "DELETE FROM catalog_export_payloads WHERE site_id = 1",
            "DELETE FROM catalog_jobs WHERE site_id = 1",
            "DELETE FROM catalog_exports WHERE site_id = 1",
            "DELETE FROM fact_snapshot_tuples WHERE site_id = 1",
            "DELETE FROM publication_snapshot_members WHERE site_id = 1",
            "DELETE FROM publication_snapshots WHERE site_id = 1",
            "UPDATE return_dedup_publications SET current_snapshot_id = NULL, "
            "dedup_publication_revision = 0 WHERE site_id = 1",
            "DELETE FROM return_dedup_snapshot_groups",
            "DELETE FROM return_dedup_snapshots WHERE site_id = 1",
            "DELETE FROM return_dedup_publications WHERE site_id = 1",
            "DELETE FROM report_source_keys WHERE site_id = 1",
            "DELETE FROM report_publication_revisions WHERE site_id = 1",
            "DELETE FROM report_dataset_scope_assignments WHERE site_id = 1",
            "DELETE FROM catalog_audit_events WHERE site_id = 1",
            "DELETE FROM catalog_command_effects WHERE site_id = 1",
            "DELETE FROM catalog_command_claims WHERE site_id = 1",
            "DELETE FROM report_source_scopes WHERE site_id = 1",
        ):
            connection.execute(sa.text(statement))
        connection.execute(
            sa.text(
                """
                UPDATE site_current_configs
                SET current_config_version_id = 1, updated_by_user_id = NULL
                WHERE site_id = 1
                """
            )
        )
        connection.execute(
            sa.text(
                "DELETE FROM site_config_versions "
                "WHERE site_id = 1 AND version_number > 1"
            )
        )


@pytest.fixture(name="catalog_snapshot_case")
def catalog_snapshot_case_fixture(
    publication_case: PublicationIntegrationCase,
) -> Iterator[PublicationIntegrationCase]:
    _cleanup(publication_case)
    try:
        yield publication_case
    finally:
        _cleanup(publication_case)


def _confirm_scope(case: PublicationIntegrationCase) -> int:
    engine = case.dataset_case.runtime_engine()
    try:
        principal = Principal(
            user_id=case.admin_user_id,
            username="snapshot-admin",
            display_name="Snapshot Admin",
            roles=frozenset({"admin"}),
            session_id=case.admin_user_id,
            csrf_token_hash=b"x" * 32,
        )
        with Session(engine) as session:
            context = resolve_current_site_context(session, principal)
        result = CatalogScopeService(
            MySqlCatalogScopeRepository(engine),
            clock=lambda: datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
        ).confirm(
            context,
            ConfirmScopeCommand(
                operation_token=uuid4(),
                expected_site_config_revision=context.site_config_revision,
                seller_account_scope_key="catalog-snapshot-account",
                seller_account_display_name="Catalog Snapshot Account",
                marketplace_scope_code="amazon_us",
                reason="Confirm scope for RR catalog snapshot consistency",
            ),
        )
        if result.report_source_scope_id is None:
            raise AssertionError("confirmed scope omitted its source scope id")
        return result.report_source_scope_id
    finally:
        engine.dispose()


def _seed_ready_dedup(
    case: PublicationIntegrationCase,
    *,
    scope_id: int,
    return_dataset_id: int,
    return_version_id: int,
) -> int:
    data_revision = int(
        case.dataset_case.scalar(
            "SELECT data_revision FROM dataset_versions WHERE id = :version_id",
            {"version_id": return_version_id},
        )
    )
    member = FrozenPublicationMember(
        dataset_id=return_dataset_id,
        published_version_id=return_version_id,
        publication_revision=0,
        version_data_revision=data_revision,
        report_date=REPORT_DATE,
    )
    set_digest = publication_set_digest((member,))
    decision_digest = hashlib.sha256(canonical_json_bytes([])).digest()
    with case.dataset_case.migration_engine.begin() as connection:
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO return_dedup_snapshots (
                    site_id, report_source_scope_id,
                    return_publication_set_digest, rule_version,
                    base_snapshot_id, checkpoint_snapshot_id, delta_depth,
                    snapshot_kind, status, decision_digest
                ) VALUES (
                    1, :scope_id, :set_digest, 'return_event_fingerprint_v1',
                    NULL, NULL, 0, 'checkpoint', 'ready', :decision_digest
                )
                """
            ),
            {
                "scope_id": scope_id,
                "set_digest": set_digest,
                "decision_digest": decision_digest,
            },
        )
        assert inserted.lastrowid is not None
        snapshot_id = int(inserted.lastrowid)
        connection.execute(
            sa.text(
                """
                UPDATE return_dedup_publications
                SET current_snapshot_id = :snapshot_id,
                    dedup_publication_revision = 1
                WHERE site_id = 1 AND report_source_scope_id = :scope_id
                """
            ),
            {"snapshot_id": snapshot_id, "scope_id": scope_id},
        )
    return snapshot_id


def test_rr_payload_cannot_mix_pointer_changes_and_write_persists_exact_payload(
    catalog_snapshot_case: PublicationIntegrationCase,
) -> None:
    case = catalog_snapshot_case
    _baseline, business = case.materialize_baseline(
        report_date=REPORT_DATE,
        variant="snapshot-business",
        report_type="business_report",
    )
    _return_baseline, returns = case.materialize_baseline(
        report_date=REPORT_DATE,
        variant="snapshot-returns",
        report_type="return_report",
    )
    case.dataset_case.mark_published(business.dataset_id, business.version_id)
    case.dataset_case.mark_published(returns.dataset_id, returns.version_id)
    scope_id = _confirm_scope(case)
    dedup_snapshot_id = _seed_ready_dedup(
        case,
        scope_id=scope_id,
        return_dataset_id=returns.dataset_id,
        return_version_id=returns.version_id,
    )

    def switch_business_pointer() -> None:
        with case.dataset_case.migration_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "DELETE FROM dataset_publications WHERE dataset_id = :dataset_id"
                ),
                {"dataset_id": business.dataset_id},
            )
            connection.execute(
                sa.text(
                    """
                    UPDATE report_publication_revisions
                    SET publication_revision = publication_revision + 1
                    WHERE dataset_id = :dataset_id
                    """
                ),
                {"dataset_id": business.dataset_id},
            )

    runtime = case.dataset_case.runtime_engine()
    try:
        frozen = MySqlCatalogSnapshotCoordinator(
            runtime,
            after_pointer_read=switch_business_pointer,
        ).freeze(site_id=1, fact_cutoff_at=CUTOFF)

        business_member = next(
            member
            for member in frozen.publication_snapshot.members
            if member.report_type == "business_report"
            and member.report_date == REPORT_DATE
        )
        assert business_member.member_status == "published"
        assert business_member.dataset_id == business.dataset_id
        assert business_member.published_version_id == business.version_id
        assert business_member.publication_pointer_revision == 0
        assert frozen.fact_tuple.return_dedup_snapshot_id == dedup_snapshot_id
        assert (
            case.dataset_case.scalar(
                "SELECT COUNT(*) FROM dataset_publications WHERE dataset_id = :id",
                {"id": business.dataset_id},
            )
            == 0
        )

        token = uuid4()
        writer = MySqlCatalogSnapshotWriter(runtime)
        created = writer.persist_building(
            frozen,
            operation_token=token,
            created_by_user_id=case.owner_user_id,
        )
        assert (
            writer.persist_building(
                frozen,
                operation_token=token,
                created_by_user_id=case.owner_user_id,
            )
            == created
        )

        rows = case.dataset_case.rows(
            """
            SELECT exports.export_status, exports.workbook_status,
                   exports.artifact_sha256, exports.artifact_storage_key,
                   snapshots.status AS snapshot_status,
                   tuples.status AS tuple_status,
                   members.member_status, members.published_version_id
            FROM catalog_exports AS exports
            INNER JOIN fact_snapshot_tuples AS tuples
                ON tuples.id = exports.fact_snapshot_tuple_id
            INNER JOIN publication_snapshots AS snapshots
                ON snapshots.id = tuples.publication_snapshot_id
            INNER JOIN publication_snapshot_members AS members
                ON members.publication_snapshot_id = snapshots.id
            WHERE exports.id = :export_id
              AND members.report_type = 'business_report'
              AND members.report_date = :report_date
            """,
            {"export_id": created.export_id, "report_date": REPORT_DATE},
        )
        assert rows == [
            {
                "export_status": "building",
                "workbook_status": None,
                "artifact_sha256": None,
                "artifact_storage_key": None,
                "snapshot_status": "building",
                "tuple_status": "building",
                "member_status": "published",
                "published_version_id": business.version_id,
            }
        ]
        payload_json = case.dataset_case.scalar(
            "SELECT evidence_payload_json FROM catalog_export_payloads "
            "WHERE export_id = :export_id",
            {"export_id": created.export_id},
        )
        rendered = str(payload_json)
        decoded = (
            json.loads(payload_json) if isinstance(payload_json, str) else payload_json
        )
        assert isinstance(decoded, dict)
        assert set(decoded) == {"summaries"}
        for forbidden in (
            "order_id",
            "fulfillment_center_id",
            "license_plate_number",
            "customer_comments",
        ):
            assert forbidden not in rendered
    finally:
        runtime.dispose()
