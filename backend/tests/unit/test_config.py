from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest
from app.config import Settings, StorageSettings


@pytest.mark.parametrize(
    "origin",
    [
        "http://.",
        "http://example.test:notaport",
        "http://example.test:99999",
        "http://-invalid.example.test",
    ],
)
def test_invalid_cors_origins_are_rejected(origin: str) -> None:
    with pytest.raises(ValueError, match="CORS origin"):
        Settings(cors_allowed_origins=(origin,))


def test_storage_settings_load_only_when_explicitly_requested(tmp_path: Path) -> None:
    settings = StorageSettings.from_env(
        {
            "APP_STORAGE_ROOT": str(tmp_path),
            "APP_STORAGE_MAX_UPLOAD_BYTES": "104857600",
            "APP_STORAGE_LEASE_TTL_SECONDS": "900",
            "APP_STORAGE_LEASE_RENEW_INTERVAL_SECONDS": "300",
            "APP_STORAGE_ORPHAN_AGE_SECONDS": "86400",
        }
    )

    assert settings.root == Path(os.path.abspath(os.fspath(tmp_path)))
    assert settings.max_upload_bytes == 104_857_600
    assert settings.lease_ttl == timedelta(minutes=15)
    assert settings.lease_renew_interval == timedelta(minutes=5)
    assert settings.orphan_age == timedelta(hours=24)


def test_storage_settings_do_not_resolve_security_sensitive_path_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_resolved(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"Path.resolve was called with {args!r} {kwargs!r}")

    monkeypatch.setattr(Path, "resolve", fail_if_resolved)

    settings = StorageSettings(
        root=tmp_path / "objects",
        max_upload_bytes=1,
        lease_ttl=timedelta(minutes=15),
        lease_renew_interval=timedelta(minutes=5),
        orphan_age=timedelta(hours=24),
    )

    assert settings.root == Path(os.path.abspath(os.fspath(tmp_path / "objects")))


def test_existing_settings_do_not_require_storage_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "APP_STORAGE_ROOT",
        "APP_STORAGE_MAX_UPLOAD_BYTES",
        "APP_STORAGE_LEASE_TTL_SECONDS",
        "APP_STORAGE_LEASE_RENEW_INTERVAL_SECONDS",
        "APP_STORAGE_ORPHAN_AGE_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    assert Settings().environment
    with pytest.raises(ValueError, match="APP_STORAGE_ROOT"):
        StorageSettings.from_env()


def test_production_requires_a_non_development_session_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_SESSION_SECRET", raising=False)

    with pytest.raises(ValueError, match="APP_SESSION_SECRET"):
        Settings(environment="production")


@pytest.mark.parametrize(
    "session_secret",
    [
        "development-only-session-secret-change-before-deployment",
        "CHANGE_ME_TO_A_LONG_RANDOM_SECRET",
    ],
)
def test_public_session_secrets_cannot_protect_persistent_authentication(
    session_secret: str,
) -> None:
    with pytest.raises(ValueError, match="APP_SESSION_SECRET"):
        Settings(session_secret=session_secret)


def test_explicit_random_session_secret_can_protect_persistent_authentication() -> None:
    settings = Settings(session_secret="local-random-session-secret-0123456789abcdef")

    assert settings.session_secret == "local-random-session-secret-0123456789abcdef"


def test_production_requires_secure_session_cookies() -> None:
    with pytest.raises(ValueError, match="session_cookie_secure"):
        Settings(
            environment="production",
            session_secret="x" * 32,
            session_cookie_secure=False,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"root": Path("relative/storage")}, "absolute"),
        ({"max_upload_bytes": 0}, "max_upload_bytes"),
        ({"lease_ttl": timedelta(0)}, "lease_ttl"),
        (
            {
                "lease_ttl": timedelta(minutes=5),
                "lease_renew_interval": timedelta(minutes=5),
            },
            "lease_renew_interval",
        ),
        ({"orphan_age": timedelta(hours=23)}, "orphan_age"),
    ],
)
def test_storage_settings_reject_unsafe_values(
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "root": tmp_path,
        "max_upload_bytes": 104_857_600,
        "lease_ttl": timedelta(minutes=15),
        "lease_renew_interval": timedelta(minutes=5),
        "orphan_age": timedelta(hours=24),
    }
    values.update(overrides)

    with pytest.raises((TypeError, ValueError), match=message):
        StorageSettings(**values)  # type: ignore[arg-type]
