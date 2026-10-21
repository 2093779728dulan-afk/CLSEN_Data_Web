from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Literal, cast
from uuid import UUID

import pytest
from app.datasets.repository import _BUSINESS_COLUMNS, _Actor, _Dataset, _Version
from app.publications.commands import (
    ActiveDraftMoveTarget,
    CreatePublishedMoveRevisionCommand,
    CreateRevisionCommand,
    DraftPointerExpectation,
    FinalizePublishedMoveCommand,
    PublicationConfirmation,
    PublicationPointerExpectation,
    PublishCommand,
    RollbackCommand,
    UndoPublishedMoveCommand,
    ValidationExpectation,
)
from app.publications.repository import (
    MySqlPublicationRepository,
    PublicationCommitOutcomeUnknown,
    PublicationOperationConflict,
    PublicationPermissionDenied,
    PublicationPointerConflict,
    PublicationStateConflict,
    PublicationTransactionBusy,
    _PublishedMoveRevisionCloner,
    _PublishedRevisionCloner,
)
from app.publications.results import (
    DraftCommandResult,
    PublicationCommandResult,
    PublicationTransition,
)
from app.publications.rules import EligibilityFailure, PublicationIneligible
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

TOKEN = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_TOKEN = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
NOW = datetime(2026, 8, 8, 5, 6, 7, 890123, tzinfo=UTC)
DB_NOW = NOW.replace(tzinfo=None)
POINTED_AT = datetime(2026, 8, 8, 4, 6, 7, 890123, tzinfo=UTC)
DB_POINTED_AT = POINTED_AT.replace(tzinfo=None)
PUBLISHED_AT = datetime(2026, 8, 7, 5, 6, 7, 890123, tzinfo=UTC)
DB_PUBLISHED_AT = PUBLISHED_AT.replace(tzinfo=None)
DIGEST = bytes.fromhex("11" * 32)
MOVE_REVISION_TOKEN = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
TARGET_PUBLISHED_AT = datetime(2026, 8, 7, 6, 7, 8, 901234, tzinfo=UTC)
DB_TARGET_PUBLISHED_AT = TARGET_PUBLISHED_AT.replace(tzinfo=None)
TARGET_POINTED_AT = datetime(2026, 8, 8, 3, 6, 7, 890123, tzinfo=UTC)
DB_TARGET_POINTED_AT = TARGET_POINTED_AT.replace(tzinfo=None)


def _validation() -> ValidationExpectation:
    return ValidationExpectation(
        run_id=31,
        version_id=23,
        data_revision=4,
        ruleset_version="rules-v3",
        data_digest=DIGEST,
    )


def _confirmation() -> PublicationConfirmation:
    return PublicationConfirmation(
        confirmed_report_date=date(2026, 8, 8),
        report_type="business_report",
        row_count=2,
        totals=(("units_ordered", "3"),),
    )


def _publish_command(*, replacing: bool = True) -> PublishCommand:
    return PublishCommand(
        dataset_id=5,
        expected_draft=DraftPointerExpectation(
            version_id=23,
            status="ready_for_publish",
            data_revision=4,
            review_revision=7,
            pointed_at=POINTED_AT,
        ),
        expected_publication=(
            PublicationPointerExpectation(17, PUBLISHED_AT)
            if replacing
            else PublicationPointerExpectation(None, None)
        ),
        validation=_validation(),
        confirmation=_confirmation(),
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Publish the reviewed data",
    )


def _rollback_command() -> RollbackCommand:
    return RollbackCommand(
        dataset_id=5,
        expected_publication=PublicationPointerExpectation(23, PUBLISHED_AT),
        target_version_id=17,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Restore the previous publication",
    )


def _create_revision_command() -> CreateRevisionCommand:
    return CreateRevisionCommand(
        dataset_id=5,
        expected_publication=PublicationPointerExpectation(17, PUBLISHED_AT),
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Create an editable revision",
    )


def _create_move_revision_command(
    *,
    action: str = "merge",
    rebuild_strategy: str | None = None,
) -> CreatePublishedMoveRevisionCommand:
    return CreatePublishedMoveRevisionCommand(
        source_dataset_id=5,
        expected_source_publication=PublicationPointerExpectation(17, PUBLISHED_AT),
        target_report_date=date(2026, 8, 9),
        target=ActiveDraftMoveTarget(
            dataset_id=6,
            draft=DraftPointerExpectation(
                version_id=21,
                status="draft",
                data_revision=2,
                review_revision=3,
                pointed_at=TARGET_POINTED_AT,
            ),
            publication=PublicationPointerExpectation(19, TARGET_PUBLISHED_AT),
            action=cast(Any, action),
            rebuild_strategy=cast(Any, rebuild_strategy),
        ),
        merge_decisions=(),
        actor_user_id=9,
        operation_token=MOVE_REVISION_TOKEN,
        reason="Move the publication to the correct report date",
    )


def _move_confirmation() -> PublicationConfirmation:
    return PublicationConfirmation(
        confirmed_report_date=date(2026, 8, 9),
        report_type="business_report",
        row_count=2,
        totals=(("units_ordered", "3"),),
    )


def _finalize_move_command() -> FinalizePublishedMoveCommand:
    return FinalizePublishedMoveCommand(
        move_revision_operation_token=MOVE_REVISION_TOKEN,
        source_dataset_id=5,
        expected_source_publication=PublicationPointerExpectation(17, PUBLISHED_AT),
        target_dataset_id=6,
        expected_target_draft=DraftPointerExpectation(
            version_id=23,
            status="ready_for_publish",
            data_revision=4,
            review_revision=7,
            pointed_at=TARGET_POINTED_AT,
        ),
        expected_target_publication=PublicationPointerExpectation(
            19,
            TARGET_PUBLISHED_AT,
        ),
        validation=_validation(),
        confirmation=_move_confirmation(),
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Activate the reviewed cross-date move",
    )


def _undo_move_command(
    *,
    restore_target_version_id: int | None = 19,
) -> UndoPublishedMoveCommand:
    return UndoPublishedMoveCommand(
        move_command_id=37,
        source_dataset_id=5,
        expected_source_publication=PublicationPointerExpectation(None, None),
        restore_source_version_id=17,
        target_dataset_id=6,
        expected_target_publication=PublicationPointerExpectation(
            23,
            TARGET_PUBLISHED_AT,
        ),
        restore_target_version_id=restore_target_version_id,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Reverse the cross-date move",
    )


def _confirmation_payload() -> dict[str, object]:
    validation = _validation()
    confirmation = _confirmation()
    return {
        "validation_run_id": validation.run_id,
        "validation_data_digest": validation.data_digest.hex(),
        "ruleset_version": validation.ruleset_version,
        "confirmed_report_date": confirmation.confirmed_report_date.isoformat(),
        "confirmed_report_type": confirmation.report_type,
        "confirmed_row_count": confirmation.row_count,
        "confirmed_totals": {name: value for name, value in confirmation.totals},
    }


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _confirmation_digest() -> bytes:
    return hashlib.sha256(
        _canonical_json(_confirmation_payload()).encode("ascii")
    ).digest()


class _Result:
    def __init__(
        self,
        row: Mapping[str, object] | None = None,
        *,
        rows: tuple[Mapping[str, object], ...] = (),
        rowcount: int = 1,
        lastrowid: int | None = None,
    ) -> None:
        self._row = row
        self._rows = rows
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def mappings(self) -> _Result:
        return self

    def first(self) -> Mapping[str, object] | None:
        return self._row

    def all(self) -> tuple[Mapping[str, object], ...]:
        return self._rows


class _RevisionCloneConnection:
    def __init__(self) -> None:
        self.logical_row_id = UUID("11111111-2222-3333-4444-555555555555")
        self.values = {
            name: index for index, name in enumerate(_BUSINESS_COLUMNS, start=1)
        }
        self.executions: list[tuple[str, dict[str, object]]] = []
        self.events: list[str] = []

    @staticmethod
    def _sql(statement: object) -> str:
        return " ".join(str(statement).split())

    def scalars(
        self,
        statement: object,
        _parameters: Mapping[str, object] | None = None,
    ) -> tuple[int, ...]:
        sql = self._sql(statement)
        self.events.append(sql)
        if "SELECT DISTINCT batch_id" in sql:
            return (101, 102)
        if "FROM import_batches" in sql:
            return (101, 102)
        if "SELECT row_records.id" in sql and "FROM version_rows" in sql:
            return (501,)
        raise AssertionError(f"unexpected scalar sequence SQL: {sql}")

    def scalar(
        self,
        statement: object,
        _parameters: Mapping[str, object] | None = None,
    ) -> int:
        sql = self._sql(statement)
        self.events.append(sql)
        if "SELECT COALESCE(MAX(version_no), 0) + 1" in sql:
            return 4
        raise AssertionError(f"unexpected scalar SQL: {sql}")

    def execute(
        self,
        statement: object,
        parameters: object = None,
    ) -> _Result:
        sql = self._sql(statement)
        bound = dict(parameters) if isinstance(parameters, Mapping) else {}
        self.executions.append((sql, bound))
        self.events.append(sql)
        if "FROM version_table_columns" in sql:
            return _Result(
                rows=tuple(
                    {
                        "column_id": UUID(
                            int=index,
                        ).bytes,
                        "source_header": name,
                        "value_kind": "text",
                        "standard_field_name": name,
                    }
                    for index, name in enumerate(_BUSINESS_COLUMNS, start=1)
                )
            )
        if "FROM version_extension_cells" in sql:
            return _Result(rows=())
        if "SELECT row_records.id AS source_row_id" in sql:
            return _Result(
                rows=(
                    {
                        "source_row_id": 501,
                        "source_ordinal": 7,
                        "logical_row_id": self.logical_row_id.bytes,
                        "row_state": "excluded",
                        "original_parsed_source_row_id": 401,
                        "source_parse_baseline_row_id": 301,
                        **self.values,
                    },
                )
            )
        if "SELECT batch_id, input_role" in sql:
            return _Result(
                rows=(
                    {"batch_id": 101, "input_role": "primary"},
                    {"batch_id": 102, "input_role": "merge_source"},
                )
            )
        if "INSERT INTO dataset_versions" in sql:
            return _Result(lastrowid=23)
        if "INSERT INTO version_base_snapshots" in sql:
            return _Result(lastrowid=61)
        if "INSERT INTO version_base_snapshot_members" in sql:
            return _Result(lastrowid=71)
        if "INSERT INTO version_base_rows (" in sql:
            return _Result(lastrowid=81)
        if "INSERT INTO version_rows (" in sql:
            return _Result(lastrowid=91)
        if "INSERT INTO" in sql:
            return _Result(rowcount=1)
        raise AssertionError(f"unexpected clone SQL: {sql}")


def _version_row(version_id: int, *, status: str) -> dict[str, object]:
    return {
        "dataset_id": 5,
        "id": version_id,
        "report_type": "business_report",
        "version_no": 4 if version_id == 23 else 3,
        "status": status,
        "data_revision": 4 if version_id == 23 else 3,
        "review_revision": 7 if version_id == 23 else 5,
        "ruleset_version": "rules-v3",
        "created_by": 9,
    }


class _WorkflowConnection:
    def __init__(
        self,
        *,
        draft_present: bool = True,
        publication_version_id: int | None = 17,
        latest_full_run_id: int = 31,
        issues: tuple[Mapping[str, object], ...] = (),
        issue_reviews: tuple[Mapping[str, object], ...] = (),
        confirmation_digest: bytes | None = None,
        historical_publication: bool = True,
        delete_rowcount: int = 1,
        moved_source_operation: Literal[
            "published_move",
            "published_move_ancestor",
            "completed_published_move_ancestor",
            "reassign",
        ]
        | None = None,
    ) -> None:
        self.draft_present = draft_present
        self.publication_version_id = publication_version_id
        self.latest_full_run_id = latest_full_run_id
        self.issues = issues
        self.issue_reviews = issue_reviews
        self.stored_confirmation_digest = (
            _confirmation_digest()
            if confirmation_digest is None
            else confirmation_digest
        )
        self.historical_publication = historical_publication
        self.delete_rowcount = delete_rowcount
        self.moved_source_operation = moved_source_operation
        self.executions: list[tuple[str, dict[str, object]]] = []

    def execute(
        self,
        statement: object,
        parameters: Mapping[str, object] | None = None,
    ) -> _Result:
        sql = " ".join(str(statement).split())
        bound = dict(parameters or {})
        self.executions.append((sql, bound))

        if "UPDATE daily_dataset_locks" in sql:
            return _Result(rowcount=1)
        if "DELETE FROM dataset_drafts" in sql:
            return _Result(rowcount=self.delete_rowcount)
        if "INSERT INTO dataset_drafts" in sql:
            return _Result(rowcount=1)
        if "FROM daily_datasets" in sql:
            return _Result(
                rows=(
                    {
                        "id": 5,
                        "site_id": 2,
                        "report_date": date(2026, 8, 8),
                        "report_type": "business_report",
                    },
                )
            )
        if "FROM dataset_drafts" in sql:
            if not self.draft_present:
                return _Result(None)
            return _Result(
                {
                    "version_id": 23,
                    "version_status": "ready_for_publish",
                    "pointed_at": DB_POINTED_AT,
                }
            )
        if "FROM dataset_publications" in sql:
            if self.publication_version_id is None:
                return _Result(None)
            return _Result(
                {
                    "version_id": self.publication_version_id,
                    "version_status": "published",
                    "published_at": DB_PUBLISHED_AT,
                }
            )
        if "FROM dataset_versions" in sql:
            version_id = int(cast(Any, bound["version_id"]))
            return _Result(
                _version_row(
                    version_id,
                    status=(
                        "ready_for_publish"
                        if version_id == 23 and self.draft_present
                        else "published"
                    ),
                )
            )
        if "WITH RECURSIVE lineage_versions" in sql:
            if self.moved_source_operation is None:
                return _Result(rows=())
            is_published_move = self.moved_source_operation in {
                "published_move",
                "published_move_ancestor",
                "completed_published_move_ancestor",
            }
            child_version_id = (
                22
                if self.moved_source_operation
                in {
                    "published_move_ancestor",
                    "completed_published_move_ancestor",
                }
                else 23
            )
            return _Result(
                rows=(
                    {
                        "child_version_id": child_version_id,
                        "child_dataset_id": 5,
                        "parent_version_id": 13,
                        "parent_dataset_id": 4,
                        "operation_token": MOVE_REVISION_TOKEN.bytes,
                        "operation_kind": (
                            "create_published_move_revision"
                            if is_published_move
                            else "reassign_date"
                        ),
                        "result_kind": (
                            "move_revision_created"
                            if is_published_move
                            else "reassigned"
                        ),
                        "result_dataset_id": 5,
                        "result_version_id": child_version_id,
                        "result_status": "draft",
                        "result_data_revision": 0,
                        "result_review_revision": 0,
                        "source_dataset_id": 4,
                        "source_version_id": 13,
                        "published_move_source_parent_version_id": (
                            13 if is_published_move else None
                        ),
                        "published_move_source_lineage_type": (
                            "moved_source" if is_published_move else None
                        ),
                        "completed_move_count": (
                            1
                            if self.moved_source_operation
                            == "completed_published_move_ancestor"
                            else 0
                        ),
                    },
                )
            )
        if "FROM version_parent_versions" in sql:
            return _Result(
                rows=(
                    ({"parent_version_id": 13},)
                    if self.moved_source_operation in {"published_move", "reassign"}
                    else ()
                )
            )
        if "FROM draft_operation_results" in sql:
            if self.moved_source_operation in {None, "published_move_ancestor"}:
                return _Result(rows=())
            is_published_move = self.moved_source_operation == "published_move"
            return _Result(
                rows=(
                    {
                        "operation_kind": (
                            "create_published_move_revision"
                            if is_published_move
                            else "reassign_date"
                        ),
                        "result_kind": (
                            "move_revision_created"
                            if is_published_move
                            else "reassigned"
                        ),
                        "result_dataset_id": 5,
                        "result_version_id": 23,
                        "result_status": "draft",
                        "result_data_revision": 0,
                        "result_review_revision": 0,
                        "source_dataset_id": 4,
                        "source_version_id": 13,
                        "published_move_source_parent_version_id": (
                            13 if is_published_move else None
                        ),
                        "published_move_source_lineage_type": (
                            "moved_source" if is_published_move else None
                        ),
                    },
                )
            )
        if "FROM validation_runs" in sql:
            rows: list[Mapping[str, object]] = [
                {
                    "id": 31,
                    "version_id": 23,
                    "run_type": "full",
                    "data_revision": 4,
                    "ruleset_version": "rules-v3",
                    "status": "succeeded",
                    "result": "passed",
                    "data_digest": DIGEST,
                }
            ]
            if self.latest_full_run_id != 31:
                rows.append(
                    {
                        "id": self.latest_full_run_id,
                        "version_id": 23,
                        "run_type": "full",
                        "data_revision": 4,
                        "ruleset_version": "rules-v3",
                        "status": "succeeded",
                        "result": "passed",
                        "data_digest": bytes.fromhex("22" * 32),
                    }
                )
            return _Result(rows=tuple(rows))
        if "FROM validation_issues" in sql:
            return _Result(rows=self.issues)
        if "FROM issue_review_events" in sql:
            return _Result(rows=self.issue_reviews)
        if "FROM version_review_events" in sql:
            return _Result(
                {
                    "to_status": "ready_for_publish",
                    "data_revision": 4,
                    "to_review_revision": 7,
                    "selected_validation_run_id": 31,
                    "confirmation_digest": self.stored_confirmation_digest,
                    "confirmation_json": _confirmation_payload(),
                }
            )
        if "FROM publication_events AS events" in sql:
            return _Result(
                {"id": 19} if self.historical_publication else None,
            )
        if "UPDATE dataset_versions" in sql:
            return _Result(rowcount=1)
        if "INSERT INTO publication_events" in sql:
            return _Result(lastrowid=41)
        if "INSERT INTO publication_outbox" in sql:
            return _Result(lastrowid=43)
        if "INSERT INTO dataset_publications" in sql:
            return _Result(rowcount=1)
        if "UPDATE dataset_publications" in sql:
            return _Result(rowcount=1)
        if "INSERT INTO audit_events" in sql:
            return _Result(lastrowid=47)
        if "INSERT INTO publication_command_results" in sql:
            return _Result(rowcount=1)
        if "INSERT INTO draft_operation_results" in sql:
            return _Result(rowcount=1)
        raise AssertionError(f"unexpected SQL: {sql}")


class _MoveWorkflowConnection:
    def __init__(
        self,
        *,
        source_draft_present: bool = False,
        target_draft_id: int | None = 23,
        source_publication_id: int | None = 17,
        target_publication_id: int | None = 19,
        move_lineage_valid: bool = True,
        original_move_is_latest: bool = True,
    ) -> None:
        self.source_draft_present = source_draft_present
        self.target_draft_id = target_draft_id
        self.source_publication_id = source_publication_id
        self.target_publication_id = target_publication_id
        self.move_lineage_valid = move_lineage_valid
        self.original_move_is_latest = original_move_is_latest
        self.executions: list[tuple[str, dict[str, object]]] = []
        self._next_event_id = 41

    @staticmethod
    def _dataset_row(dataset_id: int) -> dict[str, object]:
        return {
            "id": dataset_id,
            "site_id": 2,
            "report_date": date(2026, 8, 8 if dataset_id == 5 else 9),
            "report_type": "business_report",
        }

    @staticmethod
    def _version_row(dataset_id: int, version_id: int) -> dict[str, object]:
        attributes = {
            17: (3, "published", 3, 5),
            19: (2, "published", 2, 2),
            21: (3, "draft", 2, 3),
            23: (4, "ready_for_publish", 4, 7),
        }
        version_no, status, data_revision, review_revision = attributes[version_id]
        return {
            "dataset_id": dataset_id,
            "id": version_id,
            "report_type": "business_report",
            "version_no": version_no,
            "status": status,
            "data_revision": data_revision,
            "review_revision": review_revision,
            "ruleset_version": "rules-v3",
            "created_by": 9,
        }

    def execute(
        self,
        statement: object,
        parameters: Mapping[str, object] | None = None,
    ) -> _Result:
        sql = " ".join(str(statement).split())
        bound = dict(parameters or {})
        self.executions.append((sql, bound))

        if "UPDATE daily_dataset_locks" in sql:
            return _Result(rowcount=len(cast(Any, bound.get("dataset_ids", (5, 6)))))
        if "FROM daily_datasets" in sql:
            if "id IN" in sql:
                identities = tuple(cast(Any, bound["dataset_ids"]))
                return _Result(
                    rows=tuple(self._dataset_row(int(item)) for item in identities)
                )
            if "report_date = :report_date" in sql:
                return _Result(self._dataset_row(6))
            dataset_id = int(cast(Any, bound["dataset_id"]))
            return _Result(self._dataset_row(dataset_id))
        if "FROM dataset_drafts" in sql:
            dataset_id = int(cast(Any, bound["dataset_id"]))
            if dataset_id == 5:
                if not self.source_draft_present:
                    return _Result(None)
                return _Result(
                    {
                        "version_id": 25,
                        "version_status": "draft",
                        "pointed_at": DB_TARGET_POINTED_AT,
                    }
                )
            if self.target_draft_id is None:
                return _Result(None)
            if self.target_draft_id == 21:
                return _Result(
                    {
                        "version_id": 21,
                        "version_status": "draft",
                        "pointed_at": DB_TARGET_POINTED_AT,
                    }
                )
            return _Result(
                {
                    "version_id": 23,
                    "version_status": "ready_for_publish",
                    "pointed_at": DB_TARGET_POINTED_AT,
                }
            )
        if "FROM dataset_publications" in sql:
            dataset_id = int(cast(Any, bound["dataset_id"]))
            version_id = (
                self.source_publication_id
                if dataset_id == 5
                else self.target_publication_id
            )
            if version_id is None:
                return _Result(None)
            return _Result(
                {
                    "version_id": version_id,
                    "version_status": "published",
                    "published_at": (
                        DB_PUBLISHED_AT if dataset_id == 5 else DB_TARGET_PUBLISHED_AT
                    ),
                }
            )
        if "FROM dataset_versions" in sql:
            dataset_id = int(cast(Any, bound["dataset_id"]))
            version_id = int(cast(Any, bound["version_id"]))
            row = self._version_row(dataset_id, version_id)
            if version_id == 23 and self.target_draft_id is None:
                row["status"] = "published"
            return _Result(row)
        if "FROM draft_operation_results" in sql:
            return _Result(
                {
                    "operation_kind": "create_published_move_revision",
                    "result_kind": "move_revision_created",
                    "result_dataset_id": 6,
                    "result_version_id": 23,
                    "result_status": "draft",
                    "source_dataset_id": 5,
                    "source_version_id": 17,
                    "published_move_source_parent_version_id": 17,
                    "published_move_source_lineage_type": "moved_source",
                }
            )
        if "FROM version_parent_versions" in sql:
            return _Result(
                {"lineage_type": "moved_source"} if self.move_lineage_valid else None
            )
        if "FROM validation_runs" in sql:
            return _Result(
                rows=(
                    {
                        "id": 31,
                        "version_id": 23,
                        "run_type": "full",
                        "data_revision": 4,
                        "ruleset_version": "rules-v3",
                        "status": "succeeded",
                        "result": "passed",
                        "data_digest": DIGEST,
                    },
                )
            )
        if "FROM validation_issues" in sql or "FROM issue_review_events" in sql:
            return _Result(rows=())
        if "FROM version_review_events" in sql:
            payload = {
                "validation_run_id": 31,
                "validation_data_digest": DIGEST.hex(),
                "ruleset_version": "rules-v3",
                "confirmed_report_date": "2026-08-09",
                "confirmed_report_type": "business_report",
                "confirmed_row_count": 2,
                "confirmed_totals": {"units_ordered": "3"},
            }
            return _Result(
                {
                    "to_status": "ready_for_publish",
                    "data_revision": 4,
                    "to_review_revision": 7,
                    "selected_validation_run_id": 31,
                    "confirmation_digest": hashlib.sha256(
                        _canonical_json(payload).encode("ascii")
                    ).digest(),
                    "confirmation_json": payload,
                }
            )
        if "FROM publication_commands AS commands" in sql:
            return _Result(
                {
                    "command_id": 37,
                    "operation_kind": "move",
                    "result_kind": "moved",
                    "result_dataset_id": 6,
                    "result_version_id": 23,
                    "move_revision_operation_token": MOVE_REVISION_TOKEN.bytes,
                }
            )
        if "FROM publication_events" in sql and "command_id = :move_command_id" in sql:
            return _Result(
                rows=(
                    {
                        "id": 31,
                        "sequence_number": 1,
                        "event_type": "moved_out",
                        "dataset_id": 5,
                        "peer_dataset_id": 6,
                        "previous_version_id": 17,
                        "next_version_id": None,
                    },
                    {
                        "id": 32,
                        "sequence_number": 2,
                        "event_type": "moved_in",
                        "dataset_id": 6,
                        "peer_dataset_id": 5,
                        "previous_version_id": 19,
                        "next_version_id": 23,
                    },
                )
            )
        if "latest successful publication event" in sql:
            dataset_id = int(cast(Any, bound["dataset_id"]))
            return _Result(
                {
                    "command_id": 37 if self.original_move_is_latest else 38,
                    "event_type": "moved_out" if dataset_id == 5 else "moved_in",
                }
            )
        if "DELETE FROM dataset_drafts" in sql:
            return _Result(rowcount=1)
        if "UPDATE dataset_drafts" in sql:
            return _Result(rowcount=1)
        if "UPDATE dataset_versions" in sql:
            return _Result(rowcount=1)
        if "INSERT INTO publication_events" in sql:
            event_id = self._next_event_id
            self._next_event_id += 1
            return _Result(lastrowid=event_id)
        if "INSERT INTO publication_outbox" in sql:
            return _Result(lastrowid=51)
        if "DELETE FROM dataset_publications" in sql:
            return _Result(rowcount=1)
        if "INSERT INTO dataset_publications" in sql:
            return _Result(rowcount=1)
        if "UPDATE dataset_publications" in sql:
            return _Result(rowcount=1)
        if "INSERT INTO audit_events" in sql:
            return _Result(lastrowid=61)
        if "INSERT INTO publication_command_results" in sql:
            return _Result(rowcount=1)
        if "INSERT INTO draft_operation_results" in sql:
            return _Result(rowcount=1)
        raise AssertionError(f"unexpected move SQL: {sql}")


class _PublishedMoveClonerStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def clone(self, connection: Connection, **keywords: object) -> _Version:
        self.calls.append({"connection": connection, **keywords})
        return _Version(
            dataset_id=6,
            version_id=23,
            report_type="business_report",
            version_no=4,
            status="draft",
            data_revision=0,
            review_revision=0,
            ruleset_version="rules-v3",
            created_by=9,
        )


def _repository(engine: Engine | None = None) -> MySqlPublicationRepository:
    return MySqlPublicationRepository(engine or cast(Engine, object()))


def _sql_index(connection: _WorkflowConnection, fragment: str) -> int:
    return next(
        index
        for index, (sql, _parameters) in enumerate(connection.executions)
        if fragment in sql
    )


def _mutation_names(connection: _WorkflowConnection) -> list[str]:
    markers = {
        "DELETE FROM dataset_drafts": "delete_draft",
        "INSERT INTO dataset_drafts": "insert_draft",
        "UPDATE dataset_versions": "publish_version",
        "INSERT INTO publication_events": "event",
        "INSERT INTO publication_outbox": "outbox",
        "INSERT INTO dataset_publications": "insert_pointer",
        "UPDATE dataset_publications": "update_pointer",
        "INSERT INTO audit_events": "audit",
        "INSERT INTO publication_command_results": "result",
        "INSERT INTO draft_operation_results": "draft_result",
    }
    return [
        name
        for sql, _parameters in connection.executions
        for marker, name in markers.items()
        if marker in sql
    ]


def test_published_revision_cloner_preserves_rows_and_lineage() -> None:
    repository = _repository()
    cloner = _PublishedRevisionCloner(repository)
    connection = _RevisionCloneConnection()
    dataset = _Dataset(
        dataset_id=5,
        site_id=2,
        report_date=date(2026, 8, 8),
        report_type="business_report",
    )
    parent = _Version(
        dataset_id=5,
        version_id=17,
        report_type="business_report",
        version_no=3,
        status="published",
        data_revision=3,
        review_revision=5,
        ruleset_version="business_report_v1",
        created_by=8,
    )

    revision = cloner.clone(
        cast(Connection, connection),
        dataset=dataset,
        parent=parent,
        actor_user_id=9,
        occurred_at=DB_NOW,
    )

    assert revision == _Version(
        dataset_id=5,
        version_id=23,
        report_type="business_report",
        version_no=4,
        status="draft",
        data_revision=0,
        review_revision=0,
        ruleset_version="business_report_v1",
        created_by=9,
    )

    def parameters_for(fragment: str) -> dict[str, object]:
        return next(
            parameters for sql, parameters in connection.executions if fragment in sql
        )

    snapshot = parameters_for("INSERT INTO version_base_snapshots")
    assert snapshot["snapshot_kind"] == "revision"
    assert snapshot["row_count"] == 1
    member = parameters_for("INSERT INTO version_base_snapshot_members")
    assert member["member_type"] == "dataset_version"
    assert member["member_role"] == "base"
    assert member["parent_version_id"] == 17
    assert member["parse_baseline_id"] is None

    base = parameters_for("INSERT INTO version_base_rows (")
    current = parameters_for("INSERT INTO version_rows (")
    assert base["logical_row_id"] == connection.logical_row_id.bytes
    assert current["logical_row_id"] == connection.logical_row_id.bytes
    assert base["row_state"] == "excluded"
    assert current["row_state"] == "excluded"
    assert base["source_parse_baseline_row_id"] == 301
    assert base["original_parsed_source_row_id"] == 401
    assert current["original_source_row_id"] == 401
    assert current["base_row_id"] == 81

    typed_base = parameters_for("INSERT INTO business_version_base_rows")
    typed_current = parameters_for("INSERT INTO business_report_rows")
    assert {name: typed_base[name] for name in _BUSINESS_COLUMNS} == connection.values
    assert {
        name: typed_current[name] for name in _BUSINESS_COLUMNS
    } == connection.values

    parent_link = parameters_for("INSERT INTO version_parent_versions")
    assert parent_link["parent_version_id"] == 17
    assert parent_link["lineage_type"] == "base"
    input_links = [
        parameters
        for sql, parameters in connection.executions
        if "INSERT INTO version_input_batches" in sql
    ]
    assert [
        (item["input_ordinal"], item["batch_id"], item["input_role"])
        for item in input_links
    ] == [(1, 101, "primary"), (2, 102, "merge_source")]

    assert next(
        index
        for index, sql in enumerate(connection.events)
        if "SELECT DISTINCT batch_id" in sql
    ) < next(
        index
        for index, sql in enumerate(connection.events)
        if "SELECT row_records.id" in sql
    )


def test_published_move_cloner_freezes_source_as_moved_lineage() -> None:
    repository = _repository()
    cloner = _PublishedMoveRevisionCloner(repository)
    connection = _RevisionCloneConnection()
    target_dataset = _Dataset(
        dataset_id=6,
        site_id=2,
        report_date=date(2026, 8, 9),
        report_type="business_report",
    )
    source = _Version(
        dataset_id=5,
        version_id=17,
        report_type="business_report",
        version_no=3,
        status="published",
        data_revision=3,
        review_revision=5,
        ruleset_version="business_report_v1",
        created_by=8,
    )

    moved = cloner.clone(
        cast(Connection, connection),
        dataset=target_dataset,
        source=source,
        target=None,
        decisions=(),
        actor_user_id=9,
        occurred_at=DB_NOW,
    )

    assert moved.dataset_id == 6
    snapshot = next(
        parameters
        for sql, parameters in connection.executions
        if "INSERT INTO version_base_snapshots" in sql
    )
    assert snapshot["snapshot_kind"] == "published_move"
    member = next(
        parameters
        for sql, parameters in connection.executions
        if "INSERT INTO version_base_snapshot_members" in sql
    )
    assert member["member_role"] == "moved_source"
    parent = next(
        parameters
        for sql, parameters in connection.executions
        if "INSERT INTO version_parent_versions" in sql
    )
    assert parent["parent_version_id"] == 17
    assert parent["lineage_type"] == "moved_source"
    inputs = [
        parameters
        for sql, parameters in connection.executions
        if "INSERT INTO version_input_batches" in sql
    ]
    assert [item["input_role"] for item in inputs] == [
        "moved_source",
        "moved_source",
    ]


class _RevisionClonerStub:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, int, datetime]] = []

    def clone(
        self,
        connection: Connection,
        *,
        dataset: object,
        parent: _Version,
        actor_user_id: int,
        occurred_at: datetime,
    ) -> _Version:
        self.calls.append((connection, dataset, actor_user_id, occurred_at))
        return _Version(
            dataset_id=parent.dataset_id,
            version_id=23,
            report_type=parent.report_type,
            version_no=4,
            status="draft",
            data_revision=0,
            review_revision=0,
            ruleset_version=parent.ruleset_version,
            created_by=actor_user_id,
        )


def test_create_revision_locks_current_publication_and_writes_frozen_draft_result(
    monkeypatch: Any,
) -> None:
    repository = _repository()
    cloner = _RevisionClonerStub()
    monkeypatch.setattr(repository, "_revision_cloner", cloner)
    connection = _WorkflowConnection(
        draft_present=False,
        publication_version_id=17,
    )
    command = _create_revision_command()

    result = repository._create_revision(
        cast(Connection, connection),
        actor=_Actor(9, frozenset({"data_manager"})),
        command=command,
        occurred_at=DB_NOW,
    )

    assert result == DraftCommandResult(
        operation_token=TOKEN,
        result_kind="revision_created",
        dataset_id=5,
        version_id=23,
        version_no=4,
        status="draft",
        data_revision=0,
        review_revision=0,
        source_dataset_id=5,
        source_version_id=17,
        completed_at=NOW,
    )
    assert [
        _sql_index(connection, fragment)
        for fragment in (
            "UPDATE daily_dataset_locks",
            "FROM daily_datasets",
            "FROM dataset_drafts",
            "FROM dataset_publications",
            "FROM dataset_versions",
        )
    ] == sorted(
        _sql_index(connection, fragment)
        for fragment in (
            "UPDATE daily_dataset_locks",
            "FROM daily_datasets",
            "FROM dataset_drafts",
            "FROM dataset_publications",
            "FROM dataset_versions",
        )
    )
    assert [
        int(cast(Any, parameters["version_id"]))
        for sql, parameters in connection.executions
        if "FROM dataset_versions" in sql
    ] == [17]
    assert len(cloner.calls) == 1
    assert _mutation_names(connection) == ["insert_draft", "audit", "draft_result"]
    result_sql, result_parameters = next(
        item
        for item in connection.executions
        if "INSERT INTO draft_operation_results" in item[0]
    )
    assert "superseded_version_id_1" in result_sql
    assert result_parameters == {
        "operation_token": TOKEN.bytes,
        "operation_kind": "create_revision",
        "operation_digest": command.operation_digest,
        "actor_user_id": 9,
        "result_kind": "created",
        "result_dataset_id": 5,
        "result_version_id": 23,
        "result_version_no": 4,
        "result_status": "draft",
        "result_data_revision": 0,
        "result_review_revision": 0,
        "superseded_version_id_1": None,
        "superseded_version_id_2": None,
        "source_dataset_id": 5,
        "source_version_id": 17,
        "create_revision_parent_version_id": 17,
        "completed_at": DB_NOW,
    }
    assert not any(
        "publication_events" in sql or "publication_outbox" in sql
        for sql, _parameters in connection.executions
    )


def test_create_revision_rejects_an_active_draft_and_publication_aba(
    monkeypatch: Any,
) -> None:
    repository = _repository()
    cloner = _RevisionClonerStub()
    monkeypatch.setattr(repository, "_revision_cloner", cloner)

    with pytest.raises(PublicationStateConflict, match="active draft"):
        repository._create_revision(
            cast(Connection, _WorkflowConnection(draft_present=True)),
            actor=_Actor(9, frozenset({"data_manager"})),
            command=_create_revision_command(),
            occurred_at=DB_NOW,
        )

    stale = CreateRevisionCommand(
        dataset_id=5,
        expected_publication=PublicationPointerExpectation(17, NOW),
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Create an editable revision",
    )
    with pytest.raises(PublicationPointerConflict, match="publication pointer"):
        repository._create_revision(
            cast(
                Connection,
                _WorkflowConnection(
                    draft_present=False,
                    publication_version_id=17,
                ),
            ),
            actor=_Actor(9, frozenset({"data_manager"})),
            command=stale,
            occurred_at=DB_NOW,
        )

    assert cloner.calls == []


def test_publish_locks_and_mutates_in_the_required_fixed_order() -> None:
    repository = _repository()
    connection = _WorkflowConnection()
    command = _publish_command()

    result = repository._publish(
        cast(Connection, connection),
        actor=_Actor(9, frozenset({"data_manager"})),
        command=command,
        occurred_at=DB_NOW,
        command_id=37,
        operation_kind="replace",
    )

    assert result.command_type == "publish"
    assert result.transitions[0].event_type == "replaced"
    assert result.transitions[0].previous_version_id == 17
    assert result.transitions[0].next_version_id == 23
    assert [
        _sql_index(connection, fragment)
        for fragment in (
            "UPDATE daily_dataset_locks",
            "FROM daily_datasets",
            "FROM dataset_drafts",
            "FROM dataset_publications",
            "FROM dataset_versions",
            "version_parent_versions AS parents",
            "draft_operation_results AS operations",
            "FROM validation_runs",
            "FROM validation_issues",
            "FROM issue_review_events",
            "FROM version_review_events",
        )
    ] == sorted(
        _sql_index(connection, fragment)
        for fragment in (
            "UPDATE daily_dataset_locks",
            "FROM daily_datasets",
            "FROM dataset_drafts",
            "FROM dataset_publications",
            "FROM dataset_versions",
            "version_parent_versions AS parents",
            "draft_operation_results AS operations",
            "FROM validation_runs",
            "FROM validation_issues",
            "FROM issue_review_events",
            "FROM version_review_events",
        )
    )
    version_ids = [
        int(cast(Any, parameters["version_id"]))
        for sql, parameters in connection.executions
        if "FROM dataset_versions" in sql
    ]
    assert version_ids == [17, 23]
    assert _mutation_names(connection) == [
        "delete_draft",
        "publish_version",
        "event",
        "outbox",
        "update_pointer",
        "audit",
        "result",
    ]
    delete_sql, delete_parameters = next(
        item
        for item in connection.executions
        if "DELETE FROM dataset_drafts" in item[0]
    )
    assert "version_status = :draft_status" in delete_sql
    assert "pointed_at = :draft_pointed_at" in delete_sql
    assert delete_parameters["draft_pointed_at"] == DB_POINTED_AT
    pointer_sql, pointer_parameters = next(
        item
        for item in connection.executions
        if "UPDATE dataset_publications" in item[0]
    )
    assert "published_at = :expected_published_at" in pointer_sql
    assert pointer_parameters["expected_published_at"] == DB_PUBLISHED_AT
    assert all(command.reason not in sql for sql, _parameters in connection.executions)


def test_first_publish_inserts_pointer_and_emits_published_event() -> None:
    repository = _repository()
    connection = _WorkflowConnection(publication_version_id=None)

    result = repository._publish(
        cast(Connection, connection),
        actor=_Actor(9, frozenset({"data_manager"})),
        command=_publish_command(replacing=False),
        occurred_at=DB_NOW,
        command_id=37,
        operation_kind="publish",
    )

    assert result.transitions[0].event_type == "published"
    assert result.transitions[0].previous_version_id is None
    assert "insert_pointer" in _mutation_names(connection)
    assert "update_pointer" not in _mutation_names(connection)


def test_publish_rejects_published_move_draft_before_business_mutation() -> None:
    repository = _repository()
    connection = _WorkflowConnection(moved_source_operation="published_move")

    with pytest.raises(
        PublicationStateConflict,
        match="atomic published-move finalization",
    ):
        repository._publish(
            cast(Connection, connection),
            actor=_Actor(9, frozenset({"admin"})),
            command=_publish_command(),
            occurred_at=DB_NOW,
            command_id=37,
            operation_kind="replace",
        )

    assert _mutation_names(connection) == []
    assert not any(
        "FROM validation_runs" in sql for sql, _parameters in connection.executions
    )
    for fragment in (
        "version_parent_versions AS parents",
        "draft_operation_results AS operations",
    ):
        assert next(
            parameters for sql, parameters in connection.executions if fragment in sql
        ) == {"version_id": 23}


def test_publish_rejects_published_move_hidden_behind_a_draft_predecessor() -> None:
    repository = _repository()
    connection = _WorkflowConnection(moved_source_operation="published_move_ancestor")

    with pytest.raises(PublicationStateConflict, match="atomic published-move"):
        repository._publish(
            cast(Connection, connection),
            actor=_Actor(9, frozenset({"data_manager"})),
            command=_publish_command(),
            occurred_at=DB_NOW,
            command_id=37,
            operation_kind="replace",
        )

    assert _mutation_names(connection) == []
    assert not any(
        "FROM validation_runs" in sql for sql, _parameters in connection.executions
    )


def test_publish_allows_an_ordinary_revision_after_a_completed_published_move() -> None:
    repository = _repository()
    connection = _WorkflowConnection(
        moved_source_operation="completed_published_move_ancestor"
    )

    result = repository._publish(
        cast(Connection, connection),
        actor=_Actor(9, frozenset({"data_manager"})),
        command=_publish_command(),
        occurred_at=DB_NOW,
        command_id=37,
        operation_kind="replace",
    )

    assert result.transitions[0].event_type == "replaced"
    assert _mutation_names(connection) == [
        "delete_draft",
        "publish_version",
        "event",
        "outbox",
        "update_pointer",
        "audit",
        "result",
    ]


def test_publish_allows_reassigned_unpublished_draft() -> None:
    repository = _repository()
    connection = _WorkflowConnection(moved_source_operation="reassign")

    result = repository._publish(
        cast(Connection, connection),
        actor=_Actor(9, frozenset({"data_manager"})),
        command=_publish_command(),
        occurred_at=DB_NOW,
        command_id=37,
        operation_kind="replace",
    )

    assert result.transitions[0].event_type == "replaced"
    assert _mutation_names(connection) == [
        "delete_draft",
        "publish_version",
        "event",
        "outbox",
        "update_pointer",
        "audit",
        "result",
    ]
    for fragment in (
        "version_parent_versions AS parents",
        "draft_operation_results AS operations",
    ):
        assert next(
            parameters for sql, parameters in connection.executions if fragment in sql
        ) == {"version_id": 23}


def test_publish_rechecks_latest_full_run_before_any_mutation() -> None:
    repository = _repository()
    connection = _WorkflowConnection(latest_full_run_id=32)

    with pytest.raises(PublicationIneligible) as raised:
        repository._publish(
            cast(Connection, connection),
            actor=_Actor(9, frozenset({"data_manager"})),
            command=_publish_command(),
            occurred_at=DB_NOW,
            command_id=37,
            operation_kind="replace",
        )

    assert EligibilityFailure.VALIDATION_CHANGED in raised.value.failures
    assert _mutation_names(connection) == []


def test_publish_rechecks_warning_acknowledgement_and_required_note() -> None:
    repository = _repository()
    connection = _WorkflowConnection(
        issues=(
            {
                "id": 81,
                "severity": "warning",
                "requires_note": True,
            },
        ),
    )

    with pytest.raises(PublicationIneligible) as raised:
        repository._publish(
            cast(Connection, connection),
            actor=_Actor(9, frozenset({"data_manager"})),
            command=_publish_command(),
            occurred_at=DB_NOW,
            command_id=37,
            operation_kind="replace",
        )

    assert EligibilityFailure.UNACKNOWLEDGED_WARNINGS in raised.value.failures
    assert EligibilityFailure.MISSING_REQUIRED_NOTES in raised.value.failures
    assert _mutation_names(connection) == []


def test_publish_rechecks_frozen_human_confirmation() -> None:
    repository = _repository()
    connection = _WorkflowConnection(confirmation_digest=bytes.fromhex("33" * 32))

    with pytest.raises(PublicationIneligible) as raised:
        repository._publish(
            cast(Connection, connection),
            actor=_Actor(9, frozenset({"data_manager"})),
            command=_publish_command(),
            occurred_at=DB_NOW,
            command_id=37,
            operation_kind="replace",
        )

    assert EligibilityFailure.CONFIRMATION_CHANGED in raised.value.failures
    assert _mutation_names(connection) == []


def test_publish_uses_a_conditional_draft_delete_as_the_first_mutation() -> None:
    repository = _repository()
    connection = _WorkflowConnection(delete_rowcount=0)

    with pytest.raises(PublicationPointerConflict, match="draft pointer"):
        repository._publish(
            cast(Connection, connection),
            actor=_Actor(9, frozenset({"data_manager"})),
            command=_publish_command(),
            occurred_at=DB_NOW,
            command_id=37,
            operation_kind="replace",
        )

    assert _mutation_names(connection) == ["delete_draft"]


def test_rollback_is_admin_only_rejects_drafts_and_requires_history() -> None:
    repository = _repository()

    with pytest.raises(PublicationPermissionDenied, match="administrator"):
        repository._rollback(
            cast(Connection, _WorkflowConnection(draft_present=False)),
            actor=_Actor(9, frozenset({"data_manager"})),
            command=_rollback_command(),
            occurred_at=DB_NOW,
            command_id=37,
        )

    with pytest.raises(PublicationStateConflict, match="active draft"):
        repository._rollback(
            cast(Connection, _WorkflowConnection(draft_present=True)),
            actor=_Actor(9, frozenset({"admin"})),
            command=_rollback_command(),
            occurred_at=DB_NOW,
            command_id=37,
        )

    with pytest.raises(PublicationStateConflict, match="historical"):
        repository._rollback(
            cast(
                Connection,
                _WorkflowConnection(
                    draft_present=False,
                    publication_version_id=23,
                    historical_publication=False,
                ),
            ),
            actor=_Actor(9, frozenset({"admin"})),
            command=_rollback_command(),
            occurred_at=DB_NOW,
            command_id=37,
        )


def test_rollback_only_moves_the_pointer_and_appends_auditable_records() -> None:
    repository = _repository()
    connection = _WorkflowConnection(
        draft_present=False,
        publication_version_id=23,
    )

    result = repository._rollback(
        cast(Connection, connection),
        actor=_Actor(9, frozenset({"admin"})),
        command=_rollback_command(),
        occurred_at=DB_NOW,
        command_id=37,
    )

    assert result.command_type == "rollback"
    assert result.transitions[0].event_type == "rolled_back"
    assert result.transitions[0].previous_version_id == 23
    assert result.transitions[0].next_version_id == 17
    assert [
        int(cast(Any, parameters["version_id"]))
        for sql, parameters in connection.executions
        if "FROM dataset_versions" in sql
    ] == [17, 23]
    assert _mutation_names(connection) == [
        "event",
        "outbox",
        "update_pointer",
        "audit",
        "result",
    ]
    assert not any(
        "UPDATE dataset_versions" in sql for sql, _parameters in connection.executions
    )
    history_sql = next(
        sql
        for sql, _parameters in connection.executions
        if "FROM publication_events AS events" in sql
    )
    assert "publication_command_results" in history_sql
    assert "events.dataset_id = :dataset_id" in history_sql
    assert "events.next_version_id = :target_version_id" in history_sql


@pytest.mark.parametrize(
    ("action", "rebuild_strategy", "expected_target_parent", "disposition"),
    [
        ("merge", None, 21, "superseded"),
        ("force_rebuild", "merge", 19, "force_rebuilt"),
        ("force_rebuild", "replace", None, "force_rebuilt"),
    ],
)
def test_create_published_move_revision_uses_explicit_target_strategy_and_lineage(
    monkeypatch: Any,
    action: str,
    rebuild_strategy: str | None,
    expected_target_parent: int | None,
    disposition: str,
) -> None:
    repository = _repository()
    cloner = _PublishedMoveClonerStub()
    monkeypatch.setattr(repository, "_published_move_cloner", cloner, raising=False)
    dispositions: list[dict[str, object]] = []
    monkeypatch.setattr(
        repository,
        "_discard_version",
        lambda _connection, **keywords: dispositions.append(keywords),
    )
    connection = _MoveWorkflowConnection(target_draft_id=21)
    command = _create_move_revision_command(
        action=action,
        rebuild_strategy=rebuild_strategy,
    )

    result = repository._create_published_move_revision(
        cast(Connection, connection),
        actor=_Actor(9, frozenset({"admin"})),
        command=command,
        occurred_at=DB_NOW,
    )

    assert result == DraftCommandResult(
        operation_token=MOVE_REVISION_TOKEN,
        result_kind="published_move_revision_created",
        dataset_id=6,
        version_id=23,
        version_no=4,
        status="draft",
        data_revision=0,
        review_revision=0,
        source_dataset_id=5,
        source_version_id=17,
        completed_at=NOW,
    )
    assert len(cloner.calls) == 1
    assert cast(_Version, cloner.calls[0]["source"]).version_id == 17
    target_parent = cast(_Version | None, cloner.calls[0]["target"])
    assert (
        target_parent.version_id if target_parent is not None else None
    ) == expected_target_parent
    assert len(dispositions) == 1
    assert dispositions[0]["event_type"] == disposition
    assert dispositions[0]["operation_kind"] == "create_published_move_revision"
    lock_parameters = next(
        parameters
        for sql, parameters in connection.executions
        if "UPDATE daily_dataset_locks" in sql
    )
    assert tuple(cast(Any, lock_parameters["dataset_ids"])) == (5, 6)
    result_parameters = next(
        parameters
        for sql, parameters in connection.executions
        if "INSERT INTO draft_operation_results" in sql
    )
    assert result_parameters["result_kind"] == "move_revision_created"
    assert result_parameters["source_dataset_id"] == 5
    assert result_parameters["source_version_id"] == 17
    assert result_parameters["published_move_source_parent_version_id"] == 17
    assert result_parameters["published_move_source_lineage_type"] == "moved_source"
    assert result_parameters["superseded_version_id_1"] == 21
    assert result_parameters["superseded_version_id_2"] is None
    assert not any(
        "DELETE FROM dataset_publications" in sql
        for sql, _parameters in connection.executions
    )


def test_create_published_move_revision_cancel_is_frozen_without_mutating_drafts(
    monkeypatch: Any,
) -> None:
    repository = _repository()
    cloner = _PublishedMoveClonerStub()
    monkeypatch.setattr(repository, "_published_move_cloner", cloner, raising=False)
    connection = _MoveWorkflowConnection(target_draft_id=21)

    result = repository._create_published_move_revision(
        cast(Connection, connection),
        actor=_Actor(9, frozenset({"admin"})),
        command=_create_move_revision_command(action="cancel"),
        occurred_at=DB_NOW,
    )

    assert result.result_kind == "published_move_revision_cancelled"
    assert result.status == "cancelled"
    assert result.dataset_id == 5
    assert result.version_id == 17
    assert cloner.calls == []
    result_parameters = next(
        parameters
        for sql, parameters in connection.executions
        if "INSERT INTO draft_operation_results" in sql
    )
    assert result_parameters["result_kind"] == "cancelled"
    assert result_parameters["source_dataset_id"] is None
    assert result_parameters["source_version_id"] is None
    assert result_parameters["published_move_source_parent_version_id"] is None
    assert result_parameters["published_move_source_lineage_type"] is None
    assert not any(
        "UPDATE dataset_drafts" in sql or "UPDATE dataset_versions" in sql
        for sql, _parameters in connection.executions
    )


def test_create_published_move_revision_is_admin_only_and_blocks_source_drafts(
    monkeypatch: Any,
) -> None:
    repository = _repository()
    monkeypatch.setattr(
        repository,
        "_published_move_cloner",
        _PublishedMoveClonerStub(),
        raising=False,
    )
    command = _create_move_revision_command()

    with pytest.raises(PublicationPermissionDenied, match="administrator"):
        repository._create_published_move_revision(
            cast(Connection, _MoveWorkflowConnection(target_draft_id=21)),
            actor=_Actor(9, frozenset({"data_manager"})),
            command=command,
            occurred_at=DB_NOW,
        )
    with pytest.raises(PublicationStateConflict, match=r"source.*active draft"):
        repository._create_published_move_revision(
            cast(
                Connection,
                _MoveWorkflowConnection(
                    source_draft_present=True,
                    target_draft_id=21,
                ),
            ),
            actor=_Actor(9, frozenset({"admin"})),
            command=command,
            occurred_at=DB_NOW,
        )


def test_finalize_published_move_validates_lineage_then_switches_both_sides() -> None:
    repository = _repository()
    connection = _MoveWorkflowConnection(target_draft_id=23)
    command = _finalize_move_command()

    result = repository._finalize_published_move(
        cast(Connection, connection),
        actor=_Actor(9, frozenset({"admin"})),
        command=command,
        occurred_at=DB_NOW,
        command_id=37,
    )

    assert result.command_type == "move"
    assert [item.event_type for item in result.transitions] == [
        "moved_out",
        "moved_in",
    ]
    assert result.transitions[0].dataset_id == 5
    assert result.transitions[0].previous_version_id == 17
    assert result.transitions[0].next_version_id is None
    assert result.transitions[1].dataset_id == 6
    assert result.transitions[1].previous_version_id == 19
    assert result.transitions[1].next_version_id == 23
    version_locks = [
        (
            int(cast(Any, parameters["dataset_id"])),
            int(cast(Any, parameters["version_id"])),
        )
        for sql, parameters in connection.executions
        if "FROM dataset_versions" in sql
    ]
    assert version_locks == [(5, 17), (6, 19), (6, 23)]
    lineage_index = next(
        index
        for index, (sql, _parameters) in enumerate(connection.executions)
        if "FROM version_parent_versions" in sql
    )
    first_mutation_index = next(
        index
        for index, (sql, _parameters) in enumerate(connection.executions)
        if "DELETE FROM dataset_drafts" in sql
    )
    assert lineage_index < first_mutation_index
    event_parameters = [
        parameters
        for sql, parameters in connection.executions
        if "INSERT INTO publication_events" in sql
    ]
    assert [item["sequence_number"] for item in event_parameters] == [1, 2]
    assert [item["peer_dataset_id"] for item in event_parameters] == [6, 5]
    assert (
        sum(
            "INSERT INTO publication_outbox" in sql
            for sql, _parameters in connection.executions
        )
        == 2
    )
    frozen = next(
        parameters
        for sql, parameters in connection.executions
        if "INSERT INTO publication_command_results" in sql
    )
    assert frozen["result_kind"] == "moved"
    assert frozen["move_revision_operation_token"] == MOVE_REVISION_TOKEN.bytes
    assert frozen["reversed_move_command_id"] is None
    assert any(
        "DELETE FROM dataset_publications" in sql and parameters["dataset_id"] == 5
        for sql, parameters in connection.executions
    )


def test_finalize_published_move_rejects_missing_moved_source_before_mutation() -> None:
    repository = _repository()
    connection = _MoveWorkflowConnection(
        target_draft_id=23,
        move_lineage_valid=False,
    )

    with pytest.raises(PublicationStateConflict, match="moved_source"):
        repository._finalize_published_move(
            cast(Connection, connection),
            actor=_Actor(9, frozenset({"admin"})),
            command=_finalize_move_command(),
            occurred_at=DB_NOW,
            command_id=37,
        )

    assert not any(
        sql.startswith(("DELETE", "INSERT", "UPDATE"))
        and "daily_dataset_locks" not in sql
        for sql, _parameters in connection.executions
    )


def test_lock_versions_accepts_an_empty_move_target() -> None:
    assert (
        _repository()._lock_versions(
            cast(Connection, object()),
            dataset_id=6,
            version_ids=(),
        )
        == {}
    )


def test_undo_move_requires_latest_original_and_restores_both_sides() -> None:
    repository = _repository()
    connection = _MoveWorkflowConnection(
        target_draft_id=None,
        source_publication_id=None,
        target_publication_id=23,
    )
    command = _undo_move_command()

    result = repository._undo_published_move(
        cast(Connection, connection),
        actor=_Actor(9, frozenset({"admin"})),
        command=command,
        occurred_at=DB_NOW,
        command_id=39,
    )

    assert result.command_type == "reverse_move"
    assert [item.event_type for item in result.transitions] == [
        "move_reversed",
        "move_reversed",
    ]
    assert result.transitions[0].previous_version_id is None
    assert result.transitions[0].next_version_id == 17
    assert result.transitions[1].previous_version_id == 23
    assert result.transitions[1].next_version_id == 19
    assert (
        sum(
            "INSERT INTO publication_outbox" in sql
            for sql, _parameters in connection.executions
        )
        == 2
    )
    assert any(
        "INSERT INTO dataset_publications" in sql and parameters["dataset_id"] == 5
        for sql, parameters in connection.executions
    )
    frozen = next(
        parameters
        for sql, parameters in connection.executions
        if "INSERT INTO publication_command_results" in sql
    )
    assert frozen["result_kind"] == "move_reversed"
    assert frozen["move_revision_operation_token"] is None
    assert frozen["reversed_move_command_id"] == 37

    stale = _MoveWorkflowConnection(
        target_draft_id=None,
        source_publication_id=None,
        target_publication_id=23,
        original_move_is_latest=False,
    )
    with pytest.raises(PublicationStateConflict, match="latest"):
        repository._undo_published_move(
            cast(Connection, stale),
            actor=_Actor(9, frozenset({"admin"})),
            command=command,
            occurred_at=DB_NOW,
            command_id=39,
        )
    assert not any(
        "INSERT INTO publication_events" in sql for sql, _parameters in stale.executions
    )


class _RecoveryConnection:
    def __init__(self, *, stored_digest: bytes) -> None:
        self.stored_digest = stored_digest
        self.executions: list[str] = []

    def execute(
        self,
        statement: object,
        _parameters: Mapping[str, object] | None = None,
    ) -> _Result:
        sql = " ".join(str(statement).split())
        self.executions.append(sql)
        if "FROM publication_commands" in sql:
            return _Result(
                {
                    "id": 37,
                    "operation_kind": "replace",
                    "operation_digest": self.stored_digest,
                    "actor_user_id": 9,
                }
            )
        if "FROM publication_command_results" in sql:
            return _Result(
                {
                    "result_kind": "replaced",
                    "result_dataset_id": 5,
                    "result_version_id": 23,
                    "result_status": "published",
                    "result_data_revision": 4,
                    "result_review_revision": 7,
                    "validation_run_id": 31,
                    "publication_event_id": 41,
                    "completed_at": DB_NOW,
                }
            )
        if "FROM publication_events" in sql:
            return _Result(
                rows=(
                    {
                        "id": 41,
                        "sequence_number": 1,
                        "event_type": "replaced",
                        "dataset_id": 5,
                        "peer_dataset_id": None,
                        "previous_version_id": 17,
                        "next_version_id": 23,
                    },
                )
            )
        raise AssertionError(f"unexpected SQL: {sql}")


class _CrossMoveRecoveryConnection:
    def __init__(self, operation_kind: Literal["move", "reverse_move"]) -> None:
        self.operation_kind = operation_kind
        self.executions: list[str] = []

    def execute(
        self,
        statement: object,
        _parameters: Mapping[str, object] | None = None,
    ) -> _Result:
        sql = " ".join(str(statement).split())
        self.executions.append(sql)
        if "FROM publication_commands" in sql:
            command = (
                _finalize_move_command()
                if self.operation_kind == "move"
                else _undo_move_command()
            )
            return _Result(
                {
                    "id": 37 if self.operation_kind == "move" else 39,
                    "operation_kind": self.operation_kind,
                    "operation_digest": command.operation_digest,
                    "actor_user_id": 9,
                }
            )
        if "FROM publication_command_results" in sql:
            if self.operation_kind == "move":
                return _Result(
                    {
                        "result_kind": "moved",
                        "result_dataset_id": 6,
                        "result_version_id": 23,
                        "result_status": "published",
                        "result_data_revision": 4,
                        "result_review_revision": 7,
                        "validation_run_id": 31,
                        "publication_event_id": 42,
                        "move_revision_operation_token": (MOVE_REVISION_TOKEN.bytes),
                        "reversed_move_command_id": None,
                        "completed_at": DB_NOW,
                    }
                )
            return _Result(
                {
                    "result_kind": "move_reversed",
                    "result_dataset_id": 5,
                    "result_version_id": 17,
                    "result_status": "published",
                    "result_data_revision": 3,
                    "result_review_revision": 5,
                    "validation_run_id": None,
                    "publication_event_id": 43,
                    "move_revision_operation_token": None,
                    "reversed_move_command_id": 37,
                    "completed_at": DB_NOW,
                }
            )
        if "FROM publication_events" in sql:
            if self.operation_kind == "move":
                return _Result(
                    rows=(
                        {
                            "id": 41,
                            "sequence_number": 1,
                            "event_type": "moved_out",
                            "dataset_id": 5,
                            "peer_dataset_id": 6,
                            "previous_version_id": 17,
                            "next_version_id": None,
                        },
                        {
                            "id": 42,
                            "sequence_number": 2,
                            "event_type": "moved_in",
                            "dataset_id": 6,
                            "peer_dataset_id": 5,
                            "previous_version_id": 19,
                            "next_version_id": 23,
                        },
                    )
                )
            return _Result(
                rows=(
                    {
                        "id": 43,
                        "sequence_number": 1,
                        "event_type": "move_reversed",
                        "dataset_id": 5,
                        "peer_dataset_id": 6,
                        "previous_version_id": None,
                        "next_version_id": 17,
                    },
                    {
                        "id": 44,
                        "sequence_number": 2,
                        "event_type": "move_reversed",
                        "dataset_id": 6,
                        "peer_dataset_id": 5,
                        "previous_version_id": 23,
                        "next_version_id": 19,
                    },
                )
            )
        raise AssertionError(f"unexpected cross move recovery SQL: {sql}")


class _MoveRevisionRecoveryConnection:
    def __init__(self, *, cancelled: bool) -> None:
        self.cancelled = cancelled

    def execute(
        self,
        statement: object,
        _parameters: Mapping[str, object] | None = None,
    ) -> _Result:
        sql = " ".join(str(statement).split())
        command = _create_move_revision_command(
            action="cancel" if self.cancelled else "merge"
        )
        if "FROM draft_operation_tokens" in sql:
            return _Result(
                {
                    "operation_kind": "create_published_move_revision",
                    "operation_digest": command.operation_digest,
                    "actor_user_id": 9,
                }
            )
        if "FROM draft_operation_results" in sql:
            if self.cancelled:
                return _Result(
                    {
                        "result_kind": "cancelled",
                        "result_dataset_id": 5,
                        "result_version_id": 17,
                        "result_version_no": 3,
                        "result_status": "cancelled",
                        "result_data_revision": 3,
                        "result_review_revision": 5,
                        "superseded_version_id_1": None,
                        "superseded_version_id_2": None,
                        "source_dataset_id": None,
                        "source_version_id": None,
                        "create_revision_parent_version_id": None,
                        "published_move_source_parent_version_id": None,
                        "published_move_source_lineage_type": None,
                        "completed_at": DB_NOW,
                    }
                )
            return _Result(
                {
                    "result_kind": "move_revision_created",
                    "result_dataset_id": 6,
                    "result_version_id": 23,
                    "result_version_no": 4,
                    "result_status": "draft",
                    "result_data_revision": 0,
                    "result_review_revision": 0,
                    "superseded_version_id_1": 21,
                    "superseded_version_id_2": None,
                    "source_dataset_id": 5,
                    "source_version_id": 17,
                    "create_revision_parent_version_id": None,
                    "published_move_source_parent_version_id": 17,
                    "published_move_source_lineage_type": "moved_source",
                    "completed_at": DB_NOW,
                }
            )
        raise AssertionError(f"unexpected move revision recovery SQL: {sql}")


def test_recovery_uses_only_the_claim_and_append_only_frozen_result() -> None:
    repository = _repository()
    command = _publish_command()
    connection = _RecoveryConnection(stored_digest=command.operation_digest)

    result = repository._command_result(
        cast(Connection, connection),
        operation_token=TOKEN,
        operation_kind="replace",
        operation_digest=command.operation_digest,
        actor_user_id=9,
        require_result=True,
    )

    assert result is not None
    assert result.command_id == 37
    assert result.transitions[0].event_id == 41
    assert all("dataset_versions" not in sql for sql in connection.executions)
    assert all("dataset_publications" not in sql for sql in connection.executions)


def test_recovery_rejects_token_reuse_with_another_digest() -> None:
    repository = _repository()
    connection = _RecoveryConnection(stored_digest=bytes.fromhex("44" * 32))

    with pytest.raises(PublicationOperationConflict, match="another publication"):
        repository._command_result(
            cast(Connection, connection),
            operation_token=TOKEN,
            operation_kind="replace",
            operation_digest=_publish_command().operation_digest,
            actor_user_id=9,
            require_result=True,
        )


@pytest.mark.parametrize("operation_kind", ["move", "reverse_move"])
def test_cross_move_recovery_uses_two_frozen_events(
    operation_kind: Literal["move", "reverse_move"],
) -> None:
    repository = _repository()
    connection = _CrossMoveRecoveryConnection(operation_kind)
    command = (
        _finalize_move_command() if operation_kind == "move" else _undo_move_command()
    )

    result = repository._command_result(
        cast(Connection, connection),
        operation_token=TOKEN,
        operation_kind=operation_kind,
        operation_digest=command.operation_digest,
        actor_user_id=9,
        require_result=True,
    )

    assert result is not None
    assert result.command_type == operation_kind
    assert len(result.transitions) == 2
    assert all("dataset_versions" not in sql for sql in connection.executions)
    assert all("dataset_publications" not in sql for sql in connection.executions)


@pytest.mark.parametrize("cancelled", [False, True])
def test_move_revision_recovery_returns_the_frozen_first_result(
    cancelled: bool,
) -> None:
    repository = _repository()
    command = _create_move_revision_command(action="cancel" if cancelled else "merge")

    result = repository._published_move_revision_result(
        cast(Connection, _MoveRevisionRecoveryConnection(cancelled=cancelled)),
        command=command,
        require_result=True,
    )

    assert result is not None
    assert result.result_kind == (
        "published_move_revision_cancelled"
        if cancelled
        else "published_move_revision_created"
    )
    assert result.status == ("cancelled" if cancelled else "draft")


class _RetryConnection:
    def __init__(self, identity: int) -> None:
        self.identity = identity


class _BeginContext:
    def __init__(self, engine: _RetryEngine, connection: _RetryConnection) -> None:
        self.engine = engine
        self.connection = connection

    def __enter__(self) -> _RetryConnection:
        self.engine.events.append(("begin", self.connection.identity))
        return self.connection

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: object,
    ) -> Literal[False]:
        self.engine.events.append(
            (
                "rollback" if exception_type is not None else "commit",
                self.connection.identity,
            )
        )
        return False


class _RetryEngine:
    def __init__(self) -> None:
        self.connections: list[_RetryConnection] = []
        self.events: list[tuple[str, int]] = []

    def begin(self) -> _BeginContext:
        connection = _RetryConnection(len(self.connections) + 1)
        self.connections.append(connection)
        return _BeginContext(self, connection)


class _MySqlDriverError(RuntimeError):
    pass


def _mysql_error(code: int, *, invalidated: bool = False) -> DBAPIError:
    return DBAPIError(
        statement="injected publication transaction",
        params=None,
        orig=_MySqlDriverError(code, "injected MySQL failure"),
        connection_invalidated=invalidated,
    )


def _publication_result() -> PublicationCommandResult:
    return PublicationCommandResult(
        operation_token=TOKEN,
        command_id=37,
        command_type="publish",
        transitions=(
            PublicationTransition(
                event_id=41,
                sequence_number=1,
                event_type="published",
                dataset_id=5,
                peer_dataset_id=None,
                previous_version_id=None,
                next_version_id=23,
            ),
        ),
        completed_at=NOW,
    )


def _move_revision_result() -> DraftCommandResult:
    return DraftCommandResult(
        operation_token=MOVE_REVISION_TOKEN,
        result_kind="published_move_revision_created",
        dataset_id=6,
        version_id=23,
        version_no=4,
        status="draft",
        data_revision=0,
        review_revision=0,
        source_dataset_id=5,
        source_version_id=17,
        completed_at=NOW,
    )


def _configure_retry(
    monkeypatch: Any,
    failures: tuple[DBAPIError, ...],
) -> tuple[MySqlPublicationRepository, _RetryEngine, list[int], list[int]]:
    engine = _RetryEngine()
    waits: list[int] = []
    repository = MySqlPublicationRepository(
        cast(Engine, engine),
        retry_waiter=waits.append,
    )
    pending = deque(failures)
    recoveries: list[int] = []

    def recover(**_keywords: object) -> None:
        recoveries.append(1)

    def claim(connection: _RetryConnection, **_keywords: object) -> int:
        return 37

    def actor(connection: _RetryConnection, actor_user_id: int) -> _Actor:
        return _Actor(actor_user_id, frozenset({"data_manager"}))

    def work(
        connection: Connection,
        _actor: _Actor,
        _timestamp: datetime,
        _command_id: int,
    ) -> PublicationCommandResult:
        if pending:
            raise pending.popleft()
        return _publication_result()

    monkeypatch.setattr(repository, "_recover_command", recover)
    monkeypatch.setattr(repository, "_claim_command", claim)
    monkeypatch.setattr(repository, "_load_actor", actor)
    monkeypatch.setattr(repository, "_retry_test_work", work, raising=False)
    return repository, engine, waits, recoveries


def _execute_retry(repository: MySqlPublicationRepository) -> PublicationCommandResult:
    work = cast(Any, repository)._retry_test_work
    return repository._execute_command(
        operation_kind="publish",
        operation_token=TOKEN,
        operation_digest=_publish_command(replacing=False).operation_digest,
        actor_user_id=9,
        occurred_at=NOW,
        request_payload={"dataset_id": 5},
        work=work,
    )


@pytest.mark.parametrize("error_code", [1205, 1213])
def test_retryable_mysql_failure_uses_a_new_transaction(
    monkeypatch: Any,
    error_code: int,
) -> None:
    repository, engine, waits, recoveries = _configure_retry(
        monkeypatch,
        (_mysql_error(error_code),),
    )

    assert _execute_retry(repository) == _publication_result()
    assert engine.events == [
        ("begin", 1),
        ("rollback", 1),
        ("begin", 2),
        ("commit", 2),
    ]
    assert waits == [1]
    assert len(recoveries) == 2


def test_retryable_mysql_failures_stop_after_four_total_attempts(
    monkeypatch: Any,
) -> None:
    repository, engine, waits, _recoveries = _configure_retry(
        monkeypatch,
        tuple(_mysql_error(1213) for _index in range(4)),
    )

    with pytest.raises(PublicationTransactionBusy, match="4 attempts"):
        _execute_retry(repository)

    assert len(engine.connections) == 4
    assert waits == [1, 2, 3]


def test_invalidated_connection_recovers_without_blind_replay(
    monkeypatch: Any,
) -> None:
    repository, engine, waits, recoveries = _configure_retry(
        monkeypatch,
        (_mysql_error(1213, invalidated=True),),
    )

    with pytest.raises(PublicationCommitOutcomeUnknown, match="acknowledgement"):
        _execute_retry(repository)

    assert len(engine.connections) == 1
    assert waits == []
    assert len(recoveries) == 2


@pytest.mark.parametrize("error_code", [1205, 1213])
def test_move_revision_retry_restarts_the_complete_transaction(
    monkeypatch: Any,
    error_code: int,
) -> None:
    engine = _RetryEngine()
    waits: list[int] = []
    repository = MySqlPublicationRepository(
        cast(Engine, engine),
        retry_waiter=waits.append,
    )
    pending = deque((_mysql_error(error_code),))
    recoveries: list[int] = []

    def recover(_command: object) -> None:
        recoveries.append(1)

    def claim(_connection: object, **_keywords: object) -> None:
        return None

    def actor(_connection: object, actor_user_id: int) -> _Actor:
        return _Actor(actor_user_id, frozenset({"admin"}))

    def create(_connection: object, **_keywords: object) -> DraftCommandResult:
        if pending:
            raise pending.popleft()
        return _move_revision_result()

    monkeypatch.setattr(
        repository,
        "_recover_published_move_revision_operation",
        recover,
    )
    monkeypatch.setattr(
        repository,
        "_claim_published_move_revision_operation",
        claim,
    )
    monkeypatch.setattr(repository, "_load_actor", actor)
    monkeypatch.setattr(repository, "_create_published_move_revision", create)

    result = repository.create_published_move_revision(
        _create_move_revision_command(),
        occurred_at=NOW,
    )

    assert result == _move_revision_result()
    assert engine.events == [
        ("begin", 1),
        ("rollback", 1),
        ("begin", 2),
        ("commit", 2),
    ]
    assert waits == [1]
    assert len(recoveries) == 2


def test_publication_repository_reuses_dataset_lock_and_actor_snapshot() -> None:
    assert issubclass(MySqlPublicationRepository, object)
    assert MySqlPublicationRepository._lock_datasets.__qualname__.startswith(
        "MySqlDatasetRepository."
    )
    assert MySqlPublicationRepository._load_actor.__qualname__.startswith(
        "MySqlDatasetRepository."
    )
