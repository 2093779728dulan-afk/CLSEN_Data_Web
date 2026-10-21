import { useState } from "react";
import { CatalogProductDrawer, type CatalogStyleLoader } from "./CatalogProductDrawer";
import { ArrowRight, LayoutGrid, RefreshCw, Rows3, Shirt } from "lucide-react";
import { Link } from "react-router-dom";
import { ContentReveal, StatusMessage, Button, EmptyState, ErrorState, FilterToolbar, FormField, GlideSelectField, LinkButton, Pagination, Skeleton, StatusBadge, Table } from "../../design-system";
import type { CatalogStyle, CurrentCatalog } from "./catalogApi";
import type { CatalogListState } from "./CatalogNavigationContext";
import type { catalogReadError } from "./catalogReadError";
import { catalogStatusDisplay } from "./catalogTypes";
import styles from "./CatalogProductList.module.css";

type Props = {
  catalog: CurrentCatalog | null | undefined;
  failure?: ReturnType<typeof catalogReadError>;
  refreshing?: boolean;
  loadStyle?: CatalogStyleLoader;
  canManage: boolean;
  list: CatalogListState;
  onListChange: (value: CatalogListState) => void;
  onReload: () => void;
  onOpenStyle: () => void;
};

function dateRange(style: CatalogStyle) {
  const { first_seen_date: first, latest_seen_date: latest } = style.source_summary;
  if (!first && !latest) return "暂无来源日期";
  if (!latest) return `始于 ${first}`;
  if (!first) return `最近 ${latest}`;
  if (first === latest) return first;
  return `${first} 至 ${latest}`;
}

function ProductCard({ item, onOpen, onPreview }: { item: CatalogStyle; onOpen: () => void; onPreview: () => void }) {
  const status = catalogStatusDisplay(item.status);
  return <article className={styles.card}>
    <div className={styles.cardHeading}><span className={styles.productIcon} aria-hidden="true"><Shirt /></span><div><span className={styles.code}>{item.style_code}</span><small>系统身份 STYLE #{item.style_id}</small></div><StatusBadge label={status.label} tone={status.tone} /></div>
    <h3><Link onClick={onOpen} to={`/catalog/styles/${item.style_id}`}>{item.standard_name}</Link></h3>
    <p className={styles.category}>{item.category_name || "未分类"}</p>
    <dl className={styles.metrics}><div><dt>实际变体</dt><dd>{item.variant_count}</dd></div><div><dt>Seller SKU</dt><dd>{item.seller_sku_count}</dd></div><div><dt>来源报告</dt><dd>{item.source_summary.source_report_count ?? "—"}</dd></div><div><dt>观察记录</dt><dd>{item.source_summary.observation_count ?? "—"}</dd></div></dl>
    <Button className={styles.preview} variant="quiet" aria-label={`快速查看 ${item.style_code}`} onClick={onPreview}>快速查看</Button>
    <footer className={styles.cardFooter}><span>{dateRange(item)}</span><Link aria-label={`查看 ${item.style_code} 商品卡`} onClick={onOpen} to={`/catalog/styles/${item.style_id}`}>查看商品卡<ArrowRight aria-hidden="true" /></Link></footer>
  </article>;
}

/** Shared by the real catalog route and fictional reference stories. Reads only. */
export function CatalogProductList({ catalog, failure, refreshing = false, loadStyle, canManage, list, onListChange, onReload, onOpenStyle }: Props) {
  const [preview, setPreview] = useState<{ item: CatalogStyle; session: number } | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const openPreview = (item: CatalogStyle) => { setPreview(previous => ({ item, session: (previous?.session ?? 0) + 1 })); setPreviewOpen(true); };
  const retained = Boolean(catalog && failure?.retry);
  const reset = () => onListChange({ ...list, query: "", status: "all", sort: "code", page: 1 });
  const filtered = (catalog?.styles ?? []).filter(item => {
    const status = item.status.trim().toLowerCase();
    return `${item.style_code} ${item.standard_name} ${item.category_name ?? ""}`.toLocaleLowerCase().includes(list.query.trim().toLocaleLowerCase())
      && (list.status === "all" || (list.status === "enabled" ? ["active", "enabled"].includes(status) : ["inactive", "disabled"].includes(status)));
  }).sort((a, b) => list.sort === "name" ? a.standard_name.localeCompare(b.standard_name, "zh-CN") : a.style_code.localeCompare(b.style_code, "zh-CN", { numeric: true }));
  const pages = Math.max(1, Math.ceil(filtered.length / 12));
  const page = Math.min(list.page, pages);
  const visible = filtered.slice((page - 1) * 12, page * 12);
  const loading = catalog === undefined && !failure;
  return <section className={styles.page} aria-label="商品主档列表">
    <header className={styles.header}><div><div className={styles.version}>{catalog ? <><span>CATALOG V{catalog.version_number}</span><span>发布修订 {catalog.catalog_publication_revision}</span>{!canManage && <StatusBadge label="只读" tone="quiet" />}</> : <span>当前商品目录</span>}</div><h2>{catalog ? "当前批准主档" : "商品目录"}</h2><p>只显示已批准生效的商品，进入商品卡查看实际变体、销售别名和来源。</p></div><Button icon={<RefreshCw />} loading={loading || refreshing} disabled={Boolean(failure && !failure.retry)} loadingLabel={refreshing ? "正在刷新主档" : "正在读取主档"} onClick={onReload}>刷新商品主档</Button></header>
    {retained && <StatusMessage kind="warning" title="刷新未完成，当前显示上次读取的主档" action={<Button onClick={onReload} disabled={refreshing}>重新读取</Button>}>{failure?.message}</StatusMessage>}
    {failure && !retained ? <ErrorState title="商品主档读取未完成" description={failure.message} action={failure.setup ? canManage ? <LinkButton to="/catalog/maintenance">前往批量维护，完成初始化</LinkButton> : <span>请联系管理员完成准备状态。</span> : failure.retry ? <Button onClick={onReload}>重新读取</Button> : undefined} />
      : loading ? <div role="status" aria-label="正在读取商品主档" className={styles.loading}><p>正在读取商品主档…</p><div className={styles.cards}>{[0, 1, 2].map(key => <Skeleton key={key} lines={4} />)}</div></div>
      : !catalog ? <EmptyState title="商品主档尚未初始化" description="已导入的报表不会自动批准为商品主档。请先确认来源范围，再生成候选、审核款式映射并批准。" action={canManage ? <LinkButton to="/catalog/maintenance" variant="primary">开始初始化商品主档</LinkButton> : <span>请联系管理员完成初始化；你可以继续查看已发布报表。</span>} />
      : <>
        <ContentReveal className={styles.workspace}>
          <div className={styles.controls}><FilterToolbar matchingCount={filtered.length} totalCount={catalog.styles.length} query={list.query} onQueryChange={query => onListChange({ ...list, query, page: 1 })} hasAdditionalFilters={list.status !== "all" || list.sort !== "code"} onReset={reset} searchLabel="查找商品" placeholder="款式编号、名称或分类">
            <FormField label="商品状态"><GlideSelectField ariaLabel="商品状态" value={list.status} onChange={status => onListChange({ ...list, status: status as CatalogListState["status"], page: 1 })} options={[{ value: "all", label: "全部状态" }, { value: "enabled", label: "已启用" }, { value: "disabled", label: "已停用" }]} /></FormField>
            <FormField label="排序"><GlideSelectField ariaLabel="排序" value={list.sort} onChange={sort => onListChange({ ...list, sort, page: 1 })} options={[{ value: "code", label: "款式编号" }, { value: "name", label: "商品名称" }]} /></FormField>
          </FilterToolbar></div>
          <div className={styles.resultHeading}><span aria-live="polite">{refreshing ? "正在刷新，保留当前列表" : `${filtered.length} 款商品`}<span className={styles.pageNote}> · 每页 12 款</span></span><div className={styles.views} role="group" aria-label="商品主档视图"><Button aria-pressed={list.view === "cards"} icon={<LayoutGrid />} onClick={() => onListChange({ ...list, view: "cards" })} variant="quiet">商品卡</Button><Button aria-pressed={list.view === "table"} icon={<Rows3 />} onClick={() => onListChange({ ...list, view: "table" })} variant="quiet">批量表格</Button></div></div>
          {visible.length === 0 ? <div className={styles.empty}><EmptyState title={catalog.styles.length === 0 ? "当前主档尚无商品" : "没有符合条件的商品"} description={catalog.styles.length === 0 ? "当前已批准版本没有商品记录，请核对主档维护结果。" : "试试其他款式编号、名称或状态，也可以点击上方“重置筛选”查看全部商品。"} /></div>
            : list.view === "cards" ? <div className={styles.cards}>{visible.map(item => <ProductCard key={item.style_id} item={item} onOpen={onOpenStyle} onPreview={() => openPreview(item)} />)}</div>
            : <div className={styles.tableFrame}><p className={styles.tableHint}>点击款式编号或“查看商品卡”进入详情；窄屏可横向滚动表格。</p><Table className={styles.table} aria-label="商品主档批量表格"><thead><tr><th scope="col">款式编号</th><th scope="col">标准商品名称</th><th scope="col">状态</th><th scope="col">实际变体</th><th scope="col">Seller SKU</th><th scope="col">来源报告</th><th scope="col">最近出现</th><th scope="col">操作</th></tr></thead><tbody>{visible.map(item => { const status = catalogStatusDisplay(item.status); return <tr key={item.style_id}><td><Link onClick={onOpenStyle} to={`/catalog/styles/${item.style_id}`}>{item.style_code}</Link><small>STYLE #{item.style_id}</small></td><td><strong>{item.standard_name}</strong><small>{item.category_name || "未分类"}</small></td><td><StatusBadge label={status.label} tone={status.tone} /></td><td>{item.variant_count}</td><td>{item.seller_sku_count}</td><td>{item.source_summary.source_report_count ?? "—"}</td><td className={styles.date}>{item.source_summary.latest_seen_date ?? "—"}</td><td><Button variant="quiet" aria-label={`快速查看 ${item.style_code}`} onClick={() => openPreview(item)}>快速查看</Button><Link aria-label={`查看 ${item.style_code} 商品卡`} onClick={onOpenStyle} to={`/catalog/styles/${item.style_id}`}><ArrowRight aria-hidden="true" /><span>查看商品卡</span></Link></td></tr>; })}</tbody></Table></div>}
          <footer className={styles.footer}><Pagination itemLabel="款商品" onPageChange={next => onListChange({ ...list, page: next })} page={page} totalItems={filtered.length} totalPages={pages} /></footer>
        </ContentReveal>
        {preview && <CatalogProductDrawer key={preview.session} item={preview.item} open={previewOpen} onOpenChange={setPreviewOpen} onOpenStyle={onOpenStyle} loadStyle={loadStyle} />}
        <details className={styles.guide}><summary>商品身份与阅读说明</summary><dl><div><dt>款式编号</dt><dd>日常识别一个商品款式的业务编号。</dd></div><div><dt>内部展示 SKU</dt><dd>已经确认存在的颜色与尺码变体。</dd></div><div><dt>Seller SKU</dt><dd>站点与账号中的销售别名，可多个指向同一变体。</dd></div></dl></details>
      </>}
  </section>;
}
