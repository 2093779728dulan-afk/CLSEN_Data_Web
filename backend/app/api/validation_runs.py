"""Full validation command API for editable daily drafts."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from app.api.dependencies import get_database_engine, require_write_roles
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.validation.repository import MySqlValidationRepository
from app.validation.service import ValidationService
from app.validation.types import (
    RunValidationCommand,
    ValidationCommitOutcomeUnknown,
    ValidationPermissionDenied,
    ValidationPersistenceError,
    ValidationTransactionBusy,
)

router = APIRouter(prefix="/api/validation-runs", tags=["validation-runs"])
_Manager = Annotated[Principal, Depends(require_write_roles("admin", "data_manager"))]
_Engine = Annotated[Engine, Depends(get_database_engine)]
_IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


class RunValidationRequest(BaseModel):
    dataset_id: int
    data_revision: int
    ruleset_version: str


class ValidationRunResponse(BaseModel):
    validation_run_id: int
    version_id: int
    data_revision: int
    status: Literal["succeeded", "failed"]
    result: Literal["passed", "failed", "error"]
    data_digest: str
    summary: dict[str, object]


@router.post("/{version_id}", response_model=ValidationRunResponse)
def run_validation(
    version_id: int,
    payload: RunValidationRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> ValidationRunResponse:
    try:
        service = ValidationService(repository=MySqlValidationRepository(engine))
        result = service.run_validation(
            RunValidationCommand(
                dataset_id=payload.dataset_id,
                version_id=version_id,
                data_revision=payload.data_revision,
                ruleset_version=payload.ruleset_version,
                actor_user_id=principal.user_id,
                operation_token=operation_token,
            )
        )
    except ValidationPermissionDenied as error:
        raise ApiError(
            403,
            "validation_forbidden",
            "Permission to validate this draft was denied.",
        ) from error
    except ValidationTransactionBusy as error:
        raise ApiError(
            503,
            "validation_busy",
            "Validation is temporarily busy.",
        ) from error
    except ValidationCommitOutcomeUnknown as error:
        raise ApiError(
            503,
            "validation_outcome_unknown",
            "The validation command outcome could not be confirmed.",
        ) from error
    except ValidationPersistenceError as error:
        raise ApiError(
            409,
            "validation_conflict",
            "Validation conflicts with current draft state.",
        ) from error
    return ValidationRunResponse(
        validation_run_id=result.validation_run_id,
        version_id=result.version_id,
        data_revision=result.data_revision,
        status=result.status,
        result=result.result,
        data_digest=result.data_digest.hex(),
        summary=result.summary.as_payload(),
    )
