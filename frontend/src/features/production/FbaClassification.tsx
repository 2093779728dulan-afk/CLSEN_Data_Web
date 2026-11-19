import { useEffect, useState } from "react";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, Dialog, FormField, Input, LinkButton, StatusMessage } from "../../design-system";
import { fbaReasons, type FbaClassificationReview, type FbaClassificationRow, type FbaReason, type FbaScope, type FbaState } from "./fbaTypes";
import type { Sku } from "./types";
import { useCommand, useLoad } from "./useProductionApi";
import styles from "./FbaWorkspace.module.css";

type Selection = { row: FbaClassificationRow } | { review: FbaClassificationReview };
type Guard = {dirty:boolean;busy:boolean;unknown:boolean};
const operations: Record<string,string> = { ASSIGN:"登记不可售", CONSUME:"恢复或冲销", CORRECT:"人工更正", REPORT_CORRECT:"报告更正", SOURCE:"更新报告依据" };
const sources = { MANUAL:"人工登记", REPORT:"报告记录", LEGACY:"历史记录" };

export function FbaClassification({ data, scope, catalog, canWrite, saved, onGuard }: {data:FbaState;scope:FbaScope;catalog:Sku[];canWrite:boolean;saved:()=>void;onGuard:(guard:Guard)=>void}) {
  const summary = data.classification_summary?.[scope.id];
  const [expanded, setExpanded] = useState(false);
  const [view, setView] = useState("current");
  const [reason, setReason] = useState("");
  const [sku, setSku] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const [selection, setSelection] = useState<Selection>();
  const { registerSensitivePurge } = useAuthzGeneration();
  useEffect(() => registerSensitivePurge(() => {setSelection(undefined);setExpanded(false);setReason("");setSku("");setFrom("");setTo("");}),[registerSensitivePurge]);
  const params = new URLSearchParams({scope_id:scope.id, view, reason_code:reason, sku_id:sku, from:view === "history" ? from : "", to:view === "history" ? to : "", page:String(page), page_size:"20"});
  const details = useLoad<{items:FbaClassificationRow[];total:number}>(`/api/production/fba/classifications?${params}`, scope.revision, expanded && !!summary?.ready);
  const label = (skuId:string) => catalog.find(item => item.sku_id === skuId)?.code || data.identities.find(item => item.scope_id === scope.id && item.sku_id === skuId)?.seller_sku || `商品${skuId}`;
  if (!summary) return null;
  return <section className={styles.classification} aria-label="不可售分类">
    {summary.ready ? <div className={styles.classificationTotals}>
      <strong>不可售分类</strong>{Object.entries(fbaReasons).filter(([code]) => code !== "UNCLASSIFIED" || BigInt(summary.totals.UNCLASSIFIED || "0") > 0n).map(([code, text]) => <Button key={code} variant="quiet" aria-pressed={expanded && reason === code} onClick={() => {setExpanded(true);setReason(code);setView("current");setPage(1);}}>{text}<strong>{BigInt(summary.totals[code as FbaReason] || "0") === 0n ? "" : summary.totals[code as FbaReason]}</strong></Button>)}
      <Button variant="quiet" aria-expanded={expanded} onClick={() => {setExpanded(!expanded);setReason("");setPage(1);}}>明细</Button>
    </div> : <StatusMessage kind="warning" title={summary.issue || "不可售分类待核对"} />}
    {summary.pending.length > 0 && <div className={styles.classificationPending} aria-label="报告分类待核对">
      {summary.pending.map(review => <div key={review.id}><span>{label(review.sku_id)} · 报告为{fbaReasons[review.reason_code]}，与人工分类不同</span>{canWrite && <Button variant="secondary" onClick={() => setSelection({review})}>核对分类</Button>}</div>)}
    </div>}
    {expanded && summary.ready && <div className={styles.workspace}>
      <div className={styles.classificationFilters}>
        <select aria-label="分类视图" value={view} onChange={event => {setView(event.target.value);setPage(1);}}><option value="current">当前未恢复</option><option value="history">处理记录</option></select>
        <select aria-label="筛选不可售原因" value={reason} onChange={event => {setReason(event.target.value);setPage(1);}}><option value="">全部原因</option>{Object.entries(fbaReasons).map(([code, text]) => <option key={code} value={code}>{text}</option>)}</select>
        <select aria-label="筛选分类商品" value={sku} onChange={event => {setSku(event.target.value);setPage(1);}}><option value="">全部商品</option>{data.identities.filter(item => item.scope_id === scope.id).map(item => <option key={item.sku_id} value={item.sku_id}>{label(item.sku_id)}</option>)}</select>
        {view === "history" && <div className={styles.classificationDates}><Input aria-label="分类开始日期" type="date" value={from} onChange={event => {setFrom(event.target.value);setPage(1);}} /><Input aria-label="分类结束日期" type="date" value={to} onChange={event => {setTo(event.target.value);setPage(1);}} /></div>}
      </div>
      {details.error && <StatusMessage kind="danger" title={details.error} />}
      {details.loading ? <p role="status">正在读取分类明细…</p> : details.value && <>
        <div className={styles.scroll}><table className={styles.table} aria-label="不可售分类明细"><thead><tr><th>商品规格</th><th>原因</th><th>{view === "current" ? "当前件数" : "变动件数"}</th><th>日期</th><th>来源</th><th>操作</th></tr></thead><tbody>
          {details.value.items.map(row => <tr key={row.id}><th scope="row">{label(row.sku_id)}</th><td>{fbaReasons[row.reason_code]}</td><td>{BigInt(row.units).toLocaleString("zh-CN")}</td><td>{row.business_date}</td><td><details><summary>{view === "history" ? operations[row.operation_kind] || row.operation_kind : sources[row.source_kind]}</summary><div className={styles.classificationEvidence}><span>{row.actor_name} · {row.occurred_at}</span>{row.raw_disposition && <span>原始处置 {row.raw_disposition}</span>}{row.manual_override && <span>已人工核对分类</span>}<span>{row.note}</span>{row.batch_id && <LinkButton to={`/production/warehouses/${scope.warehouse_id}?owner=${scope.owner_id}&tab=stock&fba_view=receipts&fba_batch=${row.batch_id}`}>查看接收原件</LinkButton>}{row.report_version_id && <LinkButton to="/ledger/published-details">查看已发布报告</LinkButton>}</div></details></td><td>{canWrite && view === "current" && <Button variant="quiet" onClick={() => setSelection({row})}>更正分类</Button>}</td></tr>)}
          {!details.value.items.length && <tr><td colSpan={6}>暂无记录</td></tr>}
        </tbody></table></div>
        <div className={styles.actions}><span>共{details.value.total}条</span><Button disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</Button><span>{page}</span><Button disabled={page * 20 >= details.value.total} onClick={() => setPage(page + 1)}>下一页</Button></div>
      </>}
    </div>}
    {selection && <ClassificationCorrection key={"row" in selection ? selection.row.id : selection.review.id} selection={selection} scope={scope} label={label("row" in selection ? selection.row.sku_id : selection.review.sku_id)} data={summary.items} close={() => setSelection(undefined)} saved={saved} onGuard={onGuard} />}
  </section>;
}

function ClassificationCorrection({selection,scope,label,data,close,saved,onGuard}:{selection:Selection;scope:FbaScope;label:string;data:FbaClassificationRow[];close:()=>void;saved:()=>void;onGuard:(guard:Guard)=>void}) {
  const row = "row" in selection ? selection.row : undefined;
  const review = "review" in selection ? selection.review : undefined;
  const [target, setTarget] = useState<FbaReason>(row?.reason_code === "WAREHOUSE_DAMAGED" ? "CUSTOMER_DAMAGED" : "WAREHOUSE_DAMAGED");
  const [units, setUnits] = useState(row?.units || "");
  const [note, setNote] = useState("");
  const [acceptReport, setAcceptReport] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const command = useCommand<FbaState>(() => {close();saved();});
  const disabled = command.busy || command.unknown;
  const dirty = !!note || acceptReport || units !== (row?.units || "");
  useEffect(() => {onGuard({dirty,busy:command.busy,unknown:command.unknown});},[dirty,command.busy,command.unknown,onGuard]);
  useEffect(() => () => onGuard({dirty:false,busy:false,unknown:false}),[onGuard]);
  const quantityError = !!row && (!/^[1-9][0-9]*$/.test(units) || BigInt(units) > BigInt(row.units));
  return <Dialog open title={review ? "核对报告分类" : "更正不可售原因"} size="medium" dismissDisabled={disabled} closeOnOutsideClick={false} onOpenChange={open => {if (!open) close();}}>
    <form className={styles.workspace} onSubmit={event => {event.preventDefault();setAttempted(true);if (!note.trim() || quantityError) {event.currentTarget.querySelector<HTMLElement>('input')?.focus();return;}command.submit("/api/production/fba/commands/classification-correct",{scope_id:scope.id,expected_revision:scope.revision,sku_id:row?.sku_id || review?.sku_id,reason:note,...(row ? {origin_event_id:row.origin_event_id,from_reason:row.reason_code,reason_code:target,units} : {review_id:review?.id,accept_report:acceptReport})});}}>
      <strong>{label}</strong>
      {row ? <><FormField label="更正为"><select disabled={disabled} value={target} onChange={event => setTarget(event.target.value as FbaReason)}>{Object.entries(fbaReasons).filter(([code]) => code !== row.reason_code).map(([code, text]) => <option key={code} value={code}>{text}</option>)}</select></FormField><FormField label={`本次更正件数（最多${row.units}件）`}><Input aria-invalid={attempted && quantityError} inputMode="numeric" disabled={disabled} value={units} onChange={event => setUnits(event.target.value)} /></FormField></> : <>
        <p>当前 {data.filter(item => item.sku_id === review?.sku_id && item.origin_event_id === review.origin_event_id).map(item => `${fbaReasons[item.reason_code]} ${item.units}件`).join(" · ") || "已全部处理"}</p><p>报告 {review && fbaReasons[review.reason_code]} · {review?.raw_disposition}</p>
        <div className={styles.qualityModes}><Button aria-pressed={!acceptReport} disabled={disabled} onClick={() => setAcceptReport(false)}>保留人工分类</Button><Button aria-pressed={acceptReport} disabled={disabled} onClick={() => setAcceptReport(true)}>采用报告分类</Button></div><LinkButton to="/ledger/published-details">查看已发布报告</LinkButton>
      </>}
      <FormField label="核对说明"><Input aria-invalid={attempted && !note.trim()} disabled={disabled} value={note} onChange={event => setNote(event.target.value)} /></FormField>
      {attempted && (quantityError || !note.trim()) && <StatusMessage kind="danger" title={quantityError ? "请填写当前可归属范围内的整数数量" : "请填写核对说明"} />}
      {command.feedback}<div className={styles.actions}><Button disabled={disabled} onClick={close}>取消</Button><Button variant="primary" type="submit" disabled={disabled}>保存分类</Button></div>
    </form>
  </Dialog>;
}
