import { ProductionConfirmDialog } from "./ProductionConfirmDialog";
import { useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { writeApi } from "../../api/client";
import { Button, Dialog, FormField, Input, StatusMessage, Table } from "../../design-system";
import { GuidedOperationLayout } from "./GuidedOperationLayout";
import { ProductionOperationDialog } from "./ProductionOperationDialog";
import { useCommand, useLoad } from "./useProductionApi";
import { useProductionLeave } from "./useProductionLeave";
import type { Allocation, Document, Source } from "./types";
import type { WorkbenchStock } from "./WorkbenchFields";
import { overviewSearchParams, type OverviewGuard } from "./stockOverview";
import styles from "./Production.module.css";

type Binding = { id: string; source_line_id: string; allocation_id: string | null; carton_id: string; sku_id: string; sku_label: string; source_sku_label?: string; source_catalog_version?: string; catalog_version: string; identity_status: string; units: string; received_units: string; settled_units: string };
type Line = { binding_id: string; sku_id: string; catalog_version: string; qualified_units: string; pending_units: string; defective_units: string };
type Receipt = { id: string; shipment_id: string; shipment_revision: string; warehouse_id: string | null; owner_id: string | null; business_date: string | null; reason: string; revision: string; status: "DRAFT" | "POSTED" | "REVERSED"; upload_id?: string | null; lines: Line[] };
type Settlement = { id: string; binding_id: string; units: string; reason: string; status: "ACTIVE" | "REVERSED"; revision: string };
type DestinationState = { shipment: { id: string; revision: string; destination_id: string | null }; bindings: Binding[]; receipts: Receipt[]; settlements: Settlement[] };
type BindingInput = { carton_id: string; source_line_id: string; allocation_id: string | null; sku_id: string; units: string };
type FilePreview = { lines: Line[]; issues: { sheet: string; row: number; column: string; message: string }[]; original: { upload_id: string } };
const api = "/api/production/inventory";
const emptyBinding = (): BindingInput => ({ carton_id: "", source_line_id: "", allocation_id: null, sku_id: "", units: "" });
const zeroLine = (binding: Binding): Line => ({ binding_id: binding.id, sku_id: binding.sku_id, catalog_version: binding.catalog_version, qualified_units: "0", pending_units: "0", defective_units: "0" });
const validNumber = (value: string) => /^(0|[1-9][0-9]*)$/.test(value);

function ReceiptFrame({ embedded, close, children }: { embedded?: boolean; close: () => void; children: ReactNode }) {
  return embedded ? <section aria-label="到仓实收核验">{children}</section> : <ProductionOperationDialog title="目的仓实收" description="核对已确认出货、质量与目的仓；最后一次确认才会入库。" close={close}>{children}</ProductionOperationDialog>;
}
function ReceiptHistory({ embedded, children }: { embedded: boolean; children: ReactNode }) {
  return embedded ? <details className={styles.panel}><summary>接收与差异历史</summary>{children}</details> : <section className={styles.panel}><h3>接收与差异历史</h3>{children}</section>;
}
function ReceiptLayout({ compact, ...props }: ComponentProps<typeof GuidedOperationLayout> & { compact?: boolean }) {
  return compact ? <>{props.children}<div className={styles.actions}>{props.actions}</div><p>{props.footerNote}</p></> : <GuidedOperationLayout {...props} />;
}

export function DestinationReceiptPicker({ warehouseId, ownerId, initialShipmentId, canWrite, close, saved }: { warehouseId: string; ownerId: string; initialShipmentId?: string; canWrite: boolean; close: () => void; saved: () => void }) {
  const [shipmentId, setShipmentId] = useState(initialShipmentId || "");
  const query = new URLSearchParams({ warehouse_id: warehouseId, owner_id: ownerId });
  const source = useLoad<{ items: { id: string; system_number: string; business_number: string }[] }>(`${api}/destination-shipments?${query}`, 0, !shipmentId);
  return <>
    <Dialog open={!shipmentId} onOpenChange={open => { if (!open) close(); }} title="选择目的仓来源出货" description="当前仓库与货权已锁定；只显示明确发往本仓的已确认出货。">
      {source.error ? <StatusMessage kind="danger" title="来源读取失败">{source.error}</StatusMessage> : !source.value ? <p role="status">正在读取来源…</p> : source.value.items.length ? <FormField label="来源出货"><select value="" onChange={event => setShipmentId(event.target.value)}><option value="">请选择来源出货</option>{source.value.items.map(item => <option key={item.id} value={item.id}>{item.business_number || item.system_number}</option>)}</select></FormField> : <p>当前范围没有明确发往本仓的已确认出货。</p>}
    </Dialog>
    {shipmentId && <DestinationReceiptDialog shipmentId={shipmentId} warehouseId={warehouseId} ownerId={ownerId} canWrite={canWrite} close={close} saved={saved} />}
  </>;
}

export function DestinationReceiptDialog({ shipmentId, warehouseId, ownerId, canWrite = true, close, saved, embedded = false, onGuardChange }: { shipmentId: string; warehouseId?: string; ownerId?: string; canWrite?: boolean; close: () => void; saved: () => void; embedded?: boolean; onGuardChange?: (guard: OverviewGuard) => void }) {
  const [refresh, setRefresh] = useState(0); const [step, setStep] = useState(0);
  const [bindings, setBindings] = useState<BindingInput[]>([emptyBinding()]); const [bindingReason, setBindingReason] = useState("");
  const [scope, setScope] = useState(warehouseId && ownerId ? `${warehouseId}:${ownerId}` : "");
  const [lines, setLines] = useState<Line[]>([]); const [date, setDate] = useState(""); const [reason, setReason] = useState("");
  const [selected, setSelected] = useState(""); const [editMode, setEditMode] = useState<"draft" | "correct">("draft");
  const [uploadId, setUploadId] = useState(""); const [file, setFile] = useState<File>(); const [fileError, setFileError] = useState(""); const [issues, setIssues] = useState<FilePreview["issues"]>([]); const [fileBusy, setFileBusy] = useState(false);
  const [dirty, setDirty] = useState(false); const [closePrompt, setClosePrompt] = useState(false); const [shortage, setShortage] = useState<Record<string, string>>({}); const [shortReason, setShortReason] = useState("");
  const shipment = useLoad<Document>(`/api/production/shipments/${shipmentId}`, refresh);
  const state = useLoad<DestinationState>(`${api}/destination-state?shipment_id=${shipmentId}`, refresh);
  const stock = useLoad<WorkbenchStock>(`${api}/availability`, refresh);
  const receipt = useLoad<Receipt>(`${api}/destination-receipts/${selected}`, refresh, !!selected);
  const applied = useRef("");
  const done = () => { setRefresh(value => value + 1); saved(); };
  const bindingCommand = useCommand(() => { setDirty(false); done(); });
  const draftCommand = useCommand<Receipt>(result => { setSelected(result.id); setEditMode("draft"); applied.current = `${result.id}:${result.revision}`; setDirty(false); done(); });
  const confirmCommand = useCommand<Receipt>(result => { setSelected(result.id); setDirty(false); done(); });
  const otherCommand = useCommand(() => { setDirty(false); done(); });
  const busy = fileBusy || bindingCommand.busy || draftCommand.busy || confirmCommand.busy || otherCommand.busy;
  const unknown = bindingCommand.unknown || draftCommand.unknown || confirmCommand.unknown || otherCommand.unknown;
  const touched = dirty || !!shortReason || Object.values(shortage).some(Boolean);
  const leave = useProductionLeave(touched, busy, unknown, embedded ? overviewSearchParams : []);
  useEffect(() => { onGuardChange?.({dirty:touched,busy,unknown,blocked:leave.blocked}); }, [touched,busy,unknown,leave.blocked,onGuardChange]);
  useEffect(() => {
    if (!receipt.value || applied.current === `${receipt.value.id}:${receipt.value.revision}`) return;
    const item = receipt.value; applied.current = `${item.id}:${item.revision}`;
    setScope(item.warehouse_id && item.owner_id ? `${item.warehouse_id}:${item.owner_id}` : "");
    setLines(item.lines); setDate(item.business_date || ""); setReason(item.status === "POSTED" ? "" : item.reason); setUploadId(item.upload_id || ""); setDirty(false);
  }, [receipt.value]);
  useEffect(() => {
    if (selected || lines.length || !state.value?.bindings.length) return;
    setLines(state.value.bindings.map(zeroLine));
  }, [state.value, selected, lines.length]);
  const original = shipment.value; const view = state.value; const current = receipt.value;
  const cartonless=original?.dispatch_purpose==="WAREHOUSE_DISPATCH"&&!original.cartons?.length;
  useEffect(()=>{if(!cartonless||!view?.bindings.length||selected)return;const match=stock.value?.scopes.find(item=>item.warehouse_id===original?.destination_id&&item.owner_id===original?.owner_id);if(match&&!scope)setScope(`${match.warehouse_id}:${match.owner_id}`);setStep(1);},[cartonless,view?.bindings.length,original?.destination_id,original?.owner_id,stock.value,scope,selected]);
  const selectedScope = stock.value?.scopes.find(item => `${item.warehouse_id}:${item.owner_id}` === scope);
  const impact = new Map<string, { qualified: bigint; pending: bigint; defective: bigint }>();
  for (const line of lines) if ([line.qualified_units, line.pending_units, line.defective_units].every(validNumber)) {
    const sums = impact.get(line.sku_id) || { qualified: 0n, pending: 0n, defective: 0n };
    sums.qualified += BigInt(line.qualified_units); sums.pending += BigInt(line.pending_units); sums.defective += BigInt(line.defective_units); impact.set(line.sku_id, sums);
  }
  const choices = (original?.sources || []).flatMap<{ key: string; source: Source; allocation?: Allocation }>(source => source.id ? source.allocations.length ? source.allocations.filter(a => a.id).map(a => ({ key: `${source.id}|${a.id}`, source, allocation: a })) : [{ key: `${source.id}|`, source }] : []);
  function closeRequested() { if (busy || unknown) return; if (touched) setClosePrompt(true); else { leave.allowLeave(); close(); } }
  function mark<T>(setter: (value: T) => void, value: T) { setDirty(true); setter(value); }
  function updateBinding(index: number, update: Partial<BindingInput>) { setDirty(true); setBindings(values => values.map((item, i) => i === index ? { ...item, ...update } : item)); }
  function updateLine(index: number, update: Partial<Line>) { setDirty(true); setLines(values => values.map((item, i) => i === index ? { ...item, ...update } : item)); }
  function saveBinding() {
    if (!original) return;
    bindingCommand.submit(`${api}/destination-bindings`, { shipment_id: shipmentId, expected_shipment_revision: original.revision, reason: bindingReason, bindings });
  }
  function payload() {
    const [warehouse_id, owner_id] = scope.split(":");
    return { shipment_id: shipmentId, expected_shipment_revision: original?.revision, warehouse_id: warehouse_id || null, owner_id: owner_id || null, business_date: date, reason, lines, ...(uploadId ? { upload_id: uploadId } : {}) };
  }
  function saveDraft() {
    if (!original) return;
    const editing = current?.status === "DRAFT" && editMode === "draft";
    draftCommand.submit(editing ? `${api}/destination-receipts/${current.id}/update` : `${api}/destination-receipts`, { ...payload(), ...(editing ? { expected_revision: current.revision } : {}) });
  }
  function confirm() {
    if (!current || !original) return;
    if (editMode === "correct") confirmCommand.submit(`${api}/destination-receipts/${current.id}/correct`, { ...payload(), expected_revision: current.revision });
    else confirmCommand.submit(`${api}/destination-receipts/${current.id}/confirm`, { expected_revision: current.revision });
  }
  async function upload() {
    if (!file || busy || unknown) return;
    setFileBusy(true); setFileError(""); setIssues([]);
    try {
      const query = new URLSearchParams({ shipment_id: shipmentId, filename: file.name });
      const result = await writeApi<FilePreview>(`${api}/destination-files/preview?${query}`, { rawBody: file, headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" } });
      setIssues(result.issues); setUploadId(result.original.upload_id);
      if (!result.issues.length) { setLines(result.lines); setDirty(true); }
    } catch (error) { setFileError(error instanceof Error ? error.message : "表格读取失败。"); }
    finally { setFileBusy(false); }
  }
  const steps = ["来源与范围", "本次质量数量", "日期与依据", "核对并入库"];
  const canConfirm = !!current && (editMode === "correct" ? current.status === "POSTED" : current.status === "DRAFT" && !dirty);
  return <>
    <ReceiptFrame embedded={embedded} close={closeRequested}>
      {shipment.error || state.error || stock.error ? <StatusMessage kind="danger" title="来源读取失败">{shipment.error || state.error || stock.error}</StatusMessage> : !original || !view || !stock.value ? <p role="status">正在读取来源与库存范围…</p> : <div style={{ width: "100%", overflowY: "auto" }}>
        {bindingCommand.feedback}{draftCommand.feedback}{confirmCommand.feedback}{otherCommand.feedback}
        {!canWrite && <StatusMessage kind="info" title="当前账号只读">可以查看接收和结案历史；写入需要相应权限。</StatusMessage>}
        <fieldset disabled={!canWrite || busy || unknown} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        <ReceiptLayout compact={embedded} step={step} steps={steps} summaries={[scope || "仓库待选", `${lines.length} 条来源`, date || "日期待填", "确认前不入库"]} contextTitle="来源出货" context={<p>{original.business_number || original.system_number}</p>} title={steps[step]!} lead={[cartonless?"核对本批货物来源与目的仓。":"明确目的仓货权，并逐条核对箱、来源及订单分配；不能按SKU猜配。", "填写本次实际收下的合格、待检和次品数量。", "填写实际接收日期与依据；未收部分保留待核。", "核对本次数量与来源余量，确认后只向目的仓入账一次。"][step]!} busy={busy} unknown={unknown} go={setStep} footerNote="草稿、导入和预览不会产生入库事实。" actions={embedded ? <>{editMode === "draft"&&<Button variant="secondary" disabled={busy || unknown || !view.bindings.length} onClick={saveDraft}>保存核验草稿</Button>}<Button variant="primary" disabled={busy || unknown || !canConfirm || !view.bindings.length} onClick={confirm}>确认目的仓入库</Button></> : <><Button variant="secondary" disabled={busy || unknown} onClick={() => step ? setStep(step - 1) : closeRequested()}>{step ? "上一步" : "关闭"}</Button>{step < 3 ? <Button variant="primary" disabled={busy || unknown || (step === 0 && !view.bindings.length)} onClick={() => setStep(step + 1)}>下一步</Button> : <>{editMode === "draft" && <Button variant="secondary" disabled={busy || unknown} onClick={saveDraft}>保存草稿</Button>}<Button variant="primary" disabled={busy || unknown || !canConfirm} onClick={confirm}>确认目的仓入库</Button></>}</>}>
          {embedded&&view.bindings.length>0&&selectedScope&&<p>本次接收：{selectedScope.warehouse_name} · {view.bindings.length}条货物来源已核对</p>}
          {((embedded&&(!view.bindings.length||!selectedScope)) || (!embedded&&step === 0)) && <section className={styles.panel}>
            <p>出货 {original.business_number || original.system_number} · 修订 {original.revision} · 目的地 {original.destination || "待核"}</p>
            <FormField label="目的仓"><select disabled={!!warehouseId || busy || unknown} value={scope} onChange={event => mark(setScope, event.target.value)}><option value="">请选择已建账范围</option>{stock.value.scopes.filter(item => !original.destination_id || item.warehouse_id === original.destination_id).map(item => <option key={`${item.warehouse_id}:${item.owner_id}`} value={`${item.warehouse_id}:${item.owner_id}`}>{item.warehouse_name}</option>)}</select></FormField>
            {!original.destination_id && <StatusMessage kind="warning" title="目的仓尚无稳定身份">原文字地点不能自动成为入库仓，请先核对出货资料。</StatusMessage>}
            {!selectedScope && <p>未选择或尚未建账的范围不能确认入库。</p>}
            {!view.bindings.length ? <><h3>核对箱与来源对应</h3><p>逐行选择实际箱、出货来源及订单分配；必须完整覆盖原箱及分配数量。</p>
              {bindings.map((item, index) => <div className={styles.fields} key={index}>
                <FormField label={`第${index + 1}行箱`}><select value={item.carton_id} onChange={event => updateBinding(index, { carton_id: event.target.value })}><option value="">请选择箱</option>{original.cartons?.filter(box => box.id).map(box => <option key={box.id} value={box.id}>{box.number} · {box.id}</option>)}</select></FormField>
                <FormField label={`第${index + 1}行来源与订单`}><select value={`${item.source_line_id}|${item.allocation_id || ""}`} onChange={event => { const choice = choices.find(candidate => candidate.key === event.target.value); updateBinding(index, { source_line_id: choice?.source.id || "", allocation_id: choice?.allocation?.id || null, sku_id: choice?.source.sku_id || "" }); }}><option value="|">请选择来源</option>{choices.map(choice => <option key={choice.key} value={choice.key}>{choice.source.sku_label || choice.source.sku_id} · 来源{choice.source.id} · {choice.allocation ? `订单行${choice.allocation.order_line_id}` : "无订单分配"}</option>)}</select></FormField>
                <FormField label={`第${index + 1}行对应件数`}><Input value={item.units} inputMode="numeric" onChange={event => updateBinding(index, { units: event.target.value })} /></FormField><Button variant="quiet" onClick={() => { setDirty(true); setBindings(values => values.filter((_, i) => i !== index)); }}>移除此行</Button>
              </div>)}<Button variant="secondary" onClick={() => { setDirty(true); setBindings(values => [...values, emptyBinding()]); }}>增加对应行</Button><FormField label="对应依据"><Input value={bindingReason} onChange={event => mark(setBindingReason, event.target.value)} /></FormField><Button disabled={busy || unknown} onClick={saveBinding}>保存来源对应</Button></> : <><h3>已核对来源</h3><p>已关联 {view.bindings.length} 条出货商品明细。</p></>}
          </section>}
          {(embedded || step === 1) && <section className={styles.panel}><div className={styles.actions}><a href={`${api}/destination-files/template?shipment_id=${shipmentId}`}>下载本批标准模板</a><input aria-label="选择目的仓实收表格" type="file" accept=".xlsx" onChange={event => setFile(event.target.files?.[0])} /><Button variant="secondary" disabled={!file || busy || unknown} onClick={() => void upload()}>读取表格到明细</Button></div>{fileError && <StatusMessage kind="danger" title="表格读取失败">{fileError}</StatusMessage>}{issues.map((issue, index) => <p key={index}>{issue.sheet} 第{issue.row}行 · {issue.column}：{issue.message}</p>)}
            {lines.some(line => view.bindings.find(item => item.id === line.binding_id)?.catalog_version !== line.catalog_version) && <StatusMessage kind="warning" title="商品目录版本已变化">请核对当前商品身份后更新草稿；原出货与接收历史版本不变。{view.bindings.map(item => <p key={item.id}>来源：{item.source_sku_label || item.sku_id}（{item.source_catalog_version || "待核"}） → 当前：{item.sku_label || "待核"}（{item.catalog_version || "不可用"}）</p>)}<Button variant="secondary" disabled={view.bindings.some(item => item.identity_status !== "active" || !item.catalog_version)} onClick={() => { setLines(values => values.map(line => ({ ...line, catalog_version: view.bindings.find(item => item.id === line.binding_id)?.catalog_version || line.catalog_version }))); setDirty(true); }}>核对并使用当前商品版本</Button></StatusMessage>}
            <Table aria-label="本次实收明细"><thead><tr>{!cartonless&&<th>{embedded?"发货箱":"箱 / 来源"}</th>}<th>商品 / 余量</th><th>合格</th><th>待检</th><th>次品</th></tr></thead><tbody>{lines.map((line, index) => { const binding = view.bindings.find(item => item.id === line.binding_id); return <tr key={line.binding_id}>{!cartonless&&<td>{embedded ? original.cartons?.find(box=>String(box.id)===binding?.carton_id)?.number||"箱号待核" : <>{binding?.carton_id} · 来源{binding?.source_line_id} · 分配{binding?.allocation_id || "无"}</>}</td>}<td>{binding?.sku_label || line.sku_id} · 发出{binding?.units} / 已收{binding?.received_units} / 已结案{binding?.settled_units}</td>{(["qualified_units", "pending_units", "defective_units"] as const).map(field => <td key={field}><Input aria-label={`${line.binding_id} ${field}`} inputMode="numeric" value={line[field]} onChange={event => updateLine(index, { [field]: event.target.value })} /></td>)}</tr>; })}</tbody></Table></section>}
          {(embedded || step === 2) && <section className={styles.panel}><FormField label="实际接收日期"><Input type="date" value={date} onChange={event => mark(setDate, event.target.value)} /></FormField><FormField label="依据与差异说明"><Input value={reason} onChange={event => mark(setReason, event.target.value)} /></FormField><p>少收先保留待核；只有明确结案才单独登记，不能把未收当损失。</p></section>}
          {(embedded || step === 3) && <section className={styles.panel}><p>目的仓：{selectedScope ? selectedScope.warehouse_name : "未选择"}；日期：{date || "未填写"}；依据：{reason || "未填写"}</p>{!embedded&&<Table aria-label="入库核对"><thead><tr><th>来源</th><th>本次合格 / 待检 / 次品</th><th>原发 / 已收 / 已结案</th></tr></thead><tbody>{lines.map(line => { const binding = view.bindings.find(item => item.id === line.binding_id); return <tr key={line.binding_id}><td>{binding?.sku_label || line.sku_id} · 箱{binding?.carton_id}</td><td>{[line.qualified_units, line.pending_units, line.defective_units].every(validNumber) ? `${line.qualified_units} / ${line.pending_units} / ${line.defective_units}` : "数量待核"}</td><td>{binding?.units} / {binding?.received_units} / {binding?.settled_units}</td></tr>; })}</tbody></Table>}<h4>目的仓库存影响</h4>{editMode === "correct" && <p>更正会先检查并冲销原接收，再登记下方更正数量；实际净变化以服务器核对为准。</p>}{[...impact].map(([sku, amount]) => <p key={sku}>SKU {sku}：本次合格 {amount.qualified.toString()} 件、待检 {amount.pending.toString()} 件、次品 {amount.defective.toString()} 件；仅合格数量可能增加可发，仍受预留与冻结约束。</p>)}{editMode === "draft" && (!current || dirty) && <p>请先保存当前草稿，再核对并确认。</p>}</section>}
        </ReceiptLayout>
        </fieldset>
        <ReceiptHistory embedded={embedded}>{canWrite && <Button variant="secondary" disabled={busy || unknown || dirty} onClick={() => { setSelected(""); setEditMode("draft"); applied.current = ""; setLines(view.bindings.map(zeroLine)); setDate(""); setReason(""); setUploadId(""); setStep(1); }}>新建本次接收</Button>}{view.receipts.map(item => <p key={item.id}>接收 {item.id} · {item.status} · 修订 {item.revision} <Button variant="quiet" disabled={busy || unknown || dirty} onClick={() => { applied.current = ""; setSelected(item.id); setEditMode(item.status === "POSTED" ? "correct" : "draft"); setStep(item.status === "DRAFT" ? 1 : 3); }}>{canWrite ? item.status === "DRAFT" ? "继续草稿" : "查看 / 更正" : "查看"}</Button> <a href={`${api}/destination-files/${item.id}/export`}>导出明细</a></p>)}
          {canWrite && current?.upload_id && <p><a href={`${api}/destination-uploads/${current.upload_id}/original`}>下载本次导入原件</a></p>}
          {canWrite && current?.status === "POSTED" && <><p>更正将保留原接收及历史，并先核对当前库存与下游依赖。</p><Button variant="danger" disabled={busy || unknown || !reason.trim()} onClick={() => otherCommand.submit(`${api}/destination-receipts/${current.id}/reverse`, { expected_revision: current.revision, reason })}>按填写的依据撤销入库</Button></>}
          {canWrite && current?.status === "DRAFT" && <Button variant="quiet" disabled={busy || unknown || !reason.trim()} onClick={() => otherCommand.submit(`${api}/destination-receipts/${current.id}/abandon`, { expected_revision: current.revision, reason })}>按填写的依据放弃草稿</Button>}
          <h4>少收结案</h4>{canWrite && <FormField label="结案或撤销依据"><Input value={shortReason} onChange={event => setShortReason(event.target.value)} /></FormField>}{view.bindings.map(item => <div key={item.id}><span>{cartonless?item.sku_label:`箱${item.carton_id}`} · 发{item.units} / 已收{item.received_units} / 已结案{item.settled_units}</span>{canWrite && <><Input aria-label={`${cartonless?"货物来源":"箱来源"}${item.id}结案件数`} value={shortage[item.id] || ""} onChange={event => setShortage(values => ({ ...values, [item.id]: event.target.value }))} /><Button variant="secondary" disabled={busy || unknown || !shortReason.trim() || !validNumber(shortage[item.id] || "")} onClick={() => otherCommand.submit(`${api}/destination-settlements`, { binding_id: item.id, units: shortage[item.id], expected_shipment_revision: original.revision, reason: shortReason })}>确认少收结案</Button></>}</div>)}
          {view.settlements.map(item => <p key={item.id}>结案 {item.id} · {item.units}件 · {item.status} · {item.reason} {canWrite && item.status === "ACTIVE" && <Button variant="quiet" disabled={busy || unknown || !shortReason.trim()} onClick={() => otherCommand.submit(`${api}/destination-settlements/${item.id}/reverse`, { expected_revision: item.revision, reason: shortReason })}>撤销结案</Button>}</p>)}
        </ReceiptHistory>
      </div>}
    </ReceiptFrame>
    <ProductionConfirmDialog open={closePrompt} onOpenChange={setClosePrompt} title="还有未保存的输入" description="继续填写，或放弃当前未保存的内容。"><Button onClick={() => setClosePrompt(false)}>继续填写</Button><Button variant="danger" onClick={() => { leave.allowLeave(); setClosePrompt(false); close(); }}>放弃并关闭</Button></ProductionConfirmDialog>
    {leave.prompt}
  </>;
}
