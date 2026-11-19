import type { DirectoryRecord } from "./directoryTypes";

export const fbaViews = ["balance", "updates", "receipts", "fulfillment", "returns", "tracking", "connect", "observation", "history"] as const;
export function fbaView(params: URLSearchParams) {
  const requested = params.get("fba_view");
  if (requested) return fbaViews.find(v => v === requested) || "balance";
  return params.get("tab") === "records" ? "receipts" : params.get("tab") === "adjust" ? "observation" : "balance";
}
export function warehouseTabs(record: DirectoryRecord): readonly (readonly [string,string])[] {
  if (record.type === "FBA") return [["stock","库存"],["transit","运输"],["profile","仓库资料"]];
  const stock = [["stock","库存"],["records","收发记录"],["adjust","盘点与异常"]] as const;
  // Unknown or retained scopes do not prove that historical queries are unavailable.
  if (record.scopes?.length || !record.inventory_state || record.inventory_state === "READY") return [...stock,["transit","运输"],["profile","资料"]];
  if (["FACTORY","OWN","THIRD_PARTY"].includes(record.type || "")) return [["stock","库存"],["transit","运输"],["profile","资料"]];
  return [["transit","运输"],["profile","资料"]];
}
