# ruff: noqa: E501, SIM117
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.catalog.scope_correction import Correction, CorrectionRejected, execute
from app.catalog.scope_repository import MySqlCatalogScopeRepository
from app.catalog.scope_service import CatalogScopeService

from tests.integration.dataset_test_support import (
    DatasetIntegrationCase,
)
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.test_catalog_scope import (
    _cleanup_catalog_scope,
    _command,
    _context,
    _materialize,
    _principal,
)

pytestmark = pytest.mark.mysql


def _assert_no_catalog_jobs(case: DatasetIntegrationCase) -> None:
    with case.migration_engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text("SELECT COUNT(*) FROM catalog_jobs WHERE site_id = 1")
            )
            == 0
        )


def test_offline_correction_preserves_identity_and_serializes(
    dataset_case: DatasetIntegrationCase,
) -> None:
    case = dataset_case
    _assert_no_catalog_jobs(case)
    _cleanup_catalog_scope(case)
    runtime = case.runtime_engine()
    try:
        _materialize(case, date(2095, 6, 1))
        context = _context(runtime, _principal(case.admin_user_id, "admin"))
        service = CatalogScopeService(MySqlCatalogScopeRepository(runtime))
        original_command = _command(context, scope_key="1", display_name="1")
        original = service.confirm(context, original_command)
        assert original.report_source_scope_id is not None
        context = _context(runtime, _principal(case.admin_user_id, "admin"))
        with case.migration_engine.connect() as c:
            username = c.scalar(
                sa.text("SELECT username_normalized FROM users WHERE id=:id"),
                {"id": case.admin_user_id},
            )
            viewer = c.scalar(
                sa.text("SELECT username_normalized FROM users WHERE id=:id"),
                {"id": case.owner_user_id},
            )
        command = Correction(
            1,
            original.report_source_scope_id,
            username,
            context.site_config_revision,
            "1",
            "synthetic-seller-2",
            "Synthetic seller",
            "Correct test placeholder",
            "https://example.com/evidence",
            str(uuid4()),
        )
        preview = execute(case.migration_engine, command)
        assert preview["status"] == "preview"
        assert (
            preview["evidence"]["preserved"]["report_dataset_scope_assignments"][
                "count"
            ]
            > 0
        )
        for invalid in (
            replace(command, actor_username=viewer),
            replace(command, site_id=2),
            replace(command, expected_revision=999),
            replace(command, expected_old_key="wrong"),
        ):
            with pytest.raises(CorrectionRejected):
                execute(case.migration_engine, invalid, apply=True, quiesced=True)
        with pytest.raises(CorrectionRejected, match="stop_lan_writers"):
            execute(case.migration_engine, command, apply=True)
        with case.migration_engine.begin() as c:
            c.execute(
                sa.text(
                    "UPDATE return_dedup_publications SET dedup_publication_revision=1 WHERE site_id=1"
                )
            )
        with pytest.raises(CorrectionRejected, match="dedup_pointer_not_empty"):
            execute(case.migration_engine, command, apply=True, quiesced=True)
        with case.migration_engine.begin() as c:
            c.execute(
                sa.text(
                    "UPDATE return_dedup_publications SET dedup_publication_revision=0 WHERE site_id=1"
                )
            )

        def run() -> dict[str, Any]:
            return execute(case.migration_engine, command, apply=True, quiesced=True)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        assert sorted(r["status"] for r in results) == ["applied", "replayed"]
        applied = next(r for r in results if r["status"] == "applied")
        assert applied["evidence"]["preserved"] == preview["evidence"]["preserved"]
        with pytest.raises(CorrectionRejected, match="operation_token_conflict"):
            execute(
                case.migration_engine,
                replace(command, reason="changed"),
                apply=True,
                quiesced=True,
            )
        with pytest.raises(CorrectionRejected, match="already_corrected"):
            execute(
                case.migration_engine,
                replace(command, operation_token=str(uuid4())),
                apply=True,
                quiesced=True,
            )
        fresh = _context(runtime, _principal(case.admin_user_id, "admin"))
        assert service.status(fresh).seller_account_display_name == "Synthetic seller"
        assert (
            service.status(fresh).report_source_scope_id
            == original.report_source_scope_id
        )
        assert service.confirm(fresh, original_command) == original
        new_confirmation = _command(
            fresh, scope_key="synthetic-seller-2", display_name="Synthetic seller"
        )
        new_result = service.confirm(fresh, new_confirmation)
        assert new_result.seller_account_display_name == "Synthetic seller"
        assert service.confirm(fresh, new_confirmation) == new_result
        with case.migration_engine.connect() as c:
            assert (
                c.scalar(
                    sa.text(
                        "SELECT seller_account_display_name FROM report_source_scopes WHERE site_id=1"
                    )
                )
                == "1"
            )
            assert (
                c.scalar(
                    sa.text(
                        "SELECT COUNT(*) FROM catalog_audit_events WHERE event_kind='catalog.source_scope_corrected'"
                    )
                )
                == 1
            )
        with runtime.begin() as c:
            with pytest.raises(sa.exc.DBAPIError):
                c.execute(
                    sa.text(
                        "UPDATE report_source_scope_corrections SET seller_account_display_name='tamper'"
                    )
                )
    finally:
        runtime.dispose()
        with case.migration_engine.begin() as c:
            c.execute(
                sa.text("DELETE FROM report_source_scope_corrections WHERE site_id=1")
            )
        _cleanup_catalog_scope(case)
