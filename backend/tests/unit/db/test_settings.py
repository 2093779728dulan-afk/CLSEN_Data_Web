from __future__ import annotations

import pytest
from app.db.settings import DatabaseSettings


def test_database_settings_require_explicit_mysql_pymysql_utf8mb4_url() -> None:
    settings = DatabaseSettings.from_url(
        "mysql+pymysql://clsen_app:p%40ssword@127.0.0.1:3307/clsen_data?charset=utf8mb4"
    )

    assert settings.url.drivername == "mysql+pymysql"
    assert settings.url.host == "127.0.0.1"
    assert settings.url.port == 3307
    assert settings.url.database == "clsen_data"
    assert settings.url.password == "p@ssword"
    assert settings.url.query["charset"] == "utf8mb4"


@pytest.mark.parametrize(
    "url",
    [
        "sqlite+pysqlite:///local.db",
        "mysql+mysqldb://user:password@localhost/clsen_data?charset=utf8mb4",
        "mysql+pymysql://user:password@localhost/clsen_data",
        "mysql+pymysql://user:password@localhost/clsen_data?charset=utf8",
    ],
)
def test_database_settings_reject_unsupported_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValueError, match=r"mysql\+pymysql|utf8mb4"):
        DatabaseSettings.from_url(url)


def test_database_settings_hide_credentials_from_diagnostics() -> None:
    settings = DatabaseSettings.from_url(
        "mysql+pymysql://clsen_app:do-not-log-me@localhost/clsen_data?charset=utf8mb4"
    )

    assert "do-not-log-me" not in repr(settings)
    assert "do-not-log-me" not in settings.safe_url
    assert "***" in settings.safe_url


def test_database_settings_read_a_named_environment_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "APP_TEST_DATABASE_URL",
        "mysql+pymysql://test_user:secret@localhost/clsen_data_test?charset=utf8mb4",
    )

    settings = DatabaseSettings.from_env("APP_TEST_DATABASE_URL")

    assert settings.url.database == "clsen_data_test"


def test_missing_database_environment_contract_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_TEST_DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="APP_TEST_DATABASE_URL"):
        DatabaseSettings.from_env("APP_TEST_DATABASE_URL")
