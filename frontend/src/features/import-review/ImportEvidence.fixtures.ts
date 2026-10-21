import type { ImportBatchNoteResponse, RawFilePreviewResponse } from "../../api/generated";

// Fictional source rows and note identities, shared only by stories and UI checks.
export const evidencePreview: RawFilePreviewResponse = {
  encoding: "utf-8-sig", headers: ["Seller SKU", "订购数量", "销售额", ""],
  rows: Array.from({ length: 55 }, (_, index) => [`DEMO-${String(index + 1).padStart(3, "0")}`, String(index % 7), `${(index % 7 * 18.5).toFixed(2)}`, index === 2 ? "示例待核对" : ""]),
  row_count: 55, truncated: true,
};
export const evidenceNote: ImportBatchNoteResponse = {
  author_user_id: 88, author_username: "fictional-reviewer", body: "示例：第 3 行的辅助说明需要复核，数量与金额已核对。",
  created_at: "2026-09-12T06:00:00Z", import_batch_id: 81, note_id: 801, note_key: "demo-batch-note-1",
  revision_number: 1, target_type: "import_batch", visibility: "internal",
};
