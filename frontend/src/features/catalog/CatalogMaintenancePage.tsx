import { CatalogGuidedFlow } from "./CatalogGuidedFlow";

import { Button, Skeleton, StatusBadge, StatusMessage } from "../../design-system";
import { useCallback, useEffect, useState } from "react";

import { getCurrentCatalog, type CurrentCatalog } from "./catalogApi";

import { CatalogImportHistory } from "./CatalogImportHistory";
import { useSearchParams } from "react-router-dom";
import css from "./CatalogMaintenancePage.module.css";

export function CatalogMaintenancePage() {
  const [params] = useSearchParams();
  const listingValue = params.get("listing") || "";
  const selectedListing = /^[1-9][0-9]*$/.test(listingValue) && Number.isSafeInteger(Number(listingValue)) ? Number(listingValue) : undefined;
  const [catalog, setCatalog] = useState<CurrentCatalog | null>();

  const [error, setError] = useState<string>();
  const [retry, setRetry] = useState(0);
  const refresh=useCallback(()=>setRetry(value=>value+1),[]);
  useEffect(() => {
    let active = true;
    setError(undefined);
    void getCurrentCatalog().then((value) => { if (active) setCatalog(value); }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "无法读取当前目录。");
    });
    return () => { active = false; };
  }, [retry]);
  if (error) return <StatusMessage kind="danger" title="目录读取未完成" action={<Button onClick={() => setRetry(value => value + 1)}>重新读取</Button>}>{error}</StatusMessage>;
  if (catalog === undefined) return <div><p role="status">正在读取建档与维护…</p><Skeleton lines={4} /></div>;
  return <div className={css.page}><header className={css.header}><div className={css.identity}><h2>建档与维护</h2><StatusBadge label={catalog?`当前目录 V${catalog.version_number}`:'尚未建立目录'} tone="quiet" />{selectedListing&&<StatusBadge label={`商品表 #${selectedListing}`} tone="quiet"/>}</div><CatalogGuidedFlow key={selectedListing ?? 'workspace'} entryMode="workspace" initialMode={selectedListing ? 'product' : 'analysis'} autoOpen={!!selectedListing} initialListing={selectedListing} onClosed={refresh}/></header><CatalogImportHistory refreshKey={retry}/></div>;
}

