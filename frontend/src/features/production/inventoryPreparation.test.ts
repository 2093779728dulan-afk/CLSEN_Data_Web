import { describe, expect, it } from "vitest";
import type { StockRow } from "./InventorySnapshotPage";
import { groupInventoryProducts, inventoryColor, inventoryNeeds, inventorySizeQuantities, prepareInventoryProducts, type StockColor } from "./inventoryPreparation";

function row(overrides: Partial<StockRow> = {}): StockRow {
  return { source_key: "原页!3", sheet: "旧分类", source_row: 3, style_code: "1101", old_style_code: "LEGACY-ONLY", source_sku: "", color: "navy", color_note: "", location: "新仓库", location_group: "WAREHOUSE_1", quantities: {}, stock_units: "5", literal_units: "5", formula_units: "0", unknown_cells: 0, source_total: { cell: "J3", raw: "5", units: "5", state: "LITERAL" }, notes: [], issues: [], sku_id: null, ...overrides };
}
describe("single-warehouse inventory products", () => {
  it("counts each color source once and keeps product totals equal to complete color totals", () => {
    const records = [row({ source_key: "原页!3", style_code: "100" }), row({ source_key: "原页!4", style_code: "20" }), row({ source_key: "原页!5", style_code: "20" })];
    const before = structuredClone(records);
    const result = groupInventoryProducts(records);
    expect(result.map(value => [value.style_code, value.stock_units])).toEqual([["20", "10"], ["100", "5"]]);
    expect(result[0]?.colors).toHaveLength(1);
    expect(result[0]?.colors[0]?.rows.map(value => value.source_key)).toEqual(["原页!4", "原页!5"]);
    expect(result.every(product => BigInt(product.stock_units) === product.colors.reduce((sum, color) => sum + BigInt(color.stock_units), 0n))).toBe(true);
    expect(records).toEqual(before);
    expect(result.flatMap(product => product.colors.flatMap(color => color.rows)).every(value => value.sku_id === null)).toBe(true);
  });
  it("excludes an unknown warehouse even when its style and color match", () => {
    const result = groupInventoryProducts([row({ stock_units: "18" }), row({ source_key: "原页!4", color: "NAVY", stock_units: "141", location: "", location_group: "UNCONFIRMED" })]);
    expect(result).toHaveLength(1);
    expect(result[0]?.stock_units).toBe("18");
    expect(result[0]?.colors[0]?.stock_units).toBe("18");
    expect(result[0]?.colors[0]?.rows).toHaveLength(1);
  });
  it("groups color case for display but keeps different names and original evidence", () => {
    const records = [row(), row({ source_key: "原页!4", color: "NAVY", stock_units: "7" }), row({ source_key: "原页!5", color: "Classic Navy", stock_units: "9" })];
    const result = groupInventoryProducts(records)[0];
    expect(result?.stock_units).toBe("21");
    expect(result?.colors.map(color => [color.color, color.stock_units])).toEqual([["Classic Navy", "9"], ["navy", "12"]]);
    expect(records.map(value => value.color)).toEqual(["navy", "NAVY", "Classic Navy"]);
  });
  it("keeps all colors and the original total when searching one color or filtering a missing size", () => {
    const products = groupInventoryProducts([row(), row({ source_key: "原页!4", color: "black", stock_units: "7", unknown_cells: 1 })]);
    const filtered = prepareInventoryProducts(products, "NAVY", "quantity");
    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.stock_units).toBe("12");
    expect(filtered[0]?.colors).toHaveLength(2);
    expect(prepareInventoryProducts(products, "NO-SUCH-PRODUCT", "")).toEqual([]);
    expect(prepareInventoryProducts(products, "LEGACY-ONLY", "")).toEqual([]);
    expect(prepareInventoryProducts(products, "旧分类", "")).toEqual([]);
  });
  it("retains distinct style codes and exact integer quantities above JS safe precision", () => {
    const result = groupInventoryProducts([row({ style_code: "22003", stock_units: "9007199254740993" }), row({ source_key: "原页!4", style_code: "22003", stock_units: "9" }), row({ source_key: "原页!5", style_code: "2203", stock_units: "1" }), row({ source_key: "原页!6", style_code: "02203", stock_units: "2" })]);
    expect(result).toHaveLength(3);
    expect(result.find(product => product.style_code === "22003")?.stock_units).toBe("9007199254741002");
    expect(result.find(product => product.style_code === "2203")?.stock_units).toBe("1");
    expect(result.find(product => product.style_code === "02203")?.stock_units).toBe("2");
  });
  it("does not infer identity from missing codes, colors or multi-color descriptions", () => {
    const missing = [row({ source_key: "原页!3", style_code: "", color: "" }), row({ source_key: "原页!4", style_code: "", color: "" })];
    expect(groupInventoryProducts(missing)).toHaveLength(2);
    const descriptions = groupInventoryProducts([row({ color: "深蓝/浅灰" }), row({ source_key: "原页!4", color: "深蓝/浅灰" })]);
    expect(descriptions[0]?.colors).toHaveLength(2);
    expect(descriptions[0]?.needs).toContain("identity");
    const record = row({ color: "", color_note: "深蓝（海军蓝）" });
    expect(inventoryColor(record)).toBe("深蓝（海军蓝）");
    expect(record.color).toBe("");
    expect(inventoryNeeds(row({ style_code: "3102\n改1121" }))).toContain("identity");
  });
  it("preserves zero and unknown cells and counts the declared row quantity once", () => {
    const record = row({ stock_units: "0", literal_units: "0", unknown_cells: 2, quantities: { S: { cell: "D3", raw: "0", units: "0", state: "LITERAL" }, M: { cell: "E3", raw: "", units: null, state: "UNKNOWN" }, L: { cell: "F3", raw: "/", units: null, state: "UNKNOWN" } } });
    const before = structuredClone(record);
    const result = prepareInventoryProducts(groupInventoryProducts([record]), "", "quantity");
    expect(result[0]?.stock_units).toBe("0");
    expect(result[0]?.colors[0]?.unknown_cells).toBe(2);
    expect(record).toEqual(before);
    expect(record.quantities.S?.units).toBe("0");
    expect(record.quantities.L?.units).toBeNull();
  });
  it("keeps formulas and additional quantities pending without adding them to product totals", () => {
    const record = row({ formula_units: "35", notes: [{ cell: "V3", raw: "另有3件尺码不明" }] });
    expect(inventoryNeeds(record)).toContain("extra");
    const result = prepareInventoryProducts(groupInventoryProducts([record]), "另有", "extra");
    expect(result[0]?.stock_units).toBe("5");
    expect(record.formula_units).toBe("35");
  });
});

function color(rows: StockRow[]): StockColor { return { key: "navy", color: "navy", stock_units: "7", unknown_cells: 0, rows }; }
describe("inline color size quantities", () => {
  it("shows explicit zero and numbers while keeping blank, slash and absent sizes pending", () => {
    const result = inventorySizeQuantities(color([row({ quantities: {
      S: { cell: "D3", raw: "0", state: "LITERAL", units: "0" }, M: { cell: "E3", raw: "7", state: "LITERAL", units: "7" },
      L: { cell: "F3", raw: "/", state: "UNKNOWN", units: null }, XL: { cell: "G3", raw: "", state: "UNKNOWN", units: null },
    } })]));
    expect(result.map(value => value.size)).toEqual(["XS", "S", "M", "L", "XL", "XXL", "3XL"]);
    expect(result.find(value => value.size === "S")).toEqual({ size: "S", known_units: "0", literal_sources: 1, pending_sources: 0 });
    expect(result.find(value => value.size === "M")?.known_units).toBe("7");
    expect(result.filter(value => ["XS", "L", "XL", "XXL", "3XL"].includes(value.size)).every(value => value.literal_sources === 0 && value.pending_sources === 1)).toBe(true);
  });
  it("aggregates sizes exactly across color sources and identifies a partial known quantity", () => {
    const rows = [row({ quantities: { S: { cell: "D3", raw: "9007199254740993", state: "LITERAL", units: "9007199254740993" }, M: { cell: "E3", raw: "4", state: "LITERAL", units: "4" } } }), row({ source_key: "原页!4", color: "NAVY", quantities: { S: { cell: "D4", raw: "9", state: "LITERAL", units: "9" }, M: { cell: "E4", raw: "/", state: "UNKNOWN", units: null } } })];
    const before = structuredClone(rows);
    const result = inventorySizeQuantities(color(rows));
    expect(result.find(value => value.size === "S")?.known_units).toBe("9007199254741002");
    expect(result.find(value => value.size === "M")).toEqual({ size: "M", known_units: "4", literal_sources: 1, pending_sources: 1 });
    expect(result.find(value => value.size === "3XL")?.pending_sources).toBe(2);
    expect(rows).toEqual(before);
  });
  it("does not move formulas or whole-row totals into a size quantity", () => {
    const record = row({ formula_units: "35", source_total: { cell: "J3", raw: "999", state: "LITERAL", units: "999" }, quantities: { S: { cell: "D3", raw: "=20+15", state: "ADDITION_REFERENCE", units: "35" }, M: { cell: "E3", raw: "5", state: "LITERAL", units: "5" } } });
    const result = inventorySizeQuantities(color([record]));
    expect(result.find(value => value.size === "S")).toEqual({ size: "S", known_units: "0", literal_sources: 0, pending_sources: 1 });
    expect(result.find(value => value.size === "M")?.known_units).toBe("5");
    expect(record.stock_units).toBe("5");
  });
});
