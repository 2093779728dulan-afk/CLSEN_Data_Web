import { describe, expect, it, vi } from "vitest";
import type { BatchReviewItem, BatchReviewRun } from "./batchReviewTypes";
import { runBatchReviewExecutor } from "./batchReviewExecutor";
import type { BatchReviewExecutorItemResult } from "./batchReviewExecutor";
import type { BatchReviewExecutorEvent } from "./batchReviewExecutor";

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

  it("reports a failed item once, reloads, and continues other queued items", async () => {
    const run = runWith(3);
    const failure = new Error("advance rejected");
    const completed = new Set<number>();
    const advance = vi.fn((item: BatchReviewItem) => {
      if (item.id === 1) return Promise.reject(failure);
      completed.add(item.id);
      return Promise.resolve();
    });
    const reload = vi.fn(() => Promise.resolve({
      ...run,
      items: run.items.map((item) => ({
        ...item,
        recovery_available: !completed.has(item.id),
        status: completed.has(item.id) ? "ready_for_publish" : "queued",
      })),
    }));
    const onItemResult = vi.fn<(result: BatchReviewExecutorItemResult) => void>();
    const events: BatchReviewExecutorEvent[] = [];

    const result = await runBatchReviewExecutor(run, advance, reload, {
      concurrency: 1, onItemResult, onEvent: (event) => events.push(event),
    });

    expect(advance.mock.calls.map(([item]) => item.id)).toEqual([1, 2, 3]);
    expect(reload).toHaveBeenCalledTimes(3);
    expect(result.revision).toBe(run.revision);
    expect(result.items[0]?.status).toBe("queued");
    expect(onItemResult.mock.calls.map(([item]) => item)).toEqual([
      { itemId: 1, outcome: "failed", schedulable: true, error: failure },
      { itemId: 2, outcome: "advanced", schedulable: false },
      { itemId: 3, outcome: "advanced", schedulable: false },
    ]);
    expect(events[0]).toMatchObject({ item_id: 1, execution_outcome: "failed", domain_status: "queued" });
    expect(events[1]).toMatchObject({ item_id: 1, execution_outcome: "skipped", reason_code: "FAILED_EARLIER_IN_PASS" });
    expect(events.at(-1)).toMatchObject({ execution_outcome: "completed_with_failure",
      reason_code: "NO_MORE_SCHEDULABLE_ITEMS", advanced_count: 2, failed_count: 1, skipped_count: 1 });
    console.info("TRACE_B=" + JSON.stringify(events));
  });

  it("retains authoritative completion after a lost advance response", async () => {
    const run = runWith(1);
    const completed = { ...run, status: "completed", items: [
      { ...run.items[0]!, status: "ready_for_publish", recovery_available: false },
    ] } as BatchReviewRun;
    const onItemResult = vi.fn();
    const events: BatchReviewExecutorEvent[] = [];
    const advance = vi.fn().mockRejectedValue(new Error("response lost"));

    expect(await runBatchReviewExecutor(run, advance, () => Promise.resolve(completed), {
      onItemResult, onEvent: (event) => events.push(event),
    })).toBe(completed);
    expect(advance).toHaveBeenCalledTimes(1);
    expect(onItemResult).toHaveBeenCalledWith(expect.objectContaining({
      itemId: 1, outcome: "failed", schedulable: false,
    }));
    expect(events[0]).toMatchObject({ execution_outcome: "failed", domain_status: "ready_for_publish" });
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

  it("reports explicit reload failure while preserving the rejection", async () => {
    const run = runWith(1);
    const failure = new Error("private refresh error");
    const events: BatchReviewExecutorEvent[] = [];
    await expect(runBatchReviewExecutor(run, () => Promise.resolve(), () => Promise.reject(failure), {
      onEvent: (event) => events.push(event),
    })).rejects.toBe(failure);
    expect(events.at(-1)).toMatchObject({ stage: "pass", execution_outcome: "failed", reason_code: "RELOAD_FAILED" });
    expect(events[0]).not.toHaveProperty("domain_status");
    expect(JSON.stringify(events)).not.toContain("private refresh error");
  });

  it.each(["paused", "empty", "aborted"])("reports %s end reason", async (state) => {
    const run = state === "paused" ? { ...runWith(1), status: "paused" } : runWith(state === "empty" ? 0 : 1);
    const controller = new AbortController();
    if (state === "aborted") controller.abort();
    const events: BatchReviewExecutorEvent[] = [];
    const advance = vi.fn(() => Promise.resolve());
    await runBatchReviewExecutor(run, advance, () => Promise.resolve(run), {
      signal: controller.signal, onEvent: (event) => events.push(event),
    });
    expect(advance).not.toHaveBeenCalled();
    expect(events).toHaveLength(1);
    expect(events[0]?.reason_code).toBe(state === "paused" ? "RUN_PAUSED" : state === "empty" ? "NO_MORE_SCHEDULABLE_ITEMS" : "ABORTED");
  });
});
