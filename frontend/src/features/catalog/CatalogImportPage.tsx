import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getCatalogImport, getCatalogRows } from "./catalogApi";
import { CatalogEvidencePanel } from "./CatalogEvidencePanel";
import { CatalogImportSectionTable, isCatalogRowPending } from "./CatalogImportSectionTable";
import { CatalogIssueSummary } from "./CatalogIssueSummary";
import { buildCatalogReviewOptions } from "./catalogReviewOptions";
import { workflowLabel } from "./catalogImportState";
import { CATALOG_SECTIONS, type CatalogImportRow, type CatalogImportSummary, type CatalogSection } from "./catalogTypes";
import { CatalogWorkflowActions } from "./CatalogWorkflowActions";

import { useCatalogNavigation } from "./CatalogNavigationContext";

const SECTION_META: Record<CatalogSection, { description: string; label: string }> = {
  styles: { label: "款式命名", description: "确认款号与标准商品名称，名称将作为目录中的款式主数据。" },
  skus: { label: "SKU 标准化", description: "补全内部展示 SKU、标准颜色与尺码，保证后续经营数据可被准确归集。" },
  mappings: { label: "SKU 映射", description: "决定卖家 SKU 是否纳入目录；排除时请填写原因。" },
  exceptions: { label: "解析异常", description: "处理无法自动识别的原始字段，或明确将其排除。" },
  evidence: { label: "来源证据", description: "查看审核依据。敏感来源标识需要单独显式查看。" },
};

function emptyRows(): Record<CatalogSection, CatalogImportRow[]> {
  return { styles: [], skus: [], mappings: [], exceptions: [], evidence: [] };
}

export function CatalogImportPage() {
  const { reviewReturn } = useCatalogNavigation();
  const importId = Number(useParams().import_id);
  const [imported, setImported] = useState<CatalogImportSummary>();
  const [section, setSection] = useState<CatalogSection>("styles");
  const [rowsBySection, setRowsBySection] = useState<Record<CatalogSection, CatalogImportRow[]>>(emptyRows);
  const [onlyPending, setOnlyPending] = useState(true);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string>();
  const [rowsLoading, setRowsLoading] = useState(true);
  const [loadedSections, setLoadedSections] = useState(0);
  const reloadSequence = useRef(0);
  const reload = useCallback(async () => {
    const sequence = ++reloadSequence.current;
    setRowsLoading(true);
    setLoadedSections(0);
    setError(undefined);
    try {
    const next = await getCatalogImport(importId);
    if (sequence !== reloadSequence.current) return;
    setImported(next);
    if (next.status === "uploaded" || next.status === "parsing") { setImported(next); setError(undefined); return; }
    const pages = await Promise.all(CATALOG_SECTIONS.map(async (item) => {
      const first = await getCatalogRows(importId, item, next.workflow_revision);
      const rows = [...(first.rows ?? [])];
      const remaining = await Promise.all(Array.from({ length: Math.max(0, Math.ceil((first.total_rows ?? rows.length) / 200) - 1) }, (_, index) => getCatalogRows(importId, item, next.workflow_revision, index + 2)));
      for (const more of remaining) {
        if (!more.rows.length) throw new Error("审核行未完整返回，请重新读取草稿。");
        rows.push(...more.rows);
      }
      if (typeof first.total_rows === "number" && rows.length !== first.total_rows) throw new Error("审核行未完整返回，请重新读取草稿。");
      if (sequence === reloadSequence.current) setLoadedSections((count) => count + 1);
      return { ...first, rows };
    }));
    if (sequence !== reloadSequence.current) return;
    setRowsBySection(Object.fromEntries(pages.map((page, index) => [CATALOG_SECTIONS[index], page.rows ?? []])) as Record<CatalogSection, CatalogImportRow[]>);
    setImported(next);
    setRowsLoading(false);
    setError(undefined);
    } catch (reason) { if (sequence === reloadSequence.current) throw reason; }
  }, [importId]);
  useEffect(() => { void reload().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "无法读取审核草稿。")); }, [reload]);
  useEffect(() => {
    if (!imported || (imported.status !== "uploaded" && imported.status !== "parsing")) return;
    const timer = window.setInterval(() => void reload().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "无法刷新解析状态。")), 1000);
    return () => window.clearInterval(timer);
  }, [imported, reload]);
  const progress = useMemo(() => ([
    { key: "styles" as const, label: "款式命名", done: rowsBySection.styles.filter((row) => !isCatalogRowPending("styles", row)).length, total: rowsBySection.styles.length },
    { key: "skus" as const, label: "SKU 标准化", done: rowsBySection.skus.filter((row) => !isCatalogRowPending("skus", row)).length, total: rowsBySection.skus.length },
    { key: "mappings" as const, label: "SKU 映射", done: rowsBySection.mappings.filter((row) => !isCatalogRowPending("mappings", row)).length, total: rowsBySection.mappings.length },
  ]), [rowsBySection]);
  const pendingCount = Object.entries(rowsBySection).reduce((count, [key, rows]) => count + rows.filter((row) => isCatalogRowPending(key as CatalogSection, row)).length, 0);
  const reviewOptions = useMemo(() => buildCatalogReviewOptions(rowsBySection), [rowsBySection]);
  if (error) return <section className="catalog-panel"><p className="form-error" role="alert">{error}</p><button type="button" onClick={() => { void reload().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "无法重新读取草稿。")); }}>重新读取草稿</button></section>;
  if (!imported || imported.import_id !== importId) return <p role="status">正在读取在线审核工作台…</p>;
  return <div className="catalog-stack">
    <nav className="catalog-review-return" aria-label="审核返回导航"><Link className="catalog-back-link" to={reviewReturn}>返回来源页面</Link>
    <Link className="catalog-back-link" to="/catalog/unmatched">返回待处理，选择下一项</Link></nav>
    <header className="catalog-import-heading catalog-import-heading--workspace"><div><p className="section-kicker">{imported.source_kind === "xlsx" ? "XLSX 导入" : "在线审核"} · 导入 {imported.import_id}</p><h2>商品主档审核</h2><p>{imported.base_catalog_version_id === null ? "首次初始化" : "已有目录批量修订"}：补全标准字段并确认 SKU 映射后，才可提交批准。</p></div><span className={`catalog-status catalog-status--${imported.status}`}>{workflowLabel(imported)}</span></header>
    {rowsLoading ? <section className="catalog-panel" role="status" aria-live="polite"><h3>正在准备审核明细</h3><p>已读取 {loadedSections} / {CATALOG_SECTIONS.length} 类数据，完成后即可核对和操作。</p><progress aria-label="审核明细加载进度" max={CATALOG_SECTIONS.length} value={loadedSections} /></section> : <>
    <section aria-label="审核完成进度" className="catalog-progress"><div className="catalog-progress__summary"><strong>待处理 {pendingCount} 项</strong><span>按顺序完成三项核心审核工作</span></div><div className="catalog-progress__items">{progress.map((item) => <button className={section === item.key ? "is-active" : ""} key={item.key} onClick={() => setSection(item.key)} type="button"><span>{item.label}</span><strong>{item.done}<small> / {item.total}</small></strong><i aria-hidden="true"><b style={{ width: item.total ? `${item.done / item.total * 100}%` : "100%" }} /></i></button>)}</div></section>
    <CatalogIssueSummary status={imported.status} issues={imported.issues} failureReason={imported.failure_reason_code} onLocate={(issue) => { setSection(issue.section); setOnlyPending(false); setQuery(issue.row_key ?? ""); }} />
    {imported.has_original_file && imported.permissions.can_download_original && <a className="catalog-download" href={`/api/catalog/imports/${imported.import_id}/file`}>下载原始 XLSX</a>}
    <section className="catalog-panel catalog-review-panel"><div className="catalog-tabs" role="tablist">{CATALOG_SECTIONS.map((item) => <button aria-selected={section === item} key={item} onClick={() => setSection(item)} role="tab" type="button">{SECTION_META[item].label}<span>{rowsBySection[item].length}</span></button>)}</div><div className="catalog-review-panel__heading"><div><h3>{SECTION_META[section].label}</h3><p>{SECTION_META[section].description}</p></div>{section !== "evidence" && <div className="catalog-review-controls"><label className="catalog-pending-toggle"><input checked={onlyPending} onChange={(event) => setOnlyPending(event.target.checked)} type="checkbox" />仅看待处理</label><label className="catalog-search"><span className="sr-only">搜索当前审核项</span><input onChange={(event) => setQuery(event.target.value)} placeholder="搜索款号、SKU 或字段内容" value={query} /></label></div>}</div>{section !== "evidence" && <CatalogImportSectionTable canEdit={imported.permissions.can_edit} importId={importId} onlyPending={onlyPending} onSaved={async () => { await reload(); }} options={reviewOptions} query={query} rows={rowsBySection[section]} section={section} workflowRevision={imported.workflow_revision} />}{section === "evidence" && <CatalogEvidencePanel importId={importId} workflowRevision={imported.workflow_revision} />}</section>
    <CatalogWorkflowActions imported={imported} onChanged={reload} />
    </>}
  </div>;
}
