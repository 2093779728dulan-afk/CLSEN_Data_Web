import type { InspectionResponse, SuccessfulParse, VersionSummary } from "../../api/types";
import type { UploadSession } from "./workflowTypes";

export const intakeUpload: UploadSession = { fileName: "business-2026-09-12.csv", upload: { batch_id: 81 } };
export const intakeInspection: InspectionResponse = { status: "recognized", report_type: "business_report", report_date: "2026-09-12", encoding: "utf-8-sig", ruleset_version: "business_report_v1", issue_codes: [] };
export const intakeParse: SuccessfulParse = { batch_id: 81, parse_attempt_id: 91, parse_baseline_id: 101, confirmation_revision: 1, report_type: "business_report", source_row_count: 2 };
export const intakeTarget: VersionSummary = {
  dataset_id: 41, version_id: 51, version_no: 4, status: "published", report_date: "2026-09-12", report_type: "business_report",
  created_at: "2026-09-12T04:00:00Z", published_at: "2026-09-12T05:00:00Z", sealed_at: "2026-09-12T05:00:00Z",
  data_revision: 2, review_revision: 1, dedup_publication_revision: null, publication_revision: null, draft_pointed_at: null, is_current_publication: true, is_active_draft: false,
};
