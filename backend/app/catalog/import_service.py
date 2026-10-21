"""Pure workbook-to-draft projection shared by XLSX and online imports."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

from app.catalog.canonical_json import CanonicalValue, canonical_json_bytes
from app.catalog.workbook import SHEET_HEADERS, SHEET_HEADERS_V2, CatalogWorkbookData

_SECTION_SHEETS: Final = {
    "styles": "款式主档",
    "skus": "SKU变体",
    "mappings": "SellerSKU映射",
    "exceptions": "待处理异常",
    "evidence": "来源证据",
}

_PAYLOAD_FIELDS: Final = {
    "styles": (
        "row_key",
        "system_style_id",
        "style_code",
        "standard_name",
        "status",
        "candidate_seller_sku_count",
        "source_title_count",
        "first_seen_date",
        "latest_seen_date",
        "change_reason",
    ),
    "skus": (
        "row_key",
        "system_sku_id",
        "style_row_key",
        "internal_display_sku",
        "standard_color",
        "standard_size",
        "status",
        "source_color_preview",
        "source_color_set_sha256",
        "source_size_preview",
        "source_size_set_sha256",
        "first_seen_date",
        "latest_seen_date",
        "change_reason",
    ),
    "mappings": (
        "row_key",
        "seller_account",
        "marketplace",
        "seller_sku_preview",
        "seller_sku_sha256",
        "identity_decision",
        "target_sku_row_key",
        "target_internal_display_sku_check",
        "first_seen_date",
        "latest_seen_date",
        "business_occurrences",
        "return_occurrences",
        "exclusion_reason",
        "change_reason",
    ),
    "exceptions": (
        "row_key",
        "reason_code",
        "seller_sku_preview",
        "seller_sku_sha256",
        "source_report",
        "candidate_style_code",
        "candidate_color",
        "candidate_size",
        "action",
        "target_sku_row_key",
        "corrected_style_code",
        "corrected_standard_color",
        "corrected_standard_size",
        "exclusion_reason",
        "note",
    ),
    "evidence": (
        "row_key",
        "seller_sku_preview",
        "seller_sku_sha256",
        "report_type",
        "first_seen_date",
        "latest_seen_date",
        "occurrence_count",
        "title_distinct_count",
        "latest_title_preview",
        "latest_title_sha256",
        "parent_asin_distinct_count",
        "child_asin_distinct_count",
        "fnsku_distinct_count",
        "evidence_set_sha256",
    ),
}

_PAYLOAD_FIELDS_V2: Final = {
    **_PAYLOAD_FIELDS,
    "styles": (
        "row_key",
        "system_style_id",
        "style_code",
        "standard_name",
        "category_action",
        "category_code",
        "status",
        "candidate_seller_sku_count",
        "source_title_count",
        "first_seen_date",
        "latest_seen_date",
        "change_reason",
    ),
}


@dataclass(frozen=True, slots=True)
class DraftRow:
    section: str
    row_key: str
    row_origin: str
    projection_state: str
    payload: dict[str, CanonicalValue]
    payload_digest: bytes


@dataclass(frozen=True, slots=True)
class DraftIssue:
    section: str
    row_key: str | None
    severity: str
    reason_code: str
    field: str | None
    safe_message: str
    issue_digest: bytes


@dataclass(frozen=True, slots=True)
class DraftProjection:
    rows: tuple[DraftRow, ...]
    issues: tuple[DraftIssue, ...]
    initial_status: str


def _issue(
    *,
    section: str,
    row_key: str,
    reason_code: str,
    field: str,
) -> DraftIssue:
    detail: dict[str, CanonicalValue] = {
        "field": field,
        "safe_message": "A required catalog decision or standard field is missing.",
    }
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "section": section,
                "row_key": row_key,
                "severity": "blocking",
                "reason_code": reason_code,
                "detail": detail,
            }
        )
    ).digest()
    return DraftIssue(
        section,
        row_key,
        "blocking",
        reason_code,
        field,
        str(detail["safe_message"]),
        digest,
    )


def project_catalog_workbook(workbook: CatalogWorkbookData) -> DraftProjection:
    metadata = {str(row[0]): row[1] for row in workbook.rows["生成信息"]}
    version = metadata.get("模板版本")
    fields_by_section = (
        _PAYLOAD_FIELDS_V2
        if version == "product_catalog_workbook_v2"
        else _PAYLOAD_FIELDS
    )
    headers = (
        SHEET_HEADERS_V2 if version == "product_catalog_workbook_v2" else SHEET_HEADERS
    )
    rows: list[DraftRow] = []
    for section, sheet_name in _SECTION_SHEETS.items():
        fields = fields_by_section[section]
        if len(fields) != len(headers[sheet_name]):
            raise RuntimeError("catalog workbook projection field contract drifted")
        for source_row in workbook.rows[sheet_name]:
            payload: dict[str, CanonicalValue] = {}
            for field, value in zip(fields, source_row, strict=True):
                if not (
                    value is None
                    or (isinstance(value, (str, int)) and not isinstance(value, bool))
                ):
                    raise ValueError("catalog draft cell value is invalid")
                payload[field] = value
            if section == "styles":
                if version == "product_catalog_workbook_v1":
                    payload["category_action"] = "keep"
                    payload["category_code"] = None
                else:
                    action = payload.get("category_action")
                    action_map = {
                        "保持原值": "keep",
                        "明确清空": "clear",
                        "选择分类": "set",
                    }
                    if action not in action_map:
                        raise ValueError("catalog category action is invalid")
                    payload["category_action"] = action_map[str(action)]
                    if payload["category_action"] == "set":
                        if (
                            not isinstance(payload.get("category_code"), str)
                            or not payload["category_code"]
                        ):
                            raise ValueError("catalog category code is required")
                    elif payload.get("category_code") is not None:
                        raise ValueError("catalog category code must be blank")
            row_key = payload["row_key"]
            if not isinstance(row_key, str) or not row_key:
                raise ValueError("catalog draft row key is invalid")
            origin = "system"
            if section == "styles" and payload["candidate_seller_sku_count"] is None:
                origin = "user_created"
            if section == "skus" and payload["source_color_set_sha256"] is None:
                origin = "user_created"
            projection_state = "included"
            digest = hashlib.sha256(canonical_json_bytes(payload)).digest()
            rows.append(
                DraftRow(
                    section,
                    row_key,
                    origin,
                    projection_state,
                    payload,
                    digest,
                )
            )
    rows.sort(key=lambda row: (row.section.encode(), row.row_key.encode("utf-8")))
    from app.catalog.projection import compute_reachability

    return validate_draft_rows(compute_reachability(tuple(rows), final=False).rows)


def validate_draft_rows(rows: tuple[DraftRow, ...]) -> DraftProjection:
    """Recompute safe blocking issues for a persisted semantic row snapshot."""

    issues: list[DraftIssue] = []
    for row in rows:
        if row.projection_state == "audit_only":
            continue
        if row.section == "styles" and row.payload.get("standard_name") is None:
            issues.append(
                _issue(
                    section=row.section,
                    row_key=row.row_key,
                    reason_code="required",
                    field="/standard_name",
                )
            )
        elif row.section == "skus":
            for field in (
                "internal_display_sku",
                "standard_color",
                "standard_size",
            ):
                if row.payload.get(field) is None:
                    issues.append(
                        _issue(
                            section=row.section,
                            row_key=row.row_key,
                            reason_code="required",
                            field=f"/{field}",
                        )
                    )
        elif row.section == "mappings" and row.payload.get("identity_decision") is None:
            issues.append(
                _issue(
                    section=row.section,
                    row_key=row.row_key,
                    reason_code="required",
                    field="/identity_decision",
                )
            )
    issues.sort(key=lambda issue: issue.issue_digest)
    return DraftProjection(
        rows,
        tuple(issues),
        "needs_attention" if issues else "validated",
    )


__all__ = (
    "DraftIssue",
    "DraftProjection",
    "DraftRow",
    "project_catalog_workbook",
    "validate_draft_rows",
)
