import { Button, EmptyState, ErrorState, LinkButton, Pagination, Skeleton, StatusBadge } from "../../design-system";
import styles from "./PublishedDateSummaries.module.css";
import { Fragment, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

import type { ReportType } from "../../api/generated";
import type { PublishedRowsResponse, PublishedSummaryResponse } from "./publishedDetailsTypes";

export type PublishedDateExpansion =
  | { date: string; status: "loading" }
  | { date: string; message: string; status: "error" }
  | { date: string; response: PublishedRowsResponse; status: "ready" };

export type PublishedDateSummariesProps = {
  emptyMessage?: string;
  error?: string;
  expandedDate?: string;
  expansion?: PublishedDateExpansion;
  loading: boolean;
  onPageChange: (page: number) => void;
  onRetry: () => void;
  onRetryExpansion: (reportDate: string) => void;
  onToggleExpanded: (reportDate: string) => void;
  reportType: ReportType;
  reportingTimezone: string;
  renderExpandedRows?: (response: PublishedRowsResponse) => ReactNode;
  response?: PublishedSummaryResponse;
};

function integer(value: number | null): string {
  return value === null ? "—" : value.toLocaleString("zh-CN");
}

function decimal(value: string | null): string {
  if (value === null) return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(parsed)
    : value;
}

function publicationTime(value: string, reportingTimezone: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      day: "2-digit",
      hour: "2-digit",
      hour12: false,
      minute: "2-digit",
      month: "2-digit",
      timeZone: reportingTimezone,
      year: "numeric",
    }).format(date);
  } catch {
    return value;
  }
}

function displayCell(value: string | number | null): string {
  if (value === null || value === "") return "—";
  return String(value);
}

function ExpansionRegion({
  expansion,
  onRetry,
  reportDate,
  renderExpandedRows,
}: {
  expansion?: PublishedDateExpansion;
  onRetry: (reportDate: string) => void;
  reportDate: string;
  renderExpandedRows?: (response: PublishedRowsResponse) => ReactNode;
}) {
  const active = expansion?.date === reportDate ? expansion : undefined;
  return <div aria-label={`${reportDate} 展开明细`} className={styles["published-summaries__expansion"]} role="region">
    {!active || active.status === "loading" ? <p aria-live="polite" className={styles["published-summaries__expansion-state"]} role="status">
      正在读取 {reportDate} 的匹配明细…
    </p> : active.status === "error" ? <div className={styles["published-summaries__expansion-error"]} role="alert">
      <p>{active.message}</p>
      <Button onClick={() => onRetry(reportDate)} type="button">重试 {reportDate} 展开明细</Button>
    </div> : renderExpandedRows ? renderExpandedRows(active.response) : active.response.rows.length === 0 ? <p className={styles["published-summaries__expansion-state"]}>
      这个日期没有匹配当前搜索的明细行。
    </p> : <ExpandedRows response={active.response} />}
  </div>;
}

function ExpandedRows({ response }: { response: PublishedRowsResponse }) {
  const columns = response.columns.slice().sort((left, right) => left.display_order - right.display_order);
  return <div aria-label="展开明细只读表" className={styles["published-summaries__expanded-scroll"]} role="region" tabIndex={0}>
    <table className={styles["published-summaries__expanded-table"]}>
      <thead>
        <tr><th>行</th><th>发布版本</th>{columns.map((column) => <th key={column.column_id}>{column.source_header}</th>)}</tr>
      </thead>
      <tbody>{response.rows.map((row) => {
        const cells = new Map(row.cells.map((cell) => [cell.column_id, cell.value]));
        return <tr key={`${row.report_date}:${row.version_id}:${row.row_ordinal}`}>
          <th scope="row">{row.row_ordinal}</th>
          <td>v{row.version_no}</td>
          {columns.map((column) => <td key={column.column_id}>{displayCell(cells.get(column.column_id) ?? null)}</td>)}
        </tr>;
      })}</tbody>
    </table>
  </div>;
}

function SummaryMetrics({
  reportType,
  summary,
}: {
  reportType: ReportType;
  summary: PublishedSummaryResponse["summaries"][number];
}) {
  if (reportType === "return_report") {
    return <div className={styles["published-summaries__metrics"]}>
      <span>退货数量 · 全日 {integer(summary.return_quantity)}</span>
    </div>;
  }
  return <div className={styles["published-summaries__metrics"]}>
    <span>销售额 · 全日 {decimal(summary.sales)}</span>
    <span>订购数 · 全日 {integer(summary.units_ordered)}</span>
    <span>会话数 · 全日 {integer(summary.sessions)}</span>
  </div>;
}

export function PublishedDateSummaries({
  emptyMessage = "所选范围内没有当前已发布明细。",
  error,
  expandedDate,
  expansion,
  loading,
  onPageChange,
  onRetry,
  onRetryExpansion,
  onToggleExpanded,
  reportType,
  reportingTimezone,
  renderExpandedRows,
  response,
}: PublishedDateSummariesProps) {
  const location = useLocation();
  const returnTo = encodeURIComponent(location.pathname + location.search);
  const summaries = response?.summaries.slice().sort((left, right) => right.report_date.localeCompare(left.report_date)) ?? [];
  const pagination = response?.pagination;

  return <section aria-busy={loading} aria-label="已发布日期摘要" className={styles["published-summaries"]}>
    <div className={styles["published-summaries__scroll"]} role="region" tabIndex={0} aria-label="发布日期与全日指标">
      <table aria-label="已发布日期摘要表">
        <thead><tr>
          <th>报告日</th>
          <th>当前发布</th>
          <th>匹配 / 总行数</th>
          <th>全日指标</th>
          <th>读取操作</th>
        </tr></thead>
        <tbody>
          {loading && !response ? Array.from({ length: 5 }, (_, index) => <tr className={styles["published-summaries__skeleton"]} key={index}>
            <td colSpan={5}><Skeleton lines={1} height={32} />{index === 0 && <span className={styles["sr-only"]} aria-label="正在读取日期摘要" role="status">正在读取日期摘要</span>}</td>
          </tr>) : error ? <tr><td colSpan={5}>
            <ErrorState title="日期摘要读取失败" description={error} action={<Button onClick={onRetry}>重新读取日期摘要</Button>} />
          </td></tr> : summaries.length === 0 ? <tr><td colSpan={5}>
            <EmptyState title={emptyMessage} />
          </td></tr> : summaries.map((summary) => {
            const expanded = expandedDate === summary.report_date;
            return <Fragment key={summary.report_date}>
              <tr className={expanded ? styles["published-summaries__row"] + " " + styles["is-expanded"] : styles["published-summaries__row"]}>
                <th scope="row"><time dateTime={summary.report_date}>{summary.report_date}</time></th>
                <td data-label="当前发布"><StatusBadge label={`当前发布 v${summary.version_no}`} tone="good" /><small>{publicationTime(summary.published_at, reportingTimezone)}</small></td>
                <td data-label="匹配 / 总行数"><strong>{summary.matching_row_count.toLocaleString("zh-CN")} / {summary.total_row_count.toLocaleString("zh-CN")} 行</strong><small>搜索匹配 / 该日全部</small></td>
                <td data-label="全日指标"><SummaryMetrics reportType={reportType} summary={summary} /></td>
                <td><div className={styles["published-summaries__actions"]}>
                  <Button
                    aria-expanded={expanded}
                    aria-controls={`published-expansion-${summary.report_date}`}
                    onClick={() => onToggleExpanded(summary.report_date)}
                    type="button"
                  >{expanded ? `收起 ${summary.report_date} 明细` : `展开 ${summary.report_date} 明细`}</Button>
                  <LinkButton variant="quiet" aria-label={`查看 ${summary.report_date} 单日摘要`} to={`/published-details/${summary.report_date}?return_to=${returnTo}`}>查看单日摘要</LinkButton>
                  <LinkButton variant="quiet" aria-label={`打开 ${summary.report_date} 日期工作台`} to={`/published/${summary.report_date}?report_type=${reportType}`}>打开日期工作台</LinkButton>
                  <LinkButton variant="quiet" aria-label={`查看 ${summary.report_date} 版本记录`} to={`/versions?report_date=${summary.report_date}&report_type=${reportType}`}>查看版本记录</LinkButton>
                </div></td>
              </tr>
              {expanded && <tr className={styles["published-summaries__expanded-row"]}>
                <td colSpan={5} id={`published-expansion-${summary.report_date}`}>
                  <ExpansionRegion expansion={expansion} onRetry={onRetryExpansion} reportDate={summary.report_date} renderExpandedRows={renderExpandedRows} />
                </td>
              </tr>}
            </Fragment>;
          })}
        </tbody>
      </table>
    </div>
    {pagination && pagination.total_pages > 1 && <footer className={styles["published-summaries__pagination"]}><Pagination itemLabel="发布日期" loading={loading} onPageChange={onPageChange} page={pagination.page} totalItems={pagination.total_items} totalPages={pagination.total_pages} /></footer>}
  </section>;
}

export default PublishedDateSummaries;
