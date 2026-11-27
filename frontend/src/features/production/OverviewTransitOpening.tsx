import { Disclosure } from "../../design-system";
import { Button, StatusMessage } from "../../design-system";
import { orderProductName } from "./orderProgress";
import { TransitOpening, type TransitOpeningRow } from "./TransitOpening";
import type { Sku } from "./types";
import { useLoad } from "./useProductionApi";
import styles from "./OverviewTransitOpening.module.css";

type OpeningRead = {
  opening_scope?: { warehouse_id: string; owner_id: string };
  opening_balances?: TransitOpeningRow[];
};

export function OverviewTransitOpening({ refresh, warehouse, query, catalog, enabled = true, retry }: {
  refresh: number; warehouse: string; query: string; catalog: Sku[]; enabled?: boolean; retry: () => void;
}) {
  const data = useLoad<OpeningRead>("/api/production/inventory/transport-summary", refresh, enabled, true);
  if (!enabled) return null;
  if (data.error) return <StatusMessage kind="danger" title="历史在途读取失败" action={<Button onClick={retry}>重试历史在途</Button>}>{data.error}</StatusMessage>;
  if (data.initialLoading) return <p role="status">正在读取历史在途…</p>;
  const search = query.trim().toLocaleLowerCase();
  const rows = (data.value?.opening_balances || [])
    .filter(() => !warehouse || warehouse === data.value?.opening_scope?.warehouse_id)
    .map(row => ({ ...row, sku_label: orderProductName({ sku_id: row.sku_id, sku_label: row.sku_label }, catalog) }))
    .filter(row => !search || row.sku_label.toLocaleLowerCase().includes(search));
  if (!rows.length) return null;
  const total = rows.reduce((sum, row) => sum + BigInt(row.units), 0n).toLocaleString("zh-CN");
  return <section className={styles.opening} aria-label="历史在途">
    <Disclosure>
      <summary><h2>历史在途</h2><strong>{total} 件</strong><span>{rows.length} SKU</span><time>{rows[0]!.snapshot_on}</time></summary>
      <div className={styles.body}><TransitOpening rows={rows}/></div>
    </Disclosure>
  </section>;
}
