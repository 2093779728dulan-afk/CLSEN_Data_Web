from __future__ import annotations

import pytest
from app.analytics.style_repository import (
    AnalyticsIdentityFactCombinationInvalid,
    CatalogSnapshotRangeOutOfBounds,
    MySqlStyleAnalyticsRepository,
)

from tests.integration.test_style_analytics import (
    REPORT_DATE,
    ApprovedStyleAnalyticsCase,
    _dataset_case,  # noqa: F401
    _publication_case,  # noqa: F401
    catalog_approval_case_fixture,  # noqa: F401
    style_analytics_case_fixture,  # noqa: F401
)

pytestmark = pytest.mark.mysql


def test_current_and_catalog_snapshot_replay_the_same_frozen_day(
    style_analytics_case: ApprovedStyleAnalyticsCase,
) -> None:
    repository = MySqlStyleAnalyticsRepository(style_analytics_case.engine)

    current = repository.ledger(
        site_id=1,
        from_date=REPORT_DATE,
        to_date=REPORT_DATE,
        fact_basis="current",
        return_basis="report_date",
    )
    snapshot = repository.ledger(
        site_id=1,
        from_date=REPORT_DATE,
        to_date=REPORT_DATE,
        catalog_version_id=style_analytics_case.catalog_version_id,
        fact_basis="catalog_snapshot",
        return_basis="report_date",
    )

    assert [row.metrics for row in current.rows] == [
        row.metrics for row in snapshot.rows
    ]
    assert current.provenance.fact_basis == "current"
    assert current.provenance.publication_refs.snapshot_id is None
    assert snapshot.provenance.fact_basis == "catalog_snapshot"
    assert snapshot.provenance.publication_refs.snapshot_id is not None
    assert current.provenance.return_dedup_snapshot_id == (
        snapshot.provenance.return_dedup_snapshot_id
    )


def test_invalid_identity_fact_combinations_fail_without_fallback(
    style_analytics_case: ApprovedStyleAnalyticsCase,
) -> None:
    repository = MySqlStyleAnalyticsRepository(style_analytics_case.engine)

    with pytest.raises(AnalyticsIdentityFactCombinationInvalid):
        repository.ledger(
            site_id=1,
            from_date=REPORT_DATE,
            to_date=REPORT_DATE,
            catalog_version_id=style_analytics_case.catalog_version_id + 1000,
            fact_basis="current",
        )
    with pytest.raises(CatalogSnapshotRangeOutOfBounds):
        repository.ledger(
            site_id=1,
            from_date=REPORT_DATE.replace(day=REPORT_DATE.day - 1),
            to_date=REPORT_DATE,
            catalog_version_id=style_analytics_case.catalog_version_id,
            fact_basis="catalog_snapshot",
        )
