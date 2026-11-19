import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, FormField, Input, LinkButton, Menu, Pagination, StatusMessage } from "../../design-system";
import { useLoad, useSearchDraft } from "./useProductionApi";
import { ArrivalVerificationWindow } from "./ArrivalVerification";
import type { DirectoryRecord } from "./directoryTypes";
import type { TransportEvent, TransportState } from "./transport";
import { transportTime } from "./transport";
import { TransitOpening, type TransitOpeningRow } from "./TransitOpening";
import { units, type Sku } from "./types";
import { orderProductName } from "./orderProgress";
import { Download } from "lucide-react";
import styles from "./FbaWorkspace.module.css";
import layout from "./WarehouseTransit.module.css";

export type TransitItem = { id:string; business_number:string; system_number:string; business_date:string|null; owner_id:string; warehouse_id:string|null; destination_id:string|null; source_name:string|null; destination_name:string|null; destination_kind:string|null; dispatch_purpose:string; shipped_units:string; received_units:string|null; unreceived_units:string|null; settled_units:string|null; stage:string; eta_overdue:boolean; departed:TransportEvent|null; arrived:TransportEvent|null; duration_hours:string|null; receipt_dates:string[]; planned_dispatch_dates?:string[]; transport:TransportState; cartons?:{id:string;number:string}[]; sources:{fulfillment_mode?:string;id:string;sku_id:string;sku_label:string;actual_units:string;received_units:string|null;unreceived_units:string|null;bindings:{carton_id:string;allocation_id:string|null;units:string;received_units:string}[];allocations:{id?:string;order_id?:string;order_line_id?:string;order_number:string;units:string}[]}[] };
type TransitPage = { warehouse_id:string;owner_id:string;direction:string;items:TransitItem[];total:number;page:number;page_size:number;as_of:string;opening_balances?:TransitOpeningRow[] };
const transitStages: Record<string,string>={RECEIVED:"已收清",EXCEPTION:"运输异常",ARRIVAL_CHECK:"到仓待核",SETTLED:"差异已结案",IN_TRANSIT:"运输中",UNREGISTERED:"未收待核 / 运输未登记"};
const qty=(value:string|null)=>value===null?"待核":units(value);
function transitCsv(data:TransitPage){
  const head=["用途：当前页汇总查看，不可直接作为业务明细导入","货权","方向","来源仓","目的仓","SKU ID","商品规格","已发件数","累计实收件数","未收件数","运输状态","实际发出原文","发出时区","预计到达原文","预计到达时区","实际到达原文","到达时区","仓库实收日","运输耗时小时","读取时点UTC"];
  const body=data.items.flatMap(item=>item.sources.map(source=>[item.business_number||item.system_number,item.owner_id,data.direction==="incoming"?"待运入":"已运出",item.source_name||"未登记",item.destination_name||"未登记",source.sku_id,source.sku_label,source.actual_units,qty(source.received_units),qty(source.unreceived_units),transitStages[item.stage],item.departed?.occurred_local||"未填写",item.departed?.timezone||"",item.transport.record?.arrival_local||"未填写",item.transport.record?.arrival_timezone||"",item.arrived?.occurred_local||"未填写",item.arrived?.timezone||"",item.receipt_dates.join(" / ")||"未登记",item.duration_hours??"未知",data.as_of]));
  for(const row of data.opening_balances??[]) body.push([`平台在途期初 ${row.snapshot_on}`,data.owner_id,"待运入","","",row.sku_id,row.sku_label,"","",row.units,"平台已发","","","","","","","","",data.as_of]);
  const cell=(input:string|undefined)=>{const value=input??"";return `"${(/^[=+@\t\r-]/.test(value)?"'":"")+value.replaceAll('"','""')}"`;};
  return "\ufeff"+[head,...body].map(row=>row.map(cell).join(",")).join("\r\n");
}
export function WarehouseTransit({record,owner,canWrite,refresh}:{record:DirectoryRecord;owner:string;canWrite:boolean;refresh:number}){
  const [params,setParams]=useSearchParams();const direction=params.get("transit_direction")==="outgoing"?"outgoing":"incoming";
  const page=/^[1-9][0-9]*$/.test(params.get("transit_page")||"")?Number(params.get("transit_page")):1;
  const query=params.get("transit_q")||"",node=params.get("transit_node")||"",exactSku=params.get("sku_id")||"";const [draft,setDraft]=useSearchDraft(query);
  const [composing,setComposing]=useState(false);
  const searchPending=composing||draft.trim()!==query;
  useEffect(()=>{
    if(composing||draft.trim()===query)return;
    const timer=window.setTimeout(()=>setParams(previous=>{const next=new URLSearchParams(previous);if(draft.trim())next.set("transit_q",draft.trim());else next.delete("transit_q");next.delete("transit_page");return next;},{replace:true}),300);
    return()=>window.clearTimeout(timer);
  },[draft,query,composing,setParams]);
  const [revision,setRevision]=useState(0);const [receipt,setReceipt]=useState<{item:TransitItem;trigger:HTMLElement}>();
  const data=useLoad<TransitPage>(`/api/production/inventory/warehouse-transit?${new URLSearchParams({warehouse_id:record.id,...(owner?{owner_id:owner}:{}),direction,page:String(page),q:query,node,...(exactSku?{sku_id:exactSku}:{})})}`,`${refresh}:${revision}`,true,true);
  const catalog=useLoad<{items:Sku[]}>("/api/production/skus?contract_version=2",refresh);
  const change=(values:Record<string,string>)=>{const next=new URLSearchParams(params);for(const [key,value] of Object.entries(values)){if(value)next.set(key,value);else next.delete(key);}setParams(next);};
  const canTransfer=canWrite&&record.status==="ACTIVE"&&["FACTORY","OWN","THIRD_PARTY"].includes(record.type||"")&&record.scopes?.some(s=>s.owner_id===owner);
  return <section className={styles.workspace} aria-label="仓库运输">
    <header className={layout.toolbar}><div className={layout.directions} role="group" aria-label="运输方向"><Button variant="quiet" aria-pressed={direction==="incoming"} onClick={()=>change({transit_direction:"incoming",transit_page:""})}>待运入</Button><Button variant="quiet" aria-pressed={direction==="outgoing"} onClick={()=>change({transit_direction:"outgoing",transit_page:""})}>已运出</Button></div>{canTransfer&&<LinkButton variant="primary" to={`/production/shipments/new?${new URLSearchParams({flow:"guided",purpose:"LOGISTICS_TRANSFER",warehouse_id:record.id,owner_id:owner})}`}>登记仓间发运</LinkButton>}</header>
    <p className={styles.note}>发出未收与两端在库分开。实际发运有依据才标运输中，物流到达/签收后未收清标到仓待核；预计到达不自动入库。运输记录与原出货、分批接收共用同一事实。</p>
    {!owner&&<StatusMessage kind="info" title="逐批保留货权">尚未选择货权，显示本仓明确关联批次及各自货权；不汇总为同一库存范围。</StatusMessage>}
    {exactSku&&<StatusMessage kind="info" title={`当前按稳定SKU ${exactSku}筛选`}>数量只显示该规格，不代表整批数量。<Button variant="quiet" onClick={()=>change({sku_id:"",transit_page:""})}>查看全部SKU</Button></StatusMessage>}
    <form className={layout.filters} role="search" aria-label="查找运输批次" onSubmit={e=>{e.preventDefault();if(!composing)change({transit_q:draft.trim(),transit_page:""});}}><FormField label="查找批次或SKU"><Input type="search" value={draft} onChange={e=>setDraft(e.target.value)} onCompositionStart={()=>setComposing(true)} onCompositionEnd={e=>{setComposing(false);setDraft(e.currentTarget.value);}} placeholder="批次号 / 款号 / 规格"/></FormField><FormField label="最新物流节点筛选"><select value={node} onChange={e=>change({transit_node:e.target.value,transit_page:""})}><option value="">全部节点</option><option value="UNREGISTERED">未登记运输节点</option><option value="IN_TRANSIT">已发运 / 运输中</option><option value="ARRIVED">物流到达</option><option value="SIGNED">物流签收</option><option value="EXCEPTION">运输异常</option></select></FormField></form>
    {data.error&&<StatusMessage kind="danger" title="运输读取未完成">{data.error}。已读取记录保留，不能把失败当成没有运输。</StatusMessage>}
    {!data.value&&!data.error&&<p role="status">正在读取运输批次…</p>}
    {data.value&&<><div className={layout.listHeader}><h2>{direction==="incoming"?"本仓待运入及接收历史":"从本仓发出的运输"}</h2><Button variant="quiet" icon={<Download size={16}/>} title="导出当前筛选的当前页，仅用于查看" disabled={!data.current||searchPending} onClick={()=>{const url=URL.createObjectURL(new Blob([transitCsv(data.value!)],{type:"text/csv;charset=utf-8"}));const anchor=document.createElement("a");anchor.href=url;anchor.download=`仓库运输-${record.id}-${direction}-第${page}页-查看.csv`;anchor.click();URL.revokeObjectURL(url);}}>导出当前页</Button></div>
    <TransitOpening rows={data.value.opening_balances}/>
    {!data.value.items.length&&!data.value.opening_balances?.length&&<StatusMessage kind="info" title="当前范围没有匹配批次">调整批次、SKU或节点筛选；没有记录不代表库存为零。</StatusMessage>}
    {data.value.items.map(item=><article key={item.id} className={styles.panel} aria-label={`运输批次 ${item.business_number||item.system_number}`}><header className={layout.batchHeader}><h3>{item.business_number||item.system_number}</h3><strong>{transitStages[item.stage]}</strong>{item.eta_overdue&&<span className={styles.error}>已超过预计到达，尚无到达记录</span>}</header><p className={styles.note}>{item.source_name||"来源地点未登记"} → {item.destination_name||"目的地点未登记"} · 货权{item.owner_id} · {item.dispatch_purpose==="LOGISTICS_TRANSFER"?"独立仓间发运，不累计订单已发":"原出货批次"}</p>
      <dl className={styles.summary}>{[["已发",units(item.shipped_units)],["累计实收",qty(item.received_units)],["未收",qty(item.unreceived_units)],["差异已结案",qty(item.settled_units)]].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <details><summary>运输时间与资料</summary><div className={styles.fields}><p>计划发运日：{item.planned_dispatch_dates?.length?item.planned_dispatch_dates.join(" / "):"未登记"}（既有出库安排，仅日期）</p><p>出库业务日：{item.business_date||"未填写"}（仅日期）</p><p>实际发出：{item.departed?transportTime(item.departed.occurred_local,item.departed.timezone):"未填写"}</p><p>预计到达：{item.transport.record?.arrival_local?transportTime(item.transport.record.arrival_local,item.transport.record.arrival_timezone):"未填写"}</p><p>物流到达：{item.arrived?transportTime(item.arrived.occurred_local,item.arrived.timezone):"未填写"}</p><p>仓库实收日：{item.receipt_dates.length?item.receipt_dates.join(" / "):"尚无实收记录"}</p><p>运输耗时：{item.duration_hours===null?"未知，需明确发出与到达时点":`${item.duration_hours}小时`}</p></div>
      <p>最新节点：{item.transport.latest_event?transportTime(item.transport.latest_event.occurred_local,item.transport.latest_event.timezone):"运输未登记"} · 承运资料{item.transport.record?`${item.transport.record.carrier} / ${item.transport.record.tracking_number}`:"未填写"}{item.transport.source_revision_current===false&&" · 关联原出货修订，请先核对更正"}</p></details>
      {item.transport.source_revision_current === false && <StatusMessage kind="warning" title="原出货已更正，请核对运输资料"/>}
      <div className={styles.scroll} tabIndex={0}><table className={styles.table} aria-label={`${item.business_number||item.system_number}运送规格`}><thead><tr><th>款号 / SKU</th><th>已发</th><th>实收</th><th>未收</th><th>货物来源</th></tr></thead><tbody>{item.sources.map(source=><tr key={source.id}><th scope="row">{orderProductName(source,catalog.value?.items||[])}</th><td>{units(source.actual_units)}</td><td>{qty(source.received_units)}</td><td>{qty(source.unreceived_units)}</td><td><details><summary>查看发货来源</summary>{source.bindings.length?source.bindings.map(b=><p key={`${b.carton_id}:${b.allocation_id}`}>{b.carton_id?`发货箱 ${item.cartons?.find(box=>String(box.id)===b.carton_id)?.number||"箱号待核"}`:"本批货物"} · 发出{b.units}件，已收{b.received_units}件</p>):<p>尚未核对箱来源分配，实收余量保持待核。</p>}{source.allocations.map((a,i)=><p key={i}>关联订单 {a.order_number} · {a.units}件</p>)}</details></td></tr>)}</tbody></table></div>
      <div className={layout.batchActions}><Menu label="更多" items={[{id:"source",label:"查看原出货",href:`/production/shipments/${item.id}`},{id:"transport",label:"运输时间与更正",href:`/production/shipments/${item.id}#transport`}]}/>{direction==="incoming"&&canWrite&&record.status==="ACTIVE"&&item.destination_kind!=="LOCATION"&&!["RECEIVED","SETTLED"].includes(item.stage)&&<Button variant="primary" disabled={!data.current||searchPending} onClick={event=>setReceipt({item,trigger:event.currentTarget})}>开始到仓核验</Button>}</div>
    </article>)}{(data.value.total>data.value.page_size||data.value.page>1)&&<Pagination page={data.value.page} totalItems={data.value.total} totalPages={Math.ceil(data.value.total/data.value.page_size)} onPageChange={v=>change({transit_page:String(v)})}/>}<p className={styles.note}>读取于{data.value.as_of}；导出仅含当前页、当前筛选，不能回导入账。</p></>}
    {receipt&&<ArrivalVerificationWindow item={receipt.item} returnFocus={receipt.trigger} canWrite={canWrite} refresh={refresh} close={()=>{setReceipt(undefined);setRevision(v=>v+1);}} saved={()=>setRevision(v=>v+1)}/>}
  </section>;
}
