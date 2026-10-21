import { BatchReviewView } from "./BatchReviewView";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { ApiRequestError } from "../../api/client";
import { BatchReviewApi } from "./batchReviewApi";
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
          onEvent: (event) => console.info("batch_review_runtime", event),
          onItemResult: (result) => {
            if (!controller.signal.aborted && result.outcome === "failed") setError(pageError(result.error));
          },
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

  return <BatchReviewView run={run} loading={loading} error={error} selectedIds={selectedIds} accepted={accepted} busyAction={busyAction} busyItemId={busyItemId}
    onRefresh={() => { if (!run) setLoading(true); void load(); }}
    onToggle={(itemId, selected) => setSelectedIds((current) => { const next = new Set(current); if (selected) next.add(itemId); else next.delete(itemId); return next; })}
    onAccept={setAccepted} onConfirm={() => void confirm()} onChangeState={(action) => void changeState(action)} onRetry={(item) => void retry(item)} />;
}
