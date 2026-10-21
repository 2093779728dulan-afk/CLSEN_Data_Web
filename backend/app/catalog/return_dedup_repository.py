"""MySQL persistence for frozen return-dedup staging and snapshot publication."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.return_dedup import (
    RETURN_EVENT_FINGERPRINT_VERSION,
    CandidateGroup,
    PriorGroupRevision,
    ReturnEventFields,
    ReturnEventMember,
    build_candidate_groups,
    plan_snapshot_delta,
    validate_duplicate_decision,
)
from app.catalog.source_refs import SafeSourceRef, make_safe_source_ref
from app.catalog.types import CatalogSourceKind
from app.site_context import CurrentSiteContext

type StagingStatus = Literal["building", "ready", "failed", "superseded"]


class ReturnDedupError(RuntimeError):
    code = "return_dedup_unavailable"

    def __init__(self) -> None:
        super().__init__(self.code)


class ReturnDedupPermissionDenied(ReturnDedupError):
    code = "return_dedup_forbidden"


class ReturnDedupNotFound(ReturnDedupError):
    code = "return_dedup_staging_not_found"


class ReturnDedupIdempotencyConflict(ReturnDedupError):
    code = "idempotency_key_reused"


class ReturnDedupJobRevisionConflict(ReturnDedupError):
    code = "return_dedup_job_revision_conflict"


class ReturnDedupPublicationRevisionConflict(ReturnDedupError):
    code = "return_dedup_publication_revision_conflict"


class ReturnDedupStagingNotReady(ReturnDedupError):
    code = "return_dedup_staging_not_ready"


class ReturnDedupStagingFailed(ReturnDedupError):
    code = "return_dedup_staging_failed"


class ReturnDedupStagingSuperseded(ReturnDedupError):
    code = "return_dedup_staging_superseded"


class ReturnDedupStagingConflict(ReturnDedupError):
    code = "return_dedup_staging_conflict"


class ReturnDedupDecisionInvalid(ReturnDedupError):
    code = "return_dedup_decision_invalid"


class ReturnDedupIntegrityError(ReturnDedupError):
    code = "return_dedup_integrity_error"


@dataclass(frozen=True, slots=True)
class CreateReturnDedupStaging:
    operation_token: UUID
    dataset_id: int
    proposed_version_id: int
    expected_publication_revision: int
    expected_dedup_publication_revision: int
    initialization_revision: int | None = None
    expected_set_digest: bytes | None = None

    def __post_init__(self) -> None:
        if self.initialization_revision is not None and (
            self.initialization_revision < 1
            or self.expected_set_digest is None
            or len(self.expected_set_digest) != 32
        ):
            raise ValueError("initialization requires revision and digest")
        if self.operation_token.version != 4:
            raise ValueError("operation_token must be UUID v4")
        if self.dataset_id < 1 or self.proposed_version_id < 1:
            raise ValueError("dataset and version IDs must be positive")
        if (
            self.expected_publication_revision < 0
            or self.expected_dedup_publication_revision < 0
        ):
            raise ValueError("publication revisions must be nonnegative")

    def digest(self, *, actor_user_id: int, site_id: int) -> bytes:
        return hashlib.sha256(
            canonical_json_bytes(
                {
                    **(
                        {
                            "initialization_revision": self.initialization_revision,
                            "expected_set_digest": self.expected_set_digest.hex()
                            if self.expected_set_digest
                            else None,
                        }
                        if self.initialization_revision is not None
                        else {}
                    ),
                    "actor_user_id": actor_user_id,
                    "dataset_id": self.dataset_id,
                    "expected_dedup_publication_revision": (
                        self.expected_dedup_publication_revision
                    ),
                    "expected_publication_revision": (
                        self.expected_publication_revision
                    ),
                    "proposed_version_id": self.proposed_version_id,
                    "site_id": site_id,
                }
            )
        ).digest()


@dataclass(frozen=True, slots=True)
class RetryReturnDedupStaging:
    operation_token: UUID
    expected_job_revision: int
    proposed_set_digest: bytes

    def __post_init__(self) -> None:
        if self.operation_token.version != 4:
            raise ValueError("operation_token must be UUID v4")
        if self.expected_job_revision < 0:
            raise ValueError("expected_job_revision must be nonnegative")
        if len(self.proposed_set_digest) != 32:
            raise ValueError("proposed_set_digest must be 32 bytes")

    def digest(self, *, actor_user_id: int, job_id: int) -> bytes:
        return hashlib.sha256(
            canonical_json_bytes(
                {
                    "actor_user_id": actor_user_id,
                    "expected_job_revision": self.expected_job_revision,
                    "job_id": job_id,
                    "proposed_set_digest": self.proposed_set_digest.hex(),
                }
            )
        ).digest()


@dataclass(frozen=True, slots=True)
class FrozenPublicationMember:
    dataset_id: int
    published_version_id: int
    publication_revision: int
    version_data_revision: int
    report_date: date

    def digest_payload(self) -> list[object]:
        return [
            self.report_date.isoformat(),
            self.dataset_id,
            self.published_version_id,
            self.publication_revision,
            self.version_data_revision,
        ]


@dataclass(frozen=True, slots=True)
class ReturnDedupStagingJob:
    job_id: int
    site_id: int
    report_source_scope_id: int
    operation_token: UUID
    actor_user_id: int
    dataset_id: int
    proposed_version_id: int
    proposed_set_digest: bytes
    expected_publication_revision: int
    expected_dedup_publication_revision: int
    status: StagingStatus
    job_revision: int
    retry_allowed: bool
    failure_reason: str | None
    lease_token: UUID | None
    fencing_token: int
    lease_expires_at: datetime | None
    result_snapshot_id: int | None
    initialization_revision: int | None = None


@dataclass(frozen=True, slots=True)
class ReturnDedupGroupMemberView:
    source_key_id: int
    source_ref: SafeSourceRef
    report_date: date
    dataset_id: int
    published_version_id: int


@dataclass(frozen=True, slots=True)
class ReturnDedupGroupView:
    group_id: str
    group_revision: int
    decision: Literal["unresolved", "confirmed_distinct", "duplicate_of"]
    canonical_member_id: int | None
    member_count: int
    members: tuple[ReturnDedupGroupMemberView, ...]


@dataclass(frozen=True, slots=True)
class ReturnDedupGroupPage:
    dedup_publication_revision: int
    snapshot_id: int
    page: int
    page_size: int
    total_items: int
    groups: tuple[ReturnDedupGroupView, ...]


@dataclass(frozen=True, slots=True)
class DecideReturnDedupGroup:
    operation_token: UUID
    group_id: str
    expected_dedup_publication_revision: int
    expected_group_revision: int
    decision: Literal["confirmed_distinct", "duplicate_of"]
    canonical_member_id: int | None
    reason: str

    def __post_init__(self) -> None:
        if self.operation_token.version != 4:
            raise ValueError("operation_token must be UUID v4")
        if len(self.group_id) != 64:
            raise ValueError("group_id must be a SHA-256 hex value")
        try:
            bytes.fromhex(self.group_id)
        except ValueError as error:
            raise ValueError("group_id must be a SHA-256 hex value") from error
        if (
            self.expected_dedup_publication_revision < 0
            or self.expected_group_revision < 1
        ):
            raise ValueError("decision revisions are invalid")
        normalized_reason = self.reason.strip()
        if not normalized_reason or len(normalized_reason) > 500:
            raise ValueError("decision reason must contain 1 to 500 characters")
        object.__setattr__(self, "reason", normalized_reason)

    def digest(self, *, actor_user_id: int, site_id: int) -> bytes:
        return hashlib.sha256(
            canonical_json_bytes(
                {
                    "actor_user_id": actor_user_id,
                    "canonical_member_id": self.canonical_member_id,
                    "decision": self.decision,
                    "expected_dedup_publication_revision": (
                        self.expected_dedup_publication_revision
                    ),
                    "expected_group_revision": self.expected_group_revision,
                    "group_id": self.group_id,
                    "reason": self.reason,
                    "site_id": site_id,
                }
            )
        ).digest()


@dataclass(frozen=True, slots=True)
class ReturnDedupDecisionResult:
    group_id: str
    group_revision: int
    dedup_publication_revision: int
    snapshot_id: int
    decision: Literal["confirmed_distinct", "duplicate_of"]
    canonical_member_id: int | None


@dataclass(frozen=True, slots=True)
class ReturnDedupLease:
    job_id: int
    job_revision: int
    lease_token: UUID
    fencing_token: int
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class FrozenReturnDedupInput:
    job: ReturnDedupStagingJob
    members: tuple[FrozenPublicationMember, ...]
    events: tuple[ReturnEventMember, ...]
    previous_snapshot_id: int | None
    previous_checkpoint_id: int | None
    previous_delta_depth: int | None
    previous_groups: Mapping[bytes, tuple[int, PriorGroupRevision]]


def _mysql_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ReturnDedupIntegrityError()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if value.utcoffset() is None:
        raise ReturnDedupIntegrityError()
    return value.astimezone(UTC)


def _bytes(value: object, length: int) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ReturnDedupIntegrityError()
    result = bytes(value)
    if len(result) != length:
        raise ReturnDedupIntegrityError()
    return result


def publication_set_digest(
    members: tuple[FrozenPublicationMember, ...],
) -> bytes:
    ordered = tuple(
        sorted(members, key=lambda item: (item.report_date, item.dataset_id))
    )
    return hashlib.sha256(
        canonical_json_bytes([member.digest_payload() for member in ordered])
    ).digest()


def _job_from_row(row: RowMapping) -> ReturnDedupStagingJob:
    lease_raw = row["lease_token"]
    lease_token = UUID(bytes=_bytes(lease_raw, 16)) if lease_raw is not None else None
    lease_expires = row["lease_expires_at"]
    status = str(row["status"])
    if status not in {"building", "ready", "failed", "superseded"}:
        raise ReturnDedupIntegrityError()
    return ReturnDedupStagingJob(
        job_id=int(row["id"]),
        site_id=int(row["site_id"]),
        report_source_scope_id=int(row["report_source_scope_id"]),
        operation_token=UUID(bytes=_bytes(row["operation_token"], 16)),
        actor_user_id=int(row["actor_user_id"]),
        dataset_id=int(row["dataset_id"]),
        proposed_version_id=int(row["proposed_version_id"]),
        proposed_set_digest=_bytes(row["proposed_set_digest"], 32),
        expected_publication_revision=int(row["expected_publication_revision"]),
        expected_dedup_publication_revision=int(
            row["expected_dedup_publication_revision"]
        ),
        initialization_revision=row["initialization_revision"],
        status=status,  # type: ignore[arg-type]
        job_revision=int(row["job_revision"]),
        retry_allowed=bool(row["retry_allowed"]),
        failure_reason=(
            str(row["failure_reason_code"])
            if row["failure_reason_code"] is not None
            else None
        ),
        lease_token=lease_token,
        fencing_token=int(row["fencing_token"]),
        lease_expires_at=(
            _utc_datetime(lease_expires) if lease_expires is not None else None
        ),
        result_snapshot_id=(
            int(row["result_snapshot_id"])
            if row["result_snapshot_id"] is not None
            else None
        ),
    )


_JOB_COLUMNS = """
    id, site_id, report_source_scope_id, operation_token, actor_user_id,
    dataset_id, proposed_version_id, proposed_set_digest,
    expected_publication_revision, expected_dedup_publication_revision,
    status, job_revision, retry_allowed, failure_reason_code, lease_token,
    fencing_token, lease_expires_at, result_snapshot_id, initialization_revision
"""


class MySqlReturnDedupRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _require_manager(context: CurrentSiteContext) -> None:
        if not context.principal_roles.intersection({"data_manager", "admin"}):
            raise ReturnDedupPermissionDenied()

    @staticmethod
    def _lock_scope(connection: Connection, *, site_id: int) -> int:
        # The scope row is immutable and the runtime account intentionally has
        # no UPDATE privilege. Mutable publication-revision and dedup-pointer
        # rows provide the write synchronization boundaries.
        rows = connection.execute(
            sa.text(
                """
                SELECT id FROM report_source_scopes
                WHERE site_id = :site_id
                """
            ),
            {"site_id": site_id},
        ).all()
        if len(rows) != 1:
            raise ReturnDedupNotFound()
        return int(rows[0][0])

    @staticmethod
    def _job(
        connection: Connection,
        *,
        job_id: int | None = None,
        operation_token: UUID | None = None,
        lock: bool = False,
    ) -> ReturnDedupStagingJob | None:
        if (job_id is None) == (operation_token is None):
            raise ValueError("exactly one job locator is required")
        predicate = "id = :value" if job_id is not None else "operation_token = :value"
        suffix = " FOR UPDATE" if lock else ""
        if job_id is not None:
            value: object = job_id
        elif operation_token is not None:
            value = operation_token.bytes
        else:  # pragma: no cover - guarded by the locator invariant above
            raise ValueError("operation token is required")
        row = (
            connection.execute(
                sa.text(
                    f"SELECT {_JOB_COLUMNS} FROM return_dedup_staging_jobs "
                    f"WHERE {predicate}{suffix}"
                ),
                {"value": value},
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _job_from_row(row)

    def get_job(
        self, context: CurrentSiteContext, job_id: int
    ) -> ReturnDedupStagingJob:
        self._require_manager(context)
        with self._engine.connect() as connection:
            job = self._job(connection, job_id=job_id)
        if job is None or job.site_id != context.site_id:
            raise ReturnDedupNotFound()
        return job

    def retry(
        self,
        context: CurrentSiteContext,
        job_id: int,
        command: RetryReturnDedupStaging,
        *,
        occurred_at: datetime,
    ) -> ReturnDedupStagingJob:
        self._require_manager(context)
        digest = command.digest(
            actor_user_id=context.principal_user_id,
            job_id=job_id,
        )
        with self._engine.begin() as connection:
            job = self._job(connection, job_id=job_id, lock=True)
            if job is None or job.site_id != context.site_id:
                raise ReturnDedupNotFound()
            replay = (
                connection.execute(
                    sa.text(
                        """
                        SELECT retry_operation_digest
                        FROM return_dedup_staging_jobs
                        WHERE id = :job_id
                          AND retry_operation_token = :operation_token
                        """
                    ),
                    {
                        "job_id": job_id,
                        "operation_token": command.operation_token.bytes,
                    },
                )
                .mappings()
                .one_or_none()
            )
            if replay is not None:
                if not hmac.compare_digest(
                    _bytes(replay["retry_operation_digest"], 32), digest
                ):
                    raise ReturnDedupIdempotencyConflict()
                return job
            if (
                job.status != "failed"
                or not job.retry_allowed
                or job.job_revision != command.expected_job_revision
                or not hmac.compare_digest(
                    job.proposed_set_digest, command.proposed_set_digest
                )
            ):
                raise ReturnDedupJobRevisionConflict()
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE return_dedup_staging_jobs
                    SET status = 'building', job_revision = job_revision + 1,
                        retry_allowed = FALSE, failure_reason_code = NULL,
                        retry_operation_token = :operation_token,
                        retry_operation_digest = :operation_digest,
                        updated_at = :updated_at
                    WHERE id = :job_id AND status = 'failed'
                      AND retry_allowed = TRUE
                      AND job_revision = :expected_revision
                    """
                ),
                {
                    "operation_token": command.operation_token.bytes,
                    "operation_digest": digest,
                    "updated_at": _mysql_datetime(occurred_at),
                    "job_id": job_id,
                    "expected_revision": command.expected_job_revision,
                },
            )
            if updated.rowcount != 1:
                raise ReturnDedupJobRevisionConflict()
            result = self._job(connection, job_id=job_id)
            if result is None:
                raise ReturnDedupIntegrityError()
            return result

    def next_claimable(self, *, occurred_at: datetime) -> tuple[int, int] | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT id, job_revision
                        FROM return_dedup_staging_jobs
                        WHERE status = 'building'
                          AND (lease_token IS NULL OR lease_expires_at <= :now)
                        ORDER BY id
                        LIMIT 1
                        """
                    ),
                    {"now": _mysql_datetime(occurred_at)},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return int(row["id"]), int(row["job_revision"])

    @staticmethod
    def _undo_restoration_member(
        connection: Connection,
        *,
        site_id: int,
        scope_id: int,
        source_dataset_id: int,
        restore_source_version_id: int,
    ) -> tuple[int, FrozenPublicationMember | None] | None:
        rows = (
            connection.execute(
                sa.text(
                    """
                    WITH move_events AS (
                        SELECT events.command_id,
                               MAX(CASE WHEN events.event_type = 'moved_out'
                                        THEN events.dataset_id END)
                                   AS source_dataset_id,
                               MAX(CASE WHEN events.event_type = 'moved_out'
                                        THEN events.previous_version_id END)
                                   AS restore_source_version_id,
                               MAX(CASE WHEN events.event_type = 'moved_in'
                                        THEN events.dataset_id END)
                                   AS target_dataset_id,
                               MAX(CASE WHEN events.event_type = 'moved_in'
                                        THEN events.previous_version_id END)
                                   AS restore_target_version_id,
                               MAX(CASE WHEN events.event_type = 'moved_in'
                                        THEN events.next_version_id END)
                                   AS moved_target_version_id
                        FROM publication_events AS events
                        GROUP BY events.command_id
                        HAVING COUNT(*) = 2
                           AND SUM(events.event_type = 'moved_out') = 1
                           AND SUM(events.event_type = 'moved_in') = 1
                    )
                    SELECT move_events.target_dataset_id,
                           move_events.restore_target_version_id,
                           target_datasets.report_date,
                           target_revisions.publication_revision,
                           restored_target.data_revision
                    FROM move_events
                    INNER JOIN publication_command_results AS results
                        ON results.command_id = move_events.command_id
                       AND results.operation_kind = 'move'
                       AND results.result_kind = 'moved'
                       AND results.result_status = 'published'
                    INNER JOIN publication_commands AS commands
                        ON commands.id = results.command_id
                       AND commands.operation_token = results.operation_token
                       AND commands.operation_kind = results.operation_kind
                       AND commands.operation_digest = results.operation_digest
                       AND commands.actor_user_id = results.actor_user_id
                    INNER JOIN daily_datasets AS source_datasets
                        ON source_datasets.id = move_events.source_dataset_id
                       AND source_datasets.site_id = :site_id
                       AND source_datasets.report_type = 'return_report'
                    INNER JOIN daily_datasets AS target_datasets
                        ON target_datasets.id = move_events.target_dataset_id
                       AND target_datasets.site_id = source_datasets.site_id
                       AND target_datasets.report_type = source_datasets.report_type
                    INNER JOIN report_dataset_scope_assignments AS target_assignments
                        ON target_assignments.dataset_id = target_datasets.id
                       AND target_assignments.site_id = target_datasets.site_id
                       AND target_assignments.report_source_scope_id = :scope_id
                    INNER JOIN report_publication_revisions AS target_revisions
                        ON target_revisions.dataset_id = target_datasets.id
                       AND target_revisions.site_id = target_datasets.site_id
                       AND target_revisions.report_source_scope_id = :scope_id
                    LEFT JOIN dataset_versions AS restored_target
                        ON restored_target.id = move_events.restore_target_version_id
                       AND restored_target.dataset_id = target_datasets.id
                       AND restored_target.report_type = target_datasets.report_type
                       AND restored_target.status = 'published'
                    LEFT JOIN dataset_publications AS source_publications
                        ON source_publications.dataset_id = source_datasets.id
                    INNER JOIN dataset_publications AS target_publications
                        ON target_publications.dataset_id = target_datasets.id
                       AND target_publications.version_id =
                           move_events.moved_target_version_id
                    WHERE commands.operation_kind = 'move'
                      AND move_events.source_dataset_id = :source_dataset_id
                      AND move_events.restore_source_version_id =
                          :restore_source_version_id
                      AND source_publications.dataset_id IS NULL
                      AND (
                          move_events.restore_target_version_id IS NULL
                          OR restored_target.id IS NOT NULL
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM publication_command_results AS reversals
                          WHERE reversals.operation_kind = 'reverse_move'
                            AND reversals.result_kind = 'move_reversed'
                            AND reversals.reversed_move_command_id =
                                results.command_id
                      )
                    ORDER BY results.completed_at DESC, results.command_id DESC
                    LIMIT 2
                    """
                ),
                {
                    "site_id": site_id,
                    "scope_id": scope_id,
                    "source_dataset_id": source_dataset_id,
                    "restore_source_version_id": restore_source_version_id,
                },
            )
            .mappings()
            .all()
        )
        if len(rows) != 1:
            return None
        row = rows[0]
        target_dataset_id = int(row["target_dataset_id"])
        if row["restore_target_version_id"] is None:
            return target_dataset_id, None
        if row["data_revision"] is None:
            raise ReturnDedupIntegrityError()
        return target_dataset_id, FrozenPublicationMember(
            dataset_id=target_dataset_id,
            published_version_id=int(row["restore_target_version_id"]),
            publication_revision=int(row["publication_revision"]),
            version_data_revision=int(row["data_revision"]),
            report_date=row["report_date"],
        )

    @staticmethod
    def _frozen_members(
        connection: Connection,
        *,
        site_id: int,
        scope_id: int,
        target_dataset_id: int,
        proposed_version_id: int,
        initialization: bool = False,
    ) -> tuple[FrozenPublicationMember, ...]:
        proposed = (
            connection.execute(
                sa.text(
                    """
                    SELECT datasets.id AS dataset_id, datasets.report_date,
                           datasets.report_type, versions.id AS version_id,
                           versions.data_revision, versions.status,
                           revisions.publication_revision
                    FROM daily_datasets AS datasets
                    INNER JOIN report_dataset_scope_assignments AS assignments
                        ON assignments.dataset_id = datasets.id
                       AND assignments.site_id = datasets.site_id
                    INNER JOIN report_publication_revisions AS revisions
                        ON revisions.dataset_id = datasets.id
                       AND revisions.site_id = datasets.site_id
                       AND revisions.report_source_scope_id =
                           assignments.report_source_scope_id
                    INNER JOIN dataset_versions AS versions
                        ON versions.dataset_id = datasets.id
                       AND versions.report_type = datasets.report_type
                    WHERE datasets.site_id = :site_id
                      AND assignments.report_source_scope_id = :scope_id
                      AND versions.id = :version_id
                    """
                ),
                {
                    "site_id": site_id,
                    "scope_id": scope_id,
                    "version_id": proposed_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        if (
            proposed is None
            or proposed["report_type"] != "return_report"
            or proposed["status"] not in {"ready_for_publish", "published"}
        ):
            raise ReturnDedupNotFound()
        source_revision = connection.scalar(
            sa.text(
                """
                SELECT publication_revision
                FROM report_publication_revisions
                WHERE dataset_id = :dataset_id AND site_id = :site_id
                  AND report_source_scope_id = :scope_id
                """
            ),
            {
                "dataset_id": target_dataset_id,
                "site_id": site_id,
                "scope_id": scope_id,
            },
        )
        if source_revision is None:
            raise ReturnDedupNotFound()
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT datasets.id AS dataset_id, datasets.report_date,
                           publications.version_id, versions.data_revision,
                           revisions.publication_revision
                    FROM daily_datasets AS datasets
                    INNER JOIN report_dataset_scope_assignments AS assignments
                        ON assignments.dataset_id = datasets.id
                       AND assignments.site_id = datasets.site_id
                    INNER JOIN report_publication_revisions AS revisions
                        ON revisions.dataset_id = datasets.id
                       AND revisions.site_id = datasets.site_id
                       AND revisions.report_source_scope_id =
                           assignments.report_source_scope_id
                    INNER JOIN dataset_publications AS publications
                        ON publications.dataset_id = datasets.id
                    INNER JOIN dataset_versions AS versions
                        ON versions.id = publications.version_id
                       AND versions.dataset_id = datasets.id
                       AND versions.status = 'published'
                    WHERE datasets.site_id = :site_id
                      AND datasets.report_type = 'return_report'
                      AND assignments.report_source_scope_id = :scope_id
                    ORDER BY datasets.report_date, datasets.id
                    """
                ),
                {"site_id": site_id, "scope_id": scope_id},
            )
            .mappings()
            .all()
        )
        members = {
            int(row["dataset_id"]): FrozenPublicationMember(
                dataset_id=int(row["dataset_id"]),
                published_version_id=int(row["version_id"]),
                publication_revision=int(row["publication_revision"]),
                version_data_revision=int(row["data_revision"]),
                report_date=row["report_date"],
            )
            for row in rows
        }
        proposed_dataset_id = int(proposed["dataset_id"])
        if initialization:
            if (
                target_dataset_id not in members
                or members[target_dataset_id].published_version_id
                != proposed_version_id
            ):
                raise ReturnDedupPublicationRevisionConflict()
            return tuple(
                sorted(
                    members.values(),
                    key=lambda item: (item.report_date, item.dataset_id),
                )
            )
        if proposed_dataset_id != target_dataset_id:
            members.pop(target_dataset_id, None)
        elif target_dataset_id not in members and proposed["status"] == "published":
            restoration = MySqlReturnDedupRepository._undo_restoration_member(
                connection,
                site_id=site_id,
                scope_id=scope_id,
                source_dataset_id=target_dataset_id,
                restore_source_version_id=proposed_version_id,
            )
            if restoration is None:
                raise ReturnDedupNotFound()
            restored_target_dataset_id, restored_target = restoration
            members.pop(restored_target_dataset_id, None)
            if restored_target is not None:
                members[restored_target_dataset_id] = replace(
                    restored_target,
                    publication_revision=(restored_target.publication_revision + 1),
                )
        members[proposed_dataset_id] = FrozenPublicationMember(
            dataset_id=proposed_dataset_id,
            published_version_id=proposed_version_id,
            # The staged snapshot becomes current only after the publication
            # transaction advances every affected pointer revision. Freeze the
            # post-commit value so the snapshot remains valid after commit.
            publication_revision=int(proposed["publication_revision"]) + 1,
            version_data_revision=int(proposed["data_revision"]),
            report_date=proposed["report_date"],
        )
        return tuple(
            sorted(
                members.values(),
                key=lambda item: (item.report_date, item.dataset_id),
            )
        )

    @staticmethod
    def _lock_initialization(connection: Connection, site_id: int) -> None:
        # Match source confirmation lock order, before any consistent reads.
        connection.execute(
            sa.text(
                """
                SELECT current_config_version_id FROM site_current_configs WHERE
                site_id=:site FOR UPDATE
                """
            ),
            {"site": site_id},
        ).all()
        connection.execute(
            sa.text(
                """
                SELECT current_snapshot_id FROM return_dedup_publications WHERE
                site_id=:site FOR UPDATE
                """
            ),
            {"site": site_id},
        ).all()

    @staticmethod
    def _config_revision(connection: Connection, site_id: int) -> int:
        value = connection.scalar(
            sa.text(
                """
                SELECT v.version_number FROM site_current_configs c JOIN
                site_config_versions v ON v.id=c.current_config_version_id AND
                v.site_id=c.site_id WHERE c.site_id=:site
                """
            ),
            {"site": site_id},
        )
        if value is None:
            raise ReturnDedupNotFound()
        return int(value)

    def initialization_preview(self, context: CurrentSiteContext) -> dict[str, Any]:
        self._require_manager(context)
        with self._engine.connect() as connection:
            scope = self._lock_scope(connection, site_id=context.site_id)
            target = connection.execute(
                sa.text(
                    """
                    SELECT d.id,p.version_id FROM daily_datasets d JOIN
                    dataset_publications p ON p.dataset_id=d.id WHERE d.site_id=:site
                    AND d.report_type='return_report' ORDER BY d.report_date
                    DESC,d.id DESC LIMIT 1
                    """
                ),
                {"site": context.site_id},
            ).one_or_none()
            if target is None:
                raise ReturnDedupNotFound()
            members = self._frozen_members(
                connection,
                site_id=context.site_id,
                scope_id=scope,
                target_dataset_id=target.id,
                proposed_version_id=target.version_id,
                initialization=True,
            )
            pointer = connection.execute(
                sa.text(
                    """
                    SELECT current_snapshot_id,dedup_publication_revision FROM
                    return_dedup_publications WHERE site_id=:site AND
                    report_source_scope_id=:scope
                    """
                ),
                {"site": context.site_id, "scope": scope},
            ).one()
            if (
                pointer.current_snapshot_id is not None
                or pointer.dedup_publication_revision != 0
            ):
                raise ReturnDedupPublicationRevisionConflict()
            selected = next(m for m in members if m.dataset_id == target.id)
            return {
                "dataset_id": selected.dataset_id,
                "proposed_version_id": selected.published_version_id,
                "expected_publication_revision": selected.publication_revision,
                "expected_dedup_publication_revision": 0,
                "initialization_revision": self._config_revision(
                    connection, context.site_id
                ),
                "expected_set_digest": publication_set_digest(members).hex(),
                "existing_job_id": connection.scalar(
                    sa.text(
                        """
                        SELECT id FROM return_dedup_staging_jobs WHERE site_id=:site
                        AND initialization_revision=:revision AND
                        proposed_set_digest=:digest AND status='building' ORDER BY id
                        DESC LIMIT 1
                        """
                    ),
                    {
                        "site": context.site_id,
                        "revision": self._config_revision(connection, context.site_id),
                        "digest": publication_set_digest(members),
                    },
                ),
                "published_return_reports": len(members),
                "coverage_from": members[0].report_date.isoformat(),
                "coverage_to": members[-1].report_date.isoformat(),
            }

    def create_staging(
        self,
        context: CurrentSiteContext,
        command: CreateReturnDedupStaging,
        *,
        occurred_at: datetime,
    ) -> ReturnDedupStagingJob:
        self._require_manager(context)
        operation_digest = command.digest(
            actor_user_id=context.principal_user_id,
            site_id=context.site_id,
        )
        timestamp = _mysql_datetime(occurred_at)
        with self._engine.begin() as connection:
            if command.initialization_revision is not None:
                self._lock_initialization(connection, context.site_id)
            replay = self._job(
                connection, operation_token=command.operation_token, lock=True
            )
            if replay is not None:
                row_digest = connection.scalar(
                    sa.text(
                        "SELECT operation_digest FROM return_dedup_staging_jobs "
                        "WHERE id = :job_id"
                    ),
                    {"job_id": replay.job_id},
                )
                if (
                    replay.site_id != context.site_id
                    or replay.actor_user_id != context.principal_user_id
                    or not hmac.compare_digest(_bytes(row_digest, 32), operation_digest)
                ):
                    raise ReturnDedupIdempotencyConflict()
                return replay
            scope_id = self._lock_scope(connection, site_id=context.site_id)
            members = self._frozen_members(
                connection,
                site_id=context.site_id,
                scope_id=scope_id,
                target_dataset_id=command.dataset_id,
                proposed_version_id=command.proposed_version_id,
                initialization=command.initialization_revision is not None,
            )
            target_revision = connection.scalar(
                sa.text(
                    """
                    SELECT publication_revision
                    FROM report_publication_revisions
                    WHERE dataset_id = :dataset_id AND site_id = :site_id
                      AND report_source_scope_id = :scope_id
                    """
                ),
                {
                    "dataset_id": command.dataset_id,
                    "site_id": context.site_id,
                    "scope_id": scope_id,
                },
            )
            if (
                target_revision is None
                or int(target_revision) != command.expected_publication_revision
            ):
                raise ReturnDedupPublicationRevisionConflict()
            dedup_revision = connection.scalar(
                sa.text(
                    """
                    SELECT dedup_publication_revision
                    FROM return_dedup_publications
                    WHERE site_id = :site_id
                      AND report_source_scope_id = :scope_id
                    FOR UPDATE
                    """
                ),
                {"site_id": context.site_id, "scope_id": scope_id},
            )
            if (
                dedup_revision is None
                or int(dedup_revision) != command.expected_dedup_publication_revision
            ):
                raise ReturnDedupPublicationRevisionConflict()
            set_digest = publication_set_digest(members)
            if command.initialization_revision is not None:
                actual_revision = self._config_revision(connection, context.site_id)
                pointer_id = connection.scalar(
                    sa.text(
                        """
                        SELECT current_snapshot_id FROM return_dedup_publications
                        WHERE site_id=:site AND report_source_scope_id=:scope
                        """
                    ),
                    {"site": context.site_id, "scope": scope_id},
                )
                if (
                    actual_revision != command.initialization_revision
                    or dedup_revision != 0
                    or pointer_id is not None
                    or set_digest != command.expected_set_digest
                ):
                    raise ReturnDedupPublicationRevisionConflict()
            existing = (
                connection.execute(
                    sa.text(
                        f"SELECT {_JOB_COLUMNS} FROM return_dedup_staging_jobs "
                        "WHERE site_id = :site_id AND proposed_set_digest = :digest "
                        "FOR UPDATE"
                    ),
                    {"site_id": context.site_id, "digest": set_digest},
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                existing_job = _job_from_row(existing)
                if (
                    existing_job.operation_token != command.operation_token
                    or existing_job.actor_user_id != context.principal_user_id
                ):
                    raise ReturnDedupStagingConflict()
                return existing_job
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO return_dedup_staging_jobs (
                        site_id, report_source_scope_id, operation_token,
                        operation_digest, actor_user_id, dataset_id,
                        proposed_version_id, proposed_set_digest, rule_version,
                        expected_publication_revision,
                        expected_dedup_publication_revision, status,
                        job_revision, retry_allowed, failure_reason_code,
                        lease_token, fencing_token, lease_expires_at,
                        result_snapshot_id, created_at, updated_at
                        , initialization_revision
                    ) VALUES (
                        :site_id, :scope_id, :operation_token,
                        :operation_digest, :actor_user_id, :dataset_id,
                        :version_id, :set_digest, :rule_version,
                        :publication_revision, :dedup_revision, 'building',
                        0, FALSE, NULL, NULL, 0, NULL, NULL,
                        :created_at, :updated_at, :initialization_revision
                    )
                    """
                ),
                {
                    "site_id": context.site_id,
                    "scope_id": scope_id,
                    "operation_token": command.operation_token.bytes,
                    "operation_digest": operation_digest,
                    "actor_user_id": context.principal_user_id,
                    "dataset_id": command.dataset_id,
                    "version_id": command.proposed_version_id,
                    "set_digest": set_digest,
                    "initialization_revision": command.initialization_revision,
                    "rule_version": RETURN_EVENT_FINGERPRINT_VERSION,
                    "publication_revision": command.expected_publication_revision,
                    "dedup_revision": command.expected_dedup_publication_revision,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
            if inserted.lastrowid is None:
                raise ReturnDedupIntegrityError()
            job_id = int(inserted.lastrowid)
            for index, member in enumerate(members, start=1):
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO return_dedup_staging_members (
                            job_id, dataset_id, published_version_id,
                            publication_revision, version_data_revision,
                            report_date, member_order, created_at
                        ) VALUES (
                            :job_id, :dataset_id, :version_id,
                            :publication_revision, :data_revision,
                            :report_date, :member_order, :created_at
                        )
                        """
                    ),
                    {
                        "job_id": job_id,
                        "dataset_id": member.dataset_id,
                        "version_id": member.published_version_id,
                        "publication_revision": member.publication_revision,
                        "data_revision": member.version_data_revision,
                        "report_date": member.report_date,
                        "member_order": index,
                        "created_at": timestamp,
                    },
                )
            created = self._job(connection, job_id=job_id)
            if created is None:
                raise ReturnDedupIntegrityError()
            return created

    def claim(
        self,
        *,
        job_id: int,
        expected_job_revision: int,
        lease_token: UUID,
        occurred_at: datetime,
        lease_ttl: timedelta,
    ) -> ReturnDedupLease:
        if lease_token.version != 4 or lease_ttl <= timedelta(0):
            raise ValueError("claim requires a UUID v4 token and positive TTL")
        now = _mysql_datetime(occurred_at)
        expires = _mysql_datetime(occurred_at + lease_ttl)
        with self._engine.begin() as connection:
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE return_dedup_staging_jobs
                    SET lease_token = :lease_token,
                        lease_expires_at = :lease_expires_at,
                        fencing_token = fencing_token + 1,
                        job_revision = job_revision + 1,
                        updated_at = :updated_at
                    WHERE id = :job_id
                      AND status = 'building'
                      AND job_revision = :expected_revision
                      AND (lease_token IS NULL OR lease_expires_at <= :now)
                    """
                ),
                {
                    "lease_token": lease_token.bytes,
                    "lease_expires_at": expires,
                    "updated_at": now,
                    "job_id": job_id,
                    "expected_revision": expected_job_revision,
                    "now": now,
                },
            )
            if updated.rowcount != 1:
                raise ReturnDedupJobRevisionConflict()
            job = self._job(connection, job_id=job_id)
            if job is None or job.lease_expires_at is None:
                raise ReturnDedupIntegrityError()
            return ReturnDedupLease(
                job_id=job.job_id,
                job_revision=job.job_revision,
                lease_token=lease_token,
                fencing_token=job.fencing_token,
                lease_expires_at=job.lease_expires_at,
            )

    def renew(
        self,
        lease: ReturnDedupLease,
        *,
        occurred_at: datetime,
        lease_ttl: timedelta,
    ) -> ReturnDedupLease:
        expires = _mysql_datetime(occurred_at + lease_ttl)
        with self._engine.begin() as connection:
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE return_dedup_staging_jobs
                    SET lease_expires_at = :expires_at,
                        job_revision = job_revision + 1,
                        updated_at = :updated_at
                    WHERE id = :job_id AND status = 'building'
                      AND job_revision = :job_revision
                      AND lease_token = :lease_token
                      AND fencing_token = :fencing_token
                      AND lease_expires_at > :updated_at
                    """
                ),
                {
                    "expires_at": expires,
                    "updated_at": _mysql_datetime(occurred_at),
                    "job_id": lease.job_id,
                    "job_revision": lease.job_revision,
                    "lease_token": lease.lease_token.bytes,
                    "fencing_token": lease.fencing_token,
                },
            )
            if updated.rowcount != 1:
                raise ReturnDedupJobRevisionConflict()
        return ReturnDedupLease(
            job_id=lease.job_id,
            job_revision=lease.job_revision + 1,
            lease_token=lease.lease_token,
            fencing_token=lease.fencing_token,
            lease_expires_at=occurred_at + lease_ttl,
        )

    @staticmethod
    def _staging_members(
        connection: Connection, job_id: int
    ) -> tuple[FrozenPublicationMember, ...]:
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT dataset_id, published_version_id,
                           publication_revision, version_data_revision,
                           report_date, member_order
                    FROM return_dedup_staging_members
                    WHERE job_id = :job_id
                    ORDER BY member_order
                    """
                ),
                {"job_id": job_id},
            )
            .mappings()
            .all()
        )
        members = tuple(
            FrozenPublicationMember(
                dataset_id=int(row["dataset_id"]),
                published_version_id=int(row["published_version_id"]),
                publication_revision=int(row["publication_revision"]),
                version_data_revision=int(row["version_data_revision"]),
                report_date=row["report_date"],
            )
            for row in rows
        )
        if not members or publication_set_digest(members) is None:
            raise ReturnDedupIntegrityError()
        return members

    @staticmethod
    def _snapshot_state(
        connection: Connection, snapshot_id: int | None
    ) -> tuple[
        int | None,
        int | None,
        Mapping[bytes, tuple[int, PriorGroupRevision]],
    ]:
        if snapshot_id is None:
            return None, None, {}
        snapshots: list[RowMapping] = []
        current_id: int | None = snapshot_id
        for _depth in range(33):
            if current_id is None:
                break
            row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT id, base_snapshot_id, checkpoint_snapshot_id,
                               delta_depth, snapshot_kind, status
                        FROM return_dedup_snapshots WHERE id = :snapshot_id
                        """
                    ),
                    {"snapshot_id": current_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["status"] != "ready":
                raise ReturnDedupIntegrityError()
            snapshots.append(row)
            if row["snapshot_kind"] == "checkpoint":
                break
            current_id = int(row["base_snapshot_id"])
        else:
            raise ReturnDedupIntegrityError()
        if not snapshots or snapshots[-1]["snapshot_kind"] != "checkpoint":
            raise ReturnDedupIntegrityError()
        state: dict[bytes, tuple[int, PriorGroupRevision]] = {}
        for snapshot in reversed(snapshots):
            entries = (
                connection.execute(
                    sa.text(
                        """
                        SELECT entries.entry_kind, revisions.id,
                               revisions.group_key_sha256, revisions.revision,
                               revisions.member_set_digest, revisions.decision,
                               revisions.canonical_source_key_id
                        FROM return_dedup_snapshot_groups AS entries
                        INNER JOIN return_dedup_group_revisions AS revisions
                            ON revisions.id = entries.group_revision_id
                        WHERE entries.snapshot_id = :snapshot_id
                        ORDER BY entries.id
                        """
                    ),
                    {"snapshot_id": int(snapshot["id"])},
                )
                .mappings()
                .all()
            )
            for entry in entries:
                key = _bytes(entry["group_key_sha256"], 32)
                if entry["entry_kind"] == "remove":
                    state.pop(key, None)
                    continue
                prior = PriorGroupRevision(
                    group_key_sha256=key,
                    revision=int(entry["revision"]),
                    member_set_digest=_bytes(entry["member_set_digest"], 32),
                    decision=str(entry["decision"]),  # type: ignore[arg-type]
                    canonical_source_key_id=(
                        int(entry["canonical_source_key_id"])
                        if entry["canonical_source_key_id"] is not None
                        else None
                    ),
                )
                state[key] = (int(entry["id"]), prior)
        head = snapshots[0]
        checkpoint_id = (
            int(head["id"])
            if head["snapshot_kind"] == "checkpoint"
            else int(head["checkpoint_snapshot_id"])
        )
        return checkpoint_id, int(head["delta_depth"]), state

    def load_frozen_input(self, lease: ReturnDedupLease) -> FrozenReturnDedupInput:
        with self._engine.connect() as connection:
            job = self._job(connection, job_id=lease.job_id)
            if (
                job is None
                or job.status != "building"
                or job.job_revision != lease.job_revision
                or job.lease_token != lease.lease_token
                or job.fencing_token != lease.fencing_token
            ):
                raise ReturnDedupJobRevisionConflict()
            members = self._staging_members(connection, job.job_id)
            if not hmac.compare_digest(
                publication_set_digest(members), job.proposed_set_digest
            ):
                raise ReturnDedupIntegrityError()
            rows = (
                connection.execute(
                    sa.text(
                        """
                        WITH latest_keys AS (
                            SELECT source_keys.*, ROW_NUMBER() OVER (
                                PARTITION BY source_keys.version_id,
                                             source_keys.source_row_id
                                ORDER BY source_keys.source_key_revision DESC,
                                         source_keys.id DESC
                            ) AS key_rank
                            FROM report_source_keys AS source_keys
                            WHERE source_keys.report_type = 'return_report'
                        )
                        SELECT members.dataset_id, members.published_version_id,
                               members.report_date,
                               row_records.id AS active_row_id,
                               current_keys.id AS source_key_id,
                               return_values.return_date,
                               return_values.order_id, return_values.sku,
                               return_values.asin, return_values.fnsku,
                               return_values.product_name, return_values.quantity,
                               return_values.fulfillment_center_id,
                               return_values.detailed_disposition,
                               return_values.reason, return_values.status,
                               return_values.license_plate_number,
                               return_values.customer_comments
                        FROM return_dedup_staging_members AS members
                        INNER JOIN dataset_versions AS versions
                            ON versions.id = members.published_version_id
                           AND versions.dataset_id = members.dataset_id
                           AND versions.data_revision = members.version_data_revision
                        INNER JOIN version_rows AS row_records
                            ON row_records.version_id = versions.id
                           AND row_records.report_type = 'return_report'
                           AND row_records.row_state = 'active'
                        INNER JOIN return_report_rows AS return_values
                            ON return_values.version_id = versions.id
                           AND return_values.version_row_id = row_records.id
                        INNER JOIN latest_keys AS current_keys
                            ON current_keys.version_id = versions.id
                           AND current_keys.source_row_id = row_records.id
                           AND current_keys.key_rank = 1
                        WHERE members.job_id = :job_id
                        ORDER BY members.member_order, row_records.id
                        """
                    ),
                    {"job_id": job.job_id},
                )
                .mappings()
                .all()
            )
            events: list[ReturnEventMember] = []
            from app.catalog.return_dedup import return_event_fingerprint_v1

            for row in rows:
                return_date = row["return_date"]
                if not isinstance(return_date, datetime):
                    raise ReturnDedupIntegrityError()
                try:
                    fields = ReturnEventFields(
                        return_date=return_date.replace(tzinfo=UTC),
                        order_id=row["order_id"],
                        sku=row["sku"],
                        asin=row["asin"],
                        fnsku=row["fnsku"],
                        product_name=row["product_name"],
                        quantity=row["quantity"],
                        fulfillment_center_id=row["fulfillment_center_id"],
                        detailed_disposition=row["detailed_disposition"],
                        reason=row["reason"],
                        status=row["status"],
                        license_plate_number=row["license_plate_number"],
                        customer_comments=row["customer_comments"],
                    )
                except (TypeError, ValueError) as error:
                    raise ReturnDedupIntegrityError() from error
                events.append(
                    ReturnEventMember(
                        report_source_scope_id=job.report_source_scope_id,
                        publication_id=int(row["dataset_id"]),
                        report_date=row["report_date"],
                        dataset_id=int(row["dataset_id"]),
                        published_version_id=int(row["published_version_id"]),
                        active_row_id=int(row["active_row_id"]),
                        source_key_id=int(row["source_key_id"]),
                        fingerprint=return_event_fingerprint_v1(fields).sha256,
                    )
                )
            pointer = (
                connection.execute(
                    sa.text(
                        """
                        SELECT current_snapshot_id, dedup_publication_revision
                        FROM return_dedup_publications
                        WHERE site_id = :site_id
                          AND report_source_scope_id = :scope_id
                        """
                    ),
                    {"site_id": job.site_id, "scope_id": job.report_source_scope_id},
                )
                .mappings()
                .one_or_none()
            )
            if (
                pointer is None
                or int(pointer["dedup_publication_revision"])
                != job.expected_dedup_publication_revision
            ):
                raise ReturnDedupStagingSuperseded()
            snapshot_id = (
                int(pointer["current_snapshot_id"])
                if pointer["current_snapshot_id"] is not None
                else None
            )
            checkpoint_id, delta_depth, previous = self._snapshot_state(
                connection, snapshot_id
            )
            return FrozenReturnDedupInput(
                job=job,
                members=members,
                events=tuple(events),
                previous_snapshot_id=snapshot_id,
                previous_checkpoint_id=checkpoint_id,
                previous_delta_depth=delta_depth,
                previous_groups=previous,
            )

    @staticmethod
    def _assert_lease(job: ReturnDedupStagingJob, lease: ReturnDedupLease) -> None:
        if (
            job.status != "building"
            or job.job_revision != lease.job_revision
            or job.lease_token != lease.lease_token
            or job.fencing_token != lease.fencing_token
        ):
            raise ReturnDedupJobRevisionConflict()

    @staticmethod
    def _current_members_match(
        connection: Connection,
        *,
        job: ReturnDedupStagingJob,
        members: tuple[FrozenPublicationMember, ...],
    ) -> bool:
        try:
            current = MySqlReturnDedupRepository._frozen_members(
                connection,
                site_id=job.site_id,
                scope_id=job.report_source_scope_id,
                target_dataset_id=job.dataset_id,
                proposed_version_id=job.proposed_version_id,
                initialization=job.initialization_revision is not None,
            )
        except ReturnDedupPublicationRevisionConflict, ReturnDedupNotFound:
            return False
        return hmac.compare_digest(
            publication_set_digest(current), publication_set_digest(members)
        )

    @staticmethod
    def _persist_group(
        connection: Connection,
        *,
        job: ReturnDedupStagingJob,
        group: CandidateGroup,
        occurred_at: datetime,
    ) -> int:
        existing = connection.scalar(
            sa.text(
                """
                SELECT id FROM return_dedup_group_revisions
                WHERE site_id = :site_id AND report_source_scope_id = :scope_id
                  AND group_key_sha256 = :group_key AND revision = :revision
                """
            ),
            {
                "site_id": job.site_id,
                "scope_id": job.report_source_scope_id,
                "group_key": group.group_key_sha256,
                "revision": group.revision,
            },
        )
        if existing is not None:
            return int(existing)
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO return_dedup_group_revisions (
                    site_id, report_source_scope_id, group_key_sha256,
                    revision, member_set_digest, decision,
                    canonical_source_key_id, reason_code,
                    decided_by_user_id, created_at
                ) VALUES (
                    :site_id, :scope_id, :group_key, :revision,
                    :member_digest, :decision, :canonical_id,
                    NULL, NULL, :created_at
                )
                """
            ),
            {
                "site_id": job.site_id,
                "scope_id": job.report_source_scope_id,
                "group_key": group.group_key_sha256,
                "revision": group.revision,
                "member_digest": group.member_set_digest,
                "decision": group.decision,
                "canonical_id": group.canonical_source_key_id,
                "created_at": occurred_at,
            },
        )
        if inserted.lastrowid is None:
            raise ReturnDedupIntegrityError()
        revision_id = int(inserted.lastrowid)
        for member_order, member in enumerate(group.members, start=1):
            connection.execute(
                sa.text(
                    """
                    INSERT INTO return_dedup_group_members (
                        group_revision_id, source_key_id, member_order, created_at
                    ) VALUES (
                        :revision_id, :source_key_id, :member_order, :created_at
                    )
                    """
                ),
                {
                    "revision_id": revision_id,
                    "source_key_id": member.source_key_id,
                    "member_order": member_order,
                    "created_at": occurred_at,
                },
            )
        return revision_id

    def complete(
        self,
        lease: ReturnDedupLease,
        *,
        frozen: FrozenReturnDedupInput,
        groups: tuple[CandidateGroup, ...],
        occurred_at: datetime,
    ) -> ReturnDedupStagingJob:
        timestamp = _mysql_datetime(occurred_at)
        with self._engine.begin() as connection:
            if frozen.job.initialization_revision is not None:
                self._lock_initialization(connection, frozen.job.site_id)
            self._lock_scope(connection, site_id=frozen.job.site_id)
            job = self._job(connection, job_id=lease.job_id, lock=True)
            if job is None:
                raise ReturnDedupNotFound()
            self._assert_lease(job, lease)
            pointer = (
                connection.execute(
                    sa.text(
                        """
                        SELECT current_snapshot_id, dedup_publication_revision
                        FROM return_dedup_publications
                        WHERE site_id = :site_id
                          AND report_source_scope_id = :scope_id
                        FOR UPDATE
                        """
                    ),
                    {"site_id": job.site_id, "scope_id": job.report_source_scope_id},
                )
                .mappings()
                .one_or_none()
            )
            if (
                pointer is None
                or int(pointer["dedup_publication_revision"])
                != job.expected_dedup_publication_revision
                or not self._current_members_match(
                    connection, job=job, members=frozen.members
                )
                or (
                    job.initialization_revision is not None
                    and (
                        pointer["current_snapshot_id"] is not None
                        or self._config_revision(connection, job.site_id)
                        != job.initialization_revision
                    )
                )
            ):
                connection.execute(
                    sa.text(
                        """
                        UPDATE return_dedup_staging_jobs
                        SET status = 'superseded', job_revision = job_revision + 1,
                            lease_token = NULL, lease_expires_at = NULL,
                            retry_allowed = FALSE,
                            failure_reason_code = 'publication_revision_changed',
                            updated_at = :updated_at
                        WHERE id = :job_id AND job_revision = :job_revision
                          AND lease_token = :lease_token
                          AND fencing_token = :fencing_token
                        """
                    ),
                    {
                        "updated_at": timestamp,
                        "job_id": lease.job_id,
                        "job_revision": lease.job_revision,
                        "lease_token": lease.lease_token.bytes,
                        "fencing_token": lease.fencing_token,
                    },
                )
                superseded = self._job(connection, job_id=job.job_id)
                if superseded is None:
                    raise ReturnDedupIntegrityError()
                return superseded
            previous_ids = {
                key: revision_id
                for key, (revision_id, _prior) in frozen.previous_groups.items()
            }
            current_ids: dict[bytes, int] = {}
            for group in groups:
                current_ids[group.group_key_sha256] = self._persist_group(
                    connection,
                    job=job,
                    group=group,
                    occurred_at=timestamp,
                )
            plan = plan_snapshot_delta(
                previous_snapshot_id=frozen.previous_snapshot_id,
                previous_checkpoint_id=frozen.previous_checkpoint_id,
                previous_delta_depth=frozen.previous_delta_depth,
                previous_groups=previous_ids,
                current_groups=current_ids,
            )
            decision_digest = hashlib.sha256(
                canonical_json_bytes(
                    [
                        [key.hex(), revision_id]
                        for key, revision_id in sorted(current_ids.items())
                    ]
                )
            ).digest()
            snapshot = connection.execute(
                sa.text(
                    """
                    INSERT INTO return_dedup_snapshots (
                        site_id, report_source_scope_id,
                        return_publication_set_digest, rule_version,
                        base_snapshot_id, checkpoint_snapshot_id, delta_depth,
                        snapshot_kind, status, decision_digest, created_at
                    ) VALUES (
                        :site_id, :scope_id, :set_digest, :rule_version,
                        :base_id, :checkpoint_id, :delta_depth,
                        :snapshot_kind, 'ready', :decision_digest, :created_at
                    )
                    """
                ),
                {
                    "site_id": job.site_id,
                    "scope_id": job.report_source_scope_id,
                    "set_digest": job.proposed_set_digest,
                    "rule_version": RETURN_EVENT_FINGERPRINT_VERSION,
                    "base_id": plan.base_snapshot_id,
                    "checkpoint_id": plan.checkpoint_snapshot_id,
                    "delta_depth": plan.delta_depth,
                    "snapshot_kind": plan.snapshot_kind,
                    "decision_digest": decision_digest,
                    "created_at": timestamp,
                },
            )
            if snapshot.lastrowid is None:
                raise ReturnDedupIntegrityError()
            snapshot_id = int(snapshot.lastrowid)
            for entry in plan.entries:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO return_dedup_snapshot_groups (
                            snapshot_id, group_revision_id, entry_kind, created_at
                        ) VALUES (
                            :snapshot_id, :revision_id, :entry_kind, :created_at
                        )
                        """
                    ),
                    {
                        "snapshot_id": snapshot_id,
                        "revision_id": entry.group_revision_id,
                        "entry_kind": entry.entry_kind,
                        "created_at": timestamp,
                    },
                )
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE return_dedup_staging_jobs
                    SET status = 'ready', job_revision = job_revision + 1,
                        retry_allowed = FALSE, failure_reason_code = NULL,
                        lease_token = NULL, lease_expires_at = NULL,
                        result_snapshot_id = :snapshot_id,
                        updated_at = :updated_at
                    WHERE id = :job_id AND status = 'building'
                      AND job_revision = :job_revision
                      AND lease_token = :lease_token
                      AND fencing_token = :fencing_token
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "updated_at": timestamp,
                    "job_id": lease.job_id,
                    "job_revision": lease.job_revision,
                    "lease_token": lease.lease_token.bytes,
                    "fencing_token": lease.fencing_token,
                },
            )
            if updated.rowcount != 1:
                raise ReturnDedupJobRevisionConflict()
            if job.initialization_revision is not None:
                published = connection.execute(
                    sa.text(
                        """
                        UPDATE return_dedup_publications SET
                        current_snapshot_id=:snapshot, dedup_publication_revision=1,
                        updated_at=:now WHERE site_id=:site AND
                        report_source_scope_id=:scope AND current_snapshot_id IS NULL
                        AND dedup_publication_revision=0
                        """
                    ),
                    {
                        "snapshot": snapshot_id,
                        "now": timestamp,
                        "site": job.site_id,
                        "scope": job.report_source_scope_id,
                    },
                )
                if published.rowcount != 1:
                    raise ReturnDedupPublicationRevisionConflict()
                payload = canonical_json_bytes(
                    {
                        "snapshot_id": snapshot_id,
                        "publication_set_digest": job.proposed_set_digest.hex(),
                        "reports": len(frozen.members),
                        "unresolved_groups": len(groups),
                    }
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO
                        catalog_audit_events(site_id,actor_user_id,event_kind,resource_kind,resource_id,operation_token,safe_payload_json,event_digest,created_at)
                        VALUES(:site,:actor,'catalog.return_snapshot_initialized','return_dedup_snapshot',:snapshot,:token,:payload,:digest,:now)
                        """
                    ),
                    {
                        "site": job.site_id,
                        "actor": job.actor_user_id,
                        "snapshot": snapshot_id,
                        "token": job.operation_token.bytes,
                        "payload": payload.decode(),
                        "digest": hashlib.sha256(payload).digest(),
                        "now": timestamp,
                    },
                )
            result = self._job(connection, job_id=job.job_id)
            if result is None:
                raise ReturnDedupIntegrityError()
            return result

    @staticmethod
    def _group_view(
        connection: Connection,
        *,
        group_key: bytes,
        group_revision_id: int,
    ) -> ReturnDedupGroupView:
        revision = (
            connection.execute(
                sa.text(
                    """
                    SELECT revision, decision, canonical_source_key_id
                    FROM return_dedup_group_revisions
                    WHERE id = :revision_id
                    """
                ),
                {"revision_id": group_revision_id},
            )
            .mappings()
            .one_or_none()
        )
        if revision is None:
            raise ReturnDedupIntegrityError()
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT source_keys.id AS source_key_id,
                           datasets.report_date, source_keys.dataset_id,
                           source_keys.version_id, return_values.sku
                    FROM return_dedup_group_members AS members
                    INNER JOIN report_source_keys AS source_keys
                        ON source_keys.id = members.source_key_id
                    INNER JOIN daily_datasets AS datasets
                        ON datasets.id = source_keys.dataset_id
                    INNER JOIN return_report_rows AS return_values
                        ON return_values.version_id = source_keys.version_id
                       AND return_values.version_row_id = source_keys.source_row_id
                    WHERE members.group_revision_id = :revision_id
                    ORDER BY members.member_order
                    """
                ),
                {"revision_id": group_revision_id},
            )
            .mappings()
            .all()
        )
        if len(rows) < 2:
            raise ReturnDedupIntegrityError()
        members = tuple(
            ReturnDedupGroupMemberView(
                source_key_id=int(row["source_key_id"]),
                source_ref=make_safe_source_ref(
                    source_ref_id=f"return_source_key:{int(row['source_key_id'])}",
                    raw_value=str(row["sku"]),
                    source_kind=CatalogSourceKind.SELLER_SKU,
                ),
                report_date=row["report_date"],
                dataset_id=int(row["dataset_id"]),
                published_version_id=int(row["version_id"]),
            )
            for row in rows
        )
        return ReturnDedupGroupView(
            group_id=group_key.hex(),
            group_revision=int(revision["revision"]),
            decision=revision["decision"],
            canonical_member_id=(
                int(revision["canonical_source_key_id"])
                if revision["canonical_source_key_id"] is not None
                else None
            ),
            member_count=len(members),
            members=members,
        )

    def list_groups(
        self,
        context: CurrentSiteContext,
        *,
        status: Literal["unresolved", "resolved", "all"],
        page: int,
        page_size: int,
    ) -> ReturnDedupGroupPage:
        self._require_manager(context)
        if status not in {"unresolved", "resolved", "all"}:
            raise ValueError("unsupported group status")
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("group pagination is invalid")
        with self._engine.connect() as connection:
            scope_id = self._lock_scope(connection, site_id=context.site_id)
            pointer = (
                connection.execute(
                    sa.text(
                        """
                        SELECT current_snapshot_id, dedup_publication_revision
                        FROM return_dedup_publications
                        WHERE site_id = :site_id
                          AND report_source_scope_id = :scope_id
                        """
                    ),
                    {"site_id": context.site_id, "scope_id": scope_id},
                )
                .mappings()
                .one_or_none()
            )
            if pointer is None or pointer["current_snapshot_id"] is None:
                raise ReturnDedupStagingNotReady()
            snapshot_id = int(pointer["current_snapshot_id"])
            _checkpoint, _depth, state = self._snapshot_state(connection, snapshot_id)
            items = sorted(state.items())
            if status == "unresolved":
                items = [item for item in items if item[1][1].decision == "unresolved"]
            elif status == "resolved":
                items = [item for item in items if item[1][1].decision != "unresolved"]
            total = len(items)
            start = (page - 1) * page_size
            selected = items[start : start + page_size]
            groups = tuple(
                self._group_view(
                    connection,
                    group_key=key,
                    group_revision_id=revision_id,
                )
                for key, (revision_id, _prior) in selected
            )
            return ReturnDedupGroupPage(
                dedup_publication_revision=int(pointer["dedup_publication_revision"]),
                snapshot_id=snapshot_id,
                page=page,
                page_size=page_size,
                total_items=total,
                groups=groups,
            )

    @staticmethod
    def _decision_result(value: object) -> ReturnDedupDecisionResult:
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ReturnDedupIntegrityError()
        try:
            decision = value["decision"]
            if decision not in {"confirmed_distinct", "duplicate_of"}:
                raise ValueError
            return ReturnDedupDecisionResult(
                group_id=str(value["group_id"]),
                group_revision=int(value["group_revision"]),
                dedup_publication_revision=int(value["dedup_publication_revision"]),
                snapshot_id=int(value["snapshot_id"]),
                decision=decision,
                canonical_member_id=(
                    int(value["canonical_member_id"])
                    if value["canonical_member_id"] is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ReturnDedupIntegrityError() from error

    @staticmethod
    def _recover_decision(
        connection: Connection,
        *,
        context: CurrentSiteContext,
        command: DecideReturnDedupGroup,
        operation_digest: bytes,
    ) -> ReturnDedupDecisionResult | None:
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT claims.operation_kind, claims.operation_digest,
                           claims.site_id, claims.actor_user_id,
                           effects.safe_result_json
                    FROM catalog_command_claims AS claims
                    LEFT JOIN catalog_command_effects AS effects
                        ON effects.operation_token = claims.operation_token
                    WHERE claims.operation_token = :operation_token
                    """
                ),
                {"operation_token": command.operation_token.bytes},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        if (
            row["operation_kind"] != "return_dedup_decision"
            or int(row["site_id"]) != context.site_id
            or int(row["actor_user_id"]) != context.principal_user_id
            or not hmac.compare_digest(
                _bytes(row["operation_digest"], 32), operation_digest
            )
        ):
            raise ReturnDedupIdempotencyConflict()
        if row["safe_result_json"] is None:
            raise ReturnDedupIntegrityError()
        return MySqlReturnDedupRepository._decision_result(row["safe_result_json"])

    def decide_group(
        self,
        context: CurrentSiteContext,
        command: DecideReturnDedupGroup,
        *,
        occurred_at: datetime,
    ) -> ReturnDedupDecisionResult:
        self._require_manager(context)
        operation_digest = command.digest(
            actor_user_id=context.principal_user_id,
            site_id=context.site_id,
        )
        timestamp = _mysql_datetime(occurred_at)
        with self._engine.connect() as connection:
            recovered = self._recover_decision(
                connection,
                context=context,
                command=command,
                operation_digest=operation_digest,
            )
        if recovered is not None:
            return recovered

        group_key = bytes.fromhex(command.group_id)
        with self._engine.begin() as connection:
            scope_id = self._lock_scope(connection, site_id=context.site_id)
            pointer = (
                connection.execute(
                    sa.text(
                        """
                        SELECT current_snapshot_id, dedup_publication_revision
                        FROM return_dedup_publications
                        WHERE site_id = :site_id
                          AND report_source_scope_id = :scope_id
                        """
                    ),
                    {"site_id": context.site_id, "scope_id": scope_id},
                )
                .mappings()
                .one_or_none()
            )
            if pointer is None or pointer["current_snapshot_id"] is None:
                raise ReturnDedupStagingNotReady()
            base_snapshot_id = int(pointer["current_snapshot_id"])
            if (
                int(pointer["dedup_publication_revision"])
                != command.expected_dedup_publication_revision
            ):
                raise ReturnDedupPublicationRevisionConflict()
            checkpoint_id, depth, state = self._snapshot_state(
                connection, base_snapshot_id
            )
            current = state.get(group_key)
            if (
                current is None
                or current[1].revision != command.expected_group_revision
            ):
                raise ReturnDedupPublicationRevisionConflict()
            current_revision_id, current_group = current
            member_rows = (
                connection.execute(
                    sa.text(
                        """
                    SELECT source_key_id, member_order
                    FROM return_dedup_group_members
                    WHERE group_revision_id = :revision_id
                    ORDER BY member_order
                    """
                    ),
                    {"revision_id": current_revision_id},
                )
                .mappings()
                .all()
            )
            member_ids = frozenset(int(row["source_key_id"]) for row in member_rows)
            canonical_targets: dict[int, int] = {}
            for _key, (revision_id, prior) in state.items():
                if (
                    prior.decision != "duplicate_of"
                    or prior.canonical_source_key_id is None
                ):
                    continue
                for source_key_id in connection.scalars(
                    sa.text(
                        "SELECT source_key_id FROM return_dedup_group_members "
                        "WHERE group_revision_id = :revision_id"
                    ),
                    {"revision_id": revision_id},
                ):
                    member_id = int(source_key_id)
                    if member_id != prior.canonical_source_key_id:
                        canonical_targets[member_id] = prior.canonical_source_key_id
            try:
                validate_duplicate_decision(
                    decision=command.decision,
                    canonical_source_key_id=command.canonical_member_id,
                    member_source_key_ids=member_ids,
                    canonical_targets=canonical_targets,
                )
            except ValueError as error:
                raise ReturnDedupDecisionInvalid() from error
            next_revision = current_group.revision + 1
            existing_revision = connection.scalar(
                sa.text(
                    """
                    SELECT id FROM return_dedup_group_revisions
                    WHERE site_id = :site_id
                      AND report_source_scope_id = :scope_id
                      AND group_key_sha256 = :group_key
                      AND revision = :revision
                    """
                ),
                {
                    "site_id": context.site_id,
                    "scope_id": scope_id,
                    "group_key": group_key,
                    "revision": next_revision,
                },
            )
            if existing_revision is None:
                inserted = connection.execute(
                    sa.text(
                        """
                        INSERT INTO return_dedup_group_revisions (
                            site_id, report_source_scope_id, group_key_sha256,
                            revision, member_set_digest, decision,
                            canonical_source_key_id, reason_code,
                            decided_by_user_id, created_at
                        ) VALUES (
                            :site_id, :scope_id, :group_key, :revision,
                            :member_digest, :decision, :canonical_id,
                            'manual_decision', :actor_user_id, :created_at
                        )
                        """
                    ),
                    {
                        "site_id": context.site_id,
                        "scope_id": scope_id,
                        "group_key": group_key,
                        "revision": next_revision,
                        "member_digest": current_group.member_set_digest,
                        "decision": command.decision,
                        "canonical_id": command.canonical_member_id,
                        "actor_user_id": context.principal_user_id,
                        "created_at": timestamp,
                    },
                )
                if inserted.lastrowid is None:
                    raise ReturnDedupIntegrityError()
                next_revision_id = int(inserted.lastrowid)
                for member in member_rows:
                    connection.execute(
                        sa.text(
                            """
                            INSERT INTO return_dedup_group_members (
                                group_revision_id, source_key_id,
                                member_order, created_at
                            ) VALUES (
                                :revision_id, :source_key_id,
                                :member_order, :created_at
                            )
                            """
                        ),
                        {
                            "revision_id": next_revision_id,
                            "source_key_id": int(member["source_key_id"]),
                            "member_order": int(member["member_order"]),
                            "created_at": timestamp,
                        },
                    )
            else:
                next_revision_id = int(existing_revision)
            next_groups = {
                key: revision_id for key, (revision_id, _prior) in state.items()
            }
            next_groups[group_key] = next_revision_id
            plan = plan_snapshot_delta(
                previous_snapshot_id=base_snapshot_id,
                previous_checkpoint_id=checkpoint_id,
                previous_delta_depth=depth,
                previous_groups={
                    key: revision_id for key, (revision_id, _prior) in state.items()
                },
                current_groups=next_groups,
            )
            decision_digest = hashlib.sha256(
                canonical_json_bytes(
                    [
                        [key.hex(), revision_id]
                        for key, revision_id in sorted(next_groups.items())
                    ]
                )
            ).digest()
            base_snapshot = (
                connection.execute(
                    sa.text(
                        """
                    SELECT return_publication_set_digest, rule_version
                    FROM return_dedup_snapshots
                    WHERE id = :snapshot_id AND status = 'ready'
                    """
                    ),
                    {"snapshot_id": base_snapshot_id},
                )
                .mappings()
                .one_or_none()
            )
            if base_snapshot is None:
                raise ReturnDedupIntegrityError()
            inserted_snapshot = connection.execute(
                sa.text(
                    """
                    INSERT INTO return_dedup_snapshots (
                        site_id, report_source_scope_id,
                        return_publication_set_digest, rule_version,
                        base_snapshot_id, checkpoint_snapshot_id, delta_depth,
                        snapshot_kind, status, decision_digest, created_at
                    ) VALUES (
                        :site_id, :scope_id, :set_digest, :rule_version,
                        :base_id, :checkpoint_id, :delta_depth,
                        :snapshot_kind, 'ready', :decision_digest, :created_at
                    )
                    """
                ),
                {
                    "site_id": context.site_id,
                    "scope_id": scope_id,
                    "set_digest": base_snapshot["return_publication_set_digest"],
                    "rule_version": base_snapshot["rule_version"],
                    "base_id": plan.base_snapshot_id,
                    "checkpoint_id": plan.checkpoint_snapshot_id,
                    "delta_depth": plan.delta_depth,
                    "snapshot_kind": plan.snapshot_kind,
                    "decision_digest": decision_digest,
                    "created_at": timestamp,
                },
            )
            if inserted_snapshot.lastrowid is None:
                raise ReturnDedupIntegrityError()
            next_snapshot_id = int(inserted_snapshot.lastrowid)
            for entry in plan.entries:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO return_dedup_snapshot_groups (
                            snapshot_id, group_revision_id, entry_kind, created_at
                        ) VALUES (
                            :snapshot_id, :revision_id, :entry_kind, :created_at
                        )
                        """
                    ),
                    {
                        "snapshot_id": next_snapshot_id,
                        "revision_id": entry.group_revision_id,
                        "entry_kind": entry.entry_kind,
                        "created_at": timestamp,
                    },
                )

        result = ReturnDedupDecisionResult(
            group_id=command.group_id,
            group_revision=next_revision,
            dedup_publication_revision=command.expected_dedup_publication_revision + 1,
            snapshot_id=next_snapshot_id,
            decision=command.decision,
            canonical_member_id=command.canonical_member_id,
        )
        safe_result: dict[str, Any] = {
            "canonical_member_id": result.canonical_member_id,
            "decision": result.decision,
            "dedup_publication_revision": result.dedup_publication_revision,
            "group_id": result.group_id,
            "group_revision": result.group_revision,
            "snapshot_id": result.snapshot_id,
        }
        safe_result_json = canonical_json_bytes(safe_result).decode("utf-8")
        with self._engine.begin() as connection:
            recovered = self._recover_decision(
                connection,
                context=context,
                command=command,
                operation_digest=operation_digest,
            )
            if recovered is not None:
                return recovered
            scope_id = self._lock_scope(connection, site_id=context.site_id)
            pointer = (
                connection.execute(
                    sa.text(
                        """
                    SELECT current_snapshot_id, dedup_publication_revision
                    FROM return_dedup_publications
                    WHERE site_id = :site_id
                      AND report_source_scope_id = :scope_id
                    FOR UPDATE
                    """
                    ),
                    {"site_id": context.site_id, "scope_id": scope_id},
                )
                .mappings()
                .one_or_none()
            )
            if (
                pointer is None
                or int(pointer["dedup_publication_revision"])
                != command.expected_dedup_publication_revision
                or int(pointer["current_snapshot_id"] or 0) != base_snapshot_id
            ):
                raise ReturnDedupPublicationRevisionConflict()
            _checkpoint, _depth, current_state = self._snapshot_state(
                connection, base_snapshot_id
            )
            pointer_group = current_state.get(group_key)
            if (
                pointer_group is None
                or pointer_group[1].revision != command.expected_group_revision
            ):
                raise ReturnDedupPublicationRevisionConflict()
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_command_claims (
                        operation_token, operation_kind, operation_digest,
                        site_id, actor_user_id, resource_kind, resource_id,
                        status, created_at
                    ) VALUES (
                        :operation_token, 'return_dedup_decision',
                        :operation_digest, :site_id, :actor_user_id,
                        'return_dedup_group', :resource_id,
                        'completed', :created_at
                    )
                    """
                ),
                {
                    "operation_token": command.operation_token.bytes,
                    "operation_digest": operation_digest,
                    "site_id": context.site_id,
                    "actor_user_id": context.principal_user_id,
                    "resource_id": pointer_group[0],
                    "created_at": timestamp,
                },
            )
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE return_dedup_publications
                    SET current_snapshot_id = :snapshot_id,
                        dedup_publication_revision =
                            dedup_publication_revision + 1,
                        updated_at = :updated_at
                    WHERE site_id = :site_id
                      AND report_source_scope_id = :scope_id
                      AND current_snapshot_id = :base_snapshot_id
                      AND dedup_publication_revision = :expected_revision
                    """
                ),
                {
                    "snapshot_id": next_snapshot_id,
                    "updated_at": timestamp,
                    "site_id": context.site_id,
                    "scope_id": scope_id,
                    "base_snapshot_id": base_snapshot_id,
                    "expected_revision": command.expected_dedup_publication_revision,
                },
            )
            if updated.rowcount != 1:
                raise ReturnDedupPublicationRevisionConflict()
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_command_effects (
                        operation_token, operation_kind, operation_digest,
                        site_id, actor_user_id, response_schema_version,
                        response_status_code, safe_result_json, completed_at
                    ) VALUES (
                        :operation_token, 'return_dedup_decision',
                        :operation_digest, :site_id, :actor_user_id,
                        1, 200, :safe_result_json, :completed_at
                    )
                    """
                ),
                {
                    "operation_token": command.operation_token.bytes,
                    "operation_digest": operation_digest,
                    "site_id": context.site_id,
                    "actor_user_id": context.principal_user_id,
                    "safe_result_json": safe_result_json,
                    "completed_at": timestamp,
                },
            )
            audit_payload = {
                **safe_result,
                "reason": command.reason,
            }
            audit_bytes = canonical_json_bytes(audit_payload)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_audit_events (
                        site_id, actor_user_id, event_kind, resource_kind,
                        resource_id, operation_token, safe_payload_json,
                        event_digest, created_at
                    ) VALUES (
                        :site_id, :actor_user_id, 'return_dedup_decided',
                        'return_dedup_group', :resource_id,
                        :operation_token, :safe_payload_json,
                        :event_digest, :created_at
                    )
                    """
                ),
                {
                    "site_id": context.site_id,
                    "actor_user_id": context.principal_user_id,
                    "resource_id": next_revision_id,
                    "operation_token": command.operation_token.bytes,
                    "safe_payload_json": audit_bytes.decode("utf-8"),
                    "event_digest": hashlib.sha256(audit_bytes).digest(),
                    "created_at": timestamp,
                },
            )
        return result

    def fail(
        self,
        lease: ReturnDedupLease,
        *,
        reason_code: str,
        retry_allowed: bool,
        occurred_at: datetime,
    ) -> ReturnDedupStagingJob:
        if not reason_code or len(reason_code) > 64 or not reason_code.isascii():
            raise ValueError("failure reason must be a safe ASCII code")
        with self._engine.begin() as connection:
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE return_dedup_staging_jobs
                    SET status = 'failed', job_revision = job_revision + 1,
                        retry_allowed = :retry_allowed,
                        failure_reason_code = :reason_code,
                        lease_token = NULL, lease_expires_at = NULL,
                        updated_at = :updated_at
                    WHERE id = :job_id AND status = 'building'
                      AND job_revision = :job_revision
                      AND lease_token = :lease_token
                      AND fencing_token = :fencing_token
                    """
                ),
                {
                    "retry_allowed": retry_allowed,
                    "reason_code": reason_code,
                    "updated_at": _mysql_datetime(occurred_at),
                    "job_id": lease.job_id,
                    "job_revision": lease.job_revision,
                    "lease_token": lease.lease_token.bytes,
                    "fencing_token": lease.fencing_token,
                },
            )
            if updated.rowcount != 1:
                raise ReturnDedupJobRevisionConflict()
            job = self._job(connection, job_id=lease.job_id)
            if job is None:
                raise ReturnDedupIntegrityError()
            return job


def build_frozen_groups(
    frozen: FrozenReturnDedupInput,
) -> tuple[CandidateGroup, ...]:
    return build_candidate_groups(
        frozen.events,
        previous={
            key: prior for key, (_identity, prior) in frozen.previous_groups.items()
        },
    )


__all__ = (
    "CreateReturnDedupStaging",
    "FrozenPublicationMember",
    "FrozenReturnDedupInput",
    "MySqlReturnDedupRepository",
    "RetryReturnDedupStaging",
    "ReturnDedupDecisionInvalid",
    "ReturnDedupError",
    "ReturnDedupIdempotencyConflict",
    "ReturnDedupIntegrityError",
    "ReturnDedupJobRevisionConflict",
    "ReturnDedupLease",
    "ReturnDedupNotFound",
    "ReturnDedupPermissionDenied",
    "ReturnDedupPublicationRevisionConflict",
    "ReturnDedupStagingFailed",
    "ReturnDedupStagingJob",
    "ReturnDedupStagingNotReady",
    "ReturnDedupStagingSuperseded",
    "build_frozen_groups",
    "publication_set_digest",
)
