import { useMemo, type RefObject } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Dialog, LinkButton, Pagination, StatusMessage, Table } from "../../design-system";
import { useLoad } from "./useProductionApi";
import { ReadContent, ReadState } from "./WorkbenchFields";
import { WarehouseInventory, type WarehouseStock } from "./WarehouseCenter";
import { FbaBalance } from "./FbaWorkspace";
import type { FbaState } from "./fbaTypes";
import { inventoryStates, type DirectoryRecord } from "./directoryTypes";
import { orderStageProgress } from "./productionTrace";
import type { Document, DocumentPage, Sku } from "./types";
import styles from "./ProductionProgressFlow.module.css";

export function OrderStageBoard({refresh,catalog,page,selectedOrderId,reload,onPage,onOrder}:{refresh:number;catalog:Sku[];page:number;selectedOrderId?:string;reload:()=>void;onPage:(page:number)=>void;onOrder:(order:Document,trigger:HTMLElement)=>void}) {
 const list=useLoad<DocumentPage>(`/api/production/orders?${new URLSearchParams({status:"CONFIRMED",page:String(page),page_size:"5"})}`,refresh,true,true);
 return <section className={styles.stageBoard} aria-label="订单阶段看板"><header><h2 title="当前站点全部已确认订单">订单阶段</h2>{list.value&&<span>{list.value?.total} 笔</span>}</header>
  <ReadContent loading={list.initialLoading} error={list.error} retry={reload}>
   {list.value&&<><div className={styles.scroll}><Table aria-label="订单当前阶段"><thead><tr><th>款号</th><th>订单</th><th>当前阶段</th><th>生产状态</th><th title="当前节点逐规格完成度">节点进度</th></tr></thead><tbody>{list.value.items.map(order=>{
    const codes=[...new Set((order.lines||[]).map(l=>catalog.find(s=>s.sku_id===l.sku_id)?.style_code).filter(Boolean))];
    const number=order.business_number||order.system_number;
    const current=orderStageProgress(order);
    const selected=selectedOrderId===order.id;
    return <tr key={order.id} data-selected={selected||undefined}>
     <th scope="row">{codes.join("、")||"待核"}</th>
     <td><Button variant="quiet" aria-label={`查看订单阶段 ${number}`} aria-current={selected?"true":undefined} title={number} onClick={e=>onOrder(order,e.currentTarget)}>{number.length>18?`#${order.id}`:number}</Button></td>
     <td><span className={styles.stageLabel} data-completed={current.label==="目的仓已收齐"||undefined}>{current.label}</span></td><td>{[...new Set((order.lines||[]).map(line=>line.production_status).filter(Boolean))].join(" / ")}</td>
     <td className={styles.stageProgress}>{current.percent===undefined?"待核":<><progress aria-label={`订单 ${number} ${current.label}`} max={100} value={current.percent}/><span>{current.percent}%</span></>}</td>
    </tr>;
   })}{!list.value.items.length&&<tr><td colSpan={5}>暂无已确认订单</td></tr>}</tbody></Table></div>
   {list.value.total>5&&<Pagination itemLabel="订单" page={list.value.page} totalItems={list.value.total} totalPages={Math.max(1,Math.ceil(list.value.total/5))} onPageChange={onPage}/>}</>}
  </ReadContent>
 </section>;
}

export function OverviewWarehouseDrawer({id,owner,catalog,refresh,reload,onOwner,close,returnFocus}:{id:string;owner:string;catalog:Sku[];refresh:number;reload:()=>void;onOwner:(owner:string)=>void;close:()=>void;returnFocus:RefObject<HTMLElement|null>}) {
 const [params]=useSearchParams();
 const liveFocus=useMemo(()=>({get current(){return returnFocus.current?.isConnected?returnFocus.current:document.querySelector<HTMLButtonElement>(`button[data-overview-warehouse="${id}"]`);}}),[id,returnFocus]);
 const detail=useLoad<DirectoryRecord>(`/api/production/warehouses/${id}`,refresh,true,true);
 return <Dialog open presentation="drawer" size="large" title={detail.current?`${detail.value!.name}库存`:"仓库库存"} description="在库数量" contentClassName={styles.traceDrawer} onOpenChange={open=>{if(!open)close();}} returnFocusTarget={liveFocus}>
  <div className={`${styles.details} ${styles.warehouseDrawer}`}><ReadContent loading={detail.loading} error={detail.error} retry={reload}>
   {detail.current&&<><LinkButton to={`/production/warehouses/${id}?${new URLSearchParams({tab:"stock",...(params.get("stock_goods")?{stock_goods:params.get("stock_goods")!}:{}),...(owner?{owner}:{})})}`}>打开仓库中心</LinkButton>
   {detail.value!.type==="FBA"?<OverviewFbaStock catalog={catalog} id={id} owner={owner} onOwner={onOwner} refresh={refresh} reload={reload}/>:<OverviewOrdinaryStock record={detail.value!} owner={owner} onOwner={onOwner} catalog={catalog} refresh={refresh} reload={reload}/>}</>}
  </ReadContent></div>
 </Dialog>;
}
function OwnerSelect({value,options,onOwner}:{value:string;options:{owner_id:string;owner_name:string}[];onOwner:(id:string)=>void}) {
 return options.length>1||!options.some(s=>s.owner_id===value)?<label className={styles.ownerSelect}>货主 <select aria-label="查看库存货主" value={value} onChange={e=>onOwner(e.target.value)}>{!options.some(s=>s.owner_id===value)&&<option value="">请选择货主</option>}{options.map(s=><option key={s.owner_id} value={s.owner_id}>{s.owner_name}</option>)}</select></label>:null;
}
function OverviewOrdinaryStock({record,owner,onOwner,catalog,refresh,reload}:{record:DirectoryRecord;owner:string;onOwner:(id:string)=>void;catalog:Sku[];refresh:number;reload:()=>void}) {
 const scopes=(record.scopes||[]).filter(s=>s.warehouse_id===record.id);const chosen=owner||scopes[0]?.owner_id||"";
 const ready=record.inventory_state==="READY"&&scopes.some(s=>s.owner_id===chosen);
 const stock=useLoad<WarehouseStock>(`/api/production/inventory/availability?${new URLSearchParams({warehouse_id:record.id,owner_id:chosen})}`,refresh,ready,true);
 const value=stock.current?{...stock.value!,items:stock.value!.items.filter(i=>i.warehouse_id===record.id&&i.owner_id===chosen),scopes:stock.value!.scopes.filter(s=>s.warehouse_id===record.id&&s.owner_id===chosen)}:undefined;
 return <><OwnerSelect value={chosen} options={scopes} onOwner={onOwner}/>{!ready?<StatusMessage kind="info" title={record.inventory_state==="READY"?"货权范围待核":inventoryStates[record.inventory_state||""]||"库存状态待核"}/>:<ReadContent loading={stock.loading} error={stock.error} retry={reload}>{value?<WarehouseInventory key={`${record.id}:${chosen}`} stock={value} catalog={catalog} record={record} owner={chosen} writable={false}/>:!stock.error&&<ReadState/>}</ReadContent>}</>;
}
function OverviewFbaStock({id,owner,onOwner,refresh,reload,catalog}:{catalog:Sku[];id:string;owner:string;onOwner:(id:string)=>void;refresh:number;reload:()=>void}) {
 const state=useLoad<FbaState>(`/api/production/fba/state?warehouse_id=${id}`,refresh,true,true);
 if(!state.current)return <ReadContent loading={state.loading} error={state.error} retry={reload}><ReadState/></ReadContent>;
 const data=state.value!;if(!data.enabled||!data.initialized)return <StatusMessage kind="info" title={!data.enabled?"FBA库存适配未启用":"FBA期初与身份尚未确认"}/>;
 const scopes=data.scopes.filter(s=>s.warehouse_id===id);const scope=scopes.find(s=>s.owner_id===(owner||scopes[0]?.owner_id));
 return <><OwnerSelect value={scope?.owner_id||""} options={scopes.map(s=>({owner_id:s.owner_id,owner_name:`${s.seller_account} · ${s.owner_id}`}))} onOwner={onOwner}/>{scope?<>{scope.simulated&&<StatusMessage kind="info" title="模拟FBA库存 · 真实账号未绑定"/>}<FbaBalance data={data} scope={scope} identities={data.identities.filter(i=>i.scope_id===scope.id)} catalog={catalog}/></>:<StatusMessage kind="warning" title="货权范围待核"/>}</>;
}
