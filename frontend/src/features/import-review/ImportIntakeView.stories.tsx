import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { PageHeader } from "../../design-system";
import { ImportIntakeView, type ImportIntakeViewProps } from "./ImportIntakeView";
import { intakeInspection, intakeParse, intakeTarget, intakeUpload } from "./ImportIntakeView.fixtures";
import type { ImportQueueItem } from "./workflowTypes";

type Scenario = "reference" | "recognition" | "date-mismatch" | "baseline" | "target-conflict" | "active-draft-conflict" | "uploading" | "parsing" | "restoring" | "read-failure" | "parse-failure";
function ReferencePage({ scenario = "reference" }: { scenario?: Scenario }) {
  const isParsed = ["baseline", "target-conflict", "active-draft-conflict"].includes(scenario);
  const [stage, setStage] = useState(isParsed ? 3 : ["recognition", "date-mismatch", "parsing", "parse-failure"].includes(scenario) ? 2 : 0);
  const [files, setFiles] = useState<File[]>(scenario === "uploading" ? [new File(["sku,units\nfictional,2"], "fictional.csv", { type: "text/csv" })] : []);
  const [assignedDate, setAssignedDate] = useState(scenario === "date-mismatch" ? "2026-09-13" : "2026-09-12");
  const [reportType, setReportType] = useState<ImportQueueItem["reportType"]>("business_report");
  const [encoding, setEncoding] = useState<ImportQueueItem["encoding"]>("utf-8-sig");
  const [reason, setReason] = useState("与本次源表核对后生成审核草稿。");
  const [decision, setDecision] = useState<ImportIntakeViewProps["materializeDecision"]>();
  const [confirmed, setConfirmed] = useState(false);
  const [notice, setNotice] = useState<string>();
  const [error, setError] = useState<string | undefined>(["read-failure", "parse-failure"].includes(scenario) ? "示例：读取或解析未完成，原始文件仍保留，可以重试。" : undefined);
  const [conflict, setConflict] = useState(["target-conflict", "active-draft-conflict"].includes(scenario));
  const upload = stage >= 2 ? intakeUpload : undefined;
  const inspection = stage >= 2 ? { ...intakeInspection, report_type: reportType } : undefined;
  const parsed = stage >= 3 ? { ...intakeParse, report_type: reportType } : undefined;
  return <main style={{ maxWidth: 1240, padding: 24, margin: "0 auto" }}>
    <PageHeader eyebrow="每日数据" title="数据导入审核" description="先核对来源与报告日，再生成审核草稿。" />
    <ImportIntakeView activeStage={stage === 0 ? "选择原始文件" : stage === 2 ? "确认识别结果" : "生成审核草稿"} reachedSteps={stage}
      assignedDate={assignedDate} reportType={reportType} encoding={encoding} files={files} importQueue={[]} upload={upload} inspection={inspection} parsed={parsed} published={false}
      materializeReason={reason} materializeDecision={decision} forceRebuildConfirmed={confirmed} materializeMerge={{ ready: false }} canForceRebuild={scenario === "active-draft-conflict"}
      materializePreview={conflict ? { publication: intakeTarget, activeDraft: scenario === "active-draft-conflict" ? { ...intakeTarget, version_id: 52, version_no: 5, status: "draft", is_active_draft: true, is_current_publication: false } : undefined, reportDate: assignedDate, reportType } : undefined}
      busyAction={scenario === "uploading" ? "upload" : scenario === "parsing" ? "parse" : scenario === "restoring" ? "resume" : undefined}
      error={error} notice={notice} reset={() => { setStage(0); setFiles([]); setError(undefined); setNotice(undefined); setConflict(false); setDecision(undefined); }}
      changeAssignedDate={setAssignedDate} changeReportType={setReportType} changeEncoding={setEncoding} setFiles={setFiles}
      uploadAndInspect={event => { event.preventDefault(); setStage(2); setError(undefined); }} updateBatchDate={() => setNotice("样板归属日已更新。")}
      confirmParse={() => { setStage(3); setError(undefined); }} reparseCurrentBaseline={() => { setStage(2); setConflict(false); setDecision(undefined); }}
      setMaterializeReason={setReason} resetPendingMaterialize={() => setNotice(undefined)} inspectMaterializeTarget={() => { setConflict(true); setDecision(undefined); }}
      selectMaterializeDecision={value => { setDecision(value); setConfirmed(false); }} setForceRebuildConfirmed={setConfirmed}
      confirmMaterializeDecision={() => { if (decision === "cancel") { setConflict(false); setDecision(undefined); setNotice("已取消，解析基线保留。 "); } else setNotice("样板已核对所选方式；不执行真实草稿写入。 "); }}
      activateQueueItem={() => setStage(2)} retryQueueInspection={() => { setStage(2); setError(undefined); }} reviewNextQueuedFile={() => setStage(0)} />
    <p>文件与任务均为虚构数据，上传、识别和解析只改变样板状态，不请求 API。草稿审核、重复行矩阵和发布保留在实际页面的原流程中。</p>
  </main>;
}
const meta = { title: "Pages/Import Intake", component: ReferencePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReferencePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Recognition: Story = { args: { scenario: "recognition" } };
export const DateMismatch: Story = { args: { scenario: "date-mismatch" } };
export const Baseline: Story = { args: { scenario: "baseline" } };
export const TargetConflict: Story = { args: { scenario: "target-conflict" } };
export const ActiveDraftConflict: Story = { args: { scenario: "active-draft-conflict" } };
export const Uploading: Story = { args: { scenario: "uploading" } };
export const Parsing: Story = { args: { scenario: "parsing" } };
export const Restoring: Story = { args: { scenario: "restoring" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const ParseFailure: Story = { args: { scenario: "parse-failure" } };
