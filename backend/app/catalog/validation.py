"""Complete approval validation, deterministic diff, and risk primitives."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.import_service import DraftRow, validate_draft_rows
from app.catalog.normalization import catalog_identity_key_v1
from app.catalog.projection import CatalogReachability, compute_reachability


@dataclass(frozen=True, slots=True)
class CatalogValidationIssue:
    section: str
    row_key: str | None
    field: str | None
    reason_code: str


@dataclass(frozen=True, slots=True)
class CatalogApprovalEvaluation:
    reachability: CatalogReachability
    issues: tuple[CatalogValidationIssue, ...]
    diff_digest: bytes
    risk: str


def _value(row: DraftRow, field: str) -> str | None:
    value = row.payload.get(field)
    return value if isinstance(value, str) and value else None


def _diff_digest(rows: tuple[DraftRow, ...]) -> bytes:
    ordered = sorted(
        rows,
        key=lambda row: (row.section.encode("utf-8"), row.row_key.encode("utf-8")),
    )
    return hashlib.sha256(
        canonical_json_bytes(
            [[row.section, row.row_key, row.payload_digest.hex()] for row in ordered]
        )
    ).digest()


def evaluate_approval_rows(
    rows: tuple[DraftRow, ...],
    *,
    existing_style_values: dict[int, tuple[str, str, str]] | None = None,
    existing_sku_values: dict[int, tuple[int, str, str, str, str]] | None = None,
) -> CatalogApprovalEvaluation:
    reachability = compute_reachability(rows, final=True)
    issues: list[CatalogValidationIssue] = []
    basic = validate_draft_rows(reachability.rows)
    for issue in basic.issues:
        issues.append(
            CatalogValidationIssue(
                issue.section,
                issue.row_key,
                issue.field,
                issue.reason_code,
            )
        )

    style_rows = {
        row.row_key: row
        for row in reachability.rows
        if row.section == "styles" and row.projection_state == "included"
    }
    sku_rows = {
        row.row_key: row
        for row in reachability.rows
        if row.section == "skus" and row.projection_state == "included"
    }
    style_keys: dict[bytes, str] = {}
    display_keys: dict[bytes, str] = {}
    variant_keys: dict[tuple[bytes, bytes, bytes], str] = {}
    for row in style_rows.values():
        value = _value(row, "style_code")
        if value is None:
            issues.append(
                CatalogValidationIssue("styles", row.row_key, "/style_code", "required")
            )
            continue
        key = catalog_identity_key_v1(value).utf8
        if key in style_keys:
            issues.append(
                CatalogValidationIssue(
                    "styles", row.row_key, "/style_code", "duplicate_identity"
                )
            )
        style_keys[key] = row.row_key
    for row in sku_rows.values():
        style_key = _value(row, "style_row_key")
        display = _value(row, "internal_display_sku")
        color = _value(row, "standard_color")
        size = _value(row, "standard_size")
        if style_key not in style_rows:
            issues.append(
                CatalogValidationIssue(
                    "skus", row.row_key, "/style_row_key", "invalid_reference"
                )
            )
            continue
        if display is None or color is None or size is None:
            continue
        display_key = catalog_identity_key_v1(display).utf8
        variant_key = (
            catalog_identity_key_v1(
                _value(style_rows[style_key], "style_code") or ""
            ).utf8,
            catalog_identity_key_v1(color).utf8,
            catalog_identity_key_v1(size).utf8,
        )
        if display_key in display_keys:
            issues.append(
                CatalogValidationIssue(
                    "skus", row.row_key, "/internal_display_sku", "duplicate_identity"
                )
            )
        if variant_key in variant_keys:
            issues.append(
                CatalogValidationIssue(
                    "skus", row.row_key, "/standard_color", "duplicate_variant"
                )
            )
        display_keys[display_key] = row.row_key
        variant_keys[variant_key] = row.row_key

    for row in reachability.rows:
        if row.section != "mappings":
            continue
        decision = row.payload.get("identity_decision")
        target = _value(row, "target_sku_row_key")
        if decision == "mapped" and target not in sku_rows:
            issues.append(
                CatalogValidationIssue(
                    "mappings", row.row_key, "/target_sku_row_key", "invalid_reference"
                )
            )
        elif decision == "excluded":
            reason = _value(row, "exclusion_reason")
            if reason is None or len(reason.strip()) < 10:
                issues.append(
                    CatalogValidationIssue(
                        "mappings", row.row_key, "/exclusion_reason", "required"
                    )
                )
        elif decision not in {"mapped", "excluded"}:
            issues.append(
                CatalogValidationIssue(
                    "mappings", row.row_key, "/identity_decision", "required"
                )
            )

    risk = "normal"
    for row in style_rows.values():
        raw_id = _value(row, "system_style_id")
        if raw_id is None or existing_style_values is None:
            continue
        style_id = int(raw_id)
        prior = existing_style_values.get(style_id)
        style_current = (
            _value(row, "style_code") or "",
            _value(row, "standard_name") or "",
            _value(row, "status") or "",
        )
        if prior is not None and (
            prior[0] != style_current[0] or prior[2] != style_current[2]
        ):
            risk = "high"
    for row in sku_rows.values():
        raw_id = _value(row, "system_sku_id")
        if raw_id is None or existing_sku_values is None:
            continue
        sku_id = int(raw_id)
        sku_prior = existing_sku_values.get(sku_id)
        style_row = style_rows.get(_value(row, "style_row_key") or "")
        style_id = int(_value(style_row, "system_style_id") or 0) if style_row else 0
        sku_current = (
            style_id,
            _value(row, "internal_display_sku") or "",
            _value(row, "standard_color") or "",
            _value(row, "standard_size") or "",
            _value(row, "status") or "",
        )
        if sku_prior is not None and sku_prior != sku_current:
            risk = "high"

    issues.sort(
        key=lambda item: (
            item.section.encode("utf-8"),
            b"" if item.row_key is None else item.row_key.encode("utf-8"),
            "" if item.field is None else item.field,
            item.reason_code,
        )
    )
    return CatalogApprovalEvaluation(
        reachability,
        tuple(issues),
        _diff_digest(rows),
        risk,
    )


__all__ = (
    "CatalogApprovalEvaluation",
    "CatalogValidationIssue",
    "evaluate_approval_rows",
)
