import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiRequestError, requestApi, writeApi } from "../../api/client";
import { RequestGate } from "../../api/requestGate";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { LinkButton, Button, Dialog, FormField, Input, PageHeader, StatusMessage, Table  } from "../../design-system";
import { CatalogReferencePanel, CatalogCandidateCell, type CatalogReferenceResult } from "./CatalogReference";
import { units } from "./types";
import { useProductionLeave } from "./useProductionLeave";
import { DraftQuantityChange, SourceDraftReview, type DraftReviewItem } from "./SourceDraftReview";
import styles from "./Production.module.css";

type DraftLine = { source_row: number; actual_units: string; order_reference_note: string; review_note: string };
type PackingInput = { source_digest: string; revision: number; business_number: string; business_date: string; notes: string; lines: DraftLine[] };
type SavedPacking = PackingInput & { last_save_key: string; updated_at: string; draft_units: string; dispatch_status: "ASSUMED_DISPATCHED"; confirmation_enabled: false };
type PackingSource = {
  catalog_reference?: CatalogReferenceResult;
  sample_id: string; filename: string; source_digest: string; box1_units: string; box2_units: string; source_units: string;
  filename_date_hint: string; excluded_rows: number[]; excluded_sheets: string[];
  issues: { row: number; message: string }[];
  rows: { source_row: number; sku_code: string; asin: string; fnsku: string; box1_units: string; box2_units: string; source_units: string; original_d: string; reference_difference: string | null }[];
  saved_draft: SavedPacking | null;
};

function usePackingSource(sourcePath: string, refresh: number) {
  const [source, setSource] = useState<PackingSource>(); const [error, setError] = useState<string>();
  const { generation, registerSensitivePurge } = useAuthzGeneration();
  useEffect(() => registerSensitivePurge(() => { setSource(undefined); setError(undefined); }), [registerSensitivePurge]);
  useEffect(() => {
    const gate = new RequestGate(); const ticket = gate.begin([sourcePath, refresh], generation);
    setSource(undefined); setError(undefined);
    void requestApi<PackingSource>(sourcePath, { signal: ticket.signal }).then(result => { if (ticket.isCurrent()) setSource(result); }).catch((reason: unknown) => { if (ticket.isCurrent()) setError(reason instanceof Error ? reason.message : "装箱单读取未完成。"); });
    return () => gate.dispose();
  }, [sourcePath, refresh, generation]);
  return { source, error };
}

function fields(saved: SavedPacking): PackingInput {
  return { source_digest: saved.source_digest, revision: saved.revision, business_number: saved.business_number, business_date: saved.business_date, notes: saved.notes, lines: saved.lines };
}

export function ShipmentSourceDraftPage({ canWrite }: { canWrite: boolean }) {
  const [params] = useSearchParams();
  const sampleId = params.get("sample") || "packing-list-20260904";
  const sourcePath = `/api/production/shipment-source-drafts/${encodeURIComponent(sampleId)}`;
  const [refresh, setRefresh] = useState(0); const { source, error } = usePackingSource(sourcePath, refresh);
  return <><PageHeader eyebrow="PRODUCTION · B 1.1.0 · 本地副本" title="装箱单体验 · 假设已发" description="读取已授权装箱单的真实SKU和箱内件数；已发状态仅为体验假设。草稿独立保存，实际日期、商品身份和订单归属仍待核实，不计入有效出货。" actions={<div className={styles.actions}><LinkButton to="/production/source-drafts">原表与导入草稿</LinkButton><LinkButton to="/production/shipments">返回实际出货</LinkButton></div>} />
    {!source ? <StatusMessage kind={error ? "danger" : "info"} title={error ? "读取未完成" : "正在读取装箱单…"}>{error}</StatusMessage> : <PackingEditor key={`${source.sample_id}:${refresh}`} source={source} canWrite={canWrite} onReload={() => setRefresh(value => value + 1)} />}
  </>;
}

function PackingEditor({ source, canWrite, onReload }: { source: PackingSource; canWrite: boolean; onReload: () => void }) {
  const sourcePath = `/api/production/shipment-source-drafts/${encodeURIComponent(source.sample_id)}`;
  const initialState = useRef<PackingInput>(source.saved_draft ? fields(source.saved_draft) : { source_digest: source.source_digest, revision: 0, business_number: "", business_date: "", notes: "", lines: source.rows.map(row => ({ source_row: row.source_row, actual_units: row.source_units, order_reference_note: "", review_note: "" })) });
  const initial = initialState.current;
  const [input, setInput] = useState(initial); const [baseline, setBaseline] = useState(JSON.stringify(initial));
  const [saved, setSaved] = useState(source.saved_draft); const [busy, setBusy] = useState(false); const [unknown, setUnknown] = useState(false);
  const [error, setError] = useState<string>(); const [success, setSuccess] = useState(false); const [invalidRow, setInvalidRow] = useState<number>();
  const [reloadOpen, setReloadOpen] = useState(false); const reloadTrigger = useRef<HTMLButtonElement>(null);
  const pending = useRef<{ key: string; body: PackingInput } | undefined>(undefined);
  const { generation, registerSensitivePurge } = useAuthzGeneration(); const currentGeneration = useRef(generation); currentGeneration.current = generation;
  useEffect(() => registerSensitivePurge(() => { setInput({ ...initial, business_number: "", business_date: "", notes: "", lines: [] }); setSaved(null); setError(undefined); pending.current = undefined; }), [registerSensitivePurge, initial]);
  const leave = useProductionLeave(JSON.stringify(input) !== baseline, busy, unknown);
  const validQuantities = input.lines.every(line => /^(0|[1-9]\d{0,17})$/.test(line.actual_units));
  const total = validQuantities ? input.lines.reduce((sum, line) => sum + BigInt(line.actual_units), 0n).toString() : undefined;
  const originalByRow = new Map(source.rows.map(row => [row.source_row, row.source_units]));
  const changedCount = input.lines.filter(line => line.actual_units !== originalByRow.get(line.source_row)).length;
  const locked = busy || unknown || !canWrite;
  function updateLine(sourceRow: number, changes: Partial<DraftLine>) { setInvalidRow(undefined); setInput({ ...input, lines: input.lines.map(line => line.source_row === sourceRow ? { ...line, ...changes } : line) }); }
  function restoreQuantity(sourceRow?: number) {
    setInput(value => ({ ...value, lines: value.lines.map(line => sourceRow === undefined || line.source_row === sourceRow ? { ...line, actual_units: originalByRow.get(line.source_row)! } : line) }));
    setSuccess(false); setError(undefined); setInvalidRow(undefined);
  }
  function accept(result: SavedPacking) { const next = fields(result); setInput(next); setBaseline(JSON.stringify(next)); setSaved(result); setUnknown(false); setSuccess(true); pending.current = undefined; }
  async function save(retry = false) {
    if (!retry) {
      const invalid = input.lines.find(line => !/^(0|[1-9]\d{0,17})$/.test(line.actual_units));
      if (invalid) { setInvalidRow(invalid.source_row); setError(`原表第${invalid.source_row}行：请填写非负整数件数。`); document.getElementById(`packing-quantity-${invalid.source_row}`)?.focus(); return; }
      pending.current = { key: crypto.randomUUID(), body: input };
    }
    const operation = pending.current; if (!operation) return;
    const atGeneration = generation; setBusy(true); setError(undefined); setSuccess(false);
    try {
      const result = await writeApi<SavedPacking>(sourcePath, { body: operation.body, operationKey: operation.key });
      if (atGeneration === currentGeneration.current) accept(result);
    } catch (reason) {
      if (atGeneration !== currentGeneration.current) return;
      if (reason instanceof ApiRequestError && reason.status >= 400 && reason.status < 500) { pending.current = undefined; setUnknown(false); } else setUnknown(true);
      setError(reason instanceof Error ? reason.message : "保存未完成，请先核实当前草稿。");
    } finally { if (atGeneration === currentGeneration.current) setBusy(false); }
  }
  async function checkSaved() {
    const atGeneration = generation; setBusy(true);
    try {
      const result = await requestApi<PackingSource>(sourcePath);
      if (atGeneration !== currentGeneration.current) return;
      if (result.saved_draft && pending.current && result.saved_draft.last_save_key === pending.current.key) { accept(result.saved_draft); setError(undefined); }
      else setError("当前未查到这次保存；可重发原操作或继续核实，输入保持锁定。");
    } catch (reason) { if (atGeneration === currentGeneration.current) setError(reason instanceof Error ? reason.message : "核实未完成。"); }
    finally { if (atGeneration === currentGeneration.current) setBusy(false); }
  }
  const invalidQuantity = input.lines.find(line => !/^(0|[1-9]\d{0,17})$/.test(line.actual_units));
  const missingReference = input.lines.find(line => !line.order_reference_note.trim());
  const referenceCount = input.lines.filter(line => line.order_reference_note.trim()).length;
  const reviewItems: DraftReviewItem[] = [
    { key: "date", title: input.business_date ? "已填日期，仍待核实" : "缺实际出货日期", detail: input.business_date ? `草稿填写了${input.business_date}，当前仍未核实实际发运日期。` : "原表没有明确实际出货日期；文件名日期仅作线索。", targetId: locked ? "packing-draft-information" : "packing-shipment-date", actionLabel: "定位出货日期" },
    ...(invalidQuantity ? [{ key: "quantity", title: `第${invalidQuantity.source_row}行数量待修正`, detail: "草稿出货量须为非负整数；当前总差额尚不可核对。", targetId: locked ? `packing-sku-${invalidQuantity.source_row}` : `packing-quantity-${invalidQuantity.source_row}`, actionLabel: "定位数量问题" }] : []),
    ...source.issues.map((issue, index) => ({ key: `source-${index}`, title: `原表第${issue.row}行待核对`, detail: issue.message, targetId: `packing-sku-${issue.row}`, actionLabel: `定位第${issue.row}行` })),
    { key: "sku", title: `SKU待匹配：${source.rows.length}条`, detail: "正式商品尚未绑定；主档核对展示只读候选或未匹配结果。平台标识保留，仍需核实。", targetId: `packing-sku-${source.rows[0]?.source_row}`, actionLabel: "查看SKU明细" },
    { key: "order", title: `订单待关联：${source.rows.length}条`, detail: `已填归属说明${referenceCount}条，仅供核对，尚未建立实际订单关联。`, targetId: locked ? `packing-sku-${source.rows[0]?.source_row}` : `packing-order-reference-${missingReference?.source_row ?? source.rows[0]?.source_row}`, actionLabel: "定位归属说明" },
    { key: "dispatch", title: "已发状态仅为假设", detail: "填写日期、数量或说明不会把假设改成已核实实际发运。", targetId: "packing-dispatch-assumption", actionLabel: "查看假设说明" },
  ];
  return <><section className={styles.panel}><h2>{source.filename}</h2>
    <dl className={styles.metadata}><div><dt>SKU明细</dt><dd>{source.rows.length}条</dd></div><div><dt>箱1件数</dt><dd>{units(source.box1_units)}件</dd></div><div><dt>箱2件数</dt><dd>{units(source.box2_units)}件</dd></div><div><dt>原表装箱合计</dt><dd>{units(source.source_units)}件</dd></div><div><dt>草稿出货量</dt><dd>{total !== undefined ? `${units(total)}件` : "待修正数量"}</dd></div><div><dt>保存状态</dt><dd>{saved ? `导入草稿 · 修订${saved.revision}` : "尚未保存"}</dd></div></dl>
    <div id="packing-dispatch-assumption" tabIndex={-1} className={styles.reviewTarget}><StatusMessage kind="warning" title="已发状态：假设，尚未核实">原表装箱件数来自真实文件；本次仅假设已发用于体验，不代表已确认的实际发运。实际日期、SKU和订单归属仍待核实。</StatusMessage></div>
    <p>只读取Sheet1商品明细，件数按箱1＋箱2计算；同一SKU的空箱格按该箱未装入处理。已排除{source.excluded_sheets.join("、")}及第{source.excluded_rows.join("、")}行的合计、重量和尺寸，不重复加上D列或G列数量。</p>
    <p>{source.filename_date_hint ? `文件名含${source.filename_date_hint}，只作日期线索；` : "文件名没有有效日期线索；"}原表没有明确实际出货日期。订单归属说明仅为核对备注，不会自动绑定订单。</p>
  </section>
  <CatalogReferencePanel reference={source.catalog_reference} />
  <SourceDraftReview items={reviewItems} changedCount={changedCount} totalDifference={total === undefined ? undefined : (BigInt(total) - BigInt(source.source_units)).toString()} disabled={locked} onRestoreAll={() => restoreQuantity()} />
  <form className={styles.body} onSubmit={event => { event.preventDefault(); void save(); }} onChangeCapture={() => { setError(undefined); setSuccess(false); }}>
    <fieldset id="packing-draft-information" tabIndex={-1} disabled={locked} className={`${styles.panel} ${styles.reviewTarget}`}><legend>出货导入草稿</legend><div className={styles.fields}><FormField label="业务出货单号（可选）"><Input value={input.business_number} maxLength={120} onChange={event => setInput({ ...input, business_number: event.target.value })} /></FormField><FormField label="实际出货日期（待核对，可留空）"><Input id="packing-shipment-date" type="date" value={input.business_date} onChange={event => setInput({ ...input, business_date: event.target.value })} /></FormField><FormField label="草稿备注"><Input value={input.notes} maxLength={2000} onChange={event => setInput({ ...input, notes: event.target.value })} /></FormField></div><p>补填日期也只保存为未核实的草稿资料；原文件保持不变。</p></fieldset>
    <Table className={styles.packingDraftTable} title="装箱明细与草稿核对" description="原箱内件数保持；草稿量与订单归属说明独立保存。窄屏可左右滑动查看完整明细。"><thead><tr><th>原行</th><th>原SKU / 平台标识</th><th>箱1</th><th>箱2</th><th>装箱合计</th><th>草稿出货量</th><th>订单归属说明</th><th>核对说明</th><th>关联状态</th></tr></thead><tbody>{source.rows.map((row, index) => <tr key={row.source_row} className={input.lines[index]?.actual_units !== row.source_units ? styles.changedDraftRow : undefined}><td>{row.source_row}</td><td id={`packing-sku-${row.source_row}`} tabIndex={-1} className={styles.reviewTarget}>{row.sku_code}<details><summary>查看原标识及参考列</summary><p>ASIN：{row.asin || "—"}</p><p>FNSKU：{row.fnsku || "—"}</p><p>无表头D列：{row.original_d || "—"}；与箱合计差：{row.reference_difference ?? "待核对"}。仅供核对。</p></details></td><td>{row.box1_units}件</td><td>{row.box2_units}件</td><td>{row.source_units}件</td><td><Input id={`packing-quantity-${row.source_row}`} aria-label={`原表第${row.source_row}行草稿出货量`} aria-invalid={invalidRow === row.source_row} inputMode="numeric" disabled={locked} value={input.lines[index]?.actual_units || ""} onChange={event => updateLine(row.source_row, { actual_units: event.target.value })} /><DraftQuantityChange original={row.source_units} current={input.lines[index]?.actual_units || ""} allowZero disabled={locked} inputId={`packing-quantity-${row.source_row}`} onRestore={() => restoreQuantity(row.source_row)} /></td><td><Input id={`packing-order-reference-${row.source_row}`} aria-label={`原表第${row.source_row}行订单归属说明`} maxLength={300} disabled={locked} value={input.lines[index]?.order_reference_note || ""} onChange={event => updateLine(row.source_row, { order_reference_note: event.target.value })} /></td><td><Input aria-label={`原表第${row.source_row}行核对说明`} maxLength={300} disabled={locked} value={input.lines[index]?.review_note || ""} onChange={event => updateLine(row.source_row, { review_note: event.target.value })} /></td><td><CatalogCandidateCell reference={source.catalog_reference} sourceRow={row.source_row} /><small className={styles.secondary}>订单待关联</small></td></tr>)}</tbody></Table>
    {error && <StatusMessage kind="danger" title={unknown ? "保存结果待核实" : "草稿未保存"}>{error}</StatusMessage>}
    {success && <StatusMessage kind="success" title="出货导入草稿已保存">已发状态仍是假设，订单归属仍待核对。刷新后可继续查看，不增加有效出货量。</StatusMessage>}
    {!canWrite && <StatusMessage kind="info" title="查看人员只读">可以查看装箱明细，不能修改或保存草稿。</StatusMessage>}
    <div className={styles.actions}>{canWrite && !unknown && <Button type="submit" disabled={busy} loading={busy}>保存出货导入草稿</Button>}{unknown && <><Button disabled={busy} onClick={() => { void checkSaved(); }}>核实当前草稿</Button><Button variant="secondary" disabled={busy} onClick={() => { void save(true); }}>重发原保存操作</Button></>}<Button ref={reloadTrigger} variant="secondary" disabled={busy || unknown} onClick={() => { if (JSON.stringify(input) !== baseline) setReloadOpen(true); else onReload(); }}>重新载入草稿</Button></div>
    {saved && <p>上次保存：{new Date(saved.updated_at).toLocaleString("zh-CN")} · 草稿修订{saved.revision}</p>}
  </form><Dialog contentClassName={styles.productionDialog} open={reloadOpen} onOpenChange={setReloadOpen} returnFocusTarget={reloadTrigger} title="重新载入已保存草稿" description="未保存输入会被放弃；原装箱单和已保存草稿保持。"><div className={styles.guardActions}><Button variant="secondary" onClick={() => setReloadOpen(false)}>继续核对</Button><Button onClick={onReload}>放弃输入并重新载入</Button></div></Dialog>{leave.prompt}</>;
}
