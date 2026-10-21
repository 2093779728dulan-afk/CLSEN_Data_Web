import { useState, type FormEvent } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { AdminAccessBoundary, AdminWorkspaceHeader, type AdminSection } from "./AdminAccountsView";
import { AdminAuditView } from "./AdminAuditView";
import { auditEvents } from "./AdminAuditView.fixtures";
import { accountPrincipal } from "./AdminAccountsView.fixtures";
import css from "./AdminAccountsView.module.css";
import "./AdminConsole.css";

type Scenario = "reference" | "filtered" | "details" | "loading" | "read-failure" | "filter-failure" | "empty" | "busy" | "access-denied";
function AuditStory({ scenario }: { scenario: Scenario }) {
  const [section, setSection] = useState<AdminSection>("audit");
  const [filter, setFilter] = useState(scenario === "filtered" ? "admin.user_updated" : "");
  const [applied, setApplied] = useState(filter);
  const [offset, setOffset] = useState(0);
  const [failed, setFailed] = useState(scenario === "read-failure");
  const [error, setError] = useState<string | undefined>(scenario === "read-failure" ? "示例审计读取失败，请重新载入。" : scenario === "filter-failure" ? "示例筛选读取失败，请再次应用筛选。" : undefined);
  if (scenario === "access-denied") return <AdminAccessBoundary />;
  const filtered = scenario === "empty" ? [] : auditEvents.filter(item => !applied || item.event_type === applied);
  const submit = (event: FormEvent) => { event.preventDefault(); setApplied(filter.trim()); setOffset(0); setError(undefined); };
  return <main className={`admin-console ${css.workspace}`}>
    <AdminWorkspaceHeader principal={accountPrincipal} section={section} onSectionChange={setSection} />
    <p>虚构审计样板，不请求真实API；筛选和分页仅更新本地内存。</p>
    {section === "audit" ? <AdminAuditView page={{ items: filtered.slice(offset, offset + 20), total: filtered.length, offset, limit: 20, next_offset: offset + 20 < filtered.length ? offset + 20 : null }} offset={offset} pageSize={20} filter={filter} appliedFilter={applied}
      initialLoading={scenario === "loading"} loadFailed={failed} busy={scenario === "busy"} error={error} onFilterChange={setFilter} onFilter={submit}
      onPage={next => { setOffset(next); setError(undefined); }} onRetry={() => { setFailed(false); setError(undefined); }} /> : <p>此批样板仅覆盖内部审计</p>}
  </main>;
}
const meta = { title: "Pages/Admin Audit", component: AuditStory, parameters: { layout: "fullscreen" }, args: { scenario: "reference" } } satisfies Meta<typeof AuditStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = {};
export const Filtered: Story = { args: { scenario: "filtered" } };
export const Details: Story = { args: { scenario: "details" }, play: ({ canvas }) => { canvas.getAllByText("查看脱敏详情")[0]?.click(); } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const FilterFailure: Story = { args: { scenario: "filter-failure" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const Busy: Story = { args: { scenario: "busy" } };
export const AccessDenied: Story = { args: { scenario: "access-denied" } };
