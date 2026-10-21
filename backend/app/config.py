"""Application configuration sourced from explicit environment variables."""

from __future__ import annotations

import logging
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from ipaddress import ip_address
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

_DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)
_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})
_DNS_LABEL_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)
_MINIMUM_ORPHAN_AGE = timedelta(hours=24)
_LEGACY_DEVELOPMENT_SESSION_SECRET = (
    "development-only-session-secret-change-before-deployment"
)
_EXAMPLE_SESSION_SECRET = "CHANGE_ME_TO_A_LONG_RANDOM_SECRET"
_EPHEMERAL_DEVELOPMENT_SESSION_SECRET = secrets.token_urlsafe(32)
_PUBLIC_SESSION_SECRETS = frozenset(
    {
        _LEGACY_DEVELOPMENT_SESSION_SECRET,
        _EXAMPLE_SESSION_SECRET,
    }
)
_MINIMUM_SESSION_SECRET_LENGTH = 32


def _environment_value() -> str:
    return os.getenv("APP_ENVIRONMENT", "development")


def _log_level_value() -> str:
    return os.getenv("APP_LOG_LEVEL", "INFO")


def _cors_origins_value() -> tuple[str, ...]:
    raw_value = os.getenv("APP_CORS_ALLOWED_ORIGINS")
    if raw_value is None:
        return _DEFAULT_CORS_ORIGINS
    return tuple(origin.strip() for origin in raw_value.split(",") if origin.strip())


def _session_secret_value() -> str:
    return os.getenv("APP_SESSION_SECRET", _EPHEMERAL_DEVELOPMENT_SESSION_SECRET)


def _session_cookie_secure_value() -> bool | None:
    value = os.getenv("APP_SESSION_COOKIE_SECURE")
    if value is None:
        return None
    normalised = value.strip().lower()
    if normalised in {"1", "true", "yes"}:
        return True
    if normalised in {"0", "false", "no"}:
        return False
    raise ValueError("APP_SESSION_COOKIE_SECURE must be true or false")


def _product_analytics_source_value() -> str:
    value = os.getenv("APP_PRODUCT_ANALYTICS_SOURCE")
    if value is None and _environment_value().strip().lower() in {
        "development",
        "test",
    }:
        return "legacy_parser"
    if value not in {"legacy_parser", "p0_catalog"}:
        raise ValueError(
            "APP_PRODUCT_ANALYTICS_SOURCE must be legacy_parser or p0_catalog"
        )
    return value


def _normalise_origin(origin: str) -> str:
    if origin == "*":
        raise ValueError("Wildcard CORS origins are not allowed.")

    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"Invalid CORS origin: {origin!r}") from error

    has_valid_path = parsed.path in {"", "/"}
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.hostname is None
        or not has_valid_path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or parsed.netloc.endswith(":")
    ):
        raise ValueError(f"Invalid CORS origin: {origin!r}")

    hostname = parsed.hostname
    try:
        canonical_host = ip_address(hostname).compressed
    except ValueError:
        try:
            canonical_host = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as error:
            raise ValueError(f"Invalid CORS origin: {origin!r}") from error
        labels = canonical_host.split(".")
        if (
            len(canonical_host) > 253
            or not labels
            or any(_DNS_LABEL_PATTERN.fullmatch(label) is None for label in labels)
        ):
            raise ValueError(f"Invalid CORS origin: {origin!r}") from None

    host_for_origin = f"[{canonical_host}]" if ":" in canonical_host else canonical_host
    port_suffix = f":{port}" if port is not None else ""
    return f"{parsed.scheme.lower()}://{host_for_origin}{port_suffix}"


def _required_storage_environment_value(
    environment: Mapping[str, str],
    name: str,
) -> str:
    value = environment.get(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} must be configured")
    return value.strip()


def _storage_environment_integer(
    environment: Mapping[str, str],
    name: str,
) -> int:
    value = _required_storage_environment_value(environment, name)
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


@dataclass(frozen=True, slots=True)
class StorageSettings:
    """Explicit file-storage limits and reconciliation timing."""

    root: Path
    max_upload_bytes: int
    lease_ttl: timedelta
    lease_renew_interval: timedelta
    orphan_age: timedelta

    def __post_init__(self) -> None:
        root = Path(self.root)
        if not root.is_absolute():
            raise ValueError("root must be an explicit absolute path")
        root = Path(os.path.abspath(os.fspath(root)))
        if root == Path(root.anchor):
            raise ValueError("root must not be a filesystem root")

        if type(self.max_upload_bytes) is not int or self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be a positive integer")

        durations = {
            "lease_ttl": self.lease_ttl,
            "lease_renew_interval": self.lease_renew_interval,
            "orphan_age": self.orphan_age,
        }
        for name, value in durations.items():
            if not isinstance(value, timedelta):
                raise TypeError(f"{name} must be a timedelta")
            if value <= timedelta(0):
                raise ValueError(f"{name} must be greater than zero")

        if self.lease_renew_interval >= self.lease_ttl:
            raise ValueError("lease_renew_interval must be shorter than lease_ttl")
        if self.orphan_age < _MINIMUM_ORPHAN_AGE:
            raise ValueError("orphan_age must be at least 24 hours")
        if self.orphan_age <= self.lease_ttl:
            raise ValueError("orphan_age must be longer than lease_ttl")

        object.__setattr__(self, "root", root)

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> Self:
        """Load storage settings only when the storage subsystem starts."""

        source = os.environ if environment is None else environment
        root = Path(_required_storage_environment_value(source, "APP_STORAGE_ROOT"))
        max_upload_bytes = _storage_environment_integer(
            source,
            "APP_STORAGE_MAX_UPLOAD_BYTES",
        )
        lease_ttl_seconds = _storage_environment_integer(
            source,
            "APP_STORAGE_LEASE_TTL_SECONDS",
        )
        lease_renew_interval_seconds = _storage_environment_integer(
            source,
            "APP_STORAGE_LEASE_RENEW_INTERVAL_SECONDS",
        )
        orphan_age_seconds = _storage_environment_integer(
            source,
            "APP_STORAGE_ORPHAN_AGE_SECONDS",
        )
        try:
            return cls(
                root=root,
                max_upload_bytes=max_upload_bytes,
                lease_ttl=timedelta(seconds=lease_ttl_seconds),
                lease_renew_interval=timedelta(seconds=lease_renew_interval_seconds),
                orphan_age=timedelta(seconds=orphan_age_seconds),
            )
        except OverflowError as error:
            raise ValueError(
                "storage duration is outside the supported range"
            ) from error


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated process settings.

    Environment variables use the ``APP_`` prefix so local scripts and deployed
    services share one explicit configuration contract.
    """

    environment: str = field(default_factory=_environment_value)
    log_level: str = field(default_factory=_log_level_value)
    cors_allowed_origins: tuple[str, ...] = field(default_factory=_cors_origins_value)
    session_secret: str = field(default_factory=_session_secret_value, repr=False)
    session_cookie_secure: bool | None = field(
        default_factory=_session_cookie_secure_value
    )
    product_analytics_source: str = field(
        default_factory=_product_analytics_source_value
    )
    session_ttl: timedelta = timedelta(hours=8)
    login_rate_limit_attempts: int = 5
    login_rate_limit_window: timedelta = timedelta(minutes=15)
    bootstrap_csrf_ttl: timedelta = timedelta(minutes=10)

    def __post_init__(self) -> None:
        environment = self.environment.strip()
        if not environment:
            raise ValueError("environment must not be empty")

        log_level = self.log_level.strip().upper()
        if log_level not in _LOG_LEVELS:
            valid_levels = ", ".join(sorted(_LOG_LEVELS))
            raise ValueError(f"log_level must be one of: {valid_levels}")

        origins = tuple(
            dict.fromkeys(
                _normalise_origin(origin.strip())
                for origin in self.cors_allowed_origins
            )
        )

        session_secret = self.session_secret.strip()
        if len(session_secret) < _MINIMUM_SESSION_SECRET_LENGTH:
            raise ValueError(
                "session_secret must be at least "
                f"{_MINIMUM_SESSION_SECRET_LENGTH} characters"
            )
        if session_secret in _PUBLIC_SESSION_SECRETS:
            raise ValueError("APP_SESSION_SECRET must not use a public placeholder")
        if environment.lower() in {"production", "server"} and (
            session_secret == _EPHEMERAL_DEVELOPMENT_SESSION_SECRET
        ):
            raise ValueError(
                "APP_SESSION_SECRET must be configured outside development"
            )

        if self.session_cookie_secure is None:
            session_cookie_secure = environment.lower() not in {"development", "test"}
        else:
            session_cookie_secure = self.session_cookie_secure
        if self.product_analytics_source not in {"legacy_parser", "p0_catalog"}:
            raise ValueError(
                "product_analytics_source must be legacy_parser or p0_catalog"
            )
        if (
            environment.lower() in {"production", "server"}
            and not session_cookie_secure
        ):
            raise ValueError(
                "session_cookie_secure must be enabled outside development"
            )

        durations = {
            "session_ttl": self.session_ttl,
            "login_rate_limit_window": self.login_rate_limit_window,
            "bootstrap_csrf_ttl": self.bootstrap_csrf_ttl,
        }
        for name, duration in durations.items():
            if not isinstance(duration, timedelta) or duration <= timedelta(0):
                raise ValueError(f"{name} must be a positive timedelta")
        if self.login_rate_limit_attempts < 1:
            raise ValueError("login_rate_limit_attempts must be at least 1")

        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "log_level", log_level)
        object.__setattr__(self, "cors_allowed_origins", origins)
        object.__setattr__(self, "session_secret", session_secret)
        object.__setattr__(self, "session_cookie_secure", session_cookie_secure)

    @property
    def numeric_log_level(self) -> int:
        """Return the logging module's numeric value for the configured level."""

        return logging.getLevelNamesMapping()[self.log_level]
