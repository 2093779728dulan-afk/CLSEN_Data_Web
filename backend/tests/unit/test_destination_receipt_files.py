from io import BytesIO

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.production.destination_receipt_files import preview, workbook

BINDINGS = [
    {
        "id": "11",
        "source_line_id": "3",
        "allocation_id": "5",
        "carton_id": "box-one",
        "sku_id": "1001",
        "catalog_version": "2:2",
    }
]


def mutate(raw: bytes, cell: str, value: object) -> bytes:
    book = openpyxl.load_workbook(BytesIO(raw))
    book.active[cell] = value
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def test_export_roundtrips_current_binding_and_integer_quality() -> None:
    lines = [
        {
            "binding_id": "11",
            "sku_id": "1001",
            "catalog_version": "2:2",
            "qualified_units": "56",
            "pending_units": "2",
            "defective_units": "2",
        }
    ]
    assert preview(workbook(BINDINGS, lines), BINDINGS) == {
        "lines": lines,
        "issues": [],
    }


def test_rejects_stale_identity_formulas_and_fractional_quantity() -> None:
    raw = workbook(BINDINGS)
    for cell, value in [("B2", "99"), ("G2", "=1+1"), ("H2", "1.5"), ("I2", "01")]:
        result = preview(mutate(raw, cell, value), BINDINGS)
        assert result["lines"] == []
        assert result["issues"][0]["row"] == 2
    with pytest.raises(ValueError):
        preview(b"not an xlsx", BINDINGS)
