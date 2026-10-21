"""Pure ordering and retry-policy boundaries shared by publication adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.catalog.return_dedup_repository import (
    FrozenPublicationMember,
    ReturnDedupIntegrityError,
    ReturnDedupStagingFailed,
    ReturnDedupStagingNotReady,
    ReturnDedupStagingSuperseded,
    publication_set_digest,
)

from ._common import positive


def ordered_dataset_ids(dataset_ids: Iterable[int]) -> tuple[int, ...]:
    """Return the only permitted dataset-lock order for a command."""

    identities = tuple(dataset_ids)
    if not identities:
        raise ValueError("at least one dataset ID is required")
    for identity in identities:
        positive(identity, "dataset_id")
    return tuple(sorted(set(identities)))


@dataclass(frozen=True, slots=True)
class ReturnPublicationGuard:
    site_id: int
    report_source_scope_id: int
    snapshot_id: int
    expected_dedup_revision: int
    affected_revisions: tuple[tuple[int, int], ...]


def _database_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ReturnDedupIntegrityError()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if value.utcoffset() is None:
        raise ReturnDedupIntegrityError()
    return value.astimezone(UTC)


def lock_return_publication_guard(
    connection: Connection,
    *,
    operation_token: UUID,
    proposed_versions: Mapping[int, int | None],
) -> ReturnPublicationGuard | None:
    """Lock and validate the staged return set before publication mutation."""

    dataset_ids = ordered_dataset_ids(proposed_versions)
    datasets = (
        connection.execute(
            sa.text(
                """
                SELECT datasets.id, datasets.site_id, datasets.report_type,
                       assignments.report_source_scope_id
                FROM daily_datasets AS datasets
                LEFT JOIN report_dataset_scope_assignments AS assignments
                    ON assignments.dataset_id = datasets.id
                   AND assignments.site_id = datasets.site_id
                WHERE datasets.id IN :dataset_ids
                ORDER BY datasets.id
                """
            ).bindparams(sa.bindparam("dataset_ids", expanding=True)),
            {"dataset_ids": dataset_ids},
        )
        .mappings()
        .all()
    )
    if len(datasets) != len(dataset_ids):
        raise ReturnDedupIntegrityError()
    if all(row["report_type"] != "return_report" for row in datasets):
        return None
    if any(row["report_type"] != "return_report" for row in datasets):
        raise ReturnDedupIntegrityError()
    site_ids = {int(row["site_id"]) for row in datasets}
    scope_ids = {
        int(row["report_source_scope_id"])
        for row in datasets
        if row["report_source_scope_id"] is not None
    }
    if not scope_ids:
        return None
    if len(site_ids) != 1 or len(scope_ids) != 1:
        raise ReturnDedupIntegrityError()
    site_id = next(iter(site_ids))
    scope_id = next(iter(scope_ids))

    # This range lock is the site-return synchronization boundary. Every
    # return publication path acquires it before dataset pointer locks.
    revision_rows = (
        connection.execute(
            sa.text(
                """
                SELECT dataset_id, publication_revision
                FROM report_publication_revisions
                WHERE site_id = :site_id
                  AND report_source_scope_id = :scope_id
                ORDER BY dataset_id
                FOR UPDATE
                """
            ),
            {"site_id": site_id, "scope_id": scope_id},
        )
        .mappings()
        .all()
    )
    revisions = {
        int(row["dataset_id"]): int(row["publication_revision"])
        for row in revision_rows
    }
    if any(dataset_id not in revisions for dataset_id in dataset_ids):
        raise ReturnDedupIntegrityError()

    job = (
        connection.execute(
            sa.text(
                """
                SELECT id, site_id, report_source_scope_id, status,
                       proposed_set_digest,
                       expected_dedup_publication_revision,
                       result_snapshot_id
                FROM return_dedup_staging_jobs
                WHERE operation_token = :operation_token
                FOR UPDATE
                """
            ),
            {"operation_token": operation_token.bytes},
        )
        .mappings()
        .one_or_none()
    )
    if job is None:
        raise ReturnDedupStagingNotReady()
    if int(job["site_id"]) != site_id or int(job["report_source_scope_id"]) != scope_id:
        raise ReturnDedupIntegrityError()
    if job["status"] == "failed":
        raise ReturnDedupStagingFailed()
    if job["status"] == "superseded":
        raise ReturnDedupStagingSuperseded()
    if job["status"] != "ready" or job["result_snapshot_id"] is None:
        raise ReturnDedupStagingNotReady()

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
            {"site_id": site_id, "scope_id": scope_id},
        )
        .mappings()
        .one_or_none()
    )
    if pointer is None:
        raise ReturnDedupIntegrityError()
    expected_dedup_revision = int(job["expected_dedup_publication_revision"])
    if int(pointer["dedup_publication_revision"]) != expected_dedup_revision:
        raise ReturnDedupStagingSuperseded()
    snapshot = (
        connection.execute(
            sa.text(
                """
                SELECT return_publication_set_digest, rule_version,
                       delta_depth, status
                FROM return_dedup_snapshots
                WHERE id = :snapshot_id AND site_id = :site_id
                  AND report_source_scope_id = :scope_id
                """
            ),
            {
                "snapshot_id": int(job["result_snapshot_id"]),
                "site_id": site_id,
                "scope_id": scope_id,
            },
        )
        .mappings()
        .one_or_none()
    )
    if (
        snapshot is None
        or snapshot["status"] != "ready"
        or snapshot["rule_version"] != "return_event_fingerprint_v1"
        or int(snapshot["delta_depth"]) > 31
    ):
        raise ReturnDedupIntegrityError()

    rows = (
        connection.execute(
            sa.text(
                """
                SELECT datasets.id AS dataset_id, datasets.report_date,
                       publications.version_id, versions.data_revision
                FROM daily_datasets AS datasets
                INNER JOIN report_dataset_scope_assignments AS assignments
                    ON assignments.dataset_id = datasets.id
                   AND assignments.site_id = datasets.site_id
                INNER JOIN dataset_publications AS publications
                    ON publications.dataset_id = datasets.id
                INNER JOIN dataset_versions AS versions
                    ON versions.id = publications.version_id
                   AND versions.dataset_id = datasets.id
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
    current = {
        int(row["dataset_id"]): FrozenPublicationMember(
            dataset_id=int(row["dataset_id"]),
            published_version_id=int(row["version_id"]),
            publication_revision=revisions[int(row["dataset_id"])],
            version_data_revision=int(row["data_revision"]),
            report_date=row["report_date"],
        )
        for row in rows
    }
    for dataset_id, version_id in proposed_versions.items():
        if version_id is None:
            current.pop(dataset_id, None)
            continue
        version = (
            connection.execute(
                sa.text(
                    """
                    SELECT datasets.report_date, versions.data_revision
                    FROM daily_datasets AS datasets
                    INNER JOIN dataset_versions AS versions
                        ON versions.dataset_id = datasets.id
                       AND versions.report_type = datasets.report_type
                    WHERE datasets.id = :dataset_id
                      AND versions.id = :version_id
                      AND datasets.site_id = :site_id
                      AND datasets.report_type = 'return_report'
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                    "site_id": site_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        if version is None:
            raise ReturnDedupIntegrityError()
        current[dataset_id] = FrozenPublicationMember(
            dataset_id=dataset_id,
            published_version_id=version_id,
            # The guard validates the state that will exist after the same
            # transaction advances the affected publication revisions.
            publication_revision=revisions[dataset_id] + 1,
            version_data_revision=int(version["data_revision"]),
            report_date=version["report_date"],
        )
    proposed_digest = publication_set_digest(tuple(current.values()))
    job_digest = bytes(job["proposed_set_digest"])
    snapshot_digest = bytes(snapshot["return_publication_set_digest"])
    if proposed_digest != job_digest or proposed_digest != snapshot_digest:
        raise ReturnDedupStagingSuperseded()
    return ReturnPublicationGuard(
        site_id=site_id,
        report_source_scope_id=scope_id,
        snapshot_id=int(job["result_snapshot_id"]),
        expected_dedup_revision=expected_dedup_revision,
        affected_revisions=tuple(
            (dataset_id, revisions[dataset_id]) for dataset_id in dataset_ids
        ),
    )


def advance_return_publication_guard(
    connection: Connection,
    guard: ReturnPublicationGuard | None,
    *,
    occurred_at: datetime,
) -> None:
    if guard is None:
        return
    timestamp = _database_utc(occurred_at).replace(tzinfo=None)
    for dataset_id, expected_revision in guard.affected_revisions:
        updated = connection.execute(
            sa.text(
                """
                UPDATE report_publication_revisions
                SET publication_revision = publication_revision + 1,
                    updated_at = :updated_at
                WHERE dataset_id = :dataset_id
                  AND publication_revision = :expected_revision
                """
            ),
            {
                "updated_at": timestamp,
                "dataset_id": dataset_id,
                "expected_revision": expected_revision,
            },
        )
        if updated.rowcount != 1:
            raise ReturnDedupStagingSuperseded()
    updated_pointer = connection.execute(
        sa.text(
            """
            UPDATE return_dedup_publications
            SET current_snapshot_id = :snapshot_id,
                dedup_publication_revision = dedup_publication_revision + 1,
                updated_at = :updated_at
            WHERE site_id = :site_id
              AND report_source_scope_id = :scope_id
              AND dedup_publication_revision = :expected_revision
            """
        ),
        {
            "snapshot_id": guard.snapshot_id,
            "updated_at": timestamp,
            "site_id": guard.site_id,
            "scope_id": guard.report_source_scope_id,
            "expected_revision": guard.expected_dedup_revision,
        },
    )
    if updated_pointer.rowcount != 1:
        raise ReturnDedupStagingSuperseded()


@dataclass(frozen=True, slots=True)
class MySqlTransactionRetryPolicy:
    """Bound full-transaction replay without owning connections or sleeping."""

    max_attempts: int = field(default=4, init=False)
    retryable_error_codes: frozenset[int] = field(
        default_factory=lambda: frozenset({1205, 1213}),
        init=False,
    )

    def should_retry(
        self,
        error_code: int | None,
        failed_attempt: int,
        *,
        connection_invalidated: bool = False,
    ) -> bool:
        if failed_attempt < 1 or failed_attempt > self.max_attempts:
            raise ValueError(
                f"failed_attempt must be between 1 and {self.max_attempts}"
            )
        return (
            not connection_invalidated
            and error_code in self.retryable_error_codes
            and failed_attempt < self.max_attempts
        )
