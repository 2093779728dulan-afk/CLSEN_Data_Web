"""Bounded raw-body upload boundary for catalog XLSX imports."""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from unicodedata import normalize
from urllib.parse import unquote_to_bytes
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.catalog.export_service import CATALOG_WORKBOOK_MEDIA_TYPE
from app.catalog.ooxml import MAX_ARCHIVE_BYTES
from app.catalog.workbook import CatalogWorkbookData, parse_catalog_workbook
from app.imports.storage import StagedContent, StoredContent, UploadTooLargeError


class CatalogUploadMetadataError(ValueError):
    code = "catalog_upload_metadata_invalid"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(self.code)


class CatalogUploadRegistrationError(RuntimeError):
    code = "catalog_upload_registration_conflict"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CatalogUploadMetadata:
    operation_token: UUID
    original_filename: str
    declared_media_type: str
    declared_content_length: int
    effective_max_upload_bytes: int


@dataclass(frozen=True, slots=True)
class CatalogRawUploadCommand:
    operation_token: UUID
    original_filename: str
    declared_media_type: str
    declared_content_length: int
    site_id: int
    owner_user_id: int


@dataclass(frozen=True, slots=True)
class CatalogRawUploadResult:
    catalog_import_id: int
    raw_file_storage_key: str
    sha256_hex: str
    size_bytes: int


class CatalogUploadStore(Protocol):
    def write_stream(self, token: UUID, source: object) -> StagedContent: ...

    def promote(self, staged: StagedContent) -> StoredContent: ...

    def discard_staged(self, staged: StagedContent) -> None: ...


class CatalogUploadRepository(Protocol):
    def register_upload(
        self,
        command: CatalogRawUploadCommand,
        *,
        stored: StoredContent,
        workbook: CatalogWorkbookData,
    ) -> int: ...


def parse_catalog_upload_metadata(
    *,
    idempotency_key: str,
    original_filename: str,
    content_type: str,
    content_length: str,
    configured_max_upload_bytes: int,
) -> CatalogUploadMetadata:
    try:
        token = UUID(idempotency_key)
    except (AttributeError, TypeError, ValueError) as error:
        raise CatalogUploadMetadataError("idempotency_key_invalid") from error
    if token.version != 4 or str(token) != idempotency_key.lower():
        raise CatalogUploadMetadataError("idempotency_key_invalid")
    if content_type != CATALOG_WORKBOOK_MEDIA_TYPE:
        raise CatalogUploadMetadataError("content_type_invalid")
    try:
        decoded = unquote_to_bytes(original_filename).decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError) as error:
        raise CatalogUploadMetadataError("original_filename_invalid") from error
    decoded = normalize("NFC", decoded)
    if (
        not decoded
        or len(decoded) > 512
        or not decoded.casefold().endswith(".xlsx")
        or "/" in decoded
        or "\\" in decoded
        or any(ord(character) < 32 or ord(character) == 127 for character in decoded)
    ):
        raise CatalogUploadMetadataError("original_filename_invalid")
    try:
        length = int(content_length, 10)
    except (TypeError, ValueError) as error:
        raise CatalogUploadMetadataError("content_length_invalid") from error
    if type(configured_max_upload_bytes) is not int or configured_max_upload_bytes < 1:
        raise ValueError("configured_max_upload_bytes must be positive")
    effective_limit = min(configured_max_upload_bytes, MAX_ARCHIVE_BYTES)
    if length < 1 or length > effective_limit:
        raise CatalogUploadMetadataError("content_length_invalid")
    return CatalogUploadMetadata(
        token,
        decoded,
        content_type,
        length,
        effective_limit,
    )


class _BoundedReader:
    def __init__(self, source: object, limit: int) -> None:
        self._source = source
        self._remaining = limit + 1

    def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            raise UploadTooLargeError()
        requested = self._remaining if size < 0 else min(size, self._remaining)
        chunk = self._source.read(requested)  # type: ignore[attr-defined]
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise TypeError("catalog upload stream must return bytes")
        content = bytes(chunk)
        self._remaining -= len(content)
        if self._remaining == 0 and content:
            raise UploadTooLargeError()
        return content


class CatalogRawUploadService:
    """Stage and hash bytes, safety-parse, then register a catalog-only import."""

    def __init__(
        self,
        *,
        store: CatalogUploadStore,
        repository: CatalogUploadRepository,
        configured_max_upload_bytes: int,
    ) -> None:
        if (
            type(configured_max_upload_bytes) is not int
            or configured_max_upload_bytes < 1
        ):
            raise ValueError("configured_max_upload_bytes must be positive")
        self._store = store
        self._repository = repository
        self._limit = min(configured_max_upload_bytes, MAX_ARCHIVE_BYTES)

    def upload(
        self,
        source: io.BufferedIOBase | io.BytesIO,
        command: CatalogRawUploadCommand,
    ) -> CatalogRawUploadResult:
        if command.operation_token.version != 4:
            raise CatalogUploadMetadataError("idempotency_key_invalid")
        if command.declared_media_type != CATALOG_WORKBOOK_MEDIA_TYPE:
            raise CatalogUploadMetadataError("content_type_invalid")
        if (
            command.declared_content_length < 1
            or command.declared_content_length > self._limit
        ):
            raise CatalogUploadMetadataError("content_length_invalid")
        staged = self._store.write_stream(
            command.operation_token, _BoundedReader(source, self._limit)
        )
        try:
            if staged.size_bytes != command.declared_content_length:
                raise CatalogUploadMetadataError("content_length_mismatch")
            source.seek(0)
            content = source.read(self._limit + 1)
            if len(content) != staged.size_bytes:
                raise CatalogUploadMetadataError("content_length_mismatch")
            workbook = parse_catalog_workbook(content, max_archive_bytes=self._limit)
            stored = self._store.promote(staged)
            catalog_import_id = self._repository.register_upload(
                command,
                stored=stored,
                workbook=workbook,
            )
            return CatalogRawUploadResult(
                catalog_import_id,
                stored.storage_key,
                stored.sha256_hex,
                stored.size_bytes,
            )
        finally:
            self._store.discard_staged(staged)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MySqlCatalogUploadRepository:
    """Atomically register one raw file and one catalog import, never a daily batch."""

    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._engine = engine
        self._clock = clock

    def register_upload(
        self,
        command: CatalogRawUploadCommand,
        *,
        stored: StoredContent,
        workbook: CatalogWorkbookData,
    ) -> int:
        metadata: dict[str, object] = {}
        for row in workbook.rows["生成信息"]:
            if len(row) != 2 or not isinstance(row[0], str):
                raise CatalogUploadRegistrationError()
            metadata[row[0]] = row[1]
        export_text = metadata.get("目录导出ID")
        try:
            export_id = int(str(export_text), 10)
        except (TypeError, ValueError) as error:
            raise CatalogUploadRegistrationError() from error
        if export_id < 1:
            raise CatalogUploadRegistrationError()
        digest = bytes.fromhex(stored.sha256_hex)
        uploaded_at = self._clock()
        if uploaded_at.tzinfo is None or uploaded_at.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        timestamp = uploaded_at.astimezone(UTC).replace(tzinfo=None)
        with self._engine.begin() as connection:
            existing_id = connection.scalar(
                sa.text(
                    "SELECT id FROM catalog_imports "
                    "WHERE operation_token = :operation_token FOR UPDATE"
                ),
                {"operation_token": command.operation_token.bytes},
            )
            existing = None
            if existing_id is not None:
                existing = (
                    connection.execute(
                        sa.text(
                            """
                            SELECT imports.id, imports.site_id,
                                   imports.owner_user_id, imports.export_id,
                                   imports.original_filename,
                                   imports.declared_media_type,
                                   files.sha256, files.storage_key,
                                   files.size_bytes
                            FROM catalog_imports AS imports
                            INNER JOIN raw_files AS files
                                ON files.id = imports.raw_file_id
                            WHERE imports.id = :import_id
                            """
                        ),
                        {"import_id": int(existing_id)},
                    )
                    .mappings()
                    .one_or_none()
                )
            if existing is not None:
                if (
                    int(existing["site_id"]) != command.site_id
                    or int(existing["owner_user_id"]) != command.owner_user_id
                    or int(existing["export_id"]) != export_id
                    or existing["original_filename"] != command.original_filename
                    or existing["declared_media_type"] != command.declared_media_type
                    or bytes(existing["sha256"]) != digest
                    or existing["storage_key"] != stored.storage_key
                    or int(existing["size_bytes"]) != stored.size_bytes
                ):
                    raise CatalogUploadRegistrationError()
                return int(existing["id"])

            export = (
                connection.execute(
                    sa.text(
                        """
                        SELECT id, site_id, base_catalog_version_id,
                               fact_snapshot_tuple_id, normalization_manifest_id,
                               export_status, workbook_status
                        FROM catalog_exports
                        WHERE id = :export_id AND site_id = :site_id
                        FOR SHARE
                        """
                    ),
                    {"export_id": export_id, "site_id": command.site_id},
                )
                .mappings()
                .one_or_none()
            )
            if (
                export is None
                or export["export_status"] != "ready"
                or export["workbook_status"] != "ready"
            ):
                raise CatalogUploadRegistrationError()

            connection.execute(
                sa.text(
                    """
                    INSERT IGNORE INTO raw_files (
                        sha256, storage_key, original_filename, media_type,
                        size_bytes, uploaded_by_user_id, uploaded_at
                    ) VALUES (
                        :sha256, :storage_key, :filename, :media_type,
                        :size_bytes, :owner_user_id, :uploaded_at
                    )
                    """
                ),
                {
                    "sha256": digest,
                    "storage_key": stored.storage_key,
                    "filename": command.original_filename,
                    "media_type": command.declared_media_type,
                    "size_bytes": stored.size_bytes,
                    "owner_user_id": command.owner_user_id,
                    "uploaded_at": timestamp,
                },
            )
            raw = (
                connection.execute(
                    sa.text(
                        "SELECT id, storage_key, size_bytes FROM raw_files "
                        "WHERE sha256 = :sha256"
                    ),
                    {"sha256": digest},
                )
                .mappings()
                .one_or_none()
            )
            if (
                raw is None
                or raw["storage_key"] != stored.storage_key
                or int(raw["size_bytes"]) != stored.size_bytes
            ):
                raise CatalogUploadRegistrationError()
            raw_file_id = int(raw["id"])

            inserted_import = connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_imports (
                        site_id, operation_token, source_kind, owner_user_id,
                        export_id, raw_file_id, original_filename,
                        declared_media_type, base_catalog_version_id,
                        fact_snapshot_tuple_id, normalization_manifest_id,
                        status, workflow_revision, parse_attempt_revision
                    ) VALUES (
                        :site_id, :operation_token, 'xlsx', :owner_user_id,
                        :export_id, :raw_file_id, :filename,
                        :media_type, :base_catalog_version_id,
                        :fact_snapshot_tuple_id, :normalization_manifest_id,
                        'uploaded', 0, 0
                    )
                    """
                ),
                {
                    "site_id": command.site_id,
                    "operation_token": command.operation_token.bytes,
                    "owner_user_id": command.owner_user_id,
                    "export_id": export_id,
                    "raw_file_id": raw_file_id,
                    "filename": command.original_filename,
                    "media_type": command.declared_media_type,
                    "base_catalog_version_id": export["base_catalog_version_id"],
                    "fact_snapshot_tuple_id": int(export["fact_snapshot_tuple_id"]),
                    "normalization_manifest_id": export["normalization_manifest_id"],
                },
            )
            if inserted_import.lastrowid is None:
                raise CatalogUploadRegistrationError()
            return int(inserted_import.lastrowid)


__all__ = (
    "CatalogRawUploadCommand",
    "CatalogRawUploadResult",
    "CatalogRawUploadService",
    "CatalogUploadMetadata",
    "CatalogUploadMetadataError",
    "CatalogUploadRegistrationError",
    "MySqlCatalogUploadRepository",
    "parse_catalog_upload_metadata",
)
