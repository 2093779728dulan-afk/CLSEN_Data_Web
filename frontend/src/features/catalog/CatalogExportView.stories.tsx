import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { StatusMessage } from "../../design-system";
import type { CatalogExportStatus } from "./catalogApi";
import { CatalogExportView } from "./CatalogExportView";
import "./CatalogWorkspace.css";

type Scenario = "reference" | "idle" | "unready" | "building" | "failed" | "no-resume" | "stale" | "capacity" | "no-download" | "upload-failure" | "busy";
const ready: CatalogExportStatus = { export_id: 8001, base_catalog_version_id: 4, catalog_publication_revision: 7, export_status: "ready", job_status: "succeeded", job_revision: 2, execution_phase: "completed", attempt_count: 1, max_attempts: 3, next_attempt_at: null, retry_allowed: false, worker_available: true, workbook_status: "ready", permissions: { can_download: true, can_resume: false }, capacity_violations: [], failure_reason_code: null };
function Sample({ scenario = "reference" }: { scenario?: Scenario }) {
  const [current, setCurrent] = useState<CatalogExportStatus | undefined>(() => scenario === "idle" || scenario === "unready" ? undefined : scenario === "building" ? { ...ready, export_status: "building", job_status: "queued", execution_phase: "retry_scheduled", next_attempt_at: "2099-01-01T00:00:00Z", worker_available: false, workbook_status: null } : scenario === "failed" || scenario === "no-resume" ? { ...ready, job_status: "failed", export_status: "failed", execution_phase: "awaiting_manual_recovery", failure_reason_code: "fictional_worker_failure", attempt_count: 3, worker_available: false, permissions: { can_download: false, can_resume: scenario === "failed" } } : scenario === "stale" ? { ...ready, catalog_publication_revision: 6 } : scenario === "capacity" ? { ...ready, workbook_status: "capacity_exceeded" } : scenario === "no-download" ? { ...ready, permissions: { can_download: false, can_resume: false } } : ready);
  const [file, setFile] = useState<File | undefined>(() => scenario === "busy" || scenario === "upload-failure" ? new File(["fictional only"], "fictional-workbook.xlsx") : undefined);
  const [message, setMessage] = useState<string>();
  const [error, setError] = useState<string | undefined>(() => scenario === "upload-failure" ? "虚构示例：工作簿格式未通过检查。已选择的文件保留，请修正后重新选择。" : undefined);
  return <main className="catalog-workspace" id="main-content" onClick={event => {
    const target = event.target as HTMLElement;
    if (target.closest("a")?.getAttribute("href")?.endsWith("/file")) { event.preventDefault(); setMessage("样板仅展示下载入口，不下载真实文件；候选编号 8001。"); }
  }}><CatalogExportView current={current} catalogPublicationRevision={7} generationReady={scenario !== "unready"} busy={scenario === "busy"} selectedFile={file} error={error}
    onCreate={() => { setCurrent(ready); setMessage("虚构候选已生成，尚未批准。"); }} onResume={() => { setCurrent(ready); setMessage("虚构任务已恢复并生成候选，尚未批准。"); }}
    onStartOnline={() => setMessage(`虚构导航：候选 ${current?.export_id} → /catalog/imports/42`)} onFileChange={setFile}
    onUpload={() => { setError(undefined); setMessage(`虚构上传：${file?.name} → /catalog/imports/43；不读取或上传真实文件。`); }} />
    {message && <StatusMessage kind="info" title="样板操作结果">{message}</StatusMessage>}
    <p>所有候选、文件与任务均为虚构示例。操作只更新样板内存，不请求实际 API；刷新会重置。</p>
  </main>;
}
const meta = { title: "Patterns/Catalog Workbook", component: Sample, parameters: { layout: "fullscreen" } } satisfies Meta<typeof Sample>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Idle: Story = { args: { scenario: "idle" } };
export const Unready: Story = { args: { scenario: "unready" } };
export const Building: Story = { args: { scenario: "building" } };
export const Failed: Story = { args: { scenario: "failed" } };
export const NoResume: Story = { args: { scenario: "no-resume" } };
export const Stale: Story = { args: { scenario: "stale" } };
export const Capacity: Story = { args: { scenario: "capacity" } };
export const NoDownload: Story = { args: { scenario: "no-download" } };
export const UploadFailure: Story = { args: { scenario: "upload-failure" } };
export const Busy: Story = { args: { scenario: "busy" } };
