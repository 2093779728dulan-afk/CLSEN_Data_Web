from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.api.batch_reviews import PreflightRequest, create_preflight, get_batch_review
from app.auth.sessions import Principal

from tests.integration.dataset_test_support import (
    DatasetIntegrationCase,
)
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers shared fixture
)

pytestmark = pytest.mark.mysql


def test_preflight_and_get_api_models_round_trip_persisted_server_facts(
    dataset_case: DatasetIntegrationCase,
) -> None:
    baseline = dataset_case.seed_baseline(
        report_date=date(2098, 4, 1),
        variant="batch-api",
    )
    principal = Principal(
        user_id=dataset_case.owner_user_id,
        username="batch-api-manager",
        display_name="Batch API Manager",
        roles=frozenset({"data_manager"}),
        session_id=1,
        csrf_token_hash=b"csrf",
    )
    runtime_engine = dataset_case.runtime_engine()
    run_id: int | None = None
    try:
        created = create_preflight(
            payload=PreflightRequest(batch_ids=[baseline.batch_id]),
            principal=principal,
            engine=runtime_engine,
            operation_token=uuid4(),
        )
        run_id = created.id
        recovered = get_batch_review(
            run_id=created.id,
            principal=principal,
            engine=runtime_engine,
        )

        assert recovered.model_dump() == created.model_dump()
        assert recovered.items[0].batch_id == baseline.batch_id
        assert recovered.items[0].filename.endswith(".csv")
        assert recovered.items[0].report_date == "2098-04-01"
        assert recovered.items[0].report_type == "business_report"
        assert recovered.items[0].encoding == "utf-8-sig"
        assert recovered.items[0].operation_token is None
    finally:
        runtime_engine.dispose()
        if run_id is not None:
            with dataset_case.migration_engine.begin() as connection:
                connection.execute(
                    sa.text("DELETE FROM batch_review_commands WHERE run_id = :run_id"),
                    {"run_id": run_id},
                )
                connection.execute(
                    sa.text("DELETE FROM batch_review_runs WHERE id = :run_id"),
                    {"run_id": run_id},
                )
