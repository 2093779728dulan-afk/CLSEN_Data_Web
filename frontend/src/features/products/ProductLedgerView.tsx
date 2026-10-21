import type { FormEvent, ReactNode } from "react";
import { Button, Checkbox, EmptyState, FormField, Input, Pagination, Select, Skeleton, StatusBadge, Table } from "../../design-system";
import { AnalyticsErrorState } from "./AnalyticsErrorState";
import type { AnalyticsFailure } from "./analyticsError";
import { LedgerMetricHelp, type LedgerHelpKey } from "./LedgerMetricHelp";
import { averagePrice, salesShare, returnSalesRatio } from "./ledgerInsights";
import { ProductIdentityCell } from "./ProductIdentityCell";
import { CoverageReconciliation } from "./CoverageReconciliation";
import { MetricValueView, type MetricKind } from "./MetricValueView";
import type { CatalogCategory } from "../catalog/catalogApi";
import type { StyleLedgerResponse } from "./productAnalyticsTypes";
import type { ProductLedgerView as LedgerFilters } from "./productLedgerState";
import css from "./ProductLedgerView.module.css";

type Props = {
  today: string;
  view: LedgerFilters;
  canonical: string;
  categories: CatalogCategory[];
  draft: { from: string; to: string; search: string };
  response?: StyleLedgerResponse;
  failure?: AnalyticsFailure;
  loading: boolean;
  refreshing: boolean;
  showNames: boolean;
  setupContent?: ReactNode;
  onDraftChange: (change: Partial<Props["draft"]>) => void;
  onShowNamesChange: (show: boolean) => void;
  onSubmit: (event: FormEvent) => void;
  onUpdate: (change: Partial<LedgerFilters>) => void;
  onRetry: () => void;
};
const metricColumns: Array<{ key: MetricKind; label: string }> = [
  { key: "units", label: "销量" }, { key: "sales", label: "销售额 US$" },
  { key: "returns", label: "本期退货量" }, { key: "sessions", label: "会话" }, { key: "conversion", label: "转化率" },
];

export function ProductLedgerView({ today, view, canonical, categories, draft, response, failure, loading, refreshing, showNames, setupContent, onDraftChange, onShowNamesChange, onSubmit, onUpdate, onRetry }: Props) {
  const selectedCategory = categories.find(item => item.category_id === view.category_id);
  const rootCategory = selectedCategory?.parent_category_id ?? view.category_id;
  const error = failure?.message;
  const sortLabels: Record<LedgerFilters["sort"], string> = { style_code: "款号", standard_name: "标准名称", units: "销量", sales: "销售额", returns: "本期退货量", sessions: "会话", conversion: "转化率" };
  const sortDescription = response ? `${sortLabels[response.sort]} · ${response.direction === "desc" ? "从高到低" : "从低到高"}` : "";
  const returnsView = response?.sort === "returns" && response.direction === "desc";
  const metricHelp = (metric: LedgerHelpKey) => response && <LedgerMetricHelp metric={metric} from={view.from} to={view.to} returnBasis={view.return_basis} factBasis={view.fact_basis} catalogVersion={response.provenance.catalog_version} />;
  const pageCount = response ? Math.max(1, Math.ceil(response.total_rows / response.page_size)) : 1;

  return <main className={css.workspace} id="main-content">
    <header className={css.heading}>
      <div><StatusBadge label="稳定款式分析" tone="quiet" /><h1>产品总表</h1>
        <p>按稳定款式比较销量、销售额、退货、会话与转化率。标准名称来自已批准商品主档。</p></div>
      {response && <dl className={css.provenance}><div><dt>身份来源</dt><dd>P0 商品主档</dd></div>
        <div><dt>目录版本</dt><dd>{response.provenance.catalog_version}</dd></div>
        <div><dt>事实口径</dt><dd>{response.provenance.fact_basis === "current" ? "当前事实" : "目录快照"}</dd></div>
        <div><dt>一致时间</dt><dd>{response.provenance.consistent_as_of}</dd></div>
        <div><dt>报告时区</dt><dd>{response.provenance.reporting_timezone}</dd></div></dl>}
    </header>

    <form aria-label="产品总表筛选" className={css.filters} onSubmit={onSubmit}>
      <FormField label="开始日期" required><Input max={today} onChange={(event) => onDraftChange({ from: event.target.value })} required type="date" value={draft.from} /></FormField>
      <FormField label="结束日期" required><Input min={draft.from} max={today} onChange={(event) => onDraftChange({ to: event.target.value })} required type="date" value={draft.to} /></FormField>
      <FormField label="主分类"><Select aria-label="筛选主分类" value={rootCategory ?? ""} onChange={(event) => onUpdate({ category_id: Number(event.target.value) || null })}><option value="">全部分类</option>{categories.filter((item) => !item.parent_category_id).map((item) => <option key={item.category_id} value={item.category_id}>{item.display_name}</option>)}</Select></FormField>
      {rootCategory && <FormField label="细分类"><Select aria-label="筛选细分类" value={selectedCategory?.parent_category_id ? (view.category_id ?? "") : ""} onChange={(event) => onUpdate({ category_id: Number(event.target.value) || rootCategory })}><option value="">全部细分类（含仅主分类商品）</option>{categories.filter((item) => item.parent_category_id === rootCategory).map((item) => <option key={item.category_id} value={item.category_id}>{item.display_name}</option>)}</Select></FormField>}
      <FormField className={css.search} label="款号或标准名称"><Input maxLength={100} onChange={(event) => onDraftChange({ search: event.target.value })} placeholder="输入款号或标准名称" value={draft.search} /></FormField>
      <FormField label="退货日期"><Select onChange={(event) => onUpdate({ return_basis: event.target.value as LedgerFilters["return_basis"] })} value={view.return_basis}><option value="event_date">事件日期</option><option value="report_date">报表日期</option></Select></FormField>
      <FormField label="事实版本"><Select onChange={(event) => onUpdate({ fact_basis: event.target.value as LedgerFilters["fact_basis"] })} value={view.fact_basis}><option value="current">当前事实</option><option value="catalog_snapshot">目录快照</option></Select></FormField>
      <Button variant="primary" type="submit">应用筛选</Button>
    </form>

    <p className={css.live} aria-live="polite">{loading ? response ? "正在更新排序，暂时显示上次结果。" : "正在读取产品总表，旧结果已隐藏。" : error ? error : response ? `已读取 ${response.total_rows} 个稳定款式。` : ""}</p>
    {loading && !response && <section aria-busy="true" aria-label="正在读取产品总表"><Skeleton lines={3} /></section>}
    {failure && <AnalyticsErrorState title="产品总表读取失败" failure={failure} onRetry={() => onRetry()} />}
    {failure?.setup && setupContent}


    {response && <>
      {response.coverage.business.published_days === 0 && response.coverage.returns.published_days === 0 && <EmptyState title="所选日期没有已发布报表" description="请调整日期或到每日数据查看已有报表；缺失数据不代表销量为零。" />}
      <section className={css.ledger} aria-labelledby="product-ledger-title">
        <div className={css.sectionHeading}><div><p className={css.count}>{response.total_rows.toLocaleString("zh-CN")} STYLES</p><h2 id="product-ledger-title">稳定款式</h2></div>
          <Checkbox checked={showNames} onChange={event => onShowNamesChange(event.target.checked)} label="显示商品名称" />
          <FormField label="每页"><Select onChange={(event) => onUpdate({ page_size: Number(event.target.value) })} value={view.page_size}><option value="25">25</option><option value="50">50</option><option value="100">100</option></Select></FormField></div>
        <div className={css.shortcuts} role="group" aria-label="经营快捷视图">
          <Button aria-pressed={response.sort === "sales" && response.direction === "desc"} onClick={() => onUpdate({ sort: "sales", direction: "desc" })}>销售贡献</Button>
          <Button aria-pressed={returnsView} onClick={() => onUpdate({ sort: "returns", direction: "desc" })}>退货关注</Button>
          <span className={css.sortStatus} aria-live="polite">当前排序：<strong>{sortDescription}</strong>{refreshing ? " · 正在更新…" : " · 点击表头切换顺序"}</span>
        </div>
        <p className={css.basis}>分类筛选以所选已批准目录的分类路径为准。 本期退货按{view.return_basis === "event_date" ? "事件日期" : "报表日期"}统计；可能来自此前订单。{returnsView && "同期退销比 = 本期退货量 ÷ 本期销量，不代表订单退货率。"} 平均单价 = 销售额 ÷ 销量。{response.coverage.business.missing_days > 0 && "销售报表有缺失，占比和单价仅反映已发布数据。"}</p>
        {response.rows.length === 0 ? <EmptyState title="没有匹配的稳定款式" description="调整日期或搜索条件；未归类来源不会伪造成款式。" /> :
          <div className={css.tableRegion} role="region" aria-label="产品总表，可横向滚动" tabIndex={0}><Table aria-label="稳定款式指标" aria-busy={refreshing} inert={refreshing} className={css.table}><thead><tr>
            <th aria-sort={response.sort === "style_code" ? response.direction === "asc" ? "ascending" : "descending" : "none"} scope="col"><div className={css.columnHeading}><Button variant="quiet" disabled={refreshing} onClick={() => onUpdate({ sort: "style_code", direction: view.sort === "style_code" && view.direction === "asc" ? "desc" : "asc" })} type="button" title="点击按款号排序，再次点击切换顺序">款号</Button>{metricHelp("identity")}</div></th>
            <th scope="col"><div className={css.columnHeading}>实际变体{metricHelp("variants")}</div></th>{metricColumns.map((column) => <th aria-sort={response.sort === column.key ? response.direction === "asc" ? "ascending" : "descending" : "none"} key={column.key} scope="col"><div className={css.columnHeading}><Button variant="quiet" disabled={refreshing} onClick={() => onUpdate({ sort: column.key, direction: view.sort === column.key && view.direction === "desc" ? "asc" : "desc" })} type="button" title={`点击按${column.label}排序，再次点击切换顺序`}>{column.label}</Button>{metricHelp(column.key)}</div></th>)}<th scope="col"><div className={css.columnHeading}>平均单价 US${metricHelp("average")}</div></th>
          </tr></thead><tbody>{response.rows.map((row) => <tr id={`style-${row.style_id}`} key={row.style_id}>
            <th scope="row"><ProductIdentityCell row={row} showName={showNames} ledgerUrl={`?${canonical}`} detailUrl={`/products/${encodeURIComponent(row.style_id)}?from=${view.from}&to=${view.to}&return_basis=${view.return_basis}&fact_basis=${view.fact_basis}${view.fact_basis === "catalog_snapshot" ? `&catalog_version=${encodeURIComponent(response.provenance.catalog_version_id)}` : ""}`} /></th>
            <td><strong>{row.sku_count}</strong><small>{row.color_count} 色 · {row.size_count} 码</small></td>
            {metricColumns.map((column) => <td key={column.key}><MetricValueView compact percentage kind={column.key} metric={row.metrics[column.key]} />
              {column.key === "sales" && <small>占比 {salesShare(row.metrics.sales, response.filtered_sales_total)}</small>}
              {column.key === "returns" && returnsView && <small>同期退销比 {returnSalesRatio(row.metrics.returns, row.metrics.units)}{(row.metrics.returns.is_partial || row.metrics.units.is_partial) && " · 部分数据"}</small>}</td>)}
            <td>{averagePrice(row.metrics.sales, row.metrics.units)}{(row.metrics.sales.is_partial || row.metrics.units.is_partial) && <small>部分数据</small>}</td>
          </tr>)}</tbody></Table></div>}
        <div className={css.pagination}><Pagination itemLabel="款式" loading={loading} onPageChange={(page) => onUpdate({ page })} page={response.page} totalItems={response.total_rows} totalPages={pageCount} /></div>
      </section>
      <div className={css.coverage}><CoverageReconciliation coverage={response.coverage} reconciliation={response.reconciliation} from={view.from} to={view.to} returnBasis={view.return_basis} /></div>
    </>}
  </main>;
}
