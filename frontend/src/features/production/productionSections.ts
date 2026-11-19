export const productionSections = [
  { id: "overview", label: "业务总览", to: "/production/overview", paths: ["/production/overview"], items: [{ label: "业务总览", to: "/production/overview", paths: ["/production/overview"] }] },
  { id: "orders", label: "订单与出货", to: "/production/orders", paths: ["/production/orders", "/production/shipments", "/production/summary", "/production/products"], items: [
    { label: "订单跟进", to: "/production/orders", paths: ["/production/orders", "/production/summary", "/production/products"] },
    { label: "全部出货", to: "/production/shipments", paths: ["/production/shipments"] },
  ] },
  { id: "stock", label: "仓库中心", to: "/production/warehouses", paths: ["/production/stock", "/production/warehouses"], items: [
    { label: "仓库中心", to: "/production/warehouses", paths: ["/production/warehouses"] },
    { label: "库存总览", to: "/production/stock", paths: ["/production/stock"] },
    { label: "库存记录", to: "/production/stock/movements", paths: ["/production/stock/movements", "/production/stock/loans", "/production/stock/history", "/production/stock/materials"] },
  ] },
  { id: "factories", label: "工厂管理", to: "/production/factories", paths: ["/production/factories"], items: [
    { label: "工厂管理", to: "/production/factories", paths: ["/production/factories"] },
  ] },
] as const;

export const matchesProductionPath = (pathname: string, path: string) => pathname === path || pathname.startsWith(`${path}/`);
export function productionSection(pathname: string, search = "") {
  if (pathname.startsWith("/production/inventory")) return productionSections[2];
  if (pathname.startsWith("/production/imports") || pathname.startsWith("/production/manual-tables")) {
    return productionSections[new URLSearchParams(search).get("kind") === "inventory" ? 2 : 1];
  }
  if (pathname.startsWith("/production/source-drafts")) return productionSections[1];
  return productionSections.find(section => section.paths.some(path => matchesProductionPath(pathname, path)));
}
