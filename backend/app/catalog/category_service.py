# ruff: noqa: E501
"""Site-scoped product-category dictionary and audit operations."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.catalog.canonical_json import canonical_json_bytes


class CatalogCategoryError(RuntimeError):
    code = "catalog_category_invalid"

    def __init__(self, code: str | None = None) -> None:
        if code is not None:
            self.code = code
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CatalogCategory:
    category_id: int
    code: str
    display_name: str
    aliases: tuple[str, ...]
    status: str
    parent_category_id: int | None = None


class _GroupedCategory(TypedDict):
    code: str
    name: str
    status: str
    aliases: list[str]
    parent: int | None


_CODE = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")


def normalize_category_code(value: str) -> str:
    code = unicodedata.normalize("NFKC", value).strip().upper()
    if not _CODE.fullmatch(code):
        raise CatalogCategoryError()
    return code


def normalize_alias_key(value: str) -> str:
    key = unicodedata.normalize("NFKC", value).strip().casefold()
    if not key or len(key) > 128:
        raise CatalogCategoryError()
    return key


def _name(value: str) -> str:
    result = unicodedata.normalize("NFKC", value).strip()
    if not result or len(result) > 128:
        raise CatalogCategoryError()
    return result


def _audit(
    connection: Connection,
    *,
    site_id: int,
    actor_user_id: int,
    event_kind: str,
    category_id: int,
    operation_token: UUID,
    payload: dict[str, object],
) -> None:
    safe = canonical_json_bytes(payload)
    digest = hashlib.sha256(
        event_kind.encode("ascii") + operation_token.bytes + safe
    ).digest()
    connection.execute(
        sa.text("""
        INSERT INTO catalog_audit_events (
            site_id, actor_user_id, event_kind, resource_kind, resource_id,
            operation_token, safe_payload_json, event_digest
        ) VALUES (
            :site_id, :actor, :kind, 'category', :category_id,
            :token, CAST(:payload AS JSON), :digest
        )
    """),
        {
            "site_id": site_id,
            "actor": actor_user_id,
            "kind": event_kind,
            "category_id": category_id,
            "token": operation_token.bytes,
            "payload": safe.decode("utf-8"),
            "digest": digest,
        },
    )


def _check_parent(
    connection: Connection,
    site_id: int,
    parent_id: int | None,
    category_id: int | None = None,
) -> None:
    # Serialize hierarchy changes within a site; use category rows with write grants.
    rows = (
        connection.execute(
            sa.text(
                "SELECT id,parent_category_id,status FROM product_categories WHERE site_id=:site_id ORDER BY id FOR UPDATE"
            ),
            {"site_id": site_id},
        )
        .mappings()
        .all()
    )
    if parent_id is None:
        return
    parent = next((row for row in rows if row["id"] == parent_id), None)
    if (
        parent_id == category_id
        or parent is None
        or parent["parent_category_id"] is not None
        or parent["status"] != "enabled"
    ):
        raise CatalogCategoryError("catalog_category_invalid")
    if category_id is not None and any(
        row["parent_category_id"] == category_id for row in rows
    ):
        raise CatalogCategoryError("catalog_category_invalid")


def category_parent_snapshot(
    connection: Connection, site_id: int, category_id: int | None
) -> str | None:
    import json

    row = (
        connection.execute(
            sa.text(
                "SELECT parent.id, parent.code, parent.display_name FROM product_categories child JOIN product_categories parent ON parent.id=child.parent_category_id AND parent.site_id=child.site_id WHERE child.id=:id AND child.site_id=:site_id"
            ),
            {"id": category_id, "site_id": site_id},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else json.dumps(dict(row), ensure_ascii=False)


class MySqlCatalogCategoryService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list(self, *, site_id: int) -> tuple[CatalogCategory, ...]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    sa.text("""
                SELECT categories.id, categories.code, categories.display_name,
                       categories.status, categories.parent_category_id, aliases.alias
                FROM product_categories AS categories
                LEFT JOIN product_category_aliases AS aliases
                  ON aliases.category_id = categories.id AND aliases.site_id = categories.site_id
                WHERE categories.site_id = :site_id
                ORDER BY categories.code, aliases.alias_key
            """),
                    {"site_id": site_id},
                )
                .mappings()
                .all()
            )
        grouped: dict[int, _GroupedCategory] = {}
        for row in rows:
            item = grouped.setdefault(
                int(row["id"]),
                {
                    "code": str(row["code"]),
                    "name": str(row["display_name"]),
                    "status": str(row["status"]),
                    "aliases": [],
                    "parent": (
                        None
                        if row["parent_category_id"] is None
                        else int(row["parent_category_id"])
                    ),
                },
            )
            if row["alias"] is not None:
                item["aliases"].append(str(row["alias"]))
        return tuple(
            CatalogCategory(
                key,
                str(value["code"]),
                str(value["name"]),
                tuple(value["aliases"]),
                str(value["status"]),
                value["parent"],
            )
            for key, value in grouped.items()
        )

    def create(
        self,
        *,
        site_id: int,
        actor_user_id: int,
        operation_token: UUID,
        code: str,
        display_name: str,
        aliases: tuple[str, ...],
        parent_category_id: int | None = None,
    ) -> CatalogCategory:
        normalized_code, display = normalize_category_code(code), _name(display_name)
        normalized_aliases = tuple(
            (unicodedata.normalize("NFKC", item).strip(), normalize_alias_key(item))
            for item in aliases
        )
        try:
            with self._engine.begin() as connection:
                _check_parent(connection, site_id, parent_category_id)
                conflict = connection.scalar(
                    sa.text(
                        "SELECT 1 FROM product_category_aliases WHERE site_id=:site_id AND alias_key=:key"
                    ),
                    {"site_id": site_id, "key": normalized_code.casefold()},
                )
                if conflict:
                    raise CatalogCategoryError("catalog_category_conflict")
                inserted = connection.execute(
                    sa.text("""
                    INSERT INTO product_categories (site_id, code, display_name, status, created_by_user_id, updated_by_user_id, parent_category_id)
                    VALUES (:site_id, :code, :name, 'enabled', :actor, :actor, :parent)
                """),
                    {
                        "site_id": site_id,
                        "code": normalized_code,
                        "parent": parent_category_id,
                        "name": display,
                        "actor": actor_user_id,
                    },
                )
                category_id = int(inserted.lastrowid or 0)
                for alias, key in normalized_aliases:
                    alias_as_code = unicodedata.normalize("NFKC", alias).strip().upper()
                    if (
                        _CODE.fullmatch(alias_as_code)
                        and alias_as_code == normalized_code
                    ):
                        continue
                    if _CODE.fullmatch(alias_as_code) and connection.scalar(
                        sa.text(
                            "SELECT 1 FROM product_categories "
                            "WHERE site_id=:site_id AND code=:code"
                        ),
                        {"site_id": site_id, "code": alias_as_code},
                    ):
                        raise CatalogCategoryError("catalog_category_conflict")
                    connection.execute(
                        sa.text(
                            "INSERT INTO product_category_aliases (site_id, category_id, alias, alias_key, created_by_user_id) VALUES (:site_id,:category_id,:alias,:key,:actor)"
                        ),
                        {
                            "site_id": site_id,
                            "category_id": category_id,
                            "alias": alias,
                            "key": key,
                            "actor": actor_user_id,
                        },
                    )
                _audit(
                    connection,
                    site_id=site_id,
                    actor_user_id=actor_user_id,
                    event_kind="category_created",
                    category_id=category_id,
                    operation_token=operation_token,
                    payload={"code": normalized_code, "display_name": display},
                )
        except IntegrityError as error:
            raise CatalogCategoryError("catalog_category_conflict") from error
        return CatalogCategory(
            category_id,
            normalized_code,
            display,
            tuple(item[0] for item in normalized_aliases),
            "enabled",
            parent_category_id,
        )

    def update(
        self,
        *,
        site_id: int,
        category_id: int,
        actor_user_id: int,
        operation_token: UUID,
        display_name: str,
        status: str,
        aliases: tuple[str, ...],
        code: str | None = None,
        parent_category_id: int | None = None,
        update_parent: bool = False,
    ) -> CatalogCategory:
        new_code = normalize_category_code(code) if code is not None else None
        display = _name(display_name)
        if status not in {"enabled", "disabled"}:
            raise CatalogCategoryError()
        normalized_aliases = tuple(
            (unicodedata.normalize("NFKC", item).strip(), normalize_alias_key(item))
            for item in aliases
        )
        try:
            with self._engine.begin() as connection:
                row = (
                    connection.execute(
                        sa.text(
                            "SELECT code,parent_category_id FROM product_categories WHERE id=:id AND site_id=:site_id FOR UPDATE"
                        ),
                        {"id": category_id, "site_id": site_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise CatalogCategoryError("catalog_category_not_found")
                parent_category_id = (
                    parent_category_id
                    if update_parent
                    else row.get("parent_category_id")
                )
                _check_parent(connection, site_id, parent_category_id, category_id)
                new_code = new_code or str(row["code"])
                if connection.scalar(
                    sa.text(
                        "SELECT 1 FROM product_category_aliases WHERE site_id=:site_id AND alias_key=:key AND category_id<>:id"
                    ),
                    {"site_id": site_id, "key": new_code.casefold(), "id": category_id},
                ):
                    raise CatalogCategoryError("catalog_category_conflict")
                connection.execute(
                    sa.text(
                        "UPDATE product_categories SET parent_category_id=:parent,code=:code,display_name=:name,status=:status,updated_by_user_id=:actor WHERE id=:id AND site_id=:site_id"
                    ),
                    {
                        "code": new_code,
                        "parent": parent_category_id,
                        "name": display,
                        "status": status,
                        "actor": actor_user_id,
                        "id": category_id,
                        "site_id": site_id,
                    },
                )
                connection.execute(
                    sa.text(
                        "DELETE FROM product_category_aliases WHERE category_id=:id AND site_id=:site_id"
                    ),
                    {"id": category_id, "site_id": site_id},
                )
                for alias, key in normalized_aliases:
                    if key == new_code.casefold():
                        continue
                    alias_as_code = unicodedata.normalize("NFKC", alias).strip().upper()
                    if _CODE.fullmatch(alias_as_code) and connection.scalar(
                        sa.text(
                            "SELECT 1 FROM product_categories WHERE site_id=:site_id "
                            "AND code=:code AND id<>:id"
                        ),
                        {"site_id": site_id, "code": alias_as_code, "id": category_id},
                    ):
                        raise CatalogCategoryError("catalog_category_conflict")
                    connection.execute(
                        sa.text(
                            "INSERT INTO product_category_aliases (site_id,category_id,alias,alias_key,created_by_user_id) VALUES (:site_id,:id,:alias,:key,:actor)"
                        ),
                        {
                            "site_id": site_id,
                            "id": category_id,
                            "alias": alias,
                            "key": key,
                            "actor": actor_user_id,
                        },
                    )
                _audit(
                    connection,
                    site_id=site_id,
                    actor_user_id=actor_user_id,
                    event_kind="category_updated",
                    category_id=category_id,
                    operation_token=operation_token,
                    payload={
                        "parent_category_id": parent_category_id,
                        "previous_parent_category_id": row.get("parent_category_id"),
                        "previous_code": str(row["code"]),
                        "code": new_code,
                        "display_name": display,
                        "status": status,
                        "aliases": [item[0] for item in normalized_aliases],
                    },
                )
        except IntegrityError as error:
            raise CatalogCategoryError("catalog_category_conflict") from error
        return CatalogCategory(
            category_id,
            new_code,
            display,
            tuple(item[0] for item in normalized_aliases),
            status,
            parent_category_id,
        )


__all__ = (
    "CatalogCategory",
    "CatalogCategoryError",
    "MySqlCatalogCategoryService",
    "normalize_category_code",
)
