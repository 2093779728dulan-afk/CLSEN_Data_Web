"""Fail-closed read models for administrator publication recovery actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, cast

import sqlalchemy as sa
from sqlalchemy.orm import Session

type ReportType = Literal["business_report", "return_report"]


@dataclass(frozen=True, slots=True)
class PublicationPointerSnapshot:
    version_id: int | None
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class UndoablePublishedMove:
    move_command_id: int
    source_dataset_id: int
    source_report_date: date
    restore_source_version_id: int
    source_current_publication: PublicationPointerSnapshot
    target_dataset_id: int
    target_report_date: date
    restore_target_version_id: int | None
    target_current_publication: PublicationPointerSnapshot
    moved_target_version_id: int
    completed_at: datetime
    report_type: ReportType


_UNDOABLE_PUBLISHED_MOVES = sa.text(
    """
    WITH move_event_sets AS (
        SELECT events.command_id,
               COUNT(*) AS event_count,
               SUM(events.event_type = 'moved_out') AS moved_out_count,
               SUM(events.event_type = 'moved_in') AS moved_in_count,
               MAX(CASE WHEN events.event_type = 'moved_out'
                        THEN events.id END) AS moved_out_event_id,
               MAX(CASE WHEN events.event_type = 'moved_in'
                        THEN events.id END) AS moved_in_event_id,
               MAX(CASE WHEN events.event_type = 'moved_out'
                        THEN events.sequence_number END) AS moved_out_sequence,
               MAX(CASE WHEN events.event_type = 'moved_in'
                        THEN events.sequence_number END) AS moved_in_sequence,
               MAX(CASE WHEN events.event_type = 'moved_out'
                        THEN events.dataset_id END) AS source_dataset_id,
               MAX(CASE WHEN events.event_type = 'moved_out'
                        THEN events.peer_dataset_id END) AS source_peer_dataset_id,
               MAX(CASE WHEN events.event_type = 'moved_out'
                        THEN events.previous_version_id END)
                   AS restore_source_version_id,
               MAX(CASE WHEN events.event_type = 'moved_out'
                        THEN events.next_version_id END)
                   AS source_next_version_id,
               MAX(CASE WHEN events.event_type = 'moved_out'
                        THEN events.occurred_at END) AS moved_out_at,
               MAX(CASE WHEN events.event_type = 'moved_in'
                        THEN events.dataset_id END) AS target_dataset_id,
               MAX(CASE WHEN events.event_type = 'moved_in'
                        THEN events.peer_dataset_id END) AS target_peer_dataset_id,
               MAX(CASE WHEN events.event_type = 'moved_in'
                        THEN events.previous_version_id END)
                   AS restore_target_version_id,
               MAX(CASE WHEN events.event_type = 'moved_in'
                        THEN events.next_version_id END)
                   AS moved_target_version_id,
               MAX(CASE WHEN events.event_type = 'moved_in'
                        THEN events.occurred_at END) AS moved_in_at
        FROM publication_events AS events
        GROUP BY events.command_id
        HAVING COUNT(*) = 2
           AND SUM(events.event_type = 'moved_out') = 1
           AND SUM(events.event_type = 'moved_in') = 1
    )
    SELECT results.command_id AS move_command_id,
           event_sets.source_dataset_id,
           source_datasets.report_date AS source_report_date,
           event_sets.restore_source_version_id,
           event_sets.target_dataset_id,
           target_datasets.report_date AS target_report_date,
           event_sets.restore_target_version_id,
           target_publications.version_id AS target_publication_version_id,
           target_publications.published_at AS target_published_at,
           event_sets.moved_target_version_id,
           results.completed_at,
           source_datasets.report_type
    FROM publication_command_results AS results
    INNER JOIN publication_commands AS commands
        ON commands.id = results.command_id
       AND commands.operation_token = results.operation_token
       AND commands.operation_kind = results.operation_kind
       AND commands.operation_digest = results.operation_digest
       AND commands.actor_user_id = results.actor_user_id
    INNER JOIN move_event_sets AS event_sets
        ON event_sets.command_id = results.command_id
    INNER JOIN daily_datasets AS source_datasets
        ON source_datasets.id = event_sets.source_dataset_id
    INNER JOIN daily_datasets AS target_datasets
        ON target_datasets.id = event_sets.target_dataset_id
    INNER JOIN dataset_versions AS source_versions
        ON source_versions.dataset_id = event_sets.source_dataset_id
       AND source_versions.id = event_sets.restore_source_version_id
       AND source_versions.report_type = source_datasets.report_type
       AND source_versions.status = 'published'
    INNER JOIN dataset_versions AS moved_target_versions
        ON moved_target_versions.dataset_id = event_sets.target_dataset_id
       AND moved_target_versions.id = event_sets.moved_target_version_id
       AND moved_target_versions.report_type = target_datasets.report_type
       AND moved_target_versions.status = 'published'
    INNER JOIN draft_operation_results AS move_revisions
        ON move_revisions.operation_token = results.move_revision_operation_token
       AND move_revisions.result_dataset_id = event_sets.target_dataset_id
       AND move_revisions.result_version_id = event_sets.moved_target_version_id
       AND move_revisions.operation_kind = 'create_published_move_revision'
       AND move_revisions.result_kind = 'move_revision_created'
       AND move_revisions.result_status = 'draft'
       AND move_revisions.source_dataset_id = event_sets.source_dataset_id
       AND move_revisions.source_version_id = event_sets.restore_source_version_id
       AND move_revisions.published_move_source_parent_version_id =
           event_sets.restore_source_version_id
       AND move_revisions.published_move_source_lineage_type = 'moved_source'
    LEFT JOIN dataset_versions AS restored_target_versions
        ON restored_target_versions.dataset_id = event_sets.target_dataset_id
       AND restored_target_versions.id = event_sets.restore_target_version_id
       AND restored_target_versions.report_type = target_datasets.report_type
       AND restored_target_versions.status = 'published'
    LEFT JOIN dataset_publications AS source_publications
        ON source_publications.dataset_id = event_sets.source_dataset_id
    INNER JOIN dataset_publications AS target_publications
        ON target_publications.dataset_id = event_sets.target_dataset_id
       AND target_publications.version_id = event_sets.moved_target_version_id
       AND target_publications.version_status = 'published'
    LEFT JOIN dataset_drafts AS source_drafts
        ON source_drafts.dataset_id = event_sets.source_dataset_id
    LEFT JOIN dataset_drafts AS target_drafts
        ON target_drafts.dataset_id = event_sets.target_dataset_id
    WHERE commands.operation_kind = 'move'
      AND results.operation_kind = 'move'
      AND results.result_kind = 'moved'
      AND results.result_status = 'published'
      AND results.result_dataset_id = event_sets.target_dataset_id
      AND results.result_version_id = event_sets.moved_target_version_id
      AND results.publication_event_id = event_sets.moved_in_event_id
      AND results.validation_run_id IS NOT NULL
      AND results.move_revision_operation_token IS NOT NULL
      AND results.reversed_move_command_id IS NULL
      AND event_sets.moved_out_sequence = 1
      AND event_sets.moved_in_sequence = 2
      AND event_sets.source_dataset_id <> event_sets.target_dataset_id
      AND event_sets.source_peer_dataset_id = event_sets.target_dataset_id
      AND event_sets.target_peer_dataset_id = event_sets.source_dataset_id
      AND event_sets.restore_source_version_id IS NOT NULL
      AND event_sets.source_next_version_id IS NULL
      AND event_sets.moved_target_version_id IS NOT NULL
      AND source_datasets.site_id = target_datasets.site_id
      AND source_datasets.report_type = target_datasets.report_type
      AND source_versions.id IS NOT NULL
      AND moved_target_versions.id IS NOT NULL
      AND (
            event_sets.restore_target_version_id IS NULL
            OR restored_target_versions.id IS NOT NULL
          )
      AND source_publications.dataset_id IS NULL
      AND source_drafts.dataset_id IS NULL
      AND target_drafts.dataset_id IS NULL
      AND results.completed_at = event_sets.moved_out_at
      AND results.completed_at = event_sets.moved_in_at
      AND target_publications.published_at = results.completed_at
      AND NOT EXISTS (
          SELECT 1
          FROM publication_events AS later_source_events
          WHERE later_source_events.dataset_id = event_sets.source_dataset_id
            AND (
                later_source_events.occurred_at > event_sets.moved_out_at
                OR (
                    later_source_events.occurred_at = event_sets.moved_out_at
                    AND later_source_events.id > event_sets.moved_out_event_id
                )
            )
      )
      AND NOT EXISTS (
          SELECT 1
          FROM publication_events AS later_target_events
          WHERE later_target_events.dataset_id = event_sets.target_dataset_id
            AND (
                later_target_events.occurred_at > event_sets.moved_in_at
                OR (
                    later_target_events.occurred_at = event_sets.moved_in_at
                    AND later_target_events.id > event_sets.moved_in_event_id
                )
            )
      )
      AND NOT EXISTS (
          SELECT 1
          FROM publication_command_results AS reversals
          INNER JOIN publication_commands AS reversal_commands
              ON reversal_commands.id = reversals.command_id
             AND reversal_commands.operation_token = reversals.operation_token
             AND reversal_commands.operation_kind = reversals.operation_kind
             AND reversal_commands.operation_digest = reversals.operation_digest
             AND reversal_commands.actor_user_id = reversals.actor_user_id
          WHERE reversals.operation_kind = 'reverse_move'
            AND reversals.result_kind = 'move_reversed'
            AND reversals.reversed_move_command_id = results.command_id
      )
    ORDER BY results.completed_at DESC, results.command_id DESC
    """
)


def _utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if value.utcoffset() is None:
        return None
    return value.astimezone(UTC)


def _candidate(row: sa.RowMapping) -> UndoablePublishedMove | None:
    try:
        source_report_date = row["source_report_date"]
        target_report_date = row["target_report_date"]
        report_type = row["report_type"]
        completed_at = _utc_timestamp(row["completed_at"])
        target_published_at = _utc_timestamp(row["target_published_at"])
        if (
            not isinstance(source_report_date, date)
            or not isinstance(target_report_date, date)
            or report_type not in {"business_report", "return_report"}
            or completed_at is None
            or target_published_at is None
        ):
            return None
        restore_target = row["restore_target_version_id"]
        return UndoablePublishedMove(
            move_command_id=int(row["move_command_id"]),
            source_dataset_id=int(row["source_dataset_id"]),
            source_report_date=source_report_date,
            restore_source_version_id=int(row["restore_source_version_id"]),
            source_current_publication=PublicationPointerSnapshot(None, None),
            target_dataset_id=int(row["target_dataset_id"]),
            target_report_date=target_report_date,
            restore_target_version_id=(
                None if restore_target is None else int(restore_target)
            ),
            target_current_publication=PublicationPointerSnapshot(
                version_id=int(row["target_publication_version_id"]),
                published_at=target_published_at,
            ),
            moved_target_version_id=int(row["moved_target_version_id"]),
            completed_at=completed_at,
            report_type=cast(ReportType, report_type),
        )
    except KeyError, TypeError, ValueError:
        return None


class UndoablePublishedMoveQueryService:
    """Return only moves whose exact two-pointer reversal remains safe."""

    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def list_moves(self) -> list[UndoablePublishedMove]:
        rows = self._database_session.execute(_UNDOABLE_PUBLISHED_MOVES).mappings()
        return [candidate for row in rows if (candidate := _candidate(row)) is not None]
