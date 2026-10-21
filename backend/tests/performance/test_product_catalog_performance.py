from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.catalog.service import CatalogService
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings

from tests.integration.conftest import (
    alembic_config,  # noqa: F401
    mysql_engine,  # noqa: F401
    mysql_settings,  # noqa: F401
)
from tests.integration.dataset_test_support import (
    dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import publication_case  # noqa: F401
from tests.integration.test_authentication_api import _create_user
from tests.integration.test_catalog_repository import (
    _prepare_ready_import,
    catalog_approval_case_fixture,  # noqa: F401
)
from tests.performance.product_catalog_scale_fixture import (
    PERFORMANCE_BUDGET_MS,
    SCALE_COUNTS,
    SCALE_NAME,
    assert_release_profile,
    build_scale_workbook,
    fixture_contract_digest,
    iter_seller_keys,
    iter_source_evidence_keys,
    percentile_95,
    produce_scale_evidence,
    release_source_identity,
    seed_scale_database,
    validate_release_evidence_identity,
)


def test_analytics_scale_v1_is_exact_and_deterministic() -> None:
    keys = list(iter_seller_keys())
    evidence = list(iter_source_evidence_keys())
    assert len(keys) == 11_200
    assert len({key.seller_sku for key in keys}) == 11_200
    assert len(evidence) == 22_400
    assert len(set(evidence)) == 22_400
    assert SCALE_COUNTS["business_rows"] == 4_088_000
    assert SCALE_COUNTS["return_rows"] == 408_800
    assert SCALE_COUNTS["duplicate_canonical_members"] == 4_088
    assert SCALE_COUNTS["unresolved_duplicate_members"] == 4_088
    assert len(fixture_contract_digest()) == 64


def test_release_p95_uses_twenty_samples() -> None:
    assert percentile_95(float(value) for value in range(1, 21)) == 19.0
    with pytest.raises(ValueError, match="exactly 20"):
        percentile_95([1.0] * 19)


def test_scale_workbook_round_trips_through_review_projection() -> None:
    if os.getenv("APP_GENERATE_PRODUCT_CATALOG_SCALE_EVIDENCE") == "1":
        pytest.skip("the producer performs the same full workbook roundtrip")
    from app.catalog.import_service import project_catalog_workbook
    from app.catalog.workbook import parse_catalog_workbook, render_catalog_workbook

    source = build_scale_workbook()
    archive = render_catalog_workbook(source)
    parsed = parse_catalog_workbook(archive)
    reparsed = parse_catalog_workbook(render_catalog_workbook(parsed))
    projection = project_catalog_workbook(parsed)

    assert len(parsed.rows["款式主档"]) == SCALE_COUNTS["styles"]
    assert len(parsed.rows["来源证据"]) == SCALE_COUNTS["source_evidence"]
    assert reparsed.rows == parsed.rows
    assert len(projection.rows) == sum(
        len(rows) for sheet, rows in parsed.rows.items() if sheet != "生成信息"
    )


@pytest.mark.mysql
def test_generate_scale_evidence_when_requested(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.getenv("APP_GENERATE_PRODUCT_CATALOG_SCALE_EVIDENCE") != "1":
        pytest.skip("scale evidence producer was not requested")
    evidence_path = os.getenv("APP_PRODUCT_CATALOG_SCALE_EVIDENCE_PATH", "")
    if not evidence_path:
        pytest.fail("scale evidence output path is required", pytrace=False)
    runtime_url = os.getenv("APP_TEST_RUNTIME_DATABASE_URL", "")
    if not runtime_url:
        pytest.fail("scale producer runtime URL is required", pytrace=False)

    import tests.integration.dataset_test_support as dataset_support
    import tests.integration.publication_test_support as publication_support
    import tests.integration.test_catalog_repository as catalog_support

    # The matrix destroys the entire runner-owned database. Avoid a multi-million
    # row fixture teardown inside nested integration finalizers.
    monkeypatch.setattr(dataset_support, "_cleanup_case", lambda _case: None)
    monkeypatch.setattr(
        publication_support, "_cleanup_publication_records", lambda _case: None
    )
    monkeypatch.setattr(catalog_support, "_cleanup_catalog", lambda _case: None)
    case = request.getfixturevalue("catalog_approval_case")
    runtime, import_id, preview = _prepare_ready_import(case)
    try:
        approved = CatalogService(runtime).approve_import(
            import_id=import_id,
            site_id=1,
            actor_user_id=case.owner_user_id,
            actor_roles=frozenset({"data_manager"}),
            operation_token=uuid4(),
            expected_workflow_revision=2,
            expected_catalog_publication_revision=0,
            projection_id=preview.projection_id,
            projection_digest=preview.projection_digest,
            reason="Approve the scale benchmark base catalog",
            now=datetime(2026, 8, 21, 15, 5, tzinfo=UTC),
        )
        seed = seed_scale_database(
            case.dataset_case.migration_engine,
            base_catalog_version_id=approved.catalog_version_id,
            actor_user_id=case.owner_user_id,
        )
        _, username = _create_user(
            case.dataset_case.migration_engine,
            role="data_manager",
            password="analytics scale benchmark password",
        )
        evidence = produce_scale_evidence(
            case.dataset_case.migration_engine,
            runtime_database_url=runtime_url,
            seed=seed,
            username=username,
            password="analytics scale benchmark password",
            output_path=Path(evidence_path),
        )
    finally:
        runtime.dispose()
    assert evidence["counts"] == SCALE_COUNTS


@pytest.mark.mysql
def test_release_profile_and_external_scale_evidence() -> None:
    if os.getenv("APP_REQUIRE_PRODUCT_CATALOG_PERFORMANCE") != "1":
        pytest.skip("canonical performance runner is required")
    evidence_path = os.getenv("APP_PRODUCT_CATALOG_SCALE_EVIDENCE_PATH", "")
    if not evidence_path:
        pytest.fail("scale evidence path is required", pytrace=False)
    path = Path(evidence_path)
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        pytest.fail("scale evidence is unreadable", pytrace=False)
    if not isinstance(evidence, dict):
        pytest.fail("scale evidence root is invalid", pytrace=False)
    try:
        validate_release_evidence_identity(evidence, release_source_identity())
    except ValueError as error:
        pytest.fail(str(error), pytrace=False)

    settings = DatabaseSettings.from_url(os.environ["APP_TEST_DATABASE_URL"])
    profile_engine = create_database_engine(settings)
    try:
        with profile_engine.connect() as connection:
            version, comment, buffer_pool = connection.execute(
                sa.text(
                    "SELECT @@version, @@version_comment, @@innodb_buffer_pool_size"
                )
            ).one()
    finally:
        profile_engine.dispose()
    assert_release_profile(
        mysql_version=str(version),
        version_comment=str(comment),
        buffer_pool_bytes=int(buffer_pool),
        cpu_count=int(evidence.get("cpu_count", 0)),
        memory_bytes=int(evidence.get("memory_bytes", 0)),
    )
    assert evidence.get("fixture") == SCALE_NAME
    assert evidence.get("fixture_contract_digest") == fixture_contract_digest()
    assert evidence.get("counts") == SCALE_COUNTS
    assert evidence.get("warmup_samples") == 3
    assert evidence.get("measured_samples") == 20
    assert evidence.get("mysql_version") in {"8.0", "8.4"}
    assert str(version).startswith(f"{evidence['mysql_version']}.")
    assert evidence.get("loopback_release_api") is True
    assert evidence.get("dedup_successors") == 365
    assert evidence.get("redo_log_capacity_bytes") == 2 * 1024**3
    assert evidence.get("innodb_flush_log_at_trx_commit") == 2
    assert evidence.get("sync_binlog") == 0
    assert evidence.get("delta_depth_max", 33) <= 32
    assert evidence.get("physical_group_membership", 150_001) <= 150_000
    timings = evidence.get("p95_ms")
    assert isinstance(timings, dict)
    for scenario, budget in PERFORMANCE_BUDGET_MS.items():
        assert isinstance(timings.get(scenario), (int, float))
        assert timings[scenario] <= budget
    assert evidence.get("explain_analyze_bounded") is True
    assert evidence.get("xlsx_excel_roundtrip") is True
