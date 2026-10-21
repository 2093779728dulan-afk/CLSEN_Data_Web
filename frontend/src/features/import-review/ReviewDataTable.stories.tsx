import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { ReviewDataTable } from "./ReviewDataTable";
import { dataTableWorkspace } from "./ReviewDataTable.fixtures";

function ReferenceTable({ scenario = "reference" }: { scenario?: string }) {
  const [page, setPage] = useState(scenario === "second-page" ? 2 : 1);
  const workspace = dataTableWorkspace(scenario, page);
  const rejectWrite = () => Promise.reject(new Error("虚构样板不提交真实审核操作。"));
  return <main style={{ maxWidth: 1240, margin: "0 auto", padding: 16 }}>
    <ReviewDataTable workspace={workspace} busy={scenario === "busy"} onPageChange={setPage} operator={{ id: 88, username: "fictional-reviewer", display_name: "虚构审核员" }} onAddRow={rejectWrite} onAddRowNote={rejectWrite} onAddCellNote={rejectWrite} onChangeRowState={rejectWrite} onSetField={rejectWrite} onRestoreField={rejectWrite} onReviewIssue={rejectWrite} onReviseNote={rejectWrite} />
    <p>虚构两页记录，不请求 API。差异、行状态与空值用于核对显示；编辑不提交真实数据。</p>
  </main>;
}
const meta = { title: "Patterns/Draft Data Table", component: ReferenceTable, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReferenceTable>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = {};
export const LongValues: Story = { args: { scenario: "long-values" } };
export const Unchanged: Story = { args: { scenario: "unchanged" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const FilterEmpty: Story = {};
export const Busy: Story = { args: { scenario: "busy" } };
export const SecondPage: Story = { args: { scenario: "second-page" } };
