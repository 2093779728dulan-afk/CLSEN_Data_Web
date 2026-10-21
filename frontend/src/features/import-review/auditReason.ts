import type { Principal, ReportType } from "../../api/types";

export type AuditOperator = Pick<Principal, "display_name" | "id" | "username">;

export function reportTypeAuditLabel(reportType: ReportType) {
  return reportType === "business_report" ? "经营报告" : "退货报告";
}

export function auditOperatorLabel(operator: AuditOperator) {
  return `${operator.display_name}（${operator.username} / 用户 #${operator.id}）`;
}

export function defaultAuditReason(
  operator: AuditOperator | undefined,
  action: string,
  source: string,
) {
  if (!operator) return "";
  return `操作人：${auditOperatorLabel(operator)}；操作：${action}；来源：${source}。`;
}
