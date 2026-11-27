import { Disclosure } from "../../design-system";
import { TableImportReview } from "./TableImportReview";
import { useTableBaseline } from "./useTableBaseline";
import { withoutTableBaseline } from "./tableImportDiff";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ReceiptBatchSelection } from "./ReceiptBatchSelection";
import { receiptOrderGroups, receiptRemaining, type ReceiptSourceLine } from "./orderProgress";
import { Link, useSearchParams } from "react-router-dom";
import { Plus, Trash2 } from "lucide-react";
import { writeApi } from "../../api/client";
import { Button, FormField, Input, LinkButton, StatusMessage, Table } from "../../design-system";
import { type Carton, type Document, type OrderLine, units } from "./types";
import { type WorkbenchStock, Fields, ReadState, WarehouseField } from "./WorkbenchFields";
import { useBusinessToday } from "./workbenchDate"; import { DestinationField } from "./DirectoryFields"; import { destinationValue } from "./directoryTypes";
import { useLoad, useCommand } from "./useProductionApi";
import { useProductionLeave } from "./useProductionLeave";
import { StockImpact, type StockImpacts } from "./StockMovementFields";
import { RevisionHistory } from "./ProductionViews";
import { WarehouseRecordSteps } from "./WarehouseRecordStatus";
import { OperationTableImport, type OperationImportPreview } from "./OperationTableImport";
import { ShipmentCartons } from "./ShipmentCartons";
import { packingError } from "./shipmentPacking";
import { GuidedOperationLayout } from "./GuidedOperationLayout";
import { ReceiptQuantityPreview } from "./ReceiptQuantityPreview";
import styles from "./OrderWorkbench.module.css";
import wizardStyles from "./QualityMovementWizard.module.css";

type Props = { order: Document; stock?: WorkbenchStock; stockError?: string; canWrite: boolean; saved: () => void; scopeLocked?: boolean; guided?: boolean; onGuidedClose?: () => void; onDraftSaved?: (id: string) => void; resumeDraftId?: string; receiptBatch?: boolean; receiptOrderReferences?: string[]; selectBatchOrders?: boolean };
const qualities = { QUALIFIED: "合格", PENDING: "待检", DEFECTIVE: "次品" } as const;
const quantity = (value: string) => /^(0|[1-9][0-9]*)$/.test(value) ? BigInt(value) : 0n;
type StockDocument = { id: string; revision: string; status: string; preview_hash?: string; impacts?: StockImpacts };
type ReceiptDraft = StockDocument & { kind: string; warehouse_id: string; owner_id: string; business_date: string; reason: string; lines: { sku_id: string; units: string; quality: string; purpose: string; location_from?: string; location_to?: string; loan_id?: string; plan_id?: string; production_allocations?: { order_line_id: string; units: string }[] }[] };

function sumKnown(values: (string | null | undefined)[]) {
  if (!values.length || values.some(value => value == null)) return undefined;
  return values.reduce((sum, value) => sum + BigInt(value!), 0n).toString();
}
function nonNegativeDifference(left?: string | null, right?: string | null) {
  if (left == null || right == null) return undefined;
  return (BigInt(left) > BigInt(right) ? BigInt(left) - BigInt(right) : 0n).toString();
}
function receiptDifference(expected?: string | null, received?: string | null) {
  if (expected == null || received == null) return "未读取";
  const value = BigInt(expected) - BigInt(received);
  return value >= 0n ? `${units(value.toString())}件` : `超额入库 ${units((-value).toString())}件`;
}
function shipmentDifference(value?: string | null) {
  if (value == null) return "未读取";
  return BigInt(value) >= 0n ? `${units(value)}件` : `已超发 ${units((-BigInt(value)).toString())}件`;
}
function afterDifference(expected: string, cumulative: string, current: string) {
  const value = BigInt(expected) - BigInt(cumulative) - quantity(current);
  return value >= 0n ? `${units(value.toString())}件` : `超出 ${units((-value).toString())}件`;
}
function unitFact(value?: string | null, unknown = "未读取") { return value == null ? unknown : `${units(value)}件`; }
function orderTotals(order: Document) {
  const lines = order.lines || [];
  const expected = order.expected_units ?? sumKnown(lines.map(line => line.expected_units));
  const produced = sumKnown(lines.map(line => line.produced_units));
  const received = order.received_units ?? sumKnown(lines.map(line => line.received_units));
  const shipped = order.actual_units ?? sumKnown(lines.map(line => line.actual_units));
  return { expected, produced, received, shipped };
}
function BusinessReference({ kind, order, receiptBatch = false, receiptOrderReferences, orderSelector }: { kind: "receipt" | "shipment"; order: Document; receiptBatch?: boolean; receiptOrderReferences?: string[]; orderSelector?: ReactNode }) {
  const totals = orderTotals(order);
  const shipmentPending = order.difference_units ?? nonNegativeDifference(totals.expected, totals.shipped);
  const receiptPlan = sumKnown((order.lines || []).map(line => line.planned_production_units ?? line.expected_units));
  const receiptAccounted = sumKnown((order.lines || []).map(line => line.received_units == null ? null : (BigInt(line.received_units) + BigInt(line.production_direct_units || "0")).toString()));
  const facts = kind === "receipt" ? [
    ["计划生产", unitFact(receiptPlan)],
    ["累计生产", unitFact(orderSelector && !order.lines?.length ? "0" : totals.produced, "未登记")],
    ["累计已入库", unitFact(totals.received)],
    ["计划待入库", orderSelector ? unitFact(order.lines?.length ? sumKnown(order.lines.map(line => receiptRemaining(line)?.toString())) : "0") : receiptDifference(receiptPlan, receiptAccounted)],
  ] : [
    ["下单数量", unitFact(totals.expected)],
    ["累计已发", unitFact(totals.shipped)],
    ["订单差额", shipmentDifference(shipmentPending)],
    ["计划目的地", order.destination || "未登记"],
  ];
  return <section className={styles.businessReference} aria-label={kind === "receipt" ? "入库业务参照" : "出货业务参照"}>
    <header><div><span>{receiptBatch ? "来源订单" : "生产工厂"}</span><h3>{receiptBatch ? receiptOrderReferences ? `${receiptOrderReferences.length} 笔订单` : "本批来源订单" : order.factory_name || "未登记"}</h3></div>{!orderSelector && <p>订单累计参照 · 未含本次</p>}</header>
    {orderSelector || receiptBatch&&<Disclosure className={styles.sourceOrders}><summary>查看完整订单编号</summary><ul>{(receiptOrderReferences||[order.business_number]).map(reference=><li key={reference} title={reference}>{reference}</li>)}</ul></Disclosure>}
    <dl>{facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    {kind === "receipt" && !orderSelector && (receiptBatch ? order.lines?.some(line => line.received_units != null && BigInt(line.received_units) >= BigInt(line.expected_units)) : totals.expected != null && totals.received != null && BigInt(totals.received) >= BigInt(totals.expected)) && <StatusMessage kind="warning" title={receiptBatch ? "所选订单含已完成或超额入库的规格，请避免重复入库" : "本单已完成入库，请核对是否为补充或超额入库"}>如确实收到额外货物，可继续填写；请在“日期与依据”说明本次入库原因，避免重复入库。</StatusMessage>}
  </section>;
}
function ReceiptProduct({line}:{line:OrderLine}) {
 const display=line as OrderLine&{receipt_product_name?:string;receipt_order_reference?:string};
 return display.receipt_product_name?<><span>{display.receipt_product_name}</span><small className={styles.receiptOrderLabel} title={display.receipt_order_reference}>{display.receipt_order_reference}</small></>:<>{line.sku_label}</>;
}
function ShipmentLineReference({ line, current }: { line: OrderLine; current: string }) {
  const difference = line.difference_units ?? nonNegativeDifference(line.expected_units, line.actual_units);
  return <div className={styles.lineReference} aria-label={`${line.sku_label}订单参照`}>
    <span><small>计划</small>{unitFact(line.expected_units)}</span>
    <span><small>已发</small>{unitFact(line.actual_units)}</span>
    <span><small>差额</small>{shipmentDifference(difference)}</span>
    <span data-change="true"><small>本次后差额</small>{afterDifference(line.expected_units, line.actual_units, current)}</span>
  </div>;
}

export function ReceiptPanel(props: Props & { compact?: boolean }) {
  const [completed, setCompleted] = useState<string>();
  const [resumeId, setResumeId] = useState(props.resumeDraftId);
  const restored = useLoad<ReceiptDraft>(`/api/production/inventory/documents/${resumeId}`, 0, !!resumeId);
  if (resumeId && !restored.value) return <ReadState error={restored.error} />;
  const initial = resumeId ? restored.value : undefined;
  if (initial && (!props.stock?.scopes.some(scope => scope.warehouse_id === initial.warehouse_id && scope.owner_id === initial.owner_id) || props.compact && (initial.warehouse_id !== props.order.receipt_warehouse_id || initial.owner_id !== props.order.receipt_owner_id))) return <StatusMessage kind="danger" title="入库草稿不属于当前仓库及货主" />;
  if (initial && (initial.kind !== "IN" || !initial.lines.length || initial.lines.some(line => line.purpose !== "PRODUCTION_RECEIPT" || !Object.hasOwn(qualities, line.quality) || line.location_from || line.location_to || line.loan_id || line.plan_id || !line.production_allocations?.length || line.production_allocations.some(allocation => !props.order.lines?.some(orderLine => orderLine.id === allocation.order_line_id && orderLine.sku_id === line.sku_id)) || line.production_allocations.reduce((sum, allocation) => sum + BigInt(allocation.units), 0n) !== BigInt(line.units)))) return <StatusMessage kind="info" title="此记录保留完整来源关系">请从<LinkButton variant="secondary" to={`/production/stock/movements/${initial.id}`}>完整入库单</LinkButton>核对和处理。</StatusMessage>;
  const postedId = completed || (initial?.status === "POSTED" ? initial.id : undefined);
  if (initial && initial.status !== "DRAFT" && !postedId) return <StatusMessage kind="info" title="本批记录已结束"><LinkButton variant="secondary" to={`/production/stock/movements/${initial.id}`}>查看完整入库单</LinkButton></StatusMessage>;
  if (!postedId && initial && !props.stock?.scopes.some(scope => scope.warehouse_id === initial.warehouse_id && scope.owner_id === initial.owner_id && scope.warehouse_status === "ACTIVE" && ["OWN", "FACTORY", "THIRD_PARTY"].includes(scope.warehouse_type || ""))) return <StatusMessage kind="warning" title="该草稿不能使用普通生产入库">FBA请使用到仓核验中的接收报告流程；草稿原仓库与内容保留。<LinkButton variant="secondary" to={`/production/stock/movements/${initial.id}`}>查看原入库草稿</LinkButton></StatusMessage>;
  return postedId ? <div className={props.guided ? styles.operationResult : undefined}>{!props.compact && !props.guided && <h2>入库</h2>}<StatusMessage kind="success" title="本批入库已确认">入库单 {postedId} 已确认，请核对本单累计实收和仓库库存。原批次不会再次提交。</StatusMessage><div className={styles.actions}><LinkButton variant="secondary" to={`/production/stock/movements/${postedId}`}>查看本批入库记录</LinkButton><Button variant="secondary" onClick={() => { setCompleted(undefined); setResumeId(undefined); props.onDraftSaved?.(""); }}>登记下一批入库</Button>{props.guided && <Button variant="primary" onClick={props.onGuidedClose}>完成</Button>}</div></div> : <ReceiptEditor key={resumeId || "new"} {...props} initial={initial} posted={id => { setCompleted(id); props.onDraftSaved?.(""); props.saved(); }} />;
}
function ReceiptEditor({ order: sourceOrder, stock, stockError, canWrite, compact = false, guided = false, onGuidedClose, onDraftSaved, posted, initial, receiptBatch = false, receiptOrderReferences: sourceReferences, selectBatchOrders = false }: Props & { compact?: boolean; posted: (id: string) => void; initial?: ReceiptDraft }) {
  const groups = selectBatchOrders ? receiptOrderGroups((sourceOrder.lines || []) as ReceiptSourceLine[]) : [];
  const [selectedOrders, setSelectedOrders] = useState<string[]>(() => groups.filter(group => initial ? initial.lines.some(line => line.production_allocations?.some(allocation => sourceOrder.lines?.some(source => source.id === allocation.order_line_id && (source as ReceiptSourceLine).order_id === group.id))) : !group.complete).map(group => group.id));
  const selectedLines = selectBatchOrders ? sourceOrder.lines?.filter(line => selectedOrders.includes((line as ReceiptSourceLine).order_id)) : sourceOrder.lines;
  const order = selectBatchOrders ? { ...sourceOrder, lines: selectedLines, revision: sourceOrder.revision.split(",").filter(part => selectedOrders.includes(part.split(":")[0]!)).join(","), expected_units: selectedLines?.length ? sumKnown(selectedLines.map(line => line.expected_units)) : "0", received_units: selectedLines?.length ? sumKnown(selectedLines.map(line => line.received_units)) : "0" } : sourceOrder;
  const receiptOrderReferences = selectBatchOrders ? groups.filter(group => selectedOrders.includes(group.id)).map(group => group.label) : sourceReferences;
  const [warehouse, setWarehouse] = useState(initial ? `${initial.warehouse_id}:${initial.owner_id}` : order.receipt_warehouse_id ? `${order.receipt_warehouse_id}:${order.receipt_owner_id || "1"}` : "");
  const today = useBusinessToday();
  const [date, setDate] = useState(initial?.business_date || today()); const [reason, setReason] = useState(withoutTableBaseline(initial?.reason)); const [amounts, setAmounts] = useState<Record<string, string>>(() => { const values: Record<string, string> = {}; for (const line of initial?.lines || []) for (const allocation of line.production_allocations || []) { const key = `${allocation.order_line_id}:${line.quality}`; values[key] = (BigInt(values[key] || "0") + BigInt(allocation.units)).toString(); } return values; });
  const audit = useTableBaseline(initial?.reason, "receipt"); const [importBusy, setImportBusy] = useState(false); const [imported, setImported] = useState<OperationImportPreview>();
  const [draft, setDraft] = useState<StockDocument | undefined>(initial); const [preview, setPreview] = useState<StockDocument>(); const [dirty, setDirty] = useState(false); const [error, setError] = useState("");
  const [step, setStep] = useState(0); const previewAfterSave = useRef(false);
  const [showQuality, setShowQuality] = useState(false);
  const [showStockReference, setShowStockReference] = useState(false);
  const command = useCommand<StockDocument>(result => {
    if (result.preview_hash) { setPreview(result); return; }
    if (result.status === "POSTED") { leave.allowLeave(); posted(result.id); return; }
    setDraft(result); setDirty(false); setPreview(undefined);
  }, () => setPreview(undefined));
  const submitReceipt = useRef(command.submit); submitReceipt.current = command.submit;
  const draftSaved = useRef(onDraftSaved); draftSaved.current = onDraftSaved;
  const leave = useProductionLeave(dirty, command.busy || importBusy, command.unknown, receiptBatch ? ["receipt_draft"] : []);
  useEffect(() => { if (draft?.id) draftSaved.current?.(draft.id); }, [draft?.id]);
  useEffect(() => {
    if (!guided || !previewAfterSave.current || !draft || command.busy || command.unknown) return;
    previewAfterSave.current = false;
    submitReceipt.current(`/api/production/inventory/documents/${draft.id}/preview`, { expected_revision: draft.revision });
  }, [guided, draft, command.busy, command.unknown]);
  function applyReceipt(result: OperationImportPreview) {
    const next: Record<string, string> = {};
    for (const row of result.rows) for (const [quality, amount] of [["QUALIFIED", row.qualified_units], ["PENDING", row.pending_units], ["DEFECTIVE", row.defective_units]]) next[`${row.order_line_id}:${quality}`] = amount || "";
    if (selectBatchOrders && (order.lines || []).some(line => receiptRemaining(line) === 0n && Object.keys(qualities).some(quality => quantity(next[`${line.id}:${quality}`] || "") > 0n))) setShowReceived(true);
    setAmounts(next); setDirty(true); setPreview(undefined); setError(""); setImported(result); audit.apply(result.table_baseline);
    setReason(value => value || `表格导入：${result.filename}`);
    if (guided) setStep(1);
  }
  const receiptScopes = stock?.scopes.filter(scope => scope.warehouse_status === "ACTIVE" && ["OWN", "FACTORY", "THIRD_PARTY"].includes(scope.warehouse_type || "")) || [];
  const receiptScope = receiptScopes.find(scope => `${scope.warehouse_id}:${scope.owner_id}` === warehouse);
  const scopeWarning = warehouse && !receiptScope ? <StatusMessage kind="warning" title="请选择可办理生产入库的普通仓库">原计划仓库尚未建账、已停用或不支持普通生产入库，请核对后选择。FBA请从出货批次开始到仓核验；当前不会自动替换仓库。</StatusMessage> : null;
  const totals = Object.keys(qualities).map(quality => (order.lines || []).reduce((sum, line) => sum + quantity(amounts[`${line.id}:${quality}`] || ""), 0n));
  function invalidAmounts() {
    return (order.lines || []).some(line => Object.keys(qualities).some(quality => { const value = amounts[`${line.id}:${quality}`] || ""; return value !== "" && !/^(0|[1-9][0-9]{0,17})$/.test(value); }));
  }
  const importToolbar = <OperationTableImport key={order.revision} inline kind="receipt" batch={receiptBatch} order={order} context={JSON.stringify({order:order.id,revision:order.revision,warehouse,draft:draft?.id,draftRevision:draft?.revision})} eligible={(order.lines || []).map(line=>line.sku_id)} locked={command.busy || command.unknown || selectBatchOrders && !selectedOrders.length} onBusy={setImportBusy} onApply={applyReceipt}/>;
  const importReview = <TableImportReview baseline={audit.baseline} rows={(order.lines || []).filter(line=>Object.keys(qualities).some(q=>quantity(amounts[`${line.id}:${q}`] || "")>0n)).map(line=>({key:line.id,label:line.sku_label,values:{"合格":amounts[`${line.id}:QUALIFIED`] || "0","待检":amounts[`${line.id}:PENDING`] || "0","次品":amounts[`${line.id}:DEFECTIVE`] || "0"}}))}/>;
  const hasQuality = (order.lines || []).some(line => ["PENDING", "DEFECTIVE"].some(quality => !!amounts[`${line.id}:${quality}`] && amounts[`${line.id}:${quality}`] !== "0"));
  const qualityExpanded = showQuality || hasQuality;
  const editableQualities = Object.entries(qualities).filter(([quality]) => qualityExpanded || quality === "QUALIFIED");
  function changeReceiptAmount(line: OrderLine, quality: string, value: string) {
    setAmounts(previous => ({ ...previous, [`${line.id}:${quality}`]: value }));
    setDirty(true);
    setPreview(undefined);
  }
  const orderSelector = selectBatchOrders ? <ReceiptBatchSelection groups={groups} selected={selectedOrders} disabled={!!draft || command.busy || command.unknown || importBusy} onChange={(id, checked) => {
    setSelectedOrders(previous => checked ? [...previous, id] : previous.filter(value => value !== id));
    setDirty(true); setPreview(undefined); setImported(undefined); setError("");
  }} /> : undefined;
  const [showReceived, setShowReceived] = useState(() => selectBatchOrders && (order.lines || []).some(line => receiptRemaining(line) === 0n && Object.keys(qualities).some(quality => quantity(amounts[`${line.id}:${quality}`] || "") > 0n)));
  const receivedLines = selectBatchOrders ? (order.lines || []).filter(line => receiptRemaining(line) === 0n) : [];
  const receiptTableRows = (lines: OrderLine[]) => lines.map(line => {
        const lineTotal = Object.keys(qualities).reduce((sum, quality) => sum + quantity(amounts[`${line.id}:${quality}`] || ""), 0n);
        const valid = Object.keys(qualities).every(quality => !amounts[`${line.id}:${quality}`] || /^(0|[1-9][0-9]{0,17})$/.test(amounts[`${line.id}:${quality}`]!));
        const overReceipt = selectBatchOrders && lineTotal > 0n && line.received_units != null && BigInt(line.received_units) + BigInt(line.production_direct_units || "0") + lineTotal > BigInt(line.expected_units);
        return <tr key={line.id} data-over-receipt={overReceipt || undefined} title={overReceipt ? "本次超收，请填写入库依据" : undefined}>
          <th scope="row"><ReceiptProduct line={line} /></th>
          <td>{units(line.planned_production_units ?? line.expected_units)}</td><td>{line.produced_units == null ? "未登记" : units(line.produced_units)}</td>
          <td><ReceiptQuantityPreview before={line.received_units} added={valid ? lineTotal : 0n} label={line.sku_label} /></td>
          {editableQualities.map(([quality, label]) => <td key={quality}><Input aria-label={`${line.sku_label}本次${label}`} inputMode="numeric" pattern="0|[1-9][0-9]*" value={amounts[`${line.id}:${quality}`] || ""} onChange={event => changeReceiptAmount(line, quality, event.target.value)} /></td>)}
          {qualityExpanded && <td>{units(lineTotal.toString())}</td>}
        </tr>;
  });
  const overReceiptNotice = selectBatchOrders && (order.lines || []).some(line => {
    const total = Object.keys(qualities).reduce((sum, quality) => sum + quantity(amounts[`${line.id}:${quality}`] || ""), 0n);
    return total > 0n && line.received_units != null && BigInt(line.received_units) + BigInt(line.production_direct_units || "0") + total > BigInt(line.expected_units);
  }) ? <StatusMessage kind="warning" title="本次有超收，请在日期与依据填写原因" /> : null;
  const receiptTable = <>
    <div className={styles.receiptProducts}>
      <div className={styles.receiptHeading}><h3>本次入库产品</h3><span>确认后生效</span></div>
      <div className={styles.receiptTools}>{(!selectBatchOrders || !!selectedOrders.length) && importToolbar}<label title="展开待检和次品数量"><input type="checkbox" aria-label="填写待检或次品" checked={qualityExpanded} disabled={hasQuality} onChange={event => setShowQuality(event.target.checked)} />待检 / 次品</label></div>
    {(!selectBatchOrders || (order.lines || []).some(line => receiptRemaining(line) !== 0n)) && <Table aria-label="本次入库产品" className={styles.receiptTable}>
      <thead><tr><th>商品规格</th><th>计划生产</th><th>已生产</th><th>累计入库</th>{editableQualities.map(([quality, label]) => <th key={quality}>{qualityExpanded ? `本次${label}` : "本次入库"}</th>)}{qualityExpanded && <th>本次合计</th>}</tr></thead>
      <tbody>{receiptTableRows((order.lines || []).filter(line => !selectBatchOrders || receiptRemaining(line) !== 0n))}</tbody>
    </Table>}
    {!!receivedLines.length && <Disclosure className={styles.receivedProducts} open={showReceived} onToggle={event => setShowReceived(event.currentTarget.open)}><summary>已收齐 · {receivedLines.length} 项</summary>{showReceived && <Table aria-label="已收齐入库产品" className={styles.receiptTable}><thead><tr><th>商品规格</th><th>计划生产</th><th>已生产</th><th>累计入库</th>{editableQualities.map(([quality, label]) => <th key={quality}>{qualityExpanded ? `本次${label}` : "本次入库"}</th>)}{qualityExpanded && <th>本次合计</th>}</tr></thead><tbody>{receiptTableRows(receivedLines)}</tbody></Table>}</Disclosure>}
    {overReceiptNotice}
    </div>
    <p className={styles.packingTotal}>本次入库 <strong>{units(totals.reduce((sum, value) => sum + value, 0n).toString())}</strong> 件{qualityExpanded && <> · 合格 {units(totals[0]!.toString())} · 待检 {units(totals[1]!.toString())} · 次品 {units(totals[2]!.toString())}</>}</p>
    <Disclosure className={styles.receiptStockReference} onToggle={event => setShowStockReference(event.currentTarget.open)}><summary>库存参照</summary>{showStockReference && <Table title="本仓当前库存"><thead><tr><th>商品规格</th><th>本仓库存</th></tr></thead><tbody>{order.lines?.map(line => <tr key={line.id}><th scope="row"><ReceiptProduct line={line} /></th><td><Availability sku={line.sku_id} line={line.id} scope={warehouse} currentOnly /></td></tr>)}</tbody></Table>}</Disclosure>
  </>;
  function saveDraft(andPreview = false) {
    if (audit.blocked) return;
    let auditedReason: string;
    try {auditedReason=audit.withNote(reason);} catch(e){setError(e instanceof Error ? e.message : "原表核对未完成");return;}
    if (!receiptScope) { setError("请选择已启用并建账的普通仓库；FBA请使用到仓核验中的接收报告流程。"); return; }
    if (invalidAmounts()) { setError("实收数量须为不超过18位的非负整数，请检查后再继续。"); return; }
    if (importBusy) { setError("表格正在读取，请等待完成后保存。"); return; }
    const lines = (order.lines || []).flatMap(line => Object.keys(qualities).filter(quality => quantity(amounts[`${line.id}:${quality}`] || "") > 0n).map(quality => ({ sku_id: line.sku_id, units: amounts[`${line.id}:${quality}`], quality, purpose: "PRODUCTION_RECEIPT", counterparty: receiptBatch ? (line as OrderLine & { receipt_factory_name?: string }).receipt_factory_name || "" : order.factory_name || "", production_allocations: [{ order_line_id: line.id, units: amounts[`${line.id}:${quality}`] }] })));
    if (!lines.length) { setError("请至少填写一个规格的本次实收数量；没有收到的规格留空或填0。"); return; }
    if (lines.length > 500) { setError("本次超过500条商品质量明细，请减少本次实收行并分批入库。"); return; }
    const [warehouse_id, owner_id] = warehouse.split(":"); setError("");
    previewAfterSave.current = andPreview;
    command.submit(`/api/production/inventory/documents${draft ? `/${draft.id}/update` : ""}`, { kind: "IN", warehouse_id, owner_id, business_date: date, reason:auditedReason, lines, ...(draft ? { expected_revision: draft.revision } : {}) });
  }
  function advanceReceipt() {
    setError("");
    if (selectBatchOrders && !selectedOrders.length) { setError("请选择本次入库订单。"); return; }
    if (!receiptScope) { setError("请选择本次实收入库仓库及货权。"); return; }
    if (step === 1 && invalidAmounts()) { setError("实收数量须为不超过18位的非负整数，请检查后再继续。"); return; }
    if (step === 1 && !(order.lines || []).some(line => Object.keys(qualities).some(quality => quantity(amounts[`${line.id}:${quality}`] || "") > 0n))) { setError("请至少填写一个规格的本次实收数量；没有收到的规格留空或填0。"); return; }
    if (step === 2 && (!date || !reason.trim())) { setError(!date ? "请选择实际入库日期。" : "请填写入库依据或备注。"); return; }
    setStep(value => Math.min(3, value + 1));
  }
  if (guided && (!canWrite || !stock?.writes_enabled || stockError)) return <StatusMessage kind="info" title={!canWrite ? "当前账号只读" : "当前环境的库存写入未就绪"}>请关闭向导，核对库存资料后再操作。</StatusMessage>;
  if (guided) {
    const total = totals.reduce((sum, value) => sum + value, 0n);
    const scope = stock?.scopes.find(item => `${item.warehouse_id}:${item.owner_id}` === warehouse);
    const steps = ["核对入库仓库", "填写实收明细", "日期与依据", "核对并确认"];
    const summaries = [receiptScope?.warehouse_name || "仓库待选", `${units(total.toString())}件`, date || "日期待填", preview && !dirty ? "可确认入库" : draft ? "草稿待核对" : "尚未保存"];
    return <form className={wizardStyles.form} onSubmit={event => event.preventDefault()}>
      <GuidedOperationLayout step={step} steps={steps} summaries={summaries} contextTitle="本次来源与范围" context={<div><strong title={order.business_number || order.system_number}>{(order.business_number || order.system_number).length > 18 ? `订单 #${order.id}` : order.business_number || order.system_number}</strong><small>{scope ? scope.warehouse_name : "仓库及货权待核"}</small></div>} title={steps[step] || steps[0]!} lead={step === 0 ? "手工填写和表格导入最终共用同一套实收明细；导入不会直接入库。" : step === 1 ? "对照订单计划、生产进度、累计已入库和本仓现有库存，再填写本次实际收到的数量。" : step === 2 ? "记录实际到仓日期和可追溯依据，生产完成通知本身不会增加库存。" : "核对本次前后数量；先保存草稿并查看服务端库存影响，确认后才正式入库。"} reference={<BusinessReference kind="receipt" order={order} receiptBatch={receiptBatch} receiptOrderReferences={receiptOrderReferences} orderSelector={orderSelector} />} busy={command.busy || importBusy} unknown={command.unknown} go={setStep} footerNote="草稿和导入都不改变库存，最终确认后才生效。" actions={<>
        <Button type="button" variant="secondary" disabled={command.busy || command.unknown || importBusy} onClick={step === 0 ? onGuidedClose : () => setStep(step === 3 ? 1 : step - 1)}>{step === 0 ? "取消" : step === 3 ? "返回修改" : "上一步"}</Button>
        {step < 3 ? <Button type="button" variant="primary" disabled={command.busy || command.unknown || importBusy || selectBatchOrders && !selectedOrders.length} onClick={advanceReceipt}>下一步</Button> : preview && !dirty ? <Button type="button" variant="primary" disabled={!receiptScope || command.busy || command.unknown} onClick={() => command.submit(`/api/production/inventory/documents/${draft!.id}/confirm`, { expected_revision: draft!.revision, preview_hash: preview.preview_hash })}>确认本次入库</Button> : <Button type="button" variant="primary" loading={command.busy} disabled={!receiptScope || command.unknown || selectBatchOrders && !selectedOrders.length} onClick={() => draft && !dirty ? command.submit(`/api/production/inventory/documents/${draft.id}/preview`, { expected_revision: draft.revision }) : saveDraft(true)}>{draft && !dirty ? "生成库存预览" : "保存草稿并预览"}</Button>}
      </>}>
        <fieldset disabled={command.busy || command.unknown || importBusy} className={wizardStyles.fields}>
          {step === 0 && <>{!compact && <WarehouseField disabled={!!draft} label="本次实收入库仓库" scopes={receiptScopes} value={warehouse} onChange={value => { setWarehouse(value); setDirty(true); setPreview(undefined); }} />}{imported && <p role="status">已读取 {imported.filename}；再次导入会替换当前明细，尚未保存或入库。</p>}</>}
          {step === 1 && receiptTable}
          {step === 2 && <div className={wizardStyles.evidence}><FormField label="实际入库日期" required><Input required type="date" value={date} onChange={event => { setDate(event.target.value); setDirty(true); setPreview(undefined); }} /></FormField><FormField label="入库依据 / 备注" required><textarea required rows={3} maxLength={2000} value={reason} placeholder="例如：工厂送货单号、本次到仓说明" onChange={event => { setReason(event.target.value); setDirty(true); setPreview(undefined); }} /></FormField></div>}
          {step === 3 && <>{overReceiptNotice}{importReview}<dl className={wizardStyles.summary}><div><dt>来源订单</dt><dd>{receiptBatch&&receiptOrderReferences?.length?`${receiptOrderReferences.length} 笔订单`:order.business_number || order.system_number}</dd></div><div><dt>入库范围</dt><dd>{scope ? scope.warehouse_name : "待核"}</dd></div><div><dt>入库日期</dt><dd>{date}</dd></div><div><dt>入库依据</dt><dd>{reason}</dd></div></dl><Table title="本次实收核对"><thead><tr><th>产品规格</th><th>操作前已入库</th><th>本次实收</th><th>预计累计</th><th>计划剩余未入库</th></tr></thead><tbody>{order.lines?.filter(line => Object.keys(qualities).some(quality => quantity(amounts[`${line.id}:${quality}`] || "") > 0n)).map(line => { const lineTotal = Object.keys(qualities).reduce((sum, quality) => sum + quantity(amounts[`${line.id}:${quality}`] || ""), 0n); const before = line.received_units; const after = before == null ? undefined : (BigInt(before) + lineTotal).toString(); return <tr key={line.id}><th scope="row"><ReceiptProduct line={line}/><small className={styles.qualityBreakdown}>合格 {units(amounts[`${line.id}:QUALIFIED`] || "0")} · 待检 {units(amounts[`${line.id}:PENDING`] || "0")} · 次品 {units(amounts[`${line.id}:DEFECTIVE`] || "0")}</small></th><td>{unitFact(before)}</td><td>{units(lineTotal.toString())}件</td><td>{unitFact(after)}</td><td>{selectBatchOrders ? unitFact(receiptRemaining({ ...line, received_units: after })?.toString()) : receiptDifference(line.planned_production_units ?? line.expected_units, after == null ? undefined : (BigInt(after) + BigInt(line.production_direct_units || "0")).toString())}</td></tr>; })}</tbody></Table>{draft && <p role="status">入库草稿 {draft.id} 已保存，尚未增加库存。{dirty ? "输入已修改，请重新保存并预览。" : "可继续核对库存影响。"}</p>}{preview && !dirty && <><StockImpact compact impacts={preview.impacts} skuName={id => order.lines?.find(line => line.sku_id === id)?.sku_label || id} warehouseName={id => stock?.scopes.find(item => item.warehouse_id === id)?.warehouse_name || id} /><StatusMessage kind="info" title="服务端预览完成，尚未入库">确认后才增加实物库存，待检和次品不增加当前可发。</StatusMessage></>}</>}
        </fieldset>
        {scopeWarning}{stockError && <ReadState error={stockError} />}{error && <StatusMessage kind="danger" title={error} />}{audit.feedback}{command.feedback}{leave.prompt}
      </GuidedOperationLayout>
    </form>;
  }
  return <>{!compact && <h2>入库</h2>}
    {canWrite && stock?.writes_enabled ? <form onChangeCapture={() => { setDirty(true); setPreview(undefined); }} onSubmit={e => { e.preventDefault(); saveDraft(); }}><fieldset disabled={command.busy || command.unknown || importBusy}><Fields>{!compact && <WarehouseField disabled={!!draft} label="本次实收入库仓库" scopes={receiptScopes} value={warehouse} onChange={setWarehouse} />}<FormField label="实际入库日期" required><Input required type="date" value={date} onChange={e => setDate(e.target.value)} /></FormField></Fields><>{receiptTable}<FormField label="入库依据 / 备注" required><Input required maxLength={2000} value={reason} placeholder="例如：工厂送货单号、本次到仓说明" onChange={e => setReason(e.target.value)} /></FormField>
    {draft && <p role="status">入库草稿 {draft.id} 已保存，尚未增加库存。{dirty ? "输入已修改，请先保存草稿修改。" : "可预览本次库存变化。"}</p>}
    {compact && draft && <WarehouseRecordSteps status={draft.status} preview={!!preview} />}
    {preview && <>{importReview}<StockImpact compact={compact} impacts={preview.impacts} skuName={id => order.lines?.find(l => l.sku_id === id)?.sku_label || id} warehouseName={id => stock.scopes.find(s => s.warehouse_id === id)?.warehouse_name || id} /><StatusMessage kind="info" title="服务端预览完成，尚未入库">确认后才增加实物库存，待检和次品不增加当前可发。</StatusMessage></>}
    <div className={styles.actions}><Button variant={compact ? "primary" : "secondary"} type="submit">{draft ? "保存草稿修改" : "保存入库草稿"}</Button>{draft && <Button variant="secondary" disabled={!receiptScope || dirty} onClick={() => command.submit(`/api/production/inventory/documents/${draft.id}/preview`, { expected_revision: draft.revision })}>预览库存影响</Button>}{draft && preview && <Button disabled={!receiptScope || dirty} onClick={() => command.submit(`/api/production/inventory/documents/${draft.id}/confirm`, { expected_revision: draft.revision, preview_hash: preview.preview_hash })}>核对并确认入库</Button>}</div></></fieldset></form> : <StatusMessage kind="info" title={!canWrite ? "当前账号只读" : "当前环境的库存写入未启用"}>可查看已登记实收；不会用生产量或预计量自动入库。</StatusMessage>}
    {imported && <p role="status">已从 {imported.filename} 填入本次实收 {units(imported.total_units)} 件；请继续核对并保存草稿，导入本身未入库。</p>}
    {scopeWarning}{stockError && <ReadState error={stockError} />}{error && <StatusMessage kind="danger" title={error} />}{audit.feedback}{command.feedback}{leave.prompt}
    <ReceiptRecords order={order} stock={stock} />{draft && <p><Link to={`/production/stock/movements/${draft.id}`}>继续处理入库草稿 {draft.id}</Link></p>}
  </>;
}

export function ReceiptRecords({ order, stock }: { order: Document; stock?: WorkbenchStock }) {
  return <Disclosure className={styles.tools}><summary>本单实收入库记录</summary>{order.receipts?.length ? <Table title="已保存的实收记录"><thead><tr><th>入库单</th><th>日期 / 仓库</th><th>产品规格</th><th>质量 / 数量</th><th>状态</th></tr></thead><tbody>{order.receipts.map((r, i) => <tr key={`${r.document_id}:${i}`}><td><Link to={`/production/stock/movements/${r.document_id}`}>入库单 {r.document_id}</Link></td><td>{r.business_date}<br />{stock?.scopes.find(s => s.warehouse_id === r.warehouse_id)?.warehouse_name || "仓库待核"}</td><td>{order.lines?.find(l => l.id === r.order_line_id)?.sku_label || "商品待核"}</td><td>{qualities[r.quality as keyof typeof qualities] || r.quality} · {units(r.units)}</td><td>{r.status === "POSTED" ? "已入库" : "已冲销"}</td></tr>)}</tbody></Table> : <p>尚无已过账的生产实收记录。草稿不计入累计入库。</p>}</Disclosure>;
}
export function ShipmentRecords({ order }: { order: Document }) {
  const [params] = useSearchParams();
  return <Disclosure className={styles.tools}><summary>本单历次出货及装箱记录</summary>{order.shipments?.length ? order.shipments.map(s => <p key={s.id}><LinkButton variant="secondary" to={s.status === "DRAFT" ? `?${new URLSearchParams({ ...Object.fromEntries(params), operation: "guided", shipment: s.id })}` : `/production/shipments/${s.id}`}>{s.business_number || s.system_number}</LinkButton> · {s.business_date} · {s.status === "CONFIRMED" ? "已发货" : s.status === "DRAFT" ? "装箱草稿" : "已作废"}</p>) : <p>尚无关联出货。</p>}</Disclosure>;
}

export function ShipmentPanel(props: Props) {
  const [params, setParams] = useSearchParams(); const id = params.get("shipment");
  const [savedDocument, setSavedDocument] = useState<Document>();
  const existing = useLoad<Document>(`/api/production/shipments/${id}`, 0, !!id);
  const current = savedDocument?.id === id ? savedDocument : existing.value;
  const rememberSavedDocument = (document: Document) => { setSavedDocument(document); const next = new URLSearchParams(params); next.set("shipment", document.id); setParams(next); };
  if (props.scopeLocked && current && (current.warehouse_id !== props.order.receipt_warehouse_id || current.owner_id !== props.order.receipt_owner_id)) return <StatusMessage kind="danger" title="发货批次不属于当前仓库及货主" />;
  if (props.guided && current && current.status !== "DRAFT") return <div className={styles.operationResult}><StatusMessage kind="info" title={current.status === "CONFIRMED" ? "本批已确认发货" : "本批已作废"}>本批记录保留在历史中。更正或查看明细请打开完整出货单。</StatusMessage><div className={styles.actions}><LinkButton variant="secondary" to={`/production/shipments/${current.id}`}>查看本批出货记录</LinkButton><Button variant="primary" onClick={props.onGuidedClose}>完成</Button></div></div>;
  if (props.guided) return id && !current ? <ReadState error={existing.error} /> : <ShipmentEditor key={`${id || "new"}:${current?.revision || ""}`} {...props} initial={current} onSavedDocument={rememberSavedDocument} />;
  return <><div className={styles.sectionHeading}><h2>出货装箱</h2>{props.canWrite && id && <Button variant="secondary" onClick={() => { const next = new URLSearchParams(params); next.delete("shipment"); setParams(next); }}>登记另一批出货</Button>}</div>
    {id && !current ? <ReadState error={existing.error} /> : <ShipmentEditor key={`${id || "new"}:${current?.revision || ""}`} {...props} initial={current} onSavedDocument={rememberSavedDocument} />}
    <ShipmentRecords order={props.order} />
  </>;
}
function ShipmentEditor({ order, stock, stockError, canWrite, saved, scopeLocked = false, guided = false, onGuidedClose, initial, onSavedDocument }: Props & { initial?: Document; onSavedDocument: (document: Document) => void }) {
  const [confirmOperation, setConfirmOperation] = useState({ busy: false, unknown: false });
  const audit = useTableBaseline(initial?.notes, "packing"); const [importBusy, setImportBusy] = useState(false); const [imported, setImported] = useState<OperationImportPreview>();
  const [warehouse, setWarehouse] = useState(initial?.warehouse_id ? `${initial.warehouse_id}:${initial.owner_id || "1"}` : order.receipt_warehouse_id ? `${order.receipt_warehouse_id}:${order.receipt_owner_id || "1"}` : "");
  const today = useBusinessToday();
  const [mode, setMode] = useState(initial?.sources?.[0]?.fulfillment_mode || "WAREHOUSE_STOCK"); const [place, setPlace] = useState(() => destinationValue(initial || { destination: order.destination || "", destination_id: order.destination_id, destination_type: order.destination_type })); const destination = place.destination; const [date, setDate] = useState(initial?.business_date || today());
  const [number, setNumber] = useState(initial?.business_number || ""); const [note, setNote] = useState(withoutTableBaseline(initial?.notes)); const [reason, setReason] = useState(""); const [sourceNote, setSourceNote] = useState(initial?.manual_source_note || "");
  const [amounts, setAmounts] = useState<Record<string, string>>(Object.fromEntries(initial?.sources?.map(s => [s.sku_id, s.actual_units]) || []));
  const [boxes, setBoxes] = useState<Carton[]>(initial?.cartons || [{ number: "", items: [] }]); const [review, setReview] = useState(false); const [error, setError] = useState(""); const [dirty, setDirty] = useState(false);
  const [step, setStep] = useState(0);
  const [sourceReview, setSourceReview] = useState<{ candidates: { id: string; system_number: string }[]; duplicate_document?: Document }>(); const [checking, setChecking] = useState(false);
  const command = useCommand(result => { leave.allowLeave(); saved(); onSavedDocument(result); }); const leave = useProductionLeave(dirty, checking || importBusy || command.busy || confirmOperation.busy, command.unknown || confirmOperation.unknown);
  // A cross-order or mixed-source legacy shipment is never flattened by this one-order form.
  const advanced = !!initial && (initial.sources?.some(s => s.allocations.some(a => !order.lines?.some(l => l.id === a.order_line_id))) || new Set(initial.sources?.map(s => s.sku_id)).size !== initial.sources?.length || new Set(initial.sources?.map(s => s.fulfillment_mode)).size > 1 || initial.sources?.some(s => s.plan_id));
  const confirmed = initial?.status === "CONFIRMED"; const readOnly = !canWrite || initial?.status === "VOID" || advanced;
  const activeLines = (order.lines || []).filter(l => !initial || initial.sources?.some(s => s.sku_id === l.sku_id) || l.tracking_state !== "CLOSED");
  const total = activeLines.reduce((sum, l) => sum + quantity(amounts[l.sku_id] || ""), 0n);
  const packed = (sku: string) => boxes.reduce((sum, box) => sum + box.items.filter(i => i.sku_id === sku).reduce((s, i) => s + quantity(i.units), 0n), 0n);
  function applyPacking(result: OperationImportPreview) {
    const next: Record<string, string> = {};
    for (const box of result.cartons) for (const item of box.items) next[item.sku_id] = (BigInt(next[item.sku_id] || "0") + BigInt(item.units)).toString();
    setAmounts(next); setBoxes(result.cartons); setDirty(true); setReview(false); setSourceReview(undefined); setError(""); setImported(result); audit.apply(result.table_baseline);
    setSourceNote(value => value || `表格导入：${result.filename}`);
    if (guided) setStep(1);
  }
  function boxAmount(index: number, sku: string, value: string) {
    setBoxes(v => v.map((box, i) => i === index ? { ...box, items: [...box.items.filter(x => x.sku_id !== sku), ...(value ? [{ sku_id: sku, units: value }] : [])] } : box));
  }
  const importReview = <TableImportReview baseline={audit.baseline} rows={activeLines.filter(line=>quantity(amounts[line.sku_id] || "")>0n).map(line=>({key:line.sku_id,label:line.sku_label,values:{"出货数量":amounts[line.sku_id] || "0","装箱分配":boxes.flatMap(box=>box.items.filter(item=>item.sku_id===line.sku_id && quantity(item.units)>0n).map(item=>`${box.number}：${item.units}`)).sort().join("；")}}))}/>;
  async function save(saveMode: string) {
    if (audit.blocked) return;
    let auditedNote: string;
    try {auditedNote=audit.withNote(note);} catch(e){setError(e instanceof Error ? e.message : "原表核对未完成");return;}
    if (importBusy) { setError("表格正在读取，请等待完成后保存。"); return; }
    const sources = activeLines.filter(l => quantity(amounts[l.sku_id] || "") > 0n).map(l => ({ ...(initial?.sources?.find(s => s.sku_id === l.sku_id) || {}), sku_id: l.sku_id, actual_units: amounts[l.sku_id], fulfillment_mode: mode, allocations: [{ order_line_id: l.id, units: amounts[l.sku_id] }] }));
    const cartons = boxes.filter(b => b.number.trim() || b.items.some(i => quantity(i.units) > 0n)).map(b => ({ ...b, number: b.number.trim(), items: b.items.filter(i => quantity(i.units) > 0n) }));
    if (!sources.length) { setError("请填写至少一个商品的本次出货数量。"); return; }
    if (saveMode === "confirm" && activeLines.some(l => packed(l.sku_id) !== quantity(amounts[l.sku_id] || ""))) { setError("每个产品的装箱合计须等于本次出货；请核对未装箱数量。"); return; }
    const [warehouse_id, owner_id] = warehouse.split(":");
    const body = { save_mode: saveMode, business_number: number, business_date: date, ...place, sources, cartons, notes: auditedNote, dispatch_purpose: "OUTWARD_ORDER", manual_source_note: sourceNote, ...(mode === "WAREHOUSE_STOCK" ? { warehouse_id, owner_id } : {}), ...(initial ? { expected_revision: initial.revision, reason, ...(initial.sources?.some(s => s.fulfillment_mode === "WAREHOUSE_STOCK") && mode === "PRODUCTION_DIRECT" ? { warehouse_id: initial.warehouse_id, owner_id: initial.owner_id } : {}) } : {}), _order_revisions: { [order.id]: order.revision }, overage_reason: reason };
    setError("");
    if (!initial && saveMode === "confirm" && !sourceReview) { setChecking(true); try { const result = await writeApi<{ candidates: { id: string; system_number: string }[]; duplicate_document?: Document }>("/api/production/sources/shipments/check", { body, idempotent: false }); if (result.candidates.length || result.duplicate_document) { setSourceReview(result); return; } } catch (e) { setError(e instanceof Error ? e.message : "来源核对失败"); return; } finally { setChecking(false); } }
    if (saveMode === "confirm" && !review) { setReview(true); return; }
    command.submit(initial ? `/api/production/shipments/${initial.id}${confirmed ? "/correct" : ""}` : "/api/production/shipments", body, initial && !confirmed ? "PUT" : "POST");
  }
  function advanceShipment() {
    setError("");
    if (step === 0 && (!date || !destination.trim() || (mode === "WAREHOUSE_STOCK" && !warehouse))) { setError(!date ? "请选择实际发运日期。" : !destination.trim() ? "请选择或填写实际目的地。" : "请核对发货仓库及货权。"); return; }
    if (step === 1 && !activeLines.some(line => quantity(amounts[line.sku_id] || "") > 0n)) { setError("请填写至少一个商品的本次出货数量。"); return; }
    if (step === 2) {
      const issue = packingError(activeLines.map(line => ({ sku_id: line.sku_id, label: line.sku_label, units: amounts[line.sku_id] || "0" })), boxes);
      if (issue) { setError(issue); return; }
    }
    setStep(value => Math.min(3, value + 1));
  }
  if (guided) {
    const steps = ["来源与目的地", "填写出货数量", "完成装箱", "核对并发货"];
    const packedTotal = activeLines.reduce((sum, line) => sum + packed(line.sku_id), 0n);
    const summaries = [destination || "目的地待选", `${units(total.toString())}件`, `${units(packedTotal.toString())}件 · ${boxes.filter(box => box.number.trim() || box.items.some(item => quantity(item.units) > 0n)).length}箱`, review ? "等待最终确认" : initial?.status === "DRAFT" ? "草稿待确认" : "尚未发货"];
    const sourceScope = mode === "WAREHOUSE_STOCK" ? stock?.scopes.find(item => `${item.warehouse_id}:${item.owner_id}` === warehouse) : undefined;
    return <form className={wizardStyles.form} onSubmit={event => event.preventDefault()}>
      <GuidedOperationLayout step={step} steps={steps} summaries={summaries} contextTitle="本次来源生产单" context={<div><strong>{order.business_number || order.system_number}</strong><small>{mode === "WAREHOUSE_STOCK" ? sourceScope ? sourceScope.warehouse_name : "仓库及货权待核" : "生产完成后直接出货"}</small></div>} title={steps[step] || steps[0]!} lead={step === 0 ? "先对照生产单累计进度，再确认从哪里发、发往哪里和实际交接日期；目的地不是签收状态。" : step === 1 ? "对照累计已发、订单差额和本仓当前可发量，再填写本次出货；导入不会保存或扣库存。" : step === 2 ? "每个商品的装箱合计必须等于本次出货数量，箱号用于后续运输和签收追踪。" : "核对操作前、本次和操作后数量；确认实际交接后才扣减仓库库存并计入订单已发。"} reference={<BusinessReference kind="shipment" order={order} />} busy={checking || importBusy || command.busy || command.unknown || confirmOperation.busy} unknown={command.unknown || confirmOperation.unknown} go={setStep} footerNote="装箱草稿不扣库存，确认实际发货后才生效。" actions={<>
        <Button type="button" variant="secondary" disabled={checking || importBusy || command.busy || command.unknown || confirmOperation.busy || confirmOperation.unknown} onClick={step === 0 ? onGuidedClose : () => { setReview(false); setSourceReview(undefined); setStep(step - 1); }}>{step === 0 ? "取消" : "上一步"}</Button>
        {step > 0 && step < 3 && !confirmed && <Button type="button" variant="secondary" disabled={readOnly || checking || importBusy || command.busy || command.unknown || confirmOperation.busy || confirmOperation.unknown} onClick={() => void save("draft")}>{initial ? "保存草稿修改" : "保存装箱草稿"}</Button>}
        {step < 3 ? <Button type="button" variant="primary" disabled={readOnly || checking || importBusy || command.busy || command.unknown || confirmOperation.busy || confirmOperation.unknown} onClick={advanceShipment}>下一步</Button> : <>{!initial && <Button type="button" variant="secondary" disabled={readOnly || checking || importBusy || command.busy || command.unknown} onClick={() => void save("draft")}>保存装箱草稿</Button>}<Button type="button" variant="primary" disabled={readOnly || checking || importBusy || command.busy || command.unknown || confirmOperation.busy || confirmOperation.unknown || !!sourceReview?.duplicate_document} onClick={() => void save(initial?.status === "DRAFT" ? "draft" : "confirm")}>{initial?.status === "DRAFT" ? "保存草稿修改" : review ? confirmed ? "确认保存出货更正" : "确认已实际发货" : confirmed ? "核对出货更正" : "核对并确认出货"}</Button></>}
      </>}>
        <fieldset disabled={readOnly || checking || importBusy || command.busy || command.unknown || confirmOperation.busy || confirmOperation.unknown} className={wizardStyles.fields}>
          {advanced && <StatusMessage kind="info" title="此记录包含跨订单、混合来源或关联安排">为保留原关系，请从<Link to={`/production/shipments/${initial?.id}`}>完整出货详情</Link>核对及更正。</StatusMessage>}
          {step === 0 && <><div className={wizardStyles.evidence}><FormField label="货物来源" required><select disabled={scopeLocked} value={mode} onChange={event => { setMode(event.target.value as typeof mode); setDirty(true); setReview(false); setSourceReview(undefined); }}><option value="WAREHOUSE_STOCK">仓库库存出货</option>{!scopeLocked && <option value="PRODUCTION_DIRECT">生产完成后直接出货（不经仓库）</option>}</select></FormField>{mode === "WAREHOUSE_STOCK" && <WarehouseField disabled={scopeLocked} label="发货仓库" scopes={stock?.scopes || []} value={warehouse} onChange={value => { setWarehouse(value); setDirty(true); setReview(false); setSourceReview(undefined); }} />}<div className={styles.shipmentDestination}><DestinationField required value={place} onChange={value => { setPlace(value); setDirty(true); setReview(false); setSourceReview(undefined); }} /></div><FormField label="实际发运日期" required><Input required type="date" value={date} onChange={event => { setDate(event.target.value); setDirty(true); setReview(false); setSourceReview(undefined); }} /></FormField></div></>}
          {step === 1 && <><OperationTableImport inline kind="packing" order={order} context={JSON.stringify({ order: order.id, revision: order.revision, warehouse, mode, shipment: initial?.id, shipmentRevision: initial?.revision, eligible: activeLines.map(line => line.sku_id) })} eligible={activeLines.map(line => line.sku_id)} locked={readOnly || command.busy || command.unknown || confirmOperation.busy || confirmOperation.unknown} onBusy={setImportBusy} onApply={applyPacking} /><Table title="本次出货产品"><thead><tr><th>产品规格</th><th>订单参照</th><th>本仓库存参照</th><th>本次出货</th></tr></thead><tbody>{activeLines.map(line => <tr key={line.id}><th scope="row">{line.sku_label}</th><td><ShipmentLineReference line={line} current={amounts[line.sku_id] || "0"} /></td><td>{mode === "WAREHOUSE_STOCK" ? <Availability sku={line.sku_id} line={line.id} scope={warehouse} detailed direction="out" onHandChange={amounts[line.sku_id] || "0"} dispatchChange={amounts[line.sku_id] || "0"} /> : "生产直发，不计仓库库存"}</td><td><Input aria-label={`${line.sku_label}本次出货`} inputMode="numeric" pattern="0|[1-9][0-9]*" value={amounts[line.sku_id] || ""} onChange={event => { setAmounts(value => ({ ...value, [line.sku_id]: event.target.value })); setDirty(true); setReview(false); setSourceReview(undefined); }} /></td></tr>)}</tbody></Table><p className={styles.packingTotal}>本次出货 <strong>{units(total.toString())}</strong> 件。{imported ? ` 已从${imported.filename}填入，可继续手工修改。` : ""}</p></>}
          {step === 2 && <ShipmentCartons products={activeLines.map(line => ({ sku_id: line.sku_id, label: line.sku_label, units: amounts[line.sku_id] || "0" }))} boxes={boxes} change={value => { setBoxes(value); setDirty(true); setReview(false); }} />}
          {step === 3 && <>{importReview}<dl className={wizardStyles.summary}><div><dt>来源订单</dt><dd>{order.business_number || order.system_number}</dd></div><div><dt>发货范围</dt><dd>{mode === "WAREHOUSE_STOCK" ? sourceScope ? sourceScope.warehouse_name : "待核" : "生产直发"}</dd></div><div><dt>目的地</dt><dd>{destination}</dd></div><div><dt>发运日期</dt><dd>{date}</dd></div></dl><Table title="本次出货与装箱核对"><thead><tr><th>产品规格</th><th>操作前已发</th><th>本次出货</th><th>预计累计</th><th>操作后差额</th><th>装箱结果</th></tr></thead><tbody>{activeLines.filter(line => quantity(amounts[line.sku_id] || "") > 0n).map(line => { const current = quantity(amounts[line.sku_id] || ""); return <tr key={line.id}><th scope="row">{line.sku_label}</th><td>{unitFact(line.actual_units)}</td><td>{units(current.toString())}件</td><td>{units((BigInt(line.actual_units) + current).toString())}件</td><td>{afterDifference(line.expected_units, line.actual_units, current.toString())}</td><td>{units(packed(line.sku_id).toString())}件 · {packed(line.sku_id) === current ? "一致" : "待补齐"}</td></tr>; })}</tbody></Table><div className={wizardStyles.evidence}><FormField label="业务出货单号（可选）"><Input maxLength={120} value={number} onChange={event => { setNumber(event.target.value); setDirty(true); setReview(false); }} /></FormField><FormField label="人工来源及区别说明"><Input maxLength={2000} value={sourceNote} onChange={event => { setSourceNote(event.target.value); setDirty(true); setReview(false); setSourceReview(undefined); }} /></FormField><FormField label={confirmed ? "更正原因 / 超发说明" : "超发说明（累计超过下单量时必填）"} required={confirmed}><Input required={confirmed} maxLength={2000} value={reason} onChange={event => { setReason(event.target.value); setDirty(true); setReview(false); }} /></FormField><FormField label="出货备注（可选）"><Input maxLength={2000} value={note} onChange={event => { setNote(event.target.value); setDirty(true); setReview(false); }} /></FormField></div>{sourceReview && <StatusMessage kind="warning" title="请核对来源，避免重复发货">{sourceReview.duplicate_document ? <Link to={`/production/shipments/${sourceReview.duplicate_document.id}`}>打开已有出货</Link> : <>{sourceReview.candidates.map(candidate => <p key={candidate.id}><Link to={`/production/shipments/${candidate.id}`}>{candidate.system_number}</Link></p>)}<p>确为另一批发运时，填写区别说明后继续。</p></>}</StatusMessage>}{review && <StatusMessage kind="warning" title={confirmed ? "请确认本次出货更正" : "请确认货物已实际交接发运"}>目的地：{destination}；本次 {units(total.toString())} 件。{mode === "WAREHOUSE_STOCK" ? "确认时服务端重新核对库存、自有预留及订单修订。" : "生产直发不增加或扣减仓库库存。"}</StatusMessage>}{initial?.status === "DRAFT" && canWrite && !advanced && <DraftShipmentConfirm document={initial} dirty={dirty} onStateChange={setConfirmOperation} saved={result => { leave.allowLeave(); onSavedDocument(result); saved(); }} compact />}</>}
        </fieldset>
        {stockError && <ReadState error={stockError} />}{error && <StatusMessage kind="danger" title={error} />}{audit.feedback}{command.feedback}{leave.prompt}
      </GuidedOperationLayout>
    </form>;
  }
  return <><p className={styles.muted}>{initial ? `出货单 ${initial.business_number || initial.system_number} · 修订 ${initial.revision}` : "每次实际发运为独立一批。"} 保存装箱草稿不扣库存，确认实际发货才计入订单已出货。</p>
    {advanced && <StatusMessage kind="info" title="此记录包含跨订单、混合来源或关联安排">为保留原关系，请从<Link to={`/production/shipments/${initial.id}`}>完整出货详情</Link>核对及更正。</StatusMessage>}
    <form onChangeCapture={() => { setDirty(true); setReview(false); setSourceReview(undefined); }} onSubmit={e => { e.preventDefault(); void save(initial?.status === "DRAFT" ? "draft" : "confirm"); }}><fieldset disabled={readOnly || checking || importBusy || command.busy || command.unknown || confirmOperation.busy || confirmOperation.unknown}>
      
      <Fields><FormField label="货物来源" required><select disabled={scopeLocked} value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="WAREHOUSE_STOCK">仓库库存出货</option>{!scopeLocked && <option value="PRODUCTION_DIRECT">生产完成后直接出货（不经仓库）</option>}</select></FormField>{mode === "WAREHOUSE_STOCK" && <WarehouseField disabled={scopeLocked} label="发货仓库" scopes={stock?.scopes || []} value={warehouse} onChange={setWarehouse} />}<FormField label="实际发运日期" required><Input required type="date" value={date} onChange={e => setDate(e.target.value)} /></FormField></Fields>
      <div className={styles.shipmentDestination}><DestinationField required value={place} onChange={v => { setPlace(v); setDirty(true); setReview(false); setSourceReview(undefined); }} /></div>
      <OperationTableImport inline kind="packing" order={order} context={JSON.stringify({ order: order.id, revision: order.revision, warehouse, mode, shipment: initial?.id, shipmentRevision: initial?.revision, eligible: activeLines.map(line => line.sku_id) })} eligible={activeLines.map(line => line.sku_id)} locked={readOnly || command.busy || command.unknown || confirmOperation.busy || confirmOperation.unknown} onBusy={setImportBusy} onApply={applyPacking} /><><Table title="本次出货产品"><thead><tr><th>产品规格</th><th>本次当前可发</th><th>本次出货</th><th>已装箱</th><th>未装箱</th></tr></thead><tbody>{activeLines.map(l => <tr key={l.id}><th scope="row">{l.sku_label}</th><td>{mode === "WAREHOUSE_STOCK" ? <Availability sku={l.sku_id} line={l.id} scope={warehouse} /> : "生产直发，不计仓库库存"}</td><td><Input aria-label={`${l.sku_label}本次出货`} inputMode="numeric" pattern="0|[1-9][0-9]*" value={amounts[l.sku_id] || ""} onChange={e => setAmounts(v => ({ ...v, [l.sku_id]: e.target.value }))} /></td><td>{units(packed(l.sku_id).toString())}</td><td className={packed(l.sku_id) > quantity(amounts[l.sku_id] || "") ? styles.danger : undefined}>{units((quantity(amounts[l.sku_id] || "") - packed(l.sku_id)).toString())}</td></tr>)}</tbody></Table>
      <Table title="装箱明细"><thead><tr><th>箱号</th>{activeLines.map(l => <th key={l.id}>{l.sku_label}</th>)}<th>箱内合计</th><th>操作</th></tr></thead><tbody>{boxes.map((box, index) => <tr key={index}><td><Input aria-label={`第${index + 1}箱箱号`} maxLength={80} placeholder="例如：A001" value={box.number} onChange={e => setBoxes(v => v.map((b, i) => i === index ? { ...b, number: e.target.value } : b))} /></td>{activeLines.map(l => <td key={l.id}><Input aria-label={`第${index + 1}箱${l.sku_label}装箱数`} inputMode="numeric" pattern="0|[1-9][0-9]*" value={box.items.find(i => i.sku_id === l.sku_id)?.units || ""} onChange={e => boxAmount(index, l.sku_id, e.target.value)} /></td>)}<td>{units(box.items.reduce((sum, i) => sum + quantity(i.units), 0n).toString())}</td><td><Button variant="quiet" aria-label={`移除第${index + 1}箱`} icon={<Trash2 />} onClick={() => { setBoxes(v => v.filter((_, i) => i !== index)); setDirty(true); setReview(false); }}>移除</Button></td></tr>)}</tbody></Table><Button variant="secondary" disabled={boxes.length >= 500} icon={<Plus />} onClick={() => { setBoxes(v => [...v, { number: "", items: [] }]); setDirty(true); setReview(false); }}>添加箱</Button></>
      <Fields><FormField label="业务出货单号（可选）"><Input maxLength={120} value={number} onChange={e => setNumber(e.target.value)} /></FormField><FormField label="人工来源及区别说明"><Input maxLength={2000} value={sourceNote} onChange={e => setSourceNote(e.target.value)} /></FormField><FormField label={confirmed ? "更正原因 / 超发说明" : "超发说明（累计超过下单量时必填）"} required={confirmed}><Input required={confirmed} maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></FormField></Fields><FormField label="出货备注（可选）"><Input maxLength={2000} value={note} onChange={e => setNote(e.target.value)} /></FormField>
      <p className={styles.packingTotal}>本次 <strong>{units(total.toString())}</strong> 件 · 已装箱 <strong>{units(activeLines.reduce((sum, l) => sum + packed(l.sku_id), 0n).toString())}</strong> 件 · <strong>{boxes.length}</strong> 箱</p>
      {sourceReview && <StatusMessage kind="warning" title="请核对来源，避免重复发货">{sourceReview.duplicate_document ? <Link to={`/production/shipments/${sourceReview.duplicate_document.id}`}>打开已有出货</Link> : <>{sourceReview.candidates.map(c => <p key={c.id}><Link to={`/production/shipments/${c.id}`}>{c.system_number}</Link></p>)}<p>确为另一批发运时，填写区别说明后继续。</p></>}</StatusMessage>}
      {review && importReview}{review && <StatusMessage kind="warning" title={confirmed ? "请确认本次出货更正" : "请确认货物已实际交接发运"}>目的地：{destination}；本次 {units(total.toString())} 件。{mode === "WAREHOUSE_STOCK" ? "确认时服务端重新核对库存、自有预留及订单修订；当前预览不代表预留。" : "此为生产直发事实，不增加或扣减仓库库存。"}</StatusMessage>}
      {!readOnly && <div className={styles.actions}>{!initial && <Button variant="secondary" onClick={e => { if (e.currentTarget.form?.reportValidity()) void save("draft"); }}>{initial ? "保存装箱草稿修改" : "保存装箱草稿"}</Button>}<Button variant="primary" type="submit" disabled={!!sourceReview?.duplicate_document}>{initial && !confirmed ? "保存装箱草稿修改" : review ? confirmed ? "确认保存出货更正" : "确认已实际发货" : confirmed ? "核对出货更正" : "核对并确认出货"}</Button></div>}
    </fieldset></form>
    {imported && <p role="status">已从 {imported.filename} 填入本批 {units(imported.total_units)} 件、{imported.box_count} 箱；导入本身未保存或发货。</p>}
    {initial?.status === "DRAFT" && canWrite && !advanced && <DraftShipmentConfirm document={initial} dirty={dirty} onStateChange={setConfirmOperation} saved={() => { leave.allowLeave(); saved(); }} />}
    {initial?.history?.length ? <Disclosure className={styles.tools}><summary>本批出货修订记录</summary><RevisionHistory history={initial.history} /></Disclosure> : null}
    {stockError && <ReadState error={stockError} />}{error && <StatusMessage kind="danger" title={error} />}{audit.feedback}{command.feedback}{leave.prompt}
  </>;
}
function Availability({ sku, line, scope, detailed = false, currentOnly = false, direction = "out", onHandChange = "0", dispatchChange = "0" }: { sku: string; line: string; scope: string; detailed?: boolean; currentOnly?: boolean; direction?: "in" | "out"; onHandChange?: string; dispatchChange?: string }) {
  const [refresh, setRefresh] = useState(0); const [warehouse, owner] = scope.split(":");
  const state = useLoad<{ state: string; on_hand_units?: string | null; dispatch_allowed_units: string | null; own_reserved_units?: string; missing?: string }>(`/api/production/inventory/availability?warehouse_id=${warehouse}&owner_id=${owner}&sku_id=${sku}&order_line_ids=${line}`, refresh, !!scope);
  if (currentOnly) return <span>{!scope ? "请先选择仓库" : state.error ? "库存读取失败，请重试" : !state.value ? "读取中" : state.value.on_hand_units == null ? "待核" : units(state.value.on_hand_units)}</span>;
  if (!detailed) return <div className={styles.availability}>{!scope ? "请先选择仓库" : state.value ? state.value.state === "ready" && state.value.dispatch_allowed_units != null ? <><strong>{units(state.value.dispatch_allowed_units)} 件</strong>{state.value.own_reserved_units && state.value.own_reserved_units !== "0" && <small>含本单预留 {units(state.value.own_reserved_units)}</small>}</> : "当前不可发 / 待核" : state.error || "读取中…"}{scope && <Button variant="quiet" onClick={() => setRefresh(r => r + 1)}>刷新</Button>}</div>;
  const after = (current: string, change: string) => direction === "in" ? BigInt(current) + quantity(change) : BigInt(current) - quantity(change);
  return <div className={styles.inventoryReference} aria-label="本仓库存参照">
    {!scope ? <span>请先选择仓库</span> : state.error ? <span className={styles.inventoryError}>库存读取失败，未显示为0。{state.error}</span> : !state.value ? <span>库存读取中，尚未取得数量…</span> : state.value.state !== "ready" || state.value.dispatch_allowed_units == null ? <span>库存未就绪：{state.value.missing || "当前不可发，数量待核"}</span> : <>
      <span><small>实际在库</small><strong>{unitFact(state.value.on_hand_units)}</strong>{state.value.on_hand_units != null && <em>本次后 {unitFact(after(state.value.on_hand_units, onHandChange).toString())}</em>}</span>
      <span><small>当前可发</small><strong>{unitFact(state.value.dispatch_allowed_units)}</strong><em>{after(state.value.dispatch_allowed_units, dispatchChange) >= 0n ? `本次后可发 ${unitFact(after(state.value.dispatch_allowed_units, dispatchChange).toString())}` : `预计缺口 ${unitFact((-after(state.value.dispatch_allowed_units, dispatchChange)).toString())}`}</em></span>
      {state.value.own_reserved_units && state.value.own_reserved_units !== "0" && <span><small>本单预留</small><strong>{unitFact(state.value.own_reserved_units)}</strong></span>}
    </>}
    {scope && <Button type="button" variant="quiet" onClick={() => setRefresh(value => value + 1)}>刷新库存</Button>}
  </div>;
}
export function DraftShipmentConfirm({ document, dirty, saved, onStateChange, onReviewChange, compact = false }: { document: Document; dirty: boolean; saved: (result: Document) => void; onStateChange?: (s: { busy: boolean; unknown: boolean }) => void; onReviewChange?: (review: boolean) => void; compact?: boolean }) {
  const [review, setReview] = useState(false); const command = useCommand(result => saved(result));
  useEffect(() => { onStateChange?.({ busy: command.busy, unknown: command.unknown }); }, [command.busy, command.unknown, onStateChange]);
  useEffect(() => { onReviewChange?.(review); }, [review, onReviewChange]);
  return <section className={styles.confirmDraft}>{!compact && <p>此出货仍是草稿，尚未扣库存或计入订单已发。{dirty ? "请先保存以上修改。" : "核对本批目的地及装箱明细后再确认实际发货。"}</p>}{review && !dirty && <StatusMessage kind="warning" title="请确认这批货已实际交接">确认将按服务端当前可发量校验，并保存实际发货事实。</StatusMessage>}<Button variant="primary" disabled={dirty || command.busy || command.unknown} onClick={() => { if (!review) setReview(true); else command.submit(`/api/production/shipments/${document.id}/confirm`, { expected_revision: document.revision }); }}>{review && !dirty ? "确认本草稿已实际发货" : "核对并确认本出货草稿"}</Button>{command.feedback}</section>;
}
