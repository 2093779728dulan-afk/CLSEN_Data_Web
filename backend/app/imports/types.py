"""Domain contracts for immutable raw-file ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

type ReportType = Literal["business_report", "return_report"]


class IngestError(RuntimeError):
    """Base class for raw-file ingestion failures."""


class LeaseNotFound(IngestError):
    """The supplied lease token does not identify a lease."""


class LeaseExpired(IngestError):
    """The active ingest lease expired before finalization."""


class InvalidLeaseTransition(IngestError):
    """A lease could not move through the required state transition."""


class IngestCommitFailed(IngestError):
    """The final database transaction is known not to have committed."""


class CommitOutcomeUnknown(IngestError):
    """The database connection failed while the commit outcome was uncertain."""


@dataclass(frozen=True, slots=True)
class ImportCommand:
    """Metadata accepted while storing an as-yet unconfirmed upload.

    A caller may preselect the business date, but the report type is deliberately
    absent.  Type and date become authoritative only through the later human
    confirmation workflow.
    """

    original_filename: str
    media_type: str | None
    created_by_user_id: int
    site_config_version_id: int
    report_date: date | None = None

    def __post_init__(self) -> None:
        filename = self.original_filename.strip()
        if not filename:
            raise ValueError("original_filename must not be blank")
        if len(filename) > 255:
            raise ValueError("original_filename must not exceed 255 characters")
        if self.media_type is not None and len(self.media_type) > 127:
            raise ValueError("media_type must not exceed 127 characters")
        if self.created_by_user_id < 1:
            raise ValueError("created_by_user_id must be positive")
        if self.site_config_version_id < 1:
            raise ValueError("site_config_version_id must be positive")
        object.__setattr__(self, "original_filename", filename)


@dataclass(frozen=True, slots=True)
class FinalizedImport:
    """Repository result after a conclusive finalization transaction."""

    raw_file_id: int
    batch_id: int
    created: bool


@dataclass(frozen=True, slots=True)
class ImportCreated:
    """A first import batch was created for the uploaded content."""

    raw_file_id: int
    batch_id: int
    sha256_hex: str
    storage_key: str
    size_bytes: int
    content_reused: bool


@dataclass(frozen=True, slots=True)
class DuplicateBatchConflict:
    """The same content already belongs to an import batch."""

    existing_batch_id: int
    raw_file_id: int
    sha256_hex: str


@dataclass(frozen=True, slots=True)
class RecoveredImport:
    """A completed result recovered after an uncertain commit acknowledgement."""

    raw_file_id: int
    batch_id: int


type IngestResult = ImportCreated | DuplicateBatchConflict | RecoveredImport
