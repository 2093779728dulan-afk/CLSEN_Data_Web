import { ProductionConfirmDialog } from "./ProductionConfirmDialog";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { requestApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, FormField, Input, Menu, StatusMessage, Table } from "../../design-system";
import { useCommand, useLoad } from "./useProductionApi";
import { useProductionLeave } from "./useProductionLeave";
import { transportCsv, transportStatus, transportTime, type TransportEvent, type TransportState } from "./transport";
import type { OverviewGuard } from "./stockOverview";
import styles from "./TransportPanel.module.css";

const blank = { carrier: "", tracking_number: "", arrival_local: "", arrival_timezone: "Asia/Shanghai", source_reference: "", reason: "", event_kind: "IN_TRANSIT", occurred_local: "", timezone: "Asia/Shanghai", location: "", description: "", signed_units: "" };
type Draft = typeof blank;
const names: Record<string, string> = { carrier: "承运商", tracking_number: "运单号", arrival_local: "预计到达", arrival_timezone: "预计到达时区", source_reference: "来源依据", shipment_revision: "出货修订", event_kind: "节点", occurred_local: "发生时间", timezone: "发生时区", location: "地点", description: "说明", signed_units: "承运商累计签收件数" };
function changes(before: Record<string, unknown> | null, after: Record<string, unknown>) {
  return Object.entries(names).filter(([field]) => (before?.[field] ?? "") !== (after[field] ?? "")).map(([field, label]) => {
    const value = (v: unknown) => { const scalar = typeof v === "string" || typeof v === "number" || typeof v === "boolean" ? v.toString() : ""; return field === "event_kind" ? transportStatus[scalar as keyof typeof transportStatus] || "未登记" : scalar || "未登记"; };
    return <p key={field}>{label}：{before ? `${value(before[field])} → ` : ""}{value(after[field])}</p>;
  });
}
export function TransportPanel({ shipmentId, canWrite, onSaved, onGuardChange, onReceive, compact = false }: { compact?: boolean; shipmentId: string; canWrite: boolean; onReceive?:(trigger:HTMLButtonElement)=>void; onSaved?:()=>void; onGuardChange?:(guard:OverviewGuard)=>void }) {
  const path = `/api/production/inventory/transport-state?shipment_id=${encodeURIComponent(shipmentId)}`;
  const [refresh, setRefresh] = useState(0); const data = useLoad<TransportState>(path, refresh, true, true);
  const transportCurrent = data.current;
  const location = useLocation(); const panel = useRef<HTMLElement>(null); const positioned = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (transportCurrent && location.hash === "#transport" && positioned.current !== location.key) {
      panel.current?.scrollIntoView({ block: "start" }); positioned.current = location.key;
    }
  }, [transportCurrent, location.hash, location.key]);
  const [mode, setMode] = useState<"record" | "event">(); const [eventId, setEventId] = useState<string>(); const [basis, setBasis] = useState<TransportState>();
  const [draft, setDraft] = useState<Draft>(blank); const [initial, setInitial] = useState<Draft>(blank); const [discard, setDiscard] = useState(false); const [readError, setReadError] = useState<string>(); const [reading, setReading] = useState(false);
  const command = useCommand<TransportState>(() => { setMode(undefined); setEventId(undefined); setRefresh(v => v + 1); onSaved?.(); });
  const rereadRequest = useRef<AbortController | null>(null);
  const { registerSensitivePurge } = useAuthzGeneration();
  useEffect(() => () => rereadRequest.current?.abort(), []);
  useEffect(() => registerSensitivePurge(() => { rereadRequest.current?.abort(); setReading(false); setMode(undefined); setDraft(blank); setInitial(blank); setBasis(undefined); setReadError(undefined); }), [registerSensitivePurge]);
  const dirty = !!mode && JSON.stringify(initial) !== JSON.stringify(draft); const locked = command.busy || command.unknown || reading;
  useEffect(()=>{onGuardChange?.({dirty,busy:locked,unknown:command.unknown});},[dirty,locked,command.unknown,onGuardChange]);
  useEffect(()=>()=>onGuardChange?.({dirty:false,busy:false,unknown:false}),[onGuardChange]);
  const value = data.value;
  function edit(next: "record" | "event", event?: TransportEvent) {
    if (!value) return;
    const record = value.record;
    const input = { ...blank, ...(next === "record" && record ? { carrier: record.carrier, tracking_number: record.tracking_number, arrival_local: record.arrival_local, arrival_timezone: record.arrival_timezone || blank.arrival_timezone, source_reference: record.source_reference } : {}), ...(event ? { event_kind: event.event_kind, occurred_local: event.occurred_local, timezone: event.timezone, location: event.location, description: event.description, source_reference: event.source_reference, signed_units: event.signed_units ?? "" } : {}) };
    setInitial(input); setDraft(input); setBasis(value); setEventId(event?.id); setMode(next); setReadError(undefined);
  }
  function close() { if (dirty) setDiscard(true); else setMode(undefined); }
  function submit() {
    if (!basis) return;
    const scope = { shipment_id: shipmentId, expected_shipment_revision: basis.shipment_revision, expected_warehouse_id: basis.warehouse_id || "", expected_owner_id: basis.owner_id || "", expected_destination_id: basis.destination_id || "" };
    if (mode === "record") command.submit(`/api/production/inventory/transport-records${basis.record ? `/${basis.record.id}/correct` : ""}`, { ...scope, expected_revision: basis.record?.revision || "0", carrier: draft.carrier, tracking_number: draft.tracking_number, arrival_local: draft.arrival_local, arrival_timezone: draft.arrival_timezone, source_reference: draft.source_reference, reason: draft.reason });
    else command.submit(`/api/production/inventory/transport-events${eventId ? `/${eventId}/correct` : ""}`, { ...scope, transport_id: basis.record?.id, expected_transport_revision: basis.record?.revision, ...(eventId ? { expected_revision: basis.events.find(e => e.id === eventId)?.revision } : {}), event_kind: draft.event_kind, occurred_local: draft.occurred_local, timezone: draft.timezone, location: draft.location, description: draft.description, source_reference: draft.source_reference, reason: draft.reason, signed_units: draft.event_kind === "SIGNED" ? draft.signed_units || null : null });
  }
  async function reread() {
    rereadRequest.current?.abort(); const controller = new AbortController(); rereadRequest.current = controller;
    setReading(true); setReadError(undefined);
    try { const current = await requestApi<TransportState>(path, { signal: controller.signal }); if (!controller.signal.aborted) { setBasis(current); setRefresh(v => v + 1); } }
    catch (error) { if (!controller.signal.aborted) setReadError(error instanceof Error ? error.message : "读取未完成"); }
    finally { if (!controller.signal.aborted) setReading(false); }
  }
  const field = (key: keyof Draft, label: string, required = false, type = "text") => <FormField label={label} required={required}><Input required={required} type={type} value={draft[key]} onChange={e => setDraft(v => ({ ...v, [key]: e.target.value }))} /></FormField>;
  const signed = value?.events.find(e => e.event_kind === "SIGNED")?.signed_units;
  const shipped = BigInt(value?.shipment_units || "0");
  const received = BigInt(value?.destination_received_units || "0");
  const remaining = shipped > received ? shipped - received : 0n;
  const percent = shipped > 0n ? Number((received < shipped ? received : shipped) * 1000n / shipped) / 10 : 0;
  const editable = canWrite && value?.shipment_status === "CONFIRMED";
  const complete = remaining === 0n && shipped > 0n;

  return <section ref={panel} className={styles.panel} data-embedded={!!onGuardChange||undefined} id="transport" aria-label="运输跟踪">
    <header className={`${styles.header} ${compact ? styles.compactHeader : ""}`}>{!compact && <div><h2>运输跟踪</h2></div>}<Menu label="更多运输操作" items={[...(complete&&editable&&!mode?[{id:"supplement",label:"补充运输记录",disabled:locked,onSelect:()=>edit(value?.registered?"event":"record")}]:[]),...(editable&&value?.registered?[{id:"correct",label:"更正运输资料",disabled:locked||!!mode,onSelect:()=>edit("record")}]:[]),{id:"refresh",label:"刷新运输资料",disabled:locked,onSelect:()=>setRefresh(v=>v+1)},{id:"export",label:"导出运输记录",disabled:!value,onSelect:()=>{if(!value)return;const url=URL.createObjectURL(new Blob([transportCsv(value)],{type:"text/csv;charset=utf-8"}));const link=document.createElement("a");link.href=url;link.download=`运输记录-${shipmentId}.csv`;link.click();URL.revokeObjectURL(url);}}]}/></header>
    {data.error && <StatusMessage kind="danger" title="运输资料读取未完成">{data.error}</StatusMessage>}
    {!value && !data.error && <p role="status">正在读取运输资料…</p>}
    {value && <>
      <div className={styles.receiving}>
        <dl className={styles.quantities} aria-label="本批收货进度">
          <div><dt>已发</dt><dd>{shipped.toString()}<small>件</small></dd></div>
          <div><dt>实收</dt><dd>{received.toString()}<small>件</small></dd></div>
          <div><dt>待收</dt><dd>{remaining.toString()}<small>件</small></dd></div>
        </dl>
        <progress className={styles.progress} aria-label="本批入库完成度" value={percent} max={100}/>
        <div className={styles.actions}>
          {editable&&onReceive&&<Button variant="primary" disabled={locked||dirty||!data.current} onClick={event=>onReceive(event.currentTarget)}>{remaining===0n&&shipped>0n?"查看本批接收记录":"核对本批到仓入库"}</Button>}
          {editable&&!complete&&!mode&&<Button variant={onReceive?"secondary":"primary"} disabled={!!value.registered&&!value.source_revision_current} onClick={()=>edit(value.registered?"event":"record")}>{value.registered?"追加运输节点":"登记运输资料"}</Button>}
        </div>
      </div>
      {!value.registered ? <StatusMessage kind="info" title="运输未登记">登记承运商及物流节点后可跟进运输。</StatusMessage> : <>
        <dl className={styles.summary}>
          <div><dt>当前进度</dt><dd>{remaining===0n&&shipped>0n?"目的仓已收齐":transportStatus[value.status]}</dd></div>
          <div><dt>承运商 / 运单号</dt><dd>{value.record?.carrier} · {value.record?.tracking_number}</dd></div>
          <div><dt>预计到达</dt><dd>{transportTime(value.record?.arrival_local || "", value.record?.arrival_timezone || "")}</dd></div>
        </dl>
        {!value.source_revision_current&&<StatusMessage kind="warning" title="出货已发生更正">请从“更多运输操作”更正运输资料，再追加节点。</StatusMessage>}
      </>}
      {signed!=null&&<p className={styles.signature}>承运商累计签收 {signed} 件 · 签收与实收相差 {BigInt(signed)-received} 件</p>}
      {mode && <form className={styles.editor} onSubmit={e => { e.preventDefault(); submit(); }}><h3>{mode === "record" ? basis?.record ? "更正运输资料" : "登记运输资料" : eventId ? "更正运输节点" : "追加运输节点"}</h3><fieldset className={styles.fields} disabled={locked}>
        {mode === "record" ? <>{field("carrier", "承运商", true)}{field("tracking_number", "运单号", true)}{field("arrival_local", "预计到达时间", false, "datetime-local")}{field("arrival_timezone", "预计到达时区")}</> : <><FormField label="运输节点" required><select value={draft.event_kind} onChange={e => setDraft(v => ({ ...v, event_kind: e.target.value }))}>{(["DISPATCHED", "IN_TRANSIT", "ARRIVED", "SIGNED", "EXCEPTION"] as const).map(k => <option key={k} value={k}>{transportStatus[k]}</option>)}</select></FormField>{field("occurred_local", "节点发生时间", true, "datetime-local")}{field("timezone", "发生时区（例如 Asia/Shanghai 或 +08:00）", true)}{field("location", "发生地点")}{draft.event_kind === "SIGNED" && field("signed_units", "承运商累计签收件数（未知可留空）")}{field("description", "节点说明")}</>}
        <div className={styles.wide}>{field("source_reference", "来源依据（人工登记，请注明凭据）", true)}</div>{(mode === "record" && !!basis?.record || !!eventId) && <div className={styles.wide}>{field("reason", "更正原因", true)}</div>}
      </fieldset>{command.feedback}{readError && <StatusMessage kind="danger" title="当前修订读取失败">{readError}</StatusMessage>}<div className={styles.actions}><Button disabled={locked} variant="secondary" onClick={close}>取消填写</Button>{command.errorCode === "transport_revision_conflict" && <Button disabled={locked} variant="secondary" onClick={() => void reread()}>读取当前修订，保留输入</Button>}<Button variant="primary" type="submit" disabled={locked || !data.current}>保存{mode === "record" ? "运输资料" : "运输节点"}</Button></div><p className={styles.note}>发生时间按填写时区记录，录入时间另存。夏令时重复时可用明确的 UTC 偏移时区。</p></form>}
      <details className={styles.history}><summary>物流节点与依据（{value.events.length} 条）</summary>
        <p className={styles.note}>物流签收与目的仓实收分别登记，运输记录不会改变库存。累计签收快照不相加。</p>
        {value.record&&<p className={styles.note}>资料依据：{value.record.source_reference} · 运输资料修订 {value.record.revision} · 关联出货修订 {value.record.shipment_revision}</p>}
        {!!value.events.length&&<div className={styles.tableScroll}><Table title="物流节点" description="按发生时间排序；更正保留原修订。"><thead><tr><th>节点 / 时间</th><th>地点与说明</th><th>累计签收</th><th>依据</th><th>操作</th></tr></thead><tbody>{value.events.map(event=><tr key={event.id}><th><div className={styles.event}>{transportStatus[event.event_kind]}<small>{transportTime(event.occurred_local,event.timezone)}</small><small>节点 {event.id} · 修订 {event.revision}</small></div></th><td>{event.location||"未登记"}<p>{event.description}</p></td><td>{event.event_kind==="SIGNED"?event.signed_units??"未登记":"不适用"}</td><td>{event.source_reference}</td><td>{editable&&!complete&&!mode&&<Button variant="quiet" onClick={()=>edit("event",event)}>更正节点</Button>}</td></tr>)}</tbody></Table></div>}
      </details>
      {!!value.history.length && <details className={styles.history}><summary>运输修订历史（{value.history.length} 条）</summary><ul>{value.history.map(h => <li key={`${h.document_kind}-${h.document_id}-${h.revision}`}><strong>{h.document_kind === "transport" ? "运输资料" : `运输节点 ${h.document_id}`} · 修订 {h.revision}</strong><p className={styles.note}>{h.actor_name} · {h.created_at} · {h.reason}</p><div className={styles.changes}>{changes(h.before_value, h.after_value)}</div></li>)}</ul></details>}
    </>}
    <ProductionConfirmDialog open={discard} onOpenChange={setDiscard} title="放弃本次运输填写？" description="尚未保存的输入会被放弃，已登记记录及历史保留。"><Button onClick={() => setDiscard(false)}>继续填写</Button><Button variant="danger" onClick={() => { setDiscard(false); setMode(undefined); }}>放弃填写</Button></ProductionConfirmDialog>{!onGuardChange&&<TransportLeaveGuard dirty={dirty} busy={command.busy} unknown={command.unknown}/>}
  </section>;
}

function TransportLeaveGuard({dirty,busy,unknown}:{dirty:boolean;busy:boolean;unknown:boolean}) {return useProductionLeave(dirty,busy,unknown).prompt;}
