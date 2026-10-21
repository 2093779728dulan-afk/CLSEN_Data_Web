import type { CatalogImportSummary } from "./catalogTypes";

export function workflowLabel(value: CatalogImportSummary): string {
  return {
    approved: "已批准",
    needs_attention: "需要处理",
    parse_failed: "解析失败",
    parsing: "正在解析",
    ready_for_approval: "等待批准",
    rejected: "已拒绝",
    uploaded: "等待解析",
    validated: "校验通过",
    withdrawn: "已撤回",
  }[value.status] ?? value.status;
}
