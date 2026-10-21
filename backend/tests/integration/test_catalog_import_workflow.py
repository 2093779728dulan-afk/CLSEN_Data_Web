from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.catalog.canonical_json import CanonicalValue, canonical_json_bytes
from app.catalog.export_service import CatalogExportCommand, MySqlCatalogExportFinalizer
from app.catalog.import_repository import (
    CatalogParseAttemptStale,
    CatalogParseLease,
    CatalogWorkflowRevisionConflict,
    MySqlCatalogImportRepository,
)
from app.catalog.import_service import (
    DraftProjection,
    DraftRow,
    project_catalog_workbook,
)
from app.catalog.workbook import CatalogWorkbookData
from app.imports.storage import StoredContent
from sqlalchemy.engine import Engine

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import PublicationIntegrationCase
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)
from tests.integration.test_catalog_export_finalization import _building_export
from tests.integration.test_catalog_snapshot_consistency import _cleanup

pytestmark = pytest.mark.mysql


def _cleanup_imports(case: PublicationIntegrationCase) -> None:
    with case.dataset_case.migration_engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE catalog_imports "
                "SET validation_run_id = NULL, superseded_by_id = NULL "
                "WHERE site_id = 1"
            )
        )
        for statement in (
            "DELETE FROM catalog_approval_projections WHERE site_id = 1",
            "DELETE FROM catalog_validation_runs WHERE site_id = 1",
            "DELETE FROM catalog_import_issues WHERE site_id = 1",
            "DELETE FROM catalog_draft_identity_reservations WHERE site_id = 1",
            "DELETE FROM catalog_import_rows WHERE site_id = 1",
            "DELETE FROM catalog_parse_attempts WHERE site_id = 1",
            "DELETE FROM catalog_imports WHERE site_id = 1",
            "DELETE FROM raw_files WHERE original_filename IN "
            "('catalog.xlsx','missing.xlsx')",
            "DELETE FROM catalog_command_effects WHERE site_id = 1",
            "DELETE FROM catalog_command_claims WHERE site_id = 1",
            "DELETE FROM product_catalog_publications WHERE site_id = 1",
        ):
            connection.execute(sa.text(statement))


@pytest.fixture(name="catalog_import_case")
def catalog_import_case_fixture(
    publication_case: PublicationIntegrationCase,
) -> Iterator[PublicationIntegrationCase]:
    _cleanup_imports(publication_case)
    _cleanup(publication_case)
    try:
        yield publication_case
    finally:
        _cleanup_imports(publication_case)
        _cleanup(publication_case)


def ready_export_projection(
    case: PublicationIntegrationCase,
) -> tuple[Engine, CatalogExportCommand, CatalogWorkbookData, DraftProjection]:
    from app.worker.catalog_exports import MySqlCatalogExportWorkSource

    building, runtime = _building_export(case)
    command = MySqlCatalogExportWorkSource(runtime).next_building()
    assert command is not None
    projection = project_catalog_workbook(command.workbook)
    MySqlCatalogExportFinalizer(runtime).finalize_ready(
        command,
        artifact=StoredContent(
            "sha256/bb/" + "b" * 64,
            "b" * 64,
            123,
            False,
        ),
        capacity_violations=(),
    )
    assert command.export_id == building.export_id
    return runtime, command, command.workbook, projection


def _validated_projection() -> DraftProjection:
    payload: dict[str, CanonicalValue] = {
        "row_key": "user-style",
        "system_style_id": None,
        "style_code": "STYLE-1",
        "standard_name": "Standard name",
        "status": "enabled",
        "candidate_seller_sku_count": None,
        "source_title_count": None,
        "first_seen_date": None,
        "latest_seen_date": None,
        "change_reason": None,
    }
    row = DraftRow(
        "styles",
        "user-style",
        "user_created",
        "included",
        payload,
        hashlib.sha256(canonical_json_bytes(payload)).digest(),
    )
    return DraftProjection((row,), (), "validated")


def test_online_import_has_no_fake_parse_attempt_and_pages_all_sections(
    catalog_import_case: PublicationIntegrationCase,
) -> None:
    runtime, command, _workbook, projection = ready_export_projection(
        catalog_import_case
    )
    try:
        repository = MySqlCatalogImportRepository(runtime)
        import_id = repository.create_online_from_export(
            site_id=1,
            owner_user_id=catalog_import_case.owner_user_id,
            operation_token=uuid4(),
            export_id=command.export_id,
            expected_catalog_publication_revision=0,
            projection=projection,
        )
        state = repository.get_state(import_id=import_id, site_id=1)
        assert state.source_kind == "online"
        assert state.status == projection.initial_status
        assert state.workflow_revision == 0
        assert state.parse_attempt_revision == 0
        assert (
            catalog_import_case.dataset_case.scalar(
                "SELECT COUNT(*) FROM catalog_parse_attempts "
                "WHERE import_id = :import_id",
                {"import_id": import_id},
            )
            == 0
        )

        for section in ("styles", "skus", "mappings", "exceptions", "evidence"):
            page = repository.page_rows(
                import_id=import_id,
                site_id=1,
                section=section,
                page=1,
                page_size=200,
                at_workflow_revision=0,
            )
            assert page.workflow_revision == 0
            assert page.total_rows == len(page.rows)
        with pytest.raises(CatalogWorkflowRevisionConflict):
            repository.page_rows(
                import_id=import_id,
                site_id=1,
                section="styles",
                page=1,
                page_size=200,
                at_workflow_revision=1,
            )
    finally:
        runtime.dispose()


def test_parse_lease_renew_failure_resume_and_aba_fencing(
    catalog_import_case: PublicationIntegrationCase,
) -> None:
    runtime, command, _workbook, projection = ready_export_projection(
        catalog_import_case
    )
    try:
        now = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
        with catalog_import_case.dataset_case.migration_engine.begin() as connection:
            raw = connection.execute(
                sa.text(
                    """
                    INSERT INTO raw_files (
                        sha256, storage_key, original_filename, media_type,
                        size_bytes, uploaded_by_user_id, uploaded_at
                    ) VALUES (
                        :sha256, :storage_key, 'catalog.xlsx',
                        'application/vnd.openxmlformats-officedocument.'
                        'spreadsheetml.sheet', 8, :owner, :uploaded_at
                    )
                    """
                ),
                {
                    "sha256": b"c" * 32,
                    "storage_key": "sha256/63/" + "63" * 32,
                    "owner": catalog_import_case.owner_user_id,
                    "uploaded_at": now.replace(tzinfo=None),
                },
            )
            assert raw.lastrowid is not None
            imported = connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_imports (
                        site_id, operation_token, source_kind, owner_user_id,
                        export_id, raw_file_id, original_filename,
                        declared_media_type, base_catalog_version_id,
                        fact_snapshot_tuple_id, normalization_manifest_id,
                        status, workflow_revision, parse_attempt_revision
                    ) SELECT
                        1, :token, 'xlsx', :owner, id, :raw_file_id,
                        'catalog.xlsx',
                        'application/vnd.openxmlformats-officedocument.'
                        'spreadsheetml.sheet', base_catalog_version_id,
                        fact_snapshot_tuple_id, normalization_manifest_id,
                        'uploaded', 0, 0
                    FROM catalog_exports WHERE id = :export_id
                    """
                ),
                {
                    "token": uuid4().bytes,
                    "owner": catalog_import_case.owner_user_id,
                    "raw_file_id": int(raw.lastrowid),
                    "export_id": command.export_id,
                },
            )
            assert imported.lastrowid is not None
            import_id = int(imported.lastrowid)

        repository = MySqlCatalogImportRepository(runtime)
        first = repository.claim_next_parse(
            lease_token=uuid4(),
            now=now,
            lease_ttl=timedelta(minutes=5),
        )
        assert first is not None
        renewed = repository.renew_parse(
            first,
            now=now + timedelta(minutes=1),
            lease_ttl=timedelta(minutes=5),
        )
        with pytest.raises(CatalogParseAttemptStale):
            repository.complete_parse(
                first,
                projection=projection,
                completed_at=now + timedelta(minutes=2),
            )
        failed_revision = repository.fail_parse(
            renewed,
            completed_at=now + timedelta(minutes=2),
            recoverable=True,
            reason="catalog_source_temporarily_unavailable",
        )
        resumed_token = uuid4()
        resumed = repository.resume_parse(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=uuid4(),
            expected_workflow_revision=failed_revision,
            expected_parse_attempt_revision=1,
            lease_token=resumed_token,
            now=now + timedelta(minutes=3),
            lease_ttl=timedelta(minutes=5),
        )
        assert resumed.safe_result["parse_attempt_revision"] == 2
        second = CatalogParseLease(
            import_id,
            1,
            failed_revision + 1,
            2,
            resumed_token,
            now + timedelta(minutes=8),
            first.storage_key,
            first.sha256_hex,
            first.size_bytes,
        )
        complete_revision = repository.complete_parse(
            second,
            projection=projection,
            completed_at=now + timedelta(minutes=4),
        )
        assert complete_revision == failed_revision + 2
        with pytest.raises(CatalogParseAttemptStale):
            repository.fail_parse(
                renewed,
                completed_at=now + timedelta(minutes=4),
                recoverable=True,
                reason="catalog_source_temporarily_unavailable",
            )
    finally:
        runtime.dispose()


def test_validate_submit_preview_reject_withdraw_and_rebase_are_replayable(
    catalog_import_case: PublicationIntegrationCase,
) -> None:
    runtime, command, _workbook, _projection = ready_export_projection(
        catalog_import_case
    )
    try:
        repository = MySqlCatalogImportRepository(runtime)
        projection = _validated_projection()
        import_id = repository.create_online_from_export(
            site_id=1,
            owner_user_id=catalog_import_case.owner_user_id,
            operation_token=uuid4(),
            export_id=command.export_id,
            expected_catalog_publication_revision=0,
            projection=projection,
        )
        validated = repository.validate_import(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=uuid4(),
            expected_workflow_revision=0,
        )
        assert validated.safe_result["status"] == "validated"
        submitted = repository.transition_import(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=uuid4(),
            expected_workflow_revision=1,
            command="submit",
        )
        assert submitted.safe_result["status"] == "ready_for_approval"
        preview_token = uuid4()
        preview = repository.create_approval_preview(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=preview_token,
            expected_workflow_revision=2,
            risk="normal",
            now=datetime(2026, 8, 21, 13, 0, tzinfo=UTC),
        )
        replay = repository.create_approval_preview(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=preview_token,
            expected_workflow_revision=2,
            risk="normal",
            now=datetime(2026, 8, 21, 13, 5, tzinfo=UTC),
        )
        assert replay == preview
        refreshed = repository.create_approval_preview(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=uuid4(),
            expected_workflow_revision=2,
            risk="normal",
            now=datetime(2026, 8, 21, 13, 35, tzinfo=UTC),
        )
        assert (
            refreshed.safe_result["projection_id"]
            != preview.safe_result["projection_id"]
        )
        assert (
            refreshed.safe_result["projection_digest"]
            != preview.safe_result["projection_digest"]
        )
        assert (
            refreshed.safe_result["diff_digest"] == preview.safe_result["diff_digest"]
        )
        assert refreshed.safe_result["expires_at"] != preview.safe_result["expires_at"]
        assert (
            repository.get_state(import_id=import_id, site_id=1).workflow_revision == 2
        )
        rejected = repository.transition_import(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.admin_user_id,
            operation_token=uuid4(),
            expected_workflow_revision=2,
            command="reject",
            reason="Reject for safe integration test",
        )
        assert rejected.safe_result["status"] == "rejected"
        rebased = repository.rebase_import(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=uuid4(),
            expected_workflow_revision=3,
            replacement_export_id=command.export_id,
            expected_catalog_publication_revision=0,
            projection=projection,
        )
        successor_value = rebased.safe_result["successor_import_id"]
        assert isinstance(successor_value, int) and not isinstance(
            successor_value, bool
        )
        successor_id = successor_value
        successor = repository.get_state(import_id=successor_id, site_id=1)
        assert successor.source_kind == "online"
        assert successor.owner_user_id == catalog_import_case.owner_user_id
        assert successor.parse_attempt_revision == 0

        withdraw_id = repository.create_online_from_export(
            site_id=1,
            owner_user_id=catalog_import_case.owner_user_id,
            operation_token=uuid4(),
            export_id=command.export_id,
            expected_catalog_publication_revision=0,
            projection=projection,
        )
        withdrawn = repository.transition_import(
            import_id=withdraw_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=uuid4(),
            expected_workflow_revision=0,
            command="withdraw",
        )
        assert withdrawn.safe_result["status"] == "withdrawn"
    finally:
        runtime.dispose()
