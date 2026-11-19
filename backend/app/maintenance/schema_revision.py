"""Single source of truth for schema writers and compatible backup readers."""

from __future__ import annotations

CURRENT_SCHEMA_REVISION = "0037"
BACKUP_READER_SCHEMA_REVISIONS = (
    "0020",
    "0021",
    "0022",
    "0023",
    "0024",
    "0025",
    "0026",
    "0027",
    "0028",
    "0029",
    "0030",
    "0031",
    "0032",
    "0033",
    "0034",
    "0035",
    "0036",
    "0037",
)

__all__ = ("BACKUP_READER_SCHEMA_REVISIONS", "CURRENT_SCHEMA_REVISION")
