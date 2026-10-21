import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { useInRouterContext, useSearchParams } from "react-router-dom";

import { ApiRequestError, requestApi } from "../../api/client";
import type {
  CreatePublishedMoveRequest,
  CreateRevisionRequest,
  DraftCommandResponse,
  MoveTargetRequest,
  PublicationCommandResponse,
  PublicationPointerRequest,
  RollbackRequest,
  UndoPublishedMoveRequest,
  UndoablePublishedMoveResponse,
  VersionDetailResponse,
  VersionSummaryResponse,
} from "../../api/generated";
import type { Principal, ReportType } from "../../api/types";
import {
  MergeDecisionMatrix,
  type MergeDecisionState,
} from "../import-review/MergeDecisionMatrix";
import {
  prepareReturnDedupStaging,
  ReturnDedupStagingSupersededError,
} from "../workbench/workbenchApi";
import "./VersionHistory.css";
import { RevisionConfirmationView, MoveConfirmationView, UndoMoveConfirmationView, RollbackConfirmationView } from "./VersionCommandViews";
import { VersionHistoryView } from "./VersionHistoryView";
import { VersionRows } from "./VersionRows";
import { BatchReviewHistory } from "../batch-review/BatchReviewHistory";

export type VersionHistoryFilter = {
  reportDate: string;
  reportType: ReportType;
};

export type PublishedMoveRevisionHandoff = {
  command: DraftCommandResponse;
  reportType: ReportType;
  sourcePublication: {
    datasetId: number;
    publishedAt: string;
    versionId: number;
  };
  sourceReportDate: string;
  targetPublication: {
    publishedAt: string | null;
    versionId: number | null;
  };
  targetReportDate: string;
};

export type PublishedRevisionHandoff = {
  command: DraftCommandResponse;
  reportDate: string;
  reportType: ReportType;
};

export type VersionHistoryProps = {
  initialReportDate: string;
  initialReportType?: ReportType;
  onFilterChange?: (filter: VersionHistoryFilter) => void;
  onForceRebuildRequest?: (draft: VersionSummaryResponse) => void;
  onMoveRevisionCreated?: (handoff: PublishedMoveRevisionHandoff) => void;
  onRevisionCreated?: (handoff: PublishedRevisionHandoff) => void;
  onRollbackCompleted?: (result: PublicationCommandResponse) => void;
  principal: Principal;
};

function makeUuid() {
  if (typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}

function readCookie(name: string) {
  const prefix = `${encodeURIComponent(name)}=`;
  const item = document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : undefined;
}

async function versionCommandWrite<T>(path: string, body: unknown, operationKey: string) {
  const csrfToken = readCookie("clsen_csrf");
  if (!csrfToken) {
    throw new ApiRequestError(403, "csrf_missing", "当前会话缺少写入凭据，请退出后重新登录。");
  }
  return requestApi<T>(path, {
    body: JSON.stringify(body),
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": operationKey,
      "X-CSRF-Token": csrfToken,
    },
    method: "POST",
  });
}

type PublishedTargetPreview = {
  kind: "published";
  publication: VersionSummaryResponse;
};

type ActiveDraftTargetPreview = {
  draft: VersionSummaryResponse;
  kind: "active_draft";
  publication?: VersionSummaryResponse;
};

export type MoveTargetPreview =
  | { kind: "empty" }
  | PublishedTargetPreview
  | ActiveDraftTargetPreview
  | { datasetId: number; kind: "pointerless" }
  | { kind: "invalid"; message: string };

export type MoveDecision =
  | "create"
  | "merge_published"
  | "replace_published"
  | "client_cancel"
  | "merge_draft"
  | "cancel_draft"
  | "force_merge"
  | "force_replace";

function publicationPointer(version?: VersionSummaryResponse): PublicationPointerRequest {
  return version ? {
    published_at: version.published_at,
    version_id: version.version_id,
  } : { published_at: null, version_id: null };
}

function classifyMoveTarget(versions: VersionSummaryResponse[]): MoveTargetPreview {
  if (versions.length === 0) return { kind: "empty" };
  const publications = versions.filter((version) => version.is_current_publication);
  const drafts = versions.filter((version) => version.is_active_draft);
  if (publications.length > 1 || drafts.length > 1) {
    return { kind: "invalid", message: "目标日期返回了多个活动指针，无法安全继续。" };
  }
  const publication = publications[0];
  const draft = drafts[0];
  if (publication && !publication.published_at) {
    return { kind: "invalid", message: "目标发布指针缺少发布时间，无法建立并发预期。" };
  }
  if (draft) {
    if (!draft.draft_pointed_at || (draft.status !== "draft" && draft.status !== "ready_for_publish")) {
      return { kind: "invalid", message: "目标草稿指针不完整，无法建立并发预期。" };
    }
    if (publication && publication.dataset_id !== draft.dataset_id) {
      return { kind: "invalid", message: "目标发布与草稿不属于同一数据集。" };
    }
    return { draft, kind: "active_draft", ...(publication ? { publication } : {}) };
  }
  if (publication) return { kind: "published", publication };
  return { datasetId: versions[0]?.dataset_id ?? 0, kind: "pointerless" };
}

function initialMoveDecision(preview: MoveTargetPreview): MoveDecision | undefined {
  if (preview.kind === "empty") return "create";
  if (preview.kind === "published") return "merge_published";
  if (preview.kind === "active_draft") return "merge_draft";
  return undefined;
}

function moveTargetRequest(
  preview: MoveTargetPreview,
  decision: MoveDecision,
): MoveTargetRequest | undefined {
  if (preview.kind === "empty" && decision === "create") {
    return { dataset_id: null, target_kind: "empty" };
  }
  if (preview.kind === "published") {
    if (decision !== "merge_published" && decision !== "replace_published") return undefined;
    return {
      dataset_id: preview.publication.dataset_id,
      publication: publicationPointer(preview.publication),
      strategy: decision === "merge_published" ? "merge" : "replace",
      target_kind: "published",
    };
  }
  if (preview.kind === "active_draft") {
    const draft = preview.draft;
    const base = {
      dataset_id: draft.dataset_id,
      draft: {
        data_revision: draft.data_revision,
        pointed_at: draft.draft_pointed_at ?? "",
        review_revision: draft.review_revision,
        status: draft.status as "draft" | "ready_for_publish",
        version_id: draft.version_id,
      },
      publication: publicationPointer(preview.publication),
      target_kind: "active_draft" as const,
    };
    if (decision === "merge_draft") return { ...base, action: "merge" };
    if (decision === "cancel_draft") return { ...base, action: "cancel" };
    if (decision === "force_merge" && preview.publication) {
      return { ...base, action: "force_rebuild", rebuild_strategy: "merge" };
    }
    if (decision === "force_replace") {
      return { ...base, action: "force_rebuild", rebuild_strategy: "replace" };
    }
  }
  return undefined;
}

function targetPublicationPointer(preview: MoveTargetPreview) {
  const publication = preview.kind === "published"
    ? preview.publication
    : preview.kind === "active_draft"
      ? preview.publication
      : undefined;
  return {
    publishedAt: publication?.published_at ?? null,
    versionId: publication?.version_id ?? null,
  };
}

function moveErrorMessage(reason: unknown) {
  if (reason instanceof ApiRequestError && reason.status === 409) {
    return "来源或目标日期的数据已变化；系统没有自动覆盖任何版本。请重新检查目标日期后再决定。";
  }
  return reason instanceof Error ? reason.message : "跨日期移动未完成。";
}

function undoMoveErrorMessage(reason: unknown) {
  if (reason instanceof ApiRequestError && reason.status === 409) {
    return "来源或目标日期的数据已变化；系统没有撤销或覆盖任何发布版本。请刷新后重新确认。";
  }
  return reason instanceof Error ? reason.message : "跨日期移动撤销未完成。";
}

function errorMessage(reason: unknown) {
  if (reason instanceof ApiRequestError && reason.status === 409) {
    return "发布指针或版本状态已变化，请刷新版本记录后重新确认。";
  }
  return reason instanceof Error ? reason.message : "版本记录读取失败。";
}

function PublishedRevisionDialog({
  onClose,
  onCreated,
  onNotice,
  source,
}: {
  onClose: () => void;
  onCreated?: (handoff: PublishedRevisionHandoff) => void;
  onNotice: (message: string) => void;
  source: VersionDetailResponse;
}) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();
  const operationKey = useRef<string | undefined>(undefined);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!source.published_at || !reason.trim()) return;
    setSubmitting(true);
    setError(undefined);
    const payload: CreateRevisionRequest = {
      expected_publication: {
        published_at: source.published_at,
        version_id: source.version_id,
      },
      reason: reason.trim(),
    };
    operationKey.current ??= makeUuid();
    try {
      const result = await versionCommandWrite<DraftCommandResponse>(
        `/api/datasets/${source.dataset_id}/revisions`,
        payload,
        operationKey.current,
      );
      if (result.result_kind !== "revision_created" || result.status !== "draft") {
        throw new Error("创建修订 API 返回了无法识别的草稿结果，页面未跳转。");
      }
      onClose();
      onNotice(`修订草稿 v${result.version_no} 已创建，正在进入审核工作区。`);
      onCreated?.({
        command: result,
        reportDate: source.report_date,
        reportType: source.report_type,
      });
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return <RevisionConfirmationView source={source} reason={reason} submitting={submitting} error={error} onClose={onClose}
    onReasonChange={value => { setReason(value); operationKey.current = undefined; }} onSubmit={event => { void submit(event); }} />;
}

function PublishedMoveDialog({
  onClose,
  onCreated,
  onNotice,
  source,
}: {
  onClose: () => void;
  onCreated?: (handoff: PublishedMoveRevisionHandoff) => void;
  onNotice: (message: string) => void;
  source: VersionSummaryResponse;
}) {
  const [targetDate, setTargetDate] = useState("");
  const [targetPreview, setTargetPreview] = useState<MoveTargetPreview>();
  const [decision, setDecision] = useState<MoveDecision>();
  const [reason, setReason] = useState("");
  const [forceConfirmed, setForceConfirmed] = useState(false);
  const [checking, setChecking] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [moveError, setMoveError] = useState<string>();
  const [mergeState, setMergeState] = useState<MergeDecisionState>({
    decisions: [],
    ready: false,
  });
  const operationKey = useRef<string | undefined>(undefined);

  const resetCommandKey = () => { operationKey.current = undefined; };
  const changeTargetDate = (value: string) => {
    setTargetDate(value);
    setTargetPreview(undefined);
    setDecision(undefined);
    setForceConfirmed(false);
    setMoveError(undefined);
    setMergeState({ decisions: [], ready: false });
    resetCommandKey();
  };
  const changeDecision = (value: MoveDecision) => {
    setDecision(value);
    setForceConfirmed(false);
    setMoveError(undefined);
    setMergeState({ decisions: [], ready: false });
    resetCommandKey();
  };

  const inspectTarget = async () => {
    if (!targetDate || targetDate === source.report_date) {
      setMoveError("目标报告日必须与来源报告日不同。");
      return;
    }
    setChecking(true);
    setMoveError(undefined);
    setTargetPreview(undefined);
    setDecision(undefined);
    setForceConfirmed(false);
    resetCommandKey();
    try {
      const targetVersions = await requestApi<VersionSummaryResponse[]>(
        `/api/versions?report_date=${encodeURIComponent(targetDate)}&report_type=${source.report_type}`,
      );
      const preview = classifyMoveTarget(targetVersions);
      setTargetPreview(preview);
      setDecision(initialMoveDecision(preview));
    } catch (caught) {
      setMoveError(moveErrorMessage(caught));
    } finally {
      setChecking(false);
    }
  };

  const forceRebuild = decision === "force_merge" || decision === "force_replace";
  const mergeTargetVersionId = targetPreview?.kind === "published" && decision === "merge_published"
    ? targetPreview.publication.version_id
    : targetPreview?.kind === "active_draft" && decision === "merge_draft"
      ? targetPreview.draft.version_id
      : targetPreview?.kind === "active_draft" && decision === "force_merge"
        ? targetPreview.publication?.version_id
        : undefined;
  const commandTarget = targetPreview && decision
    ? moveTargetRequest(targetPreview, decision)
    : undefined;
  const submitLabel = decision === "cancel_draft"
    ? "记录取消决定"
    : forceRebuild
      ? "强制重建跨日期草稿"
      : "创建跨日期审核草稿";

  const submitMove = async (event: FormEvent) => {
    event.preventDefault();
    if (decision === "client_cancel") {
      onClose();
      return;
    }
    if (!targetPreview || !decision || !commandTarget || !source.published_at) {
      setMoveError("当前版本或目标预览不完整，无法建立安全的移动命令。");
      return;
    }
    if (forceRebuild && !forceConfirmed) return;
    setSubmitting(true);
    setMoveError(undefined);
    const payload: CreatePublishedMoveRequest = {
      expected_source_publication: publicationPointer(source),
      merge_decisions: mergeTargetVersionId ? mergeState.decisions : [],
      reason: reason.trim(),
      source_dataset_id: source.dataset_id,
      target: commandTarget,
      target_report_date: targetDate,
    };
    operationKey.current ??= makeUuid();
    try {
      const result = await versionCommandWrite<DraftCommandResponse>(
        `/api/admin/versions/${source.version_id}/move-date`,
        payload,
        operationKey.current,
      );
      if (result.result_kind === "published_move_revision_cancelled") {
        onNotice("已记录取消决定；来源发布和目标活动草稿均未改变。");
        onClose();
        return;
      }
      if (result.result_kind !== "published_move_revision_created" || result.status !== "draft") {
        throw new Error("移动 API 返回了无法识别的结果，未进入后续审核。");
      }
      const handoff: PublishedMoveRevisionHandoff = {
        command: result,
        reportType: source.report_type,
        sourcePublication: {
          datasetId: source.dataset_id,
          publishedAt: source.published_at,
          versionId: source.version_id,
        },
        sourceReportDate: source.report_date,
        targetPublication: targetPublicationPointer(targetPreview),
        targetReportDate: targetDate,
      };
      onNotice(`跨日期审核草稿 v${result.version_no} 已创建；来源日期继续保持发布，需审核后再最终生效。`);
      onCreated?.(handoff);
      onClose();
    } catch (caught) {
      setMoveError(moveErrorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  };

  return <MoveConfirmationView source={source} targetDate={targetDate} targetPreview={targetPreview} decision={decision} reason={reason}
    submitting={submitting} checking={checking} forceRebuild={forceRebuild} forceConfirmed={forceConfirmed} changeTargetDate={changeTargetDate}
    changeDecision={changeDecision} onForceConfirmedChange={value => { setForceConfirmed(value); resetCommandKey(); }}
    onReasonChange={value => { setReason(value); resetCommandKey(); }} onInspectTarget={() => { void inspectTarget(); }} commandReady={Boolean(commandTarget)}
    mergeReady={mergeTargetVersionId === undefined || mergeState.ready} moveError={moveError} submitLabel={submitLabel} onClose={onClose}
    onSubmit={event => { void submitMove(event); }}
    mergeMatrix={mergeTargetVersionId ? <MergeDecisionMatrix disabled={submitting} onStateChange={state => { setMergeState(state); resetCommandKey(); }} sourceId={source.version_id} sourceKind="dataset_version" targetVersionId={mergeTargetVersionId} /> : undefined} />;
}

function UndoPublishedMoveDialog({
  move,
  onClose,
  onCompleted,
  requiresReturnDedup,
}: {
  move: UndoablePublishedMoveResponse;
  onClose: () => void;
  onCompleted: (result: PublicationCommandResponse) => Promise<void>;
  requiresReturnDedup: boolean;
}) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [undoError, setUndoError] = useState<string>();
  const operationKey = useRef<string | undefined>(undefined);

  const submitUndo = async (event: FormEvent) => {
    event.preventDefault();
    const normalizedReason = reason.trim();
    if (!normalizedReason) return;
    setSubmitting(true);
    setUndoError(undefined);
    const payload: UndoPublishedMoveRequest = {
      expected_source_publication: move.source_current_publication,
      expected_target_publication: move.target_current_publication,
      reason: normalizedReason,
      restore_source_version_id: move.restore_source_version_id,
      restore_target_version_id: move.restore_target_version_id,
      source_dataset_id: move.source_dataset_id,
      target_dataset_id: move.target_dataset_id,
    };
    try {
      let result: PublicationCommandResponse | undefined;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        operationKey.current ??= makeUuid();
        try {
          if (requiresReturnDedup) {
            await prepareReturnDedupStaging({
              datasetId: move.source_dataset_id,
              operationToken: operationKey.current,
              proposedVersionId: move.restore_source_version_id,
              reportDate: move.source_report_date,
            });
          }
          result = await versionCommandWrite<PublicationCommandResponse>(
            `/api/admin/published-moves/${move.move_command_id}/undo`,
            payload,
            operationKey.current,
          );
          break;
        } catch (caught) {
          const stale = caught instanceof ReturnDedupStagingSupersededError
            || (caught instanceof ApiRequestError && [
              "return_dedup_staging_superseded",
              "return_dedup_publication_revision_conflict",
            ].includes(caught.code));
          if (!stale || attempt > 0) throw caught;
          operationKey.current = undefined;
        }
      }
      if (!result) throw new Error("退货撤销准备未能收敛，两侧发布指针保持不变。");
      await onCompleted(result);
    } catch (caught) {
      setUndoError(undoMoveErrorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  };

  return <UndoMoveConfirmationView move={move} reason={reason} submitting={submitting} undoError={undoError} onClose={onClose}
    onReasonChange={value => { setReason(value); setUndoError(undefined); operationKey.current = undefined; }} onSubmit={event => { void submitUndo(event); }} />;
}

type VersionHistoryContentProps = VersionHistoryProps & {
  onRouteFilterChange?: (filter: VersionHistoryFilter) => void;
  routeBatchReviewRunId?: number;
  routeReportDate?: string;
  routeReportType?: ReportType;
};

function VersionHistoryContent({
  initialReportDate,
  initialReportType = "business_report",
  onFilterChange,
  onForceRebuildRequest,
  onMoveRevisionCreated,
  onRevisionCreated,
  onRollbackCompleted,
  principal,
  routeBatchReviewRunId,
  routeReportDate,
  routeReportType,
  onRouteFilterChange,
}: VersionHistoryContentProps) {
  const canAdminister = principal.roles.includes("admin");
  const canManageData = canAdminister || principal.roles.includes("data_manager");
  const isViewer = principal.roles.includes("viewer")
    && !principal.roles.includes("admin")
    && !principal.roles.includes("data_manager");
  const synchronizedReportDate = routeReportDate ?? initialReportDate;
  const synchronizedReportType = routeReportType ?? initialReportType;
  const batchReviewMode = routeBatchReviewRunId !== undefined;
  const [reportDate, setReportDate] = useState(synchronizedReportDate);
  const [reportType, setReportType] = useState<ReportType>(synchronizedReportType);
  const [versions, setVersions] = useState<VersionSummaryResponse[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<number>();
  const [detail, setDetail] = useState<VersionDetailResponse>();
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [rollbackTarget, setRollbackTarget] = useState<VersionSummaryResponse>();
  const [rollbackReason, setRollbackReason] = useState("");
  const [rollbackBusy, setRollbackBusy] = useState(false);
  const [revisionSource, setRevisionSource] = useState<VersionDetailResponse>();
  const [moveSource, setMoveSource] = useState<VersionSummaryResponse>();
  const [undoableMoves, setUndoableMoves] = useState<UndoablePublishedMoveResponse[]>([]);
  const [undoTarget, setUndoTarget] = useState<UndoablePublishedMoveResponse>();
  const [undoLookupUnavailable, setUndoLookupUnavailable] = useState(false);
  const rollbackKey = useRef<string | undefined>(undefined);
  const filterChangeHandler = useRef(onFilterChange);
  const versionsRequestId = useRef(0);
  const detailRequestId = useRef(0);

  useEffect(() => { setReportDate(synchronizedReportDate); }, [synchronizedReportDate]);
  useEffect(() => { setReportType(synchronizedReportType); }, [synchronizedReportType]);
  useEffect(() => { filterChangeHandler.current = onFilterChange; }, [onFilterChange]);

  const loadUndoableMoves = useCallback(async () => {
    if (!canAdminister) {
      setUndoableMoves([]);
      setUndoLookupUnavailable(false);
      return [];
    }
    try {
      const response = await requestApi<UndoablePublishedMoveResponse[]>(
        "/api/admin/published-moves/undoable",
      );
      setUndoableMoves(response);
      setUndoLookupUnavailable(false);
      return response;
    } catch {
      setUndoableMoves([]);
      setUndoLookupUnavailable(true);
      return [];
    }
  }, [canAdminister]);

  const loadDetail = useCallback(async (
    versionId: number,
    parentVersionsRequestId?: number,
  ) => {
    const requestId = ++detailRequestId.current;
    setDetailLoading(true);
    try {
      const response = await requestApi<VersionDetailResponse>(`/api/versions/${versionId}`);
      if (
        requestId !== detailRequestId.current
        || (
          parentVersionsRequestId !== undefined
          && parentVersionsRequestId !== versionsRequestId.current
        )
      ) {
        return undefined;
      }
      const nextDetail = isViewer ? {
        ...response,
        children: response.children.filter((version) => version.status === "published"),
        parents: response.parents.filter((version) => version.status === "published"),
      } : response;
      setDetail(nextDetail);
      setSelectedVersionId(versionId);
      return nextDetail;
    } catch (reason) {
      if (requestId !== detailRequestId.current) return undefined;
      setError(errorMessage(reason));
      setDetail(undefined);
      throw reason;
    } finally {
      if (requestId === detailRequestId.current) setDetailLoading(false);
    }
  }, [isViewer]);

  const loadVersions = useCallback(async (preferredVersionId?: number) => {
    const requestId = ++versionsRequestId.current;
    ++detailRequestId.current;
    setLoading(true);
    setError(undefined);
    try {
      const path = batchReviewMode
        ? `/api/versions?batch_review_run_id=${routeBatchReviewRunId}`
        : `/api/versions?report_date=${encodeURIComponent(reportDate)}&report_type=${reportType}`;
      const response = await requestApi<VersionSummaryResponse[]>(path);
      if (requestId !== versionsRequestId.current) return [];
      const allowed = isViewer
        ? response.filter((version) => version.status === "published")
        : response;
      setVersions(allowed);
      const preferred = allowed.find((version) => version.version_id === preferredVersionId);
      const nextSelected = preferred
        ?? allowed.find((version) => version.is_current_publication)
        ?? allowed.find((version) => version.is_active_draft)
        ?? allowed[0];
      if (nextSelected) {
        try {
          await loadDetail(nextSelected.version_id, requestId);
        } catch {
          return allowed;
        }
      } else {
        setSelectedVersionId(undefined);
        setDetail(undefined);
      }
      return allowed;
    } catch (reason) {
      if (requestId !== versionsRequestId.current) return [];
      setError(errorMessage(reason));
      setVersions([]);
      setDetail(undefined);
      return [];
    } finally {
      if (requestId === versionsRequestId.current) setLoading(false);
    }
  }, [batchReviewMode, isViewer, loadDetail, reportDate, reportType, routeBatchReviewRunId]);

  useEffect(() => {
    if (!batchReviewMode) filterChangeHandler.current?.({ reportDate, reportType });
    void loadVersions();
  }, [batchReviewMode, loadVersions, reportDate, reportType]);

  useEffect(() => {
    void loadUndoableMoves();
  }, [loadUndoableMoves]);

  const currentPublication = useMemo(
    () => versions.find((version) => version.is_current_publication),
    [versions],
  );
  const activeDraft = useMemo(
    () => versions.find((version) => version.is_active_draft),
    [versions],
  );
  const selectedUndoableMove = useMemo(
    () => detail && detail.is_current_publication
      ? undoableMoves.find((move) => (
        move.report_type === detail.report_type
        && move.target_report_date === detail.report_date
        && move.target_dataset_id === detail.dataset_id
        && move.moved_target_version_id === detail.version_id
        && move.target_current_publication.version_id === detail.version_id
      ))
      : undefined,
    [detail, undoableMoves],
  );

  const selectVersion = (version: VersionSummaryResponse) => {
    setNotice(undefined);
    setError(undefined);
    void loadDetail(version.version_id).catch(() => undefined);
  };

  const openRollback = (target: VersionSummaryResponse) => {
    setRollbackTarget(target);
    setRollbackReason("");
    rollbackKey.current = undefined;
    setError(undefined);
    setNotice(undefined);
  };

  const closeRollback = () => {
    setRollbackTarget(undefined);
    setRollbackReason("");
    rollbackKey.current = undefined;
  };

  const submitRollback = async (event: FormEvent) => {
    event.preventDefault();
    if (!rollbackTarget || !currentPublication) return;
    if (rollbackTarget.dataset_id !== currentPublication.dataset_id) {
      setError("回滚目标不属于当前数据集，操作已取消。");
      return;
    }
    setRollbackBusy(true);
    setError(undefined);
    setNotice(undefined);
    const payload: RollbackRequest = {
      expected_publication: {
        published_at: currentPublication.published_at,
        version_id: currentPublication.version_id,
      },
      reason: rollbackReason.trim(),
      target_version_id: rollbackTarget.version_id,
    };
    try {
      let result: PublicationCommandResponse | undefined;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        rollbackKey.current ??= makeUuid();
        try {
          if (reportType === "return_report") {
            await prepareReturnDedupStaging({
              datasetId: rollbackTarget.dataset_id,
              operationToken: rollbackKey.current,
              proposedVersionId: rollbackTarget.version_id,
              reportDate,
            });
          }
          result = await versionCommandWrite<PublicationCommandResponse>(
            `/api/admin/datasets/${rollbackTarget.dataset_id}/rollback`,
            payload,
            rollbackKey.current,
          );
          break;
        } catch (caught) {
          const stale = caught instanceof ReturnDedupStagingSupersededError
            || (caught instanceof ApiRequestError && [
              "return_dedup_staging_superseded",
              "return_dedup_publication_revision_conflict",
            ].includes(caught.code));
          if (!stale || attempt > 0) throw caught;
          rollbackKey.current = undefined;
        }
      }
      if (!result) throw new Error("退货回滚准备未能收敛，发布指针保持不变。");
      const targetVersionNo = rollbackTarget.version_no;
      const targetVersionId = rollbackTarget.version_id;
      closeRollback();
      setNotice(`已回滚到 v${targetVersionNo}；其他日期和报表类型未受影响。`);
      await loadVersions(targetVersionId);
      onRollbackCompleted?.(result);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setRollbackBusy(false);
    }
  };

  const completeMoveUndo = async (result: PublicationCommandResponse) => {
    if (!undoTarget) return;
    if (result.command_type !== "reverse_move") {
      throw new Error("撤销 API 返回了无法识别的发布结果，页面未刷新。");
    }
    const completedMove = undoTarget;
    setUndoTarget(undefined);
    setError(undefined);
    setNotice(
      `${completedMove.source_report_date} ← ${completedMove.target_report_date} 的跨日期移动已撤销；两侧发布指针已同时恢复。`,
    );
    await Promise.all([
      loadVersions(completedMove.restore_target_version_id ?? undefined),
      loadUndoableMoves(),
    ]);
  };

  return <VersionHistoryView reportDate={reportDate} reportType={reportType}
    setReportDate={(nextDate) => { setReportDate(nextDate); onRouteFilterChange?.({ reportDate: nextDate, reportType }); }}
    setReportType={(nextType) => { setReportType(nextType); onRouteFilterChange?.({ reportDate, reportType: nextType }); }}
    batchReviewMode={batchReviewMode} routeBatchReviewRunId={routeBatchReviewRunId} canAdminister={canAdminister} canManageData={canManageData} isViewer={isViewer}
    undoLookupUnavailable={undoLookupUnavailable} notice={notice} error={error} versions={versions} currentPublication={currentPublication} activeDraft={activeDraft}
    selectedVersionId={selectedVersionId} loading={loading} detailLoading={detailLoading} detail={detail} selectedUndoableMove={selectedUndoableMove}
    onForceRebuildRequest={onForceRebuildRequest} openRollback={openRollback} selectVersion={selectVersion} onRevision={setRevisionSource} onMove={setMoveSource}
    onUndoMove={() => setUndoTarget(selectedUndoableMove)} onRetry={() => void loadVersions(selectedVersionId)}
    batchHistory={canManageData && !batchReviewMode ? <BatchReviewHistory /> : undefined}
    versionRows={detail?.status === "published" ? <VersionRows key={detail.version_id} versionId={detail.version_id} versionNo={detail.version_no} reportDate={detail.report_date} /> : undefined}>
      {rollbackTarget && currentPublication && (
        <RollbackConfirmationView current={currentPublication} target={rollbackTarget} reportDate={reportDate} reportType={reportType}
          reason={rollbackReason} submitting={rollbackBusy} error={error} onClose={closeRollback}
          onReasonChange={value => { setRollbackReason(value); rollbackKey.current = undefined; }} onSubmit={event => { void submitRollback(event); }} />
      )}

      {revisionSource && (
        <PublishedRevisionDialog
          onClose={() => setRevisionSource(undefined)}
          onCreated={onRevisionCreated}
          onNotice={(message) => { setError(undefined); setNotice(message); }}
          source={revisionSource}
        />
      )}

      {moveSource && (
        <PublishedMoveDialog
          onClose={() => setMoveSource(undefined)}
          onCreated={onMoveRevisionCreated}
          onNotice={(message) => { setError(undefined); setNotice(message); }}
          source={moveSource}
        />
      )}

      {undoTarget && (
        <UndoPublishedMoveDialog
          move={undoTarget}
          onClose={() => setUndoTarget(undefined)}
          onCompleted={completeMoveUndo}
          requiresReturnDedup={reportType === "return_report"}
        />
      )}
  </VersionHistoryView>;
}

function RoutedVersionHistory(props: VersionHistoryProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedBatchRun = Number(searchParams.get("batch_review_run_id"));
  const requestedDate = searchParams.get("report_date");
  const requestedType = searchParams.get("report_type");
  const routeReportDate = requestedDate && /^\d{4}-\d{2}-\d{2}$/.test(requestedDate)
    ? requestedDate
    : undefined;
  const routeReportType = requestedType === "business_report" || requestedType === "return_report"
    ? requestedType
    : undefined;
  return <VersionHistoryContent
    {...props}
    onRouteFilterChange={({ reportDate, reportType }) => setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("report_date", reportDate);
      next.set("report_type", reportType);
      return next;
    })}
    routeBatchReviewRunId={Number.isSafeInteger(requestedBatchRun) && requestedBatchRun > 0 ? requestedBatchRun : undefined}
    routeReportDate={routeReportDate}
    routeReportType={routeReportType}
  />;
}

export function VersionHistory(props: VersionHistoryProps) {
  const isRouted = useInRouterContext();
  return isRouted ? <RoutedVersionHistory {...props} /> : <VersionHistoryContent {...props} />;
}
