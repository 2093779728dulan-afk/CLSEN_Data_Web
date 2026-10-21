import type { ReviewWorkspace } from "../../api/types";
import { draftWorkspace } from "./DraftReviewView.fixtures";

export function fieldReviewWorkspace(scenario = "reference"): ReviewWorkspace {
  const workspace = structuredClone(draftWorkspace);
  const cell = workspace.rows[0]!.cells[1]!;
  cell.source = { type: "decimal", value: "39.00" };
  cell.parent_restore_options = [{ parent_version_id: 49, value: { type: "decimal", value: "40.00" } }];
  cell.source_restore_option = { source_batch_id: 11, parsed_source_row_id: 301, value: { type: "decimal", value: "39.00" } };
  cell.history = [{ id: 501, data_revision: 3, operation: "set", before: { type: "decimal", value: "40.00" }, after: cell.current, restored_field_change_id: null, restored_parent_version_id: null, restored_source_row_id: null, actor_user_id: 88, actor_username: "fictional-reviewer", reason: "虚构：核对原表后修正", occurred_at: "2026-08-10T03:00:00Z" }];
  cell.notes = [{ note_key: "fictional-field-note", note_id: 801, revision_number: 1, target_type: "field", row_id: 101, field_name: "sales", visibility: "internal", body: "虚构字段核对说明，原备注保留在历史中。", author_user_id: 88, author_username: "fictional-reviewer", review_revision: 1, created_at: "2026-08-10T03:00:00Z" }];
  if (scenario === "nullable") { workspace.fields[1]!.nullable = true; cell.current = { type: "null", value: null }; }
  if (scenario === "readonly" || scenario === "empty-records") { cell.history = []; cell.notes = []; cell.source_restore_option = null; cell.parent_restore_options = []; }
  if (scenario === "readonly") workspace.fields[1]!.editable = false;
  if (scenario === "integer") {
    workspace.fields[1] = { ...workspace.fields[1]!, name: "quantity", kind: "integer", scale: null, precision: null };
    cell.field_name = "quantity"; cell.current = { type: "integer", value: 7 }; cell.base = { type: "integer", value: 5 }; cell.source = { type: "integer", value: 5 };
    cell.parent_restore_options = []; cell.history = []; cell.notes = [];
    cell.source_restore_option!.value = cell.source;
  }
  if (scenario === "long-text") {
    workspace.fields[1] = { ...workspace.fields[1]!, name: "title", kind: "text", scale: null, precision: null, included_in_totals: false, max_length: 256 };
    cell.field_name = "title"; cell.current = { type: "text", value: "虚构长文本：带有来源说明与多个限定条件的商品标题，换行展示完整内容，不截断核对所需的原文。" };
    cell.base = { type: "text", value: "虚构基础标题" }; cell.source = { type: "text", value: "虚构原表标题" }; cell.history = []; cell.notes = []; cell.parent_restore_options = []; cell.source_restore_option!.value = cell.source;
  }
  return workspace;
}
