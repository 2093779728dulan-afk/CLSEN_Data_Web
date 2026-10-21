from __future__ import annotations

import csv
from collections.abc import Sequence
from io import StringIO


def csv_bytes(
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    encoding: str = "utf-8",
) -> bytes:
    target = StringIO(newline="")
    writer = csv.writer(target, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return target.getvalue().encode(encoding)
