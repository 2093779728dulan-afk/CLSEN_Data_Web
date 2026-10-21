import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { PageHeader } from "../../design-system";
import { SourcePreviewView } from "./SourcePreviewView";
import { BatchNotesView } from "./BatchNotesView";
import { NoteRevisionEditor } from "./NoteRevisionEditor";
import { evidenceNote, evidencePreview } from "./ImportEvidence.fixtures";
import css from "./ImportEvidence.module.css";

type Scenario = "reference" | "source-collapsed" | "source-loading" | "source-read-failure" | "source-empty" | "notes-collapsed" | "notes-loading" | "notes-read-failure" | "notes-empty" | "append-failure" | "revision-editing" | "revision-failure" | "revision-saving";
function EvidencePage({ scenario = "reference" }: { scenario?: Scenario }) {
  const [sourceOpen, setSourceOpen] = useState(scenario !== "source-collapsed");
  const [sourceLoading, setSourceLoading] = useState(scenario === "source-loading");
  const [sourceError, setSourceError] = useState<string | undefined>(scenario === "source-read-failure" ? "示例：源文件暂时无法读取，原文件仍保留。" : undefined);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState(scenario !== "notes-collapsed");
  const [loadState, setLoadState] = useState<"loading" | "loaded" | "error">(scenario === "notes-loading" ? "loading" : scenario === "notes-read-failure" ? "error" : "loaded");
  const [notes, setNotes] = useState(scenario === "notes-empty" ? [] : [structuredClone(evidenceNote)]);
  const [body, setBody] = useState(scenario === "append-failure" ? "示例补充说明：文件日期与识别结果一致。" : "");
  const [actionError, setActionError] = useState<string | undefined>(scenario === "append-failure" ? "示例：追加未完成，输入内容已保留。" : undefined);
  const [notice, setNotice] = useState<string>();
  const [failedOnce, setFailedOnce] = useState(false);
  const [revisionBusy, setRevisionBusy] = useState(false);
  const table = scenario === "source-empty" ? { ...evidencePreview, headers: [], rows: [], row_count: 0, truncated: false } : evidencePreview;
  const rows = table.rows.map((row, index) => ({ row, ordinal: index + 1 })).filter(({ row }) => row.some(value => value.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())));
  const retrySource = () => { setSourceError(undefined); setSourceLoading(false); setSourceOpen(true); };
  const pageSize = 8;
  return <main className={css.reference}>
    <PageHeader eyebrow="导入审核 · 辅助证据" title="源表与批次备注" description="先核对源表，再补充文件级说明。修订保留历史，源表保持只读。" />
    <div className={css.referenceGrid}>
      <SourcePreviewView fileName="fictional-business-2026-09-12.csv" open={sourceOpen} loading={sourceLoading} error={sourceError} table={sourceLoading || sourceError ? undefined : table}
        query={query} page={page} totalPages={Math.max(1, Math.ceil(rows.length / pageSize))} filteredCount={rows.length} visibleRows={rows.slice((page - 1) * pageSize, page * pageSize)}
        onToggle={() => setSourceOpen(!sourceOpen)} onRetry={retrySource} onQueryChange={value => { setQuery(value); setPage(1); }} onPageChange={setPage} />
      <BatchNotesView batchId={81} contentId="demo-batch-notes" expanded={expanded} loadState={loadState} notes={loadState === "loaded" ? notes : []} body={body}
        busy={revisionBusy || loadState !== "loaded"} busyAction={revisionBusy ? "revise" : undefined} loadError="示例：批次备注暂时无法读取。" actionError={actionError} notice={notice}
        onToggle={() => setExpanded(!expanded)} onRetry={() => setLoadState("loaded")} onBodyChange={setBody}
        onAppend={event => { event.preventDefault(); if (!body.trim()) return; setNotes([...notes, { ...evidenceNote, note_id: 802 + notes.length, note_key: `demo-batch-note-${notes.length + 1}`, body: body.trim() }]); setBody(""); setActionError(undefined); setNotice("已追加虚构备注，仅更新样板内存。 "); }}
        renderRevision={note => <NoteRevisionEditor busy={revisionBusy} internalOnly note={note} onRevise={async (_, value) => {
          if (scenario === "revision-saving") { setRevisionBusy(true); await new Promise<void>(() => { /* persistent loading story; no request */ }); }
          if (scenario === "revision-failure" && !failedOnce) { setFailedOnce(true); throw new Error("示例：修订未完成，内容已保留，可重试。 "); }
          setNotes(current => current.map(item => item.note_key === note.note_key ? { ...item, body: value.trim(), note_id: item.note_id + 100, revision_number: item.revision_number + 1 } : item));
          setNotice("已追加虚构修订，仅更新样板内存。 ");
        }} />}
      />
    </div>
    <p className={css.referenceDisclaimer}>文件内容、账号、批次与备注均为虚构。搜索和分页只覆盖预览；追加与修订仅更新当前样板内存，不请求 API，不修改真实文件或历史。</p>
  </main>;
}
const meta = { title: "Pages/Import Evidence", component: EvidencePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof EvidencePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const SourceCollapsed: Story = { args: { scenario: "source-collapsed" } };
export const SourceLoading: Story = { args: { scenario: "source-loading" } };
export const SourceReadFailure: Story = { args: { scenario: "source-read-failure" } };
export const SourceEmpty: Story = { args: { scenario: "source-empty" } };
export const NotesCollapsed: Story = { args: { scenario: "notes-collapsed" } };
export const NotesLoading: Story = { args: { scenario: "notes-loading" } };
export const NotesReadFailure: Story = { args: { scenario: "notes-read-failure" } };
export const NotesEmpty: Story = { args: { scenario: "notes-empty" } };
export const AppendFailure: Story = { args: { scenario: "append-failure" } };
export const RevisionEditing: Story = { args: { scenario: "revision-editing" } };
export const RevisionFailure: Story = { args: { scenario: "revision-failure" } };
export const RevisionSaving: Story = { args: { scenario: "revision-saving" } };
