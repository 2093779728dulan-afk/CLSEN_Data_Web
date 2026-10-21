import type { BatchReviewItem, BatchReviewRun } from "./batchReviewTypes";
import { queuedItems } from "./batchReviewTypes";

export type BatchReviewExecutorOptions = {
  concurrency?: number;
  onSnapshot?: (snapshot: BatchReviewRun) => void;
  signal?: AbortSignal;
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
  const active = new Map<number, Promise<BatchReviewRun>>();

  const start = (item: BatchReviewItem) => {
    const work = advance(item)
      .catch(() => undefined)
      .then(reload)
      .finally(() => active.delete(item.id));
    active.set(item.id, work);
  };

  while (!options.signal?.aborted) {
    if (current.status !== "running") break;
    const queue = queuedItems(current).filter((item) => !active.has(item.id));
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
    current = await reload();
    options.onSnapshot?.(current);
  }
  return current;
}
