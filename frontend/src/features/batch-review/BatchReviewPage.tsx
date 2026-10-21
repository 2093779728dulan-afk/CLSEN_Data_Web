import css from "./BatchReviewPage.module.css";
import { Button, ErrorState, LinkButton, Skeleton } from "../../design-system";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { ApiRequestError } from "../../api/client";
import { BatchReviewApi } from "./batchReviewApi";
import { BatchReviewCompletionActions } from "./BatchReviewCompletionActions";
import { BatchReviewPreflightTable } from "./BatchReviewPreflightTable";
import { BatchReviewProgressTable } from "./BatchReviewProgressTable";
import { BatchReviewSummary } from "./BatchReviewSummary";
import { runBatchReviewExecutor } from "./batchReviewExecutor";
import type { BatchReviewItem, BatchReviewRun } from "./batchReviewTypes";


function pageError(reason: unknown) {
  if (reason instanceof ApiRequestError) {
    if (reason.status === 403) return "你没有查看或操作此批量任务的权限。";
    if (reason.status === 404) return "批量任务不存在，或不属于当前站点。";
    if (reason.status === 401) return "登录状态已失效，请重新登录后恢复任务。";
    if (reason.status === 409) return "任务状态已变化，已重新读取服务器状态。";
  }
  return reason instanceof Error ? reason.message : "无法读取批量任务。";
}

export function BatchReviewPage({ runId: suppliedRunId }: { runId?: number }) {
  const params = useParams();
  const routeRunId = Number(params.runId);
  const runId = suppliedRunId ?? routeRunId;
  return <BatchReviewRunPage key={runId} runId={runId} />;
}

function BatchReviewRunPage({ runId }: { runId: number }) {
  const api = useMemo(() => new BatchReviewApi(), []);
  const [run, setRun] = useState<BatchReviewRun>();
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [accepted, setAccepted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string>();
  const [busyItemId, setBusyItemId] = useState<number>();
  const [error, setError] = useState<string>();
  const [retryGeneration, setRetryGeneration] = useState(0);
  const executorRef = useRef<Promise<void>>(Promise.resolve());
  const runRef = useRef<BatchReviewRun | undefined>(undefined);
  runRef.current = run;

  const load = useCallback(async () => {
    if (!Number.isSafeInteger(runId) || runId < 1) {
      setError("批量任务编号无效。");
      setLoading(false);
      return undefined;
    }
    setError(undefined);
    try {
      const snapshot = await api.getRun(runId);
      setRun(snapshot);
      if (snapshot.status === "preview") {
        setSelectedIds(new Set(snapshot.items.filter((item) => item.status === "eligible" && item.selected).map((item) => item.id)));
      }
      return snapshot;
    } catch (reason) {
      setError(pageError(reason));
      return undefined;
    } finally {
      setLoading(false);
    }
  }, [api, runId]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    const snapshot = runRef.current;
    if (!snapshot || snapshot.status !== "running") return undefined;
    const controller = new AbortController();
    // Abort stops scheduling, not server work. Drain it before starting another pass.
    executorRef.current = executorRef.current.then(async () => {
      if (controller.signal.aborted) return;
      const current = await api.getRun(snapshot.id);
      if (controller.signal.aborted) return;
      setRun(current);
      const result = await runBatchReviewExecutor(
        current,
        (item) => api.advance(current.id, item.id, item.operation_token),
        () => api.getRun(current.id),
        {
          signal: controller.signal,
          onSnapshot: (next) => { if (!controller.signal.aborted) setRun(next); },
        },
      );
      if (!controller.signal.aborted) setRun(result);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(pageError(reason));
    });
    return () => controller.abort();
  }, [api, run?.id, run?.status, retryGeneration]);

  useEffect(() => {
    if (!run || run.status !== "running") return undefined;
    const needsPoll = run.items.some((item) => ["parsing", "materializing", "validating"].includes(item.status));
    if (!needsPoll) return undefined;
    const timer = window.setTimeout(() => { void load(); }, 1200);
    return () => window.clearTimeout(timer);
  }, [load, run]);

  const refreshAfterConflict = async (reason: unknown) => {
    if (reason instanceof ApiRequestError && (reason.status === 409 || reason.code === "outcome_unknown")) {
      await load();
    }
    setError(pageError(reason));
  };

  const confirm = async () => {
    if (!run || selectedIds.size === 0 || !accepted) return;
    setBusyAction("confirm"); setError(undefined);
    try { setRun(await api.confirm(run.id, run.revision, [...selectedIds])); }
    catch (reason) { await refreshAfterConflict(reason); }
    finally { setBusyAction(undefined); }
  };

  const changeState = async (action: "pause" | "resume") => {
    if (!run) return;
    setBusyAction(action); setError(undefined);
    try { setRun(await api[action](run.id, run.revision)); }
    catch (reason) { await refreshAfterConflict(reason); }
    finally { setBusyAction(undefined); }
  };

  const retry = async (item: BatchReviewItem) => {
    if (!run) return;
    setBusyItemId(item.id); setError(undefined);
    try {
      setRun(await api.retry(run.id, item.id, run.revision));
      setRetryGeneration((generation) => generation + 1);
    }
    catch (reason) { await refreshAfterConflict(reason); }
    finally { setBusyItemId(undefined); }
  };

  if (loading) return <main className={css["batch-review-page"]} id="main-content"><p role="status">正在读取批量任务…</p><Skeleton lines={4} /></main>;
  if (!run) return <main className={css["batch-review-page"]} id="main-content"><ErrorState title="无法打开批量审核" description={error} action={<Button onClick={() => { setLoading(true); void load(); }}>重新读取</Button>} /></main>;

  return <main className={css["batch-review-page"]} id="main-content">
    <nav aria-label="批量审核导航"><LinkButton to="/versions">返回版本记录</LinkButton></nav>
    <BatchReviewSummary run={run} />
    {error ? <p className={"form-error"} role="alert">{error}</p> : null}
    {run.status === "preview" ? <section aria-labelledby="batch-review-preflight-title" className={css["batch-review-panel"]}>
      <div className={css["batch-review-heading-row"]}><div><p className={"eyebrow"}>服务端权威预检</p><h2 id="batch-review-preflight-title">核对文件清单</h2></div><Button variant="quiet" onClick={() => void load()} type="button">刷新预检</Button></div>
      <BatchReviewPreflightTable items={run.items} onToggle={(itemId, selected) => setSelectedIds((current) => { const next = new Set(current); if (selected) next.add(itemId); else next.delete(itemId); return next; })} selectedIds={selectedIds} />
      <label className={css["batch-review-confirmation"]}><input checked={accepted} onChange={(event) => setAccepted(event.currentTarget.checked)} type="checkbox" /><span>我已核对所选文件的报告日期和报表类型。</span></label>
      <Button variant="primary" disabled={!accepted || selectedIds.size === 0 || busyAction === "confirm"} onClick={() => void confirm()} type="button">{busyAction === "confirm" ? "正在开始…" : `开始批量审核（${selectedIds.size} 项）`}</Button>
    </section> : <section aria-labelledby="batch-review-progress-title" className={css["batch-review-panel"]}>
      <div className={css["batch-review-heading-row"]}><div><p className={"eyebrow"}>服务器恢复状态</p><h2 id="batch-review-progress-title">处理进度</h2></div><div className={css["batch-review-actions"]}>
        {run.allowed_actions.includes("pause") ? <Button variant="quiet" disabled={busyAction === "pause"} onClick={() => void changeState("pause")} type="button">{busyAction === "pause" ? "正在暂停…" : "暂停批量处理"}</Button> : null}
        {run.allowed_actions.includes("resume") ? <Button variant="primary" disabled={busyAction === "resume"} onClick={() => void changeState("resume")} type="button">{busyAction === "resume" ? "正在恢复…" : "恢复批量处理"}</Button> : null}
        <Button variant="quiet" onClick={() => void load()} type="button">刷新状态</Button>
      </div></div>
      <BatchReviewProgressTable busyItemId={busyItemId} items={run.items} onRetry={(item) => void retry(item)} />
    </section>}
    <BatchReviewCompletionActions run={run} />
  </main>;
}
