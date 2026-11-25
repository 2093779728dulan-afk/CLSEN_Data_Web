import { ProductionConfirmDialog } from "./ProductionConfirmDialog";
import { useRef, useState } from "react";
import { Button, Dialog, FormField, Input, StatusMessage, Table } from "../../design-system";
import { useCommand } from "./useProductionApi";
import { useProductionLeave } from "./useProductionLeave";
import { useBusinessToday } from "./workbenchDate";
import { knownOrderSum, orderProductName, progressChanges, progressNumber } from "./orderProgress";
import type { Document, Sku } from "./types";
import styles from "./FactoryOrderOverview.module.css";

export function OrderProgressDialog({ order, catalog, focusLine, returnFocus, close, saved, readBlocked = false }: {
  readBlocked?: boolean; order: Document; catalog: Sku[]; focusLine?: string; returnFocus: HTMLElement | null; close: () => void; saved: (result: Document) => void;
}) {
  const lines = order.lines || [];
  const [values, setValues] = useState<Record<string, string>>(Object.fromEntries(lines.map(line => [line.id, line.produced_units ?? ""])));
  const [selected, setSelected] = useState(lines.filter(line => line.tracking_state !== "CLOSED").map(line => line.id));
  const [statuses, setStatuses] = useState<Record<string, string>>(Object.fromEntries(lines.map(line => [line.id, line.production_status ?? ""])));
  const [bulkStatus, setBulkStatus] = useState("");
  const today = useBusinessToday();
  const [bulk, setBulk] = useState(""); const [reason, setReason] = useState(""); const [date, setDate] = useState(today);
  const [closing, setClosing] = useState(false); const [error, setError] = useState("");
  const initialDate = useRef(date); const focus = useRef(returnFocus);
  const changes = progressChanges(order, values, statuses);
  const invalid = lines.some(line => line.tracking_state !== "CLOSED" && values[line.id] !== "" && !progressNumber(values[line.id] || ""));
  const reasonRequired = !invalid && changes.some(change => { if (change.produced_units === undefined) return false; const line = lines.find(item => item.id === change.order_line_id)!; const value = BigInt(change.produced_units); return value > BigInt(line.planned_production_units ?? line.expected_units) || line.produced_units != null && value < BigInt(line.produced_units); });
  const dirty = lines.some(line => values[line.id] !== (line.produced_units ?? "") || statuses[line.id] !== (line.production_status ?? "")) || !!reason || !!bulk || !!bulkStatus || date !== initialDate.current;
  const command = useCommand<Document>(result => { leave.allowLeave(); saved(result); });
  const leave = useProductionLeave(dirty, command.busy, command.unknown);
  const locked = command.busy || command.unknown;
  function requestClose() { if (locked) return; if (dirty) setClosing(true); else { leave.allowLeave(); close(); } }
  function submit() {
    if (locked || readBlocked) return;
    if (invalid || !changes.length || !date || reasonRequired && !reason.trim()) { setError(invalid ? "累计生产数量须为支持范围内的非负整数；留空表示不更新。" : !changes.length ? "尚未修改生产数量或状态。" : !date ? "请选择更新日期。" : "减少累计数或超计划生产时，请填写更正原因。"); return; }
    command.submit(`/api/production/orders/${order.id}/production-progress`, { expected_revision: order.revision, effective_date: date, reason, lines: changes });
  }
  const before = knownOrderSum(lines.map(line => line.produced_units));
  const after = knownOrderSum(lines.map(line => line.tracking_state === "CLOSED" || !values[line.id] ? line.produced_units : progressNumber(values[line.id]!) ? values[line.id] : null));
  return <Dialog open title="批量更新生产进度" description={`${order.business_number || order.system_number} · ${order.factory_name || "工厂未登记"}`} size="large" contentClassName={styles.progressDialog} closeLabel="关闭生产进度编辑" dismissDisabled={locked} closeOnOutsideClick={false} returnFocusTarget={focus} onOpenChange={open => { if (!open) requestClose(); }}>
    <ProductionConfirmDialog open={closing} onOpenChange={setClosing} title="放弃未保存的修改？"><Button aria-label="继续填写进度" onClick={() => setClosing(false)}>继续填写</Button><Button aria-label="放弃并关闭进度" variant="danger" onClick={() => { leave.allowLeave(); close(); }}>放弃修改</Button></ProductionConfirmDialog>
    {command.feedback}{error && <StatusMessage kind="danger" title="进度尚未保存">{error}</StatusMessage>}
    <form onSubmit={event => { event.preventDefault(); submit(); }}><fieldset disabled={locked} className={styles.editorFields}>
      <details className={styles.bulkTools}><summary>批量填写<span>已选 {selected.length} 项</span></summary><div className={styles.bulkGrid}>
        <div className={styles.bulkGroup}><FormField label="累计生产"><Input aria-label="给已选规格填写同一累计数" inputMode="numeric" value={bulk} onChange={event => setBulk(event.target.value)} /></FormField><Button aria-label="应用到已选规格" variant="secondary" disabled={!selected.length || !progressNumber(bulk)} onClick={() => setValues(previous => ({ ...previous, ...Object.fromEntries(selected.map(id => [id, bulk])) }))}>填入已选</Button><Button aria-label="已选规格按计划量填写" variant="quiet" disabled={!selected.length} onClick={() => setValues(previous => ({ ...previous, ...Object.fromEntries(lines.filter(line => selected.includes(line.id)).map(line => [line.id, line.planned_production_units ?? line.expected_units])) }))}>按计划量</Button></div>
        <div className={styles.bulkGroup}><FormField label="生产状态"><Input aria-label="批量生产状态" maxLength={64} list="production-status-labels" value={bulkStatus} onChange={event => setBulkStatus(event.target.value)} /></FormField><Button aria-label="状态应用到已选" variant="secondary" disabled={!selected.length} onClick={() => setStatuses(previous => ({ ...previous, ...Object.fromEntries(selected.map(id => [id, bulkStatus])) }))}>填入已选</Button></div>
      </div></details>
      <datalist id="production-status-labels">{[...new Set([...lines.map(line => line.production_status ?? ""), ...Object.values(statuses)])].filter(Boolean).map(label => <option key={label} value={label} />)}</datalist>
      <Table aria-label="批量生产进度" className={styles.editorTable}><thead><tr><th>款号 / 颜色 / 尺码</th><th>生产状态</th><th>下单 / 计划生产</th><th>原累计</th><th>累计生产</th></tr></thead><tbody>{lines.map(line => <tr key={line.id} data-focused-line={focusLine === line.id || undefined}><th scope="row"><label><input type="checkbox" aria-label={`批量填写 ${orderProductName(line, catalog)}`} checked={selected.includes(line.id)} disabled={line.tracking_state === "CLOSED"} onChange={event => setSelected(previous => event.target.checked ? [...previous, line.id] : previous.filter(id => id !== line.id))} />{orderProductName(line, catalog)}</label>{line.tracking_state === "CLOSED" && <small>已关闭</small>}</th><td><Input aria-label={`${orderProductName(line, catalog)} 生产状态`} maxLength={64} list="production-status-labels" disabled={line.tracking_state === "CLOSED"} value={statuses[line.id] ?? ""} onChange={event => { setStatuses(previous => ({ ...previous, [line.id]: event.target.value })); setError(""); }} /></td><td>{line.expected_units} / {line.planned_production_units ?? line.expected_units}</td><td>{line.produced_units ?? "未登记"}</td><td><Input aria-label={`${orderProductName(line, catalog)} 累计实际生产数量`} disabled={line.tracking_state === "CLOSED"} inputMode="numeric" value={values[line.id] || ""} onChange={event => { setValues(previous => ({ ...previous, [line.id]: event.target.value })); setError(""); }} /></td></tr>)}</tbody></Table>
      {!!changes.length && <p className={styles.changeSummary}>{changes.some(change => change.produced_units !== undefined) && <>累计生产 {before ?? "未登记"} → {after ?? "待核"} 件 · </>}修改 {changes.length} 项</p>}
      <details className={styles.progressNote} open={reasonRequired || undefined}><summary>{reasonRequired ? "更正原因（必填）" : "备注"}</summary><textarea aria-label="本次备注 / 更正原因" required={reasonRequired} value={reason} maxLength={2000} onChange={event => setReason(event.target.value)} /></details>
      <div className={styles.progressFooter}><FormField label="更新日期" required><Input required type="date" value={date} onChange={event => setDate(event.target.value)} /></FormField><div><Button aria-label="取消编辑" variant="secondary" onClick={requestClose}>取消</Button><Button aria-label="核对并保存进度" variant="primary" type="submit" disabled={readBlocked || !changes.length || invalid || !date || reasonRequired && !reason.trim()}>保存</Button></div></div>
    </fieldset></form>{leave.prompt}
  </Dialog>;
}
