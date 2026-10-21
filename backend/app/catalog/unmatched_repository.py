"""Read-only discovery of Seller SKUs missing from the approved catalog."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from app.catalog.fact_tuples import ReturnFactProjection
from app.catalog.normalization import seller_sku_match_v1
from app.catalog.snapshots import MySqlCatalogSnapshotCoordinator
from app.catalog.source_refs import make_safe_source_ref
from app.catalog.types import CatalogSourceKind

ReturnBasis = Literal["report_date", "event_date"]


class CatalogUnmatchedRangeInvalid(ValueError):
    code = "catalog_unmatched_range_invalid"


def _in_range(value: date | None, from_date: date, to_date: date) -> bool:
    return value is not None and from_date <= value <= to_date


def _candidate_state(status: str) -> str:
    if status in {"approved", "rejected", "withdrawn"}:
        return "completed"
    if status in {"submitted", "validated", "ready_for_approval"}:
        return "in_review"
    return "draft"


class MySqlCatalogUnmatchedRepository:
    """Use the same current publication snapshot as catalog candidate generation."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_unmatched(
        self,
        *,
        site_id: int,
        from_date: date | None,
        to_date: date | None,
        return_basis: ReturnBasis,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        if (from_date is None) != (to_date is None):
            raise CatalogUnmatchedRangeInvalid()
        if (
            from_date is not None
            and to_date is not None
            and (to_date < from_date or (to_date - from_date).days >= 366)
        ):
            raise CatalogUnmatchedRangeInvalid()

        connection = self._engine.connect()
        try:
            connection.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
            )
            connection.exec_driver_sql(
                "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY"
            )
            frozen = MySqlCatalogSnapshotCoordinator(
                self._engine
            )._freeze_in_transaction(connection, site_id=site_id, fact_cutoff_at=None)
            # Historical datasets may remain after their publication is removed.
            # They must not extend the default current-facts display range.
            published_dates = [
                member.report_date
                for member in frozen.publication_snapshot.members
                if member.published_version_id is not None
            ]
            actual_from = from_date or min(
                published_dates,
                default=frozen.publication_snapshot.coverage_end_date,
            )
            actual_to = to_date or frozen.publication_snapshot.coverage_end_date
            if actual_to < actual_from or (actual_to - actual_from).days >= 366:
                raise CatalogUnmatchedRangeInvalid()

            version_ids: dict[str, list[int]] = {
                "business_report": [],
                "return_report": [],
            }
            publication_refs: list[dict[str, object]] = []
            for member in frozen.publication_snapshot.members:
                if member.published_version_id is None:
                    continue
                version_ids[member.report_type].append(member.published_version_id)
                if actual_from <= member.report_date <= actual_to:
                    publication_refs.append(
                        {
                            "report_type": member.report_type,
                            "report_date": member.report_date.isoformat(),
                            "published_version_id": str(member.published_version_id),
                            "pointer_revision": member.publication_pointer_revision,
                        }
                    )

            business = MySqlCatalogSnapshotCoordinator._business_rows(
                connection, version_ids["business_report"]
            )
            returns = MySqlCatalogSnapshotCoordinator._return_rows(
                connection, version_ids["return_report"]
            )
            unresolved_raw_digests = {
                item.seller_sku_ref.sha256
                for item in frozen.candidates.mappings
                if item.target_sku_id is None
            }

            groups: dict[bytes, dict[str, Any]] = {}
            for entries in business.values():
                for projection, observation in entries:
                    if observation is None or not _in_range(
                        observation.report_date, actual_from, actual_to
                    ):
                        continue
                    safe = make_safe_source_ref(
                        source_ref_id="unmatched_"
                        + hashlib.sha256(
                            observation.seller_sku.encode("utf-8")
                        ).hexdigest(),
                        raw_value=observation.seller_sku,
                        source_kind=CatalogSourceKind.SELLER_SKU,
                    )
                    if safe.sha256 not in unresolved_raw_digests:
                        continue
                    group = self._group(groups, observation.seller_sku, safe)
                    group["report_types"].add("business_report")
                    group["dates"].append(observation.report_date)
                    group["version_ids"].add(observation.published_version_id)
                    group["business_rows"] += 1
                    group["units"] += projection.units_ordered or 0
                    currency = projection.currency_code or "UNKNOWN"
                    group["sales"][currency] += Decimal(
                        projection.ordered_product_sales or "0"
                    )

            return_entries: list[tuple[ReturnFactProjection, Any]] = []
            for return_report_entries in returns.values():
                for return_projection, observation in return_report_entries:
                    if observation is None:
                        continue
                    basis_date = (
                        observation.event_date
                        if return_basis == "event_date"
                        else observation.report_date
                    )
                    if not _in_range(basis_date, actual_from, actual_to):
                        continue
                    safe = make_safe_source_ref(
                        source_ref_id="unmatched_"
                        + hashlib.sha256(
                            observation.seller_sku.encode("utf-8")
                        ).hexdigest(),
                        raw_value=observation.seller_sku,
                        source_kind=CatalogSourceKind.SELLER_SKU,
                    )
                    if safe.sha256 in unresolved_raw_digests:
                        return_entries.append((return_projection, observation))

            dedup = self._return_dedup_state(
                connection,
                snapshot_id=frozen.fact_tuple.return_dedup_snapshot_id,
                site_id=site_id,
                scope_id=frozen.fact_tuple.report_source_scope_id,
                source_key_ids=[
                    item.source_key_id for _projection, item in return_entries
                ],
            )
            for return_projection, observation in return_entries:
                decision, canonical = dedup.get(observation.source_key_id, (None, None))
                safe = make_safe_source_ref(
                    source_ref_id="unmatched_"
                    + hashlib.sha256(
                        observation.seller_sku.encode("utf-8")
                    ).hexdigest(),
                    raw_value=observation.seller_sku,
                    source_kind=CatalogSourceKind.SELLER_SKU,
                )
                group = self._group(groups, observation.seller_sku, safe)
                group["report_types"].add("return_report")
                group["dates"].append(observation.report_date)
                group["version_ids"].add(observation.published_version_id)
                group["return_rows"] += 1
                if decision == "unresolved":
                    group["unresolved_return_rows"] += 1
                elif (
                    decision in {None, "confirmed_distinct"}
                    or canonical == observation.source_key_id
                ):
                    group["return_quantity"] += return_projection.quantity or 0

            candidate_status = self._candidate_status(
                connection, site_id=site_id, groups=groups
            )
            ordered = sorted(
                groups.values(),
                key=lambda item: (
                    max(item["dates"], default=date.min),
                    item["match_bytes"],
                ),
                reverse=True,
            )
            total_items = len(ordered)
            visible = ordered[(page - 1) * page_size : page * page_size]
            items = [
                self._wire_item(
                    item,
                    candidate_status.get(item["match_bytes"]),
                    scope_id=frozen.fact_tuple.report_source_scope_id,
                )
                for item in visible
            ]
            impact_sales: defaultdict[str, Decimal] = defaultdict(Decimal)
            for item in ordered:
                for currency, value in item["sales"].items():
                    impact_sales[currency] += value
            result = {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "range": {
                    "from_date": actual_from.isoformat(),
                    "to_date": actual_to.isoformat(),
                    "return_basis": return_basis,
                },
                "baseline": {
                    "catalog_version_id": frozen.base_catalog_version_id,
                    "catalog_publication_revision": frozen.catalog_publication_revision,
                    "fact_basis": "current",
                    "consistent_as_of": frozen.publication_snapshot.transaction_started_at.isoformat(),
                    "publication_refs": publication_refs,
                },
                "impact": {
                    "business_fact_rows": sum(
                        item["business_rows"] for item in ordered
                    ),
                    "units": sum(item["units"] for item in ordered),
                    "sales_by_currency": self._money(impact_sales),
                    "return_fact_rows": sum(item["return_rows"] for item in ordered),
                    "return_quantity": sum(item["return_quantity"] for item in ordered),
                    "unresolved_return_rows": sum(
                        item["unresolved_return_rows"] for item in ordered
                    ),
                },
                "items": items,
            }
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _group(
        groups: dict[bytes, dict[str, Any]], raw: str, safe: Any
    ) -> dict[str, Any]:
        match = seller_sku_match_v1(raw)
        group = groups.get(match.utf8)
        if group is None:
            group = {
                "match_bytes": match.utf8,
                "match_sha256": match.sha256,
                "safe": safe,
                "report_types": set(),
                "dates": [],
                "version_ids": set(),
                "business_rows": 0,
                "units": 0,
                "sales": defaultdict(Decimal),
                "return_rows": 0,
                "return_quantity": 0,
                "unresolved_return_rows": 0,
            }
            groups[match.utf8] = group
        return group

    @staticmethod
    def _money(values: dict[str, Decimal]) -> list[dict[str, str]]:
        return [
            {"currency_code": currency, "value": format(value, ".2f")}
            for currency, value in sorted(values.items())
        ]

    @classmethod
    def _wire_item(
        cls,
        item: dict[str, Any],
        candidate: dict[str, object] | None,
        *,
        scope_id: int,
    ) -> dict[str, object]:
        dates = item["dates"]
        safe = item["safe"]
        return {
            "source_identity": {
                "report_source_scope_id": scope_id,
                "seller_sku_sha256": "sha256:" + item["match_sha256"].hex(),
                "seller_sku_match": "match_" + item["match_sha256"].hex(),
            },
            "source_ref_id": None,
            "preview": safe.preview,
            "digest": safe.sha256,
            "is_unsafe": safe.is_unsafe,
            "is_truncated": safe.is_truncated,
            "report_types": sorted(item["report_types"]),
            "first_seen_date": min(dates).isoformat(),
            "latest_seen_date": max(dates).isoformat(),
            "published_version_ids": [
                str(value) for value in sorted(item["version_ids"])
            ],
            "business": {
                "rows": item["business_rows"],
                "units": item["units"],
                "sales_by_currency": cls._money(item["sales"]),
            },
            "returns": {
                "rows": item["return_rows"],
                "quantity": item["return_quantity"],
                "unresolved_rows": item["unresolved_return_rows"],
            },
            "candidate": candidate or {"status": "not_started", "review_path": None},
        }

    @staticmethod
    def _return_dedup_state(
        connection: Connection,
        *,
        snapshot_id: int,
        site_id: int,
        scope_id: int,
        source_key_ids: list[int],
    ) -> dict[int, tuple[str | None, int | None]]:
        if not source_key_ids:
            return {}
        rows = (
            connection.execute(
                sa.text(
                    """
                WITH RECURSIVE snapshot_chain AS (
                  SELECT id, base_snapshot_id, 0 AS chain_rank FROM return_dedup_snapshots
                  WHERE id=:snapshot_id AND site_id=:site_id AND report_source_scope_id=:scope_id AND status='ready'
                  UNION ALL
                  SELECT prior.id, prior.base_snapshot_id, chain.chain_rank + 1
                  FROM snapshot_chain AS chain INNER JOIN return_dedup_snapshots AS prior ON prior.id=chain.base_snapshot_id
                  WHERE chain.chain_rank < 32
                ), ranked AS (
                  SELECT members.source_key_id, revisions.decision, revisions.canonical_source_key_id,
                    ROW_NUMBER() OVER (PARTITION BY members.source_key_id ORDER BY chain.chain_rank, entries.id DESC) AS entry_rank,
                    entries.entry_kind
                  FROM snapshot_chain AS chain
                  INNER JOIN return_dedup_snapshot_groups AS entries ON entries.snapshot_id=chain.id
                  INNER JOIN return_dedup_group_revisions AS revisions ON revisions.id=entries.group_revision_id
                  INNER JOIN return_dedup_group_members AS members ON members.group_revision_id=revisions.id
                  WHERE members.source_key_id IN :source_key_ids
                )
                SELECT source_key_id, decision, canonical_source_key_id FROM ranked
                WHERE entry_rank=1 AND entry_kind <> 'remove'
                """
                ).bindparams(sa.bindparam("source_key_ids", expanding=True)),
                {
                    "snapshot_id": snapshot_id,
                    "site_id": site_id,
                    "scope_id": scope_id,
                    "source_key_ids": source_key_ids,
                },
            )
            .mappings()
            .all()
        )
        return {
            int(row["source_key_id"]): (
                None if row["decision"] is None else str(row["decision"]),
                None
                if row["canonical_source_key_id"] is None
                else int(row["canonical_source_key_id"]),
            )
            for row in rows
        }

    @staticmethod
    def _candidate_status(
        connection: Connection, *, site_id: int, groups: dict[bytes, dict[str, Any]]
    ) -> dict[bytes, dict[str, object]]:
        if not groups:
            return {}
        rows = (
            connection.execute(
                sa.text(
                    """
                SELECT source_keys.seller_sku_match_bytes, imports.id, imports.status, imports.updated_at,
                       ROW_NUMBER() OVER (PARTITION BY source_keys.seller_sku_match_bytes ORDER BY imports.updated_at DESC, imports.id DESC) AS item_rank
                FROM catalog_source_evidence AS evidence
                INNER JOIN report_source_keys AS source_keys ON source_keys.id=evidence.source_key_id
                INNER JOIN catalog_source_refs AS refs ON refs.id=evidence.seller_sku_ref_id AND refs.resource_kind='export'
                INNER JOIN catalog_imports AS imports ON imports.export_id=refs.resource_id AND imports.site_id=:site_id
                WHERE evidence.site_id=:site_id AND source_keys.seller_sku_match_bytes IN :match_bytes
                """
                ).bindparams(sa.bindparam("match_bytes", expanding=True)),
                {"site_id": site_id, "match_bytes": list(groups)},
            )
            .mappings()
            .all()
        )
        return {
            bytes(row["seller_sku_match_bytes"]): {
                "status": _candidate_state(str(row["status"])),
                "workflow_status": str(row["status"]),
                "review_path": f"/catalog/imports/{int(row['id'])}",
            }
            for row in rows
            if int(row["item_rank"]) == 1
        }


__all__ = ("CatalogUnmatchedRangeInvalid", "MySqlCatalogUnmatchedRepository")
