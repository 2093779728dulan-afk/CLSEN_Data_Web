from __future__ import annotations

import json

from app.api.catalog_common import catalog_json
from app.api.catalog_queries import encode_sensitive_source


def test_sensitive_source_encoding_is_ascii_and_reversible_without_raw_json() -> None:
    result = encode_sensitive_source("safe\n危险")
    assert result.code_points == "U+0073 U+0061 U+0066 U+0065 U+000A U+5371 U+9669"
    assert result.utf8_base64url == "c2FmZQrljbHpmak"
    assert "危险" not in result.model_dump_json()


def test_sensitive_source_encoding_uses_the_catalog_json_boundary() -> None:
    response = catalog_json(encode_sensitive_source('LIVE-DANGER</script>&"RAW'))

    payload = json.loads(bytes(response.body))
    assert payload["code_points"].startswith("U+004C U+0049 U+0056 U+0045")
    assert payload["utf8_base64url"].startswith("TElWRS1EQU5HRVI")
