import { useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { FileText, Repeat2 } from "lucide-react";
import { Button, FormField, Input, LinkButton, Pagination, StatusMessage } from "../../design-system";
import { type Document, type DocumentPage } from "./types";
import { type DirectoryRecord } from "./directoryTypes";
import { type WorkbenchStock, ReadContent, ReadState } from "./WorkbenchFields";
import { useLoad } from "./useProductionApi";
import { ReceiptPanel, ShipmentPanel } from "./WorkbenchOperations";
import styles from "./DirectoryWorkspace.module.css";
import { ProductionOperationDialog } from "./ProductionOperationDialog";
const base = "/api/production/";
export function WarehouseOrderPanel({ mode, record, owner, stock, canWrite, close, saved, refresh }: { mode: string; record: DirectoryRecord; owner: string; stock: WorkbenchStock; canWrite: boolean; close: () => void; saved: () => void; refresh: number }) {
  const [params, setParams] = useSearchParams(); const orderId = params.get("source_order") || ""; const [choosing, setChoosing] = useState(!orderId); const [query, setQuery] = useState(""); const [page, setPage] = useState(1);
  const candidates = useLoad<DocumentPage>(`${base}orders?${new URLSearchParams({ status: "CONFIRMED", q: query, page: String(page), page_size: "20" })}`, refresh);
  const source = useLoad<Document>(`${base}orders/${orderId}`, refresh, !!orderId, true);
  if(mode==="ship"&&!params.get("shipment")&&!orderId)return <Navigate replace to={`/production/shipments/new?${new URLSearchParams({flow:"guided",purpose:"WAREHOUSE_DISPATCH",warehouse_id:record.id,owner_id:owner})}`}/>;
  if(mode==="receive"&&!params.get("receipt_draft")&&!orderId)return <Navigate replace to={`/production/orders/receipts/new?${new URLSearchParams({warehouse_id:record.id,owner_id:owner,return_to:`/production/warehouses/${record.id}?tab=records&mode=receive&owner=${owner}`})}`}/>;
  const chosen = source.value; const sameWarehouse = chosen?.receipt_warehouse_id === record.id && chosen.receipt_owner_id === owner;
  const action = mode === "receive" ? "入库" : "出货装箱";
  return <ProductionOperationDialog title={mode === "receive" ? action : "新建出货单"} description={`${record.name} · ${stock.scopes.find(s => s.owner_id === owner)?.owner_name || "货权待核"}`} close={close}>
    {choosing || !orderId ? <section className={styles.operationSourcePicker} aria-label={`${action}来源生产单`}>
      <div><h2>先选择来源生产单</h2><p>本次实际入库或出货须关联已确认生产单；选择只建立来源关系，不会自动改变库存。</p></div>
      <FormField label="查找生产单"><Input type="search" value={query} placeholder="输入订单号 / 工厂 / SKU" onChange={e => { setQuery(e.target.value); setPage(1); }} /></FormField>
      <FormField label="关联生产单"><select value={orderId} onChange={e => { const next = new URLSearchParams(params); if (e.target.value) next.set("source_order", e.target.value); else next.delete("source_order"); next.delete("shipment"); next.delete("receipt_draft"); setParams(next); if (e.target.value) setChoosing(false); }}><option value="">选择已确认生产单</option>{orderId && !candidates.value?.items.some(o => o.id === orderId) && <option value={orderId}>{chosen?.business_number || chosen?.system_number || `订单 ${orderId}`}</option>}{candidates.value?.items.map(o => <option key={o.id} value={o.id}>{o.business_number || o.system_number} · {o.factory_name || "工厂未登记"}{o.receipt_warehouse_id === record.id ? " · 本仓" : ""}</option>)}</select></FormField>
      {candidates.value && <Pagination page={page} totalItems={candidates.value.total} totalPages={Math.max(1, Math.ceil(candidates.value.total / 20))} onPageChange={setPage} />}{candidates.error && <ReadState error={candidates.error} />}
      {orderId && <div className={styles.operationSourceActions}><Button variant="secondary" onClick={() => setChoosing(false)}>继续使用已选生产单</Button></div>}
    </section> : <ReadContent loading={source.loading} error={source.error} retry={saved}>{!chosen ? !source.error && <ReadState /> : <div className={styles.guidedOperationBody}>
      <section className={styles.guidedSourceSummary} aria-label="当前关联生产单">
        <div className={styles.guidedSourceIdentity}><small>本次关联生产单</small><strong>{chosen.business_number || chosen.system_number || `订单 ${orderId}`}</strong></div>
        <div className={styles.guidedSourceActions}>
          <LinkButton icon={<FileText size={16} />} variant="secondary" to={`/production/orders/${chosen.id}`}>查看生产单</LinkButton>
          <Button icon={<Repeat2 size={16} />} variant="quiet" onClick={() => setChoosing(true)}>更换生产单</Button>
        </div>
      </section>
      {!sameWarehouse && <StatusMessage kind="warning" title="与原单计划入库范围不同">本次将明确登记到 {record.name}，不会修改原计划。请核对实际交接。</StatusMessage>}
      {mode === "receive" ? <ReceiptPanel compact guided resumeDraftId={params.get("receipt_draft") || undefined} onGuidedClose={close} key={chosen.id} order={{ ...chosen, receipt_warehouse_id: record.id, receipt_owner_id: owner }} stock={stock} canWrite={canWrite} saved={saved} onDraftSaved={id => { const next = new URLSearchParams(params); if (id) next.set("receipt_draft", id); else next.delete("receipt_draft"); setParams(next, { replace: true }); }} /> : <ShipmentPanel scopeLocked guided onGuidedClose={close} key={chosen.id} order={{ ...chosen, receipt_warehouse_id: record.id, receipt_owner_id: owner }} stock={stock} canWrite={canWrite} saved={saved} />}
    </div>}</ReadContent>}
  </ProductionOperationDialog>;
}

