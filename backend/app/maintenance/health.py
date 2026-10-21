"""Observable health state for the database-scoped maintenance write barrier."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Engine

_LOCK_NAME_SQL = "CONCAT('clsen:maintenance-write:', DATABASE())"


@dataclass(frozen=True, slots=True)
class MaintenanceLockStatus:
    """Current named-lock ownership and local abnormal-duration observation."""

    held: bool
    owner_connection_id: int | None
    observed_seconds: float
    warning: bool


class MaintenanceLockMonitor:
    """Track how long consecutive probes have observed a held maintenance lock."""

    def __init__(self, warning_seconds: int | None = None) -> None:
        if warning_seconds is None:
            raw_value = os.getenv("APP_MAINTENANCE_LOCK_WARNING_SECONDS", "120")
            try:
                warning_seconds = int(raw_value)
            except ValueError as error:
                raise ValueError(
                    "APP_MAINTENANCE_LOCK_WARNING_SECONDS must be an integer"
                ) from error
        if not 5 <= warning_seconds <= 3600:
            raise ValueError("maintenance lock warning must be between 5 and 3600")
        self._warning_seconds = warning_seconds
        self._first_held_observation: float | None = None

    def observe(
        self,
        *,
        owner_connection_id: int | None,
        now: float | None = None,
    ) -> MaintenanceLockStatus:
        instant = time.monotonic() if now is None else now
        if owner_connection_id is None:
            self._first_held_observation = None
            return MaintenanceLockStatus(
                held=False,
                owner_connection_id=None,
                observed_seconds=0.0,
                warning=False,
            )
        if self._first_held_observation is None:
            self._first_held_observation = instant
        duration = max(0.0, instant - self._first_held_observation)
        return MaintenanceLockStatus(
            held=True,
            owner_connection_id=owner_connection_id,
            observed_seconds=duration,
            warning=duration >= self._warning_seconds,
        )


def probe_maintenance_lock(
    engine: Engine,
    monitor: MaintenanceLockMonitor,
    *,
    ignored_owner_connection_id: int | None = None,
) -> MaintenanceLockStatus:
    """Read named-lock ownership without acquiring or disturbing the lock."""

    with engine.connect() as connection:
        owner = connection.scalar(sa.text(f"SELECT IS_USED_LOCK({_LOCK_NAME_SQL})"))
    owner_connection_id = None if owner is None else int(owner)
    if owner_connection_id == ignored_owner_connection_id:
        owner_connection_id = None
    return monitor.observe(
        owner_connection_id=owner_connection_id,
    )
