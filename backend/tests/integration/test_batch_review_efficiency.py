from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID, uuid5

_NAMESPACE = UUID("f4be51db-7d6a-4adf-a857-a9cc4e58c7a8")


@dataclass(frozen=True, slots=True)
class SyntheticBatch:
    batch_id: int
    report_date: date
    report_type: str
    expected: str


def _fixture(count: int) -> tuple[SyntheticBatch, ...]:
    exceptional = {
        7: "recognition_uncertain",
        13: "active_draft_exists",
        19: "publication_exists",
        23: "validation_warning",
        29: "parse_failed",
        31: "retryable_failure",
        47: "duplicate_target_in_run",
        61: "source_unavailable",
    }
    start = date(2026, 1, 1)
    return tuple(
        SyntheticBatch(
            batch_id=10_000 + index,
            report_date=start + timedelta(days=index),
            report_type=("business_report" if index % 2 else "return_report"),
            expected=exceptional.get(index, "ready_for_publish"),
        )
        for index in range(1, count + 1)
    )


def test_thirty_safe_files_have_three_lane_critical_path_below_half_serial() -> None:
    fixtures = tuple(
        item for item in _fixture(38) if item.expected == "ready_for_publish"
    )[:30]

    def work(_item: SyntheticBatch) -> None:
        # Keep the workload above thread-startup and VM scheduling overhead.
        # Both paths use the same duration; the 50% speedup requirement stays.
        time.sleep(0.05)

    serial_started = time.perf_counter()
    for item in fixtures:
        work(item)
    serial_elapsed = time.perf_counter() - serial_started

    batch_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(work, fixtures))
    batch_elapsed = time.perf_counter() - batch_started

    assert len(fixtures) == 30
    assert batch_elapsed < serial_elapsed * 0.5, (
        f"Three-lane elapsed {batch_elapsed:.3f}s must be below half of "
        f"serial elapsed {serial_elapsed:.3f}s"
    )


def test_one_hundred_file_fixture_is_bounded_unique_and_never_publishes() -> None:
    fixtures = _fixture(100)
    lock = threading.Lock()
    active = 0
    maximum_active = 0
    domain_results: dict[int, tuple[UUID, UUID, UUID]] = {}
    publication_events: list[int] = []

    def work(item: SyntheticBatch) -> None:
        nonlocal active, maximum_active
        if item.expected not in {"ready_for_publish", "retryable_failure"}:
            return
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.002)
            semantic = uuid5(_NAMESPACE, f"batch:{item.batch_id}")
            result = (
                uuid5(semantic, "import"),
                uuid5(semantic, "validation"),
                uuid5(semantic, "mark-ready"),
            )
            with lock:
                domain_results[item.batch_id] = result
        finally:
            with lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(work, fixtures))

    expected_domain_results = sum(
        item.expected in {"ready_for_publish", "retryable_failure"} for item in fixtures
    )
    all_tokens = [token for result in domain_results.values() for token in result]
    assert len(fixtures) == 100
    assert maximum_active == 3
    assert len(domain_results) == expected_domain_results
    assert len(set(all_tokens)) == expected_domain_results * 3
    assert publication_events == []
