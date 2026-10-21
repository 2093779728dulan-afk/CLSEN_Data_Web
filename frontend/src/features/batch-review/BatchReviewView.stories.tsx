import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { BatchReviewView } from "./BatchReviewView";
import { recompute, sampleRun } from "./BatchReviewView.fixtures";

type Scenario = "reference" | "running" | "paused" | "completed" | "exceptions" | "outcome-unknown" | "confirming" | "retrying" | "empty" | "loading" | "read-failure" | "action-failure";
function ReferencePage({ scenario = "reference" }: { scenario?: Scenario }) {
  const initial = sampleRun(["paused", "running", "completed"].includes(scenario) ? scenario : ["exceptions", "outcome-unknown", "retrying"].includes(scenario) ? "completed_with_exceptions" : "preview");
  if (scenario === "empty") initial.items = [];
  if (scenario === "outcome-unknown") { initial.status = "running"; initial.allowed_actions = ["pause"]; initial.items[1] = { ...initial.items[1]!, status: "validating", retry_allowed: false, outcome_unknown: true, reason_message: null }; }
  const [run, setRun] = useState(recompute(initial));
  const [selectedIds, setSelectedIds] = useState(new Set(initial.items.filter(i => i.status === "eligible" && i.selected).map(i => i.id)));
  const [accepted, setAccepted] = useState(scenario === "confirming");
  const [loading, setLoading] = useState(scenario === "loading");
  const [error, setError] = useState<string | undefined>(scenario === "read-failure" || scenario === "action-failure" ? "示例：任务读取或操作失败，已保留当前任务。" : undefined);
  const [readFailed, setReadFailed] = useState(scenario === "read-failure");
  return <MemoryRouter><BatchReviewView run={readFailed ? undefined : run} loading={loading} error={error} selectedIds={selectedIds} accepted={accepted}
    busyAction={scenario === "confirming" ? "confirm" : undefined} busyItemId={scenario === "retrying" ? 102 : undefined}
    onRefresh={() => { setLoading(false); setError(undefined); setReadFailed(false); }}
    onToggle={(id, selected) => setSelectedIds(previous => { const next = new Set(previous); if (selected) next.add(id); else next.delete(id); return next; })} onAccept={setAccepted}
    onConfirm={() => setRun(recompute({ ...run, revision: run.revision + 1, status: "running", allowed_actions: ["pause"], items: run.items.map(item => item.status === "eligible" ? { ...item, status: selectedIds.has(item.id) ? "queued" : "skipped", selected: selectedIds.has(item.id) } : item) }))}
    onChangeState={action => setRun({ ...run, revision: run.revision + 1, status: action === "pause" ? "paused" : "running", allowed_actions: action === "pause" ? ["resume"] : ["pause"] })}
    onRetry={item => setRun(recompute({ ...run, revision: run.revision + 1, status: "running", allowed_actions: ["pause"], items: run.items.map(i => i.id === item.id ? { ...i, status: "queued", retry_allowed: false, reason_message: null } : i) }))} />
    <p>文件、日期和任务均为虚构数据。样板只演示预检、排队、暂停与恢复，不执行真实校验或发布。</p>
  </MemoryRouter>;
}
const meta = { title: "Pages/Batch Review", component: ReferencePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReferencePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Running: Story = { args: { scenario: "running" } };
export const Paused: Story = { args: { scenario: "paused" } };
export const Completed: Story = { args: { scenario: "completed" } };
export const Exceptions: Story = { args: { scenario: "exceptions" } };
export const OutcomeUnknown: Story = { args: { scenario: "outcome-unknown" } };
export const Confirming: Story = { args: { scenario: "confirming" } };
export const Retrying: Story = { args: { scenario: "retrying" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const ActionFailure: Story = { args: { scenario: "action-failure" } };
