import { createContext, useContext } from "react";
import type { Balance } from "./StockWorkspace";
import type { Sku } from "./types";
import type { WarehouseScope } from "./WorkbenchFields";

export type OverviewStock = { scopes: WarehouseScope[]; items: Balance[] };
export type OverviewSource = { value?: OverviewStock; error?: string; loading: boolean; reload: () => void };
export type OverviewAction = { kind: "source" | "out" | "quality" | "count" | "return" | "inspect" | "movement" | "reserve" | "release" | "borrow" | "loans"; sku_id?: string; warehouse_id?: string; owner_id?: string; loan_id?: string };
export type OverviewGuard = { dirty: boolean; busy: boolean; unknown: boolean; blocked?: boolean };
export type OverviewTools = { stock?: OverviewStock; catalog?: Sku[]; stockError?: string; catalogError?: string; refresh: () => void; variants: Sku[]; historical: boolean; action: OverviewAction; startAction: (action: OverviewAction) => void; onGuardChange: (guard: OverviewGuard) => void };
// These parameters only present retained components; business routes and draft parameters remain guarded.
export const overviewSearchParams = ["stock_watch","stock_batch","stock_batch_page","stock_batch_q","stock_batch_node","stock_styles","style_id","sku_id","sku_detail","sku_page","stock_scope","stock_owner","stock_detail","stock_q","q","identity","stock_layout","view"];
export const stockAmount = (value: string | null | undefined) => value == null ? "待核" : value;
export const stockSum = (values: Balance[], field: keyof Balance, ready: boolean) => !ready || values.some(value => value[field] == null) ? null : values.reduce((total, value) => total + BigInt(value[field] as string), 0n).toString();

export const StockWindowContainer = createContext<HTMLElement | null>(null);
export const useStockWindowContainer = () => useContext(StockWindowContainer);
