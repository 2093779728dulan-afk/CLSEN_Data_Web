"""Bounded catalog-version queries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine, RowMapping


def _source_event_timestamp(payload: object, report_type: str) -> str | None:
    """Expose only the original event timestamp, never other raw source fields."""
    if report_type != "return_report" or payload is None:
        return None
    try:
        decoded = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
        if not isinstance(decoded, dict):
            return None
        header, values = decoded["header"], decoded["values"]
        index = header.index("return-date")
        value = values[index]
        return value if isinstance(value, str) and len(value) <= 128 else None
    except ValueError, KeyError, IndexError, TypeError, AttributeError:
        return None


@dataclass(frozen=True, slots=True)
class CatalogSourceSummary:
    first_seen_date: date | None
    latest_seen_date: date | None
    observation_count: int
    source_report_count: int


@dataclass(frozen=True, slots=True)
class CatalogStyleSummary:
    style_id: int
    revision: int
    style_code: str
    standard_name: str
    status: str
    category_id: int | None
    category_code: str | None
    category_name: str | None
    category_recorded: bool
    variant_count: int
    seller_sku_count: int
    source_summary: CatalogSourceSummary
    category_parent: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class CatalogSkuSummary:
    sku_id: int
    style_id: int
    revision: int
    internal_display_sku: str
    standard_color: str
    standard_size: str
    status: str
    seller_sku_count: int
    source_summary: CatalogSourceSummary


@dataclass(frozen=True, slots=True)
class CatalogSellerSkuAlias:
    mapping_id: int
    seller_sku: dict[str, object]
    seller_account: str
    marketplace: str
    mapping_status: str
    source_summary: CatalogSourceSummary


@dataclass(frozen=True, slots=True)
class CatalogEvidenceItem:
    evidence_id: int
    report_type: str
    report_date: date
    event_date: date | None
    dataset_id: int
    published_version_id: int
    source_row_id: int
    evidence_digest: str
    seller_sku: dict[str, object]
    title: dict[str, object] | None
    parent_asin: dict[str, object] | None
    child_asin: dict[str, object] | None
    fnsku: dict[str, object] | None
    source_filename: str | None = None
    source_record_number: int | None = None
    source_event_timestamp: str | None = None
    source_timezone: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogSellerSkuPage:
    page: int
    page_size: int
    total_items: int
    items: tuple[CatalogSellerSkuAlias, ...]


@dataclass(frozen=True, slots=True)
class CatalogEvidencePage:
    page: int
    page_size: int
    total_items: int
    items: tuple[CatalogEvidenceItem, ...]


@dataclass(frozen=True, slots=True)
class CatalogVersionSummary:
    catalog_version_id: int
    version_number: int
    catalog_publication_revision: int
    styles: tuple[CatalogStyleSummary, ...]
    skus: tuple[CatalogSkuSummary, ...]


def _source_summary(
    row: RowMapping | Mapping[str, Any],
) -> CatalogSourceSummary:
    return CatalogSourceSummary(
        first_seen_date=row["first_seen_date"],
        latest_seen_date=row["latest_seen_date"],
        observation_count=int(row["observation_count"] or 0),
        source_report_count=int(row["source_report_count"] or 0),
    )


def _safe_source_ref(
    row: RowMapping | Mapping[str, Any], prefix: str
) -> dict[str, object] | None:
    source_ref_id = row[f"{prefix}_id"]
    if source_ref_id is None:
        return None
    return {
        "source_ref_id": str(source_ref_id),
        "preview": str(row[f"{prefix}_preview"]),
        "digest": "sha256:" + bytes(row[f"{prefix}_sha256"]).hex(),
        "is_unsafe": bool(row[f"{prefix}_unsafe"]),
        "is_truncated": bool(row[f"{prefix}_truncated"]),
    }


class MySqlCatalogQueries:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def current_catalog(self, *, site_id: int) -> CatalogVersionSummary | None:
        with self._engine.connect() as connection:
            version = (
                connection.execute(
                    sa.text(
                        """
                        SELECT versions.id, versions.version_number,
                               pointers.catalog_publication_revision
                        FROM product_catalog_publications AS pointers
                        INNER JOIN product_catalog_versions AS versions
                          ON versions.id = pointers.current_catalog_version_id
                         AND versions.site_id = pointers.site_id
                        WHERE pointers.site_id = :site_id
                        """
                    ),
                    {"site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
            if version is None:
                return None
            version_id = int(version["id"])
            style_rows = (
                connection.execute(
                    sa.text(
                        """
                    SELECT revisions.style_id, revisions.revision,
                           revisions.style_code, revisions.standard_name,
                           revisions.status, members.category_id,
                           members.category_code_snapshot,
                           members.category_name_snapshot,
                           members.category_parent_snapshot,
                           members.category_snapshot_recorded
                    FROM product_catalog_style_members AS members
                    INNER JOIN product_style_revisions AS revisions
                      ON revisions.id = members.style_revision_id
                    WHERE members.catalog_version_id = :version_id
                    ORDER BY revisions.style_id
                    """
                    ),
                    {"version_id": version_id},
                )
                .mappings()
                .all()
            )
            sku_rows = (
                connection.execute(
                    sa.text(
                        """
                    SELECT revisions.sku_id, revisions.style_id,
                           revisions.revision, revisions.internal_display_sku,
                           revisions.standard_color, revisions.standard_size,
                           revisions.status
                    FROM product_catalog_sku_members AS members
                    INNER JOIN product_sku_revisions AS revisions
                      ON revisions.id = members.sku_revision_id
                    WHERE members.catalog_version_id = :version_id
                    ORDER BY revisions.sku_id
                    """
                    ),
                    {"version_id": version_id},
                )
                .mappings()
                .all()
            )
            sku_stats = {
                int(row["sku_id"]): row
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT mappings.sku_id,
                               COUNT(DISTINCT mappings.id) AS seller_sku_count,
                               MIN(COALESCE(evidence.event_date,
                                            evidence.report_date)) AS first_seen_date,
                               MAX(COALESCE(evidence.event_date,
                                            evidence.report_date)) AS latest_seen_date,
                               COUNT(DISTINCT evidence.id) AS observation_count,
                               COUNT(DISTINCT evidence.published_version_id)
                                   AS source_report_count
                        FROM product_catalog_mappings AS mappings
                        LEFT JOIN report_source_keys AS source_keys
                          ON source_keys.site_id = mappings.site_id
                         AND source_keys.report_source_scope_id =
                             mappings.report_source_scope_id
                         AND source_keys.seller_sku_match_sha256 =
                             mappings.seller_sku_match_sha256
                         AND source_keys.seller_sku_match_bytes =
                             mappings.seller_sku_match_bytes
                        LEFT JOIN catalog_source_evidence AS evidence
                          ON evidence.source_key_id = source_keys.id
                        WHERE mappings.catalog_version_id = :version_id
                        GROUP BY mappings.sku_id
                        """
                    ),
                    {"version_id": version_id},
                )
                .mappings()
                .all()
            }
            style_stats = {
                int(row["style_id"]): row
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT sku_members.style_id,
                               COUNT(DISTINCT sku_members.sku_id) AS variant_count,
                               COUNT(DISTINCT mappings.id) AS seller_sku_count,
                               MIN(COALESCE(evidence.event_date,
                                            evidence.report_date)) AS first_seen_date,
                               MAX(COALESCE(evidence.event_date,
                                            evidence.report_date)) AS latest_seen_date,
                               COUNT(DISTINCT evidence.id) AS observation_count,
                               COUNT(DISTINCT evidence.published_version_id)
                                   AS source_report_count
                        FROM product_catalog_sku_members AS sku_members
                        LEFT JOIN product_catalog_mappings AS mappings
                          ON mappings.catalog_version_id =
                             sku_members.catalog_version_id
                         AND mappings.site_id = sku_members.site_id
                         AND mappings.sku_id = sku_members.sku_id
                        LEFT JOIN report_source_keys AS source_keys
                          ON source_keys.site_id = mappings.site_id
                         AND source_keys.report_source_scope_id =
                             mappings.report_source_scope_id
                         AND source_keys.seller_sku_match_sha256 =
                             mappings.seller_sku_match_sha256
                         AND source_keys.seller_sku_match_bytes =
                             mappings.seller_sku_match_bytes
                        LEFT JOIN catalog_source_evidence AS evidence
                          ON evidence.source_key_id = source_keys.id
                        WHERE sku_members.catalog_version_id = :version_id
                        GROUP BY sku_members.style_id
                        """
                    ),
                    {"version_id": version_id},
                )
                .mappings()
                .all()
            }
            empty_summary: dict[str, Any] = {
                "first_seen_date": None,
                "latest_seen_date": None,
                "observation_count": 0,
                "source_report_count": 0,
            }
            styles = tuple(
                CatalogStyleSummary(
                    style_id=int(row["style_id"]),
                    revision=int(row["revision"]),
                    style_code=str(row["style_code"]),
                    standard_name=str(row["standard_name"]),
                    status=str(row["status"]),
                    category_id=None
                    if row["category_id"] is None
                    else int(row["category_id"]),
                    category_code=None
                    if row["category_code_snapshot"] is None
                    else str(row["category_code_snapshot"]),
                    category_name=None
                    if row["category_name_snapshot"] is None
                    else str(row["category_name_snapshot"]),
                    category_recorded=bool(row["category_snapshot_recorded"]),
                    category_parent=json.loads(row["category_parent_snapshot"])
                    if isinstance(row.get("category_parent_snapshot"), str)
                    else row.get("category_parent_snapshot"),
                    variant_count=int(
                        style_stats.get(int(row["style_id"]), empty_summary).get(
                            "variant_count", 0
                        )
                    ),
                    seller_sku_count=int(
                        style_stats.get(int(row["style_id"]), empty_summary).get(
                            "seller_sku_count", 0
                        )
                    ),
                    source_summary=_source_summary(
                        style_stats.get(int(row["style_id"]), empty_summary)
                    ),
                )
                for row in style_rows
            )
            skus = tuple(
                CatalogSkuSummary(
                    int(row["sku_id"]),
                    int(row["style_id"]),
                    int(row["revision"]),
                    str(row["internal_display_sku"]),
                    str(row["standard_color"]),
                    str(row["standard_size"]),
                    str(row["status"]),
                    int(
                        sku_stats.get(int(row["sku_id"]), empty_summary).get(
                            "seller_sku_count", 0
                        )
                    ),
                    _source_summary(sku_stats.get(int(row["sku_id"]), empty_summary)),
                )
                for row in sku_rows
            )
        return CatalogVersionSummary(
            version_id,
            int(version["version_number"]),
            int(version["catalog_publication_revision"]),
            styles,
            skus,
        )

    def style_pending_items(
        self,
        *,
        site_id: int,
        style_id: int,
        limit: int = 20,
    ) -> tuple[dict[str, object], ...]:
        """Return bounded active draft summaries associated with one stable style."""

        with self._engine.connect() as connection:
            imports = (
                connection.execute(
                    sa.text(
                        """
                        SELECT id, status, workflow_revision, updated_at
                        FROM catalog_imports
                        WHERE site_id = :site_id
                          AND status IN (
                            'needs_attention', 'validated', 'ready_for_approval'
                          )
                        ORDER BY updated_at DESC, id DESC
                        LIMIT :limit
                        """
                    ),
                    {"site_id": site_id, "limit": limit},
                )
                .mappings()
                .all()
            )
            result: list[dict[str, object]] = []
            for imported in imports:
                import_id = int(imported["id"])
                workflow_revision = int(imported["workflow_revision"])
                rows = (
                    connection.execute(
                        sa.text(
                            """
                            SELECT section, row_key, projection_state, payload_json
                            FROM catalog_import_rows AS current_rows
                            WHERE import_id = :import_id
                              AND site_id = :site_id
                              AND workflow_revision = (
                                  SELECT MAX(previous.workflow_revision)
                                  FROM catalog_import_rows AS previous
                                  WHERE previous.import_id = current_rows.import_id
                                    AND previous.section = current_rows.section
                                    AND previous.workflow_revision <= :workflow_revision
                              )
                              AND section IN ('styles', 'skus', 'mappings')
                            ORDER BY section, id
                            """
                        ),
                        {
                            "import_id": import_id,
                            "site_id": site_id,
                            "workflow_revision": workflow_revision,
                        },
                    )
                    .mappings()
                    .all()
                )
                decoded: list[tuple[str, str, str, dict[str, object]]] = []
                for row in rows:
                    payload_value = row["payload_json"]
                    payload = (
                        json.loads(payload_value)
                        if isinstance(payload_value, str)
                        else payload_value
                    )
                    if not isinstance(payload, dict):
                        continue
                    decoded.append(
                        (
                            str(row["section"]),
                            str(row["row_key"]),
                            str(row["projection_state"]),
                            payload,
                        )
                    )
                style_keys = {
                    row_key
                    for section, row_key, _state, payload in decoded
                    if section == "styles"
                    and str(payload.get("system_style_id")) == str(style_id)
                }
                candidate_sku_keys = {
                    row_key
                    for section, row_key, state, payload in decoded
                    if section == "skus"
                    and state == "included"
                    and payload.get("system_sku_id") is None
                    and payload.get("style_row_key") in style_keys
                }
                mappings = [
                    payload
                    for section, _row_key, state, payload in decoded
                    if section == "mappings"
                    and state == "included"
                    and payload.get("target_sku_row_key") in candidate_sku_keys
                ]
                pending_sku_keys = {
                    str(payload["target_sku_row_key"])
                    for payload in mappings
                    if payload.get("target_sku_row_key") is not None
                }
                if not pending_sku_keys and not mappings:
                    continue
                previews = tuple(
                    str(payload["seller_sku_preview"])
                    for payload in mappings
                    if payload.get("seller_sku_preview") is not None
                )[:3]
                result.append(
                    {
                        "import_id": import_id,
                        "status": str(imported["status"]),
                        "workflow_revision": workflow_revision,
                        "updated_at": imported["updated_at"],
                        "variant_count": len(pending_sku_keys),
                        "seller_sku_count": len(mappings),
                        "seller_sku_previews": previews,
                        "review_path": f"/catalog/imports/{import_id}",
                    }
                )
            return tuple(result)

    @staticmethod
    def _current_version_id(connection: Any, *, site_id: int) -> int | None:
        value = connection.scalar(
            sa.text(
                "SELECT current_catalog_version_id "
                "FROM product_catalog_publications WHERE site_id = :site_id"
            ),
            {"site_id": site_id},
        )
        return None if value is None else int(value)

    @staticmethod
    def _variant_is_current(
        connection: Any, *, site_id: int, version_id: int, sku_id: int
    ) -> bool:
        value = connection.scalar(
            sa.text(
                "SELECT 1 FROM product_catalog_sku_members "
                "WHERE catalog_version_id = :version_id AND site_id = :site_id "
                "AND sku_id = :sku_id"
            ),
            {"site_id": site_id, "version_id": version_id, "sku_id": sku_id},
        )
        return value is not None

    def variant_seller_skus(
        self, *, site_id: int, sku_id: int, page: int, page_size: int
    ) -> CatalogSellerSkuPage | None:
        offset = (page - 1) * page_size
        with self._engine.connect() as connection:
            version_id = self._current_version_id(connection, site_id=site_id)
            if version_id is None or not self._variant_is_current(
                connection, site_id=site_id, version_id=version_id, sku_id=sku_id
            ):
                return None
            total_items = int(
                connection.scalar(
                    sa.text(
                        "SELECT COUNT(*) FROM product_catalog_mappings "
                        "WHERE catalog_version_id = :version_id "
                        "AND site_id = :site_id AND sku_id = :sku_id"
                    ),
                    {
                        "version_id": version_id,
                        "site_id": site_id,
                        "sku_id": sku_id,
                    },
                )
                or 0
            )
            rows = (
                connection.execute(
                    sa.text(
                        """
                        SELECT mappings.id AS mapping_id,
                               mappings.seller_sku_match_sha256,
                               scopes.seller_account_display_name,
                               mappings.marketplace_scope_code,
                               MIN(refs.safe_preview) AS seller_sku_preview,
                               MAX(refs.is_unsafe) AS seller_sku_unsafe,
                               MAX(refs.is_truncated) AS seller_sku_truncated,
                               MIN(COALESCE(evidence.event_date,
                                            evidence.report_date)) AS first_seen_date,
                               MAX(COALESCE(evidence.event_date,
                                            evidence.report_date)) AS latest_seen_date,
                               COUNT(DISTINCT evidence.id) AS observation_count,
                               COUNT(DISTINCT evidence.published_version_id)
                                   AS source_report_count
                        FROM product_catalog_mappings AS mappings
                        INNER JOIN report_source_scopes AS scopes
                          ON scopes.id = mappings.report_source_scope_id
                         AND scopes.site_id = mappings.site_id
                        LEFT JOIN report_source_keys AS source_keys
                          ON source_keys.site_id = mappings.site_id
                         AND source_keys.report_source_scope_id =
                             mappings.report_source_scope_id
                         AND source_keys.seller_sku_match_sha256 =
                             mappings.seller_sku_match_sha256
                         AND source_keys.seller_sku_match_bytes =
                             mappings.seller_sku_match_bytes
                        LEFT JOIN catalog_source_evidence AS evidence
                          ON evidence.source_key_id = source_keys.id
                        LEFT JOIN catalog_source_refs AS refs
                          ON refs.id = evidence.seller_sku_ref_id
                        WHERE mappings.catalog_version_id = :version_id
                          AND mappings.site_id = :site_id
                          AND mappings.sku_id = :sku_id
                        GROUP BY mappings.id,
                                 mappings.seller_sku_match_sha256,
                                 scopes.seller_account_display_name,
                                 mappings.marketplace_scope_code
                        ORDER BY mappings.id
                        LIMIT :limit OFFSET :offset
                        """
                    ),
                    {
                        "version_id": version_id,
                        "site_id": site_id,
                        "sku_id": sku_id,
                        "limit": page_size,
                        "offset": offset,
                    },
                )
                .mappings()
                .all()
            )
        items = tuple(
            CatalogSellerSkuAlias(
                mapping_id=int(row["mapping_id"]),
                seller_sku={
                    "source_ref_id": f"mapping:{int(row['mapping_id'])}",
                    "preview": str(row["seller_sku_preview"] or "来源值不可用"),
                    "digest": "sha256:" + bytes(row["seller_sku_match_sha256"]).hex(),
                    "is_unsafe": bool(row["seller_sku_unsafe"]),
                    "is_truncated": bool(row["seller_sku_truncated"]),
                },
                seller_account=str(row["seller_account_display_name"]),
                marketplace=str(row["marketplace_scope_code"]),
                mapping_status="mapped",
                source_summary=_source_summary(row),
            )
            for row in rows
        )
        return CatalogSellerSkuPage(page, page_size, total_items, items)

    def variant_evidence(
        self, *, site_id: int, sku_id: int, page: int, page_size: int
    ) -> CatalogEvidencePage | None:
        offset = (page - 1) * page_size
        joins = """
            FROM product_catalog_mappings AS mappings
            INNER JOIN report_source_keys AS source_keys
              ON source_keys.site_id = mappings.site_id
             AND source_keys.report_source_scope_id =
                 mappings.report_source_scope_id
             AND source_keys.seller_sku_match_sha256 =
                 mappings.seller_sku_match_sha256
             AND source_keys.seller_sku_match_bytes =
                 mappings.seller_sku_match_bytes
            INNER JOIN catalog_source_evidence AS evidence
              ON evidence.source_key_id = source_keys.id
            INNER JOIN catalog_source_refs AS seller
              ON seller.id = evidence.seller_sku_ref_id
            LEFT JOIN catalog_source_refs AS title
              ON title.id = evidence.title_ref_id
            LEFT JOIN catalog_source_refs AS parent_asin
              ON parent_asin.id = evidence.parent_asin_ref_id
            LEFT JOIN catalog_source_refs AS child_asin
              ON child_asin.id = evidence.child_asin_ref_id
            LEFT JOIN catalog_source_refs AS fnsku
              ON fnsku.id = evidence.fnsku_ref_id
            LEFT JOIN version_rows AS original_row
              ON original_row.id = evidence.source_row_id
             AND original_row.version_id = evidence.published_version_id
            LEFT JOIN parsed_source_rows AS parsed
              ON parsed.id = original_row.original_parsed_source_row_id
            LEFT JOIN parse_attempts AS attempt ON attempt.id = parsed.parse_attempt_id
            LEFT JOIN import_batches AS batch
              ON batch.id = attempt.batch_id AND batch.site_id = mappings.site_id
            LEFT JOIN raw_files AS file ON file.id = batch.raw_file_id
            LEFT JOIN site_config_versions AS config
              ON config.id = batch.site_config_version_id
             AND config.site_id = mappings.site_id
            WHERE mappings.catalog_version_id = :version_id
              AND mappings.site_id = :site_id
              AND mappings.sku_id = :sku_id
        """
        parameters = {"site_id": site_id, "sku_id": sku_id}
        with self._engine.connect() as connection:
            version_id = self._current_version_id(connection, site_id=site_id)
            if version_id is None or not self._variant_is_current(
                connection, site_id=site_id, version_id=version_id, sku_id=sku_id
            ):
                return None
            parameters["version_id"] = version_id
            total_items = int(
                connection.scalar(
                    sa.text("SELECT COUNT(DISTINCT evidence.id) " + joins),
                    parameters,
                )
                or 0
            )
            rows = (
                connection.execute(
                    sa.text(
                        """
                        SELECT evidence.id AS evidence_id,
                               evidence.report_type, evidence.report_date,
                               evidence.event_date, evidence.dataset_id,
                               evidence.published_version_id,
                               evidence.source_row_id,
                               file.original_filename AS source_filename,
                               CASE WHEN batch.id IS NOT NULL
                                    THEN parsed.source_row_number
                               END AS source_record_number,
                               CASE WHEN batch.id IS NOT NULL
                                    THEN parsed.decoded_fields
                               END AS source_decoded_fields,
                               config.source_timezone,
                               evidence.evidence_tuple_digest,
                               seller.id AS seller_id,
                               seller.safe_preview AS seller_preview,
                               seller.raw_sha256 AS seller_sha256,
                               seller.is_unsafe AS seller_unsafe,
                               seller.is_truncated AS seller_truncated,
                               title.id AS title_id,
                               title.safe_preview AS title_preview,
                               title.raw_sha256 AS title_sha256,
                               title.is_unsafe AS title_unsafe,
                               title.is_truncated AS title_truncated,
                               parent_asin.id AS parent_asin_id,
                               parent_asin.safe_preview AS parent_asin_preview,
                               parent_asin.raw_sha256 AS parent_asin_sha256,
                               parent_asin.is_unsafe AS parent_asin_unsafe,
                               parent_asin.is_truncated AS parent_asin_truncated,
                               child_asin.id AS child_asin_id,
                               child_asin.safe_preview AS child_asin_preview,
                               child_asin.raw_sha256 AS child_asin_sha256,
                               child_asin.is_unsafe AS child_asin_unsafe,
                               child_asin.is_truncated AS child_asin_truncated,
                               fnsku.id AS fnsku_id,
                               fnsku.safe_preview AS fnsku_preview,
                               fnsku.raw_sha256 AS fnsku_sha256,
                               fnsku.is_unsafe AS fnsku_unsafe,
                               fnsku.is_truncated AS fnsku_truncated
                        """
                        + joins
                        + " ORDER BY evidence.report_date DESC, evidence.id DESC "
                        "LIMIT :limit OFFSET :offset"
                    ),
                    {**parameters, "limit": page_size, "offset": offset},
                )
                .mappings()
                .all()
            )
        items = tuple(
            CatalogEvidenceItem(
                evidence_id=int(row["evidence_id"]),
                report_type=str(row["report_type"]),
                report_date=row["report_date"],
                event_date=row["event_date"],
                dataset_id=int(row["dataset_id"]),
                published_version_id=int(row["published_version_id"]),
                source_row_id=int(row["source_row_id"]),
                source_filename=row["source_filename"],
                source_record_number=row["source_record_number"],
                source_event_timestamp=_source_event_timestamp(
                    row["source_decoded_fields"], str(row["report_type"])
                ),
                source_timezone=row["source_timezone"],
                evidence_digest="sha256:" + bytes(row["evidence_tuple_digest"]).hex(),
                seller_sku=_safe_source_ref(row, "seller") or {},
                title=_safe_source_ref(row, "title"),
                parent_asin=_safe_source_ref(row, "parent_asin"),
                child_asin=_safe_source_ref(row, "child_asin"),
                fnsku=_safe_source_ref(row, "fnsku"),
            )
            for row in rows
        )
        return CatalogEvidencePage(page, page_size, total_items, items)


__all__ = (
    "CatalogEvidenceItem",
    "CatalogEvidencePage",
    "CatalogSellerSkuAlias",
    "CatalogSellerSkuPage",
    "CatalogSkuSummary",
    "CatalogSourceSummary",
    "CatalogStyleSummary",
    "CatalogVersionSummary",
    "MySqlCatalogQueries",
)
