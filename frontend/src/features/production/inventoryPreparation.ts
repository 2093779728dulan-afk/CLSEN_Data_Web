import type { StockRow } from "./InventorySnapshotPage";

export type InventoryFocus = "identity" | "location" | "quantity" | "extra";
export const inventoryFocusLabels: Record<InventoryFocus, string> = {
  identity: "款号或颜色待确认", location: "仓库归属待确认", quantity: "尺码数量待核", extra: "公式或附加数量待核",
};
export function inventoryColor(row: StockRow) { return row.color || row.color_note; }
export function inventoryNeeds(row: StockRow): InventoryFocus[] {
  const result: InventoryFocus[] = [];
  if (!row.style_code || row.style_code === "无款号" || /改|\n/.test(row.style_code) || !inventoryColor(row) || /\n|\//.test(inventoryColor(row))) result.push("identity");
  if (row.location_group === "UNCONFIRMED") result.push("location");
  if (row.unknown_cells > 0) result.push("quantity");
  if (row.formula_units !== "0" || row.notes.some(note => note.raw.includes("另有")) || row.issues.some(issue => issue.includes("合计"))) result.push("extra");
  return result;
}
export type StockColor = { key: string; color: string; stock_units: string; unknown_cells: number; rows: StockRow[] };
export type StockProduct = { key: string; style_code: string; stock_units: string; colors: StockColor[]; needs: InventoryFocus[] };
export const inventorySizes = ["XS", "S", "M", "L", "XL", "XXL", "3XL"] as const;
const byCode = new Intl.Collator("zh-CN", { numeric: true });

export function inventorySizeQuantities(color: StockColor) {
  return inventorySizes.map(size => {
    let known = 0n, literalSources = 0, pendingSources = 0;
    for (const row of color.rows) {
      const quantity = row.quantities[size];
      if (quantity?.state === "LITERAL" && quantity.units !== null) {
        known += BigInt(quantity.units); literalSources++;
      } else {
        pendingSources++;
      }
    }
    return { size, known_units: known.toString(), literal_sources: literalSources, pending_sources: pendingSources };
  });
}

export function groupInventoryProducts(rows: StockRow[]): StockProduct[] {
  const products = new Map<string, StockProduct>();
  for (const row of rows) {
    // This is a single-warehouse display grouping, never a catalog/SKU mapping.
    if (row.location_group !== "WAREHOUSE_1") continue;
    const unresolvedStyle = !row.style_code || row.style_code === "无款号" || /改|\n/.test(row.style_code);
    const key = JSON.stringify(unresolvedStyle ? ["source", row.source_key] : ["style", row.style_code]);
    let product = products.get(key);
    if (!product) {
      product = { key, style_code: row.style_code, stock_units: "0", colors: [], needs: [] };
      products.set(key, product);
    }
    const name = inventoryColor(row);
    // Only color case differs; no translation or alias inference is applied.
    const colorKey = JSON.stringify(!name || /\n|\//.test(name) ? ["source", row.source_key] : ["color", name.toLocaleLowerCase("en-US")]);
    let color = product.colors.find(value => value.key === colorKey);
    if (!color) {
      color = { key: colorKey, color: name, stock_units: "0", unknown_cells: 0, rows: [] };
      product.colors.push(color);
    }
    color.rows.push(row);
    color.stock_units = (BigInt(color.stock_units) + BigInt(row.stock_units)).toString();
    color.unknown_cells += row.unknown_cells;
    product.stock_units = (BigInt(product.stock_units) + BigInt(row.stock_units)).toString();
    product.needs = [...new Set([...product.needs, ...inventoryNeeds(row)])];
  }
  return [...products.values()].map(product => ({ ...product, colors: product.colors.sort((a, b) => byCode.compare(a.color, b.color)) }))
    .sort((a, b) => byCode.compare(a.style_code, b.style_code) || byCode.compare(a.key, b.key));
}

export function prepareInventoryProducts(products: StockProduct[], query: string, focus: string): StockProduct[] {
  const search = query.trim().toLocaleLowerCase();
  // Filter whole products so a color search never changes their total quantity.
  return products.filter(product => (!focus || product.needs.includes(focus as InventoryFocus))
    && product.colors.some(color => color.rows.some(row => [row.style_code, row.color, row.color_note,
      ...row.notes.filter(note => note.raw.includes("另有")).map(note => note.raw)].join(" ").toLocaleLowerCase().includes(search))));
}
