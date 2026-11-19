import { describe,it,expect } from "vitest";
import { orderTrace,shipmentTrace,relatedTrace,progress,chainTrace,orderStage,orderStageProgress } from "./productionTrace";
import type { Document, Sku } from "./types";
import type { TransitItem } from "./WarehouseTransit";
const order={id:"1",status:"CONFIRMED",expected_units:"100",lines:[{id:"11",expected_units:"100",produced_units:"80",received_units:"60"}]} as Document;
const batch={id:"2",warehouse_id:"3",destination_id:"4",shipped_units:"100",received_units:"60",settled_units:"0",unreceived_units:"40",stage:"IN_TRANSIT",transport:{status:"SIGNED",source_revision_current:true,latest_event:{location:"洛杉矶"}},sources:[{id:"21",actual_units:"100",received_units:"60",allocations:[]}]} as unknown as TransitItem;
describe("read-only trace facts",()=>{
 it("shows same-route freight and transport while keeping order attribution pending",()=>{
  const graph=chainTrace({id:"g",orders:[order],shipments:[],related_shipments:[batch],completed:false},"1");
  const dispatch=graph.nodes.find(node=>node.stage==="dispatch")!;
  expect(dispatch.title).toBe("本仓出货 · 待关联订单");expect(dispatch.status).toBe("订单归属待核");
  expect(dispatch.kind).toBe("shipment");expect(dispatch.rootId).toBe(batch.id);
  expect(graph.nodes.find(node=>node.stage==="transport")?.status).toBe("物流签收");
  expect(graph.nodes.find(node=>node.stage==="destination")?.quantity).toBe("实收 60 件");
  expect(order.fulfillment_lines).toBeUndefined();
 });
 it("shows one quantity and resolves distinct style codes from stable SKU identities",()=>{
  const catalog=[{sku_id:"1",style_code:"1112"},{sku_id:"2",style_code:"1112"},{sku_id:"3",style_code:"2121"}] as Sku[];
  const styled={...order,lines:["1","2","3"].map((sku_id,i)=>({...order.lines![0]!,id:String(i+1),sku_id}))};
  const graph=chainTrace({id:"g1",orders:[styled],shipments:[],completed:false},"1",undefined,catalog);
  expect(graph.nodes[0]?.styleCodes).toEqual(["1112","2121"]);expect(orderTrace(styled,"1",catalog).nodes[0]?.styleCodes).toEqual(["1112","2121"]);
  expect(graph.nodes.every(n=>!/[0-9]\s*[/／]\s*[0-9]/.test(n.quantity))).toBe(true);expect(orderTrace(styled,"1").nodes[0]?.styleCodes).toEqual([]);
 });

 it("keeps simultaneous partial production and receipt",()=>{const g=orderTrace(order,"site1");expect(g.nodes.map(n=>n.tone)).toEqual(["done","partial","partial"]);expect(g.nodes[1]?.quantity).toBe("80 件");expect(g.nodes[2]?.quantity).toBe("60 件");expect(g.nodes[1]?.percent).toBe(80);expect(g.nodes[2]?.percent).toBe(60);});
 it("omits the warehouse receipt node for evidenced all-direct fulfillment",()=>{expect(orderTrace({...order,lines:order.lines!.map(l=>({...l,production_direct_units:"100"}))},"1").nodes.map(n=>n.stage)).toEqual(["order","production"]);});
 it("never offsets another SKU shortage with an overage",()=>{const result=progress([{actual:"120",expected:"50"},{actual:"0",expected:"50"}]);expect(result.tone).toBe("partial");expect(result.percent).toBe(50);expect(result.remaining).toBe("50");});
 it("distinguishes unknown and zero and draft from facts",()=>{expect(progress([{actual:null,expected:"100"}]).amount).toBeNull();expect(progress([{actual:null,expected:"100"}]).percent).toBeUndefined();expect(progress([{actual:"0",expected:"100"}]).percent).toBe(0);expect(progress([{actual:"0",expected:"100"}]).tone).toBe("idle");expect(orderTrace({...order,status:"DRAFT"},"1").nodes.every(n=>n.tone==="unknown")).toBe(true);});
 it("does not turn signed into received or mark remaining as in transit",()=>{const g=shipmentTrace(batch,"1");expect(g.nodes[1]?.status).toBe("物流签收");expect(g.nodes[2]?.tone).toBe("partial");expect(g.nodes[2]?.quantity).toBe("实收 60 件");});
 it("keeps exception and completed quantities together",()=>{const g=shipmentTrace({...batch,transport:{...batch.transport,status:"EXCEPTION"},received_units:"100",sources:batch.sources.map(s=>({...s,received_units:"100"}))},"1");expect(g.nodes[1]?.warning).toBe("运输异常");expect(g.nodes[2]?.tone).toBe("done");});
 it("does not fabricate receipt when shortage is settled or unknown",()=>{expect(shipmentTrace({...batch,stage:"SETTLED",settled_units:"40"},"1").nodes[2]?.status).toContain("差异已结案 40");expect(shipmentTrace({...batch,received_units:null,sources:batch.sources.map(s=>({...s,received_units:null}))},"1").nodes[2]?.tone).toBe("unknown");});
 it("never joins same warehouse or SKU without explicit allocations",()=>{expect(relatedTrace(order,[batch],"1").nodes).toHaveLength(3);expect(orderTrace(order,"1").nodes[0]?.id).not.toBe(orderTrace(order,"2").nodes[0]?.id);});
 it("deduplicates batches and keeps allocation counts on direct edges",()=>{const linked={...batch,sources:batch.sources.map(s=>({...s,fulfillment_mode:"PRODUCTION_DIRECT",allocations:[{id:"31",order_id:"1",order_line_id:"11",order_number:"PO1",units:"30"},{id:"32",order_id:"9",order_line_id:"99",order_number:"PO9",units:"70"}]}))};const g=relatedTrace(order,[linked,linked],"1");expect(g.nodes).toHaveLength(6);expect(g.edges.find(e=>e.quantity)?.quantity).toBe("本单分配 30 件 · 生产直发");expect(g.edges.find(e=>e.quantity)?.source).toContain(":production");});
});

describe("complete route summaries",()=>{
 const fulfilled=(id:string,received:string|null,expected="100"):Document=>({...order,id,lines:order.lines!.map(l=>({...l,id:`${id}1`,expected_units:expected,produced_units:expected,received_units:expected})),fulfillment_lines:[{id:`${id}1`,sku_id:"5",expected_units:expected,shipped_units:expected,received_units:received}]});
 it("shows every stage without expansion and does not reuse a shared batch total for each order",()=>{
  const g=chainTrace({id:"order-1",orders:[fulfilled("1","100"),fulfilled("2","100"),fulfilled("3","40")],shipments:[{...batch,shipped_units:"300",received_units:"240"}],completed:false},"1");
  expect(g.nodes.map(n=>n.stage)).toEqual(["order","production","receipt","dispatch","transport","destination"]);
  expect(g.nodes.at(-1)?.quantity).toBe("明确实收 240 件");expect(g.nodes.at(-1)?.percent).toBe(80);
 });
 it("keeps identical SKU lines separate and keeps unknown allocations unknown",()=>{
  let g=chainTrace({id:"1",orders:[fulfilled("1","200"),fulfilled("2","0")],shipments:[batch],completed:false},"1");
  expect(g.nodes.at(-1)?.percent).toBe(50);
  g=chainTrace({id:"1",orders:[fulfilled("1",null)],shipments:[batch],completed:false},"1");expect(g.nodes.at(-1)?.percent).toBeUndefined();expect(g.nodes.at(-1)?.tone).toBe("unknown");
  g=chainTrace({id:"1",orders:[fulfilled("1","100"),fulfilled("2",null)],shipments:[batch],completed:false},"1");expect(g.nodes.at(-1)?.quantity).toBe("明确实收 已登记 100 件");expect(g.nodes.at(-1)?.status).toBe("1 项待核");
 });
 it("omits all-direct receipt and preserves settled difference without inventing receipts",()=>{
  const o=fulfilled("1","60");o.lines=o.lines!.map(l=>({...l,production_direct_units:"100",received_units:"0"}));
  const g=chainTrace({id:"1",orders:[o],shipments:[{...batch,settled_units:"40",stage:"SETTLED"}],completed:false},"1");
  expect(g.nodes.some(n=>n.stage==="receipt")).toBe(false);expect(g.nodes.at(-1)?.percent).toBe(60);expect(g.nodes.at(-1)?.warning).toContain("不计实收");
 });
 it("does not invent an order for independent stock freight and shows planned downstream when unlinked",()=>{
  const g=chainTrace({id:"s1",orders:[],shipments:[batch],completed:false},"1");expect(g.nodes.map(n=>n.stage)).toEqual(["dispatch","transport","destination"]);
  const planned=chainTrace({id:"o1",orders:[fulfilled("1","0")],shipments:[],completed:false},"1");expect(planned.nodes).toHaveLength(6);expect(planned.nodes.find(n=>n.stage==="transport")).toMatchObject({status:"订单归属待核",tone:"unknown"});expect(planned.nodes.at(-1)?.status).toBe("订单归属待核");expect(planned.nodes.at(-1)?.percent).toBeUndefined();expect(planned.nodes.at(-1)?.remaining).toBeUndefined();
  const destination=chainTrace({id:"o1",orders:[{...fulfilled("1","0"),destination:"美国FBA"}],shipments:[],completed:false},"1");expect(destination.nodes.at(-1)?.title).toBe("计划 美国FBA");expect(destination.nodes.at(-1)?.percent).toBeUndefined();
 });
});

it("derives order stages from line facts without inferring dispatch or transport from missing attribution",()=>{
 const make=(produced:string|null,received:string|undefined)=>({...order,lines:[{...order.lines![0]!,sku_id:"1",produced_units:produced,received_units:received}]});
 expect(orderStage(make("0","0"))).toBe("待生产");expect(orderStage(make("40","0"))).toBe("生产中");expect(orderStage(make("100","0"))).toBe("待成品入库");expect(orderStage(make("100","40"))).toBe("部分入库");expect(orderStage(make("100","100"))).toBe("已入库 · 发运待核");expect(orderStage(make(null,"0"))).toBe("生产待核");expect(orderStage(make("100",undefined))).toBe("入库待核");
 const received=make("100","100");const allocated={...received,fulfillment_lines:[{id:"11",sku_id:"1",expected_units:"100",shipped_units:"100",received_units:null}]};expect(orderStage(allocated)).toBe("已发货 · 待实收");expect(orderStage({...allocated,fulfillment_lines:[{...allocated.fulfillment_lines[0]!,received_units:"100"}]})).toBe("目的仓已收齐");expect(orderStage({...allocated,fulfillment_lines:[{...allocated.fulfillment_lines[0]!,shipped_units:"40"}]})).toBe("部分发货");
 expect(orderStage({...received,lines:[{...received.lines[0]!,produced_units:"200",received_units:"200"},{...received.lines[0]!,id:"12",produced_units:"0",received_units:"0"}]})).toBe("部分入库");
 const direct={...make("100","0"),lines:[{...make("100","0").lines[0]!,production_direct_units:"100"}]};expect(orderStage(direct)).toBe("生产完成 · 发运待核");
 expect(orderStageProgress(make("40","0"))).toEqual({label:"生产中",percent:40});
 expect(orderStageProgress(make("100","40"))).toEqual({label:"部分入库",percent:40});
 expect(orderStageProgress(make(null,"0")).percent).toBeUndefined();
 expect(orderStageProgress(allocated).percent).toBeUndefined();
 expect(orderStageProgress({...received,lines:[{...received.lines[0]!,production_direct_units:"60",received_units:"20"}]})).toEqual({label:"部分入库",percent:50});
 expect(orderStageProgress({...received,lines:[{...received.lines[0]!,received_units:"200"},{...received.lines[0]!,id:"12",received_units:"0"}]}).percent).toBe(50);
});
