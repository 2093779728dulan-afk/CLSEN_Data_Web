import { Plus, Trash2 } from "lucide-react";
import { Button, Input, Table } from "../../design-system";
import { type Carton, units } from "./types";

import type { PackingProduct } from "./shipmentPacking";
const count = (value: string) => /^\d+$/.test(value) ? BigInt(value) : 0n;

/** One carton editor and packing contract for the ordinary and multi-order workflows. */
export function ShipmentCartons({ products, boxes, change }: { products: PackingProduct[]; boxes: Carton[]; change: (boxes: Carton[]) => void }) {
  const total = products.reduce((sum, product) => sum + count(product.units), 0n);
  const packed = boxes.reduce((sum, box) => sum + box.items.reduce((amount, item) => amount + count(item.units), 0n), 0n);
  return <>
    <Table title="装箱明细"><thead><tr><th>箱号</th>{products.map(product => <th key={product.sku_id}>{product.label}</th>)}<th>箱内合计</th><th>操作</th></tr></thead><tbody>{boxes.map((box, index) => <tr key={index}>
      <td><Input aria-label={`第${index + 1}箱箱号`} maxLength={80} placeholder="例如：A001" value={box.number} onChange={event => change(boxes.map((item, n) => n === index ? { ...item, number: event.target.value } : item))} /></td>
      {products.map(product => <td key={product.sku_id}><Input aria-label={`第${index + 1}箱${product.label}装箱数`} inputMode="numeric" pattern="0|[1-9][0-9]*" value={box.items.find(item => item.sku_id === product.sku_id)?.units || ""} onChange={event => change(boxes.map((item, n) => n !== index ? item : { ...item, items: [...item.items.filter(line => line.sku_id !== product.sku_id), { sku_id: product.sku_id, units: event.target.value }] }))} /></td>)}
      <td>{units(box.items.reduce((sum, item) => sum + count(item.units), 0n).toString())}</td><td><Button variant="quiet" aria-label={`移除第${index + 1}箱`} icon={<Trash2 />} onClick={() => change(boxes.filter((_, n) => n !== index))}>移除</Button></td>
    </tr>)}</tbody></Table>
    <Button variant="secondary" icon={<Plus />} disabled={boxes.length >= 500} onClick={() => change([...boxes, { number: "", items: [] }])}>添加箱</Button>
    <p>本次 <strong>{units(total.toString())}</strong> 件 · 已装箱 <strong>{units(packed.toString())}</strong> 件 · <strong>{boxes.length}</strong> 箱</p>
  </>;
}

