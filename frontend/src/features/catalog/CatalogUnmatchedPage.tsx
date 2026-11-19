import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { requestApi } from "../../api/client";
import { CatalogReadError } from "./CatalogReadFailure";
import { CatalogPlatformStatus } from "./CatalogPlatformStatus";
import { catalogReadError } from "./catalogReadError";
import styles from "./CatalogUnmatchedView.module.css";
import { Button, LinkButton } from "../../design-system";
import { CatalogSourceSelection } from "./CatalogSourceSelection";
import { CatalogTaskList } from "./CatalogTaskList";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  listCatalogUnmatched,
  type CatalogUnmatchedResponse, type CatalogUnmatchedItem,
} from "./catalogApi";
import { CatalogUnmatchedView, type PendingStyle } from "./CatalogUnmatchedView";
import { useCatalogNavigation } from "./CatalogNavigationContext";

export function CatalogUnmatchedPage() {
  const { setStyleReturn } = useCatalogNavigation();
  const { generation, registerSensitivePurge } = useAuthzGeneration();

  const [parameters, setParameters] = useSearchParams();
  const tab = parameters.get("tab") ?? "unmatched";
  const [selected, setSelected] = useState<CatalogUnmatchedItem>();
  const closeSelection = useCallback(() => {setSelected(undefined);setAttempt(value=>value+1);}, []);
  const recheckId = parameters.get("selection_import");
  useEffect(() => {
    if (!recheckId) return;
    let active = true;
    void requestApi<{source_key: string; scope_id: number; version_ids: number[]}>(`/api/catalog/unmatched/selection-candidates/${Number(recheckId)}/source`).then(request => {
      if (active && request) setSelected({ source_identity: { seller_sku_match: request.source_key, report_source_scope_id: request.scope_id, seller_sku_sha256: "" }, published_version_ids: request.version_ids.map(String) } as CatalogUnmatchedItem);
    }).catch(reason => { if (active) setError(catalogReadError(reason, "无法读取此候选来源，请重试。")); });
    return () => { active = false; };
  }, [recheckId, generation]);
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
  useEffect(() => registerSensitivePurge(() => { setUnmatched(undefined); setSelected(undefined); setPending(undefined); setError(undefined); setPendingError(undefined); }), [registerSensitivePurge]);

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
      setPending([]);
    }
    if (tab === "unmatched") void load();
    return () => { active = false; };
  }, [attempt, from, page, returnBasis, to, tab, generation]);

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

  const navigation = <nav className={styles.taskTabs} aria-label="待归属与审核任务分类">{[["unmatched", "待归属"], ["review", "待审核"], ["attention", "需处理"]].map(([value, label]) => <Button key={value} variant={tab === value ? "primary" : "quiet"} aria-current={tab === value ? "page" : undefined} onClick={() => { const next = new URLSearchParams(parameters); next.set("tab", value!); next.delete("task_page"); setParameters(next); }}>{label}</Button>)}<LinkButton variant="quiet" to="/catalog/maintenance">全部记录</LinkButton></nav>;
  if (tab !== "unmatched") return <div className={styles.workspace}>{navigation}{tab === "attention" && <CatalogPlatformStatus compact revision={attempt} />}<CatalogTaskList kind={tab === "review" ? "review" : "attention"} /></div>;
  if (error) return <div className={styles.workspace}>{navigation}{selected && <CatalogSourceSelection item={selected} onClose={closeSelection} />}{import.meta.env.VITE_PRODUCTION_CATALOG_ENABLED === "true" && error.setup && <CatalogPlatformStatus compact revision={attempt} />}<CatalogReadError failure={error} onRetry={() => setAttempt(value => value + 1)} /></div>;
  return <div className={styles.workspace}>{navigation}{selected && <CatalogSourceSelection item={selected} onClose={closeSelection} />}{import.meta.env.VITE_PRODUCTION_CATALOG_ENABLED === "true" && unmatched && <CatalogPlatformStatus compact revision={attempt} />}<CatalogUnmatchedView unmatched={unmatched} pending={pending} pendingError={pendingError}
    onRetry={() => setAttempt(value => value + 1)} onOpenStyle={() => setStyleReturn(`/catalog/unmatched?${parameters.toString()}`)}
    onSelect={setSelected} showPending={false} page={page} returnBasis={returnBasis} returnTo={returnTo} maintenancePath={maintenancePath} changePage={changePage} /></div>;
}
