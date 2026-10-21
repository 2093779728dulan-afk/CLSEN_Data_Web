"""The first administrator-only API contract: role catalogue visibility."""

from __future__ import annotations

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_database_session, require_roles
from app.auth.sessions import Principal

router = APIRouter(prefix="/api/admin", tags=["admin"])
_require_admin = require_roles("admin")
_AdminPrincipal = Annotated[Principal, Depends(_require_admin)]
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]


class RoleResponse(BaseModel):
    code: str
    description: str


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(
    _principal: _AdminPrincipal,
    database_session: _DatabaseSession,
) -> list[RoleResponse]:
    rows = database_session.execute(
        sa.text("SELECT code, description FROM roles ORDER BY id")
    ).mappings()
    return [
        RoleResponse(code=str(row["code"]), description=str(row["description"]))
        for row in rows
    ]
