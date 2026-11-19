# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
"""Small synthetic workbooks for the dedicated experience; no business input."""

from io import BytesIO

import openpyxl  # type: ignore[import-untyped]


def example(kind: str) -> bytes:
    book = openpyxl.Workbook()
    s = book.active
    if kind == "inventory":
        s.title = "库存"
        s.append([None, None, None, None, "尺码（虚构样例）"])
        s.append(
            [
                "新款号",
                "SKU",
                "性别",
                "COLOR",
                "XS",
                "S",
                "M",
                "L",
                "XL",
                "XXL",
                "3XL",
                "合计",
                "库位",
            ]
        )
        s.append(
            [
                "99001",
                "FACTORY-01",
                None,
                "Blue",
                0,
                0,
                10,
                5,
                0,
                0,
                0,
                "=SUM(E3:K3)",
                "人工表格虚构体验仓",
            ]
        )
        s.append(
            ["99002", None, None, "Black", 0, 0, 8, 0, 0, 0, 0, 8, "人工表格虚构体验仓"]
        )
    elif kind == "orders":
        s.title = "Sheet1"
        s.append(
            [
                "DELIVERY",
                "GENDER",
                "CAT",
                "SKU",
                "IMAGE",
                "SUPPLIER COMPOSITION",
                "VENROY COMPOSITION",
                "PO PLACED DATE",
                "XS",
                "S",
                "M",
                "L",
                "XL",
                "XXL",
                "3XL",
                "QTY",
            ]
        )
        s.append(
            [
                "2026-10-17",
                None,
                None,
                "99001-Blue",
                None,
                None,
                None,
                None,
                0,
                0,
                3,
                2,
                0,
                0,
                0,
                "=SUM(I2:O2)",
            ]
        )
        s.append(
            [
                "2026-10-17",
                None,
                None,
                "99002-Black",
                None,
                None,
                None,
                None,
                0,
                0,
                1,
                0,
                0,
                0,
                0,
                1,
            ]
        )
    else:
        s.title = "Sheet1"
        s.append([None, None, None, "总数量", "箱1", "箱2", None, "差异"])
        s.append(
            [
                "99001-Blue-M",
                "SYNTHETIC-ASIN-01",
                "SYNTHETIC-FNSKU-01",
                3,
                2,
                1,
                "=SUM(E2:F2)",
                "=D2-G2",
            ]
        )
        s.append(
            [
                "99002-Black-M",
                "SYNTHETIC-ASIN-02",
                "SYNTHETIC-FNSKU-02",
                1,
                1,
                0,
                "=SUM(E3:F3)",
                "=D3-G3",
            ]
        )
        s.append(
            [
                "合计",
                None,
                None,
                "=SUM(D2:D3)",
                "=SUM(E2:E3)",
                "=SUM(F2:F3)",
                None,
                None,
            ]
        )
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()
