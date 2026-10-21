import { Fragment, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";

import "./CatalogWorkspace.css";

export function CatalogLayout({ children, canManage }: { children: ReactNode; canManage: boolean }) {
  const { pathname } = useLocation();
  return (
    <main className={`catalog-workspace${pathname.startsWith("/catalog/imports/") ? " catalog-workspace--review" : ""}`} id="main-content">
      <header className="catalog-workspace__header">
        <div><p className="section-kicker">PRODUCT CATALOG</p><h1>商品主档</h1></div>
        <nav aria-label="商品主档导航">
          <NavLink end to="/catalog">商品</NavLink>
          {canManage && <NavLink to="/catalog/unmatched">待处理</NavLink>}
          {canManage && <NavLink to="/catalog/versions">目录版本</NavLink>}
          {canManage && <NavLink to="/catalog/maintenance">批量维护</NavLink>}
        </nav>
      </header>
      <Fragment key={pathname}>{children}</Fragment>
    </main>
  );
}
