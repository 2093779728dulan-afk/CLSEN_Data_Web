from __future__ import annotations

import json
from datetime import datetime
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from app.parsers.repository import (
    MySqlParseRepository,
    _decoded_fields,
    _is_pymysql_duplicate_key,
)
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

_FAKE_PYMYSQL_INTEGRITY_ERROR = cast(
    type[Exception],
    type(
        "IntegrityError",
        (Exception,),
        {"__module__": "pymysql.err"},
    ),
)


def _integrity_error(code: int) -> IntegrityError:
    return IntegrityError(
        "INSERT INTO parse_operation_tokens ...",
        {},
        _FAKE_PYMYSQL_INTEGRITY_ERROR(code, "synthetic constraint error"),
    )


def test_failed_source_snapshot_preserves_duplicate_and_uneven_columns() -> None:
    serialized = _decoded_fields(
        ("duplicate", "duplicate", "third"),
        ("first", "second"),
    )

    assert json.loads(serialized) == {
        "header": ["duplicate", "duplicate", "third"],
        "values": ["first", "second"],
    }


def test_duplicate_key_detection_is_limited_to_pymysql_1062() -> None:
    assert _is_pymysql_duplicate_key(_integrity_error(1062))
    assert not _is_pymysql_duplicate_key(_integrity_error(1452))
    assert not _is_pymysql_duplicate_key(
        IntegrityError("INSERT ...", {}, RuntimeError(1062, "not PyMySQL"))
    )


def test_parse_token_claim_propagates_other_integrity_errors_unchanged() -> None:
    connection_mock = MagicMock(spec=Connection)
    savepoint = MagicMock()
    connection_mock.begin_nested.return_value = savepoint
    error = _integrity_error(1452)
    connection_mock.execute.side_effect = error

    with pytest.raises(IntegrityError) as raised:
        MySqlParseRepository._claim_parse_operation(
            cast(Connection, connection_mock),
            processing_token=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            batch_id=7,
            operation_digest=b"d" * 32,
            registered_at=datetime(2026, 8, 7, 8, 0),
        )

    assert raised.value is error
    savepoint.rollback.assert_called_once_with()
