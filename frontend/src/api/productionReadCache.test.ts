import { expect, it, vi } from "vitest";
import { isBusinessWrite, ProductionReadCache } from "./productionReadCache";

it("shares pending reads and bounds retained query results", async () => {
  const cache = new ProductionReadCache();
  let resolve!: (value: number) => void;
  const load = vi.fn(() => new Promise<number>(yes => { resolve = yes; }));
  const first = cache.read("one", load);
  expect(cache.read("one", load)).toBe(first);
  resolve(1); await first.promise;
  expect(load).toHaveBeenCalledTimes(1); expect(cache.peek("one")).toBe(1);
  for (let index = 0; index < 24; index++) cache.put(String(index), index);
  expect(cache.peek("one")).toBeUndefined(); expect(cache.peek("23")).toBe(23);
});

it("invalidates active reads and rejects their late values", async () => {
  const cache = new ProductionReadCache(); const listener = vi.fn(); cache.subscribe(listener);
  let resolve!: (value: number) => void;
  const job = cache.read("stock", () => new Promise<number>(yes => { resolve = yes; }));
  cache.put("catalog", 1); cache.invalidate();
  expect(job.controller.signal.aborted).toBe(true); expect(cache.peek("catalog")).toBeUndefined();
  resolve(9); await job.promise; expect(cache.peek("stock")).toBeUndefined();
  expect(listener).toHaveBeenCalledTimes(1); expect(cache.version()).toBe(1);
});

it("distinguishes business writes from previews and ordinary reads", () => {
  expect(isBusinessWrite("/api/production/orders/1/confirm", "POST")).toBe(true);
  expect(isBusinessWrite("/api/catalog/changes/1/approve", "POST")).toBe(true);
  expect(isBusinessWrite("/api/production/orders/table/preview?kind=order", "POST")).toBe(false);
  expect(isBusinessWrite("/api/production/orders", "GET")).toBe(false);
  expect(isBusinessWrite("/api/auth/logout", "POST")).toBe(false);
});

it("does not offer a failed or denied cached read to a later page mount", async () => {
  const cache = new ProductionReadCache(); cache.put("stock", 8);
  await expect(cache.read("stock", () => Promise.reject(new Error("denied"))).promise).rejects.toThrow("denied");
  expect(cache.peek("stock")).toBeUndefined();
});

it("reuses fresh values, revalidates expired values and never blocks an explicit refresh", async () => {
  const now = vi.spyOn(Date, "now"); now.mockReturnValue(1_000);
  try {
    const cache = new ProductionReadCache(); const load = vi.fn().mockResolvedValue(8);
    await cache.read("stock", load, 30_000).promise;
    await cache.read("stock", load, 30_000).promise; expect(load).toHaveBeenCalledTimes(1);
    now.mockReturnValue(31_001); await cache.read("stock", load, 30_000).promise; expect(load).toHaveBeenCalledTimes(2);
    await cache.read("stock", load).promise; expect(load).toHaveBeenCalledTimes(3);
    cache.invalidate(); expect(cache.isFresh("stock")).toBe(false);
  } finally { now.mockRestore(); }
});
