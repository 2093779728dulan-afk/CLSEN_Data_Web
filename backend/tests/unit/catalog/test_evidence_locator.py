import json

import pytest
from app.catalog.queries import _source_event_timestamp


def test_original_timestamp_keeps_offset_and_does_not_expose_other_fields() -> None:
    payload = json.dumps(
        {
            "header": ["order-id", "return-date"],
            "values": ["private-order", "2026-07-08T00:45:40+00:00"],
        }
    )
    assert (
        _source_event_timestamp(payload, "return_report") == "2026-07-08T00:45:40+00:00"
    )
    assert _source_event_timestamp(payload, "business_report") is None


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "bad-json",
        {},
        {"header": [], "values": []},
        {"header": ["return-date"], "values": []},
    ],
)
def test_missing_original_timestamp_is_not_invented(payload: object) -> None:
    assert _source_event_timestamp(payload, "return_report") is None
