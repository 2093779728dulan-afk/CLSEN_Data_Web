import type { ReviewIssue } from "../../api/types";
import { readyDraftWorkspace } from "./DraftReviewView.fixtures";

export type IssueScenario = "reference" | "warning" | "blocking" | "handled" | "optional-note" | "long-values" | "saving" | "save-failure";
export function issueReviewWorkspace(scenario: IssueScenario = "reference") {
  const workspace = structuredClone(readyDraftWorkspace());
  workspace.head.status = "draft"; workspace.head.review_revision = 1;
  const warning: ReviewIssue = {
    id: 701, row_id: 101, severity: "warning", field_name: "sales", rule_code: "sales.changed",
    message: "销售额与源文件不同", source_value: "40.00", processed_value: "42.50", requires_note: true,
    details: null, created_at: "2026-08-10T03:31:00Z",
    review: { state: "open", actor_user_id: null, actor_username: null, comment: null, event_id: null, event_type: null, occurred_at: null },
  };
  const blocking: ReviewIssue = { ...structuredClone(warning), id: 702, severity: "blocking", row_id: null, field_name: null, rule_code: "totals.mismatch", message: "报表合计与明细不一致", source_value: "40.00", processed_value: "42.50" };
  let issues = [warning, blocking];
  if (["warning", "saving", "save-failure", "optional-note"].includes(scenario)) issues = [warning];
  if (scenario === "blocking") issues = [blocking];
  if (scenario === "optional-note") { warning.requires_note = false; warning.source_value = null; warning.processed_value = 0; }
  if (scenario === "handled") {
    for (const issue of issues) issue.review = { state: issue.severity === "warning" ? "acknowledged" : "resolved", actor_user_id: 88, actor_username: "fictional-reviewer", comment: "虚构审核记录：已与原表逐项核对。", event_id: issue.id + 100, event_type: issue.severity === "warning" ? "acknowledge" : "resolve", occurred_at: "2026-08-10T04:00:00Z" };
  }
  if (scenario === "long-values") { warning.source_value = { reference: "虚构来源字段与较长补充说明".repeat(10), amount: 0 }; warning.processed_value = { reference: "虚构处理字段".repeat(10), amount: "42.50" }; blocking.row_id = 101; blocking.field_name = "sales"; }
  const validation = workspace.latest_full_validation!;
  validation.issues = issues; validation.result = "failed";
  const stage = validation.summary.stages.parse_fidelity;
  stage.warning_count = issues.filter(issue => issue.severity === "warning").length;
  stage.blocking_count = issues.filter(issue => issue.severity === "blocking").length;
  return workspace;
}
