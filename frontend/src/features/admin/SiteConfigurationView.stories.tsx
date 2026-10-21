import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { StatusMessage } from "../../design-system";
import { AdminAccessBoundary, AdminWorkspaceHeader, type AdminSection } from "./AdminAccountsView";
import { accountPrincipal } from "./AdminAccountsView.fixtures";
import { SiteConfigurationView } from "./SiteConfigurationView";
import { siteConfigs, siteForm } from "./SiteConfigurationView.fixtures";
import css from "./SiteConfigurationView.module.css";

type Scenario = "reference" | "create" | "creating" | "create-failure" | "loading" | "read-failure" | "empty" | "access-denied" | "multi-site";
function SiteConfigPage({ scenario = "reference" }: { scenario?: Scenario }) {
  const [configs, setConfigs] = useState(scenario === "empty" ? [] : scenario === "multi-site" ? [...structuredClone(siteConfigs), { ...siteConfigs[0]!, id: 801, site_id: 81, site_code: "demo-jp", site_display_name: "示例日本站点", version_number: 1, source_timezone: "Asia/Tokyo", reporting_timezone: "Asia/Tokyo", currency_code: "JPY", change_reason: "示例：日本站点初始口径" }] : structuredClone(siteConfigs));
  const [section, setSection] = useState<AdminSection>("site");
  const [showCreate, setShowCreate] = useState(["create", "creating", "create-failure"].includes(scenario));
  const [form, setForm] = useState({ ...siteForm, changeReason: ["creating", "create-failure"].includes(scenario) ? "示例：调整统计时区" : "" });
  const [loadFailed, setLoadFailed] = useState(scenario === "read-failure");
  const [error, setError] = useState<string | undefined>(scenario === "read-failure" ? "示例：管理资料暂时无法读取，请重新载入。" : scenario === "create-failure" ? "示例：创建结果暂时无法确认，已保留本次表单内容。" : undefined);
  const [notice, setNotice] = useState<string>();
  if (scenario === "access-denied") return <AdminAccessBoundary />;
  return <main className={css.reference}>
    <AdminWorkspaceHeader principal={accountPrincipal} section={section} onSectionChange={setSection} />
    {section === "site" ? <SiteConfigurationView configs={configs} currentConfig={configs.find(config => config.is_current) ?? configs[0]} initialLoading={scenario === "loading"} loadFailed={loadFailed} busy={scenario === "creating"} showCreate={showCreate} form={form} error={error} notice={notice}
      onRetry={() => { setLoadFailed(false); setError(undefined); }}
      onBeginCreate={() => { setShowCreate(true); setForm({ ...siteForm }); setError(undefined); setNotice(undefined); }}
      onCancel={() => setShowCreate(false)} onChange={changes => setForm(current => ({ ...current, ...changes }))}
      onCreate={event => {
        event.preventDefault();
        const target = configs.find(config => config.site_id === Number(form.siteId)) ?? (Number(form.siteId) === 71 ? siteConfigs[0] : undefined);
        if (!target) { setError("此样板仅包含台账中的虚构站点，请使用其站点编号。"); return; }
        const next = { ...target, is_current: true, id: 900 + configs.length, site_id: Number(form.siteId), version_number: Math.max(0, ...configs.filter(config => config.site_id === Number(form.siteId)).map(config => config.version_number)) + 1, source_timezone: form.sourceTimezone, reporting_timezone: form.reportingTimezone, currency_code: form.currencyCode.trim().toUpperCase(), effective_at: new Date(form.effectiveAt).toISOString(), change_reason: form.changeReason.trim(), created_at: "2026-09-13T00:05:00Z" };
        setConfigs(current => [next, ...current.map(config => config.site_id === next.site_id ? { ...config, is_current: false } : config)]); setShowCreate(false); setError(undefined); setNotice(`示例配置 v${next.version_number} 已创建，仅更新样板内存。`);
      }} /> : <StatusMessage kind="info" title="此批样板仅覆盖站点配置与版本历史">可返回“站点配置”继续体验；实际页面保留所选功能。</StatusMessage>}
    <p className={css.disclaimer}>站点、版本与时间均为虚构，表单只更新样板内存，不请求 API。示例多站点记录用于展示范围区别，不表示扩大了生产站点授权。</p>
  </main>;
}
const meta = { title: "Pages/Admin Site Configuration", component: SiteConfigPage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof SiteConfigPage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Create: Story = { args: { scenario: "create" } };
export const Creating: Story = { args: { scenario: "creating" } };
export const CreateFailure: Story = { args: { scenario: "create-failure" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const AccessDenied: Story = { args: { scenario: "access-denied" } };
export const MultiSite: Story = { args: { scenario: "multi-site" } };
