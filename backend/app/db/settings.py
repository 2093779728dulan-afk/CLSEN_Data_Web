"""Validated database connection settings with redacted diagnostics."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from sqlalchemy.engine import URL, make_url


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Connection and pool settings for the synchronous PyMySQL engine."""

    url: URL = field(repr=False)
    pool_size: int = 10
    max_overflow: int = 20

    def __post_init__(self) -> None:
        if self.url.drivername != "mysql+pymysql":
            raise ValueError("database URL must use the mysql+pymysql driver")
        if self.url.query.get("charset") != "utf8mb4":
            raise ValueError("database URL must set charset=utf8mb4")
        if not self.url.username or self.url.password is None:
            raise ValueError("database URL must include an explicit user and password")
        if not self.url.host or not self.url.database:
            raise ValueError("database URL must include a host and database name")
        if self.pool_size < 1:
            raise ValueError("pool_size must be at least 1")
        if self.max_overflow < 0:
            raise ValueError("max_overflow must not be negative")

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        pool_size: int = 10,
        max_overflow: int = 20,
    ) -> DatabaseSettings:
        """Parse and validate one explicit SQLAlchemy database URL."""

        return cls(
            url=make_url(url),
            pool_size=pool_size,
            max_overflow=max_overflow,
        )

    @classmethod
    def from_env(
        cls,
        variable_name: str = "APP_DATABASE_URL",
        *,
        pool_size: int = 10,
        max_overflow: int = 20,
    ) -> DatabaseSettings:
        """Load a named URL contract without silently selecting another account."""

        value = os.getenv(variable_name)
        if value is None or not value.strip():
            raise ValueError(f"{variable_name} must be configured")
        return cls.from_url(
            value,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )

    @property
    def safe_url(self) -> str:
        """Return a URL suitable for diagnostics with credentials redacted."""

        return self.url.render_as_string(hide_password=True)
