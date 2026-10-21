import { ProductLedgerView } from "./ProductLedgerView";
import { analyticsError, type AnalyticsFailure } from "./analyticsError";
import { CatalogSetup } from "../catalog/CatalogSetup";
import { listCatalogCategories, type CatalogCategory } from "../catalog/catalogApi";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { loadStyleLedger } from "./productAnalyticsApi";
import type { StyleLedgerResponse } from "./productAnalyticsTypes";
import {
  parseProductLedgerSearch,
  serializeProductLedgerSearch,
  updateProductLedgerView,
  type ProductLedgerView as LedgerFilters,
} from "./productLedgerState";


type Loaded = { key: string; scope: string; generation: number; value: StyleLedgerResponse };
type Failed = { key: string; failure: AnalyticsFailure };

function requestKey(view: LedgerFilters): string {
  return serializeProductLedgerSearch(view).toString();
}

export function ProductLedgerPage({ today }: { today: string }) {
  const location = useLocation();
  const restored = useRef<string | null>(null);
  const { generation } = useAuthzGeneration();
  const [parameters, setParameters] = useSearchParams();
  const raw = parameters.toString();
  const view = useMemo(() => parseProductLedgerSearch(new URLSearchParams(raw), today), [raw, today]);
  const canonical = useMemo(() => serializeProductLedgerSearch(view).toString(), [view]);
  const key = requestKey(view);
  const scope = requestKey({ ...view, sort: "units", direction: "desc" });
  const [categories, setCategories] = useState<CatalogCategory[]>([]);
  useEffect(() => { let active = true; void listCatalogCategories().then((value) => { if (active) setCategories(value); }).catch(() => { if (active) setCategories([]); }); return () => { active = false; }; }, [generation]);
  const [loaded, setLoaded] = useState<Loaded>();
  const [failed, setFailed] = useState<Failed>();
  const [loadingKey, setLoadingKey] = useState<string>();
  const [showNames, setShowNames] = useState(false);
  const [reload, setReload] = useState(0);
  const [draft, setDraft] = useState({ from: view.from, search: view.search, to: view.to });
  const sequence = useRef(0);
  const pendingUpdate = useRef<{ locationKey: string; view: LedgerFilters } | undefined>(undefined);
  useLayoutEffect(() => { pendingUpdate.current = undefined; }, [location.key]);

  useEffect(() => {
    if (raw !== canonical) setParameters(new URLSearchParams(canonical), { replace: true, state: location.state as { restoreFocus?: string } | null });
  }, [canonical, location.state, raw, setParameters]);

  useEffect(() => setDraft({ from: view.from, search: view.search, to: view.to }), [view.from, view.search, view.to]);

  useEffect(() => {
    const current = ++sequence.current;
    const controller = new AbortController();
    const requestView = parseProductLedgerSearch(new URLSearchParams(key), today);
    setFailed(undefined);
    setLoadingKey(key);
    void loadStyleLedger(requestView, controller.signal).then((value) => {
      if (current !== sequence.current || controller.signal.aborted) return;
      setLoaded({ key, scope, generation, value });
      setLoadingKey(undefined);
    }).catch((error: unknown) => {
      if (current !== sequence.current || controller.signal.aborted) return;
      setFailed({ key, failure: analyticsError(error, "无法读取产品总表，请稍后重试。") });
      setLoadingKey(undefined);
    });
    return () => controller.abort();
  }, [generation, key, scope, reload, today]);

  const update = (change: Partial<LedgerFilters>, replace = false) => {
    // The URL changes before the router commits. Compose rapid edits until that
    // location changes; a new history entry (including Back/Forward) owns its view.
    const current = pendingUpdate.current?.locationKey === location.key ? pendingUpdate.current.view : view;
    const factChange = change.fact_basis === "catalog_snapshot"
      ? { catalog_version: current.catalog_version ?? (loaded?.generation === generation && loaded.key === key ? loaded.value.provenance.catalog_version_id : null) }
      : change.fact_basis === "current" ? { catalog_version: null } : {};
    const next = updateProductLedgerView(current, { ...factChange, ...change });
    pendingUpdate.current = { locationKey: location.key, view: next };
    setParameters(serializeProductLedgerSearch(next), { replace });
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    update({ from: draft.from, search: draft.search.slice(0, 100), to: draft.to });
  };
  const failure = failed?.key === key ? failed.failure : undefined;
  const error = failure?.message;
  const response = !error && loaded?.generation === generation && loaded.scope === scope ? loaded.value : undefined;
  const refreshing = Boolean(response && loaded?.key !== key);
  const loading = loadingKey === key || refreshing;
  useEffect(() => {
    const focusId = (location.state as { restoreFocus?: string } | null)?.restoreFocus;
    if (!response || !focusId || restored.current === location.key) return;
    const link = document.getElementById(focusId)?.querySelector<HTMLButtonElement>("button");
    if (link) { link.focus(); restored.current = location.key; }
  }, [location.key, location.state, response]);
  return <ProductLedgerView today={today} view={view} canonical={canonical} categories={categories} draft={draft} response={response} failure={failure} loading={loading} refreshing={refreshing} showNames={showNames}
    setupContent={failure?.setup ? <CatalogSetup /> : undefined}
    onDraftChange={change => setDraft(current => ({ ...current, ...change }))}
    onShowNamesChange={setShowNames} onSubmit={submit} onUpdate={update} onRetry={() => setReload(current => current + 1)}
  />;
}
