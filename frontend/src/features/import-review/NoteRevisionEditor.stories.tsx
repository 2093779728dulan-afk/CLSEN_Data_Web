import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import type { ReviewNote } from "../../api/types";
import { NoteRevisionEditor } from "./NoteRevisionEditor";
import css from "./NoteRevisionEditor.module.css";

type Scenario = "reference" | "batch" | "row" | "field" | "viewer-visible" | "long-content" | "empty" | "saving" | "save-failure";
function NoteRevision({ scenario = "reference" }: { scenario?: Scenario }) {
  const scope = scenario === "batch" ? "批次" : scenario === "row" ? "行" : scenario === "field" ? "字段" : "版本";
  const [note, setNote] = useState<ReviewNote>(() => ({
    note_key: "fictional-note-1", note_id: 801, revision_number: 1, target_type: scenario === "row" ? "row" : scenario === "field" ? "field" : "version",
    row_id: scenario === "row" || scenario === "field" ? 101 : null, field_name: scenario === "field" ? "sales" : null,
    body: scenario === "long-content" ? "虚构审核依据：这段说明包含需要保留的原表核对记录。\n".repeat(12) : "虚构审核说明：已核对来源，差异待确认。",
    visibility: scenario === "viewer-visible" ? "viewer_visible" : "internal", author_user_id: 88, author_username: "fictional-reviewer", review_revision: 1, created_at: "2026-08-10T03:00:00Z",
  }));
  const attempts = useRef(0);
  return <main className={css.stage}><h1>备注修订</h1><p>共用编辑器的虚构样板；保存只追加本地修订，不请求实际 API。</p><article className={css.record} aria-label={`${scope}备注`}>
    <header className={css.identity}><strong>{scope}备注{scenario === "row" || scenario === "field" ? " · 行 #101" : ""}{scenario === "field" ? " · sales" : ""}</strong><span>{note.author_username} · 第 {note.revision_number} 版 · {scenario === "batch" || note.visibility === "internal" ? "仅审核人员" : "查看人员可见"}</span></header>
    <p>{note.body}</p>
    <NoteRevisionEditor note={note} busy={false} internalOnly={scenario === "batch"} onRevise={async (_previous, body, visibility) => {
      attempts.current += 1;
      if (scenario === "saving") await new Promise<void>(() => {});
      if (scenario === "save-failure" && attempts.current === 1) throw new Error("示例：修订响应未确认。");
      setNote(current => ({ ...current, body, visibility, note_id: current.note_id + 1, revision_number: current.revision_number + 1, review_revision: current.review_revision + 1 }));
    }} />
  </article></main>;
}
const meta = { title: "Patterns/Note Revision", component: NoteRevision, parameters: { layout: "fullscreen" } } satisfies Meta<typeof NoteRevision>;
export default meta; type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Batch: Story = { args: { scenario: "batch" } };
export const Row: Story = { args: { scenario: "row" } };
export const Field: Story = { args: { scenario: "field" } };
export const ViewerVisible: Story = { args: { scenario: "viewer-visible" } };
export const LongContent: Story = { args: { scenario: "long-content" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const Saving: Story = { args: { scenario: "saving" } };
export const SaveFailure: Story = { args: { scenario: "save-failure" } };
