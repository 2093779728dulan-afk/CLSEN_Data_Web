from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID, uuid4

from app.catalog.export_service import (
    CatalogExportCommand,
    CatalogExportMaterializer,
    catalog_download_filename,
    catalog_download_headers,
)
from app.catalog.workbook import CatalogWorkbookData
from app.imports.storage import StagedContent, StoredContent


def _data(*, style_rows: int = 0) -> CatalogWorkbookData:
    return CatalogWorkbookData(
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
            "款式主档": (
                (
                    "style",
                    None,
                    "100",
                    None,
                    "enabled",
                    0,
                    0,
                    None,
                    None,
                    None,
                ),
            )
            * style_rows,
            "SKU变体": (),
            "SellerSKU映射": (),
            "待处理异常": (),
            "来源证据": (),
        }
    )


class _Store:
    def __init__(self) -> None:
        self.staged: bytes | None = None
        self.discarded = False
        self.promoted = False

    def write_stream(self, token: UUID, source: object) -> StagedContent:
        self.staged = source.read()  # type: ignore[attr-defined]
        digest = hashlib.sha256(self.staged).hexdigest()
        return StagedContent(
            token,
            f".ingest/{token}.part",
            Path("staged"),
            digest,
            len(self.staged),
        )

    def promote(self, staged: StagedContent) -> StoredContent:
        self.promoted = True
        return StoredContent(
            storage_key=f"sha256/{staged.sha256_hex[:2]}/{staged.sha256_hex}",
            sha256_hex=staged.sha256_hex,
            size_bytes=staged.size_bytes,
            reused=False,
        )

    def discard_staged(self, staged: StagedContent) -> None:
        self.discarded = True


class _Finalizer:
    def __init__(self) -> None:
        self.ready: tuple[StoredContent | None, tuple[object, ...]] | None = None
        self.failed: str | None = None

    def finalize_ready(
        self,
        command: CatalogExportCommand,
        *,
        artifact: StoredContent | None,
        capacity_violations: tuple[object, ...],
    ) -> None:
        self.ready = artifact, capacity_violations

    def finalize_failed(self, command: CatalogExportCommand, *, reason: str) -> None:
        self.failed = reason


def _command(data: CatalogWorkbookData) -> CatalogExportCommand:
    return CatalogExportCommand(
        export_id=41,
        operation_token=uuid4(),
        payload_digest=b"p" * 32,
        workbook=data,
    )


def test_ready_export_round_trips_and_is_only_then_finalized() -> None:
    store = _Store()
    finalizer = _Finalizer()

    result = CatalogExportMaterializer(store=store, finalizer=finalizer).materialize(
        _command(_data(style_rows=1))
    )

    assert result.export_status == "ready"
    assert result.workbook_status == "ready"
    assert store.promoted and store.discarded
    assert finalizer.ready is not None
    assert finalizer.ready[0] is not None
    assert finalizer.ready[1] == ()


def test_row_capacity_stays_online_ready_without_artifact() -> None:
    store = _Store()
    finalizer = _Finalizer()

    result = CatalogExportMaterializer(store=store, finalizer=finalizer).materialize(
        _command(_data(style_rows=30_001))
    )

    assert result.export_status == "ready"
    assert result.workbook_status == "capacity_exceeded"
    assert result.capacity_violations[0].code == "sheet_row_limit"
    assert store.staged is None and not store.promoted
    assert finalizer.ready is not None and finalizer.ready[0] is None


def test_download_name_and_headers_are_fixed_and_content_free() -> None:
    expected = hashlib.sha256(b"41").hexdigest()[:16]
    filename = catalog_download_filename(41)
    assert filename == f"product-catalog-{expected}.xlsx"
    assert catalog_download_headers(41) == {
        "Content-Type": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
