from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.auth.sessions import BootstrapCsrfTokens, LoginRateLimiter


def test_bootstrap_csrf_token_expires_and_rejects_tampering() -> None:
    issued_at = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    tokens = BootstrapCsrfTokens(secret="x" * 32, ttl=timedelta(minutes=10))

    token = tokens.issue(now=issued_at)

    assert tokens.is_valid(token, now=issued_at + timedelta(minutes=10))
    assert not tokens.is_valid(token, now=issued_at + timedelta(minutes=10, seconds=1))
    assert not tokens.is_valid(f"{token}x", now=issued_at)


def test_login_rate_limiter_recovers_after_its_window() -> None:
    current_time = 100.0

    def clock() -> float:
        return current_time

    limiter = LoginRateLimiter(
        maximum_attempts=2,
        window=timedelta(seconds=60),
        clock=clock,
    )
    limiter.record_failure("127.0.0.1:operator")
    limiter.record_failure("127.0.0.1:operator")

    assert not limiter.is_allowed("127.0.0.1:operator")
    assert limiter.retry_after_seconds("127.0.0.1:operator") == 60

    current_time += 60

    assert limiter.is_allowed("127.0.0.1:operator")


def test_login_rate_limiter_applies_a_total_failure_limit_per_source() -> None:
    limiter = LoginRateLimiter(
        maximum_attempts=2,
        maximum_source_attempts=3,
        maximum_tracked_keys=20,
        window=timedelta(seconds=60),
    )

    for username in ("first", "second", "third"):
        key = f"127.0.0.1:{username}"
        assert limiter.is_allowed(key, source_key="127.0.0.1")
        limiter.record_failure(key, source_key="127.0.0.1")
        if username == "first":
            limiter.reset(key)

    assert not limiter.is_allowed(
        "127.0.0.1:fourth",
        source_key="127.0.0.1",
    )
    assert limiter.is_allowed(
        "127.0.0.2:fourth",
        source_key="127.0.0.2",
    )


def test_login_rate_limiter_globally_evicts_expired_keys() -> None:
    current_time = 100.0

    def clock() -> float:
        return current_time

    limiter = LoginRateLimiter(
        maximum_attempts=2,
        maximum_source_attempts=4,
        maximum_tracked_keys=2,
        window=timedelta(seconds=60),
        clock=clock,
    )
    limiter.record_failure("127.0.0.1:first", source_key="127.0.0.1")

    assert not limiter.is_allowed(
        "127.0.0.2:second",
        source_key="127.0.0.2",
    )

    current_time += 60

    assert limiter.is_allowed(
        "127.0.0.2:second",
        source_key="127.0.0.2",
    )
    limiter.record_failure("127.0.0.2:second", source_key="127.0.0.2")
    assert not limiter.is_allowed(
        "127.0.0.3:third",
        source_key="127.0.0.3",
    )
