import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import type { ReportType } from "../../api/types";
import type { VersionSummaryResponse } from "../../api/generated";
import { current, detailFor, draft, historical } from "./VersionHistoryView.fixtures";
import { VersionHistoryView } from "./VersionHistoryView";
import { VersionRowsView } from "./VersionRowsView";
import { sampleWorkbench } from "../workbench/DateWorkbenchView.fixtures";
import { BatchReviewHistoryView } from "../batch-review/BatchReviewHistoryView";

type Scenario = "reference" | "manager" | "active-draft" | "batch-drafts" | "empty" | "loading" | "read-failure" | "detail-loading" | "detail-failure" | "rows-open" | "rows-loading" | "rows-failure" | "rows-empty";
function ReferencePage({ scenario = "reference" }: { scenario?: Scenario }) {
  const [reportDate, setReportDate] = useState("2026-09-12");
  const [reportType, setReportType] = useState<ReportType>("business_report");
  const [selected, setSelected] = useState<VersionSummaryResponse>(scenario === "batch-drafts" ? draft : current);
  const [error, setError] = useState<string | undefined>(scenario === "read-failure" || scenario === "detail-failure" ? "示例：版本读取失败，请重新读取当前范围。" : undefined);
  const [rowsError, setRowsError] = useState<string | undefined>(scenario === "rows-failure" ? "示例：所选版本数据暂时无法读取。" : undefined);
  const [detailLoading, setDetailLoading] = useState(scenario === "detail-loading");
  const [loading, setLoading] = useState(scenario === "loading");
  const [rowsOpen, setRowsOpen] = useState(scenario.startsWith("rows-"));
  const [rowPage, setRowPage] = useState(1);
  const [taskPage, setTaskPage] = useState(1);
  const [notice, setNotice] = useState<string>();
  const canManageData = scenario === "manager" || scenario === "active-draft" || scenario === "batch-drafts";
  const detail = { ...detailFor(selected), report_date: reportDate, report_type: reportType };
  const empty = scenario === "empty" || reportDate === "2026-09-13";
  const versions = empty || loading || scenario === "read-failure" && error ? [] : scenario === "batch-drafts" ? [draft] : scenario === "active-draft" ? [draft, current, historical] : [current, historical];
  const workbench = sampleWorkbench("published");
  return <><VersionHistoryView reportDate={reportDate} reportType={reportType} setReportDate={setReportDate} setReportType={setReportType} batchReviewMode={scenario === "batch-drafts"} routeBatchReviewRunId={scenario === "batch-drafts" ? 81 : undefined}
    canAdminister={false} canManageData={canManageData} isViewer={!canManageData} undoLookupUnavailable={false} notice={notice} error={error} versions={versions}
    currentPublication={versions.find(version => version.is_current_publication)} activeDraft={versions.find(version => version.is_active_draft)} selectedVersionId={selected.version_id}
    loading={loading} detailLoading={detailLoading} detail={error || detailLoading ? undefined : detail} selectVersion={version => { setSelected(version); setError(undefined); setRowsOpen(false); setRowPage(1); }}
    onRevision={() => setNotice("虚构样板：创建修订入口已触发。实际页面会要求填写修订原因并确认。")}
    onMove={() => setNotice("虚构样板：移动入口已触发。")} onUndoMove={() => setNotice("虚构样板：撤销入口已触发。")} openRollback={() => setNotice("虚构样板：回滚入口已触发。")}
    onRetry={() => { setError(undefined); setLoading(false); setDetailLoading(false); }}
    batchHistory={canManageData && scenario !== "batch-drafts" ? <BatchReviewHistoryView page={taskPage} onPageChange={setTaskPage} onRetry={() => setTaskPage(1)} result={{ items: [{ id: taskPage === 1 ? 81 : 82, status: "completed_with_exceptions", revision: 4 }], has_next: taskPage === 1 }} /> : undefined}
    versionRows={<VersionRowsView versionNo={selected.version_no} reportDate={reportDate} open={rowsOpen} onToggle={() => setRowsOpen(!rowsOpen)} page={rowPage} onPageChange={setRowPage} error={rowsError} onRetry={() => setRowsError(undefined)}
      response={scenario === "rows-loading" ? undefined : { version_id: selected.version_id, columns: workbench.columns, rows: scenario === "rows-empty" ? [] : [{ ...workbench.rows[0]!, row_ordinal: rowPage === 1 ? 1 : 51 }], pagination: { page: rowPage, total_pages: scenario === "rows-empty" ? 1 : 2, total_rows: scenario === "rows-empty" ? 0 : 51 } }} />} />
    <p>本页日期、版本、备注与数据均为虚构样板，不请求实际 API；修订入口仅展示反馈，真实确认流程沿用原页面。</p>
  </>;
}
const meta = { title: "Pages/Version History", component: ReferencePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReferencePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Manager: Story = { args: { scenario: "manager" } };
export const ActiveDraft: Story = { args: { scenario: "active-draft" } };
export const BatchDrafts: Story = { args: { scenario: "batch-drafts" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const DetailLoading: Story = { args: { scenario: "detail-loading" } };
export const DetailFailure: Story = { args: { scenario: "detail-failure" } };
export const RowsOpen: Story = { args: { scenario: "rows-open" } };
export const RowsLoading: Story = { args: { scenario: "rows-loading" } };
export const RowsFailure: Story = { args: { scenario: "rows-failure" } };
export const RowsEmpty: Story = { args: { scenario: "rows-empty" } };
