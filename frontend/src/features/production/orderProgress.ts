import type { Document, OrderLine, Sku } from "./types";

export function orderProductName(line: {sku_id:string;sku_label?:string}, catalog: Sku[]) {
  const sku = catalog.find(item => item.sku_id === line.sku_id);
  return sku?.code || (sku?.style_code && sku.standard_color && sku.standard_size
    ? `${sku.style_code} · ${sku.standard_color} · ${sku.standard_size}`
    : line.sku_label) || `SKU ${line.sku_id}（资料待核）`;
}
export function knownOrderSum(values: (string | null | undefined)[]) {
  return !values.length || values.some(value => value == null) ? null : values.reduce((sum, value) => sum + BigInt(value!), 0n).toString();
}
export const progressNumber = (value: string) => /^(0|[1-9][0-9]{0,18})$/.test(value) && BigInt(value) <= 9223372036854775807n;
export function progressChanges(order: Document, values: Record<string, string>, statuses?: Record<string, string>) {
  return (order.lines || []).filter(line => line.tracking_state !== "CLOSED").flatMap(line => {
    const change: { order_line_id: string; produced_units?: string; production_status?: string } = { order_line_id: line.id };
    if (values[line.id] !== "" && values[line.id] !== undefined && values[line.id] !== (line.produced_units ?? "")) change.produced_units = values[line.id];
    if (statuses?.[line.id] !== undefined && statuses[line.id]!.trim() !== (line.production_status ?? "")) change.production_status = statuses[line.id]!.trim();
    return change.produced_units !== undefined || change.production_status !== undefined ? [change] : [];
  });
}
export function orderOverviewUrl(search: URLSearchParams) {
  const next = new URLSearchParams(search);
  for (const key of ["new", "edit", "tab", "line", "operation", "shipment", "receipt_draft", "reload"]) next.delete(key);
  return `/production/orders${next.size ? `?${next}` : ""}`;
}

export type ReceiptSourceLine = OrderLine & { order_id: string; order_label?: string; order_reference?: string; receipt_factory_name?: string };

export function receiptRemaining(line: OrderLine): bigint | undefined {
  if (line.received_units == null) return undefined;
  const remaining = BigInt(line.planned_production_units ?? line.expected_units) - BigInt(line.received_units) - BigInt(line.production_direct_units || "0");
  return remaining > 0n ? remaining : 0n;
}

export function receiptOrderGroups(lines: ReceiptSourceLine[]) {
  return [...new Set(lines.map(line => line.order_id))].map(id => {
    const items = lines.filter(line => line.order_id === id);
    const first = items[0]!;
    const remaining = items.map(receiptRemaining);
    return { id, label: first.order_reference || first.order_label || id, factory: first.receipt_factory_name,
      expected: items.reduce((n, line) => n + BigInt(line.planned_production_units ?? line.expected_units), 0n),
      received: items.every(line => line.received_units != null) ? items.reduce((n, line) => n + BigInt(line.received_units!), 0n) : undefined,
      remaining: remaining.every(value => value != null) ? remaining.reduce<bigint>((n, value) => n + value, 0n) : undefined,
      complete: remaining.every(value => value === 0n) };
  });
}

