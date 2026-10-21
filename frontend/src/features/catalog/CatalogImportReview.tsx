import { useCallback, useMemo, useState } from "react";
import { ArrowLeft, Check, FileSearch, Layers, Link2, ListTodo, RefreshCw, Shirt, TriangleAlert } from "lucide-react";

import { Button, FilterToolbar, LinkButton, Skeleton, StatusBadge, StatusMessage, Tabs } from "../../design-system";
import { CatalogEvidencePanel } from "./CatalogEvidencePanel";
import { CatalogImportSectionTable, filterCatalogReviewRows, isCatalogRowPending } from "./CatalogImportSectionTable";
import { CatalogIssueSummary } from "./CatalogIssueSummary";
import { workflowLabel } from "./catalogImportState";
import { buildCatalogReviewOptions } from "./catalogReviewOptions";
import { CATALOG_SECTIONS, type CatalogImportRow, type CatalogImportSummary, type CatalogRowIssue, type CatalogSection } from "./catalogTypes";
import { CatalogWorkflowActions } from "./CatalogWorkflowActions";
import styles from "./CatalogImportReview.module.css";
import type { saveCatalogMutations } from "./catalogApi";

const SECTION_META: Record<CatalogSection, { description: string; label: string }> = {
  styles: { label: "款式命名", description: "确认款号与标准商品名称。" },
  skus: { label: "SKU 标准化", description: "补全内部展示 SKU、标准颜色与尺码。" },
  mappings: { label: "SKU 映射", description: "决定卖家 SKU 是否纳入目录；排除时请填写原因。" },
  exceptions: { label: "解析异常", description: "更正无法识别的原始字段，或明确将其排除。" },
  evidence: { label: "来源证据", description: "查看审核依据；敏感来源标识需要单独显式查看。" },
};
const SECTION_ICONS = { styles: Shirt, skus: Layers, mappings: Link2, exceptions: TriangleAlert, evidence: FileSearch };

export type CatalogImportReviewProps = {
  imported: CatalogImportSummary;
  rowsBySection: Record<CatalogSection, CatalogImportRow[]>;
  rowsLoading?: boolean; loadedSections?: number; refreshing?: boolean; error?: string; reviewReturn?: string;
  onReload: () => void; onSaved: (revision: number) => Promise<void>; onWorkflowChanged: () => Promise<void>;
  saveMutations?: typeof saveCatalogMutations;
};

/** Shared by the routed application and the fictional Storybook reference pages. */
export function CatalogImportReview({ imported, rowsBySection, rowsLoading = false, loadedSections = 0, refreshing = false, error, reviewReturn = "/catalog/maintenance", onReload, onSaved, onWorkflowChanged, saveMutations }: CatalogImportReviewProps) {
  const [section, setSection] = useState<CatalogSection>("styles");
  const [onlyPending, setOnlyPending] = useState(true);
  const [locate, setLocate] = useState<{ issue: CatalogRowIssue; request: number }>();
  const [query, setQuery] = useState("");
  const [draftCounts, setDraftCounts] = useState<Partial<Record<CatalogSection, number>>>({});
  const [savingSections, setSavingSections] = useState<Partial<Record<CatalogSection, boolean>>>({});
  const onDraftCountChange = useCallback((key: CatalogSection, count: number) => setDraftCounts(current => current[key] === count ? current : { ...current, [key]: count }), []);
  const onSavingChange = useCallback((key: CatalogSection, saving: boolean) => setSavingSections(current => current[key] === saving ? current : { ...current, [key]: saving }), []);
  const unsaved = Object.values(draftCounts).reduce((total, count) => total + (count ?? 0), 0);
  const saving = Object.values(savingSections).some(Boolean);
  const locked = saving || refreshing || Boolean(error);
  const blockedReason = locked ? "请等待保存或读取完成；读取失败时请先重新读取草稿。" : unsaved ? `还有 ${unsaved} 行未保存，请先保存修改再进行校验与批准。` : undefined;
  const options = useMemo(() => buildCatalogReviewOptions(rowsBySection), [rowsBySection]);
  const pendingCount = CATALOG_SECTIONS.reduce((total, key) => total + rowsBySection[key].filter(row => isCatalogRowPending(key, row)).length, 0);
  const editableCount = CATALOG_SECTIONS.filter(key => key !== "evidence").reduce((total, key) => total + rowsBySection[key].filter(row => row.projection_state !== "audit_only").length, 0);
  const completedCount = editableCount - pendingCount;
  return <div className={styles.page}>
    <nav className={styles.navigation} aria-label="审核返回导航">
      <LinkButton icon={<ArrowLeft />} to={reviewReturn} variant="quiet">返回来源页面</LinkButton>
      <LinkButton aria-label="返回待处理列表，选择下一项" icon={<ListTodo />} to="/catalog/unmatched" variant="secondary">待处理列表</LinkButton>
    </nav>
    <header className={styles.header}>
      <div><div className={styles.eyebrow}>{imported.source_kind === "xlsx" ? "XLSX 导入" : "在线审核"}<span>#{imported.import_id}</span><span>修订 {imported.workflow_revision}</span></div>
        <div className={styles.titleRow}><h1>商品主档审核</h1><StatusBadge label={workflowLabel(imported)} tone={imported.status === "approved" ? "good" : "warn"} />{!imported.permissions.can_edit && <StatusBadge label="只读" tone="quiet" />}</div>
        <p>把来源字段整理为标准目录。保存草稿后，再校验与批准。</p>
      </div>
      <div className={styles.headerActions}>
        {imported.has_original_file && imported.permissions.can_download_original && <a href={`/api/catalog/imports/${imported.import_id}/file`}>下载原始 XLSX</a>}
        <Button disabled={saving} loading={refreshing} loadingLabel="正在读取草稿" icon={<RefreshCw />} onClick={onReload} variant="secondary">重新读取草稿</Button>
      </div>
    </header>
    {error && <StatusMessage kind="danger" title="最新明细读取失败">{error} 编辑内容保留在当前页面；请重新读取后核对。</StatusMessage>}
    {refreshing && !rowsLoading && <StatusMessage kind="info" title="正在更新审核明细">当前分类、筛选和其他未保存修改会保留。</StatusMessage>}
    {rowsLoading ? <section className={styles.stage} role="status" aria-live="polite"><h2>正在准备审核明细</h2><p>已读取 {loadedSections} / {CATALOG_SECTIONS.length} 类数据。</p><progress aria-label="审核明细加载进度" max={CATALOG_SECTIONS.length} value={loadedSections} /><div aria-hidden="true" className={styles.loadingWorkspace}><Skeleton lines={5} /><div><Skeleton lines={2} /><Skeleton lines={5} /></div></div></section> : <>
      <section className={styles.summary} aria-label="审核完成进度">
        <strong>待处理 {pendingCount} 项</strong><span><Check size={14} aria-hidden="true" />已补全 {completedCount} / {editableCount}</span>
        <progress aria-label="审核字段补全进度" max={Math.max(editableCount, 1)} value={completedCount} />
        <span className={unsaved ? styles.unsaved : undefined}>{unsaved ? `${unsaved} 行本地修改未保存` : imported.status === "approved" ? "已批准生效，本页展示批次记录" : "草稿修改尚未批准生效"}</span>
      </section>
      {(imported.status === "parse_failed" || imported.failure_reason_code || imported.issues?.length) ? <CatalogIssueSummary status={imported.status} issues={imported.issues} failureReason={imported.failure_reason_code} onLocate={issue => { setSection(issue.section); setOnlyPending(false); setQuery(issue.row_key ?? ""); setLocate(current => ({ issue, request: (current?.request ?? 0) + 1 })); }} /> : null}
      <section className={styles.workspace} aria-label="审核明细">
        <Tabs animate ariaLabel="主档审核分类" keepMounted orientation="vertical" value={section} onValueChange={value => setSection(value as CatalogSection)} items={CATALOG_SECTIONS.map(key => {
          const Icon = SECTION_ICONS[key];
          const pending = rowsBySection[key].filter(row => isCatalogRowPending(key, row)).length;
          return {
          value: key, label: <span className={styles.category}><Icon size={18} aria-hidden="true" /><span><strong>{SECTION_META[key].label}</strong><small>{key === "evidence" ? `${rowsBySection[key].length} 条来源记录` : !rowsBySection[key].length ? "暂无记录" : pending ? `${pending} 项待处理` : "字段已补全"}{draftCounts[key] ? ` · ${draftCounts[key]} 行未保存` : ""}</small></span><span className={styles.categoryCount}>{rowsBySection[key].length}</span></span>,
          content: <><div className={styles.sectionHeading}><div><h2>{SECTION_META[key].label}</h2><p>{SECTION_META[key].description}</p></div>
          </div>{key !== "evidence" && <div className={styles.filterBar}><FilterToolbar matchingCount={filterCatalogReviewRows(key, rowsBySection[key], onlyPending, query).length} onOnlyPendingChange={setOnlyPending} onQueryChange={setQuery} onlyPending={onlyPending} query={query} totalCount={rowsBySection[key].length} /></div>}{key === "evidence" ? section === "evidence" && <CatalogEvidencePanel importId={imported.import_id} workflowRevision={imported.workflow_revision} /> : <CatalogImportSectionTable active={section === key}
            onLocateRow={rowKey => { setOnlyPending(false); setQuery(rowKey); setLocate(current => ({ issue: { section: key, row_key: rowKey, field: null, severity: "error", reason_code: "save_failed" }, request: (current?.request ?? 0) + 1 })); }} locate={locate?.issue.section === key ? locate : undefined} issues={imported.issues?.filter(issue => issue.section === key)} busy={locked} identityBlocked={unsaved > 0} canEdit={imported.permissions.can_edit} importId={imported.import_id} onDraftCountChange={onDraftCountChange} onSavingChange={onSavingChange} onSaved={onSaved}
            onlyPending={onlyPending} options={options} query={query} rows={rowsBySection[key]} saveMutations={saveMutations} section={key} workflowRevision={imported.workflow_revision} />}</>,
        }; })} />
      </section>
      <div className={styles.workflow}>
        <CatalogWorkflowActions blockedReason={blockedReason} imported={imported} onChanged={onWorkflowChanged} /></div>
    </>}
  </div>;
}
