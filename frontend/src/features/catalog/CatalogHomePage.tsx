import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getCurrentCatalog, type CurrentCatalog } from "./catalogApi";
import { catalogReadError } from "./catalogReadError";
import { CatalogSetup } from "./CatalogSetup";
import { useCatalogNavigation } from "./CatalogNavigationContext";
import { CatalogProductList } from "./CatalogProductList";

export function CatalogHomePage({ canManage }: { canManage: boolean }) {
  const [catalog, setCatalog] = useState<CurrentCatalog | null>();
  const [error, setError] = useState<ReturnType<typeof catalogReadError>>();
  const [refresh, setRefresh] = useState(0);
  const [reading, setReading] = useState(true);
  const reload = () => { setReading(true); setError(undefined); setRefresh((value) => value + 1); };
  const { list, setList, setStyleReturn } = useCatalogNavigation();
  useEffect(() => {
    let active = true;
    void getCurrentCatalog().then((value) => { if (active) { setCatalog(value); setReading(false); } }).catch((reason: unknown) => {
      if (active) {
        const failure = catalogReadError(reason, "无法读取商品主档，请检查连接后重试。");
        setError(failure);
        if (!failure.retry) setCatalog(undefined); // Permission/setup failures must clear cached data.
        setReading(false);
      }
    });
    return () => { active = false; };
  }, [refresh]);
  useEffect(() => {
    const refreshVisible = () => {
      if (document.visibilityState !== "hidden") { setReading(true); setError(undefined); setRefresh((value) => value + 1); }
    };
    window.addEventListener("focus", refreshVisible);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => { window.removeEventListener("focus", refreshVisible); document.removeEventListener("visibilitychange", refreshVisible); };
  }, []);
  return <div className="catalog-stack">
    <CatalogProductList catalog={catalog} failure={error} refreshing={reading && catalog !== undefined} canManage={canManage} list={list} onListChange={setList} onReload={reload} onOpenStyle={() => setStyleReturn("/catalog")} />
    {(catalog !== undefined && !error || error?.setup) && <CatalogSetup />}
    {catalog !== undefined && !error && canManage && <p className="catalog-maintenance-hint">需要生成候选或使用 XLSX？<Link to="/catalog/maintenance">进入批量维护</Link>。<Link to="/catalog/unmatched">查看待处理</Link></p>}
  </div>;
}
