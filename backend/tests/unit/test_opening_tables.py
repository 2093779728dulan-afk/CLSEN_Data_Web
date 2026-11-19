from io import BytesIO
from pathlib import Path
from typing import Any, cast

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api.errors import ApiError
from app.production.opening_tables import (
    opening_template,
    parse_opening,
    read_source,
    retain_source,
)

CATALOG = {"11": {"code": "1112-Black-L"}, "12": {"code": "2121-Camel-M"}}


def workbook(rows: Any) -> Any:
    book = openpyxl.load_workbook(BytesIO(opening_template(CATALOG)))
    sheet = book.active
    sheet.delete_rows(2, 2)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def test_opening_zero_and_exact_sku_roundtrip() -> None:
    result = parse_opening(
        workbook([["2121-Camel-M", 0, 0, 1], ["1112-Black-L", 5, 0, 0]]),
        "opening.xlsx",
        CATALOG,
    )
    assert result["sku_count"] == 2
    assert result["lines"][0] == {"sku_id": "12", "quality": "QUALIFIED", "units": "0"}
    assert result["lines"][3] == {"sku_id": "11", "quality": "QUALIFIED", "units": "5"}


@pytest.mark.parametrize(
    "row",
    [
        ["1112-black-L", 0, 0, 0],
        ["1112-Black-L ", 0, 0, 0],
        ["1112-Black-L", None, 0, 0],
        ["1112-Black-L", -1, 0, 0],
        ["1112-Black-L", 0.5, 0, 0],
        ["1112-Black-L", "=1+1", 0, 0],
    ],
)
def test_opening_rejects_invalid_identity_and_quantity_with_location(row: Any) -> None:
    with pytest.raises(ApiError) as error:
        parse_opening(workbook([row]), "opening.xlsx", CATALOG)
    assert cast(dict[str, str], error.value.detail)["code"] == "opening_rows"
    assert "2" in cast(dict[str, str], error.value.detail)["message"]


def test_opening_rejects_duplicate_and_empty_files() -> None:
    with pytest.raises(ApiError):
        parse_opening(
            workbook([["1112-Black-L", 0, 0, 0]] * 2), "opening.xlsx", CATALOG
        )
    with pytest.raises(ApiError):
        parse_opening(b"bad", "opening.xlsx", CATALOG)


def test_template_preserves_blank_as_unknown_and_centers_data() -> None:
    book = openpyxl.load_workbook(BytesIO(opening_template(CATALOG)))
    assert book.active["B2"].value is None
    assert book.active["A2"].alignment.horizontal == "center"
    book.close()


def test_opening_original_is_immutable_and_actor_site_scoped(tmp_path: Path) -> None:
    raw = workbook([["1112-Black-L", 0, 0, 0]])
    digest = retain_source(str(tmp_path), 1, 7, raw)
    assert retain_source(str(tmp_path), 1, 7, raw) == digest
    assert read_source(str(tmp_path), 1, 7, digest) == raw
    for site, actor in [(2, 7), (1, 8)]:
        with pytest.raises(ApiError):
            read_source(str(tmp_path), site, actor, digest)
    with pytest.raises(ApiError):
        read_source(str(tmp_path), 1, 7, "../escape")
    (tmp_path / "opening-uploads/1/7" / f"{digest}.xlsx").write_bytes(b"changed")
    with pytest.raises(ApiError):
        read_source(str(tmp_path), 1, 7, digest)
