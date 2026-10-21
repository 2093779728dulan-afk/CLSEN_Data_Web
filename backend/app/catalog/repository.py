"""Database repository for stable catalog identities and reservations."""

from __future__ import annotations

import json
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.import_service import DraftRow


class CatalogReservationConflict(RuntimeError):
    code = "catalog_identity_key_reserved"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CatalogIdentityCounts:
    styles: int
    style_revisions: int
    skus: int
    sku_revisions: int
    reservations: int


@dataclass(frozen=True, slots=True)
class CatalogReservation:
    key_kind: str
    key_sha256: bytes
    key_bytes: bytes
    style_id: int | None
    sku_id: int | None


def load_import_rows(
    connection: Connection,
    *,
    import_id: int,
    workflow_revision: int,
) -> tuple[DraftRow, ...]:
    rows = connection.execute(
        sa.text(
            """
            SELECT source.section, source.row_key, source.row_origin,
                   source.projection_state, source.payload_json,
                   source.payload_digest
            FROM catalog_import_rows AS source
            INNER JOIN (
                SELECT section, MAX(workflow_revision) AS row_revision
                FROM catalog_import_rows
                WHERE import_id = :import_id
                  AND workflow_revision <= :workflow_revision
                GROUP BY section
            ) AS latest
              ON latest.section = source.section
             AND latest.row_revision = source.workflow_revision
            WHERE source.import_id = :import_id
            ORDER BY CAST(source.section AS BINARY), CAST(source.row_key AS BINARY)
            """
        ),
        {"import_id": import_id, "workflow_revision": workflow_revision},
    ).mappings()
    result: list[DraftRow] = []
    for row in rows:
        payload = (
            json.loads(row["payload_json"])
            if isinstance(row["payload_json"], str)
            else row["payload_json"]
        )
        if not isinstance(payload, dict):
            raise RuntimeError("catalog draft payload is invalid")
        canonical_json_bytes(payload)
        result.append(
            DraftRow(
                str(row["section"]),
                str(row["row_key"]),
                str(row["row_origin"]),
                str(row["projection_state"]),
                payload,
                bytes(row["payload_digest"]),
            )
        )
    return tuple(result)


class MySqlCatalogRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def identity_counts(self, *, site_id: int) -> CatalogIdentityCounts:
        with self._engine.connect() as connection:
            values = []
            for table in (
                "product_styles",
                "product_style_revisions",
                "product_skus",
                "product_sku_revisions",
                "product_identity_key_reservations",
            ):
                values.append(
                    int(
                        connection.scalar(
                            sa.text(
                                f"SELECT COUNT(*) FROM {table} WHERE site_id = :site_id"
                            ),
                            {"site_id": site_id},
                        )
                        or 0
                    )
                )
        return CatalogIdentityCounts(*values)

    def first_reservation(
        self, *, site_id: int, key_kind: str
    ) -> CatalogReservation | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        "SELECT key_kind, key_sha256, key_bytes, style_id, sku_id "
                        "FROM product_identity_key_reservations "
                        "WHERE site_id = :site_id AND key_kind = :key_kind "
                        "ORDER BY id LIMIT 1"
                    ),
                    {"site_id": site_id, "key_kind": key_kind},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return CatalogReservation(
            str(row["key_kind"]),
            bytes(row["key_sha256"]),
            bytes(row["key_bytes"]),
            None if row["style_id"] is None else int(row["style_id"]),
            None if row["sku_id"] is None else int(row["sku_id"]),
        )

    def assert_reservation_owner(
        self,
        *,
        site_id: int,
        key_kind: str,
        key_sha256: bytes,
        key_bytes: bytes,
        style_id: int | None,
        sku_id: int | None,
    ) -> None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        "SELECT style_id, sku_id "
                        "FROM product_identity_key_reservations "
                        "WHERE site_id = :site_id AND key_kind = :key_kind "
                        "AND key_sha256 = :digest AND key_bytes = :key_bytes"
                    ),
                    {
                        "site_id": site_id,
                        "key_kind": key_kind,
                        "digest": key_sha256,
                        "key_bytes": key_bytes,
                    },
                )
                .mappings()
                .one_or_none()
            )
        if row is None or (
            (None if row["style_id"] is None else int(row["style_id"])) != style_id
            or (None if row["sku_id"] is None else int(row["sku_id"])) != sku_id
        ):
            raise CatalogReservationConflict()


__all__ = (
    "CatalogIdentityCounts",
    "CatalogReservation",
    "CatalogReservationConflict",
    "MySqlCatalogRepository",
    "load_import_rows",
)
