"""Fail-closed ZIP and OOXML envelope validation for catalog workbooks."""

from __future__ import annotations

import io
import os
import posixpath
import struct
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Never

from defusedxml import ElementTree as SafeElementTree  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

MIB: Final = 1024 * 1024
MAX_ARCHIVE_BYTES: Final = 100 * MIB
MAX_MEMBER_COUNT: Final = 128
MAX_MEMBER_UNCOMPRESSED_BYTES: Final = 64 * MIB
MAX_WORKBOOK_UNCOMPRESSED_BYTES: Final = 200 * MIB
MAX_COMPRESSION_RATIO: Final = 200
STREAM_BYTES: Final = MIB

SHEET_NAMES: Final = (
    "生成信息",
    "款式主档",
    "SKU变体",
    "SellerSKU映射",
    "待处理异常",
    "来源证据",
)

_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOCUMENT_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_REL_OFFICE_DOCUMENT = f"{_DOCUMENT_REL_NS}/officeDocument"
_REL_CORE = f"{_PACKAGE_REL_NS}/metadata/core-properties"
_REL_APP = f"{_DOCUMENT_REL_NS}/extended-properties"
_REL_WORKSHEET = f"{_DOCUMENT_REL_NS}/worksheet"
_REL_STYLES = f"{_DOCUMENT_REL_NS}/styles"
_REL_SHARED_STRINGS = f"{_DOCUMENT_REL_NS}/sharedStrings"
_REL_THEME = f"{_DOCUMENT_REL_NS}/theme"

_BASE_PARTS: Final = frozenset(
    {
        "[Content_Types].xml",
        "_rels/.rels",
        "docProps/core.xml",
        "docProps/app.xml",
        "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels",
        "xl/styles.xml",
        *(f"xl/worksheets/sheet{index}.xml" for index in range(1, 7)),
    }
)
_OPTIONAL_PARTS: Final = frozenset(
    {"xl/sharedStrings.xml", "xl/theme/theme1.xml", "docProps/custom.xml"}
)
_CONTENT_TYPE_DEFAULTS: Final = {
    "rels": "application/vnd.openxmlformats-package.relationships+xml",
    "xml": "application/xml",
}
_CONTENT_TYPE_OVERRIDES: Final = {
    "/docProps/custom.xml": (
        "application/vnd.openxmlformats-officedocument.custom-properties+xml"
    ),
    "/docProps/core.xml": (
        "application/vnd.openxmlformats-package.core-properties+xml"
    ),
    "/docProps/app.xml": (
        "application/vnd.openxmlformats-officedocument.extended-properties+xml"
    ),
    "/xl/workbook.xml": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    ),
    "/xl/styles.xml": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"
    ),
    "/xl/sharedStrings.xml": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
    ),
    "/xl/theme/theme1.xml": ("application/vnd.openxmlformats-officedocument.theme+xml"),
    **{
        f"/xl/worksheets/sheet{index}.xml": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
        )
        for index in range(1, 7)
    },
}
_LOCAL_FILE_HEADER = struct.Struct("<IHHHHHIIIHH")
_LOCAL_FILE_SIGNATURE = 0x04034B50


class CatalogWorkbookUnsafeError(ValueError):
    """An externally content-free unsafe-workbook error."""

    code = "catalog_workbook_unsafe"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(self.code)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, reason={self.reason!r})"


@dataclass(frozen=True, slots=True)
class CapacityViolation:
    code: str
    sheet_or_member: str | None
    actual: str
    limit: str
    unit: str


class CatalogWorkbookCapacityError(ValueError):
    """A safe workbook cannot be represented within the v1 workbook limits."""

    code = "catalog_workbook_capacity_exceeded"

    def __init__(self, violations: tuple[CapacityViolation, ...]) -> None:
        if not violations:
            raise ValueError("capacity violations must not be empty")
        self.violations = violations
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class ValidatedCatalogOoxml:
    archive_bytes: int
    member_count: int
    total_uncompressed_bytes: int
    members: tuple[str, ...]


def _unsafe(reason: str) -> Never:
    raise CatalogWorkbookUnsafeError(reason)


def _read_archive(source: bytes | bytearray | memoryview | Path) -> bytes:
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source)
    if not isinstance(source, Path):
        raise TypeError("source must be bytes or pathlib.Path")
    try:
        before = source.stat(follow_symlinks=False)
        if not source.is_file() or source.is_symlink():
            _unsafe("archive_not_regular_file")
        with source.open("rb") as handle:
            content = handle.read()
            opened = os.fstat(handle.fileno())
        after = source.stat(follow_symlinks=False)
    except CatalogWorkbookUnsafeError:
        raise
    except OSError:
        _unsafe("archive_read_failed")
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        or len(content) != before.st_size
    ):
        _unsafe("archive_changed_during_read")
    return content


def _parse_xml(content: bytes) -> SafeElementTree.Element:
    try:
        return SafeElementTree.fromstring(
            content,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except DefusedXmlException:
        _unsafe("ooxml_xml_unsafe")
    except SafeElementTree.ParseError:
        _unsafe("ooxml_xml_invalid")


def _safe_member_name(name: str) -> str:
    if not name or "\x00" in name or "\\" in name:
        _unsafe("zip_member_path_invalid")
    if name.startswith("/") or name.endswith("/"):
        _unsafe("zip_member_path_invalid")
    if len(name) >= 2 and name[1] == ":":
        _unsafe("zip_member_path_invalid")
    segments = name.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        _unsafe("zip_member_path_invalid")
    if posixpath.normpath(name) != name:
        _unsafe("zip_member_path_invalid")
    return unicodedata.normalize("NFC", name).casefold()


def _decode_local_name(raw_name: bytes, flags: int) -> str:
    try:
        return raw_name.decode("utf-8" if flags & 0x800 else "cp437")
    except UnicodeDecodeError:
        _unsafe("zip_local_header_mismatch")


def _validate_local_header(archive: bytes, info: zipfile.ZipInfo) -> None:
    start = info.header_offset
    end = start + _LOCAL_FILE_HEADER.size
    if start < 0 or end > len(archive):
        _unsafe("zip_local_header_mismatch")
    values = _LOCAL_FILE_HEADER.unpack(archive[start:end])
    (
        signature,
        _version,
        flags,
        compression,
        _time,
        _date,
        crc,
        compressed_size,
        uncompressed_size,
        name_size,
        extra_size,
    ) = values
    name_start = end
    name_end = name_start + name_size
    extra_end = name_end + extra_size
    if signature != _LOCAL_FILE_SIGNATURE or extra_end > len(archive):
        _unsafe("zip_local_header_mismatch")
    local_name = _decode_local_name(archive[name_start:name_end], flags)
    if (
        local_name != info.filename
        or flags != info.flag_bits
        or compression != info.compress_type
    ):
        _unsafe("zip_local_header_mismatch")
    if flags & 0x08:
        if any(value != 0 for value in (crc, compressed_size, uncompressed_size)) and (
            crc != info.CRC
            or compressed_size != info.compress_size
            or uncompressed_size != info.file_size
        ):
            _unsafe("zip_local_header_mismatch")
    elif (
        crc != info.CRC
        or compressed_size != info.compress_size
        or uncompressed_size != info.file_size
    ):
        _unsafe("zip_local_header_mismatch")


def _relationship_rows(root: SafeElementTree.Element) -> list[dict[str, str]]:
    if root.tag != f"{{{_RELATIONSHIPS_NS}}}Relationships":
        _unsafe("ooxml_relationship_contract_mismatch")
    rows: list[dict[str, str]] = []
    for child in root:
        if child.tag != f"{{{_RELATIONSHIPS_NS}}}Relationship" or list(child):
            _unsafe("ooxml_relationship_contract_mismatch")
        attributes = dict(child.attrib)
        if set(attributes) - {"Id", "Type", "Target", "TargetMode"}:
            _unsafe("ooxml_relationship_contract_mismatch")
        if attributes.get("TargetMode") is not None:
            if attributes["TargetMode"] == "External":
                _unsafe("ooxml_external_relationship")
            _unsafe("ooxml_relationship_contract_mismatch")
        if not all(attributes.get(key) for key in ("Id", "Type", "Target")):
            _unsafe("ooxml_relationship_contract_mismatch")
        rows.append(attributes)
    ids = [row["Id"] for row in rows]
    if len(ids) != len(set(ids)):
        _unsafe("ooxml_relationship_contract_mismatch")
    return rows


def _validate_content_types(parts: dict[str, bytes]) -> None:
    root = _parse_xml(parts["[Content_Types].xml"])
    if root.tag != f"{{{_CONTENT_TYPES_NS}}}Types" or root.attrib:
        _unsafe("ooxml_content_types_mismatch")
    defaults: dict[str, str] = {}
    overrides: dict[str, str] = {}
    for child in root:
        if child.tag == f"{{{_CONTENT_TYPES_NS}}}Default":
            if set(child.attrib) != {"Extension", "ContentType"} or list(child):
                _unsafe("ooxml_content_types_mismatch")
            key = child.attrib["Extension"]
            if key in defaults:
                _unsafe("ooxml_content_types_mismatch")
            defaults[key] = child.attrib["ContentType"]
        elif child.tag == f"{{{_CONTENT_TYPES_NS}}}Override":
            if set(child.attrib) != {"PartName", "ContentType"} or list(child):
                _unsafe("ooxml_content_types_mismatch")
            key = child.attrib["PartName"]
            if key in overrides:
                _unsafe("ooxml_content_types_mismatch")
            overrides[key] = child.attrib["ContentType"]
        else:
            _unsafe("ooxml_content_types_mismatch")
    expected = {
        name: content_type
        for name, content_type in _CONTENT_TYPE_OVERRIDES.items()
        if name.removeprefix("/") in parts
    }
    if defaults != _CONTENT_TYPE_DEFAULTS or overrides != expected:
        _unsafe("ooxml_content_types_mismatch")


def _validate_relationships(parts: dict[str, bytes]) -> None:
    root_rows = _relationship_rows(_parse_xml(parts["_rels/.rels"]))
    expected_root = {
        (_REL_OFFICE_DOCUMENT, "xl/workbook.xml"),
        (_REL_CORE, "docProps/core.xml"),
        (_REL_APP, "docProps/app.xml"),
    }
    if "docProps/custom.xml" in parts:
        expected_root.add(
            (f"{_DOCUMENT_REL_NS}/custom-properties", "docProps/custom.xml")
        )
        custom = _parse_xml(parts["docProps/custom.xml"])
        ns = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
        vt = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
        if custom.tag != f"{{{ns}}}Properties":
            _unsafe("ooxml_custom_properties_invalid")
        for prop in custom:
            if (
                prop.tag != f"{{{ns}}}property"
                or "linkTarget" in prop.attrib
                or len(prop) != 1
                or list(prop[0])
                or prop[0].tag
                not in {
                    f"{{{vt}}}{kind}"
                    for kind in ("lpwstr", "lpstr", "bool", "i4", "r8", "filetime")
                }
            ):
                _unsafe("ooxml_custom_properties_invalid")
    if (
        len(root_rows) != len(expected_root)
        or {(row["Type"], row["Target"]) for row in root_rows} != expected_root
    ):
        _unsafe("ooxml_relationship_contract_mismatch")

    workbook_rows = _relationship_rows(_parse_xml(parts["xl/_rels/workbook.xml.rels"]))
    allowed_types = {
        _REL_WORKSHEET,
        _REL_STYLES,
        _REL_SHARED_STRINGS,
        _REL_THEME,
    }
    if any(row["Type"] not in allowed_types for row in workbook_rows):
        _unsafe("ooxml_relationship_not_allowed")
    expected_pairs = {
        *((_REL_WORKSHEET, f"worksheets/sheet{index}.xml") for index in range(1, 7)),
        (_REL_STYLES, "styles.xml"),
    }
    if "xl/sharedStrings.xml" in parts:
        expected_pairs.add((_REL_SHARED_STRINGS, "sharedStrings.xml"))
    if "xl/theme/theme1.xml" in parts:
        expected_pairs.add((_REL_THEME, "theme/theme1.xml"))

    def workbook_target(value: str) -> str:
        normalized = value.lstrip("/")
        return normalized.removeprefix("xl/")

    actual_pairs = {
        (row["Type"], workbook_target(row["Target"])) for row in workbook_rows
    }
    normalized_expected = {(kind, target) for kind, target in expected_pairs}
    if len(workbook_rows) != len(expected_pairs) or actual_pairs != normalized_expected:
        _unsafe("ooxml_relationship_contract_mismatch")

    workbook = _parse_xml(parts["xl/workbook.xml"])
    if workbook.tag != f"{{{_SPREADSHEET_NS}}}workbook":
        _unsafe("ooxml_workbook_contract_mismatch")
    forbidden = {
        f"{{{_SPREADSHEET_NS}}}externalReferences",
        f"{{{_SPREADSHEET_NS}}}customWorkbookViews",
    }
    if any(element.tag in forbidden for element in workbook.iter()):
        _unsafe("ooxml_workbook_unsafe_content")
    defined_names = workbook.findall(f"{{{_SPREADSHEET_NS}}}definedNames")
    if any(list(element) or (element.text or "").strip() for element in defined_names):
        _unsafe("ooxml_workbook_unsafe_content")
    sheets_nodes = workbook.findall(f"{{{_SPREADSHEET_NS}}}sheets")
    if len(sheets_nodes) != 1:
        _unsafe("ooxml_workbook_contract_mismatch")
    sheets = list(sheets_nodes[0])
    if len(sheets) != 6:
        _unsafe("ooxml_workbook_contract_mismatch")
    rel_by_id = {row["Id"]: row for row in workbook_rows}
    for index, (sheet, expected_name) in enumerate(
        zip(sheets, SHEET_NAMES, strict=True), start=1
    ):
        rel_id = sheet.attrib.get(f"{{{_DOCUMENT_REL_NS}}}id")
        if (
            sheet.tag != f"{{{_SPREADSHEET_NS}}}sheet"
            or sheet.attrib.get("name") != expected_name
            or sheet.attrib.get("sheetId") != str(index)
            or sheet.attrib.get("state", "visible") != "visible"
            or rel_id not in rel_by_id
            or rel_by_id[rel_id]["Type"] != _REL_WORKSHEET
            or workbook_target(rel_by_id[rel_id]["Target"])
            != f"worksheets/sheet{index}.xml"
        ):
            _unsafe("ooxml_workbook_contract_mismatch")


def _validate_worksheet_content(parts: dict[str, bytes]) -> None:
    for index in range(1, 7):
        root = _parse_xml(parts[f"xl/worksheets/sheet{index}.xml"])
        if root.tag != f"{{{_SPREADSHEET_NS}}}worksheet":
            _unsafe("ooxml_worksheet_contract_mismatch")
        for element in root.iter():
            local_name = element.tag.rpartition("}")[2]
            if local_name in {
                "f",
                "mergeCells",
                "mergeCell",
                "hyperlinks",
                "oleObjects",
                "controls",
                "drawing",
                "legacyDrawing",
            }:
                _unsafe("ooxml_worksheet_unsafe_content")
            if local_name in {"row", "col"} and element.attrib.get("hidden") in {
                "1",
                "true",
                "True",
            }:
                _unsafe("ooxml_hidden_content")


def _validate_package_contract(parts: dict[str, bytes]) -> None:
    part_names = frozenset(parts)
    if not _BASE_PARTS.issubset(part_names) or not part_names.issubset(
        _BASE_PARTS | _OPTIONAL_PARTS
    ):
        _unsafe("ooxml_part_not_allowed")
    _validate_content_types(parts)
    _validate_relationships(parts)
    _validate_worksheet_content(parts)
    for name, content in parts.items():
        if name.endswith((".xml", ".rels")):
            _parse_xml(content)


def validate_catalog_ooxml(
    source: bytes | bytearray | memoryview | Path,
    *,
    max_archive_bytes: int = MAX_ARCHIVE_BYTES,
    max_member_count: int = MAX_MEMBER_COUNT,
    max_member_uncompressed_bytes: int = MAX_MEMBER_UNCOMPRESSED_BYTES,
    max_total_uncompressed_bytes: int = MAX_WORKBOOK_UNCOMPRESSED_BYTES,
    max_compression_ratio: int = MAX_COMPRESSION_RATIO,
) -> ValidatedCatalogOoxml:
    """Validate in the mandated archive→central→contract→stream order."""

    limits = (
        max_archive_bytes,
        max_member_count,
        max_member_uncompressed_bytes,
        max_total_uncompressed_bytes,
        max_compression_ratio,
    )
    if any(type(limit) is not int or limit < 1 for limit in limits):
        raise ValueError("all OOXML limits must be positive integers")
    archive = _read_archive(source)
    if len(archive) > max_archive_bytes:
        raise CatalogWorkbookCapacityError(
            (
                CapacityViolation(
                    code="archive_bytes_limit",
                    sheet_or_member=None,
                    actual=str(len(archive)),
                    limit=str(max_archive_bytes),
                    unit="bytes",
                ),
            )
        )
    if not archive.startswith(b"PK\x03\x04"):
        _unsafe("zip_signature_invalid")

    try:
        package = zipfile.ZipFile(io.BytesIO(archive), "r")
        infos = package.infolist()
    except OSError, zipfile.BadZipFile, ValueError:
        _unsafe("zip_central_directory_invalid")
    with package:
        if len(infos) > max_member_count:
            _unsafe("zip_member_count_exceeded")
        if not infos:
            _unsafe("zip_central_directory_invalid")
        if package.comment:
            _unsafe("zip_archive_comment_not_allowed")

        canonical_names: set[str] = set()
        exact_names: set[str] = set()
        for info in infos:
            raw_name = info.orig_filename
            canonical = _safe_member_name(raw_name[:-1] if info.is_dir() else raw_name)
            if raw_name in exact_names or canonical in canonical_names:
                _unsafe("zip_member_name_collision")
            if info.is_dir():
                allowed_dirs = {
                    part[:index]
                    for part in _BASE_PARTS | _OPTIONAL_PARTS
                    for index, char in enumerate(part)
                    if char == "/"
                }
                if raw_name[:-1] not in allowed_dirs or info.file_size != 0:
                    _unsafe("zip_member_path_invalid")
            else:
                exact_names.add(raw_name)
            canonical_names.add(canonical)
        if not _BASE_PARTS.issubset(exact_names) or not exact_names.issubset(
            _BASE_PARTS | _OPTIONAL_PARTS
        ):
            _unsafe("ooxml_part_not_allowed")

        for info in infos:
            if info.flag_bits & 0x1:
                _unsafe("zip_encryption_not_allowed")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                _unsafe("zip_compression_not_allowed")
            if info.extra:
                _unsafe("zip_extra_field_not_allowed")
            _validate_local_header(archive, info)

        parts: dict[str, bytes] = {}
        total = 0
        for info in infos:
            observed = 0
            output = bytearray()
            try:
                with package.open(info, "r") as member:
                    while chunk := member.read(STREAM_BYTES):
                        observed += len(chunk)
                        total += len(chunk)
                        if observed > max_member_uncompressed_bytes:
                            raise CatalogWorkbookCapacityError(
                                (
                                    CapacityViolation(
                                        code="member_uncompressed_bytes_limit",
                                        sheet_or_member=info.filename,
                                        actual=str(observed),
                                        limit=str(max_member_uncompressed_bytes),
                                        unit="bytes",
                                    ),
                                )
                            )
                        if total > max_total_uncompressed_bytes:
                            raise CatalogWorkbookCapacityError(
                                (
                                    CapacityViolation(
                                        code="workbook_uncompressed_bytes_limit",
                                        sheet_or_member=None,
                                        actual=str(total),
                                        limit=str(max_total_uncompressed_bytes),
                                        unit="bytes",
                                    ),
                                )
                            )
                        output.extend(chunk)
            except CatalogWorkbookCapacityError:
                raise
            except OSError, EOFError, RuntimeError, zipfile.BadZipFile, zlib_error():
                _unsafe("zip_member_integrity_mismatch")
            if observed != info.file_size:
                _unsafe("zip_member_size_mismatch")
            ratio = observed / max(info.compress_size, 1)
            if ratio > max_compression_ratio:
                raise CatalogWorkbookCapacityError(
                    (
                        CapacityViolation(
                            code="member_compression_ratio_limit",
                            sheet_or_member=info.filename,
                            actual=format(ratio, ".12g"),
                            limit=str(max_compression_ratio),
                            unit="ratio",
                        ),
                    )
                )
            if not info.is_dir():
                parts[info.filename] = bytes(output)

        _validate_package_contract(parts)
        return ValidatedCatalogOoxml(
            archive_bytes=len(archive),
            member_count=len(infos),
            total_uncompressed_bytes=total,
            members=tuple(info.filename for info in infos),
        )


def zlib_error() -> type[Exception]:
    """Avoid importing zlib on paths that never decompress a member."""

    import zlib

    return zlib.error


__all__ = (
    "MAX_ARCHIVE_BYTES",
    "MAX_COMPRESSION_RATIO",
    "MAX_MEMBER_COUNT",
    "MAX_MEMBER_UNCOMPRESSED_BYTES",
    "MAX_WORKBOOK_UNCOMPRESSED_BYTES",
    "SHEET_NAMES",
    "CapacityViolation",
    "CatalogWorkbookCapacityError",
    "CatalogWorkbookUnsafeError",
    "ValidatedCatalogOoxml",
    "validate_catalog_ooxml",
)
