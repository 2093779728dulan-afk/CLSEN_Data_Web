import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { ApiRequestError } from "../../api/client";
import { CatalogWorkflowActions } from "./CatalogWorkflowActions";
import type { CatalogImportSummary } from "./catalogTypes";
import type { catalogCommand } from "./catalogApi";
import "./CatalogWorkspace.css";

type Scenario = "reference" | "high-risk" | "rebase" | "saving" | "failure" | "blocked" | "read-only" | "approved";
function Sample({ scenario = "reference" }: { scenario?: Scenario }) {
  const [imported, setImported] = useState<CatalogImportSummary>({
    import_id: 42, workflow_revision: 3, catalog_publication_revision: 7, base_catalog_version_id: 4, export_id: 8001,
    parse_attempt_revision: 1, source_kind: "online", status: scenario === "approved" ? "approved" : "ready_for_approval",
    approved_catalog_version_number: scenario === "approved" ? 5 : null,
    failure_reason_code: null, has_original_file: false, submitted_by_user_id: 88, validation_run_id: 12,
    permissions: { can_view: true, can_edit: false, can_validate: false, can_submit: false, can_preview: scenario !== "read-only",
      can_approve_normal: scenario !== "read-only", can_approve_high_risk: false, can_download_original: false,
      can_rebase: scenario !== "read-only", can_reject: scenario !== "read-only", can_withdraw: false, can_resume: false },
  });
  const pending = useRef(imported);
  const failed = useRef(false);
  const command: typeof catalogCommand = async (_id, action, revision) => {
    if (scenario === "saving" && action !== "approval-preview") return new Promise(() => {});
    await new Promise(resolve => setTimeout(resolve, 300));
    if (scenario === "failure" && action === "rebase" && !failed.current) {
      failed.current = true;
      throw new ApiRequestError(409, "REVISION_CONFLICT", "示例：目录发布修订已变化，请核对最新导出后重新操作。");
    }
    if (action === "approval-preview") return { risk: scenario === "high-risk" ? "high" : "normal", included_row_count: 18, audit_only_row_count: 2, catalog_publication_revision: 7, projection_id: 901, projection_digest: "fictional-projection-digest" };
    pending.current = { ...pending.current, workflow_revision: revision + 1, status: action === "approve" ? "approved" : "needs_attention", approved_catalog_version_number: action === "approve" ? 5 : null };
    return { workflow_revision: revision + 1, ...(action === "approve" ? { catalog_version_number: 5 } : {}) };
  };
  return <MemoryRouter><main className="catalog-workspace" id="main-content"><CatalogWorkflowActions imported={imported} command={command} onChanged={() => setImported(pending.current)} blockedReason={scenario === "blocked" ? "还有 2 行未保存，请先保存修改再进行校验与批准。" : undefined} /><p>虚构审核样板：编号与版本仅用于展示，不请求实际 API，不批准真实目录；刷新会重置示例。</p></main></MemoryRouter>;
}
const meta = { title: "Patterns/Catalog Workflow Forms", component: Sample, parameters: { layout: "fullscreen" } } satisfies Meta<typeof Sample>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const HighRisk: Story = { args: { scenario: "high-risk" } };
export const Rebase: Story = { args: { scenario: "rebase" } };
export const Saving: Story = { args: { scenario: "saving" } };
export const Failure: Story = { args: { scenario: "failure" } };
export const Blocked: Story = { args: { scenario: "blocked" } };
export const ReadOnly: Story = { args: { scenario: "read-only" } };
export const Approved: Story = { args: { scenario: "approved" } };
