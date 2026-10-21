"""Resumable import orchestration for the table-first date workbench."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Literal, cast
from uuid import UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.engine import Engine, RowMapping

from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import (
    ActiveDraftConflict,
    BaselineConflict,
    BaselineNotFound,
    DatasetCommitOutcomeUnknown,
    DatasetPermissionDenied,
    DatasetTransactionBusy,
    MaterializeBaselineCommand,
    MergeConflict,
    PublishedLineageConflict,
    RevisionConflict,
    SealedVersionConflict,
    TargetConflict,
)
from app.imports.types import ReportType
from app.parsers.types import SupportedEncoding
from app.parsers.workflow import (
    ConfirmAndParseCommand,
    FailedParse,
    ParseWorkflow,
    SuccessfulParse,
)

type WorkbenchImportStatus = Literal[
    "workspace_ready",
    "confirmation_required",
    "conflict_required",
    "duplicate",
    "failed",
    "processing",
]
type WorkbenchStageCallback = Callable[[str, Mapping[str, int]], None]


class WorkbenchImportError(RuntimeError):
    """Base class for expected import-orchestration errors."""


class WorkbenchImportNotFound(WorkbenchImportError):
    """The requested batch is not visible to the current workbench."""


class WorkbenchImportOperationConflict(WorkbenchImportError):
    """An idempotency key is already bound to another import command."""


@dataclass(frozen=True, slots=True)
class WorkbenchImportResult:
    batch_id: int
    status: WorkbenchImportStatus
    stage: str
    report_date: date | None = None
    report_type: ReportType | None = None
    encoding: SupportedEncoding | None = None
    issue_codes: tuple[str, ...] = ()
    workspace_url: str | None = None
    dataset_id: int | None = None
    version_id: int | None = None
    parse_attempt_id: int | None = None
    parse_baseline_id: int | None = None
    duplicate: bool = False
    message: str | None = None

    def as_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["report_date"] = (
            self.report_date.isoformat() if self.report_date is not None else None
        )
        payload["issue_codes"] = list(self.issue_codes)
        return payload


@dataclass(frozen=True, slots=True)
class OrchestrateImportCommand:
    batch_id: int
    sha256_hex: str
    actor_user_id: int
    operation_token: UUID
    requested_report_date: date | None = None
    requested_report_type: ReportType | None = None
    confirmed_report_type: ReportType | None = None
    confirmed_report_date: date | None = None
    confirmed_encoding: SupportedEncoding | None = None

    operation_kind: Literal["orchestrate_import"] = "orchestrate_import"

    def __post_init__(self) -> None:
        if self.batch_id < 1 or self.actor_user_id < 1:
            raise ValueError("batch and actor IDs must be positive")
        if len(self.sha256_hex) != 64:
            raise ValueError("sha256_hex must be a SHA-256 digest")
        bytes.fromhex(self.sha256_hex)
        explicit = (
            self.confirmed_report_type,
            self.confirmed_report_date,
            self.confirmed_encoding,
        )
        if any(value is not None for value in explicit) and not all(
            value is not None for value in explicit
        ):
            raise ValueError(
                "explicit confirmation must include type, date, and encoding"
            )

    @property
    def operation_digest(self) -> bytes:
        return hashlib.sha256(
            json.dumps(
                {
                    "command": self.operation_kind,
                    "batch_id": self.batch_id,
                    "sha256_hex": self.sha256_hex,
                    "actor_user_id": self.actor_user_id,
                    "requested_report_date": (
                        self.requested_report_date.isoformat()
                        if self.requested_report_date is not None
                        else None
                    ),
                    "confirmed_report_type": self.confirmed_report_type,
                    **(
                        {"requested_report_type": self.requested_report_type}
                        if self.requested_report_type is not None
                        else {}
                    ),
                    "confirmed_report_date": (
                        self.confirmed_report_date.isoformat()
                        if self.confirmed_report_date is not None
                        else None
                    ),
                    "confirmed_encoding": self.confirmed_encoding,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        ).digest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _mysql_timestamp(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, str):
        decoded = json.loads(value)
        return cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _result_from_payload(payload: object) -> WorkbenchImportResult:
    value = _json_object(payload)
    report_date_value = value.get("report_date")
    issue_codes = value.get("issue_codes")
    return WorkbenchImportResult(
        batch_id=int(cast(str | int, value["batch_id"])),
        status=cast(WorkbenchImportStatus, str(value["status"])),
        stage=str(value["stage"]),
        report_date=(
            date.fromisoformat(report_date_value)
            if isinstance(report_date_value, str)
            else None
        ),
        report_type=cast(ReportType | None, value.get("report_type")),
        encoding=cast(SupportedEncoding | None, value.get("encoding")),
        issue_codes=(
            tuple(str(item) for item in issue_codes)
            if isinstance(issue_codes, list)
            else ()
        ),
        workspace_url=(
            str(value["workspace_url"])
            if value.get("workspace_url") is not None
            else None
        ),
        dataset_id=(
            int(cast(str | int, value["dataset_id"]))
            if value.get("dataset_id") is not None
            else None
        ),
        version_id=(
            int(cast(str | int, value["version_id"]))
            if value.get("version_id") is not None
            else None
        ),
        parse_attempt_id=(
            int(cast(str | int, value["parse_attempt_id"]))
            if value.get("parse_attempt_id") is not None
            else None
        ),
        parse_baseline_id=(
            int(cast(str | int, value["parse_baseline_id"]))
            if value.get("parse_baseline_id") is not None
            else None
        ),
        duplicate=bool(value.get("duplicate", False)),
        message=str(value["message"]) if value.get("message") is not None else None,
    )


class MySqlWorkbenchImportRepository:
    """Short transactions and state projections used by the orchestrator."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def register_or_recover(
        self,
        command: OrchestrateImportCommand,
    ) -> WorkbenchImportResult | None:
        now = _mysql_timestamp(_utc_now())
        with self._engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT IGNORE INTO workbench_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, expected_cell_revision, registered_at
                    ) VALUES (
                        :token, :kind, :digest, :actor_user_id, NULL, :registered_at
                    )
                    """
                ),
                {
                    "token": command.operation_token.bytes,
                    "kind": command.operation_kind,
                    "digest": command.operation_digest,
                    "actor_user_id": command.actor_user_id,
                    "registered_at": now,
                },
            )
            token = (
                connection.execute(
                    sa.text(
                        """
                        SELECT operation_kind, operation_digest, actor_user_id
                        FROM workbench_operation_tokens
                        WHERE operation_token = :token
                        LIMIT 1
                        """
                    ),
                    {"token": command.operation_token.bytes},
                )
                .mappings()
                .first()
            )
            if token is None:
                raise WorkbenchImportError(
                    "import operation registration was not stored"
                )
            stored_digest = token["operation_digest"]
            if isinstance(stored_digest, memoryview):
                stored_digest = stored_digest.tobytes()
            if (
                token["operation_kind"] != command.operation_kind
                or int(token["actor_user_id"]) != command.actor_user_id
                or not isinstance(stored_digest, bytes)
                or not hmac.compare_digest(stored_digest, command.operation_digest)
            ):
                raise WorkbenchImportOperationConflict(
                    "operation token belongs to another import command"
                )
            payload = connection.scalar(
                sa.text(
                    """
                    SELECT response_payload
                    FROM workbench_operation_results
                    WHERE operation_token = :token
                    LIMIT 1
                    """
                ),
                {"token": command.operation_token.bytes},
            )
            return _result_from_payload(payload) if payload is not None else None

    def recover_registered(
        self,
        command: OrchestrateImportCommand,
    ) -> WorkbenchImportResult | None:
        """Recover a retried upload without claiming an unrelated duplicate."""

        with self._engine.connect() as connection:
            token = (
                connection.execute(
                    sa.text(
                        """
                        SELECT operation_kind, operation_digest, actor_user_id
                        FROM workbench_operation_tokens
                        WHERE operation_token = :token
                        LIMIT 1
                        """
                    ),
                    {"token": command.operation_token.bytes},
                )
                .mappings()
                .first()
            )
            if token is None:
                return None
            stored_digest = token["operation_digest"]
            if isinstance(stored_digest, memoryview):
                stored_digest = stored_digest.tobytes()
            if (
                token["operation_kind"] != command.operation_kind
                or int(token["actor_user_id"]) != command.actor_user_id
                or not isinstance(stored_digest, bytes)
                or not hmac.compare_digest(stored_digest, command.operation_digest)
            ):
                raise WorkbenchImportOperationConflict(
                    "operation token belongs to another import command"
                )
            payload = connection.scalar(
                sa.text(
                    """
                    SELECT response_payload
                    FROM workbench_operation_results
                    WHERE operation_token = :token
                    LIMIT 1
                    """
                ),
                {"token": command.operation_token.bytes},
            )
        return _result_from_payload(payload) if payload is not None else None

    def finish(
        self,
        command: OrchestrateImportCommand,
        result: WorkbenchImportResult,
    ) -> WorkbenchImportResult:
        with self._engine.begin() as connection:
            existing = connection.scalar(
                sa.text(
                    """
                    SELECT response_payload
                    FROM workbench_operation_results
                    WHERE operation_token = :token
                    LIMIT 1
                    """
                ),
                {"token": command.operation_token.bytes},
            )
            if existing is not None:
                return _result_from_payload(existing)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO workbench_operation_results (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, response_status_code,
                        response_payload, completed_at
                    ) VALUES (
                        :token, :kind, :digest, :actor_user_id, 200,
                        :payload, :completed_at
                    )
                    """
                ),
                {
                    "token": command.operation_token.bytes,
                    "kind": command.operation_kind,
                    "digest": command.operation_digest,
                    "actor_user_id": command.actor_user_id,
                    "payload": json.dumps(
                        result.as_payload(),
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    "completed_at": _mysql_timestamp(_utc_now()),
                },
            )
        return result

    def batch_state(self, batch_id: int) -> RowMapping:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT batches.id AS batch_id, batches.site_id,
                               batches.site_config_version_id,
                               batches.status AS batch_status,
                               batches.report_date, batches.candidate_report_date,
                               batches.detected_report_date,
                               batches.detected_report_type,
                               batches.confirmed_report_type, batches.confirmed_at,
                               batches.detection_summary,
                               attempts.encoding,
                               baselines.id AS parse_baseline_id,
                               datasets.id AS dataset_id,
                               datasets.report_date AS dataset_report_date,
                               datasets.report_type AS dataset_report_type,
                               versions.id AS version_id,
                               versions.status AS version_status
                        FROM import_batches AS batches
                        LEFT JOIN parse_attempts AS attempts
                            ON attempts.id = batches.current_successful_parse_attempt_id
                        LEFT JOIN parse_baselines AS baselines
                            ON baselines.parse_attempt_id = attempts.id
                        LEFT JOIN version_input_batches AS inputs
                            ON inputs.batch_id = batches.id
                        LEFT JOIN dataset_versions AS versions
                            ON versions.id = inputs.version_id
                        LEFT JOIN daily_datasets AS datasets
                            ON datasets.id = versions.dataset_id
                        WHERE batches.id = :batch_id
                        ORDER BY versions.id DESC
                        LIMIT 1
                        """
                    ),
                    {"batch_id": batch_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise WorkbenchImportNotFound("import batch does not exist")
        return row

    def target_has_workspace(
        self,
        *,
        site_id: int,
        report_date: date,
        report_type: ReportType,
    ) -> bool:
        with self._engine.connect() as connection:
            value = connection.scalar(
                sa.text(
                    """
                    SELECT EXISTS(
                        SELECT 1
                        FROM daily_datasets AS datasets
                        LEFT JOIN dataset_drafts AS drafts
                            ON drafts.dataset_id = datasets.id
                        LEFT JOIN dataset_publications AS publications
                            ON publications.dataset_id = datasets.id
                        WHERE datasets.site_id = :site_id
                          AND datasets.report_date = :report_date
                          AND datasets.report_type = :report_type
                          AND (drafts.version_id IS NOT NULL
                               OR publications.version_id IS NOT NULL)
                    )
                    """
                ),
                {
                    "site_id": site_id,
                    "report_date": report_date,
                    "report_type": report_type,
                },
            )
        return bool(value == 1)

    def sha256_hex(self, batch_id: int) -> str:
        with self._engine.connect() as connection:
            value = connection.scalar(
                sa.text(
                    """
                    SELECT LOWER(HEX(files.sha256))
                    FROM import_batches AS batches
                    INNER JOIN raw_files AS files ON files.id = batches.raw_file_id
                    WHERE batches.id = :batch_id
                    """
                ),
                {"batch_id": batch_id},
            )
        if not isinstance(value, str):
            raise WorkbenchImportNotFound("import batch does not exist")
        return value

    def pending_batch_ids(self, *, limit: int = 100) -> tuple[int, ...]:
        with self._engine.connect() as connection:
            values = connection.scalars(
                sa.text(
                    """
                    SELECT id
                    FROM import_batches
                    WHERE confirmed_at IS NULL
                    ORDER BY created_at DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).all()
        return tuple(int(value) for value in values)


class WorkbenchImportOrchestrator:
    def __init__(
        self,
        engine: Engine,
        *,
        workflow: ParseWorkflow,
        repository: MySqlWorkbenchImportRepository | None = None,
    ) -> None:
        self._engine = engine
        self._workflow = workflow
        self._repository = repository or MySqlWorkbenchImportRepository(engine)

    def run(
        self,
        command: OrchestrateImportCommand,
        *,
        on_stage: WorkbenchStageCallback | None = None,
    ) -> WorkbenchImportResult:
        recovered = self._repository.register_or_recover(command)
        if recovered is not None:
            return recovered
        if command.confirmed_report_type is not None:
            state = self._repository.batch_state(command.batch_id)
            return self._continue(
                command,
                state=state,
                report_type=command.confirmed_report_type,
                report_date=cast(date, command.confirmed_report_date),
                encoding=cast(SupportedEncoding, command.confirmed_encoding),
                issue_codes=(),
                on_stage=on_stage,
            )

        recognition = self._workflow.inspect(command.batch_id)
        state = self._repository.batch_state(command.batch_id)
        report_date = recognition.detected_report_date or command.requested_report_date
        issue_codes = tuple(issue.code for issue in recognition.issues)
        if (
            command.requested_report_type is not None
            and recognition.report_type is not None
            and command.requested_report_type != recognition.report_type
        ):
            issue_codes = (*issue_codes, "selected_type_conflict")
        certain = (
            recognition.status == "suggested"
            and recognition.report_type is not None
            and report_date is not None
            and recognition.encoding is not None
            and not issue_codes
            and not (
                recognition.detected_report_date is not None
                and command.requested_report_date is not None
                and recognition.detected_report_date != command.requested_report_date
            )
        )
        if not certain:
            if (
                recognition.detected_report_date is not None
                and command.requested_report_date is not None
                and recognition.detected_report_date != command.requested_report_date
            ):
                issue_codes = (*issue_codes, "selected_date_conflict")
            return self._repository.finish(
                command,
                WorkbenchImportResult(
                    batch_id=command.batch_id,
                    status="confirmation_required",
                    stage="recognition",
                    report_date=report_date,
                    report_type=recognition.report_type,
                    encoding=recognition.encoding,
                    issue_codes=issue_codes,
                    message="请确认识别出的日期、报表类型和编码。",
                ),
            )
        return self._continue(
            command,
            state=state,
            report_type=cast(ReportType, recognition.report_type),
            report_date=cast(date, report_date),
            encoding=cast(SupportedEncoding, recognition.encoding),
            issue_codes=issue_codes,
            on_stage=on_stage,
        )

    def _continue(
        self,
        command: OrchestrateImportCommand,
        *,
        state: RowMapping,
        report_type: ReportType,
        report_date: date,
        encoding: SupportedEncoding,
        issue_codes: tuple[str, ...],
        on_stage: WorkbenchStageCallback | None,
    ) -> WorkbenchImportResult:
        if self._repository.target_has_workspace(
            site_id=int(state["site_id"]),
            report_date=report_date,
            report_type=report_type,
        ):
            return self._repository.finish(
                command,
                WorkbenchImportResult(
                    batch_id=command.batch_id,
                    status="conflict_required",
                    stage="target_conflict",
                    report_date=report_date,
                    report_type=report_type,
                    encoding=encoding,
                    issue_codes=issue_codes,
                    workspace_url=(
                        f"/review/{report_date.isoformat()}?report_type={report_type}"
                    ),
                    message="目标日期已有草稿或发布版本, 请选择合并或替换策略。",
                ),
            )
        if on_stage is not None:
            on_stage("parsing", {})
        parse_result = self._workflow.confirm_and_parse(
            ConfirmAndParseCommand(
                batch_id=command.batch_id,
                report_type=report_type,
                report_date=report_date,
                encoding=encoding,
                site_config_version_id=int(state["site_config_version_id"]),
                actor_user_id=command.actor_user_id,
                operation_token=uuid5(command.operation_token, "workbench-parse"),
            )
        )
        if isinstance(parse_result, FailedParse):
            return self._repository.finish(
                command,
                WorkbenchImportResult(
                    batch_id=command.batch_id,
                    status="failed",
                    stage="parse_failed",
                    report_date=report_date,
                    report_type=report_type,
                    encoding=encoding,
                    issue_codes=(parse_result.error_code,),
                    message="CSV 解析失败, 请检查文件内容。",
                ),
            )
        if not isinstance(parse_result, SuccessfulParse):
            raise WorkbenchImportError("parse did not produce a terminal result")
        if on_stage is not None:
            on_stage(
                "materializing",
                {
                    "parse_attempt_id": parse_result.parse_attempt_id,
                    "parse_baseline_id": parse_result.parse_baseline_id,
                },
            )
        try:
            draft = DatasetService(
                repository=MySqlDatasetRepository(self._engine)
            ).materialize_baseline(
                MaterializeBaselineCommand(
                    batch_id=command.batch_id,
                    parse_baseline_id=parse_result.parse_baseline_id,
                    report_date=report_date,
                    strategy="replace",
                    expected_active_draft=None,
                    expected_publication_version_id=None,
                    merge_decisions=(),
                    actor_user_id=command.actor_user_id,
                    operation_token=uuid5(
                        command.operation_token,
                        "workbench-materialize",
                    ),
                    reason="日期工作台自动识别、解析并创建工作草稿",
                )
            )
        except (
            DatasetCommitOutcomeUnknown,
            DatasetTransactionBusy,
            DatasetPermissionDenied,
        ):
            raise
        except (
            ActiveDraftConflict,
            BaselineConflict,
            BaselineNotFound,
            MergeConflict,
            PublishedLineageConflict,
            RevisionConflict,
            SealedVersionConflict,
            TargetConflict,
        ):
            return self._repository.finish(
                command,
                WorkbenchImportResult(
                    batch_id=command.batch_id,
                    status="conflict_required",
                    stage="materialize_conflict",
                    report_date=report_date,
                    report_type=report_type,
                    encoding=encoding,
                    workspace_url=(
                        f"/review/{report_date.isoformat()}?report_type={report_type}"
                    ),
                    message="生成工作草稿时目标状态发生变化, 请处理当前版本后继续。",
                ),
            )
        return self._repository.finish(
            command,
            WorkbenchImportResult(
                batch_id=command.batch_id,
                status="workspace_ready",
                stage="draft",
                report_date=report_date,
                report_type=report_type,
                encoding=encoding,
                workspace_url=f"/review/{report_date.isoformat()}?report_type={report_type}",
                dataset_id=draft.dataset_id,
                version_id=draft.version_id,
                parse_attempt_id=parse_result.parse_attempt_id,
                parse_baseline_id=parse_result.parse_baseline_id,
            ),
        )

    def describe(
        self,
        batch_id: int,
        *,
        duplicate: bool = False,
    ) -> WorkbenchImportResult:
        state = self._repository.batch_state(batch_id)
        report_date = cast(
            date | None,
            state["dataset_report_date"]
            or state["report_date"]
            or state["detected_report_date"]
            or state["candidate_report_date"],
        )
        report_type = cast(
            ReportType | None,
            state["dataset_report_type"]
            or state["confirmed_report_type"]
            or state["detected_report_type"],
        )
        workspace_url = (
            f"/review/{report_date.isoformat()}?report_type={report_type}"
            if report_date is not None and report_type is not None
            else None
        )
        if state["version_id"] is not None:
            status: WorkbenchImportStatus = (
                "duplicate" if duplicate else "workspace_ready"
            )
            stage = str(state["version_status"])
        elif state["batch_status"] in {"failed", "rejected"}:
            status, stage = "failed", str(state["batch_status"])
        elif state["confirmed_at"] is None:
            status, stage = "confirmation_required", "recognition"
        else:
            status, stage = "processing", str(state["batch_status"])
        summary = _json_object(state["detection_summary"])
        raw_issues = summary.get("issue_codes")
        return WorkbenchImportResult(
            batch_id=batch_id,
            status=status,
            stage=stage,
            report_date=report_date,
            report_type=report_type,
            encoding=cast(SupportedEncoding | None, state["encoding"]),
            issue_codes=(
                tuple(str(item) for item in raw_issues)
                if isinstance(raw_issues, list)
                else ()
            ),
            workspace_url=workspace_url,
            dataset_id=(int(state["dataset_id"]) if state["dataset_id"] else None),
            version_id=(int(state["version_id"]) if state["version_id"] else None),
            duplicate=duplicate,
            message="该文件已存在。" if duplicate else None,
        )

    def pending(self) -> tuple[WorkbenchImportResult, ...]:
        return tuple(
            self.describe(batch_id) for batch_id in self._repository.pending_batch_ids()
        )
