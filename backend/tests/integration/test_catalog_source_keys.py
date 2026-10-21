from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from app.catalog.normalization import seller_sku_match_v1
from app.catalog.scope_repository import (
    MySqlCatalogScopeRepository,
    source_key_material,
)
from app.catalog.scope_service import CatalogScopeService
from app.review.repository import MySqlReviewRepository
from app.review.service import ReviewService
from app.review.types import (
    AddRowCommand,
    DraftHeadExpectation,
    ReviewMutationResult,
    SetFieldValueCommand,
)
from app.validation.fields import FieldValue

from tests.integration.dataset_test_support import NOW, DatasetIntegrationCase
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers the shared fixture
)
from tests.integration.test_catalog_scope import (
    _cleanup_catalog_scope,
    _command,
    _context,
    _materialize,
    _principal,
)

pytestmark = pytest.mark.mysql


def _database_utc(value: object) -> datetime:
    assert isinstance(value, datetime)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _head(case: DatasetIntegrationCase, dataset_id: int) -> DraftHeadExpectation:
    row = case.rows(
        """
        SELECT drafts.dataset_id, drafts.version_id, drafts.version_status,
               drafts.pointed_at, versions.data_revision,
               versions.review_revision
        FROM dataset_drafts AS drafts
        INNER JOIN dataset_versions AS versions
            ON versions.id = drafts.version_id
           AND versions.dataset_id = drafts.dataset_id
        WHERE drafts.dataset_id = :dataset_id
        """,
        {"dataset_id": dataset_id},
    )[0]
    return DraftHeadExpectation(
        dataset_id=int(row["dataset_id"]),
        version_id=int(row["version_id"]),
        status=cast(Any, row["version_status"]),
        data_revision=int(row["data_revision"]),
        review_revision=int(row["review_revision"]),
        pointed_at=_database_utc(row["pointed_at"]),
    )


def _advanced_head(
    previous: DraftHeadExpectation,
    result: ReviewMutationResult,
) -> DraftHeadExpectation:
    assert result.data_revision is not None
    assert result.review_revision is not None
    return DraftHeadExpectation(
        dataset_id=previous.dataset_id,
        version_id=previous.version_id,
        status=cast(Any, result.status),
        data_revision=int(result.data_revision),
        review_revision=int(result.review_revision),
        pointed_at=previous.pointed_at,
    )


def _manual_business_row(sku: str) -> dict[str, FieldValue]:
    return {
        "parent_asin": "B0CATALOGP1",
        "child_asin": "B0CATALOG01",
        "title": "Manual catalog collision fixture",
        "sku": sku,
        "sessions_total": 2,
        "sessions_b2b": 0,
        "conversion_rate_total": Decimal("0.500000000"),
        "session_percentage_b2b": Decimal("0.000000000"),
        "page_views_total": 2,
        "page_views_b2b": 0,
        "page_view_percentage_total": Decimal("0.500000000"),
        "page_view_percentage_b2b": Decimal("0.000000000"),
        "featured_offer_percentage": Decimal("1.000000000"),
        "featured_offer_percentage_b2b": Decimal("0.000000000"),
        "units_ordered": 1,
        "units_ordered_b2b": 0,
        "unit_session_percentage": Decimal("0.500000000"),
        "unit_session_percentage_b2b": Decimal("0.000000000"),
        "ordered_product_sales": Decimal("19.990000"),
        "ordered_product_sales_b2b": Decimal("0.000000"),
        "currency_code": "USD",
        "total_order_items": 1,
        "total_order_items_b2b": 0,
    }


@pytest.fixture(name="source_key_case")
def source_key_case_fixture(
    dataset_case: DatasetIntegrationCase,
) -> Iterator[DatasetIntegrationCase]:
    _cleanup_catalog_scope(dataset_case)
    try:
        yield dataset_case
    finally:
        _cleanup_catalog_scope(dataset_case)


def test_parser_review_and_manual_rows_share_versioned_match_keys(
    source_key_case: DatasetIntegrationCase,
) -> None:
    case = source_key_case
    runtime = case.runtime_engine()
    try:
        admin_context = _context(runtime, _principal(case.admin_user_id, "admin"))
        confirmed = CatalogScopeService(
            MySqlCatalogScopeRepository(runtime),
            clock=lambda: NOW,
        ).confirm(admin_context, _command(admin_context))
        assert confirmed.report_source_scope_id is not None
        scope_id = confirmed.report_source_scope_id

        dataset_id, version_id = _materialize(
            case,
            date(2098, 1, 1) + timedelta(days=uuid4().int % 365),
        )
        initial = case.rows(
            """
            SELECT source_keys.source_row_id, source_keys.source_key_revision,
                   source_keys.seller_sku_raw_sha256,
                   source_keys.seller_sku_match_sha256,
                   source_keys.seller_sku_match_bytes, typed_rows.sku
            FROM report_source_keys AS source_keys
            INNER JOIN business_report_rows AS typed_rows
                ON typed_rows.version_id = source_keys.version_id
               AND typed_rows.version_row_id = source_keys.source_row_id
            WHERE source_keys.version_id = :version_id
            ORDER BY source_keys.source_row_id
            """,
            {"version_id": version_id},
        )
        assert len(initial) == 2
        for row in initial:
            expected = seller_sku_match_v1(str(row["sku"]))
            assert int(row["source_key_revision"]) == 0
            assert bytes(row["seller_sku_match_sha256"]) == expected.sha256
            assert bytes(row["seller_sku_match_bytes"]) == expected.utf8

        review = ReviewService(
            repository=MySqlReviewRepository(runtime),
            clock=lambda: NOW,
        )
        head = _head(case, dataset_id)
        edited_row_id = int(initial[0]["source_row_id"])
        long_sku = "\U0001f600" * 200
        long_edit = review.set_field_value(
            SetFieldValueCommand(
                head=head,
                row_id=edited_row_id,
                field_name="sku",
                value=long_sku,
                actor_user_id=case.owner_user_id,
                operation_token=uuid4(),
                reason="Prove the full normalized UTF-8 bytes fit the sidecar",
            )
        )
        head = _advanced_head(head, long_edit)
        long_match_bytes = case.scalar(
            """
            SELECT seller_sku_match_bytes
            FROM report_source_keys
            WHERE version_id = :version_id
              AND source_row_id = :source_row_id
              AND source_key_revision = 1
            """,
            {"version_id": version_id, "source_row_id": edited_row_id},
        )
        assert bytes(long_match_bytes) == seller_sku_match_v1(long_sku).utf8
        assert len(bytes(long_match_bytes)) == 800

        edited = review.set_field_value(
            SetFieldValueCommand(
                head=head,
                row_id=edited_row_id,
                field_name="sku",
                value="  \uff21\uff22\uff23  ",
                actor_user_id=case.owner_user_id,
                operation_token=uuid4(),
                reason="Exercise the frozen Seller SKU normalizer",
            )
        )
        head = _advanced_head(head, edited)
        added = review.add_row(
            AddRowCommand(
                head=head,
                source_batch_id=case.baselines[-1].batch_id,
                values=_manual_business_row("ABC"),
                actor_user_id=case.owner_user_id,
                operation_token=uuid4(),
                reason="Create an explicit normalization collision",
            )
        )
        assert added.affected_row_id is not None

        current_collision = case.rows(
            """
            SELECT source_keys.source_row_id, source_keys.source_key_revision,
                   source_keys.seller_sku_raw_sha256,
                   source_keys.seller_sku_match_sha256,
                   source_keys.seller_sku_match_bytes,
                   source_keys.collision_group_sha256
            FROM report_source_keys AS source_keys
            INNER JOIN (
                SELECT version_id, source_row_id,
                       MAX(source_key_revision) AS source_key_revision
                FROM report_source_keys
                WHERE version_id = :version_id
                GROUP BY version_id, source_row_id
            ) AS latest
                ON latest.version_id = source_keys.version_id
               AND latest.source_row_id = source_keys.source_row_id
               AND latest.source_key_revision = source_keys.source_key_revision
            INNER JOIN version_rows AS row_records
                ON row_records.version_id = source_keys.version_id
               AND row_records.id = source_keys.source_row_id
               AND row_records.row_state = 'active'
            WHERE source_keys.version_id = :version_id
              AND source_keys.seller_sku_match_bytes = :match_bytes
            ORDER BY source_keys.source_row_id
            """,
            {"version_id": version_id, "match_bytes": b"ABC"},
        )
        assert len(current_collision) == 2
        assert (
            len({bytes(row["seller_sku_raw_sha256"]) for row in current_collision}) == 2
        )
        assert (
            len({bytes(row["collision_group_sha256"]) for row in current_collision})
            == 1
        )
        assert all(
            bytes(row["seller_sku_match_sha256"]) == seller_sku_match_v1("ABC").sha256
            for row in current_collision
        )
        revisions = case.rows(
            """
            SELECT source_key_revision
            FROM report_source_keys
            WHERE version_id = :version_id AND source_row_id = :source_row_id
            ORDER BY source_key_revision
            """,
            {"version_id": version_id, "source_row_id": edited_row_id},
        )
        assert [int(row["source_key_revision"]) for row in revisions] == [0, 1, 2]

        same_key_other_scope = source_key_material(scope_id + 1, "ABC")
        current_scope_key = source_key_material(scope_id, "ABC")
        assert same_key_other_scope.match_sha256 == current_scope_key.match_sha256
        assert same_key_other_scope.match_bytes == current_scope_key.match_bytes
        assert (
            same_key_other_scope.collision_group_sha256
            != current_scope_key.collision_group_sha256
        )
    finally:
        runtime.dispose()
