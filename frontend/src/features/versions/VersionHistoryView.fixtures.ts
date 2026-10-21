import type { VersionDetailResponse, VersionSummaryResponse } from "../../api/generated";

// Fictional stories/browser-check data.
export const current: VersionSummaryResponse = {
  dataset_id: 41,
  version_id: 53,
  report_date: "2026-09-12",
  report_type: "business_report",
  version_no: 3,
  status: "published",
  data_revision: 2,
  review_revision: 3,
  dedup_publication_revision: null,
  created_at: "2026-09-12T01:00:00Z",
  sealed_at: "2026-09-12T03:00:00Z",
  is_current_publication: true,
  published_at: "2026-09-12T03:00:00Z",
  publication_revision: null,
  is_active_draft: false,
  draft_pointed_at: null,
};

export const historical: VersionSummaryResponse = {
  ...current,
  version_id: 51,
  version_no: 1,
  created_at: "2026-09-11T01:00:00Z",
  sealed_at: "2026-09-11T03:00:00Z",
  is_current_publication: false,
  published_at: null,
};

export const draft: VersionSummaryResponse = {
  ...current,
  version_id: 54,
  version_no: 4,
  status: "draft",
  sealed_at: null,
  is_current_publication: false,
  published_at: null,
  is_active_draft: true,
  draft_pointed_at: "2026-09-12T04:00:00Z",
};

export function detailFor(version: VersionSummaryResponse = current): VersionDetailResponse {
  return {
    ...version,
    parents: [{
      dataset_id: 41,
      version_id: 51,
      report_date: "2026-09-12",
      report_type: "business_report",
      version_no: 1,
      status: "published",
      lineage_type: "base",
      lineage_ordinal: 0,
    }],
    children: [],
    viewer_visible_notes: [{
      note_key: "version-note",
      revision_number: 2,
      body: "虚构备注：本示例已逐项核对",
      created_at: "2026-09-12T02:30:00Z",
    }],
  };
}
