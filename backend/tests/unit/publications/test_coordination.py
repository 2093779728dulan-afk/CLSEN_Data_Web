from __future__ import annotations

import pytest
from app.publications import MySqlTransactionRetryPolicy, ordered_dataset_ids


def test_dataset_lock_order_is_positive_unique_and_ascending() -> None:
    assert ordered_dataset_ids((9, 3, 9, 5)) == (3, 5, 9)
    with pytest.raises(ValueError, match="at least one"):
        ordered_dataset_ids(())
    with pytest.raises(ValueError, match="positive"):
        ordered_dataset_ids((3, 0))


@pytest.mark.parametrize("error_code", [1205, 1213])
def test_retry_policy_allows_exactly_four_total_transaction_attempts(
    error_code: int,
) -> None:
    policy = MySqlTransactionRetryPolicy()

    assert policy.max_attempts == 4
    assert [policy.should_retry(error_code, attempt) for attempt in range(1, 5)] == [
        True,
        True,
        True,
        False,
    ]


def test_retry_policy_never_replays_non_retryable_or_invalidated_connections() -> None:
    policy = MySqlTransactionRetryPolicy()

    assert not policy.should_retry(1048, failed_attempt=1)
    assert not policy.should_retry(1213, failed_attempt=1, connection_invalidated=True)
    with pytest.raises(ValueError, match="failed_attempt"):
        policy.should_retry(1213, failed_attempt=0)
    with pytest.raises(ValueError, match="failed_attempt"):
        policy.should_retry(1213, failed_attempt=5)
