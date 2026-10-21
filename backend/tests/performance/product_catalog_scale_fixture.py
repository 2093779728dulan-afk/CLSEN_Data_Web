"""Deterministic analytics_scale_v1 identities and release budget helpers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import httpx2
import sqlalchemy as sa
from app.catalog.workbook import CatalogWorkbookData, CellValue
from sqlalchemy.engine import Engine

SCALE_NAME: Final = "analytics_scale_v1"
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
SCALE_SEED: Final = 20260819
SCALE_COUNTS: Final = {
    "styles": 1_700,
    "seller_sku_keys": 11_200,
    "days": 365,
    "business_rows": 4_088_000,
    "return_rows": 408_800,
    "aliases": 560,
    "unmatched": 224,
    "excluded": 112,
    "duplicate_candidate_members": 8_176,
    "duplicate_canonical_members": 4_088,
    "unresolved_duplicate_members": 4_088,
    "missing_days": 12,
    "max_series": 16,
    "source_evidence": 22_400,
}
PERFORMANCE_BUDGET_MS: Final = {
    "ledger_31d_page50": 1_500.0,
    "style_31d_8series": 750.0,
    "style_365d_8series": 1_500.0,
    "dedup_staging": 30_000.0,
    "publication_dedup_cas": 500.0,
}
_LOOPBACK_LOGIN_ERROR_CODES_BY_STATUS: Final[dict[int, frozenset[str]]] = {
    401: frozenset({"invalid_credentials"}),
    403: frozenset({"csrf_invalid"}),
    429: frozenset({"login_rate_limited"}),
}
_LOOPBACK_LOGIN_5XX_ERROR_CODES: Final = frozenset({"internal_server_error"})


@dataclass(frozen=True, slots=True)
class SyntheticSellerKey:
    ordinal: int
    style_ordinal: int
    seller_sku: str


@dataclass(frozen=True, slots=True)
class ScaleSeedResult:
    catalog_version_id: int
    report_source_scope_id: int
    style_id_with_sixteen_series: int
    business_row_id_from: int
    business_row_id_to: int
    return_row_id_from: int
    return_row_id_to: int
    source_key_id_from: int
    source_key_id_to: int
    snapshot_id_from: int
    snapshot_id_to: int
    from_date: date
    to_date: date


def iter_seller_keys() -> Iterator[SyntheticSellerKey]:
    """Yield all fixed keys without retaining the 4.5M-row fixture in Python."""

    for ordinal in range(SCALE_COUNTS["seller_sku_keys"]):
        style_ordinal = ordinal % SCALE_COUNTS["styles"]
        yield SyntheticSellerKey(
            ordinal=ordinal,
            style_ordinal=style_ordinal,
            seller_sku=(
                f"{10_000 + style_ordinal}-C{ordinal % 7:02d}-S{ordinal % 16:02d}"
            ),
        )


def iter_source_evidence_keys() -> Iterator[tuple[str, str]]:
    """One summary per Seller SKU and report type, never three title tuples."""

    for key in iter_seller_keys():
        for report_type in ("business_report", "return_report"):
            yield key.seller_sku, report_type


def _sha256_label(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _style_ordinal_for_sku(sku_ordinal: int) -> int:
    if not 0 <= sku_ordinal < 10_304:
        raise ValueError("scale SKU ordinal is out of range")
    if sku_ordinal < 16:
        return 0
    return 1 + ((sku_ordinal - 16) % (SCALE_COUNTS["styles"] - 1))


def build_scale_workbook() -> CatalogWorkbookData:
    """Build the full deterministic XLSX payload without retaining fact rows.

    The workbook contains all 1,700 styles, the 10,304 actual variants implied
    by 10,864 mapped keys and 560 aliases, every one of the 11,200 identity
    decisions, and one aggregated evidence row per key/report type.
    """

    style_rows = tuple(
        (
            f"style-{ordinal:04d}",
            None,
            f"{10_000 + ordinal}",
            f"Synthetic standard style {ordinal:04d}",
            "enabled",
            (16 if ordinal == 0 else None),
            6,
            "2024-01-01",
            "2024-12-30",
            None,
        )
        for ordinal in range(SCALE_COUNTS["styles"])
    )
    sku_rows = tuple(
        (
            f"sku-{ordinal:05d}",
            None,
            f"style-{_style_ordinal_for_sku(ordinal):04d}",
            f"DISPLAY-{ordinal:05d}",
            f"Color {ordinal % 16:02d}",
            f"Size {ordinal % 8:02d}",
            "enabled",
            f"Color {ordinal % 16:02d}",
            _sha256_label(f"color:{ordinal % 16}"),
            f"Size {ordinal % 8:02d}",
            _sha256_label(f"size:{ordinal % 8}"),
            "2024-01-01",
            "2024-12-30",
            None,
        )
        for ordinal in range(10_304)
    )
    mapping_rows: list[tuple[CellValue, ...]] = []
    exception_rows: list[tuple[CellValue, ...]] = []
    for key in iter_seller_keys():
        seller_digest = _sha256_label(key.seller_sku)
        if key.ordinal < SCALE_COUNTS["unmatched"]:
            decision = None
            target = None
            target_check = None
            exclusion_reason = None
            exception_rows.append(
                (
                    f"exception-{key.ordinal:05d}",
                    "unmatched_seller_sku",
                    key.seller_sku,
                    seller_digest,
                    "both",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
            )
        elif key.ordinal < SCALE_COUNTS["unmatched"] + SCALE_COUNTS["excluded"]:
            decision = "excluded"
            target = None
            target_check = None
            exclusion_reason = "Excluded by analytics scale fixture"
        else:
            mapped_ordinal = key.ordinal - (
                SCALE_COUNTS["unmatched"] + SCALE_COUNTS["excluded"]
            )
            sku_ordinal = mapped_ordinal % 10_304
            decision = "mapped"
            target = f"sku-{sku_ordinal:05d}"
            target_check = f"DISPLAY-{sku_ordinal:05d}"
            exclusion_reason = None
        mapping_rows.append(
            (
                f"mapping-{key.ordinal:05d}",
                "analytics-scale",
                "amazon_us",
                key.seller_sku,
                seller_digest,
                decision,
                target,
                target_check,
                "2024-01-01",
                "2024-12-30",
                SCALE_COUNTS["days"],
                36 + int(key.ordinal < 400),
                exclusion_reason,
                None,
            )
        )
    evidence_rows = tuple(
        (
            f"evidence-{key.ordinal:05d}-{report_type}",
            key.seller_sku,
            _sha256_label(key.seller_sku),
            report_type,
            "2024-01-01",
            "2024-12-30",
            SCALE_COUNTS["days"] if report_type == "business_report" else 36,
            3,
            f"Synthetic title {key.ordinal:05d} variant 2",
            _sha256_label(f"title:{key.ordinal}:2:{report_type}"),
            3,
            3,
            3,
            _sha256_label(f"evidence:{key.ordinal}:{report_type}"),
        )
        for key in iter_seller_keys()
        for report_type in ("business_report", "return_report")
    )
    return CatalogWorkbookData(
        rows={
            "生成信息": (
                ("模板版本", "product_catalog_workbook_v1"),
                ("目录导出ID", "analytics-scale-v1"),
                ("站点代码", "SCALE"),
                ("Seller Account", "analytics-scale"),
                ("Marketplace", "amazon_us"),
                ("基础目录版本", None),
                ("来源快照摘要", _sha256_label(fixture_contract_digest())),
                ("规范化规则版本", "catalog_identity_key_v1"),
                ("生成时间", datetime(2026, 8, 19, tzinfo=UTC)),
            ),
            "款式主档": style_rows,
            "SKU变体": sku_rows,
            "SellerSKU映射": tuple(mapping_rows),
            "待处理异常": tuple(exception_rows),
            "来源证据": evidence_rows,
        }
    )


def _batched(
    values: list[dict[str, object]], size: int = 2_000
) -> Iterator[list[dict[str, object]]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _seed_catalog_identities(
    connection: sa.Connection,
    *,
    base_catalog_version_id: int,
    actor_user_id: int,
) -> tuple[int, int]:
    base = (
        connection.execute(
            sa.text(
                """
            SELECT * FROM product_catalog_versions
            WHERE id = :catalog_version_id AND site_id = 1 AND status = 'ready'
            """
            ),
            {"catalog_version_id": base_catalog_version_id},
        )
        .mappings()
        .one()
    )
    version_number = int(
        connection.scalar(
            sa.text(
                "SELECT COALESCE(MAX(version_number), 0) + 1 "
                "FROM product_catalog_versions WHERE site_id = 1"
            )
        )
        or 1
    )
    inserted = connection.execute(
        sa.text(
            """
            INSERT INTO product_catalog_versions (
                site_id, version_number, base_catalog_version_id,
                workbook_schema_version, normalization_manifest_id,
                fact_snapshot_tuple_id, source_import_id, validation_run_id,
                approval_digest, diff_digest, risk, status,
                approved_by_user_id, approved_at, approval_reason, created_at
            ) VALUES (
                1, :version_number, :base_catalog_version_id,
                :workbook_schema_version, :normalization_manifest_id,
                :fact_snapshot_tuple_id, :source_import_id, :validation_run_id,
                :approval_digest, :diff_digest, 'normal', 'ready',
                :actor_user_id, UTC_TIMESTAMP(6),
                'Approve deterministic analytics scale fixture', UTC_TIMESTAMP(6)
            )
            """
        ),
        {
            "version_number": version_number,
            "base_catalog_version_id": base_catalog_version_id,
            "workbook_schema_version": base["workbook_schema_version"],
            "normalization_manifest_id": base["normalization_manifest_id"],
            "fact_snapshot_tuple_id": base["fact_snapshot_tuple_id"],
            "source_import_id": base["source_import_id"],
            "validation_run_id": base["validation_run_id"],
            "approval_digest": hashlib.sha256(b"analytics-scale-approval").digest(),
            "diff_digest": hashlib.sha256(b"analytics-scale-diff").digest(),
            "actor_user_id": actor_user_id,
        },
    )
    if inserted.lastrowid is None:
        raise AssertionError("scale catalog version id was not allocated")
    catalog_version_id = int(inserted.lastrowid)
    style_id_from = int(
        connection.scalar(
            sa.text("SELECT COALESCE(MAX(id), 0) + 1 FROM product_styles")
        )
        or 1
    )
    style_revision_from = int(
        connection.scalar(
            sa.text("SELECT COALESCE(MAX(id), 0) + 1 FROM product_style_revisions")
        )
        or 1
    )
    style_rows: list[dict[str, object]] = []
    for ordinal in range(SCALE_COUNTS["styles"]):
        style_id = style_id_from + ordinal
        revision_id = style_revision_from + ordinal
        style_code = f"SCALE-{ordinal:04d}"
        key_bytes = style_code.encode("utf-8")
        style_rows.append(
            {
                "ordinal": ordinal,
                "style_id": style_id,
                "revision_id": revision_id,
                "style_code": style_code,
                "key_bytes": key_bytes,
                "key_digest": hashlib.sha256(key_bytes).digest(),
                "standard_name": f"Synthetic standard style {ordinal:04d}",
                "actor_user_id": actor_user_id,
                "token": UUID(int=ordinal + 1).bytes,
                "catalog_version_id": catalog_version_id,
            }
        )
    for batch in _batched(style_rows):
        connection.execute(
            sa.text(
                """
                INSERT INTO product_styles (
                    id, site_id, style_code, style_key_sha256, style_key_bytes,
                    standard_name, status, current_revision, created_at, updated_at
                ) VALUES (
                    :style_id, 1, :style_code, :key_digest, :key_bytes,
                    :standard_name, 'enabled', 1, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                )
                """
            ),
            batch,
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO product_style_revisions (
                    id, site_id, style_id, revision, style_code,
                    style_key_sha256, style_key_bytes, standard_name, status,
                    change_reason, actor_user_id, source_import_id,
                    source_command_token, created_at
                ) VALUES (
                    :revision_id, 1, :style_id, 1, :style_code,
                    :key_digest, :key_bytes, :standard_name, 'enabled',
                    'Create analytics scale identity', :actor_user_id, NULL,
                    :token, UTC_TIMESTAMP(6)
                )
                """
            ),
            batch,
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO product_catalog_style_members (
                    catalog_version_id, site_id, style_id, style_revision_id, created_at
                ) VALUES (
                    :catalog_version_id, 1, :style_id, :revision_id, UTC_TIMESTAMP(6)
                )
                """
            ),
            batch,
        )
    sku_id_from = int(
        connection.scalar(sa.text("SELECT COALESCE(MAX(id), 0) + 1 FROM product_skus"))
        or 1
    )
    sku_revision_from = int(
        connection.scalar(
            sa.text("SELECT COALESCE(MAX(id), 0) + 1 FROM product_sku_revisions")
        )
        or 1
    )
    local_by_style: dict[int, int] = {}
    sku_rows: list[dict[str, object]] = []
    for ordinal in range(10_304):
        style_ordinal = _style_ordinal_for_sku(ordinal)
        local = local_by_style.get(style_ordinal, 0)
        local_by_style[style_ordinal] = local + 1
        style_id = style_id_from + style_ordinal
        sku_id = sku_id_from + ordinal
        revision_id = sku_revision_from + ordinal
        display = f"SCALE-DISPLAY-{ordinal:05d}"
        color = f"Color {local:02d}"
        size = "Size 00"
        display_bytes = display.encode("utf-8")
        color_bytes = color.encode("utf-8")
        size_bytes = size.encode("utf-8")
        sku_rows.append(
            {
                "ordinal": ordinal,
                "style_ordinal": style_ordinal,
                "style_id": style_id,
                "sku_id": sku_id,
                "revision_id": revision_id,
                "display": display,
                "display_bytes": display_bytes,
                "display_digest": hashlib.sha256(display_bytes).digest(),
                "color": color,
                "color_bytes": color_bytes,
                "color_digest": hashlib.sha256(color_bytes).digest(),
                "size": size,
                "size_bytes": size_bytes,
                "size_digest": hashlib.sha256(size_bytes).digest(),
                "actor_user_id": actor_user_id,
                "token": uuid4().bytes,
                "catalog_version_id": catalog_version_id,
            }
        )
    for batch in _batched(sku_rows):
        connection.execute(
            sa.text(
                """
                INSERT INTO product_skus (
                    id, site_id, style_id, internal_display_sku,
                    display_key_sha256, display_key_bytes, standard_color,
                    color_key_sha256, color_key_bytes, standard_size,
                    size_key_sha256, size_key_bytes, status, current_revision,
                    created_at, updated_at
                ) VALUES (
                    :sku_id, 1, :style_id, :display,
                    :display_digest, :display_bytes, :color,
                    :color_digest, :color_bytes, :size,
                    :size_digest, :size_bytes, 'enabled', 1,
                    UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                )
                """
            ),
            batch,
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO product_sku_revisions (
                    id, site_id, sku_id, style_id, revision,
                    internal_display_sku, display_key_sha256, display_key_bytes,
                    standard_color, color_key_sha256, color_key_bytes,
                    standard_size, size_key_sha256, size_key_bytes, status,
                    change_reason, actor_user_id, source_import_id,
                    source_command_token, created_at
                ) VALUES (
                    :revision_id, 1, :sku_id, :style_id, 1,
                    :display, :display_digest, :display_bytes,
                    :color, :color_digest, :color_bytes,
                    :size, :size_digest, :size_bytes, 'enabled',
                    'Create analytics scale variant', :actor_user_id, NULL,
                    :token, UTC_TIMESTAMP(6)
                )
                """
            ),
            batch,
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO product_catalog_sku_members (
                    catalog_version_id, site_id, sku_id, sku_revision_id,
                    style_id, created_at
                ) VALUES (
                    :catalog_version_id, 1, :sku_id, :revision_id,
                    :style_id, UTC_TIMESTAMP(6)
                )
                """
            ),
            batch,
        )
    connection.execute(
        sa.text(
            """
            UPDATE product_catalog_publications
            SET current_catalog_version_id = :catalog_version_id,
                catalog_publication_revision = catalog_publication_revision + 1,
                updated_at = UTC_TIMESTAMP(6)
            WHERE site_id = 1
            """
        ),
        {"catalog_version_id": catalog_version_id},
    )
    return catalog_version_id, style_id_from


_FACT_INSERT_GUARDS: Final = (
    "trg_version_rows_terminal_insert",
    "trg_business_rows_terminal_insert",
    "trg_return_rows_terminal_insert",
)


def _drop_fact_insert_guards(connection: sa.Connection) -> tuple[str, ...]:
    definitions: list[str] = []
    for trigger_name in _FACT_INSERT_GUARDS:
        row = (
            connection.exec_driver_sql(f"SHOW CREATE TRIGGER `{trigger_name}`")
            .mappings()
            .one()
        )
        statement = str(row["SQL Original Statement"])
        statement = re.sub(
            r"\ACREATE\s+DEFINER=`[^`]+`@`[^`]+`\s+TRIGGER\s+",
            "CREATE TRIGGER ",
            statement,
            count=1,
            flags=re.IGNORECASE,
        )
        definitions.append(statement)
        connection.exec_driver_sql(f"DROP TRIGGER `{trigger_name}`")
    return tuple(definitions)


def _restore_fact_insert_guards(
    connection: sa.Connection, definitions: tuple[str, ...]
) -> None:
    for statement in definitions:
        connection.exec_driver_sql(statement)
    count = int(
        connection.scalar(
            sa.text(
                """
                SELECT COUNT(*) FROM information_schema.TRIGGERS
                WHERE TRIGGER_SCHEMA=DATABASE()
                  AND TRIGGER_NAME IN (
                    'trg_version_rows_terminal_insert',
                    'trg_business_rows_terminal_insert',
                    'trg_return_rows_terminal_insert'
                  )
                """
            )
        )
        or 0
    )
    if count != len(_FACT_INSERT_GUARDS):
        raise AssertionError("fact insert guards were not restored after scale seed")


def seed_scale_database(
    engine: Engine,
    *,
    base_catalog_version_id: int,
    actor_user_id: int,
) -> ScaleSeedResult:
    """Seed the fixed 4.5M-row fixture using set-based MySQL statements."""

    from app.catalog.return_dedup_repository import (
        FrozenPublicationMember,
        publication_set_digest,
    )

    start_date = date(2024, 1, 1)
    end_date = start_date + timedelta(days=SCALE_COUNTS["days"] - 1)
    with engine.connect() as connection:
        fact_insert_guard_definitions = _drop_fact_insert_guards(connection)
    with engine.begin() as connection:
        for table in (
            "_analytics_scale_return_ordinals",
            "_analytics_scale_keys",
            "_analytics_scale_days",
        ):
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
        connection.exec_driver_sql(
            """
            CREATE TABLE _analytics_scale_days (
                day_ordinal INT UNSIGNED PRIMARY KEY,
                report_date DATE NOT NULL UNIQUE,
                business_dataset_id BIGINT UNSIGNED NOT NULL,
                business_version_id BIGINT UNSIGNED NOT NULL,
                return_dataset_id BIGINT UNSIGNED NOT NULL,
                return_version_id BIGINT UNSIGNED NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE _analytics_scale_keys (
                key_ordinal INT UNSIGNED PRIMARY KEY,
                seller_sku VARCHAR(255) NOT NULL,
                match_bytes VARBINARY(1020) NOT NULL,
                match_sha256 BINARY(32) NOT NULL,
                classification VARCHAR(16) CHARACTER SET ascii
                    COLLATE ascii_bin NOT NULL,
                sku_ordinal INT UNSIGNED NULL,
                UNIQUE KEY uq_scale_seller_sku (seller_sku),
                KEY ix_scale_match (match_sha256)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE _analytics_scale_return_ordinals (
                row_ordinal INT UNSIGNED PRIMARY KEY
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        catalog_version_id, style_id = _seed_catalog_identities(
            connection,
            base_catalog_version_id=base_catalog_version_id,
            actor_user_id=actor_user_id,
        )
        scope_id = int(
            connection.scalar(
                sa.text(
                    "SELECT id FROM report_source_scopes "
                    "WHERE site_id = 1 ORDER BY id LIMIT 1"
                )
            )
            or 0
        )
        if scope_id < 1:
            raise AssertionError(
                "scale fixture requires the approved report source scope"
            )
        dataset_id_from = int(
            connection.scalar(
                sa.text("SELECT COALESCE(MAX(id), 0) + 1 FROM daily_datasets")
            )
            or 1
        )
        version_id_from = int(
            connection.scalar(
                sa.text("SELECT COALESCE(MAX(id), 0) + 1 FROM dataset_versions")
            )
            or 1
        )
        day_rows = [
            {
                "ordinal": ordinal,
                "report_date": start_date + timedelta(days=ordinal),
                "business_dataset_id": dataset_id_from + ordinal * 2,
                "business_version_id": version_id_from + ordinal * 2,
                "return_dataset_id": dataset_id_from + ordinal * 2 + 1,
                "return_version_id": version_id_from + ordinal * 2 + 1,
            }
            for ordinal in range(SCALE_COUNTS["days"])
        ]
        connection.execute(
            sa.text(
                """
                INSERT INTO _analytics_scale_days (
                    day_ordinal, report_date, business_dataset_id,
                    business_version_id, return_dataset_id, return_version_id
                ) VALUES (
                    :ordinal, :report_date, :business_dataset_id,
                    :business_version_id, :return_dataset_id, :return_version_id
                )
                """
            ),
            day_rows,
        )
        key_rows: list[dict[str, object]] = []
        for key in iter_seller_keys():
            if key.ordinal < SCALE_COUNTS["unmatched"]:
                classification = "unmatched"
                sku_ordinal = None
            elif key.ordinal < SCALE_COUNTS["unmatched"] + SCALE_COUNTS["excluded"]:
                classification = "excluded"
                sku_ordinal = None
            else:
                classification = "mapped"
                sku_ordinal = (
                    key.ordinal - SCALE_COUNTS["unmatched"] - SCALE_COUNTS["excluded"]
                ) % 10_304
            encoded = key.seller_sku.encode("utf-8")
            key_rows.append(
                {
                    "ordinal": key.ordinal,
                    "seller_sku": key.seller_sku,
                    "match_bytes": encoded,
                    "match_sha256": hashlib.sha256(encoded).digest(),
                    "classification": classification,
                    "sku_ordinal": sku_ordinal,
                }
            )
        for batch in _batched(key_rows):
            connection.execute(
                sa.text(
                    """
                    INSERT INTO _analytics_scale_keys (
                        key_ordinal, seller_sku, match_bytes, match_sha256,
                        classification, sku_ordinal
                    ) VALUES (
                        :ordinal, :seller_sku, :match_bytes, :match_sha256,
                        :classification, :sku_ordinal
                    )
                    """
                ),
                batch,
            )
        connection.execute(
            sa.text(
                "INSERT INTO _analytics_scale_return_ordinals (row_ordinal) "
                "VALUES (:ordinal)"
            ),
            [{"ordinal": ordinal} for ordinal in range(1_120)],
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO daily_datasets (
                    id, site_id, report_date, report_type, created_at
                )
                SELECT business_dataset_id, 1, report_date,
                       'business_report', UTC_TIMESTAMP(6)
                FROM _analytics_scale_days
                UNION ALL
                SELECT return_dataset_id, 1, report_date,
                       'return_report', UTC_TIMESTAMP(6)
                FROM _analytics_scale_days
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO dataset_versions (
                    id, dataset_id, report_type, version_no, status,
                    data_revision, review_revision, ruleset_version,
                    created_by, created_at, sealed_at
                )
                SELECT business_version_id, business_dataset_id, 'business_report', 1,
                       'published', 0, 0, 'analytics_scale_v1', :actor_user_id,
                       UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                FROM _analytics_scale_days
                UNION ALL
                SELECT return_version_id, return_dataset_id, 'return_report', 1,
                       'published', 0, 0, 'analytics_scale_v1', :actor_user_id,
                       UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                FROM _analytics_scale_days
                """
            ),
            {"actor_user_id": actor_user_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO report_dataset_scope_assignments (
                    dataset_id, site_id, report_source_scope_id, assigned_at
                )
                SELECT business_dataset_id, 1, :scope_id, UTC_TIMESTAMP(6)
                FROM _analytics_scale_days
                UNION ALL
                SELECT return_dataset_id, 1, :scope_id, UTC_TIMESTAMP(6)
                FROM _analytics_scale_days
                """
            ),
            {"scope_id": scope_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO report_publication_revisions (
                    dataset_id, site_id, report_source_scope_id,
                    publication_revision, updated_at
                )
                SELECT business_dataset_id, 1, :scope_id,
                       IF(day_ordinal < 353, 1, 0), UTC_TIMESTAMP(6)
                FROM _analytics_scale_days
                UNION ALL
                SELECT return_dataset_id, 1, :scope_id,
                       IF(day_ordinal < 353, 1, 0), UTC_TIMESTAMP(6)
                FROM _analytics_scale_days
                """
            ),
            {"scope_id": scope_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO dataset_publications (
                    dataset_id, version_id, published_at, version_status
                )
                SELECT business_dataset_id, business_version_id,
                       UTC_TIMESTAMP(6), 'published'
                FROM _analytics_scale_days WHERE day_ordinal < 353
                UNION ALL
                SELECT return_dataset_id, return_version_id,
                       UTC_TIMESTAMP(6), 'published'
                FROM _analytics_scale_days WHERE day_ordinal < 353
                """
            )
        )
        sku_id_from = int(
            connection.scalar(
                sa.text(
                    "SELECT MIN(sku_id) FROM product_catalog_sku_members "
                    "WHERE catalog_version_id = :catalog"
                ),
                {"catalog": catalog_version_id},
            )
            or 0
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO product_catalog_mappings (
                    catalog_version_id, site_id, report_source_scope_id,
                    marketplace_scope_code, seller_sku_match_sha256,
                    seller_sku_match_bytes, sku_id, decision_source,
                    actor_user_id, evidence_digest, created_at
                )
                SELECT :catalog, 1, :scope, 'amazon_us', match_sha256,
                       match_bytes, :sku_id_from + sku_ordinal,
                       'system_candidate', :actor, match_sha256, UTC_TIMESTAMP(6)
                FROM _analytics_scale_keys WHERE classification = 'mapped'
                """
            ),
            {
                "catalog": catalog_version_id,
                "scope": scope_id,
                "sku_id_from": sku_id_from,
                "actor": actor_user_id,
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO product_catalog_exclusions (
                    catalog_version_id, site_id, report_source_scope_id,
                    marketplace_scope_code, seller_sku_match_sha256,
                    seller_sku_match_bytes, reason, actor_user_id,
                    evidence_digest, created_at
                )
                SELECT :catalog, 1, :scope, 'amazon_us', match_sha256,
                       match_bytes, 'Excluded by analytics scale fixture',
                       :actor, match_sha256, UTC_TIMESTAMP(6)
                FROM _analytics_scale_keys WHERE classification = 'excluded'
                """
            ),
            {"catalog": catalog_version_id, "scope": scope_id, "actor": actor_user_id},
        )
        business_row_from = int(
            connection.scalar(
                sa.text("SELECT COALESCE(MAX(id), 0) + 1 FROM version_rows")
            )
            or 1
        )
        return_row_from = business_row_from + SCALE_COUNTS["business_rows"]
        source_key_from = int(
            connection.scalar(
                sa.text("SELECT COALESCE(MAX(id), 0) + 1 FROM report_source_keys")
            )
            or 1
        )
    with engine.begin() as connection:
        connection.exec_driver_sql("SET SESSION unique_checks = 0")
        connection.exec_driver_sql("SET SESSION foreign_key_checks = 0")
        connection.execute(
            sa.text(
                """
                INSERT INTO version_rows (
                    id, version_id, report_type, logical_row_id, row_ordinal,
                    row_state, base_row_id, original_parsed_source_row_id,
                    created_at, updated_at
                )
                SELECT :row_from + days.day_ordinal * 11200 + scale_keys.key_ordinal,
                       days.business_version_id, 'business_report',
                       UNHEX(LPAD(HEX(scale_keys.key_ordinal + 1), 32, '0')),
                       scale_keys.key_ordinal + 1, 'active', NULL, NULL,
                       UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                FROM _analytics_scale_days AS days
                CROSS JOIN _analytics_scale_keys AS scale_keys
                """
            ),
            {"row_from": business_row_from},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO business_report_rows (
                    version_row_id, version_id, report_type, parent_asin,
                    child_asin, title, sku, sessions_total, units_ordered,
                    ordered_product_sales, currency_code, total_order_items
                )
                SELECT :row_from + days.day_ordinal * 11200 + scale_keys.key_ordinal,
                       days.business_version_id, 'business_report',
                       CONCAT('P', LPAD(scale_keys.key_ordinal % 100000, 9, '0')),
                       CONCAT('C', LPAD(scale_keys.key_ordinal % 100000, 9, '0')),
                       CONCAT('Synthetic title ', scale_keys.key_ordinal,
                              ' variant ', days.day_ordinal % 3),
                       scale_keys.seller_sku, 10 + scale_keys.key_ordinal % 20,
                       1 + scale_keys.key_ordinal % 5,
                       CAST((1 + scale_keys.key_ordinal % 5) * 9.75 AS DECIMAL(20,6)),
                       'USD', 1 + scale_keys.key_ordinal % 5
                FROM _analytics_scale_days AS days
                CROSS JOIN _analytics_scale_keys AS scale_keys
                """
            ),
            {"row_from": business_row_from},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO report_source_keys (
                    id, dataset_id, version_id, source_row_id, site_id,
                    report_source_scope_id, report_type, source_key_revision,
                    seller_sku_raw_sha256, seller_sku_match_sha256,
                    seller_sku_match_bytes, normalization_version,
                    collision_group_sha256, created_at
                )
                SELECT :key_from + days.day_ordinal * 11200 + scale_keys.key_ordinal,
                       days.business_dataset_id, days.business_version_id,
                       :row_from + days.day_ordinal * 11200 + scale_keys.key_ordinal,
                       1, :scope, 'business_report', 1,
                       scale_keys.match_sha256, scale_keys.match_sha256,
                       scale_keys.match_bytes,
                       'seller_sku_match_v1', NULL, UTC_TIMESTAMP(6)
                FROM _analytics_scale_days AS days
                CROSS JOIN _analytics_scale_keys AS scale_keys
                """
            ),
            {
                "key_from": source_key_from,
                "row_from": business_row_from,
                "scope": scope_id,
            },
        )
        connection.exec_driver_sql("SET SESSION foreign_key_checks = 1")
        connection.exec_driver_sql("SET SESSION unique_checks = 1")
    with engine.begin() as connection:
        connection.exec_driver_sql("SET SESSION unique_checks = 0")
        connection.exec_driver_sql("SET SESSION foreign_key_checks = 0")
        connection.execute(
            sa.text(
                """
                INSERT INTO version_rows (
                    id, version_id, report_type, logical_row_id, row_ordinal,
                    row_state, base_row_id, original_parsed_source_row_id,
                    created_at, updated_at
                )
                SELECT :row_from + days.day_ordinal * 1120 + ordinals.row_ordinal,
                       days.return_version_id, 'return_report',
                       UNHEX(LPAD(HEX(ordinals.row_ordinal + 1), 32, '0')),
                       ordinals.row_ordinal + 1, 'active', NULL, NULL,
                       UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                FROM _analytics_scale_days AS days
                CROSS JOIN _analytics_scale_return_ordinals AS ordinals
                """
            ),
            {"row_from": return_row_from},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO return_report_rows (
                    version_row_id, version_id, report_type, return_date,
                    order_id, sku, asin, fnsku, product_name, quantity,
                    fulfillment_center_id, detailed_disposition, reason,
                    status, license_plate_number, customer_comments
                )
                SELECT :row_from + days.day_ordinal * 1120 + ordinals.row_ordinal,
                       days.return_version_id, 'return_report',
                       TIMESTAMP(days.report_date) + INTERVAL 12 HOUR,
                       CONCAT('SCALE-', days.day_ordinal, '-', ordinals.row_ordinal),
                       scale_keys.seller_sku,
                       CONCAT('A', LPAD(scale_keys.key_ordinal % 100000, 9, '0')),
                       CONCAT('F', LPAD(scale_keys.key_ordinal % 100000, 9, '0')),
                       CONCAT('Synthetic return ', scale_keys.key_ordinal), 1,
                       'SCALE', 'SELLABLE', 'CUSTOMER_RETURN', 'Completed',
                       CONCAT('LP', days.day_ordinal, '-', ordinals.row_ordinal),
                       CONCAT('Synthetic comment ', ordinals.row_ordinal)
                FROM _analytics_scale_days AS days
                CROSS JOIN _analytics_scale_return_ordinals AS ordinals
                INNER JOIN _analytics_scale_keys AS scale_keys
                    ON scale_keys.key_ordinal =
                       (days.day_ordinal * 1120 + ordinals.row_ordinal) % 11200
                """
            ),
            {"row_from": return_row_from},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO report_source_keys (
                    id, dataset_id, version_id, source_row_id, site_id,
                    report_source_scope_id, report_type, source_key_revision,
                    seller_sku_raw_sha256, seller_sku_match_sha256,
                    seller_sku_match_bytes, normalization_version,
                    collision_group_sha256, created_at
                )
                SELECT :key_from + days.day_ordinal * 1120 + ordinals.row_ordinal,
                       days.return_dataset_id, days.return_version_id,
                       :row_from + days.day_ordinal * 1120 + ordinals.row_ordinal,
                       1, :scope, 'return_report', 1,
                       scale_keys.match_sha256, scale_keys.match_sha256,
                       scale_keys.match_bytes,
                       'seller_sku_match_v1', NULL, UTC_TIMESTAMP(6)
                FROM _analytics_scale_days AS days
                CROSS JOIN _analytics_scale_return_ordinals AS ordinals
                INNER JOIN _analytics_scale_keys AS scale_keys
                    ON scale_keys.key_ordinal =
                       (days.day_ordinal * 1120 + ordinals.row_ordinal) % 11200
                """
            ),
            {
                "key_from": source_key_from + SCALE_COUNTS["business_rows"],
                "row_from": return_row_from,
                "scope": scope_id,
            },
        )
        connection.exec_driver_sql("SET SESSION foreign_key_checks = 1")
        connection.exec_driver_sql("SET SESSION unique_checks = 1")
    with engine.connect() as connection:
        _restore_fact_insert_guards(connection, fact_insert_guard_definitions)
    with engine.connect() as connection:
        member_rows = (
            connection.execute(
                sa.text(
                    """
                SELECT days.return_dataset_id AS dataset_id,
                       days.return_version_id AS published_version_id,
                       revisions.publication_revision,
                       versions.data_revision, days.report_date
                FROM _analytics_scale_days AS days
                INNER JOIN dataset_publications AS publications
                    ON publications.dataset_id = days.return_dataset_id
                   AND publications.version_id = days.return_version_id
                INNER JOIN report_publication_revisions AS revisions
                    ON revisions.dataset_id = days.return_dataset_id
                INNER JOIN dataset_versions AS versions
                    ON versions.id = days.return_version_id
                UNION ALL
                SELECT datasets.id, publications.version_id,
                       revisions.publication_revision, versions.data_revision,
                       datasets.report_date
                FROM daily_datasets AS datasets
                INNER JOIN dataset_publications AS publications
                    ON publications.dataset_id = datasets.id
                INNER JOIN report_publication_revisions AS revisions
                    ON revisions.dataset_id = datasets.id
                INNER JOIN dataset_versions AS versions
                    ON versions.id = publications.version_id
                WHERE datasets.report_type = 'return_report'
                  AND datasets.report_date NOT BETWEEN :from_date AND :to_date
                ORDER BY report_date, dataset_id
                """
                ),
                {"from_date": start_date, "to_date": end_date},
            )
            .mappings()
            .all()
        )
    frozen_members = tuple(
        FrozenPublicationMember(
            dataset_id=int(row["dataset_id"]),
            published_version_id=int(row["published_version_id"]),
            publication_revision=int(row["publication_revision"]),
            version_data_revision=int(row["data_revision"]),
            report_date=row["report_date"],
        )
        for row in member_rows
    )
    publication_digest = publication_set_digest(frozen_members)
    with engine.begin() as connection:
        group_revision_from = int(
            connection.scalar(
                sa.text(
                    "SELECT COALESCE(MAX(id), 0) + 1 FROM return_dedup_group_revisions"
                )
            )
            or 1
        )
        member_id_from = int(
            connection.scalar(
                sa.text(
                    "SELECT COALESCE(MAX(id), 0) + 1 FROM return_dedup_group_members"
                )
            )
            or 1
        )
        return_key_from = source_key_from + SCALE_COUNTS["business_rows"]
        connection.execute(
            sa.text(
                """
                INSERT INTO return_dedup_group_revisions (
                    id, site_id, report_source_scope_id, group_key_sha256,
                    revision, member_set_digest, decision,
                    canonical_source_key_id, reason_code, decided_by_user_id,
                    created_at
                )
                SELECT :revision_from + group_no, 1, :scope,
                       UNHEX(SHA2(CONCAT('scale-group-', group_no), 256)), 1,
                       UNHEX(SHA2(CONCAT('scale-members-', group_no), 256)),
                       IF(group_no < 2044, 'duplicate_of', 'unresolved'),
                       IF(group_no < 2044, :return_key_from + group_no * 2, NULL),
                       IF(group_no < 2044, 'scale_duplicate', NULL),
                       IF(group_no < 2044, :actor, NULL), UTC_TIMESTAMP(6)
                FROM (
                    SELECT days.day_ordinal * 12 + offsets.value AS group_no
                    FROM _analytics_scale_days AS days
                    CROSS JOIN (
                        SELECT 0 value UNION ALL SELECT 1 UNION ALL SELECT 2
                        UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
                        UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
                        UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11
                    ) AS offsets
                    WHERE days.day_ordinal * 12 + offsets.value < 4088
                ) AS scale_groups
                """
            ),
            {
                "revision_from": group_revision_from,
                "scope": scope_id,
                "return_key_from": return_key_from,
                "actor": actor_user_id,
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO return_dedup_group_members (
                    id, group_revision_id, source_key_id, member_order, created_at
                )
                SELECT :member_from + group_no * 2 + member_no,
                       :revision_from + group_no,
                       :return_key_from + group_no * 2 + member_no,
                       member_no + 1, UTC_TIMESTAMP(6)
                FROM (
                    SELECT days.day_ordinal * 12 + offsets.value AS group_no
                    FROM _analytics_scale_days AS days
                    CROSS JOIN (
                        SELECT 0 value UNION ALL SELECT 1 UNION ALL SELECT 2
                        UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
                        UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
                        UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11
                    ) AS offsets
                    WHERE days.day_ordinal * 12 + offsets.value < 4088
                ) AS scale_groups
                CROSS JOIN (SELECT 0 member_no UNION ALL SELECT 1) AS members
                """
            ),
            {
                "member_from": member_id_from,
                "revision_from": group_revision_from,
                "return_key_from": return_key_from,
            },
        )
        snapshot_from = int(
            connection.scalar(
                sa.text("SELECT COALESCE(MAX(id), 0) + 1 FROM return_dedup_snapshots")
            )
            or 1
        )
        checkpoint_id = 0
        previous_id = 0
        snapshot_rows: list[dict[str, object]] = []
        for ordinal in range(365):
            snapshot_id = snapshot_from + ordinal
            if ordinal % 32 == 0:
                checkpoint_id = snapshot_id
                base_snapshot_id = None
                checkpoint_snapshot_id = None
                depth = 0
                kind = "checkpoint"
            else:
                base_snapshot_id = previous_id
                checkpoint_snapshot_id = checkpoint_id
                depth = ordinal % 32
                kind = "delta"
            snapshot_rows.append(
                {
                    "id": snapshot_id,
                    "scope": scope_id,
                    "publication_digest": publication_digest,
                    "base": base_snapshot_id,
                    "checkpoint": checkpoint_snapshot_id,
                    "depth": depth,
                    "kind": kind,
                    "decision_digest": hashlib.sha256(
                        f"scale-decision-{ordinal}".encode("ascii")
                    ).digest(),
                }
            )
            previous_id = snapshot_id
        connection.execute(
            sa.text(
                """
                INSERT INTO return_dedup_snapshots (
                    id, site_id, report_source_scope_id,
                    return_publication_set_digest, rule_version,
                    base_snapshot_id, checkpoint_snapshot_id, delta_depth,
                    snapshot_kind, status, decision_digest, created_at
                ) VALUES (
                    :id, 1, :scope, :publication_digest,
                    'return_event_fingerprint_v1', :base, :checkpoint, :depth,
                    :kind, 'ready', :decision_digest, UTC_TIMESTAMP(6)
                )
                """
            ),
            snapshot_rows,
        )
        checkpoint_rows = [row for row in snapshot_rows if row["kind"] == "checkpoint"]
        for checkpoint in checkpoint_rows:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO return_dedup_snapshot_groups (
                        snapshot_id, group_revision_id, entry_kind, created_at
                    )
                    SELECT :snapshot_id, :revision_from + group_no,
                           'checkpoint', UTC_TIMESTAMP(6)
                    FROM (
                        SELECT days.day_ordinal * 12 + offsets.value AS group_no
                        FROM _analytics_scale_days AS days
                        CROSS JOIN (
                            SELECT 0 value UNION ALL SELECT 1 UNION ALL SELECT 2
                            UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
                            UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
                            UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11
                        ) AS offsets
                        WHERE days.day_ordinal * 12 + offsets.value < 4088
                    ) AS scale_groups
                    """
                ),
                {"snapshot_id": checkpoint["id"], "revision_from": group_revision_from},
            )
        connection.execute(
            sa.text(
                """
                UPDATE return_dedup_publications
                SET current_snapshot_id = :snapshot_id,
                    dedup_publication_revision = dedup_publication_revision + 365,
                    updated_at = UTC_TIMESTAMP(6)
                WHERE site_id = 1 AND report_source_scope_id = :scope
                """
            ),
            {"snapshot_id": snapshot_from + 364, "scope": scope_id},
        )
    return ScaleSeedResult(
        catalog_version_id=catalog_version_id,
        report_source_scope_id=scope_id,
        style_id_with_sixteen_series=style_id,
        business_row_id_from=business_row_from,
        business_row_id_to=return_row_from - 1,
        return_row_id_from=return_row_from,
        return_row_id_to=return_row_from + SCALE_COUNTS["return_rows"] - 1,
        source_key_id_from=source_key_from,
        source_key_id_to=source_key_from
        + SCALE_COUNTS["business_rows"]
        + SCALE_COUNTS["return_rows"]
        - 1,
        snapshot_id_from=snapshot_from,
        snapshot_id_to=snapshot_from + 364,
        from_date=start_date,
        to_date=end_date,
    )


def _measure_twenty(operation: object) -> tuple[list[float], float]:
    if not callable(operation):
        raise TypeError("benchmark operation must be callable")
    for _ in range(3):
        operation()
    values: list[float] = []
    for _ in range(20):
        started = time.perf_counter()
        operation()
        values.append((time.perf_counter() - started) * 1_000)
    return values, percentile_95(values)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _assert_loopback_login_ok(response: httpx2.Response) -> None:
    if response.status_code == 200:
        return

    status_code = int(response.status_code)
    if status_code in _LOOPBACK_LOGIN_ERROR_CODES_BY_STATUS:
        category = f"login_http_{status_code}"
        allowed_error_codes = _LOOPBACK_LOGIN_ERROR_CODES_BY_STATUS[status_code]
    elif 500 <= status_code <= 599:
        category = "login_http_5xx"
        allowed_error_codes = _LOOPBACK_LOGIN_5XX_ERROR_CODES
    else:
        category = "login_http_other"
        allowed_error_codes = frozenset()

    error_code = "unknown"
    try:
        payload: object = response.json()
        if isinstance(payload, Mapping):
            error_payload: object = payload.get("error")
            if isinstance(error_payload, Mapping):
                candidate: object = error_payload.get("code")
                if type(candidate) is str and candidate in allowed_error_codes:
                    error_code = candidate
    except Exception:
        error_code = "unknown"

    raise AssertionError(
        "scale loopback login failed "
        f"category={category} status={status_code} code={error_code}"
    )


def _request_ok(
    client: httpx2.Client, path: str, parameters: dict[str, str]
) -> httpx2.Response:
    response = client.get(path, params=parameters)
    if response.status_code != 200:
        try:
            error_code = str(response.json().get("code", "unknown"))
        except TypeError, ValueError:
            error_code = "unreadable"
        raise AssertionError(
            "loopback scale request failed with status "
            f"{response.status_code} code {error_code}"
        )
    if response.headers.get("X-Identity-Source") != "p0_catalog":
        raise AssertionError("loopback scale response used the wrong identity source")
    return response


def _request_eight_series_ok(
    client: httpx2.Client, path: str, parameters: dict[str, str]
) -> None:
    response = _request_ok(client, path, parameters)
    series = response.json().get("series")
    if not isinstance(series, list) or len(series) != 8:
        raise AssertionError("scale style response did not contain eight series")


def _assert_p95_budget(name: str, p95_ms: float) -> None:
    budget_ms = PERFORMANCE_BUDGET_MS[name]
    if p95_ms > budget_ms:
        raise AssertionError(f"{name} p95 {p95_ms:.3f}ms exceeded {budget_ms:.3f}ms")


def _scale_counts(connection: sa.Connection, seed: ScaleSeedResult) -> dict[str, int]:
    def scalar(
        sql: str,
        parameters: Mapping[str, object] | None = None,
    ) -> int:
        return int(connection.scalar(sa.text(sql), parameters or {}) or 0)

    return {
        "styles": scalar(
            "SELECT COUNT(*) FROM product_catalog_style_members "
            "WHERE catalog_version_id=:catalog",
            {"catalog": seed.catalog_version_id},
        ),
        "seller_sku_keys": scalar("SELECT COUNT(*) FROM _analytics_scale_keys"),
        "days": scalar("SELECT COUNT(*) FROM _analytics_scale_days"),
        "business_rows": scalar(
            "SELECT COUNT(*) FROM version_rows WHERE id BETWEEN :first AND :last",
            {"first": seed.business_row_id_from, "last": seed.business_row_id_to},
        ),
        "return_rows": scalar(
            "SELECT COUNT(*) FROM version_rows WHERE id BETWEEN :first AND :last",
            {"first": seed.return_row_id_from, "last": seed.return_row_id_to},
        ),
        "aliases": scalar(
            """
            SELECT COUNT(*) - COUNT(DISTINCT sku_id)
            FROM product_catalog_mappings WHERE catalog_version_id=:catalog
            """,
            {"catalog": seed.catalog_version_id},
        ),
        "unmatched": scalar(
            "SELECT COUNT(*) FROM _analytics_scale_keys "
            "WHERE classification='unmatched'"
        ),
        "excluded": scalar(
            "SELECT COUNT(*) FROM _analytics_scale_keys WHERE classification='excluded'"
        ),
        "duplicate_candidate_members": scalar(
            """
            SELECT COUNT(*) FROM return_dedup_group_members AS members
            INNER JOIN return_dedup_group_revisions AS revisions
                ON revisions.id=members.group_revision_id
            WHERE revisions.id >= :first AND revisions.id < :first + 4088
            """,
            {
                "first": scalar(
                    """
                    SELECT MIN(group_revision_id)
                    FROM return_dedup_snapshot_groups
                    WHERE snapshot_id=:snapshot
                    """,
                    {"snapshot": seed.snapshot_id_from},
                )
            },
        ),
        "duplicate_canonical_members": scalar(
            """
            SELECT COUNT(*) FROM return_dedup_group_members AS members
            INNER JOIN return_dedup_group_revisions AS revisions
                ON revisions.id=members.group_revision_id
            WHERE revisions.decision='duplicate_of'
              AND revisions.id >= (
                SELECT MIN(group_revision_id) FROM return_dedup_snapshot_groups
                WHERE snapshot_id=:snapshot)
              AND revisions.id < (
                SELECT MIN(group_revision_id) + 4088 FROM return_dedup_snapshot_groups
                WHERE snapshot_id=:snapshot)
            """,
            {"snapshot": seed.snapshot_id_from},
        ),
        "unresolved_duplicate_members": scalar(
            """
            SELECT COUNT(*) FROM return_dedup_group_members AS members
            INNER JOIN return_dedup_group_revisions AS revisions
                ON revisions.id=members.group_revision_id
            WHERE revisions.decision='unresolved'
              AND revisions.id >= (
                SELECT MIN(group_revision_id) FROM return_dedup_snapshot_groups
                WHERE snapshot_id=:snapshot)
              AND revisions.id < (
                SELECT MIN(group_revision_id) + 4088 FROM return_dedup_snapshot_groups
                WHERE snapshot_id=:snapshot)
            """,
            {"snapshot": seed.snapshot_id_from},
        ),
        "missing_days": scalar(
            """
            SELECT COUNT(*) FROM _analytics_scale_days AS days
            WHERE NOT EXISTS (
                SELECT 1 FROM dataset_publications AS publications
                WHERE publications.dataset_id=days.business_dataset_id)
            """
        ),
        "max_series": scalar(
            """
            SELECT COUNT(*) FROM product_catalog_sku_members
            WHERE catalog_version_id=:catalog AND style_id=:style
            """,
            {
                "catalog": seed.catalog_version_id,
                "style": seed.style_id_with_sixteen_series,
            },
        ),
        "source_evidence": SCALE_COUNTS["source_evidence"],
    }


def _git_output(*arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise ValueError("release source identity could not be derived from Git")
    return completed.stdout


def _git_binary_output(*arguments: str) -> bytes:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("release source identity could not be derived from Git")
    return completed.stdout


def release_source_identity(source_sha: str | None = None) -> dict[str, str]:
    """Derive immutable release identity from an exact clean Git checkout."""

    source = (
        source_sha
        if source_sha is not None
        else os.getenv("APP_RELEASE_SOURCE_SHA", "")
    )
    if re.fullmatch(r"[0-9a-f]{40}", source) is None:
        raise ValueError("source_sha must be a full lowercase Git SHA")
    head = str(_git_output("rev-parse", "HEAD")).strip()
    if head != source:
        raise ValueError("source_sha does not match checkout HEAD")
    dirty = str(_git_output("status", "--porcelain")).strip()
    if dirty:
        raise ValueError("release source checkout has tracked changes")

    git_tree = str(_git_output("rev-parse", f"{source}^{{tree}}")).strip()
    tree_listing = _git_binary_output("ls-tree", "-r", "--full-tree", source).replace(
        b"\r\n", b"\n"
    )
    if tree_listing and not tree_listing.endswith(b"\n"):
        tree_listing += b"\n"
    artifact_digest = hashlib.sha256(tree_listing).hexdigest()

    manifest = json.loads(
        (REPOSITORY_ROOT / "scripts" / "ci-suite-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    runner_paths = manifest["release_suites"]["performance"]["runner_paths"]
    if not isinstance(runner_paths, list) or not runner_paths:
        raise ValueError("performance runner identity manifest is invalid")
    runner_lines: list[str] = []
    for path in runner_paths:
        if not isinstance(path, str) or not path:
            raise ValueError("performance runner identity path is invalid")
        blob = str(_git_output("rev-parse", f"{source}:{path}")).strip()
        if re.fullmatch(r"[0-9a-f]{40}", blob) is None:
            raise ValueError(f"release runner blob is invalid: {path}")
        runner_lines.append(f"{path}\0{blob}")
    runner_payload = ("\n".join(sorted(runner_lines)) + "\n").encode("utf-8")
    return {
        "source_sha": source,
        "git_tree": git_tree,
        "artifact_digest": artifact_digest,
        "runner_digest": hashlib.sha256(runner_payload).hexdigest(),
    }


def validate_release_evidence_identity(
    evidence: Mapping[str, object], expected: Mapping[str, str]
) -> None:
    """Fail closed when external evidence is not bound to the derived source."""

    for field in ("source_sha", "git_tree", "artifact_digest", "runner_digest"):
        value = evidence.get(field)
        if not isinstance(value, str) or value != expected[field]:
            raise ValueError(f"release evidence {field} is missing or mismatched")


def produce_scale_evidence(
    engine: Engine,
    *,
    runtime_database_url: str,
    seed: ScaleSeedResult,
    username: str,
    password: str,
    output_path: Path,
) -> dict[str, object]:
    """Measure the real loopback API and atomically write sanitized evidence."""

    source_identity = release_source_identity()

    with engine.connect() as connection:
        (
            version,
            version_comment,
            buffer_pool,
            redo_capacity,
            flush_at_commit,
            sync_binlog,
        ) = connection.execute(
            sa.text(
                """
                SELECT @@version, @@version_comment, @@innodb_buffer_pool_size,
                       @@innodb_redo_log_capacity,
                       @@innodb_flush_log_at_trx_commit, @@sync_binlog
                """
            )
        ).one()
        observed_counts = _scale_counts(connection, seed)
        delta_depth_max = int(
            connection.scalar(
                sa.text(
                    "SELECT MAX(delta_depth) FROM return_dedup_snapshots "
                    "WHERE id BETWEEN :first AND :last"
                ),
                {"first": seed.snapshot_id_from, "last": seed.snapshot_id_to},
            )
            or 0
        )
        physical_membership = int(
            connection.scalar(
                sa.text(
                    """
                    SELECT COUNT(DISTINCT members.id)
                    FROM return_dedup_snapshot_groups AS snapshot_groups
                    INNER JOIN return_dedup_group_members AS members
                        ON members.group_revision_id=snapshot_groups.group_revision_id
                    WHERE snapshot_groups.snapshot_id BETWEEN :first AND :last
                    """
                ),
                {"first": seed.snapshot_id_from, "last": seed.snapshot_id_to},
            )
            or 0
        )
        plan = str(
            connection.scalar(
                sa.text(
                    """
                    EXPLAIN ANALYZE
                    SELECT COUNT(*) FROM version_rows
                    WHERE id BETWEEN :first AND :last AND row_state='active'
                    """
                ),
                {"first": seed.business_row_id_from, "last": seed.business_row_id_to},
            )
            or ""
        )
    if observed_counts != SCALE_COUNTS:
        raise AssertionError(f"analytics scale counts drifted: {observed_counts!r}")
    workbook = build_scale_workbook()
    from app.catalog.import_service import project_catalog_workbook
    from app.catalog.workbook import parse_catalog_workbook, render_catalog_workbook

    archive = render_catalog_workbook(workbook)
    parsed = parse_catalog_workbook(archive)
    reparsed = parse_catalog_workbook(render_catalog_workbook(parsed))
    projection = project_catalog_workbook(reparsed)
    xlsx_roundtrip = (
        reparsed.rows == parsed.rows
        and len(reparsed.rows["来源证据"]) == SCALE_COUNTS["source_evidence"]
        and len(projection.rows)
        == sum(len(rows) for name, rows in reparsed.rows.items() if name != "生成信息")
    )
    port = _free_loopback_port()
    backend_root = Path(__file__).resolve().parents[2]
    process_environment = os.environ.copy()
    process_environment.update(
        {
            "APP_DATABASE_URL": runtime_database_url,
            "APP_ENVIRONMENT": "test",
            "APP_LOG_LEVEL": "WARNING",
            "APP_PRODUCT_ANALYTICS_SOURCE": "p0_catalog",
            "APP_SESSION_SECRET": uuid4().hex + uuid4().hex,
            "APP_SESSION_COOKIE_SECURE": "false",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=backend_root,
        env=process_environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        ready = False
        for _ in range(120):
            if process.poll() is not None:
                raise AssertionError("loopback release API stopped before readiness")
            try:
                response = httpx2.get(f"{base_url}/api/health/ready", timeout=1.0)
                if response.status_code == 200:
                    ready = True
                    break
            except httpx2.HTTPError:
                pass
            time.sleep(0.25)
        if not ready:
            raise AssertionError("loopback release API did not become ready")
        with httpx2.Client(base_url=base_url, timeout=120.0) as client:
            csrf = client.get("/api/auth/csrf")
            if csrf.status_code != 200:
                raise AssertionError("scale login CSRF bootstrap failed")
            token = str(csrf.json()["csrf_token"])
            login = client.post(
                "/api/auth/login",
                json={"username": username, "password": password},
                headers={"X-CSRF-Token": token},
            )
            _assert_loopback_login_ok(login)
            published_to = seed.to_date - timedelta(days=SCALE_COUNTS["missing_days"])
            ledger_parameters = {
                "from": (published_to - timedelta(days=30)).isoformat(),
                "to": published_to.isoformat(),
                "return_basis": "report_date",
                "page": "1",
                "page_size": "50",
                "sort": "units",
                "direction": "desc",
            }
            style_path = (
                f"/api/dashboard/styles/{seed.style_id_with_sixteen_series}/card"
            )
            card_31_parameters = {
                "from": (published_to - timedelta(days=30)).isoformat(),
                "to": published_to.isoformat(),
                "return_basis": "report_date",
                "metric": "units",
                "dimension": "color",
            }
            samples: dict[str, list[float]] = {}
            samples["ledger_31d_page50"], ledger_p95 = _measure_twenty(
                lambda: _request_ok(
                    client, "/api/dashboard/style-ledger", ledger_parameters
                )
            )
            _assert_p95_budget("ledger_31d_page50", ledger_p95)
            print(f"analytics scale ledger_31d_page50 p95={ledger_p95:.3f}ms")
            card_365_parameters = {
                **card_31_parameters,
                "from": seed.from_date.isoformat(),
                "to": seed.to_date.isoformat(),
            }
            samples["style_31d_8series"], card_31_p95 = _measure_twenty(
                lambda: _request_eight_series_ok(client, style_path, card_31_parameters)
            )
            _assert_p95_budget("style_31d_8series", card_31_p95)
            print(f"analytics scale style_31d_8series p95={card_31_p95:.3f}ms")
            samples["style_365d_8series"], card_365_p95 = _measure_twenty(
                lambda: _request_eight_series_ok(
                    client, style_path, card_365_parameters
                )
            )
            _assert_p95_budget("style_365d_8series", card_365_p95)
            print(f"analytics scale style_365d_8series p95={card_365_p95:.3f}ms")
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    with engine.connect() as connection:

        def dedup_scan() -> None:
            value = connection.scalar(
                sa.text(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT seller_sku_match_sha256
                        FROM report_source_keys
                        WHERE id BETWEEN :first AND :last
                          AND report_type='return_report'
                        GROUP BY seller_sku_match_sha256
                        HAVING COUNT(*) > 1
                    ) AS candidate_groups
                    """
                ),
                {
                    "first": seed.source_key_id_from + SCALE_COUNTS["business_rows"],
                    "last": seed.source_key_id_to,
                },
            )
            if int(value or 0) != SCALE_COUNTS["seller_sku_keys"]:
                raise AssertionError("dedup staging candidate scan drifted")

        samples["dedup_staging"], dedup_p95 = _measure_twenty(dedup_scan)

    def cas_lock() -> None:
        connection = engine.connect()
        transaction = connection.begin()
        try:
            connection.execute(
                sa.text(
                    """
                    SELECT revisions.dataset_id
                    FROM report_publication_revisions AS revisions
                    INNER JOIN _analytics_scale_days AS days
                        ON days.return_dataset_id=revisions.dataset_id
                    WHERE days.day_ordinal=0 FOR UPDATE
                    """
                )
            ).one()
            connection.execute(
                sa.text(
                    """
                    SELECT site_id FROM return_dedup_publications
                    WHERE site_id=1 AND report_source_scope_id=:scope FOR UPDATE
                    """
                ),
                {"scope": seed.report_source_scope_id},
            ).one()
            connection.execute(
                sa.text(
                    """
                    UPDATE report_publication_revisions AS revisions
                    INNER JOIN _analytics_scale_days AS days
                        ON days.return_dataset_id=revisions.dataset_id
                    SET revisions.publication_revision=
                        revisions.publication_revision + 1
                    WHERE days.day_ordinal=0
                    """
                )
            )
            connection.execute(
                sa.text(
                    """
                    UPDATE return_dedup_publications
                    SET dedup_publication_revision=dedup_publication_revision + 1
                    WHERE site_id=1 AND report_source_scope_id=:scope
                    """
                ),
                {"scope": seed.report_source_scope_id},
            )
        finally:
            transaction.rollback()
            connection.close()

    samples["publication_dedup_cas"], cas_p95 = _measure_twenty(cas_lock)
    p95_values = {
        "ledger_31d_page50": ledger_p95,
        "style_31d_8series": card_31_p95,
        "style_365d_8series": card_365_p95,
        "dedup_staging": dedup_p95,
        "publication_dedup_cas": cas_p95,
    }
    evidence: dict[str, object] = {
        **source_identity,
        "fixture": SCALE_NAME,
        "fixture_seed": SCALE_SEED,
        "fixture_contract_digest": fixture_contract_digest(),
        "counts": observed_counts,
        "mysql_version": "8.0" if str(version).startswith("8.0.") else "8.4",
        "mysql_server_version": str(version),
        "mysql_version_comment_sha256": hashlib.sha256(
            str(version_comment).encode("utf-8")
        ).hexdigest(),
        "cpu_count": 4,
        "memory_bytes": 8 * 1024**3,
        "buffer_pool_bytes": int(buffer_pool),
        "redo_log_capacity_bytes": int(redo_capacity),
        "innodb_flush_log_at_trx_commit": int(flush_at_commit),
        "sync_binlog": int(sync_binlog),
        "loopback_release_api": True,
        "warmup_samples": 3,
        "measured_samples": 20,
        "p95_ms": p95_values,
        "sample_digest": {
            name: hashlib.sha256(
                json.dumps(values, separators=(",", ":")).encode("ascii")
            ).hexdigest()
            for name, values in samples.items()
        },
        "dedup_successors": 365,
        "delta_depth_max": delta_depth_max,
        "physical_group_membership": physical_membership,
        "explain_analyze_bounded": (
            "Index range scan" in plan and "Table scan on version_rows" not in plan
        ),
        "explain_analyze_sha256": hashlib.sha256(plan.encode("utf-8")).hexdigest(),
        "xlsx_excel_roundtrip": xlsx_roundtrip,
        "xlsx_sha256": hashlib.sha256(archive).hexdigest(),
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(evidence, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(output_path)
    return evidence


def fixture_contract_digest() -> str:
    payload = {
        "counts": SCALE_COUNTS,
        "name": SCALE_NAME,
        "seed": SCALE_SEED,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def percentile_95(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if len(ordered) != 20:
        raise ValueError("release p95 requires exactly 20 measured samples")
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def assert_release_profile(
    *,
    mysql_version: str,
    version_comment: str,
    buffer_pool_bytes: int,
    cpu_count: int,
    memory_bytes: int,
) -> None:
    if not mysql_version.startswith(("8.0.", "8.4.")):
        raise AssertionError("performance profile requires Oracle MySQL 8.0/8.4")
    if "mysql" not in version_comment.casefold():
        raise AssertionError("performance profile rejected a non-Oracle server")
    if cpu_count != 4 or memory_bytes != 8 * 1024**3:
        raise AssertionError("performance profile must be exactly 4 vCPU and 8 GiB")
    if buffer_pool_bytes != 2 * 1024**3:
        raise AssertionError("performance profile must use a 2 GiB buffer pool")


__all__ = (
    "PERFORMANCE_BUDGET_MS",
    "SCALE_COUNTS",
    "SCALE_NAME",
    "SCALE_SEED",
    "ScaleSeedResult",
    "assert_release_profile",
    "build_scale_workbook",
    "fixture_contract_digest",
    "iter_seller_keys",
    "iter_source_evidence_keys",
    "percentile_95",
    "produce_scale_evidence",
    "release_source_identity",
    "seed_scale_database",
    "validate_release_evidence_identity",
)
