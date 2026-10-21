import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useRef, useState } from "react";
import { MemoryRouter } from "react-router-dom";
import type { AnalyticsReadiness, CatalogScopeStatusResponse, ReturnInitializationPreview } from "../../api/generated";
import { CatalogLayout } from "./CatalogLayout";
import { CatalogSetupView, type SourceScopeFields } from "./CatalogSetupView";

type Scenario = "reference" | "source-submitting" | "source-failure" | "confirmed" | "preview" | "initializing" | "initialization-failure" | "missing-reports" | "ready" | "read-only" | "loading" | "read-failure";
const readiness: AnalyticsReadiness = { catalog_approved: false, coverage_from: "2026-07-01", coverage_to: "2026-08-06", prerequisites_present: false, published_business_reports: 37, published_reports: 74, published_return_reports: 37, return_snapshot_present: false, source_scope_confirmed: false };
const scope: CatalogScopeStatusResponse = { marketplace_scope_code: "amazon_us", permissions: { can_confirm: true }, report_source_scope_id: null, seller_account_display_name: null, site_config_revision: 3, site_config_version_id: 2, status: "unconfirmed" };
const preview: ReturnInitializationPreview = { dataset_id: 74, proposed_version_id: 93, expected_publication_revision: 0, expected_dedup_publication_revision: 0, initialization_revision: 3, expected_set_digest: "a".repeat(64), published_return_reports: 37, coverage_from: "2026-07-01", coverage_to: "2026-08-06", existing_job_id: null };
const sourceFailure = "来源范围确认未完成。请先刷新核对是否已生效；相同内容再次提交会沿用操作编号。请勿填写另一账号绕过冲突。";
const initializationFailure = "首次快照尚未完成。来源或报表可能发生变化，请刷新核对；相同提交沿用操作编号，不会重复发布日报。";

function SetupPage({ scenario = "reference" }: { scenario?: Scenario }) {
  const isConfirmed = ["confirmed", "preview", "initializing", "initialization-failure", "missing-reports", "ready", "read-only"].includes(scenario);
  const [current, setCurrent] = useState<{ readiness: AnalyticsReadiness; scope: CatalogScopeStatusResponse } | undefined>(() => ["loading", "read-failure"].includes(scenario) ? undefined : { readiness: { ...readiness, source_scope_confirmed: isConfirmed, ...(scenario === "missing-reports" ? { published_reports: 37, published_return_reports: 0 } : {}), ...(scenario === "ready" ? { catalog_approved: true, return_snapshot_present: true, prerequisites_present: true } : {}) }, scope: { ...scope, ...(isConfirmed ? { status: "confirmed", seller_account_display_name: "示例美国账号", report_source_scope_id: 1, permissions: { can_confirm: false } } : {}) } });
  const [fields, setFields] = useState<SourceScopeFields>(() => ["source-submitting", "source-failure"].includes(scenario) ? { account: "DEMO-SCOPE-US", name: "示例美国账号", reason: "虚构报表来源说明", acknowledged: true } : { account: "", name: "", reason: "", acknowledged: false });
  const [busy, setBusy] = useState(["source-submitting", "initializing"].includes(scenario));
  const [value, setValue] = useState<ReturnInitializationPreview | undefined>(["preview", "initializing", "initialization-failure"].includes(scenario) ? preview : undefined);
  const [error, setError] = useState<string | undefined>(scenario === "read-failure" ? "无法读取初始化状态，请刷新；不会据此生成或批准商品。" : scenario === "source-failure" ? sourceFailure : scenario === "initialization-failure" ? initializationFailure : undefined);
  const [progress, setProgress] = useState<string | undefined>(scenario === "initializing" ? "正在建立首次退货快照…" : undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const run = (action: () => void) => { if (timer.current) clearTimeout(timer.current); setBusy(true); timer.current = setTimeout(() => { action(); setBusy(false); timer.current = undefined; }, 350); };
  return <MemoryRouter><CatalogLayout canManage={scenario !== "read-only"}>
    <CatalogSetupView current={current} editable={scenario !== "read-only"} busy={busy} fields={fields} preview={value} error={error} progress={progress}
      onFieldsChange={changes => setFields(existing => ({ ...existing, ...changes }))}
      onConfirm={event => { event.preventDefault(); setError(undefined); run(() => { setCurrent({ readiness: { ...readiness, source_scope_confirmed: true }, scope: { ...scope, status: "confirmed", permissions: { can_confirm: false }, report_source_scope_id: 1, seller_account_display_name: fields.name } }); setFields(existing => ({ ...existing, acknowledged: false })); }); }}
      onPrepare={() => { setError(undefined); run(() => setValue(preview)); }}
      onInitialize={() => { setError(undefined); setProgress("正在建立首次退货快照…"); run(() => { setValue(undefined); setProgress("首次退货快照已建立。请继续生成商品候选，审核映射后批准。"); setCurrent(existing => existing ? { ...existing, readiness: { ...existing.readiness, return_snapshot_present: true } } : existing); }); }}
      onRefresh={() => { setError(undefined); setValue(undefined); run(() => setCurrent(existing => existing ?? { readiness, scope })); }} />
    <p>来源账号、报表和快照均为虚构数据。操作只更新样板内存，不请求实际 API；真实确认、版本摘要、幂等与任务监控仍由 CatalogSetup 原容器负责。</p>
  </CatalogLayout></MemoryRouter>;
}

const meta = { title: "Pages/Catalog Setup", component: SetupPage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof SetupPage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const SourceSubmitting: Story = { args: { scenario: "source-submitting" } };
export const SourceFailure: Story = { args: { scenario: "source-failure" } };
export const Confirmed: Story = { args: { scenario: "confirmed" } };
export const Preview: Story = { args: { scenario: "preview" } };
export const Initializing: Story = { args: { scenario: "initializing" } };
export const InitializationFailure: Story = { args: { scenario: "initialization-failure" } };
export const MissingReports: Story = { args: { scenario: "missing-reports" } };
export const Ready: Story = { args: { scenario: "ready" } };
export const ReadOnly: Story = { args: { scenario: "read-only" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
