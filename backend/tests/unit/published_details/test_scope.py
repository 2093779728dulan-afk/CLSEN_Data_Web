from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from app.analytics.models import PublicationReference
from app.auth.sessions import Principal
from app.published_details.models import (
    PublishedDetailPagination,
    PublishedDetailQuery,
    PublishedDetailScope,
    PublishedRangeResponse,
)
from app.published_details.scope import (
    PublishedScopeCodec,
    PublishedScopeExpired,
    PublishedScopeInvalid,
)


@dataclass
class Clock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value

    def advance(self, elapsed: timedelta) -> None:
        self.value += elapsed


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 8, 14, 12, tzinfo=UTC))


@pytest.fixture
def codec(clock: Clock) -> PublishedScopeCodec:
    return PublishedScopeCodec(
        secret="unit-test-secret",
        clock=clock,
        ttl=timedelta(minutes=5),
    )


def principal(*, user_id: int = 7, roles: frozenset[str] | None = None) -> Principal:
    return Principal(
        user_id=user_id,
        username="reader",
        display_name="Reader",
        roles=roles or frozenset({"viewer"}),
        session_id=4,
        csrf_token_hash=b"x" * 32,
    )


def query(
    *,
    site_id: int = 3,
    report_type: str = "business_report",
    from_date: date = date(2026, 8, 1),
    to_date: date = date(2026, 8, 2),
) -> PublishedDetailQuery:
    return PublishedDetailQuery(
        site_id=site_id,
        report_type=report_type,  # type: ignore[arg-type]
        from_date=from_date,
        to_date=to_date,
    )


def scope(
    clock: Clock,
    *,
    user_id: int = 7,
    site_id: int = 3,
    roles: tuple[str, ...] = ("viewer",),
) -> PublishedDetailScope:
    return PublishedDetailScope(
        user_id=user_id,
        roles=roles,
        site_id=site_id,
        report_type="business_report",
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 2),
        issued_at=clock(),
        expires_at=clock() + timedelta(minutes=5),
        publications=(
            PublicationReference(
                dataset_id=11,
                site_id=site_id,
                report_date=date(2026, 8, 1),
                report_type="business_report",
                version_id=101,
                published_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
            ),
            PublicationReference(
                dataset_id=12,
                site_id=site_id,
                report_date=date(2026, 8, 2),
                report_type="business_report",
                version_id=102,
                published_at=datetime(2026, 8, 2, 1, tzinfo=UTC),
            ),
        ),
    )


def test_scope_token_binds_user_site_roles_type_and_range(
    codec: PublishedScopeCodec,
    clock: Clock,
) -> None:
    expected_scope = scope(clock, user_id=7, site_id=3)
    token = codec.encode(expected_scope)

    decoded = codec.decode(token, principal(user_id=7), query())

    assert decoded.publications == expected_scope.publications
    assert decoded.roles == ("viewer",)
    with pytest.raises(PublishedScopeInvalid):
        codec.decode(token, principal(user_id=8), query())
    with pytest.raises(PublishedScopeInvalid):
        codec.decode(token, principal(roles=frozenset({"admin"})), query())
    with pytest.raises(PublishedScopeInvalid):
        codec.decode(token, principal(), query(site_id=4))
    with pytest.raises(PublishedScopeInvalid):
        codec.decode(token, principal(), query(report_type="return_report"))
    with pytest.raises(PublishedScopeInvalid):
        codec.decode(token, principal(), query(from_date=date(2026, 8, 2)))


def test_scope_token_expires(
    codec: PublishedScopeCodec,
    clock: Clock,
) -> None:
    token = codec.encode(scope(clock))

    clock.advance(timedelta(minutes=6))

    with pytest.raises(PublishedScopeExpired):
        codec.decode(token, principal(), query())


def test_scope_token_rejects_future_issue_time(
    codec: PublishedScopeCodec,
    clock: Clock,
) -> None:
    future_scope = scope(clock).model_copy(
        update={
            "issued_at": clock() + timedelta(microseconds=1),
            "expires_at": clock() + timedelta(minutes=5, microseconds=1),
        }
    )

    with pytest.raises(PublishedScopeInvalid):
        codec.encode(future_scope)

    clock.advance(timedelta(microseconds=1))
    token = codec.encode(scope(clock))
    clock.advance(-timedelta(microseconds=1))

    with pytest.raises(PublishedScopeInvalid):
        codec.decode(token, principal(), query())


def test_scope_token_rejects_malformed_tampered_and_duplicate_payloads(
    codec: PublishedScopeCodec,
    clock: Clock,
) -> None:
    token = codec.encode(scope(clock))

    with pytest.raises(PublishedScopeInvalid):
        codec.decode("not-a-token", principal(), query())
    with pytest.raises(PublishedScopeInvalid):
        codec.decode(token[:-1] + "A", principal(), query())

    payload = (
        b'{"expires_at":"2026-08-14T12:05:00Z","expires_at":"2026-08-14T12:05:00Z"}'
    )
    signature = hmac.new(b"unit-test-secret", payload, hashlib.sha256).digest()
    duplicate_token = ".".join(_encode_part(value) for value in (payload, signature))

    with pytest.raises(PublishedScopeInvalid):
        codec.decode(duplicate_token, principal(), query())


def test_scope_token_rejects_noncanonical_base64_and_invalid_signatures(
    codec: PublishedScopeCodec,
    clock: Clock,
) -> None:
    token = codec.encode(scope(clock))
    payload_part, signature_part = token.split(".")

    with pytest.raises(PublishedScopeInvalid):
        codec.decode(
            f"{_base64_pad_bit_variant(payload_part)}.{signature_part}",
            principal(),
            query(),
        )
    with pytest.raises(PublishedScopeInvalid):
        codec.decode(
            f"{payload_part}.{_base64_pad_bit_variant(signature_part)}",
            principal(),
            query(),
        )
    with pytest.raises(PublishedScopeInvalid):
        codec.decode(f"{payload_part}.AA", principal(), query())
    with pytest.raises(PublishedScopeInvalid):
        codec.decode(f"{payload_part}=.{signature_part}", principal(), query())


def test_scope_token_rejects_publication_extra_fields(
    codec: PublishedScopeCodec,
    clock: Clock,
) -> None:
    token = codec.encode(scope(clock))
    payload_part, _ = token.split(".")
    payload = json.loads(_decode_part(payload_part))
    payload["publications"][0]["internal_row_id"] = 99
    canonical_payload = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(
        b"unit-test-secret", canonical_payload, hashlib.sha256
    ).digest()

    with pytest.raises(PublishedScopeInvalid):
        codec.decode(
            ".".join(_encode_part(value) for value in (canonical_payload, signature)),
            principal(),
            query(),
        )


def test_public_boundary_models_reject_coercion_and_extra_fields() -> None:
    with pytest.raises(ValueError):
        PublishedDetailQuery(
            site_id="3",  # type: ignore[arg-type]
            report_type="business_report",
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 2),
        )
    with pytest.raises(ValueError):
        PublishedDetailQuery(
            site_id=3,
            report_type="business_report",
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 2),
            unexpected=True,  # type: ignore[call-arg]
        )
    with pytest.raises(ValueError):
        PublishedDetailPagination(
            page="1",  # type: ignore[arg-type]
            page_size=25,
            total_items=1,
            total_pages=1,
        )
    with pytest.raises(ValueError):
        PublishedRangeResponse(
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 2),
            unexpected=True,  # type: ignore[call-arg]
        )


def test_scope_token_uses_canonical_json(
    codec: PublishedScopeCodec,
    clock: Clock,
) -> None:
    token = codec.encode(scope(clock, roles=("viewer", "admin")))
    payload_part, signature_part = token.split(".")
    payload = _decode_part(payload_part)
    assert payload == json.dumps(
        json.loads(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert b"=" not in payload_part.encode("ascii")
    assert b"=" not in signature_part.encode("ascii")


def _encode_part(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_part(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _base64_pad_bit_variant(value: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    remainder = len(value) % 4
    assert remainder in {2, 3}
    preserved_bits = 0b110000 if remainder == 2 else 0b111100
    original_index = alphabet.index(value[-1])
    variant_index = (original_index & preserved_bits) | (
        (original_index + 1) & ~preserved_bits
    )
    if variant_index == original_index:
        variant_index = (original_index & preserved_bits) | 1
    return f"{value[:-1]}{alphabet[variant_index]}"
