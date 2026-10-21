import { ApiRequestError } from "../../api/client";

export function analyticsError(error: unknown, fallback: string) {
  if (!(error instanceof ApiRequestError)) return { message: fallback, retry: true };
  const messages: Record<string, string> = {
    analytics_source_scope_required: "报表已导入，但账号来源范围尚未确认。请在商品主档的批量维护中完成初始化。",
    analytics_catalog_required: "商品主档尚未初始化。请先生成候选，审核款式映射并批准目录。",
    analytics_return_snapshot_required: "退货去重快照尚未建立。请从每日审核完成退货发布准备，再读取产品分析。",
    analytics_snapshot_stale: "退货快照与当前已发布报表不一致。请在每日审核更新退货发布准备；反复重读不会修复快照。",
    analytics_identity_fact_combination_invalid: "所选目录版本与事实口径不匹配，请重新选择版本或事实口径。",
    catalog_snapshot_range_out_of_bounds: "所选日期超出目录快照覆盖范围，请调整日期或切换当前事实。",
    style_analytics_unavailable: "商品分析暂不可用，请检查初始化状态；若前置已齐全，请联系管理员核对。",
  };
  if (messages[error.code]) return { message: messages[error.code], retry: false, setup: ["analytics_source_scope_required", "analytics_catalog_required", "analytics_return_snapshot_required", "analytics_snapshot_stale", "style_analytics_unavailable"].includes(error.code) };
  if (error.status === 403) return { message: "当前账号没有读取产品分析的权限。", retry: false };
  if (error.status === 404) return { message: "未找到这个稳定款式。", retry: false };
  if (error.status === 422) return { message: "筛选条件无效，请检查日期、颜色和系列。", retry: false };
  return { message: fallback, retry: true };
}

export type AnalyticsFailure = ReturnType<typeof analyticsError>;
