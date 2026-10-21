"""Opaque, database-backed browser sessions and authentication primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import secrets
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.auth.passwords import password_needs_rehash, verify_password
from app.cli import normalise_username
from app.config import Settings
from app.maintenance.barrier import (
    MAINTENANCE_WRITE_LOCK_TIMEOUT_OPTION,
    MaintenanceBarrierTimeout,
)

_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "x/I+e7E9zmOwTd07hp6LlA$"
    "MD3dD4Em7IBKAvZ1D9ENTpEIEHqCL6n8YBTl41vK330"
)
_SESSION_TOKEN_BYTES = 32
_CSRF_TOKEN_BYTES = 32


def _utc_now() -> datetime:
    return datetime.now(tz=UTC).replace(tzinfo=None)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _random_token(byte_count: int) -> str:
    return secrets.token_urlsafe(byte_count)


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated account and the session proof used for one request."""

    user_id: int
    username: str
    display_name: str
    roles: frozenset[str]
    session_id: int
    csrf_token_hash: bytes


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Only returned after successful credential verification."""

    principal: Principal
    session_token: str
    csrf_token: str
    expires_at: datetime


class LoginRateLimiter:
    """Small per-process login limiter suitable for a single local instance.

    Identity buckets and aggregate source buckets share a bounded active-key
    capacity. Capacity exhaustion rejects new buckets until global expiry
    pruning releases space. A successful login resets only its identity bucket,
    so it cannot erase the source's aggregate failure history.

    A production deployment with multiple backend instances must enforce the
    equivalent limit in a shared edge proxy or durable store.
    """

    def __init__(
        self,
        *,
        maximum_attempts: int,
        window: timedelta,
        maximum_source_attempts: int | None = None,
        maximum_tracked_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if maximum_attempts < 1:
            raise ValueError("maximum_attempts must be at least 1")
        resolved_source_maximum = (
            maximum_attempts * 5
            if maximum_source_attempts is None
            else maximum_source_attempts
        )
        if resolved_source_maximum < 1:
            raise ValueError("maximum_source_attempts must be at least 1")
        if maximum_tracked_keys < 2:
            raise ValueError("maximum_tracked_keys must be at least 2")
        window_seconds = window.total_seconds()
        if window_seconds <= 0:
            raise ValueError("window must be positive")

        self._maximum_attempts = maximum_attempts
        self._maximum_source_attempts = resolved_source_maximum
        self._maximum_tracked_keys = maximum_tracked_keys
        self._window_seconds = window_seconds
        self._clock = clock
        self._account_attempts: dict[str, deque[float]] = {}
        self._source_attempts: dict[str, deque[float]] = {}
        self._lock = RLock()

    def is_allowed(self, key: str, *, source_key: str | None = None) -> bool:
        with self._lock:
            now = self._clock()
            self._prune_expired(now)
            if not self._has_capacity_for(key, source_key):
                return False
            account_attempts = self._account_attempts.get(key)
            if (
                account_attempts is not None
                and len(account_attempts) >= self._maximum_attempts
            ):
                return False
            source_attempts = (
                self._source_attempts.get(source_key)
                if source_key is not None
                else None
            )
            return not (
                source_attempts is not None
                and len(source_attempts) >= self._maximum_source_attempts
            )

    def record_failure(self, key: str, *, source_key: str | None = None) -> None:
        with self._lock:
            now = self._clock()
            self._prune_expired(now)
            if not self._has_capacity_for(key, source_key):
                return

            account_attempts = self._account_attempts.setdefault(key, deque())
            if len(account_attempts) < self._maximum_attempts:
                account_attempts.append(now)
            if source_key is None:
                return
            source_attempts = self._source_attempts.setdefault(source_key, deque())
            if len(source_attempts) < self._maximum_source_attempts:
                source_attempts.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._prune_expired(self._clock())
            self._account_attempts.pop(key, None)

    def retry_after_seconds(
        self,
        key: str,
        *,
        source_key: str | None = None,
    ) -> int:
        with self._lock:
            now = self._clock()
            self._prune_expired(now)
            blocking_delays: list[float] = []
            account_attempts = self._account_attempts.get(key)
            if (
                account_attempts is not None
                and len(account_attempts) >= self._maximum_attempts
            ):
                blocking_delays.append(
                    self._window_seconds - (now - account_attempts[0])
                )
            source_attempts = (
                self._source_attempts.get(source_key)
                if source_key is not None
                else None
            )
            if (
                source_attempts is not None
                and len(source_attempts) >= self._maximum_source_attempts
            ):
                blocking_delays.append(
                    self._window_seconds - (now - source_attempts[0])
                )
            if not self._has_capacity_for(key, source_key):
                # Every active key expires within one window. Returning the full
                # window is conservative and avoids promising an early retry when
                # more than one capacity slot is required.
                blocking_delays.append(self._window_seconds)
            if not blocking_delays:
                return 0
            return max(1, math.ceil(max(blocking_delays)))

    def _has_capacity_for(self, key: str, source_key: str | None) -> bool:
        required_slots = int(key not in self._account_attempts)
        if source_key is not None:
            required_slots += int(source_key not in self._source_attempts)
        tracked_keys = len(self._account_attempts) + len(self._source_attempts)
        return tracked_keys + required_slots <= self._maximum_tracked_keys

    def _prune_expired(self, now: float) -> None:
        cutoff = now - self._window_seconds
        for attempts_by_key in (self._account_attempts, self._source_attempts):
            expired_keys: list[str] = []
            for key, attempts in attempts_by_key.items():
                while attempts and attempts[0] <= cutoff:
                    attempts.popleft()
                if not attempts:
                    expired_keys.append(key)
            for key in expired_keys:
                del attempts_by_key[key]


class BootstrapCsrfTokens:
    """Short-lived signed CSRF tokens for the pre-authentication login form."""

    def __init__(self, *, secret: str, ttl: timedelta) -> None:
        self._secret = secret.encode("utf-8")
        self._ttl_seconds = int(ttl.total_seconds())

    def issue(self, *, now: datetime | None = None) -> str:
        issued_at = int((now or datetime.now(tz=UTC)).timestamp())
        nonce = _random_token(_CSRF_TOKEN_BYTES)
        payload = f"{issued_at}.{nonce}"
        signature = hmac.new(
            self._secret,
            payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        encoded_signature = (
            base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        )
        return f"{payload}.{encoded_signature}"

    def is_valid(self, token: str, *, now: datetime | None = None) -> bool:
        pieces = token.split(".")
        if len(pieces) != 3:
            return False
        issued_text, nonce, received_signature = pieces
        if not nonce or len(nonce) < 32:
            return False
        try:
            issued_at = int(issued_text)
            padding = "=" * (-len(received_signature) % 4)
            signature = base64.urlsafe_b64decode(received_signature + padding)
        except ValueError, UnicodeEncodeError:
            return False
        payload = f"{issued_text}.{nonce}"
        expected_signature = hmac.new(
            self._secret,
            payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        current_timestamp = int((now or datetime.now(tz=UTC)).timestamp())
        return (
            hmac.compare_digest(signature, expected_signature)
            and issued_at <= current_timestamp
            and current_timestamp - issued_at <= self._ttl_seconds
        )


class SessionService:
    """Read and mutate auth state within the caller's transaction boundary."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authenticate(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        request_id: str,
        now: datetime | None = None,
    ) -> LoginResult | None:
        occurred_at = now or _utc_now()
        try:
            username_normalised = normalise_username(username)
        except ValueError:
            username_normalised = ""

        rows = (
            session.execute(
                sa.text(
                    """
                SELECT users.id, users.username_normalized, users.display_name,
                       users.password_hash, users.status, roles.code AS role_code
                FROM users
                LEFT JOIN user_roles ON user_roles.user_id = users.id
                LEFT JOIN roles ON roles.id = user_roles.role_id
                WHERE users.username_normalized = :username
                """
                ),
                {"username": username_normalised},
            )
            .mappings()
            .all()
        )
        if not rows:
            verify_password(_DUMMY_PASSWORD_HASH, password)
            self._write_audit_event(
                session,
                actor_user_id=None,
                event_type="authentication.login_failed",
                request_id=request_id,
                payload={"outcome": "failed"},
                occurred_at=occurred_at,
            )
            return None

        user = rows[0]
        password_matches = verify_password(str(user["password_hash"]), password)
        if not password_matches or user["status"] != "active":
            self._write_audit_event(
                session,
                actor_user_id=None,
                event_type="authentication.login_failed",
                request_id=request_id,
                payload={"outcome": "failed"},
                occurred_at=occurred_at,
            )
            return None

        user_id = int(user["id"])
        if password_needs_rehash(str(user["password_hash"])):
            # Import only here so the common verification path remains explicit.
            from app.auth.passwords import hash_password

            session.execute(
                sa.text(
                    "UPDATE users SET password_hash = :password_hash, "
                    "updated_at = :occurred_at WHERE id = :user_id"
                ),
                {
                    "password_hash": hash_password(password),
                    "occurred_at": occurred_at,
                    "user_id": user_id,
                },
            )
        session.execute(
            sa.text(
                "UPDATE users SET last_login_at = :occurred_at, "
                "updated_at = :occurred_at WHERE id = :user_id"
            ),
            {"occurred_at": occurred_at, "user_id": user_id},
        )

        session_token = _random_token(_SESSION_TOKEN_BYTES)
        csrf_token = _random_token(_CSRF_TOKEN_BYTES)
        expires_at = occurred_at + self._settings.session_ttl
        result = session.execute(
            sa.text(
                """
                INSERT INTO auth_sessions (
                    token_hash, csrf_token_hash, user_id, created_at,
                    expires_at, last_seen_at
                ) VALUES (
                    :token_hash, :csrf_token_hash, :user_id, :created_at,
                    :expires_at, :last_seen_at
                )
                """
            ),
            {
                "token_hash": _digest(session_token),
                "csrf_token_hash": _digest(csrf_token),
                "user_id": user_id,
                "created_at": occurred_at,
                "expires_at": expires_at,
                "last_seen_at": occurred_at,
            },
        )
        cursor_result = cast(CursorResult[Any], result)
        session_id = cursor_result.lastrowid
        if session_id is None:
            raise RuntimeError("database did not return a session ID")
        roles = frozenset(
            str(row["role_code"]) for row in rows if row["role_code"] is not None
        )
        principal = Principal(
            user_id=user_id,
            username=str(user["username_normalized"]),
            display_name=str(user["display_name"]),
            roles=roles,
            session_id=int(session_id),
            csrf_token_hash=_digest(csrf_token),
        )
        self._write_audit_event(
            session,
            actor_user_id=user_id,
            event_type="authentication.login_succeeded",
            request_id=request_id,
            payload={"outcome": "succeeded"},
            occurred_at=occurred_at,
        )
        return LoginResult(
            principal=principal,
            session_token=session_token,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )

    def get_principal(
        self,
        session: Session,
        *,
        session_token: str,
        now: datetime | None = None,
    ) -> Principal | None:
        occurred_at = now or _utc_now()
        rows = (
            session.execute(
                sa.text(
                    """
                SELECT auth_sessions.id AS session_id,
                       auth_sessions.csrf_token_hash,
                       users.id AS user_id, users.username_normalized,
                       users.display_name, roles.code AS role_code
                FROM auth_sessions
                INNER JOIN users ON users.id = auth_sessions.user_id
                LEFT JOIN user_roles ON user_roles.user_id = users.id
                LEFT JOIN roles ON roles.id = user_roles.role_id
                WHERE auth_sessions.token_hash = :token_hash
                  AND auth_sessions.revoked_at IS NULL
                  AND auth_sessions.expires_at > :occurred_at
                  AND users.status = 'active'
                """
                ),
                {"token_hash": _digest(session_token), "occurred_at": occurred_at},
            )
            .mappings()
            .all()
        )
        if not rows:
            return None
        row = rows[0]
        touch_statement = sa.text(
            "UPDATE auth_sessions SET last_seen_at = :occurred_at "
            "WHERE id = :session_id AND revoked_at IS NULL"
        ).execution_options(**{MAINTENANCE_WRITE_LOCK_TIMEOUT_OPTION: 0})
        # Session activity is telemetry, not business state. A backup must not
        # turn an otherwise read-only authenticated request into a blocked
        # write; the fixed session expiry remains authoritative.
        with suppress(MaintenanceBarrierTimeout):
            session.execute(
                touch_statement,
                {"occurred_at": occurred_at, "session_id": row["session_id"]},
            )
        return Principal(
            user_id=int(row["user_id"]),
            username=str(row["username_normalized"]),
            display_name=str(row["display_name"]),
            roles=frozenset(
                str(role_row["role_code"])
                for role_row in rows
                if role_row["role_code"] is not None
            ),
            session_id=int(row["session_id"]),
            csrf_token_hash=bytes(row["csrf_token_hash"]),
        )

    def revoke(
        self,
        session: Session,
        *,
        principal: Principal,
        request_id: str,
        now: datetime | None = None,
    ) -> None:
        occurred_at = now or _utc_now()
        session.execute(
            sa.text(
                """
                UPDATE auth_sessions
                SET revoked_at = :occurred_at, revoked_reason = 'logout'
                WHERE id = :session_id AND revoked_at IS NULL
                """
            ),
            {"occurred_at": occurred_at, "session_id": principal.session_id},
        )
        self._write_audit_event(
            session,
            actor_user_id=principal.user_id,
            event_type="authentication.logout",
            request_id=request_id,
            payload={"outcome": "succeeded"},
            occurred_at=occurred_at,
        )

    @staticmethod
    def csrf_matches(principal: Principal, csrf_token: str) -> bool:
        try:
            received_hash = _digest(csrf_token)
        except UnicodeEncodeError:
            return False
        return hmac.compare_digest(received_hash, principal.csrf_token_hash)

    @staticmethod
    def _write_audit_event(
        session: Session,
        *,
        actor_user_id: int | None,
        event_type: str,
        request_id: str,
        payload: dict[str, str],
        occurred_at: datetime,
    ) -> None:
        session.execute(
            sa.text(
                """
                INSERT INTO audit_events (
                    site_id, actor_user_id, event_type, object_type, object_id,
                    request_id, redacted_payload, occurred_at
                ) VALUES (
                    NULL, :actor_user_id, :event_type, 'authentication', NULL,
                    :request_id, :payload, :occurred_at
                )
                """
            ),
            {
                "actor_user_id": actor_user_id,
                "event_type": event_type,
                "request_id": request_id,
                "payload": json.dumps(payload, sort_keys=True),
                "occurred_at": occurred_at,
            },
        )
