import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ApiRequestError, requestApi, StableOperationKeyStore, writeApi } from "../../api/client";
import { RequestGate } from "../../api/requestGate";
import { productionDataChanged, type ProductionReadCache } from "../../api/productionReadCache";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, StatusMessage } from "../../design-system";
import type { Document } from "./types";
import styles from "./Production.module.css";

type ReadResult<T> = { owner: ProductionReadCache; path: string; refresh: number | string; generation: number; pending: boolean; value?: T; error?: string };
export function useSearchDraft(applied: string) {
  const [draft, setDraft] = useState({ applied, value: applied });
  // Reset on a changed URL before committing the input, never in a later effect.
  if (draft.applied !== applied) setDraft({ applied, value: applied });
  return [draft.applied === applied ? draft.value : applied, (value: string) => setDraft({ applied, value })] as const;
}
export function useRefreshOnReturn(refresh: () => void, enabled = true) {
  const callback = useRef(refresh); callback.current = refresh;
  useEffect(() => {
    if (!enabled) return;
    const returned = () => { if (document.visibilityState !== "hidden") callback.current(); };
    window.addEventListener("focus", returned);
    document.addEventListener("visibilitychange", returned);
    return () => { window.removeEventListener("focus", returned); document.removeEventListener("visibilitychange", returned); };
  }, [enabled]);
}
export function useLoad<T>(path: string, revision: number | string = 0, enabled = true, retainOnRefresh = false, refreshOnReturn = path.startsWith("/api/production/skus?")) {
  const { generation, registerSensitivePurge, productionReads } = useAuthzGeneration();
  const [returned, setReturned] = useState(0);
  useRefreshOnReturn(() => setReturned(value => value + 1), enabled && refreshOnReturn);
  const wasRefreshing = useRef(refreshOnReturn);
  useEffect(() => {
    if (refreshOnReturn && !wasRefreshing.current) { productionReads.forget(path); setReturned(value => value + 1); }
    wasRefreshing.current = refreshOnReturn;
  }, [refreshOnReturn, productionReads, path]);
  const lastExplicitRefresh = useRef(revision);
  const dataRevision = useSyncExternalStore(productionReads.subscribe, productionReads.version);
  const cachedRead = path.startsWith("/api/production/") && !path.startsWith("/api/production/commands/");
  const refresh = `${revision}:${returned}:${dataRevision}`;
  const retain = retainOnRefresh || path.startsWith("/api/production/skus?");
  const [result, setResult] = useState<ReadResult<T> | undefined>(() => {
    const value = enabled && cachedRead ? productionReads.peek<T>(path) : undefined;
    return value === undefined ? undefined : { owner: productionReads, path, refresh, generation, value, pending: true };
  });
  useEffect(() => registerSensitivePurge(() => setResult(undefined)), [registerSensitivePurge]);
  useEffect(() => {
    if (!enabled) { setResult(undefined); return; }
    const cached = cachedRead ? productionReads.peek<T>(path) : undefined;
    setResult(previous => ({ owner: productionReads, path, refresh, generation, pending: true, value: cached ?? ((retain || cachedRead) && previous?.path === path && previous.generation === generation && previous.owner === productionReads ? previous.value : undefined) }));
    let active = true;
    const gate = cachedRead ? undefined : new RequestGate();
    const ticket = gate?.begin([path, refresh], generation);
    const force = lastExplicitRefresh.current !== revision;
    lastExplicitRefresh.current = revision;
    const maxAge = /\/(?:skus|factories|warehouses)\?/.test(path) ? 300_000 : 30_000;
    const job = cachedRead ? productionReads.read<T>(path, signal => requestApi<T>(path, { signal }), force ? 0 : maxAge) : undefined;
    const isCurrent = () => active && (job ? !job.controller.signal.aborted : ticket!.isCurrent());
    void (job?.promise ?? requestApi<T>(path, { signal: ticket!.signal })).then(value => {
      if (isCurrent()) setResult({ owner: productionReads, path, refresh, generation, pending: false, value });
    }).catch((reason: unknown) => {
      if (!isCurrent()) return;
      const denied = reason instanceof ApiRequestError && (reason.status === 401 || reason.status === 403);
      if (denied && cachedRead) productionReads.forget(path);
      setResult(previous => ({ owner: productionReads, path, refresh, generation, pending: false, value: (retain || cachedRead) && !denied ? previous?.value : undefined, error: reason instanceof Error ? reason.message : "读取失败。" }));
    });
    return () => { active = false; gate?.dispose(); };
  }, [path, refresh, generation, enabled, retain, cachedRead, productionReads, revision]);
  // Hide another resource synchronously, before the effect clears the old result.
  const sameResource = enabled && result?.path === path && result.generation === generation && result.owner === productionReads;
  const sameRequest = sameResource && result.refresh === refresh;
  const value = sameResource && (retain || sameRequest || cachedRead) ? result.value : undefined;
  const error = sameRequest ? result.error : undefined;
  const loading = enabled && (!sameRequest || result.pending);
  return { value, error, loading, initialLoading: loading && value === undefined, refreshing: loading && value !== undefined, current: sameRequest && !result.pending && !error && value !== undefined };
}
type Pending = { path: string; body: Record<string, unknown>; key: string; method: "POST" | "PUT" | "DELETE" };
export function useCommand<T = Document & { deleted?: boolean }>(onSuccess: (result: T) => void, onRejected?: () => void) {
  const keys = useRef(new StableOperationKeyStore()); const pending = useRef<Pending | undefined>(undefined);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string>(); const [errorCode, setErrorCode] = useState<string>(); const [unknown, setUnknown] = useState(false);
  const { generation, registerSensitivePurge, purgeSensitiveState } = useAuthzGeneration();
  const active = useRef(true); const auth = useRef(generation); auth.current = generation;
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => registerSensitivePurge(() => { pending.current = undefined; keys.current = new StableOperationKeyStore(); setUnknown(false); setError(undefined); setErrorCode(undefined); }), [registerSensitivePurge]);
  async function run(command: Pending, query = false) {
    if (busy) return;
    setBusy(true); setError(undefined); setErrorCode(undefined); const start = auth.current;
    try {
      const result = query ? await requestApi<T>(`/api/production/commands/${command.key}`) : await writeApi<T>(command.path, { method: command.method, body: command.body, operationKey: command.key });
      if (query) productionDataChanged();
      if (active.current && auth.current === start) { setUnknown(false); pending.current = undefined; keys.current = new StableOperationKeyStore(); onSuccess(result); }
    } catch (reason) {
      if (!active.current || auth.current !== start) return;
      if (reason instanceof ApiRequestError && reason.status === 403 && reason.code !== "sku_scope_forbidden" && reason.code !== "production_read_only") { purgeSensitiveState(); return; }
      const uncertain = query || !(reason instanceof ApiRequestError) || reason.status >= 500;
      setUnknown(uncertain); if (!uncertain) { pending.current = undefined; onRejected?.(); }
      setError(reason instanceof Error ? reason.message : "保存未完成。"); setErrorCode(reason instanceof ApiRequestError ? reason.code : undefined);
    } finally { if (active.current && auth.current === start) setBusy(false); }
  }
  function submit(path: string, body: Record<string, unknown>, method: Pending["method"] = "POST") {
    if (!active.current || busy || unknown || pending.current) return;
    const key = keys.current.forCommand("save", path, body); const command = { path, body: { ...body, operation_token: key }, key, method };
    pending.current = command; void run(command);
  }
  return { submit, busy, unknown, errorCode, feedback: error ? <StatusMessage kind={unknown ? "warning" : "danger"} title={unknown ? "保存结果待核实，已锁定当前输入" : "操作未完成"} action={unknown && <div className={styles.actions}><Button disabled={busy} onClick={() => { if (pending.current) void run(pending.current, true); }} variant="secondary">查询原操作结果</Button><Button disabled={busy} onClick={() => { if (pending.current) void run(pending.current); }} variant="secondary">重发原操作</Button></div>}>{error}</StatusMessage> : null };
}
