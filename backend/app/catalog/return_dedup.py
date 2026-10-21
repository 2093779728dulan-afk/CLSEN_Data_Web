"""Pure deterministic rules for cross-publication return-event deduplication."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Final, Literal

from app.catalog.canonical_json import canonical_json_bytes

RETURN_EVENT_FINGERPRINT_VERSION: Final = "return_event_fingerprint_v1"

type DedupDecision = Literal["unresolved", "confirmed_distinct", "duplicate_of"]
type SnapshotKind = Literal["checkpoint", "delta"]
type SnapshotEntryKind = Literal["checkpoint", "upsert", "remove"]


def _required_text(value: object) -> str:
    if not isinstance(value, str) or any(
        0xD800 <= ord(character) <= 0xDFFF for character in value
    ):
        raise ValueError("return event text must contain Unicode scalar values")
    return value


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be positive")
    return value


def _digest(value: object, *, label: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError(f"{label} must be binary")
    result = bytes(value)
    if len(result) != 32:
        raise ValueError(f"{label} must be 32 bytes")
    return result


@dataclass(frozen=True, slots=True)
class ReturnEventFields:
    return_date: datetime
    order_id: str = field(repr=False)
    sku: str = field(repr=False)
    asin: str = field(repr=False)
    fnsku: str = field(repr=False)
    product_name: str = field(repr=False)
    quantity: int
    fulfillment_center_id: str = field(repr=False)
    detailed_disposition: str = field(repr=False)
    reason: str = field(repr=False)
    status: str = field(repr=False)
    license_plate_number: str = field(repr=False)
    customer_comments: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.return_date, datetime)
            or self.return_date.tzinfo is None
            or self.return_date.utcoffset() is None
        ):
            raise ValueError("return_date must be timezone-aware")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise ValueError("quantity must be an integer")
        for value in (
            self.order_id,
            self.sku,
            self.asin,
            self.fnsku,
            self.product_name,
            self.fulfillment_center_id,
            self.detailed_disposition,
            self.reason,
            self.status,
            self.license_plate_number,
            self.customer_comments,
        ):
            _required_text(value)


@dataclass(frozen=True, slots=True, repr=False)
class ReturnEventFingerprint:
    version: str
    sha256: bytes
    canonical_payload: bytes = field(repr=False)

    def __repr__(self) -> str:
        return (
            "ReturnEventFingerprint("
            f"version={self.version!r}, sha256={self.sha256.hex()!r})"
        )


def return_event_fingerprint_v1(
    fields: ReturnEventFields,
) -> ReturnEventFingerprint:
    timestamp = fields.return_date.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    payload = canonical_json_bytes(
        {
            "return_date": timestamp,
            "order_id": fields.order_id,
            "sku": fields.sku,
            "asin": fields.asin,
            "fnsku": fields.fnsku,
            "product_name": fields.product_name,
            "quantity": fields.quantity,
            "fulfillment_center_id": fields.fulfillment_center_id,
            "detailed_disposition": fields.detailed_disposition,
            "reason": fields.reason,
            "status": fields.status,
            "license_plate_number": fields.license_plate_number,
            "customer_comments": fields.customer_comments,
        }
    )
    return ReturnEventFingerprint(
        version=RETURN_EVENT_FINGERPRINT_VERSION,
        sha256=hashlib.sha256(payload).digest(),
        canonical_payload=payload,
    )


@dataclass(frozen=True, slots=True)
class ReturnEventMember:
    report_source_scope_id: int
    publication_id: int
    report_date: date
    dataset_id: int
    published_version_id: int
    active_row_id: int
    source_key_id: int
    fingerprint: bytes = field(repr=False)

    def __post_init__(self) -> None:
        for label in (
            "report_source_scope_id",
            "publication_id",
            "dataset_id",
            "published_version_id",
            "active_row_id",
            "source_key_id",
        ):
            _positive(getattr(self, label), label)
        if not isinstance(self.report_date, date):
            raise ValueError("report_date must be a date")
        object.__setattr__(
            self,
            "fingerprint",
            _digest(self.fingerprint, label="fingerprint"),
        )

    @property
    def canonical_order(self) -> tuple[date, int, int, int]:
        return (
            self.report_date,
            self.dataset_id,
            self.published_version_id,
            self.active_row_id,
        )

    def digest_payload(self) -> list[object]:
        return [
            self.publication_id,
            self.report_date.isoformat(),
            self.dataset_id,
            self.published_version_id,
            self.active_row_id,
            self.source_key_id,
        ]


@dataclass(frozen=True, slots=True)
class PriorGroupRevision:
    group_key_sha256: bytes
    revision: int
    member_set_digest: bytes
    decision: DedupDecision
    canonical_source_key_id: int | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "group_key_sha256",
            _digest(self.group_key_sha256, label="group_key_sha256"),
        )
        object.__setattr__(
            self,
            "member_set_digest",
            _digest(self.member_set_digest, label="member_set_digest"),
        )
        _positive(self.revision, "revision")
        validate_duplicate_decision(
            decision=self.decision,
            canonical_source_key_id=self.canonical_source_key_id,
            member_source_key_ids=(
                frozenset()
                if self.canonical_source_key_id is None
                else frozenset({self.canonical_source_key_id})
            ),
            canonical_targets={},
            membership_required=False,
        )


@dataclass(frozen=True, slots=True)
class CandidateGroup:
    report_source_scope_id: int
    group_key_sha256: bytes
    revision: int
    member_set_digest: bytes
    decision: DedupDecision
    canonical_source_key_id: int | None
    suggested_canonical_source_key_id: int
    members: tuple[ReturnEventMember, ...]


def _group_key(scope_id: int, fingerprint: bytes) -> bytes:
    return hashlib.sha256(
        b"return_dedup_group_v1\0"
        + scope_id.to_bytes(8, "big", signed=False)
        + fingerprint
    ).digest()


def _member_set_digest(members: tuple[ReturnEventMember, ...]) -> bytes:
    return hashlib.sha256(
        canonical_json_bytes([member.digest_payload() for member in members])
    ).digest()


def build_candidate_groups(
    members: tuple[ReturnEventMember, ...],
    *,
    previous: Mapping[bytes, PriorGroupRevision],
) -> tuple[CandidateGroup, ...]:
    buckets: dict[tuple[int, bytes], list[ReturnEventMember]] = {}
    for member in members:
        buckets.setdefault(
            (member.report_source_scope_id, member.fingerprint), []
        ).append(member)
    result: list[CandidateGroup] = []
    for (scope_id, fingerprint), bucket in buckets.items():
        if len({member.publication_id for member in bucket}) < 2:
            continue
        ordered = tuple(sorted(bucket, key=lambda member: member.canonical_order))
        key = _group_key(scope_id, fingerprint)
        member_digest = _member_set_digest(ordered)
        prior = previous.get(key)
        if prior is not None and prior.member_set_digest == member_digest:
            revision = prior.revision
            decision = prior.decision
            canonical_source_key_id = prior.canonical_source_key_id
        else:
            revision = 1 if prior is None else prior.revision + 1
            decision = "unresolved"
            canonical_source_key_id = None
        result.append(
            CandidateGroup(
                report_source_scope_id=scope_id,
                group_key_sha256=key,
                revision=revision,
                member_set_digest=member_digest,
                decision=decision,
                canonical_source_key_id=canonical_source_key_id,
                suggested_canonical_source_key_id=ordered[0].source_key_id,
                members=ordered,
            )
        )
    return tuple(sorted(result, key=lambda group: group.group_key_sha256))


def validate_duplicate_decision(
    *,
    decision: str,
    canonical_source_key_id: int | None,
    member_source_key_ids: frozenset[int],
    canonical_targets: Mapping[int, int],
    membership_required: bool = True,
) -> None:
    if decision == "confirmed_distinct":
        if canonical_source_key_id is not None:
            raise ValueError("confirmed_distinct cannot select a canonical member")
    elif decision == "duplicate_of":
        if canonical_source_key_id is None:
            raise ValueError("duplicate_of requires a canonical member")
        if membership_required and canonical_source_key_id not in member_source_key_ids:
            raise ValueError("canonical member is outside the current group")
        if canonical_source_key_id in canonical_targets:
            raise ValueError("duplicate decisions cannot form a chain")
    elif decision == "unresolved":
        if canonical_source_key_id is not None:
            raise ValueError("unresolved cannot select a canonical member")
    else:
        raise ValueError("unsupported dedup decision")

    for start in canonical_targets:
        seen: set[int] = set()
        current = start
        while current in canonical_targets:
            if current in seen:
                raise ValueError("duplicate decisions cannot form a cycle")
            seen.add(current)
            current = canonical_targets[current]


@dataclass(frozen=True, slots=True)
class SnapshotEntryPlan:
    group_key_sha256: bytes
    group_revision_id: int
    entry_kind: SnapshotEntryKind


@dataclass(frozen=True, slots=True)
class SnapshotDeltaPlan:
    snapshot_kind: SnapshotKind
    base_snapshot_id: int | None
    checkpoint_snapshot_id: int | None
    delta_depth: int
    entries: tuple[SnapshotEntryPlan, ...]


def plan_snapshot_delta(
    *,
    previous_snapshot_id: int | None,
    previous_checkpoint_id: int | None,
    previous_delta_depth: int | None,
    previous_groups: Mapping[bytes, int],
    current_groups: Mapping[bytes, int],
) -> SnapshotDeltaPlan:
    if previous_snapshot_id is None:
        if previous_checkpoint_id is not None or previous_delta_depth is not None:
            raise ValueError("initial snapshot lineage is inconsistent")
        checkpoint = True
    else:
        _positive(previous_snapshot_id, "previous_snapshot_id")
        if previous_checkpoint_id is None or previous_delta_depth is None:
            raise ValueError("delta lineage is incomplete")
        _positive(previous_checkpoint_id, "previous_checkpoint_id")
        if previous_delta_depth < 0 or previous_delta_depth > 31:
            raise ValueError("previous delta depth is outside the supported range")
        checkpoint = previous_delta_depth >= 31

    if checkpoint:
        entries = tuple(
            SnapshotEntryPlan(key, revision_id, "checkpoint")
            for key, revision_id in sorted(current_groups.items())
        )
        return SnapshotDeltaPlan(
            snapshot_kind="checkpoint",
            base_snapshot_id=None,
            checkpoint_snapshot_id=None,
            delta_depth=0,
            entries=entries,
        )

    if previous_delta_depth is None:  # narrowed above; keeps static checking explicit
        raise ValueError("delta lineage is incomplete")
    changed: list[SnapshotEntryPlan] = []
    for key, revision_id in sorted(current_groups.items()):
        if previous_groups.get(key) != revision_id:
            changed.append(SnapshotEntryPlan(key, revision_id, "upsert"))
    for key, revision_id in sorted(previous_groups.items()):
        if key not in current_groups:
            changed.append(SnapshotEntryPlan(key, revision_id, "remove"))
    changed.sort(key=lambda entry: (entry.group_key_sha256, entry.entry_kind))
    return SnapshotDeltaPlan(
        snapshot_kind="delta",
        base_snapshot_id=previous_snapshot_id,
        checkpoint_snapshot_id=previous_checkpoint_id,
        delta_depth=previous_delta_depth + 1,
        entries=tuple(changed),
    )


__all__ = (
    "RETURN_EVENT_FINGERPRINT_VERSION",
    "CandidateGroup",
    "PriorGroupRevision",
    "ReturnEventFields",
    "ReturnEventFingerprint",
    "ReturnEventMember",
    "SnapshotDeltaPlan",
    "SnapshotEntryPlan",
    "build_candidate_groups",
    "plan_snapshot_delta",
    "return_event_fingerprint_v1",
    "validate_duplicate_decision",
)
