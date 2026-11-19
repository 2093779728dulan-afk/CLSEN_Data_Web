"""Production-origin mapping consumes later reports without a second identity."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.analytics.style_repository import MySqlStyleAnalyticsRepository
from app.catalog.commands import CatalogDecisionMutation
from app.catalog.import_repository import MySqlCatalogImportRepository
from app.catalog.production_sources import ProductionSource, create_production_import
from app.catalog.repository import load_import_rows
from app.catalog.service import CatalogService

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import PublicationIntegrationCase
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)
from tests.integration.test_catalog_repository import (
    catalog_approval_case_fixture,  # noqa: F401
)
from tests.integration.test_catalog_snapshot_consistency import (
    _confirm_scope,
    _seed_ready_dedup,
)

pytestmark = pytest.mark.mysql
REPORT_DATE = date(2026, 8, 22)


def test_production_mapping_later_sales_returns_and_atomic_rollback(
    catalog_approval_case: PublicationIntegrationCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tests.integration.dataset_test_support as support
    import tests.integration.test_catalog_snapshot_consistency as snapshot_support

    monkeypatch.setattr(snapshot_support, "REPORT_DATE", REPORT_DATE)
    case = catalog_approval_case
    scope = _confirm_scope(case)
    engine = case.dataset_case.runtime_engine()
    actor = case.admin_user_id
    code = "QA-AMAZON-FORMAL-REPORTS"
    source = ProductionSource.model_validate(
        {
            "source_name": "Fictional approved Amazon listing",
            "report_source_scope_id": scope,
            "channel_evidence": "Fictional scope and listing verified",
            "rows": [
                {
                    "style_code": "QA-REPORT-STYLE",
                    "color": "Olive",
                    "size": "M",
                    "formal_sku": code,
                },
                {"style_code": "QA-REPORT-STYLE", "color": "Olive", "size": "L"},
            ],
        }
    )
    result = create_production_import(
        engine,
        site_id=1,
        actor_id=actor,
        token=uuid4(),
        source=source,
        expected_revision=0,
    )
    import_id = result["import_id"]
    assert isinstance(import_id, int | str)
    identity = int(import_id)
    repo = MySqlCatalogImportRepository(engine)

    def args() -> dict[str, Any]:
        return dict(
            import_id=identity,
            site_id=1,
            actor_user_id=actor,
            operation_token=uuid4(),
            expected_workflow_revision=repo.get_state(
                import_id=identity, site_id=1
            ).workflow_revision,
        )

    with engine.connect() as connection:
        rows = load_import_rows(connection, import_id=identity, workflow_revision=0)
    sku = next(
        r for r in rows if r.section == "skus" and r.payload["standard_size"] == "M"
    )
    mutations = []
    for row in rows:
        if row.section == "styles":
            mutations.append(
                CatalogDecisionMutation(
                    uuid4(),
                    "update_style",
                    row.row_key,
                    None,
                    {"standard_name": "Fictional shirt"},
                )
            )
        elif row.section == "skus":
            mutations.append(
                CatalogDecisionMutation(
                    uuid4(),
                    "update_sku",
                    row.row_key,
                    None,
                    {
                        "internal_display_sku": code
                        if row.payload["standard_size"] == "M"
                        else None,
                        "code_status": "confirmed"
                        if row.payload["standard_size"] == "M"
                        else "pending",
                        "code_evidence": source.source_name,
                    },
                )
            )
        elif row.section == "mappings":
            mutations.append(
                CatalogDecisionMutation(
                    uuid4(),
                    "map_seller_sku",
                    None,
                    row.row_key,
                    {"target_sku_row_key": sku.row_key},
                )
            )
    repo.apply_decisions(**args(), mutations=tuple(mutations))
    repo.validate_import(**args())
    repo.transition_import(**args(), command="submit")
    service = CatalogService(engine)
    preview = service.preview_import(
        **args(), actor_roles=frozenset({"admin"}), now=datetime.now(UTC)
    )
    approval = args() | dict(
        actor_roles=frozenset({"admin"}),
        expected_catalog_publication_revision=preview.catalog_publication_revision,
        projection_id=preview.projection_id,
        projection_digest=preview.projection_digest,
        reason="Fictional report linkage validation",
        now=datetime.now(UTC),
    )

    def fail_mapping(
        conn: sa.Connection,
        cursor: Any,
        statement: str,
        parameters: object,
        context: Any,
        executemany: bool,
    ) -> None:
        if "INSERT INTO product_catalog_mappings" in statement:
            raise RuntimeError("synthetic mapping write failure")

    sa.event.listen(engine, "before_cursor_execute", fail_mapping)
    try:
        with pytest.raises(RuntimeError, match="synthetic mapping"):
            service.approve_import(**approval)
    finally:
        sa.event.remove(engine, "before_cursor_execute", fail_mapping)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text("SELECT COUNT(*) FROM product_skus WHERE site_id=1")
            )
            == 0
        )
        assert (
            connection.scalar(
                sa.text("SELECT COUNT(*) FROM product_catalog_versions WHERE site_id=1")
            )
            == 0
        )
    approved = service.approve_import(**approval)
    repeated = service.approve_import(**approval)
    assert repeated.catalog_version_id == approved.catalog_version_id
    with engine.connect() as connection:
        sku_id = connection.scalar(
            sa.text("SELECT id FROM product_skus WHERE internal_display_sku=:code"),
            {"code": code},
        )
        style_id = connection.scalar(
            sa.text("SELECT style_id FROM product_skus WHERE id=:id"), {"id": sku_id}
        )
    original = support._variant_report

    def report(kind: str, variant: str, **kwargs: Any) -> bytes:
        encoding = "utf-8-sig" if kind == "business_report" else "windows-1252"
        rows = list(
            csv.reader(io.StringIO(original(kind, variant, **kwargs).decode(encoding)))
        )
        header = rows[0]
        index = header.index("SKU" if kind == "business_report" else "sku")
        qty = header.index(
            "已订购商品数量" if kind == "business_report" else "quantity"
        )
        rows[1][index] = code
        rows[1][qty] = "10" if kind == "business_report" else "2"
        rows[2][index] = "QA-UNMATCHED"
        rows[2][qty] = "1"
        output = io.StringIO()
        csv.writer(output).writerows(rows)
        return output.getvalue().encode(encoding)

    monkeypatch.setattr(support, "_variant_report", report)
    _, business = case.materialize_baseline(
        report_date=REPORT_DATE, variant="formal-business"
    )
    _, returns = case.materialize_baseline(
        report_date=REPORT_DATE, variant="formal-returns", report_type="return_report"
    )
    case.dataset_case.mark_published(business.dataset_id, business.version_id)
    case.dataset_case.mark_published(returns.dataset_id, returns.version_id)
    _seed_ready_dedup(
        case,
        scope_id=scope,
        return_dataset_id=returns.dataset_id,
        return_version_id=returns.version_id,
    )
    repository = MySqlStyleAnalyticsRepository(engine)

    def check() -> None:
        ledger = repository.ledger(
            site_id=1,
            from_date=REPORT_DATE,
            to_date=REPORT_DATE,
            return_basis="report_date",
        )
        assert ledger.reconciliation.mapped_totals.units == 10
        assert ledger.reconciliation.mapped_totals.returns == 2
        assert ledger.reconciliation.unmatched_totals.units == 1
        assert ledger.reconciliation.unmatched_totals.returns == 1
        assert ledger.reconciliation.source_totals.units == 11
        assert ledger.reconciliation.source_totals.returns == 3
        card = repository.card(
            site_id=1,
            style_id=style_id,
            from_date=REPORT_DATE,
            to_date=REPORT_DATE,
            return_basis="report_date",
            metric="units",
            dimension="color",
        )
        confirmed = next(v for v in card.variants if v.sku_id == str(sku_id))
        assert confirmed.internal_display_sku == code
        assert len(confirmed.seller_sku_aliases) == 1
        assert confirmed.seller_sku_aliases[0].preview == code
        pending = next(v for v in card.variants if v.sku_id != str(sku_id))
        assert pending.internal_display_sku is None
        assert pending.standard_size == "L"
        sku_card = repository.card(
            site_id=1,
            style_id=style_id,
            from_date=REPORT_DATE,
            to_date=REPORT_DATE,
            return_basis="report_date",
            metric="units",
            dimension="sku",
        )
        assert any(
            item.label == "Olive · L · 正式SKU待补"
            for item in sku_card.available_series
        )
        assert all(item.label != "None" for item in sku_card.available_series)

    check()
    from app.config import Settings
    from app.db.session import create_session_factory
    from app.main import create_app
    from fastapi.testclient import TestClient

    from tests.integration.test_authentication_api import _create_user, _login

    _, username = _create_user(
        engine, role="viewer", password="fictional analytics password"
    )
    settings = Settings(
        environment="test",
        log_level="WARNING",
        cors_allowed_origins=(),
        session_secret="fictional-analytics-api-secret-0000000",
        session_cookie_secure=False,
    )
    with TestClient(
        create_app(settings=settings, session_factory=create_session_factory(engine))
    ) as client:
        _login(client, username=username, password="fictional analytics password")
        path = f"/api/dashboard/styles/{style_id}/card"
        params = {
            "from": REPORT_DATE.isoformat(),
            "to": REPORT_DATE.isoformat(),
            "return_basis": "report_date",
            "dimension": "sku",
        }
        old = client.get(path, params=params)
        assert old.status_code == 409, old.text
        assert old.json()["error"]["code"] == "catalog_consumer_upgrade_required"
        new = client.get(path, params=params | {"contract_version": "2"})
        assert new.status_code == 200, new.text
        assert any(v["internal_display_sku"] is None for v in new.json()["variants"])
    # Byte-identical uploads are recognized before parsing; neither report doubles.
    from datetime import timedelta

    from app.imports.repository import MySqlIngestRepository
    from app.imports.service import IngestService
    from app.imports.types import DuplicateBatchConflict, ImportCommand

    ingest = IngestService(
        repository=MySqlIngestRepository(engine, lock_timeout_seconds=5),
        store=case.dataset_case.store,
        lease_ttl=timedelta(minutes=30),
        lease_renew_interval=timedelta(minutes=5),
        clock=lambda: support.NOW,
    )
    for kind, variant in [
        ("business_report", "formal-business"),
        ("return_report", "formal-returns"),
    ]:
        duplicate = ingest.ingest(
            io.BytesIO(report(kind, variant)),
            ImportCommand(
                original_filename="fictional-repeat.csv",
                media_type="text/csv",
                created_by_user_id=actor,
                site_config_version_id=1,
                report_date=REPORT_DATE,
            ),
        )
        assert isinstance(duplicate, DuplicateBatchConflict)
    check()
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text("SELECT COUNT(*) FROM product_skus WHERE site_id=1")
            )
            == 2
        )
    engine.dispose()
