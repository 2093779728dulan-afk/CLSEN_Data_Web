import type { BatchReviewItem, BatchReviewRun } from "./batchReviewTypes";
import { queuedItems } from "./batchReviewTypes";

export type BatchReviewExecutorOptions = {
  concurrency?: number;
  onSnapshot?: (snapshot: BatchReviewRun) => void;
  onItemResult?: (result: BatchReviewExecutorItemResult) => void;
  onEvent?: (event: BatchReviewExecutorEvent) => void;
  signal?: AbortSignal;
};

const REASONS = {
  advanced: "ACTION_COMPLETED", failed: "ADVANCE_FAILED",
  skipped: "FAILED_EARLIER_IN_PASS", reload: "RELOAD_FAILED",
  paused: "RUN_PAUSED", aborted: "ABORTED",
  empty: "NO_MORE_SCHEDULABLE_ITEMS", completed: "RUN_COMPLETED",
  inactive: "RUN_NOT_RUNNING",
} as const;

export type BatchReviewExecutorEvent = {
  component: "batch_review_executor";
  run_id: number;
  item_id?: number;
  stage: "item" | "pass";
  action: "advance_item" | "skip_item" | "complete_pass";
  execution_outcome: "success" | "failed" | "skipped" | "completed" | "completed_with_failure" | "cancelled";
  reason_code: typeof REASONS[keyof typeof REASONS];
  domain_status?: string;
  failure_class?: "UNKNOWN";
  retry_behavior?: "NO_RETRY" | "RECOVER_STATE";
  advanced_count?: number;
  failed_count?: number;
  skipped_count?: number;
  duration_ms?: number;
};

export type BatchReviewExecutorItemResult = {
  itemId: number;
  outcome: "failed" | "advanced";
  schedulable: boolean;
  error?: unknown;
};

export async function runBatchReviewExecutor(
  snapshot: BatchReviewRun,
  advance: (item: BatchReviewItem) => Promise<unknown>,
  reload: () => Promise<BatchReviewRun>,
  options: BatchReviewExecutorOptions = {},
): Promise<BatchReviewRun> {
  const concurrency = options.concurrency ?? 3;
  if (!Number.isSafeInteger(concurrency) || concurrency < 1 || concurrency > 3) {
    throw new Error("Batch-review concurrency must be between one and three.");
  }
  let current = snapshot;
  const started = performance.now();
  let advancedCount = 0;
  let skippedCount = 0;
  let reloadFailed = false;
  const active = new Map<number, Promise<BatchReviewRun>>();
  const failedItems = new Set<number>();
  const skippedItems = new Set<number>();
  const emit = (event: Omit<BatchReviewExecutorEvent, "component" | "run_id">) => {
    options.onEvent?.({ component: "batch_review_executor", run_id: snapshot.id, ...event });
  };

  const start = (item: BatchReviewItem) => {
    let outcome: "failed" | "advanced" = "advanced";
    let error: unknown;
    const work = advance(item)
      .catch((reason: unknown) => {
        failedItems.add(item.id);
        outcome = "failed";
        error = reason;
      })
      .then(() => {
        if (outcome === "advanced") advancedCount += 1;
        return reload().catch((reason: unknown) => {
          reloadFailed = true;
          emit({ stage: "item", action: "advance_item", item_id: item.id,
            execution_outcome: outcome === "failed" ? "failed" : "success",
            reason_code: outcome === "failed" ? REASONS.failed : REASONS.advanced,
            ...(outcome === "failed" ? { failure_class: "UNKNOWN", retry_behavior: "RECOVER_STATE" } as const : {}),
          });
          throw reason;
        });
      })
      .then((reloaded) => {
        emit({ stage: "item", action: "advance_item", item_id: item.id,
          execution_outcome: outcome === "failed" ? "failed" : "success",
          reason_code: outcome === "failed" ? REASONS.failed : REASONS.advanced,
          domain_status: reloaded.items.find((candidate) => candidate.id === item.id)?.status,
          ...(outcome === "failed" ? { failure_class: "UNKNOWN", retry_behavior: "RECOVER_STATE" } as const : {}),
        });
        options.onItemResult?.({
          itemId: item.id,
          outcome,
          schedulable: queuedItems(reloaded).some((candidate) => candidate.id === item.id),
          ...(outcome === "failed" ? { error } : {}),
        });
        return reloaded;
      })
      .finally(() => active.delete(item.id));
    active.set(item.id, work);
  };

  try {
    while (!options.signal?.aborted) {
      if (current.status !== "running") break;
      for (const item of queuedItems(current)) {
        if (failedItems.has(item.id) && !active.has(item.id) && !skippedItems.has(item.id)) {
          skippedItems.add(item.id);
          skippedCount += 1;
          emit({ stage: "item", action: "skip_item", item_id: item.id,
            execution_outcome: "skipped", reason_code: REASONS.skipped,
            domain_status: item.status, retry_behavior: "NO_RETRY" });
        }
      }
      const queue = queuedItems(current).filter((item) => !active.has(item.id) && !failedItems.has(item.id));
      for (const item of queue) {
        if (active.size >= concurrency) break;
        start(item);
      }
      if (active.size === 0) break;
      current = await Promise.race(active.values());
      options.onSnapshot?.(current);
    }
    if (active.size > 0) {
      await Promise.allSettled(active.values());
      current = await reload().catch((reason: unknown) => { reloadFailed = true; throw reason; });
      options.onSnapshot?.(current);
    }
  } catch (reason: unknown) {
    await Promise.allSettled(active.values());
    emit({ stage: "pass", action: "complete_pass", execution_outcome: "failed",
      reason_code: reloadFailed ? REASONS.reload : REASONS.failed,
      failure_class: "UNKNOWN", retry_behavior: "RECOVER_STATE",
      advanced_count: advancedCount, failed_count: failedItems.size, skipped_count: skippedCount,
      duration_ms: performance.now() - started });
    throw reason;
  }
  emit({ stage: "pass", action: "complete_pass",
    execution_outcome: reloadFailed ? "failed" : options.signal?.aborted ? "cancelled" : failedItems.size > 0 ? "completed_with_failure" : "completed",
    reason_code: reloadFailed ? REASONS.reload : options.signal?.aborted ? REASONS.aborted : current.status === "paused" ? REASONS.paused
      : current.status === "running" ? REASONS.empty
      : current.status === "completed" || current.status === "completed_with_exceptions" ? REASONS.completed : REASONS.inactive,
    domain_status: current.status, advanced_count: advancedCount,
    failed_count: failedItems.size, skipped_count: skippedCount,
    duration_ms: performance.now() - started });
  return current;
}
