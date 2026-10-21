"""Lease-fenced catalog XLSX parse worker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from app.catalog.import_repository import MySqlCatalogImportRepository
from app.catalog.import_service import project_catalog_workbook
from app.catalog.ooxml import CatalogWorkbookUnsafeError
from app.catalog.workbook import parse_catalog_workbook
from app.imports.storage import ContentStoreError


class CatalogImportContentStore(Protocol):
    def read_bytes(
        self,
        storage_key: str,
        expected_sha256_hex: str,
        expected_size: int,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class CatalogImportWorkerResult:
    import_id: int
    status: str
    workflow_revision: int
    parse_attempt_revision: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CatalogImportWorker:
    def __init__(
        self,
        repository: MySqlCatalogImportRepository,
        store: CatalogImportContentStore,
        *,
        lease_ttl: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] = _utc_now,
        token_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        self._repository = repository
        self._store = store
        self._lease_ttl = lease_ttl
        self._clock = clock
        self._token_factory = token_factory

    def run_once(self) -> CatalogImportWorkerResult | None:
        lease = self._repository.claim_next_parse(
            lease_token=self._token_factory(),
            now=self._clock(),
            lease_ttl=self._lease_ttl,
        )
        if lease is None:
            return None
        try:
            content = self._store.read_bytes(
                lease.storage_key,
                lease.sha256_hex,
                lease.size_bytes,
            )
            workbook = parse_catalog_workbook(content)
            projection = project_catalog_workbook(workbook)
            revision = self._repository.complete_parse(
                lease,
                projection=projection,
                completed_at=self._clock(),
            )
            return CatalogImportWorkerResult(
                lease.import_id,
                projection.initial_status,
                revision,
                lease.parse_attempt_revision,
            )
        except CatalogWorkbookUnsafeError:
            revision = self._repository.fail_parse(
                lease,
                completed_at=self._clock(),
                recoverable=False,
                reason="catalog_workbook_unsafe",
            )
            return CatalogImportWorkerResult(
                lease.import_id,
                "parse_failed",
                revision,
                lease.parse_attempt_revision,
            )
        except ContentStoreError:
            revision = self._repository.fail_parse(
                lease,
                completed_at=self._clock(),
                recoverable=True,
                reason="catalog_source_temporarily_unavailable",
            )
            return CatalogImportWorkerResult(
                lease.import_id,
                "parse_failed",
                revision,
                lease.parse_attempt_revision,
            )


__all__ = ("CatalogImportWorker", "CatalogImportWorkerResult")
