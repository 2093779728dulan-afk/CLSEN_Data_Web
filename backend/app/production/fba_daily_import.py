"""Publish clean daily uploads through existing validation and review services."""

# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
from datetime import UTC
from typing import Any
from uuid import UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.api.errors import ApiError
from app.batch_review.service import validation_is_clean
from app.publications.commands import (
    DraftPointerExpectation,
    PublicationConfirmation,
    PublicationPointerExpectation,
    PublishCommand,
    ValidationExpectation,
)
from app.publications.repository import MySqlPublicationRepository
from app.publications.service import PublicationService
from app.review.repository import MySqlReviewRepository
from app.review.service import ReviewService
from app.review.types import DraftHeadExpectation, MarkReadyCommand
from app.validation.repository import MySqlValidationRepository
from app.validation.service import ValidationService
from app.validation.types import RunValidationCommand


def publish_clean_daily(
    engine: Engine, dataset_id: int, version_id: int, actor: int, operation: UUID
) -> None:
    def head() -> dict[str, Any] | None:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text("""
                SELECT v.id,v.dataset_id,v.status,v.data_revision,v.review_revision,
                       v.ruleset_version,d.pointed_at
                FROM dataset_versions v JOIN dataset_drafts d
                  ON d.version_id=v.id AND d.dataset_id=v.dataset_id
                WHERE v.id=:version AND v.dataset_id=:dataset
            """),
                    {"version": version_id, "dataset": dataset_id},
                )
                .mappings()
                .one_or_none()
            )
            return dict(row) if row else None

    with engine.connect() as connection:
        published = (
            connection.execute(
                sa.text(
                    "SELECT version_id,published_at FROM dataset_publications "
                    "WHERE dataset_id=:id"
                ),
                {"id": dataset_id},
            )
            .mappings()
            .one_or_none()
        )
    if published and int(published["version_id"]) == version_id:
        return
    current = head()
    if not current:
        raise ApiError(409, "daily_draft_changed", "报告草稿已变化，请继续原报告核对。")
    receipt = ValidationService(
        repository=MySqlValidationRepository(engine)
    ).run_validation(
        RunValidationCommand(
            dataset_id,
            version_id,
            current["data_revision"],
            current["ruleset_version"],
            actor,
            uuid5(operation, "validate"),
        )
    )
    if not validation_is_clean(receipt):
        raise ApiError(
            409, "daily_report_review_required", "日报校验包含待核项，请继续报告核对。"
        )
    if current["status"] == "draft":
        ReviewService(repository=MySqlReviewRepository(engine)).mark_ready(
            MarkReadyCommand(
                head=DraftHeadExpectation(
                    dataset_id,
                    version_id,
                    "draft",
                    current["data_revision"],
                    current["review_revision"],
                    current["pointed_at"].replace(tzinfo=UTC),
                ),
                validation_run_id=receipt.validation_run_id,
                validation_data_digest=receipt.data_digest,
                ruleset_version=receipt.ruleset_version,
                confirmed_report_date=receipt.summary.report_date,
                confirmed_report_type=receipt.summary.report_type,
                confirmed_row_count=receipt.summary.row_count,
                confirmed_totals=receipt.summary.totals,
                actor_user_id=actor,
                operation_token=uuid5(operation, "ready"),
                reason="用户上传日报，完整校验通过后自动更新",
            )
        )
        current = head()
    if not current or current["status"] != "ready_for_publish":
        raise ApiError(409, "daily_draft_changed", "报告状态已变化，请继续原报告核对。")
    PublicationService(repository=MySqlPublicationRepository(engine)).publish(
        PublishCommand(
            dataset_id=dataset_id,
            expected_draft=DraftPointerExpectation(
                version_id,
                "ready_for_publish",
                current["data_revision"],
                current["review_revision"],
                current["pointed_at"].replace(tzinfo=UTC),
            ),
            expected_publication=PublicationPointerExpectation(
                int(published["version_id"]) if published else None,
                published["published_at"].replace(tzinfo=UTC) if published else None,
            ),
            validation=ValidationExpectation(
                receipt.validation_run_id,
                version_id,
                receipt.data_revision,
                receipt.ruleset_version,
                receipt.data_digest,
            ),
            confirmation=PublicationConfirmation(
                receipt.summary.report_date,
                receipt.summary.report_type,
                receipt.summary.row_count,
                receipt.summary.totals,
            ),
            actor_user_id=actor,
            operation_token=uuid5(operation, "publish"),
            reason="用户上传日报，自动发布并衔接FBA库存",
        )
    )
