export type Kind = "orders" | "shipments";
export type Sku = { sku_id: string; style_id?: string; style_code?: string; standard_color?: string; standard_size?: string; code: string | null; label: string; status: string; catalog_version: string };
export type OrderLine = { planned_production_units?: string | null; production_plan_reason?: string; production_status?: string; production_direct_units?: string; produced_units?: string | null; received_units?: string; tracking_state?: "OPEN" | "CLOSED"; closed_units?: string; pending_units?: string; overage_units?: string; id: string; sku_id: string; sku_label: string; expected_units: string; actual_units: string; difference_units: string };
export type ProductionReceiptSource = { line_number: string; order_id?: string; order_line_id: string; order_number?: string; order_business_number?: string; units: string };
export type Allocation = { id?: string; order_line_id: string; units: string; order_id?: string; order_number?: string; order_business_number?: string };
export type FulfillmentMode = "WAREHOUSE_STOCK" | "PRODUCTION_DIRECT";
export type Source = { order_attribution?: "automatic" | "manual"; import_row?: number; import_code?: string; replaces_source_id?: string; id?: string; sku_id: string; sku_label?: string; catalog_version?: string; plan_id?: string | null; fulfillment_mode?: FulfillmentMode; actual_units: string; allocations: Allocation[] };
export type Document = {
  fulfillment_lines?: {id:string;sku_id:string;expected_units:string;shipped_units:string;received_units:string|null}[];
  production_completion_state?: "OPEN" | "COMPLETED"; production_completion_ready?: boolean;
  destination_id?: string | null; destination_type?: string | null;
  factory_id?: string | null; factory_name?: string | null; receipt_warehouse_id?: string | null; receipt_owner_id?: string | null; destination?: string; cartons?: Carton[] | null;
  source_system?: string; source_event_kind?: string; external_event_id?: string; source_batch?: string; manual_source_note?: string; dispatch_purpose?: string;
  stock_tracked?: boolean; warehouse_id?: string | null; owner_id?: string | null; id: string; system_number: string; business_number: string; business_date: string | null;
  notes: string; status: "DRAFT" | "CONFIRMED" | "VOID"; revision: string;
  tracking_state?: "OPEN" | "CLOSED" | "PARTIAL_CLOSED"; closed_units?: string; pending_units?: string; overage_units?: string; expected_units?: string; actual_units: string; difference_units?: string;
  lines?: OrderLine[]; sources?: Source[];
  received_units?: string;
  receipts?: { document_id: string; line_number: string; order_line_id: string; sku_id: string; units: string; quality: string; business_date: string; status: "POSTED" | "REVERSED"; warehouse_id: string }[];
  shipments?: (Pick<Document, "id" | "system_number" | "status" | "business_date"> & { business_number?: string })[];
  file_sources?: { preview_id: string; filename: string; digest: string; created_at: string }[];
  history?: { operation_kind?: string; effective_date?: string; revision: string; actor_id: string; actor_name?: string; reason: string; created_at: string; before_value: unknown; after_value: unknown }[];
};
export type DocumentPage = { progress_counts?: {active:number;completed:number;all:number}; items: Document[]; total: number; page: number; page_size: number };
export type Carton = { id?: string; number: string; items: { sku_id: string; units: string }[] };
export type Summary = { closed_units?: string; pending_units?: string; overage_units?: string; cumulative_actual_units?: string; cumulative_difference_units?: string; expected_units: string; actual_units: string; difference_units: string; shipment_period_filtered: boolean;
  items: { tracking_state?: "OPEN" | "CLOSED"; pending_units?: string; overage_units?: string; closed_units?: string; cumulative_actual_units?: string; id: string; order_id: string; order_number: string; sku_id: string; sku_label: string; expected_units: string; actual_units: string; difference_units: string }[];
  skus: { sku_id: string; sku_label: string; expected_units: string; actual_units: string; difference_units: string }[] };
export const statusName = { DRAFT: "草稿", CONFIRMED: "已确认", VOID: "已作废" };
export const kindName = { orders: "预计订单", shipments: "实际出货" };
export function units(value?: string) { return value === undefined ? "—" : BigInt(value).toLocaleString("zh-CN"); }

export const trackingName = { OPEN: "跟进中", CLOSED: "已关闭", PARTIAL_CLOSED: "部分关闭" };
