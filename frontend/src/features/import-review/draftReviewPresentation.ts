import { ApiRequestError } from "../../api/client";
import type { ReportType, ReviewWorkspace, ValidationRun } from "../../api/types";

export function reportTypeLabel(reportType: ReportType) {
  return reportType === "business_report" ? "经营报告" : "退货报告";
}

export function validationCounts(validation: ValidationRun, workspace?: ReviewWorkspace) {
  const workspaceValidation = workspace?.latest_full_validation;
  if (
    workspaceValidation?.id === validation.validation_run_id
    && workspaceValidation.issues.length > 0
  ) {
    return workspaceValidation.issues.reduce(
      (counts, issue) => ({
        blocking: counts.blocking + (issue.severity === "blocking" && issue.review.state !== "resolved" ? 1 : 0),
        warning: counts.warning + (issue.severity === "warning" && issue.review.state === "open" ? 1 : 0),
      }),
      { blocking: 0, warning: 0 },
    );
  }
  const stages = Object.values(validation.summary.stages);
  return stages.reduce(
    (counts, stage) => ({
      blocking: counts.blocking + stage.blocking_count,
      warning: counts.warning + stage.warning_count,
    }),
    { blocking: 0, warning: 0 },
  );
}

export function errorMessage(reason: unknown) {
  if (reason instanceof ApiRequestError && reason.status === 409) {
    return "草稿或发布指针已变化。请刷新当前日期后再继续，系统没有覆盖任何数据。";
  }
  return reason instanceof Error ? reason.message : "操作未完成。";
}
