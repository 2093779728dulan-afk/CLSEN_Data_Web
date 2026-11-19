export const transportStatus = { UNREGISTERED: "未登记", REGISTERED: "已登记", DISPATCHED: "承运商已发运", IN_TRANSIT: "运输中", ARRIVED: "物流到达", SIGNED: "物流签收", EXCEPTION: "运输异常" };
export type TransportEvent = { id: string; transport_id: string; revision: string; event_kind: keyof typeof transportStatus; occurred_at: string; occurred_local: string; timezone: string; location: string; description: string; source_reference: string; signed_units: string | null; created_at: string };
export type TransportRecord = { id: string; revision: string; shipment_id: string; shipment_revision: string; carrier: string; tracking_number: string; estimated_arrival: string | null; arrival_local: string; arrival_timezone: string; source_reference: string; source_snapshot: unknown };
export type TransportState = { registered: boolean; shipment_id: string; shipment_revision: string; shipment_status: string; warehouse_id: string | null; owner_id: string | null; destination_id: string | null; source_revision_current?: boolean; status: keyof typeof transportStatus; record: TransportRecord | null; events: TransportEvent[]; latest_event: TransportEvent | null; destination_received_units: string; shipment_units: string; history: { document_kind: string; document_id: string; revision: string; actor_name: string; reason: string; operation_kind: string; created_at: string; before_value: Record<string, unknown> | null; after_value: Record<string, unknown> }[] };
export const transportTime = (local: string, zone: string) => local ? `${local.replace("T", " ")} (${zone})` : "未登记";
export function transportSummary(value: TransportState) {
  return value.record ? `${value.record.carrier} · ${value.record.tracking_number} · ${transportStatus[value.status]} · 预计到达 ${transportTime(value.record.arrival_local, value.record.arrival_timezone)}` : "运输未登记";
}
export function transportCsv(value: TransportState) {
  const record = value.record;
  const head = ["出货ID", "出货修订", "运输ID", "运输修订", "承运商", "运单号", "预计到达原文", "预计到达时区", "运输资料依据", "原出货来源与箱及订单分配", "节点ID", "节点修订", "节点", "发生时间原文", "发生时区", "发生时间UTC", "地点", "承运商累计签收件数", "节点依据", "登记时间UTC"];
  const common = [value.shipment_id, record?.shipment_revision || value.shipment_revision, record?.id, record?.revision, record?.carrier, record?.tracking_number, record?.arrival_local, record?.arrival_timezone, record?.source_reference, record ? JSON.stringify(record.source_snapshot) : ""];
  const body = value.events.length ? value.events.map(event => [...common, event.id, event.revision, transportStatus[event.event_kind], event.occurred_local, event.timezone, event.occurred_at, event.location, event.event_kind === "SIGNED" ? event.signed_units ?? "未登记" : "不适用", event.source_reference, event.created_at]) : [[...common, "", "", "未登记运输节点", "", "", "", "", "未登记", "", ""]];
  const cell = (v: string | null | undefined) => { const text = String(v ?? ""); return `"${(/^[=+@\t\r-]/.test(text) ? "'" : "") + text.replaceAll('"', '""')}"`; };
  return "\ufeff" + [head, ...body].map(row => row.map(cell).join(",")).join("\r\n");
}
