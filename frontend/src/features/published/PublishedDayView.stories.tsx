import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useRef, useState } from "react";
import { Link, MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import type { DailyLedgerRow } from "../../api/generated";
import { PublishedDayView } from "./PublishedDayView";
import { PublishedMonthTrend } from "./PublishedMonthTrend";

type Scenario = "reference" | "partial" | "zero-values" | "loading" | "read-failure" | "empty" | "single-day" | "embedded";
function SampleDay({ scenario }: { scenario: Scenario }) {
  const { reportDate = "2026-09-12" } = useParams();
  const [loading, setLoading] = useState(scenario === "loading");
  const [error, setError] = useState<string | undefined>(scenario === "read-failure" ? "示例：当前发布数据读取失败，请重新读取；不会修改发布指针。" : undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const base: DailyLedgerRow = { report_date: reportDate, sales: "18420.50", units_ordered: 246, sessions: 3150, conversion_rate: "0.0781", return_quantity: 5, overall_status: "complete", business_status: "published", return_status: "published", counts_as_incomplete: false, pending_summary: null, reasons: [] };
  const row = scenario === "empty" ? undefined : scenario === "partial" ? { ...base, overall_status: "partial" as const, return_status: "missing" as const, return_quantity: null, counts_as_incomplete: true, pending_summary: "退货报告缺失" } : scenario === "zero-values" ? { ...base, sales: "0", units_ordered: 0, sessions: 0, conversion_rate: "0", return_quantity: 0 } : base;
  const rows: DailyLedgerRow[] = scenario === "empty" ? [] : scenario === "single-day" ? [base] : [
    { ...base, report_date: "2026-09-01", sales: "14520.10", units_ordered: 182, sessions: 2640 },
    { ...base, report_date: "2026-09-02", sales: "17290.00", units_ordered: 226, sessions: 2890 },
    { ...base, report_date: "2026-09-04", sales: "16630.50", units_ordered: 210, sessions: 2510 },
    { ...base, report_date: "2026-09-05", sales: "18030.45", units_ordered: 232, sessions: 2850 },
    ...(row ? [row] : []),
  ];
  const standalone = scenario !== "embedded";
  return <><PublishedDayView currencyCode="USD" reportDate={reportDate} standalone={standalone} returnTo="/ledger/published-details?from=2026-09-01&to=2026-09-30&mode=rows" row={loading || error ? undefined : row} loading={loading} error={error}
    onRetry={() => { setError(undefined); setLoading(true); timer.current = setTimeout(() => { setLoading(false); timer.current = undefined; }, 350); }}>
    {!loading && !error && standalone && <PublishedMonthTrend rows={rows} reportDate={reportDate} currencyCode="USD" />}
  </PublishedDayView><p>日期、金额与报告状态均为虚构样板；沿用现有月内趋势组件与精确计算，无需账号，不请求实际 API。</p><Link to="/published-details/2026-09-11">查看另一日期样板</Link></>;
}
function Destination() { const location = useLocation(); return <main><h1>虚构导航目的地</h1><p>{location.pathname}{location.search}</p><Link to="/published-details/2026-09-12">返回日期样板</Link></main>; }
function ReferencePage({ scenario = "reference" }: { scenario?: Scenario }) {
  return <MemoryRouter initialEntries={['/published-details/2026-09-12']}><Routes><Route path="/published-details/:reportDate" element={<SampleDay key={scenario} scenario={scenario} />} /><Route path="*" element={<Destination />} /></Routes></MemoryRouter>;
}
const meta = { title: "Pages/Published Day Detail", component: ReferencePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReferencePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Partial: Story = { args: { scenario: "partial" } };
export const ZeroValues: Story = { args: { scenario: "zero-values" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const SingleDay: Story = { args: { scenario: "single-day" } };
export const Embedded: Story = { args: { scenario: "embedded" } };
