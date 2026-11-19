import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, useParams, useSearchParams } from "react-router-dom";

import { Button, ErrorState, Skeleton } from "../../design-system";
import { getCatalogImport, getCatalogRows } from "./catalogApi";
import { CatalogImportReview } from "./CatalogImportReview";
import { useCatalogNavigation } from "./CatalogNavigationContext";
import { CATALOG_SECTIONS, type CatalogDraftSaveAction, type CatalogSaveRecovery, type CatalogImportRow, type CatalogImportSummary, type CatalogSection } from "./catalogTypes";

function emptyRows(): Record<CatalogSection, CatalogImportRow[]> {
  return { styles: [], skus: [], mappings: [], exceptions: [], evidence: [] };
}

export function CatalogImportPage({embeddedId,onGuardChange,onNavigate,onCompleted,onSaveAction}:{onSaveAction?:(action:CatalogDraftSaveAction|undefined)=>void;onCompleted?:()=>void;embeddedId?:number;onGuardChange?:(guard:{dirty:boolean;busy:boolean;unknown:boolean})=>void;onNavigate?:(id:number)=>void}={}) {
  const { reviewReturn } = useCatalogNavigation();
  const [query] = useSearchParams();
  const returnTo = query.get("return_to");
  const reviewPath = returnTo?.startsWith("/catalog/") ? returnTo : reviewReturn;
  const routeId=useParams().import_id; const importId = embeddedId??Number(routeId);
  const [imported, setImported] = useState<CatalogImportSummary>();
  const [rowsBySection, setRowsBySection] = useState<Record<CatalogSection, CatalogImportRow[]>>(emptyRows);
  const [error, setError] = useState<string>();
  const [rowsLoading, setRowsLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadedSections, setLoadedSections] = useState(0);
  const reloadSequence = useRef(0);
  const hasRows = useRef(false);
  const snapshot = useRef<{ imported: CatalogImportSummary; rows: Record<CatalogSection, CatalogImportRow[]> } | undefined>(undefined);
  const reload = useCallback(async () => {
    const sequence = ++reloadSequence.current;
    setRefreshing(true); setError(undefined);
    if (!hasRows.current) { setRowsLoading(true); setLoadedSections(0); }
    try {
      const next = await getCatalogImport(importId);
      if (sequence !== reloadSequence.current) return next.workflow_revision;
      if (!hasRows.current) setImported(next);
      if (next.record_kind === "listing_source") { setImported(next); setRowsLoading(false); return next.workflow_revision; }
      if (next.status === "uploaded" || next.status === "parsing") { setImported(next); return next.workflow_revision; }
      const pages = await Promise.all(CATALOG_SECTIONS.map(async item => {
        const first = await getCatalogRows(importId, item, next.workflow_revision);
        const rows = [...(first.rows ?? [])];
        const remaining = await Promise.all(Array.from({ length: Math.max(0, Math.ceil((first.total_rows ?? rows.length) / 200) - 1) }, (_, index) => getCatalogRows(importId, item, next.workflow_revision, index + 2)));
        for (const more of remaining) {
          if (!more.rows.length) throw new Error("审核行未完整返回，请重新读取草稿。");
          rows.push(...more.rows);
        }
        if (typeof first.total_rows === "number" && rows.length !== first.total_rows) throw new Error("审核行未完整返回，请重新读取草稿。");
        if (sequence === reloadSequence.current) setLoadedSections(count => count + 1);
        return rows;
      }));
      if (sequence !== reloadSequence.current) return next.workflow_revision;
      const nextRows = Object.fromEntries(pages.map((rows, index) => [CATALOG_SECTIONS[index], rows])) as Record<CatalogSection, CatalogImportRow[]>;
      snapshot.current = { imported: next, rows: nextRows };
      setRowsBySection(nextRows);
      setImported(next); hasRows.current = true; setRowsLoading(false);
      return next.workflow_revision;
    } catch (reason) {
      if (sequence === reloadSequence.current) setError(reason instanceof Error ? reason.message : "无法读取审核草稿。");
      throw reason;
    } finally { if (sequence === reloadSequence.current) setRefreshing(false); }
  }, [importId]);
  useEffect(() => {
    const requestSequence = reloadSequence;
    hasRows.current = false;
    void reload().catch(() => undefined);
    return () => { ++requestSequence.current; };
  }, [reload]);
  useEffect(() => {
    if (!imported || (imported.status !== "uploaded" && imported.status !== "parsing")) return;
    const timer = window.setInterval(() => void reload().catch(() => undefined), 1000);
    return () => window.clearInterval(timer);
  }, [imported, reload]);
  useEffect(()=>{if(imported?.status==='approved')onCompleted?.();},[imported?.status,onCompleted]);
  const saved = useCallback(async (revision: number) => {
    const actual = await reload();
    if (actual < revision) {
      const message = "读取到的草稿早于已保存修订，请重新读取核对。";
      setError(message); throw new Error(message);
    }
  }, [reload]);
  const recoverConflict = useCallback(async (): Promise<CatalogSaveRecovery> => {
    const previous = snapshot.current;
    const revision = await reload();
    const latest = snapshot.current;
    if (!previous || !latest || latest.imported.import_id !== importId || latest.imported.workflow_revision !== revision) throw new Error("最新草稿未完整读回，请重新读取；输入仍保留。");
    const fingerprint = (rows: Record<CatalogSection, CatalogImportRow[]>) => JSON.stringify(CATALOG_SECTIONS.map(section => [...rows[section]].sort((a, b) => a.row_key.localeCompare(b.row_key)).map(row => [row.row_key, row.row_origin, row.projection_state, Object.entries(row.payload).sort(([a], [b]) => a.localeCompare(b)), row.display_sku_choice ?? null])));
    return { workflowRevision: revision, canEdit: latest.imported.permissions.can_edit, unchanged: fingerprint(previous.rows) === fingerprint(latest.rows) };
  }, [importId, reload]);
  if (!imported || imported.import_id !== importId) return error ? <ErrorState title="无法打开商品主档审核" description={error} action={<Button onClick={() => void reload().catch(() => undefined)}>重新读取草稿</Button>} /> : <div role="status"><p>正在读取在线审核工作台…</p><Skeleton lines={3} /></div>;
  if (imported.record_kind === "listing_source" && imported.review_path) return <Navigate replace to={imported.review_path} />;
  return <CatalogImportReview key={importId} imported={imported} rowsBySection={rowsBySection} rowsLoading={rowsLoading} loadedSections={loadedSections} refreshing={refreshing} error={error}
    onRecoverConflict={recoverConflict} onSaveAction={onSaveAction} embedded={!!embeddedId} onGuardChange={onGuardChange} onNavigate={onNavigate} reviewReturn={reviewPath} onReload={() => void reload().catch(() => undefined)} onSaved={saved} onWorkflowChanged={async () => { await reload(); }} />;
}
