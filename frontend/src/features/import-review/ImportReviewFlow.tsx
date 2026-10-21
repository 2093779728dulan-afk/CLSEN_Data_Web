import { ImportIntakeView } from "./ImportIntakeView";
import surfaceCss from "./ReviewSurfaces.module.css";
import { useEffect, useMemo, useReducer, useRef, useState, type FormEvent } from "react";

import {
  ApiRequestError,
  StableOperationKeyStore,
  requestApi,
  writeApi,
} from "../../api/client";
import type {
  ChangeDateRequest,
  ConfirmParseRequest,
  ForceRebuildDraftRequest,
  MaterializeBaselineRequest,
} from "../../api/generated";
import type {
  ConfirmParseResponse,
  DraftHead,
  DraftMutation,
  PublicationPointer,
  InspectionResponse,
  PublicationCommandResponse,
  ReportType,
  ReviewWorkspace,
  SuccessfulParse,
  UploadResponse,
  VersionSummary,
} from "../../api/types";
import { isSuccessfulParse } from "../../api/types";
import { BatchReviewEntry } from "../batch-review/BatchReviewEntry";
import { BatchNotePanel } from "./BatchNotePanel";
import {
  defaultAuditReason,
  reportTypeAuditLabel,
  type AuditOperator,
} from "./auditReason";
import { DraftReviewGate } from "./DraftReviewGate";
import {
  MergeDecisionMatrix,
  type MergeDecisionState,
} from "./MergeDecisionMatrix";
import { SourceFilePreview } from "./SourceFilePreview";
import {
  importReviewReducer,
  initialImportReviewState,
  selectActiveQueueItem,
} from "./importReviewReducer";
import {
  loadReviewRecovery,
  removeReviewRecovery,
  reviewRecoveryKey,
  saveReviewRecovery,
} from "./reviewRecovery";
import type {
  DraftReviewContext,
  ImportQueueItem,
  ReviewLocationHandoff,
  UploadSession,
} from "./workflowTypes";

type Props = {
  canFinalizePublishedMove?: boolean;
  canForceRebuild?: boolean;
  initialDraft?: DraftReviewContext;
  initialVersionId?: number;
  initialBatchId?: number;
  onBatchReviewCreated?: (runId: number) => void;
  onPublished: (result: PublicationCommandResponse) => void;
  onReportDateChanged?: (handoff: ReviewLocationHandoff) => void;
  reportDate: string;
  initialReportType?: ReportType;
  siteId?: number;
  userId?: number;
  operator?: AuditOperator;
};

type PendingMaterializeCommand = {
  body: ForceRebuildDraftRequest | MaterializeBaselineRequest;
  inputFingerprint: string;
  operationKey: string;
  path: string;
  publication: PublicationPointer;
  slot: "force-rebuild" | "materialize";
};

type MaterializeDecision = "merge" | "replace" | "force-rebuild" | "cancel";

type MaterializeTargetPreview = {
  activeDraft?: VersionSummary;
  publication?: VersionSummary;
  reportDate: string;
  reportType: ReportType;
};

function hasMaterializeConflict(preview: MaterializeTargetPreview) {
  return preview.activeDraft !== undefined || preview.publication !== undefined;
}

function displayError(reason: unknown) {
  if (reason instanceof ApiRequestError && reason.code === "duplicate_import") {
    return `${reason.message} 请从原有导入批次继续，系统不会创建重复数据。`;
  }
  if (reason instanceof ApiRequestError && reason.status === 409) {
    return "导入状态已变化，请刷新后继续；现有文件和草稿均未被覆盖。";
  }
  return reason instanceof Error ? reason.message : "操作未完成。";
}

function reachedChainSteps(
  upload: UploadSession | undefined,
  inspection: InspectionResponse | undefined,
  parsed: SuccessfulParse | undefined,
  draft: DraftReviewContext | undefined,
  published: boolean,
) {
  if (published) return 5;
  if (draft) return 4;
  if (parsed) return 3;
  if (inspection) return 2;
  if (upload) return 1;
  return 0;
}

function duplicateBatch(reason: unknown): ImportQueueItem["existing"] | undefined {
  if (!(reason instanceof ApiRequestError) || reason.code !== "duplicate_import") return undefined;
  const batchId = reason.details.existing_batch_id;
  if (!batchId) return undefined;
  const reportType: ReportType | undefined = reason.details.report_type === "business_report" || reason.details.report_type === "return_report"
    ? reason.details.report_type
    : undefined;
  return {
    batchId,
    reportDate: /^\d{4}-\d{2}-\d{2}$/.test(reason.details.report_date ?? "")
      ? reason.details.report_date
      : undefined,
    reportType,
    stage: reason.details.stage,
    workspaceUrl: reason.details.workspace_url,
  };
}

function existingStageLabel(stage: string | undefined) {
  const labels: Record<string, string> = {
    draft: "草稿待审核",
    failed: "处理失败",
    parsed: "已解析",
    processing: "处理中",
    published: "已发布",
    ready: "待发布",
    uploaded: "已上传",
  };
  return stage ? labels[stage] ?? stage : "待继续处理";
}

export function ImportReviewFlow({ canFinalizePublishedMove = false, canForceRebuild = false, initialBatchId, initialDraft, initialReportType, initialVersionId, onBatchReviewCreated, onPublished, onReportDateChanged, operator, reportDate, siteId = 0, userId = 0 }: Props) {
  const recoveryIdentity = useMemo(() => ({ reportDate, siteId, userId }), [reportDate, siteId, userId]);
  const [restoredFlow] = useState(() => initialBatchId ? undefined : loadReviewRecovery(recoveryIdentity));
  const [reviewState, dispatchReview] = useReducer(
    importReviewReducer,
    undefined,
    () => {
      const state = initialImportReviewState(reportDate, restoredFlow?.reviewState);
      return initialReportType && !state.activeQueueId
        ? { ...state, intake: { ...state.intake, reportType: initialReportType } }
        : state;
    },
  );
  const { activeQueueId, importQueue } = reviewState;
  const activeQueueItem = selectActiveQueueItem(reviewState);
  const assignedDate = activeQueueItem?.assignedDate ?? reviewState.intake.assignedDate;
  const upload = activeQueueItem?.upload;
  const inspection = activeQueueItem?.inspection;
  const reportType = activeQueueItem?.reportType ?? reviewState.intake.reportType;
  const encoding = activeQueueItem?.encoding ?? reviewState.intake.encoding;
  const parsed = activeQueueItem?.parsed;
  const published = activeQueueItem?.status === "completed";
  const [files, setFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState<DraftReviewContext | undefined>(initialDraft);
  const [noteBatchIds, setNoteBatchIds] = useState<number[]>(
    initialDraft?.sourceBatchId === undefined ? restoredFlow?.noteBatchIds ?? [] : [initialDraft.sourceBatchId],
  );
  const [materializeReason, setMaterializeReason] = useState(restoredFlow?.materializeReason ?? "");
  const [materializePreview, setMaterializePreview] = useState<MaterializeTargetPreview>();
  const [materializeDecision, setMaterializeDecision] = useState<MaterializeDecision>();
  const [forceRebuildConfirmed, setForceRebuildConfirmed] = useState(false);
  const [materializeMerge, setMaterializeMerge] = useState<MergeDecisionState>({
    decisions: [],
    ready: false,
  });
  const [busyAction, setBusyAction] = useState<string>();
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const operationKeys = useRef(new StableOperationKeyStore()).current;
  const pendingMaterialize = useRef<PendingMaterializeCommand | undefined>(undefined);
  const automaticMaterializeReason = useRef("");
  const materializeReasonSupplement = useRef("");
  const persistedSessionKey = useRef(reviewRecoveryKey(recoveryIdentity));

  useEffect(() => {
    if (!parsed || !upload || !operator) return;
    const nextAutomaticReason = defaultAuditReason(
      operator,
      `生成 ${assignedDate} ${reportTypeAuditLabel(reportType)}审核草稿`,
      `导入批次 #${parsed.batch_id} · 原始文件 ${upload.fileName}`,
    );
    setMaterializeReason((current) => {
      const trimmed = current.trim();
      if (trimmed && current !== automaticMaterializeReason.current && !trimmed.startsWith("操作人：")) {
        materializeReasonSupplement.current = trimmed;
      } else if (trimmed && current !== automaticMaterializeReason.current) {
        return current;
      }
      const supplement = materializeReasonSupplement.current;
      const next = supplement
        ? `${nextAutomaticReason.slice(0, -1)}；补充说明：${supplement}${/[。！？.!?]$/.test(supplement) ? "" : "。"}`
        : nextAutomaticReason;
      automaticMaterializeReason.current = next;
      return next;
    });
  }, [assignedDate, operator, parsed, reportType, upload]);

  const patchActiveQueueItem = (changes: Partial<ImportQueueItem>) => {
    dispatchReview({ changes, type: "patch-active" });
  };
  const setAssignedDate = (value: string) => {
    if (activeQueueId) patchActiveQueueItem({ assignedDate: value });
    else dispatchReview({ changes: { assignedDate: value }, type: "set-intake" });
  };
  const setReportType = (value: ReportType) => {
    if (activeQueueId) patchActiveQueueItem({ reportType: value });
    else dispatchReview({ changes: { reportType: value }, type: "set-intake" });
  };
  const setEncoding = (value: ImportQueueItem["encoding"]) => {
    if (activeQueueId) patchActiveQueueItem({ encoding: value });
    else dispatchReview({ changes: { encoding: value }, type: "set-intake" });
  };
  const setParsed = (value: SuccessfulParse | undefined) => patchActiveQueueItem({ parsed: value });
  const setPublished = (value: boolean) => patchActiveQueueItem({ status: value ? "completed" : "ready" });
  const setImportQueue = (value: ImportQueueItem[] | ((current: ImportQueueItem[]) => ImportQueueItem[])) => {
    if (typeof value === "function") dispatchReview({ type: "update-queue", update: value });
    else dispatchReview({ items: value, type: "replace-queue" });
  };
  const setActiveQueueId = (value: string | undefined) => dispatchReview({ id: value, type: "set-active" });

  useEffect(() => {
    const key = reviewRecoveryKey(recoveryIdentity);
    if (persistedSessionKey.current !== key) {
      window.sessionStorage.removeItem(persistedSessionKey.current);
      persistedSessionKey.current = key;
    }
    if (importQueue.length === 0) {
      removeReviewRecovery(recoveryIdentity);
      return;
    }
    saveReviewRecovery(recoveryIdentity, {
      materializeReason,
      noteBatchIds,
      reviewState,
    });
  }, [importQueue.length, materializeReason, noteBatchIds, recoveryIdentity, reviewState]);

  const queueBatchFingerprint = useMemo(() => importQueue
    .flatMap((item) => item.upload ? [`${item.id}:${item.upload.upload.batch_id}`] : [])
    .sort()
    .join("|"), [importQueue]);
  const batchReviewBatchIds = useMemo(() => importQueue
    .filter((item) => item.status !== "completed" && item.existing?.stage !== "published")
    .flatMap((item) => item.upload ? [item.upload.upload.batch_id] : []), [importQueue]);

  useEffect(() => {
    if (!queueBatchFingerprint) return;
    const controller = new AbortController();
    void Promise.all(importQueue.map(async (item) => {
      if (!item.upload) return { id: item.id, status: 404 };
      const response = await fetch(`/api/imports/${item.upload.upload.batch_id}/raw-file`, {
        credentials: "same-origin",
        method: "HEAD",
        signal: controller.signal,
      });
      return { id: item.id, status: response.status };
    })).then((results) => {
      if (controller.signal.aborted) return;
      const missingIds = results.filter((result) => result.status === 404).map((result) => result.id);
      const unavailableIds = new Set(results.filter((result) => result.status === 409).map((result) => result.id));
      if (missingIds.length > 0) {
        dispatchReview({ ids: missingIds, type: "remove-items" });
      }
      if (unavailableIds.size > 0) {
        dispatchReview({
          type: "update-queue",
          update: (current) => current.map((item) => unavailableIds.has(item.id)
            ? { ...item, error: "原文件完整性检查未通过，当前批次暂不可用。" }
            : item),
        });
      }
      if (activeQueueId && missingIds.includes(activeQueueId)) {
        setNoteBatchIds([]);
      }
      if (missingIds.length > 0) setNotice("已移除不存在的旧导入批次，可以重新上传文件。 ");
      if (unavailableIds.size > 0) setError("部分恢复批次的原文件暂不可用，请先检查文件完整性。");
    }).catch((reason: unknown) => {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) return;
    });
    return () => controller.abort();
    // Queue item details change frequently. Raw-file probes intentionally key only
    // off the stable batch identity fingerprint.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queueBatchFingerprint]);

  const writeCommand = async <T,>(slot: string, path: string, body: unknown) => {
    const operationKey = operationKeys.forCommand(slot, path, body);
    const result = await writeApi<T>(path, { body, operationKey });
    operationKeys.complete(slot, operationKey);
    return result;
  };

  const resetPendingMaterialize = () => {
    operationKeys.reset("materialize");
    operationKeys.reset("force-rebuild");
    pendingMaterialize.current = undefined;
  };

  const clearMaterializePreview = () => {
    setMaterializePreview(undefined);
    setMaterializeDecision(undefined);
    setForceRebuildConfirmed(false);
    setMaterializeMerge({ decisions: [], ready: false });
    resetPendingMaterialize();
  };

  const selectMaterializeDecision = (decision: MaterializeDecision) => {
    setMaterializeDecision(decision);
    setForceRebuildConfirmed(false);
    setMaterializeMerge({ decisions: [], ready: false });
    resetPendingMaterialize();
  };

  const changeAssignedDate = (value: string) => {
    setAssignedDate(value);
    clearMaterializePreview();
  };

  const changeReportType = (value: ReportType) => {
    setReportType(value);
    clearMaterializePreview();
  };

  const changeEncoding = (value: ImportQueueItem["encoding"]) => {
    setEncoding(value);
    operationKeys.reset("confirm-parse");
  };

  const activateQueueItem = (item: ImportQueueItem) => {
    if (!item.upload || !item.inspection || item.status === "failed") return;
    setActiveQueueId(item.id);
    setDraft(undefined);
    setNoteBatchIds([item.upload.upload.batch_id]);
    setMaterializeReason("");
    clearMaterializePreview();
    operationKeys.reset("change-batch-date");
    operationKeys.reset("confirm-parse");
    setError(undefined);
    setNotice(`已切换到 ${item.upload.fileName}，请独立确认这份文件。`);
  };

  const retryQueueInspection = async (item: ImportQueueItem) => {
    if (!item.upload) return;
    setBusyAction(`inspect:${item.id}`);
    setError(undefined);
    try {
      const nextInspection = await writeApi<InspectionResponse>(
        `/api/imports/${item.upload.upload.batch_id}/inspect`,
        { idempotent: false },
      );
      const recovered: ImportQueueItem = {
        ...item,
        encoding: nextInspection.encoding ?? item.encoding,
        error: undefined,
        inspection: nextInspection,
        reportType: nextInspection.report_type ?? item.reportType,
        status: "ready",
      };
      setImportQueue((current) => current.map((candidate) => (
        candidate.id === item.id ? recovered : candidate
      )));
      activateQueueItem(recovered);
      setNotice(`导入批次 #${item.upload.upload.batch_id} 已重新识别，仍需人工确认。`);
    } catch (caught) {
      setImportQueue((current) => current.map((candidate) => (
        candidate.id === item.id ? { ...candidate, error: displayError(caught) } : candidate
      )));
      setError(displayError(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  useEffect(() => {
    if (initialBatchId || initialDraft || !initialVersionId) return;
    let active = true;
    setBusyAction("resume");
    void (async () => {
      try {
        const workspace = await requestApi<ReviewWorkspace>(
          `/api/drafts/${initialVersionId}/review-workspace?page=1&page_size=50`,
        );
        if (!active) return;
        let publication: PublicationPointer = { version_id: null, published_at: null };
        if (workspace.publication_mode === "ordinary") {
          const versions = await requestApi<VersionSummary[]>(
            `/api/versions?report_date=${encodeURIComponent(workspace.report_date)}&report_type=${workspace.report_type}`,
          );
          if (!active) return;
          const current = versions.find((item) => item.is_current_publication);
          if (current) {
            publication = {
              version_id: current.version_id,
              published_at: current.published_at,
            };
          }
        } else if (workspace.published_move) {
          publication = workspace.published_move.target_publication;
        }
        setDraft({
          head: workspace.head,
          publicationMode: workspace.publication_mode,
          publishedMove: workspace.published_move,
          reportDate: workspace.report_date,
          reportType: workspace.report_type,
          rulesetVersion: workspace.ruleset_version,
          publication,
        });
        setNoteBatchIds([...new Set(workspace.source_batches.map((source) => source.batch_id))]);
      } catch (caught) {
        if (active) setError(displayError(caught));
      } finally {
        if (active) setBusyAction(undefined);
      }
    })();
    return () => { active = false; };
  }, [initialBatchId, initialDraft, initialVersionId]);

  useEffect(() => {
    if (!initialBatchId) return;
    let active = true;
    setBusyAction("resume");
    setDraft(undefined);
    setError(undefined);
    void writeApi<InspectionResponse>(`/api/imports/${initialBatchId}/inspect`, { idempotent: false }).then((result) => {
      if (!active) return;
      const item: ImportQueueItem = {
        id: `source-${initialBatchId}`,
        assignedDate: result.report_date ?? reportDate,
        encoding: result.encoding ?? "utf-8-sig",
        reportType: result.report_type ?? "business_report",
        inspection: result,
        status: "ready",
        upload: { fileName: `导入批次 #${initialBatchId} 的原始 CSV`, upload: { batch_id: initialBatchId } },
      };
      dispatchReview({ type: "replace-queue", items: [item], activeQueueId: item.id });
      setNoteBatchIds([initialBatchId]);
      setNotice(`当前处理文件批次 #${initialBatchId}。请先核对原始文件预览，再解析并选择替换方式；旧草稿和已发布数据尚未改变。`);
    }).catch((reason: unknown) => {
      if (active) setError(displayError(reason));
    }).finally(() => {
      if (active) setBusyAction(undefined);
    });
    return () => { active = false; };
  }, [initialBatchId, reportDate]);

  useEffect(() => {
    if (!upload && !draft) dispatchReview({ changes: { assignedDate: reportDate, ...(initialReportType ? { reportType: initialReportType } : {}) }, type: "set-intake" });
  }, [draft, initialReportType, reportDate, upload]);

  const reachedSteps = reachedChainSteps(upload, inspection, parsed, draft, published);
  const activeStage = published
    ? "已发布"
    : draft
      ? "审核草稿"
      : parsed
        ? "生成草稿"
        : inspection
          ? "确认识别"
          : "上传原表";

  const uploadAndInspect = async (event: FormEvent) => {
    event.preventDefault();
    if (files.length === 0) return;
    setBusyAction("upload");
    setError(undefined);
    setNotice(undefined);
    const queue: ImportQueueItem[] = [];
    const shouldAssignDetectedDates = files.length > 1;
    for (const [index, selectedFile] of files.entries()) {
      const id = `${Date.now()}-${index}-${selectedFile.name}`;
      let nextSession: UploadSession | undefined;
      try {
        const result = await writeApi<UploadResponse>(
          // This is only a provisional raw-file association. The confirmed parse
          // command below uses each file's inspected date to create the actual
          // date-scoped dataset, so an inferred filename date is never trusted
          // without human confirmation.
          `/api/imports?report_date=${encodeURIComponent(assignedDate)}`,
          {
            rawBody: selectedFile,
            idempotent: false,
            headers: {
              "Content-Type": selectedFile.type || "text/csv",
              // Fetch header values are ByteStrings. Percent-encoding keeps Chinese
              // report names transport-safe; the API decodes this display metadata.
              "X-Original-Filename": encodeURIComponent(selectedFile.name),
            },
          },
        );
        nextSession = { fileName: selectedFile.name, upload: result };
        const nextInspection = await writeApi<InspectionResponse>(
          `/api/imports/${result.batch_id}/inspect`,
          { idempotent: false },
        );
        queue.push({
          assignedDate: shouldAssignDetectedDates && nextInspection.report_date
            ? nextInspection.report_date
            : assignedDate,
          encoding: nextInspection.encoding ?? "utf-8-sig",
          id,
          inspection: nextInspection,
          reportType: nextInspection.report_type ?? "business_report",
          status: "ready",
          upload: nextSession,
        });
      } catch (caught) {
        const existing = duplicateBatch(caught);
        if (existing) {
          const existingDate = existing.reportDate ?? assignedDate;
          const existingReportType: ReportType = existing.reportType ?? "business_report";
          queue.push({
            assignedDate: existingDate,
            encoding: "utf-8-sig",
            error: `服务器阶段：${existingStageLabel(existing.stage)}。原始文件仍安全保留，可从批次 #${existing.batchId} 继续。`,
            existing,
            id,
            reportType: existingReportType,
            status: "existing",
            upload: {
              fileName: selectedFile.name,
              upload: { batch_id: existing.batchId },
            },
          });
          continue;
        }
        queue.push({
          assignedDate,
          encoding: "utf-8-sig",
          error: displayError(caught),
          id,
          reportType: "business_report",
          status: "failed",
          upload: nextSession,
        });
      }
    }
    setImportQueue(queue);
    const firstReady = queue.find((item) => item.status === "ready");
    const failedCount = queue.filter((item) => item.status === "failed").length;
    const existingCount = queue.filter((item) => item.status === "existing").length;
    const readyCount = queue.filter((item) => item.status === "ready").length;
    if (failedCount === 0) {
      setFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
    if (firstReady) {
      activateQueueItem(firstReady);
      const detectedDateCount = queue.filter((item) => (
        item.status === "ready" && item.inspection?.report_date === item.assignedDate
      )).length;
      setNotice(`${queue.length} 份文件已逐份处理：${readyCount} 份等待人工确认${shouldAssignDetectedDates ? `，其中 ${detectedDateCount} 份已按文件识别日期归入对应工作日` : ""}${existingCount ? `，${existingCount} 份已有服务器批次` : ""}${failedCount ? `，${failedCount} 份失败` : ""}。识别结果仍需人工确认后才会生成草稿。`);
    } else if (existingCount > 0) {
      setNotice(`${existingCount} 份文件已存在于服务器，本次未新增这些文件的导入批次，未改变已发布日报。${failedCount ? `另有 ${failedCount} 份失败，请查看各项原因。` : ""}`);
    } else {
      setError("所选文件均未能保存或识别，请查看队列中的失败原因后重新选择。");
    }
    setBusyAction(undefined);
  };

  const updateBatchDate = async () => {
    if (!upload) return;
    setBusyAction("date");
    setError(undefined);
    setNotice(undefined);
    try {
      const path = `/api/imports/${upload.upload.batch_id}/change-date`;
      const body = { report_date: assignedDate } satisfies ChangeDateRequest;
      await writeCommand<void>("change-batch-date", path, body);
      setNotice(`导入批次 #${upload.upload.batch_id} 已归属 ${assignedDate}。`);
      onReportDateChanged?.({
        reportDate: assignedDate,
        reportType,
      });
    } catch (caught) {
      setError(displayError(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  const confirmParse = async () => {
    if (!upload || !inspection) return;
    setBusyAction("parse");
    setError(undefined);
    setNotice(undefined);
    try {
      const path = `/api/imports/${upload.upload.batch_id}/confirm-parse`;
      const body = {
        report_type: reportType,
        report_date: assignedDate,
        encoding,
      } satisfies ConfirmParseRequest;
      const response = await writeCommand<ConfirmParseResponse>(
        "confirm-parse",
        path,
        body,
      );
      if (!isSuccessfulParse(response.result)) {
        setError(`解析失败：${response.result.error_code}。原始文件和本次失败尝试已保留，可以修正识别选择后重新解析。`);
        return;
      }
      clearMaterializePreview();
      setParsed(response.result);
      onReportDateChanged?.({
        reportDate: assignedDate,
        reportType,
      });
      setNotice("解析基线已生成，但尚未进入草稿或看板。");
    } catch (caught) {
      setError(displayError(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  const commitMaterialize = async (
    preview: MaterializeTargetPreview,
    strategy: Exclude<MaterializeDecision, "cancel">,
  ) => {
    if (!upload || !inspection || !parsed) return;
    if (strategy === "replace" && preview.activeDraft) {
      throw new Error("目标日期已有活动草稿；普通导入不能覆盖它，请选择合并或由管理员强制重建。");
    }
    let body: ForceRebuildDraftRequest | MaterializeBaselineRequest;
    let path: string;
    let slot: PendingMaterializeCommand["slot"];
    if (strategy === "force-rebuild") {
      const activeDraft = preview.activeDraft;
      if (!canForceRebuild || !activeDraft) {
        throw new Error("只有管理员能对明确存在的目标活动草稿执行强制重建。");
      }
      path = `/api/admin/drafts/${activeDraft.version_id}/force-rebuild`;
      slot = "force-rebuild";
      body = {
        batch_id: upload.upload.batch_id,
        parse_baseline_id: parsed.parse_baseline_id,
        report_date: preview.reportDate,
        expected_active_draft: {
          version_id: activeDraft.version_id,
          data_revision: activeDraft.data_revision,
          review_revision: activeDraft.review_revision,
        },
        expected_publication_version_id: preview.publication?.version_id ?? null,
        reason: materializeReason,
      } satisfies ForceRebuildDraftRequest;
    } else {
      path = "/api/datasets/materialize";
      slot = "materialize";
      body = {
        batch_id: upload.upload.batch_id,
        parse_baseline_id: parsed.parse_baseline_id,
        report_date: preview.reportDate,
        strategy,
        expected_active_draft: preview.activeDraft ? {
          version_id: preview.activeDraft.version_id,
          data_revision: preview.activeDraft.data_revision,
          review_revision: preview.activeDraft.review_revision,
        } : null,
        expected_publication_version_id: preview.publication?.version_id ?? null,
        merge_decisions: strategy === "merge" ? materializeMerge.decisions : [],
        reason: materializeReason,
      } satisfies MaterializeBaselineRequest;
    }
    const inputFingerprint = `${path}:${JSON.stringify(body)}`;
    let pending = pendingMaterialize.current;
    if (!pending || pending.inputFingerprint !== inputFingerprint) {
      pending = {
        body,
        inputFingerprint,
        operationKey: operationKeys.forCommand(slot, path, body),
        path,
        publication: preview.publication
          ? {
              version_id: preview.publication.version_id,
              published_at: preview.publication.published_at,
            }
          : { version_id: null, published_at: null },
        slot,
      };
      pendingMaterialize.current = pending;
    }
    const result = await writeApi<DraftMutation>(pending.path, {
      body: pending.body,
      operationKey: pending.operationKey,
    });
    operationKeys.complete(pending.slot, pending.operationKey);
    pendingMaterialize.current = undefined;
    const head = await requestApi<DraftHead>(`/api/drafts/${result.version_id}`);
    setDraft({
      head,
      publicationMode: "ordinary",
      publishedMove: null,
      reportDate: preview.reportDate,
      reportType: preview.reportType,
      rulesetVersion: inspection.ruleset_version,
      sourceRowCount: parsed.source_row_count,
      sourceBatchId: upload.upload.batch_id,
      publication: pending.publication,
    });
    setNotice(strategy === "force-rebuild"
      ? `目标活动草稿 v${preview.activeDraft?.version_no} 已废弃并重建；旧草稿和修改历史仍可审计，新草稿必须重新校验。`
      : undefined);
  };

  const inspectMaterializeTarget = async () => {
    if (!upload || !inspection || !parsed) return;
    setBusyAction("materialize");
    setError(undefined);
    setNotice(undefined);
    try {
      let preview = materializePreview;
      if (!preview) {
        const versions = await requestApi<VersionSummary[]>(
          `/api/versions?report_date=${encodeURIComponent(assignedDate)}&report_type=${reportType}`,
        );
        preview = {
          activeDraft: versions.find((item) => item.is_active_draft),
          publication: versions.find((item) => item.is_current_publication),
          reportDate: assignedDate,
          reportType,
        };
        resetPendingMaterialize();
        setMaterializeDecision(undefined);
        setMaterializePreview(preview);
      }
      if (hasMaterializeConflict(preview)) return;
      await commitMaterialize(preview, "merge");
    } catch (caught) {
      setError(displayError(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  const confirmMaterializeDecision = async () => {
    if (!materializePreview || !materializeDecision) return;
    if (materializeDecision === "cancel") {
      clearMaterializePreview();
      setError(undefined);
      setNotice("已取消生成草稿；解析基线仍安全保留，没有写入或覆盖目标日期。");
      return;
    }
    setBusyAction("materialize");
    setError(undefined);
    setNotice(undefined);
    try {
      await commitMaterialize(materializePreview, materializeDecision);
    } catch (caught) {
      setError(displayError(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  const reparseCurrentBaseline = () => {
    setParsed(undefined);
    clearMaterializePreview();
    operationKeys.reset("confirm-parse");
    setNotice("已返回日期与识别确认。修改所属日期后再次解析会创建新的不可变基线，旧基线保持可追溯。");
    setError(undefined);
  };

  const resumeSourceForReparse = async (batchId: number) => {
    setDraft(undefined);
    clearMaterializePreview();
    operationKeys.reset("confirm-parse");
    setBusyAction("reparse");
    setError(undefined);
    try {
      const nextInspection = await writeApi<InspectionResponse>(
        `/api/imports/${batchId}/inspect`,
        { idempotent: false },
      );
      const recoveredItem: ImportQueueItem = {
        assignedDate: nextInspection.report_date ?? reportDate,
        encoding: nextInspection.encoding ?? "utf-8-sig",
        id: activeQueueId ?? `reparse-${batchId}`,
        inspection: nextInspection,
        reportType: nextInspection.report_type ?? "business_report",
        status: "ready",
        upload: {
        fileName: `导入批次 #${batchId} 的原始 CSV`,
        upload: { batch_id: batchId },
        },
      };
      dispatchReview({
        activeQueueId: recoveredItem.id,
        items: activeQueueId
          ? importQueue.map((item) => item.id === activeQueueId ? recoveredItem : item)
          : [recoveredItem],
        type: "replace-queue",
      });
      setNoteBatchIds([batchId]);
      setNotice("旧草稿已废弃并保留审计历史。请重新确认识别参数后创建新的解析尝试。");
    } catch (caught) {
      setError(displayError(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  const leaveDiscardedDraft = () => {
    setDraft(undefined);
    dispatchReview({ reportDate, type: "reset" });
    setNoteBatchIds([]);
    setNotice("活动草稿已废弃并保留在版本历史中。可以选择新的文件继续。 ");
  };

  const reset = () => {
    setFiles([]);
    setDraft(undefined);
    setNoteBatchIds([]);
    setMaterializeReason("");
    setMaterializePreview(undefined);
    setMaterializeDecision(undefined);
    setForceRebuildConfirmed(false);
    setMaterializeMerge({ decisions: [], ready: false });
    operationKeys.reset("change-batch-date");
    operationKeys.reset("confirm-parse");
    resetPendingMaterialize();
    setError(undefined);
    setNotice(undefined);
    dispatchReview({ reportDate, type: "reset" });
  };

  const reviewNextQueuedFile = () => {
    const next = importQueue.find((item) => item.status === "ready" && item.id !== activeQueueId);
    if (next) {
      activateQueueItem(next);
      return;
    }
    reset();
    setNotice("本次批量队列已处理完成，可以选择下一批文件。");
  };

  return <ImportIntakeView
    activeStage={activeStage}
    reachedSteps={reachedSteps}
    assignedDate={assignedDate}
    reportType={reportType}
    encoding={encoding}
    files={files}
    fileInputRef={fileInputRef}
    importQueue={importQueue}
    activeQueueId={activeQueueId}
    upload={upload}
    inspection={inspection}
    parsed={parsed}
    draft={draft}
    published={published}
    busyAction={busyAction}
    error={error}
    notice={notice}
    operator={operator}
    materializeReason={materializeReason}
    materializePreview={materializePreview}
    materializeDecision={materializeDecision}
    forceRebuildConfirmed={forceRebuildConfirmed}
    materializeMerge={materializeMerge}
    canForceRebuild={canForceRebuild}
    reset={reset}
    activateQueueItem={activateQueueItem}
    retryQueueInspection={retryQueueInspection}
    reviewNextQueuedFile={reviewNextQueuedFile}
    uploadAndInspect={uploadAndInspect}
    changeAssignedDate={changeAssignedDate}
    changeReportType={changeReportType}
    changeEncoding={changeEncoding}
    setFiles={setFiles}
    updateBatchDate={updateBatchDate}
    confirmParse={confirmParse}
    reparseCurrentBaseline={reparseCurrentBaseline}
    setMaterializeReason={setMaterializeReason}
    resetPendingMaterialize={resetPendingMaterialize}
    inspectMaterializeTarget={inspectMaterializeTarget}
    selectMaterializeDecision={selectMaterializeDecision}
    setForceRebuildConfirmed={setForceRebuildConfirmed}
    confirmMaterializeDecision={confirmMaterializeDecision}
    sourcePreview={upload && inspection && !draft && !published ? <SourceFilePreview batchId={upload.upload.batch_id} encoding={encoding} fileName={upload.fileName} key={`${upload.upload.batch_id}:${encoding}`} /> : undefined}
    mergeMatrix={parsed && materializePreview && (materializePreview.activeDraft || materializePreview.publication) ? <MergeDecisionMatrix disabled={busyAction === "materialize"} onStateChange={setMaterializeMerge} operator={operator} sourceId={parsed.parse_baseline_id} sourceKind="parse_baseline" targetVersionId={(materializePreview.activeDraft ?? materializePreview.publication)!.version_id} /> : undefined}
    draftWorkspace={draft ? <div className={surfaceCss["review-workspace-shell"]}><div className={surfaceCss["review-workspace-shell__main"]}><DraftReviewGate canFinalizePublishedMove={canFinalizePublishedMove} context={draft} onDiscarded={leaveDiscardedDraft} onPublished={(result) => { setPublished(true); onPublished(result); }} onReparseSource={resumeSourceForReparse} onReportDateChanged={onReportDateChanged} operator={operator} /></div><aside aria-label="导入证据与备注" className={surfaceCss["review-workspace-shell__evidence"]}><p className="section-kicker">证据与备注</p><h3>原始批次</h3><p>备注和来源文件独立保留，不干扰总表审核。</p>{noteBatchIds.map((batchId) => <BatchNotePanel batchId={batchId} key={batchId} />)}</aside></div> : undefined}
    notes={noteBatchIds.length > 0 ? <aside aria-label="导入证据与备注" className={surfaceCss["review-evidence-drawer"]}><p className="section-kicker">证据与备注</p>{noteBatchIds.map((batchId) => <BatchNotePanel batchId={batchId} key={batchId} />)}</aside> : undefined}
    batchEntry={<BatchReviewEntry batchIds={batchReviewBatchIds} onCreated={onBatchReviewCreated} />}
  />;
}
