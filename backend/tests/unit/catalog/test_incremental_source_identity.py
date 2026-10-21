# ruff: noqa: E501
"""Repeated exports must resolve immutable evidence retained by an earlier export."""

import hashlib
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
import sqlalchemy as sa
from app.catalog.approval import _source_decision_key as approval_key
from app.catalog.evidence import aggregate_source_evidence
from app.catalog.import_repository import _source_decision_key as draft_key
from app.catalog.snapshots import (
    FrozenCatalogExportPayload,
    MySqlCatalogSnapshotWriter,
)
from tests.unit.catalog.test_candidates import _observation

type Resolver = Callable[..., tuple[int, bytes, bytes]]


def test_repeated_export_creates_own_refs_without_duplicating_observation() -> None:
    observation = _observation("100-NAVY-L", source_key_id=1)
    evidence = aggregate_source_evidence((observation,))
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE catalog_source_evidence (id INTEGER PRIMARY KEY, source_key_id INTEGER, dataset_id INTEGER, published_version_id INTEGER, source_row_id INTEGER)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE catalog_source_refs (id INTEGER PRIMARY KEY, site_id INTEGER, resource_kind TEXT, resource_id INTEGER, source_kind TEXT, raw_value TEXT, raw_sha256 BLOB, safe_preview TEXT, is_unsafe INTEGER, is_truncated INTEGER)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO catalog_source_evidence VALUES (1, :key, :dataset, :version, :row)"
            ),
            {
                "key": observation.source_key_id,
                "dataset": observation.dataset_id,
                "version": observation.published_version_id,
                "row": observation.source_row_id,
            },
        )
        payload = cast(
            FrozenCatalogExportPayload,
            SimpleNamespace(evidence=evidence, site_id=1),
        )
        for export_id in (10, 20):
            MySqlCatalogSnapshotWriter._persist_evidence(
                connection, payload=payload, export_id=export_id
            )
        assert (
            connection.scalar(sa.text("SELECT COUNT(*) FROM catalog_source_evidence"))
            == 1
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM catalog_source_refs WHERE resource_id=20 AND source_kind='seller_sku'"
                )
            )
            == 1
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM catalog_source_refs WHERE resource_id=10 AND source_kind='seller_sku'"
                )
            )
            == 1
        )
    engine.dispose()


@pytest.mark.parametrize("resolve", [draft_key, approval_key])
def test_new_export_ref_resolves_deduplicated_evidence_with_site_boundary(
    resolve: Resolver,
) -> None:
    engine = sa.create_engine("sqlite://")
    raw_digest = hashlib.sha256(b"100-NAVY-L").digest()
    match_digest = raw_digest
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE catalog_exports (id INTEGER, site_id INTEGER, fact_snapshot_tuple_id INTEGER)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE fact_snapshot_tuples (id INTEGER, publication_snapshot_id INTEGER)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE publication_snapshots (id INTEGER, report_source_scope_id INTEGER)"
            )
        )
        connection.execute(sa.text("INSERT INTO catalog_exports VALUES (20, 1, 1)"))
        connection.execute(sa.text("INSERT INTO fact_snapshot_tuples VALUES (1, 1)"))
        connection.execute(sa.text("INSERT INTO publication_snapshots VALUES (1, 3)"))
        connection.execute(
            sa.text(
                "CREATE TABLE catalog_source_refs (id INTEGER, site_id INTEGER, resource_kind TEXT, resource_id INTEGER, source_kind TEXT, raw_sha256 BLOB)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE catalog_source_evidence (seller_sku_ref_id INTEGER, site_id INTEGER, source_key_id INTEGER, report_source_scope_id INTEGER)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE report_source_keys (id INTEGER, site_id INTEGER, report_source_scope_id INTEGER, seller_sku_match_sha256 BLOB, seller_sku_match_bytes BLOB)"
            )
        )
        for ref_id, export_id in ((1, 10), (2, 20)):
            connection.execute(
                sa.text(
                    "INSERT INTO catalog_source_refs VALUES (:id, 1, 'export', :export, 'seller_sku', :digest)"
                ),
                {"id": ref_id, "export": export_id, "digest": raw_digest},
            )
        connection.execute(
            sa.text("INSERT INTO catalog_source_evidence VALUES (1, 1, 4, 3)")
        )
        connection.execute(
            sa.text("INSERT INTO report_source_keys VALUES (4, 1, 3, :digest, :value)"),
            {"digest": match_digest, "value": b"100-NAVY-L"},
        )
        # Identical text in another account must not enter this export's key.
        connection.execute(
            sa.text("INSERT INTO catalog_source_evidence VALUES (1, 1, 5, 9)")
        )
        connection.execute(
            sa.text("INSERT INTO report_source_keys VALUES (5, 1, 9, :digest, :value)"),
            {"digest": match_digest, "value": b"100-NAVY-L"},
        )
        assert resolve(
            connection,
            site_id=1,
            export_id=20,
            raw_sha256_ref="sha256:" + raw_digest.hex(),
        ) == (3, match_digest, b"100-NAVY-L")
        with pytest.raises(RuntimeError):
            resolve(
                connection,
                site_id=2,
                export_id=20,
                raw_sha256_ref="sha256:" + raw_digest.hex(),
            )
        with pytest.raises(RuntimeError):
            resolve(
                connection,
                site_id=1,
                export_id=30,
                raw_sha256_ref="sha256:" + raw_digest.hex(),
            )
    engine.dispose()
