import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { reviewDays, reviewEntries } from "./AdvancedReviewWorkspaceView.fixtures";
import { StatusMessage } from "../design-system";
import { AdvancedReviewWorkspaceView, ReviewWorkbenchReturnView, SourceBatchReviewView } from "./AdvancedReviewWorkspaceView";

type Scenario = "reference" | "empty" | "loading" | "read-failure" | "refreshing" | "read-only" | "published" | "source-batch";
function ReviewStory({ scenario }: { scenario: Scenario }) {
  const [selected, setSelected] = useState({ year: 2026, month: 8, day: 10 });
  const [activeVersionId, setActiveVersionId] = useState(51);
  const [failed, setFailed] = useState(scenario === "read-failure");
  const canWrite = scenario !== "read-only";
  const entries = scenario === "empty" ? [] : scenario === "published" ? reviewEntries.filter(entry => entry.status === "published") : reviewEntries;
  const active = entries.find(entry => entry.version_id === activeVersionId);
  const content = <StatusMessage kind="info" title={selected.day === 10 && active ? `当前草稿 · ${active.report_type === "business_report" ? "经营报告" : "退货报告"} v${active.version_no}` : "当前日期可以开始导入"}>日期、报表类型与版本已经隔离；审核和发布在当前报告内完成。</StatusMessage>;
  return <MemoryRouter><ReviewWorkbenchReturnView target="/review/2026-08-10?report_type=business_report" />{scenario === "source-batch" ? <SourceBatchReviewView batchId={11}><StatusMessage kind="info" title="指定来源批次 #11">核对文件与归属日期，再选择合并或替换生成审核草稿。</StatusMessage></SourceBatchReviewView> : <AdvancedReviewWorkspaceView selected={selected} calendarDays={scenario === "empty" ? [] : reviewDays} entries={entries} calendarKnown={!failed && !["loading", "refreshing"].includes(scenario)} loading={["loading", "refreshing"].includes(scenario)} error={failed ? "示例网络中断。" : undefined} reportingTimezone="America/Los_Angeles" canWrite={canWrite} activeVersionId={activeVersionId} onSelect={setSelected} onSelectDraft={entry => setActiveVersionId(entry.version_id)} onRetry={() => setFailed(false)}>{scenario === "loading" ? undefined : content}</AdvancedReviewWorkspaceView>}</MemoryRouter>;
}
const meta = { title: "Pages/Advanced Review Workspace", component: ReviewStory, parameters: { layout: "fullscreen" }, args: { scenario: "reference" } } satisfies Meta<typeof ReviewStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = {};
export const Empty: Story = { args: { scenario: "empty" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const Refreshing: Story = { args: { scenario: "refreshing" } };
export const ReadOnly: Story = { args: { scenario: "read-only" } };
export const Published: Story = { args: { scenario: "published" } };
export const SourceBatch: Story = { args: { scenario: "source-batch" } };
