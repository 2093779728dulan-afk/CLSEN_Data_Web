from __future__ import annotations

import hashlib

from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.import_service import DraftRow
from app.catalog.projection import compute_reachability


def _row(
    section: str,
    key: str,
    origin: str,
    payload: dict[str, object],
) -> DraftRow:
    return DraftRow(
        section,
        key,
        origin,
        "included",
        payload,  # type: ignore[arg-type]
        hashlib.sha256(canonical_json_bytes(payload)).digest(),
    )


def test_final_reachability_keeps_user_rows_and_audits_unmapped_system_candidates() -> (
    None
):
    rows = (
        _row(
            "styles",
            "style-system",
            "system",
            {"row_key": "style-system", "system_style_id": None},
        ),
        _row(
            "skus",
            "sku-system",
            "system",
            {
                "row_key": "sku-system",
                "system_sku_id": None,
                "style_row_key": "style-system",
            },
        ),
        _row(
            "styles",
            "style-user",
            "user_created",
            {"row_key": "style-user", "system_style_id": None},
        ),
        _row(
            "mappings",
            "mapping-1",
            "system",
            {
                "row_key": "mapping-1",
                "identity_decision": "excluded",
                "target_sku_row_key": None,
            },
        ),
    )
    projection = compute_reachability(rows, final=True)
    assert projection.included_row_keys == ("style-user",)
    assert projection.audit_only_row_keys == ("sku-system", "style-system")
    by_key = {row.row_key: row for row in projection.rows}
    assert by_key["style-user"].projection_state == "included"
    assert by_key["style-system"].projection_state == "audit_only"
    assert by_key["sku-system"].projection_state == "audit_only"
