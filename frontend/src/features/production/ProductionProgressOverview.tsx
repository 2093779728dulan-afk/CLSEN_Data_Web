import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { requestApi } from "../../api/client";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Button, Input, LinkButton, Menu, Pagination, StatusMessage } from "../../design-system";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { useLoad, useSearchDraft } from "./useProductionApi";
import { ProductionProgressFlow } from "./ProductionProgressFlow";
import { Search } from "lucide-react";
import { OrderStageBoard, OverviewWarehouseDrawer } from "./ProductionOverviewPanels";
import { ProductionTraceDrawer } from "./ProductionTraceDrawer";
import { orderTrace, shipmentTrace, chainTrace, focusedChainGroup, orderShipments, quantity, type ChainPage, type ChainGroup, type TraceNode, type TraceGraph } from "./productionTrace";
import { useProductionLeave } from "./useProductionLeave";
import { OrderCompletionAction } from "./OrderCompletionAction";
import { OverviewTransitOpening } from "./OverviewTransitOpening";
import { OrderProgressDialog } from "./OrderProgressDialog";
import { ArrivalVerificationWindow } from "./ArrivalVerification";
import type { Document, Sku } from "./types";
import type { TransitItem } from "./WarehouseTransit";
import type { OverviewGuard } from "./stockOverview";
import styles from "./ProductionProgressFlow.module.css";
type Directory={id:string;name:string;type?:string;status?:string};
function useDirectory(path:string,refresh:number) {
 const lastRefresh=useRef(0);
 const {generation,registerSensitivePurge,productionReads}=useAuthzGeneration();
 const revision=useSyncExternalStore(productionReads.subscribe,productionReads.version);
 const key=`${generation}:${refresh}:${revision}:${path}`,cacheKey=`directory:${path}`;
 const [state,setState]=useState<{owner:typeof productionReads;key:string;items:Directory[];error?:string}|undefined>(()=>({owner:productionReads,key,items:productionReads.peek<Directory[]>(cacheKey)||[]}));
 useEffect(()=>registerSensitivePurge(()=>setState(undefined)),[registerSensitivePurge]);
 useEffect(()=>{let active=true;const force=lastRefresh.current!==refresh;lastRefresh.current=refresh;const job=productionReads.read(cacheKey,async signal=>{const items:Directory[]=[];let pages=1;for(let page=1;page<=pages;page++){const result=await requestApi<{items:Directory[];total:number;page_size:number}>(`${path}${path.includes("?")?"&":"?"}page=${page}`,{signal});items.push(...result.items);pages=Math.ceil(result.total/(result.page_size||20));}return items;},force?0:300_000);void job.promise.then(items=>{if(active&&!job.controller.signal.aborted)setState({owner:productionReads,key,items});}).catch((error:unknown)=>{if(active&&!job.controller.signal.aborted)setState({owner:productionReads,key,items:[],error:error instanceof Error?error.message:"目录读取失败"});});return()=>{active=false;};},[path,key,cacheKey,productionReads,refresh]);
 return {value:state?.owner===productionReads?{items:state.items}:undefined,error:state?.owner===productionReads&&state.key===key?state.error:undefined};
}
const pageNumber=(v:string|null)=>v&&/^[1-9][0-9]*$/.test(v)&&Number(v)<=1000000?Number(v):1;
function Chain({title,subtitle,graph,open,actions,highlighted}:{title:string;subtitle:string;graph:TraceGraph;open:(node:TraceNode,trigger:HTMLElement)=>void;actions?:ReactNode;highlighted?:boolean}) {return <article data-search-match={highlighted||undefined} data-expanded-chain={graph.nodes.length>3||undefined} className={styles.root} aria-label={title} aria-description={subtitle}><header className={styles.rootHeader}><div><strong title={`${title} · ${subtitle}`}>{title}</strong></div>{actions}</header><ProductionProgressFlow graph={graph} onOpen={open} label={title}/></article>;}
function routeTitle(group:ChainGroup,warehouses:Directory[]) {
 const factories=[...new Set(group.orders.map(o=>o.factory_name||"工厂待核"))];
 const receipts=[...new Set(group.orders.map(o=>warehouses.find(w=>w.id===o.receipt_warehouse_id)?.name).filter(Boolean))];
 const destinations=group.shipments.length?[...new Set(group.shipments.map(s=>s.destination_name||"目的仓待登记"))]:[...new Set(group.orders.map(o=>warehouses.find(w=>o.destination_type==="WAREHOUSE"&&w.id===o.destination_id)?.name||o.destination).filter(Boolean))].map(name=>`计划 ${name}`);
 return [...(group.orders.length?[factories.join("、"),receipts.join("、")||"生产直发／入库仓待核"]:[group.shipments[0]?.source_name||"来源待核"]),destinations.join("、")||"目的仓待登记"].join(" → ");
}
export default function ProductionProgressOverview({canWrite,viewSwitch}:{canWrite:boolean;viewSwitch?:ReactNode}) {
 const [params,setParams]=useSearchParams();const location=useLocation();const navigate=useNavigate();const {generation,preferenceScope,registerSensitivePurge}=useAuthzGeneration();
 const [refresh,setRefresh]=useState(0);const [query,setQuery]=useSearchDraft(params.get("q")||"");const [notice,setNotice]=useState("");
 const [editor,setEditor]=useState<{order:Document;trigger:HTMLElement}>();const [arrival,setArrival]=useState<{item:TransitItem;trigger:HTMLElement}>();
 const [completionGuards,setCompletionGuards]=useState<Record<string,{busy:boolean;unknown:boolean}>>({});
 const completionGuard=useCallback((id:string,busy:boolean,unknown:boolean)=>setCompletionGuards(previous=>previous[id]?.busy===busy&&previous[id]?.unknown===unknown?previous:{...previous,[id]:{busy,unknown}}),[]);
 const [transportGuard,setTransportGuard]=useState<OverviewGuard>({dirty:false,busy:false,unknown:false});
 const transportGuardChanged=useCallback((guard:OverviewGuard)=>setTransportGuard(previous=>previous.dirty===guard.dirty&&previous.busy===guard.busy&&previous.unknown===guard.unknown?previous:guard),[]);

 const chainFocus=useRef<HTMLElement|null>(null);const warehouseFocus=useRef<HTMLElement|null>(null);const focus=useRef<HTMLElement|null>(null);const switchRef=useRef<HTMLDivElement>(null);
 useEffect(()=>registerSensitivePurge(()=>{setEditor(undefined);setArrival(undefined);setNotice("");setCompletionGuards({});setTransportGuard({dirty:false,busy:false,unknown:false});focus.current=null;}),[registerSensitivePurge]);
 const q=params.get("q")||"",factory=params.get("factory")||"",warehouse=params.get("warehouse")||"";
 const productionProgress=params.get("progress")==="completed"?"completed":params.get("progress")==="active"?"active":"all";
 const chainProgress=params.get("chain_progress")==="completed"?"completed":params.get("chain_progress")==="all"?"all":"active";
 const page=pageNumber(params.get("page"));const kind=params.get("trace_kind")||"",target=params.get("trace_id")||"",stage=params.get("trace_stage")||"";
 const validTarget=/^[1-9][0-9]*$/.test(target)&&["order","shipment"].includes(kind);
 const paramsWriter=useRef(setParams);paramsWriter.current=setParams;
 const change=useCallback((values:Record<string,string>)=>paramsWriter.current(previous=>{const next=new URLSearchParams(previous);for(const [k,v] of Object.entries(values)){if(v)next.set(k,v);else next.delete(k);}return next;}),[]);
 const reset={page:"",batch_page:"",branch_order:"",branch_page:"",expand_chain:"",focus_order:"",trace_kind:"",trace_id:"",trace_stage:"",trace_summary:"",receipt_edit:"",receipt_orders:"",receipt_draft:""};
 const filter=(key:string,value:string)=>change({...reset,[key]:value});
 const chains=useLoad<ChainPage>(`/api/production/inventory/progress-chains?${new URLSearchParams({page:String(page),page_size:"5",q,factory,warehouse_id:warehouse,progress:productionProgress,chain_progress:chainProgress})}`,refresh,true,true);
 const inPage=chains.value?.items.some(g=>(kind==="order"?g.orders:[...g.shipments,...(g.related_shipments||[])]).some(r=>r.id===target));
 const targetChains=useLoad<ChainPage>(`/api/production/inventory/progress-chains?${new URLSearchParams({trace_kind:kind,trace_id:target,page_size:"5"})}`,refresh,validTarget&&!inPage&&!chains.loading,true);
 const factories=useDirectory("/api/production/factories?status=",refresh),warehouses=useDirectory("/api/production/warehouses",refresh);
 const catalog=useLoad<{items:Sku[]}>("/api/production/skus?contract_version=2",refresh);
 const stock=useLoad<{items:{warehouse_id:string;owner_id:string;on_hand_units:string|null}[];scopes:{warehouse_id:string;owner_id:string}[]}>("/api/production/inventory/availability?projection=summary",refresh);
 const stockWarehouse=params.get("stock_warehouse")||"";
 const groups=useMemo(()=>validTarget&&!inPage?(targetChains.value?.detail_scope==="complete_chain_groups"?targetChains.value.items:[]):chains.value?.detail_scope==="complete_chain_groups"?chains.value.items:[],[validTarget,inPage,targetChains.value,chains.value]);
 const scope=`${preferenceScope}:${generation}`,focused=params.get("focus_order")||"";
 const graphs=useMemo(()=>groups.map(group=>({group,graph:chainTrace(group,scope,group.orders.some(o=>o.id===focused)?focused:undefined,catalog.value?.items||[])})),[groups,scope,focused,catalog.value?.items]);
 const allOrders=groups.flatMap(g=>g.orders),allBatches=groups.flatMap(g=>[...g.shipments,...(g.related_shipments||[])]);
 const selectedGroup=groups.find(g=>(kind==="order"?g.orders:[...g.shipments,...(g.related_shipments||[])]).some(r=>r.id===target));
 const scopedGroup=selectedGroup?focusedChainGroup(selectedGroup,focused):undefined;
 useEffect(()=>{
  if(!validTarget||!selectedGroup||selectedGroup.orders.some(order=>order.status==="VOID"))return;
  const actualProgress=selectedGroup.completed?"completed":"active";
  if(chainProgress!==actualProgress)change({chain_progress:actualProgress});
 },[validTarget,selectedGroup,chainProgress,change]);
 const selectedOrder=allOrders.find(o=>kind==="order"&&o.id===target),selectedBatch=allBatches.find(b=>kind==="shipment"&&b.id===target);
 const selected=params.get("trace_summary")==="1"?graphs.flatMap(v=>v.graph.nodes).find(n=>n.kind===kind&&n.rootId===target&&n.stage===stage):graphs.flatMap(v=>v.graph.nodes).find(n=>!n.summary&&n.kind===kind&&n.rootId===target&&n.stage===stage)||(selectedOrder?orderTrace(selectedOrder,scope,catalog.value?.items||[]).nodes.find(n=>n.stage===stage):selectedBatch?shipmentTrace(selectedBatch,scope).nodes.find(n=>n.stage===stage):undefined);
 const open=useCallback((node:TraceNode,trigger:HTMLElement)=>{
  focus.current=trigger;
  const sourceGroup=groups.find(item=>(node.kind==="order"?item.orders:item.shipments).some(record=>record.id===node.rootId));
  const group=sourceGroup?focusedChainGroup(sourceGroup,focused):undefined;
  const single=node.summary&&node.stage==="transport"&&group?.shipments.length===1?group.shipments[0]:undefined;
  change({trace_kind:single?"shipment":node.kind,trace_id:single?.id||node.rootId,trace_stage:node.stage,trace_summary:single?"":node.summary?"1":""});
 },[change,groups,focused]);
 const drawerBatch=selected?.summary&&selected.stage==="transport"&&scopedGroup?.shipments.length===1?scopedGroup.shipments[0]:selectedBatch;
 const drawerNode=selected?.summary&&selected.stage==="transport"&&drawerBatch?shipmentTrace(drawerBatch,scope).nodes.find(node=>node.stage==="transport")||selected:selected;

 const close=()=>change({trace_stage:"",trace_summary:"",receipt_edit:"",receipt_orders:"",receipt_draft:""});const linkState={overviewReturn:`${location.pathname}${location.search}`};
 const savedOrder=(order:Document)=>{setRefresh(v=>v+1);setNotice(`订单 ${order.business_number||order.system_number} 完成状态已更新；生产完成与总链路到齐分别显示。`);change({trace_kind:"",trace_id:"",trace_stage:"",trace_summary:""});switchRef.current?.querySelector<HTMLButtonElement>("button")?.focus();};
 return <div className={styles.page}>{!arrival&&params.get("receipt_edit")!=="1"&&<OverviewLeaveGuard dirty={transportGuard.dirty} busy={transportGuard.busy||Object.values(completionGuards).some(v=>v.busy)} unknown={transportGuard.unknown||Object.values(completionGuards).some(v=>v.unknown)}/>}
 <header className={styles.header}><div className={styles.heading}><h1>业务总览</h1>{viewSwitch}</div><Menu label="更多" items={[
  {id:"orders",label:"订单办理",onSelect:()=>{void navigate("/production/orders",{state:linkState});}},
  ...(canWrite?[{id:"new-shipment",label:"新建仓库出货",onSelect:()=>{void navigate(`/production/shipments/intake?${new URLSearchParams({return_to:linkState.overviewReturn})}`,{state:linkState});}}]:[]),
  {id:"shipments",label:"出货批次",onSelect:()=>{void navigate("/production/shipments",{state:linkState});}},
  {id:"table",label:"表格与导出",onSelect:()=>change({overview_view:"table"})},
  {id:"refresh",label:"刷新",onSelect:()=>setRefresh(v=>v+1)}
 ]}/></header>
 <div className={styles.toolbar}><form className={styles.searchForm} onSubmit={e=>{e.preventDefault();filter("q",query.trim());}}><Input aria-label="搜索订单、款号或出货批次" placeholder="搜索款号、订单或出货批次" value={query} onChange={e=>setQuery(e.target.value)}/><Button type="submit" variant="quiet" icon={<Search size={18}/>} aria-label="搜索" title="搜索"/></form>
 <details className={styles.filterPanel}><summary>筛选{[factory,warehouse,productionProgress!=="all"?productionProgress:""].filter(Boolean).length?` · ${[factory,warehouse,productionProgress!=="all"?productionProgress:""].filter(Boolean).length}`:""}</summary><div className={styles.filters}><label>生产工厂 <select value={factory} onChange={e=>filter("factory",e.target.value)}><option value="">全部工厂</option>{factories.value?.items.map(f=><option key={f.id} value={f.id}>{f.name}</option>)}</select></label><label>仓库 <select value={warehouse} onChange={e=>filter("warehouse",e.target.value)}><option value="">全部仓库</option>{warehouses.value?.items.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select></label><label>生产跟进 <select aria-label="生产人工完成状态" value={productionProgress} onChange={e=>filter("progress",e.target.value)}><option value="all">全部生产状态</option><option value="active">人工未完成</option><option value="completed">人工已完成</option></select></label>{(q||factory||warehouse||target||productionProgress!=="all")&&<Button variant="quiet" onClick={()=>change({...reset,q:"",factory:"",warehouse:"",progress:"all"})}>清空筛选与定位</Button>}</div></details></div>

 {(factories.error||warehouses.error)&&<StatusMessage kind="danger" title="筛选目录读取失败" action={<Button onClick={()=>setRefresh(v=>v+1)}>重试目录</Button>}>{factories.error||warehouses.error}</StatusMessage>}
 {notice&&<StatusMessage kind="success" title={notice}/>}{(target||kind)&&!validTarget&&<StatusMessage kind="warning" title="链路定位参数无效">清除定位后重新选择原单据。</StatusMessage>}
 {validTarget&&<div className={styles.locator} role="status"><span>已定位{kind==="order"?"生产订单":"出货批次"}的完整链路</span><Button variant="quiet" onClick={()=>change({trace_kind:"",trace_id:"",trace_stage:"",trace_summary:""})}>返回分页结果</Button></div>}
 <section ref={chainFocus} tabIndex={-1} className={styles.section} aria-label="完整业务链路"><div className={styles.sectionHeader}><h2>下单至目的仓入库 · {validTarget&&!inPage?groups.length:chains.value?.total??"待核"} 条链路</h2><div className={styles.actions} ref={switchRef} role="group" aria-label="总链路完成状态">{[{key:"active",label:"进行中"},{key:"completed",label:"已完成"},{key:"all",label:"全部"}].map(v=><Button key={v.key} variant="quiet" aria-pressed={chainProgress===v.key} onClick={()=>filter("chain_progress",v.key)}>{v.label} {chains.value?.chain_counts[v.key as "active"|"completed"|"all"]??""}</Button>)}</div></div>
 {(chains.error||targetChains.error||chains.value&&chains.value.detail_scope!=="complete_chain_groups")&&<StatusMessage kind="danger" title="完整链路读取失败" action={<Button onClick={()=>setRefresh(v=>v+1)}>重试链路</Button>}>{chains.error||targetChains.error||"未返回完整链路范围，请核对服务版本。"}</StatusMessage>}{(chains.initialLoading||targetChains.initialLoading)&&<p role="status">正在读取完整链路…</p>}
 <OverviewTransitOpening refresh={refresh} warehouse={warehouse} query={q} catalog={catalog.value?.items||[]} enabled={!factory&&chainProgress!=="completed"} retry={()=>setRefresh(v=>v+1)}/>
 <div className={styles.groupRecords}>{graphs.map(({group,graph})=>{
  if(group.orders.length>0&&group.orders.every(order=>order.status==="VOID")&&!group.shipments.length)return <StatusMessage key={group.id} kind="info" title="订单已作废" action={<LinkButton to={`/production/orders/${group.orders[0]!.id}`}>查看订单记录</LinkButton>}>已退出履约跟进，历史记录可继续查看。</StatusMessage>;
  const expanded=params.get("expand_chain")===group.id||group.orders.some(o=>o.id===params.get("branch_order"));const focusOrder=group.orders.find(o=>o.id===focused);
  const visibleOrders=focusOrder?[focusOrder]:group.orders,visibleBatches=focusOrder?orderShipments(focusOrder,group.shipments):group.shipments;
  const end=graph.nodes.find(n=>n.stage==="destination");const title=group.orders.length===1?`订单 ${group.orders[0]!.business_number||group.orders[0]!.system_number}`:group.orders.length?`${group.orders.length} 笔订单 · 同路径履约`:`独立出货 · ${group.shipments.length} 批`;
  return <div key={group.id} className={styles.group} data-chain-group={group.id}>
   <div className={styles.chainSummary}><div><strong title={group.orders.length?`${group.orders.length} 单 · ${group.shipments.length} 批出货`:"来源订单未关联"} className={group.completed?styles.completeText:undefined}>{group.completed?"总链路已完成":"总链路进行中"}</strong><span>{group.related_shipments?.length&&!group.shipments.length?"本仓出货已显示，订单实收归属待核":<>{focusOrder?"本单 · ":""}{end?.quantity.startsWith("尚无")?"":end?.quantity}{end?.percent!==undefined?` · ${end.percent}%`:""}{end?.remaining!==undefined&&end.remaining!=="0"?` · 待到齐 ${quantity(end.remaining)} 件`:""}</>}</span></div></div>
   <Chain highlighted={!!q} title={title} subtitle={routeTitle(group,warehouses.value?.items||[])} graph={graph} open={open} actions={<Button variant="quiet" aria-expanded={expanded} onClick={()=>change({expand_chain:expanded?"":group.id,branch_order:""})}>{expanded?"收起订单与批次":"展开订单与批次"}</Button>}/>
   {group.orders.length>1&&<details className={styles.orderPicker}><summary title={focusOrder?.business_number||focusOrder?.system_number}>{focusOrder?`查看订单 · ${focusOrder.business_number||focusOrder.system_number}`:"按订单查看"}</summary><div className={styles.orderFocus} role="group" aria-label={`${title}订单聚焦`}><Button variant="quiet" aria-pressed={!focusOrder} onClick={()=>change({focus_order:"",trace_stage:"",trace_summary:""})}>整组</Button>{group.orders.map(o=><Button key={o.id} variant="quiet" aria-pressed={focusOrder?.id===o.id} onClick={()=>change({focus_order:o.id,trace_stage:"",trace_summary:""})}>{o.business_number||o.system_number}</Button>)}</div></details>}
   {expanded&&<div className={styles.groupDetails}>
    {visibleOrders.length>0&&<div className={styles.records}>{visibleOrders.map(order=><Chain key={order.id} title={`订单明细 ${order.business_number||order.system_number}`} subtitle={order.production_completion_state==="COMPLETED"?"生产人工已完成":"生产待跟进"} graph={orderTrace(order,scope,catalog.value?.items||[])} open={open} actions={<OrderCompletionAction order={order} canWrite={canWrite} blocked={!chains.current||chains.loading} reload={()=>setRefresh(v=>v+1)} saved={savedOrder} onGuardChange={completionGuard}/>}/>)}</div>}
    <div className={styles.records}>{visibleBatches.map(item=><Chain key={item.id} title={`出货 ${item.business_number||item.system_number}`} subtitle={`${item.source_name||"来源待核"} → ${item.destination_name||"目的仓待核"} · 整批事实，不重复累计订单`} graph={shipmentTrace(item,scope)} open={open}/>)}</div>
    
   </div>}
  </div>;
 })}</div>
 {!chains.loading&&!targetChains.loading&&!groups.length&&!chains.error&&!targetChains.error&&<p>{validTarget?"当前站点没有此单据的链路。":"当前筛选没有链路，可切换已完成或全部查看历史。"}</p>}
 {stage&&!selected&&!chains.loading&&!targetChains.loading&&<StatusMessage kind="warning" title="当前单据没有此环节，请重新选择节点"/>}
 {!validTarget&&chains.value&&(chains.value.total>5||chains.value.page>1)&&<Pagination itemLabel="链路" page={chains.value.page} totalItems={chains.value.total} totalPages={Math.max(1,Math.ceil(chains.value.total/5))} onPageChange={v=>change({...reset,page:String(v)})}/>}
 </section>
 <aside className={styles.support} aria-label="库存与订单阶段"><section><h2>仓库当前在库</h2>{stock.error&&<StatusMessage kind="danger" title="库存读取失败">{stock.error}</StatusMessage>}{warehouses.value?.items.filter(w=>w.status==="ACTIVE"&&(!warehouse||w.id===warehouse)).map(w=>{const scopes=stock.value?.scopes.filter(s=>s.warehouse_id===w.id)||[],items=stock.value?.items.filter(i=>i.warehouse_id===w.id)||[];const known=!!scopes.length&&scopes.every(s=>items.some(i=>i.owner_id===s.owner_id))&&items.every(i=>i.on_hand_units!==null);return <p key={w.id}><Button variant="quiet" data-overview-warehouse={w.id} aria-label={`查看${w.name}库存`} onClick={e=>{warehouseFocus.current=e.currentTarget;change({stock_warehouse:w.id,stock_owner:"",stock_q:"",stock_state:""});}}>{w.name}</Button> {known?`${items.reduce((n,i)=>n+BigInt(i.on_hand_units!),0n).toLocaleString("zh-CN")} 件`:stock.loading?"读取中":scopes.length?"待核":w.type==="FBA"?"FBA未接入":"尚未建账"}</p>;})}</section><OrderStageBoard refresh={refresh} catalog={catalog.value?.items||[]} selectedOrderId={kind==="order"?target:undefined} page={pageNumber(params.get("order_stage_page"))} reload={()=>setRefresh(v=>v+1)} onPage={page=>change({order_stage_page:String(page)})} onOrder={order=>{change({...reset,trace_kind:"order",trace_id:order.id,focus_order:order.id});chainFocus.current?.focus({preventScroll:true});chainFocus.current?.scrollIntoView({block:"start"});}}/></aside>
 {stockWarehouse&&/^[1-9][0-9]*$/.test(stockWarehouse)&&!editor&&!arrival&&<OverviewWarehouseDrawer key={stockWarehouse} id={stockWarehouse} owner={params.get("stock_owner")||""} catalog={catalog.value?.items||[]} refresh={refresh} reload={()=>setRefresh(v=>v+1)} onOwner={owner=>change({stock_owner:owner,stock_q:"",stock_state:""})} close={()=>change({stock_warehouse:"",stock_owner:"",stock_q:"",stock_state:""})} returnFocus={warehouseFocus}/>}
 {selected&&selectedOrder?.status!=="VOID"&&!stockWarehouse&&!editor&&!arrival&&<ProductionTraceDrawer node={drawerNode!} order={selectedOrder} batch={drawerBatch} group={scopedGroup} warehouses={warehouses.value?.items||[]} catalog={catalog.value?.items||[]} refresh={refresh} close={close} canWrite={canWrite} linkState={linkState} returnFocus={focus} notice={notice} operationLocked={transportGuard.busy||transportGuard.unknown} receiptOrders={params.get("receipt_edit")==="1"?params.get("receipt_orders")||undefined:undefined} receiptDraft={params.get("receipt_draft")||undefined} onReceive={orders=>change({receipt_edit:"1",receipt_orders:orders.map(o=>`${o.id}:${o.revision}`).join(","),receipt_draft:""})} onReceiptDraft={id=>change({receipt_draft:id})} onReceiptSaved={()=>{setNotice("本批成品入库已确认，数量和库存已按原记录更新。");change({receipt_edit:"",receipt_orders:"",receipt_draft:""});setRefresh(v=>v+1);}} onTransportGuard={transportGuardChanged} onTransportSaved={()=>{setNotice("运输记录已保存，物流与实收入库分别显示。");setRefresh(v=>v+1);}} onProduce={(order,trigger)=>setEditor({order,trigger})} onArrival={(item,trigger)=>setArrival({item,trigger})} onOrder={(id,trigger)=>{focus.current=trigger;change({trace_kind:"order",trace_id:id,trace_stage:["order","production","receipt"].includes(stage)?stage:"order",trace_summary:"",expand_chain:selectedGroup?.id||""});}} onBranch={id=>change({trace_kind:"shipment",trace_id:id,trace_stage:["dispatch","transport","destination"].includes(stage)?stage:"dispatch",trace_summary:"",expand_chain:selectedGroup?.id||""})}/>}
 {editor&&<OrderProgressDialog order={editor.order} catalog={catalog.value?.items||[]} returnFocus={focus.current||editor.trigger} close={()=>setEditor(undefined)} saved={()=>{setEditor(undefined);setRefresh(v=>v+1);}}/>}
 {arrival&&<ArrivalVerificationWindow item={arrival.item} canWrite={canWrite} refresh={refresh} returnFocus={focus.current||arrival.trigger} close={()=>{setArrival(undefined);setRefresh(v=>v+1);}} saved={()=>{setArrival(undefined);setRefresh(v=>v+1);}}/>}
 </div>;
}

function OverviewLeaveGuard({dirty,busy,unknown}:{dirty:boolean;busy:boolean;unknown:boolean}) {return useProductionLeave(dirty,busy,unknown).prompt;}
