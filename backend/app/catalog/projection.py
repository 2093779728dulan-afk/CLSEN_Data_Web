"""Server-owned catalog draft reachability projection."""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.catalog.import_service import DraftRow


@dataclass(frozen=True, slots=True)
class CatalogReachability:
    rows: tuple[DraftRow, ...]
    included_row_keys: tuple[str, ...]
    audit_only_row_keys: tuple[str, ...]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def compute_reachability(
    rows: tuple[DraftRow, ...],
    *,
    final: bool,
) -> CatalogReachability:
    """Compute the only permitted included/audit-only closure.

    Existing formal identities and user-created rows are roots. Final mapped
    decisions add their SKU target; before final validation an undecided row's
    server-provided candidate target remains a temporary root.
    """

    styles = {row.row_key: row for row in rows if row.section == "styles"}
    skus = {row.row_key: row for row in rows if row.section == "skus"}
    included_styles: set[str] = set()
    included_skus: set[str] = set()

    for row in styles.values():
        if row.row_origin == "user_created" or _text(
            row.payload.get("system_style_id")
        ):
            included_styles.add(row.row_key)
    for row in skus.values():
        if row.row_origin == "user_created" or _text(row.payload.get("system_sku_id")):
            included_skus.add(row.row_key)

    for row in rows:
        if row.section != "mappings":
            continue
        decision = row.payload.get("identity_decision")
        target = _text(row.payload.get("target_sku_row_key"))
        if target is not None and (
            decision == "mapped" or (decision is None and not final)
        ):
            included_skus.add(target)

    for sku_key in tuple(included_skus):
        sku = skus.get(sku_key)
        if sku is not None:
            style_key = _text(sku.payload.get("style_row_key"))
            if style_key is not None:
                included_styles.add(style_key)

    projected: list[DraftRow] = []
    audit_only: list[str] = []
    included: list[str] = []
    for row in rows:
        state = row.projection_state
        if row.section == "styles":
            state = "included" if row.row_key in included_styles else "audit_only"
        elif row.section == "skus":
            state = "included" if row.row_key in included_skus else "audit_only"
        if row.section in {"styles", "skus"}:
            if state == "included":
                included.append(row.row_key)
            else:
                audit_only.append(row.row_key)
        projected.append(replace(row, projection_state=state))

    return CatalogReachability(
        tuple(projected),
        tuple(sorted(included, key=lambda value: value.encode("utf-8"))),
        tuple(sorted(audit_only, key=lambda value: value.encode("utf-8"))),
    )


__all__ = ("CatalogReachability", "compute_reachability")
