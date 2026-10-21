from __future__ import annotations

import io
import zipfile

import pytest
from app.catalog.ooxml import (
    CatalogWorkbookCapacityError,
    CatalogWorkbookUnsafeError,
    validate_catalog_ooxml,
)

_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _package(*, worksheet_xml: str | None = None) -> dict[str, bytes]:
    sheets = "".join(
        f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(
            (
                "生成信息",
                "款式主档",
                "SKU变体",
                "SellerSKU映射",
                "待处理异常",
                "来源证据",
            ),
            start=1,
        )
    )
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.worksheet+xml"/>'
        for index in range(1, 7)
    )
    workbook_rels = "".join(
        f'<Relationship Id="rId{index}" Type="{_DOC_REL}/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, 7)
    )
    empty_sheet = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{_MAIN}"><sheetData/></worksheet>'
    )
    result = {
        "[Content_Types].xml": (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Types xmlns="{_CT}">'
            '<Default Extension="rels" ContentType="application/vnd.'
            'openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.'
            'openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.extended-properties+xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.'
            f'openxmlformats-officedocument.spreadsheetml.styles+xml"/>{overrides}'
            "</Types>"
        ).encode(),
        "_rels/.rels": (
            f'<Relationships xmlns="{_REL}">'
            f'<Relationship Id="rId1" Type="{_DOC_REL}/officeDocument" '
            'Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
            'package/2006/relationships/metadata/core-properties" '
            'Target="docProps/core.xml"/>'
            f'<Relationship Id="rId3" Type="{_DOC_REL}/extended-properties" '
            'Target="docProps/app.xml"/></Relationships>'
        ).encode(),
        "docProps/core.xml": (
            b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
            b'package/2006/metadata/core-properties"/>'
        ),
        "docProps/app.xml": (
            b'<Properties xmlns="http://schemas.openxmlformats.org/'
            b'officeDocument/2006/extended-properties"/>'
        ),
        "xl/workbook.xml": (
            f'<workbook xmlns="{_MAIN}" xmlns:r="{_DOC_REL}"><sheets>'
            f"{sheets}</sheets></workbook>"
        ).encode(),
        "xl/_rels/workbook.xml.rels": (
            f'<Relationships xmlns="{_REL}">{workbook_rels}'
            f'<Relationship Id="rId7" Type="{_DOC_REL}/styles" '
            'Target="styles.xml"/></Relationships>'
        ).encode(),
        "xl/styles.xml": (
            f'<styleSheet xmlns="{_MAIN}"><fonts count="1"><font/></fonts>'
            '<fills count="1"><fill/></fills><borders count="1"><border/></borders>'
            '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
            '<cellXfs count="1"><xf/></cellXfs></styleSheet>'
        ).encode(),
    }
    for index in range(1, 7):
        result[f"xl/worksheets/sheet{index}.xml"] = (
            worksheet_xml or empty_sheet
        ).encode()
    return result


def _archive(
    parts: dict[str, bytes], *, compression: int = zipfile.ZIP_DEFLATED
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as package:
        for name, content in parts.items():
            package.writestr(name, content)
    return output.getvalue()


def _archive_with_raw_backslash_member(parts: dict[str, bytes]) -> bytes:
    placeholder = "xl+workbook.xml"
    raw_name = "xl\\workbook.xml"
    parts[placeholder] = parts["xl/workbook.xml"]
    archive = _archive(parts)
    placeholder_bytes = placeholder.encode("ascii")
    assert archive.count(placeholder_bytes) == 2
    return archive.replace(placeholder_bytes, raw_name.encode("ascii"))


def test_exact_allowlisted_package_is_accepted() -> None:
    validated = validate_catalog_ooxml(_archive(_package()))

    assert validated.member_count == 13
    assert validated.total_uncompressed_bytes > 0


def test_empty_known_directories_are_accepted() -> None:
    parts = _package()
    parts.update({"xl/": b"", "xl/worksheets/": b"", "_rels/": b""})
    validate_catalog_ooxml(_archive(parts))


@pytest.mark.parametrize(
    "name,content", [("../xl/", b""), ("xl/", b"payload"), ("unknown/", b"")]
)
def test_unsafe_directories_are_rejected(name: str, content: bytes) -> None:
    parts = _package()
    parts[name] = content
    with pytest.raises(CatalogWorkbookUnsafeError):
        validate_catalog_ooxml(_archive(parts))


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("../xl/workbook.xml", "zip_member_path_invalid"),
        ("/xl/workbook.xml", "zip_member_path_invalid"),
        ("xl/unknown.xml", "ooxml_part_not_allowed"),
    ],
)
def test_bad_member_paths_and_unknown_parts_are_rejected(
    name: str, reason: str
) -> None:
    parts = _package()
    parts[name] = parts["xl/workbook.xml"]

    with pytest.raises(CatalogWorkbookUnsafeError) as captured:
        validate_catalog_ooxml(_archive(parts))

    assert captured.value.reason == reason


def test_backslash_member_path_is_rejected() -> None:
    with pytest.raises(CatalogWorkbookUnsafeError) as captured:
        validate_catalog_ooxml(_archive_with_raw_backslash_member(_package()))

    assert captured.value.reason == "zip_member_path_invalid"


def test_casefold_member_collision_is_rejected() -> None:
    parts = _package()
    parts["XL/workbook.xml"] = parts["xl/workbook.xml"]

    with pytest.raises(CatalogWorkbookUnsafeError) as captured:
        validate_catalog_ooxml(_archive(parts))

    assert captured.value.reason == "zip_member_name_collision"


def test_member_count_precedes_unknown_part_validation() -> None:
    parts = _package()
    for index in range(116):
        parts[f"unknown/{index}.xml"] = b"<x/>"
    assert len(parts) == 129

    with pytest.raises(CatalogWorkbookUnsafeError) as captured:
        validate_catalog_ooxml(_archive(parts))

    assert captured.value.reason == "zip_member_count_exceeded"


@pytest.mark.parametrize(
    "worksheet_xml",
    [
        f'<worksheet xmlns="{_MAIN}"><sheetData>'
        '<row hidden="1"/></sheetData></worksheet>',
        f'<worksheet xmlns="{_MAIN}"><cols>'
        '<col min="1" max="1" hidden="1"/></cols><sheetData/></worksheet>',
        f'<worksheet xmlns="{_MAIN}"><sheetData>'
        "<row><c><f>1+1</f></c></row></sheetData></worksheet>",
        f'<worksheet xmlns="{_MAIN}"><sheetData/><mergeCells count="1">'
        '<mergeCell ref="A1:B1"/></mergeCells></worksheet>',
    ],
)
def test_hidden_content_formulas_and_merged_cells_are_rejected(
    worksheet_xml: str,
) -> None:
    with pytest.raises(CatalogWorkbookUnsafeError):
        validate_catalog_ooxml(_archive(_package(worksheet_xml=worksheet_xml)))


def test_dtd_and_external_relationship_are_rejected() -> None:
    parts = _package()
    parts["docProps/core.xml"] = b'<!DOCTYPE x [<!ENTITY e "x">]><x>&e;</x>'
    with pytest.raises(CatalogWorkbookUnsafeError) as dtd:
        validate_catalog_ooxml(_archive(parts))
    assert dtd.value.reason == "ooxml_xml_unsafe"

    parts = _package()
    parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
        b"/></Relationships>", b' TargetMode="External"/></Relationships>'
    )
    with pytest.raises(CatalogWorkbookUnsafeError) as external:
        validate_catalog_ooxml(_archive(parts))
    assert external.value.reason == "ooxml_external_relationship"


def test_archive_and_compression_capacity_have_stable_codes() -> None:
    archive = _archive(_package())
    with pytest.raises(CatalogWorkbookCapacityError) as archive_error:
        validate_catalog_ooxml(archive, max_archive_bytes=len(archive) - 1)
    assert archive_error.value.violations[0].code == "archive_bytes_limit"

    parts = _package()
    parts["xl/worksheets/sheet1.xml"] = b"0" * 100_000
    with pytest.raises(CatalogWorkbookCapacityError) as ratio_error:
        validate_catalog_ooxml(_archive(parts), max_compression_ratio=2)
    assert ratio_error.value.violations[0].code == "member_compression_ratio_limit"
