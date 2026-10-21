import type { DateWorkbenchResponse } from "../../api/generated";

// Fictional Storybook and browser-test data; never requests a business API.
const parentAsinId = "3e2d27a9-f565-4fc8-a8d2-cbd94d8f3594";
const skuId = "4e2d27a9-f565-4fc8-a8d2-cbd94d8f3594";
const columnId = "5e2d27a9-f565-4fc8-a8d2-cbd94d8f3594";
const sessionsId = "6e2d27a9-f565-4fc8-a8d2-cbd94d8f3594";
const salesId = "7e2d27a9-f565-4fc8-a8d2-cbd94d8f3594";
const extensionId = "8e2d27a9-f565-4fc8-a8d2-cbd94d8f3594";

const draftColumns = [
  { column_id: parentAsinId, display_order: 0, editable: false, is_key: true, participates_in_statistics: false, source_header: "Parent ASIN", standard_field_name: "parent_asin", value_kind: "text" as const },
  { column_id: skuId, display_order: 1, editable: true, is_key: true, participates_in_statistics: false, source_header: "SKU", standard_field_name: "sku", value_kind: "text" as const },
  { column_id: columnId, display_order: 2, editable: true, is_key: false, participates_in_statistics: true, source_header: "Title", standard_field_name: "title", value_kind: "text" as const },
  { column_id: sessionsId, display_order: 3, editable: true, is_key: false, participates_in_statistics: true, source_header: "Sessions", standard_field_name: "sessions", value_kind: "integer" as const },
  { column_id: salesId, display_order: 4, editable: true, is_key: false, participates_in_statistics: true, source_header: "Sales", standard_field_name: "sales", value_kind: "decimal" as const },
  { column_id: extensionId, display_order: 5, editable: true, is_key: false, participates_in_statistics: false, source_header: "Marketplace extension", standard_field_name: null, value_kind: "text" as const },
];

export function sampleWorkbench(source: "empty" | "draft" | "published" = "published", canWrite = false, reportType: "business_report" | "return_report" = "business_report"): DateWorkbenchResponse {
  const hasDraft = source !== "empty";
  const editable = source === "draft" && canWrite;
  return {
    actions: hasDraft ? ["edit", "undo", "validate", "publish"] : ["upload"],
    columns: hasDraft ? draftColumns.map(column => ({ ...column, editable: column.editable && editable })) : [],
    head: hasDraft ? {
      data_revision: 0,
      dataset_id: 91,
      pointed_at: "2026-08-14T08:00:00Z",
      review_revision: 0,
      ruleset_version: "test-v1",
      status: source === "published" ? "published" : "draft",
      version_id: 92,
      version_no: 1,
    } : null,
    pagination: {
      page: 1,
      page_size: 50,
      total_pages: hasDraft ? 1 : 0,
      total_rows: hasDraft ? 6 : 0,
    },
    pending_upload_count: 0,
    permissions: {
      can_create_revision: source === "published" && canWrite,
      can_edit: editable,
      can_publish: editable,
      can_undo: editable,
      can_upload: canWrite,
      can_validate: editable,
    },
    report_date: "2026-09-12",
    report_type: reportType,
    rows: hasDraft ? Array.from({ length: 6 }, (_, index) => ({
      cells: [
        { base: "B0SAMPLE", cell_revision: 0, changed: false, column_id: parentAsinId, current: "B0SAMPLE", editable: false },
        { base: "SAMPLE-BLUE-M", cell_revision: 0, changed: false, column_id: skuId, current: "SAMPLE-BLUE-M", editable },
        { base: "示例蓝色衬衫 · 中码", cell_revision: 0, changed: false, column_id: columnId, current: "示例蓝色衬衫 · 中码", editable },
        { base: 12, cell_revision: 0, changed: false, column_id: sessionsId, current: 12, editable },
        { base: "34.50", cell_revision: 0, changed: false, column_id: salesId, current: "34.50", editable },
        { base: "虚构来源字段", cell_revision: 0, changed: false, column_id: extensionId, current: "虚构来源字段", editable },
      ],
      row_id: 93 + index,
      row_ordinal: 1 + index,
      row_state: "active",
    })) : [],
    source,
    tabs: [
      { report_type: "business_report", source: reportType === "business_report" ? source : "published" },
      { report_type: "return_report", source: reportType === "return_report" ? source : "empty" },
    ],
    validation: null,
  };
}
