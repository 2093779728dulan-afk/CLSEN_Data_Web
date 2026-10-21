"""Application service for batch-review preflight and state changes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid5

from app.batch_review.eligibility import evaluate_candidate
from app.batch_review.repository import (
    BatchReviewItemRecord,
    BatchReviewRunRecord,
    CandidateFacts,
    ClaimedItem,
    DraftState,
    PreflightItem,
)
from app.batch_review.types import (
    AdvanceBatchReviewItemCommand,
    BatchReviewItemStatus,
    BatchReviewPermissionDenied,
    BatchReviewReasonCode,
    BatchReviewRunStatus,
    ChangeBatchReviewRunStateCommand,
    ConfirmBatchReviewCommand,
    CreatePreflightCommand,
    EligibilityDecision,
    RetryBatchReviewItemCommand,
    TargetKey,
)
from app.datasets.types import (
    DatasetCommitOutcomeUnknown,
    DatasetPermissionDenied,
    DatasetTransactionBusy,
)
from app.review.types import (
    MarkReadyCommand,
    ReviewCommitOutcomeUnknown,
    ReviewError,
    ReviewTransactionBusy,
)
from app.validation.types import (
    RunValidationCommand,
    ValidationCommitOutcomeUnknown,
    ValidationPersistenceError,
    ValidationRunReceipt,
    ValidationTransactionBusy,
)
from app.workbench.import_orchestration import (
    OrchestrateImportCommand,
    WorkbenchImportResult,
)

CONFIRMATION_STATEMENT_VERSION = "batch-review-confirmation-v1"


@dataclass(frozen=True, slots=True)
class BatchReviewSummary:
    total: int
    eligible: int
    active: int
    ready_for_publish: int
    manual_review: int
    failed: int
    skipped: int


@dataclass(frozen=True, slots=True)
class BatchReviewRunView:
    id: int
    site_id: int
    status: BatchReviewRunStatus
    revision: int
    summary: BatchReviewSummary
    items: tuple[BatchReviewItemRecord, ...]
    allowed_actions: tuple[str, ...]


class _Repository(Protocol):
    def load_candidates(
        self,
        site_id: int,
        batch_ids: tuple[int, ...],
        actor_roles: frozenset[str],
    ) -> tuple[CandidateFacts, ...]: ...

    def create_preflight(
        self,
        command: CreatePreflightCommand,
        items: tuple[PreflightItem, ...],
    ) -> BatchReviewRunRecord: ...

    def get_run(self, run_id: int, site_id: int) -> BatchReviewRunRecord: ...

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
    ) -> BatchReviewRunRecord: ...

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
    ) -> BatchReviewRunRecord: ...

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
    ) -> BatchReviewRunRecord: ...

    def claim_item(
        self,
        *,
        run_id: int,
        item_id: int,
        site_id: int,
        actor_user_id: int,
        operation_token: UUID,
        operation_digest: bytes,
    ) -> ClaimedItem: ...

    def record_item_stage(
        self,
        *,
        run_id: int,
        item_id: int,
        lease_token: UUID,
        lease_fence: int,
        status: BatchReviewItemStatus,
        domain_ids: Mapping[str, int | None] | None = None,
    ) -> BatchReviewItemRecord: ...

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
    ) -> BatchReviewRunRecord: ...

    def load_draft_state(
        self,
        *,
        run_id: int,
        item_id: int,
        site_id: int,
    ) -> DraftState: ...


class _ImportOrchestrator(Protocol):
    def run(
        self,
        command: OrchestrateImportCommand,
        *,
        on_stage: Callable[[str, Mapping[str, int]], None] | None = None,
    ) -> WorkbenchImportResult: ...


class _ValidationRunner(Protocol):
    def run_validation(self, command: RunValidationCommand) -> ValidationRunReceipt: ...


class _ReviewRunner(Protocol):
    def mark_ready(self, command: MarkReadyCommand) -> object: ...


def child_operation_token(operation_token: UUID, stage: str) -> UUID:
    return uuid5(operation_token, stage)


def validation_is_clean(receipt: ValidationRunReceipt) -> bool:
    return (
        receipt.status == "succeeded"
        and receipt.result == "passed"
        and receipt.summary.parse_fidelity.warning_count == 0
        and receipt.summary.parse_fidelity.blocking_count == 0
        and receipt.summary.draft_explainability.warning_count == 0
        and receipt.summary.draft_explainability.blocking_count == 0
    )


class BatchReviewService:
    def __init__(
        self,
        repository: _Repository,
        *,
        orchestrator: _ImportOrchestrator | None = None,
        validation: _ValidationRunner | None = None,
        review: _ReviewRunner | None = None,
    ) -> None:
        self._repository = repository
        self._orchestrator = orchestrator
        self._validation = validation
        self._review = review

    def create_preflight(
        self,
        command: CreatePreflightCommand,
    ) -> BatchReviewRunView:
        self._require_writer(command.actor_roles)
        facts = sorted(
            self._repository.load_candidates(
                command.site_id,
                command.batch_ids,
                command.actor_roles,
            ),
            key=lambda item: item.candidate.batch_id,
        )
        seen_targets: set[TargetKey] = set()
        items: list[PreflightItem] = []
        for fact in facts:
            decision = evaluate_candidate(fact.candidate, fact.target, seen_targets)
            items.append(PreflightItem(fact, decision))
            if decision.eligible and decision.target_key is not None:
                seen_targets.add(decision.target_key)
        return self._view(self._repository.create_preflight(command, tuple(items)))

    def get_run(self, run_id: int, site_id: int) -> BatchReviewRunView:
        return self._view(self._repository.get_run(run_id, site_id))

    def confirm(self, command: ConfirmBatchReviewCommand) -> BatchReviewRunView:
        if command.confirmation_statement_version != CONFIRMATION_STATEMENT_VERSION:
            raise ValueError("confirmation statement version is not current")
        run = self._repository.get_run(command.run_id, command.site_id)
        selected = set(command.selected_item_ids)
        selected_items = tuple(item for item in run.items if item.id in selected)
        if len(selected_items) != len(selected):
            raise ValueError("selected item is not part of this run")
        batch_ids = tuple(sorted(item.batch_id for item in selected_items))
        facts = self._repository.load_candidates(
            command.site_id,
            batch_ids,
            frozenset({"data_manager"}),
        )
        facts_by_batch = {item.candidate.batch_id: item for item in facts}
        seen_targets: set[TargetKey] = set()
        refreshed: dict[int, EligibilityDecision] = {}
        for item in sorted(selected_items, key=lambda value: value.batch_id):
            fact = facts_by_batch[item.batch_id]
            decision = evaluate_candidate(fact.candidate, fact.target, seen_targets)
            refreshed[item.id] = decision
            if decision.eligible and decision.target_key is not None:
                seen_targets.add(decision.target_key)
        record = self._repository.confirm_run(
            run_id=command.run_id,
            site_id=command.site_id,
            actor_user_id=command.actor_user_id,
            expected_revision=command.expected_revision,
            selected_item_ids=command.selected_item_ids,
            refreshed=refreshed,
            confirmation_statement_version=command.confirmation_statement_version,
            operation_token=command.operation_token,
            operation_digest=command.operation_digest,
        )
        return self._view(record)

    @staticmethod
    def requested_run_transition(
        command: ChangeBatchReviewRunStateCommand,
    ) -> tuple[BatchReviewRunStatus, BatchReviewRunStatus]:
        if command.action == "pause":
            return BatchReviewRunStatus.RUNNING, BatchReviewRunStatus.PAUSED
        return BatchReviewRunStatus.PAUSED, BatchReviewRunStatus.RUNNING

    def pause(
        self,
        command: ChangeBatchReviewRunStateCommand,
    ) -> BatchReviewRunView:
        if command.action != "pause":
            raise ValueError("pause requires a pause command")
        return self._change_state(command)

    def resume(
        self,
        command: ChangeBatchReviewRunStateCommand,
    ) -> BatchReviewRunView:
        if command.action != "resume":
            raise ValueError("resume requires a resume command")
        return self._change_state(command)

    def _change_state(
        self,
        command: ChangeBatchReviewRunStateCommand,
    ) -> BatchReviewRunView:
        current, target = self.requested_run_transition(command)
        return self._view(
            self._repository.change_run_state(
                run_id=command.run_id,
                site_id=command.site_id,
                actor_user_id=command.actor_user_id,
                expected_revision=command.expected_revision,
                current=current,
                target=target,
                operation_token=command.operation_token,
                operation_digest=command.operation_digest,
            )
        )

    def retry_item(
        self,
        command: RetryBatchReviewItemCommand,
    ) -> BatchReviewRunView:
        return self._view(
            self._repository.retry_item(
                run_id=command.run_id,
                item_id=command.item_id,
                site_id=command.site_id,
                actor_user_id=command.actor_user_id,
                expected_revision=command.expected_revision,
                operation_token=command.operation_token,
                operation_digest=command.operation_digest,
            )
        )

    def advance_item(
        self,
        command: AdvanceBatchReviewItemCommand,
    ) -> BatchReviewItemRecord:
        if (
            self._orchestrator is None
            or self._validation is None
            or self._review is None
        ):
            raise RuntimeError("batch-review advance dependencies are not configured")
        claim = self._repository.claim_item(
            run_id=command.run_id,
            item_id=command.item_id,
            site_id=command.site_id,
            actor_user_id=command.actor_user_id,
            operation_token=command.operation_token,
            operation_digest=command.operation_digest,
        )
        if claim.recovered and claim.item.status in {
            BatchReviewItemStatus.READY_FOR_PUBLISH,
            BatchReviewItemStatus.MANUAL_REVIEW,
            BatchReviewItemStatus.FAILED,
        }:
            return claim.item

        def on_stage(stage: str, domain_ids: Mapping[str, int]) -> None:
            status = {
                "parsing": BatchReviewItemStatus.PARSING,
                "materializing": BatchReviewItemStatus.MATERIALIZING,
            }.get(stage)
            if status is not None:
                self._repository.record_item_stage(
                    run_id=command.run_id,
                    item_id=command.item_id,
                    lease_token=claim.lease_token,
                    lease_fence=claim.lease_fence,
                    status=status,
                    domain_ids=domain_ids,
                )

        try:
            facts = self._repository.load_candidates(
                command.site_id,
                (claim.item.batch_id,),
                frozenset({"data_manager"}),
            )[0]
            candidate = facts.candidate
            if (
                candidate.report_date is None
                or candidate.report_type is None
                or candidate.encoding is None
            ):
                return self._finish_manual(
                    command,
                    claim,
                    BatchReviewReasonCode.RECOGNITION_UNCERTAIN,
                    "确认后的日期、类型或编码已不可用。",
                )
            imported = self._orchestrator.run(
                OrchestrateImportCommand(
                    batch_id=candidate.batch_id,
                    sha256_hex=facts.sha256_hex,
                    actor_user_id=command.actor_user_id,
                    operation_token=child_operation_token(
                        command.operation_token, "import"
                    ),
                    confirmed_report_type=candidate.report_type,
                    confirmed_report_date=candidate.report_date,
                    confirmed_encoding=candidate.encoding,
                ),
                on_stage=on_stage,
            )
            if imported.status in {"confirmation_required", "conflict_required"}:
                return self._finish_manual(
                    command,
                    claim,
                    BatchReviewReasonCode.TARGET_CHANGED,
                    "导入事实或目标状态已变化, 请人工处理。",
                )
            if imported.status == "failed":
                return self._finish_failed(
                    command,
                    claim,
                    "解析未能生成可用草稿。",
                    retry_allowed=False,
                )
            if (
                imported.status != "workspace_ready"
                or imported.dataset_id is None
                or imported.version_id is None
            ):
                return self._finish_unknown(command, claim)
            domain_ids = {
                "parse_attempt_id": imported.parse_attempt_id,
                "parse_baseline_id": imported.parse_baseline_id,
                "dataset_id": imported.dataset_id,
                "version_id": imported.version_id,
            }
            self._repository.record_item_stage(
                run_id=command.run_id,
                item_id=command.item_id,
                lease_token=claim.lease_token,
                lease_fence=claim.lease_fence,
                status=BatchReviewItemStatus.VALIDATING,
                domain_ids=domain_ids,
            )
            before = self._repository.load_draft_state(
                run_id=command.run_id,
                item_id=command.item_id,
                site_id=command.site_id,
            )
            receipt = self._validation.run_validation(
                RunValidationCommand(
                    dataset_id=before.head.dataset_id,
                    version_id=before.head.version_id,
                    data_revision=before.head.data_revision,
                    ruleset_version=before.ruleset_version,
                    actor_user_id=command.actor_user_id,
                    operation_token=child_operation_token(
                        command.operation_token, "validation"
                    ),
                )
            )
            domain_ids["validation_run_id"] = receipt.validation_run_id
            if not validation_is_clean(receipt):
                reason = (
                    BatchReviewReasonCode.VALIDATION_BLOCKING
                    if receipt.summary.parse_fidelity.blocking_count
                    + receipt.summary.draft_explainability.blocking_count
                    else BatchReviewReasonCode.VALIDATION_WARNING
                )
                return self._finish_manual(
                    command,
                    claim,
                    reason,
                    "完整校验包含警告或阻断, 请人工审核。",
                    domain_ids=domain_ids,
                )
            after = self._repository.load_draft_state(
                run_id=command.run_id,
                item_id=command.item_id,
                site_id=command.site_id,
            )
            if (
                before != after
                or receipt.dataset_id != before.head.dataset_id
                or receipt.version_id != before.head.version_id
                or receipt.data_revision != before.head.data_revision
                or receipt.review_revision != before.head.review_revision
                or receipt.ruleset_version != before.ruleset_version
            ):
                return self._finish_manual(
                    command,
                    claim,
                    BatchReviewReasonCode.TARGET_CHANGED,
                    "校验后草稿或审核修订发生变化。",
                    domain_ids=domain_ids,
                )
            result = self._review.mark_ready(
                MarkReadyCommand(
                    head=before.head,
                    validation_run_id=receipt.validation_run_id,
                    validation_data_digest=receipt.data_digest,
                    ruleset_version=receipt.ruleset_version,
                    confirmed_report_date=receipt.summary.report_date,
                    confirmed_report_type=receipt.summary.report_type,
                    confirmed_row_count=receipt.summary.row_count,
                    confirmed_totals=receipt.summary.totals,
                    actor_user_id=command.actor_user_id,
                    operation_token=child_operation_token(
                        command.operation_token, "mark-ready"
                    ),
                    reason=(
                        f"批量审核任务 {command.run_id} 项目 {command.item_id} "
                        "通过完整校验"
                    ),
                )
            )
            if getattr(result, "status", None) != "ready_for_publish":
                return self._finish_unknown(command, claim, domain_ids=domain_ids)
            return self._finish(
                command,
                claim,
                status=BatchReviewItemStatus.READY_FOR_PUBLISH,
                domain_ids=domain_ids,
            )
        except (
            DatasetCommitOutcomeUnknown,
            ValidationCommitOutcomeUnknown,
            ReviewCommitOutcomeUnknown,
        ):
            return self._finish_unknown(command, claim)
        except (
            DatasetTransactionBusy,
            ValidationTransactionBusy,
            ReviewTransactionBusy,
        ):
            return self._finish_failed(
                command,
                claim,
                "服务暂时繁忙, 可稍后重试。",
                retry_allowed=True,
            )
        except DatasetPermissionDenied:
            return self._finish_manual(
                command,
                claim,
                BatchReviewReasonCode.PERMISSION_DENIED,
                "当前操作权限已变化。",
            )
        except ValidationPersistenceError, ReviewError:
            return self._finish_manual(
                command,
                claim,
                BatchReviewReasonCode.TARGET_CHANGED,
                "草稿或校验状态已变化, 请人工处理。",
            )

    def _finish_manual(
        self,
        command: AdvanceBatchReviewItemCommand,
        claim: ClaimedItem,
        reason_code: BatchReviewReasonCode,
        message: str,
        *,
        domain_ids: Mapping[str, int | None] | None = None,
    ) -> BatchReviewItemRecord:
        return self._finish(
            command,
            claim,
            status=BatchReviewItemStatus.MANUAL_REVIEW,
            reason_code=reason_code,
            reason_message=message,
            domain_ids=domain_ids,
        )

    def _finish_failed(
        self,
        command: AdvanceBatchReviewItemCommand,
        claim: ClaimedItem,
        message: str,
        *,
        retry_allowed: bool,
    ) -> BatchReviewItemRecord:
        return self._finish(
            command,
            claim,
            status=BatchReviewItemStatus.FAILED,
            reason_code=BatchReviewReasonCode.RETRYABLE_FAILURE,
            reason_message=message,
            retry_allowed=retry_allowed,
        )

    def _finish_unknown(
        self,
        command: AdvanceBatchReviewItemCommand,
        claim: ClaimedItem,
        *,
        domain_ids: Mapping[str, int | None] | None = None,
    ) -> BatchReviewItemRecord:
        return self._finish(
            command,
            claim,
            status=BatchReviewItemStatus.FAILED,
            reason_code=BatchReviewReasonCode.OUTCOME_UNKNOWN,
            reason_message="正在确认服务器提交结果, 请刷新任务状态。",
            outcome_unknown=True,
            domain_ids=domain_ids,
        )

    def _finish(
        self,
        command: AdvanceBatchReviewItemCommand,
        claim: ClaimedItem,
        *,
        status: BatchReviewItemStatus,
        reason_code: BatchReviewReasonCode | None = None,
        reason_message: str | None = None,
        retry_allowed: bool = False,
        outcome_unknown: bool = False,
        domain_ids: Mapping[str, int | None] | None = None,
    ) -> BatchReviewItemRecord:
        run = self._repository.finish_item(
            run_id=command.run_id,
            item_id=command.item_id,
            site_id=command.site_id,
            actor_user_id=command.actor_user_id,
            operation_token=command.operation_token,
            lease_token=claim.lease_token,
            lease_fence=claim.lease_fence,
            status=status,
            reason_code=reason_code,
            reason_message=reason_message,
            retry_allowed=retry_allowed,
            outcome_unknown=outcome_unknown,
            domain_ids=domain_ids,
        )
        return next(item for item in run.items if item.id == command.item_id)

    @staticmethod
    def _require_writer(roles: frozenset[str]) -> None:
        if not roles.intersection({"admin", "data_manager"}):
            raise BatchReviewPermissionDenied("batch review requires a write role")

    @staticmethod
    def summarize_statuses(
        statuses: tuple[BatchReviewItemStatus, ...],
    ) -> BatchReviewSummary:
        active_statuses = {
            BatchReviewItemStatus.QUEUED,
            BatchReviewItemStatus.PARSING,
            BatchReviewItemStatus.MATERIALIZING,
            BatchReviewItemStatus.VALIDATING,
        }
        return BatchReviewSummary(
            total=len(statuses),
            eligible=sum(
                status is BatchReviewItemStatus.ELIGIBLE for status in statuses
            ),
            active=sum(status in active_statuses for status in statuses),
            ready_for_publish=sum(
                status is BatchReviewItemStatus.READY_FOR_PUBLISH for status in statuses
            ),
            manual_review=sum(
                status is BatchReviewItemStatus.MANUAL_REVIEW for status in statuses
            ),
            failed=sum(status is BatchReviewItemStatus.FAILED for status in statuses),
            skipped=sum(status is BatchReviewItemStatus.SKIPPED for status in statuses),
        )

    @classmethod
    def _view(cls, record: BatchReviewRunRecord) -> BatchReviewRunView:
        summary = cls.summarize_statuses(tuple(item.status for item in record.items))
        actions: list[str] = []
        if record.status is BatchReviewRunStatus.PREVIEW and summary.eligible:
            actions.append("confirm")
        if record.status is BatchReviewRunStatus.RUNNING:
            actions.append("pause")
        if record.status is BatchReviewRunStatus.PAUSED:
            actions.append("resume")
        if any(item.retry_allowed for item in record.items):
            actions.append("retry")
        return BatchReviewRunView(
            id=record.id,
            site_id=record.site_id,
            status=record.status,
            revision=record.revision,
            summary=summary,
            items=record.items,
            allowed_actions=tuple(actions),
        )
