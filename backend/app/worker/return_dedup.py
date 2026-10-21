"""Lease-fenced worker for deterministic return-dedup snapshots."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.catalog.return_dedup_repository import (
    MySqlReturnDedupRepository,
    ReturnDedupError,
    ReturnDedupStagingJob,
    build_frozen_groups,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ReturnDedupWorker:
    def __init__(
        self,
        repository: MySqlReturnDedupRepository,
        *,
        lease_ttl: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not timedelta(seconds=5) <= lease_ttl <= timedelta(hours=1):
            raise ValueError(
                "return dedup lease TTL must be between 5 seconds and 1 hour"
            )
        self._repository = repository
        self._lease_ttl = lease_ttl
        self._clock = clock

    def run_once(self) -> ReturnDedupStagingJob | None:
        started_at = self._clock()
        candidate = self._repository.next_claimable(occurred_at=started_at)
        if candidate is None:
            return None
        lease = self._repository.claim(
            job_id=candidate[0],
            expected_job_revision=candidate[1],
            lease_token=uuid4(),
            occurred_at=started_at,
            lease_ttl=self._lease_ttl,
        )
        try:
            frozen = self._repository.load_frozen_input(lease)
            groups = build_frozen_groups(frozen)
            return self._repository.complete(
                lease,
                frozen=frozen,
                groups=groups,
                occurred_at=self._clock(),
            )
        except ReturnDedupError as error:
            return self._repository.fail(
                lease,
                reason_code=error.code,
                retry_allowed=False,
                occurred_at=self._clock(),
            )
        except Exception:
            return self._repository.fail(
                lease,
                reason_code="return_dedup_build_failed",
                retry_allowed=True,
                occurred_at=self._clock(),
            )


__all__ = ("ReturnDedupWorker",)
