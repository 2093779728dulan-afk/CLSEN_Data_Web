import { ArrowLeft, ChevronDown, ChevronRight, FileSearch } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { SafeSourceRefView } from "../../components/source-reference/SafeSourceRefView";
import { StatusBadge } from "../../design-system";
import {
  getCatalogStyle,
  getCatalogStylePendingItems,
  getCatalogVariantEvidence,
  getCatalogVariantSellerSkus,
  type CatalogEvidenceItem,
  type CatalogPage,
  type CatalogPendingItem,
  type CatalogSellerSkuAlias,
  type CatalogSku,
  type CatalogSourceSummary,
  type CatalogStyle,
} from "./catalogApi";
import { catalogStatusDisplay } from "./catalogTypes";
import { CatalogCategoryEditor } from "./CatalogCategoryEditor";
import { CatalogChangeReview } from "./CatalogChangeReview";
import { CatalogPendingItems } from "./CatalogPendingItems";

import { useCatalogNavigation } from "./CatalogNavigationContext";

function SourceSummary({ value }: { value: CatalogSourceSummary }) {
  return <span className="catalog-source-summary">{value.source_report_count} 份报告 · {value.observation_count} 条观察 · {value.first_seen_date ?? "—"} 至 {value.latest_seen_date ?? "—"}</span>;
}

function EvidenceRow({ item }: { item: CatalogEvidenceItem }) {
  const [copyMessage, setCopyMessage] = useState("");
  const reportQuery = new URLSearchParams({ report_date: item.report_date, report_type: item.report_type });
  const copySku = async () => {
    try { await navigator.clipboard.writeText(item.seller_sku.preview); setCopyMessage("已复制 SKU"); }
    catch { setCopyMessage("复制失败，请手动选择 SKU 文本复制"); }
  };
  return <li className="catalog-evidence-row">
    <div><strong>{item.report_type === "business_report" ? "经营报告" : "退货报告"}</strong><span>报告归属日：{item.report_date}</span><span>记录事件日期：{item.event_date ?? "未提供"}</span></div>
    <div><span className="catalog-evidence-row__label">Seller SKU</span><SafeSourceRefView source={item.seller_sku} />{!item.seller_sku.is_truncated && !item.seller_sku.is_unsafe && <button type="button" onClick={() => void copySku()}>复制 SKU</button>}<span role="status">{copyMessage}</span></div>
    {item.title && <div><span className="catalog-evidence-row__label">标题</span><SafeSourceRefView source={item.title} /></div>}
    <div><Link to={`/versions?${reportQuery.toString()}`}>查看来源报告版本</Link><p>按报告归属日查找，并选择下方系统版本编号对应的记录。请按对应文件及记录序号核对，不可用系统记录编号定位 Excel 行。</p><p>来源文件：{item.source_filename ?? "未保留文件关联"}</p><p>原表记录序号：{item.source_record_number ?? "未提供"}（表头为第 1 条；CSV 多行单元格会导致文本物理行号不同）</p>{item.report_type === "return_report" && <><p>原始退货时间：{item.source_event_timestamp ?? "未保留"}</p><p>导入来源时区：{item.source_timezone ?? "未提供"}；原始时间如带 UTC 偏移，以该偏移为准。事件日期与报告归属日可能不同。</p></>}{item.title?.is_unsafe && <p>标题含需安全处理的字符，当前展示为安全摘要；此标记不代表 SKU 错误。</p>}</div>
    <details className="catalog-evidence-row__locator"><summary>系统追溯信息</summary><span>系统版本编号 {item.published_version_id} · 系统记录编号 {item.source_row_id}（非文件行号）</span><code>{item.evidence_digest.slice(-8)}</code></details>
  </li>;
}

function VariantDetails({ sku }: { sku: CatalogSku }) {
  const [expanded, setExpanded] = useState(false);
  const [aliases, setAliases] = useState<CatalogPage<CatalogSellerSkuAlias>>();
  const [evidence, setEvidence] = useState<CatalogPage<CatalogEvidenceItem>>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const status = catalogStatusDisplay(sku.status);

  const toggle = async () => {
    const next = !expanded;
    setExpanded(next);
    if (!next || aliases) return;
    setBusy(true);
    setError(undefined);
    try { setAliases(await getCatalogVariantSellerSkus(sku.sku_id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "无法读取 Seller SKU。"); }
    finally { setBusy(false); }
  };

  const loadEvidence = async (page = 1) => {
    setBusy(true);
    setError(undefined);
    try { setEvidence(await getCatalogVariantEvidence(sku.sku_id, page)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "无法读取来源明细。"); }
    finally { setBusy(false); }
  };

  return <article className="catalog-variant-card">
    <div className="catalog-variant-card__main">
      <div className="catalog-variant-card__identity"><span>内部展示 SKU</span><strong>{sku.internal_display_sku}</strong><small>实际变体 {sku.standard_color} / {sku.standard_size} · 系统身份 SKU #{sku.sku_id}</small></div>
      <div className="catalog-variant-card__source"><strong>{sku.seller_sku_count} 个 Seller SKU</strong><SourceSummary value={sku.source_summary} /></div>
      <StatusBadge label={status.label} tone={status.tone} />
      <button aria-expanded={expanded} className="catalog-variant-card__toggle" disabled={busy} onClick={() => { void toggle(); }} type="button">{expanded ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}{expanded ? "收起 Seller SKU" : "展开 Seller SKU"}</button>
    </div>
    {expanded && <div className="catalog-variant-card__details">
      {busy && !aliases && <p role="status">正在读取关联 Seller SKU…</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
      {aliases && <section aria-label="关联 Seller SKU"><div className="catalog-variant-card__section-heading"><div><h3>关联 Seller SKU</h3><p>同一稳定 SKU 下的已批准销售标识，共 {aliases.total_items} 个。</p></div><button className="catalog-evidence-action" onClick={() => { void loadEvidence(1); }} type="button"><FileSearch aria-hidden="true" />查看来源明细</button></div>
        {aliases.items.length === 0 ? <p>暂无已批准 Seller SKU。</p> : <ul className="catalog-alias-list">{aliases.items.map((alias) => <li key={alias.mapping_id}><SafeSourceRefView source={alias.seller_sku} /><span>{alias.seller_account} · {alias.marketplace}</span><SourceSummary value={alias.source_summary} /></li>)}</ul>}
      </section>}
      {evidence && <section aria-label="来源明细" className="catalog-evidence"><div className="catalog-variant-card__section-heading"><div><h3>来源明细</h3><p>按需读取安全摘要，第 {evidence.page} 页，共 {evidence.total_items} 条。</p></div></div><ul className="catalog-evidence-list">{evidence.items.map((item) => <EvidenceRow item={item} key={item.evidence_id} />)}</ul><div className="catalog-evidence-pagination"><button disabled={busy || evidence.page === 1} onClick={() => { void loadEvidence(evidence.page - 1); }} type="button">上一页</button><button disabled={busy || evidence.page * evidence.page_size >= evidence.total_items} onClick={() => { void loadEvidence(evidence.page + 1); }} type="button">下一页</button></div></section>}
    </div>}
  </article>;
}

export function CatalogStylePage() {
  const { styleReturn } = useCatalogNavigation();
  const styleId = Number(useParams().style_id);
  const [value, setValue] = useState<{ catalog_version_id: number; catalog_publication_revision?: number; permissions?: { can_edit: boolean; can_manage_categories: boolean }; style: CatalogStyle; skus: CatalogSku[] }>();
  const [pending, setPending] = useState<{ items: CatalogPendingItem[]; permissions: { can_review: boolean } }>();
  const [error, setError] = useState<string>();
  const refresh = useCallback(async () => {
    const [style, pendingItems] = await Promise.all([getCatalogStyle(styleId), getCatalogStylePendingItems(styleId)]);
    setValue(style);
    setPending(pendingItems);
  }, [styleId]);
  useEffect(() => { void refresh().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "无法读取款式。")); }, [refresh]);
  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (!value) return <p role="status">正在读取款式…</p>;
  return <section className="catalog-panel catalog-style-card">
    <Link className="catalog-back-link" to={styleReturn}><ArrowLeft aria-hidden="true" />{styleReturn === "/catalog/unmatched" ? "返回待处理" : "返回商品主档"}</Link>
    <header className="catalog-style-card__header">
      <div className="catalog-style-card__ticket"><span>款式编号</span><strong>{value.style.style_code}</strong><small>系统永久身份 STYLE #{value.style.style_id}</small></div>
      <div><p className="section-kicker">已批准商品</p><h2>{value.style.standard_name}</h2><p className={value.style.category_id ? "catalog-category-label" : "catalog-category-label catalog-category-label--pending"}>{value.style.category_id ? `${value.style.category_parent ? `${value.style.category_parent.display_name} / ` : ""}${value.style.category_name}（${value.style.category_code}）` : value.style.category_recorded === false ? "未记录分类" : "待分类"}</p><SourceSummary value={value.style.source_summary} /></div>
      <dl><div><dt>实际变体</dt><dd>{value.style.variant_count}</dd></div><div><dt>Seller SKU</dt><dd>{value.style.seller_sku_count}</dd></div></dl>
    </header>
    {pending && <CatalogPendingItems canReview={pending.permissions.can_review} items={pending.items} />}
    {(value.permissions?.can_edit || value.permissions?.can_manage_categories) && <div className="catalog-style-actions">{value.permissions.can_edit && <CatalogChangeReview catalogPublicationRevision={value.catalog_publication_revision ?? 0} onApproved={refresh} style={value.style} />}{value.permissions.can_manage_categories && <CatalogCategoryEditor />}</div>}
    <ol aria-label="商品身份层级" className="catalog-hierarchy">
      <li><span>1</span><div><strong>款式编号</strong><small>{value.style.style_code}</small></div></li>
      <li><span>2</span><div><strong>实际变体</strong><small>只列出已确认存在的颜色与尺码组合</small></div></li>
      <li><span>3</span><div><strong>Seller SKU</strong><small>展开变体后查看它在各站点与账号中的销售别名</small></div></li>
      <li><span>4</span><div><strong>来源</strong><small>按需读取报告、版本与原始行定位</small></div></li>
    </ol>
    <div className="catalog-style-card__variants"><div><h3>实际变体</h3><p>每行都是当前批准版本中真实存在的一个变体，不会补齐颜色 × 尺码组合。</p></div>{value.skus.length === 0 ? <p>当前商品卡暂无实际变体。</p> : value.skus.map((sku) => <VariantDetails key={sku.sku_id} sku={sku} />)}</div>
  </section>;
}
