import type { MergePreviewResponse } from "./MergeDecisionMatrix";

export function mergePreview(kind: "business" | "return" | "identical" | "hidden" | "empty" = "business"): MergePreviewResponse {
  const conflicts = Array.from({ length: 6 }, (_, index) => {
    const common = { child_asin: `B0DEMO${index + 1}`, sku: `SAMPLE-BLUE-${index + 1}`, title: "虚构蓝色衬衫 · 商品来源说明", sales: "42.00", sessions: "12", quantity: "1", extra_note: "虚构目标备注" };
    const target_values = kind === "return" ? { return_date: "2026-09-11", order_id: `DEMO-ORDER-${index + 1}`, sku: common.sku, asin: common.child_asin, fnsku: `DEMO-${index + 1}`, quantity: "1", license_plate_number: "", reason: "虚构目标原因" } : common;
    const source_values = { ...target_values };
    if (kind !== "identical" && index !== 0) {
      if (kind === "return") Object.assign(source_values, { reason: "虚构来源原因" });
      else Object.assign(source_values, { sales: "43.00", extra_note: "虚构来源备注，需核对原表" });
    }
    if (kind === "hidden" && index === 0) Object.assign(source_values, { child_asin: "B0SOURCE", sku: "SOURCE-SKU", title: "虚构来源完整标题，包含完整说明", sales: "75.00", sessions: "24", quantity: "2", extra_note: "第七个差异字段，必须在全部字段中可查看" });
    return { target_row_id: 101 + index, source_row_id: 201 + index, target_row_ordinal: 1 + index, source_row_ordinal: 11 + index, target_values, source_values };
  });
  return { report_type: kind === "return" ? "return_report" : "business_report", target_version_id: 51, source_kind: "parse_baseline", source_id: 61, conflicts: kind === "empty" ? [] : conflicts };
}
