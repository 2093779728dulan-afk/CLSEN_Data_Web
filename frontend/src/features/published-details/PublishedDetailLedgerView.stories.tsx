import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useRef, useState } from "react";
import { Link, MemoryRouter, Route, Routes, useLocation, useSearchParams } from "react-router-dom";
import { PublishedDetailLedgerView } from "./PublishedDetailLedgerView";
import { PublishedDateSummaries, type PublishedDateExpansion } from "./PublishedDateSummaries";
import { ReadonlyPublishedDataGrid } from "./ReadonlyPublishedDataGrid";
import { parsePublishedDetailsSearch, serializePublishedDetailsSearch, updatePublishedDetailsViewState } from "./publishedDetailsState";
import type { PublishedDetailsViewState, PublishedRowsResponse, PublishedSummaryResponse } from "./publishedDetailsTypes";
import css from "./PublishedDetailLedgerView.module.css";

type Scenario = "column-settings" | "reference" | "all-rows" | "return-report" | "loading" | "read-failure" | "empty" | "expansion-failure" | "expansion-loading" | "scope-changed";
const dates = ["2026-09-12", "2026-09-11", "2026-09-10"];
function fictionalRows(reportType: PublishedDetailsViewState["reportType"], from: string, to: string): PublishedRowsResponse {
  const columns: PublishedRowsResponse["columns"] = [{ column_id: "8e4555a0-5397-4b36-b165-0af347ba05b9", source_header: "Seller SKU", display_order: 0, is_key: true, participates_in_statistics: false, standard_field_name: "seller_sku", value_kind: "text" }, { column_id: "9e4555a0-5397-4b36-b165-0af347ba05b9", source_header: reportType === "return_report" ? "退货数量" : "销售额", display_order: 1, is_key: false, participates_in_statistics: true, standard_field_name: reportType === "return_report" ? "return_quantity" : "sales", value_kind: "decimal" }];
  return { columns, range: { from_date: from, to_date: to }, scope_token: "fictional-published-scope", publications: [], permissions: { can_export: false }, pagination: { page: 1, page_size: 25, total_items: 2, total_pages: 1 }, rows: [1, 2].map((ordinal) => ({ report_date: to, version_id: 100 + Number(to.slice(-2)), version_no: 3, row_ordinal: ordinal, published_at: "2026-09-12T08:30:00Z", cells: [{ column_id: "8e4555a0-5397-4b36-b165-0af347ba05b9", value: ordinal === 1 ? "SAMPLE-BLUE-S" : "SAMPLE-WHITE-M" }, { column_id: "9e4555a0-5397-4b36-b165-0af347ba05b9", value: to === "2026-09-11" ? 0 : reportType === "return_report" ? ordinal === 1 ? 3 : 2 : ordinal === 1 ? "120.50" : "0.00" }] })) };
}
function SampleLedger({ scenario }: { scenario: Scenario }) {
  const [params, setParams] = useSearchParams();
  const view = parsePublishedDetailsSearch(params, "2026-09-12");
  const [dateDraft, setDateDraft] = useState({ from: view.from, to: view.to });
  const [dateError, setDateError] = useState<string>();
  const [searchDraft, setSearchDraft] = useState(view.search);
  const [loading, setLoading] = useState(scenario === "loading");
  const [error, setError] = useState(scenario === "read-failure");
  const [expansionError, setExpansionError] = useState(scenario === "expansion-failure");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  useEffect(() => { setDateDraft({ from: view.from, to: view.to }); setSearchDraft(view.search); }, [view.from, view.to, view.search]);
  const commit = (updates: Partial<PublishedDetailsViewState>) => setParams(serializePublishedDetailsSearch(updatePublishedDetailsViewState(view, updates)));
  const rows = fictionalRows(view.reportType, view.from, view.to);
  rows.rows = scenario === "empty" ? [] : rows.rows.filter(row => !view.search || row.cells.some(cell => String(cell.value).includes(view.search)) || row.report_date.includes(view.search));
  if (view.sortColumnId) {
    const column = rows.columns.find(item => item.column_id === view.sortColumnId);
    const value = (row: PublishedRowsResponse["rows"][number]) => row.cells.find(cell => cell.column_id === view.sortColumnId)?.value ?? "";
    rows.rows.sort((left, right) => {
      const comparison = column?.value_kind === "decimal" ? Number(value(left)) - Number(value(right)) : String(value(left)).localeCompare(String(value(right)));
      return view.direction === "desc" ? -comparison : comparison;
    });
  }
  rows.pagination.total_items = rows.rows.length;
  const summaries: PublishedSummaryResponse = { range: rows.range, scope_token: rows.scope_token, publications: [], permissions: rows.permissions, pagination: { page: 1, page_size: 25, total_items: 3, total_pages: 1 }, summaries: dates.filter(date => view.from <= date && date <= view.to && (scenario !== "empty") && (!view.search || date.includes(view.search) || "SAMPLE-BLUE-S".includes(view.search))).map(date => ({ report_date: date, publication: { dataset_id: Number(date.slice(-2)), site_id: 1, version_id: 100 + Number(date.slice(-2)), report_type: view.reportType, report_date: date, published_at: `${date}T08:30:00Z` }, published_at: `${date}T08:30:00Z`, version_id: 100 + Number(date.slice(-2)), version_no: 3, total_row_count: 2, matching_row_count: view.search ? 1 : 2, metric_scope: "full_day", sales: date === "2026-09-11" ? "0" : "120.50", sessions: date === "2026-09-11" ? 0 : 3100, units_ordered: date === "2026-09-11" ? 0 : 246, return_quantity: date === "2026-09-11" ? 0 : 5 })) };
  summaries.pagination.total_items = summaries.summaries.length;
  const retry = () => { setError(false); setLoading(true); timer.current = setTimeout(() => { setLoading(false); timer.current = undefined; }, 350); };
  const expansion: PublishedDateExpansion | undefined = view.expandedDate ? scenario === "expansion-loading" ? { date: view.expandedDate, status: "loading" } : expansionError ? { date: view.expandedDate, status: "error", message: "虚构：当日明细读取失败，日期摘要仍可查看。" } : { date: view.expandedDate, status: "ready", response: { ...fictionalRows(view.reportType, view.from, view.expandedDate), range: rows.range } } : undefined;
  const query = { from: view.from, to: view.to, reportType: view.reportType, search: view.search || undefined };
  const grid = (response = rows, pagination = true) => <ReadonlyPublishedDataGrid siteId="storybook" userId="fictional-viewer" response={loading || error ? undefined : response} exportQuery={query} loading={loading} error={error ? "虚构：读取失败，请重新读取。" : undefined} onRetry={retry} sort={view.sortColumnId ? { columnId: view.sortColumnId, direction: view.direction } : null} onSort={command => commit({ sortColumnId: command.direction ? command.columnId : undefined, direction: command.direction ?? "asc" })} onPageChange={page => commit({ page })} pagination={pagination} />;
  return <><PublishedDetailLedgerView siteId={1} displayName="虚构查看人员" reportingTimezone="Asia/Shanghai" range={rows.range} reportType={view.reportType} mode={view.mode} dateDraft={dateDraft} dateError={dateError} onDateDraft={setDateDraft} onApplyDates={event => { event.preventDefault(); if (!dateDraft.from || !dateDraft.to || dateDraft.from > dateDraft.to) { setDateError("开始日期不能晚于结束日期。"); return; } setDateError(undefined); commit(dateDraft); }} searchDraft={searchDraft} onSearchDraft={setSearchDraft} onSearch={event => { event.preventDefault(); commit({ search: searchDraft }); }} resolvingRange={false} stagedReason={view.mode === "summary" && !view.expandedDate ? "当前账号无导出权限；列设置将在全部明细列结构加载后可用。" : undefined} count={loading || error ? undefined : view.mode === "rows" ? rows.pagination.total_items : summaries.summaries.length} conflictNotice={scenario === "scope-changed" ? "发布数据已更新，正在重新读取" : undefined} onReportType={reportType => commit({ reportType, expandedDate: undefined })} onMode={mode => commit({ mode, expandedDate: undefined })} onQuickRange={value => commit({ from: value === 7 ? "2026-09-06" : value === 30 ? "2026-08-14" : "2026-09-01", to: "2026-09-12", expandedDate: undefined })}>
    {view.mode === "rows" ? grid() : <PublishedDateSummaries reportType={view.reportType} reportingTimezone="Asia/Shanghai" response={loading || error ? undefined : summaries} loading={loading} error={error ? "虚构：当前范围暂时无法读取。" : undefined} onRetry={retry} expandedDate={view.expandedDate} expansion={expansion} onToggleExpanded={date => setParams(serializePublishedDetailsSearch({ ...view, expandedDate: view.expandedDate === date ? undefined : date }))} onRetryExpansion={() => setExpansionError(false)} onPageChange={page => commit({ page })} renderExpandedRows={response => grid(response, false)} />}
  </PublishedDetailLedgerView><p>虚构报告与原始字段样板；筛选仅作用于样板，列设置沿用真实组件，不请求实际 API。</p></>;
}
function Destination() { const location = useLocation(); return <main className={css.destination}><h1>虚构导航目的地</h1><p>{location.pathname}{location.search}</p><Link to="/ledger/published-details?from=2026-09-01&to=2026-09-12">返回明细样板</Link></main>; }
function ReferencePage({ scenario = "reference" }: { scenario?: Scenario }) {
  const entry = `/ledger/published-details?from=2026-09-01&to=2026-09-12${(scenario === "all-rows" || scenario === "column-settings") ? "&mode=rows" : ""}${scenario === "return-report" ? "&report_type=return_report" : ""}${scenario.startsWith("expansion-") ? "&report_date=2026-09-12" : ""}`;
  return <MemoryRouter initialEntries={[entry]}><Routes><Route path="/ledger/published-details" element={<SampleLedger scenario={scenario} />} /><Route path="*" element={<Destination />} /></Routes></MemoryRouter>;
}
const meta = { title: "Pages/Published Detail Ledger", component: ReferencePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReferencePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const AllRows: Story = { args: { scenario: "all-rows" } };
export const ReturnReport: Story = { args: { scenario: "return-report" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const ExpansionFailure: Story = { args: { scenario: "expansion-failure" } };
export const ExpansionLoading: Story = { args: { scenario: "expansion-loading" } };
export const ScopeChanged: Story = { args: { scenario: "scope-changed" } };

export const ColumnSettings: Story = { args: { scenario: "column-settings" } };
