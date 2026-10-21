import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useRef, useState } from "react";
import { Link, MemoryRouter, Route, Routes, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import type { DailyLedgerRow } from "../../api/generated";
import { PublishedDailyView } from "./PublishedDailyView";

type Scenario = "reference" | "manager" | "filtered" | "filter-empty" | "no-records" | "loading" | "read-failure" | "zero-values";
function SampleDashboard({ scenario }: { scenario: Scenario }) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const month = params.get("month") ?? "2026-09";
  const status = params.get("status") ?? "all";
  const [loading, setLoading] = useState(scenario === "loading");
  const [error, setError] = useState<string | undefined>(scenario === "read-failure" ? "示例：本月发布总表暂时无法读取。请重新读取，不会修改发布版本。" : undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const base: DailyLedgerRow = { report_date: `${month}-10`, overall_status: "complete", business_status: "published", return_status: "published", counts_as_incomplete: false, pending_summary: null, reasons: [], sales: "18420.50", units_ordered: 246, sessions: 3150, conversion_rate: "0.0781", return_quantity: 5 };
  const all: DailyLedgerRow[] = scenario === "no-records" ? [] : scenario === "zero-values" ? [{ ...base, sales: "0", units_ordered: 0, sessions: 0, conversion_rate: "0", return_quantity: 0 }] : [
    { ...base, report_date: `${month}-12`, overall_status: "partial", return_status: "missing", return_quantity: null, counts_as_incomplete: true, pending_summary: "退货报告缺失" },
    { ...base, report_date: `${month}-11`, overall_status: "blocked", business_status: "blocked", return_status: "missing", sales: null, units_ordered: null, sessions: null, conversion_rate: null, return_quantity: null, counts_as_incomplete: true, pending_summary: "经营报告存在阻断项，请核对审核结果" },
    base,
    { ...base, report_date: `${month}-09`, overall_status: "review", business_status: "processing", sales: null, units_ordered: null, sessions: null, conversion_rate: null, counts_as_incomplete: true, pending_summary: "经营报告正在处理中" },
    { ...base, report_date: `${month}-08`, overall_status: "empty", business_status: "missing", return_status: "missing", sales: null, units_ordered: null, sessions: null, conversion_rate: null, return_quantity: null, pending_summary: null },
  ];
  const update = (updates: Record<string, string | undefined>) => { const next = new URLSearchParams(params); for (const [key, value] of Object.entries(updates)) { if (value === undefined) next.delete(key); else next.set(key, value); } setParams(next); };
  const displayed = loading || error ? [] : scenario === "filter-empty" ? all.filter(row => row.overall_status !== "blocked") : all;
  return <><PublishedDailyView month={month} range={{ from: `${month}-01`, to: `${month}-${new Date(Number(month.slice(0, 4)), Number(month.slice(5)), 0).getDate()}` }} currencyCode="USD" canWrite={scenario === "manager"} allowLegacyProducts={false}
    rows={displayed.filter(row => status === "all" || row.overall_status === status)} totalRows={displayed.length} completeCount={displayed.filter(row => row.overall_status === "complete").length} incompleteCount={displayed.filter(row => row.counts_as_incomplete).length}
    status={status} loading={loading} error={error} onMonthChange={value => update({ month: value })} onStatusChange={value => update({ status: value === "all" ? undefined : value })} onTabChange={() => undefined}
    onRetry={() => { setError(undefined); setLoading(true); timer.current = setTimeout(() => { setLoading(false); timer.current = undefined; }, 350); }}
    onReviewToday={() => { void navigate(`/review/${month}-12`); }} onOpenDay={destination => { void navigate(destination, { state: { returnTo: `/?${params}` } }); }} />
    <p>全部日期与金额为虚构样板数据，无需账号；筛选和月份保存在样板 URL，日期入口为虚构预览，不读取或写入实际 API。</p></>;
}
function Destination() {
  const location = useLocation();
  return <main><h1>虚构日期入口</h1><p>{location.pathname}</p><p>这里只核对日期路径，真实明细与审核仍由原页面提供。</p><Link to={(location.state as { returnTo?: string } | null)?.returnTo ?? "/?month=2026-09"}>返回发布总表</Link></main>;
}
function ReferencePage({ scenario = "reference" }: { scenario?: Scenario }) {
  const initial = `/?month=2026-09${scenario === "filtered" ? "&status=partial" : scenario === "filter-empty" ? "&status=blocked" : ""}`;
  return <MemoryRouter initialEntries={[initial]}><Routes><Route path="/" element={<SampleDashboard scenario={scenario} />} /><Route path="*" element={<Destination />} /></Routes></MemoryRouter>;
}
const meta = { title: "Pages/Published Daily Ledger", component: ReferencePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReferencePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Manager: Story = { args: { scenario: "manager" } };
export const Filtered: Story = { args: { scenario: "filtered" } };
export const FilterEmpty: Story = { args: { scenario: "filter-empty" } };
export const NoRecords: Story = { args: { scenario: "no-records" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const ZeroValues: Story = { args: { scenario: "zero-values" } };
