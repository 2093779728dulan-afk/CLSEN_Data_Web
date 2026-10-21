import type { ReviewCell, ReviewFieldContract, ReviewWorkspace } from "../../api/types";
import { fieldReviewWorkspace } from "./CellReviewDrawer.fixtures";
type ReviewValue = ReviewCell["current"];

export function dataTableWorkspace(scenario = "reference", page = 1, pageSize = 6, totalRows = 12): ReviewWorkspace {
  const workspace = fieldReviewWorkspace();
  const textField = workspace.fields[0]!;
  workspace.fields = [textField, { ...textField, name: "asin" }, { ...textField, name: "title", required_on_add: false, max_length: 256 }, workspace.fields[1]!, { ...workspace.fields[1]!, name: "units", kind: "integer", precision: null, scale: null }, { ...workspace.fields[1]!, name: "refund", nullable: true }];
  const originalRow = workspace.rows[0]!;
  workspace.rows = Array.from({ length: Math.min(pageSize, Math.max(0, totalRows - (page - 1) * pageSize)) }, (_, index) => {
    const ordinal = (page - 1) * pageSize + index + 1;
    const row = { ...structuredClone(originalRow), row_id: 100 + ordinal, row_ordinal: ordinal, logical_row_id: `11111111-1111-4111-8111-${String(ordinal).padStart(12, "0")}`, base_row_id: 200 + ordinal, original_parsed_source_row_id: 300 + ordinal, row_state: index === 2 ? "excluded" as const : index === 4 ? "deleted" as const : "active" as const };
    row.cells = workspace.fields.map((field: ReviewFieldContract) => {
      let current: ReviewValue;
      if (field.name === "sku") current = { type: "text", value: `A-${String(ordinal).padStart(2, "0")}` };
      else if (field.name === "asin") current = { type: "text", value: `B0DEMO${String(ordinal).padStart(4, "0")}` };
      else if (field.name === "title") current = { type: "text", value: scenario === "long-values" ? "虚构商品标题：带有多种颜色、尺寸及来源限定信息的完整长文本，用于验证内部滚动与抽屉完整显示。" : `虚构轻量衬衫 ${ordinal}` };
      else if (field.name === "units") current = { type: "integer", value: ordinal * 3 };
      else if (field.name === "refund") current = { type: "null", value: null };
      else current = { type: "decimal", value: (ordinal * 10 + 2.5).toFixed(2) };
      const changed = scenario !== "unchanged" && field.name === "sales" && index !== 5;
      const sourceChanged = changed && index !== 1;
      const base: ReviewValue = changed ? { type: "decimal", value: (ordinal * 10).toFixed(2) } : current;
      const source: ReviewValue = sourceChanged ? { type: "decimal", value: (ordinal * 10 - 1).toFixed(2) } : current;
      return { field_name: field.name, current, base, source, changed_from_base: changed, changed_from_source: sourceChanged, parent_restore_options: changed ? [{ parent_version_id: 49, value: base }] : [], source_restore_option: { source_batch_id: 11, parsed_source_row_id: 300 + ordinal, value: source }, history: [], notes: [] };
    });
    return row;
  });
  workspace.latest_full_validation = null;
  workspace.version_notes = [];
  workspace.pagination = { page, page_size: pageSize, total_rows: totalRows, total_pages: Math.ceil(totalRows / pageSize) };
  if (scenario === "empty") { workspace.rows = []; workspace.pagination = { page: 1, page_size: 6, total_rows: 0, total_pages: 0 }; }
  return workspace;
}
