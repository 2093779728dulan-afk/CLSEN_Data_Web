import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import type { ComponentProps } from "react";
import { StatusMessage } from "../../design-system";
import { ReviewDataTable } from "./ReviewDataTable";
import { fieldReviewWorkspace } from "./CellReviewDrawer.fixtures";
import styles from "./CellReviewDrawer.module.css";

type Scenario = "reference" | "nullable" | "readonly" | "integer" | "empty-records" | "long-text" | "saving" | "save-failure" | "note-editing" | "note-failure";
function FieldReview({ scenario = "reference" }: { scenario?: Scenario }) {
  const [workspace, setWorkspace] = useState(() => fieldReviewWorkspace(scenario));
  const [busy, setBusy] = useState(false); const attempts = useRef(0);
  const [notice, setNotice] = useState<string>();
  const act = async (update: () => void) => {
    attempts.current += 1; setBusy(true);
    try {
      if (scenario === "saving") await new Promise<void>(() => {});
      if (["save-failure", "note-failure"].includes(scenario) && attempts.current === 1) throw new Error("示例：保存响应未确认，编辑内容保留。请核对后重试。");
      update(); setNotice("样板操作已记录；没有真实数据写入。");
    } finally { setBusy(false); }
  };
  const onSetField: ComponentProps<typeof ReviewDataTable>["onSetField"] = (_row, cell, value) => act(() => setWorkspace(current => {
    const next = structuredClone(current); const target = next.rows[0]!.cells.find(item => item.field_name === cell.field_name)!;
    target.current = value; target.changed_from_source = JSON.stringify(value) !== JSON.stringify(target.source);
    next.head.data_revision += 1; return next;
  }));
  const onRestoreField: ComponentProps<typeof ReviewDataTable>["onRestoreField"] = (_row, cell, source) => {
    const value = source.source_kind === "source" ? cell.source_restore_option!.value : source.source_kind === "parent" ? cell.parent_restore_options.find(item => item.parent_version_id === source.parent_version_id)!.value : cell.history.find(item => item.id === source.field_change_id)!.before;
    return onSetField(_row, cell, value, "虚构恢复依据");
  };
  const reject = () => Promise.reject(new Error("当前样板不执行无关行或问题操作。"));
  return <main className={styles.stage}><h1>字段对照与修正</h1><p>点击金额或数量字段查看；源值、历史与回调全部为虚构，不发送 API。</p>
    {notice && <StatusMessage kind="success" title="本地样板结果">{notice}</StatusMessage>}
    <ReviewDataTable workspace={workspace} busy={busy} operator={{ id: 88, username: "fictional-reviewer", display_name: "虚构审核员" }}
      onSetField={onSetField} onRestoreField={onRestoreField} onPageChange={() => {}} onAddRow={reject} onAddRowNote={reject} onChangeRowState={reject} onReviewIssue={reject}
      onAddCellNote={(_row, cell, body, visibility) => act(() => setWorkspace(current => {
        const next = structuredClone(current); next.rows[0]!.cells.find(item => item.field_name === cell.field_name)!.notes.push({ note_key: "fictional-added-note", note_id: 802, revision_number: 1, target_type: "field", row_id: 101, field_name: cell.field_name, visibility, body, author_user_id: 88, author_username: "fictional-reviewer", review_revision: 2, created_at: "2026-08-10T04:00:00Z" }); return next;
      }))}
      onReviseNote={(note, body, visibility) => act(() => setWorkspace(current => {
        const next = structuredClone(current); const target = next.rows[0]!.cells.flatMap(cell => cell.notes).find(item => item.note_key === note.note_key)!;
        target.body = body; target.visibility = visibility; target.revision_number += 1; target.note_id += 1; next.head.review_revision += 1; return next;
      }))} />
  </main>;
}
const meta = { title: "Patterns/Field Review", component: FieldReview, parameters: { layout: "fullscreen" } } satisfies Meta<typeof FieldReview>;
export default meta; type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Nullable: Story = { args: { scenario: "nullable" } };
export const Readonly: Story = { args: { scenario: "readonly" } };
export const Integer: Story = { args: { scenario: "integer" } };
export const EmptyRecords: Story = { args: { scenario: "empty-records" } };
export const LongText: Story = { args: { scenario: "long-text" } };
export const Saving: Story = { args: { scenario: "saving" } };
export const SaveFailure: Story = { args: { scenario: "save-failure" } };
export const NoteEditing: Story = { args: { scenario: "note-editing" } };
export const NoteFailure: Story = { args: { scenario: "note-failure" } };
