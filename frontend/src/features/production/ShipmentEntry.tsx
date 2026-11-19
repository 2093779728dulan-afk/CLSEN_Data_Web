import { useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { Button, FormField, Input, LinkButton, PageHeader, Pagination, StatusMessage } from "../../design-system";
import { type Document, type DocumentPage } from "./types";
import { useLoad } from "./useProductionApi";
import { ReadContent, ReadState, type WorkbenchStock } from "./WorkbenchFields";
import { ProductionOperationDialog } from "./ProductionOperationDialog";
import { ShipmentPanel } from "./WorkbenchOperations";
import styles from "./DirectoryWorkspace.module.css";

/** All ordinary shipment entries use the same editor as orders and warehouses. */
export function ShipmentEntry({ canWrite }: { canWrite: boolean }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const sourceId = params.get("source_order") || "";
  const legacyChooser = params.get("mode") === "order";
  const candidates = useLoad<DocumentPage>(`/api/production/orders?${new URLSearchParams({ status: "CONFIRMED", selectable: "true", q: query, page: String(page), page_size: "20" })}`, refresh, canWrite && !sourceId && legacyChooser);
  const source = useLoad<Document>(`/api/production/orders/${sourceId}`, refresh, canWrite && !!sourceId, true);
  const stock = useLoad<WorkbenchStock>("/api/production/inventory/availability", refresh, canWrite && !!sourceId, true);
  const close = () => { void navigate("/production/shipments"); };
  const retry = () => setRefresh(value => value + 1);
  if (canWrite && !sourceId && !legacyChooser) {
    const query = new URLSearchParams(params); query.set("flow", "guided"); query.set("purpose", "WAREHOUSE_DISPATCH");
    return <Navigate replace to={`/production/shipments/new?${query}`} />;
  }
  return <>
    <PageHeader title={legacyChooser || sourceId ? "历史订单分配出货" : "仓库出货"} description="旧订单分配入口：选择生产单，接着核对来源与目的地、填写数量、装箱并确认。与订单内使用同一套出货单，无需重复登记。" actions={<LinkButton variant="secondary" to="/production/shipments">返回全部出货</LinkButton>} />
    {!canWrite ? <StatusMessage kind="info" title="当前账号只读">可以查询出货记录；新建需具备写入权限。</StatusMessage> : sourceId ? <ProductionOperationDialog title="新建出货单" description={source.value?.business_number || source.value?.system_number || "正在核对来源生产单"} close={close}>
      <ReadContent loading={source.loading || stock.loading} error={source.error || stock.error} retry={retry}>
        {!source.value || !stock.value ? <ReadState error={source.error || stock.error} /> : source.value.id !== sourceId || source.value.status !== "CONFIRMED" ? <StatusMessage kind="warning" title="来源生产单尚未确认或身份不匹配">请返回全部出货，重新选择已确认生产单。</StatusMessage> : <ShipmentPanel key={sourceId} guided order={source.value} stock={stock.value} stockError={stock.error} canWrite={canWrite} saved={retry} onGuidedClose={close} />}
      </ReadContent>
    </ProductionOperationDialog> : <section className={styles.operationSourcePicker} aria-label="出货来源选择">
      <h2>先选择本次出货的生产单</h2>
      <p>与订单和仓库使用同一套四步向导，选择生产单不会保存或扣减库存。</p>
      <FormField label="查找生产单"><Input type="search" placeholder="订单号 / 工厂 / SKU" value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} /></FormField>
      <FormField label="关联生产单"><select value="" disabled={!candidates.value || !!candidates.error} onChange={event => { const next = new URLSearchParams(); next.set("source_order", event.target.value); setParams(next); }}><option value="">选择已确认生产单</option>{candidates.value?.items.map(order => <option key={order.id} value={order.id}>{order.business_number || order.system_number} · {order.factory_name || "工厂未登记"}</option>)}</select></FormField>
      {candidates.error ? <StatusMessage kind="danger" title="生产单读取失败"><Button variant="secondary" onClick={retry}>重新读取</Button></StatusMessage> : !candidates.value ? <ReadState /> : candidates.value.items.length === 0 ? <StatusMessage kind="info" title="没有匹配的已确认生产单">调整搜索，或先完成生产单确认。</StatusMessage> : <Pagination page={page} totalItems={candidates.value.total} totalPages={Math.max(1, Math.ceil(candidates.value.total / 20))} onPageChange={setPage} />}
      <div className={styles.operationSourceActions}><LinkButton variant="secondary" to="/production/shipments/new?flow=guided&purpose=OUTWARD_ORDER">多订单或混合来源出货</LinkButton><LinkButton variant="secondary" to="/production/shipments/intake?method=table">其他表格与原资料</LinkButton></div>
    </section>}
  </>;
}
