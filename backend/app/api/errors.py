"""Stable domain errors rendered by the shared API error envelope."""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel


class ApiErrorDetail(BaseModel):
    """Stable public error fields returned for one failed request."""

    code: str
    message: str
    request_id: str


class ApiErrorResponse(BaseModel):
    """Shared error envelope rendered by application exception handlers."""

    error: ApiErrorDetail


class ApiError(HTTPException):
    """An intentional HTTP error with a public machine-readable code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(
            status_code=status_code,
            detail={"code": code, "message": message},
        )
