import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type FormEvent } from "react";
import type { MoveDecision, MoveTargetPreview } from "./VersionHistory";
import { Button, StatusMessage } from "../../design-system";
import { current, draft, historical, detailFor } from "./VersionHistoryView.fixtures";
import { RevisionConfirmationView, MoveConfirmationView, UndoMoveConfirmationView, RollbackConfirmationView } from "./VersionCommandViews";
import styles from "./VersionCommandViews.module.css";

const undoExample = {
  move_command_id: 77, source_dataset_id: 40, source_report_date: "2026-09-11", restore_source_version_id: 47,
  source_current_publication: { version_id: null, published_at: null }, target_dataset_id: 41, target_report_date: "2026-09-12",
  restore_target_version_id: 51, target_current_publication: { version_id: 53, published_at: "2026-09-12T03:00:00Z" },
  moved_target_version_id: 53, completed_at: "2026-09-12T03:00:00Z", report_type: "business_report" as const,
};
type Scenario = "revision" | "revision-submitting" | "revision-failure" | "move" | "move-checking" | "move-published" | "move-draft" | "move-blocked" | "move-failure" | "undo" | "undo-failure" | "rollback" | "rollback-failure";
function CommandPage({ scenario = "revision" }: { scenario?: Scenario }) {
  const [open, setOpen] = useState(true);
  const [reason, setReason] = useState(scenario.includes("failure") || scenario.includes("submitting") ? "虚构原因：复核报告归属日期" : "");
  const [targetDate, setTargetDate] = useState(scenario === "move" ? "" : "2026-09-13");
  const [preview, setPreview] = useState<MoveTargetPreview | undefined>(scenario === "move-draft" ? { kind: "active_draft", draft, publication: current } : scenario === "move-published" ? { kind: "published", publication: current } : scenario === "move-blocked" ? { kind: "pointerless", datasetId: 41 } : undefined);
  const [decision, setDecision] = useState<MoveDecision | undefined>(scenario === "move-draft" ? "force_replace" : scenario === "move-published" ? "replace_published" : undefined);
  const [forceConfirmed, setForceConfirmed] = useState(false);
  const [error, setError] = useState<string | undefined>(scenario.includes("failure") ? "示例：发布状态已变化，请重新读取后核对，输入的原因已保留。" : undefined);
  const [notice, setNotice] = useState<string>();
  const submitting = scenario === "revision-submitting";
  const forceRebuild = decision === "force_merge" || decision === "force_replace";
  const submit = (event: FormEvent) => { event.preventDefault(); setError(undefined); setNotice("样板已接收本次确认；未发送实际写入命令。"); setOpen(false); };
  const common = { reason, onReasonChange: setReason, submitting, onClose: () => setOpen(false), onSubmit: submit };
  return <div className={styles.stage}>
    <h1>版本操作确认</h1><p>虚构日期与版本；本页仅展示共享确认界面，不发真实 API。</p>
    <Button onClick={() => setOpen(true)}>重新打开确认</Button>
    {notice && <StatusMessage kind="info" title="样板反馈">{notice}</StatusMessage>}
    {open && (scenario.startsWith("revision") ? <RevisionConfirmationView {...common} source={detailFor()} error={error} />
      : scenario.startsWith("move") ? <MoveConfirmationView {...common} source={current} targetDate={targetDate} targetPreview={preview} decision={decision} checking={scenario === "move-checking"}
        forceRebuild={forceRebuild} forceConfirmed={forceConfirmed} onForceConfirmedChange={setForceConfirmed}
        changeTargetDate={value => { setTargetDate(value); setPreview(undefined); setDecision(undefined); setForceConfirmed(false); setError(undefined); }}
        changeDecision={value => { setDecision(value); setForceConfirmed(false); }}
        onInspectTarget={() => { setError(undefined); setPreview({ kind: "empty" }); setDecision("create"); }}
        commandReady={Boolean(preview && decision && decision !== "client_cancel" && preview.kind !== "pointerless")}
        mergeReady={decision !== "merge_published" && decision !== "merge_draft" && decision !== "force_merge"}
        mergeMatrix={decision === "merge_published" || decision === "merge_draft" || decision === "force_merge" ? <StatusMessage kind="info" title="行冲突确认">实际页面沿用原合并决策矩阵；本样板不请求行数据，因此不会开放合并提交。</StatusMessage> : undefined}
        moveError={error} submitLabel={decision === "cancel_draft" ? "记录取消决定" : forceRebuild ? "强制重建跨日期草稿" : "创建跨日期审核草稿"} />
      : scenario.startsWith("undo") ? <UndoMoveConfirmationView {...common} move={undoExample} undoError={error} />
      : <RollbackConfirmationView {...common} current={current} target={historical} reportDate={current.report_date} reportType={current.report_type} error={error} />)}
  </div>;
}
const meta = { title: "Pages/Version Commands", component: CommandPage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof CommandPage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Revision: Story = { args: { scenario: "revision" } };
export const RevisionSubmitting: Story = { args: { scenario: "revision-submitting" } };
export const RevisionFailure: Story = { args: { scenario: "revision-failure" } };
export const Move: Story = { args: { scenario: "move" } };
export const MoveChecking: Story = { args: { scenario: "move-checking" } };
export const MovePublished: Story = { args: { scenario: "move-published" } };
export const MoveDraft: Story = { args: { scenario: "move-draft" } };
export const MoveBlocked: Story = { args: { scenario: "move-blocked" } };
export const MoveFailure: Story = { args: { scenario: "move-failure" } };
export const Undo: Story = { args: { scenario: "undo" } };
export const UndoFailure: Story = { args: { scenario: "undo-failure" } };
export const Rollback: Story = { args: { scenario: "rollback" } };
export const RollbackFailure: Story = { args: { scenario: "rollback-failure" } };
