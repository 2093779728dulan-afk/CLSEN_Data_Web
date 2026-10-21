import type { CalendarDay, CalendarEntry } from "../api/types";

export const reviewEntries: CalendarEntry[] = [
  { report_date: "2026-08-10", dataset_id: 41, report_type: "business_report", status: "draft", version_id: 51, version_no: 2 },
  { report_date: "2026-08-10", dataset_id: 41, report_type: "business_report", status: "published", version_id: 42, version_no: 1 },
  { report_date: "2026-08-10", dataset_id: 61, report_type: "return_report", status: "ready_for_publish", version_id: 62, version_no: 3 },
];
export const reviewDays: CalendarDay[] = [
  { report_date: "2026-08-09", status: "red", published_report_types: [], draft_report_types: ["business_report"], reasons: ["blocking_issues"] },
  { report_date: "2026-08-10", status: "yellow", published_report_types: ["business_report"], draft_report_types: ["business_report", "return_report"], reasons: [] },
  { report_date: "2026-08-11", status: "blue", published_report_types: ["business_report"], draft_report_types: [], reasons: [] },
  { report_date: "2026-08-12", status: "green", published_report_types: ["business_report", "return_report"], draft_report_types: [], reasons: [] },
];
