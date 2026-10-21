import { describe, expect, it, vi } from "vitest";
import type { BatchReviewItem, BatchReviewRun } from "./batchReviewTypes";
import { runBatchReviewExecutor } from "./batchReviewExecutor";

function runWith(count: number): BatchReviewRun {
  const items = Array.from({ length: count }, (_, index) => ({
    id: index + 1,
    recovery_available: true,
    status: "queued",
  })) as BatchReviewItem[];
  return { id: 1, status: "running", revision: 0, items } as BatchReviewRun;
}

describe("runBatchReviewExecutor", () => {
  it("never starts more than three and backfills one completed slot", async () => {
    const run = runWith(5);
    const resolvers = new Map<number, () => void>();
    let active = 0;
    let maximum = 0;
    const completed = new Set<number>();
    const advance = (item: BatchReviewItem) => new Promise<void>((resolve) => {
      active += 1;
      maximum = Math.max(maximum, active);
      resolvers.set(item.id, () => {
        active -= 1;
        completed.add(item.id);
        resolve();
      });
    });
    const reload = () => Promise.resolve({
      ...run,
      items: run.items.map((item) => ({
        ...item,
        recovery_available: !completed.has(item.id),
        status: completed.has(item.id) ? "ready_for_publish" : "queued",
      })),
    });

    const executing = runBatchReviewExecutor(run, advance, reload);
    await Promise.resolve();
    expect([...resolvers]).toHaveLength(3);
    resolvers.get(1)?.();
    await vi.waitFor(() => expect(resolvers.has(4)).toBe(true));
    resolvers.get(2)?.();
    await vi.waitFor(() => expect(resolvers.has(5)).toBe(true));
    for (const resolve of resolvers.values()) resolve();
    await executing;
    expect(maximum).toBe(3);
  });

  it("does not claim queued work while the server says paused", async () => {
    const advance = () => Promise.reject(new Error("must not run"));
    const paused = { ...runWith(3), status: "paused" };
    const result = await runBatchReviewExecutor(paused, advance, () => Promise.resolve(paused));
    expect(result).toBe(paused);
  });

  it("reclaims only active work explicitly marked recoverable by the server", async () => {
    const run = runWith(2);
    run.items[0] = { ...run.items[0]!, status: "validating", recovery_available: true };
    run.items[1] = { ...run.items[1]!, status: "validating", recovery_available: false };
    const advance = vi.fn().mockResolvedValue(undefined);
    const completed = {
      ...run,
      status: "completed",
      items: run.items.map((item) => ({ ...item, recovery_available: false, status: "ready_for_publish" })),
    } as BatchReviewRun;

    await runBatchReviewExecutor(run, advance, () => Promise.resolve(completed));

    expect(advance).toHaveBeenCalledTimes(1);
    expect(advance).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
  });
});
