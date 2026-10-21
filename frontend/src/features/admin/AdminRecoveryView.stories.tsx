import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { AdminRecoveryView } from "./AdminRecoveryView";
import { AdminAccessBoundary, AdminWorkspaceHeader, type AdminSection } from "./AdminAccountsView";
import { accountPrincipal } from "./AdminAccountsView.fixtures";
import type { AdminForceRebuildContext } from "./AdminConsole";
import css from "./AdminAccountsView.module.css";
import "./AdminConsole.css";

const context: AdminForceRebuildContext = { batchId: 11, expectedActiveDraft: { version_id: 51, data_revision: 2, review_revision: 3 }, expectedPublicationVersionId: 49, parseBaselineId: 31, reportDate: "2026-09-13", versionId: 51 };
type Scenario = "reference" | "context" | "confirmed" | "submitting" | "failure" | "success" | "unpublished" | "loading" | "read-failure" | "access-denied";
function RecoveryStory({ scenario }: { scenario: Scenario }) {
  const [section, setSection] = useState<AdminSection>("recovery");
  const [reason, setReason] = useState(["confirmed", "submitting", "failure"].includes(scenario) ? "来源文件已更正，按确认后的解析基线重新构建。" : "");
  const [confirmed, setConfirmed] = useState(["confirmed", "submitting", "failure"].includes(scenario));
  const [notice, setNotice] = useState<string | undefined>(scenario === "success" ? "草稿已重建为 v3；新草稿仍需重新校验。" : undefined);
  const [error, setError] = useState<string | undefined>(scenario === "failure" ? "示例网络中断，提交结果尚未确认；请保留相同内容并重试。" : scenario === "read-failure" ? "示例管理状态读取失败。" : undefined);
  const [loadFailed, setLoadFailed] = useState(scenario === "read-failure");
  if (scenario === "access-denied") return <AdminAccessBoundary />;
  return <main className={`admin-console ${css.workspace}`}><AdminWorkspaceHeader principal={accountPrincipal} section={section} onSectionChange={setSection} /><p>虚构恢复样板，不执行真实草稿重建。</p>
    {section === "recovery" ? <AdminRecoveryView context={scenario === "reference" || scenario === "read-failure" || loadFailed || scenario === "loading" ? undefined : scenario === "unpublished" ? { ...context, expectedPublicationVersionId: null } : context}
      loading={scenario === "loading"} loadFailed={loadFailed} busy={scenario === "submitting"} reason={reason} confirmed={confirmed} error={error} notice={notice}
      onRetry={() => { setLoadFailed(false); setError(undefined); }} onReasonChange={setReason} onConfirmedChange={setConfirmed}
      onSubmit={event => { event.preventDefault(); setError(undefined); setNotice("草稿已重建为 v3；新草稿仍需重新校验。"); setReason(""); setConfirmed(false); }} /> : <p>此批样板仅覆盖草稿恢复。</p>}
  </main>;
}
const meta = { title: "Pages/Admin Recovery", component: RecoveryStory, parameters: { layout: "fullscreen" }, args: { scenario: "reference" } } satisfies Meta<typeof RecoveryStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = {};
export const Context: Story = { args: { scenario: "context" } };
export const Confirmed: Story = { args: { scenario: "confirmed" } };
export const Submitting: Story = { args: { scenario: "submitting" } };
export const Failure: Story = { args: { scenario: "failure" } };
export const Success: Story = { args: { scenario: "success" } };
export const Unpublished: Story = { args: { scenario: "unpublished" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const AccessDenied: Story = { args: { scenario: "access-denied" } };
