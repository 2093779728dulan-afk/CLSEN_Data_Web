import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, Input, LinkButton, PageHeader, Pagination, StatusMessage, Table } from "../../design-system";
import { useLoad, useSearchDraft } from "./useProductionApi";
import { ReadState, type WorkbenchStock } from "./WorkbenchFields";
import { ReceiptPanel } from "./WorkbenchOperations";
import { knownOrderSum, orderProductName } from "./orderProgress";
import { type Document, type DocumentPage, type OrderLine, type Sku, units } from "./types";
import styles from "./BatchReceiptPage.module.css";

export function BatchReceiptPage({ canWrite }: { canWrite: boolean }) {
  const { generation } = useAuthzGeneration();
  return <BatchReceipt key={generation} canWrite={canWrite} />;
}

function BatchReceipt({ canWrite }: { canWrite: boolean }) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const scope = params.get("orders") || "";
  const [selected, setSelected] = useState<Record<string, Document>>({});
  const [query, setQuery] = useSearchDraft(params.get("q") || "");
  const [refresh, setRefresh] = useState(0);
  const stock = useLoad<WorkbenchStock>("/api/production/inventory/availability", refresh, canWrite);
  const catalog = useLoad<{ items: Sku[] }>("/api/production/skus?contract_version=2", refresh, canWrite);
  const list = useLoad<DocumentPage>(`/api/production/orders?${new URLSearchParams({ status: "CONFIRMED", factory: params.get("factory") || "", q: params.get("q") || "", page: params.get("page") || "1", page_size: "20" })}`, refresh, canWrite && !scope);
  const returnTo=params.get("return_to")||"";const warehouse=params.get("warehouse_id")||"";const owner=params.get("owner_id")||"";
  const back = /^\/production\/(?:warehouses\/[1-9][0-9]*|overview|stock(?:\/forecast)?)(?:\?|$)/.test(returnTo)?returnTo:`/production/orders${params.get("factory") ? `?factory=${encodeURIComponent(params.get("factory")!)}` : ""}`;
  const selection = Object.values(selected);
  const lineCount = selection.reduce((sum, order) => sum + (order.lines?.length || 0), 0);
  const draftId = params.get("receipt_draft") || undefined;
  return <section className={styles.page} aria-label="多订单入库">
    <PageHeader title="批量入库" actions={<LinkButton variant="secondary" to={back}>{back.startsWith("/production/warehouses/")?"返回仓库":back.startsWith("/production/overview")?"返回业务总览":back.startsWith("/production/stock")?"返回库存总览":"返回订单跟进"}</LinkButton>} />
    {!canWrite ? <StatusMessage kind="info" title="当前账号只读">请由有权限的账号登记实际入库。</StatusMessage> : !stock.value || !catalog.value ? <><ReadState error={stock.error || catalog.error} />{(stock.error || catalog.error) && <Button onClick={() => setRefresh(value => value + 1)}>重新读取</Button>}</> : !stock.value?.writes_enabled ? <StatusMessage kind="warning" title="当前环境的库存写入未启用" /> : scope ? <>
      <ReceiptBatchEditor orders={scope} warehouse={warehouse} owner={owner} stock={stock.value} catalog={catalog.value.items} refresh={refresh} canWrite={canWrite} resumeDraftId={draftId} close={()=>{void navigate(back);}} onDraftSaved={id=>{const next=new URLSearchParams(params);if(id)next.set("receipt_draft",id);else next.delete("receipt_draft");setParams(next,{replace:true});}} selectionUrl={`?${new URLSearchParams([...params].filter(([key])=>!["orders","receipt_draft"].includes(key)))}`}/>

    </> : <>
      <form className={styles.search} onSubmit={event => { event.preventDefault(); const next = new URLSearchParams(params); next.set("q", query.trim()); next.set("page", "1"); setParams(next); }}><Input aria-label="查找入库来源订单" placeholder="款号、订单号或工厂" type="search" value={query} onChange={event => setQuery(event.target.value)} /><Button type="submit" variant="secondary">查找</Button></form>
      <details><summary>选择说明</summary><p>可跨页选择，最多20单 / 500条明细；未收到的规格留空。</p></details>
      {list.error ? <StatusMessage kind="danger" title="订单读取失败" action={<Button onClick={() => setRefresh(value => value + 1)}>重新读取订单</Button>}>{list.error}</StatusMessage> : !list.value ? <ReadState /> : <>
        <Table title="选择来源订单"><thead><tr><th>选择</th><th>来源订单 / 工厂</th><th>产品规格</th><th>下单</th><th>已入库</th></tr></thead><tbody>{list.value.items.map(item => <tr key={item.id}><td><input type="checkbox" aria-label={`选择 ${item.business_number || item.system_number}`} checked={!!selected[item.id]} disabled={!item.lines?.length || !selected[item.id] && (selection.length >= 20 || lineCount + (item.lines?.length || 0) > 500)} onChange={event => setSelected(previous => { const next = { ...previous }; if (event.target.checked) next[item.id] = item; else delete next[item.id]; return next; })} /></td><th scope="row">{item.business_number || item.system_number}<small>{item.factory_name || "工厂未登记"} · {item.business_date}</small></th><td>{item.lines?.length ?? "未读取"}个规格</td><td>{units(item.expected_units)}</td><td>{units(item.received_units)}</td></tr>)}</tbody></Table>
        {!list.value.items.length && <p>没有匹配的已确认订单，请调整搜索。</p>}
        <Pagination page={list.value.page} totalItems={list.value.total} totalPages={Math.max(1, Math.ceil(list.value.total / (list.value.page_size || 20)))} itemLabel="订单" onPageChange={page => { const next = new URLSearchParams(params); next.set("page", String(page)); setParams(next); }} />
      </>}
      <section className={styles.selection} aria-label="本批已选订单"><strong>已选{selection.length}单 · {lineCount}个规格</strong><div>{selection.map(item => <Button key={item.id} variant="secondary" aria-label={`移除 ${item.business_number || item.system_number}`} onClick={() => setSelected(previous => { const next = { ...previous }; delete next[item.id]; return next; })}>{item.business_number || item.system_number} ×</Button>)}</div><Button variant="primary" disabled={!selection.length || !list.current} onClick={() => { const next = new URLSearchParams(params); const planned=selection[0];if(!params.get("warehouse_id")&&planned?.receipt_warehouse_id&&planned.receipt_owner_id&&selection.every(item=>item.receipt_warehouse_id===planned.receipt_warehouse_id&&item.receipt_owner_id===planned.receipt_owner_id)&&stock.value?.scopes.some(scope=>scope.warehouse_id===planned.receipt_warehouse_id&&scope.owner_id===planned.receipt_owner_id&&scope.warehouse_status==="ACTIVE"&&["OWN","FACTORY","THIRD_PARTY"].includes(scope.warehouse_type||""))){next.set("warehouse_id",planned.receipt_warehouse_id);next.set("owner_id",planned.receipt_owner_id);}next.set("orders", selection.sort((a, b) => BigInt(a.id) < BigInt(b.id) ? -1 : 1).map(item => `${item.id}:${item.revision}`).join(",")); setParams(next); }}>开始本批入库</Button></section>
    </>}
  </section>;
}

export function ReceiptBatchEditor({orders,warehouse,owner,stock,catalog,refresh,canWrite,resumeDraftId,close,onDraftSaved,saved,selectionUrl,selectBatchOrders=false}:{orders:string;warehouse?:string;owner?:string;stock:WorkbenchStock;catalog:Sku[];refresh:number;canWrite:boolean;resumeDraftId?:string;close:()=>void;onDraftSaved:(id:string)=>void;saved?:()=>void;selectionUrl?:string;selectBatchOrders?:boolean}) {
 const [retry,setRetry]=useState(0);
 const source=useLoad<Omit<Document,"lines">&{lines:(OrderLine&{order_label:string;order_reference?:string})[]}>(`/api/production/receipt-batches/sources?${new URLSearchParams({orders})}`,`${refresh}:${retry}`,canWrite,true);
 const order:Document|undefined=source.value&&{...source.value,...(warehouse?{receipt_warehouse_id:warehouse,receipt_owner_id:owner}:{}),system_number:"本批入库",business_number:[...new Set(source.value.lines.map(line=>line.order_label))].join("、"),factory_name:"本批来源订单",actual_units:"0",notes:"",business_date:null,expected_units:knownOrderSum(source.value.lines.map(line=>line.expected_units))??undefined,received_units:knownOrderSum(source.value.lines.map(line=>line.received_units))??undefined,lines:source.value.lines.map(line=>({...line,sku_label:`${line.order_label} / ${orderProductName(line,catalog)}`,receipt_product_name:orderProductName(line,catalog),receipt_order_reference:line.order_reference||line.order_label}))};
 return source.error?<StatusMessage kind="danger" title="来源订单读取未完成" action={<Button onClick={()=>setRetry(v=>v+1)}>重试读取</Button>}>{source.error}{selectionUrl&&<LinkButton variant="secondary" to={selectionUrl}>重新选择来源订单</LinkButton>}{resumeDraftId&&<LinkButton to={`/production/stock/movements/${resumeDraftId}`}>查看已保存入库草稿</LinkButton>}</StatusMessage>:!order?<ReadState/>:<div className={styles.editor}><ReceiptPanel receiptBatch selectBatchOrders={selectBatchOrders} receiptOrderReferences={[...new Set(source.value!.lines.map(line=>line.order_reference||line.order_label))]} guided order={order} stock={stock} canWrite={canWrite} saved={saved||(()=>undefined)} resumeDraftId={resumeDraftId} onGuidedClose={close} onDraftSaved={onDraftSaved}/></div>;
}
