import { type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { ClickSpark, PageTransition, RouteNavigation } from "../../design-system";

import "./CatalogWorkspace.css";

export function CatalogLayout({ children, canManage }: { children: ReactNode; canManage: boolean }) {
  const { pathname } = useLocation();
  return (
    <ClickSpark><main className={`catalog-workspace${pathname.startsWith("/catalog/imports/") ? " catalog-workspace--review" : ""}`} id="main-content">
      <header className="catalog-workspace__header">
        <div>{pathname !== "/catalog/unmatched" && <p className="section-kicker">PRODUCT CATALOG</p>}<h1>商品主档</h1></div>
        <RouteNavigation ariaLabel="商品主档导航" items={[
          { label: "商品", to: "/catalog", end: true },
          ...(canManage ? [
            ...(import.meta.env.VITE_PRODUCTION_CATALOG_ENABLED === "true" ? [{ label: "建档与维护", to: "/catalog/maintenance" }] : []),
            { label: "待归属与审核", to: "/catalog/unmatched" },
            { label: "目录版本", to: "/catalog/versions" },
            ...(import.meta.env.VITE_PRODUCTION_CATALOG_ENABLED !== "true" ? [{ label: "批量维护", to: "/catalog/maintenance" }] : []),
          ] : []),
        ]} />
      </header>
      <PageTransition key={pathname}>{children}</PageTransition>
    </main></ClickSpark>
  );
}
