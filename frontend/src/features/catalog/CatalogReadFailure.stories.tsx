import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useRef, useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { ApiRequestError } from "../../api/client";
import type { AnalyticsReadiness, CatalogScopeStatusResponse } from "../../api/generated";
import { StatusMessage } from "../../design-system";
import { CatalogLayout } from "./CatalogLayout";
import { CatalogReadFailurePanel } from "./CatalogReadFailure";
import { CatalogSetupView } from "./CatalogSetupView";
import { CatalogVersionsView } from "./CatalogVersionsView";
import { catalogReadError } from "./catalogReadError";

type Scenario = "reference" | "repeat-failure" | "rate-limited" | "forbidden" | "not-found" | "invalid-query" | "setup" | "long-message";
const readiness: AnalyticsReadiness = { catalog_approved: false, coverage_from: "2026-07-01", coverage_to: "2026-08-06", prerequisites_present: false, published_business_reports: 37, published_reports: 74, published_return_reports: 37, return_snapshot_present: false, source_scope_confirmed: false };
const scope: CatalogScopeStatusResponse = { marketplace_scope_code: "amazon_us", permissions: { can_confirm: false }, report_source_scope_id: null, seller_account_display_name: null, site_config_revision: 3, site_config_version_id: 2, status: "unconfirmed" };

function ReadFeedback({ scenario = "reference" }: { scenario?: Scenario }) {
  const [loading, setLoading] = useState(false);
  const [recovered, setRecovered] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [refreshed, setRefreshed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const status = scenario === "forbidden" ? 403 : scenario === "not-found" ? 404 : scenario === "invalid-query" ? 422 : scenario === "rate-limited" ? 429 : scenario === "setup" ? 409 : 503;
  const failure = catalogReadError(new ApiRequestError(status, scenario === "setup" ? "catalog_snapshot_unavailable" : "demo_read_failure", "虚构读取失败"), scenario === "rate-limited" ? "请求过于频繁，请稍后手动重新读取。" : scenario === "long-message" ? "无法读取目录版本，请检查连接后重试。".repeat(12) : "无法读取目录版本，请检查连接后重试。");
  const retry = () => { setAttempt(value => value + 1); setLoading(true); timer.current = setTimeout(() => { setLoading(false); setRecovered(scenario !== "repeat-failure"); timer.current = undefined; }, 350); };
  return <MemoryRouter><CatalogLayout canManage><div className="catalog-stack">
    {loading || recovered ? <CatalogVersionsView versions={loading ? undefined : []} onReload={retry} /> : <CatalogReadFailurePanel failure={failure} onRetry={retry} />}
    {failure.setup && <CatalogSetupView current={{ readiness, scope }} editable={false} busy={false} fields={{ account: "", name: "", reason: "", acknowledged: false }} onFieldsChange={() => undefined} onConfirm={event => event.preventDefault()} onPrepare={() => undefined} onInitialize={() => undefined} onRefresh={() => setRefreshed(true)} />}
    {refreshed && <StatusMessage kind="info" title="准备状态已刷新">虚构前置仍未完成；刷新不会代替来源确认或建立快照。</StatusMessage>}
    {attempt > 0 && <p role="status">本次手动读取 {attempt} 次；{recovered ? "读取已恢复。" : "未自动重试。"}</p>}
    <p>虚构状态样板，不请求实际 API，不执行初始化写入；刷新页面重置样板。</p>
  </div></CatalogLayout></MemoryRouter>;
}
const meta = { title: "Patterns/Catalog Read Feedback", component: ReadFeedback, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReadFeedback>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const RepeatFailure: Story = { args: { scenario: "repeat-failure" } };
export const RateLimited: Story = { args: { scenario: "rate-limited" } };
export const Forbidden: Story = { args: { scenario: "forbidden" } };
export const NotFound: Story = { args: { scenario: "not-found" } };
export const InvalidQuery: Story = { args: { scenario: "invalid-query" } };
export const Setup: Story = { args: { scenario: "setup" } };
export const LongMessage: Story = { args: { scenario: "long-message" } };
