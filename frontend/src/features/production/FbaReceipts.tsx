import { ShipmentDateNotice } from "./ShipmentDateNotice";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, FormField, Input, LinkButton, StatusMessage } from "../../design-system";
import { FbaFileUpload } from "./FbaFileUpload";
import { FbaUnifiedReceipt } from "./FbaUnifiedReceipt";
import { ReceiptQuantityPreview } from "./ReceiptQuantityPreview";
import { useCommand, useLoad } from "./useProductionApi";
import { useProductionLeave } from "./useProductionLeave";
import { ReadState } from "./WorkbenchFields";
import type { Document, DocumentPage, Sku } from "./types";
import { tracked, fbaBatchStates, type FbaState, type FbaScope, type FbaBatch, type FbaDecision } from "./fbaTypes";
import type { OverviewGuard } from "./stockOverview";
import styles from "./FbaWorkspace.module.css";

const api="/api/production/fba";
type BindingInput={carton_id:string;source_line_id:string;allocation_id:string|null;sku_id:string;units:string};
export function FbaReceipts({data,scope,catalog,canWrite,refresh,reload,onReceived,shipmentId,embedded=false,onGuardChange}:{data:FbaState;scope:FbaScope;catalog:Sku[];canWrite:boolean;refresh:number;reload:()=>void;onReceived?:()=>void;shipmentId?:string;embedded?:boolean;onGuardChange?:(guard:OverviewGuard)=>void}) {
  const [params,setParams]=useSearchParams();const [localBatch,setLocalBatch]=useState("");const selected=embedded?localBatch:params.get("fba_batch")||"";
  const reportUpload = useRef<HTMLElement>(null);
  const reportLibrary = useRef<HTMLElement>(null);
  const [toolsOpen,setToolsOpen]=useState(false);
  const focusUpload=useRef(false);
  const sourcesPanel=useRef<HTMLElement>(null);
  useEffect(()=>{if(toolsOpen){if(focusUpload.current){focusUpload.current=false;reportUpload.current?.scrollIntoView?.({block:"center"});reportUpload.current?.querySelector<HTMLInputElement>("input[type=file]")?.focus();}else{sourcesPanel.current?.scrollIntoView?.({block:"start"});sourcesPanel.current?.focus();}}},[toolsOpen]);
  const reportHeading = useRef<HTMLHeadingElement>(null);
  const [guards,setGuards]=useState<Record<string,OverviewGuard>>({});
  const linkGuard=useCallback((value:OverviewGuard)=>setGuards(p=>({...p,link:value})),[]);
  const uploadGuard=useCallback((value:OverviewGuard)=>setGuards(p=>({...p,upload:value})),[]);
  const reviewGuard=useCallback((value:OverviewGuard)=>setGuards(p=>({...p,review:value})),[]);
  const reimportGuard=useCallback((value:OverviewGuard)=>setGuards(p=>({...p,reimport:value})),[]);
  const unifiedGuard=useCallback((value:OverviewGuard)=>setGuards(p=>({...p,unified:value})),[]);
  const [chosenShipment,setChosenShipment]=useState(shipmentId||"");
  const [localDraft,setLocalDraft]=useState("");
  const [draftSelection,setDraftSelection]=useState(0);
  const selectedDraft=embedded?localDraft:params.get("fba_draft")||"";
  const shipments=useLoad<{items:{id:string;business_number:string;system_number:string}[]}>(`/api/production/inventory/destination-shipments?warehouse_id=${scope.warehouse_id}&owner_id=${scope.owner_id}`,refresh,!shipmentId);
  const dirty=Object.values(guards).some(g=>g.dirty),busy=Object.values(guards).some(g=>g.busy),unknown=Object.values(guards).some(g=>g.unknown);
  useEffect(()=>{onGuardChange?.({dirty,busy,unknown});},[dirty,busy,unknown,onGuardChange]);
  const blockedBy=(own:string[])=>Object.entries(guards).some(([key,g])=>!own.includes(key)&&(g.busy||g.unknown||key==="unified"&&g.dirty));
  const uploadBlocked=Object.entries(guards).some(([key,g])=>key!=="upload"&&(g.dirty||g.busy||g.unknown));
  function selectBatch(id:string){if(id===selected)return;if(id)setToolsOpen(false);if(embedded)setLocalBatch(id);else{const next=new URLSearchParams(params);if(id)next.set("fba_batch",id);else next.delete("fba_batch");setParams(next);}}
  function selectDraft(value:Pick<FbaBatch,"id">){if(embedded)setLocalDraft(value.id);else{const next=new URLSearchParams(params);next.set("fba_draft",value.id);setParams(next);}reload();}
  const drafts=data.batches.filter(value=>value.scope_id===scope.id&&value.shipment_id===chosenShipment&&value.source_kind==="MANUAL"&&value.status==="DRAFT");

  const batch=useLoad<FbaBatch>(`${api}/batches/${selected}`,refresh,!!selected);const [result,setResult]=useState<FbaBatch>();
  const active=result?.id===selected&&(!batch.value||Number(result.revision)>Number(batch.value.revision))?result:batch.value;
  const reviewingReport=!!selected&&active?.source_kind!=="MANUAL";
  useEffect(()=>{if(reviewingReport&&active?.id){reportHeading.current?.scrollIntoView?.({block:"start"});reportHeading.current?.focus({preventScroll:true});}},[reviewingReport,active?.id]);
  useEffect(()=>{if(active?.source_kind==="MANUAL"&&active.shipment_id)setChosenShipment(active.shipment_id);},[active?.source_kind,active?.shipment_id]);
  useEffect(()=>{const draft=data.batches.find(value=>value.id===selectedDraft&&value.scope_id===scope.id&&value.source_kind==="MANUAL");if(draft?.shipment_id)setChosenShipment(draft.shipment_id);},[selectedDraft,data.batches,scope.id]);
  function saved(value:FbaBatch){setResult(value);selectBatch(value.id);reload();}
  function replaceFile(){
    if(toolsOpen){reportUpload.current?.scrollIntoView?.({block:"center"});reportUpload.current?.querySelector<HTMLInputElement>("input[type=file]")?.focus();}
    else{focusUpload.current=true;setToolsOpen(true);}
  }
  return <div className={`${styles.workspace} ${styles.receipts}`} data-embedded={embedded||undefined}>
    {!embedded&&<StandaloneReceiptLeave dirty={dirty} busy={busy} unknown={unknown}/>}
    {reviewingReport&&<div className={styles.receiptToolbar}><h2 ref={reportHeading} tabIndex={-1}>FBA接收核对</h2><Button variant="quiet" disabled={dirty||busy||unknown} onClick={()=>{setResult(undefined);selectBatch("");}}>{shipmentId?"返回接收表":"接收其他出货"}</Button></div>}
    {!reviewingReport&&!shipmentId&&<FormField label="接收出货批次" error={shipments.error}><select value={chosenShipment} disabled={dirty||busy||unknown} onChange={event=>{setChosenShipment(event.target.value);setLocalDraft("");const next=new URLSearchParams(params);next.delete("fba_draft");next.delete("fba_batch");setParams(next);}}><option value="">选择本批出货，填写数量或导入接收表</option>{shipments.value?.items.map(item=><option key={item.id} value={item.id}>{item.business_number||item.system_number}</option>)}</select></FormField>}
    {!reviewingReport&&drafts.length>1&&<FormField label="继续已保存的接收草稿"><select value={selectedDraft||drafts[0]?.id} disabled={dirty||busy||unknown} onChange={event=>{const draft=drafts.find(value=>value.id===event.target.value);if(draft){selectDraft(draft);setDraftSelection(value=>value+1);}}}>{drafts.map(draft=><option key={draft.id} value={draft.id}>接收草稿 {draft.id}</option>)}</select></FormField>}
    {!reviewingReport&&chosenShipment&&<fieldset hidden={toolsOpen} style={{border:0,padding:0,margin:0,minWidth:0}} disabled={Object.entries(guards).some(([key,guard])=>key!=="unified"&&(guard.dirty||guard.busy||guard.unknown))}><FbaUnifiedReceipt key={`${scope.id}:${chosenShipment}:${draftSelection}`} data={data} scope={scope} catalog={catalog} shipmentId={chosenShipment} refresh={refresh} canWrite={canWrite} saved={()=>{reload();onReceived?.();}} draftId={selectedDraft} onSources={()=>setToolsOpen(true)} onDraft={selectDraft} onGuardChange={unifiedGuard} onReport={value=>{setResult(value);reload();}}/></fieldset>}
    {reviewingReport&&(active?<fieldset style={{border:0,padding:0,margin:0,minWidth:0}} disabled={blockedBy(["review","reimport"])}><FbaBatchReview onReplaceFile={replaceFile} events={data.events || []} catalog={catalog} onGuardChange={reviewGuard} onUploadGuardChange={reimportGuard} key={`${active.id}:${active.revision}`} batch={active} canWrite={canWrite} saved={value=>{saved(value);if(value.resolved.length>active.resolved.length)onReceived?.();}}/></fieldset>:<ReadState error={batch.error}/>)}
    {!chosenShipment&&!!selected&&<Button variant="quiet" disabled={busy||unknown} onClick={()=>setToolsOpen(previous=>!previous)}>来源与原件</Button>}
    <section ref={sourcesPanel} hidden={!toolsOpen} tabIndex={-1} aria-label="货件关联资料"><Button variant="quiet" disabled={busy||unknown} onClick={()=>setToolsOpen(false)}>返回验收</Button><fieldset style={{border:0,padding:0,margin:0,minWidth:0}} disabled={blockedBy(["link"])}><FbaShipmentLink initialShipmentId={shipmentId} onGuardChange={embedded?linkGuard:undefined} key={scope.id} data={data} scope={scope} catalog={catalog} canWrite={canWrite} refresh={refresh} saved={reload}/></fieldset></section>
    <section ref={reportLibrary} className={styles.receiptSupplement} hidden={!toolsOpen&&!!(chosenShipment||selected)} aria-label="收货表记录">
    <section ref={reportUpload} className={styles.panel}>
      {canWrite&&(!chosenShipment||reviewingReport)&&<FbaFileUpload compact onGuardChange={uploadGuard} disabled={uploadBlocked} key={scope.id} path={`${api}/uploads?scope_id=${scope.id}&prepare=true${shipmentId?`&shipment_id=${shipmentId}`:""}`} label="FBA收货表" saved={r=>{if("rows" in r)saved(r);}}/>}
      <section className={styles.reportHistory}><h3>已上传收货表（{data.batches.filter(b=>b.scope_id===scope.id&&b.source_kind!=="MANUAL").length} 份）</h3><div className={styles.reportList}>{data.batches.filter(b=>b.scope_id===scope.id&&b.source_kind!=="MANUAL").map(b=><Button key={b.id} variant="secondary" aria-pressed={selected===b.id} disabled={dirty||busy||unknown} onClick={()=>{setResult(undefined);selectBatch(b.id);}}>{b.filename} · {b.status==="POSTED"?"已处理":b.status==="PARTIAL"?"部分处理":b.status==="ABANDONED"?"已结束":"草稿"}</Button>)}</div></section>
    </section>
    </section>
  </div>;
}
function StandaloneReceiptLeave({dirty,busy,unknown}:OverviewGuard){
  return useProductionLeave(dirty,busy,unknown,["fba_batch","fba_draft"]).prompt;
}
function FbaShipmentLink({data,scope,catalog,canWrite,refresh,saved,initialShipmentId,onGuardChange}:{data:FbaState;scope:FbaScope;catalog:Sku[];canWrite:boolean;refresh:number;saved:()=>void;initialShipmentId?:string;onGuardChange?:(guard:OverviewGuard)=>void}) {
  const [shipmentId,setShipmentId]=useState(initialShipmentId||"");const [reference,setReference]=useState("");const [reason,setReason]=useState("");const [bindings,setBindings]=useState<BindingInput[]>([]);
  const list=useLoad<DocumentPage>("/api/production/shipments?page_size=100",refresh,!initialShipmentId);const shipment=useLoad<Document>(`/api/production/shipments/${shipmentId}`,refresh,!!shipmentId);
  const bindingState=useLoad<{bindings:unknown[]}>(`/api/production/inventory/destination-state?shipment_id=${shipmentId}`,refresh,!!shipmentId);
  const command=useCommand<FbaState>(()=>{if(onGuardChange){setReference("");setReason("");setBindings([]);}saved();});const bindingCommand=useCommand(saved);const disabled=!canWrite||command.busy||command.unknown||bindingCommand.busy||bindingCommand.unknown;
  const dirty=!!reference||!!reason||bindings.length>0,busy=command.busy||bindingCommand.busy,unknown=command.unknown||bindingCommand.unknown;
  useEffect(()=>{onGuardChange?.({dirty,busy,unknown});},[dirty,busy,unknown,onGuardChange]);
  useEffect(()=>()=>onGuardChange?.({dirty:false,busy:false,unknown:false}),[onGuardChange]);
  function suggest(){const source=shipment.value;if(!source)return;setBindings((source.cartons||[]).flatMap(box=>box.items.map(item=>{const found=(source.sources||[]).filter(s=>s.sku_id===item.sku_id);const row=found.length===1?found[0]:undefined;return{carton_id:box.id||"",sku_id:item.sku_id,units:item.units,source_line_id:row?.id||"",allocation_id:row?.allocations.length===1?row.allocations[0]?.id||null:null};})));}
  function change(index:number,values:Partial<BindingInput>){setBindings(previous=>previous.map((row,i)=>i===index?{...row,...values}:row));}
  return <section className={styles.panel}><h2>货件关联</h2>{command.feedback}{bindingCommand.feedback}
    <div className={styles.scroll} tabIndex={0}><table className={styles.table} aria-label="已关联FBA货件"><thead><tr><th>FBA货件号</th><th>原出货</th><th>来源依据</th></tr></thead><tbody>{data.references.filter(r=>r.scope_id===scope.id&&(!initialShipmentId||r.shipment_id===initialShipmentId)).map(r=><tr key={r.id}><td>{r.reference_id}</td><td><LinkButton to={`/production/shipments/${r.shipment_id}`} variant="quiet">查看出货 #{r.shipment_id}</LinkButton></td><td>{r.evidence}</td></tr>)}</tbody></table></div>
    {canWrite&&(!initialShipmentId||!data.references.some(r=>r.scope_id===scope.id&&r.shipment_id===initialShipmentId))&&<><fieldset className={styles.fields} disabled={disabled}><FormField label="已确认原出货" required><select disabled={!!initialShipmentId} value={shipmentId} onChange={e=>{setShipmentId(e.target.value);setBindings([]);}}><option value="">请选择出货</option>{initialShipmentId&&<option value={initialShipmentId}>{shipment.value?.business_number||shipment.value?.system_number||`出货 ${initialShipmentId}`}</option>}{list.value?.items.filter(s=>s.status==="CONFIRMED"&&s.destination_id===scope.warehouse_id&&s.owner_id===scope.owner_id).map(s=><option key={s.id} value={s.id}>{s.business_number||s.system_number}</option>)}</select></FormField><FormField label="FBA货件号" required><Input value={reference} onChange={e=>setReference(e.target.value)}/></FormField><FormField label="货件与出货对应依据" required><Input value={reason} onChange={e=>setReason(e.target.value)}/></FormField></fieldset>
      {shipment.value&&!(shipment.value.dispatch_purpose==="WAREHOUSE_DISPATCH"&&!shipment.value.cartons?.length)&&!bindingState.value?.bindings.length&&<><div className={styles.actions}><Button variant="secondary" disabled={disabled} onClick={suggest}>应用唯一箱来源候选</Button><Button variant="quiet" disabled={disabled} onClick={()=>setBindings(p=>[...p,{carton_id:"",source_line_id:"",allocation_id:null,sku_id:"",units:""}])}>增加分配行</Button></div><p className={styles.note}>候选只是建议。多来源或多订单必须明确选择并拆分，确认时服务端重新核对各箱、来源和订单数量。</p>
      {bindings.map((b,index)=>{const sources=shipment.value?.sources?.filter(s=>s.sku_id===b.sku_id)||[];const source=sources.find(s=>s.id===b.source_line_id);return <details key={index} className={styles.row}><summary>{catalog.find(s=>s.sku_id===b.sku_id)?.code||`分配${index+1}`} · {b.units||"待填"}件 · 箱{shipment.value?.cartons?.find(c=>c.id===b.carton_id)?.number||"待核"}</summary><fieldset className={styles.fields} disabled={disabled}><FormField label={`分配${index+1}规格`}><select value={b.sku_id} onChange={e=>change(index,{sku_id:e.target.value,source_line_id:"",allocation_id:null})}><option value="">选择规格</option>{catalog.map(s=><option key={s.sku_id} value={s.sku_id}>{s.label}</option>)}</select></FormField><FormField label={`分配${index+1}箱`}><select value={b.carton_id} onChange={e=>change(index,{carton_id:e.target.value})}><option value="">选择原箱</option>{shipment.value?.cartons?.map(c=><option value={c.id} key={c.id}>箱{c.number} · {c.id}</option>)}</select></FormField><FormField label={`分配${index+1}来源`}><select value={b.source_line_id} onChange={e=>change(index,{source_line_id:e.target.value,allocation_id:null})}><option value="">明确选择来源行</option>{sources.map(s=><option value={s.id} key={s.id}>{s.sku_label} · 来源{s.id} · {s.actual_units}件</option>)}</select></FormField><FormField label={`分配${index+1}订单`}><select value={b.allocation_id||""} onChange={e=>change(index,{allocation_id:e.target.value||null})}><option value="">无订单分配 / 待核</option>{source?.allocations.map(a=><option key={a.id} value={a.id}>{a.order_business_number||a.order_number||a.order_line_id} · 分配{a.units}件</option>)}</select></FormField><FormField label={`分配${index+1}件数`}><Input value={b.units} onChange={e=>change(index,{units:e.target.value})}/></FormField></fieldset><Button variant="quiet" disabled={disabled} onClick={()=>setBindings(p=>p.filter((_,i)=>i!==index))}>移除此分配行</Button></details>;})}
      <div><Button disabled={disabled||!reason||!bindings.length} onClick={()=>bindingCommand.submit("/api/production/inventory/destination-bindings",{shipment_id:shipmentId,expected_shipment_revision:shipment.value?.revision,reason,bindings})}>确认箱与订单分配</Button></div></>}
      <div><Button disabled={disabled||!shipment.value||!bindingState.value?.bindings.length||!reference||!reason} onClick={()=>command.submit(`${api}/commands/references`,{scope_id:scope.id,shipment_id:shipmentId,expected_shipment_revision:shipment.value?.revision,reference_id:reference,reason})}>关联平台货件</Button></div>
    </>}
  </section>;
}
function FbaBatchReview({batch,canWrite,saved,onGuardChange,onUploadGuardChange,catalog,events,onReplaceFile}:{events:FbaState["events"];catalog:Sku[];batch:FbaBatch;canWrite:boolean;saved:(batch:FbaBatch)=>void;onGuardChange?:(guard:OverviewGuard)=>void;onUploadGuardChange?:(guard:OverviewGuard)=>void;onReplaceFile:()=>void}) {
  const receiptHistory = useRef<HTMLDetailsElement>(null);
  const exceptionReview = useRef<HTMLDetailsElement>(null);
  const initial=batch.rows.map(row=>batch.decisions.find(d=>String(d.source_row)===String(row.source_row))||{source_row:String(row.source_row),decision:"PENDING" as const});
  const [decisions,setDecisions]=useState<FbaDecision[]>(initial);const resolved=new Set(batch.resolved.map(r=>Number(r.source_row)));
  const [selected,setSelected]=useState(batch.rows.filter(r=>!r.posting_block&&!resolved.has(r.source_row)).map(r=>String(r.source_row)));const [prefix,setPrefix]=useState(batch.decisions.find(d=>d.event_key)?.event_key?.replace(/-行\d+$/,"")||"");const [reason,setReason]=useState(batch.decisions.find(d=>d.reason)?.reason||"");
  const command=useCommand<FbaBatch>(saved);const disabled=!canWrite||command.busy||command.unknown||!["DRAFT","PARTIAL"].includes(batch.status);const dirty=JSON.stringify(initial)!==JSON.stringify(decisions);
  const touched=dirty||reason!==(batch.decisions.find(d=>d.reason)?.reason||"")||prefix!==(batch.decisions.find(d=>d.event_key)?.event_key?.replace(/-行\d+$/,"")||"");
  useEffect(()=>{onGuardChange?.({dirty:touched,busy:command.busy,unknown:command.unknown});},[touched,command.busy,command.unknown,onGuardChange]);
  useEffect(()=>()=>onGuardChange?.({dirty:false,busy:false,unknown:false}),[onGuardChange]);
  function receiptQuantity(row:FbaBatch["rows"][number]) {
    const decision=batch.decisions.find(value=>String(value.source_row)===String(row.source_row));
    const resolution=batch.resolved.find(value=>String(value.source_row)===String(row.source_row));
    const quantity=resolution?.confirmed_units ?? decision?.quantity ?? row.quantity;
    if(!/^-?[0-9]+$/.test(quantity))return quantity;
    if(resolution?.decision==="SAME"||decision?.decision==="SAME")return "0";
    const linked=resolution?.linked_units ?? (decision?.receipt_links||[]).reduce((sum,link)=>sum+BigInt(link.units),0n).toString();
    return (BigInt(quantity)-BigInt(linked)).toString();
  }
  const ready=batch.rows.filter(row=>!row.posting_block&&!resolved.has(row.source_row)&&/^[1-9][0-9]*$/.test(row.quantity)&&!row.existing_candidates.length&&!row.same_file_candidates.length&&!batch.issues.some(issue=>issue.row===row.source_row)&&batch.decisions.some(d=>String(d.source_row)===String(row.source_row)&&d.decision==="NEW"&&!d.correction_of&&!!d.allocations?.length&&!!d.reason));
  const readyUnits=ready.reduce((sum,row)=>sum+BigInt(receiptQuantity(row)),0n).toString();
  const planned = new Map<string, { sku: string; units: bigint; available: bigint }>();
  for (const row of ready) {
    const decision = batch.decisions.find(value => String(value.source_row) === String(row.source_row));
    for (const allocation of decision?.allocations || []) {
      const binding = row.bindings.find(value => value.id === allocation.binding_id);
      if (!binding || !/^[1-9][0-9]*$/.test(allocation.units)) continue;
      const previous = planned.get(binding.id);
      planned.set(binding.id, { sku: row.raw.MSKU || "待核商品", units: (previous?.units || 0n) + BigInt(allocation.units), available: BigInt(binding.units) - BigInt(binding.received_units) });
    }
  }
  const overages = [...planned.values()].filter(value => value.units > value.available);

  function change(row:string,values:Partial<FbaDecision>){setDecisions(p=>p.map(d=>String(d.source_row)===row?{...d,...values}:d));}
  function bulk(mode:"new"|"bindings"|"same"){setDecisions(p=>p.map(d=>{const row=batch.rows.find(r=>String(r.source_row)===String(d.source_row))!;if(row.posting_block||resolved.has(row.source_row)||!selected.includes(String(row.source_row)))return d;if(mode==="new")return{...d,decision:"NEW",event_key:`${prefix}-行${row.source_row}`,reason};if(mode==="same"&&row.existing_candidates.length===1)return{...d,decision:"SAME",existing_event_id:row.existing_candidates[0]!.id,reason};if(mode==="bindings"&&row.bindings.length===1)return{...d,allocations:[{binding_id:row.bindings[0]!.id,units:row.quantity}]};return d;}));}
  type ReportGroup = { shipment: string; reference:string; style: string; rows: typeof batch.rows; bindings: FbaBatch["rows"][number]["bindings"] };
  const groups = new Map<string, ReportGroup>();
  for (const row of batch.rows.filter(row => !row.posting_block)) {
    const style = catalog.find(sku => sku.sku_id === row.identity?.sku_id)?.style_code || "待核商品";
    const shipments = [...new Set(row.bindings.map(binding => binding.shipment_id))];
    for (const shipment of shipments.length ? shipments : [""]) {
      const reference=row.raw["Reference ID"]||"";
      const key = `${reference}:${shipment}:${style}`;
      const group = groups.get(key) || { shipment, reference, style, rows: [], bindings: [] };
      group.rows.push(row);
      for (const binding of row.bindings.filter(binding => binding.shipment_id === shipment)) {
        if (!group.bindings.some(item => item.id === binding.id)) group.bindings.push(binding);
      }
      groups.set(key, group);
    }
  }
  const shipmentIds = new Set([...groups.values()].map(group => group.shipment).filter(Boolean));
  const skuIds = new Set(batch.rows.map(row => row.identity?.sku_id).filter(Boolean));
  const relevantEvents = events.filter(event => event.scope_id === batch.scope_id && skuIds.has(event.sku_id) && (shipmentIds.has(event.shipment_id || "") || batch.resolved.some(row => row.event_id === event.id) || batch.rows.some(row => row.existing_candidates.some(candidate => candidate.id === event.id))));
  function openReceiptHistory() {
    if (receiptHistory.current) { receiptHistory.current.open = true; receiptHistory.current.scrollIntoView({ block: "start" }); receiptHistory.current.focus(); }
  }
  function openExceptionReview() {
    if(exceptionReview.current){exceptionReview.current.open=true;exceptionReview.current.scrollIntoView({block:"start"});exceptionReview.current.focus();}
  }
  return <section className={`${styles.panel} ${styles.receiptReview}`} aria-label="FBA接收审核"><header className={styles.receiptToolbar}><h3>{batch.filename}</h3><span className={styles.receiptState}>{fbaBatchStates[batch.status]||"待核"}</span></header>{command.feedback}
    {batch.rows.some(row => row.ledger_kind) && <div className={styles.scroll}><table className={styles.table} aria-label="分类账核对"><thead><tr><th>日期</th><th>商品规格</th><th>类型</th><th>数量</th><th>处理</th></tr></thead><tbody>{batch.rows.map(row => <tr key={row.source_row}><td>{row.business_date}</td><th scope="row">{row.raw.MSKU}</th><td>{{RECEIPT:"货件接收",CORRECTION:"冲销更正",CUSTOMER_RETURN:"客户实物退回",ADJUSTMENT:"其他库存调整",UNKNOWN:"待核"}[row.ledger_kind || "UNKNOWN"]}</td><td>{row.quantity}</td><td>{row.posting_block === "SNAPSHOT_COVERED" ? `快照已覆盖 · ${row.snapshot_on}` : row.posting_block ? "待核" : resolved.has(row.source_row) ? "已处理" : row.ledger_kind === "CORRECTION" ? "关联原事件" : "待确认"}</td></tr>)}</tbody></table></div>}
    {batch.issues.filter(issue => issue.code !== "fba_event_type_invalid").map((issue,index)=><StatusMessage key={index} kind="danger" title={`原表第${issue.row}行 · ${issue.column}`}>{issue.message} 原值：{issue.raw||"（空白）"}。代码：{issue.code}</StatusMessage>)}
    {!!overages.length&&<StatusMessage kind="warning" title={overages.every(value => value.available <= 0n) ? "本批已收齐，当前报告可能重复" : "接收数量超出待收"}>请核对下表标红的数量，再决定更换文件或处理异常。<div className={styles.actions}><Button variant="secondary" onClick={openReceiptHistory}>查看已入库记录</Button>{canWrite&&<Button variant="quiet" disabled={command.busy||command.unknown||touched} onClick={onReplaceFile}>更换文件</Button>}</div></StatusMessage>}
    {[...groups].map(([key, group]) => {
      const shipped = group.bindings.reduce((sum, binding) => sum + BigInt(binding.units), 0n);
      const received = group.bindings.reduce((sum, binding) => sum + BigInt(binding.received_units), 0n);
      const remaining = shipped > received ? shipped - received : 0n;
      return <section key={key} className={styles.receiptGroup}>
        {group.shipment && <ShipmentDateNotice shipmentId={group.shipment} receivedOn={group.rows.filter(row => selected.includes(String(row.source_row))).map(row => row.business_date)} canWrite={canWrite} />}
        <header className={styles.receiptGroupHeading}><strong>{group.reference || "货件待核"} · {group.style}</strong><span>{group.bindings.length ? `出货 #${group.shipment} · 已发${shipped}件 · 累计接收${received}件 · 本批待收${remaining}件` : "出货来源待核"}</span></header>
        <div className={styles.scroll}><table className={`${styles.table} ${styles.receiptReviewTable}`} aria-label={`${shipmentIds.size > 1 ? `出货 #${group.shipment} ` : ""}${group.style} 本批接收核对`}>
          <thead><tr><th>商品规格</th><th title="本批已入库数量，确认后更新">已入库</th><th>本次接收</th><th>核对结果</th></tr></thead>
          <tbody>{[...new Set(group.rows.map(row => row.identity?.sku_id || row.raw.MSKU))].map(sku => {
            const items = group.rows.filter(row => (row.identity?.sku_id || row.raw.MSKU) === sku);
            const bindings = [...new Map(items.flatMap(row => row.bindings.filter(binding => binding.shipment_id === group.shipment)).map(binding => [binding.id, binding])).values()];
            const bindingIds = new Set(bindings.map(binding => binding.id));
            const before = bindings.reduce((sum, binding) => sum + BigInt(binding.received_units), 0n);
            let amount = 0n;
            let unknown = false;
            for (const row of items.filter(row => ready.includes(row))) {
              const allocations = batch.decisions.find(decision => String(decision.source_row) === String(row.source_row))?.allocations || [];
              if (allocations.length && allocations.every(allocation => row.bindings.some(binding => binding.id === allocation.binding_id) && /^-?[0-9]+$/.test(allocation.units))) {
                amount += allocations.filter(allocation => bindingIds.has(allocation.binding_id)).reduce((sum, allocation) => sum + BigInt(allocation.units), 0n);
              } else if (new Set(row.bindings.map(binding => binding.shipment_id)).size <= 1 && /^-?[0-9]+$/.test(receiptQuantity(row))) {
                amount += BigInt(receiptQuantity(row));
              } else unknown = true;
            }
            const over = [...planned].filter(([id]) => bindingIds.has(id)).reduce((sum, [, value]) => sum + (value.units > value.available ? value.units - value.available : 0n), 0n);
            const pending = items.filter(row => !resolved.has(row.source_row) && !ready.includes(row)).length;
            const status = unknown ? "来源分配待核" : over > 0n ? `超出${over}件` : pending ? `${pending}行待核` : items.every(row => resolved.has(row.source_row)) ? "已处理" : "可确认";
            return <tr key={sku} className={over > 0n ? styles.overageRow : undefined}>
              <th scope="row">{items[0]!.raw.MSKU}</th>
              <td><ReceiptQuantityPreview before={bindings.length ? before.toString() : undefined} added={!over && !unknown ? amount : 0n} label={items[0]!.raw.MSKU || sku!} /></td>
              <td>{unknown ? "待核" : amount.toString()}</td><td>{status}</td>
            </tr>;
          })}</tbody>
        </table></div>
      </section>;
    })}
    {!disabled&&<div className={styles.receiptReviewActions}>
      {overages.length>0?<><span>数量核对完成后可入库</span><Button variant="secondary" onClick={openExceptionReview}>处理异常</Button></>:<>
        {!!ready.length&&<><span>确认后更新库存</span><Button className={styles.receiptConfirm} variant="primary" disabled={touched||command.busy||command.unknown} onClick={()=>command.submit(`${api}/commands/batch-confirm`,{batch_id:batch.id,expected_revision:batch.revision,source_rows:ready.map(row=>String(row.source_row)),reason:"用户整批核对接收原表，确认本次实际入库"})}>确认本次入库 {readyUnits} 件</Button></>}
        {!ready.length&&batch.rows.some(row=>!row.posting_block&&!resolved.has(row.source_row))&&<Button disabled={touched||command.busy||command.unknown} onClick={()=>command.submit(`${api}/batches/${batch.id}/prepare`,{})}>匹配本批接收来源</Button>}
      </>}
    </div>}
    <details ref={receiptHistory} tabIndex={-1} className={styles.receiptHistory}>
      <summary>已入库记录</summary>
      <p>本报告新增入库{batch.rows.filter(row => resolved.has(row.source_row)).reduce((sum, row) => sum + (/^-?[0-9]+$/.test(receiptQuantity(row)) ? BigInt(receiptQuantity(row)) : 0n), 0n).toString()}件</p>
      <div className={styles.scroll}><table className={styles.table} aria-label="关联出货已入库记录"><thead><tr><th>日期</th><th>商品规格</th><th>入库数量</th><th>来源</th></tr></thead><tbody>{relevantEvents.map(event => <tr key={event.id}><td>{event.occurred_local.slice(0, 10)}</td><th scope="row">{catalog.find(sku => sku.sku_id === event.sku_id)?.code || batch.rows.find(row => row.identity?.sku_id === event.sku_id)?.raw.MSKU || event.sku_id}</th><td>{event.units}</td><td><details><summary>{event.correction_of ? "接收更正" : event.source_kind === "MANUAL" ? "手工接收" : "报告接收"}</summary><p>记录 #{event.id} · {event.evidence}</p></details></td></tr>)}{!relevantEvents.length && <tr><td colSpan={4}>暂无可定位的记录，可展开已上传收货表回查原批次。</td></tr>}</tbody></table></div>
    </details>
    <details ref={exceptionReview} tabIndex={-1} className={styles.receiptSupplement}><summary>逐行核对与更正</summary>
    {!disabled&&<><fieldset className={styles.fields} disabled={disabled}><FormField label="本批人工事件核对前缀" hint="须有原始证据依据，不把行号冒充官方唯一事件ID。"><Input value={prefix} onChange={e=>setPrefix(e.target.value)}/></FormField><FormField label="本批核对依据" required><Input value={reason} onChange={e=>setReason(e.target.value)}/></FormField></fieldset><div className={styles.actions}><Button variant="secondary" disabled={!prefix||!reason} onClick={()=>bulk("new")}>标为新增待确认</Button><Button variant="secondary" onClick={()=>bulk("bindings")}>应用唯一出货来源</Button><Button variant="secondary" disabled={!reason} onClick={()=>bulk("same")}>复核唯一相同事件候选</Button></div><div className={styles.actions}><Button variant="quiet" onClick={()=>setSelected([])}>清空本次选择</Button><Button variant="quiet" onClick={()=>setSelected(batch.rows.filter(r=>!r.posting_block&&!resolved.has(r.source_row)).map(r=>String(r.source_row)))}>选择所有未处理行</Button>{[...new Set(batch.rows.map(r=>r.business_date))].filter(Boolean).map(date=><Button variant="quiet" key={date} onClick={()=>setSelected(batch.rows.filter(r=>r.business_date===date&&!r.posting_block&&!resolved.has(r.source_row)).map(r=>String(r.source_row)))}>选择{date}</Button>)}</div></>}
    {batch.rows.map(row=>{const d=decisions.find(d=>String(d.source_row)===String(row.source_row))!;const rowId=String(row.source_row);const done=resolved.has(row.source_row);const locked=disabled||done||!!row.posting_block;return <div className={styles.row} key={rowId}><div className={styles.rowTitle}><label className={styles.check}><input type="checkbox" aria-label={`选择原表第${rowId}行`} disabled={locked} checked={selected.includes(rowId)} onChange={e=>setSelected(p=>e.target.checked?[...p,rowId]:p.filter(id=>id!==rowId))}/><strong>第{rowId}行 · {row.raw.MSKU}</strong> {row.quantity}件</label><span className={styles.note}>{row.business_date} · FC {row.raw["Fulfillment Center"]} · {done?"已处理":!row.identity?"身份待匹配":tracked(row.identity.tracked)?"已跟踪":"未纳入跟踪"}</span></div>
      <details><summary>查看原文与处理决定 · {d.decision==="NEW"?"新增核对":d.decision==="SAME"?"关联已有事件":"待核"}</summary><p className={styles.note}>{row.raw["Date and Time"]} · Reference {row.raw["Reference ID"]} · ASIN {row.raw.ASIN} · FNSKU {row.raw.FNSKU} · Store {row.raw.Store||"空白，使用已确认账号范围"}</p>
      <fieldset className={styles.fields} disabled={locked}><FormField label={`第${rowId}行处理`}><select value={d.decision} onChange={e=>change(rowId,{decision:e.target.value as FbaDecision["decision"]})}><option value="PENDING">保留待核</option><option value="NEW">独立新增事件</option><option value="SAME">同一已有事件</option></select></FormField>
      {d.decision==="SAME"?<FormField label={`第${rowId}行已有事件`}><select value={d.existing_event_id||""} onChange={e=>change(rowId,{existing_event_id:e.target.value})}><option value="">明确选择已有事件</option>{row.existing_candidates.map(e=><option key={e.id} value={e.id}>{e.event_key} · {e.units}件 · 批次{e.batch_id}第{e.source_row}行</option>)}</select></FormField>:<><FormField label={`第${rowId}行事件核对引用`}><Input value={d.event_key||""} onChange={e=>change(rowId,{event_key:e.target.value})}/></FormField><FormField label={`第${rowId}行更正原接收记录`} hint="负数必须关联原正数事件；正数修订可关联此前负数。"><select value={d.correction_of||""} onChange={e=>{change(rowId,{correction_of:e.target.value,decision:"NEW",event_key:d.event_key||`receipt-review:${batch.id}:${rowId}`,reason:d.reason||`用户核对原表第${rowId}行更正`,allocations:d.allocations?.length?d.allocations:row.bindings.length===1?[{binding_id:row.bindings[0]!.id,units:row.quantity}]:[]});if(!reason)setReason("用户核对本批接收更正");}}><option value="">选择原接收记录</option>{d.correction_of&&!events.some(event=>event.event_key===d.correction_of)&&<option value={d.correction_of}>{d.correction_of}</option>}{events.filter(event=>event.scope_id===batch.scope_id&&event.sku_id===row.identity?.sku_id&&row.bindings.some(binding=>binding.reference_link_id===event.reference_link_id)&&/^-?[0-9]+$/.test(row.quantity)&&BigInt(event.units)*BigInt(row.quantity)<0n).map(event=><option key={event.id} value={event.event_key}>{event.occurred_local} · {event.units} 件 · 记录 {event.id}</option>)}</select></FormField></>}
      <FormField label={`第${rowId}行依据`}><Input value={d.reason||""} onChange={e=>change(rowId,{reason:e.target.value})}/></FormField></fieldset>
      {d.decision==="NEW"&&<><label className={styles.check}><input type="checkbox" disabled={locked} checked={d.independent_occurrence||false} onChange={e=>change(rowId,{independent_occurrence:e.target.checked})}/>存在相同候选时，已核实本行是独立发生而非重复报告</label><div className={styles.fields}>{row.bindings.map(binding=>{const value=d.allocations?.find(a=>a.binding_id===binding.id)?.units||"";return <FormField key={binding.id} label={`第${rowId}行 ${binding.carton_id?`箱${binding.carton_id}`:"本批货物"} 件数`} hint={`来源${binding.source_line_id}，分配${binding.units}件，已净收${binding.received_units}件`}><Input disabled={locked} value={value} onChange={e=>change(rowId,{allocations:[...(d.allocations||[]).filter(a=>a.binding_id!==binding.id),...(e.target.value?[{binding_id:binding.id,units:e.target.value}]:[])]})}/></FormField>;})}</div>{!row.bindings.length&&<p className={styles.error}>该平台货件尚未关联出货来源，本行不能入账。</p>}</>}
      </details></div>;})}
    {!disabled&&<><div className={styles.actions}><Button variant="secondary" disabled={!dirty||!reason||command.busy||command.unknown} onClick={()=>command.submit(`${api}/commands/batch-save`,{batch_id:batch.id,expected_revision:batch.revision,decisions,reason})}>保存核对草稿</Button><Button variant="primary" disabled={dirty||!selected.length||!reason||command.busy||command.unknown} onClick={()=>command.submit(`${api}/commands/batch-confirm`,{batch_id:batch.id,expected_revision:batch.revision,source_rows:selected,reason})}>确认所选{selected.length}行接收</Button><Button variant="quiet" disabled={!reason||command.busy||command.unknown} onClick={()=>command.submit(`${api}/commands/batch-abandon`,{batch_id:batch.id,expected_revision:batch.revision,reason})}>结束未处理明细</Button></div><FbaFileUpload onGuardChange={onUploadGuardChange} path={`${api}/batches/${batch.id}/reimport`} label="系统核对工作簿回导" disabled={command.busy||command.unknown||(onGuardChange?touched:dirty)} saved={r=>{if("rows" in r)saved(r);}}/></>}
    </details>
    <details className={styles.receiptSupplement}><summary>原文件与操作记录</summary>
      <div className={styles.actions}>{canWrite&&<LinkButton variant="quiet" to={`${api}/batches/${batch.id}/original`} reloadDocument>下载接收原件</LinkButton>}<LinkButton variant="quiet" to={`${api}/batches/${batch.id}/export`} reloadDocument>导出核对明细</LinkButton></div>
      <p>批次 #{batch.id} · 修订 {batch.revision} · 原表 {batch.rows.length} 行 · 已处理 {batch.resolved.length} 行</p>
      {batch.history.map((h,index)=><p key={index}>{h.created_at} · {h.actor_name} · {h.operation_kind} · 修订{h.revision} · {h.reason}</p>)}
    </details>
  </section>;
}
