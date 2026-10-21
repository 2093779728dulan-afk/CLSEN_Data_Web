from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Never

import httpx2
import pytest
from tests.performance.product_catalog_scale_fixture import (
    _assert_loopback_login_ok,
)

_SYNTHETIC_SECRET = "SYNTHETIC_SECRET_31c8"


class _SyntheticPayloadError(Exception):
    def __str__(self) -> str:
        return _SYNTHETIC_SECRET


class _EvilResponse(httpx2.Response):
    def __init__(self, status_code: int, failure: BaseException) -> None:
        super().__init__(status_code)
        self._failure = failure

    def json(self, **kwargs: object) -> object:
        raise self._failure


class _PayloadResponse(httpx2.Response):
    def __init__(self, status_code: int, payload: object) -> None:
        super().__init__(status_code)
        self._payload = payload

    def json(self, **kwargs: object) -> object:
        return self._payload


class _EvilMapping(Mapping[str, object]):
    def __init__(self, operation: str, failure: BaseException) -> None:
        self._operation = operation
        self._failure = failure

    def __getitem__(self, key: str) -> object:
        if self._operation == "contains":
            _ = key in self
        elif self._operation == "iteration":
            next(iter(self))
        self._raise_failure()

    def __iter__(self) -> Iterator[str]:
        self._raise_failure()

    def __len__(self) -> int:
        return 1

    def __contains__(self, key: object) -> bool:
        self._raise_failure()

    def get(self, key: str, default: object = None) -> object:
        if self._operation == "get":
            self._raise_failure()
        return super().get(key, default)

    def _raise_failure(self) -> Never:
        raise self._failure


@pytest.mark.parametrize(
    ("status_code", "error_code", "category"),
    (
        (401, "invalid_credentials", "login_http_401"),
        (403, "csrf_invalid", "login_http_403"),
        (429, "login_rate_limited", "login_http_429"),
        (500, "internal_server_error", "login_http_5xx"),
    ),
)
def test_loopback_login_failure_has_safe_status_category_and_code(
    status_code: int,
    error_code: str,
    category: str,
) -> None:
    response = httpx2.Response(
        status_code,
        json={"error": {"code": error_code, "message": "not retained"}},
    )

    with pytest.raises(AssertionError) as captured:
        _assert_loopback_login_ok(response)

    assert str(captured.value) == (
        "scale loopback login failed "
        f"category={category} status={status_code} code={error_code}"
    )


def test_loopback_login_failure_uses_safe_fallback_for_unknown_status() -> None:
    response = httpx2.Response(
        418,
        json={"error": {"code": "invalid_credentials"}},
    )

    with pytest.raises(AssertionError) as captured:
        _assert_loopback_login_ok(response)

    assert str(captured.value) == (
        "scale loopback login failed category=login_http_other status=418 code=unknown"
    )


@pytest.mark.parametrize(
    "payload",
    (
        {"error": {"code": "database_secret_is_EXPOSED"}},
        {"error": {"code": ["invalid_credentials"]}},
        {"error": "invalid_credentials"},
        {"code": "invalid_credentials"},
        ["invalid_credentials"],
    ),
)
def test_loopback_login_failure_does_not_retain_unknown_or_malformed_payload(
    payload: object,
) -> None:
    response = httpx2.Response(401, json=payload)

    with pytest.raises(AssertionError) as captured:
        _assert_loopback_login_ok(response)

    failure = str(captured.value)
    assert failure == (
        "scale loopback login failed category=login_http_401 status=401 code=unknown"
    )
    assert "EXPOSED" not in failure


def test_loopback_login_failure_does_not_retain_body_headers_or_cookies() -> None:
    secret = "SENSITIVE_TOKEN_7f9c"
    response = httpx2.Response(
        500,
        content=secret,
        headers={"Authorization": secret, "Set-Cookie": f"session={secret}"},
    )

    with pytest.raises(AssertionError) as captured:
        _assert_loopback_login_ok(response)

    failure = str(captured.value)
    assert failure == (
        "scale loopback login failed category=login_http_5xx status=500 code=unknown"
    )
    assert secret not in failure


def test_loopback_login_failure_contains_json_exception() -> None:
    response = _EvilResponse(500, _SyntheticPayloadError())

    with pytest.raises(AssertionError) as captured:
        _assert_loopback_login_ok(response)

    failure = str(captured.value)
    assert failure == (
        "scale loopback login failed category=login_http_5xx status=500 code=unknown"
    )
    assert _SYNTHETIC_SECRET not in failure


@pytest.mark.parametrize("operation", ("get", "contains", "index", "iteration"))
def test_loopback_login_failure_contains_mapping_exception(operation: str) -> None:
    response = _PayloadResponse(401, _EvilMapping(operation, _SyntheticPayloadError()))

    with pytest.raises(AssertionError) as captured:
        _assert_loopback_login_ok(response)

    failure = str(captured.value)
    assert failure == (
        "scale loopback login failed category=login_http_401 status=401 code=unknown"
    )
    assert _SYNTHETIC_SECRET not in failure


@pytest.mark.parametrize(
    "failure", (KeyboardInterrupt(), SystemExit(), GeneratorExit())
)
def test_loopback_login_failure_does_not_catch_control_flow(
    failure: BaseException,
) -> None:
    response = _EvilResponse(500, failure)

    with pytest.raises(type(failure)):
        _assert_loopback_login_ok(response)


def test_loopback_login_success_is_unchanged() -> None:
    response = httpx2.Response(
        200,
        json={"password": "must-not-be-read", "csrf_token": "must-not-be-read"},
    )

    _assert_loopback_login_ok(response)
