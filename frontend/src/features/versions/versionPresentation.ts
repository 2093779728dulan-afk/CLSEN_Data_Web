import type { VersionLineageResponse, VersionSummaryResponse } from "../../api/generated";
import type { ReportType } from "../../api/types";

export function reportTypeLabel(reportType: ReportType) {
  return reportType === "business_report" ? "经营报告" : "退货报告";
}

export function statusLabel(version: VersionSummaryResponse) {
  if (version.is_current_publication) return "当前发布";
  if (version.is_active_draft) return "活动草稿";
  if (version.status === "ready_for_publish") return "待发布";
  if (version.status === "published") return "历史发布";
  if (version.status === "discarded") return "已废弃";
  return "草稿";
}

export function formatTimestamp(value: string | null) {
  if (!value) return "—";
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    hour12: false,
    timeStyle: "short",
  }).format(instant);
}

export function lineageLabel(lineage: VersionLineageResponse) {
  const labels: Record<VersionLineageResponse["lineage_type"], string> = {
    base: "基础版本",
    draft_predecessor: "草稿前序",
    merge_source: "合并来源",
    merge_target: "合并目标",
    moved_source: "跨日来源",
  };
  return `${labels[lineage.lineage_type]} · v${lineage.version_no}`;
}
