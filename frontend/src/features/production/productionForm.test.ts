import { describe, expect, it } from "vitest";
import { validateProductionInput, type ProductionInput } from "./productionForm";

const input: ProductionInput = { date: "2026-10-12", lines: [{ sku_id: "1001", expected_units: "100" }], sources: [{ sku_id: "1001", actual_units: "40", allocations: [{ order_line_id: "501", units: "40" }] }], reason: "", effectiveDate: "", confirmedEdit: false, demand: false, confirm: true };
describe("production form validation", () => {
  it("keeps a warehouse leg independent of production orders while retaining quantity checks",()=>{
    const transfer={...input,transfer:true,sources:[{sku_id:"1001",actual_units:"4",fulfillment_mode:"WAREHOUSE_STOCK" as const,allocations:[]}]};
    expect(validateProductionInput("shipments",transfer)).toEqual({});
    expect(validateProductionInput("shipments",{...transfer,sources:[{...transfer.sources[0]!,actual_units:"0"}]})).toHaveProperty("source-0-units");
    expect(validateProductionInput("shipments",{...input,transfer:true})).toHaveProperty("source-0-allocations");
  });
  it("permits independent warehouse quantities without any production-order allocation", () => {
    const warehouse={...input,warehouseDispatch:true,sources:[{sku_id:"1001",actual_units:"4",fulfillment_mode:"WAREHOUSE_STOCK" as const,allocations:[]}]};
    expect(validateProductionInput("shipments",warehouse)).toEqual({});
    expect(validateProductionInput("shipments",{...warehouse,sources:[{...warehouse.sources[0]!,actual_units:"0"}]})).toHaveProperty("source-0-units");
    expect(validateProductionInput("shipments",{...input,warehouseDispatch:true})).toHaveProperty("source-0-allocations");
    expect(validateProductionInput("shipments",{...warehouse,sources:[{...warehouse.sources[0]!,fulfillment_mode:"PRODUCTION_DIRECT"}]})).toHaveProperty("source-0-allocations");
  });
  it("points missing SKU and quantity to their own fields", () => {
    const errors = validateProductionInput("orders", { ...input, lines: [{ sku_id: "", expected_units: "" }] });
    expect(errors["line-0-sku"]).toContain("请选择第1行SKU");
    expect(errors["line-0-units"]).toContain("预计数量");
  });
  it("keeps integers beyond JavaScript precision and the server's signed-long boundary", () => {
    expect(validateProductionInput("orders", { ...input, lines: [{ sku_id: "1001", expected_units: "9007199254740993" }] })).toEqual({});
    expect(validateProductionInput("orders", { ...input, lines: [{ sku_id: "1001", expected_units: "9223372036854775808" }] })).toHaveProperty("line-0-units");
  });
  it("rejects repeated SKU instead of silently merging demand", () => {
    expect(validateProductionInput("orders", { ...input, lines: [...input.lines, ...input.lines] })).toHaveProperty("line-1-sku");
  });
  it("allows an unallocated draft, but requires conserved allocations at confirmation", () => {
    const draft = { ...input, confirm: false, sources: [{ sku_id: "1001", actual_units: "40", allocations: [] }] };
    expect(validateProductionInput("shipments", draft)).toEqual({});
    expect(validateProductionInput("shipments", { ...draft, confirm: true })).toHaveProperty("source-0-allocations");
    expect(validateProductionInput("shipments", { ...input, sources: [{ ...input.sources[0]!, allocations: [{ order_line_id: "501", units: "30" }] }] })).toHaveProperty("source-0-allocations");
  });
  it("supports multi-order allocation without rounding or duplicate lines", () => {
    expect(validateProductionInput("shipments", { ...input, sources: [{ sku_id: "1001", actual_units: "40", allocations: [{ order_line_id: "501", units: "25" }, { order_line_id: "502", units: "15" }] }] })).toEqual({});
    expect(validateProductionInput("shipments", { ...input, sources: [{ sku_id: "1001", actual_units: "40", allocations: [{ order_line_id: "501", units: "25" }, { order_line_id: "501", units: "15" }] }] })).toHaveProperty("allocation-0-1-order");
  });
  it("requires reason and effective date for the existing demand-change command", () => {
    const errors = validateProductionInput("orders", { ...input, confirmedEdit: true, demand: true });
    expect(errors).toHaveProperty("reason"); expect(errors).toHaveProperty("effectiveDate");
  });
});
