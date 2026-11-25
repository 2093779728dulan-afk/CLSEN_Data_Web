import { act, cleanup, render, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { AuthzGenerationProvider, useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { ApiRequestError } from "../../api/client";
import { useCommand, useLoad, useSearchDraft } from "./useProductionApi";
import { productionDataChanged } from "../../api/productionReadCache";

const read = vi.hoisted(() => vi.fn());
const write = vi.hoisted(() => vi.fn());
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: read, writeApi: write }));
let siteId = 1;
function Wrapper({ children }: { children: ReactNode }) {
  return <AuthzGenerationProvider boundary={{ principalId: 1, roles: ["viewer"], siteId, siteConfigVersionId: 1 }} onRevoked={() => undefined}>{children}</AuthzGenerationProvider>;
}
function deferred() {
  let resolve!: (value: { quantity: number }) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<{ quantity: number }>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
afterEach(() => { cleanup(); read.mockReset(); write.mockReset(); vi.restoreAllMocks(); siteId = 1; });

it("reuses a fresh cached page on remount without requesting it again", async () => {
  const pending = deferred(); read.mockResolvedValueOnce({ quantity: 8 }).mockReturnValue(pending.promise);
  function Page({ visible }: { visible: boolean }) { return visible ? <Child /> : null; }
  const observed: ReturnType<typeof useLoad<{ quantity: number }>>[] = [];
  function Child() { observed.push(useLoad<{ quantity: number }>("/api/production/inventory/availability?projection=summary")); return null; }
  const { rerender } = render(<Wrapper><Page visible /></Wrapper>);
  await waitFor(() => expect(observed.at(-1)?.current).toBe(true));
  rerender(<Wrapper><Page visible={false} /></Wrapper>); rerender(<Wrapper><Page visible /></Wrapper>);
  expect(observed.at(-1)?.value?.quantity).toBe(8); expect(observed.at(-1)?.initialLoading).toBe(false);
  expect(observed.at(-1)?.current).toBe(false);
  await waitFor(() => expect(observed.at(-1)?.current).toBe(true));
  expect(read).toHaveBeenCalledTimes(1); expect(observed.at(-1)?.value?.quantity).toBe(8);
});

it("deduplicates mounted consumers and refreshes both after a business write", async () => {
  read.mockResolvedValueOnce({ quantity: 8 }).mockResolvedValue({ quantity: 9 });
  const { result } = renderHook(() => [useLoad<{quantity:number}>("/api/production/skus?contract_version=2"), useLoad<{quantity:number}>("/api/production/skus?contract_version=2")], { wrapper: Wrapper });
  await waitFor(() => expect(result.current.every(item => item.current)).toBe(true));
  expect(read).toHaveBeenCalledTimes(1);
  act(() => productionDataChanged());
  await waitFor(() => expect(result.current.every(item => item.value?.quantity === 9 && item.current)).toBe(true));
  expect(read).toHaveBeenCalledTimes(2);
});

it("keeps a cleared or unsubmitted search on unrelated renders and resets only for changed applied filters", () => {
  const { result, rerender } = renderHook(({ applied }) => useSearchDraft(applied), { initialProps: { applied: "first" } });
  act(() => result.current[1]("")); rerender({ applied: "first" });
  expect(result.current[0]).toBe("");
  act(() => result.current[1]("unsubmitted")); rerender({ applied: "first" });
  expect(result.current[0]).toBe("unsubmitted");
  rerender({ applied: "second" }); expect(result.current[0]).toBe("second");
  rerender({ applied: "first" }); expect(result.current[0]).toBe("first");
});

it("retains the same resource during refresh but marks it non-current until success", async () => {
  const pending = deferred(); read.mockResolvedValueOnce({ quantity: 8 }).mockReturnValueOnce(pending.promise);
  const { result, rerender } = renderHook(({ refresh }) => useLoad<{ quantity: number }>("/stock?owner=1", refresh, true, true), { wrapper: Wrapper, initialProps: { refresh: 0 } });
  await waitFor(() => expect(result.current.value?.quantity).toBe(8));
  rerender({ refresh: 1 });
  expect(result.current.value?.quantity).toBe(8);
  expect(result.current.loading).toBe(true); expect(result.current.current).toBe(false);
  await act(async () => { pending.resolve({ quantity: 9 }); await pending.promise; });
  expect(result.current.value?.quantity).toBe(9); expect(result.current.current).toBe(true);
});
it("keeps existing clear-on-refresh behavior unless retention is requested", async () => {
  read.mockResolvedValueOnce({ quantity: 8 }).mockReturnValueOnce(deferred().promise);
  const { result, rerender } = renderHook(({ refresh }) => useLoad("/stock", refresh), { wrapper: Wrapper, initialProps: { refresh: 0 } });
  await waitFor(() => expect(result.current.value).toBeDefined());
  rerender({ refresh: 1 }); expect(result.current.value).toBeUndefined();
});
it("never retains another path or accepts its late response", async () => {
  const first = deferred(); const second = deferred();
  read.mockResolvedValueOnce({ quantity: 8 }).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  const { result, rerender } = renderHook(({ path, refresh }) => useLoad<{ quantity: number }>(path, refresh, true, true), { wrapper: Wrapper, initialProps: { path: "/stock?owner=1", refresh: 0 } });
  await waitFor(() => expect(result.current.value).toBeDefined());
  rerender({ path: "/stock?owner=1", refresh: 1 });
  rerender({ path: "/stock?owner=2", refresh: 1 }); expect(result.current.value).toBeUndefined();
  await act(async () => { first.resolve({ quantity: 99 }); await first.promise; });
  expect(result.current.value).toBeUndefined();
  await act(async () => { second.resolve({ quantity: 2 }); await second.promise; });
  expect(result.current.value?.quantity).toBe(2);
});
it("retains a read-only reference after a network error, with explicit error and non-current state", async () => {
  read.mockResolvedValueOnce({ quantity: 8 }).mockRejectedValueOnce(new Error("连接中断"));
  const { result, rerender } = renderHook(({ refresh }) => useLoad("/stock", refresh, true, true), { wrapper: Wrapper, initialProps: { refresh: 0 } });
  await waitFor(() => expect(result.current.value).toBeDefined());
  rerender({ refresh: 1 }); await waitFor(() => expect(result.current.error).toBe("连接中断"));
  expect(result.current.value).toEqual({ quantity: 8 }); expect(result.current.current).toBe(false); expect(result.current.loading).toBe(false);
});
it.each([401, 403])("clears retained data on permission failure %s", async status => {
  read.mockResolvedValueOnce({ quantity: 8 }).mockRejectedValueOnce(new ApiRequestError(status, "denied", "无权读取"));
  const { result, rerender } = renderHook(({ refresh }) => useLoad("/stock", refresh, true, true), { wrapper: Wrapper, initialProps: { refresh: 0 } });
  await waitFor(() => expect(result.current.value).toBeDefined());
  rerender({ refresh: 1 }); await waitFor(() => expect(result.current.error).toBe("无权读取"));
  expect(result.current.value).toBeUndefined();
});
it("purges retained results on site changes and explicit sensitive-state purge", async () => {
  read.mockResolvedValueOnce({ quantity: 8 }).mockReturnValue(deferred().promise);
  const { result, rerender } = renderHook(() => ({ ...useLoad("/stock", 0, true, true), purge: useAuthzGeneration().purgeSensitiveState }), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.value).toBeDefined());
  act(() => result.current.purge()); expect(result.current.value).toBeUndefined();
  siteId = 2; rerender(); expect(result.current.value).toBeUndefined();
  expect(result.current.current).toBe(false);
});

it("keeps loaded references and exposes a SKU activation rejection without purging the form", async () => {
  read.mockResolvedValue({ version: 2 });
  write.mockRejectedValue(new ApiRequestError(403, "sku_scope_forbidden", "该商品不在本次启用范围内，请保留待核。"));
  const saved = vi.fn();
  const { result } = renderHook(() => ({ reference: useLoad("/api/production/workbench"), command: useCommand(saved) }), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.reference.current).toBe(true));
  act(() => result.current.command.submit("/api/production/orders", { lines: [{ sku_id: "19", expected_units: "1" }] }));
  await waitFor(() => expect(result.current.command.errorCode).toBe("sku_scope_forbidden"));
  expect(result.current.reference.value).toEqual({ version: 2 });
  expect(result.current.reference.loading).toBe(false);
  expect(result.current.command.busy).toBe(false);
  expect(result.current.command.unknown).toBe(false);
  expect(result.current.command.feedback).not.toBeNull();
  expect(saved).not.toHaveBeenCalled();
});
it("still purges sensitive references for an actual command permission denial", async () => {
  read.mockResolvedValue({ version: 2 });
  write.mockRejectedValue(new ApiRequestError(403, "role_forbidden", "当前账号不能办理。"));
  const { result } = renderHook(() => ({ reference: useLoad("/api/production/workbench"), command: useCommand(vi.fn()) }), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.reference.current).toBe(true));
  act(() => result.current.command.submit("/api/production/orders", {}));
  await waitFor(() => expect(result.current.reference.value).toBeUndefined());
});


it.each(["focus", "visibilitychange"])("refreshes expired references on return via %s and retains SKU choices until current", async event => {
  const now=vi.spyOn(Date,"now"); now.mockReturnValue(1_000);
  const pending = deferred(); read.mockResolvedValueOnce({quantity:8}).mockReturnValueOnce(pending.promise);
  const {result} = renderHook(() => useLoad<{quantity:number}>("/api/production/skus?contract_version=2"), {wrapper:Wrapper});
  await waitFor(() => expect(result.current.current).toBe(true));
  now.mockReturnValue(302_000);
  act(() => { (event === "focus" ? window : document).dispatchEvent(new Event(event)); });
  await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
  expect(result.current.value?.quantity).toBe(8); expect(result.current.current).toBe(false);
  await act(async () => {pending.resolve({quantity:9}); await pending.promise;});
  expect(result.current.value?.quantity).toBe(9); expect(result.current.current).toBe(true);
});
it("does not refresh an editing document or disabled reference on focus", async () => {
  read.mockResolvedValue({quantity:8});
  const {result,rerender}=renderHook(({enabled})=>useLoad("/api/production/orders/1",0,enabled,true,false),{wrapper:Wrapper,initialProps:{enabled:true}});
  await waitFor(()=>expect(result.current.current).toBe(true));
  act(()=>{window.dispatchEvent(new Event("focus"));}); expect(read).toHaveBeenCalledTimes(1);
  rerender({enabled:false}); act(()=>{document.dispatchEvent(new Event("visibilitychange"));});
  expect(read).toHaveBeenCalledTimes(1); expect(result.current.value).toBeUndefined();
});


it("does not reread on entering edit mode and revalidates after leaving it", async () => {
  read.mockResolvedValue({quantity:8});
  const {result,rerender}=renderHook(({editing})=>useLoad("/api/production/orders/1",0,true,true,!editing),{wrapper:Wrapper,initialProps:{editing:false}});
  await waitFor(()=>expect(result.current.current).toBe(true));
  rerender({editing:true}); act(()=>{window.dispatchEvent(new Event("focus"));});
  expect(read).toHaveBeenCalledTimes(1); expect(result.current.current).toBe(true);
  read.mockResolvedValue({quantity:9}); rerender({editing:false});
  await waitFor(()=>expect(result.current.value).toEqual({quantity:9}));expect(read).toHaveBeenCalledTimes(2);
});


it("never exposes another site's cached production data and clears it on a sensitive purge", async () => {
  const pending = deferred(); read.mockResolvedValueOnce({quantity:8}).mockReturnValue(pending.promise);
  const {result,rerender}=renderHook(()=>({...useLoad<{quantity:number}>("/api/production/skus?contract_version=2"),purge:useAuthzGeneration().purgeSensitiveState}),{wrapper:Wrapper});
  await waitFor(()=>expect(result.current.current).toBe(true));
  siteId=2;rerender();expect(result.current.value).toBeUndefined();
  await act(async()=>{pending.resolve({quantity:9});await pending.promise;});
  expect(result.current.value?.quantity).toBe(9);
  act(()=>result.current.purge());expect(result.current.value).toBeUndefined();expect(result.current.current).toBe(false);
});

it("reports disabled production writes without purging the current draft or references", async () => {
  read.mockResolvedValue({ quantity: 8 });
  write.mockRejectedValue(new ApiRequestError(403, "production_read_only", "库存写入尚未启用。"));
  const success = vi.fn(); const rejected = vi.fn();
  const { result } = renderHook(() => ({ reference: useLoad("/api/production/workbench"), command: useCommand(success, rejected), auth: useAuthzGeneration() }), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.reference.current).toBe(true));
  const generation = result.current.auth.generation;
  act(() => result.current.command.submit("/api/production/inventory/display-settings", { expected_revision: "0", style_ids: ["1"] }));
  await waitFor(() => expect(result.current.command.errorCode).toBe("production_read_only"));
  expect(result.current.command.feedback).not.toBeNull();
  expect(result.current.command.unknown).toBe(false);
  expect(result.current.reference.value).toEqual({ quantity: 8 });
  expect(result.current.auth.generation).toBe(generation);
  expect(success).not.toHaveBeenCalled(); expect(rejected).toHaveBeenCalledOnce();
});
