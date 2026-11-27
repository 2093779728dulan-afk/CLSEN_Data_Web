import { Disclosure } from "../../design-system";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Check, FileSearch, Layers, Link2, ListTodo, RefreshCw, Shirt, TriangleAlert } from "lucide-react";

import { Button, FilterToolbar, LinkButton, Skeleton, StatusBadge, StatusMessage, Tabs } from "../../design-system";
import { CatalogEvidencePanel } from "./CatalogEvidencePanel";
import { CatalogImportSectionTable, filterCatalogReviewRows, isCatalogRowPending } from "./CatalogImportSectionTable";
import { CatalogIssueSummary } from "./CatalogIssueSummary";
import { workflowLabel } from "./catalogImportState";
import { buildCatalogReviewOptions } from "./catalogReviewOptions";
import { CATALOG_SECTIONS, type CatalogDraftSaveAction, type CatalogSaveRecovery, type CatalogImportRow, type CatalogImportSummary, type CatalogRowIssue, type CatalogSection } from "./catalogTypes";
import { CatalogWorkflowActions } from "./CatalogWorkflowActions";
import styles from "./CatalogImportReview.module.css";
import type { saveCatalogMutations } from "./catalogApi";

const SECTION_META: Record<CatalogSection, { description: string; label: string }> = {
  styles: { label: "款式命名", description: "确认款号。标准商品名称选填，可参考官方报告后补。" },
  skus: { label: "SKU 标准化", description: "确认标准颜色与尺码，选择有来源的正式SKU或明确待补。" },
  mappings: { label: "SKU 映射", description: "决定卖家 SKU 是否纳入目录；排除时请填写原因。" },
  exceptions: { label: "解析异常", description: "更正无法识别的原始字段，或明确将其排除。" },
  evidence: { label: "来源证据", description: "查看审核依据；敏感来源标识需要单独显式查看。" },
};
const SECTION_ICONS = { styles: Shirt, skus: Layers, mappings: Link2, exceptions: TriangleAlert, evidence: FileSearch };

export type CatalogImportReviewProps = {
  onRecoverConflict?: () => Promise<CatalogSaveRecovery>;
  onSaveAction?: (action: CatalogDraftSaveAction | undefined) => void;
  embedded?:boolean;onGuardChange?:(guard:{dirty:boolean;busy:boolean;unknown:boolean})=>void;onNavigate?:(id:number)=>void;
  imported: CatalogImportSummary;
  rowsBySection: Record<CatalogSection, CatalogImportRow[]>;
  rowsLoading?: boolean; loadedSections?: number; refreshing?: boolean; error?: string; reviewReturn?: string;
  onReload: () => void; onSaved: (revision: number) => Promise<void>; onWorkflowChanged: () => Promise<void>;
  saveMutations?: typeof saveCatalogMutations;
};

/** Shared by the routed application and the fictional Storybook reference pages. */
export function CatalogImportReview({ embedded, onRecoverConflict, onSaveAction, onGuardChange, onNavigate, imported, rowsBySection, rowsLoading = false, loadedSections = 0, refreshing = false, error, reviewReturn = "/catalog/maintenance", onReload, onSaved, onWorkflowChanged, saveMutations }: CatalogImportReviewProps) {
  const [saveAction, setSaveAction] = useState<CatalogDraftSaveAction>();
  const [section, setSection] = useState<CatalogSection>(()=>["mappings","skus","exceptions","styles"].find(key=>rowsBySection[key as CatalogSection].some(row=>isCatalogRowPending(key as CatalogSection,row))) as CatalogSection||"styles");
  const [onlyPending, setOnlyPending] = useState(true);
  const initialSection=useRef(false);
  useEffect(()=>{if(rowsLoading||initialSection.current)return;initialSection.current=true;const next=(["mappings","skus","exceptions","styles"] as const).find(key=>rowsBySection[key].some(row=>isCatalogRowPending(key,row)));if(next)setSection(next);},[rowsLoading,rowsBySection]);

  const [locate, setLocate] = useState<{ issue: CatalogRowIssue; request: number }>();
  const [query, setQuery] = useState("");
  const [draftCounts, setDraftCounts] = useState<Partial<Record<CatalogSection, number>>>({});
  const [savingSections, setSavingSections] = useState<Partial<Record<CatalogSection, boolean>>>({});
  const [workflowGuard,setWorkflowGuard]=useState({dirty:false,busy:false,unknown:false});
  const onDraftCountChange = useCallback((key: CatalogSection, count: number) => setDraftCounts(current => current[key] === count ? current : { ...current, [key]: count }), []);
  const onSavingChange = useCallback((key: CatalogSection, saving: boolean) => setSavingSections(current => current[key] === saving ? current : { ...current, [key]: saving }), []);
  const unsaved = Object.values(draftCounts).reduce((total, count) => total + (count ?? 0), 0);
  const saving = Object.values(savingSections).some(Boolean);
  useEffect(()=>onGuardChange?.({dirty:unsaved>0||workflowGuard.dirty,busy:saving||refreshing||workflowGuard.busy,unknown:workflowGuard.unknown}),[unsaved,saving,refreshing,workflowGuard,onGuardChange]);
  const blockedReason = saving || refreshing || Boolean(error) ? "请等待保存或读取完成；读取失败时请先重新读取草稿。" : unsaved ? `还有 ${unsaved} 行未保存，请先保存修改再进行校验与批准。` : undefined;
  const locked = saving || refreshing || Boolean(error) || workflowGuard.busy || workflowGuard.unknown;
  const options = useMemo(() => buildCatalogReviewOptions(rowsBySection), [rowsBySection]);
  const sourceCount = imported.production_source?.report_selection?.source_rows.length ?? imported.production_source?.rows.length ?? rowsBySection.evidence.length;
  const pendingCount = CATALOG_SECTIONS.reduce((total, key) => total + rowsBySection[key].filter(row => isCatalogRowPending(key, row)).length, 0);
  const pendingNames = rowsBySection.styles.filter(row => row.projection_state !== "audit_only" && !String(row.payload.standard_name ?? "").trim()).length;
  const editableCount = CATALOG_SECTIONS.filter(key => key !== "evidence").reduce((total, key) => total + rowsBySection[key].filter(row => row.projection_state !== "audit_only").length, 0);
  const completedCount = editableCount - pendingCount;
  return <div className={styles.page}>
    <nav hidden={embedded} className={styles.navigation} aria-label="审核返回导航">
      <LinkButton icon={<ArrowLeft />} to={reviewReturn.startsWith("/catalog/unmatched") ? reviewReturn : imported.production_source?.report_selection ? reviewReturn : imported.production_source?.sku_format_policy === "style-color-size-v1" ? `/catalog/production-sources?entry=product-intake&listing=${imported.import_id}` : imported.production_source?.source_schema === "amazon_listing_v1" ? imported.status === "approved" ? "/catalog/production-sources?entry=amazon-listing" : `/catalog/production-sources?entry=amazon-listing&listing=${imported.import_id}` : imported.source_kind === "production" ? "/catalog/production-sources" : reviewReturn} variant="quiet">{reviewReturn.startsWith("/catalog/unmatched") ? "返回待归属与审核" : imported.production_source?.sku_format_policy === "style-color-size-v1" ? "返回商品建档" : imported.production_source?.source_schema === "amazon_listing_v1" ? "返回亚马逊商品清单核对" : imported.source_kind === "production" ? "返回商品建档" : "返回来源页面"}</LinkButton>
      <LinkButton aria-label="返回待处理列表，选择下一项" icon={<ListTodo />} to="/catalog/unmatched" variant="secondary">待处理列表</LinkButton>
    </nav>
    <header className={styles.header}>
      <div><div className={styles.eyebrow}>{imported.source_kind === "production" ? "商品建档候选" : imported.source_kind === "xlsx" ? "XLSX 导入" : "在线审核"}<span>#{imported.import_id}</span><span>修订 {imported.workflow_revision}</span></div>
        <div className={styles.titleRow}><h1>商品主档审核</h1><StatusBadge label={workflowLabel(imported)} tone={imported.status === "approved" ? "good" : "warn"} />{!imported.permissions.can_edit && <StatusBadge label="只读" tone="quiet" />}</div>
        <p>把来源字段整理为标准目录。保存草稿后，再校验与批准。</p>
      </div>
      <div className={styles.headerActions}>
        {imported.has_original_file && imported.permissions.can_download_original && <LinkButton variant="secondary" reloadDocument download to={`/api/catalog/imports/${imported.import_id}/file`}>下载原始 XLSX</LinkButton>}
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
      {pendingNames > 0 && <StatusMessage kind="info" title={`${pendingNames} 款商品名称待补，可继续建档`} action={<Button variant="quiet" onClick={() => { setSection("styles"); setOnlyPending(false); setQuery("名称待补"); }}>查看待补名称</Button>} />}
      {(imported.status === "parse_failed" || imported.failure_reason_code || imported.issues?.length) ? <CatalogIssueSummary pendingEdits={unsaved} onSection={key=>{setSection(key);setOnlyPending(true);setQuery("");setLocate(undefined);}} status={imported.status} issues={imported.issues} failureReason={imported.failure_reason_code} onLocate={issue => { setSection(issue.section); setOnlyPending(false); setQuery(issue.row_key ?? ""); setLocate(current => ({ issue, request: (current?.request ?? 0) + 1 })); }} /> : null}
      {!!imported.production_source?.format_adjustments?.length && <Disclosure><summary>本批格式整理记录（{imported.production_source.format_adjustments.length}处，原文保留）</summary><table aria-label="已保存格式整理对照"><thead><tr><th>来源位置</th><th>字段</th><th>原值</th><th>候选值</th><th>依据</th></tr></thead><tbody>{imported.production_source.format_adjustments.map((change, index) => <tr key={index}><td>{change.location}</td><td>{({ style_code: "款号", color: "颜色", size: "尺码" } as Record<string, string>)[change.field] ?? change.field}</td><td><code>{JSON.stringify(change.before)}</code></td><td><code>{JSON.stringify(change.after)}</code></td><td>{change.reason}</td></tr>)}</tbody></table></Disclosure>}
      <div className={styles.workflow}>
        <CatalogWorkflowActions automatic embedded={embedded} onGuardChange={setWorkflowGuard} onNavigate={onNavigate} blockedReason={blockedReason} imported={imported} onChanged={onWorkflowChanged} /></div>
      <section className={styles.workspace} aria-label="审核明细">
        <Tabs animate ariaLabel="主档审核分类" keepMounted orientation="vertical" value={section} onValueChange={value => setSection(value as CatalogSection)} items={CATALOG_SECTIONS.map(key => {
          const Icon = SECTION_ICONS[key];
          const pending = rowsBySection[key].filter(row => isCatalogRowPending(key, row)).length;
          return {
          value: key, label: <span className={styles.category}><Icon size={18} aria-hidden="true" /><span><strong>{SECTION_META[key].label}</strong><small>{key === "evidence" ? `${sourceCount} 条来源记录` : !rowsBySection[key].length ? "暂无记录" : pending ? `${pending} 项待处理` : "字段已补全"}{draftCounts[key] ? ` · ${draftCounts[key]} 行未保存` : ""}</small></span><span className={styles.categoryCount}>{key === "evidence" ? sourceCount : rowsBySection[key].length}</span></span>,
          content: <><div className={styles.sectionHeading}><div><h2>{SECTION_META[key].label}</h2><p>{SECTION_META[key].description}</p></div>
          </div>{key !== "evidence" && <div className={styles.filterBar}><FilterToolbar matchingCount={filterCatalogReviewRows(key, rowsBySection[key], onlyPending, query).length} onOnlyPendingChange={setOnlyPending} onQueryChange={setQuery} onlyPending={onlyPending} query={query} totalCount={rowsBySection[key].length} /></div>}{key === "evidence" ? section === "evidence" && (imported.production_source ? <section aria-label="商品建档来源"><h3>{imported.production_source.source_name}</h3><p>登记时间 {new Date(imported.production_source.recorded_at).toLocaleString("zh-CN")} · 原始来源摘要 {imported.production_source.digest}</p>{imported.production_source.report_selection && <p>已发布报表单条来源：{imported.production_source.report_selection.source_rows.map(row => row.seller_sku).join("、")} · 账号范围#{imported.production_source.report_selection.request.scope_id} · 报告版本{imported.production_source.report_selection.request.version_ids.join("、")}</p>}<table><thead><tr><th>行</th><th>原款号</th><th>原颜色</th><th>原尺码</th></tr></thead><tbody>{imported.production_source.rows.map((row, index) => <tr key={index}><td>{index + 1}</td><td>{row.style_code}</td><td>{row.color}</td><td>{row.size}</td></tr>)}</tbody></table></section> : <CatalogEvidencePanel importId={imported.import_id} workflowRevision={imported.workflow_revision} />) : <CatalogImportSectionTable onRecoverConflict={onRecoverConflict} onSaveAction={onSaveAction ?? setSaveAction} active={section === key}
            onLocateRow={rowKey => { setOnlyPending(false); setQuery(rowKey); setLocate(current => ({ issue: { section: key, row_key: rowKey, field: null, severity: "error", reason_code: "save_failed" }, request: (current?.request ?? 0) + 1 })); }} locate={locate?.issue.section === key ? locate : undefined} issues={imported.issues?.filter(issue => issue.section === key)} busy={locked} identityBlocked={unsaved > 0} canEdit={imported.permissions.can_edit} importId={imported.import_id} onDraftCountChange={onDraftCountChange} onSavingChange={onSavingChange} onSaved={onSaved}
            onlyPending={onlyPending} options={options} productionSource={imported.source_kind === "production"} query={query} rows={rowsBySection[key]} saveMutations={saveMutations} section={key} workflowRevision={imported.workflow_revision} />}</>,
        }; })} />
      </section>

    </>}
    {!embedded && !onSaveAction && saveAction && <footer className={styles.saveBar} aria-label="审核固定操作"><strong>当前分类有未保存修改</strong><Button variant="primary" disabled={saveAction.disabled} onClick={saveAction.run}>{saveAction.label}</Button></footer>}
  </div>;
}
