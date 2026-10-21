import styles from "./PublishedDashboard.module.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { CircleCheck } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { requestApi } from "../../api/client";
import type {
  DailyLedgerResponse,
  DailyLedgerRow,
  ProductLedgerResponse,
  ProductLedgerRow,
  ProductLedgerSort,
  SortDirection,
} from "../../api/generated";
import type { Principal } from "../../api/types";
import { Button, EmptyState, ErrorState, FormField, Input, Pagination, Select, StatusBadge, type StatusTone } from "../../design-system";
import type { ProductAnalyticsSource } from "../products/productAnalyticsSource";
import { ProductInfoDialog } from "./ProductInfoDialog";


type Tab = "daily" | "products";

export interface PublishedDashboardProps {
  currencyCode?: string;
  initialMonth?: string;
  principal?: Principal;
  productAnalyticsSource?: ProductAnalyticsSource;
}

const DEFAULT_PRINCIPAL: Principal = {
  display_name: "查看人员",
  id: 0,
  roles: ["viewer"],
  username: "viewer",
};

const STATUS_LABEL: Record<DailyLedgerRow["overall_status"], string> = {
  blocked: "阻断",
  complete: "完整发布",
  empty: "无数据",
  future: "未来日期",
  partial: "部分发布",
  review: "审核中",
};

const STATUS_TONE: Record<DailyLedgerRow["overall_status"], StatusTone> = {
  blocked: "bad",
  complete: "good",
  empty: "quiet",
  future: "quiet",
  partial: "warn",
  review: "warn",
};

const REPORT_STATUS_LABEL: Record<DailyLedgerRow["business_status"], string> = {
  blocked: "阻断",
  draft: "草稿",
  failed: "失败",
  future: "未来",
  missing: "缺失",
  processing: "处理中",
  published: "已发布",
};

const PRODUCT_COLUMNS: Array<{ key: ProductLedgerSort; label: string }> = [
  { key: "sales", label: "销售额" },
  { key: "units_ordered", label: "订购数" },
  { key: "sessions", label: "会话数" },
  { key: "conversion_rate", label: "转化率" },
  { key: "return_quantity", label: "退货数" },
  { key: "published_days", label: "数据天数" },
  { key: "latest_published_date", label: "最近发布日" },
];

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function validMonth(value: string | null | undefined) {
  return value && /^\d{4}-(0[1-9]|1[0-2])$/.test(value) ? value : currentMonth();
}

function monthRange(month: string) {
  const [year = 2000, monthNumber = 1] = month.split("-").map(Number);
  const lastDay = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  return { from: `${month}-01`, to: `${month}-${String(lastDay).padStart(2, "0")}` };
}

function money(value: string | null, code: string) {
  if (value === null) return "—";
  return new Intl.NumberFormat("zh-CN", {
    currency: code,
    maximumFractionDigits: 2,
    style: "currency",
  }).format(Number(value));
}

function integer(value: number | null) {
  return value === null ? "—" : value.toLocaleString("zh-CN");
}

function percent(value: string | null) {
  return value === null ? "—" : `${(Number(value) * 100).toFixed(2)}%`;
}

function activateRow(event: React.KeyboardEvent, action: () => void) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    action();
  }
}

function Status({ status }: { status: DailyLedgerRow["overall_status"] }) {
  return <StatusBadge label={STATUS_LABEL[status]} tone={STATUS_TONE[status]} />;
}

export function PublishedDashboard({ currencyCode = "USD", initialMonth, principal = DEFAULT_PRINCIPAL, productAnalyticsSource = "legacy_parser" }: PublishedDashboardProps) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const month = validMonth(params.get("month") ?? initialMonth);
  const tab: Tab = productAnalyticsSource === "legacy_parser" && params.get("tab") === "products" ? "products" : "daily";
  const status = params.get("status") ?? "all";
  const search = params.get("search") ?? "";
  const sort = (params.get("sort") ?? "sales") as ProductLedgerSort;
  const direction: SortDirection = params.get("direction") === "asc" ? "asc" : "desc";
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const range = useMemo(() => monthRange(month), [month]);
  const [daily, setDaily] = useState<DailyLedgerResponse>();
  const [products, setProducts] = useState<ProductLedgerResponse>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [reload, setReload] = useState(0);
  const [selectedStyle, setSelectedStyle] = useState<string>();
  const openerRef = useRef<HTMLElement | null>(null);
  const canWrite = principal.roles.includes("admin") || principal.roles.includes("data_manager");

  const updateParams = (updates: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(updates)) {
      if (!value) next.delete(key);
      else next.set(key, value);
    }
    setParams(next);
  };

  useEffect(() => {
    if (params.get("month") === month) return;
    const next = new URLSearchParams(params);
    next.set("month", month);
    setParams(next, { replace: true });
  }, [month, params, setParams]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    setDaily(undefined);
    setProducts(undefined);
    const query = new URLSearchParams({ from: range.from, to: range.to });
    const request = tab === "daily"
      ? requestApi<DailyLedgerResponse>(`/api/dashboard/daily-ledger?${query}`, { signal: controller.signal }).then((value) => { if (!controller.signal.aborted) setDaily(value); })
      : (() => {
          query.set("search", search);
          query.set("sort", sort);
          query.set("direction", direction);
          query.set("page", String(page));
          query.set("page_size", "25");
          return requestApi<ProductLedgerResponse>(`/api/dashboard/product-ledger?${query}`, { signal: controller.signal }).then((value) => { if (!controller.signal.aborted) setProducts(value); });
        })();
    void request
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "无法读取总表。");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [direction, page, range.from, range.to, reload, search, sort, tab]);

  const dailyRows = (daily?.rows ?? [])
    .filter((row) => status === "all" || row.overall_status === status)
    .slice()
    .sort((left, right) => right.report_date.localeCompare(left.report_date));
  const incompleteCount = daily?.rows?.filter((row) => row.counts_as_incomplete).length ?? 0;

  const openProduct = (row: ProductLedgerRow, target: HTMLElement) => {
    if (row.row_kind !== "product" || !row.style_code) return;
    openerRef.current = target;
    setSelectedStyle(row.style_code);
  };
  const closeProduct = () => {
    setSelectedStyle(undefined);
    window.setTimeout(() => openerRef.current?.focus(), 0);
  };

  return <main className={styles["ledger-home"]} id="main-content">
    <header className={styles["ledger-home__header"]}>
      <div>
        <div className={styles["ledger-kicker"]}><span>当前发布口径</span><time dateTime={month}>{month}</time><StatusBadge label={canWrite ? "数据管理视图" : "只读发布视图"} tone="quiet" /></div>
        <h1>发布数据总表</h1>
        <p>按月核对日期完整度与商品表现；表内经营值仅来自当前发布版本。</p>
      </div>
      <div className={styles["ledger-home__header-actions"]}>
        <FormField className={styles["ledger-month-filter"]} label="查看月份"><Input aria-label="统计月份" onChange={(event) => updateParams({ month: event.target.value, page: undefined })} type="month" value={month} /></FormField>
        {canWrite && <Button variant="primary" onClick={() => { void navigate(`/review/${new Date().toISOString().slice(0, 10)}`); }} type="button">进入今日审核</Button>}
      </div>
    </header>

    <section className={styles["ledger-toolbar"]} aria-label="总表工具栏">
      <div className={styles["ledger-destinations"]}>
        <div className={styles["ledger-tabs"]} role="tablist">
          <button aria-selected={tab === "daily"} onClick={() => updateParams({ tab: "daily", page: undefined })} role="tab" type="button">每日总表</button>
          {productAnalyticsSource === "legacy_parser" && <button aria-selected={tab === "products"} onClick={() => updateParams({ tab: "products", page: undefined })} role="tab" type="button">产品总表</button>}
        </div>
        <Link className={styles["ledger-details-link"]} to={`/ledger/published-details?from=${range.from}&to=${range.to}`}>发布明细</Link>
      </div>
      {tab === "daily" ? <div className={styles["ledger-filter-row"]}>
        <FormField className={styles["ledger-status-filter"]} label="状态"><Select aria-label="日期状态" onChange={(event) => updateParams({ status: event.target.value === "all" ? undefined : event.target.value })} value={status}>
          <option value="all">全部日期</option><option value="complete">完整发布</option><option value="partial">部分发布</option><option value="review">审核中</option><option value="blocked">阻断</option><option value="empty">无数据</option>
        </Select></FormField>
        <span aria-live="polite"><StatusBadge label={loading ? "正在核对本月数据" : error ? "本月完整度暂不可用" : incompleteCount === 0 ? "本月无需补齐" : `${incompleteCount} 个日期待补齐`} tone={loading || error ? "quiet" : incompleteCount === 0 ? "good" : "warn"} /></span>
      </div> : <FormField className={styles["ledger-search"]} label="搜索产品"><Input onChange={(event) => updateParams({ search: event.target.value || undefined, page: undefined })} placeholder="款号、Seller SKU、ASIN、FNSKU 或名称" type="search" value={search} /></FormField>}
    </section>

    {error && <ErrorState title="总表读取失败" description={error} action={<Button onClick={() => setReload((value) => value + 1)}>重新读取</Button>} />}

    <section className={styles["ledger-sheet"]} aria-busy={loading} aria-label={tab === "daily" ? "每日发布总表" : "产品发布总表"}>
      {tab === "daily" ? <div aria-label="发布数据表，可横向滚动" className={styles["ledger-table-scroll"]} role="region" tabIndex={0}><table className={styles["ledger-table"] + " " + styles["ledger-table--daily"]}>
        <thead><tr><th>报告日</th><th>状态</th><th>经营报告</th><th>退货报告</th><th>销售额</th><th>订购数</th><th>会话数</th><th>转化率</th><th>退货数</th><th>待办</th></tr></thead>
        <tbody>{loading ? Array.from({ length: 8 }, (_, index) => <tr className={styles["ledger-skeleton"]} key={index}><td colSpan={10}><span /></td></tr>) : dailyRows.map((row) => {
          const destination = canWrite ? `/review/${row.report_date}` : `/published/${row.report_date}`;
          return <tr key={row.report_date} onClick={() => { void navigate(destination); }} onKeyDown={(event) => activateRow(event, () => { void navigate(destination); })} tabIndex={0}>
            <th data-label="报告日" scope="row"><time dateTime={row.report_date}>{row.report_date}</time></th>
            <td data-label="状态"><Status status={row.overall_status} /></td>
            <td className={styles["ledger-report-state"]} data-label="经营报告">{REPORT_STATUS_LABEL[row.business_status]}</td><td className={styles["ledger-report-state"]} data-label="退货报告">{REPORT_STATUS_LABEL[row.return_status]}</td>
            <td data-label="销售额">{money(row.sales, currencyCode)}</td><td data-label="订购数">{integer(row.units_ordered)}</td><td data-label="会话数">{integer(row.sessions)}</td><td data-label="转化率">{percent(row.conversion_rate)}</td><td data-label="退货数">{integer(row.return_quantity)}</td><td className="ledger-todo-cell" data-label="待办">{row.pending_summary ? <span className={styles["ledger-todo"] + " " + styles["ledger-todo--action"]}>{row.pending_summary}</span> : <span className={styles["ledger-todo"] + " " + styles["ledger-todo--clear"]}><CircleCheck aria-hidden="true" />无需处理</span>}</td>
          </tr>;
        })}</tbody>
      </table>{!loading && !error && !dailyRows.length && <EmptyState title="这个月份没有符合条件的日期记录" description="未来日期和完全无活动的日期不会计入待补齐。" />}</div> : <><div aria-label="发布数据表，可横向滚动" className={styles["ledger-table-scroll"]} role="region" tabIndex={0}><table className={styles["ledger-table"] + " " + styles["ledger-table--products"]}>
        <thead><tr><th>商品款号</th><th>商品名称</th><th>变体</th><th>颜色</th><th>尺寸</th>{PRODUCT_COLUMNS.map((column) => <th aria-sort={sort === column.key ? (direction === "asc" ? "ascending" : "descending") : "none"} key={column.key}><button onClick={() => updateParams({ sort: column.key, direction: sort === column.key && direction === "desc" ? "asc" : "desc", page: undefined })} type="button">{column.label}</button></th>)}</tr></thead>
        <tbody>{loading ? Array.from({ length: 8 }, (_, index) => <tr className={styles["ledger-skeleton"]} key={index}><td colSpan={12}><span /></td></tr>) : products?.rows.map((row) => {
          const clickable = row.row_kind === "product";
          return <tr aria-label={clickable ? `打开款号 ${row.style_code} 商品信息` : "未归类 Seller SKU"} className={clickable ? styles["ledger-product-row"] : styles["ledger-product-row"] + " " + styles["ledger-product-row--unclassified"]} key={`${row.row_kind}:${row.style_code ?? row.unclassified_sku ?? "missing"}`} onClick={(event) => { if (clickable) openProduct(row, event.currentTarget); }} onKeyDown={(event) => activateRow(event, () => { if (clickable) openProduct(row, event.currentTarget); })} tabIndex={clickable ? 0 : undefined}>
            <th data-label="商品款号" scope="row">{row.style_code ?? <span>未归类 · {row.unclassified_sku ?? "缺少 SKU"}</span>}</th><td data-label="商品名称">{row.name_status === "multiple" ? "多个变体名称" : row.product_name ?? "未维护"}</td><td data-label="变体">{row.variant_count}</td><td data-label="颜色">{row.color_count}</td><td data-label="尺寸">{row.size_count}</td><td data-label="销售额">{money(row.sales, currencyCode)}</td><td data-label="订购数">{integer(row.units_ordered)}</td><td data-label="会话数">{integer(row.sessions)}</td><td data-label="转化率">{percent(row.conversion_rate)}</td><td data-label="退货数">{integer(row.return_quantity)}</td><td data-label="数据天数">{row.published_days}</td><td data-label="最近发布日">{row.latest_published_date ?? "—"}</td>
          </tr>;
        })}</tbody>
      </table>{!loading && !error && products && !products.rows.length && <EmptyState title="没有找到商品" description="可按款号、变体标识或商品名称搜索。" />}</div>
      {products && products.total_rows > products.page_size && <footer className={styles["ledger-pagination"]}><Pagination itemLabel="商品" loading={loading} onPageChange={(nextPage) => updateParams({ page: String(nextPage) })} page={products.page} totalItems={products.total_rows} totalPages={Math.ceil(products.total_rows / products.page_size)} /></footer>}</>}
    </section>

    {productAnalyticsSource === "legacy_parser" && selectedStyle && <ProductInfoDialog currencyCode={currencyCode} from={range.from} onClose={closeProduct} styleCode={selectedStyle} to={range.to} />}
  </main>;
}

export default PublishedDashboard;
