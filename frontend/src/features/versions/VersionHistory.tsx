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
  VersionLineageResponse,
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

type MoveTargetPreview =
  | { kind: "empty" }
  | PublishedTargetPreview
  | ActiveDraftTargetPreview
  | { datasetId: number; kind: "pointerless" }
  | { kind: "invalid"; message: string };

type MoveDecision =
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

function reportTypeLabel(reportType: ReportType) {
  return reportType === "business_report" ? "经营报告" : "退货报告";
}

function statusLabel(version: VersionSummaryResponse) {
  if (version.is_current_publication) return "当前发布";
  if (version.is_active_draft) return "活动草稿";
  if (version.status === "ready_for_publish") return "待发布";
  if (version.status === "published") return "历史发布";
  if (version.status === "discarded") return "已废弃";
  return "草稿";
}

function formatTimestamp(value: string | null) {
  if (!value) return "—";
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    hour12: false,
    timeStyle: "short",
  }).format(instant);
}

function lineageLabel(lineage: VersionLineageResponse) {
  const labels: Record<VersionLineageResponse["lineage_type"], string> = {
    base: "基础版本",
    draft_predecessor: "草稿前序",
    merge_source: "合并来源",
    merge_target: "合并目标",
    moved_source: "跨日来源",
  };
  return `${labels[lineage.lineage_type]} · v${lineage.version_no}`;
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

  return (
    <div className="version-history__dialog-layer" role="presentation">
      <form
        aria-label="创建发布修订"
        className="version-history__dialog"
        onSubmit={(event) => { void submit(event); }}
        role="dialog"
      >
        <header>
          <div><span>PUBLISHED REVISION</span><h2>基于 v{source.version_no} 创建修订</h2></div>
          <button aria-label="关闭创建修订" disabled={submitting} onClick={onClose} type="button">×</button>
        </header>
        <p>当前发布版本保持在线；系统会创建一个新的审核草稿，审核并发布后才会切换发布指针。</p>
        <dl>
          <div><dt>报告日</dt><dd>{source.report_date}</dd></div>
          <div><dt>当前发布</dt><dd>v{source.version_no}</dd></div>
        </dl>
        <label>
          修订原因
          <textarea
            disabled={submitting}
            onChange={(event) => {
              setReason(event.target.value);
              operationKey.current = undefined;
            }}
            required
            rows={4}
            value={reason}
          />
        </label>
        {error && <p className="version-history__error" role="alert">{error}</p>}
        <footer>
          <button className="version-history__secondary" disabled={submitting} onClick={onClose} type="button">取消</button>
          <button className="version-history__primary" disabled={submitting || !reason.trim()} type="submit">
            {submitting ? "正在创建…" : "确认创建修订"}
          </button>
        </footer>
      </form>
    </div>
  );
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

  return (
    <div className="version-history__dialog-layer" role="presentation">
      <form
        aria-label="已发布数据跨日期移动"
        aria-modal="true"
        className="version-history__dialog version-history__dialog--move"
        onSubmit={(event) => { void submitMove(event); }}
        role="dialog"
      >
        <header>
          <div><span>ADMIN DATE MOVE</span><h2>移动当前发布版本</h2></div>
          <button aria-label="关闭跨日期移动" disabled={submitting} onClick={onClose} type="button">×</button>
        </header>

        <div className="version-history__move-route" aria-label="移动日期范围">
          <div><span>来源报告日</span><strong>{source.report_date}</strong><small>v{source.version_no} 保持发布</small></div>
          <span aria-hidden="true">→</span>
          <div><span>目标报告日</span><strong>{targetDate || "尚未选择"}</strong><small>{reportTypeLabel(source.report_type)}</small></div>
        </div>

        <div className="version-history__target-check">
          <label>目标报告日<input disabled={submitting} max="9999-12-31" min="2000-01-01" onChange={(event) => changeTargetDate(event.target.value)} required type="date" value={targetDate} /></label>
          <button className="version-history__secondary" disabled={submitting || checking || !targetDate || targetDate === source.report_date} onClick={() => { void inspectTarget(); }} type="button">{checking ? "正在检查…" : "检查目标日期"}</button>
        </div>

        {targetPreview?.kind === "empty" && (
          <section className="version-history__target-state version-history__target-state--empty">
            <strong>目标日期尚无数据</strong>
            <p>将创建新的目标数据集和活动草稿；来源发布版本在审核期间继续生效。</p>
          </section>
        )}

        {targetPreview?.kind === "published" && (
          <section className="version-history__target-state">
            <strong>目标日期已有发布版本 v{targetPreview.publication.version_no}</strong>
            <p>选择如何生成审核草稿。此步骤不会立即切换任一日期的发布指针。</p>
            <fieldset className="version-history__decision-list">
              <legend>目标处理方式</legend>
              <label><input aria-label="合并目标发布版本" checked={decision === "merge_published"} disabled={submitting} name="published-target" onChange={() => changeDecision("merge_published")} type="radio" />合并目标发布版本<span>保留目标与来源数据，行冲突由服务端阻断，绝不自动覆盖。</span></label>
              <label><input aria-label="替换目标发布版本" checked={decision === "replace_published"} disabled={submitting} name="published-target" onChange={() => changeDecision("replace_published")} type="radio" />替换目标发布版本<span>审核草稿只以来源版本为基础；最终生效仍需完整校验和确认。</span></label>
              <label><input aria-label="取消本次移动" checked={decision === "client_cancel"} disabled={submitting} name="published-target" onChange={() => changeDecision("client_cancel")} type="radio" />取消本次移动<span>关闭流程，不向服务器发送写请求。</span></label>
            </fieldset>
          </section>
        )}

        {targetPreview?.kind === "active_draft" && (
          <section className="version-history__target-state version-history__target-state--draft">
            <strong>目标日期已有活动草稿 v{targetPreview.draft.version_no}</strong>
            <p>所有选项都绑定当前草稿修订与指针时间；目标状态变化时服务器将拒绝命令。</p>
            <fieldset className="version-history__decision-list">
              <legend>活动草稿处理方式</legend>
              <label><input aria-label="合并到活动草稿" checked={decision === "merge_draft"} disabled={submitting} name="draft-target" onChange={() => changeDecision("merge_draft")} type="radio" />合并到活动草稿<span>生成合并草稿并保留两侧谱系，旧活动草稿作为已审计前序版本封存。</span></label>
              <label><input aria-label="记录取消，保留活动草稿" checked={decision === "cancel_draft"} disabled={submitting} name="draft-target" onChange={() => changeDecision("cancel_draft")} type="radio" />记录取消，保留活动草稿<span>服务器记录取消决定，不修改来源发布或目标草稿。</span></label>
              {targetPreview.publication && <label><input aria-label="强制重建并合并目标发布" checked={decision === "force_merge"} disabled={submitting} name="draft-target" onChange={() => changeDecision("force_merge")} type="radio" />强制重建并合并目标发布<span>废弃当前活动草稿，以目标发布版本与来源版本合并重建。</span></label>}
              <label><input aria-label="强制重建，仅保留来源版本" checked={decision === "force_replace"} disabled={submitting} name="draft-target" onChange={() => changeDecision("force_replace")} type="radio" />强制重建，仅保留来源版本<span>废弃当前活动草稿，新草稿只复制来源发布版本。</span></label>
            </fieldset>
          </section>
        )}

        {targetPreview?.kind === "pointerless" && (
          <section className="version-history__target-state version-history__target-state--blocked">
            <strong>目标日期只有历史版本，但没有活动草稿或当前发布指针。</strong>
            <p>当前移动 API 无法可靠表达这个目标状态，系统不会猜测或自动覆盖。</p>
          </section>
        )}

        {targetPreview?.kind === "invalid" && (
          <section className="version-history__target-state version-history__target-state--blocked">
            <strong>目标指针状态不完整</strong><p>{targetPreview.message} 系统不会继续创建草稿。</p>
          </section>
        )}

        {targetPreview && decision && decision !== "client_cancel" && targetPreview.kind !== "pointerless" && targetPreview.kind !== "invalid" && (
          <label>移动原因<textarea disabled={submitting} maxLength={1000} onChange={(event) => { setReason(event.target.value); resetCommandKey(); }} required rows={3} value={reason} /></label>
        )}

        {mergeTargetVersionId && <MergeDecisionMatrix disabled={submitting} onStateChange={(state) => { setMergeState(state); resetCommandKey(); }} sourceId={source.version_id} sourceKind="dataset_version" targetVersionId={mergeTargetVersionId} />}

        {forceRebuild && (
          <label className="version-history__force-confirm"><input checked={forceConfirmed} disabled={submitting} onChange={(event) => { setForceConfirmed(event.target.checked); resetCommandKey(); }} type="checkbox" />我确认目标活动草稿会被废弃，但审计记录会保留。</label>
        )}

        {moveError && <p className="version-history__dialog-error" role="alert">{moveError}</p>}
        <p className="version-history__warning">这里只创建目标日期的审核草稿。来源发布数据在最终审核生效前不会被撤下。</p>
        <footer>
          <button className="version-history__secondary" disabled={submitting} onClick={onClose} type="button">返回版本记录</button>
          {decision === "client_cancel" ? (
            <button className="version-history__secondary" disabled={submitting} onClick={onClose} type="button">关闭且不创建移动草稿</button>
          ) : commandTarget ? (
            <button className={forceRebuild ? "version-history__danger" : "version-history__primary"} disabled={submitting || !reason.trim() || (forceRebuild && !forceConfirmed) || (mergeTargetVersionId !== undefined && !mergeState.ready)} type="submit">{submitting ? "正在提交…" : submitLabel}</button>
          ) : null}
        </footer>
      </form>
    </div>
  );
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

  return (
    <div className="version-history__dialog-layer" role="presentation">
      <form
        aria-label="撤销跨日期移动确认"
        aria-modal="true"
        className="version-history__dialog version-history__dialog--move"
        onSubmit={(event) => { void submitUndo(event); }}
        role="dialog"
      >
        <header>
          <div><span>ADMIN MOVE REVERSAL</span><h2>撤销跨日期移动</h2></div>
          <button aria-label="关闭撤销确认" disabled={submitting} onClick={onClose} type="button">×</button>
        </header>

        <p>系统将同时锁定两个报告日，并在一个事务内恢复两侧发布指针。</p>
        <div className="version-history__move-route version-history__move-route--reverse" aria-label="撤销后的日期恢复路线">
          <div>
            <span>恢复来源报告日</span>
            <strong>{move.source_report_date}</strong>
            <small>恢复版本 #{move.restore_source_version_id}</small>
          </div>
          <span aria-hidden="true">←</span>
          <div>
            <span>撤销目标报告日</span>
            <strong>{move.target_report_date}</strong>
            <small>{move.restore_target_version_id === null ? "恢复为无发布版本" : `恢复版本 #${move.restore_target_version_id}`}</small>
          </div>
        </div>

        <dl>
          <div><dt>当前目标版本</dt><dd>#{move.moved_target_version_id}</dd></div>
          <div><dt>原移动命令</dt><dd>#{move.move_command_id}</dd></div>
          <div><dt>移动完成时间</dt><dd>{formatTimestamp(move.completed_at)}</dd></div>
        </dl>
        <label>
          撤销原因
          <textarea
            disabled={submitting}
            maxLength={1000}
            onChange={(event) => {
              setReason(event.target.value);
              setUndoError(undefined);
              operationKey.current = undefined;
            }}
            required
            rows={4}
            value={reason}
          />
        </label>
        {undoError && <p className="version-history__dialog-error" role="alert">{undoError}</p>}
        <p className="version-history__warning">任一日期已有新发布或活动草稿时，服务器会拒绝整个操作，不会只恢复一侧。</p>
        <footer>
          <button className="version-history__secondary" disabled={submitting} onClick={onClose} type="button">保留当前移动</button>
          <button className="version-history__danger" disabled={submitting || !reason.trim()} type="submit">
            {submitting ? "正在撤销…" : "确认撤销跨日期移动"}
          </button>
        </footer>
      </form>
    </div>
  );
}

function VersionSpine({
  canAdminister,
  currentPublication,
  onForceRebuildRequest,
  onRollback,
  onSelect,
  selectedVersionId,
  versions,
}: {
  canAdminister: boolean;
  currentPublication?: VersionSummaryResponse;
  onForceRebuildRequest?: (draft: VersionSummaryResponse) => void;
  onRollback: (version: VersionSummaryResponse) => void;
  onSelect: (version: VersionSummaryResponse) => void;
  selectedVersionId?: number;
  versions: VersionSummaryResponse[];
}) {
  return (
    <ol className="version-history__spine">
      {versions.map((version) => {
        const rollbackEligible = canAdminister
          && version.status === "published"
          && !version.is_current_publication
          && currentPublication?.dataset_id === version.dataset_id;
        return (
          <li
            className={`version-history__spine-item version-history__spine-item--${version.status}${version.is_current_publication ? " version-history__spine-item--current" : ""}`}
            key={version.version_id}
          >
            <span className="version-history__node" aria-hidden="true" />
            <article aria-current={selectedVersionId === version.version_id ? "true" : undefined}>
              <button
                aria-label={`查看版本 v${version.version_no}，${statusLabel(version)}`}
                className="version-history__select"
                onClick={() => onSelect(version)}
                type="button"
              >
                <span className="version-history__version-no">v{version.version_no}</span>
                <span className={`version-history__state version-history__state--${version.is_current_publication ? "published" : version.is_active_draft ? "draft" : version.status}`}>
                  {statusLabel(version)}
                </span>
                <small>{formatTimestamp(version.created_at)}</small>
                <span className="version-history__revision">数据 r{version.data_revision} · 审核 r{version.review_revision}</span>
              </button>
              <div className="version-history__item-actions">
                {rollbackEligible && <button onClick={() => onRollback(version)} type="button">回滚到 v{version.version_no}</button>}
                {canAdminister && version.is_active_draft && onForceRebuildRequest && (
                  <button onClick={() => onForceRebuildRequest(version)} type="button">请求重建 v{version.version_no}</button>
                )}
              </div>
            </article>
          </li>
        );
      })}
    </ol>
  );
}

function LineageList({
  emptyText,
  items,
}: {
  emptyText: string;
  items: VersionLineageResponse[];
}) {
  if (items.length === 0) return <p className="version-history__lineage-empty">{emptyText}</p>;
  return (
    <ul className="version-history__lineage-list">
      {items.map((item) => (
        <li key={`${item.version_id}:${item.lineage_type}:${item.lineage_ordinal}`}>
          <span>{lineageLabel(item)}</span>
          <small>{item.report_date} · {reportTypeLabel(item.report_type)}</small>
        </li>
      ))}
    </ul>
  );
}

type VersionHistoryContentProps = VersionHistoryProps & {
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

  return (
    <main className="version-history" id="main-content">
      <header className="version-history__hero">
        <div>
          <p className="version-history__kicker">IMMUTABLE VERSION LINEAGE</p>
          <h1>版本记录</h1>
          <p>{batchReviewMode ? `仅显示批量任务 #${routeBatchReviewRunId} 产生且当前仍为待发布的草稿。` : "每个报告日与报表类型独立维护发布指针。历史版本不会覆盖，回滚也会留下新的发布事件。"}</p>
        </div>
        {!batchReviewMode ? <form aria-label="版本筛选" className="version-history__filters">
          <label>报告日期<input onChange={(event) => setReportDate(event.target.value)} type="date" value={reportDate} /></label>
          <label>报表类型<select onChange={(event) => setReportType(event.target.value as ReportType)} value={reportType}><option value="business_report">经营报告</option><option value="return_report">退货报告</option></select></label>
        </form> : <a className="version-history__secondary" href={`/review/batch/${routeBatchReviewRunId}`}>返回批量任务</a>}
      </header>

      {canManageData && !batchReviewMode && <BatchReviewHistory />}
      {isViewer && <p className="version-history__boundary">查看人员仅能读取已发布版本和查看人员可见备注。</p>}
      {canAdminister && undoLookupUnavailable && (
        <p className="version-history__boundary">撤销状态暂时无法读取；已隐藏撤销入口，版本浏览不受影响。</p>
      )}
      {notice && <p className="version-history__notice" aria-live="polite">{notice}</p>}
      {error && <p className="version-history__error" role="alert">{error}</p>}

      <section className="version-history__docket" aria-labelledby="version-docket-title">
        <div>
          <span>{batchReviewMode ? "BATCH REVIEW RESULTS" : "REPORT SLICE"}</span>
          <h2 id="version-docket-title">{batchReviewMode ? `批量任务 #${routeBatchReviewRunId} · 待发布草稿` : `${reportTypeLabel(reportType)} · ${reportDate}`}</h2>
        </div>
        <dl>
          <div><dt>当前发布</dt><dd>{currentPublication ? `v${currentPublication.version_no}` : "—"}</dd></div>
          <div><dt>活动草稿</dt><dd>{activeDraft ? `v${activeDraft.version_no}` : "—"}</dd></div>
          <div><dt>可见版本</dt><dd>{versions.length}</dd></div>
        </dl>
      </section>

      {loading ? (
        <p className="version-history__loading">{batchReviewMode ? "正在读取任务的待发布草稿…" : "正在读取该日期的版本谱系…"}</p>
      ) : versions.length === 0 ? (
        <section className="version-history__empty">
          <span aria-hidden="true">v</span>
          <div><h2>{batchReviewMode ? "此任务当前没有待发布草稿。" : `该日期的${reportTypeLabel(reportType)}还没有版本。`}</h2><p>{batchReviewMode ? "草稿发布、退回或发生状态变化后会自动离开此筛选。" : "完成导入、审核与发布后，版本证据会出现在这里。"}</p></div>
        </section>
      ) : (
        <div className="version-history__workspace">
          <section aria-labelledby="version-list-title" className="version-history__list-panel">
            <header><p>VERSION SPINE</p><h2 id="version-list-title">不可变版本脊柱</h2></header>
            <VersionSpine
              canAdminister={canAdminister}
              currentPublication={currentPublication}
              onForceRebuildRequest={onForceRebuildRequest}
              onRollback={openRollback}
              onSelect={selectVersion}
              selectedVersionId={selectedVersionId}
              versions={versions}
            />
          </section>

          <section aria-labelledby="version-detail-title" className="version-history__detail-panel">
            {detailLoading && <p className="version-history__loading">正在读取版本详情…</p>}
            {!detailLoading && detail && (
              <>
                <header className="version-history__detail-heading">
                  <div><span>VERSION #{detail.version_id}</span><h2 id="version-detail-title">v{detail.version_no} · {statusLabel(detail)}</h2></div>
                  <div className="version-history__detail-actions">
                    <a href={`/${canManageData ? "review" : "published"}/${detail.report_date}?report_type=${detail.report_type}`}>{detail.is_active_draft && canManageData ? "继续审核草稿" : "返回日期工作台"}</a>
                    <span className={`version-history__seal version-history__seal--${detail.is_current_publication ? "published" : detail.is_active_draft ? "draft" : detail.status}`}>{statusLabel(detail)}</span>
                    {canManageData && detail.is_current_publication && (
                      <button
                        className="version-history__move-action"
                        disabled={Boolean(activeDraft) || !detail.published_at}
                        onClick={() => setRevisionSource(detail)}
                        title={activeDraft
                          ? "该报告已有活动草稿，需先完成或废弃该草稿。"
                          : !detail.published_at
                            ? "当前发布缺少发布时间，无法建立并发预期。"
                            : undefined}
                        type="button"
                      >
                        创建修订
                      </button>
                    )}
                    {canAdminister && detail.is_current_publication && (
                      <button
                        className="version-history__move-action"
                        disabled={Boolean(activeDraft) || !detail.published_at}
                        onClick={() => setMoveSource(detail)}
                        title={activeDraft ? "来源日期已有活动草稿，需先完成或废弃该草稿。" : undefined}
                        type="button"
                      >
                        移动到其他日期
                      </button>
                    )}
                    {selectedUndoableMove && (
                      <button
                        className="version-history__undo-move-action"
                        onClick={() => setUndoTarget(selectedUndoableMove)}
                        type="button"
                      >
                        撤销跨日期移动
                      </button>
                    )}
                  </div>
                </header>
                {detail.status === "published" && <VersionRows key={detail.version_id} versionId={detail.version_id} versionNo={detail.version_no} reportDate={detail.report_date} />}
                {canManageData && detail.is_current_publication && activeDraft && (
                  <p className="version-history__source-draft-block">该报告已有活动草稿 v{activeDraft.version_no}；请先完成或废弃该草稿，再创建新的修订。</p>
                )}
                <dl className="version-history__facts">
                  <div><dt>创建时间</dt><dd>{formatTimestamp(detail.created_at)}</dd></div>
                  <div><dt>封存时间</dt><dd>{formatTimestamp(detail.sealed_at)}</dd></div>
                  <div><dt>发布时间</dt><dd>{formatTimestamp(detail.published_at)}</dd></div>
                  <div><dt>修订</dt><dd>数据 r{detail.data_revision} / 审核 r{detail.review_revision}</dd></div>
                </dl>

                <div className="version-history__lineage-grid">
                  <section><h3>父版本</h3><LineageList emptyText="没有父版本；这是该链的起点。" items={detail.parents} /></section>
                  <section><h3>后续版本</h3><LineageList emptyText="没有后续版本。" items={detail.children} /></section>
                </div>

                <section className="version-history__notes" aria-labelledby="viewer-notes-title">
                  <header><h3 id="viewer-notes-title">查看人员可见备注</h3><span>{detail.viewer_visible_notes.length} 条</span></header>
                  {detail.viewer_visible_notes.length > 0 ? (
                    <ol>{detail.viewer_visible_notes.map((note) => <li key={note.note_key}><p>{note.body}</p><span>修订 {note.revision_number} · {formatTimestamp(note.created_at)}</span></li>)}</ol>
                  ) : <p>此版本没有查看人员可见备注。</p>}
                </section>
              </>
            )}
          </section>
        </div>
      )}

      {rollbackTarget && currentPublication && (
        <div className="version-history__dialog-layer" role="presentation">
          <form aria-label="管理员回滚确认" className="version-history__dialog" onSubmit={(event) => { void submitRollback(event); }} role="dialog">
            <header><div><span>ADMIN ROLLBACK</span><h2>回滚到 v{rollbackTarget.version_no}</h2></div><button aria-label="关闭回滚确认" disabled={rollbackBusy} onClick={closeRollback} type="button">×</button></header>
            <p>只切换 {reportDate} · {reportTypeLabel(reportType)} 的发布指针。</p>
            <dl><div><dt>当前发布</dt><dd>v{currentPublication.version_no}</dd></div><div><dt>回滚目标</dt><dd>v{rollbackTarget.version_no}</dd></div></dl>
            <label>回滚原因<textarea disabled={rollbackBusy} onChange={(event) => { setRollbackReason(event.target.value); rollbackKey.current = undefined; }} required rows={4} value={rollbackReason} /></label>
            <p className="version-history__warning">回滚不会删除当前版本；系统会追加一条发布事件，并立即让看板读取目标版本。</p>
            <footer><button className="version-history__secondary" disabled={rollbackBusy} onClick={closeRollback} type="button">取消</button><button className="version-history__danger" disabled={rollbackBusy || !rollbackReason.trim()} type="submit">{rollbackBusy ? "正在回滚…" : `确认回滚到 v${rollbackTarget.version_no}`}</button></footer>
          </form>
        </div>
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
    </main>
  );
}

function RoutedVersionHistory(props: VersionHistoryProps) {
  const [searchParams] = useSearchParams();
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
    routeBatchReviewRunId={Number.isSafeInteger(requestedBatchRun) && requestedBatchRun > 0 ? requestedBatchRun : undefined}
    routeReportDate={routeReportDate}
    routeReportType={routeReportType}
  />;
}

export function VersionHistory(props: VersionHistoryProps) {
  const isRouted = useInRouterContext();
  return isRouted ? <RoutedVersionHistory {...props} /> : <VersionHistoryContent {...props} />;
}
