import { useEffect, useState } from "react";
import { ApiRequestError, requestApi } from "../../api/client";
import { FormField, Select } from "../../design-system";
import type { Scope } from "./CatalogListingSourcePage";
import { useSearchParams } from "react-router-dom";
import { getCurrentCatalog, type CurrentCatalog } from "./catalogApi";
import { catalogReadError } from "./catalogReadError";
import { CatalogSetup } from "./CatalogSetup";
import { useCatalogNavigation } from "./CatalogNavigationContext";
import { CatalogProductList } from "./CatalogProductList";

export function CatalogHomePage({ canManage }: { canManage: boolean }) {
  const [search, setSearch] = useSearchParams();
  const requestedScope = Number(search.get("scope")) || undefined;
  const [scopes, setScopes] = useState<Scope[]>([]);
  const [scopeId, setScopeId] = useState<number>();
  const [catalog, setCatalog] = useState<CurrentCatalog | null>();
  const [error, setError] = useState<ReturnType<typeof catalogReadError>>();
  const [refresh, setRefresh] = useState(0);
  const [reading, setReading] = useState(true);
  const reload = () => { setReading(true); setError(undefined); setRefresh((value) => value + 1); };
  const { list, setList, setStyleReturn } = useCatalogNavigation();
  useEffect(() => {
    let active = true;
    void (async () => {
      const cap = await requestApi<{ scopes: Scope[] }>("/api/catalog/production-sources/capabilities");
      if (!active) return;
      setScopes(cap.scopes);
      const selected = requestedScope ?? cap.scopes[0]?.id;
      if (selected && !cap.scopes.some(scope => scope.id === selected)) throw new ApiRequestError(404, "catalog_scope_not_found", "店铺不存在或无权访问。");
      setScopeId(selected);
      const value = await getCurrentCatalog(selected);
      if (active) { setCatalog(value); setReading(false); }
    })().catch((reason: unknown) => {
      if (active) {
        const failure = catalogReadError(reason, "无法读取商品主档，请检查连接后重试。");
        setError(failure);
        if (!failure.retry) setCatalog(undefined); // Permission/setup failures must clear cached data.
        setReading(false);
      }
    });
    return () => { active = false; };
  }, [refresh, requestedScope]);
  useEffect(() => {
    const refreshVisible = () => {
      if (document.visibilityState !== "hidden") { setReading(true); setError(undefined); setRefresh((value) => value + 1); }
    };
    window.addEventListener("focus", refreshVisible);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => { window.removeEventListener("focus", refreshVisible); document.removeEventListener("visibilitychange", refreshVisible); };
  }, []);
  return <div className="catalog-stack">
    {scopes.length > 0 && <FormField label="店铺"><Select aria-label="商品店铺" value={scopeId ?? ""} disabled={reading} onChange={event => { const next = new URLSearchParams(search); next.set("scope", event.target.value); setCatalog(undefined); setReading(true); setSearch(next); setList({ ...list, page: 1 }); }}>
      {scopes.map(scope => <option key={scope.id} value={scope.id}>{scope.seller_account_display_name} · {scope.marketplace_scope_code}</option>)}
    </Select></FormField>}
    <CatalogProductList key={scopeId} scopeId={scopeId} catalog={catalog} failure={error} refreshing={reading && catalog !== undefined} canManage={canManage} list={list} onListChange={setList} onReload={reload} onOpenStyle={() => setStyleReturn(scopeId ? `/catalog?scope=${scopeId}` : "/catalog")} />
    {((catalog === null && !error) || error?.setup) && <CatalogSetup />}

  </div>;
}
