"""HMAC-protected consistency scopes for published-detail reads."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Never

from app.auth.sessions import Principal
from app.published_details.models import PublishedDetailQuery, PublishedDetailScope

_TOKEN_PART_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SCOPE_FIELDS = frozenset(
    {
        "expires_at",
        "from_date",
        "issued_at",
        "publications",
        "report_type",
        "roles",
        "site_id",
        "to_date",
        "user_id",
    }
)
_PUBLICATION_FIELDS = frozenset(
    {
        "dataset_id",
        "site_id",
        "report_date",
        "report_type",
        "version_id",
        "published_at",
    }
)


class PublishedScopeInvalid(ValueError):
    """A scope token is malformed, forged, or bound to a different request."""


class PublishedScopeExpired(PublishedScopeInvalid):
    """A correctly signed scope token is no longer valid."""


class PublishedScopeCodec:
    """Encode and validate short-lived, signed publication-pointer snapshots."""

    def __init__(
        self,
        *,
        secret: str,
        clock: Callable[[], datetime],
        ttl: timedelta,
    ) -> None:
        if not secret:
            raise ValueError("secret must not be empty")
        if ttl <= timedelta():
            raise ValueError("ttl must be positive")
        self._secret = secret.encode("utf-8")
        self._clock = clock
        self._ttl = ttl

    def encode(self, scope: PublishedDetailScope) -> str:
        """Return the canonical signed representation of an exact scope."""

        if not isinstance(scope, PublishedDetailScope):
            raise TypeError("scope must be a PublishedDetailScope")
        now = _utc_clock_value(self._clock())
        if scope.issued_at > now:
            raise PublishedScopeInvalid("scope issue time is in the future")
        if scope.expires_at - scope.issued_at != self._ttl:
            raise PublishedScopeInvalid("scope lifetime does not match codec ttl")
        payload = _canonical_json(scope.model_dump(mode="json"))
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{_encode_part(payload)}.{_encode_part(signature)}"

    def issue_timestamps(self) -> tuple[datetime, datetime]:
        """Return a UTC issue/expiry pair using this codec's authoritative TTL."""

        issued_at = _utc_clock_value(self._clock())
        return issued_at, issued_at + self._ttl

    def decode(
        self,
        token: str,
        principal: Principal,
        expected_query: PublishedDetailQuery,
    ) -> PublishedDetailScope:
        """Verify a token and its binding to the authenticated request."""

        payload = self._verified_payload(token)
        scope = _parse_scope(payload)
        now = _utc_clock_value(self._clock())
        if scope.issued_at > now:
            raise PublishedScopeInvalid("scope issue time is in the future")
        if scope.expires_at - scope.issued_at != self._ttl:
            raise PublishedScopeInvalid("scope lifetime does not match codec ttl")
        if now >= scope.expires_at:
            raise PublishedScopeExpired("scope token has expired")
        self._assert_request_binding(scope, principal, expected_query)
        return scope

    def _verified_payload(self, token: str) -> bytes:
        if not isinstance(token, str):
            raise PublishedScopeInvalid("scope token is malformed")
        parts = token.split(".")
        if len(parts) != 2:
            raise PublishedScopeInvalid("scope token is malformed")
        payload_part, signature_part = parts
        try:
            payload = _decode_part(payload_part)
            received_signature = _decode_part(signature_part)
        except (ValueError, UnicodeEncodeError) as error:
            raise PublishedScopeInvalid("scope token is malformed") from error
        if len(received_signature) != hashlib.sha256().digest_size:
            raise PublishedScopeInvalid("scope token signature is invalid")
        expected_signature = hmac.new(
            self._secret,
            payload,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(received_signature, expected_signature):
            raise PublishedScopeInvalid("scope token signature is invalid")
        return payload

    @staticmethod
    def _assert_request_binding(
        scope: PublishedDetailScope,
        principal: Principal,
        expected_query: PublishedDetailQuery,
    ) -> None:
        if not isinstance(principal, Principal):
            raise PublishedScopeInvalid("scope principal does not match")
        if not isinstance(expected_query, PublishedDetailQuery):
            raise PublishedScopeInvalid("scope query does not match")
        if scope.user_id != principal.user_id:
            raise PublishedScopeInvalid("scope principal does not match")
        if scope.roles != tuple(sorted(principal.roles)):
            raise PublishedScopeInvalid("scope principal does not match")
        if (
            scope.site_id != expected_query.site_id
            or scope.report_type != expected_query.report_type
            or scope.from_date != expected_query.from_date
            or scope.to_date != expected_query.to_date
        ):
            raise PublishedScopeInvalid("scope query does not match")


def _encode_part(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_part(value: str) -> bytes:
    if not value or _TOKEN_PART_RE.fullmatch(value) is None:
        raise ValueError("invalid URL-safe base64")
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as error:
        raise ValueError("invalid URL-safe base64") from error
    if _encode_part(decoded) != value:
        raise ValueError("non-canonical URL-safe base64")
    return decoded


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PublishedScopeInvalid("scope payload cannot be encoded") from error


def _parse_scope(payload: bytes) -> PublishedDetailScope:
    try:
        raw_payload = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise PublishedScopeInvalid("scope payload is malformed") from error
    if not isinstance(raw_payload, dict) or set(raw_payload) != _SCOPE_FIELDS:
        raise PublishedScopeInvalid("scope payload fields are invalid")
    _validate_publication_payloads(raw_payload["publications"])
    if _canonical_json(raw_payload) != payload:
        raise PublishedScopeInvalid("scope payload is not canonical")
    try:
        return PublishedDetailScope.model_validate_json(payload, strict=True)
    except ValueError as error:
        raise PublishedScopeInvalid("scope payload is invalid") from error


def _validate_publication_payloads(value: object) -> None:
    if not isinstance(value, list):
        raise PublishedScopeInvalid("scope publications are invalid")
    for publication in value:
        if not isinstance(publication, dict) or set(publication) != _PUBLICATION_FIELDS:
            raise PublishedScopeInvalid("scope publication fields are invalid")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Never:
    raise ValueError(f"unsupported JSON constant: {value}")


def _utc_clock_value(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC)
