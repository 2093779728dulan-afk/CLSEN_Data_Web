from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from app.catalog.export_service import CATALOG_WORKBOOK_MEDIA_TYPE
from app.catalog.ooxml import CatalogWorkbookUnsafeError
from app.catalog.upload_service import (
    CatalogRawUploadCommand,
    CatalogRawUploadService,
    CatalogUploadMetadataError,
    parse_catalog_upload_metadata,
)
from app.catalog.workbook import CatalogWorkbookData, render_catalog_workbook
from app.imports.storage import StagedContent, StoredContent


def _archive() -> bytes:
    return render_catalog_workbook(
        CatalogWorkbookData(
            rows={
                "生成信息": (
                    ("模板版本", "product_catalog_workbook_v1"),
                    ("目录导出ID", "41"),
                    ("站点代码", "US"),
                    ("Seller Account", "seller"),
                    ("Marketplace", "amazon_us"),
                    ("基础目录版本", None),
                    ("来源快照摘要", "sha256:" + "0" * 64),
                    ("规范化规则版本", "manifest-v1"),
                    ("生成时间", "2026-08-21T00:00:00Z"),
                ),
                "款式主档": (),
                "SKU变体": (),
                "SellerSKU映射": (),
                "待处理异常": (),
                "来源证据": (),
            }
        )
    )


class _Store:
    def __init__(self) -> None:
        self.discarded = False
        self.promoted = False

    def write_stream(self, token: UUID, source: object) -> StagedContent:
        content = source.read()  # type: ignore[attr-defined]
        digest = hashlib.sha256(content).hexdigest()
        return StagedContent(
            token,
            f".ingest/{token}.part",
            Path("staged"),
            digest,
            len(content),
        )

    def promote(self, staged: StagedContent) -> StoredContent:
        self.promoted = True
        return StoredContent(
            f"sha256/{staged.sha256_hex[:2]}/{staged.sha256_hex}",
            staged.sha256_hex,
            staged.size_bytes,
            False,
        )

    def discard_staged(self, staged: StagedContent) -> None:
        self.discarded = True


class _Repository:
    def __init__(self) -> None:
        self.calls = 0

    def register_upload(
        self,
        command: CatalogRawUploadCommand,
        *,
        stored: StoredContent,
        workbook: CatalogWorkbookData,
    ) -> int:
        self.calls += 1
        assert workbook.rows["生成信息"][1][1] == "41"
        return 7


def _command(content: bytes) -> CatalogRawUploadCommand:
    return CatalogRawUploadCommand(
        operation_token=uuid4(),
        original_filename="catalog.xlsx",
        declared_media_type=CATALOG_WORKBOOK_MEDIA_TYPE,
        declared_content_length=len(content),
        site_id=1,
        owner_user_id=2,
    )


def test_metadata_requires_uuid4_encoded_filename_exact_type_and_length() -> None:
    token = uuid4()
    metadata = parse_catalog_upload_metadata(
        idempotency_key=str(token),
        original_filename="product%20catalog.xlsx",
        content_type=CATALOG_WORKBOOK_MEDIA_TYPE,
        content_length="123",
        configured_max_upload_bytes=200,
    )
    assert metadata.operation_token == token
    assert metadata.original_filename == "product catalog.xlsx"
    assert metadata.declared_content_length == 123

    for overrides in (
        {"idempotency_key": "00000000-0000-0000-0000-000000000000"},
        {"original_filename": "catalog.xlsm"},
        {"content_type": "application/octet-stream"},
        {"content_length": "201"},
    ):
        arguments = {
            "idempotency_key": str(token),
            "original_filename": "catalog.xlsx",
            "content_type": CATALOG_WORKBOOK_MEDIA_TYPE,
            "content_length": "123",
            "configured_max_upload_bytes": 200,
            **overrides,
        }
        with pytest.raises(CatalogUploadMetadataError):
            parse_catalog_upload_metadata(
                idempotency_key=cast(str, arguments["idempotency_key"]),
                original_filename=cast(str, arguments["original_filename"]),
                content_type=cast(str, arguments["content_type"]),
                content_length=cast(str, arguments["content_length"]),
                configured_max_upload_bytes=cast(
                    int, arguments["configured_max_upload_bytes"]
                ),
            )


def test_safe_body_is_hashed_validated_promoted_then_registered() -> None:
    content = _archive()
    store = _Store()
    repository = _Repository()

    result = CatalogRawUploadService(
        store=store, repository=repository, configured_max_upload_bytes=10_000_000
    ).upload(io.BytesIO(content), _command(content))

    assert result.catalog_import_id == 7
    assert result.sha256_hex == hashlib.sha256(content).hexdigest()
    assert store.promoted and store.discarded
    assert repository.calls == 1


def test_unsafe_or_length_mismatched_body_is_never_registered() -> None:
    repository = _Repository()
    store = _Store()
    service = CatalogRawUploadService(
        store=store, repository=repository, configured_max_upload_bytes=10_000_000
    )
    content = b"not an xlsx"
    with pytest.raises(CatalogWorkbookUnsafeError):
        service.upload(io.BytesIO(content), _command(content))
    assert repository.calls == 0 and not store.promoted and store.discarded

    archive = _archive()
    command = _command(archive)
    command = CatalogRawUploadCommand(
        operation_token=command.operation_token,
        original_filename=command.original_filename,
        declared_media_type=command.declared_media_type,
        declared_content_length=len(archive) + 1,
        site_id=command.site_id,
        owner_user_id=command.owner_user_id,
    )
    with pytest.raises(CatalogUploadMetadataError):
        service.upload(io.BytesIO(archive), command)
    assert repository.calls == 0
