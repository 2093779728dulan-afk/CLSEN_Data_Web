from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import cast
from uuid import uuid4

import pytest
from app.analytics.style_repository import MySqlStyleAnalyticsRepository
from app.catalog.service import CatalogService
from sqlalchemy.engine import Engine

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,
)
from tests.integration.publication_test_support import PublicationIntegrationCase
from tests.integration.publication_test_support import (
    publication_case as _publication_case,
)
from tests.integration.test_catalog_repository import (
    _prepare_ready_import,
    catalog_approval_case_fixture,
)

__all__ = (
    "FACT_CUTOFF",
    "REPORT_DATE",
    "ApprovedStyleAnalyticsCase",
    "_dataset_case",
    "_publication_case",
    "catalog_approval_case_fixture",
    "style_analytics_case_fixture",
)

pytestmark = pytest.mark.mysql

REPORT_DATE = date(2026, 8, 22)
FACT_CUTOFF = datetime(2098, 7, 18, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ApprovedStyleAnalyticsCase:
    publication_case: PublicationIntegrationCase
    engine: Engine
    catalog_version_id: int


@pytest.fixture(name="style_analytics_case")
def style_analytics_case_fixture(
    catalog_approval_case: PublicationIntegrationCase,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[ApprovedStyleAnalyticsCase]:
    import tests.integration.test_catalog_export_finalization as export_support
    import tests.integration.test_catalog_snapshot_consistency as snapshot_support

    monkeypatch.setattr(export_support, "REPORT_DATE", REPORT_DATE)
    monkeypatch.setattr(export_support, "CUTOFF", FACT_CUTOFF)
    monkeypatch.setattr(snapshot_support, "REPORT_DATE", REPORT_DATE)
    runtime, import_id, preview_value = _prepare_ready_import(catalog_approval_case)
    preview = preview_value
    approved = CatalogService(runtime).approve_import(
        import_id=import_id,
        site_id=1,
        actor_user_id=catalog_approval_case.owner_user_id,
        actor_roles=frozenset({"data_manager"}),
        operation_token=uuid4(),
        expected_workflow_revision=2,
        expected_catalog_publication_revision=0,
        projection_id=preview.projection_id,
        projection_digest=preview.projection_digest,
        reason="Approve the stable catalog for style analytics integration",
        now=datetime(2026, 8, 21, 15, 5, tzinfo=UTC),
    )
    try:
        yield ApprovedStyleAnalyticsCase(
            publication_case=catalog_approval_case,
            engine=runtime,
            catalog_version_id=approved.catalog_version_id,
        )
    finally:
        runtime.dispose()


def test_style_ledger_aggregates_in_mysql_and_returns_site_six_buckets(
    style_analytics_case: ApprovedStyleAnalyticsCase,
) -> None:
    response = MySqlStyleAnalyticsRepository(style_analytics_case.engine).ledger(
        site_id=1,
        from_date=REPORT_DATE,
        to_date=REPORT_DATE,
        return_basis="report_date",
        sort="units",
        direction="desc",
    )

    assert response.provenance.identity_source == "p0_catalog"
    assert response.provenance.catalog_version_id == str(
        style_analytics_case.catalog_version_id
    )
    assert response.coverage.business.published_days == 1
    assert response.coverage.returns.published_days == 1
    assert response.total_rows == len(response.rows)
    assert response.total_rows >= 1
    mapped_units = [row.metrics.units.value for row in response.rows]
    assert all(isinstance(value, int) for value in mapped_units)
    assert sum(cast(int, value) for value in mapped_units) == (
        response.reconciliation.mapped_totals.units
    )
    totals = response.reconciliation
    assert totals.source_totals.units == sum(
        value
        for value in (
            totals.mapped_totals.units,
            totals.unmatched_totals.units,
            totals.excluded_totals.units,
        )
        if value is not None
    )
    assert totals.source_totals.returns == sum(
        value
        for value in (
            totals.mapped_totals.returns,
            totals.unmatched_totals.returns,
            totals.excluded_totals.returns,
            totals.duplicate_totals.returns,
            totals.unresolved_duplicate_totals.returns,
        )
        if value is not None
    )


def test_style_card_uses_stable_style_and_sku_members_only(
    style_analytics_case: ApprovedStyleAnalyticsCase,
) -> None:
    repository = MySqlStyleAnalyticsRepository(style_analytics_case.engine)
    ledger = repository.ledger(
        site_id=1,
        from_date=REPORT_DATE,
        to_date=REPORT_DATE,
        return_basis="report_date",
    )
    style_id = int(ledger.rows[0].style_id)

    card = repository.card(
        site_id=1,
        style_id=style_id,
        from_date=REPORT_DATE,
        to_date=REPORT_DATE,
        metric="units",
        dimension="color",
        return_basis="report_date",
    )

    assert card.style.style_id == str(style_id)
    assert card.summary.metrics == ledger.rows[0].metrics
    assert card.style_reconciliation.summary_totals == (
        card.style_reconciliation.variant_totals
    )
    assert card.style_reconciliation.series_scope_totals == (
        card.style_reconciliation.summary_totals
    )
    assert all(variant.sku_id.isdecimal() for variant in card.variants)
    assert len(card.series) <= 8
