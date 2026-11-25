import type { Document } from "./types";
import { units } from "./types";

export function orderPending(order: Document, field: "produced_units" | "received_units" | "actual_units") {
  const lines = order.lines?.filter(line => line.tracking_state !== "CLOSED");
  if (!lines?.length) return order.lines ? "0" : "待核";
  if (lines.some(line => line[field] == null)) return field === "produced_units" ? "待登记" : "待核";
  return units(lines.reduce((total, line) => total + (BigInt(field === "actual_units" ? line.expected_units : line.planned_production_units ?? line.expected_units) > BigInt(line[field]!) ? BigInt(field === "actual_units" ? line.expected_units : line.planned_production_units ?? line.expected_units) - BigInt(line[field]!) : 0n), 0n).toString());
}
