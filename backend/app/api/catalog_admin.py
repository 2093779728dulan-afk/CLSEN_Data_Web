"""Catalog command recovery for original operators and audited administrators."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import Field
from starlette.responses import Response

from app.api.catalog_common import (
    CatalogEngine,
    CatalogIdempotencyKey,
    CatalogReadContext,
    CatalogWriteContext,
    catalog_json,
    require_catalog_admin,
    require_catalog_session,
    require_matching_token,
)
from app.api.errors import ApiError
from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.models import CatalogWireUuid, StrictCatalogModel

router = APIRouter(
    prefix="/api/catalog",
    tags=["catalog"],
    dependencies=[Depends(require_catalog_session)],
)


class AdminCommandLookupRequest(StrictCatalogModel):
    operation_token: CatalogWireUuid
    reason: str = Field(min_length=10, max_length=1000)


def _command(
    engine: CatalogEngine, *, token: UUID, site_id: int
) -> dict[str, object] | None:
    with engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT claims.operation_kind, claims.actor_user_id,
                           claims.resource_kind, claims.resource_id, claims.status,
                           effects.response_status_code, effects.safe_result_json
                    FROM catalog_command_claims AS claims
                    LEFT JOIN catalog_command_effects AS effects
                      ON effects.operation_token = claims.operation_token
                    WHERE claims.operation_token = :token AND claims.site_id = :site_id
                    """
                ),
                {"token": token.bytes, "site_id": site_id},
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return None
    result = row["safe_result_json"]
    if isinstance(result, str):
        result = json.loads(result)
    return {
        "operation_token": str(token),
        "operation_kind": row["operation_kind"],
        "actor_user_id": int(row["actor_user_id"]),
        "resource_kind": row["resource_kind"],
        "resource_id": row["resource_id"],
        "status": row["status"],
        "response_status_code": row["response_status_code"],
        "safe_result": result,
    }


@router.get("/commands/{operation_token}")
def get_catalog_command(
    operation_token: UUID,
    context: CatalogReadContext,
    engine: CatalogEngine,
) -> Response:
    command = _command(engine, token=operation_token, site_id=context.site_id)
    if command is None or command["actor_user_id"] != context.principal_user_id:
        raise ApiError(404, "catalog_command_not_found", "Command was not found.")
    return catalog_json(command)


@router.post("/admin/commands/{operation_token}/lookup")
def admin_lookup_catalog_command(
    operation_token: UUID,
    request: AdminCommandLookupRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_catalog_admin(context)
    require_matching_token(idempotency_key, request.operation_token)
    command = _command(engine, token=operation_token, site_id=context.site_id)
    if command is None:
        raise ApiError(404, "catalog_command_not_found", "Command was not found.")
    payload = {
        "lookup_token": str(request.operation_token),
        "target_operation_token": str(operation_token),
        "reason": request.reason.strip(),
    }
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "actor_user_id": context.principal_user_id,
                "event_kind": "catalog_command_admin_lookup",
                **payload,
            }
        )
    ).digest()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT IGNORE INTO catalog_audit_events (
                    site_id, actor_user_id, event_kind, resource_kind,
                    resource_id, operation_token, safe_payload_json, event_digest
                ) VALUES (
                    :site_id, :actor, 'catalog_command_admin_lookup',
                    'command', NULL, :token, CAST(:payload AS JSON), :digest
                )
                """
            ),
            {
                "site_id": context.site_id,
                "actor": context.principal_user_id,
                "token": request.operation_token.bytes,
                "payload": canonical_json_bytes(payload).decode("utf-8"),
                "digest": digest,
            },
        )
    return catalog_json(command)


__all__ = ("AdminCommandLookupRequest", "router")
