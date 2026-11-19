import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { requestApi } from "../../api/client";
import { StatusMessage } from "../../design-system";

import styles from "./CatalogUnmatchedView.module.css";

type PlatformStatus = { state: string; message: string; conflicts: { style_id: string; sku_id: string; scope_id: string; seller_sku: string; official_asins: string[] }[] };
export function CatalogPlatformStatus({ styleId, revision, compact = false }: { styleId?: string | number; revision: number; compact?: boolean }) {
  const [value, setValue] = useState<PlatformStatus>();
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController(); setValue(undefined); setError(false);
    void requestApi<PlatformStatus>(styleId === undefined ? "/api/catalog/listing-sources/platform/status" : `/api/catalog/listing-sources/styles/${styleId}/status`, { signal: controller.signal }).then(result => { if (!controller.signal.aborted) setValue(result); }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [styleId, revision]);
  if (error) return <StatusMessage kind="warning" title="平台标识核对未完成">请刷新后重试；当前商品与库存身份继续保留。</StatusMessage>;
  if (!value) return <p role="status">正在核对当前已发布报表中的平台标识…</p>;
  const status = <StatusMessage kind={value.state === "pending" || value.state === "incomplete" ? "warning" : "info"} title={value.state === "pending" ? "平台身份待核" : "平台标识依据"}>{value.message}{styleId === undefined && <p>此处检查当前目录已有关联及其全部可用官方依据，范围与下方按日期筛选的“尚未归属”清单不同。冲突须核对原报告，普通映射不能替代平台核对。</p>}{value.conflicts.length > 0 && <ul>{value.conflicts.map(item => <li key={`${item.scope_id}:${item.sku_id}:${item.seller_sku}`}><Link to={`/catalog/styles/${item.style_id}`}>{item.seller_sku}</Link> · 账号范围{item.scope_id} · 官方子ASIN：{item.official_asins.join("、")}</li>)}</ul>} <Link to="/catalog/production-sources?entry=amazon-listing">查看或导入亚马逊商品清单</Link></StatusMessage>;
  return compact && value.state !== "pending" && value.state !== "incomplete" && value.conflicts.length === 0 ? <details className={styles.evidence}><summary>平台资料核对</summary>{status}</details> : status;
}
