"""Immutable, actor-scoped uploads for local unposted source drafts."""
# ruff: noqa: RUF001 -- Chinese UI messages use native punctuation.

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import Any, Literal, cast
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from app.api.errors import ApiError
from app.site_context import CurrentSiteContext

SourceKind = Literal["orders", "shipments"]
MAX_UPLOAD_BYTES = 2_000_000
_UPLOAD_LOCK = Lock()


def validate_upload(filename: str, raw: bytes) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if (
        not name.lower().endswith(".xlsx")
        or len(name) > 180
        or any(ord(char) < 32 for char in name)
    ):
        raise ApiError(422, "invalid_source_filename", "请选择名称有效的XLSX原表。")
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "file_too_large", "请选择不超过2MB且非空的XLSX原表。")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 2000
                or sum(item.file_size for item in entries) > 30_000_000
            ):
                raise ApiError(
                    413, "workbook_too_large", "解压后的表格过大，请拆分原表。"
                )
            if any(item.flag_bits & 1 for item in entries):
                raise ApiError(422, "encrypted_workbook", "请上传未加密的XLSX原表。")
            if "xl/workbook.xml" not in archive.namelist():
                raise BadZipFile
    except BadZipFile as error:
        raise ApiError(422, "invalid_workbook", "文件不是可读取的XLSX表格。") from error
    return name


def _area(root: Path, context: CurrentSiteContext) -> Path:
    return root / "uploads" / str(context.site_id) / str(context.principal_user_id)


def _directory(
    root: Path, context: CurrentSiteContext, source_id: str, kind: SourceKind
) -> Path:
    if not re.fullmatch(rf"upload-{kind}-[a-f0-9]{{64}}", source_id):
        raise ApiError(404, "source_not_found", "当前账号没有这份原表来源。")
    return _area(root, context) / source_id


def registered_sources(
    root: Path, context: CurrentSiteContext
) -> list[dict[str, object]]:
    area = _area(root, context)
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(area.glob("upload-*/source.json"))
    ]


def uploaded_source(
    root: Path, context: CurrentSiteContext, source_id: str, kind: SourceKind
) -> dict[str, object]:
    directory = _directory(root, context, source_id, kind)
    if not (directory / "source.json").is_file():
        raise ApiError(404, "source_not_found", "当前账号没有这份原表来源。")
    source = cast(
        dict[str, object],
        json.loads((directory / "source.json").read_text(encoding="utf-8")),
    )
    raw = directory / "source.xlsx"
    if (
        not raw.is_file()
        or hashlib.sha256(raw.read_bytes()).hexdigest() != source["source_digest"]
        or source["source_digest"] != source_id.rsplit("-", 1)[-1]
    ):
        raise ApiError(
            409, "source_snapshot_changed", "上传副本已改变，不能覆盖原来源草稿。"
        )
    return source


def register_upload(
    root: Path,
    context: CurrentSiteContext,
    kind: SourceKind,
    filename: str,
    raw: bytes,
    preview: dict[str, object],
) -> tuple[dict[str, object], bool]:
    source_id = f"upload-{kind}-{hashlib.sha256(raw).hexdigest()}"
    directory = _directory(root, context, source_id, kind)
    with _UPLOAD_LOCK:
        if directory.is_dir():
            return uploaded_source(root, context, source_id, kind), True
        source = {
            **preview,
            "sample_id": source_id,
            "filename": filename,
            "kind": kind,
            "origin": "UPLOAD",
            "uploaded_at": datetime.now(UTC).isoformat(),
        }
        directory.parent.mkdir(parents=True, exist_ok=True)
        temporary = directory.parent / f".{uuid4().hex}.tmp"
        temporary.mkdir()
        try:
            (temporary / "source.xlsx").write_bytes(raw)
            (temporary / "source.json").write_text(
                json.dumps(source, ensure_ascii=False), encoding="utf-8"
            )
            temporary.rename(directory)
        finally:
            if temporary.is_dir():
                (temporary / "source.xlsx").unlink(missing_ok=True)
                (temporary / "source.json").unlink(missing_ok=True)
                temporary.rmdir()
    return source, False


def uploaded_bytes(
    root: Path, context: CurrentSiteContext, source_id: str, kind: SourceKind
) -> bytes:
    uploaded_source(root, context, source_id, kind)
    return (_directory(root, context, source_id, kind) / "source.xlsx").read_bytes()


def save_upload_review(
    root: Path, context: CurrentSiteContext, source_id: str, review: dict[str, Any]
) -> str:
    uploaded_source(root, context, source_id, "shipments")
    raw = json.dumps(review, ensure_ascii=False, sort_keys=True).encode("utf-8")
    review_id = f"dispatch-review-{hashlib.sha256(raw).hexdigest()}"
    directory = _area(root, context) / "dispatch-reviews"
    with _UPLOAD_LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{review_id}.json"
        if not path.is_file():
            temporary = directory / f".{uuid4().hex}.tmp"
            try:
                temporary.write_bytes(raw)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    return review_id


def uploaded_review(
    root: Path, context: CurrentSiteContext, review_id: str
) -> dict[str, Any]:
    if not re.fullmatch(r"dispatch-review-[a-f0-9]{64}", review_id):
        raise ApiError(404, "review_not_found", "当前账号没有这份原表修改记录。")
    path = _area(root, context) / "dispatch-reviews" / f"{review_id}.json"
    if not path.is_file():
        raise ApiError(404, "review_not_found", "当前账号没有这份原表修改记录。")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != review_id.removeprefix("dispatch-review-"):
        raise ApiError(409, "review_changed", "原表修改记录已改变，请重新核对。")
    review = json.loads(raw)
    uploaded_source(root, context, review["baseline"]["source_id"], "shipments")
    return cast(dict[str, Any], review)
