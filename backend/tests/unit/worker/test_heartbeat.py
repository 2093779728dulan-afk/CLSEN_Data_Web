from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from threading import Event, Lock
from uuid import UUID

import pytest
from app.worker.heartbeat import WorkerHeartbeatController, WorkerHeartbeatRepository
from app.worker.observability import QUEUE_NAMES, PollOutcome

NOW = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)
INSTANCE_ID = UUID("01234567-89ab-4def-8123-456789abcdef")


class _ControlledWait:
    def __init__(self) -> None:
        self._values: deque[bool] = deque()
        self._available = Event()
        self.intervals: list[float] = []

    def __call__(self, seconds: float) -> bool:
        self.intervals.append(seconds)
        assert self._available.wait(timeout=2)
        value = self._values.popleft()
        if not self._values:
            self._available.clear()
        return value

    def tick(self) -> None:
        self._values.append(False)
        self._available.set()

    def finish(self) -> None:
        self._values.append(True)
        self._available.set()


class _FakeRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.heartbeat_completed = Event()
        self.fail_registration = False
        self.fail_heartbeat = False
        self.fail_prune = False
        self._lock = Lock()

    def register(self, **values: object) -> datetime:
        with self._lock:
            self.calls.append(("register", values))
        if self.fail_registration:
            raise RuntimeError("registration unavailable")
        return NOW

    def heartbeat(self, **values: object) -> datetime:
        with self._lock:
            self.calls.append(("heartbeat", values))
        try:
            if self.fail_heartbeat:
                raise RuntimeError("heartbeat unavailable")
            return NOW
        finally:
            self.heartbeat_completed.set()

    def poll_started(self, **values: object) -> datetime:
        with self._lock:
            self.calls.append(("poll_started", values))
        return NOW

    def poll_succeeded(self, **values: object) -> datetime:
        with self._lock:
            self.calls.append(("poll_succeeded", values))
        return NOW

    def poll_failed(self, **values: object) -> datetime:
        with self._lock:
            self.calls.append(("poll_failed", values))
        return NOW

    def stop(self, **values: object) -> datetime:
        with self._lock:
            self.calls.append(("stop", values))
        return NOW

    def prune(self, **values: object) -> int:
        with self._lock:
            self.calls.append(("prune", values))
        if self.fail_prune:
            raise RuntimeError("prune unavailable")
        return 0


def _controller(
    repository: _FakeRepository,
    wait: _ControlledWait,
    monotonic_value: list[float],
) -> WorkerHeartbeatController:
    return WorkerHeartbeatController(
        repository,  # type: ignore[arg-type]
        instance_id=INSTANCE_ID,
        build_id="stage2-test-build",
        monotonic=lambda: monotonic_value[0],
        wait=wait,
    )


def _complete_tick(repository: _FakeRepository, wait: _ControlledWait) -> None:
    repository.heartbeat_completed.clear()
    wait.tick()
    assert repository.heartbeat_completed.wait(timeout=2)


def test_registration_opens_claim_gate_and_uses_frozen_queue_set() -> None:
    repository = _FakeRepository()
    wait = _ControlledWait()
    monotonic_value = [100.0]
    controller = _controller(repository, wait, monotonic_value)

    controller.start()
    try:
        assert controller.can_claim()
        register = repository.calls[0]
        assert register[0] == "register"
        assert register[1]["instance_id"] == INSTANCE_ID  # type: ignore[index]
        assert register[1]["supported_queues"] == QUEUE_NAMES  # type: ignore[index]
        assert repository.calls[1][0] == "prune"
    finally:
        wait.finish()
        controller.stop()


def test_claim_gate_expires_after_one_heartbeat_interval() -> None:
    repository = _FakeRepository()
    wait = _ControlledWait()
    monotonic_value = [100.0]
    controller = _controller(repository, wait, monotonic_value)

    controller.start()
    try:
        monotonic_value[0] = 110.0
        assert controller.can_claim()
        monotonic_value[0] = 110.001
        assert not controller.can_claim()
    finally:
        wait.finish()
        controller.stop()


def test_failed_heartbeat_closes_gate_until_real_success() -> None:
    repository = _FakeRepository()
    wait = _ControlledWait()
    monotonic_value = [100.0]
    controller = _controller(repository, wait, monotonic_value)

    controller.start()
    try:
        repository.fail_heartbeat = True
        _complete_tick(repository, wait)
        assert not controller.can_claim()

        repository.fail_heartbeat = False
        monotonic_value[0] = 120.0
        _complete_tick(repository, wait)
        assert controller.can_claim()
        heartbeat_sequences = [
            call[1]["sequence"]  # type: ignore[index]
            for call in repository.calls
            if call[0] == "heartbeat"
        ]
        assert heartbeat_sequences == [1, 2]
    finally:
        wait.finish()
        controller.stop()


def test_long_business_work_does_not_prevent_independent_heartbeats() -> None:
    repository = _FakeRepository()
    wait = _ControlledWait()
    monotonic_value = [100.0]
    controller = _controller(repository, wait, monotonic_value)

    controller.start()
    try:
        for value in (105.0, 110.0, 115.0):
            monotonic_value[0] = value
            _complete_tick(repository, wait)
        assert controller.can_claim()
        assert len([call for call in repository.calls if call[0] == "heartbeat"]) == 3
    finally:
        wait.finish()
        controller.stop()


def test_telemetry_methods_delegate_safe_consumer_state() -> None:
    repository = _FakeRepository()
    wait = _ControlledWait()
    monotonic_value = [100.0]
    controller = _controller(repository, wait, monotonic_value)

    controller.start()
    try:
        controller.poll_started("catalog_import")
        controller.poll_succeeded(
            "catalog_import",
            PollOutcome(result_code="queue_idle", did_work=False),
        )
        controller.poll_failed("catalog_import", "consumer_unexpected_error")
    finally:
        wait.finish()
        controller.stop()

    assert [call[0] for call in repository.calls].count("poll_started") == 1
    assert [call[0] for call in repository.calls].count("poll_succeeded") == 1
    assert [call[0] for call in repository.calls].count("poll_failed") == 1


def test_registration_failure_never_opens_claim_gate_or_starts_thread() -> None:
    repository = _FakeRepository()
    repository.fail_registration = True
    wait = _ControlledWait()
    controller = _controller(repository, wait, [100.0])

    with pytest.raises(RuntimeError, match="registration unavailable"):
        controller.start()

    assert not controller.can_claim()
    assert wait.intervals == []


def test_prune_failure_does_not_close_a_successfully_registered_gate() -> None:
    repository = _FakeRepository()
    repository.fail_prune = True
    wait = _ControlledWait()
    controller = _controller(repository, wait, [100.0])

    controller.start()
    try:
        assert controller.can_claim()
    finally:
        wait.finish()
        controller.stop()


def test_stop_closes_gate_and_persists_stopped_state() -> None:
    repository = _FakeRepository()
    wait = _ControlledWait()
    controller = _controller(repository, wait, [100.0])

    controller.start()
    wait.finish()
    controller.stop()

    assert not controller.can_claim()
    assert repository.calls[-1] == (
        "stop",
        {"instance_id": INSTANCE_ID, "result_code": "worker_stopped"},
    )


@pytest.mark.parametrize(
    ("retention_days", "limit"),
    ((0, 1), (30, 0), (30, 501)),
)
def test_repository_rejects_unbounded_pruning(
    retention_days: int,
    limit: int,
) -> None:
    repository = WorkerHeartbeatRepository(object())  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        repository.prune(retention_days=retention_days, limit=limit)
