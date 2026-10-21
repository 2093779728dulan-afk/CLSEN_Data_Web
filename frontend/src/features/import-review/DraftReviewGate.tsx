import css from "./ReviewWorkspace.module.css";
import decisionCss from "./ReviewDecision.module.css";
import { Button, Dialog, Input, Select } from "../../design-system";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiRequestError,
  StableOperationKeyStore,
  requestApi,
  writeApi,
} from "../../api/client";
import type {
  AddRowRequest,
  ChangeRowStateRequest,
  CreateNoteRequest,
  DiscardDraftRequest,
  FinalizePublishedMoveRequest,
  MarkReadyRequest,
  PublishRequest,
  ReassignDraftDateRequest,
  ReassignmentTargetRequest,
  ReviseNoteRequest,
  RestoreFieldRequest,
  ReviewIssueRequest,
  RunValidationRequest,
  SetFieldRequest,
} from "../../api/generated";
import type {
  DraftHead,
  DraftMutation,
  PublicationCommandResponse,
  PublicationPointer,
  ReviewCell,
  ReviewIssue,
  ReviewNote,
  ReviewRow,
  ReviewWorkspace,
  ReportType,
  TypedFieldValue,
  ValidationRun,
  VersionSummary,
} from "../../api/types";
import {
  MergeDecisionMatrix,
  type MergeDecisionState,
} from "./MergeDecisionMatrix";
import { NoteRevisionEditor } from "./NoteRevisionEditor";
import { ReviewDataTable } from "./ReviewDataTable";
import {
  auditOperatorLabel,
  defaultAuditReason,
  reportTypeAuditLabel,
  type AuditOperator,
} from "./auditReason";
import type { DraftReviewContext, ReviewLocationHandoff } from "./workflowTypes";
import {
  prepareReturnDedupStaging,
  ReturnDedupStagingSupersededError,
} from "../workbench/workbenchApi";

type Props = {
  canFinalizePublishedMove?: boolean;
  context: DraftReviewContext;
  onDiscarded?: () => void;
  onPublished: (result: PublicationCommandResponse) => void;
  onReparseSource?: (batchId: number) => Promise<void>;
  onReportDateChanged?: (handoff: ReviewLocationHandoff) => void;
  operator?: AuditOperator;
};

type PendingDraftMoveCommand = {
  body: ReassignDraftDateRequest;
  inputFingerprint: string;
  operationKey: string;
  publication: PublicationPointer;
};

type DraftMoveDecision = "merge" | "replace" | "cancel";

type DraftMoveTargetPreview =
  | {
      kind: "empty";
      reportDate: string;
    }
  | {
      activeDraft: VersionSummary;
      kind: "active_draft";
      publication?: VersionSummary;
      reportDate: string;
    }
  | {
      kind: "published";
      publication: VersionSummary;
      reportDate: string;
    };

function reportTypeLabel(reportType: ReportType) {
  return reportType === "business_report" ? "经营报告" : "退货报告";
}

function draftPayload(head: DraftHead) {
  return {
    dataset_id: head.dataset_id,
    status: head.status,
    data_revision: head.data_revision,
    review_revision: head.review_revision,
    pointed_at: head.pointed_at,
  };
}

function versionExpectation(head: DraftHead) {
  return {
    version_id: head.version_id,
    data_revision: head.data_revision,
    review_revision: head.review_revision,
  };
}

function validationCounts(validation: ValidationRun, workspace?: ReviewWorkspace) {
  const workspaceValidation = workspace?.latest_full_validation;
  if (
    workspaceValidation?.id === validation.validation_run_id
    && workspaceValidation.issues.length > 0
  ) {
    return workspaceValidation.issues.reduce(
      (counts, issue) => ({
        blocking: counts.blocking + (issue.severity === "blocking" && issue.review.state !== "resolved" ? 1 : 0),
        warning: counts.warning + (issue.severity === "warning" && issue.review.state === "open" ? 1 : 0),
      }),
      { blocking: 0, warning: 0 },
    );
  }
  const stages = Object.values(validation.summary.stages);
  return stages.reduce(
    (counts, stage) => ({
      blocking: counts.blocking + stage.blocking_count,
      warning: counts.warning + stage.warning_count,
    }),
    { blocking: 0, warning: 0 },
  );
}

function workspaceValidation(workspace: ReviewWorkspace): ValidationRun | undefined {
  const validation = workspace.latest_full_validation;
  if (!validation?.is_current) return undefined;
  return {
    validation_run_id: validation.id,
    version_id: workspace.head.version_id,
    data_revision: validation.data_revision,
    status: validation.status,
    result: validation.result,
    data_digest: validation.data_digest,
    summary: validation.summary,
  };
}

function errorMessage(reason: unknown) {
  if (reason instanceof ApiRequestError && reason.status === 409) {
    return "草稿或发布指针已变化。请刷新当前日期后再继续，系统没有覆盖任何数据。";
  }
  return reason instanceof Error ? reason.message : "操作未完成。";
}

function PublicationDialog({
  context,
  head,
  validation,
  onCancel,
  onPublish,
  operator,
  publicationProgress,
}: {
  context: DraftReviewContext;
  head: DraftHead;
  validation: ValidationRun;
  onCancel: () => void;
  onPublish: (reason: string) => Promise<void>;
  operator?: AuditOperator;
  publicationProgress?: "building" | "ready" | "failed" | "superseded";
}) {
  const [reason, setReason] = useState(() => defaultAuditReason(
    operator,
    context.publicationMode === "published_move" ? "确认跨日期版本生效" : "确认发布审核版本",
    `${context.reportDate} ${reportTypeAuditLabel(context.reportType)} · 版本 v${head.version_no} · 校验 #${validation.validation_run_id}`,
  ));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const counts = validationCounts(validation);
  const isPublishedMove = context.publicationMode === "published_move";
  const submit = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await onPublish(reason);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) onCancel(); }} closeLabel="返回审核" eyebrow="最终发布闸门" title={isPublishedMove ? "跨日期生效确认" : "发布确认"} description={isPublishedMove ? "生效后，来源与目标日期的发布指针会在同一事务中切换。后续修正必须创建新修订。" : "发布后，查看人员将立即读取这个版本。后续修正必须创建新修订。"}>
        <dl className={css["confirmation-ledger"]}>
          <div><dt>报告日期</dt><dd>{context.reportDate}</dd></div>
          <div><dt>报表类型</dt><dd>{reportTypeLabel(context.reportType)}</dd></div>
          <div><dt>版本</dt><dd>v{head.version_no}</dd></div>
          <div><dt>数据修订</dt><dd>r{head.data_revision}</dd></div>
          <div><dt>行数</dt><dd>{validation.summary.row_count} 行</dd></div>
          <div><dt>警告</dt><dd>{counts.warning}</dd></div>
        </dl>
        <div className={css["confirmation-totals"]}>
          <span>校验合计</span>
          {Object.entries(validation.summary.totals).map(([name, value]) => (
            <code key={name}>{name} = {value}</code>
          ))}
        </div>
        <label className="field-stack">
          发布说明
          <textarea disabled={busy} onChange={(event) => setReason(event.target.value)} required rows={3} value={reason} />
        </label>
          {operator && <p className="stage-placeholder">操作人来源：当前登录会话 · {auditOperatorLabel(operator)}。服务器将按该会话写入发布审计。</p>}
          {publicationProgress === "building" && <p aria-live="polite">正在构建退货去重快照；完成前不会切换发布指针。</p>}
          {publicationProgress === "failed" && <p aria-live="polite">首次准备失败，正在按同一发布集合安全重试。</p>}
          {error && <p className="form-error" role="alert">{error}</p>}
        <div className="dialog-actions">
          <Button variant="secondary" disabled={busy} onClick={onCancel} type="button">返回审核</Button>
          <Button variant="primary" disabled={busy || !reason.trim()} onClick={() => { void submit(); }} type="button">
            {busy ? (isPublishedMove ? "正在生效…" : "正在发布…") : (isPublishedMove ? "确认跨日期生效" : "确认发布")}
          </Button>
        </div>
    </Dialog>
  );
}

export function DraftReviewGate({ canFinalizePublishedMove = false, context: initialContext, onDiscarded, onPublished, onReparseSource, onReportDateChanged, operator }: Props) {
  const [context, setContext] = useState(initialContext);
  const [head, setHead] = useState(initialContext.head);
  const [validation, setValidation] = useState<ValidationRun>();
  const [workspace, setWorkspace] = useState<ReviewWorkspace>();
  const [busyAction, setBusyAction] = useState<string>();
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [note, setNote] = useState("");
  const [noteVisibility, setNoteVisibility] = useState<"internal" | "viewer_visible">("internal");
  const [readyReason, setReadyReason] = useState(() => defaultAuditReason(
    operator,
    "确认审核结果并标记待发布",
    `${initialContext.reportDate} ${reportTypeAuditLabel(initialContext.reportType)} · 草稿 v${initialContext.head.version_no}`,
  ));
  const [targetDate, setTargetDate] = useState(initialContext.reportDate);
  const [moveReason, setMoveReason] = useState(() => defaultAuditReason(
    operator,
    "申请更改草稿所属日期",
    `${initialContext.reportDate} ${reportTypeAuditLabel(initialContext.reportType)} · 草稿 v${initialContext.head.version_no}`,
  ));
  const [draftMovePreview, setDraftMovePreview] = useState<DraftMoveTargetPreview>();
  const [draftMoveDecision, setDraftMoveDecision] = useState<DraftMoveDecision>();
  const [draftMoveMerge, setDraftMoveMerge] = useState<MergeDecisionState>({
    decisions: [],
    ready: false,
  });
  const [showPublish, setShowPublish] = useState(false);
  const [publicationProgress, setPublicationProgress] = useState<
    "building" | "ready" | "failed" | "superseded"
  >();
  const [discardReason, setDiscardReason] = useState(() => defaultAuditReason(
    operator,
    "废弃当前审核草稿",
    `${initialContext.reportDate} ${reportTypeAuditLabel(initialContext.reportType)} · 草稿 v${initialContext.head.version_no}`,
  ));
  const [discardConfirmed, setDiscardConfirmed] = useState(false);
  const [reparseBatchId, setReparseBatchId] = useState<number>();
  const [published, setPublished] = useState(false);
  const operationKeys = useRef(new StableOperationKeyStore()).current;
  const pendingDraftMove = useRef<PendingDraftMoveCommand | undefined>(undefined);

  const writeCommand = async <T,>(slot: string, path: string, body: unknown) => {
    const operationKey = operationKeys.forCommand(slot, path, body);
    const result = await writeApi<T>(path, { body, operationKey });
    operationKeys.complete(slot, operationKey);
    return result;
  };

  const resetPendingDraftMove = () => {
    operationKeys.reset("reassign-date");
    pendingDraftMove.current = undefined;
  };

  const clearDraftMovePreview = () => {
    setDraftMovePreview(undefined);
    setDraftMoveDecision(undefined);
    setDraftMoveMerge({ decisions: [], ready: false });
    resetPendingDraftMove();
  };

  const changeTargetDate = (value: string) => {
    setTargetDate(value);
    clearDraftMovePreview();
  };

  const changeMoveReason = (value: string) => {
    setMoveReason(value);
    resetPendingDraftMove();
  };

  const changeDraftMoveDecision = (value: DraftMoveDecision) => {
    setDraftMoveDecision(value);
    setDraftMoveMerge({ decisions: [], ready: false });
    resetPendingDraftMove();
  };

  const counts = useMemo(
    () => validation ? validationCounts(validation, workspace) : undefined,
    [validation, workspace],
  );

  useEffect(() => {
    const firstBatchId = workspace?.source_batches[0]?.batch_id;
    if (firstBatchId && !workspace?.source_batches.some((item) => item.batch_id === reparseBatchId)) {
      setReparseBatchId(firstBatchId);
    }
  }, [reparseBatchId, workspace?.source_batches]);

  const refreshWorkspace = useCallback(async (versionId = head.version_id, page = 1) => {
    const nextWorkspace = await requestApi<ReviewWorkspace>(
      `/api/drafts/${versionId}/review-workspace?page=${page}&page_size=50`,
    );
    setWorkspace(nextWorkspace);
    setHead(nextWorkspace.head);
    setContext((current) => ({
      ...current,
      head: nextWorkspace.head,
      publicationMode: nextWorkspace.publication_mode,
      publishedMove: nextWorkspace.published_move,
      reportDate: nextWorkspace.report_date,
      reportType: nextWorkspace.report_type,
      rulesetVersion: nextWorkspace.ruleset_version,
    }));
    setValidation(workspaceValidation(nextWorkspace));
    return nextWorkspace;
  }, [head.version_id]);

  useEffect(() => {
    void refreshWorkspace().catch((caught: unknown) => setError(errorMessage(caught)));
  }, [refreshWorkspace]);

  const runValidation = async () => {
    setBusyAction("validation");
    setError(undefined);
    setNotice(undefined);
    try {
      const path = `/api/validation-runs/${head.version_id}`;
      const body = {
        dataset_id: head.dataset_id,
        data_revision: head.data_revision,
        ruleset_version: context.rulesetVersion,
      } satisfies RunValidationRequest;
      const result = await writeCommand<ValidationRun>("validation", path, body);
      setValidation(result);
      await refreshWorkspace();
      setNotice(result.result === "passed" ? "完整校验已通过。" : "校验发现需要处理的项目。 ");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  const saveNote = async () => {
    setBusyAction("note");
    setError(undefined);
    setNotice(undefined);
    try {
      const path = `/api/drafts/${head.version_id}/notes`;
      const body = {
        expected_review_revision: head.review_revision,
        target_type: "version",
        body: note,
        visibility: noteVisibility,
      } satisfies CreateNoteRequest;
      await writeCommand("version-note", path, body);
      await refreshWorkspace();
      setNote("");
      setNotice("备注已追加到版本记录。历史内容不会被覆盖。");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  const markReady = async () => {
    if (!validation) return;
    setBusyAction("ready");
    setError(undefined);
    setNotice(undefined);
    try {
      const path = `/api/drafts/${head.version_id}/mark-ready`;
      const body = {
        ...draftPayload(head),
        validation_run_id: validation.validation_run_id,
        validation_data_digest: validation.data_digest,
        ruleset_version: context.rulesetVersion,
        confirmed_report_date: validation.summary.report_date,
        confirmed_report_type: validation.summary.report_type,
        confirmed_row_count: validation.summary.row_count,
        confirmed_totals: validation.summary.totals,
        reason: readyReason,
      } satisfies MarkReadyRequest;
      await writeCommand("mark-ready", path, body);
      await refreshWorkspace();
      setNotice("审核结果已确认，草稿进入待发布状态。");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  const discardDraft = async (reparse: boolean) => {
    if (!discardConfirmed || !discardReason.trim()) return;
    if (reparse && (!onReparseSource || !reparseBatchId)) return;
    setBusyAction("discard");
    setError(undefined);
    setNotice(undefined);
    try {
      const path = `/api/drafts/${head.version_id}/discard`;
      const body = {
        dataset_id: head.dataset_id,
        expected_active_draft: versionExpectation(head),
        reason: discardReason,
      } satisfies DiscardDraftRequest;
      const result = await writeCommand<DraftMutation>("discard-draft", path, body);
      if (result.status !== "discarded") {
        throw new Error("废弃 API 返回了无法识别的结果。 ");
      }
      if (reparse && onReparseSource && reparseBatchId) {
        await onReparseSource(reparseBatchId);
      } else {
        onDiscarded?.();
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  const commitDraftMove = async (
    preview: DraftMoveTargetPreview,
    decision?: Exclude<DraftMoveDecision, "cancel">,
  ) => {
    let target: ReassignmentTargetRequest;
    let publication: VersionSummary | undefined;
    if (preview.kind === "empty") {
      target = { target_kind: "empty", expected_dataset_id: null };
    } else if (preview.kind === "active_draft") {
      if (decision !== "merge") {
        throw new Error("目标日期已有活动草稿，只能选择合并或取消。");
      }
      publication = preview.publication;
      target = {
        target_kind: "active_draft",
        expected_dataset_id: preview.activeDraft.dataset_id,
        expected_active_draft: {
          version_id: preview.activeDraft.version_id,
          data_revision: preview.activeDraft.data_revision,
          review_revision: preview.activeDraft.review_revision,
        },
        expected_publication_version_id: preview.publication?.version_id ?? null,
        action: "merge",
      };
    } else {
      if (decision !== "merge" && decision !== "replace") {
        throw new Error("请选择合并、替换或取消。");
      }
      publication = preview.publication;
      target = {
        target_kind: "published",
        expected_dataset_id: preview.publication.dataset_id,
        expected_publication_version_id: preview.publication.version_id,
        strategy: decision,
      };
    }
    const body = {
      source_dataset_id: head.dataset_id,
      source_draft: versionExpectation(head),
      target_report_date: preview.reportDate,
      target,
      merge_decisions: decision === "merge" ? draftMoveMerge.decisions : [],
      reason: moveReason,
    } satisfies ReassignDraftDateRequest;
    const inputFingerprint = JSON.stringify(body);
    const path = `/api/drafts/${head.version_id}/reassign-date`;
    let pending = pendingDraftMove.current;
    if (!pending || pending.inputFingerprint !== inputFingerprint) {
      pending = {
        body,
        inputFingerprint,
        operationKey: operationKeys.forCommand("reassign-date", path, body),
        publication: publication
          ? {
              version_id: publication.version_id,
              published_at: publication.published_at,
            }
          : { version_id: null, published_at: null },
      };
      pendingDraftMove.current = pending;
    }
    const result = await writeApi<DraftMutation>(path, {
      body: pending.body,
      operationKey: pending.operationKey,
    });
    operationKeys.complete("reassign-date", pending.operationKey);
    pendingDraftMove.current = undefined;
    const nextPublication = pending.publication;
    setContext((current) => ({ ...current, reportDate: preview.reportDate, publication: nextPublication }));
    await refreshWorkspace(result.version_id);
    setTargetDate(preview.reportDate);
    setMoveReason("");
    setDraftMovePreview(undefined);
    setDraftMoveDecision(undefined);
    setDraftMoveMerge({ decisions: [], ready: false });
    setNotice(`草稿已移动到 ${preview.reportDate}；原日期与目标日期保持独立版本记录。`);
    onReportDateChanged?.({
      reportDate: preview.reportDate,
      reportType: context.reportType,
      versionId: result.version_id,
    });
  };

  const inspectDraftMoveTarget = async () => {
    setBusyAction("move");
    setError(undefined);
    setNotice(undefined);
    try {
      let preview = draftMovePreview;
      if (!preview) {
        const versions = await requestApi<VersionSummary[]>(
          `/api/versions?report_date=${encodeURIComponent(targetDate)}&report_type=${context.reportType}`,
        );
        const activeDraft = versions.find((item) => item.is_active_draft);
        const publication = versions.find((item) => item.is_current_publication);
        if (activeDraft) {
          preview = {
            activeDraft,
            kind: "active_draft",
            publication,
            reportDate: targetDate,
          };
        } else if (publication) {
          preview = { kind: "published", publication, reportDate: targetDate };
        } else if (versions.length === 0) {
          preview = { kind: "empty", reportDate: targetDate };
        } else {
          throw new Error("目标日期存在历史版本但没有活动指针，请由管理员检查后处理。");
        }
        resetPendingDraftMove();
        setDraftMoveDecision(undefined);
        setDraftMovePreview(preview);
      }
      if (preview.kind !== "empty") return;
      await commitDraftMove(preview);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  const confirmDraftMoveDecision = async () => {
    if (!draftMovePreview || draftMovePreview.kind === "empty" || !draftMoveDecision) return;
    if (draftMoveDecision === "cancel") {
      clearDraftMovePreview();
      setError(undefined);
      setNotice(`已取消更改日期；草稿仍属于 ${context.reportDate}，没有发送写请求。`);
      return;
    }
    setBusyAction("move");
    setError(undefined);
    setNotice(undefined);
    try {
      await commitDraftMove(draftMovePreview, draftMoveDecision);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  const setField = async (
    row: ReviewRow,
    cell: ReviewCell,
    value: TypedFieldValue,
    reason: string,
  ) => {
    setBusyAction("field");
    setError(undefined);
    try {
      const path = `/api/drafts/${head.version_id}/fields`;
      const body = {
        ...draftPayload(head),
        row_id: row.row_id,
        field_name: cell.field_name,
        value,
        reason,
      } satisfies SetFieldRequest;
      await writeCommand("set-field", path, body);
      await refreshWorkspace();
      setNotice(`字段 ${cell.field_name} 已修正；旧校验已失效。`);
    } catch (caught) {
      setError(errorMessage(caught));
      throw caught;
    } finally {
      setBusyAction(undefined);
    }
  };

  const restoreField = async (
    row: ReviewRow,
    cell: ReviewCell,
    source: Record<string, unknown>,
    reason: string,
  ) => {
    setBusyAction("field");
    setError(undefined);
    try {
      const path = `/api/drafts/${head.version_id}/fields/${encodeURIComponent(cell.field_name)}/restore`;
      const body = {
        ...draftPayload(head),
        row_id: row.row_id,
        ...source,
        reason,
      } as RestoreFieldRequest;
      await writeCommand("restore-field", path, body);
      await refreshWorkspace();
      setNotice(`字段 ${cell.field_name} 已恢复；旧校验已失效。`);
    } catch (caught) {
      setError(errorMessage(caught));
      throw caught;
    } finally {
      setBusyAction(undefined);
    }
  };

  const addRow = async (
    sourceBatchId: number,
    values: Record<string, TypedFieldValue>,
    reason: string,
  ) => {
    setBusyAction("row-add");
    setError(undefined);
    try {
      const body = {
        ...draftPayload(head),
        source_batch_id: sourceBatchId,
        values,
        reason,
      } satisfies AddRowRequest;
      const path = `/api/drafts/${head.version_id}/rows`;
      await writeCommand("add-row", path, body);
      const pageSize = workspace?.pagination.page_size ?? 50;
      const nextRowCount = (workspace?.pagination.total_rows ?? 0) + 1;
      await refreshWorkspace(head.version_id, Math.max(1, Math.ceil(nextRowCount / pageSize)));
      setNotice("纠错行已新增并关联来源批次；旧校验已失效。");
    } catch (caught) {
      setError(errorMessage(caught));
      throw caught;
    } finally {
      setBusyAction(undefined);
    }
  };

  const changeRowState = async (
    row: ReviewRow,
    operation: "exclude" | "restore",
    reason: string,
  ) => {
    setBusyAction("row-state");
    setError(undefined);
    try {
      const body = {
        ...draftPayload(head),
        operation,
        reason,
      } satisfies ChangeRowStateRequest;
      const path = `/api/drafts/${head.version_id}/rows/${row.row_id}/state`;
      await writeCommand("change-row-state", path, body);
      await refreshWorkspace(head.version_id, workspace?.pagination.page ?? 1);
      setNotice(operation === "exclude" ? `第 ${row.row_ordinal} 行已排除；旧校验已失效。` : `第 ${row.row_ordinal} 行已恢复；旧校验已失效。`);
    } catch (caught) {
      setError(errorMessage(caught));
      throw caught;
    } finally {
      setBusyAction(undefined);
    }
  };

  const reviseNote = async (
    currentNote: ReviewNote,
    bodyText: string,
    visibility: "internal" | "viewer_visible",
  ) => {
    setBusyAction("note-revision");
    setError(undefined);
    try {
      const body = {
        expected_review_revision: head.review_revision,
        target_type: currentNote.target_type,
        row_id: currentNote.row_id,
        field_name: currentNote.field_name,
        body: bodyText,
        visibility,
        expected_note_id: currentNote.note_id,
        expected_revision_number: currentNote.revision_number,
      } satisfies ReviseNoteRequest;
      const path = `/api/drafts/${head.version_id}/notes/${encodeURIComponent(currentNote.note_key)}/revisions`;
      await writeCommand("revise-note", path, body);
      await refreshWorkspace(head.version_id, workspace?.pagination.page ?? 1);
      setNotice(`备注 ${currentNote.note_key} 已保存为新修订，旧内容仍可审计。`);
    } catch (caught) {
      setError(errorMessage(caught));
      throw caught;
    } finally {
      setBusyAction(undefined);
    }
  };

  const addCellNote = async (
    row: ReviewRow,
    cell: ReviewCell,
    body: string,
    visibility: "internal" | "viewer_visible",
  ) => {
    setBusyAction("field-note");
    setError(undefined);
    try {
      const path = `/api/drafts/${head.version_id}/notes`;
      const requestBody = {
        expected_review_revision: head.review_revision,
        target_type: "field",
        row_id: row.row_id,
        field_name: cell.field_name,
        body,
        visibility,
      } satisfies CreateNoteRequest;
      await writeCommand("field-note", path, requestBody);
      await refreshWorkspace();
      setNotice("字段备注已追加，历史备注仍然保留。");
    } catch (caught) {
      setError(errorMessage(caught));
      throw caught;
    } finally {
      setBusyAction(undefined);
    }
  };

  const addRowNote = async (
    row: ReviewRow,
    body: string,
    visibility: "internal" | "viewer_visible",
  ) => {
    setBusyAction("row-note");
    setError(undefined);
    try {
      const path = `/api/drafts/${head.version_id}/notes`;
      const requestBody = {
        expected_review_revision: head.review_revision,
        target_type: "row",
        row_id: row.row_id,
        field_name: null,
        body,
        visibility,
      } satisfies CreateNoteRequest;
      await writeCommand("row-note", path, requestBody);
      await refreshWorkspace();
      setNotice("行备注已追加，历史备注仍然保留。");
    } catch (caught) {
      setError(errorMessage(caught));
      throw caught;
    } finally {
      setBusyAction(undefined);
    }
  };

  const reviewIssue = async (
    issue: ReviewIssue,
    action: "acknowledge" | "resolve" | "reopen",
    comment: string,
  ) => {
    const currentValidation = workspace?.latest_full_validation;
    if (!currentValidation) throw new Error("当前没有可审核的校验问题。");
    setBusyAction("issue");
    setError(undefined);
    try {
      const path = `/api/drafts/${head.version_id}/issues/${issue.id}/review`;
      const body = {
        ...draftPayload(head),
        validation_run_id: currentValidation.id,
        issue_severity: issue.severity,
        issue_requires_note: issue.requires_note,
        action,
        comment: comment.trim() || null,
      } satisfies ReviewIssueRequest;
      await writeCommand("review-issue", path, body);
      await refreshWorkspace();
      setNotice(action === "acknowledge" ? "警告已确认。" : action === "resolve" ? "阻断项已标记解决，请重新校验。" : "问题已重新打开。");
    } catch (caught) {
      setError(errorMessage(caught));
      throw caught;
    } finally {
      setBusyAction(undefined);
    }
  };

  const publish = async (reason: string) => {
    if (!validation) return;
    const expectedPublication = context.publication ?? { version_id: null, published_at: null };
    const expectedDraft = {
      version_id: head.version_id,
      status: head.status,
      data_revision: head.data_revision,
      review_revision: head.review_revision,
      pointed_at: head.pointed_at,
    };
    const validationExpectation = {
      run_id: validation.validation_run_id,
      version_id: validation.version_id,
      data_revision: validation.data_revision,
      ruleset_version: context.rulesetVersion,
      data_digest: validation.data_digest,
    };
    const confirmation = {
      confirmed_report_date: validation.summary.report_date,
      report_type: validation.summary.report_type,
      row_count: validation.summary.row_count,
      totals: Object.entries(validation.summary.totals).map(([field_name, value]) => ({ field_name, value })),
    };
    let path: string;
    let payload: FinalizePublishedMoveRequest | PublishRequest;
    let slot: "finalize-published-move" | "publish";
    let stagingDatasetId = head.dataset_id;
    let stagingReportDate = context.reportDate;
    if (context.publicationMode === "published_move") {
      if (!canFinalizePublishedMove || !context.publishedMove) {
        throw new Error("此跨日期移动必须由管理员使用最终生效流程完成，不能普通发布。");
      }
      path = `/api/admin/published-moves/${encodeURIComponent(context.publishedMove.revision_operation_token)}/finalize`;
      payload = {
        source_dataset_id: context.publishedMove.source_dataset_id,
        expected_source_publication: context.publishedMove.source_publication,
        target_dataset_id: head.dataset_id,
        expected_target_draft: expectedDraft,
        expected_target_publication: context.publishedMove.target_publication,
        validation: validationExpectation,
        confirmation,
        reason,
      } satisfies FinalizePublishedMoveRequest;
      slot = "finalize-published-move";
      stagingDatasetId = context.publishedMove.source_dataset_id;
      stagingReportDate = context.publishedMove.source_report_date;
    } else if (context.publicationMode === "ordinary") {
      path = `/api/datasets/${head.dataset_id}/publish`;
      payload = {
        expected_draft: expectedDraft,
        expected_publication: expectedPublication,
        validation: validationExpectation,
        confirmation,
        reason,
      } satisfies PublishRequest;
      slot = "publish";
    } else {
      throw new Error("服务端返回了未知发布模式；为避免错误发布，当前操作已停止。");
    }
    let result: PublicationCommandResponse | undefined;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const operationKey = operationKeys.forCommand(slot, path, payload);
      try {
        if (context.reportType === "return_report") {
          await prepareReturnDedupStaging(
            {
              datasetId: stagingDatasetId,
              operationToken: operationKey,
              proposedVersionId: head.version_id,
              reportDate: stagingReportDate,
            },
            setPublicationProgress,
          );
        }
        result = await writeApi<PublicationCommandResponse>(path, {
          body: payload,
          operationKey,
        });
        operationKeys.complete(slot, operationKey);
        break;
      } catch (caught) {
        const stale = caught instanceof ReturnDedupStagingSupersededError
          || (caught instanceof ApiRequestError && [
            "return_dedup_staging_superseded",
            "return_dedup_publication_revision_conflict",
          ].includes(caught.code));
        if (!stale || attempt > 0) throw caught;
        operationKeys.reset(slot);
        setPublicationProgress(undefined);
      }
    }
    if (!result) throw new Error("退货发布准备未能收敛，发布指针保持不变。");
    setPublicationProgress(undefined);
    setShowPublish(false);
    setPublished(true);
    setNotice(context.publicationMode === "published_move" ? `跨日期移动版本 v${head.version_no} 已生效` : `版本 v${head.version_no} 已发布`);
    onPublished(result);
  };

  if (published) {
    return (
      <section aria-live="polite" className={css["publication-receipt"]}>
        <span className={css["publication-receipt__seal"]}>发</span>
        <div><p className="section-kicker">发布回执</p><h2>{context.publicationMode === "published_move" ? `跨日期移动 v${head.version_no} 已生效` : `版本 v${head.version_no} 已发布`}</h2><p>{context.publicationMode === "published_move" && context.publishedMove ? `${context.publishedMove.source_report_date} → ${context.reportDate} 已原子切换发布指针。` : `${context.reportDate} · ${reportTypeLabel(context.reportType)} 已进入只读看板。`}</p></div>
      </section>
    );
  }

  return (
    <section className={css["draft-workbench"]}>
      <header className={css["workbench-heading"]}>
        <div>
          <p className="section-kicker">差异优先审核</p>
          <h2>草稿审核 · v{head.version_no}</h2>
          <p>{context.reportDate} · {reportTypeLabel(context.reportType)} · 数据修订 r{head.data_revision} / 审核修订 r{head.review_revision}</p>
        </div>
        <span className={`${css["state-stamp"]} ${css[`state-stamp--${head.status}`] ?? ""}`}>{head.status === "draft" ? "草稿" : "待发布"}</span>
      </header>

      {workspace ? (
        <ReviewDataTable
          busy={busyAction !== undefined}
          onAddCellNote={addCellNote}
          onAddRow={addRow}
          onAddRowNote={addRowNote}
          onChangeRowState={changeRowState}
          onPageChange={(page) => { void refreshWorkspace(head.version_id, page); }}
          onRestoreField={restoreField}
          onReviewIssue={reviewIssue}
          onReviseNote={reviseNote}
          onSetField={setField}
          operator={operator}
          workspace={workspace}
        />
      ) : <p className="workspace-loading">正在读取草稿行、差异与校验问题…</p>}

      <div className={css["review-grid"]}>
        <section className={`${css["review-stage"]} ${css["review-stage--note"]}`}>
          <div className={css["review-stage__heading"]}><span>01</span><div><h3>版本备注</h3><p>补充审核依据；备注只追加，不覆盖历史。</p></div></div>
          {workspace?.version_notes.length ? <ul className="version-note-list">{workspace.version_notes.map((item) => <li key={item.note_key}><p>{item.body}</p><span>{item.author_username} · {item.visibility === "internal" ? "仅审核人员" : "查看人员可见"} · 第 {item.revision_number} 版</span><NoteRevisionEditor busy={busyAction !== undefined} note={item} onRevise={reviseNote} /></li>)}</ul> : null}
          <label className="field-stack">备注内容<textarea onChange={(event) => setNote(event.target.value)} rows={3} value={note} /></label>
          <label className="field-stack">可见范围<Select onChange={(event) => setNoteVisibility(event.target.value as typeof noteVisibility)} value={noteVisibility}><option value="internal">仅审核人员</option><option value="viewer_visible">查看人员可见</option></Select></label>
          <Button variant="secondary" disabled={busyAction === "note" || !note.trim()} onClick={() => { void saveNote(); }} type="button">{busyAction === "note" ? "正在保存…" : "追加备注"}</Button>
        </section>

        <section className={css["review-stage"]}>
          <div className={css["review-stage__heading"]}><span>02</span><div><h3>校验草稿</h3><p>检查行数、合计、字段格式和来源差异。</p></div></div>
          {!validation ? (
            <Button variant="primary" disabled={busyAction === "validation" || head.status !== "draft"} onClick={() => { void runValidation(); }} type="button">{busyAction === "validation" ? "正在校验…" : "运行草稿校验"}</Button>
          ) : (
            <div className={css["validation-receipt"]} aria-live="polite">
              <div className={css["validation-receipt__counts"]}><strong className={counts?.blocking ? css["count--blocking"] : ""}>阻断项 {counts?.blocking}</strong><strong className={counts?.warning ? css["count--warning"] : ""}>警告 {counts?.warning}</strong><strong>行数 {validation.summary.row_count}</strong></div>
              <dl>{Object.entries(validation.summary.totals).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
              <Button variant="quiet" disabled={busyAction === "validation" || head.status !== "draft"} onClick={() => { void runValidation(); }} type="button">重新校验</Button>
            </div>
          )}
          {counts && counts.blocking > 0 && <p className={`${css["gate-message"]} ${css["gate-message--blocking"]}`}>先修正阻断项，再重新运行校验。</p>}
          {counts && counts.blocking === 0 && counts.warning > 0 && <p className={`${css["gate-message"]} ${css["gate-message--warning"]}`}>需要逐项确认警告后再继续发布。</p>}
        </section>

        <section className={css["review-stage"]}>
          <div className={css["review-stage__heading"]}><span>03</span><div><h3>确认校验结果</h3><p>核对报告日期、类型和校验合计后留痕确认。</p></div></div>
          {validation && validation.result === "passed" && counts?.blocking === 0 && counts.warning === 0 && head.status === "draft" ? <>
            <label className="field-stack">审核确认说明<textarea onChange={(event) => setReadyReason(event.target.value)} rows={3} value={readyReason} /></label>
            {operator && <p className="stage-placeholder">操作人来源：当前登录会话 · {auditOperatorLabel(operator)}。</p>}
            <Button variant="primary" disabled={busyAction === "ready" || !readyReason.trim()} onClick={() => { void markReady(); }} type="button">{busyAction === "ready" ? "正在确认…" : "确认结果并标记待发布"}</Button>
          </> : head.status === "ready_for_publish" ? <p className={`${css["gate-message"]} ${css["gate-message--passed"]}`}>已锁定本次校验回执，可以进入最终发布确认。</p> : <p className="stage-placeholder">先完成草稿校验，通过后即可填写确认说明。</p>}
        </section>
      </div>

      <details className={css["draft-maintenance"]} name="draft-maintenance">
        <summary>调整草稿日期</summary>
        <p>系统会先读取目标日期的活动草稿和发布版本；有冲突时由你明确选择，不会自动覆盖。</p>
        <div className={css["draft-maintenance__form"]}>
          <label className="field-stack">目标报告日<Input onChange={(event) => changeTargetDate(event.target.value)} type="date" value={targetDate} /></label>
          <label className="field-stack field-stack--wide">移动原因<textarea onChange={(event) => changeMoveReason(event.target.value)} rows={3} value={moveReason} /></label>
          {operator && <p className={`stage-placeholder ${css["draft-maintenance__operator"]}`}>默认说明已带入当前操作人和草稿来源；目标日期会随本次命令一并记录。</p>}
          {(!draftMovePreview || draftMovePreview.kind === "empty") && <Button variant="secondary" disabled={busyAction === "move" || targetDate === context.reportDate || !moveReason.trim()} onClick={() => { void inspectDraftMoveTarget(); }} type="button">{busyAction === "move" ? "正在检查目标日…" : "检查目标日期"}</Button>}
        </div>
        {draftMovePreview && draftMovePreview.kind !== "empty" && (
          <fieldset className={`${decisionCss["target-conflict"]} ${decisionCss["target-conflict--wide"]}`}>
            <legend>目标日期已有数据，请选择处理方式</legend>
            <div className={decisionCss["target-conflict__ledger"]}>
              <span>{draftMovePreview.reportDate} · {reportTypeLabel(context.reportType)}</span>
              {draftMovePreview.kind === "active_draft" && <strong>活动草稿 v{draftMovePreview.activeDraft.version_no}</strong>}
              {draftMovePreview.kind === "active_draft" && draftMovePreview.publication && <strong>发布版本 v{draftMovePreview.publication.version_no}</strong>}
              {draftMovePreview.kind === "published" && <strong>发布版本 v{draftMovePreview.publication.version_no}</strong>}
            </div>
            <label className={decisionCss["target-choice"]}><input aria-label={draftMovePreview.kind === "active_draft" ? "合并到目标活动草稿" : "合并目标发布版本"} checked={draftMoveDecision === "merge"} disabled={busyAction === "move"} name="draft-move-decision" onChange={() => changeDraftMoveDecision("merge")} type="radio" /><span><strong>{draftMovePreview.kind === "active_draft" ? "合并到目标活动草稿" : "合并目标发布版本"}</strong><small>保留目标数据并加入当前草稿。逐行冲突不会自动覆盖；当前没有逐行决定时，服务端会阻断并要求人工处理。</small></span></label>
            {draftMovePreview.kind === "published" && <label className={decisionCss["target-choice"]}><input aria-label="替换目标发布版本" checked={draftMoveDecision === "replace"} disabled={busyAction === "move"} name="draft-move-decision" onChange={() => changeDraftMoveDecision("replace")} type="radio" /><span><strong>替换目标发布版本</strong><small>移动后的草稿仅采用当前草稿数据；目标发布版本仍保留在版本历史中。</small></span></label>}
            <label className={decisionCss["target-choice"]}><input aria-label="取消，保留当前所属日期" checked={draftMoveDecision === "cancel"} disabled={busyAction === "move"} name="draft-move-decision" onChange={() => changeDraftMoveDecision("cancel")} type="radio" /><span><strong>取消，保留当前所属日期</strong><small>不移动草稿，不发送写请求。</small></span></label>
            {draftMoveDecision === "merge" && <MergeDecisionMatrix disabled={busyAction === "move"} onStateChange={setDraftMoveMerge} operator={operator} sourceId={head.version_id} sourceKind="dataset_version" targetVersionId={draftMovePreview.kind === "active_draft" ? draftMovePreview.activeDraft.version_id : draftMovePreview.publication.version_id} />}
            <Button variant={draftMoveDecision === "cancel" ? "secondary" : "primary"} disabled={busyAction === "move" || !draftMoveDecision || !moveReason.trim() || (draftMoveDecision === "merge" && !draftMoveMerge.ready)} onClick={() => { void confirmDraftMoveDecision(); }} type="button">{busyAction === "move" ? "正在处理…" : draftMoveDecision === "cancel" ? "确认取消" : "按所选方式更改日期"}</Button>
          </fieldset>
        )}
      </details>

      {(onDiscarded || onReparseSource) && (
        <details className={`${css["draft-maintenance"]} ${css["draft-disposition"]}`} name="draft-maintenance">
          <summary>重新解析或废弃草稿</summary>
          <p>旧草稿、人工修改和备注会完整保留在审计历史中，但不会自动套用到新的解析结果。</p>
          {onReparseSource && workspace && workspace.source_batches.length > 0 && <label className="field-stack">重新解析的来源批次<Select onChange={(event) => setReparseBatchId(Number(event.target.value))} value={reparseBatchId}>{workspace.source_batches.map((source) => <option key={source.batch_id} value={source.batch_id}>导入批次 #{source.batch_id}</option>)}</Select></label>}
          <label className="field-stack">处置原因<textarea onChange={(event) => { setDiscardReason(event.target.value); operationKeys.reset("discard-draft"); }} rows={3} value={discardReason} /></label>
          {operator && <p className="stage-placeholder">操作人来源：当前登录会话 · {auditOperatorLabel(operator)}。</p>}
          <label className="check-field"><input checked={discardConfirmed} onChange={(event) => setDiscardConfirmed(event.target.checked)} type="checkbox" />我确认当前草稿将被废弃，历史记录不会删除。</label>
          <div className={`dialog-actions ${css["draft-disposition__actions"]}`}>
            {onDiscarded && <Button variant="secondary" disabled={busyAction === "discard" || !discardConfirmed || !discardReason.trim()} onClick={() => { void discardDraft(false); }} type="button">只废弃当前草稿</Button>}
            {onReparseSource && reparseBatchId && <Button variant="primary" disabled={busyAction === "discard" || !discardConfirmed || !discardReason.trim()} onClick={() => { void discardDraft(true); }} type="button">废弃并重新解析来源文件</Button>}
          </div>
        </details>
      )}

      {notice && <p className="form-notice" aria-live="polite">{notice}</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
      {head.status === "ready_for_publish" && validation && (
        context.publicationMode === "published_move" && !canFinalizePublishedMove ? (
          <div aria-live="polite" className={css["publish-gate"]} role="status"><div><p className="section-kicker">04 · 管理员生效</p><strong>审核已完成，需管理员最终生效</strong><span>这是已发布数据的跨日期移动。来源日期仍保持发布，当前账号不能使用普通发布完成切换。</span></div></div>
        ) : context.publicationMode === "published_move" && !context.publishedMove ? (
          <div className={css["publish-gate"]} role="alert"><div><p className="section-kicker">04 · 管理员生效</p><strong>无法恢复跨日期移动上下文</strong><span>请刷新当前日期；在服务端上下文恢复前不会开放普通发布。</span></div></div>
        ) : (
          <div className={css["publish-gate"]}><div><p className="section-kicker">04 · {context.publicationMode === "published_move" ? "跨日期生效" : "发布"}</p><strong>{context.publicationMode === "published_move" ? "跨日期移动已通过审核闸门" : "草稿已通过审核闸门"}</strong><span>{context.publicationMode === "published_move" ? "最终确认会同时切换来源和目标日期的发布指针。" : "最后一次确认不会修改数据，只切换该日期的发布指针。"}</span></div><Button variant="primary" onClick={() => setShowPublish(true)} type="button">{context.publicationMode === "published_move" ? "打开跨日期生效确认" : "打开发布确认"}</Button></div>
        )
      )}
      {showPublish && validation && <PublicationDialog context={context} head={head} onCancel={() => setShowPublish(false)} onPublish={publish} operator={operator} publicationProgress={publicationProgress} validation={validation} />}
    </section>
  );
}
