"""FBA Receipts source adapter; equality fingerprints are candidates, never IDs."""

# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from io import BytesIO, StringIO
from typing import Any, cast
from zipfile import BadZipFile, ZipFile
from zoneinfo import ZoneInfo

import openpyxl  # type: ignore[import-untyped]

from app.api.errors import ApiError

HEADERS = (
    "Date",
    "FNSKU",
    "ASIN",
    "MSKU",
    "Title",
    "Event Type",
    "Reference ID",
    "Quantity",
    "Fulfillment Center",
    "Disposition",
    "Reason",
    "Country",
    "Reconciled Quantity",
    "Unreconciled Quantity",
    "Date and Time",
    "Store",
)


def ledger_kind(original: dict[str, str]) -> str:
    event = original["Event Type"]
    quantity = original["Quantity"]
    if event in {"Receipts", "CustomerReturns"}:
        if re.fullmatch(r"-[1-9][0-9]{0,8}", quantity):
            return "CORRECTION"
        return "RECEIPT" if event == "Receipts" else "CUSTOMER_RETURN"
    if event in {"Adjustments", "WhseTransfers", "VendorReturns", "Shipments"}:
        return "ADJUSTMENT"
    return "UNKNOWN"


def prepare_receipt_decisions(batch: dict[str, Any]) -> list[dict[str, Any]]:
    """Fill unique draft allocations, ready for the user to confirm the batch."""
    resolved = {int(item["source_row"]) for item in batch["resolved"]}
    decisions = {int(item["source_row"]): dict(item) for item in batch["decisions"]}
    reserved: dict[str, int] = defaultdict(int)
    for number, decision in decisions.items():
        if number not in resolved and decision["decision"] == "NEW":
            for allocation in decision.get("allocations", []):
                reserved[str(allocation["binding_id"])] += int(allocation["units"])
    for row in batch["rows"]:
        number = int(row["source_row"])
        if number in resolved:
            continue
        existing = decisions.get(number)
        if existing and existing["decision"] != "PENDING":
            continue
        if not re.fullmatch(r"[1-9][0-9]{0,8}", str(row["quantity"])):
            continue
        if (
            int(row["quantity"]) <= 0
            or row.get("posting_block")
            or row["existing_candidates"]
            or row["same_file_candidates"]
            or len(row["bindings"]) != 1
            or not row["identity"]
            or str(row["identity"]["tracked"]).lower() not in {"true", "1"}
            or any(int(issue["row"]) == number for issue in batch["issues"])
        ):
            continue
        binding = row["bindings"][0]
        units = int(row["quantity"])
        key = str(binding["id"])
        if int(binding["received_units"]) + reserved[key] + units > int(
            binding["units"]
        ):
            continue
        reserved[key] += units
        decisions[number] = {
            "source_row": str(number),
            "decision": "NEW",
            "event_key": f"receipt-review:{batch['id']}:{number}",
            "reason": f"用户整批核对接收原表第{number}行，采用唯一明确出货来源",
            "allocations": [{"binding_id": key, "units": row["quantity"]}],
        }
    return list(decisions.values())


def parse_receipts(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > 2_000_000:
        raise ApiError(422, "fba_file_invalid", "请选择不超过2MB的FBA接收CSV。")
    try:
        reader = csv.DictReader(
            StringIO(raw.decode("utf-8-sig"), newline=""), strict=True
        )
        if tuple(reader.fieldnames or ()) != HEADERS:
            raise ValueError("headers")
        source = list(reader)
        if (
            not source
            or len(source) > 5000
            or any(None in r or None in r.values() for r in source)
        ):
            raise ValueError("shape")
    except (UnicodeError, csv.Error, ValueError) as exc:
        raise ApiError(
            422,
            "fba_file_invalid",
            "文件须为UTF-8的16列FBA接收CSV，保留原表头且不超过5000行。",
        ) from exc
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    similar = defaultdict(list)
    for index, original in enumerate(source, 2):
        row: dict[str, Any] = {
            "source_row": index,
            "raw": original,
            "fingerprint": hashlib.sha256(
                json.dumps(
                    [original[k] for k in HEADERS],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "quantity": original["Quantity"],
            "occurred_at": "",
            "business_date": "",
            "same_file_candidates": [],
            "ledger_kind": ledger_kind(original),
        }

        def issue(
            column: str,
            code: str,
            message: str,
            *,
            row_number: int = index,
            source: dict[str, str] = original,
        ) -> None:
            issues.append(
                {
                    "code": code,
                    "sheet": "CSV",
                    "row": row_number,
                    "column": column,
                    "raw": source[column],
                    "message": message,
                }
            )

        quantity = original["Quantity"]
        if not re.fullmatch(r"-?[1-9][0-9]{0,8}", quantity):
            issue(
                "Quantity",
                "fba_quantity_invalid",
                "接收数量须为非零带符号整数；空白不按零处理，负数须关联更正依据。",
            )
        try:
            stamp = datetime.fromisoformat(original["Date and Time"])
            if (
                stamp.utcoffset() is None
                or stamp.astimezone(ZoneInfo("America/Los_Angeles")).utcoffset()
                != stamp.utcoffset()
            ):
                raise ValueError("offset")
            row["occurred_at"] = stamp.isoformat()
            row["business_date"] = stamp.date().isoformat()
            try:
                if (
                    datetime.strptime(original["Date"], "%m/%d/%Y").date()
                    != stamp.date()
                ):
                    raise ValueError("date mismatch")
            except ValueError:
                issue(
                    "Date", "fba_date_mismatch", "日期列应与原发生时间的当地日期一致。"
                )
        except ValueError:
            issue(
                "Date and Time",
                "fba_time_invalid",
                "发生时间须含有效洛杉矶UTC偏移，保留原时刻，不使用文件名日期。",
            )
        for field, expected, code, message in (
            (
                "Event Type",
                "Receipts",
                "fba_event_type_invalid",
                "客户实物退回须沿原退回核对；其他调整保留待核，不作为货件接收入账。",
            ),
            (
                "Country",
                "US",
                "fba_country_invalid",
                "当前仅启用明确的美国FBA范围，请核对国家。",
            ),
        ):
            if original[field] != expected:
                issue(field, code, message)
        disposition = original["Disposition"].strip().upper()
        qualities = {
            "": "QUALIFIED",
            "SELLABLE": "QUALIFIED",
            "CUSTOMER_DAMAGED": "DEFECTIVE",
            "DEFECTIVE": "DEFECTIVE",
            "CARRIER_DAMAGED": "DEFECTIVE",
            "WAREHOUSE_DAMAGED": "DEFECTIVE",
            "DISTRIBUTOR_DAMAGED": "DEFECTIVE",
            "EXPIRED": "DEFECTIVE",
            "UNSELLABLE": "DEFECTIVE",
            "PENDING": "PENDING",
        }
        row["quality"] = qualities.get(disposition, "")
        if not row["quality"]:
            issue(
                "Disposition",
                "fba_disposition_invalid",
                "处置结果尚未支持，请核对原表。",
            )
        row["quality_basis"] = "报告明确处置" if disposition else "按用户指定缺省可售"
        for field in ("FNSKU", "ASIN", "MSKU", "Reference ID"):
            if not original[field] or len(original[field]) > 255:
                issue(
                    field,
                    "fba_identity_required",
                    "请保留有效原始编码与平台货件引用；未匹配不允许过账。",
                )
        similar[row["fingerprint"]].append(index)
        rows.append(row)
    for row in rows:
        row["same_file_candidates"] = [
            n for n in similar[row["fingerprint"]] if n != row["source_row"]
        ]
    return {
        "schema": "fba_receipts_csv_v1",
        "rows": rows,
        "issues": issues,
        "net_units": str(
            sum(
                int(r["quantity"])
                for r in rows
                if re.fullmatch(r"-?[1-9][0-9]{0,8}", r["quantity"])
            )
        ),
    }


DECISIONS = (
    "原表行号",
    "处理",
    "已有事件ID",
    "事件核对引用",
    "更正原事件引用",
    "箱来源分配JSON",
    "独立重复已核实",
    "依据",
)
REVIEW_EXTRA = ("确认数量", "已接收关联JSON", "原表调整说明")
UNIFIED_COLUMNS = ("接收行ID", "商品规格ID", "来源类型", "报告批次ID", "原表行号")
UNIFIED_DECISIONS = (
    "接收行ID",
    "本次接收",
    "选中",
    "来源分配JSON",
    "已有接收关联JSON",
    "处理",
    "已有事件ID",
    "独立新增已核实",
    "重叠已核对",
    "调整说明",
)


def export_batch(batch: dict[str, Any]) -> bytes:
    """Original columns and explicit decisions; reimport updates this same draft."""
    if batch.get("source_kind") == "MANUAL":
        return export_unified(batch)
    book = openpyxl.Workbook()
    info = book.active
    info.title = "生成信息"
    for pair in [
        ("模板版本", "fba_receipts_review_v2"),
        ("批次ID", str(batch["id"])),
        ("范围ID", str(batch["scope_id"])),
        ("修订", str(batch["revision"])),
        ("原件SHA256", str(batch["digest"])),
        (
            "说明",
            "核对明细；回导原批次，不新增事件。事件引用为人工核对证据，不是平台独立事件ID。",
        ),
    ]:
        info.append(pair)
    data = book.create_sheet("接收明细")
    data.append(("原表行号", *HEADERS))
    for row in batch["rows"]:
        data.append((str(row["source_row"]), *(row["raw"][k] for k in HEADERS)))
    decision = book.create_sheet("处理决定")
    decision.append((*DECISIONS, *REVIEW_EXTRA))
    by_row = {str(d["source_row"]): d for d in batch.get("decisions", [])}
    for row in batch["rows"]:
        d = by_row.get(str(row["source_row"]), {})
        decision.append(
            (
                str(row["source_row"]),
                d.get("decision", "PENDING"),
                str(d.get("existing_event_id", "")),
                d.get("event_key", ""),
                d.get("correction_of", ""),
                json.dumps(d.get("allocations", []), ensure_ascii=False),
                "是" if d.get("independent_occurrence") else "否",
                d.get("reason", ""),
                str(d.get("quantity", row["quantity"])),
                json.dumps(d.get("receipt_links", []), ensure_ascii=False),
                d.get("adjustment_reason", ""),
            )
        )
    for sheet in book:
        sheet.freeze_panes = "A2"
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 24
            for cell in column:
                cell.data_type = "s"
                cell.number_format = "@"
    out = BytesIO()
    book.save(out)
    book.close()
    return out.getvalue()


def parse_review_payload(raw: bytes, batch: dict[str, Any]) -> dict[str, Any]:
    try:
        if len(raw) > 2_000_000:
            raise ValueError("size")
        with ZipFile(BytesIO(raw)) as archive:
            if (
                len(archive.infolist()) > 1000
                or sum(x.file_size for x in archive.infolist()) > 20_000_000
            ):
                raise ValueError("envelope")
        book = openpyxl.load_workbook(BytesIO(raw), read_only=True, data_only=False)
        try:
            if book.sheetnames != ["生成信息", "接收明细", "处理决定"] or any(
                s.max_row > 5001 or s.max_column > 17 for s in book
            ):
                raise ValueError("shape")
            all_rows = {}
            for sheet in book:
                rows = list(sheet.iter_rows())
                if any(
                    c.data_type == "f"
                    or (c.value is not None and not isinstance(c.value, str))
                    for r in rows
                    for c in r
                ):
                    raise ValueError("type")
                all_rows[sheet.title] = [
                    ["" if c.value is None else c.value for c in r] for r in rows
                ]
            info = dict(all_rows["生成信息"])
            if batch.get("source_kind") == "MANUAL":
                return parse_unified(all_rows, batch)
            version = info.get("模板版本")
            if version not in {"fba_receipts_review_v1", "fba_receipts_review_v2"}:
                raise ValueError("version")
            if any(
                info.get(k) != str(v)
                for k, v in [
                    ("批次ID", batch["id"]),
                    ("范围ID", batch["scope_id"]),
                    ("原件SHA256", batch["digest"]),
                ]
            ):
                raise ValueError("revision")
            if not re.fullmatch(r"[1-9][0-9]{0,18}", info.get("修订", "")):
                raise ValueError("revision")
            data = all_rows["接收明细"]
            if data[0] != ["原表行号", *HEADERS] or data[1:] != [
                [str(r["source_row"]), *(r["raw"][k] for k in HEADERS)]
                for r in batch["rows"]
            ]:
                raise ValueError("source changed")
            decision = all_rows["处理决定"]
            columns = (
                (*DECISIONS, *REVIEW_EXTRA)
                if version == "fba_receipts_review_v2"
                else DECISIONS
            )
            if decision[0] != list(columns) or len(decision) != len(batch["rows"]) + 1:
                raise ValueError("decisions")
            result = []
            for r, original in zip(decision[1:], batch["rows"], strict=True):
                if r[0] != str(original["source_row"]) or len(r) != len(columns):
                    raise ValueError("row")
                allocations = json.loads(r[5])
                if not isinstance(allocations, list):
                    raise ValueError("allocations")
                result.append(
                    {
                        "source_row": r[0],
                        "decision": r[1],
                        "existing_event_id": r[2],
                        "event_key": r[3],
                        "correction_of": r[4],
                        "allocations": allocations,
                        "independent_occurrence": r[6] == "是",
                        "reason": r[7],
                    }
                )
                if version == "fba_receipts_review_v2":
                    links = json.loads(r[9])
                    if not isinstance(links, list):
                        raise ValueError("links")
                    # Signed historic corrections retain the original path.
                    if r[8] != original["quantity"] or int(r[8]) > 0:
                        result[-1]["quantity"] = r[8]
                    result[-1]["receipt_links"] = links
                    result[-1]["adjustment_reason"] = r[10]
            # Keep the workbook revision in the command. The transaction checks
            # it after receipt lookup, so an identical retry can replay safely.
            return {"expected_revision": info["修订"], "decisions": result}
        finally:
            book.close()
    except (
        ValueError,
        TypeError,
        KeyError,
        BadZipFile,
        openpyxl.utils.exceptions.InvalidFileException,
    ) as exc:
        raise ApiError(
            422,
            "fba_review_invalid",
            "请使用当前修订的系统核对工作簿，保留生成信息、原表身份和文本格式；不能使用公式。",
        ) from exc


def parse_review(raw: bytes, batch: dict[str, Any]) -> list[dict[str, Any]]:
    result = parse_review_payload(raw, batch)
    if result["expected_revision"] != str(batch["revision"]):
        raise ApiError(
            422, "fba_review_invalid", "工作簿修订已过期，请导出当前核对明细。"
        )
    return cast(list[dict[str, Any]], result["decisions"])


def export_unified(batch: dict[str, Any]) -> bytes:
    book = openpyxl.Workbook()
    info = book.active
    info.title = "生成信息"
    payload = batch["draft_payload"]
    for pair in [
        ("模板版本", "fba_unified_receipts_v1"),
        ("批次ID", str(batch["id"])),
        ("范围ID", str(batch["scope_id"])),
        ("修订", str(batch["revision"])),
        ("原件SHA256", batch["digest"]),
        ("货件关联ID", payload.get("reference_link_id", "")),
        ("FBA货件号", payload.get("reference_number", "")),
        ("接收日期", payload["business_date"]),
        ("实际时刻", payload.get("occurred_at", "")),
        ("接收依据", payload["reason"]),
    ]:
        info.append(pair)
    source = book.create_sheet("接收明细")
    source.append(UNIFIED_COLUMNS)
    decisions = book.create_sheet("处理决定")
    decisions.append(UNIFIED_DECISIONS)
    for line in payload["lines"]:
        source.append(
            (
                line["line_id"],
                line["sku_id"],
                "REPORT" if line.get("batch_id") else "MANUAL",
                line.get("batch_id", ""),
                line.get("source_row", ""),
            )
        )
        decisions.append(
            (
                line["line_id"],
                line["quantity"],
                "是" if line["selected"] else "否",
                json.dumps(line["allocations"], ensure_ascii=False),
                json.dumps(line.get("receipt_links", []), ensure_ascii=False),
                line.get("decision", "NEW"),
                line.get("existing_event_id", ""),
                "是" if line.get("independent_occurrence") else "否",
                "是" if line.get("overlap_checked") else "否",
                line.get("adjustment_reason", ""),
            )
        )
    for sheet in book:
        sheet.freeze_panes = "A2"
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 24
            for cell in column:
                cell.data_type = "s"
                cell.number_format = "@"
    out = BytesIO()
    book.save(out)
    book.close()
    return out.getvalue()


def parse_unified(sheets: dict[str, Any], batch: dict[str, Any]) -> dict[str, Any]:
    info = dict(sheets["生成信息"])
    if any(
        info.get(key) != str(value)
        for key, value in [
            ("模板版本", "fba_unified_receipts_v1"),
            ("批次ID", batch["id"]),
            ("范围ID", batch["scope_id"]),
            ("原件SHA256", batch["digest"]),
        ]
    ) or not re.fullmatch(r"[1-9][0-9]{0,18}", info.get("修订", "")):
        raise ValueError("identity")
    payload = batch["draft_payload"]
    for key, field in [
        ("货件关联ID", "reference_link_id"),
        ("FBA货件号", "reference_number"),
    ]:
        if key in info and info[key] != str(payload.get(field, "")):
            raise ValueError("reference changed")
    originals = [
        [
            line["line_id"],
            line["sku_id"],
            "REPORT" if line.get("batch_id") else "MANUAL",
            line.get("batch_id", ""),
            line.get("source_row", ""),
        ]
        for line in payload["lines"]
    ]
    if sheets["接收明细"] != [list(UNIFIED_COLUMNS), *originals]:
        raise ValueError("source changed")
    decisions = sheets["处理决定"]
    if decisions[0] != list(UNIFIED_DECISIONS) or len(decisions) != len(originals) + 1:
        raise ValueError("coverage")
    lines = []
    for cells, line in zip(decisions[1:], payload["lines"], strict=True):
        if (
            len(cells) != len(UNIFIED_DECISIONS)
            or cells[0] != line["line_id"]
            or any(cells[index] not in ("是", "否") for index in (2, 7, 8))
        ):
            raise ValueError("row")
        allocations, links = json.loads(cells[3]), json.loads(cells[4])
        if not isinstance(allocations, list) or not isinstance(links, list):
            raise ValueError("allocations")
        current = {
            **line,
            "quantity": cells[1],
            "selected": cells[2] == "是",
            "allocations": allocations,
            "receipt_links": links,
            "decision": cells[5],
            "independent_occurrence": cells[7] == "是",
            "overlap_checked": cells[8] == "是",
            "adjustment_reason": cells[9],
        }
        if cells[6]:
            current["existing_event_id"] = cells[6]
        else:
            current.pop("existing_event_id", None)
        lines.append(current)
    return {
        "expected_revision": info["修订"],
        "draft_payload": {
            **payload,
            "business_date": info["接收日期"],
            "occurred_at": info.get("实际时刻", ""),
            "reason": info["接收依据"],
            "lines": lines,
        },
    }
