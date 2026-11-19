import type { Kind, Source } from "./types";

export type ProductionInput = {
  date: string; lines: { sku_id: string; expected_units: string }[]; sources: Source[];
  reason: string; effectiveDate: string; confirmedEdit: boolean; demand: boolean; confirm: boolean; transfer?: boolean; warehouseDispatch?: boolean; allocationOnly?: boolean;
};
export function validateProductionInput(kind: Kind, input: ProductionInput): Record<string, string> {
  const errors: Record<string, string> = {};
  function quantity(key: string, value: string, label: string) {
    if (!/^[1-9][0-9]{0,18}$/.test(value)) errors[key] = `请输入${label}，使用大于0的整数件数。`;
    else if (BigInt(value) > 9223372036854775807n) errors[key] = `${label}超出支持范围。`;
  }
  if (!input.date) errors.date = "请选择业务日期。";
  if (kind === "orders") {
    const seen = new Set<string>();
    input.lines.forEach((line, index) => {
      if (!line.sku_id) errors[`line-${index}-sku`] = `请选择第${index + 1}行SKU。`;
      else if (seen.has(line.sku_id)) errors[`line-${index}-sku`] = "此SKU已在前面的明细中，请合并数量。";
      seen.add(line.sku_id);
      quantity(`line-${index}-units`, line.expected_units, `第${index + 1}行预计数量`);
    });
  } else input.sources.forEach((source, index) => {
    if (!source.sku_id) errors[`source-${index}-sku`] = `请选择第${index + 1}项出货SKU。`;
    quantity(`source-${index}-units`, source.actual_units, `第${index + 1}项本次实际数量`);
    if (input.warehouseDispatch && source.fulfillment_mode !== "WAREHOUSE_STOCK") {
      errors[`source-${index}-allocations`] = "仓库出货请使用已入库库存。";
      return;
    }
    if (input.warehouseDispatch && !input.allocationOnly && !source.allocations.length) {
      return;
    }
    if (input.transfer) {
      if (source.allocations.length || source.fulfillment_mode === "PRODUCTION_DIRECT" || source.plan_id) errors[`source-${index}-allocations`] = "仓间发运只使用本仓库存，不关联生产订单或销售安排。";
      return;
    }
    const seen = new Set<string>();
    source.allocations.forEach((allocation, n) => {
      if (!allocation.order_line_id) errors[`allocation-${index}-${n}-order`] = "请选择关联订单明细。";
      else if (seen.has(allocation.order_line_id)) errors[`allocation-${index}-${n}-order`] = "此订单明细已分配，请合并分配数量。";
      seen.add(allocation.order_line_id);
      quantity(`allocation-${index}-${n}-units`, allocation.units, `第${n + 1}项分配数量`);
    });
    if (input.confirm || input.confirmedEdit) {
      if (!source.allocations.length) errors[`source-${index}-allocations`] = "确认前请添加订单分配。";
      else if (!errors[`source-${index}-units`] && source.allocations.every((_, n) => !errors[`allocation-${index}-${n}-units`])) {
        const allocated = source.allocations.reduce((sum, a) => sum + BigInt(a.units), 0n);
        if (allocated !== BigInt(source.actual_units)) errors[`source-${index}-allocations`] = "分配合计必须等于本次实际数量，可使用“全部分配到此订单”。";
      }
    }
  });
  if (input.confirmedEdit && !input.reason.trim()) errors.reason = "请填写本次操作原因。";
  if (input.demand && !input.effectiveDate) errors.effectiveDate = "请选择需求变更生效日期。";
  return errors;
}
export function productionFieldId(key: string) { return `production-${key}`; }
