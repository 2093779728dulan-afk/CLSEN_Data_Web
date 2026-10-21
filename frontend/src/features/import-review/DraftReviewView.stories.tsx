import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { PageHeader } from "../../design-system";
import { DraftReviewView, type DraftReviewViewProps } from "./DraftReviewView";
import { PublicationDialog } from "./DraftPublicationDialog";
import { ReviewDataTable } from "./ReviewDataTable";
import { draftContext, draftWorkspace, readyDraftWorkspace, validationFor } from "./DraftReviewView.fixtures";
import { validationCounts } from "./draftReviewPresentation";

type Scenario = "reference" | "validated" | "blocking" | "warning" | "ready-for-publish" | "publish-dialog" | "publication-failure" | "validating" | "loading" | "read-failure" | "action-failure" | "admin-required" | "published";
function ReferencePage({ scenario = "reference" }: { scenario?: Scenario }) {
  const initial = structuredClone(["reference", "loading", "read-failure", "validating", "action-failure"].includes(scenario) ? draftWorkspace : readyDraftWorkspace());
  if (["validated", "blocking", "warning"].includes(scenario)) initial.head.status = "draft";
  if (["blocking", "warning"].includes(scenario) && initial.latest_full_validation) {
    initial.latest_full_validation.summary.stages.parse_fidelity.blocking_count = scenario === "blocking" ? 1 : 0;
    initial.latest_full_validation.summary.stages.parse_fidelity.warning_count = scenario === "warning" ? 1 : 0;
    initial.latest_full_validation.result = scenario === "blocking" ? "failed" : "passed";
  }
  const [workspace, setWorkspace] = useState(initial);
  const [loaded, setLoaded] = useState(!["loading", "read-failure"].includes(scenario));
  const [error, setError] = useState<string | undefined>(scenario === "read-failure" ? "示例：草稿暂不可读，重新读取后再继续。" : scenario === "action-failure" ? "示例：操作未完成，当前草稿已保留。" : undefined);
  const [notice, setNotice] = useState<string>();
  const [note, setNote] = useState("");
  const [visibility, setVisibility] = useState<"internal" | "viewer_visible">("internal");
  const [readyReason, setReadyReason] = useState("已与源表核对日期、类型与合计。 ");
  const [showPublish, setShowPublish] = useState(["publish-dialog", "publication-failure"].includes(scenario));
  const [targetDate, setTargetDate] = useState("2026-08-10");
  const [moveReason, setMoveReason] = useState("核对原表后修正归属日。 ");
  const [preview, setPreview] = useState<DraftReviewViewProps["draftMovePreview"]>();
  const [decision, setDecision] = useState<DraftReviewViewProps["draftMoveDecision"]>();
  const [discardReason, setDiscardReason] = useState("核对原文件后重新解析。 ");
  const [discardConfirmed, setDiscardConfirmed] = useState(false);
  const context = { ...draftContext(workspace), publicationMode: scenario === "admin-required" ? "published_move" as const : "ordinary" as const,
    publishedMove: scenario === "admin-required" ? { revision_operation_token: "11111111-1111-4111-8111-111111111111", source_dataset_id: 40, source_publication: { version_id: 49, published_at: "2026-08-09T03:00:00Z" }, source_report_date: "2026-08-09", target_publication: { version_id: null, published_at: null } } : null };
  const validation = validationFor(workspace);
  const rejectWrite = () => Promise.reject(new Error("样板不执行真实数据写入。 "));
  const operator = { id: 88, username: "fictional-reviewer", display_name: "虚构审核员" };
  return <main style={{ maxWidth: 1240, padding: 24, margin: "0 auto" }}>
    <PageHeader eyebrow="每日数据" title="草稿审核与发布" description="数据修改、校验、人工确认和发布各自留痕。" />
    <DraftReviewView context={context} head={workspace.head} workspace={loaded ? workspace : undefined} validation={validation} counts={validation ? validationCounts(validation, workspace) : undefined}
      published={scenario === "published"} error={error} notice={notice} operator={operator} busyAction={scenario === "validating" ? "validation" : undefined}
      note={note} noteVisibility={visibility} readyReason={readyReason} targetDate={targetDate} moveReason={moveReason} draftMovePreview={preview} draftMoveDecision={decision} draftMoveMerge={{ ready: false }}
      discardReason={discardReason} discardConfirmed={discardConfirmed} reparseBatchId={11} canFinalizePublishedMove={false}
      setNote={setNote} setNoteVisibility={setVisibility} setReadyReason={setReadyReason} setDiscardReason={setDiscardReason} setDiscardConfirmed={setDiscardConfirmed}
      changeTargetDate={value => { setTargetDate(value); setPreview(undefined); setDecision(undefined); }} changeMoveReason={setMoveReason} changeDraftMoveDecision={setDecision}
      setReparseBatchId={() => setNotice("样板来源为导入批次 #11。 ")} resetDiscardOperation={() => setNotice(undefined)}
      onDiscarded={() => setNotice("样板不废弃真实草稿。 ")} onReparseSource={rejectWrite} discardDraft={() => setNotice("已核对处置确认，样板不发送写请求。 ")}
      saveNote={() => { setNotice("备注内容与可见范围已核对，样板不提交。 "); }} runValidation={() => { const next = readyDraftWorkspace(); next.head.status = "draft"; setWorkspace(next); setError(undefined); }}
      markReady={() => { setWorkspace(readyDraftWorkspace()); }} setShowPublish={setShowPublish}
      inspectDraftMoveTarget={() => setPreview({ kind: "published", reportDate: targetDate, publication: { ...readyDraftWorkspace().head, report_date: targetDate, report_type: "business_report", is_current_publication: true, is_active_draft: false, created_at: "2026-08-10T02:00:00Z", published_at: "2026-08-10T02:00:00Z", sealed_at: "2026-08-10T02:00:00Z", draft_pointed_at: null, dedup_publication_revision: null, publication_revision: null } })}
      confirmDraftMoveDecision={() => { if (decision === "cancel") { setPreview(undefined); setDecision(undefined); setNotice("已取消，所属日期保留。 "); } else setNotice("样板不发送日期移动写请求。 "); }}
      onRefresh={() => { setLoaded(true); setError(undefined); }}
      versionNotes={<ul className="version-note-list">{workspace.version_notes.map(item => <li key={item.note_key}><p>{item.body}</p><span>{item.author_username} · 仅审核人员 · 第 {item.revision_number} 版</span></li>)}</ul>}
      dataTable={<ReviewDataTable workspace={workspace} busy={scenario === "validating"} operator={operator} onPageChange={() => setNotice("样板只有一页。 ")}
        onAddCellNote={rejectWrite} onAddRow={rejectWrite} onAddRowNote={rejectWrite} onChangeRowState={rejectWrite} onRestoreField={rejectWrite} onReviewIssue={rejectWrite} onReviseNote={rejectWrite} onSetField={rejectWrite} />}
      publicationDialog={showPublish && validation ? <PublicationDialog context={context} head={workspace.head} validation={validation} operator={operator} onCancel={() => setShowPublish(false)} onPublish={() => Promise.reject(new Error(scenario === "publication-failure" ? "示例：发布指针已变化，请重新读取后核对。" : "样板不提交真实发布请求。 "))} /> : undefined} />
    <p>源表、草稿、校验回执及状态全部为虚构。样板不请求 API，校验与确认只切换示例状态，编辑和发布不写入真实数据。</p>
  </main>;
}
const meta = { title: "Pages/Draft Review", component: ReferencePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReferencePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Validated: Story = { args: { scenario: "validated" } };
export const Blocking: Story = { args: { scenario: "blocking" } };
export const Warning: Story = { args: { scenario: "warning" } };
export const ReadyForPublish: Story = { args: { scenario: "ready-for-publish" } };
export const PublishDialog: Story = { args: { scenario: "publish-dialog" } };
export const PublicationFailure: Story = { args: { scenario: "publication-failure" } };
export const Validating: Story = { args: { scenario: "validating" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const ActionFailure: Story = { args: { scenario: "action-failure" } };
export const AdminRequired: Story = { args: { scenario: "admin-required" } };
export const Published: Story = { args: { scenario: "published" } };
