"""MySQL persistence for authoritative batch-review orchestration."""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from app.batch_review.types import (
    BatchReviewBusy,
    BatchReviewCandidate,
    BatchReviewItemStatus,
    BatchReviewNotFound,
    BatchReviewOperationConflict,
    BatchReviewReasonCode,
    BatchReviewRevisionConflict,
    BatchReviewRunStatus,
    BatchReviewStateConflict,
    BatchReviewTargetState,
    CreatePreflightCommand,
    EligibilityDecision,
    aggregate_run_status,
)
from app.imports.types import ReportType
from app.parsers.types import SupportedEncoding
from app.review.types import DraftHeadExpectation

_LEASE_DURATION = timedelta(minutes=5)

_CANDIDATE_SQL = sa.text(
    """
    SELECT batches.id AS batch_id, batches.site_id, batches.status AS batch_status,
           batches.report_date, batches.candidate_report_date,
           batches.detected_report_date, batches.detected_report_type,
           batches.confirmed_report_type, batches.detection_summary,
           files.original_filename, HEX(files.sha256) AS sha256_hex,
           integrity.status AS integrity_status, attempts.encoding,
           EXISTS(
               SELECT 1 FROM version_input_batches AS inputs
               WHERE inputs.batch_id = batches.id
           ) AS already_materialized,
           EXISTS(
               SELECT 1
               FROM daily_datasets AS target_datasets
               INNER JOIN dataset_drafts AS drafts
                   ON drafts.dataset_id = target_datasets.id
               WHERE target_datasets.site_id = batches.site_id
                 AND target_datasets.report_date = COALESCE(
                     batches.detected_report_date,
                     batches.candidate_report_date,
                     batches.report_date
                 )
                 AND target_datasets.report_type = COALESCE(
                     batches.detected_report_type,
                     batches.confirmed_report_type,
                     batches.report_type
                 )
           ) AS active_draft_exists,
           EXISTS(
               SELECT 1
               FROM daily_datasets AS target_datasets
               INNER JOIN dataset_publications AS publications
                   ON publications.dataset_id = target_datasets.id
               WHERE target_datasets.site_id = batches.site_id
                 AND target_datasets.report_date = COALESCE(
                     batches.detected_report_date,
                     batches.candidate_report_date,
                     batches.report_date
                 )
                 AND target_datasets.report_type = COALESCE(
                     batches.detected_report_type,
                     batches.confirmed_report_type,
                     batches.report_type
                 )
           ) AS publication_exists
    FROM import_batches AS batches
    INNER JOIN raw_files AS files ON files.id = batches.raw_file_id
    LEFT JOIN raw_file_integrity_statuses AS integrity
        ON integrity.raw_file_id = files.id
    LEFT JOIN parse_attempts AS attempts
        ON attempts.id = batches.current_successful_parse_attempt_id
    WHERE batches.site_id = :site_id
      AND batches.id IN :batch_ids
    ORDER BY batches.id
    """
).bindparams(sa.bindparam("batch_ids", expanding=True))


def _now() -> datetime:
    return datetime.now(UTC)


def _mysql_time(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, str):
        decoded = json.loads(value)
        return cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def validate_candidate_rows(
    requested_ids: tuple[int, ...],
    rows: Sequence[RowMapping | Mapping[str, Any]],
) -> Sequence[RowMapping | Mapping[str, Any]]:
    if len(requested_ids) != len(set(requested_ids)):
        raise ValueError("batch_ids must be unique")
    actual_ids = tuple(int(cast(int | str, row["batch_id"])) for row in rows)
    if set(actual_ids) != set(requested_ids) or len(actual_ids) != len(requested_ids):
        raise BatchReviewNotFound("one or more batches are missing from this site")
    return rows


@dataclass(frozen=True, slots=True)
class CandidateFacts:
    candidate: BatchReviewCandidate
    target: BatchReviewTargetState
    sha256_hex: str


@dataclass(frozen=True, slots=True)
class PreflightItem:
    facts: CandidateFacts
    decision: EligibilityDecision


@dataclass(frozen=True, slots=True)
class BatchReviewItemRecord:
    id: int
    run_id: int
    site_id: int
    batch_id: int
    filename: str
    detected_report_date: date | None
    detected_report_type: ReportType | None
    detected_encoding: SupportedEncoding | None
    recognition_status: str
    selected: bool
    status: BatchReviewItemStatus
    reason_code: BatchReviewReasonCode | None
    reason_message: str | None
    manual_review_url: str | None
    parse_attempt_id: int | None
    parse_baseline_id: int | None
    dataset_id: int | None
    version_id: int | None
    validation_run_id: int | None
    operation_token: UUID | None
    operation_digest: bytes | None
    attempt_count: int
    retry_allowed: bool
    outcome_unknown: bool
    lease_token: UUID | None
    lease_fence: int
    lease_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BatchReviewRunRecord:
    id: int
    site_id: int
    created_by_user_id: int
    status: BatchReviewRunStatus
    revision: int
    confirmation_statement_version: str | None
    items: tuple[BatchReviewItemRecord, ...]


@dataclass(frozen=True, slots=True)
class ClaimedItem:
    item: BatchReviewItemRecord
    lease_token: UUID
    lease_fence: int
    recovered: bool


@dataclass(frozen=True, slots=True)
class DraftState:
    head: DraftHeadExpectation
    ruleset_version: str
    report_date: date
    report_type: ReportType


class MySqlBatchReviewRepository:
    """Use short transactions, stable locks and durable command identities."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load_candidates(
        self,
        site_id: int,
        batch_ids: tuple[int, ...],
        actor_roles: frozenset[str],
    ) -> tuple[CandidateFacts, ...]:
        if not batch_ids or len(batch_ids) != len(set(batch_ids)):
            raise ValueError("batch_ids must be non-empty and unique")
        with self._engine.connect() as connection:
            rows = tuple(
                connection.execute(
                    _CANDIDATE_SQL,
                    {"site_id": site_id, "batch_ids": batch_ids},
                )
                .mappings()
                .all()
            )
        validate_candidate_rows(batch_ids, rows)
        return tuple(self._candidate_facts(row, actor_roles) for row in rows)

    @staticmethod
    def _candidate_facts(
        row: RowMapping,
        actor_roles: frozenset[str],
    ) -> CandidateFacts:
        summary = _json_object(row["detection_summary"])
        raw_issues = summary.get("issue_codes")
        issues = raw_issues if isinstance(raw_issues, list) else []
        report_date = cast(
            date | None,
            row["detected_report_date"]
            or row["candidate_report_date"]
            or row["report_date"],
        )
        report_type = cast(
            ReportType | None,
            row["detected_report_type"] or row["confirmed_report_type"],
        )
        raw_encoding = row["encoding"] or summary.get("encoding")
        encoding = cast(SupportedEncoding | None, raw_encoding)
        recognition_status = (
            "recognized"
            if summary.get("status") == "suggested"
            and report_date is not None
            and report_type is not None
            and encoding is not None
            and not issues
            else "uncertain"
        )
        return CandidateFacts(
            candidate=BatchReviewCandidate(
                batch_id=int(row["batch_id"]),
                site_id=int(row["site_id"]),
                filename=str(row["original_filename"]),
                report_date=report_date,
                report_type=report_type,
                encoding=encoding,
                recognition_status=recognition_status,
                source_available=row["integrity_status"] == "available",
                batch_status=str(row["batch_status"]),
                already_materialized=bool(row["already_materialized"]),
                actor_roles=actor_roles,
            ),
            target=BatchReviewTargetState(
                active_draft_exists=bool(row["active_draft_exists"]),
                publication_exists=bool(row["publication_exists"]),
            ),
            sha256_hex=str(row["sha256_hex"]).lower(),
        )

    def create_preflight(
        self,
        command: CreatePreflightCommand,
        items: tuple[PreflightItem, ...],
    ) -> BatchReviewRunRecord:
        timestamp = _mysql_time(_now())
        with self._engine.begin() as connection:
            existing = self._recover_command(
                connection,
                command.operation_token,
                command.operation_digest,
                "create_preflight",
            )
            if existing is not None:
                return self._get_run(connection, existing, command.site_id, lock=False)
            result = connection.execute(
                sa.text(
                    """
                    INSERT INTO batch_review_runs (
                        site_id, created_by_user_id, status, revision,
                        operation_kind, operation_token, operation_digest,
                        created_at, updated_at
                    ) VALUES (
                        :site_id, :actor_user_id, 'preview', 0,
                        'create_preflight', :operation_token, :operation_digest,
                        :created_at, :created_at
                    )
                    """
                ),
                {
                    "site_id": command.site_id,
                    "actor_user_id": command.actor_user_id,
                    "operation_token": command.operation_token.bytes,
                    "operation_digest": command.operation_digest,
                    "created_at": timestamp,
                },
            )
            if result.lastrowid is None:
                raise BatchReviewStateConflict("preflight run ID was not returned")
            run_id = int(result.lastrowid)
            for item in items:
                candidate = item.facts.candidate
                decision = item.decision
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO batch_review_items (
                            run_id, site_id, batch_id, filename,
                            detected_report_date, detected_report_type,
                            detected_encoding, recognition_status,
                            target_report_date, target_report_type,
                            selected, status, reason_code, reason_message,
                            manual_review_url, created_at, updated_at
                        ) VALUES (
                            :run_id, :site_id, :batch_id, :filename,
                            :report_date, :report_type, :encoding,
                            :recognition_status, :report_date, :report_type,
                            :selected, :status, :reason_code, :reason_message,
                            :manual_review_url, :created_at, :created_at
                        )
                        """
                    ),
                    {
                        "run_id": run_id,
                        "site_id": command.site_id,
                        "batch_id": candidate.batch_id,
                        "filename": candidate.filename,
                        "report_date": candidate.report_date,
                        "report_type": candidate.report_type,
                        "encoding": candidate.encoding,
                        "recognition_status": candidate.recognition_status,
                        "selected": decision.eligible,
                        "status": (
                            BatchReviewItemStatus.ELIGIBLE.value
                            if decision.eligible
                            else BatchReviewItemStatus.MANUAL_REVIEW.value
                        ),
                        "reason_code": (
                            decision.reason_code.value
                            if decision.reason_code is not None
                            else None
                        ),
                        "reason_message": decision.reason_message,
                        "manual_review_url": decision.manual_review_url,
                        "created_at": timestamp,
                    },
                )
            self._insert_command(
                connection,
                token=command.operation_token,
                kind="create_preflight",
                digest=command.operation_digest,
                site_id=command.site_id,
                actor_user_id=command.actor_user_id,
                run_id=run_id,
                item_id=None,
                revision=0,
                timestamp=timestamp,
            )
            self._append_audit_event(
                connection,
                site_id=command.site_id,
                actor_user_id=command.actor_user_id,
                event_type="batch_review_created",
                run_id=run_id,
                item_id=None,
                payload={"batch_ids": list(command.batch_ids), "revision": 0},
                request_id=str(command.operation_token),
                timestamp=timestamp,
            )
            return self._get_run(connection, run_id, command.site_id, lock=False)

    def get_run(self, run_id: int, site_id: int) -> BatchReviewRunRecord:
        with self._engine.connect() as connection:
            return self._get_run(connection, run_id, site_id, lock=False)

    def load_draft_state(
        self,
        *,
        run_id: int,
        item_id: int,
        site_id: int,
    ) -> DraftState:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT versions.dataset_id, versions.id AS version_id,
                               versions.status, versions.data_revision,
                               versions.review_revision, versions.ruleset_version,
                               drafts.pointed_at, items.target_report_date,
                               items.target_report_type
                        FROM batch_review_items AS items
                        INNER JOIN batch_review_runs AS runs
                            ON runs.id = items.run_id
                           AND runs.site_id = items.site_id
                        INNER JOIN dataset_versions AS versions
                            ON versions.id = items.version_id
                           AND versions.dataset_id = items.dataset_id
                        INNER JOIN dataset_drafts AS drafts
                            ON drafts.dataset_id = versions.dataset_id
                           AND drafts.version_id = versions.id
                        WHERE items.run_id = :run_id
                          AND items.id = :item_id
                          AND items.site_id = :site_id
                        """
                    ),
                    {"run_id": run_id, "item_id": item_id, "site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise BatchReviewStateConflict("active draft no longer matches the item")
        pointed_at = cast(datetime, row["pointed_at"]).replace(tzinfo=UTC)
        return DraftState(
            head=DraftHeadExpectation(
                dataset_id=int(row["dataset_id"]),
                version_id=int(row["version_id"]),
                status=cast(str, row["status"]),  # type: ignore[arg-type]
                data_revision=int(row["data_revision"]),
                review_revision=int(row["review_revision"]),
                pointed_at=pointed_at,
            ),
            ruleset_version=str(row["ruleset_version"]),
            report_date=cast(date, row["target_report_date"]),
            report_type=cast(ReportType, row["target_report_type"]),
        )

    def confirm_run(
        self,
        *,
        run_id: int,
        site_id: int,
        actor_user_id: int,
        expected_revision: int,
        selected_item_ids: tuple[int, ...],
        refreshed: Mapping[int, EligibilityDecision],
        confirmation_statement_version: str,
        operation_token: UUID,
        operation_digest: bytes,
    ) -> BatchReviewRunRecord:
        timestamp = _mysql_time(_now())
        with self._engine.begin() as connection:
            recovered = self._recover_command(
                connection,
                operation_token,
                operation_digest,
                "confirm",
            )
            if recovered is not None:
                return self._get_run(connection, recovered, site_id, lock=False)
            run = self._get_run(connection, run_id, site_id, lock=True)
            if run.status is not BatchReviewRunStatus.PREVIEW:
                raise BatchReviewStateConflict("only preview runs can be confirmed")
            if run.revision != expected_revision:
                raise BatchReviewRevisionConflict("run revision changed")
            selected = set(selected_item_ids)
            if not selected:
                raise BatchReviewStateConflict("at least one item must be selected")
            item_ids = {item.id for item in run.items}
            if not selected <= item_ids:
                raise BatchReviewNotFound("selected item is not in this run")
            for item in run.items:
                if item.id not in selected:
                    status = BatchReviewItemStatus.SKIPPED
                    reason_code = None
                    reason_message = "用户未选择此项目。"
                    chosen = False
                else:
                    decision = refreshed[item.id]
                    chosen = True
                    status = (
                        BatchReviewItemStatus.QUEUED
                        if decision.eligible
                        else BatchReviewItemStatus.MANUAL_REVIEW
                    )
                    reason_code = decision.reason_code
                    reason_message = decision.reason_message
                connection.execute(
                    sa.text(
                        """
                        UPDATE batch_review_items
                        SET selected = :selected, status = :status,
                            reason_code = :reason_code,
                            reason_message = :reason_message,
                            updated_at = :updated_at
                        WHERE run_id = :run_id AND id = :item_id
                        """
                    ),
                    {
                        "selected": chosen,
                        "status": status.value,
                        "reason_code": (
                            reason_code.value if reason_code is not None else None
                        ),
                        "reason_message": reason_message,
                        "updated_at": timestamp,
                        "run_id": run_id,
                        "item_id": item.id,
                    },
                )
            revision = expected_revision + 1
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE batch_review_runs
                    SET status = 'running', revision = :revision,
                        confirmed_at = :confirmed_at,
                        confirmed_by_user_id = :actor_user_id,
                        confirmation_statement_version = :statement_version,
                        operation_kind = 'confirm',
                        operation_token = :operation_token,
                        operation_digest = :operation_digest,
                        updated_at = :confirmed_at
                    WHERE id = :run_id AND site_id = :site_id
                      AND status = 'preview' AND revision = :expected_revision
                    """
                ),
                {
                    "revision": revision,
                    "confirmed_at": timestamp,
                    "actor_user_id": actor_user_id,
                    "statement_version": confirmation_statement_version,
                    "operation_token": operation_token.bytes,
                    "operation_digest": operation_digest,
                    "run_id": run_id,
                    "site_id": site_id,
                    "expected_revision": expected_revision,
                },
            )
            if updated.rowcount != 1:
                raise BatchReviewRevisionConflict("run revision changed")
            self._insert_command(
                connection,
                token=operation_token,
                kind="confirm",
                digest=operation_digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                run_id=run_id,
                item_id=None,
                revision=revision,
                timestamp=timestamp,
            )
            self._append_audit_event(
                connection,
                site_id=site_id,
                actor_user_id=actor_user_id,
                event_type="batch_review_confirmed",
                run_id=run_id,
                item_id=None,
                payload={
                    "selected_item_ids": sorted(selected),
                    "revision": revision,
                    "statement_version": confirmation_statement_version,
                },
                request_id=str(operation_token),
                timestamp=timestamp,
            )
            return self._get_run(connection, run_id, site_id, lock=False)

    def claim_item(
        self,
        *,
        run_id: int,
        item_id: int,
        site_id: int,
        actor_user_id: int,
        operation_token: UUID,
        operation_digest: bytes,
    ) -> ClaimedItem:
        now_value = _now()
        now = _mysql_time(now_value)
        expires = _mysql_time(now_value + _LEASE_DURATION)
        with self._engine.begin() as connection:
            run_row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT id, status
                        FROM batch_review_runs
                        WHERE id = :run_id AND site_id = :site_id
                        FOR UPDATE
                        """
                    ),
                    {"run_id": run_id, "site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
            if run_row is None:
                raise BatchReviewNotFound("batch review run not found")
            if run_row["status"] != BatchReviewRunStatus.RUNNING.value:
                raise BatchReviewStateConflict("run is not accepting new work")
            active_lease_count = int(
                connection.scalar(
                    sa.text(
                        """
                        SELECT COUNT(*)
                        FROM batch_review_items
                        WHERE run_id = :run_id
                          AND lease_expires_at > :now
                        """
                    ),
                    {"run_id": run_id, "now": now},
                )
                or 0
            )
            item_row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT *
                        FROM batch_review_items
                        WHERE run_id = :run_id AND id = :item_id
                        ORDER BY id
                        FOR UPDATE
                        """
                    ),
                    {"run_id": run_id, "item_id": item_id},
                )
                .mappings()
                .one_or_none()
            )
            if item_row is None:
                raise BatchReviewNotFound("batch review item not found")
            previous_token = item_row["operation_token"]
            previous_digest = item_row["operation_digest"]
            if previous_token is not None:
                if bytes(
                    previous_token
                ) != operation_token.bytes or not hmac.compare_digest(
                    bytes(previous_digest), operation_digest
                ):
                    raise BatchReviewOperationConflict(
                        "item is bound to another operation"
                    )
                terminal = str(item_row["status"]) in {
                    "ready_for_publish",
                    "manual_review",
                    "failed",
                }
                if terminal:
                    return ClaimedItem(
                        self._item_from_row(item_row),
                        UUID(bytes=bytes(item_row["lease_token"] or uuid4().bytes)),
                        int(item_row["lease_fence"]),
                        True,
                    )
            lease_expires_at = item_row["lease_expires_at"]
            if isinstance(lease_expires_at, datetime) and lease_expires_at > now:
                raise BatchReviewBusy("item already has an active lease")
            if active_lease_count >= 3:
                raise BatchReviewBusy("run already has three active leases")
            if str(item_row["status"]) not in {
                "queued",
                "parsing",
                "materializing",
                "validating",
            }:
                raise BatchReviewStateConflict("item cannot be advanced")
            lease_token = uuid4()
            fence = int(item_row["lease_fence"]) + 1
            status = "parsing" if item_row["status"] == "queued" else item_row["status"]
            connection.execute(
                sa.text(
                    """
                    UPDATE batch_review_items
                    SET operation_token = COALESCE(operation_token, :operation_token),
                        operation_digest = COALESCE(
                            operation_digest, :operation_digest
                        ),
                        status = :status, attempt_count = attempt_count + 1,
                        lease_token = :lease_token,
                        lease_started_at = :now,
                        lease_expires_at = :expires,
                        lease_fence = :lease_fence,
                        updated_at = :now
                    WHERE run_id = :run_id AND id = :item_id
                    """
                ),
                {
                    "operation_token": operation_token.bytes,
                    "operation_digest": operation_digest,
                    "status": status,
                    "lease_token": lease_token.bytes,
                    "now": now,
                    "expires": expires,
                    "lease_fence": fence,
                    "run_id": run_id,
                    "item_id": item_id,
                },
            )
            self._insert_command(
                connection,
                token=operation_token,
                kind="advance_item",
                digest=operation_digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                run_id=run_id,
                item_id=item_id,
                revision=None,
                timestamp=now,
                ignore_existing=True,
            )
            refreshed = self._item_row(connection, run_id, item_id)
            return ClaimedItem(
                self._item_from_row(refreshed), lease_token, fence, False
            )

    def record_item_stage(
        self,
        *,
        run_id: int,
        item_id: int,
        lease_token: UUID,
        lease_fence: int,
        status: BatchReviewItemStatus,
        domain_ids: Mapping[str, int | None] | None = None,
    ) -> BatchReviewItemRecord:
        if status not in {
            BatchReviewItemStatus.PARSING,
            BatchReviewItemStatus.MATERIALIZING,
            BatchReviewItemStatus.VALIDATING,
        }:
            raise BatchReviewStateConflict("recorded stage must be active")
        values = dict(domain_ids or {})
        allowed = {
            "parse_attempt_id",
            "parse_baseline_id",
            "dataset_id",
            "version_id",
            "validation_run_id",
        }
        if not set(values) <= allowed:
            raise ValueError("unsupported domain ID")
        assignments = ["status = :status", "updated_at = :updated_at"]
        assignments.extend(f"{name} = :{name}" for name in sorted(values))
        with self._engine.begin() as connection:
            updated = connection.execute(
                sa.text(
                    f"""
                    UPDATE batch_review_items
                    SET {", ".join(assignments)}
                    WHERE run_id = :run_id AND id = :item_id
                      AND lease_token = :lease_token
                      AND lease_fence = :lease_fence
                      AND lease_expires_at > :updated_at
                    """
                ),
                {
                    "status": status.value,
                    "updated_at": _mysql_time(_now()),
                    "run_id": run_id,
                    "item_id": item_id,
                    "lease_token": lease_token.bytes,
                    "lease_fence": lease_fence,
                    **values,
                },
            )
            if updated.rowcount != 1:
                raise BatchReviewBusy("item lease was lost")
            return self._item_from_row(self._item_row(connection, run_id, item_id))

    def finish_item(
        self,
        *,
        run_id: int,
        item_id: int,
        site_id: int,
        actor_user_id: int,
        operation_token: UUID,
        lease_token: UUID,
        lease_fence: int,
        status: BatchReviewItemStatus,
        reason_code: BatchReviewReasonCode | None = None,
        reason_message: str | None = None,
        retry_allowed: bool = False,
        outcome_unknown: bool = False,
        domain_ids: Mapping[str, int | None] | None = None,
    ) -> BatchReviewRunRecord:
        if status not in {
            BatchReviewItemStatus.READY_FOR_PUBLISH,
            BatchReviewItemStatus.MANUAL_REVIEW,
            BatchReviewItemStatus.FAILED,
        }:
            raise BatchReviewStateConflict("finish status must be terminal")
        values = dict(domain_ids or {})
        assignments = [
            "status = :status",
            "reason_code = :reason_code",
            "reason_message = :reason_message",
            "retry_allowed = :retry_allowed",
            "outcome_unknown = :outcome_unknown",
            "lease_token = NULL",
            "lease_started_at = NULL",
            "lease_expires_at = NULL",
            "updated_at = :updated_at",
        ]
        assignments.extend(f"{name} = :{name}" for name in sorted(values))
        timestamp = _mysql_time(_now())
        with self._engine.begin() as connection:
            updated = connection.execute(
                sa.text(
                    f"""
                    UPDATE batch_review_items
                    SET {", ".join(assignments)}
                    WHERE run_id = :run_id AND id = :item_id
                      AND lease_token = :lease_token
                      AND lease_fence = :lease_fence
                    """
                ),
                {
                    "status": status.value,
                    "reason_code": reason_code.value if reason_code else None,
                    "reason_message": reason_message,
                    "retry_allowed": retry_allowed,
                    "outcome_unknown": outcome_unknown,
                    "updated_at": timestamp,
                    "run_id": run_id,
                    "item_id": item_id,
                    "lease_token": lease_token.bytes,
                    "lease_fence": lease_fence,
                    **values,
                },
            )
            if updated.rowcount != 1:
                raise BatchReviewBusy("item lease was lost")
            connection.execute(
                sa.text(
                    """
                    UPDATE batch_review_commands
                    SET status = :command_status, completed_at = :completed_at
                    WHERE operation_token = :operation_token
                    """
                ),
                {
                    "command_status": (
                        "outcome_unknown" if outcome_unknown else "completed"
                    ),
                    "completed_at": timestamp,
                    "operation_token": operation_token.bytes,
                },
            )
            self._append_audit_event(
                connection,
                site_id=site_id,
                actor_user_id=actor_user_id,
                event_type="batch_review_item_finished",
                run_id=run_id,
                item_id=item_id,
                payload={
                    "status": status.value,
                    "reason_code": reason_code.value if reason_code else None,
                    "retry_allowed": retry_allowed,
                },
                request_id=str(operation_token),
                timestamp=timestamp,
            )
            self._recompute_run_status(connection, run_id, site_id, timestamp)
            return self._get_run(connection, run_id, site_id, lock=False)

    def change_run_state(
        self,
        *,
        run_id: int,
        site_id: int,
        actor_user_id: int,
        expected_revision: int,
        current: BatchReviewRunStatus,
        target: BatchReviewRunStatus,
        operation_token: UUID,
        operation_digest: bytes,
    ) -> BatchReviewRunRecord:
        timestamp = _mysql_time(_now())
        kind = "pause" if target is BatchReviewRunStatus.PAUSED else "resume"
        with self._engine.begin() as connection:
            recovered = self._recover_command(
                connection, operation_token, operation_digest, kind
            )
            if recovered is not None:
                return self._get_run(connection, recovered, site_id, lock=False)
            revision = expected_revision + 1
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE batch_review_runs
                    SET status = :target, revision = :revision,
                        operation_kind = :kind,
                        operation_token = :operation_token,
                        operation_digest = :operation_digest,
                        updated_at = :updated_at
                    WHERE id = :run_id AND site_id = :site_id
                      AND status = :current AND revision = :expected_revision
                    """
                ),
                {
                    "target": target.value,
                    "revision": revision,
                    "kind": kind,
                    "operation_token": operation_token.bytes,
                    "operation_digest": operation_digest,
                    "updated_at": timestamp,
                    "run_id": run_id,
                    "site_id": site_id,
                    "current": current.value,
                    "expected_revision": expected_revision,
                },
            )
            if updated.rowcount != 1:
                raise BatchReviewRevisionConflict("run state or revision changed")
            self._insert_command(
                connection,
                token=operation_token,
                kind=kind,
                digest=operation_digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                run_id=run_id,
                item_id=None,
                revision=revision,
                timestamp=timestamp,
            )
            self._append_audit_event(
                connection,
                site_id=site_id,
                actor_user_id=actor_user_id,
                event_type=f"batch_review_{kind}d",
                run_id=run_id,
                item_id=None,
                payload={"status": target.value, "revision": revision},
                request_id=str(operation_token),
                timestamp=timestamp,
            )
            return self._get_run(connection, run_id, site_id, lock=False)

    def retry_item(
        self,
        *,
        run_id: int,
        item_id: int,
        site_id: int,
        actor_user_id: int,
        expected_revision: int,
        operation_token: UUID,
        operation_digest: bytes,
    ) -> BatchReviewRunRecord:
        timestamp = _mysql_time(_now())
        with self._engine.begin() as connection:
            run = self._get_run(connection, run_id, site_id, lock=True)
            if run.revision != expected_revision:
                raise BatchReviewRevisionConflict("run revision changed")
            item = next((value for value in run.items if value.id == item_id), None)
            if item is None:
                raise BatchReviewNotFound("item not found")
            if (
                item.status is not BatchReviewItemStatus.FAILED
                or not item.retry_allowed
            ):
                raise BatchReviewStateConflict("item is not retryable")
            connection.execute(
                sa.text(
                    """
                    UPDATE batch_review_items
                    SET status = 'queued', retry_allowed = FALSE,
                        outcome_unknown = FALSE, reason_code = NULL,
                        reason_message = NULL, operation_token = NULL,
                        operation_digest = NULL, updated_at = :updated_at
                    WHERE run_id = :run_id AND id = :item_id
                    """
                ),
                {"updated_at": timestamp, "run_id": run_id, "item_id": item_id},
            )
            revision = run.revision + 1
            connection.execute(
                sa.text(
                    """
                    UPDATE batch_review_runs
                    SET status = 'running', revision = :revision,
                        updated_at = :updated_at
                    WHERE id = :run_id AND site_id = :site_id
                    """
                ),
                {
                    "revision": revision,
                    "updated_at": timestamp,
                    "run_id": run_id,
                    "site_id": site_id,
                },
            )
            self._insert_command(
                connection,
                token=operation_token,
                kind="retry_item",
                digest=operation_digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                run_id=run_id,
                item_id=item_id,
                revision=revision,
                timestamp=timestamp,
            )
            return self._get_run(connection, run_id, site_id, lock=False)

    @staticmethod
    def _recover_command(
        connection: Connection,
        token: UUID,
        digest: bytes,
        kind: str,
    ) -> int | None:
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT operation_kind, operation_digest, run_id
                    FROM batch_review_commands
                    WHERE operation_token = :operation_token
                    """
                ),
                {"operation_token": token.bytes},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        if row["operation_kind"] != kind or not hmac.compare_digest(
            bytes(row["operation_digest"]), digest
        ):
            raise BatchReviewOperationConflict(
                "idempotency key is bound to another command"
            )
        return int(row["run_id"])

    @staticmethod
    def _insert_command(
        connection: Connection,
        *,
        token: UUID,
        kind: str,
        digest: bytes,
        site_id: int,
        actor_user_id: int,
        run_id: int,
        item_id: int | None,
        revision: int | None,
        timestamp: datetime,
        ignore_existing: bool = False,
    ) -> None:
        prefix = "INSERT IGNORE" if ignore_existing else "INSERT"
        connection.execute(
            sa.text(
                f"""
                {prefix} INTO batch_review_commands (
                    operation_token, operation_kind, operation_digest,
                    site_id, actor_user_id, run_id, item_id, status,
                    response_revision, created_at, completed_at
                ) VALUES (
                    :operation_token, :operation_kind, :operation_digest,
                    :site_id, :actor_user_id, :run_id, :item_id, 'completed',
                    :response_revision, :created_at, :created_at
                )
                """
            ),
            {
                "operation_token": token.bytes,
                "operation_kind": kind,
                "operation_digest": digest,
                "site_id": site_id,
                "actor_user_id": actor_user_id,
                "run_id": run_id,
                "item_id": item_id,
                "response_revision": revision,
                "created_at": timestamp,
            },
        )

    def _get_run(
        self,
        connection: Connection,
        run_id: int,
        site_id: int,
        *,
        lock: bool,
    ) -> BatchReviewRunRecord:
        suffix = " FOR UPDATE" if lock else ""
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, site_id, created_by_user_id, status, revision,
                           confirmation_statement_version
                    FROM batch_review_runs
                    WHERE id = :run_id AND site_id = :site_id
                    """
                    + suffix
                ),
                {"run_id": run_id, "site_id": site_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise BatchReviewNotFound("batch review run not found")
        item_rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT * FROM batch_review_items
                    WHERE run_id = :run_id
                    ORDER BY id
                    """
                    + suffix
                ),
                {"run_id": run_id},
            )
            .mappings()
            .all()
        )
        return BatchReviewRunRecord(
            id=int(row["id"]),
            site_id=int(row["site_id"]),
            created_by_user_id=int(row["created_by_user_id"]),
            status=BatchReviewRunStatus(str(row["status"])),
            revision=int(row["revision"]),
            confirmation_statement_version=(
                str(row["confirmation_statement_version"])
                if row["confirmation_statement_version"] is not None
                else None
            ),
            items=tuple(self._item_from_row(item) for item in item_rows),
        )

    @staticmethod
    def _item_row(
        connection: Connection,
        run_id: int,
        item_id: int,
    ) -> RowMapping:
        return (
            connection.execute(
                sa.text(
                    """
                    SELECT * FROM batch_review_items
                    WHERE run_id = :run_id AND id = :item_id
                    """
                ),
                {"run_id": run_id, "item_id": item_id},
            )
            .mappings()
            .one()
        )

    @staticmethod
    def _item_from_row(
        row: RowMapping | Mapping[str, Any],
    ) -> BatchReviewItemRecord:
        def optional_id(name: str) -> int | None:
            return int(cast(int | str, row[name])) if row[name] is not None else None

        return BatchReviewItemRecord(
            id=int(cast(int, row["id"])),
            run_id=int(cast(int, row["run_id"])),
            site_id=int(cast(int, row["site_id"])),
            batch_id=int(cast(int, row["batch_id"])),
            filename=str(row["filename"]),
            detected_report_date=cast(date | None, row["detected_report_date"]),
            detected_report_type=cast(ReportType | None, row["detected_report_type"]),
            detected_encoding=cast(SupportedEncoding | None, row["detected_encoding"]),
            recognition_status=str(row["recognition_status"]),
            selected=bool(row["selected"]),
            status=BatchReviewItemStatus(str(row["status"])),
            reason_code=(
                BatchReviewReasonCode(str(row["reason_code"]))
                if row["reason_code"] is not None
                else None
            ),
            reason_message=(
                str(row["reason_message"])
                if row["reason_message"] is not None
                else None
            ),
            manual_review_url=(
                str(row["manual_review_url"])
                if row["manual_review_url"] is not None
                else None
            ),
            parse_attempt_id=optional_id("parse_attempt_id"),
            parse_baseline_id=optional_id("parse_baseline_id"),
            dataset_id=optional_id("dataset_id"),
            version_id=optional_id("version_id"),
            validation_run_id=optional_id("validation_run_id"),
            operation_token=(
                UUID(bytes=bytes(cast(bytes, row["operation_token"])))
                if row["operation_token"] is not None
                else None
            ),
            operation_digest=(
                bytes(cast(bytes, row["operation_digest"]))
                if row["operation_digest"] is not None
                else None
            ),
            attempt_count=int(cast(int, row["attempt_count"])),
            retry_allowed=bool(row["retry_allowed"]),
            outcome_unknown=bool(row["outcome_unknown"]),
            lease_token=(
                UUID(bytes=bytes(cast(bytes, row["lease_token"])))
                if row["lease_token"] is not None
                else None
            ),
            lease_fence=int(cast(int, row["lease_fence"])),
            lease_expires_at=cast(datetime | None, row["lease_expires_at"]),
        )

    @staticmethod
    def _recompute_run_status(
        connection: Connection,
        run_id: int,
        site_id: int,
        timestamp: datetime,
    ) -> None:
        statuses = tuple(
            BatchReviewItemStatus(str(value))
            for value in connection.scalars(
                sa.text(
                    """
                    SELECT status FROM batch_review_items
                    WHERE run_id = :run_id AND selected = TRUE
                    ORDER BY id
                    """
                ),
                {"run_id": run_id},
            ).all()
        )
        status = aggregate_run_status(statuses)
        if status in {
            BatchReviewRunStatus.COMPLETED,
            BatchReviewRunStatus.COMPLETED_WITH_EXCEPTIONS,
        }:
            connection.execute(
                sa.text(
                    """
                    UPDATE batch_review_runs
                    SET status = :status, revision = revision + 1,
                        updated_at = :updated_at
                    WHERE id = :run_id AND site_id = :site_id
                      AND status IN ('running', 'paused')
                    """
                ),
                {
                    "status": status.value,
                    "updated_at": timestamp,
                    "run_id": run_id,
                    "site_id": site_id,
                },
            )

    @staticmethod
    def _append_audit_event(
        connection: Connection,
        *,
        site_id: int,
        actor_user_id: int,
        event_type: str,
        run_id: int,
        item_id: int | None,
        payload: Mapping[str, object],
        request_id: str,
        timestamp: datetime,
    ) -> None:
        safe_payload: dict[str, object] = {
            "run_id": run_id,
            "item_id": item_id,
            **payload,
        }
        connection.execute(
            sa.text(
                """
                INSERT INTO audit_events (
                    site_id, actor_user_id, event_type, object_type,
                    object_id, request_id, redacted_payload, occurred_at
                ) VALUES (
                    :site_id, :actor_user_id, :event_type, 'batch_review_run',
                    :object_id, :request_id, :redacted_payload, :occurred_at
                )
                """
            ),
            {
                "site_id": site_id,
                "actor_user_id": actor_user_id,
                "event_type": event_type,
                "object_id": str(run_id),
                "request_id": request_id,
                "redacted_payload": _canonical_json(safe_payload),
                "occurred_at": timestamp,
            },
        )
