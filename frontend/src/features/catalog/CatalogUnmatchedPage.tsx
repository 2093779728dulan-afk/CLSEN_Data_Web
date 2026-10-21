import { CatalogReadError } from "./CatalogReadFailure";
import { catalogReadError } from "./catalogReadError";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  getCurrentCatalog,
  getCatalogStylePendingItems,
  listCatalogUnmatched,
  type CatalogUnmatchedResponse,
} from "./catalogApi";
import { CatalogUnmatchedView, type PendingStyle } from "./CatalogUnmatchedView";
import { useCatalogNavigation } from "./CatalogNavigationContext";

export function CatalogUnmatchedPage() {
  const { setStyleReturn } = useCatalogNavigation();
  const [parameters, setParameters] = useSearchParams();
  const page = Math.max(1, Number(parameters.get("page")) || 1);
  const from = parameters.get("from") ?? undefined;
  const to = parameters.get("to") ?? undefined;
  const returnBasis = parameters.get("return_basis") === "report_date" ? "report_date" : "event_date";
  const returnTo = parameters.get("return_to") ?? undefined;
  const [pending, setPending] = useState<PendingStyle[]>();
  const [pendingError, setPendingError] = useState<ReturnType<typeof catalogReadError>>();
  const [unmatched, setUnmatched] = useState<CatalogUnmatchedResponse>();
  const [error, setError] = useState<ReturnType<typeof catalogReadError>>();
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setError(undefined);
    setPendingError(undefined);
    setPending(undefined);
    setUnmatched(undefined);
    async function load() {
      try {
        const sources = await listCatalogUnmatched({ from, to, returnBasis, page, pageSize: 25 });
        if (!active) return;
        setUnmatched(sources);
      } catch (reason: unknown) {
        if (active) setError(catalogReadError(reason, "无法读取待归属来源，请检查连接后重试。"));
        return;
      }
      try {
        const catalog = await getCurrentCatalog();
      const results: PendingStyle[] = [];
      const styles = catalog?.styles ?? [];
      for (let index = 0; index < styles.length && active; index += 4) {
        const batch = await Promise.all(styles.slice(index, index + 4).map(async (style) => ({ style, summary: await getCatalogStylePendingItems(style.style_id) })));
        for (const { style, summary } of batch) {
          if (summary.permissions.can_review && summary.items.length) results.push({ style, items: summary.items });
        }
      }
        if (active) setPending(results);
      } catch (reason: unknown) {
        if (active) setPendingError(catalogReadError(reason, "无法读取已有审核候选，请稍后刷新。"));
      }
    }
    void load();
    return () => { active = false; };
  }, [attempt, from, page, returnBasis, to]);

  const maintenancePath = useMemo(() => {
    const query = new URLSearchParams();
    query.set("return_to", `/catalog/unmatched?${parameters.toString()}`);
    return `/catalog/maintenance?${query.toString()}`;
  }, [parameters]);
  const changePage = (next: number) => {
    const query = new URLSearchParams(parameters);
    query.set("page", String(next));
    setParameters(query);
  };

  if (error) return <CatalogReadError failure={error} onRetry={() => setAttempt(value => value + 1)} />;
  return <CatalogUnmatchedView unmatched={unmatched} pending={pending} pendingError={pendingError}
    onRetry={() => setAttempt(value => value + 1)} onOpenStyle={() => setStyleReturn(`/catalog/unmatched?${parameters.toString()}`)}
    page={page} returnBasis={returnBasis} returnTo={returnTo} maintenancePath={maintenancePath} changePage={changePage} />;
}
