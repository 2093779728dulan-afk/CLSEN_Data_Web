"""Bounded byte decoding and strict standard-library CSV semantics."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
from threading import Lock

from app.parsers.types import ParseError, SupportedEncoding

_FIELD_SIZE_LIMIT_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class CsvDocument:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def decode_content(content: bytes, encoding: SupportedEncoding) -> str:
    try:
        return content.decode(encoding, errors="strict")
    except UnicodeDecodeError as error:
        raise ParseError(
            f"content is not valid {encoding}",
            code="invalid_encoding",
        ) from error


def read_csv_document(
    content: bytes,
    *,
    encoding: SupportedEncoding,
    delimiter: str = ",",
) -> CsvDocument:
    text = decode_content(content, encoding)
    with _FIELD_SIZE_LIMIT_LOCK:
        current_limit = csv.field_size_limit()
        if len(text) > current_limit:
            # Uploads are already bounded. The lock keeps this process-wide limit
            # monotonic while concurrent reports contain differently sized fields.
            csv.field_size_limit(len(text))

    reader = csv.reader(StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        header = tuple(next(reader))
    except StopIteration as error:
        raise ParseError("CSV is empty", code="empty_csv") from error
    except csv.Error as error:
        raise ParseError("invalid CSV header", code="invalid_csv") from error

    rows: list[tuple[str, ...]] = []
    try:
        rows.extend(tuple(row) for row in reader)
    except csv.Error as error:
        raise ParseError("invalid CSV content", code="invalid_csv") from error
    return CsvDocument(header=header, rows=tuple(rows))
