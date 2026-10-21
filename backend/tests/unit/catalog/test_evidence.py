from __future__ import annotations

import hashlib
from datetime import date
from typing import Literal

from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.evidence import (
    EvidenceObservation,
    aggregate_source_evidence,
    evidence_set_payload,
)
from app.catalog.snapshots import _evidence_payload_json


def _observation(
    *,
    source_row_id: int,
    title: str | None,
    parent_asin: str | None,
    child_asin: str | None,
    fnsku: str | None,
    report_type: Literal["business_report", "return_report"] = "business_report",
    report_date: date = date(2026, 8, 20),
) -> EvidenceObservation:
    return EvidenceObservation(
        report_source_scope_id=7,
        source_key_id=source_row_id,
        report_type=report_type,
        report_date=report_date,
        event_date=(date(2026, 8, 19) if report_type == "return_report" else None),
        dataset_id=10,
        published_version_id=20,
        source_row_id=source_row_id,
        seller_sku="100-Red-S",
        title=title,
        parent_asin=parent_asin,
        child_asin=child_asin,
        fnsku=fnsku,
        source_locator=f"version:20:row:{source_row_id}",
    )


def test_evidence_tuple_order_is_null_then_raw_utf8_and_uses_frozen_jcs() -> None:
    observations = (
        _observation(
            source_row_id=3,
            title="é",
            parent_asin=None,
            child_asin=None,
            fnsku=None,
        ),
        _observation(
            source_row_id=2,
            title="z",
            parent_asin=None,
            child_asin=None,
            fnsku=None,
        ),
        _observation(
            source_row_id=1,
            title=None,
            parent_asin=None,
            child_asin=None,
            fnsku=None,
        ),
    )

    payload = evidence_set_payload(observations)

    assert payload == [
        [None, None, None, None],
        ["z", None, None, None],
        ["é", None, None, None],
    ]
    expected_bytes = canonical_json_bytes(payload)
    assert expected_bytes == (
        b'[[null,null,null,null],["z",null,null,null],["\xc3\xa9",null,null,null]]'
    )


def test_evidence_aggregates_exact_raw_sku_and_report_type_to_one_summary() -> None:
    observations = (
        _observation(
            source_row_id=1,
            title="old title",
            parent_asin="P1",
            child_asin="C1",
            fnsku=None,
            report_date=date(2026, 8, 19),
        ),
        _observation(
            source_row_id=2,
            title="new title",
            parent_asin="P1",
            child_asin="C2",
            fnsku="F1",
            report_date=date(2026, 8, 20),
        ),
        _observation(
            source_row_id=3,
            title="return title",
            parent_asin=None,
            child_asin="C2",
            fnsku="F1",
            report_type="return_report",
        ),
    )

    payload = aggregate_source_evidence(observations)

    assert len(payload.summaries) == 2
    business = next(
        row for row in payload.summaries if row.report_type == "business_report"
    )
    assert business.occurrence_count == 2
    assert business.title_distinct_count == 2
    assert business.child_asin_distinct_count == 2
    assert business.latest_title is not None
    assert business.latest_title.preview == "new title"
    distinct = evidence_set_payload(observations[:2])
    assert business.evidence_set_digest == (
        "sha256:" + hashlib.sha256(canonical_json_bytes(distinct)).hexdigest()
    )


def test_closed_evidence_model_cannot_contain_sensitive_return_fields() -> None:
    fields = set(EvidenceObservation.__dataclass_fields__)

    assert fields.isdisjoint(
        {
            "order_id",
            "fulfillment_center_id",
            "license_plate_number",
            "customer_comments",
        }
    )
    payload = aggregate_source_evidence(
        (
            _observation(
                source_row_id=1,
                title="safe",
                parent_asin=None,
                child_asin="C1",
                fnsku=None,
                report_type="return_report",
            ),
        )
    )
    assert "customer_comments" not in repr(payload)


def test_export_evidence_json_size_does_not_grow_with_observation_rows() -> None:
    payload = aggregate_source_evidence(
        tuple(
            _observation(
                source_row_id=index,
                title="same title",
                parent_asin="P1",
                child_asin="C1",
                fnsku="F1",
            )
            for index in range(1, 1001)
        )
    )

    exported = _evidence_payload_json(payload)

    assert set(exported) == {"summaries"}
    summaries = exported["summaries"]
    assert len(summaries) == 1
    assert summaries[0]["occurrence_count"] == 1000
    assert len(canonical_json_bytes(exported)) < 2_048
