import type { ReviewWorkspace, ValidationRun } from "../../api/types";
import type { DraftReviewContext } from "./workflowTypes";

export const draftWorkspace: ReviewWorkspace = {
  head: {
    dataset_id: 41,
    version_id: 51,
    version_no: 2,
    status: "draft",
    data_revision: 3,
    review_revision: 1,
    pointed_at: "2026-08-10T02:00:00Z",
  },
  report_date: "2026-08-10",
  report_type: "business_report",
  ruleset_version: "business_report_v1",
  publication_mode: "ordinary",
  published_move: null,
  source_batches: [{ batch_id: 11 }],
  fields: [
    { name: "sku", kind: "text", nullable: false, editable: true, required_on_add: true, included_in_totals: false, max_length: 64, precision: null, scale: null, ascii_only: false },
    { name: "sales", kind: "decimal", nullable: false, editable: true, required_on_add: true, included_in_totals: true, max_length: null, precision: 12, scale: 2, ascii_only: false },
  ],
  rows: [{
    row_id: 101,
    logical_row_id: "11111111-1111-4111-8111-111111111111",
    row_ordinal: 1,
    row_state: "active",
    base_row_id: 201,
    original_parsed_source_row_id: 301,
    cells: [
      { field_name: "sku", current: { type: "text", value: "A-01" }, base: { type: "text", value: "A-01" }, source: { type: "text", value: "A-01" }, changed_from_base: false, changed_from_source: false, parent_restore_options: [], source_restore_option: { source_batch_id: 11, parsed_source_row_id: 301, value: { type: "text", value: "A-01" } }, history: [], notes: [] },
      { field_name: "sales", current: { type: "decimal", value: "42.50" }, base: { type: "decimal", value: "40.00" }, source: { type: "decimal", value: "40.00" }, changed_from_base: true, changed_from_source: true, parent_restore_options: [], source_restore_option: { source_batch_id: 11, parsed_source_row_id: 301, value: { type: "decimal", value: "40.00" } }, history: [], notes: [] },
    ],
    history: [],
    notes: [],
  }],
  version_notes: [{
    note_key: "version-note-1",
    note_id: 801,
    revision_number: 1,
    target_type: "version",
    row_id: null,
    field_name: null,
    visibility: "internal",
    body: "初次审核说明",
    author_user_id: 1,
    author_username: "TCJ",
    review_revision: 1,
    created_at: "2026-08-10T03:00:00Z",
  }],
  latest_full_validation: null,
  pagination: { page: 1, page_size: 50, total_rows: 1, total_pages: 1 },
};

export function readyDraftWorkspace(): ReviewWorkspace {
  return {
    ...draftWorkspace,
    head: {
      ...draftWorkspace.head,
      status: "ready_for_publish",
      review_revision: 2,
    },
    latest_full_validation: {
      id: 901,
      data_revision: draftWorkspace.head.data_revision,
      ruleset_version: draftWorkspace.ruleset_version,
      status: "succeeded",
      result: "passed",
      data_digest: "d".repeat(64),
      summary: {
        schema_version: 1,
        report_date: draftWorkspace.report_date,
        report_type: draftWorkspace.report_type,
        row_count: 1,
        totals: { sales: "42.50" },
        stages: {
          parse_fidelity: {
            data_digest: "a".repeat(64),
            row_count: 1,
            totals: { sales: "42.50" },
            warning_count: 0,
            blocking_count: 0,
          },
          draft_explainability: {
            data_digest: "b".repeat(64),
            row_count: 1,
            totals: { sales: "42.50" },
            warning_count: 0,
            blocking_count: 0,
          },
        },
      },
      started_at: "2026-08-10T03:30:00Z",
      completed_at: "2026-08-10T03:31:00Z",
      is_current: true,
      issues: [],
    },
  };
}


export function draftContext(workspace = draftWorkspace): DraftReviewContext {
 return { head: workspace.head, publicationMode: "ordinary", publishedMove: null, reportDate: workspace.report_date, reportType: workspace.report_type, rulesetVersion: workspace.ruleset_version, sourceRowCount: workspace.pagination.total_rows, sourceBatchId: 11, publication: { version_id: null, published_at: null } };
}
export function validationFor(workspace: ReviewWorkspace): ValidationRun | undefined {
 const v = workspace.latest_full_validation;
 return v ? { validation_run_id: v.id, version_id: workspace.head.version_id, data_revision: v.data_revision, status: v.status, result: v.result, data_digest: v.data_digest, summary: v.summary } : undefined;
}
