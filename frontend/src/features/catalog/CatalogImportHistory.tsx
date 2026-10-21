import { useEffect, useState } from "react";
import { CatalogImportHistoryView, type CatalogHistory } from "./CatalogImportHistoryView";
import { requestApi } from "../../api/client";
import { useCatalogNavigation } from "./CatalogNavigationContext";
export function CatalogImportHistory() {
  const { setReviewReturn } = useCatalogNavigation();
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<CatalogHistory>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    let active = true;
    setResult(undefined); setError(undefined);
    void requestApi<CatalogHistory>(`/api/catalog/imports?page=${page}`).then((value) => { if (active) setResult(value); }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "读取失败"); });
    return () => { active = false; };
  }, [page, retry]);
  return <CatalogImportHistoryView result={result} error={error} page={page} onReload={() => setRetry(retry + 1)} onPageChange={setPage} onOpenReview={() => setReviewReturn("/catalog/maintenance")} />;
}
