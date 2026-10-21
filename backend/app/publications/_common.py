from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID


def positive(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be positive")


def nonnegative(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must not be negative")


def optional_positive(value: int | None, field_name: str) -> None:
    if value is not None:
        positive(value, field_name)


def normalise_reason(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("reason must be a string")
    reason = value.strip()
    if not reason:
        raise ValueError("reason must not be blank")
    return reason


def require_uuid(value: UUID, field_name: str = "operation_token") -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{field_name} must be a UUID")


def normalise_timestamp(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def timestamp_payload(value: datetime) -> str:
    canonical = normalise_timestamp(value, "timestamp")
    return canonical.isoformat(timespec="microseconds").replace("+00:00", "Z")


def sha256_digest(payload: object) -> bytes:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).digest()


def require_sha256(value: bytes, field_name: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError(f"{field_name} must be a SHA-256 digest")
    return value


def require_nonblank(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalised = value.strip()
    if not normalised:
        raise ValueError(f"{field_name} must not be blank")
    return normalised
