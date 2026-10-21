"""Immutable source-file download endpoint tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.api import raw_files
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.config import StorageSettings
from app.imports.storage import ContentHashMismatchError
from sqlalchemy.orm import Session


class _MappingResult:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def mappings(self) -> _MappingResult:
        return self

    def first(self) -> dict[str, object] | None:
        return self._row


class _DatabaseSession:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row
        self.parameters: dict[str, object] | None = None

    def execute(
        self,
        _statement: object,
        parameters: dict[str, object],
    ) -> _MappingResult:
        self.parameters = parameters
        return _MappingResult(self.row)


def _row(*, integrity_status: str = "available") -> dict[str, object]:
    return {
        "storage_key": "sha256/ab/" + "ab" * 32,
        "sha256": bytes.fromhex("ab" * 32),
        "original_filename": "每日 报告.csv",
        "media_type": "text/csv",
        "size_bytes": 8,
        "integrity_status": integrity_status,
    }


def _principal() -> Principal:
    return cast(Principal, SimpleNamespace())


def test_download_returns_verified_bytes_and_safe_attachment_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_session = _DatabaseSession(_row())
    read_calls: list[tuple[str, str, int]] = []

    class _ContentStore:
        def read_bytes(
            self,
            storage_key: str,
            expected_digest: str,
            expected_size: int,
        ) -> bytes:
            read_calls.append((storage_key, expected_digest, expected_size))
            return b"a,b\n1,2\n"

    monkeypatch.setattr(
        StorageSettings,
        "from_env",
        classmethod(
            lambda cls: SimpleNamespace(root="D:/content", max_upload_bytes=1024)
        ),
    )
    monkeypatch.setattr(raw_files, "LocalContentStore", lambda *args: _ContentStore())

    response = raw_files.download_raw_file(
        17,
        _principal(),
        cast(Session, database_session),
    )

    assert database_session.parameters == {"batch_id": 17}
    assert read_calls == [("sha256/ab/" + "ab" * 32, "ab" * 32, 8)]
    assert response.body == b"a,b\n1,2\n"
    assert response.media_type == "text/csv"
    assert response.headers["content-disposition"] == (
        'attachment; filename="source.csv"; '
        "filename*=UTF-8''%E6%AF%8F%E6%97%A5%20%E6%8A%A5%E5%91%8A.csv"
    )
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_head_checks_metadata_without_reading_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspect_calls: list[tuple[str, str, int]] = []

    class _ContentStore:
        def inspect(
            self,
            storage_key: str,
            expected_digest: str,
            expected_size: int,
        ) -> object:
            inspect_calls.append((storage_key, expected_digest, expected_size))
            return SimpleNamespace()

        def read_bytes(self, *args: object) -> bytes:
            pytest.fail("HEAD must not read file bytes")

    monkeypatch.setattr(
        StorageSettings,
        "from_env",
        classmethod(
            lambda cls: SimpleNamespace(root="D:/content", max_upload_bytes=1024)
        ),
    )
    monkeypatch.setattr(raw_files, "LocalContentStore", lambda *args: _ContentStore())
    database_session = _DatabaseSession(_row())

    response = raw_files.check_raw_file(
        17,
        _principal(),
        cast(Session, database_session),
    )

    assert inspect_calls == [("sha256/ab/" + "ab" * 32, "ab" * 32, 8)]
    assert response.body == b""
    assert response.headers["cache-control"] == "private, no-store"


def test_preview_returns_bounded_rows_and_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ContentStore:
        def read_csv_preview(self, *args: object, **kwargs: object) -> object:
            assert args == ("sha256/ab/" + "ab" * 32, "ab" * 32, 8)
            assert kwargs == {"encoding": "utf-8", "row_limit": 200}
            return SimpleNamespace(
                headers=("sku", "sales"),
                rows=(("2301-White-S", "10"),),
                truncated=True,
            )

    monkeypatch.setattr(
        StorageSettings,
        "from_env",
        classmethod(
            lambda cls: SimpleNamespace(root="D:/content", max_upload_bytes=1024)
        ),
    )
    monkeypatch.setattr(raw_files, "LocalContentStore", lambda *args: _ContentStore())

    result = raw_files.preview_raw_file(
        17,
        _principal(),
        cast(Session, _DatabaseSession(_row())),
        encoding="utf-8",
        row_limit=200,
    )

    assert result.headers == ["sku", "sales"]
    assert result.rows == [["2301-White-S", "10"]]
    assert result.row_count == 1
    assert result.truncated is True


@pytest.mark.parametrize("integrity_status", ["missing", "corrupt"])
def test_download_rejects_a_database_integrity_failure(
    integrity_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        raw_files,
        "LocalContentStore",
        lambda *args: pytest.fail(
            "storage must not be read after a failed integrity scan"
        ),
    )

    with pytest.raises(ApiError) as raised:
        raw_files.download_raw_file(
            18,
            _principal(),
            cast(Session, _DatabaseSession(_row(integrity_status=integrity_status))),
        )

    assert raised.value.status_code == 409
    assert cast(dict[str, Any], raised.value.detail)["code"] == "raw_file_unavailable"


def test_download_maps_content_hash_failure_to_safe_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ContentStore:
        def read_bytes(self, *args: object) -> bytes:
            raise ContentHashMismatchError("secret storage path and digest details")

    monkeypatch.setattr(
        StorageSettings,
        "from_env",
        classmethod(
            lambda cls: SimpleNamespace(root="D:/content", max_upload_bytes=1024)
        ),
    )
    monkeypatch.setattr(raw_files, "LocalContentStore", lambda *args: _ContentStore())

    with pytest.raises(ApiError) as raised:
        raw_files.download_raw_file(
            19,
            _principal(),
            cast(Session, _DatabaseSession(_row())),
        )

    assert raised.value.status_code == 409
    detail: object = raised.value.detail
    assert detail == {
        "code": "raw_file_unavailable",
        "message": "The source file is unavailable or failed its integrity check.",
    }
