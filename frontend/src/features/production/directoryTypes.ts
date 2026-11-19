import type { WarehouseScope } from "./WorkbenchFields";
export type DirectoryRecord = {
  id: string; name: string; status: string; revision: string; type?: string; country?: string;
  region: string; address: string; operator: string; contact: string; phone: string;
  timezone: string; seller_account: string; marketplace: string;
  notes?: string; external_code?: string;
  warehouse_ids?: string[]; factory_ids?: string[]; order_count?: string; open_order_count?: string;
  inventory_state?: string; scopes?: WarehouseScope[];
  receipt_orders?: { id: string; system_number: string; business_number: string; receipt_owner_id: string }[];
  source_evidence?: WarehouseSource;
  inventory_product_scope?: { state: "ready"; warehouse_id: string; report_source_scope_id: string; catalog_version: string; sku_ids: string[] };
  history?: { revision: string; actor_name: string; reason: string; created_at: string; before_value: unknown; after_value: unknown }[];
};
export type SourceEvidenceLine = {
  source: string; sku: string; units: string | null; status: string;
  date?: string; reference?: string; asin?: string; fnsku?: string;
};
export type WarehouseSource = {
  kind: "domestic" | "fba";
  stock_date?: string; explicit_units?: string; matched_units?: string; pending_units?: string; deferred_units?: string;
  rows?: SourceEvidenceLine[];
  packings?: { filename: string; batch_date: string; boxes: number; packed_units: string;
    received_units: string | null; reference_id: string | null; differences: string[];
    rows: SourceEvidenceLine[] }[];
  receipts?: SourceEvidenceLine[];
  excluded_receipt_rows?: number;
  issues?: string[];
};
export type DirectoryPage = { items: DirectoryRecord[]; total: number; page: number; page_size: number };
export const warehouseTypes: Record<string, string> = { FACTORY: "成品仓", OWN: "成品仓", THIRD_PARTY: "第三方海外仓", FBA: "FBA", LOCATION: "非库存地点", UNCLASSIFIED: "历史仓（类型待核）" };
export const inventoryStates: Record<string, string> = { READY: "已建账", FBA_READY: "FBA事件账已建立", UNINITIALIZED: "库存尚未建立", NOT_CONNECTED: "平台库存未接入", NOT_APPLICABLE: "非库存地点" };
export type Destination = { destination: string; destination_id?: string | null; destination_type?: string | null };
export function destinationValue(document?: Partial<Destination>): Destination {
  return { destination: document?.destination || "", destination_id: document?.destination_id || null, destination_type: document?.destination_type || null };
}
