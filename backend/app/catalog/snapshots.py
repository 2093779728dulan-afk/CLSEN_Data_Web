"""MySQL RR coordinator and exact-payload persistence for catalog exports."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Final, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import IntegrityError

from app.catalog.candidates import (
    CatalogCandidatePayload,
    ExistingCatalogDecision,
    build_catalog_candidates,
)
from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.evidence import (
    EvidenceObservation,
    SourceEvidencePayload,
    aggregate_source_evidence,
)
from app.catalog.fact_tuples import (
    NORMALIZATION_MANIFEST_ID,
    BusinessFactProjection,
    FactSnapshotTuplePayload,
    PublicationSnapshotPayload,
    PublishedFactMember,
    ReturnFactProjection,
    build_fact_snapshot_tuple,
    build_publication_snapshot,
)
from app.catalog.return_dedup_repository import (
    FrozenPublicationMember,
    publication_set_digest,
)

WORKBOOK_SCHEMA_VERSION: Final = "product_catalog_workbook_v2"


class CatalogSnapshotError(RuntimeError):
    code = "catalog_snapshot_integrity_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class CatalogSnapshotUnavailable(CatalogSnapshotError):
    code = "catalog_snapshot_unavailable"


class CatalogExportIdempotencyConflict(CatalogSnapshotError):
    code = "idempotency_key_reused"


@dataclass(frozen=True, slots=True)
class FrozenCatalogExportPayload:
    site_id: int
    base_catalog_version_id: int | None
    catalog_publication_revision: int
    dedup_publication_revision: int
    publication_snapshot: PublicationSnapshotPayload
    fact_tuple: FactSnapshotTuplePayload
    observations: tuple[EvidenceObservation, ...]
    candidates: CatalogCandidatePayload
    evidence: SourceEvidencePayload
    payload_digest: bytes


@dataclass(frozen=True, slots=True)
class BuildingCatalogExport:
    export_id: int
    publication_snapshot_id: int
    fact_snapshot_tuple_id: int
    export_status: str
    workbook_status: None
    payload_digest: bytes


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CatalogSnapshotError()
    return value


def _nonnegative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CatalogSnapshotError()
    return value


def _bytes(value: object, *, length: int = 32) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise CatalogSnapshotError()
    result = bytes(value)
    if len(result) != length:
        raise CatalogSnapshotError()
    return result


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise CatalogSnapshotError()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if value.utcoffset() is None:
        raise CatalogSnapshotError()
    return value.astimezone(UTC)


def _mysql_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("database timestamp must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _integer(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CatalogSnapshotError()
    return value


def _decimal(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (Decimal, int, str)):
        raise CatalogSnapshotError()
    return str(value)


def _event_timestamp(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise CatalogSnapshotError()
    if value.tzinfo is None:
        return value.strftime("%Y-%m-%dT%H:%M:%S.%f")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _source_locator(*, dataset_id: int, version_id: int, source_row_id: int) -> str:
    return f"dataset:{dataset_id}:version:{version_id}:row:{source_row_id}"


def _candidate_payload_json(payload: CatalogCandidatePayload) -> dict[str, Any]:
    def ref(value: Any) -> dict[str, Any]:
        return cast(dict[str, Any], value.model_dump(mode="json"))

    return {
        "styles": [
            {
                "row_key": row.row_key,
                "style_code": row.style_code,
                "standard_name": row.standard_name,
                "candidate_seller_sku_count": row.candidate_seller_sku_count,
                "source_title_count": row.source_title_count,
            }
            for row in payload.styles
        ],
        "variants": [
            {
                "row_key": row.row_key,
                "style_row_key": row.style_row_key,
                "style_code": row.style_code,
                "source_color": row.source_color,
                "source_size": row.source_size,
                "observed_seller_sku_count": row.observed_seller_sku_count,
            }
            for row in payload.variants
        ],
        "mappings": [
            {
                "row_key": row.row_key,
                "seller_sku": ref(row.seller_sku_ref),
                "report_types": list(row.report_types),
                "candidate_variant_row_key": row.candidate_variant_row_key,
                "target_sku_id": row.target_sku_id,
            }
            for row in payload.mappings
        ],
        "exclusions": [
            {
                "row_key": row.row_key,
                "seller_sku": ref(row.seller_sku_ref),
                "exclusion_reason": row.exclusion_reason,
            }
            for row in payload.exclusions
        ],
        "exceptions": [
            {
                "row_key": row.row_key,
                "decision_group_key": row.decision_group_key,
                "reason_code": row.reason_code,
                "seller_sku": ref(row.seller_sku_ref),
                "source_report": row.source_report,
                "candidate_style_code": row.candidate_style_code,
                "candidate_color": row.candidate_color,
                "candidate_size": row.candidate_size,
            }
            for row in payload.exceptions
        ],
    }


def _evidence_payload_json(payload: SourceEvidencePayload) -> dict[str, Any]:
    # Row-level observations are already persisted in catalog_source_evidence
    # with immutable dataset/version/source-row locators. Duplicating them in a
    # single JSON document made payload size grow with order volume even though
    # workbook generation consumes only the per-Seller-SKU summaries.
    summaries = [
        {
            "report_source_scope_id": row.report_source_scope_id,
            "report_type": row.report_type,
            "source_report_count": len(row.source_key_ids),
            "seller_sku": row.seller_sku_ref.model_dump(mode="json"),
            "first_seen_date": row.first_seen_date.isoformat(),
            "latest_seen_date": row.latest_seen_date.isoformat(),
            "occurrence_count": row.occurrence_count,
            "title_distinct_count": row.title_distinct_count,
            "parent_asin_distinct_count": row.parent_asin_distinct_count,
            "child_asin_distinct_count": row.child_asin_distinct_count,
            "fnsku_distinct_count": row.fnsku_distinct_count,
            "latest_title": (
                None
                if row.latest_title is None
                else row.latest_title.model_dump(mode="json")
            ),
            "evidence_set_digest": row.evidence_set_digest,
        }
        for row in payload.summaries
    ]
    return {"summaries": summaries}


def _combined_payload_digest(
    *,
    fact_tuple: FactSnapshotTuplePayload,
    candidates: CatalogCandidatePayload,
    evidence: SourceEvidencePayload,
) -> bytes:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "fact_tuple_digest": fact_tuple.tuple_digest.hex(),
                "candidate_payload_digest": candidates.payload_digest.hex(),
                "evidence_payload_digest": evidence.payload_digest.hex(),
            }
        )
    ).digest()


class MySqlCatalogSnapshotCoordinator:
    """Freeze all current inputs in one read-only repeatable-read transaction."""

    def __init__(
        self,
        engine: Engine,
        *,
        after_pointer_read: Callable[[], None] | None = None,
    ) -> None:
        self._engine = engine
        self._after_pointer_read = after_pointer_read

    def freeze(
        self,
        *,
        site_id: int,
        fact_cutoff_at: datetime | None = None,
    ) -> FrozenCatalogExportPayload:
        _positive(site_id)
        connection = self._engine.connect()
        try:
            connection.exec_driver_sql(
                "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY"
            )
            try:
                payload = self._freeze_in_transaction(
                    connection,
                    site_id=site_id,
                    fact_cutoff_at=fact_cutoff_at,
                )
                connection.commit()
                return payload
            except BaseException:
                connection.rollback()
                raise
        finally:
            connection.close()

    def _freeze_in_transaction(
        self,
        connection: Connection,
        *,
        site_id: int,
        fact_cutoff_at: datetime | None,
    ) -> FrozenCatalogExportPayload:
        transaction_started_at = _utc(
            connection.scalar(sa.text("SELECT UTC_TIMESTAMP(6)"))
        )
        cutoff = transaction_started_at if fact_cutoff_at is None else fact_cutoff_at
        cutoff = _utc(cutoff)
        if cutoff < transaction_started_at:
            raise CatalogSnapshotUnavailable()
        header_rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT scopes.id AS scope_id,
                           configs.id AS site_config_version_id,
                           configs.reporting_timezone
                    FROM sites AS sites
                    INNER JOIN site_current_configs AS current_configs
                        ON current_configs.site_id = sites.id
                    INNER JOIN site_config_versions AS configs
                        ON configs.id = current_configs.current_config_version_id
                       AND configs.site_id = sites.id
                    INNER JOIN report_source_scopes AS scopes
                        ON scopes.site_id = sites.id
                    WHERE sites.id = :site_id AND sites.status = 'active'
                    """
                ),
                {"site_id": site_id},
            )
            .mappings()
            .all()
        )
        if len(header_rows) != 1:
            raise CatalogSnapshotUnavailable()
        header = header_rows[0]
        scope_id = _positive(header["scope_id"])
        site_config_version_id = _positive(header["site_config_version_id"])
        try:
            reporting_zone = ZoneInfo(str(header["reporting_timezone"]))
        except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
            raise CatalogSnapshotError() from error
        coverage_end = cutoff.astimezone(reporting_zone).date()
        earliest = connection.scalar(
            sa.text(
                """
                SELECT MIN(datasets.report_date)
                FROM report_dataset_scope_assignments AS assignments
                INNER JOIN daily_datasets AS datasets
                    ON datasets.id = assignments.dataset_id
                   AND datasets.site_id = assignments.site_id
                WHERE assignments.site_id = :site_id
                  AND assignments.report_source_scope_id = :scope_id
                  AND datasets.report_date <= :coverage_end
                """
            ),
            {
                "site_id": site_id,
                "scope_id": scope_id,
                "coverage_end": coverage_end,
            },
        )
        coverage_start = earliest if isinstance(earliest, date) else coverage_end

        catalog_row = (
            connection.execute(
                sa.text(
                    """
                    SELECT current_catalog_version_id, catalog_publication_revision
                    FROM product_catalog_publications
                    WHERE site_id = :site_id
                    """
                ),
                {"site_id": site_id},
            )
            .mappings()
            .one_or_none()
        )
        base_catalog_version_id = (
            None
            if catalog_row is None or catalog_row["current_catalog_version_id"] is None
            else _positive(catalog_row["current_catalog_version_id"])
        )
        catalog_revision = (
            0
            if catalog_row is None
            else _nonnegative(catalog_row["catalog_publication_revision"])
        )
        pointer_rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT datasets.id AS dataset_id, datasets.report_type,
                           datasets.report_date, publications.version_id,
                           revisions.publication_revision,
                           versions.data_revision
                    FROM report_dataset_scope_assignments AS assignments
                    INNER JOIN daily_datasets AS datasets
                        ON datasets.id = assignments.dataset_id
                       AND datasets.site_id = assignments.site_id
                    INNER JOIN report_publication_revisions AS revisions
                        ON revisions.dataset_id = assignments.dataset_id
                       AND revisions.site_id = assignments.site_id
                       AND revisions.report_source_scope_id =
                           assignments.report_source_scope_id
                    LEFT JOIN dataset_publications AS publications
                        ON publications.dataset_id = datasets.id
                    LEFT JOIN dataset_versions AS versions
                        ON versions.id = publications.version_id
                       AND versions.dataset_id = datasets.id
                       AND versions.report_type = datasets.report_type
                       AND versions.status = 'published'
                    WHERE assignments.site_id = :site_id
                      AND assignments.report_source_scope_id = :scope_id
                      AND datasets.report_date BETWEEN :coverage_start
                                                   AND :coverage_end
                    ORDER BY datasets.report_date, datasets.report_type
                    """
                ),
                {
                    "site_id": site_id,
                    "scope_id": scope_id,
                    "coverage_start": coverage_start,
                    "coverage_end": coverage_end,
                },
            )
            .mappings()
            .all()
        )
        dedup_row = (
            connection.execute(
                sa.text(
                    """
                    SELECT pointers.current_snapshot_id,
                           pointers.dedup_publication_revision,
                           snapshots.return_publication_set_digest,
                           snapshots.decision_digest, snapshots.status
                    FROM return_dedup_publications AS pointers
                    LEFT JOIN return_dedup_snapshots AS snapshots
                        ON snapshots.id = pointers.current_snapshot_id
                       AND snapshots.site_id = pointers.site_id
                       AND snapshots.report_source_scope_id =
                           pointers.report_source_scope_id
                    WHERE pointers.site_id = :site_id
                      AND pointers.report_source_scope_id = :scope_id
                    """
                ),
                {"site_id": site_id, "scope_id": scope_id},
            )
            .mappings()
            .one_or_none()
        )
        if (
            dedup_row is None
            or dedup_row["current_snapshot_id"] is None
            or dedup_row["status"] != "ready"
        ):
            raise CatalogSnapshotUnavailable()
        dedup_snapshot_id = _positive(dedup_row["current_snapshot_id"])
        dedup_revision = _nonnegative(dedup_row["dedup_publication_revision"])
        frozen_return_digest = _bytes(dedup_row["return_publication_set_digest"])
        decision_digest = _bytes(dedup_row["decision_digest"])

        if self._after_pointer_read is not None:
            self._after_pointer_read()

        version_ids_by_type: dict[str, list[int]] = {
            "business_report": [],
            "return_report": [],
        }
        for row in pointer_rows:
            if row["version_id"] is not None:
                report_type = str(row["report_type"])
                if (
                    report_type not in version_ids_by_type
                    or row["data_revision"] is None
                ):
                    raise CatalogSnapshotError()
                version_ids_by_type[report_type].append(_positive(row["version_id"]))
        business_rows = self._business_rows(
            connection, version_ids_by_type["business_report"]
        )
        return_rows = self._return_rows(
            connection, version_ids_by_type["return_report"]
        )
        projections: dict[int, tuple[Any, ...]] = {}
        observations: list[EvidenceObservation] = []
        for version_id, business_entries in business_rows.items():
            projections[version_id] = tuple(row[0] for row in business_entries)
            observations.extend(
                row[1] for row in business_entries if row[1] is not None
            )
        for version_id, return_entries in return_rows.items():
            projections[version_id] = tuple(row[0] for row in return_entries)
            observations.extend(row[1] for row in return_entries if row[1] is not None)

        published: list[PublishedFactMember] = []
        missing_revisions: dict[tuple[date, Any], int] = {}
        return_members: list[FrozenPublicationMember] = []
        for row in pointer_rows:
            report_type = str(row["report_type"])
            report_date = row["report_date"]
            if report_type not in {
                "business_report",
                "return_report",
            } or not isinstance(report_date, date):
                raise CatalogSnapshotError()
            revision = _nonnegative(row["publication_revision"])
            version_value = row["version_id"]
            if version_value is None:
                missing_revisions[(report_date, report_type)] = revision
                continue
            version_id = _positive(version_value)
            data_revision = _nonnegative(row["data_revision"])
            member = PublishedFactMember(
                report_type=cast(Any, report_type),
                report_date=report_date,
                dataset_id=_positive(row["dataset_id"]),
                published_version_id=version_id,
                publication_pointer_revision=revision,
                version_data_revision=data_revision,
                active_rows=projections.get(version_id, ()),
            )
            published.append(member)
            if report_type == "return_report":
                return_members.append(
                    FrozenPublicationMember(
                        dataset_id=member.dataset_id,
                        published_version_id=member.published_version_id,
                        publication_revision=member.publication_pointer_revision,
                        version_data_revision=member.version_data_revision,
                        report_date=member.report_date,
                    )
                )
        if publication_set_digest(tuple(return_members)) != frozen_return_digest:
            raise CatalogSnapshotUnavailable()

        publication_snapshot = build_publication_snapshot(
            site_id=site_id,
            report_source_scope_id=scope_id,
            site_config_version_id=site_config_version_id,
            coverage_start_date=coverage_start,
            coverage_end_date=coverage_end,
            transaction_started_at=transaction_started_at,
            fact_cutoff_at=cutoff,
            return_publication_set_digest=frozen_return_digest,
            published_members=tuple(published),
            missing_pointer_revisions=cast(Any, missing_revisions),
        )
        fact_tuple = build_fact_snapshot_tuple(
            publication_snapshot=publication_snapshot,
            return_dedup_snapshot_id=dedup_snapshot_id,
            return_dedup_decision_digest=decision_digest,
        )
        existing = self._existing_decisions(
            connection, base_catalog_version_id=base_catalog_version_id
        )
        ordered_observations = tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.report_date,
                    item.report_type,
                    item.dataset_id,
                    item.published_version_id,
                    item.source_row_id,
                ),
            )
        )
        evidence = aggregate_source_evidence(ordered_observations)
        candidates = build_catalog_candidates(
            ordered_observations,
            existing_decisions=existing,
        )
        return FrozenCatalogExportPayload(
            site_id=site_id,
            base_catalog_version_id=base_catalog_version_id,
            catalog_publication_revision=catalog_revision,
            dedup_publication_revision=dedup_revision,
            publication_snapshot=publication_snapshot,
            fact_tuple=fact_tuple,
            observations=ordered_observations,
            candidates=candidates,
            evidence=evidence,
            payload_digest=_combined_payload_digest(
                fact_tuple=fact_tuple,
                candidates=candidates,
                evidence=evidence,
            ),
        )

    @staticmethod
    def _business_rows(
        connection: Connection, version_ids: list[int]
    ) -> dict[int, list[tuple[BusinessFactProjection, EvidenceObservation | None]]]:
        if not version_ids:
            return {}
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT report_rows.version_id, report_rows.version_row_id,
                           report_rows.parent_asin, report_rows.child_asin,
                           report_rows.title, report_rows.sku,
                           report_rows.sessions_total, report_rows.sessions_b2b,
                           report_rows.conversion_rate_total,
                           report_rows.session_percentage_b2b,
                           report_rows.page_views_total, report_rows.page_views_b2b,
                           report_rows.page_view_percentage_total,
                           report_rows.page_view_percentage_b2b,
                           report_rows.featured_offer_percentage,
                           report_rows.featured_offer_percentage_b2b,
                           report_rows.units_ordered,
                           report_rows.units_ordered_b2b,
                           report_rows.unit_session_percentage,
                           report_rows.unit_session_percentage_b2b,
                           report_rows.ordered_product_sales,
                           report_rows.ordered_product_sales_b2b,
                           report_rows.currency_code,
                           report_rows.total_order_items,
                           report_rows.total_order_items_b2b,
                           datasets.id AS dataset_id, datasets.report_date,
                           source_keys.id AS source_key_id,
                           assignments.report_source_scope_id
                    FROM version_rows AS version_rows
                    INNER JOIN business_report_rows AS report_rows
                        ON report_rows.version_row_id = version_rows.id
                       AND report_rows.version_id = version_rows.version_id
                    INNER JOIN dataset_versions AS versions
                        ON versions.id = version_rows.version_id
                    INNER JOIN daily_datasets AS datasets
                        ON datasets.id = versions.dataset_id
                    INNER JOIN report_dataset_scope_assignments AS assignments
                        ON assignments.dataset_id = datasets.id
                    LEFT JOIN report_source_keys AS source_keys
                        ON source_keys.version_id = version_rows.version_id
                       AND source_keys.source_row_id = version_rows.id
                       AND source_keys.source_key_revision = 0
                    WHERE version_rows.row_state = 'active'
                      AND version_rows.version_id IN :version_ids
                    ORDER BY version_rows.version_id, version_rows.id
                    """
                ).bindparams(sa.bindparam("version_ids", expanding=True)),
                {"version_ids": version_ids},
            )
            .mappings()
            .all()
        )
        result: dict[
            int, list[tuple[BusinessFactProjection, EvidenceObservation | None]]
        ] = {}
        for row in rows:
            projection = BusinessFactProjection(
                source_row_id=_positive(row["version_row_id"]),
                seller_sku=_text(row["sku"]),
                parent_asin=_text(row["parent_asin"]),
                child_asin=_text(row["child_asin"]),
                title=_text(row["title"]),
                sessions_total=_integer(row["sessions_total"]),
                sessions_b2b=_integer(row["sessions_b2b"]),
                conversion_rate_total=_decimal(row["conversion_rate_total"]),
                session_percentage_b2b=_decimal(row["session_percentage_b2b"]),
                page_views_total=_integer(row["page_views_total"]),
                page_views_b2b=_integer(row["page_views_b2b"]),
                page_view_percentage_total=_decimal(row["page_view_percentage_total"]),
                page_view_percentage_b2b=_decimal(row["page_view_percentage_b2b"]),
                featured_offer_percentage=_decimal(row["featured_offer_percentage"]),
                featured_offer_percentage_b2b=_decimal(
                    row["featured_offer_percentage_b2b"]
                ),
                units_ordered=_integer(row["units_ordered"]),
                units_ordered_b2b=_integer(row["units_ordered_b2b"]),
                unit_session_percentage=_decimal(row["unit_session_percentage"]),
                unit_session_percentage_b2b=_decimal(
                    row["unit_session_percentage_b2b"]
                ),
                ordered_product_sales=_decimal(row["ordered_product_sales"]),
                ordered_product_sales_b2b=_decimal(row["ordered_product_sales_b2b"]),
                currency_code=_text(row["currency_code"]),
                total_order_items=_integer(row["total_order_items"]),
                total_order_items_b2b=_integer(row["total_order_items_b2b"]),
            )
            observation = MySqlCatalogSnapshotCoordinator._observation(
                row,
                report_type="business_report",
                seller_sku=projection.seller_sku,
                title=projection.title,
                parent_asin=projection.parent_asin,
                child_asin=projection.child_asin,
                fnsku=None,
                event_date=None,
            )
            result.setdefault(_positive(row["version_id"]), []).append(
                (projection, observation)
            )
        return result

    @staticmethod
    def _return_rows(
        connection: Connection, version_ids: list[int]
    ) -> dict[int, list[tuple[ReturnFactProjection, EvidenceObservation | None]]]:
        if not version_ids:
            return {}
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT report_rows.version_id, report_rows.version_row_id,
                           report_rows.return_date, report_rows.sku,
                           report_rows.asin, report_rows.fnsku,
                           report_rows.product_name, report_rows.quantity,
                           datasets.id AS dataset_id, datasets.report_date,
                           source_keys.id AS source_key_id,
                           assignments.report_source_scope_id
                    FROM version_rows AS version_rows
                    INNER JOIN return_report_rows AS report_rows
                        ON report_rows.version_row_id = version_rows.id
                       AND report_rows.version_id = version_rows.version_id
                    INNER JOIN dataset_versions AS versions
                        ON versions.id = version_rows.version_id
                    INNER JOIN daily_datasets AS datasets
                        ON datasets.id = versions.dataset_id
                    INNER JOIN report_dataset_scope_assignments AS assignments
                        ON assignments.dataset_id = datasets.id
                    LEFT JOIN report_source_keys AS source_keys
                        ON source_keys.version_id = version_rows.version_id
                       AND source_keys.source_row_id = version_rows.id
                       AND source_keys.source_key_revision = 0
                    WHERE version_rows.row_state = 'active'
                      AND version_rows.version_id IN :version_ids
                    ORDER BY version_rows.version_id, version_rows.id
                    """
                ).bindparams(sa.bindparam("version_ids", expanding=True)),
                {"version_ids": version_ids},
            )
            .mappings()
            .all()
        )
        result: dict[
            int, list[tuple[ReturnFactProjection, EvidenceObservation | None]]
        ] = {}
        for row in rows:
            projection = ReturnFactProjection(
                source_row_id=_positive(row["version_row_id"]),
                event_date=_event_timestamp(row["return_date"]),
                seller_sku=_text(row["sku"]),
                asin=_text(row["asin"]),
                fnsku=_text(row["fnsku"]),
                title=_text(row["product_name"]),
                quantity=_integer(row["quantity"]),
            )
            event_value = row["return_date"]
            event_date = (
                event_value.date() if isinstance(event_value, datetime) else None
            )
            observation = MySqlCatalogSnapshotCoordinator._observation(
                row,
                report_type="return_report",
                seller_sku=projection.seller_sku,
                title=projection.title,
                parent_asin=None,
                child_asin=projection.asin,
                fnsku=projection.fnsku,
                event_date=event_date,
            )
            result.setdefault(_positive(row["version_id"]), []).append(
                (projection, observation)
            )
        return result

    @staticmethod
    def _observation(
        row: RowMapping,
        *,
        report_type: str,
        seller_sku: str | None,
        title: str | None,
        parent_asin: str | None,
        child_asin: str | None,
        fnsku: str | None,
        event_date: date | None,
    ) -> EvidenceObservation | None:
        if seller_sku is None:
            if row["source_key_id"] is not None:
                raise CatalogSnapshotError()
            return None
        if row["source_key_id"] is None:
            raise CatalogSnapshotError()
        dataset_id = _positive(row["dataset_id"])
        version_id = _positive(row["version_id"])
        source_row_id = _positive(row["version_row_id"])
        return EvidenceObservation(
            report_source_scope_id=_positive(row["report_source_scope_id"]),
            source_key_id=_positive(row["source_key_id"]),
            report_type=cast(Any, report_type),
            report_date=cast(date, row["report_date"]),
            event_date=event_date,
            dataset_id=dataset_id,
            published_version_id=version_id,
            source_row_id=source_row_id,
            seller_sku=seller_sku,
            title=title,
            parent_asin=parent_asin,
            child_asin=child_asin,
            fnsku=fnsku,
            source_locator=_source_locator(
                dataset_id=dataset_id,
                version_id=version_id,
                source_row_id=source_row_id,
            ),
        )

    @staticmethod
    def _existing_decisions(
        connection: Connection, *, base_catalog_version_id: int | None
    ) -> tuple[ExistingCatalogDecision, ...]:
        if base_catalog_version_id is None:
            return ()
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT seller_sku_match_bytes, 'mapped' AS action,
                           sku_id AS target_sku_id, NULL AS exclusion_reason
                    FROM product_catalog_mappings
                    WHERE catalog_version_id = :catalog_version_id
                    UNION ALL
                    SELECT seller_sku_match_bytes, 'excluded' AS action,
                           NULL AS target_sku_id, reason AS exclusion_reason
                    FROM product_catalog_exclusions
                    WHERE catalog_version_id = :catalog_version_id
                    ORDER BY seller_sku_match_bytes, action
                    """
                ),
                {"catalog_version_id": base_catalog_version_id},
            )
            .mappings()
            .all()
        )
        return tuple(
            ExistingCatalogDecision(
                seller_sku_match_bytes=bytes(row["seller_sku_match_bytes"]),
                action=cast(Any, str(row["action"])),
                target_sku_id=(
                    None if row["target_sku_id"] is None else int(row["target_sku_id"])
                ),
                exclusion_reason=_text(row["exclusion_reason"]),
            )
            for row in rows
        )


class MySqlCatalogSnapshotWriter:
    """Persist only the supplied immutable payload; never reread current pointers."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def persist_building(
        self,
        payload: FrozenCatalogExportPayload,
        *,
        operation_token: UUID,
        created_by_user_id: int,
    ) -> BuildingCatalogExport:
        if operation_token.version != 4:
            raise ValueError("operation_token must be UUID v4")
        _positive(created_by_user_id)
        candidate_json = _candidate_payload_json(payload.candidates)
        evidence_json = _evidence_payload_json(payload.evidence)
        with self._engine.begin() as connection:
            existing = self._existing(connection, operation_token)
            if existing is not None:
                return self._validate_existing(
                    existing,
                    payload=payload,
                    created_by_user_id=created_by_user_id,
                )
            try:
                snapshot_id, tuple_id = self._persist_fact_tuple(connection, payload)
                export_id = self._insert_export(
                    connection,
                    payload=payload,
                    operation_token=operation_token,
                    created_by_user_id=created_by_user_id,
                    fact_tuple_id=tuple_id,
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO catalog_jobs (
                            site_id, job_kind, resource_kind, resource_id,
                            status, execution_phase
                        ) VALUES (
                            :site_id, 'catalog_export', 'catalog_export',
                            :export_id, 'queued', 'waiting_for_worker'
                        )
                        """
                    ),
                    {"site_id": payload.site_id, "export_id": export_id},
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO catalog_export_payloads (
                            export_id, site_id, candidate_payload_json,
                            candidate_payload_digest, evidence_payload_json,
                            evidence_payload_digest, payload_digest
                        ) VALUES (
                            :export_id, :site_id, :candidate_json,
                            :candidate_digest, :evidence_json,
                            :evidence_digest, :payload_digest
                        )
                        """
                    ),
                    {
                        "export_id": export_id,
                        "site_id": payload.site_id,
                        "candidate_json": canonical_json_bytes(candidate_json).decode(
                            "utf-8"
                        ),
                        "candidate_digest": payload.candidates.payload_digest,
                        "evidence_json": canonical_json_bytes(evidence_json).decode(
                            "utf-8"
                        ),
                        "evidence_digest": payload.evidence.payload_digest,
                        "payload_digest": payload.payload_digest,
                    },
                )
                self._persist_evidence(
                    connection,
                    payload=payload,
                    export_id=export_id,
                )
            except IntegrityError as error:
                raise CatalogSnapshotError() from error
            return BuildingCatalogExport(
                export_id=export_id,
                publication_snapshot_id=snapshot_id,
                fact_snapshot_tuple_id=tuple_id,
                export_status="building",
                workbook_status=None,
                payload_digest=payload.payload_digest,
            )

    @staticmethod
    def _existing(connection: Connection, operation_token: UUID) -> RowMapping | None:
        return (
            connection.execute(
                sa.text(
                    """
                    SELECT exports.id AS export_id, exports.site_id,
                           exports.fact_snapshot_tuple_id,
                           exports.base_catalog_version_id,
                           exports.catalog_publication_revision,
                           exports.created_by_user_id, exports.export_status,
                           exports.workbook_status, tuples.publication_snapshot_id,
                           tuples.tuple_digest, payloads.payload_digest
                    FROM catalog_exports AS exports
                    INNER JOIN fact_snapshot_tuples AS tuples
                        ON tuples.id = exports.fact_snapshot_tuple_id
                    INNER JOIN catalog_export_payloads AS payloads
                        ON payloads.export_id = exports.id
                       AND payloads.site_id = exports.site_id
                    WHERE exports.operation_token = :operation_token
                    """
                ),
                {"operation_token": operation_token.bytes},
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _validate_existing(
        row: RowMapping,
        *,
        payload: FrozenCatalogExportPayload,
        created_by_user_id: int,
    ) -> BuildingCatalogExport:
        if (
            int(row["site_id"]) != payload.site_id
            or int(row["created_by_user_id"]) != created_by_user_id
            or row["base_catalog_version_id"] != payload.base_catalog_version_id
            or int(row["catalog_publication_revision"])
            != payload.catalog_publication_revision
            or _bytes(row["tuple_digest"]) != payload.fact_tuple.tuple_digest
            or _bytes(row["payload_digest"]) != payload.payload_digest
            or row["export_status"] != "building"
            or row["workbook_status"] is not None
        ):
            raise CatalogExportIdempotencyConflict()
        return BuildingCatalogExport(
            export_id=int(row["export_id"]),
            publication_snapshot_id=int(row["publication_snapshot_id"]),
            fact_snapshot_tuple_id=int(row["fact_snapshot_tuple_id"]),
            export_status="building",
            workbook_status=None,
            payload_digest=payload.payload_digest,
        )

    @staticmethod
    def _persist_fact_tuple(
        connection: Connection, payload: FrozenCatalogExportPayload
    ) -> tuple[int, int]:
        existing = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, publication_snapshot_id, site_id,
                           report_source_scope_id, return_dedup_snapshot_id,
                           site_config_version_id, fact_cutoff_at,
                           return_publication_set_digest, status
                    FROM fact_snapshot_tuples
                    WHERE tuple_digest = :tuple_digest
                    """
                ),
                {"tuple_digest": payload.fact_tuple.tuple_digest},
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            if (
                int(existing["site_id"]) != payload.site_id
                or int(existing["report_source_scope_id"])
                != payload.publication_snapshot.report_source_scope_id
                or int(existing["return_dedup_snapshot_id"])
                != payload.fact_tuple.return_dedup_snapshot_id
                or int(existing["site_config_version_id"])
                != payload.fact_tuple.site_config_version_id
                or _utc(existing["fact_cutoff_at"]) != payload.fact_tuple.fact_cutoff_at
                or _bytes(existing["return_publication_set_digest"])
                != payload.fact_tuple.return_publication_set_digest
                or existing["status"] != "building"
            ):
                raise CatalogSnapshotError()
            return int(existing["publication_snapshot_id"]), int(existing["id"])

        snapshot = payload.publication_snapshot
        inserted_snapshot = connection.execute(
            sa.text(
                """
                INSERT INTO publication_snapshots (
                    site_id, report_source_scope_id, site_config_version_id,
                    candidate_rule_version, normalization_manifest_id,
                    coverage_start_date, coverage_end_date,
                    transaction_started_at, fact_cutoff_at,
                    return_publication_set_digest, status, snapshot_digest
                ) VALUES (
                    :site_id, :scope_id, :site_config_id,
                    :candidate_rule, :normalization_manifest,
                    :coverage_start, :coverage_end,
                    :transaction_started, :fact_cutoff,
                    :return_digest, 'building', :snapshot_digest
                )
                """
            ),
            {
                "site_id": snapshot.site_id,
                "scope_id": snapshot.report_source_scope_id,
                "site_config_id": snapshot.site_config_version_id,
                "candidate_rule": snapshot.candidate_rule_version,
                "normalization_manifest": snapshot.normalization_manifest_id,
                "coverage_start": snapshot.coverage_start_date,
                "coverage_end": snapshot.coverage_end_date,
                "transaction_started": _mysql_datetime(snapshot.transaction_started_at),
                "fact_cutoff": _mysql_datetime(snapshot.fact_cutoff_at),
                "return_digest": snapshot.return_publication_set_digest,
                "snapshot_digest": snapshot.snapshot_digest,
            },
        )
        if inserted_snapshot.lastrowid is None:
            raise CatalogSnapshotError()
        snapshot_id = int(inserted_snapshot.lastrowid)
        for member in snapshot.members:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO publication_snapshot_members (
                        publication_snapshot_id, site_id, report_type,
                        report_date, dataset_id, published_version_id,
                        publication_pointer_revision, member_status,
                        active_row_count, active_row_projection_digest
                    ) VALUES (
                        :snapshot_id, :site_id, :report_type,
                        :report_date, :dataset_id, :version_id,
                        :pointer_revision, :member_status,
                        :active_row_count, :projection_digest
                    )
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "site_id": snapshot.site_id,
                    "report_type": member.report_type,
                    "report_date": member.report_date,
                    "dataset_id": member.dataset_id,
                    "version_id": member.published_version_id,
                    "pointer_revision": member.publication_pointer_revision,
                    "member_status": member.member_status,
                    "active_row_count": member.active_row_count,
                    "projection_digest": member.active_row_projection_digest,
                },
            )
        tuple_row = connection.execute(
            sa.text(
                """
                INSERT INTO fact_snapshot_tuples (
                    site_id, report_source_scope_id, publication_snapshot_id,
                    return_dedup_snapshot_id, return_dedup_snapshot_status,
                    site_config_version_id, fact_cutoff_at,
                    return_publication_set_digest, tuple_digest, status
                ) VALUES (
                    :site_id, :scope_id, :publication_snapshot_id,
                    :dedup_snapshot_id, 'ready',
                    :site_config_id, :fact_cutoff,
                    :return_digest, :tuple_digest, 'building'
                )
                """
            ),
            {
                "site_id": payload.site_id,
                "scope_id": snapshot.report_source_scope_id,
                "publication_snapshot_id": snapshot_id,
                "dedup_snapshot_id": payload.fact_tuple.return_dedup_snapshot_id,
                "site_config_id": payload.fact_tuple.site_config_version_id,
                "fact_cutoff": _mysql_datetime(payload.fact_tuple.fact_cutoff_at),
                "return_digest": payload.fact_tuple.return_publication_set_digest,
                "tuple_digest": payload.fact_tuple.tuple_digest,
            },
        )
        if tuple_row.lastrowid is None:
            raise CatalogSnapshotError()
        return snapshot_id, int(tuple_row.lastrowid)

    @staticmethod
    def _insert_export(
        connection: Connection,
        *,
        payload: FrozenCatalogExportPayload,
        operation_token: UUID,
        created_by_user_id: int,
        fact_tuple_id: int,
    ) -> int:
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO catalog_exports (
                    site_id, operation_token, fact_snapshot_tuple_id,
                    base_catalog_version_id, catalog_publication_revision,
                    workbook_schema_version, normalization_manifest_id,
                    export_status, workbook_status, artifact_sha256,
                    artifact_storage_key, failure_reason_code,
                    created_by_user_id
                ) VALUES (
                    :site_id, :operation_token, :fact_tuple_id,
                    :base_catalog_version_id, :catalog_revision,
                    :workbook_schema, :normalization_manifest,
                    'building', NULL, NULL, NULL, NULL, :created_by
                )
                """
            ),
            {
                "site_id": payload.site_id,
                "operation_token": operation_token.bytes,
                "fact_tuple_id": fact_tuple_id,
                "base_catalog_version_id": payload.base_catalog_version_id,
                "catalog_revision": payload.catalog_publication_revision,
                "workbook_schema": WORKBOOK_SCHEMA_VERSION,
                "normalization_manifest": NORMALIZATION_MANIFEST_ID,
                "created_by": created_by_user_id,
            },
        )
        if inserted.lastrowid is None:
            raise CatalogSnapshotError()
        return int(inserted.lastrowid)

    @staticmethod
    def _insert_ref(
        connection: Connection,
        *,
        site_id: int,
        export_id: int,
        source_kind: str,
        raw_value: str,
        safe_ref: Any,
    ) -> int:
        raw_sha256 = bytes.fromhex(safe_ref.sha256.removeprefix("sha256:"))
        existing = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, raw_value, safe_preview, is_unsafe, is_truncated
                    FROM catalog_source_refs
                    WHERE site_id = :site_id
                      AND resource_kind = 'export'
                      AND resource_id = :export_id
                      AND source_kind = :source_kind
                      AND raw_sha256 = :raw_sha256
                    """
                ),
                {
                    "site_id": site_id,
                    "export_id": export_id,
                    "source_kind": source_kind,
                    "raw_sha256": raw_sha256,
                },
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            if (
                str(existing["raw_value"]) != raw_value
                or str(existing["safe_preview"]) != safe_ref.preview
                or bool(existing["is_unsafe"]) != safe_ref.is_unsafe
                or bool(existing["is_truncated"]) != safe_ref.is_truncated
            ):
                raise CatalogSnapshotError()
            return int(existing["id"])
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO catalog_source_refs (
                    site_id, resource_kind, resource_id, source_kind,
                    raw_value, raw_sha256, safe_preview, is_unsafe, is_truncated
                ) VALUES (
                    :site_id, 'export', :export_id, :source_kind,
                    :raw_value, :raw_sha256, :safe_preview, :is_unsafe,
                    :is_truncated
                )
                """
            ),
            {
                "site_id": site_id,
                "export_id": export_id,
                "source_kind": source_kind,
                "raw_value": raw_value,
                "raw_sha256": raw_sha256,
                "safe_preview": safe_ref.preview,
                "is_unsafe": safe_ref.is_unsafe,
                "is_truncated": safe_ref.is_truncated,
            },
        )
        if inserted.lastrowid is None:
            raise CatalogSnapshotError()
        return int(inserted.lastrowid)

    @classmethod
    def _persist_evidence(
        cls,
        connection: Connection,
        *,
        payload: FrozenCatalogExportPayload,
        export_id: int,
    ) -> None:
        for member in payload.evidence.members:
            item = member.observation
            existing = connection.scalar(
                sa.text(
                    """
                    SELECT id FROM catalog_source_evidence
                    WHERE source_key_id = :source_key_id
                      AND dataset_id = :dataset_id
                      AND published_version_id = :version_id
                      AND source_row_id = :source_row_id
                    """
                ),
                {
                    "source_key_id": item.source_key_id,
                    "dataset_id": item.dataset_id,
                    "version_id": item.published_version_id,
                    "source_row_id": item.source_row_id,
                },
            )
            seller_ref_id = cls._insert_ref(
                connection,
                site_id=payload.site_id,
                export_id=export_id,
                source_kind="seller_sku",
                raw_value=item.seller_sku,
                safe_ref=member.seller_sku_ref,
            )

            def optional_ref(
                source_kind: str, raw_value: str | None, safe_ref: Any
            ) -> int | None:
                if raw_value is None or safe_ref is None:
                    return None
                return cls._insert_ref(
                    connection,
                    site_id=payload.site_id,
                    export_id=export_id,
                    source_kind=source_kind,
                    raw_value=raw_value,
                    safe_ref=safe_ref,
                )

            title_ref_id = optional_ref("title", item.title, member.title_ref)
            parent_ref_id = optional_ref(
                "parent_asin", item.parent_asin, member.parent_asin_ref
            )
            child_ref_id = optional_ref(
                "child_asin", item.child_asin, member.child_asin_ref
            )
            fnsku_ref_id = optional_ref("fnsku", item.fnsku, member.fnsku_ref)
            locator_ref_id = cls._insert_ref(
                connection,
                site_id=payload.site_id,
                export_id=export_id,
                source_kind="source_locator",
                raw_value=item.source_locator,
                safe_ref=member.source_locator_ref,
            )
            # Each export owns its reveal references even when the immutable
            # observation was already stored by an earlier export.
            if existing is not None:
                continue
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_source_evidence (
                        site_id, report_source_scope_id, source_key_id,
                        report_type, report_date, event_date, dataset_id,
                        published_version_id, source_row_id, seller_sku_ref_id,
                        title_ref_id, parent_asin_ref_id, child_asin_ref_id,
                        fnsku_ref_id, source_locator_ref_id,
                        evidence_tuple_digest
                    ) VALUES (
                        :site_id, :scope_id, :source_key_id,
                        :report_type, :report_date, :event_date, :dataset_id,
                        :version_id, :source_row_id, :seller_ref_id,
                        :title_ref_id, :parent_ref_id, :child_ref_id,
                        :fnsku_ref_id, :locator_ref_id, :tuple_digest
                    )
                    """
                ),
                {
                    "site_id": payload.site_id,
                    "scope_id": item.report_source_scope_id,
                    "source_key_id": item.source_key_id,
                    "report_type": item.report_type,
                    "report_date": item.report_date,
                    "event_date": item.event_date,
                    "dataset_id": item.dataset_id,
                    "version_id": item.published_version_id,
                    "source_row_id": item.source_row_id,
                    "seller_ref_id": seller_ref_id,
                    "title_ref_id": title_ref_id,
                    "parent_ref_id": parent_ref_id,
                    "child_ref_id": child_ref_id,
                    "fnsku_ref_id": fnsku_ref_id,
                    "locator_ref_id": locator_ref_id,
                    "tuple_digest": member.evidence_tuple_digest,
                },
            )


__all__ = (
    "WORKBOOK_SCHEMA_VERSION",
    "BuildingCatalogExport",
    "CatalogExportIdempotencyConflict",
    "CatalogSnapshotError",
    "CatalogSnapshotUnavailable",
    "FrozenCatalogExportPayload",
    "MySqlCatalogSnapshotCoordinator",
    "MySqlCatalogSnapshotWriter",
)
