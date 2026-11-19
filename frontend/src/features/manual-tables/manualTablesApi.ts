import type { Options as GeneratedOptions } from "../../api/generated";
import { writeApi } from "../../api/client";

export type ManualKind = "inventory" | "orders" | "packing";
export type HandoffPreview = {
  target_kind: "inventory_review" | "order" | "shipment" | "historical_reference";
  total_units: string; sku_count: number; source_row_count: number; excluded_row_count: number;
  inventory_effect_units: string; business_date: string | null; source_revision: number;
  handoff_preview_hash: string;
  candidates: { id: string; system_number?: string; business_number?: string; url: string }[];
};
export const kindLabels: Record<ManualKind, string> = { inventory: "库存结存", orders: "预下单", packing: "装箱资料" };
export type SourceRef = { sheet: string; row: number; cell: string };
export type ManualIssue = { code: string; message: string; suggestion: string; source_ref: SourceRef; blocking: boolean };
export type ManualRow = {
  source_line_key: string; source_ref: SourceRef; style: string; color: string; size: string; code: string;
  units: string | null; boxes: Record<string, string | null>; excluded: boolean;
  raw: Record<string, unknown>; issues: ManualIssue[];
  format_adjustments?: { field: string; before: string; after: string; reason: string }[];
  match?: { status: string; sku_id: string | null; catalog_version: string | null };
};
export type Decision = { style?: string; color?: string; size?: string; units?: string; sku_id?: string; reason?: string; excluded?: boolean; include_hidden?: boolean; accept_total?: boolean; boxes?: Record<string, string> };
export type ManualOptions = Required<Pick<GeneratedOptions, "sheet" | "header_row" | "start_row" | "end_row" | "columns" | "context" | "zero_policy">> & Pick<GeneratedOptions, "profile_id" | "profile_version" | "aggregate_duplicates" | "aggregation_reason"> & { decisions: Record<string, Decision> };
export type ManualResult = {
  rows: ManualRow[]; issues: ManualIssue[]; total_units: string; state: string;
  columns: Record<string, number>; sheet: string; header_row: number | null;
  sheets: { name: string; rows: number; columns: number }[];
  samples: { column: number; cell: string; value: string }[][];
  excluded_rows: { row: number; reason: string }[];
};
export type ManualBatch = { id: string; kind: ManualKind; filename: string; source_digest: string; revision: number; options: ManualOptions; result: ManualResult; target: { kind: string; id?: string; url?: string; token: string; state: string; command?: unknown } | null; updated_at: string; owner_id: string };
export type ManualCatalogItem = { sku_id: string; style: string; color: string; size: string; code: string | null; active: boolean };
export type Profile = { id: string; version: number; name: string; kind: ManualKind; options_json: Partial<ManualOptions> };
export type ManualHistory = { token: string; action: string; actor_id: string; actor_name?: string; revision: number | null; reason: string; at: string; changes?: string[] };

export async function downloadManual(batch: ManualBatch, mode: string, query: string, isCurrent: () => boolean = () => true) {
  const value = await writeApi<{ filename: string; file_base64: string }>(`/api/manual-tables/batches/${batch.id}/export`, { body: { revision: batch.revision, mode, query } });
  if (!isCurrent()) return;
  const bytes = Uint8Array.from(atob(value.file_base64), ch => ch.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
  const link = document.createElement("a"); link.href = url; link.download = value.filename; link.click();
  URL.revokeObjectURL(url);
}
