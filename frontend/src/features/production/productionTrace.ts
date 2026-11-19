import type { Document, Sku } from "./types";
import type { TransitItem } from "./WarehouseTransit";
import { transportStatus } from "./transport";

export type TraceStage = "order" | "production" | "receipt" | "dispatch" | "transport" | "destination";
export type TraceNode = { id: string; stage: TraceStage; kind: "order" | "shipment"; rootId: string; title: string; quantity: string; status: string; tone: "done" | "partial" | "unknown" | "idle"; warning?: string; location?: string; percent?: number; summary?:boolean; remaining?:string; styleCodes?:string[] };
export type TraceEdge = { id: string; source: string; target: string; planned: boolean; evidence: string; quantity?: string };
export type TraceGraph = { nodes: TraceNode[]; edges: TraceEdge[] };
export type ChainGroup = {id:string;orders:Document[];shipments:TransitItem[];related_shipments?:TransitItem[];completed:boolean};
export type ChainPage = {items:ChainGroup[];total:number;page:number;page_size:number;chain_counts:{active:number;completed:number;all:number};detail_scope:string};
export const known = (v: unknown): v is string => typeof v === "string" && /^[0-9]+$/.test(v);
export const quantity = (v: string | null | undefined) => known(v) ? BigInt(v).toLocaleString("zh-CN") : "待核";
export function progress(values: {actual?: string | null; expected?: string}[]) {
  if (!values.length || values.some(v => !known(v.actual) || !known(v.expected))) return {amount: null, remaining: undefined, percent: undefined, tone: "unknown" as const, status: "尚未登记 / 待核"};
  const amount=values.reduce((n,v)=>n+BigInt(v.actual!),0n).toString();
  const total=values.reduce((n,v)=>n+BigInt(v.expected!),0n);
  const covered=values.reduce((n,v)=>n+(BigInt(v.actual!)<BigInt(v.expected!)?BigInt(v.actual!):BigInt(v.expected!)),0n);
  const percent=total>0n?Number(covered*1000n/total)/10:undefined;
  const done=values.every(v=>BigInt(v.actual!)>=BigInt(v.expected!));
  const remaining=values.reduce((n,v)=>n+(BigInt(v.expected!)>BigInt(v.actual!)?BigInt(v.expected!)-BigInt(v.actual!):0n),0n).toString();
  return {amount, remaining, percent, tone: done ? "done" as const : BigInt(amount)>0n ? "partial" as const : "idle" as const, status:done ? "数量已达标" : BigInt(amount)>0n ? "部分完成" : "未开始"};
}
function orderStyleCodes(orders:Document[],catalog:Sku[]) {
 return [...new Set(orders.flatMap(o=>o.lines||[]).map(line=>catalog.find(s=>s.sku_id===line.sku_id)?.style_code?.trim()).filter((code):code is string=>!!code))];
}
/** A stage describes proven order quantities, never the location of unallocated stock. */
export function orderStage(order:Document):string {
 return orderStageProgress(order).label;
}
export function orderStageProgress(order:Document):{label:string;percent?:number} {
 const stage=(label:string,values:{actual?:string|null;expected?:string}[]=[])=>({label,percent:progress(values).percent});
 if(order.status!=="CONFIRMED")return stage(order.status==="VOID"?"已作废":"待确认");
 const lines=order.lines||[],facts=order.fulfillment_lines||[];
 if(!lines.length)return stage("数量待核");
 const complete=(values:{actual?:string|null;expected?:string}[])=>values.length>0&&values.every(v=>known(v.actual)&&known(v.expected)&&BigInt(v.actual)>=BigInt(v.expected));
 const any=(values:(string|null|undefined)[])=>values.some(v=>known(v)&&BigInt(v)>0n);
 const attributed=facts.length===lines.length&&lines.every(l=>facts.some(f=>f.id===l.id&&f.sku_id===l.sku_id));
 const destination=facts.map(f=>({actual:f.received_units,expected:f.expected_units}));
 const dispatch=facts.map(f=>({actual:f.shipped_units,expected:f.expected_units}));
 if(attributed&&complete(destination))return stage("目的仓已收齐",destination);
 if(attributed&&complete(dispatch))return stage("已发货 · 待实收",destination);
 if(any(facts.map(f=>f.shipped_units)))return stage("部分发货",attributed?dispatch:[]);
 const warehouseLines=lines.filter(l=>!known(l.production_direct_units)||BigInt(l.production_direct_units)<BigInt(l.expected_units));
 const receipt=warehouseLines.map(l=>({actual:l.received_units,expected:(BigInt(l.expected_units)-BigInt(l.production_direct_units||"0")).toString()}));
 if(complete(receipt))return stage("已入库 · 发运待核",attributed?dispatch:[]);
 if(warehouseLines.some(l=>!known(l.received_units)))return stage("入库待核");
 if(any(lines.map(l=>l.received_units)))return stage("部分入库",receipt);
 const production=lines.map(l=>({actual:l.produced_units,expected:l.expected_units}));
 if(complete(production))return warehouseLines.length?stage("待成品入库",receipt):stage("生产完成 · 发运待核",attributed?dispatch:[]);
 if(lines.some(l=>!known(l.produced_units)))return stage("生产待核");
 return stage(any(lines.map(l=>l.produced_units))?"生产中":"待生产",production);
}
export function orderTrace(order: Document, scope: string, catalog:Sku[]=[]): TraceGraph {
  const key=`${scope}:order:${order.id}`;
  const planned=order.status!=="CONFIRMED";
  const production=progress((order.lines||[]).map(l=>({actual:l.produced_units,expected:l.expected_units})));
  const receipt=progress((order.lines||[]).map(l=>({actual:l.received_units,expected:l.expected_units})));
  const node=(stage:TraceStage,title:string,quantity:string,status:string,tone:TraceNode["tone"]):TraceNode=>({id:`${key}:${stage}`,rootId:order.id,kind:"order",stage,title,quantity,status,tone});
  const nodes=[node("order","下单",`${planned ? "计划" : "整单"} ${quantity(order.expected_units)} 件`,planned ? order.status==="VOID" ? "已作废 / 仅历史" : "草稿 / 尚未确认" : "已确认",planned?"unknown":"done"),node("production","工厂生产",`${quantity(production.amount)} 件`,planned?"尚未确认":production.status,planned?"unknown":production.tone),node("receipt","生产入库",`${quantity(receipt.amount)} 件`,planned?"尚未确认":receipt.status,planned?"unknown":receipt.tone)];
  nodes[0]!.styleCodes=orderStyleCodes([order],catalog);
  if(!planned){nodes[1]!.percent=production.percent;nodes[2]!.percent=receipt.percent;}
  const directOnly=!!order.lines?.length&&order.lines.every(l=>known(l.production_direct_units)&&BigInt(l.production_direct_units)>=BigInt(l.expected_units));
  if(directOnly)nodes.splice(2,1);
  return {nodes,edges:nodes.slice(1).map((n,i)=>({id:`${key}:edge:${i}`,source:nodes[i]!.id,target:n.id,planned:planned||n.tone==="unknown"||n.tone==="idle",evidence:`订单 ${order.id} / 订单明细及生产入库分配`}))};
}
export function shipmentTrace(item: TransitItem, scope: string): TraceGraph {
  const key=`${scope}:shipment:${item.id}`;
  const got=progress(item.sources.map(s=>({actual:s.received_units,expected:s.actual_units})));
  const warning=item.transport.status==="EXCEPTION" ? "运输异常" : item.transport.source_revision_current===false ? "出货已更正，运输待核" : item.eta_overdue ? "已超过预计到达" : undefined;
  const transportTone=got.tone==="done"||item.transport.status==="ARRIVED"||item.transport.status==="SIGNED"?"done":item.departed||item.transport.status==="IN_TRANSIT"?"partial":"unknown";
  const nodes:TraceNode[]=[{id:`${key}:dispatch`,kind:"shipment",rootId:item.id,stage:"dispatch",title:item.source_name||"来源仓出货",quantity:`整批已发 ${quantity(item.shipped_units)} 件`,status:"已确认出货",tone:"done"},{id:`${key}:transport`,kind:"shipment",rootId:item.id,stage:"transport",title:"运输跟踪",quantity:`本批 ${quantity(item.shipped_units)} 件`,status:got.tone==="done"?"目的仓已收齐":transportStatus[item.transport.status]||"运输待核",tone:transportTone,warning,location:`最近记录：${item.transport.latest_event?.location||"地点未登记"}`},{id:`${key}:destination`,kind:"shipment",rootId:item.id,stage:"destination",percent:known(item.received_units)?got.percent:undefined,title:item.destination_name||"目的仓实收",quantity:`实收 ${quantity(item.received_units)} 件`,status:item.stage==="SETTLED"?`差异已结案 ${quantity(item.settled_units)} 件`:got.status,tone:got.tone}];
  return {nodes,edges:[{id:`${key}:dispatch-transport`,source:nodes[0]!.id,target:nodes[1]!.id,planned:transportTone==="unknown",evidence:`出货 ${item.id} / 运输记录`},{id:`${key}:transport-destination`,source:nodes[1]!.id,target:nodes[2]!.id,planned:!known(item.received_units)||BigInt(item.received_units)===0n,evidence:`出货 ${item.id} / 目的仓来源binding`} ]};
}

/** Only explicit, active allocations returned by the original shipment read join the roots. */
export function relatedTrace(order:Document, shipments:TransitItem[], scope:string):TraceGraph {
 const graph=orderTrace(order,scope);const lines=new Set(order.lines?.map(l=>l.id));
 const unique=[...new Map(shipments.map(s=>[s.id,s])).values()];
 const direct=unique.some(s=>s.sources.some(x=>x.fulfillment_mode==="PRODUCTION_DIRECT"&&x.allocations.some(a=>a.order_id===order.id&&lines.has(a.order_line_id||""))));
 if(direct&&graph.nodes.some(n=>n.stage==="receipt")){const receipt=graph.nodes.find(n=>n.stage==="receipt")!;receipt.status="直发部分不适用入库；仓储部分仍按原凭据";receipt.tone="unknown";receipt.percent=undefined;}
 for(const batch of unique){
  const allocations=batch.sources.flatMap(source=>source.allocations.filter(a=>a.order_id===order.id&&lines.has(a.order_line_id||"")).map(a=>({...a,mode:source.fulfillment_mode,sourceId:source.id})));
  if(!allocations.length)continue;
  const segment=shipmentTrace(batch,scope);graph.nodes.push(...segment.nodes);graph.edges.push(...segment.edges);
  for(const mode of [...new Set(allocations.map(a=>a.mode))]){
   const own=allocations.filter(a=>a.mode===mode);const units=own.reduce((n,a)=>n+BigInt(a.units),0n).toString();
   graph.edges.push({id:`${scope}:order:${order.id}:shipment:${batch.id}:${mode||"legacy"}`,source:`${scope}:order:${order.id}:${mode==="PRODUCTION_DIRECT"?"production":"receipt"}`,target:`${scope}:shipment:${batch.id}:dispatch`,planned:false,evidence:own.map(a=>`来源行 ${a.sourceId} / 原分配 ${a.id||"待核"}`).join("；"),quantity:`本单分配 ${quantity(units)} 件${mode==="PRODUCTION_DIRECT"?" · 生产直发":""}`});
  }
 }
 return graph;
}

export function orderShipments(order:Document,shipments:TransitItem[]) {
 const lines=new Set(order.lines?.map(l=>l.id));
 return shipments.filter(s=>s.sources.some(x=>x.allocations.some(a=>a.order_id===order.id&&lines.has(a.order_line_id||""))));
}

export function focusedChainGroup(group:ChainGroup,focusOrder?:string):ChainGroup {
 const order=group.orders.find(item=>item.id===focusOrder);
 return order?{...group,orders:[order],shipments:orderShipments(order,group.shipments),related_shipments:undefined}:group;
}

/** Summaries retain each order line as a separate denominator, even for identical SKUs. */
export function chainTrace(group:ChainGroup,scope:string,focusOrder?:string,catalog:Sku[]=[]):TraceGraph {
 const scoped=focusedChainGroup(group,focusOrder),orders=scoped.orders;
 const batches=[...new Map(scoped.shipments.map(s=>[s.id,s])).values()];
 const first=orders[0];const batch=batches[0];if(!first&&!batch)return {nodes:[],edges:[]};
 const key=`${scope}:chain:${group.id}${focusOrder?`:focus:${focusOrder}`:""}`;
 const base={kind:first?"order" as const:"shipment" as const,rootId:first?.id||batch!.id,summary:true};
 const lines=orders.flatMap(o=>o.lines||[]),fulfillment=orders.flatMap(o=>(o.fulfillment_lines||[]).map(l=>known(l.shipped_units)&&BigInt(l.shipped_units)>0n?l:{...l,shipped_units:null,received_units:null}));
 const planned=orders.some(o=>o.status!=="CONFIRMED");
 const total=lines.length?lines.reduce((n,l)=>n+BigInt(l.expected_units),0n).toString():undefined;
 const make=(stage:TraceStage,title:string,values:{actual?:string|null;expected?:string}[],prefix=""):TraceNode=>{
  const p=progress(values);const partialKnown=values.filter(v=>known(v.actual));const unknown=values.length-partialKnown.length;
  const node:TraceNode={...base,id:`${key}:${stage}`,stage,title,quantity:`${prefix}${quantity(p.amount)} 件`,status:planned?"草稿／作废不计实际":p.status,tone:planned?"unknown":p.tone,remaining:planned?undefined:p.remaining,percent:planned?undefined:p.percent};
  if(!planned&&unknown&&partialKnown.length){node.quantity=`${prefix}已登记 ${quantity(partialKnown.reduce((n,v)=>n+BigInt(v.actual!),0n).toString())} 件`;node.status=`${unknown} 项待核`;}
  return node;
 };
 let nodes:TraceNode[]=[];
 if(first){
  nodes=[{...base,id:`${key}:order`,stage:"order",styleCodes:orderStyleCodes(orders,catalog),title:`下单 · ${orders.length} 单`,quantity:`${planned?"计划":"下单"} ${quantity(total)} 件`,status:planned?"含草稿／作废，请查看明细":"已确认",tone:planned?"unknown":"done"},make("production","工厂生产",lines.map(l=>({actual:l.produced_units,expected:l.expected_units})))];
  const warehouseLines=lines.filter(l=>!known(l.production_direct_units)||BigInt(l.production_direct_units)<BigInt(l.expected_units));
  if(warehouseLines.length)nodes.push(make("receipt","成品入库",warehouseLines.map(l=>({actual:l.received_units,expected:(BigInt(l.expected_units)-BigInt(l.production_direct_units||"0")).toString()}))));
  nodes.push(make("dispatch","出货记录",fulfillment.map(l=>({actual:l.shipped_units,expected:l.expected_units})),"明确已发 "));
 }else nodes=[make("dispatch",batch!.source_name||"来源仓出货",batches.flatMap(s=>s.sources.map(x=>({actual:x.actual_units,expected:x.actual_units}))),"整批 ")];
 const segments=batches.map(b=>shipmentTrace(b,scope));const transportNodes=segments.map(s=>s.nodes.find(n=>n.stage==="transport")!);
 const arrived=transportNodes.filter(n=>n.tone==="done").length;
 const warning=transportNodes.find(n=>n.warning)?.warning;
 nodes.push({...base,id:`${key}:transport`,stage:"transport",title:"运输",quantity:batches.length?`${batches.length} 批`:"尚无关联出货",status:!batches.length?"订单归属待核":batches.length===1?transportNodes[0]!.status:arrived===batches.length?(batches.every(b=>b.sources.length&&b.sources.every(s=>known(s.received_units)&&BigInt(s.received_units)>=BigInt(s.actual_units)))?"目的仓已收齐":"已到达／待核实收"):"分批跟进中",tone:!batches.length?"unknown":arrived===batches.length?"done":"partial",warning,location:batches.length===1?transportNodes[0]!.location:undefined});
 const destinationNames=batches.length?[...new Set(batches.map(b=>b.destination_name).filter(Boolean))]:[...new Set(orders.map(o=>o.destination).filter(Boolean))].map(name=>`计划 ${name}`);
 nodes.push(make("destination",destinationNames.length===1?destinationNames[0]!:`目的仓实收${destinationNames.length>1?` · ${destinationNames.length} 仓`:""}`,first?fulfillment.map(l=>({actual:l.received_units,expected:l.expected_units})):batches.flatMap(b=>b.sources.map(s=>({actual:s.received_units,expected:s.actual_units}))),first?"明确实收 ":"实收 "));
 if(first&&!batches.length){for(const n of nodes.filter(n=>["dispatch","destination"].includes(n.stage))){n.quantity=n.stage==="dispatch"?"尚无关联出货记录":"尚无关联实收记录";n.status="订单归属待核";n.tone="unknown";n.percent=undefined;n.remaining=undefined;}}
 if(first&&!batches.length&&group.related_shipments?.length){
  const related=chainTrace({id:`${group.id}:related`,orders:[],shipments:group.related_shipments,completed:false},scope);
  const dispatch=related.nodes[0]!;
  dispatch.title="本仓出货 · 待关联订单";dispatch.status="订单归属待核";dispatch.tone="unknown";
  dispatch.percent=undefined;dispatch.remaining=undefined;
  const destination=related.nodes.find(n=>n.stage==="destination");
  if(destination)destination.title=`${destination.title} · 本批实收`;
  nodes=nodes.filter(n=>!["dispatch","transport","destination"].includes(n.stage)).concat(related.nodes);
 }
 const settled=batches.some(b=>known(b.settled_units)&&BigInt(b.settled_units)>0n);if(settled)nodes.at(-1)!.warning="含差异结案，结案量不计实收";
 if(!first&&batches.length===1)for(const node of nodes){node.summary=false;node.id=`${scope}:shipment:${batch!.id}:${node.stage}`;}
 if(orders.length===1)for(const node of nodes.filter(n=>["order","production","receipt"].includes(n.stage))){node.summary=false;node.id=`${scope}:order:${first!.id}:${node.stage}`;}
 return {nodes,edges:nodes.slice(1).map((n,i)=>({id:`${key}:edge:${i}`,source:nodes[i]!.id,target:n.id,planned:planned||n.tone==="unknown"||n.tone==="idle",evidence:first?"订单明细与明确分配；同路径只汇总展示，不补造货物归属":"独立出货及目的仓接收依据"}))};
}
