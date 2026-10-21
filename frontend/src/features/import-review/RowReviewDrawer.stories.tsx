import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import type { ComponentProps } from "react";
import { StatusMessage } from "../../design-system";
import { ReviewDataTable } from "./ReviewDataTable";
import { rowReviewWorkspace } from "./RowReviewDrawer.fixtures";
import styles from "./CellReviewDrawer.module.css";
type Scenario = "reference" | "nullable" | "no-source" | "add-saving" | "add-failure" | "exclude" | "restore" | "source-deleted" | "manual-deleted" | "empty-records" | "state-saving" | "state-failure" | "note-editing" | "note-failure";
function RowReview({ scenario = "reference" }: { scenario?: Scenario }) {
  const [workspace, setWorkspace] = useState(() => rowReviewWorkspace(scenario));
  const [busy, setBusy] = useState(false); const attempts = useRef(0); const [notice, setNotice] = useState<string>();
  const act = async (update: () => void) => {
    attempts.current += 1; setBusy(true);
    try {
      if (scenario.endsWith("saving")) await new Promise<void>(() => {});
      if (scenario.endsWith("failure") && attempts.current === 1) throw new Error("示例：保存响应未确认，内容保留。请核对后重试。");
      update(); setNotice("本地样板操作已记录，没有真实数据写入。");
    } finally { setBusy(false); }
  };
  const onAddRow: ComponentProps<typeof ReviewDataTable>["onAddRow"] = (_batch, values) => act(() => setWorkspace(w => {
    const next = structuredClone(w); next.head.data_revision += 1;
    next.rows.push({ row_id: 102, row_ordinal: 2, logical_row_id: "22222222-2222-4222-8222-222222222222", base_row_id: null, original_parsed_source_row_id: null, row_state: "active", notes: [], history: [], cells: next.fields.map(field => ({ field_name: field.name, current: values[field.name]!, base: null, source: null, changed_from_base: true, changed_from_source: true, history: [], notes: [], parent_restore_options: [], source_restore_option: null })) });
    next.pagination.total_rows += 1; return next;
  }));
  const reject = () => Promise.reject(new Error("当前样板不执行无关字段或校验操作。"));
  return <main className={styles.stage}><h1>行补录与状态管理</h1><p>从新增纠错行或行状态按钮进入；数据、来源和保存回调全部为虚构。</p>
    {notice && <StatusMessage kind="success" title="本地样板结果">{notice}</StatusMessage>}
    <ReviewDataTable workspace={workspace} busy={busy} operator={{ id: 88, username: "fictional-reviewer", display_name: "虚构审核员" }}
      onAddRow={onAddRow} onPageChange={() => {}} onSetField={reject} onRestoreField={reject} onAddCellNote={reject} onReviewIssue={reject}
      onChangeRowState={(row, operation, reason) => act(() => setWorkspace(w => { const next = structuredClone(w); const r = next.rows.find(r => r.row_id === row.row_id)!; r.row_state = operation === "exclude" ? "excluded" : "active"; next.head.data_revision += 1; r.history.unshift({ id: 602, operation, before: { row_state: row.row_state }, after: { row_state: r.row_state }, data_revision: next.head.data_revision, source_batch_id: null, actor_user_id: 88, actor_username: "fictional-reviewer", reason, occurred_at: "2026-08-10T04:00:00Z" }); return next; }))}
      onAddRowNote={(row, body, visibility) => act(() => setWorkspace(w => { const next = structuredClone(w); next.head.review_revision += 1; next.rows.find(r => r.row_id === row.row_id)!.notes.push({ note_key: "fictional-added-row-note", note_id: 812, revision_number: 1, target_type: "row", row_id: row.row_id, field_name: null, body, visibility, author_user_id: 88, author_username: "fictional-reviewer", review_revision: next.head.review_revision, created_at: "2026-08-10T04:00:00Z" }); return next; }))}
      onReviseNote={(note, body, visibility) => act(() => setWorkspace(w => { const next = structuredClone(w); const n = next.rows.flatMap(r => r.notes).find(n => n.note_key === note.note_key)!; n.body = body; n.visibility = visibility; n.note_id += 2; n.revision_number += 1; next.head.review_revision += 1; return next; }))} />
  </main>;
}
const meta = { title: "Patterns/Row Review", component: RowReview, parameters: { layout: "fullscreen" } } satisfies Meta<typeof RowReview>;
export default meta; type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Nullable: Story = { args: { scenario: "nullable" } };
export const NoSource: Story = { args: { scenario: "no-source" } };
export const AddSaving: Story = { args: { scenario: "add-saving" } };
export const AddFailure: Story = { args: { scenario: "add-failure" } };
export const Exclude: Story = { args: { scenario: "exclude" } };
export const Restore: Story = { args: { scenario: "restore" } };
export const SourceDeleted: Story = { args: { scenario: "source-deleted" } };
export const ManualDeleted: Story = { args: { scenario: "manual-deleted" } };
export const EmptyRecords: Story = { args: { scenario: "empty-records" } };
export const StateSaving: Story = { args: { scenario: "state-saving" } };
export const StateFailure: Story = { args: { scenario: "state-failure" } };
export const NoteEditing: Story = { args: { scenario: "note-editing" } };
export const NoteFailure: Story = { args: { scenario: "note-failure" } };
