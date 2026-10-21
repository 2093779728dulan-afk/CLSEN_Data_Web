from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.catalog.export_service import CATALOG_WORKBOOK_MEDIA_TYPE
from app.catalog.import_repository import MySqlCatalogImportRepository
from app.catalog.upload_service import (
    CatalogRawUploadCommand,
    MySqlCatalogUploadRepository,
)
from app.catalog.workbook import render_catalog_workbook
from app.worker.catalog_imports import CatalogImportWorker

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import PublicationIntegrationCase
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)
from tests.integration.test_catalog_import_workflow import (
    catalog_import_case_fixture as _catalog_import_case,  # noqa: F401
)
from tests.integration.test_catalog_import_workflow import ready_export_projection

pytestmark = pytest.mark.mysql


def test_worker_parses_verified_content_and_classifies_storage_failure(
    catalog_import_case: PublicationIntegrationCase,
) -> None:
    runtime, command, workbook, _projection = ready_export_projection(
        catalog_import_case
    )
    try:
        content = render_catalog_workbook(workbook)
        staged = catalog_import_case.dataset_case.store.write_stream(
            uuid4(), BytesIO(content)
        )
        try:
            stored = catalog_import_case.dataset_case.store.promote(staged)
        finally:
            catalog_import_case.dataset_case.store.discard_staged(staged)
        upload = MySqlCatalogUploadRepository(runtime).register_upload(
            CatalogRawUploadCommand(
                uuid4(),
                "catalog.xlsx",
                CATALOG_WORKBOOK_MEDIA_TYPE,
                len(content),
                1,
                catalog_import_case.owner_user_id,
            ),
            stored=stored,
            workbook=workbook,
        )
        worker = CatalogImportWorker(
            MySqlCatalogImportRepository(runtime),
            catalog_import_case.dataset_case.store,
            clock=lambda: datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
        )
        result = worker.run_once()
        assert result is not None
        assert result.import_id == upload
        assert result.status in {"needs_attention", "validated"}

        missing_digest = b"d" * 32
        with catalog_import_case.dataset_case.migration_engine.begin() as connection:
            raw = connection.execute(
                sa.text(
                    """
                    INSERT INTO raw_files (
                        sha256, storage_key, original_filename, media_type,
                        size_bytes, uploaded_by_user_id, uploaded_at
                    ) VALUES (
                        :sha256, :storage_key, 'missing.xlsx', :media_type,
                        9, :owner, UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "sha256": missing_digest,
                    "storage_key": "sha256/64/" + "64" * 32,
                    "media_type": CATALOG_WORKBOOK_MEDIA_TYPE,
                    "owner": catalog_import_case.owner_user_id,
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
                        'missing.xlsx', :media_type, base_catalog_version_id,
                        fact_snapshot_tuple_id, normalization_manifest_id,
                        'uploaded', 0, 0
                    FROM catalog_exports WHERE id = :export_id
                    """
                ),
                {
                    "token": uuid4().bytes,
                    "owner": catalog_import_case.owner_user_id,
                    "raw_file_id": int(raw.lastrowid),
                    "media_type": CATALOG_WORKBOOK_MEDIA_TYPE,
                    "export_id": command.export_id,
                },
            )
            assert imported.lastrowid is not None
            missing_import_id = int(imported.lastrowid)

        failed = worker.run_once()
        assert failed is not None
        assert failed.import_id == missing_import_id
        assert failed.status == "parse_failed"
        attempt = catalog_import_case.dataset_case.rows(
            "SELECT recoverable, failure_reason_code "
            "FROM catalog_parse_attempts WHERE import_id = :import_id",
            {"import_id": missing_import_id},
        )[0]
        assert bool(attempt["recoverable"])
        assert attempt["failure_reason_code"] == (
            "catalog_source_temporarily_unavailable"
        )
    finally:
        runtime.dispose()
