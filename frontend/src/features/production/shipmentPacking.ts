import type { Carton } from "./types";
export type PackingProduct = { sku_id: string; label: string; units: string };
const count = (value: string) => /^\d+$/.test(value) ? BigInt(value) : 0n;

export function packingError(products: PackingProduct[], boxes: Carton[]): string | undefined {
  const named = boxes.filter(box => box.number.trim() || box.items.some(item => count(item.units) > 0n));
  const names = new Set<string>();
  for (const box of named) {
    if (!box.number.trim()) return "有商品的箱子必须填写箱号。";
    if (names.has(box.number.trim())) return "箱号不能重复，请合并同箱明细或更正箱号。";
    names.add(box.number.trim());
    for (const item of box.items) if (item.units && !/^\d{1,19}$/.test(item.units)) return "装箱数须填写非负整数。";
    if (box.items.some(item => count(item.units) > 0n && !products.some(product => product.sku_id === item.sku_id))) return "箱内包含不在本次出货中的商品，请核对装箱明细。";
  }
  if (products.some(product => named.reduce((sum, box) => sum + box.items.filter(item => item.sku_id === product.sku_id).reduce((amount, item) => amount + count(item.units), 0n), 0n) !== count(product.units))) return "每个产品的装箱合计须等于本次出货；请核对未装箱数量。";
}
