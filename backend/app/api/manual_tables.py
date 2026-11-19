# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
"""Manual-only preparation routes; old production and official routes stay intact."""

import base64
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.api.catalog_common import (
    CatalogEngine,
    CatalogReadContext,
    CatalogWriteContext,
)
from app.api.errors import ApiError
from app.manual_tables.exports import render
from app.manual_tables.schemas import FIELDS, Command, HandoffCommand, Kind
from app.manual_tables.service import ManualTables, digest


class ManualRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as error:
                fields = [
                    " / ".join(
                        FIELDS.get(
                            str(v),
                            {
                                "kind": "业务类型",
                                "target_url": "关联业务记录",
                                "options": "整理选项",
                                "columns": "字段对应",
                                "decisions": "明细核对",
                                "context": "业务口径",
                                "expected_revision": "资料修订",
                                "handoff_preview_hash": "业务衔接预览",
                                "operation_token": "操作编号",
                                "excluded": "排除选项",
                                "reason": "核对原因",
                            }.get(str(v), str(v)),
                        )
                        for v in e["loc"]
                        if v not in {"body", "query", "path", "header"}
                    )
                    for e in error.errors()[:5]
                ]
                raise ApiError(
                    422,
                    "manual_input_invalid",
                    "提交内容格式不正确，请检查："
                    + "；".join(fields)
                    + "。数量应为整数字符串，选项选择是或否，修改须有原因。",
                ) from error
            except SQLAlchemyError as error:
                raise ApiError(
                    503,
                    "manual_storage_unavailable",
                    "资料存储暂不可用；如已提交，请先查询原操作结果，再使用原操作编号重试。",
                ) from error

        return handler


router = APIRouter(
    prefix="/api/manual-tables", tags=["manual-tables"], route_class=ManualRoute
)


def service(
    request: Request, engine: CatalogEngine, context: CatalogReadContext
) -> ManualTables:
    return ManualTables(engine, request.app.state.settings, context)


@router.get("/capabilities")
def capabilities(request: Request, context: CatalogReadContext) -> dict[str, Any]:
    enabled = (
        request.app.state.settings.manual_tables_enabled
        and not context.principal_roles.isdisjoint({"admin", "data_manager"})
    )
    return {
        "enabled": enabled,
        "handoff_enabled": enabled
        and request.app.state.settings.manual_tables_handoff_enabled,
        "inventory_handoff_enabled": enabled
        and request.app.state.settings.manual_tables_handoff_enabled
        and request.app.state.settings.manual_tables_inventory_handoff_enabled,
        "kinds": ["inventory", "orders", "packing"],
        "max_upload_bytes": 2_000_000,
        "reason": "仅整理人工资料；业务确认沿原模块。"
        if enabled
        else "此环境或账号未启用人工表格整理，原有导入继续可用。",
    }


@router.post("/batches")
async def upload(
    request: Request,
    engine: CatalogEngine,
    context: CatalogWriteContext,
    kind: Kind,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
    filename: str = Query(max_length=240),
) -> object:
    svc = service(request, engine, context)
    svc.require()
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 2_000_000:
            raise ApiError(
                413,
                "manual_file_large",
                "文件超过2MB，请去除无关图片或保留所需业务页。",
            )
    return await run_in_threadpool(svc.create, bytes(raw), kind, filename, str(key))


@router.get("/batches")
def listing(
    request: Request,
    engine: CatalogEngine,
    context: CatalogReadContext,
    page: int = Query(default=1, ge=1),
    kind: Kind | None = None,
    target_url: str | None = Query(default=None, max_length=500),
) -> object:
    return service(request, engine, context).listing(page, kind, target_url)


@router.get("/batches/{batch_id}")
def detail(
    batch_id: UUID, request: Request, engine: CatalogEngine, context: CatalogReadContext
) -> object:
    return service(request, engine, context).get(str(batch_id))


@router.get("/catalog")
def catalog(
    request: Request, engine: CatalogEngine, context: CatalogReadContext
) -> object:
    svc = service(request, engine, context)
    svc.require()
    return {"items": svc.catalog()}


@router.get("/examples/{kind}")
def sample(
    kind: Kind, request: Request, engine: CatalogEngine, context: CatalogReadContext
) -> Response:
    from app.manual_tables.examples import example

    service(request, engine, context).require()
    return Response(
        example(kind),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(f"虚构人工表格-{kind}.xlsx")
        },
    )


@router.post("/batches/{batch_id}/preview")
def preview(
    batch_id: UUID,
    command: Command,
    request: Request,
    engine: CatalogEngine,
    context: CatalogWriteContext,
) -> object:
    return service(request, engine, context).preview(str(batch_id), command)


def matching_token(command: Command, key: UUID) -> None:
    if command.operation_token != str(key):
        raise ApiError(
            422, "manual_token_mismatch", "操作编号不一致，请核实原操作后重试。"
        )


@router.post("/batches/{batch_id}/save")
def save(
    batch_id: UUID,
    command: Command,
    request: Request,
    engine: CatalogEngine,
    context: CatalogWriteContext,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    matching_token(command, key)
    return service(request, engine, context).save(str(batch_id), command)


@router.get("/batches/{batch_id}/history")
def history(
    batch_id: UUID, request: Request, engine: CatalogEngine, context: CatalogReadContext
) -> object:
    return service(request, engine, context).history(str(batch_id))


@router.get("/batches/{batch_id}/operations/{token}")
def operation(
    batch_id: UUID,
    token: UUID,
    request: Request,
    engine: CatalogEngine,
    context: CatalogReadContext,
) -> object:
    return service(request, engine, context).operation(str(batch_id), str(token))


@router.get("/batches/{batch_id}/source")
def source(
    batch_id: UUID, request: Request, engine: CatalogEngine, context: CatalogReadContext
) -> Response:
    svc = service(request, engine, context)
    with engine.connect() as con:
        row = svc.load(con, str(batch_id))
    return Response(
        svc.source(row),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(row["filename"])
        },
    )


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    mode: Literal["standard", "wide", "issues", "template"] = "standard"
    query: str = Field(default="", max_length=100)


@router.post("/batches/{batch_id}/export")
def export(
    batch_id: UUID,
    body: ExportRequest,
    request: Request,
    engine: CatalogEngine,
    context: CatalogWriteContext,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    svc = service(request, engine, context)
    value = svc.get(str(batch_id))
    if value["revision"] != body.revision:
        raise ApiError(409, "manual_export_stale", "批次已变化，请刷新后导出同一修订。")
    output = render(value, body.mode, body.query)
    with engine.begin() as con:
        row = svc.load(con, str(batch_id), lock=True)
        if row["revision"] != body.revision:
            raise ApiError(
                409, "manual_export_stale", "导出期间资料已有新修订，请刷新后重试。"
            )
        request_hash = digest(["export", str(batch_id), body.model_dump()])
        if not svc.replay(con, str(key), request_hash):
            svc.record(
                con,
                str(key),
                str(batch_id),
                "EXPORT",
                request_hash,
                {"mode": body.mode, "query": body.query, "revision": body.revision},
                "导出人工整理资料；未入账",
            )
    return {
        "filename": f"人工整理-{body.mode}-{batch_id}.xlsx",
        "file_base64": base64.b64encode(output).decode("ascii"),
    }


@router.post("/batches/{batch_id}/handoff")
def handoff(
    batch_id: UUID,
    command: HandoffCommand,
    request: Request,
    engine: CatalogEngine,
    context: CatalogWriteContext,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> object:
    from app.manual_tables.handoff import handoff_batch

    matching_token(command, key)
    return handoff_batch(service(request, engine, context), str(batch_id), command)


@router.post("/batches/{batch_id}/handoff-preview")
def handoff_preview(
    batch_id: UUID,
    command: HandoffCommand,
    request: Request,
    engine: CatalogEngine,
    context: CatalogWriteContext,
) -> object:
    from app.manual_tables.handoff import handoff_batch

    return handoff_batch(
        service(request, engine, context), str(batch_id), command, preview_only=True
    )


class ProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: UUID
    name: str = Field(min_length=1, max_length=120)
    shared: bool = False
    expected_version: int | None = None


@router.get("/profiles")
def profile_list(
    request: Request, engine: CatalogEngine, context: CatalogReadContext
) -> object:
    return service(request, engine, context).list_profiles()


@router.post("/profiles")
@router.post("/profiles/{profile_id}/versions")
def profile_save(
    body: ProfileRequest,
    request: Request,
    engine: CatalogEngine,
    context: CatalogWriteContext,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
    profile_id: UUID | None = None,
) -> object:
    return service(request, engine, context).save_profile(
        str(body.batch_id),
        body.name,
        body.shared,
        str(key),
        str(profile_id) if profile_id else None,
        body.expected_version,
    )


class BatchReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    revision: int = Field(ge=0)


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    references: dict[
        Literal["before", "inventory", "orders", "packing"], BatchReference
    ] = Field(min_length=2, max_length=4)


@router.post("/compare")
def compare_batches(
    body: ComparisonRequest,
    request: Request,
    engine: CatalogEngine,
    context: CatalogWriteContext,
) -> object:
    from app.manual_tables.comparison import compare

    return compare(
        service(request, engine, context),
        {k: v.model_dump(mode="json") for k, v in body.references.items()},
    )
