import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { AdminMaintenanceView } from "./AdminMaintenanceView";
import { statusFor, type MaintenanceScenario } from "./AdminMaintenanceView.fixtures";
import { AdminAccessBoundary, AdminWorkspaceHeader, type AdminSection } from "./AdminAccountsView";
import { accountPrincipal } from "./AdminAccountsView.fixtures";
import css from "./AdminAccountsView.module.css";
import "./AdminConsole.css";

function MaintenanceStory({ scenario }: { scenario: MaintenanceScenario }) {
  const [section, setSection] = useState<AdminSection>("maintenance");
  const [status, setStatus] = useState(scenario === "read-failure" || scenario === "loading" ? undefined : statusFor(scenario));
  const [error, setError] = useState<string | null>(scenario === "read-failure" ? "示例维护状态读取失败" : scenario === "refresh-failure" ? "示例网络暂时不可用" : null);
  const [refreshedAt, setRefreshedAt] = useState(new Date("2026-09-13T10:30:00Z"));
  if (scenario === "access-denied") return <AdminAccessBoundary />;
  return <main className={`admin-console ${css.workspace}`}><AdminWorkspaceHeader principal={accountPrincipal} section={section} onSectionChange={setSection} />
    <p>虚构维护样板，无真实备份、恢复或后台任务操作。</p>
    {section === "maintenance" ? <AdminMaintenanceView status={status} pageRefreshedAt={refreshedAt} refreshing={scenario === "loading" || scenario === "refreshing"} refreshError={error}
      onRefresh={() => { setStatus(statusFor(scenario)); setError(null); setRefreshedAt(new Date("2026-09-13T10:30:15Z")); }} /> : <p>此批样板仅覆盖备份与后台任务</p>}
  </main>;
}
const meta = { title: "Pages/Admin Maintenance", component: MaintenanceStory, parameters: { layout: "fullscreen" }, args: { scenario: "reference" } } satisfies Meta<typeof MaintenanceStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = {};
export const Diagnostics: Story = { args: { scenario: "diagnostics" }, play: ({ canvasElement }) => { for (const details of canvasElement.querySelectorAll(".worker-observability details")) (details as HTMLDetailsElement).open = true; } };
export const Refreshing: Story = { args: { scenario: "refreshing" } };
export const RefreshFailure: Story = { args: { scenario: "refresh-failure" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const ConsumerFailure: Story = { args: { scenario: "consumer-failure" } };
export const QueryUnknown: Story = { args: { scenario: "query-unknown" } };
export const HeartbeatDelayed: Story = { args: { scenario: "heartbeat-delayed" } };
export const BackupFailure: Story = { args: { scenario: "backup-failure" } };
export const AccessDenied: Story = { args: { scenario: "access-denied" } };
