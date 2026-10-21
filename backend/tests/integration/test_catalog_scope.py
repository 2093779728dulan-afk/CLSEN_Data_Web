from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from app.auth.sessions import Principal
from app.catalog.scope_repository import (
    MySqlCatalogScopeRepository,
    ScopeAlreadyConfirmed,
    ScopeIdempotencyConflict,
    ScopeRevisionConflict,
)
from app.catalog.scope_service import (
    CatalogScopePermissionDenied,
    CatalogScopeService,
    ConfirmScopeCommand,
)
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import MaterializeBaselineCommand
from app.site_context import CurrentSiteContext, resolve_current_site_context
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.integration.dataset_test_support import NOW, DatasetIntegrationCase
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers the shared fixture
)

pytestmark = pytest.mark.mysql


def _principal(user_id: int, *roles: str) -> Principal:
    return Principal(
        user_id=user_id,
        username=f"catalog-{user_id}",
        display_name="Catalog Test",
        roles=frozenset(roles),
        session_id=user_id,
        csrf_token_hash=b"x" * 32,
    )


def _context(engine: Engine, principal: Principal) -> CurrentSiteContext:
    with Session(engine) as session:
        return resolve_current_site_context(session, principal)


def _command(
    context: CurrentSiteContext,
    *,
    token: UUID | None = None,
    scope_key: str = "local-seller-account-one",
    display_name: str = "Local Seller Account",
    reason: str = "Confirm the one-account P0 boundary",
) -> ConfirmScopeCommand:
    return ConfirmScopeCommand(
        operation_token=token or uuid4(),
        expected_site_config_revision=context.site_config_revision,
        seller_account_scope_key=scope_key,
        seller_account_display_name=display_name,
        marketplace_scope_code="amazon_us",
        reason=reason,
    )


def _materialize(case: DatasetIntegrationCase, report_date: date) -> tuple[int, int]:
    baseline = case.seed_baseline(
        report_date=report_date,
        variant=uuid4().hex[:12],
    )
    engine = case.runtime_engine()
    try:
        result = DatasetService(
            repository=MySqlDatasetRepository(engine),
            clock=lambda: NOW,
        ).materialize_baseline(
            MaterializeBaselineCommand(
                batch_id=baseline.batch_id,
                parse_baseline_id=baseline.parse_baseline_id,
                report_date=report_date,
                strategy="replace",
                expected_active_draft=None,
                expected_publication_version_id=None,
                merge_decisions=(),
                actor_user_id=case.owner_user_id,
                operation_token=uuid4(),
                reason="Materialize a catalog scope fixture",
            )
        )
        return result.dataset_id, result.version_id
    finally:
        engine.dispose()


def _cleanup_catalog_scope(case: DatasetIntegrationCase) -> None:
    with case.migration_engine.begin() as connection:
        connection.execute(
            sa.text("DELETE FROM return_dedup_publications WHERE site_id = 1")
        )
        connection.execute(sa.text("DELETE FROM report_source_keys WHERE site_id = 1"))
        connection.execute(
            sa.text("DELETE FROM report_publication_revisions WHERE site_id = 1")
        )
        connection.execute(
            sa.text("DELETE FROM report_dataset_scope_assignments WHERE site_id = 1")
        )
        connection.execute(
            sa.text("DELETE FROM catalog_audit_events WHERE site_id = 1")
        )
        connection.execute(
            sa.text("DELETE FROM catalog_command_effects WHERE site_id = 1")
        )
        connection.execute(
            sa.text("DELETE FROM catalog_command_claims WHERE site_id = 1")
        )
        connection.execute(
            sa.text("DELETE FROM report_source_scopes WHERE site_id = 1")
        )
        connection.execute(
            sa.text(
                """
                UPDATE site_current_configs
                SET current_config_version_id = 1,
                    updated_by_user_id = NULL
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


@pytest.fixture(name="clean_catalog_scope")
def clean_catalog_scope_fixture(
    dataset_case: DatasetIntegrationCase,
) -> Iterator[DatasetIntegrationCase]:
    _cleanup_catalog_scope(dataset_case)
    try:
        yield dataset_case
    finally:
        _cleanup_catalog_scope(dataset_case)


def test_scope_confirmation_is_admin_only_idempotent_and_irreversible(
    clean_catalog_scope: DatasetIntegrationCase,
) -> None:
    case = clean_catalog_scope
    historical_dataset_id, historical_version_id = _materialize(
        case,
        date(2096, 1, 1) + timedelta(days=uuid4().int % 1000),
    )
    runtime = case.runtime_engine()
    try:
        repository = MySqlCatalogScopeRepository(runtime)
        service = CatalogScopeService(repository, clock=lambda: NOW)
        viewer_context = _context(runtime, _principal(case.owner_user_id, "viewer"))
        with pytest.raises(CatalogScopePermissionDenied):
            service.confirm(viewer_context, _command(viewer_context))

        admin_context = _context(runtime, _principal(case.admin_user_id, "admin"))
        token = uuid4()
        command = _command(admin_context, token=token)
        confirmed = service.confirm(admin_context, command)
        assert confirmed.status == "confirmed"
        assert confirmed.site_config_revision == admin_context.site_config_revision + 1

        refreshed = _context(runtime, _principal(case.admin_user_id, "admin"))
        assert service.confirm(refreshed, command) == confirmed

        with pytest.raises(ScopeIdempotencyConflict):
            service.confirm(
                refreshed,
                replace(command, seller_account_display_name="Changed Name"),
            )
        with pytest.raises(ScopeRevisionConflict):
            service.confirm(
                refreshed,
                replace(command, operation_token=uuid4()),
            )

        same_semantics = service.confirm(refreshed, _command(refreshed))
        assert same_semantics.report_source_scope_id == (
            confirmed.report_source_scope_id
        )
        with pytest.raises(ScopeAlreadyConfirmed):
            service.confirm(
                refreshed,
                _command(refreshed, scope_key="another-seller-account"),
            )

        assignment = case.rows(
            """
            SELECT dataset_id, site_id, report_source_scope_id
            FROM report_dataset_scope_assignments
            WHERE dataset_id = :dataset_id
            """,
            {"dataset_id": historical_dataset_id},
        )
        assert assignment == [
            {
                "dataset_id": historical_dataset_id,
                "site_id": 1,
                "report_source_scope_id": confirmed.report_source_scope_id,
            }
        ]
        assert (
            case.scalar(
                "SELECT publication_revision FROM report_publication_revisions "
                "WHERE dataset_id = :dataset_id",
                {"dataset_id": historical_dataset_id},
            )
            == 0
        )
        assert (
            case.scalar(
                "SELECT COUNT(*) FROM report_source_keys "
                "WHERE version_id = :version_id",
                {"version_id": historical_version_id},
            )
            == 2
        )

        new_dataset_id, _ = _materialize(
            case,
            date(2099, 1, 1) + timedelta(days=uuid4().int % 1000),
        )
        assert (
            case.scalar(
                "SELECT COUNT(*) FROM report_dataset_scope_assignments "
                "WHERE dataset_id = :dataset_id",
                {"dataset_id": new_dataset_id},
            )
            == 1
        )
        assert (
            case.scalar(
                "SELECT COUNT(*) FROM report_publication_revisions "
                "WHERE dataset_id = :dataset_id",
                {"dataset_id": new_dataset_id},
            )
            == 1
        )
        assert case.scalar("SELECT COUNT(*) FROM daily_datasets WHERE site_id = 1") == (
            case.scalar(
                "SELECT COUNT(*) FROM report_dataset_scope_assignments "
                "WHERE site_id = 1"
            )
        )
    finally:
        runtime.dispose()
