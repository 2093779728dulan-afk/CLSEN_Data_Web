"""Read immutable catalog identity values for a frozen base version."""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection


@dataclass(frozen=True, slots=True)
class CatalogIdentityInventory:
    styles: tuple[dict[str, object], ...]
    skus: tuple[dict[str, object], ...]


def load_catalog_identity_inventory(
    connection: Connection,
    *,
    site_id: int,
    catalog_version_id: int | None,
) -> CatalogIdentityInventory:
    if catalog_version_id is None:
        return CatalogIdentityInventory((), ())
    styles = tuple(
        dict(row)
        for row in connection.execute(
            sa.text(
                """
                SELECT revisions.style_id, revisions.style_code,
                       revisions.standard_name, revisions.status
                FROM product_catalog_style_members AS members
                INNER JOIN product_style_revisions AS revisions
                  ON revisions.id = members.style_revision_id
                 AND revisions.site_id = members.site_id
                WHERE members.catalog_version_id = :version_id
                  AND members.site_id = :site_id
                ORDER BY revisions.style_id
                """
            ),
            {"version_id": catalog_version_id, "site_id": site_id},
        ).mappings()
    )
    skus = tuple(
        dict(row)
        for row in connection.execute(
            sa.text(
                """
                SELECT revisions.sku_id, revisions.style_id, styles.style_code,
                       revisions.internal_display_sku,
                       revisions.standard_color, revisions.standard_size,
                       revisions.status
                FROM product_catalog_sku_members AS members
                INNER JOIN product_sku_revisions AS revisions
                  ON revisions.id = members.sku_revision_id
                 AND revisions.site_id = members.site_id
                INNER JOIN product_catalog_style_members AS style_members
                  ON style_members.style_id = revisions.style_id
                 AND style_members.site_id = members.site_id
                 AND style_members.catalog_version_id = members.catalog_version_id
                INNER JOIN product_style_revisions AS styles
                  ON styles.id = style_members.style_revision_id
                 AND styles.site_id = style_members.site_id
                WHERE members.catalog_version_id = :version_id
                  AND members.site_id = :site_id
                ORDER BY revisions.sku_id
                """
            ),
            {"version_id": catalog_version_id, "site_id": site_id},
        ).mappings()
    )
    return CatalogIdentityInventory(styles, skus)


__all__ = ("CatalogIdentityInventory", "load_catalog_identity_inventory")
