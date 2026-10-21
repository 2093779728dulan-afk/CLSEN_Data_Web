import type { ReviewWorkspace } from "../../api/types";
import { draftWorkspace } from "./DraftReviewView.fixtures";
export function rowReviewWorkspace(scenario = "reference"): ReviewWorkspace {
  const w = structuredClone(draftWorkspace); const row = w.rows[0]!;
  if (scenario === "no-source") { w.source_batches = []; row.cells.forEach(c => { c.source_restore_option = null; }); }
  if (scenario === "nullable") {
    w.fields.push({ ...w.fields[0]!, name: "quantity", kind: "integer", nullable: true, required_on_add: false, max_length: null });
  }
  if (scenario === "restore") row.row_state = "excluded";
  if (["source-deleted", "manual-deleted"].includes(scenario)) row.row_state = "deleted";
  if (scenario === "manual-deleted") { row.base_row_id = null; row.original_parsed_source_row_id = null; }
  if (!["reference", "nullable", "no-source", "add-saving", "add-failure", "empty-records"].includes(scenario)) {
    row.notes = [{ ...w.version_notes[0]!, note_key: "fictional-row-note", note_id: 811, target_type: "row", row_id: 101, field_name: null, body: "虚构行核对说明，保留此前修订。", author_user_id: 88, author_username: "fictional-reviewer" }];
    row.history = [{ id: 601, operation: row.row_state === "active" ? "restore" : "exclude", before: { row_state: "excluded" }, after: { row_state: row.row_state }, source_batch_id: 11, data_revision: 3, actor_user_id: 88, actor_username: "fictional-reviewer", reason: "虚构历史：核对重复来源与合计", occurred_at: "2026-08-10T03:00:00Z" }];
  }
  return w;
}
