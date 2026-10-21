"""Application service for catalog preview, approval, and forward restore."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.catalog.approval import (
    CatalogApprovalForbidden,
    CatalogApprovalPreview,
    CatalogApprovalResult,
    CatalogApprovalValidationFailed,
    CatalogRestoreResult,
    MySqlCatalogApprovalRepository,
    _assert_permission,
    _evaluate_with_database,
    _result_int,
)
from app.catalog.import_repository import MySqlCatalogImportRepository
from app.catalog.repository import load_import_rows


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise RuntimeError("catalog timestamp result is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class CatalogService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def assert_approval_permission(
        self,
        *,
        risk: str,
        actor_roles: frozenset[str],
        submitted_by_user_id: int,
        actor_user_id: int,
        reason: str,
    ) -> None:
        _assert_permission(
            risk=risk,
            actor_roles=actor_roles,
            submitted_by_user_id=submitted_by_user_id,
            actor_user_id=actor_user_id,
            reason=reason,
        )

    def preview_import(
        self,
        *,
        import_id: int,
        site_id: int,
        actor_user_id: int,
        actor_roles: frozenset[str],
        operation_token: UUID,
        expected_workflow_revision: int,
        now: datetime,
    ) -> CatalogApprovalPreview:
        with self._engine.connect() as connection:
            imported = (
                connection.execute(
                    sa.text(
                        "SELECT status, workflow_revision, validation_run_id, "
                        "submitted_by_user_id, base_catalog_version_id, "
                        "fact_snapshot_tuple_id, export_id FROM catalog_imports "
                        "WHERE id = :id AND site_id = :site_id"
                    ),
                    {"id": import_id, "site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
            if (
                imported is None
                or imported["status"] != "ready_for_approval"
                or int(imported["workflow_revision"]) != expected_workflow_revision
                or imported["validation_run_id"] is None
                or imported["submitted_by_user_id"] is None
            ):
                raise CatalogApprovalValidationFailed()
            if not (
                "admin" in actor_roles
                or (
                    "data_manager" in actor_roles
                    and int(imported["submitted_by_user_id"]) == actor_user_id
                )
            ):
                raise CatalogApprovalForbidden()
            pointer = (
                connection.execute(
                    sa.text(
                        "SELECT current_catalog_version_id, "
                        "catalog_publication_revision "
                        "FROM product_catalog_publications "
                        "WHERE site_id = :site_id"
                    ),
                    {"site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
            base_id = (
                None
                if imported["base_catalog_version_id"] is None
                else int(imported["base_catalog_version_id"])
            )
            current_id = (
                None
                if pointer is None or pointer["current_catalog_version_id"] is None
                else int(pointer["current_catalog_version_id"])
            )
            export_revision = connection.scalar(
                sa.text(
                    "SELECT catalog_publication_revision FROM catalog_exports "
                    "WHERE id = :export_id AND site_id = :site_id "
                    "AND export_status = 'ready'"
                ),
                {"export_id": int(imported["export_id"]), "site_id": site_id},
            )
            if (
                pointer is None
                or base_id != current_id
                or export_revision is None
                or int(export_revision) != int(pointer["catalog_publication_revision"])
            ):
                raise CatalogApprovalValidationFailed()
            rows = load_import_rows(
                connection,
                import_id=import_id,
                workflow_revision=expected_workflow_revision,
            )
            evaluation = _evaluate_with_database(
                connection,
                rows=rows,
                site_id=site_id,
                export_id=int(imported["export_id"]),
                current_catalog_id=current_id,
            )
            if evaluation.issues:
                raise CatalogApprovalValidationFailed()
        command = MySqlCatalogImportRepository(self._engine).create_approval_preview(
            import_id=import_id,
            site_id=site_id,
            actor_user_id=actor_user_id,
            operation_token=operation_token,
            expected_workflow_revision=expected_workflow_revision,
            risk=evaluation.risk,
            now=now,
        )
        value = command.safe_result
        return CatalogApprovalPreview(
            _result_int(value["projection_id"]),
            bytes.fromhex(str(value["projection_digest"])),
            _result_int(value["workflow_revision"]),
            _result_int(value["validation_run_id"]),
            base_id,
            _result_int(value["catalog_publication_revision"]),
            _result_int(value["fact_snapshot_tuple_id"]),
            str(value["risk"]),
            bytes.fromhex(str(value["diff_digest"])),
            _parse_timestamp(value["created_at"]),
            _parse_timestamp(value["expires_at"]),
            len(evaluation.reachability.included_row_keys),
            len(evaluation.reachability.audit_only_row_keys),
        )

    def approve_import(self, **kwargs: object) -> CatalogApprovalResult:
        return MySqlCatalogApprovalRepository(self._engine).approve(**kwargs)  # type: ignore[arg-type]

    def restore_version(self, **kwargs: object) -> CatalogRestoreResult:
        return MySqlCatalogApprovalRepository(self._engine).restore(**kwargs)  # type: ignore[arg-type]


__all__ = ("CatalogService",)
