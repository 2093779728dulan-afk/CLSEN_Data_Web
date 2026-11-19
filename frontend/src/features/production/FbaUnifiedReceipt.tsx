import { useBusinessToday } from "./workbenchDate";
import { ShipmentDateNotice } from "./ShipmentDateNotice";
import { Fragment, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Button, FormField, Input, LinkButton, Menu, StatusMessage } from "../../design-system";
import { StockDetailWindow } from "./StockDetailWindow";
import { FbaFileUpload } from "./FbaFileUpload";
import { FbaIdentityExtension } from "./FbaIdentityExtension";
import { ReceiptQuantityPreview } from "./ReceiptQuantityPreview";
import { useCommand, useLoad } from "./useProductionApi";
import type { Document, Sku } from "./types";
import type { FbaBatch, FbaCatalogProducts, FbaReceiptDraft, FbaReceiptLine, FbaRow, FbaScope, FbaState } from "./fbaTypes";
import { tracked } from "./fbaTypes";
import { StockWindowContainer, type OverviewGuard } from "./stockOverview";
import styles from "./FbaUnifiedReceipt.module.css";
type Binding = {
  id: string;
  sku_id: string;
  units: string;
  received_units: string;
  source_line_id: string;
  allocation_id: string | null;
};
type DestinationState = {
  bindings: Binding[];
};
const api = "/api/production/fba";
const integer = (value: string) => /^[1-9][0-9]{0,8}$/.test(value);
const amount = (value?: string) => value && /^-?[0-9]+$/.test(value) ? BigInt(value) : 0n;
function linkedUnits(line: FbaReceiptLine) { return line.decision === "SAME" ? amount(line.quantity) : (line.receipt_links || []).reduce((sum, link) => sum + amount(link.units), 0n); }
function allocate(line: FbaReceiptLine, bindings: Binding[]): FbaReceiptLine {
  const available = bindings.filter(binding => binding.sku_id === line.sku_id);
  const units = amount(line.quantity) - linkedUnits(line);
  return available.length === 1 ? { ...line, allocations: units > 0n ? [{ binding_id: available[0]!.id, units: units.toString() }] : [] } : line;
}
export function FbaUnifiedReceipt({ data, scope, catalog, shipmentId, refresh, canWrite, saved, onGuardChange, onReport, draftId, onDraft, onSources }: {
  data: FbaState;
  scope: FbaScope;
  catalog: Sku[];
  shipmentId: string;
  refresh: number;
  canWrite: boolean;
  saved: () => void;
  onGuardChange: (guard: OverviewGuard) => void;
  onReport: (batch: FbaBatch) => void;
  draftId?: string;
  onDraft?: (batch: FbaBatch) => void;
  onSources?:()=>void;
}) {
  const [sourceRevision, setSourceRevision] = useState(0);
  const loadKey = `${refresh}:${sourceRevision}`;
  const shipment = useLoad<Document>(`/api/production/shipments/${shipmentId}`, loadKey, true, true);
  const sources = useLoad<DestinationState>(`/api/production/inventory/destination-state?shipment_id=${shipmentId}`, loadKey, true, true);
  const [existingId] = useState(() => draftId || data.batches.find(batch => batch.source_kind === "MANUAL" && batch.shipment_id === shipmentId && batch.scope_id === scope.id && batch.status === "DRAFT")?.id);
  const draft = useLoad<FbaBatch>(`${api}/batches/${existingId}`, refresh, !!existingId, true);
  if(!shipment.value || !sources.value || existingId && !draft.value)
    return <StatusMessage kind={shipment.error || sources.error || draft.error ? "danger" : "info"} title="正在读取本批接收表">{shipment.error || sources.error || draft.error || "正在核对已发货商品与累计实收。"}</StatusMessage>;
  if(shipment.value.destination_id !== scope.warehouse_id || shipment.value.owner_id !== scope.owner_id || shipment.value.status !== "CONFIRMED")
    return <StatusMessage kind="warning" title="本批出货范围需要核对">请选择当前仓库与货主的已确认出货。</StatusMessage>;
  if (draft.value && (draft.value.scope_id !== scope.id || draft.value.shipment_id !== shipmentId || draft.value.source_kind !== "MANUAL")) return <StatusMessage kind="danger" title="接收草稿范围不一致">请重新选择本批草稿。</StatusMessage>;
  return <>{(shipment.error || sources.error || draft.error) && <StatusMessage kind="danger" title="最新接收资料读取未完成">{shipment.error || sources.error || draft.error}。已保留当前输入，请重新载入核对。</StatusMessage>}<fieldset className={styles.frame} disabled={!shipment.current || !sources.current || !!existingId && !draft.current}>
    <ReceiptEditor key={`${scope.id}:${shipmentId}:${existingId || "new"}`} data={data} scope={scope} catalog={catalog} shipment={shipment.value} bindings={sources.value.bindings} initial={draft.value?.status === "DRAFT" ? draft.value : undefined} canWrite={canWrite} saved={saved} onGuardChange={onGuardChange} onReport={onReport} onDraft={onDraft} onSources={onSources} refreshSources={() => setSourceRevision(previous => previous + 1)} />
  </fieldset></>;
}
function ReceiptEditor({ data, scope, catalog, shipment, bindings, initial, canWrite, saved, onGuardChange, onReport, refreshSources, onDraft, onSources }: {
  data: FbaState;
  scope: FbaScope;
  catalog: Sku[];
  shipment: Document;
  bindings: Binding[];
  initial?: FbaBatch;
  canWrite: boolean;
  saved: () => void;
  onGuardChange: (guard: OverviewGuard) => void;
  onReport: (batch: FbaBatch) => void;
  refreshSources: () => void;
  onDraft?: (batch: FbaBatch) => void;
  onSources?:()=>void;
}) {
  const today = useBusinessToday();
  const windowContainer=useContext(StockWindowContainer);
  const [tool,setTool]=useState<""|"history"|"reports"|"files"|"time"|"add"|"upload">("");
  const [referenceOverride,setReferenceOverride]=useState<{base:FbaState;value:FbaState["references"]}>();
  const references=(referenceOverride?.base===data?referenceOverride.value:data.references).filter(item=>item.scope_id===scope.id&&item.shipment_id===shipment.id&&item.shipment_revision===shipment.revision);
  const soleReference=references.length===1?references[0]:undefined;
  const empty = (): FbaReceiptDraft => ({ reference_link_id:soleReference?.id||"",reference_number:soleReference?.reference_id||"",business_date: today(), reason: "", lines: [...new Set(bindings.map(binding => binding.sku_id))].map((sku, index) => ({ line_id: String(index + 1), sku_id: sku, quantity: "", selected: bindings.some(binding => binding.sku_id === sku && amount(binding.units) > amount(binding.received_units)), allocations: [] })) });
  const [value, setValue] = useState<FbaReceiptDraft>(initial?.draft_payload ? {...initial.draft_payload,reference_link_id:initial.draft_payload.reference_link_id||soleReference?.id||"",reference_number:initial.draft_payload.reference_number||soleReference?.reference_id||""} : empty);
  const [record, setRecord] = useState(initial);
  const [identityOverride, setIdentityOverride] = useState<{ base: FbaState; value: FbaState }>();
  const identityData = identityOverride?.base === data ? identityOverride.value : data;
  const identities = identityData.identities || [];
  const identityScope = identityData.scopes?.find(item => item.id === scope.id) || scope;
  const [productRefresh, setProductRefresh] = useState(0);
  const needsProducts = bindings.some(binding => !identities.some(item => item.scope_id === scope.id && item.sku_id === binding.sku_id));
  const products = useLoad<FbaCatalogProducts>(`${api}/catalog-products?report_source_scope_id=${scope.report_source_scope_id}`, productRefresh, needsProducts);
  const automaticProducts = new Set(products.current ? (products.value?.identities || []).filter(item=>item.store===scope.store_evidence).map(item=>item.sku_id) : []);
  const [identityGuard, setIdentityGuard] = useState<OverviewGuard>({ dirty: false, busy: false, unknown: false });
  const [baseline, setBaseline] = useState(JSON.stringify(initial?.draft_payload || empty()));
  const [reports, setReports] = useState<FbaBatch[]>(initial?.source_reports || []);
  const [pendingImport, setPendingImport] = useState<FbaBatch>();
  const [replace, setReplace] = useState<string[]>([]);
  const [fillPrompt, setFillPrompt] = useState(false);
  const [review, setReview] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [showComplete, setShowComplete] = useState(false);
  const [extraSku, setExtraSku] = useState("");
  const reviewRef = useRef<HTMLElement>(null);
  const receiptHistory = useRef<HTMLElement>(null);
  const importSection = useRef<HTMLElement>(null);
  const [fileGuard, setFileGuard] = useState<OverviewGuard>({ dirty: false, busy: false, unknown: false });
  const [workbookGuard, setWorkbookGuard] = useState<OverviewGuard>({ dirty: false, busy: false, unknown: false });
  const uploadGuard = useCallback((guard: OverviewGuard) => setFileGuard(guard), []);
  const reimportGuard = useCallback((guard: OverviewGuard) => setWorkbookGuard(guard), []);
  const [newReference,setNewReference]=useState("");
  const [referenceReason,setReferenceReason]=useState("");
  const [editingReference,setEditingReference]=useState(false);
  const chosenReference=references.find(item=>item.id===value.reference_link_id&&(!value.reference_number||item.reference_id===value.reference_number));
  const referenceCommand=useCommand<FbaState>(result=>{
    setReferenceOverride({base:data,value:result.references});
    const linked=result.references.find(item=>item.scope_id===scope.id&&item.shipment_id===shipment.id&&item.reference_id===newReference);
    setValue(previous=>({...previous,reference_link_id:linked?.id||"",reference_number:linked?.reference_id||""}));
    setNewReference("");setReferenceReason("");setEditingReference(false);setReview(false);setError("");setSuccess("");saved();
  });
  const intention = useRef<"save" | "confirm">("save");
  const command = useCommand<FbaBatch>(result => {
    setRecord(result);setError("");
    if(result.status === "POSTED") {
      setSuccess(Number(result.added_units||0)>0?`已接收 ${result.added_units} 件`:`已关联 ${result.linked_units||"0"} 件，库存未重复增加`);
      const next = empty();
      setValue(next);
      setBaseline(JSON.stringify(next));
      setRecord(undefined);
      setReview(false);
      saved();
    }
    else {
      setValue(result.draft_payload!);
      setBaseline(JSON.stringify(result.draft_payload));
      onDraft?.(result);
      if(intention.current === "confirm")
        setReview(true);
      else
        setSuccess("草稿已保存");
    }
  }, refreshSources);
  const identitySaved = (result: FbaState) => {
    setIdentityOverride({ base: data, value: result });
    setReview(false);
    setError("");
    setSuccess("商品资料已核对并启用，可继续验收");
  };
  const restoreProducts = useCommand<FbaState>(identitySaved);
  const dirty = JSON.stringify(value) !== baseline;
  const operationLocked = command.busy || command.unknown || fileGuard.busy || fileGuard.unknown || workbookGuard.busy || workbookGuard.unknown || identityGuard.busy || identityGuard.unknown || restoreProducts.busy || restoreProducts.unknown || referenceCommand.busy || referenceCommand.unknown || !!pendingImport;
  const locked=!canWrite||operationLocked;
  useEffect(() => { onGuardChange({ dirty: dirty || !!newReference || !!referenceReason || fileGuard.dirty || workbookGuard.dirty || identityGuard.dirty || !!pendingImport, busy: referenceCommand.busy || command.busy || fileGuard.busy || workbookGuard.busy || identityGuard.busy || restoreProducts.busy, unknown: referenceCommand.unknown || command.unknown || fileGuard.unknown || workbookGuard.unknown || identityGuard.unknown || restoreProducts.unknown }); }, [dirty,newReference,referenceReason,referenceCommand.busy,referenceCommand.unknown, fileGuard, workbookGuard, identityGuard, pendingImport, command.busy, command.unknown, restoreProducts.busy, restoreProducts.unknown, onGuardChange]);
  useEffect(() => () => onGuardChange({ dirty: false, busy: false, unknown: false }), [onGuardChange]);
  useEffect(() => {
    if (review) {
      reviewRef.current?.scrollIntoView?.({ block: "nearest" });
      reviewRef.current?.focus({ preventScroll: true });
    }
  }, [review]);
  const sourceRow = (line: FbaReceiptLine) => reports.find(report => report.id === line.batch_id)?.rows.find(row => String(row.source_row) === line.source_row);
  const remaining = (sku: string) => bindings.filter(binding => binding.sku_id === sku).reduce((sum, binding) => sum + amount(binding.units) - amount(binding.received_units), 0n);
  const selected = value.lines.filter(line => line.selected && line.quantity !== "" && line.quantity !== "0");
  const total = selected.reduce((sum, line) => sum + amount(line.quantity), 0n);
  const linked = selected.reduce((sum, line) => sum + linkedUnits(line), 0n);
  const changes = value.lines.filter(line => line.batch_id && sourceRow(line) && (!line.selected || line.quantity !== sourceRow(line)!.quantity));
  const planned = new Map<string, bigint>();
  for(const line of selected)
    for(const allocation of line.allocations)
      planned.set(allocation.binding_id, (planned.get(allocation.binding_id) || 0n) + amount(allocation.units));
  const overages = bindings.filter(binding => (planned.get(binding.id) || 0n) > amount(binding.units) - amount(binding.received_units));
  function update(id: string, patch: Partial<FbaReceiptLine>) {
    setError("");
    setReview(false);
    setSuccess("");
    setValue(previous => ({ ...previous, lines: previous.lines.map(line => line.line_id === id ? allocate({ ...line, ...patch }, bindings) : line) }));
  }
  function fillPending() {
    const selectedManual = value.lines.filter(line => line.selected && !line.batch_id);
    if (new Set(selectedManual.map(line => line.sku_id)).size !== selectedManual.length) {
      setError("同一规格有多条手工记录，请逐条填写本次数量。");
      setFillPrompt(false);
      return;
    }
    setValue(previous => ({ ...previous, lines: previous.lines.map(line => line.selected && !line.batch_id ? allocate({ ...line, quantity: (remaining(line.sku_id) > 0n ? remaining(line.sku_id) : 0n).toString() }, bindings) : line) }));
    setFillPrompt(false);
    setReview(false);
    setSuccess("");
  }
  function incomingRows(report: FbaBatch) {
    return report.rows.filter(row => !row.posting_block && (!row.ledger_kind || row.ledger_kind==="RECEIPT") && row.raw["Event Type"]==="Receipts" && !!chosenReference && row.raw["Reference ID"]===chosenReference.reference_id && row.bindings.some(binding => binding.shipment_id === shipment.id) && !report.resolved.some(item => String(item.source_row) === String(row.source_row)) && integer(row.quantity) && row.identity && !report.issues.some(issue => issue.row === row.source_row));
  }
  function receiveReport(report: FbaBatch) {
    setError("");
    onReport(report);
    if(reports.some(existing => existing.id === report.id)) {
      setError("此报告已在当前接收表中，原核对输入已保留。");
      return;
    }
    const incoming = incomingRows(report);
    if(!incoming.length) {
      setError("原报告已保留，当前没有可填入本批的正数接收行。请在“收货表记录”中选择该报告，核对身份、来源或更正。");
      return;
    }
    setPendingImport(report);
    setReplace([]);
  }
  function applyImport() {
    if(!pendingImport)
      return;
    const report = pendingImport;
    const incoming = incomingRows(report);
    const skus = new Set(incoming.map(row => row.identity!.sku_id));
    let nextId = Math.max(0, ...value.lines.map(line => Number(line.line_id)));
    const lines = value.lines.filter(line => line.batch_id || !skus.has(line.sku_id) || amount(line.quantity) > 0n && !replace.includes(line.sku_id));
    for(const row of incoming) {
      const conflict = value.lines.some(line => !line.batch_id && line.sku_id === row.identity!.sku_id && amount(line.quantity) > 0n) && !replace.includes(row.identity!.sku_id);
      if(conflict)
        continue;
      lines.push(allocate({ line_id: String(++nextId), sku_id: row.identity!.sku_id, selected: true, quantity: row.quantity, allocations: [], batch_id: report.id, source_row: String(row.source_row), decision: "NEW", overlap_checked: !row.receipt_candidates?.some(event => event.shipment_id === shipment.id && amount(event.uncovered_units) > 0n) && !row.existing_candidates.length && !row.same_file_candidates.length }, bindings));
    }
    setReports(previous => [...previous, report]);
    setValue(previous => ({ ...previous, lines }));
    setPendingImport(undefined);setTool("");
    setReview(false);
    setSuccess("");
  }
  function invalid(line: FbaReceiptLine): string {
    const identity = identities.find(item => item.scope_id === scope.id && item.sku_id === line.sku_id);
    if (!identity && !automaticProducts.has(line.sku_id)) return "请先补齐这件商品的平台资料";
    if (identity && !tracked(identity.tracked)) return "此商品已停用，请先恢复使用";
    if(!integer(line.quantity))
      return "请输入正整数";
    const row = sourceRow(line);
    if(row?.posting_block)return row.posting_block==="SNAPSHOT_COVERED"?"原接收已包含在盘点中":"此行不属于卖家货件接收";
    if(row&&row.raw["Reference ID"]!==chosenReference?.reference_id)return "原报告对应其他FBA货件";
    if(line.batch_id && !row)
      return "原报告尚未载入";
    if(row && !line.overlap_checked)
      return "请核对是否已手工接收或重复报告";
    if(row && line.quantity !== row.quantity && !line.adjustment_reason?.trim())
      return "请填写原表调整说明";
    if(line.receipt_mode === "LINK" && !line.receipt_links?.length)
      return "请填写对应已接收记录的关联数量";
    if(linkedUnits(line) > amount(line.quantity))
      return "关联量超过本次确认量";
    if(line.decision === "SAME" && !line.existing_event_id)
      return "请选择对应原接收记录";
    if(line.decision !== "SAME" && line.allocations.reduce((sum, allocation) => sum + amount(allocation.units), 0n) !== amount(line.quantity) - linkedUnits(line))
      return "请明确各来源分配";
    if(line.allocations.some(allocation => !integer(allocation.units)))
      return "来源数量须为正整数";
    if(line.allocations.some(allocation => !bindings.some(binding => binding.id === allocation.binding_id && binding.sku_id === line.sku_id)))
      return "来源已变化，请重新填写或分配数量";
    return "";
  }
  function validate() {
    setSuccess("");
    if(!chosenReference){setError("请先填写或选择FBA货件号。");document.getElementById("fba-receipt-reference")?.focus();return false;}
    if(!selected.length) {
      setError("请勾选实际到货规格并填写本次收货数量。");
      return false;
    }
    if(!value.business_date || !value.reason.trim()) {
      setError("请填写收货日期与收货依据。");
      document.getElementById(!value.business_date ? "fba-receipt-date" : "fba-receipt-reason")?.focus();
      return false;
    }
    const first = selected.find(line => invalid(line));
    if(first || overages.length) {
      setError(first ? invalid(first) : "本次新增接收超过当前待收，请核对红色商品行。");
      const target = document.getElementById(`fba-quantity-${first?.line_id || value.lines.find(line => line.sku_id === overages[0]?.sku_id)?.line_id}`);
      target?.scrollIntoView({ block: "center" });
      target?.focus();
      target?.classList.remove(styles.attention!);
      requestAnimationFrame(() => target?.classList.add(styles.attention!));
      return false;
    }
    if(changes.some(line => !line.adjustment_reason?.trim())) {
      setError("请填写原表调整或本次不接收的原因。");
      return false;
    }
    return true;
  }
  function save(confirm = false) {
    if(confirm && !validate())
      return;
    setError("");setSuccess("");
    intention.current = confirm ? "confirm" : "save";
    if(confirm && record && !dirty && value.shipment_revision === shipment.revision) {
      setReview(true);
      return;
    }
    command.submit(`${api}/commands/unified-save`, { scope_id: scope.id, shipment_id: shipment.id, expected_shipment_revision: shipment.revision, ...(record ? { batch_id: record.id, expected_revision: record.revision } : {}), draft_payload: value });
  }
  const visible = value.lines.filter(line => showComplete || remaining(line.sku_id) > 0n || line.batch_id || line.quantity);
  const groups = [...new Set(visible.map(line => catalog.find(sku => sku.sku_id === line.sku_id)?.style_code || "本批商品"))];
  const unavailable = [...new Set(bindings.filter(binding => amount(binding.units) > amount(binding.received_units) && !identities.some(identity => identity.scope_id === scope.id && identity.sku_id === binding.sku_id && tracked(identity.tracked))).map(binding => binding.sku_id))];
  const newProducts = unavailable.filter(sku => !identities.some(identity => identity.scope_id === scope.id && identity.sku_id === sku) && !automaticProducts.has(sku));
  const stoppedProducts = unavailable.filter(sku => identities.some(identity => identity.scope_id === scope.id && identity.sku_id === sku));
  const previewRows = pendingImport ? incomingRows(pendingImport) : [];
  const shipped=bindings.reduce((sum,item)=>sum+amount(item.units),0n);
  const received=bindings.reduce((sum,item)=>sum+amount(item.received_units),0n);
  const complete=bindings.length>0&&bindings.every(item=>amount(item.received_units)>=amount(item.units))&&!value.lines.some(line=>line.batch_id||line.quantity!==""&&line.quantity!=="0");
  const toolLocked=operationLocked||fileGuard.dirty||workbookGuard.dirty||review;
  const postedBatches=data.batches.filter(batch=>batch.scope_id===scope.id&&batch.shipment_id===shipment.id&&batch.source_kind==="MANUAL"&&batch.status==="POSTED");
  const toolTitles={upload:"关联验收单",history:"接收记录",reports:"已上传验收单",files:"文件与记录",time:"接收时间",add:"添加收货明细"};
  return <section className={styles.editor} aria-label="统一到仓接收表">
    <div className={styles.heading}>
      <h2>{tool?toolTitles[tool]:complete?"本批已收齐":"验收明细"}</h2>
      <span>已发 {shipped.toString()} · 已接收 {received.toString()}{shipped>received?` · 待收 ${shipped-received}`:""}</span>
    </div>
    <div className={styles.toolbar}>
      <FormField label="FBA货件号">
        {references.length===1&&chosenReference&&!editingReference?<Input id="fba-receipt-reference" readOnly value={chosenReference.reference_id}/>:references.length>0&&!editingReference?<select id="fba-receipt-reference" disabled={locked||review} value={chosenReference?.id||""} onChange={event=>{const chosen=references.find(item=>item.id===event.target.value);setValue(previous=>({...previous,reference_link_id:chosen?.id||"",reference_number:chosen?.reference_id||""}));setReview(false);}}><option value="">选择货件</option>{references.map(item=><option key={item.id} value={item.id}>{item.reference_id}</option>)}</select>:<Input id="fba-receipt-reference" disabled={locked||!canWrite} value={newReference} onChange={event=>setNewReference(event.target.value)} />}
      </FormField>
      {canWrite&&(references.length===0||editingReference)?<>
        {editingReference&&<FormField label="更正原因"><Input disabled={locked} value={referenceReason} onChange={event=>setReferenceReason(event.target.value)}/></FormField>}
        <Button variant="secondary" disabled={locked||!newReference.trim()||editingReference&&!referenceReason.trim()} onClick={()=>referenceCommand.submit(`${api}/commands/references`,{scope_id:scope.id,shipment_id:shipment.id,expected_shipment_revision:shipment.revision,reference_id:newReference,reason:editingReference?referenceReason:"登记本批卖家发往FBA货件",...(editingReference&&chosenReference?{reference_link_id:chosenReference.id,expected_reference_number:chosenReference.reference_id}:{})})}>{editingReference?"保存更正":"保存货件号"}</Button>
        {editingReference&&<Button variant="quiet" disabled={locked} onClick={()=>{setEditingReference(false);setNewReference("");setReferenceReason("");}}>取消</Button>}
      </>:canWrite&&chosenReference&&!data.events.some(event=>event.reference_link_id===chosenReference.id)&&<Button variant="quiet" disabled={locked||review} onClick={()=>{setNewReference(chosenReference.reference_id);setEditingReference(true);}}>更正</Button>}
      <div className={styles.secondaryActions}>
        <Button variant="quiet" disabled={toolLocked} onClick={()=>{setError("");setTool(previous=>previous?"":"history");}}>{tool?"返回验收":"接收记录"}</Button>
        <Menu label="更多" portalContainer={windowContainer} items={[
          ...(data.batches.some(batch=>batch.scope_id===scope.id&&batch.source_kind!=="MANUAL"&&batch.status!=="ABANDONED")?[{id:"reports",label:"使用已上传验收单",disabled:toolLocked,onSelect:()=>setTool("reports")}]:[]),
          ...(complete&&canWrite?[{id:"upload",label:"关联后续验收单",disabled:toolLocked,onSelect:()=>setTool("upload")}]:complete||!canWrite?[]:[
            {id:"time",label:"补充接收时间",disabled:toolLocked,onSelect:()=>setTool("time")},
            {id:"add",label:"添加收货明细",disabled:toolLocked,onSelect:()=>setTool("add")},
          ]),
          ...(record||postedBatches.length?[{id:"files",label:"文件与导出记录",disabled:toolLocked,onSelect:()=>setTool("files")}]:[]),
          ...(onSources?[{id:"sources",label:"来源与原件",disabled:toolLocked,onSelect:onSources}]:[]),
        ]}/>
      </div>
    </div>
    {referenceCommand.feedback}
    <ShipmentDateNotice shipmentId={shipment.id} dispatchedOn={shipment.business_date} receivedOn={selected.map(line => line.batch_id ? sourceRow(line)?.business_date : value.business_date)} canWrite={canWrite} />
    {command.feedback || (error&&!complete&&!tool?<p role="alert" className={styles.inlineError}>{error}</p>:success?<p role="status" className={styles.inlineSuccess}>{success}</p>:null)}
    {needsProducts && !products.current && !products.error && <p role="status">正在读取已审核商品资料…</p>}
    {needsProducts && products.error && <StatusMessage kind="danger" title="商品资料读取未完成" action={<Button variant="secondary" onClick={()=>setProductRefresh(value=>value+1)}>重新读取</Button>}>{products.error}</StatusMessage>}
    {!!newProducts.length && products.current && <details open>
      <summary>补齐首次到货商品资料</summary>
      <p>{newProducts.map(sku => catalog.find(item => item.sku_id === sku)?.code || sku).join("、")}</p>
      <FbaIdentityExtension scope={identityScope} identities={identities.filter(identity => identity.scope_id === scope.id)} catalog={catalog} canWrite={canWrite && !command.busy && !command.unknown && !restoreProducts.busy && !restoreProducts.unknown} embedded skuIds={newProducts} onGuardChange={setIdentityGuard} saved={identitySaved} />
    </details>}
    {!!stoppedProducts.length && <StatusMessage kind="warning" title="本批有已停用商品">
      <p>{stoppedProducts.map(sku => catalog.find(item => item.sku_id === sku)?.code || sku).join("、")}</p>
      {restoreProducts.feedback}
      {canWrite && <Button variant="secondary" disabled={locked} onClick={() => restoreProducts.submit(`${api}/commands/tracking`, {
        scope_id: scope.id, expected_revision: identityScope.revision,
        sku_ids: [...new Set([...identities.filter(identity => identity.scope_id === scope.id && tracked(identity.tracked)).map(identity => identity.sku_id), ...stoppedProducts])],
        reason: "本次到货验收，恢复本批已登记商品",
      })}>恢复本批商品</Button>}
    </StatusMessage>}
    <div hidden={(!!tool&&tool!=="upload")||(complete&&tool!=="upload")} className={styles.formBody}>
    <div hidden={review} className={styles.formBody}>
    <section ref={importSection} className={styles.import} aria-label="导入收货表">
      <FbaFileUpload compact path={`${api}/uploads?scope_id=${scope.id}&shipment_id=${shipment.id}`} label="FBA收货表" disabled={locked || review} onGuardChange={uploadGuard} saved={result => {
        if("rows" in result)
          receiveReport(result);
      }} /></section>
    <div hidden={complete} className={styles.formBody}>
    <div className={styles.toolbar}>
      <Button variant="secondary" disabled={locked || !value.lines.some(line => line.selected && !line.batch_id)} onClick={() => value.lines.some(line => line.selected && !line.batch_id && amount(line.quantity) > 0n) ? setFillPrompt(true) : fillPending()}>填入待入库数</Button>
      {value.lines.some(line => remaining(line.sku_id) <= 0n) && <Button variant="quiet" onClick={() => setShowComplete(previous => !previous)}>{showComplete ? "收起已收齐商品" : "查看已收齐商品"}</Button>}
    </div>
    {!!overages.length && <StatusMessage kind="danger" title={overages.every(binding => remaining(binding.sku_id) <= 0n) ? "本批已收齐，请核对是否重复申报" : "本次接收超出待收，请核对数量"}>
      <div className={styles.toolbar}><Button variant="quiet" onClick={() => { setTool("history"); }}>查看已入库记录</Button><Button variant="secondary" disabled={locked} onClick={() => { importSection.current?.scrollIntoView({ block: "center" }); importSection.current?.querySelector<HTMLInputElement>("input[type=file]")?.focus(); }}>更换文件</Button></div>
    </StatusMessage>}
    <div className={styles.grid} tabIndex={0}>
      <table aria-label="本批可编辑接收商品">
        <thead>
          <tr>
            <th>选择</th>
            <th>商品规格</th>
            <th>已入库</th>
            <th>待入库</th>
            <th>本次收货</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {groups.map(group => <GroupRows key={group} group={group} lines={visible.filter(line => (catalog.find(sku => sku.sku_id === line.sku_id)?.style_code || "本批商品") === group)} catalog={catalog} bindings={bindings} locked={locked} remaining={remaining} invalid={invalid} overages={overages} sourceRow={sourceRow} reports={reports} shipmentId={shipment.id} update={update} />)}
          {!visible.length && <tr>
            <td colSpan={6}>本批已收齐，可查看接收记录或关联后续报告。</td>
          </tr>}
        </tbody>
        {!!selected.length && <tfoot>
          <tr>
            <td colSpan={4}>本次确认 {selected.length} 行</td>
            <td>{total.toString()}</td>
            <td>新增 {(total - linked).toString()}</td>
          </tr>
        </tfoot>}
      </table>
    </div>
    <fieldset className={styles.facts} disabled={locked} aria-label="收货信息">
      <FormField label="收货日期" required>
        <Input id="fba-receipt-date" type="date" value={value.business_date} onChange={event => { setValue(previous => ({ ...previous, business_date: event.target.value })); setReview(false); }} />
      </FormField>
      <FormField label="收货依据" required>
        <Input id="fba-receipt-reason" value={value.reason} placeholder="填写收货凭证或核对说明" onChange={event => { setValue(previous => ({ ...previous, reason: event.target.value })); setReview(false); }} />
      </FormField>
    </fieldset>
    {changes.length > 0 && <section className={styles.adjustments}>
      <h3>原表调整 {changes.length} 项</h3>{changes.map(line => <div key={line.line_id}>
        <span>{catalog.find(sku => sku.sku_id === line.sku_id)?.code || line.sku_id} · 第{line.source_row}行 {sourceRow(line)?.quantity} → {line.selected ? line.quantity || "0" : "本次不接收"}</span>
        <Input aria-label={`第${line.source_row}行调整说明`} disabled={locked} placeholder="调整或本次不接收原因" value={line.adjustment_reason || ""} onChange={event => update(line.line_id, { adjustment_reason: event.target.value })} />
      </div>)}</section>}
    </div></div>
    {review && <section ref={reviewRef} tabIndex={-1} className={styles.review} aria-label="确认接收摘要">
      <h3>{chosenReference?.reference_id} · 核对收货</h3>
      <p>本次确认 {total.toString()} 件，新增入库 {(total - linked).toString()} 件，关联已有接收 {linked.toString()} 件。</p>
      {selected.some(line => !line.batch_id) && <p>手工接收日期 {value.business_date}</p>}
      {selected.filter(line => line.batch_id).map(line => <p key={line.line_id}>{catalog.find(sku => sku.sku_id === line.sku_id)?.code || line.sku_id} · 报告接收日期 {sourceRow(line)?.business_date} · {sourceRow(line)?.raw.Disposition || "可售"}</p>)}
      <p>{value.reason}</p>{changes.map(line => <p key={line.line_id}>{catalog.find(sku => sku.sku_id === line.sku_id)?.code || line.sku_id} 原表 {sourceRow(line)?.quantity} → {line.selected ? line.quantity : "本次不接收"} {line.adjustment_reason}</p>)}<Button variant="primary" disabled={locked || dirty || !record} onClick={() => record && command.submit(`${api}/commands/unified-confirm`, { batch_id: record.id, expected_revision: record.revision })}>确认收货 {total.toString()} 件</Button>
      <Button variant="quiet" disabled={locked} onClick={() => setReview(false)}>返回修改</Button>
    </section>}
    {!review && !complete && <div className={styles.footer}>
      <Button variant="secondary" disabled={locked || !dirty} onClick={() => save()}>保存草稿</Button>
      <Button variant="primary" disabled={locked || fileGuard.dirty || workbookGuard.dirty || !selected.length} onClick={() => save(true)}>核对收货{total > 0n ? ` ${total} 件` : ""}</Button>
    </div>}
    </div>
    {!tool&&complete&&<div className={`${styles.grid} ${styles.resultGrid}`} tabIndex={0}><table aria-label="本批验收结果"><thead><tr><th>商品规格</th><th>已发</th><th>已接收</th><th>待收</th></tr></thead><tbody>{[...new Set(bindings.map(item=>item.sku_id))].map(sku=><tr key={sku}><th scope="row">{catalog.find(item=>item.sku_id===sku)?.code||sku}</th><td>{bindings.filter(item=>item.sku_id===sku).reduce((sum,item)=>sum+amount(item.units),0n).toString()}</td><td>{bindings.filter(item=>item.sku_id===sku).reduce((sum,item)=>sum+amount(item.received_units),0n).toString()}</td><td/></tr>)}</tbody></table></div>}
    <section hidden={tool!=="reports"} className={styles.toolPanel}><ExistingReportPicker data={data} scope={scope} disabled={locked} receive={receiveReport}/></section>
        <section hidden={tool!=="time"} className={styles.toolPanel}>
      <FormField label="收货时间（选填，含洛杉矶UTC偏移）"><Input disabled={locked} value={value.occurred_at || ""} placeholder="2026-11-05T10:00:00-08:00" onChange={event => { setValue(previous => ({ ...previous, occurred_at: event.target.value })); setReview(false);setError("");setSuccess(""); }} /></FormField>
    </section>
    <section hidden={tool!=="add"} className={styles.toolPanel}><div className={styles.toolbar}><select aria-label="选择收货商品" disabled={locked} value={extraSku} onChange={event => setExtraSku(event.target.value)}><option value="">选择本批商品</option>{[...new Set(bindings.map(binding => binding.sku_id))].map(id => <option key={id} value={id}>{catalog.find(sku => sku.sku_id === id)?.code || catalog.find(sku => sku.sku_id === id)?.label || id}</option>)}</select><Button variant="secondary" disabled={locked || !extraSku} onClick={() => { setValue(previous => ({ ...previous, lines: [...previous.lines, { line_id: String(Math.max(0, ...previous.lines.map(line => Number(line.line_id))) + 1), sku_id: extraSku, selected: true, quantity: "", allocations: [] }] })); setExtraSku("");setTool(""); setReview(false); }}>添加一行</Button></div></section>

    <section hidden={tool!=="files"} className={styles.toolPanel} aria-label="文件与记录">
    {record && <div>
      <div className={styles.toolbar}>
        <LinkButton to={`${api}/batches/${record.id}/original`} reloadDocument>下载首次手工记录</LinkButton>
        <LinkButton to={`${api}/batches/${record.id}/export`} reloadDocument>导出接收核对表</LinkButton>
      </div>{reports.map(report => <LinkButton key={report.id} to={`${api}/batches/${report.id}/original`} reloadDocument>{report.filename}</LinkButton>)}<FbaFileUpload path={`${api}/batches/${record.id}/reimport`} label="接收核对表回导" disabled={locked || dirty} onGuardChange={reimportGuard} saved={result => {
        if("draft_payload" in result && result.draft_payload) {
          setRecord(result);
          setValue(result.draft_payload);
          setBaseline(JSON.stringify(result.draft_payload));
          setReports(result.source_reports || []);
        }
      }} />{record.history.map((item, index) => <p key={index}>{item.created_at} · {item.actor_name} · {item.reason}</p>)}</div>}
    <div className={styles.toolbar}>{postedBatches.map(batch=><LinkButton key={batch.id} variant="quiet" to={`${api}/batches/${batch.id}/export`} reloadDocument>导出接收记录 {batch.id}</LinkButton>)}</div>
    </section>
    <section ref={receiptHistory} hidden={tool!=="history"} tabIndex={-1} className={styles.toolPanel}>
      <div className={styles.historyGrid}><table aria-label="本批已确认接收"><thead><tr><th>实际日期</th><th>FBA货件号</th><th>商品规格</th><th>接收数量</th><th>来源</th></tr></thead><tbody>{(data.events || []).filter(event => event.scope_id === scope.id && event.shipment_id === shipment.id).map(event => <tr key={event.id}><td>{event.occurred_local}</td><td>{event.reference_number || ""}</td><th scope="row">{catalog.find(sku => sku.sku_id === event.sku_id)?.code || event.sku_id}</th><td>{event.units}</td><td title={event.evidence}>{event.correction_of ? "接收更正" : event.source_kind === "MANUAL" ? "手工接收" : "报告接收"}</td></tr>)}</tbody></table></div>
      {(data.receipt_links || []).filter(link => link.shipment_id === shipment.id).map(link => <p key={`${link.batch_id}:${link.source_row}:${link.event_id}`}>{link.filename} 第{link.source_row}行 · 对应接收记录 {link.event_id}，关联 {link.units} 件</p>)}
    </section>
    <StockDetailWindow compact open={!!pendingImport} onClose={() => setPendingImport(undefined)} title="导入收货表" closeLabel="关闭导入核对" dismissDisabled={false} returnFocus={null} viewKey="receipt-import">
      {pendingImport && <>
        <p className={styles.importFilename}>{pendingImport.filename}</p>
        {previewRows.length < pendingImport.rows.length && <StatusMessage kind="warning" title={`${previewRows.length} 行可填入本批，${pendingImport.rows.length - previewRows.length} 行留待核对`}>
          其余明细保留在收货表记录。
        </StatusMessage>}
        <div className={`${styles.historyGrid} ${styles.importPreview}`}>
          <table aria-label="导入接收预览">
            <thead><tr><th>商品规格</th><th>报告数量</th><th>已填数量</th><th>替换已填</th></tr></thead>
            <tbody>{[...new Set(previewRows.map(row => row.identity!.sku_id))].map(sku => {
              const code = catalog.find(item => item.sku_id === sku)?.code || sku;
              const manual = value.lines.filter(line => !line.batch_id && line.sku_id === sku && amount(line.quantity) > 0n).reduce((sum, line) => sum + amount(line.quantity), 0n);
              const quantity = previewRows.filter(row => row.identity!.sku_id === sku).reduce((sum, row) => sum + amount(row.quantity), 0n);
              return <tr key={sku}>
                <th scope="row">{code}</th><td>{quantity.toString()}</td><td>{manual.toString()}</td>
                <td>{manual > 0n ? <input type="checkbox"
                  aria-label={`${code} 已填 ${manual} 件，报告 ${quantity} 件，采用报告替换`}
                  checked={replace.includes(sku)}
                  onChange={event => setReplace(previous => event.target.checked ? [...previous, sku] : previous.filter(id => id !== sku))}
                /> : "自动填入"}</td>
              </tr>;
            })}</tbody>
          </table>
        </div>
      </>}
      <div className={`${styles.toolbar} ${styles.importActions}`}>
        <Button variant="secondary" onClick={() => setPendingImport(undefined)}>取消</Button>
        <Button variant="primary" onClick={applyImport}>填入收货表</Button>
      </div>
    </StockDetailWindow>
    <StockDetailWindow compact open={fillPrompt} onClose={() => setFillPrompt(false)} title="覆盖已选商品数量？" closeLabel="关闭覆盖提醒" dismissDisabled={false} returnFocus={null} viewKey="receipt-fill">
      <p>将已选手工商品的本次收货数量填为当前待收。</p>
      <Button variant="secondary" onClick={() => setFillPrompt(false)}>保留原输入</Button>
      <Button onClick={fillPending}>填入待入库数</Button>
    </StockDetailWindow>
  </section>;
}
function ExistingReportPicker({ data, scope, disabled, receive }: {
  data: FbaState;
  scope: FbaScope;
  disabled: boolean;
  receive: (batch: FbaBatch) => void;
}) {
  const [id, setId] = useState("");
  const report = useLoad<FbaBatch>(`${api}/batches/${id}`, 0, !!id);
  return <div>
    <select aria-label="已上传收货表" disabled={disabled} value={id} onChange={event => setId(event.target.value)}>
      <option value="">请选择报告</option>{data.batches.filter(batch => batch.scope_id === scope.id && batch.source_kind !== "MANUAL").map(batch => <option key={batch.id} value={batch.id}>{batch.filename}</option>)}</select>
    <Button variant="secondary" disabled={disabled || !report.value || !report.current} onClick={() => report.value && receive(report.value)}>填入本表</Button>{report.error && <p role="alert">{report.error}</p>}</div>;
}
function GroupRows({ group, lines, catalog, bindings, locked, remaining, invalid, overages, sourceRow, reports, shipmentId, update }: {
  group: string;
  lines: FbaReceiptLine[];
  catalog: Sku[];
  bindings: Binding[];
  locked: boolean;
  remaining: (sku: string) => bigint;
  invalid: (line: FbaReceiptLine) => string;
  overages: Binding[];
  sourceRow: (line: FbaReceiptLine) => FbaRow | undefined;
  reports: FbaBatch[];
  shipmentId: string;
  update: (id: string, patch: Partial<FbaReceiptLine>) => void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  return <>
    <tr className={styles.group}>
      <th colSpan={6}>{group}</th>
    </tr>{lines.map(line => {
      const sku = catalog.find(item => item.sku_id === line.sku_id), row = sourceRow(line);
      const sources = bindings.filter(binding => binding.sku_id === line.sku_id);
      const error = line.selected && line.quantity && line.quantity !== "0" ? invalid(line) : "";
      const over = line.selected && overages.some(binding => binding.sku_id === line.sku_id);
      const sameSku = lines.filter(item => item.sku_id === line.sku_id && item.selected && item.quantity && item.quantity !== "0");
      const added = sameSku.some(item => invalid(item)) || over ? 0n : sameSku.reduce((sum, item) => sum + amount(item.quantity) - linkedUnits(item), 0n);
      const candidates = row?.receipt_candidates?.filter(event => event.shipment_id === shipmentId && amount(event.uncovered_units) > 0n) || [];
      const isExpanded = expanded[line.line_id] ?? (!!row && !line.overlap_checked);
      return <Fragment key={line.line_id}><tr className={error || over ? styles.invalid : undefined}>
        <td>
          <input type="checkbox" aria-label={`选择${sku?.code || sku?.label || line.sku_id}第${line.line_id}行`} disabled={locked} checked={line.selected} onChange={event => update(line.line_id, { selected: event.target.checked })} />
        </td>
        <th scope="row">
          <span>{sku?.code || sku?.label || line.sku_id}</span>{line.batch_id && <span className={styles.source}>{line.quantity !== row?.quantity ? "导入·已调整" : "报告导入"} · 第{line.source_row}行</span>}
          {(row || sources.length > 1) && <Button variant="quiet" disabled={locked} aria-expanded={isExpanded} onClick={() => setExpanded(previous => ({ ...previous, [line.line_id]: !isExpanded }))}>{row && !line.overlap_checked ? "核对已有接收" : "来源与接收明细"}</Button>}
        </th>
        <td title={`已发${sources.reduce((sum, binding) => sum + amount(binding.units), 0n)}件`}><ReceiptQuantityPreview before={sources.reduce((sum, binding) => sum + amount(binding.received_units), 0n).toString()} added={added} label={sku?.code || line.sku_id} /></td>
        <td>{remaining(line.sku_id).toString()}</td>
        <td>
          <Input id={`fba-quantity-${line.line_id}`} aria-label={`${sku?.code || sku?.label || line.sku_id}第${line.line_id}行本次收货`} inputMode="numeric" disabled={locked} value={line.quantity} aria-invalid={!!error || !!over} onChange={event => update(line.line_id, { quantity: event.target.value, ...(integer(event.target.value) ? { selected: true } : {}) })} />
        </td>
        <td>{over ? "超过待收" : error || (line.batch_id ? `新增 ${(amount(line.quantity) - linkedUnits(line)).toString()}` : remaining(line.sku_id) === 0n ? "已收齐" : line.quantity && line.selected ? "待确认" : "")}</td>
      </tr>{isExpanded && <tr className={styles.detailRow}><td colSpan={6}><div className={styles.detail}>
              {row && <>
                <p>{reports.find(report => report.id === line.batch_id)?.filename} · 第{line.source_row}行</p>
                <p>{row.raw["Date and Time"]} · {row.raw.Disposition || "可售"} · 原表 {row.quantity} 件</p>{(candidates.length > 0 || row.existing_candidates.length > 0 || row.same_file_candidates.length > 0) && <FormField label={`第${line.source_row}行接收关系`}>
                  <select disabled={locked} value={!line.overlap_checked ? "" : line.decision === "SAME" ? "SAME" : line.receipt_mode || (line.receipt_links?.length ? "LINK" : "NEW")} onChange={event => { setExpanded(previous => ({ ...previous, [line.line_id]: true })); update(line.line_id, { overlap_checked: !!event.target.value, receipt_mode: event.target.value as "NEW" | "LINK" | "SAME", decision: event.target.value === "SAME" ? "SAME" : "NEW", independent_occurrence: event.target.value === "NEW", receipt_links: event.target.value === "LINK" && candidates.length === 1 ? [{ event_id: candidates[0]!.id, units: (amount(line.quantity) < amount(candidates[0]!.uncovered_units) ? amount(line.quantity) : amount(candidates[0]!.uncovered_units)).toString() }] : [], existing_event_id: event.target.value === "SAME" && row.existing_candidates.length === 1 ? row.existing_candidates[0]!.id : undefined }); }}>
                    <option value="">请选择本次与已有记录的关系</option>
                    <option value="NEW">本次为另一次新增接收</option>{candidates.length > 0 && <option value="LINK">报告包含已手工接收数量</option>}{row.existing_candidates.length > 0 && <option value="SAME">与已核对报告为同一事件</option>}</select>
                </FormField>}
                {line.decision === "SAME" && <select aria-label={`第${line.source_row}行已有报告事件`} disabled={locked} value={line.existing_event_id || ""} onChange={event => update(line.line_id, { existing_event_id: event.target.value })}>
                  <option value="">选择原接收记录</option>{row.existing_candidates.map(event => <option key={event.id} value={event.id}>{event.event_key} · {event.units} 件</option>)}</select>}
                {candidates.length > 0 && line.overlap_checked && !line.independent_occurrence && line.decision !== "SAME" && candidates.map(event => <FormField key={event.id} label={`${event.business_date} · 接收记录${event.id} · 可关联${event.uncovered_units}件`} hint={event.evidence}>

                  <Input aria-label={`接收记录${event.id}关联件数`} disabled={locked} inputMode="numeric" value={line.receipt_links?.find(link => link.event_id === event.id)?.units || ""} onChange={input => update(line.line_id, { receipt_links: [...(line.receipt_links || []).filter(link => link.event_id !== event.id), ...(input.target.value && input.target.value !== "0" ? [{ event_id: event.id, units: input.target.value }] : [])] })} />
                </FormField>)}</>}
              {sources.length > 1 && line.decision !== "SAME" && sources.map(binding => <FormField key={binding.id} label={`来源${binding.source_line_id}本次新增件数 · 待收${(amount(binding.units) - amount(binding.received_units)).toString()}件`}>

                <Input disabled={locked} aria-label={`第${line.line_id}行来源${binding.id}件数`} inputMode="numeric" value={line.allocations.find(allocation => allocation.binding_id === binding.id)?.units || ""} onChange={event => update(line.line_id, { allocations: [...line.allocations.filter(allocation => allocation.binding_id !== binding.id), ...(event.target.value && event.target.value !== "0" ? [{ binding_id: binding.id, units: event.target.value }] : [])] })} />
              </FormField>)}
            </div></td></tr>}</Fragment>;
    })}</>;
}
