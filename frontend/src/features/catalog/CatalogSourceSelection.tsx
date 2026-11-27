import { Disclosure } from "../../design-system";
import { ProductionConfirmDialog } from "../production/ProductionConfirmDialog";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import type { CatalogDraftSaveAction } from "./catalogTypes";
import { CatalogImportPage } from "./CatalogImportPage";
import { skuSuggestion } from "./catalogReviewSuggestions";
import { useProductionLeave } from "../production/useProductionLeave";
import { ApiRequestError, commandApi, createOperationKey, writeApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, Dialog, FormField, Input, Select, StatusMessage } from "../../design-system";
import type { CatalogUnmatchedItem } from "./catalogApi";
import { useCatalogNavigation } from "./CatalogNavigationContext";
import styles from "./CatalogOperations.module.css";

type Sku = { code_status?: string; sku_id: number; style_id: number; style_code: string; internal_display_sku: string | null; standard_color: string; standard_size: string };
type Candidate = { import_id: number; status: string; workflow_revision: number; review_path: string; source_name: string; report_selection?: boolean };
type Context = { source: string; scope_id: number; catalog_publication_revision: number; skus: Sku[]; candidates: Candidate[]; mapped_sku_id: number | null; mapped_style_id?: number | null; excluded: boolean; evidence: { scopes: { seller_account_display_name: string; marketplace_scope_code: string }[]; observations: { report_type: string; report_date: string; source_row_id: number; version_id: number }[] } };
type Preview = { preview_digest: string; source: string; created_style_count: number; created_sku_count: number; mapping_count: number; excluded_count: number; kept_sku_count: number };
const activeStates = new Set(["needs_attention", "validated", "ready_for_approval", "rejected"]);
const stateLabels: Record<string, string> = { needs_attention: "待补全", validated: "已校验", ready_for_approval: "待批准", rejected: "已退回", superseded: "已有后继", withdrawn: "已撤回", approved: "已批准" };
function message(error: unknown) { return error instanceof Error && /[\u3400-\u9fff]/.test(error.message) ? error.message : "处理未完成，请检查连接后重试；当前输入保留。"; }

export function CatalogSourceSelection({ item, onClose }: { item: CatalogUnmatchedItem; onClose: () => void }) {
  const { generation, registerSensitivePurge } = useAuthzGeneration();
  const epoch = useRef(0);
  const location = useLocation();
  const { setReviewReturn } = useCatalogNavigation();
  const [review,setReview]=useState<number>();const [approved,setApproved]=useState(false);
  const [saveAction,setSaveAction]=useState<CatalogDraftSaveAction>();
  const [reviewGuard,setReviewGuard]=useState({dirty:false,busy:false,unknown:false});
  const [dirty,setDirty]=useState(false);const [confirmed,setConfirmed]=useState(false);const [closing,setClosing]=useState(false);
  const [context, setContext] = useState<Context>();
  const [attempt, setAttempt] = useState(0);
  const [action, setAction] = useState("map");
  const [sku, setSku] = useState("");
  const [query, setQuery] = useState("");
  const [spec, setSpec] = useState({ style_code: "", color: "", size: "" });
  const [reason, setReason] = useState("");
  const [replacement, setReplacement] = useState<Candidate>();
  const [preview, setPreview] = useState<Preview>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState<{ token: string; body: Record<string, unknown> }>();
  const [unknown, setUnknown] = useState(false);
  const source = { source_key: item.source_identity.seller_sku_match, scope_id: item.source_identity.report_source_scope_id, version_ids: item.published_version_ids.map(Number) };
  const sourceJson = JSON.stringify(source);
  useEffect(() => registerSensitivePurge(() => { ++epoch.current; setContext(undefined); setPreview(undefined); setPending(undefined); setSpec({ style_code: "", color: "", size: "" }); setReason(""); setQuery(""); setSku(""); setError(undefined); onClose(); }), [registerSensitivePurge, onClose]);
  useEffect(() => {
    const controller = new AbortController(); const ticket = ++epoch.current;
    setContext(undefined); setError(undefined); setPreview(undefined);
    void writeApi<Context>("/api/catalog/unmatched/selection-context", { body: JSON.parse(sourceJson), idempotent: false, signal: controller.signal }).then(value => { if (ticket === epoch.current && !controller.signal.aborted) {
      setContext(value);const exact=value.skus.filter(row=>row.internal_display_sku===value.source&&(!row.code_status||row.code_status==='confirmed'));
      const suggestion=skuSuggestion(value.source);
      const sameSpec=suggestion?value.skus.filter(row=>row.style_code===suggestion.style_code&&row.standard_color===suggestion.color&&row.standard_size===suggestion.size&&(!row.code_status||row.code_status==='confirmed')):[];
      if(exact.length===1||exact.length===0&&sameSpec.length===1){setAction('map');setSku(String((exact.length===1?exact[0]:sameSpec[0])!.sku_id));}else if(suggestion&&sameSpec.length===0&&exact.length===0){setAction('create');setSpec(suggestion);}
      setReason('按当前已发布来源核对本次商品候选，原报告版本与原行证据完整保留');setDirty(false);setConfirmed(false);
    } }).catch(e => { if (ticket === epoch.current && !controller.signal.aborted) setError(message(e)); });
    return () => { controller.abort(); if (epoch.current === ticket) epoch.current = ticket + 1; };
  }, [generation, sourceJson, attempt]);
  function changed() { setDirty(true);setConfirmed(false);setPreview(undefined); setPending(undefined); setError(undefined); }
  const locked = busy || unknown || reviewGuard.busy || reviewGuard.unknown;
  const leave=useProductionLeave(dirty||reviewGuard.dirty,busy||reviewGuard.busy,unknown||reviewGuard.unknown);
  function requestClose(){if(locked)return;if(dirty||reviewGuard.dirty)setClosing(true);else onClose();}
  const target = context?.skus.find(row => String(row.sku_id) === sku);
  const active = context?.candidates.filter(row => activeStates.has(row.status)) ?? [];
  const mustContinue = active.some(row => row.import_id !== replacement?.import_id);
  const command = { ...source, action, selected_sku_id: action === "map" ? Number(sku) || null : null, ...spec, reason, expected_catalog_publication_revision: context?.catalog_publication_revision, replace_import_id: replacement?.import_id ?? null, expected_workflow_revision: replacement?.workflow_revision ?? null };
  async function prepareCandidate(){
    if(locked||mustContinue||!confirmed)return;
    const ticket=epoch.current;setBusy(true);setError(undefined);
    const snapshot={...command};
    try{
      const checked=await writeApi<Preview>("/api/catalog/unmatched/selection-preview",{body:snapshot,idempotent:false});
      if(ticket!==epoch.current)return;
      setPreview(checked);const token=createOperationKey();await save({token,body:{...snapshot,preview_digest:checked.preview_digest,operation_token:token}});
    }catch(e){if(ticket===epoch.current)setError(message(e));}finally{if(ticket===epoch.current)setBusy(false);}
  }
  async function save(saved?: typeof pending) {
    if (!preview && !saved) return;
    const ticket = epoch.current;
    const transaction = saved ?? (() => { const token = createOperationKey(); return { token, body: { ...command, preview_digest: preview!.preview_digest, operation_token: token } }; })();
    setPending(transaction); setBusy(true); setError(undefined);
    try {
      const result = await commandApi<{ import_id: number }>("/api/catalog/unmatched/selection-candidates", transaction.body, transaction.token);
      if (ticket === epoch.current) { setUnknown(false);setDirty(false);setPending(undefined);setApproved(false);setReviewReturn(`${location.pathname}${location.search}`);setReview(result.import_id); }
    } catch (e) { if (ticket === epoch.current) { setError(message(e)); const uncertain = !(e instanceof ApiRequestError && e.status < 500); setUnknown(uncertain); if (!uncertain) { setPreview(undefined); setPending(undefined); } } }
    finally { if (ticket === epoch.current) setBusy(false); }
  }
  return <Dialog open title={review?"审核商品归属":"确认这条来源对应什么商品"} size="large" contentClassName={styles.guidedDialog} dismissDisabled={locked} closeOnOutsideClick={false} onOpenChange={open=>{if(!open)requestClose();}}>
    <div className={styles.guidedFlow}>
      <ol className={styles.guidedSteps} aria-label="归属处理步骤"><li aria-current={!review?'step':undefined}>1 核对商品</li><li aria-current={review?'step':undefined}>2 审核并批准</li></ol>
      <div className={styles.guidedContent}>
      <ProductionConfirmDialog open={closing} onOpenChange={setClosing} title="还有未保存的内容" description="继续处理，或放弃尚未保存的输入后返回清单。"><Button onClick={()=>setClosing(false)}>继续处理</Button><Button variant="danger" disabled={locked} onClick={onClose}>放弃输入并返回清单</Button></ProductionConfirmDialog>
      {review?<CatalogImportPage key={review} embeddedId={review} onSaveAction={setSaveAction} onGuardChange={setReviewGuard} onNavigate={id=>{setApproved(false);setReview(id);}} onCompleted={()=>setApproved(true)}/>:<>
      {error&&<StatusMessage kind="danger" title="本条处理未完成">{error}</StatusMessage>}
      {!context?<><p role="status">正在读取来源与商品建议…</p>{error&&<Button onClick={()=>setAttempt(v=>v+1)}>重新读取来源</Button>}</>:<>
        <header className={styles.selectionIntro}><strong>{context.source}</strong><p>核对下面的处理方式和商品信息。系统填写候选，批准后才会生效。</p></header>
        {context.candidates.length>0&&<section aria-label="本条已有候选"><h3>继续已有处理</h3>{context.candidates.map(row=><p key={row.import_id}><Button disabled={locked||dirty} onClick={()=>{setDirty(false);setReview(row.import_id);setApproved(false);}}>继续审核 · 批次{row.import_id} · {stateLabels[row.status]??row.status}</Button>{row.report_selection&&activeStates.has(row.status)&&<Button variant="quiet" disabled={locked} onClick={()=>{changed();setReplacement(row);}}>重新核对并保留原候选</Button>}</p>)}{replacement&&<p>将替代批次{replacement.import_id}，原记录与审核历史继续保留。</p>}</section>}
        {context.mapped_sku_id?<StatusMessage kind="info" title="此来源已有生效关联"><Link to={context.mapped_style_id?`/catalog/styles/${context.mapped_style_id}`:'/catalog'}>查看已关联商品</Link></StatusMessage>:context.excluded?<StatusMessage kind="info" title="此来源已审核排除，可从目录维护更正"/>:<>
          {mustContinue&&<StatusMessage kind="warning" title="已有候选，请从上方继续审核，避免重复建档"/>}
          <fieldset disabled={locked||mustContinue} className={styles.selectionForm}>
            <div className={styles.choiceGrid} role="radiogroup" aria-label="处理方式">{[['map','关联已有商品','商品已建档，核对具体规格'],['create','新建或补充规格','系统预填，确认款号、颜色、尺码'],['exclude','不纳入商品目录','填写排除原因，保留报告事实']].map(([value,label,help])=><label key={value}><input type="radio" name="source-action" value={value} checked={action===value} onChange={()=>{changed();setAction(value!);setReason(value==='exclude'?'':'按当前已发布来源核对本次商品候选，原报告版本与原行证据完整保留');}}/><strong>{label}</strong><span>{help}</span></label>)}</div>
            {action==='map'?<><FormField label="查找已有商品"><Input value={query} onChange={e=>setQuery(e.target.value)} placeholder="款号、SKU、颜色或尺码"/></FormField><FormField label="实际商品规格（必选）"><Select value={sku} onChange={e=>{changed();setSku(e.target.value);}}><option value="">请选择实际商品规格</option>{context.skus.filter(row=>String(row.sku_id)===sku||`${row.style_code} ${row.internal_display_sku??''} ${row.standard_color} ${row.standard_size}`.toLowerCase().includes(query.toLowerCase())).map(row=><option key={row.sku_id} value={row.sku_id} disabled={!!row.code_status&&row.code_status!=='confirmed'}>{row.style_code}-{row.standard_color}-{row.standard_size}</option>)}</Select></FormField>{target&&<p>将关联已有规格：{target.style_code}-{target.standard_color}-{target.standard_size}</p>}</>:action==='create'?<><p>已按来源编码预填可识别字段，请按实际商品核对；有误可直接修改。</p><div className={styles.specGrid}>{([['style_code','款号'],['color','颜色'],['size','尺码']] as const).map(([key,label])=><FormField key={key} label={`${label}（必填）`}><Input value={spec[key]} onChange={e=>{changed();setSpec(v=>({...v,[key]:e.target.value}));}}/></FormField>)}</div></>:<p>排除保留销售和退货原事实，须填写具体原因。</p>}
            {action==='exclude'?<FormField label="排除依据（至少10字）"><Input value={reason} onChange={e=>{changed();setReason(e.target.value);}}/></FormField>:<Disclosure><summary>查看或补充处理依据</summary><FormField label="处理依据（必填，至少10字）"><Input value={reason} onChange={e=>{changed();setReason(e.target.value);}}/></FormField></Disclosure>}
            <label className={styles.confirmChoice}><input type="checkbox" checked={confirmed} onChange={e=>{setConfirmed(e.target.checked);setDirty(true);}}/>已核对以上商品信息与处理方式</label>
          </fieldset>
        </>}
        <Disclosure className={styles.sourceEvidence}><summary>查看原报告、店铺及行证据</summary><p>{context.evidence.scopes.map(scope=>`${scope.seller_account_display_name} · ${scope.marketplace_scope_code}`).join('、')}</p><ul>{context.evidence.observations.map((row,index)=><li key={index}>{row.report_type==='business_report'?'经营报告':'退货报告'} · {row.report_date} · 版本#{row.version_id} · 原行记录#{row.source_row_id}</li>)}</ul>{preview&&<p>本次新增{preview.created_sku_count}规格，关联{preview.mapping_count}条，排除{preview.excluded_count}条；保留原{preview.kept_sku_count}个SKU。</p>}</Disclosure>
      </>}
      {unknown&&<StatusMessage kind="warning" title="保存结果尚未确认">请使用底部按钮核实原操作，输入和原操作编号已保留。</StatusMessage>}
      </>}
      {leave.prompt}
      </div>
      <footer className={styles.guidedFooter}><Button disabled={locked} variant="secondary" onClick={requestClose}>{review?'关闭，稍后继续':'返回来源清单'}</Button>{unknown?<Button variant="primary" disabled={busy} onClick={()=>void save(pending)}>查询本次保存结果</Button>:review?saveAction?<Button variant="primary" disabled={saveAction.disabled} onClick={saveAction.run}>{saveAction.label}</Button>:approved&&<Button variant="primary" disabled={locked} onClick={requestClose}>完成并返回清单</Button>:context&&!context.mapped_sku_id&&!context.excluded&&<Button variant="primary" disabled={locked||mustContinue||!confirmed||reason.trim().length<10||(action==='map'&&!sku)||(action==='create'&&Object.values(spec).some(v=>!v.trim()))} onClick={()=>void prepareCandidate()}>生成候选并审核</Button>}</footer>
    </div>
  </Dialog>;
}
