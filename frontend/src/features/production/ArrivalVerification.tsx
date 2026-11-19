import { ProductionConfirmDialog } from "./ProductionConfirmDialog";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { Button, StatusMessage } from "../../design-system";
import { DestinationReceiptDialog } from "./DestinationReceiptDialog";
import { FbaReceipts } from "./FbaReceipts";
import { StockDetailWindow } from "./StockDetailWindow";
import { useLoad } from "./useProductionApi";
import { useProductionLeave } from "./useProductionLeave";
import { overviewSearchParams, type OverviewGuard } from "./stockOverview";
import type { TransitItem } from "./WarehouseTransit";
import type { DirectoryRecord } from "./directoryTypes";
import type { FbaState } from "./fbaTypes";
import type { Sku } from "./types";
import styles from "./ArrivalVerification.module.css";

type ArrivalBatch = Pick<TransitItem, "id" | "destination_id" | "owner_id" | "business_number" | "system_number" | "source_name">;

export function ArrivalVerification({ item, refresh, canWrite, saved, onGuardChange }: {
  item: ArrivalBatch; refresh: number; canWrite: boolean; saved: () => void; onGuardChange: (guard: OverviewGuard) => void;
}) {
  const warehouse = useLoad<DirectoryRecord>(`/api/production/warehouses/${item.destination_id}`, refresh, !!item.destination_id, true);
  const record = warehouse.value;
  if (!canWrite) return <StatusMessage kind="info" title="当前账号只读">到仓核验需要相应办理权限。</StatusMessage>;
  if (!item.destination_id || !item.owner_id) return <StatusMessage kind="warning" title="目的仓范围尚未就绪">本批尚未关联明确仓库及货权，请先核对原出货资料。</StatusMessage>;
  if (!record) return <StatusMessage kind={warehouse.error ? "danger" : "info"} title={warehouse.error ? "目的仓读取未完成" : "正在确认目的仓范围"}>{warehouse.error || "批次、仓库和货权核实后即可填写。"}</StatusMessage>;
  if (record.id !== item.destination_id || record.status !== "ACTIVE" || !record.scopes?.some(scope => scope.owner_id === item.owner_id && scope.warehouse_id === record.id) || !["FBA", "FACTORY", "OWN", "THIRD_PARTY"].includes(record.type || "")) return <StatusMessage kind="warning" title="目的仓范围尚未就绪">请核对目的仓身份、启用状态及本批货权；不会改用其他仓库办理。</StatusMessage>;
  return <>
    <div className={styles.batchHeader}>
      <div className={styles.route}>
        {item.source_name && <><span>{item.source_name}</span><ArrowRight size={16} aria-hidden="true" /></>}
        <strong>{record.name}</strong>
      </div>
      <span className={styles.shipment} title="出货单号">{item.business_number || item.system_number}</span>
    </div>
    {warehouse.error && <StatusMessage kind="danger" title="目的仓范围需要重新读取">{warehouse.error}。当前输入保留，请用浏览器刷新重新核实。</StatusMessage>}
    <fieldset style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }} disabled={!warehouse.current}>
      {record.type === "FBA" ? <FbaArrival item={item} refresh={refresh} saved={saved} onGuardChange={onGuardChange} /> : <DestinationReceiptDialog embedded shipmentId={item.id} warehouseId={record.id} ownerId={item.owner_id} canWrite={canWrite} close={() => undefined} saved={saved} onGuardChange={onGuardChange} />}
    </fieldset>
  </>;
}

function FbaArrival({ item, refresh, saved, onGuardChange }: { item: ArrivalBatch; refresh: number; saved: () => void; onGuardChange: (guard: OverviewGuard) => void }) {
  const [revision, setRevision] = useState(0);
  const [guard, setGuard] = useState<OverviewGuard>({ dirty: false, busy: false, unknown: false });
  const receiveGuard = useCallback((value: OverviewGuard) => setGuard(value), []);
  const data = useLoad<FbaState>(`/api/production/fba/state?warehouse_id=${item.destination_id}`, `${refresh}:${revision}`, true, true);
  const catalog = useLoad<{ items: Sku[] }>("/api/production/skus?contract_version=2", `${refresh}:${revision}`, true, true);
  const leave = useProductionLeave(guard.dirty, guard.busy, guard.unknown, overviewSearchParams);
  useEffect(() => { onGuardChange({ ...guard, blocked: leave.blocked }); }, [guard, leave.blocked, onGuardChange]);
  const scope = data.value?.scopes.find(value => value.warehouse_id === item.destination_id && value.owner_id === item.owner_id);
  if (!data.value || !catalog.value) return <StatusMessage kind={data.error || catalog.error ? "danger" : "info"} title={data.error || catalog.error ? "FBA核验资料读取未完成" : "正在读取FBA核验资料"}>{data.error || catalog.error || "正在载入本批来源与原接收流程。"}</StatusMessage>;
  if (!data.value.enabled || !data.value.initialized || !scope) return <StatusMessage kind="warning" title="FBA接收范围尚未就绪">请先在原仓库完成FBA范围与身份核对；普通仓入库不能代替FBA接收。</StatusMessage>;
  return <>
    {(data.error || catalog.error) && <StatusMessage kind="danger" title="核验资料读取未完成">{data.error || catalog.error}。输入保留，当前暂停办理。</StatusMessage>}
    <fieldset style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }} disabled={!data.current || !catalog.current}>
      <FbaReceipts embedded shipmentId={item.id} data={data.value} scope={scope} catalog={catalog.value.items} canWrite refresh={refresh + revision} reload={() => setRevision(value => value + 1)} onReceived={saved} onGuardChange={receiveGuard} />
    </fieldset>
    {leave.prompt}
  </>;
}

export function ArrivalVerificationWindow({ item, canWrite, refresh, saved, close, returnFocus }: { item: ArrivalBatch; canWrite: boolean; refresh: number; saved: () => void; close: () => void; returnFocus: HTMLElement | null }) {
  const [guard, setGuard] = useState<OverviewGuard>({ dirty: false, busy: false, unknown: false });
  const [closing, setClosing] = useState(false);
  const receiveGuard = useCallback((value: OverviewGuard) => setGuard(value), []);
  return <StockDetailWindow open title="收货入库" closeLabel="关闭收货入库" viewKey={`arrival:${item.id}`} dismissDisabled={guard.busy || guard.unknown} returnFocus={returnFocus} onClose={() => { if (guard.busy || guard.unknown) return; if(closing){setClosing(false);return;} if (guard.dirty) setClosing(true); else close(); }}>
    <ProductionConfirmDialog open={closing} onOpenChange={setClosing} title="还有未保存的核验内容" description="继续填写，或明确放弃当前输入后关闭。"><Button onClick={() => setClosing(false)}>继续核验</Button><Button variant="danger" onClick={close}>放弃并关闭核验</Button></ProductionConfirmDialog>
    <div><ArrivalVerification item={item} refresh={refresh} canWrite={canWrite} saved={saved} onGuardChange={receiveGuard} /></div>
  </StockDetailWindow>;
}
