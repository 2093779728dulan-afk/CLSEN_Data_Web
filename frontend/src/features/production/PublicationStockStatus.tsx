import { useState } from "react";
import { Button, LinkButton, StatusMessage } from "../../design-system";
import { useCommand, useLoad } from "./useProductionApi";

type StockUpdate = {
  scope_id: string; warehouse_id: string; owner_id: string; warehouse_name: string;
  status: "updated" | "pending"; issues: { label: string }[]; can_retry: boolean;
};

export function PublicationStockStatus({ reportDate, reportType, revision, canWrite }: {
  reportDate: string; reportType: string; revision: string | number; canWrite: boolean;
}) {
  const [refresh, setRefresh] = useState(0);
  const query = new URLSearchParams({ report_date: reportDate, report_type: reportType });
  const status = useLoad<{ items: StockUpdate[] }>(`/api/production/fba/daily/status?${query}`, `${revision}:${refresh}`);
  const command = useCommand(() => setRefresh(value => value + 1));
  if (status.loading) return <p role="status">正在核对库存更新结果…</p>;
  if (status.error) return <StatusMessage kind="warning" title="库存更新结果暂未读取" action={<Button variant="quiet" onClick={() => setRefresh(value => value + 1)}>重新读取</Button>}>{status.error}</StatusMessage>;
  const items = status.value?.items || [];
  if (!items.length) return null;
  const pending = items.filter(item => item.status === "pending");
  return <section aria-label="日报库存更新结果">
    {pending.length ? pending.map(item => <StatusMessage key={item.scope_id} kind="warning" title={`日报已发布 · ${item.warehouse_name}待更新`}>
      <details><summary>查看原因</summary>{item.issues.map((issue, index) => <p key={index}>{issue.label}</p>)}</details>
      {canWrite && item.can_retry && <Button variant="secondary" disabled={command.busy || command.unknown} onClick={() => command.submit(`/api/production/fba/daily/sync?scope_id=${item.scope_id}`, {})}>重试库存更新</Button>}
      <LinkButton variant="quiet" to={`/production/warehouses/${item.warehouse_id}?owner=${item.owner_id}&fba_view=balance`}>前往库存处理</LinkButton>
    </StatusMessage>) : <StatusMessage kind="success" title="日报已发布 · 库存已更新" />}
    {command.feedback}
  </section>;
}
