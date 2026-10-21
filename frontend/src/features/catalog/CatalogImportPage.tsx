import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { Button, ErrorState, Skeleton } from "../../design-system";
import { getCatalogImport, getCatalogRows } from "./catalogApi";
import { CatalogImportReview } from "./CatalogImportReview";
import { useCatalogNavigation } from "./CatalogNavigationContext";
import { CATALOG_SECTIONS, type CatalogImportRow, type CatalogImportSummary, type CatalogSection } from "./catalogTypes";

function emptyRows(): Record<CatalogSection, CatalogImportRow[]> {
  return { styles: [], skus: [], mappings: [], exceptions: [], evidence: [] };
}

export function CatalogImportPage() {
  const { reviewReturn } = useCatalogNavigation();
  const importId = Number(useParams().import_id);
  const [imported, setImported] = useState<CatalogImportSummary>();
  const [rowsBySection, setRowsBySection] = useState<Record<CatalogSection, CatalogImportRow[]>>(emptyRows);
  const [error, setError] = useState<string>();
  const [rowsLoading, setRowsLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadedSections, setLoadedSections] = useState(0);
  const reloadSequence = useRef(0);
  const hasRows = useRef(false);
  const reload = useCallback(async () => {
    const sequence = ++reloadSequence.current;
    setRefreshing(true); setError(undefined);
    if (!hasRows.current) { setRowsLoading(true); setLoadedSections(0); }
    try {
      const next = await getCatalogImport(importId);
      if (sequence !== reloadSequence.current) return next.workflow_revision;
      if (!hasRows.current) setImported(next);
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
      setRowsBySection(Object.fromEntries(pages.map((rows, index) => [CATALOG_SECTIONS[index], rows])) as Record<CatalogSection, CatalogImportRow[]>);
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
  const saved = useCallback(async (revision: number) => {
    const actual = await reload();
    if (actual < revision) {
      const message = "读取到的草稿早于已保存修订，请重新读取核对。";
      setError(message); throw new Error(message);
    }
  }, [reload]);
  if (!imported || imported.import_id !== importId) return error ? <ErrorState title="无法打开商品主档审核" description={error} action={<Button onClick={() => void reload().catch(() => undefined)}>重新读取草稿</Button>} /> : <div role="status"><p>正在读取在线审核工作台…</p><Skeleton lines={3} /></div>;
  return <CatalogImportReview key={importId} imported={imported} rowsBySection={rowsBySection} rowsLoading={rowsLoading} loadedSections={loadedSections} refreshing={refreshing} error={error}
    reviewReturn={reviewReturn} onReload={() => void reload().catch(() => undefined)} onSaved={saved} onWorkflowChanged={async () => { await reload(); }} />;
}
