import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useRef, useState } from "react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { StatusMessage } from "../../design-system";
import { CatalogLayout } from "./CatalogLayout";
import { CatalogReadFailurePanel } from "./CatalogReadFailure";
import { CatalogVersionsView } from "./CatalogVersionsView";

type Scenario = "reference" | "empty" | "loading" | "first-version" | "unknown-risk" | "missing-fields" | "long-values" | "refresh-failure";
const records: Array<Record<string, unknown>> = [
  { id: 104, version_number: 4, risk: "normal", approved_at: "2026-09-30 14:20", base_catalog_version_id: 103 },
  { id: 103, version_number: 3, risk: "needs_review", approved_at: "2026-09-20 09:40", base_catalog_version_id: 101 },
  { id: 101, version_number: 1, risk: "normal", approved_at: "2026-09-02 16:10", base_catalog_version_id: null },
];
function VersionList({ scenario = "reference" }: { scenario?: Scenario }) {
  const values = scenario === "empty" ? [] : scenario === "first-version" ? records.slice(2) : scenario === "unknown-risk" ? [{ ...records[0], risk: "future_risk_code" }] : scenario === "missing-fields" ? [{ id: 105, version_number: 5 }] : scenario === "long-values" ? [{ id: "fictional-record-".repeat(6), version_number: "12345678901234567890", risk: "unknown_risk_".repeat(8), approved_at: "2026-09-30T14:20:00.123456+08:00", base_catalog_version_id: "fictional-base-".repeat(6) }] : records;
  const [loading, setLoading] = useState(scenario === "loading");
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const reload = () => {
    setAttempt(value => value + 1); setLoading(true); setFailed(false);
    timer.current = setTimeout(() => { setLoading(false); setFailed(scenario === "refresh-failure" && attempt === 0); timer.current = undefined; }, 350);
  };
  return <CatalogLayout canManage><Routes>
    <Route path="/catalog/versions" element={<div className="catalog-stack">
      {failed ? <CatalogReadFailurePanel failure={{ message: "无法读取目录版本，请检查连接后重试。", retry: true, setup: false }} onRetry={reload} /> : <CatalogVersionsView versions={loading ? undefined : values} onReload={reload} />}
      {attempt > 0 && !loading && !failed && <StatusMessage kind="info" title="读取已完成">第 {attempt} 次手动读取完成，显示同一组虚构批准记录。</StatusMessage>}
      <p>目录编号、风险和批准记录均为虚构数据。样板只模拟读取，不请求实际 API、不批准新版本；刷新页面重置。</p>
    </div>} />
    <Route path="*" element={<section><h2>初始化维护入口</h2><p>此处仅验证导航，不执行来源确认、快照或目录批准。</p><Link to="/catalog/versions">返回目录版本</Link></section>} />
  </Routes></CatalogLayout>;
}
function CatalogVersionStory(props: { scenario?: Scenario }) { return <MemoryRouter initialEntries={["/catalog/versions"]}><VersionList {...props} /></MemoryRouter>; }
const meta = { title: "Patterns/Catalog Versions", component: CatalogVersionStory, parameters: { layout: "fullscreen" } } satisfies Meta<typeof CatalogVersionStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const FirstVersion: Story = { args: { scenario: "first-version" } };
export const UnknownRisk: Story = { args: { scenario: "unknown-risk" } };
export const MissingFields: Story = { args: { scenario: "missing-fields" } };
export const LongValues: Story = { args: { scenario: "long-values" } };
export const RefreshFailure: Story = { args: { scenario: "refresh-failure" } };
