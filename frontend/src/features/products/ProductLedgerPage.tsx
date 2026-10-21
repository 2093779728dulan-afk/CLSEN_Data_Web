import { analyticsError, type AnalyticsFailure } from "./analyticsError";
import { AnalyticsErrorState } from "./AnalyticsErrorState";
import { CatalogSetup } from "../catalog/CatalogSetup";
import { listCatalogCategories, type CatalogCategory } from "../catalog/catalogApi";
import { LedgerMetricHelp, type LedgerHelpKey } from "./LedgerMetricHelp";
import { averagePrice, salesShare, returnSalesRatio } from "./ledgerInsights";
import { Button, EmptyState, Input, Pagination, Select, Skeleton } from "../../design-system";
import { ProductIdentityCell } from "./ProductIdentityCell";
import css from "./ProductAnalytics.module.css";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { loadStyleLedger } from "./productAnalyticsApi";
import type { StyleLedgerResponse } from "./productAnalyticsTypes";
import { CoverageReconciliation } from "./CoverageReconciliation";
import { MetricValueView, type MetricKind } from "./MetricValueView";
import {
  parseProductLedgerSearch,
  serializeProductLedgerSearch,
  updateProductLedgerView,
  type ProductLedgerView,
} from "./productLedgerState";


type Loaded = { key: string; scope: string; generation: number; value: StyleLedgerResponse };
type Failed = { key: string; failure: AnalyticsFailure };

const metricColumns: Array<{ key: MetricKind; label: string }> = [
  { key: "units", label: "销量" }, { key: "sales", label: "销售额 US$" },
  { key: "returns", label: "本期退货量" }, { key: "sessions", label: "会话" },
  { key: "conversion", label: "转化率" },
];

function requestKey(view: ProductLedgerView): string {
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
  const selectedCategory = categories.find((item) => item.category_id === view.category_id);
  const rootCategory = selectedCategory?.parent_category_id ?? view.category_id;
  const [loaded, setLoaded] = useState<Loaded>();
  const [failed, setFailed] = useState<Failed>();
  const [loadingKey, setLoadingKey] = useState<string>();
  const [showNames, setShowNames] = useState(false);
  const [reload, setReload] = useState(0);
  const [draft, setDraft] = useState({ from: view.from, search: view.search, to: view.to });
  const sequence = useRef(0);

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

  const update = (change: Partial<ProductLedgerView>, replace = false) => {
    setParameters(serializeProductLedgerSearch(updateProductLedgerView(view, change)), { replace });
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
  const sortLabels: Record<ProductLedgerView["sort"], string> = { style_code: "款号", standard_name: "标准名称", units: "销量", sales: "销售额", returns: "本期退货量", sessions: "会话", conversion: "转化率" };
  const sortDescription = response ? `${sortLabels[response.sort]} · ${response.direction === "desc" ? "从高到低" : "从低到高"}` : "";
  const returnsView = response?.sort === "returns" && response.direction === "desc";
  const metricHelp = (metric: LedgerHelpKey) => response && <LedgerMetricHelp metric={metric} from={view.from} to={view.to} returnBasis={view.return_basis} factBasis={view.fact_basis} catalogVersion={response.provenance.catalog_version} />;
  const pageCount = response ? Math.max(1, Math.ceil(response.total_rows / response.page_size)) : 1;

  return <main className={css["product-analytics"]} id="main-content">
    <header className={css["product-analytics__header"]}>
      <div><p className={css["analytics-eyebrow"]}>STABLE STYLE LEDGER</p><h1>产品总表</h1>
        <p>按稳定款式比较销量、销售额、退货、会话与转化率。标准名称来自已批准商品主档。</p></div>
      {response && <dl className={css["analytics-provenance"]}><div><dt>身份来源</dt><dd>P0 商品主档</dd></div>
        <div><dt>目录版本</dt><dd>{response.provenance.catalog_version}</dd></div>
        <div><dt>事实口径</dt><dd>{response.provenance.fact_basis === "current" ? "当前事实" : "目录快照"}</dd></div>
        <div><dt>一致时间</dt><dd>{response.provenance.consistent_as_of}</dd></div>
        <div><dt>报告时区</dt><dd>{response.provenance.reporting_timezone}</dd></div></dl>}
    </header>

    <form className={css["analytics-filterbar"]} onSubmit={submit}>
      <label>开始日期<Input max={today} onChange={(event) => setDraft((value) => ({ ...value, from: event.target.value }))} required type="date" value={draft.from} /></label>
      <label>结束日期<Input min={draft.from} max={today} onChange={(event) => setDraft((value) => ({ ...value, to: event.target.value }))} required type="date" value={draft.to} /></label>
      <label>主分类<Select aria-label="筛选主分类" value={rootCategory ?? ""} onChange={(event) => update({ category_id: Number(event.target.value) || null })}><option value="">全部分类</option>{categories.filter((item) => !item.parent_category_id).map((item) => <option key={item.category_id} value={item.category_id}>{item.display_name}</option>)}</Select></label>
      {rootCategory && <label>细分类<Select aria-label="筛选细分类" value={selectedCategory?.parent_category_id ? (view.category_id ?? "") : ""} onChange={(event) => update({ category_id: Number(event.target.value) || rootCategory })}><option value="">全部细分类（含仅主分类商品）</option>{categories.filter((item) => item.parent_category_id === rootCategory).map((item) => <option key={item.category_id} value={item.category_id}>{item.display_name}</option>)}</Select></label>}
      <label className={css["analytics-filterbar__search"]}>款号或标准名称<Input maxLength={100} onChange={(event) => setDraft((value) => ({ ...value, search: event.target.value }))} placeholder="输入款号或标准名称" value={draft.search} /></label>
      <label>退货日期<Select onChange={(event) => update({ return_basis: event.target.value as ProductLedgerView["return_basis"] })} value={view.return_basis}><option value="event_date">事件日期</option><option value="report_date">报表日期</option></Select></label>
      <label>事实版本<Select onChange={(event) => update({ fact_basis: event.target.value as ProductLedgerView["fact_basis"] })} value={view.fact_basis}><option value="current">当前事实</option><option value="catalog_snapshot">目录快照</option></Select></label>
      <Button variant="primary" type="submit">应用筛选</Button>
    </form>

    <p className={css["analytics-live"]} aria-live="polite">{loading ? response ? "正在更新排序，暂时显示上次结果。" : "正在读取产品总表，旧结果已隐藏。" : error ? error : response ? `已读取 ${response.total_rows} 个稳定款式。` : ""}</p>
    {loading && !response && <section aria-busy="true" aria-label="正在读取产品总表"><Skeleton lines={3} /></section>}
    {failure && <AnalyticsErrorState title="产品总表读取失败" failure={failure} onRetry={() => setReload(value => value + 1)} />}
    {failure?.setup && <CatalogSetup />}


    {response && <>
      {response.coverage.business.published_days === 0 && response.coverage.returns.published_days === 0 && <EmptyState title="所选日期没有已发布报表" description="请调整日期或到每日数据查看已有报表；缺失数据不代表销量为零。" />}
      <section className={css["analytics-ledger"]} aria-labelledby="product-ledger-title">
        <div className={css["analytics-section-heading"]}><div><p className={css["analytics-eyebrow"]}>{response.total_rows.toLocaleString("zh-CN")} STYLES</p><h2 id="product-ledger-title">稳定款式</h2></div>
          <label className={css["analytics-name-toggle"]}><input type="checkbox" checked={showNames} onChange={(event) => setShowNames(event.target.checked)} />显示商品名称</label>
          <label>每页<Select onChange={(event) => update({ page_size: Number(event.target.value) })} value={view.page_size}><option value="25">25</option><option value="50">50</option><option value="100">100</option></Select></label></div>
        <div className={css["ledger-views"]} role="group" aria-label="经营快捷视图">
          <Button aria-pressed={response.sort === "sales" && response.direction === "desc"} onClick={() => update({ sort: "sales", direction: "desc" })}>销售贡献</Button>
          <Button aria-pressed={returnsView} onClick={() => update({ sort: "returns", direction: "desc" })}>退货关注</Button>
          <span className={css["ledger-sort-status"]} aria-live="polite">当前排序：<strong>{sortDescription}</strong>{refreshing ? " · 正在更新…" : " · 点击表头切换顺序"}</span>
        </div>
        <p className={css["ledger-basis"]}>分类筛选以所选已批准目录的分类路径为准。 本期退货按{view.return_basis === "event_date" ? "事件日期" : "报表日期"}统计；可能来自此前订单。{returnsView && "同期退销比 = 本期退货量 ÷ 本期销量，不代表订单退货率。"} 平均单价 = 销售额 ÷ 销量。{response.coverage.business.missing_days > 0 && "销售报表有缺失，占比和单价仅反映已发布数据。"}</p>
        {response.rows.length === 0 ? <EmptyState title="没有匹配的稳定款式" description="调整日期或搜索条件；未归类来源不会伪造成款式。" /> :
          <div className={css["analytics-table-scroll"]} role="region" aria-label="产品总表，可横向滚动" tabIndex={0}><table aria-busy={refreshing} inert={refreshing} className={css["analytics-table"] + " " + css["analytics-table--ledger"] + (showNames ? " " + css["analytics-table--names"] : "")}><thead><tr>
            <th aria-sort={response.sort === "style_code" ? response.direction === "asc" ? "ascending" : "descending" : "none"} scope="col"><div className={css["ledger-column-heading"]}><button onClick={() => update({ sort: "style_code", direction: view.sort === "style_code" && view.direction === "asc" ? "desc" : "asc" })} type="button" title="点击按款号排序，再次点击切换顺序">款号</button>{metricHelp("identity")}</div></th>
            <th scope="col"><div className={css["ledger-column-heading"]}>实际变体{metricHelp("variants")}</div></th>{metricColumns.map((column) => <th aria-sort={response.sort === column.key ? response.direction === "asc" ? "ascending" : "descending" : "none"} key={column.key} scope="col"><div className={css["ledger-column-heading"]}><button onClick={() => update({ sort: column.key, direction: view.sort === column.key && view.direction === "desc" ? "asc" : "desc" })} type="button" title={`点击按${column.label}排序，再次点击切换顺序`}>{column.label}</button>{metricHelp(column.key)}</div></th>)}<th scope="col"><div className={css["ledger-column-heading"]}>平均单价 US${metricHelp("average")}</div></th>
          </tr></thead><tbody>{response.rows.map((row) => <tr id={`style-${row.style_id}`} key={row.style_id}>
            <th scope="row"><ProductIdentityCell row={row} showName={showNames} ledgerUrl={`?${canonical}`} detailUrl={`/products/${encodeURIComponent(row.style_id)}?from=${view.from}&to=${view.to}&return_basis=${view.return_basis}&fact_basis=${view.fact_basis}`} /></th>
            <td><strong>{row.sku_count}</strong><small>{row.color_count} 色 · {row.size_count} 码</small></td>
            {metricColumns.map((column) => <td key={column.key}><MetricValueView compact percentage kind={column.key} metric={row.metrics[column.key]} />
              {column.key === "sales" && <small>占比 {salesShare(row.metrics.sales, response.filtered_sales_total)}</small>}
              {column.key === "returns" && returnsView && <small>同期退销比 {returnSalesRatio(row.metrics.returns, row.metrics.units)}{(row.metrics.returns.is_partial || row.metrics.units.is_partial) && " · 部分数据"}</small>}</td>)}
            <td>{averagePrice(row.metrics.sales, row.metrics.units)}{(row.metrics.sales.is_partial || row.metrics.units.is_partial) && <small>部分数据</small>}</td>
          </tr>)}</tbody></table></div>}
        <div className={css["analytics-pagination"]}><Pagination itemLabel="款式" loading={loading} onPageChange={(page) => update({ page })} page={response.page} totalItems={response.total_rows} totalPages={pageCount} /></div>
      </section>
      <CoverageReconciliation coverage={response.coverage} reconciliation={response.reconciliation} from={view.from} to={view.to} returnBasis={view.return_basis} />
    </>}
  </main>;
}
