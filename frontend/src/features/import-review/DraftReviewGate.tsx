import { DraftReviewView } from "./DraftReviewView";
import { PublicationDialog } from "./DraftPublicationDialog";
import { errorMessage, validationCounts } from "./draftReviewPresentation";
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

  return <DraftReviewView
    context={context}
    head={head}
    published={published}
    workspace={workspace}
    validation={validation}
    counts={counts}
    busyAction={busyAction}
    error={error}
    notice={notice}
    operator={operator}
    note={note}
    noteVisibility={noteVisibility}
    readyReason={readyReason}
    targetDate={targetDate}
    moveReason={moveReason}
    draftMovePreview={draftMovePreview}
    draftMoveDecision={draftMoveDecision}
    draftMoveMerge={draftMoveMerge}
    discardReason={discardReason}
    discardConfirmed={discardConfirmed}
    reparseBatchId={reparseBatchId}
    canFinalizePublishedMove={canFinalizePublishedMove}
    onDiscarded={onDiscarded}
    onReparseSource={onReparseSource}
    setNote={setNote}
    setNoteVisibility={setNoteVisibility}
    setReadyReason={setReadyReason}
    changeTargetDate={changeTargetDate}
    changeMoveReason={changeMoveReason}
    changeDraftMoveDecision={changeDraftMoveDecision}
    setDiscardReason={setDiscardReason}
    setDiscardConfirmed={setDiscardConfirmed}
    setReparseBatchId={setReparseBatchId}
    saveNote={saveNote}
    runValidation={runValidation}
    markReady={markReady}
    inspectDraftMoveTarget={inspectDraftMoveTarget}
    confirmDraftMoveDecision={confirmDraftMoveDecision}
    discardDraft={discardDraft}
    setShowPublish={setShowPublish}
    resetDiscardOperation={() => operationKeys.reset("discard-draft")}
    onRefresh={() => { setError(undefined); void refreshWorkspace().catch((caught: unknown) => setError(errorMessage(caught))); }}
    dataTable={workspace ? <ReviewDataTable busy={busyAction !== undefined} onAddCellNote={addCellNote} onAddRow={addRow} onAddRowNote={addRowNote} onChangeRowState={changeRowState} onPageChange={(page) => { void refreshWorkspace(head.version_id, page); }} onRestoreField={restoreField} onReviewIssue={reviewIssue} onReviseNote={reviseNote} onSetField={setField} operator={operator} workspace={workspace} /> : undefined}
    versionNotes={workspace?.version_notes.length ? <ul className="version-note-list">{workspace.version_notes.map((item) => <li key={item.note_key}><p>{item.body}</p><span>{item.author_username} · {item.visibility === "internal" ? "仅审核人员" : "查看人员可见"} · 第 {item.revision_number} 版</span><NoteRevisionEditor busy={busyAction !== undefined} note={item} onRevise={reviseNote} /></li>)}</ul> : null}
    mergeMatrix={draftMovePreview && draftMovePreview.kind !== "empty" ? <MergeDecisionMatrix disabled={busyAction === "move"} onStateChange={setDraftMoveMerge} operator={operator} sourceId={head.version_id} sourceKind="dataset_version" targetVersionId={draftMovePreview.kind === "active_draft" ? draftMovePreview.activeDraft.version_id : draftMovePreview.publication.version_id} /> : undefined}
    publicationDialog={showPublish && validation ? <PublicationDialog context={context} head={head} onCancel={() => setShowPublish(false)} onPublish={publish} operator={operator} publicationProgress={publicationProgress} validation={validation} /> : undefined}
  />;
}
