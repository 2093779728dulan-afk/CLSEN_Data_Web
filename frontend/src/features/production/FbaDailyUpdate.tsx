import { Disclosure } from "../../design-system";
import { useBusinessToday } from "./workbenchDate";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, Dialog, FormField, Input, LinkButton, Pagination, StatusMessage, Table } from "../../design-system";
import { useCommand } from "./useProductionApi";
import { useProductionLeave } from "./useProductionLeave";
import { fbaReasons, type FbaReason, type FbaDailyIssue, type FbaScope, type FbaState } from "./fbaTypes";
import { FbaStocktake } from "./FbaStocktake";
import { FbaClassification } from "./FbaClassification";
import type { Sku } from "./types";
import styles from "./FbaWorkspace.module.css";

const api = "/api/production/fba";

export function FbaDailyUpdate({ data, scope, catalog, saved, canWrite, actions, showStatus = false }: {
  data: FbaState; scope: FbaScope; catalog: Sku[]; saved: () => void; canWrite: boolean; actions: ReactNode; showStatus?: boolean;
}) {
  const [quality, setQuality] = useState(false);
  const [stocktake, setStocktake] = useState(false);
  const [countGuard, setCountGuard] = useState({ dirty: false, busy: false, unknown: false });
  const [syncIssues, setSyncIssues] = useState<FbaDailyIssue[]>([]);
  const [syncComplete, setSyncComplete] = useState(false);
  const [qualityGuard, setQualityGuard] = useState({ dirty: false, busy: false, unknown: false });
  const [classificationGuard, setClassificationGuard] = useState({ dirty: false, busy: false, unknown: false });
  const { registerSensitivePurge } = useAuthzGeneration();
  useEffect(() => registerSensitivePurge(() => {
    setSyncIssues([]); setSyncComplete(false); setQuality(false); setStocktake(false);
  }), [registerSensitivePurge]);
  const daily = data.daily?.[scope.id];
  const sync = useCommand<FbaState | { updated: FbaState; issues: FbaDailyIssue[] }>(result => {
    // The original Java command receipt returns inventory state directly.
    const issues = "issues" in result ? result.issues : [];
    setSyncIssues(issues);
    setSyncComplete(issues.length === 0);
    saved();
  });
  const leave = useProductionLeave(qualityGuard.dirty || classificationGuard.dirty || countGuard.dirty, sync.busy || qualityGuard.busy || classificationGuard.busy || countGuard.busy, sync.unknown || qualityGuard.unknown || classificationGuard.unknown || countGuard.unknown);
  return <>
    {leave.prompt}
    {!showStatus && <><div className={styles.balanceToolbar}>
      {canWrite && <><Button variant="secondary" onClick={() => setStocktake(true)}>调整库存</Button><Button variant="secondary" onClick={() => setQuality(true)}>调整可售状态</Button></>}
      {actions}
    </div>
    <FbaClassification data={data} scope={scope} catalog={catalog} canWrite={canWrite} saved={saved} onGuard={setClassificationGuard} /></>}
    {showStatus && <section className={styles.workspace} aria-label="库存更新">
      <header className={styles.updateHeader}><h2>库存更新</h2><div className={styles.actions}>
        <LinkButton to="/ledger/published-details">查看已发布日报</LinkButton>
        {canWrite && <Button variant="primary" disabled={sync.busy || sync.unknown} onClick={() => {
          setSyncComplete(false); setSyncIssues([]); sync.submit(`${api}/daily/sync?scope_id=${scope.id}`, {});
        }}>重试库存更新</Button>}
      </div></header>
      {daily && daily.report_count > 0 && <div>日报销售 {daily.sales_units} 件 · 最近报告 {daily.latest_report_on}</div>}
      {sync.feedback}
      {syncComplete && <StatusMessage kind={daily?.issues.length ? "warning" : "success"} title={daily?.issues.length ? "已核对，仍有待处理记录" : "库存同步已完成"} />}
      <DailyIssues key={scope.id} issues={daily?.issues.length ? daily.issues : syncIssues} />
    </section>}
    <FbaStocktake open={stocktake} close={() => setStocktake(false)} data={data} scope={scope} catalog={catalog} saved={saved} onGuard={setCountGuard} />
    <FbaQuality open={quality} close={() => setQuality(false)} data={data} scope={scope} catalog={catalog} saved={saved} onGuard={setQualityGuard} />
  </>;
}

function DailyIssues({issues}:{issues:FbaDailyIssue[]}) {
  const [open,setOpen]=useState(false); const [page,setPage]=useState(1); const [query,setQuery]=useState("");
  const groups=useMemo(()=>{
    const result=new Map<string,{sku:string;message:string;records:FbaDailyIssue[]}>();
    for(const issue of issues){
      const key=JSON.stringify([issue.sku_id||issue.seller_sku||"",issue.code||issue.label]);
      const group=result.get(key)||{sku:issue.seller_sku||"",message:issue.message||issue.label,records:[]};
      group.records.push(issue); result.set(key,group);
    }
    return [...result.entries()];
  },[issues]);
  if(!issues.length)return null;
  const filtered=groups.filter(([,group])=>(group.sku+" "+group.message).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const pages=Math.max(1,Math.ceil(filtered.length/20)),current=Math.min(page,pages);
  return <Disclosure className={styles.issueSummary} open={open} onToggle={event=>setOpen(event.currentTarget.open)}>
    <summary>待处理 {issues.length} 条 · {groups.length} 组</summary>
    {open&&<><Input type="search" aria-label="查找待处理SKU或问题" placeholder="SKU、问题" value={query} onChange={event=>{setQuery(event.target.value);setPage(1);}}/><Table className={styles.issueTable} title="日报待处理项目"><thead><tr><th>SKU</th><th>问题</th><th>记录数</th><th>明细</th></tr></thead><tbody>
      {filtered.slice((current-1)*20,current*20).map(([key,group])=><tr key={key}><th scope="row">{group.sku}</th><td>{group.message}</td><td>{group.records.length}</td><td><DailyIssueRecords records={group.records}/></td></tr>)}
    </tbody></Table><Pagination page={current} totalItems={filtered.length} totalPages={pages} onPageChange={setPage} itemLabel="组"/></>}
  </Disclosure>;
}
function DailyIssueRecords({records}:{records:FbaDailyIssue[]}) {
  const [open,setOpen]=useState(false);
  return <Disclosure className={styles.issueRecords} onToggle={event=>setOpen(event.currentTarget.open)}><summary>记录</summary>{open&&records.map((record,index)=><div key={index}>{record.label}</div>)}</Disclosure>;
}

function FbaQuality({ open, close, data, scope, catalog, saved, onGuard }: {
  open: boolean; close: () => void; data: FbaState; scope: FbaScope; catalog: Sku[]; saved: () => void;
  onGuard: (guard: {dirty:boolean;busy:boolean;unknown:boolean}) => void;
}) {
  const [target, setTarget] = useState<"DEFECTIVE" | "QUALIFIED">("DEFECTIVE");
  const today = useBusinessToday();
  const [values, setValues] = useState<Record<string, string>>({});
  const [allocations, setAllocations] = useState<Record<string, Partial<Record<FbaReason, string>>>>({});
  const [defaultReason, setDefaultReason] = useState<FbaReason>("WAREHOUSE_DAMAGED");
  const [overrides, setOverrides] = useState<Record<string, FbaReason>>({});
  const [reason, setReason] = useState("");
  const [query, setQuery] = useState("");
  const [attempted, setAttempted] = useState(false);
  const command = useCommand<FbaState>(() => { setValues({}); setAllocations({}); setOverrides({}); setReason(""); setQuery(""); setAttempted(false); close(); saved(); });
  const restoring = target === "QUALIFIED";
  const summary = data.classification_summary?.[scope.id];
  const unavailable = summary?.ready === false;
  const quantityLabel = restoring ? "本次恢复数量" : "本次标记数量";
  const rows = data.identities.filter(item => item.scope_id === scope.id && BigInt(restoring ? item.unsellable : item.sellable) > 0n).map(item => {
    const label = catalog.find(sku => sku.sku_id === item.sku_id)?.code || item.seller_sku;
    const sources = new Map<FbaReason, bigint>();
    for (const part of summary?.items || []) if (part.sku_id === item.sku_id) sources.set(part.reason_code, (sources.get(part.reason_code) || 0n) + BigInt(part.units));
    if (!summary && BigInt(item.unsellable) > 0n) sources.set("UNCLASSIFIED", BigInt(item.unsellable));
    const multiple = restoring && sources.size > 1;
    const parts = [...sources].map(([code, available]) => {
      const value = allocations[item.sku_id]?.[code] || "";
      const units = /^[1-9][0-9]*$/.test(value) ? BigInt(value) : 0n;
      const error = !value ? "" : !units ? "请输入大于0的整数" : units > available ? `最多可恢复${available}件` : "";
      return { code, available, value, units, error };
    });
    const value = values[item.sku_id] || "";
    const units = multiple ? parts.reduce((sum, part) => sum + part.units, 0n) : /^[1-9][0-9]*$/.test(value) ? BigInt(value) : 0n;
    const available = BigInt(restoring ? item.unsellable : item.sellable);
    const error = multiple ? parts.find(part => part.error)?.error || "" : !value ? "" : !units ? "请输入大于0的整数" : units > available ? `最多可${restoring ? "恢复" : "标记"}${available}件` : "";
    const code = overrides[item.sku_id] || defaultReason;
    return { item, label, value, units, error, code, sources, multiple, parts };
  });
  const lines = rows.filter(row => row.units > 0n && !row.error).map(row => ({ sku_id: row.item.sku_id, units: row.units.toString(),
    ...(restoring ? { reason_allocations: row.multiple ? row.parts.filter(part => part.units > 0n).map(part => ({ reason_code: part.code, units: part.units.toString() })) : [...row.sources.keys()].map(code => ({ reason_code: code, units: row.units.toString() })) } : { reason_code: row.code }),
  }));
  const invalid = rows.some(row => !!row.error);
  const needsNote = !restoring && rows.some(row => row.units > 0n && row.code === "OTHER");
  const total = lines.reduce((sum, line) => sum + BigInt(line.units), 0n).toLocaleString("zh-CN");
  const confirmLabel = lines.length ? `确认${restoring ? "恢复" : "标记"}${total}件${restoring ? "可售" : "不可售"}` : `确认${restoring ? "恢复可售" : "标记不可售"}`;
  const visibleRows = rows.filter(row => `${row.label} ${row.item.seller_sku}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const hiddenFilled = rows.filter(row => row.units > 0n && !visibleRows.includes(row)).length;
  const dirty = Object.values(values).some(Boolean) || Object.values(allocations).some(parts => Object.values(parts).some(Boolean)) || !!reason;
  useEffect(() => { onGuard({dirty:open && dirty,busy:command.busy,unknown:command.unknown}); }, [open,dirty,command.busy,command.unknown,onGuard]);
  const disabled = command.busy || command.unknown;
  return <Dialog open={open} title="调整可售状态" size="large" dismissDisabled={disabled} closeOnOutsideClick={false} onOpenChange={value => { if (!value) close(); }}>
    <form className={`${styles.workspace} ${styles.qualityForm}`} onSubmit={event => {
      event.preventDefault(); setAttempted(true);
      if (!lines.length || invalid || needsNote && !reason.trim() || unavailable) {
        const form = event.currentTarget;
        if (invalid) setQuery("");
        requestAnimationFrame(() => {
          const input = form.querySelector<HTMLElement>('[aria-invalid="true"]') || form.querySelector<HTMLElement>('input[inputmode="numeric"]');
          input?.scrollIntoView?.({ block: "center" }); input?.focus();
        });
        return;
      }
      command.submit(`${api}/commands/quality`, { scope_id: scope.id, expected_revision: scope.revision,
        from_quality: restoring ? "DEFECTIVE" : "QUALIFIED", target_quality: target, lines, business_date: today(), reason: reason.trim() || "人工核对FBA库存状态" });
    }}>
      <div className={styles.qualityModes} role="group" aria-label="可售状态操作">
        {([["DEFECTIVE", "标记不可售"], ["QUALIFIED", "恢复可售"]] as const).map(([value, label]) => <Button key={value} variant="quiet" aria-pressed={target === value} disabled={disabled} onClick={() => {
          if (target === value) return;
          setTarget(value); setValues({}); setAllocations({}); setQuery(""); setAttempted(false);
        }}>{label}</Button>)}
      </div>
      {unavailable && <StatusMessage kind="danger" title={summary.issue || "分类数据需要核对"} />}
      <div className={styles.classificationFilters}>
        <Input type="search" aria-label="查找要调整的商品" placeholder="搜索款号、颜色或尺码" value={query} onChange={event => setQuery(event.target.value)} />
        {!restoring && <FormField label="统一原因"><select disabled={disabled} value={defaultReason} onChange={event => setDefaultReason(event.target.value as FbaReason)}>{Object.entries(fbaReasons).filter(([code]) => code !== "UNCLASSIFIED").map(([code, label]) => <option value={code} key={code}>{label}</option>)}</select></FormField>}
      </div>
      <div className={`${styles.scroll} ${styles.qualityTableScroll}`}><table className={`${styles.table} ${styles.qualityTable}`} aria-label="商品可售状态调整"><thead><tr><th>商品规格</th><th>可售</th><th>不可售</th><th>{quantityLabel}</th><th>原因</th></tr></thead><tbody>{visibleRows.map(({ item, label, value, units, error, code, sources, multiple, parts }) => <tr key={item.sku_id}>
        <th scope="row">{label}</th><td>{item.sellable}</td><td>{item.unsellable}</td>
        <td>{multiple ? <div className={styles.reasonAllocations}>{parts.map(part => <label key={part.code}>{fbaReasons[part.code]} <span>余{part.available.toString()}</span><Input aria-label={`${item.seller_sku} ${fbaReasons[part.code]}恢复数量`} aria-invalid={!!part.error} inputMode="numeric" placeholder="件数" disabled={disabled} value={part.value} onChange={event => setAllocations(previous => ({ ...previous, [item.sku_id]: { ...previous[item.sku_id], [part.code]: event.target.value } }))} />{part.error && <span className={styles.fieldError}>{part.error}</span>}</label>)}</div> : <Input aria-label={`${item.seller_sku} ${quantityLabel}`} aria-invalid={!!error} aria-describedby={error ? `quality-error-${item.sku_id}` : undefined} inputMode="numeric" placeholder="件数" disabled={disabled} value={value} onChange={event => setValues(previous => ({ ...previous, [item.sku_id]: event.target.value }))} />}
          {error && !multiple && <span id={`quality-error-${item.sku_id}`} className={styles.fieldError}>{error}</span>}
          {units > 0n && !error && <span className={styles.qualityPreview}>调整后 可售{(BigInt(item.sellable) + (restoring ? units : -units)).toString()} · 不可售{(BigInt(item.unsellable) + (restoring ? -units : units)).toString()}</span>}
        </td>
        <td>{restoring ? multiple ? "分别填写恢复量" : fbaReasons[[...sources.keys()][0] || "UNCLASSIFIED"] : <select aria-label={`${item.seller_sku} 不可售原因`} disabled={disabled} value={overrides[item.sku_id] || ""} onChange={event => setOverrides(previous => { const next = { ...previous }; if (event.target.value) next[item.sku_id] = event.target.value as FbaReason; else delete next[item.sku_id]; return next; })}><option value="">统一 · {fbaReasons[code]}</option>{Object.entries(fbaReasons).filter(([key]) => key !== "UNCLASSIFIED").map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>}</td>
      </tr>)}{!visibleRows.length && <tr><td colSpan={5}>{query.trim() ? "没有匹配的商品规格" : restoring ? "当前没有需要恢复可售的商品" : "当前没有可标记为不可售的商品"}</td></tr>}</tbody></table></div>
      <FormField label={needsNote ? "其他原因说明" : "备注（可选）"}><Input aria-invalid={attempted && needsNote && !reason.trim()} disabled={disabled} placeholder={restoring ? "例如 已检查合格" : "补充说明"} value={reason} onChange={event => setReason(event.target.value)} /></FormField>
      {attempted && (!lines.length || invalid || needsNote && !reason.trim()) && <StatusMessage kind="danger" title={needsNote && !reason.trim() ? "请填写其他原因说明" : "请核对商品数量"} />}
      {command.feedback}
      {invalid && rows.some(row => row.error && !visibleRows.includes(row)) && <Button variant="quiet" onClick={() => {setQuery("");requestAnimationFrame(() => document.querySelector<HTMLElement>('[role="dialog"] [aria-invalid="true"]')?.focus());}}>查看数量错误</Button>}
      <div className={`${styles.actions} ${styles.qualityActions}`}>
        <span aria-live="polite">{lines.length ? `${lines.length}个规格 · 共${total}件` : "填写本次需要处理的件数"}{hiddenFilled > 0 && ` · 筛选外已填${hiddenFilled}项`}</span>
        <div className={styles.actions}><Button disabled={disabled} onClick={close}>取消</Button><Button type="submit" variant="primary" disabled={disabled || invalid || unavailable}>{confirmLabel}</Button></div>
      </div>
    </form>
  </Dialog>;
}
