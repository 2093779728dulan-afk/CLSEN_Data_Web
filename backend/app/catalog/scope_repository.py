# ruff: noqa: E501
"""Transactional persistence for the immutable P0 report-source scope sidecars."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import IntegrityError

from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.normalization import seller_sku_match_v1
from app.site_context import CurrentSiteContext

_OPERATION_KIND = "confirm_report_source_scope"
_MARKETPLACE = "amazon_us"


class CatalogScopeRepositoryError(RuntimeError):
    code = "catalog_scope_repository_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class ScopeIdempotencyConflict(CatalogScopeRepositoryError):
    code = "idempotency_key_reused"


class ScopeAlreadyConfirmed(CatalogScopeRepositoryError):
    code = "catalog_scope_already_confirmed"


class ScopeRevisionConflict(CatalogScopeRepositoryError):
    code = "catalog_site_config_revision_conflict"


class ScopeIntegrityError(CatalogScopeRepositoryError):
    code = "catalog_scope_integrity_error"


@dataclass(frozen=True, slots=True)
class ScopeRecord:
    report_source_scope_id: int
    site_id: int
    seller_account_scope_key: bytes
    seller_account_display_name: str
    marketplace_scope_code: str
    confirmed_by_user_id: int
    confirmed_at: datetime


@dataclass(frozen=True, slots=True)
class ScopeConfirmationRecord:
    scope: ScopeRecord
    site_config_version_id: int
    site_config_revision: int


@dataclass(frozen=True, slots=True)
class SourceKeyMaterial:
    raw_sha256: bytes
    match_sha256: bytes
    match_bytes: bytes
    normalization_version: str
    collision_group_sha256: bytes


def _mysql_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    if value.utcoffset() is None:
        raise ValueError("database timestamps must be UTC-compatible")
    return value.astimezone(UTC).replace(tzinfo=None)


def _as_bytes(value: object, *, length: int) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ScopeIntegrityError()
    result = bytes(value)
    if len(result) != length:
        raise ScopeIntegrityError()
    return result


def source_key_material(
    report_source_scope_id: int,
    raw_value: str,
) -> SourceKeyMaterial:
    if report_source_scope_id < 1:
        raise ValueError("report_source_scope_id must be positive")
    normalized = seller_sku_match_v1(raw_value)
    collision_payload = (
        b"seller_sku_collision_v1\0"
        + report_source_scope_id.to_bytes(8, "big", signed=False)
        + normalized.utf8
    )
    return SourceKeyMaterial(
        raw_sha256=hashlib.sha256(raw_value.encode("utf-8")).digest(),
        match_sha256=normalized.sha256,
        match_bytes=normalized.utf8,
        normalization_version=normalized.version,
        collision_group_sha256=hashlib.sha256(collision_payload).digest(),
    )


def _scope_row(row: RowMapping) -> ScopeRecord:
    confirmed_at = row["confirmed_at"]
    if not isinstance(confirmed_at, datetime):
        raise ScopeIntegrityError()
    return ScopeRecord(
        report_source_scope_id=int(row["id"]),
        site_id=int(row["site_id"]),
        seller_account_scope_key=_as_bytes(row["seller_account_scope_key"], length=32),
        seller_account_display_name=str(row["seller_account_display_name"]),
        marketplace_scope_code=str(row["marketplace_scope_code"]),
        confirmed_by_user_id=int(row["confirmed_by_user_id"]),
        confirmed_at=confirmed_at.replace(tzinfo=UTC),
    )


def _scope_for_site(
    connection: Connection,
    *,
    site_id: int,
    lock: bool,
) -> ScopeRecord | None:
    # Scope rows are terminal and the runtime identity intentionally has no
    # UPDATE privilege. Their uniqueness is the concurrency boundary.
    del lock
    rows = (
        connection.execute(
            sa.text(
                """
                SELECT id, site_id, seller_account_scope_key,
                       seller_account_display_name, marketplace_scope_code,
                       confirmed_by_user_id, confirmed_at
                FROM report_source_scopes
                WHERE site_id = :site_id
                """
            ),
            {"site_id": site_id},
        )
        .mappings()
        .all()
    )
    if len(rows) > 1:
        raise ScopeIntegrityError()
    return None if not rows else _scope_row(rows[0])


def _effective_scope(
    connection: Connection, scope: ScopeRecord | None
) -> ScopeRecord | None:
    if scope is None:
        return None
    row = (
        connection.execute(
            sa.text(
                "SELECT seller_account_scope_key, seller_account_display_name FROM report_source_scope_corrections WHERE site_id=:site AND report_source_scope_id=:scope"
            ),
            {"site": scope.site_id, "scope": scope.report_source_scope_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return scope
    return replace(
        scope,
        seller_account_scope_key=_as_bytes(row["seller_account_scope_key"], length=32),
        seller_account_display_name=str(row["seller_account_display_name"]),
    )


def ensure_dataset_scope_assignment(
    connection: Connection,
    *,
    dataset_id: int,
    site_id: int,
    occurred_at: datetime,
) -> int | None:
    """Bind one dataset when the site's irreversible scope is confirmed.

    Before initial confirmation legacy dataset work remains available; the
    confirmation transaction backfills every such dataset before it commits.
    """

    scope = _scope_for_site(connection, site_id=site_id, lock=True)
    if scope is None:
        return None
    rows = (
        connection.execute(
            sa.text(
                """
                SELECT id, site_id, report_source_scope_id
                FROM report_dataset_scope_assignments
                WHERE dataset_id = :dataset_id
                """
            ),
            {"dataset_id": dataset_id},
        )
        .mappings()
        .all()
    )
    if len(rows) > 1:
        raise ScopeIntegrityError()
    if rows:
        row = rows[0]
        if (
            int(row["site_id"]) != site_id
            or int(row["report_source_scope_id"]) != scope.report_source_scope_id
        ):
            raise ScopeIntegrityError()
        _ensure_publication_revision(
            connection,
            dataset_id=dataset_id,
            site_id=site_id,
            scope_id=scope.report_source_scope_id,
            occurred_at=occurred_at,
        )
        return int(row["id"])
    inserted = connection.execute(
        sa.text(
            """
            INSERT INTO report_dataset_scope_assignments (
                dataset_id, site_id, report_source_scope_id, assigned_at
            ) VALUES (
                :dataset_id, :site_id, :scope_id, :assigned_at
            )
            """
        ),
        {
            "dataset_id": dataset_id,
            "site_id": site_id,
            "scope_id": scope.report_source_scope_id,
            "assigned_at": _mysql_datetime(occurred_at),
        },
    )
    if inserted.lastrowid is None:
        raise ScopeIntegrityError()
    _ensure_publication_revision(
        connection,
        dataset_id=dataset_id,
        site_id=site_id,
        scope_id=scope.report_source_scope_id,
        occurred_at=occurred_at,
    )
    return int(inserted.lastrowid)


def _ensure_publication_revision(
    connection: Connection,
    *,
    dataset_id: int,
    site_id: int,
    scope_id: int,
    occurred_at: datetime,
) -> None:
    row = (
        connection.execute(
            sa.text(
                """
                SELECT site_id, report_source_scope_id
                FROM report_publication_revisions
                WHERE dataset_id = :dataset_id
                """
            ),
            {"dataset_id": dataset_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is not None:
        if (
            int(row["site_id"]) != site_id
            or int(row["report_source_scope_id"]) != scope_id
        ):
            raise ScopeIntegrityError()
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO report_publication_revisions (
                dataset_id, site_id, report_source_scope_id,
                publication_revision, updated_at
            ) VALUES (
                :dataset_id, :site_id, :scope_id, 0, :updated_at
            )
            """
        ),
        {
            "dataset_id": dataset_id,
            "site_id": site_id,
            "scope_id": scope_id,
            "updated_at": _mysql_datetime(occurred_at),
        },
    )


def append_report_source_key(
    connection: Connection,
    *,
    dataset_id: int,
    version_id: int,
    source_row_id: int,
    report_type: str,
    seller_sku_raw: str,
    source_key_revision: int,
    occurred_at: datetime,
) -> int | None:
    """Append one immutable normalized key revision for an active report row."""

    if report_type not in {"business_report", "return_report"}:
        raise ValueError("unsupported report type")
    if source_key_revision < 0:
        raise ValueError("source_key_revision must be nonnegative")
    assignment_rows = (
        connection.execute(
            sa.text(
                """
                SELECT assignments.site_id, assignments.report_source_scope_id
                FROM report_dataset_scope_assignments AS assignments
                INNER JOIN daily_datasets AS datasets
                    ON datasets.id = assignments.dataset_id
                   AND datasets.site_id = assignments.site_id
                INNER JOIN dataset_versions AS versions
                    ON versions.id = :version_id
                   AND versions.dataset_id = datasets.id
                   AND versions.report_type = datasets.report_type
                WHERE assignments.dataset_id = :dataset_id
                  AND datasets.report_type = :report_type
                """
            ),
            {
                "dataset_id": dataset_id,
                "version_id": version_id,
                "report_type": report_type,
            },
        )
        .mappings()
        .all()
    )
    if not assignment_rows:
        return None
    if len(assignment_rows) != 1:
        raise ScopeIntegrityError()
    assignment = assignment_rows[0]
    site_id = int(assignment["site_id"])
    scope_id = int(assignment["report_source_scope_id"])
    material = source_key_material(scope_id, seller_sku_raw)
    parameters = {
        "dataset_id": dataset_id,
        "version_id": version_id,
        "source_row_id": source_row_id,
        "site_id": site_id,
        "scope_id": scope_id,
        "report_type": report_type,
        "source_key_revision": source_key_revision,
        "raw_sha256": material.raw_sha256,
        "match_sha256": material.match_sha256,
        "match_bytes": material.match_bytes,
        "normalization_version": material.normalization_version,
        "collision_group_sha256": material.collision_group_sha256,
        "created_at": _mysql_datetime(occurred_at),
    }
    savepoint = connection.begin_nested()
    try:
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO report_source_keys (
                    dataset_id, version_id, source_row_id, site_id,
                    report_source_scope_id, report_type, source_key_revision,
                    seller_sku_raw_sha256, seller_sku_match_sha256,
                    seller_sku_match_bytes, normalization_version,
                    collision_group_sha256, created_at
                ) VALUES (
                    :dataset_id, :version_id, :source_row_id, :site_id,
                    :scope_id, :report_type, :source_key_revision,
                    :raw_sha256, :match_sha256, :match_bytes,
                    :normalization_version, :collision_group_sha256, :created_at
                )
                """
            ),
            parameters,
        )
        if inserted.lastrowid is None:
            raise ScopeIntegrityError()
        savepoint.commit()
        return int(inserted.lastrowid)
    except IntegrityError as error:
        savepoint.rollback()
        existing = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, site_id, report_source_scope_id, report_type,
                           seller_sku_raw_sha256, seller_sku_match_sha256,
                           seller_sku_match_bytes, normalization_version,
                           collision_group_sha256
                    FROM report_source_keys
                    WHERE version_id = :version_id
                      AND source_row_id = :source_row_id
                      AND source_key_revision = :source_key_revision
                    """
                ),
                parameters,
            )
            .mappings()
            .one_or_none()
        )
        expected = (
            site_id,
            scope_id,
            report_type,
            material.raw_sha256,
            material.match_sha256,
            material.match_bytes,
            material.normalization_version,
            material.collision_group_sha256,
        )
        if (
            existing is None
            or (
                int(existing["site_id"]),
                int(existing["report_source_scope_id"]),
                str(existing["report_type"]),
                _as_bytes(existing["seller_sku_raw_sha256"], length=32),
                _as_bytes(existing["seller_sku_match_sha256"], length=32),
                bytes(existing["seller_sku_match_bytes"]),
                str(existing["normalization_version"]),
                _as_bytes(existing["collision_group_sha256"], length=32),
            )
            != expected
        ):
            raise ScopeIntegrityError() from error
        return int(existing["id"])


def _backfill_dataset_assignments(
    connection: Connection,
    *,
    scope: ScopeRecord,
    occurred_at: datetime,
) -> None:
    existing = int(
        connection.scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM report_dataset_scope_assignments AS assignments
                INNER JOIN daily_datasets AS datasets
                    ON datasets.id = assignments.dataset_id
                WHERE datasets.site_id = :site_id
                """
            ),
            {"site_id": scope.site_id},
        )
        or 0
    )
    if existing:
        raise ScopeIntegrityError()
    connection.execute(
        sa.text(
            """
            INSERT INTO report_dataset_scope_assignments (
                dataset_id, site_id, report_source_scope_id, assigned_at
            )
            SELECT datasets.id, datasets.site_id, :scope_id, :assigned_at
            FROM daily_datasets AS datasets
            WHERE datasets.site_id = :site_id
            ORDER BY datasets.id
            """
        ),
        {
            "scope_id": scope.report_source_scope_id,
            "site_id": scope.site_id,
            "assigned_at": _mysql_datetime(occurred_at),
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO report_publication_revisions (
                dataset_id, site_id, report_source_scope_id,
                publication_revision, updated_at
            )
            SELECT datasets.id, datasets.site_id, :scope_id, 0, :updated_at
            FROM daily_datasets AS datasets
            WHERE datasets.site_id = :site_id
            ORDER BY datasets.id
            """
        ),
        {
            "scope_id": scope.report_source_scope_id,
            "site_id": scope.site_id,
            "updated_at": _mysql_datetime(occurred_at),
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO return_dedup_publications (
                site_id, report_source_scope_id, current_snapshot_id,
                dedup_publication_revision, updated_at
            ) VALUES (
                :site_id, :scope_id, NULL, 0, :updated_at
            )
            """
        ),
        {
            "site_id": scope.site_id,
            "scope_id": scope.report_source_scope_id,
            "updated_at": _mysql_datetime(occurred_at),
        },
    )


def _backfill_source_keys(
    connection: Connection,
    *,
    site_id: int,
    occurred_at: datetime,
) -> None:
    rows = (
        connection.execute(
            sa.text(
                """
                SELECT datasets.id AS dataset_id, versions.id AS version_id,
                       row_records.id AS source_row_id, datasets.report_type,
                       versions.data_revision AS source_key_revision,
                       CASE datasets.report_type
                           WHEN 'business_report' THEN business_rows.sku
                           ELSE return_rows.sku
                       END AS seller_sku_raw
                FROM daily_datasets AS datasets
                INNER JOIN dataset_versions AS versions
                    ON versions.dataset_id = datasets.id
                   AND versions.report_type = datasets.report_type
                INNER JOIN version_rows AS row_records
                    ON row_records.version_id = versions.id
                   AND row_records.report_type = versions.report_type
                   AND row_records.row_state = 'active'
                LEFT JOIN business_report_rows AS business_rows
                    ON datasets.report_type = 'business_report'
                   AND business_rows.version_id = versions.id
                   AND business_rows.version_row_id = row_records.id
                LEFT JOIN return_report_rows AS return_rows
                    ON datasets.report_type = 'return_report'
                   AND return_rows.version_id = versions.id
                   AND return_rows.version_row_id = row_records.id
                WHERE datasets.site_id = :site_id
                ORDER BY datasets.id, versions.id, row_records.id
                """
            ),
            {"site_id": site_id},
        )
        .mappings()
        .all()
    )
    for row in rows:
        raw = row["seller_sku_raw"]
        if not isinstance(raw, str):
            raise ScopeIntegrityError()
        append_report_source_key(
            connection,
            dataset_id=int(row["dataset_id"]),
            version_id=int(row["version_id"]),
            source_row_id=int(row["source_row_id"]),
            report_type=str(row["report_type"]),
            seller_sku_raw=raw,
            source_key_revision=int(row["source_key_revision"]),
            occurred_at=occurred_at,
        )


class MySqlCatalogScopeRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def status(self, context: CurrentSiteContext) -> ScopeRecord | None:
        with self._engine.connect() as connection:
            return _effective_scope(
                connection,
                _scope_for_site(connection, site_id=context.site_id, lock=False),
            )

    def confirm(
        self,
        context: CurrentSiteContext,
        *,
        operation_token: UUID,
        operation_digest: bytes,
        expected_site_config_revision: int,
        seller_account_scope_key: bytes,
        seller_account_display_name: str,
        marketplace_scope_code: str,
        reason: str,
        occurred_at: datetime,
    ) -> ScopeConfirmationRecord:
        with self._engine.begin() as connection:
            replay = self._claim(
                connection,
                context=context,
                operation_token=operation_token,
                operation_digest=operation_digest,
                occurred_at=occurred_at,
            )
            if replay is not None:
                return replay
            pointer_id = connection.scalar(
                sa.text(
                    """
                    SELECT current_config_version_id
                    FROM site_current_configs
                    WHERE site_id = :site_id
                    FOR UPDATE
                    """
                ),
                {"site_id": context.site_id},
            )
            if pointer_id is None:
                raise ScopeRevisionConflict()
            config = (
                connection.execute(
                    sa.text(
                        """
                        SELECT configs.id, configs.version_number,
                               configs.source_timezone,
                               configs.reporting_timezone,
                               configs.currency_code
                        FROM site_config_versions AS configs
                        WHERE configs.site_id = :site_id
                          AND configs.id = :config_id
                        """
                    ),
                    {"site_id": context.site_id, "config_id": int(pointer_id)},
                )
                .mappings()
                .one_or_none()
            )
            if config is None or int(config["version_number"]) != (
                expected_site_config_revision
            ):
                raise ScopeRevisionConflict()
            scope = _scope_for_site(connection, site_id=context.site_id, lock=True)
            scope = _effective_scope(connection, scope)
            created = scope is None
            if scope is not None:
                if (
                    scope.seller_account_scope_key != seller_account_scope_key
                    or scope.seller_account_display_name != seller_account_display_name
                    or scope.marketplace_scope_code != marketplace_scope_code
                ):
                    raise ScopeAlreadyConfirmed()
                result = ScopeConfirmationRecord(
                    scope=scope,
                    site_config_version_id=int(config["id"]),
                    site_config_revision=int(config["version_number"]),
                )
            else:
                inserted = connection.execute(
                    sa.text(
                        """
                        INSERT INTO report_source_scopes (
                            site_id, seller_account_scope_key,
                            seller_account_display_name, marketplace_scope_code,
                            confirmed_by_user_id, confirmed_at, created_at
                        ) VALUES (
                            :site_id, :scope_key, :display_name, :marketplace,
                            :actor_user_id, :confirmed_at, :created_at
                        )
                        """
                    ),
                    {
                        "site_id": context.site_id,
                        "scope_key": seller_account_scope_key,
                        "display_name": seller_account_display_name,
                        "marketplace": marketplace_scope_code,
                        "actor_user_id": context.principal_user_id,
                        "confirmed_at": _mysql_datetime(occurred_at),
                        "created_at": _mysql_datetime(occurred_at),
                    },
                )
                if inserted.lastrowid is None:
                    raise ScopeIntegrityError()
                scope = ScopeRecord(
                    report_source_scope_id=int(inserted.lastrowid),
                    site_id=context.site_id,
                    seller_account_scope_key=seller_account_scope_key,
                    seller_account_display_name=seller_account_display_name,
                    marketplace_scope_code=marketplace_scope_code,
                    confirmed_by_user_id=context.principal_user_id,
                    confirmed_at=occurred_at.astimezone(UTC),
                )
                _backfill_dataset_assignments(
                    connection,
                    scope=scope,
                    occurred_at=occurred_at,
                )
                _backfill_source_keys(
                    connection,
                    site_id=context.site_id,
                    occurred_at=occurred_at,
                )
                next_revision = int(config["version_number"]) + 1
                new_config = connection.execute(
                    sa.text(
                        """
                        INSERT INTO site_config_versions (
                            site_id, version_number, source_timezone,
                            reporting_timezone, currency_code, effective_at,
                            change_reason, created_by_user_id, created_at
                        ) VALUES (
                            :site_id, :version_number, :source_timezone,
                            :reporting_timezone, :currency_code, :effective_at,
                            :change_reason, :actor_user_id, :created_at
                        )
                        """
                    ),
                    {
                        "site_id": context.site_id,
                        "version_number": next_revision,
                        "source_timezone": config["source_timezone"],
                        "reporting_timezone": config["reporting_timezone"],
                        "currency_code": config["currency_code"],
                        "effective_at": _mysql_datetime(occurred_at),
                        "change_reason": reason,
                        "actor_user_id": context.principal_user_id,
                        "created_at": _mysql_datetime(occurred_at),
                    },
                )
                if new_config.lastrowid is None:
                    raise ScopeIntegrityError()
                new_config_id = int(new_config.lastrowid)
                updated = connection.execute(
                    sa.text(
                        """
                        UPDATE site_current_configs
                        SET current_config_version_id = :new_config_id,
                            updated_by_user_id = :actor_user_id,
                            updated_at = :updated_at
                        WHERE site_id = :site_id
                          AND current_config_version_id = :old_config_id
                        """
                    ),
                    {
                        "new_config_id": new_config_id,
                        "actor_user_id": context.principal_user_id,
                        "updated_at": _mysql_datetime(occurred_at),
                        "site_id": context.site_id,
                        "old_config_id": int(config["id"]),
                    },
                )
                if updated.rowcount != 1:
                    raise ScopeRevisionConflict()
                result = ScopeConfirmationRecord(
                    scope=scope,
                    site_config_version_id=new_config_id,
                    site_config_revision=next_revision,
                )
            self._complete(
                connection,
                context=context,
                operation_token=operation_token,
                operation_digest=operation_digest,
                result=result,
                occurred_at=occurred_at,
                created=created,
            )
            return result

    @staticmethod
    def _claim(
        connection: Connection,
        *,
        context: CurrentSiteContext,
        operation_token: UUID,
        operation_digest: bytes,
        occurred_at: datetime,
    ) -> ScopeConfirmationRecord | None:
        parameters = {
            "operation_token": operation_token.bytes,
            "operation_kind": _OPERATION_KIND,
            "operation_digest": operation_digest,
            "site_id": context.site_id,
            "actor_user_id": context.principal_user_id,
            "created_at": _mysql_datetime(occurred_at),
        }
        savepoint = connection.begin_nested()
        try:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_command_claims (
                        operation_token, operation_kind, operation_digest,
                        site_id, actor_user_id, resource_kind, resource_id,
                        status, created_at
                    ) VALUES (
                        :operation_token, :operation_kind, :operation_digest,
                        :site_id, :actor_user_id, 'report_source_scope', NULL,
                        'completed', :created_at
                    )
                    """
                ),
                parameters,
            )
            savepoint.commit()
            return None
        except IntegrityError:
            savepoint.rollback()
        claim = (
            connection.execute(
                sa.text(
                    """
                    SELECT operation_kind, operation_digest, site_id,
                           actor_user_id, status
                    FROM catalog_command_claims
                    WHERE operation_token = :operation_token
                    """
                ),
                parameters,
            )
            .mappings()
            .one_or_none()
        )
        if claim is None or (
            str(claim["operation_kind"]) != _OPERATION_KIND
            or _as_bytes(claim["operation_digest"], length=32) != operation_digest
            or int(claim["site_id"]) != context.site_id
            or int(claim["actor_user_id"]) != context.principal_user_id
        ):
            raise ScopeIdempotencyConflict()
        if str(claim["status"]) != "completed":
            raise ScopeIntegrityError()
        effect = connection.scalar(
            sa.text(
                """
                SELECT safe_result_json
                FROM catalog_command_effects
                WHERE operation_token = :operation_token
                """
            ),
            parameters,
        )
        if not isinstance(effect, dict):
            if not isinstance(effect, str):
                raise ScopeIntegrityError()
            effect = json.loads(effect)
        scope = _scope_for_site(connection, site_id=context.site_id, lock=False)
        if scope is None:
            raise ScopeIntegrityError()
        # New effects retain their own identity; older effects still refer to
        # the immutable original confirmation, never the latest correction.
        if "seller_account_scope_key_hex" in effect:
            scope = replace(
                scope,
                seller_account_scope_key=bytes.fromhex(
                    effect["seller_account_scope_key_hex"]
                ),
                seller_account_display_name=str(effect["seller_account_display_name"]),
            )
        return ScopeConfirmationRecord(
            scope=scope,
            site_config_version_id=int(effect["site_config_version_id"]),
            site_config_revision=int(effect["site_config_revision"]),
        )

    @staticmethod
    def _complete(
        connection: Connection,
        *,
        context: CurrentSiteContext,
        operation_token: UUID,
        operation_digest: bytes,
        result: ScopeConfirmationRecord,
        occurred_at: datetime,
        created: bool,
    ) -> None:
        payload: dict[str, Any] = {
            "marketplace_scope_code": result.scope.marketplace_scope_code,
            "report_source_scope_id": result.scope.report_source_scope_id,
            "seller_account_display_name": result.scope.seller_account_display_name,
            "seller_account_scope_key_hex": result.scope.seller_account_scope_key.hex(),
            "site_config_revision": result.site_config_revision,
            "site_config_version_id": result.site_config_version_id,
            "status": "confirmed",
        }
        connection.execute(
            sa.text(
                """
                INSERT INTO catalog_command_effects (
                    operation_token, operation_kind, operation_digest,
                    site_id, actor_user_id, response_schema_version,
                    response_status_code, safe_result_json, completed_at
                ) VALUES (
                    :operation_token, :operation_kind, :operation_digest,
                    :site_id, :actor_user_id, 1, 200,
                    :safe_result_json, :completed_at
                )
                """
            ),
            {
                "operation_token": operation_token.bytes,
                "operation_kind": _OPERATION_KIND,
                "operation_digest": operation_digest,
                "site_id": context.site_id,
                "actor_user_id": context.principal_user_id,
                "safe_result_json": json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ),
                "completed_at": _mysql_datetime(occurred_at),
            },
        )
        audit_payload = {
            "created": created,
            "site_config_revision": result.site_config_revision,
        }
        audit_bytes = canonical_json_bytes(audit_payload)
        connection.execute(
            sa.text(
                """
                INSERT INTO catalog_audit_events (
                    site_id, actor_user_id, event_kind, resource_kind,
                    resource_id, operation_token, safe_payload_json,
                    event_digest, created_at
                ) VALUES (
                    :site_id, :actor_user_id, 'catalog.source_scope_confirmed',
                    'report_source_scope', :scope_id, :operation_token,
                    :safe_payload_json, :event_digest, :created_at
                )
                """
            ),
            {
                "site_id": context.site_id,
                "actor_user_id": context.principal_user_id,
                "scope_id": result.scope.report_source_scope_id,
                "operation_token": operation_token.bytes,
                "safe_payload_json": audit_bytes.decode("utf-8"),
                "event_digest": hashlib.sha256(audit_bytes).digest(),
                "created_at": _mysql_datetime(occurred_at),
            },
        )


__all__ = (
    "CatalogScopeRepositoryError",
    "MySqlCatalogScopeRepository",
    "ScopeAlreadyConfirmed",
    "ScopeConfirmationRecord",
    "ScopeIdempotencyConflict",
    "ScopeIntegrityError",
    "ScopeRecord",
    "ScopeRevisionConflict",
    "SourceKeyMaterial",
    "append_report_source_key",
    "ensure_dataset_scope_assignment",
    "source_key_material",
)
