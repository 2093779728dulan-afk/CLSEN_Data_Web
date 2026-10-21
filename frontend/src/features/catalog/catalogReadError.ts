import { ApiRequestError } from "../../api/client";

export function catalogReadError(error: unknown, fallback: string) {
  if (!(error instanceof ApiRequestError)) return { message: fallback, retry: true, setup: false };
  if (error.status === 403) return { message: "当前账号没有查看此商品主档页面的权限，请联系管理员。", retry: false, setup: false };
  if (error.code === "catalog_snapshot_unavailable") return {
    message: "当前来源或退货快照尚不可用，暂时无法核对待归属商品。请先查看准备状态并完成缺失步骤；反复重新读取不能补齐前置条件。",
    retry: false, setup: true,
  };
  if (error.status === 422 || error.code === "catalog_unmatched_range_invalid") return { message: "查询日期或分页条件无效，请调整筛选范围后重新打开页面。", retry: false, setup: false };
  if (error.status === 404) return { message: "未找到请求的商品主档记录，请返回商品主档核对。", retry: false, setup: false };
  return { message: fallback, retry: error.status >= 500 || error.status === 429, setup: false };
}
