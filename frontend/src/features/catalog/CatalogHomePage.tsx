import { CatalogReadError } from "./CatalogReadFailure";
import { catalogReadError } from "./catalogReadError";
import { CatalogSetup } from "./CatalogSetup";
import { LayoutGrid, Rows3 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Button, StatusBadge } from "../../design-system";
import { getCurrentCatalog, type CatalogStyle, type CurrentCatalog } from "./catalogApi";
import { catalogStatusDisplay } from "./catalogTypes";
import { useCatalogNavigation } from "./CatalogNavigationContext";

function dateRange(style: CatalogStyle) {
  const first = style.source_summary.first_seen_date;
  const latest = style.source_summary.latest_seen_date;
  if (!first && !latest) return "暂无来源日期";
  if (first === latest) return first;
  return `${first ?? "—"} 至 ${latest ?? "—"}`;
}

function CatalogCard({ style }: { style: CatalogStyle }) {
  const { setStyleReturn } = useCatalogNavigation();
  const status = catalogStatusDisplay(style.status);
  return <article className="catalog-product-card">
    <div className="catalog-product-card__ticket">
      <span>款式编号</span>
      <strong>{style.style_code}</strong>
      <small>系统身份 STYLE #{style.style_id}</small>
    </div>
    <div className="catalog-product-card__body">
      <div className="catalog-product-card__heading"><div><h3>{style.standard_name}</h3><p>{dateRange(style)}</p></div><StatusBadge label={status.label} tone={status.tone} /></div>
      <dl className="catalog-product-card__metrics">
        <div><dt>实际变体</dt><dd>{style.variant_count}</dd></div>
        <div><dt>Seller SKU</dt><dd>{style.seller_sku_count}</dd></div>
        <div><dt>来源报告</dt><dd>{style.source_summary.source_report_count}</dd></div>
        <div><dt>观察记录</dt><dd>{style.source_summary.observation_count}</dd></div>
      </dl>
      <Link className="catalog-product-card__link" onClick={() => setStyleReturn("/catalog")} to={`/catalog/styles/${style.style_id}`}>查看商品卡</Link>
    </div>
  </article>;
}

export function CatalogHomePage({ canManage }: { canManage: boolean }) {
  const [catalog, setCatalog] = useState<CurrentCatalog | null>();
  const [error, setError] = useState<ReturnType<typeof catalogReadError>>();
  const [refresh, setRefresh] = useState(0);
  const reload = () => { setCatalog(undefined); setError(undefined); setRefresh((value) => value + 1); };
  const { list, setList, setStyleReturn } = useCatalogNavigation();
  const { view } = list;
  const setView = (value: "cards" | "table") => setList({ ...list, view: value });
  useEffect(() => {
    let active = true;
    void getCurrentCatalog().then((value) => { if (active) setCatalog(value); }).catch((reason: unknown) => {
      if (active) setError(catalogReadError(reason, "无法读取商品主档，请检查连接后重试。"));
    });
    return () => { active = false; };
  }, [refresh]);
  useEffect(() => {
    const refreshVisible = () => {
      if (document.visibilityState !== "hidden") { setCatalog(undefined); setError(undefined); setRefresh((value) => value + 1); }
    };
    window.addEventListener("focus", refreshVisible);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => { window.removeEventListener("focus", refreshVisible); document.removeEventListener("visibilitychange", refreshVisible); };
  }, []);
  if (error) return <CatalogReadError failure={error} onRetry={reload} />;
  if (catalog === undefined) return <p role="status">正在读取商品主档…</p>;
  const filtered = (catalog?.styles ?? []).filter((style) => `${style.style_code} ${style.standard_name} ${style.category_name ?? ""}`.toLocaleLowerCase().includes(list.query.trim().toLocaleLowerCase())).sort((a, b) => list.sort === "name" ? a.standard_name.localeCompare(b.standard_name, "zh-CN") : a.style_code.localeCompare(b.style_code, "zh-CN", { numeric: true }));
  const pages = Math.max(1, Math.ceil(filtered.length / 12));
  const page = Math.min(list.page, pages);
  const visible = filtered.slice((page - 1) * 12, page * 12);
  return <div className="catalog-stack">
    <div className="catalog-actions"><Button onClick={reload}>刷新商品主档</Button></div>
    {!catalog ? <section className="catalog-empty"><h2>商品主档尚未初始化</h2><p>已导入的报表不会自动批准为商品主档。请先确认来源范围，再生成候选、审核款式映射并批准。</p>{canManage ? <Link to="/catalog/maintenance">开始初始化商品主档</Link> : <p>请联系管理员完成初始化；你可以继续查看已发布报表。</p>}</section> : <section className="catalog-panel catalog-master">
      <div className="catalog-panel__heading"><div><p className="section-kicker">CATALOG V{catalog.version_number}</p><h2>当前批准主档</h2><p className="catalog-master__intro">先按款式编号找到商品，再进入商品卡查看实际变体、Seller SKU 和来源。这里只显示已经批准生效的内容。</p></div><span>发布修订 {catalog.catalog_publication_revision}</span></div>
      <aside aria-label="商品身份层级" className="catalog-identity-guide">
        <div><strong>款式编号</strong><span>日常识别一个商品款式的业务编号</span></div>
        <div><strong>内部展示 SKU</strong><span>已确认存在的颜色与尺码变体</span></div>
        <div><strong>Seller SKU</strong><span>站点与账号中的销售别名，可多个指向同一变体</span></div>
      </aside>
      <div aria-label="商品主档视图" className="catalog-view-switch" role="group"><button aria-pressed={view === "cards"} onClick={() => setView("cards")} type="button"><LayoutGrid aria-hidden="true" />商品卡</button><button aria-pressed={view === "table"} onClick={() => setView("table")} type="button"><Rows3 aria-hidden="true" />批量表格</button></div>
      <div className="catalog-list-controls"><label>查找商品<input placeholder="款式编号、名称或分类" value={list.query} onChange={(event) => setList({ ...list, query: event.target.value, page: 1 })} /></label><label>排序<select aria-label="排序" value={list.sort} onChange={(event) => setList({ ...list, sort: event.target.value, page: 1 })}><option value="code">款式编号</option><option value="name">商品名称</option></select></label><span role="status">共 {filtered.length} 款</span></div>
      {view === "cards" ? <div className="catalog-card-grid">{visible.map((style) => <CatalogCard key={style.style_id} style={style} />)}</div> : <div className="catalog-table-scroll"><table><thead><tr><th>款式编号</th><th>标准商品名称</th><th>状态</th><th>实际变体</th><th>Seller SKU</th><th>来源报告</th><th>最近出现</th></tr></thead><tbody>{visible.map((style) => <tr key={style.style_id}><td><Link onClick={() => setStyleReturn("/catalog")} to={`/catalog/styles/${style.style_id}`}>{style.style_code}</Link></td><td>{style.standard_name}</td><td>{style.status}</td><td>{style.variant_count}</td><td>{style.seller_sku_count}</td><td>{style.source_summary.source_report_count}</td><td>{style.source_summary.latest_seen_date ?? "—"}</td></tr>)}</tbody></table></div>}
      {filtered.length === 0 && <p>没有符合条件的商品，请调整搜索条件。</p>}
      <div className="catalog-list-controls" aria-label="商品分页"><button type="button" disabled={page === 1} onClick={() => setList({ ...list, page: page - 1 })}>上一页</button><span>第 {page} / {pages} 页</span><button type="button" disabled={page === pages} onClick={() => setList({ ...list, page: page + 1 })}>下一页</button></div>
    </section>}
    <CatalogSetup />
    {canManage && <p className="catalog-maintenance-hint">需要生成候选或使用 XLSX？<Link to="/catalog/maintenance">进入批量维护</Link>。<Link to="/catalog/unmatched">查看待处理</Link></p>}
  </div>;
}
