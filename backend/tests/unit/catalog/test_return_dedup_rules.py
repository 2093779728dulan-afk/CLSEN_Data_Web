from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from app.catalog.return_dedup import (
    RETURN_EVENT_FINGERPRINT_VERSION,
    PriorGroupRevision,
    ReturnEventFields,
    ReturnEventMember,
    build_candidate_groups,
    plan_snapshot_delta,
    return_event_fingerprint_v1,
    validate_duplicate_decision,
)


def _fields() -> ReturnEventFields:
    return ReturnEventFields(
        return_date=datetime(2026, 8, 20, 1, 2, 3, 456789, tzinfo=UTC),
        order_id="sensitive-order",
        sku="SKU-001",
        asin="B000000001",
        fnsku="FNSKU-001",
        product_name="Original product title",
        quantity=1,
        fulfillment_center_id="ONT8",
        detailed_disposition="SELLABLE",
        reason="UNWANTED_ITEM",
        status="Unit returned to inventory",
        license_plate_number="sensitive-license",
        customer_comments="sensitive-comment",
    )


def _member(
    *,
    publication_id: int,
    active_row_id: int,
    source_key_id: int,
    fingerprint: bytes,
) -> ReturnEventMember:
    return ReturnEventMember(
        report_source_scope_id=7,
        publication_id=publication_id,
        report_date=date(2026, 8, publication_id),
        dataset_id=publication_id * 10,
        published_version_id=publication_id * 100,
        active_row_id=active_row_id,
        source_key_id=source_key_id,
        fingerprint=fingerprint,
    )


def test_fingerprint_uses_all_thirteen_typed_fields_and_is_replayable() -> None:
    original = _fields()
    first = return_event_fingerprint_v1(original)
    second = return_event_fingerprint_v1(original)

    assert first == second
    assert first.version == RETURN_EVENT_FINGERPRINT_VERSION
    assert len(first.sha256) == 32
    assert first.canonical_payload == second.canonical_payload
    assert b"2026-08-20T01:02:03.456789Z" in first.canonical_payload

    candidates = (
        replace(
            original,
            return_date=datetime(2026, 8, 20, 1, 2, 4, 456789, tzinfo=UTC),
        ),
        replace(original, order_id="changed-order"),
        replace(original, sku="SKU-002"),
        replace(original, asin="B000000002"),
        replace(original, fnsku="FNSKU-002"),
        replace(original, product_name="Changed title"),
        replace(original, quantity=2),
        replace(original, fulfillment_center_id="LGB8"),
        replace(original, detailed_disposition="DAMAGED"),
        replace(original, reason="DEFECTIVE"),
        replace(original, status="Pending"),
        replace(original, license_plate_number="changed-license"),
        replace(original, customer_comments="changed-comment"),
    )
    for candidate in candidates:
        assert return_event_fingerprint_v1(candidate).sha256 != first.sha256


def test_sensitive_values_do_not_appear_in_fingerprint_repr() -> None:
    fingerprint = return_event_fingerprint_v1(_fields())
    rendered = repr(fingerprint)
    assert "sensitive-order" not in rendered
    assert "sensitive-license" not in rendered
    assert "sensitive-comment" not in rendered


def test_candidate_groups_require_different_publications_and_stable_order() -> None:
    fingerprint = return_event_fingerprint_v1(_fields()).sha256
    same_publication = (
        _member(
            publication_id=1,
            active_row_id=9,
            source_key_id=90,
            fingerprint=fingerprint,
        ),
        _member(
            publication_id=1,
            active_row_id=10,
            source_key_id=100,
            fingerprint=fingerprint,
        ),
    )
    assert build_candidate_groups(same_publication, previous={}) == ()

    members = (
        same_publication[0],
        _member(
            publication_id=2,
            active_row_id=2,
            source_key_id=20,
            fingerprint=fingerprint,
        ),
    )
    groups = build_candidate_groups(tuple(reversed(members)), previous={})
    assert len(groups) == 1
    group = groups[0]
    assert group.revision == 1
    assert group.decision == "unresolved"
    assert group.canonical_source_key_id is None
    assert group.suggested_canonical_source_key_id == 90
    assert group.members == members

    prior = PriorGroupRevision(
        group_key_sha256=group.group_key_sha256,
        revision=4,
        member_set_digest=group.member_set_digest,
        decision="confirmed_distinct",
        canonical_source_key_id=None,
    )
    replay = build_candidate_groups(
        members,
        previous={group.group_key_sha256: prior},
    )[0]
    assert replay.revision == 4
    assert replay.decision == "confirmed_distinct"
    changed = build_candidate_groups(
        (
            *members,
            _member(
                publication_id=3,
                active_row_id=3,
                source_key_id=30,
                fingerprint=fingerprint,
            ),
        ),
        previous={group.group_key_sha256: prior},
    )[0]
    assert changed.revision == 5
    assert changed.decision == "unresolved"


def test_duplicate_decision_rejects_nonmembers_chains_and_cycles() -> None:
    member_ids = frozenset({10, 20, 30})
    validate_duplicate_decision(
        decision="confirmed_distinct",
        canonical_source_key_id=None,
        member_source_key_ids=member_ids,
        canonical_targets={},
    )
    validate_duplicate_decision(
        decision="duplicate_of",
        canonical_source_key_id=10,
        member_source_key_ids=member_ids,
        canonical_targets={},
    )
    with pytest.raises(ValueError):
        validate_duplicate_decision(
            decision="duplicate_of",
            canonical_source_key_id=99,
            member_source_key_ids=member_ids,
            canonical_targets={},
        )
    with pytest.raises(ValueError):
        validate_duplicate_decision(
            decision="duplicate_of",
            canonical_source_key_id=10,
            member_source_key_ids=member_ids,
            canonical_targets={10: 20},
        )
    with pytest.raises(ValueError):
        validate_duplicate_decision(
            decision="duplicate_of",
            canonical_source_key_id=10,
            member_source_key_ids=member_ids,
            canonical_targets={10: 20, 20: 10},
        )


def test_snapshot_plan_checkpoints_before_depth_thirty_two() -> None:
    initial = plan_snapshot_delta(
        previous_snapshot_id=None,
        previous_checkpoint_id=None,
        previous_delta_depth=None,
        previous_groups={},
        current_groups={b"a" * 32: 1},
    )
    assert initial.snapshot_kind == "checkpoint"
    assert initial.delta_depth == 0
    assert initial.entries[0].entry_kind == "checkpoint"

    delta = plan_snapshot_delta(
        previous_snapshot_id=9,
        previous_checkpoint_id=1,
        previous_delta_depth=30,
        previous_groups={b"a" * 32: 1},
        current_groups={b"a" * 32: 2, b"b" * 32: 3},
    )
    assert delta.snapshot_kind == "delta"
    assert delta.delta_depth == 31
    assert {entry.entry_kind for entry in delta.entries} == {"upsert"}

    checkpoint = plan_snapshot_delta(
        previous_snapshot_id=10,
        previous_checkpoint_id=1,
        previous_delta_depth=31,
        previous_groups={b"a" * 32: 2},
        current_groups={b"b" * 32: 3},
    )
    assert checkpoint.snapshot_kind == "checkpoint"
    assert checkpoint.delta_depth == 0
    assert checkpoint.base_snapshot_id is None
    assert checkpoint.checkpoint_snapshot_id is None
