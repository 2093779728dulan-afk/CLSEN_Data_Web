import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import { Button, StatusMessage } from "../../design-system";
import { PublicationDialog } from "./DraftPublicationDialog";
import { draftContext, readyDraftWorkspace, validationFor } from "./DraftReviewView.fixtures";
import styles from "./DraftPublicationDialog.module.css";

type Scenario = "reference" | "no-operator" | "warnings" | "cross-date" | "return-report" | "return-building" | "return-retrying" | "return-ready" | "return-superseded" | "submitting" | "failure";
function Confirmation({ scenario = "reference" }: { scenario?: Scenario }) {
  const [open, setOpen] = useState(true);
  const [complete, setComplete] = useState(false);
  const attempts = useRef(0);
  const workspace = readyDraftWorkspace();
  if (scenario.startsWith("return-")) {
    workspace.report_type = "return_report"; workspace.ruleset_version = "return_report_v1";
    workspace.latest_full_validation!.ruleset_version = "return_report_v1";
    workspace.latest_full_validation!.summary.report_type = "return_report";
    workspace.latest_full_validation!.summary.totals = { quantity: "6" };
    for (const stage of Object.values(workspace.latest_full_validation!.summary.stages)) stage.totals = { quantity: "6" };
  }
  if (scenario === "warnings") workspace.latest_full_validation!.summary.stages.parse_fidelity.warning_count = 2;
  const context = draftContext(workspace);
  if (scenario === "cross-date") {
    context.publicationMode = "published_move";
    context.publishedMove = { revision_operation_token: "11111111-1111-4111-8111-111111111111", source_dataset_id: 40, source_publication: { version_id: 49, published_at: "2026-08-09T03:00:00Z" }, source_report_date: "2026-08-09", target_publication: { version_id: null, published_at: null } };
  }
  const validation = validationFor(workspace)!;
  const progress = scenario === "return-building" ? "building" : scenario === "return-retrying" ? "failed" : scenario === "return-ready" ? "ready" : scenario === "return-superseded" ? "superseded" : undefined;
  const pending = scenario === "submitting" || progress !== undefined;
  return <main className={styles.stage}><h1>最终发布确认</h1><p>虚构校验回执，不发送真实发布或快照请求。</p>
    <Button onClick={() => { setOpen(true); setComplete(false); }}>重新打开发布确认</Button>
    {complete && <StatusMessage kind="success" title="样板确认完成">仅完成本地交互，未发布真实数据。</StatusMessage>}
    {open && <PublicationDialog context={context} head={workspace.head} validation={validation}
      operator={scenario === "no-operator" ? undefined : { id: 88, username: "fictional-reviewer", display_name: "虚构审核员" }}
      publicationProgress={progress} onCancel={() => setOpen(false)} onPublish={() => {
        attempts.current += 1;
        if (pending) return new Promise<void>(() => {});
        if (scenario === "failure" && attempts.current === 1) return Promise.reject(new Error("示例：发布响应未确认，说明已保留，请核对后重试。"));
        setOpen(false); setComplete(true); return Promise.resolve();
      }} />}
  </main>;
}
const meta = { title: "Patterns/Publication Confirmation", component: Confirmation, parameters: { layout: "fullscreen" } } satisfies Meta<typeof Confirmation>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const NoOperator: Story = { args: { scenario: "no-operator" } };
export const Warnings: Story = { args: { scenario: "warnings" } };
export const CrossDate: Story = { args: { scenario: "cross-date" } };
export const ReturnReport: Story = { args: { scenario: "return-report" } };
export const ReturnBuilding: Story = { args: { scenario: "return-building" } };
export const ReturnRetrying: Story = { args: { scenario: "return-retrying" } };
export const ReturnReady: Story = { args: { scenario: "return-ready" } };
export const ReturnSuperseded: Story = { args: { scenario: "return-superseded" } };
export const Submitting: Story = { args: { scenario: "submitting" } };
export const Failure: Story = { args: { scenario: "failure" } };
