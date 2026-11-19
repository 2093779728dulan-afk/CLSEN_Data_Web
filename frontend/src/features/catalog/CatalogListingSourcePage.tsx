import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiRequestError, commandApi, createOperationKey, requestApi, writeApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { LinkButton, Button, FormField, Input, Select, StatusMessage  } from "../../design-system";
import styles from "./CatalogOperations.module.css";
import css from "./CatalogListingSourcePage.module.css";
import { CatalogProductIntakePanel } from "./CatalogProductIntakePanel";
import { checkProductUpload, intakeSelections } from "./catalogIntake";

export type Spec = { style_code: string; color: string; size: string };
export type SourceRow = { registration?: { state: string; sku_id?: number | null }; cell_locations?: Record<string, string>; format_issues?: { sheet: string; row: number; cell: string; severity?: "error" | "warning"; code: string; message: string; original: string }[]; row_id: string; sheet: string; row: number; seller_sku: string; asin?: string; child_asin?: string; parent_asin?: string; fnsku?: string; issues: string[]; cell_types: Record<string, string>; suggestion?: Spec | null; suggested_type: "unknown" | "variant" | "parent" };
export type Selection = Spec & { row_id: string; include: boolean; record_type: "unknown" | "parent" | "variant"; selected_sku_id: number | null; use_official: boolean; confirm_raw_parent: boolean; note: string };
type Observation = { report_type: string; report_date: string; event_date?: string | null; dataset_id: number; version_id: number; source_row_id: number; child_asin?: string; parent_asin?: string; fnsku?: string };
export type Assessment = { row_id: string; state: string; message: string; scope_id?: number; official_asins: string[]; official_parent_asins: string[]; official_fnskus: string[]; observations: Observation[]; duplicate_rows: string[]; primary_row: string; can_map: boolean; fnsku_notice?: string | null };
type CheckHistory = { check_id: string; import_id: number; actor_id: string; actor: string; created_at: string; source_only: boolean; selections: (Selection & { scope_id: number })[] };
export type Sku = { style_id?: number; sku_id: number; style_code: string; standard_color: string; standard_size: string; internal_display_sku: string | null; status: string };
export type Result = { history_total?: number; history_page?: number; history_has_next?: boolean; processing?: { remaining_count: number; rows: Record<string, {state: string; import_id: number; version_number?: number | null}>; candidates: {import_id: number; status: string; version_number?: number | null; review_path: string}[] }; check_history?: CheckHistory[]; import_id: number; status: string; workflow_revision: number; catalog_publication_revision: number; source: { sku_format_policy?: string; source_name: string; parent_import_id?: number; sheets: { name: string; count: number }[]; listing_rows: SourceRow[]; selections: Selection[]; bindings: Record<string, number> }; assessments: Assessment[]; inventory: Sku[]; mappings: { report_source_scope_id: number; seller_sku: string; sku_id: number }[]; stale: boolean; check_id?: string; latest_candidate_id?: number | null; coverage: { message: string; members: { report_source_scope_id: number; report_type: string; report_date: string; version_id: number | null }[] } };
export type Scope = { id: number; seller_account_display_name: string; marketplace_scope_code: string };
const processingLabels: Record<string, string> = { in_candidate: "已进入审核候选", identity_approved: "内部身份已批准，渠道待核", channel_approved: "渠道关联已批准", excluded: "已批准排除", parent_confirmed: "父级已核对", needs_attention: "需要继续处理" };
const stateLabels: Record<string, string> = { scope_required: "待选择店铺", source_conflict: "清单编码冲突", official_conflict: "官方来源冲突", no_official: "待报表核对", source_difference: "与官方不同", consistent: "本次证据范围内一致" };
function message(error: unknown) { return error instanceof Error && /[\u3400-\u9fff]/.test(error.message) ? error.message : "处理未完成，请检查连接后重试。当前输入已保留。"; }
function initial(row: SourceRow): Selection { return { row_id: row.row_id, include: false, record_type: row.suggested_type, style_code: row.suggestion?.style_code ?? "", color: row.suggestion?.color ?? "", size: row.suggestion?.size ?? "", selected_sku_id: null, use_official: false, confirm_raw_parent: false, note: "" }; }
function selectionInput(value: Selection): Selection { const { row_id, include, record_type, style_code, color, size, selected_sku_id, use_official, confirm_raw_parent, note } = value; return { row_id, include, record_type, style_code, color, size, selected_sku_id, use_official, confirm_raw_parent, note }; }

export function CatalogListingSourcePage({ simplified = false, onReview, onGuardChange, scopeRefresh=0, onSetup, onManual, selectedListing, onListingSelected }: { simplified?: boolean; onReview?:(id:number)=>void; onGuardChange?:(guard:{dirty:boolean;busy:boolean;unknown:boolean})=>void; scopeRefresh?:number; onSetup?:()=>void; onManual?:()=>void; selectedListing?:number; onListingSelected?:(id:number)=>void }) {
  const navigate = useNavigate(); const [search, setSearch] = useSearchParams();
  const { generation, registerSensitivePurge } = useAuthzGeneration();
  const epoch = useRef(0);
  const historyPage = Math.max(1, Number(search.get("history_page")) || 1);
  const [scopes, setScopes] = useState<Scope[]>([]); const [enabled, setEnabled] = useState<boolean>();
  const [data, setData] = useState<Result>(); const [bindings, setBindings] = useState<Record<string, number>>({}); const [selections, setSelections] = useState<Record<string, Selection>>({});
  const [recent, setRecent] = useState<{ review_path?: string; import_id: number; source_name: string; source_schema?: string | null }[]>([]);
  const [notice, setNotice] = useState<string>();
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string>(); const [compared, setCompared] = useState(false); const [page, setPage] = useState(1); const [onlyPending, setOnlyPending] = useState(false);
  const [upload, setUpload] = useState<{ file: File; token: string }>(); const [uploadUnknown, setUploadUnknown] = useState(false);
  const [pending, setPending] = useState<{ path: string; body: Record<string, unknown>; token: string }>(); const [saveUnknown, setSaveUnknown] = useState(false);
  const locked = busy || uploadUnknown || saveUnknown;
  const [reviewDirty, setReviewDirty] = useState(false);const [editorDirty,setEditorDirty]=useState(false);
  const [uploadRevision, setUploadRevision] = useState(0);
  const safeExit = useRef<() => void>(() => undefined);
  useEffect(() => registerSensitivePurge(() => { ++epoch.current; setData(undefined); setReviewDirty(false);setEditorDirty(false); setBindings({}); setSelections({}); setScopes([]); setRecent([]); setNotice(undefined); setUpload(undefined); setPending(undefined); setUploadUnknown(false); setSaveUnknown(false); setBusy(false); setError(undefined); }), [registerSensitivePurge]);
  const [localId,setLocalId]=useState<number>();
  const importId = onReview?(selectedListing??localId??Number(search.get("listing"))):Number(search.get("listing"));
  useEffect(() => {
    const controller = new AbortController(); const ticket = ++epoch.current;
    setBusy(true);
    if (!(importId > 0)) {
      setData(undefined); setBindings({}); setSelections({}); setCompared(false); setReviewDirty(false); setPage(1); setNotice(undefined); setError(undefined);
    }
    void (async () => {
      const cap = await requestApi<{ enabled: boolean; can_manage: boolean; scopes: Scope[] }>("/api/catalog/production-sources/capabilities", { signal: controller.signal });
      if (controller.signal.aborted || ticket !== epoch.current) return;
      setScopes(cap.scopes); setEnabled(cap.enabled && cap.can_manage);
      if (!cap.enabled || !cap.can_manage) return;
      const files = await requestApi<{ items: typeof recent }>("/api/catalog/production-sources", { signal: controller.signal });
      if (controller.signal.aborted || ticket !== epoch.current) return;
      setRecent(files.items.filter(item => item.source_schema === "amazon_listing_v1"));
      if (importId > 0) {
        const value = await requestApi<Result>(`/api/catalog/listing-sources/${importId}?history_page=${Math.max(1, Number(new URLSearchParams(window.location.search).get("history_page")) || 1)}`, { signal: controller.signal });
        if (controller.signal.aborted || ticket !== epoch.current) return;
        const nextBindings = { ...value.source.bindings };
        const validBindings = Object.keys(nextBindings).length > 0 && Object.values(nextBindings).every(id => cap.scopes.some(scope => scope.id === id));
        setData(value); setBindings(nextBindings); setSelections(simplified ? intakeSelections(value) : Object.fromEntries(value.source.listing_rows.map(row => [row.row_id, value.source.selections.find(s => s.row_id === row.row_id) ?? initial(row)]))); setReviewDirty(false); setCompared(simplified ? validBindings : Boolean(value.check_id)); setPage(1);
      }
    })().catch(reason => { if (!controller.signal.aborted && ticket === epoch.current) setError(message(reason)); }).finally(() => { if (ticket === epoch.current) setBusy(false); });
    return () => { controller.abort(); };
  }, [generation, importId, simplified, uploadRevision, scopeRefresh]);
  useEffect(()=>onGuardChange?.({dirty:reviewDirty||editorDirty,busy,unknown:uploadUnknown||saveUnknown}),[reviewDirty,editorDirty,busy,uploadUnknown,saveUnknown,onGuardChange]);
  async function loadHistory(nextPage: number) {
    const ticket = epoch.current; setBusy(true); setError(undefined);
    try {
      const value = await requestApi<Result>(`/api/catalog/listing-sources/${importId}?history_page=${nextPage}`);
      if (ticket !== epoch.current) return;
      setData(current => current ? { ...current, check_history: value.check_history, history_page: value.history_page, history_total: value.history_total, history_has_next: value.history_has_next } : current);
      const next = new URLSearchParams(search); next.set("history_page", String(nextPage)); if(!onReview)setSearch(next);
    } catch (reason) { if (ticket === epoch.current) setError(message(reason)); }
    finally { if (ticket === epoch.current) setBusy(false); }
  }
  function change(id: string, patch: Partial<Selection>) { setReviewDirty(true); setSelections(current => { const selected = current[id]; return selected ? { ...current, [id]: { ...selected, ...patch } } : current; }); setPending(undefined); setError(undefined); }
  async function doUpload(command: { file: File; token: string }) {
    const ticket = ++epoch.current; setBusy(true); setError(undefined); setUpload(command);
    let sent = false;
    try {
      if (simplified) await checkProductUpload(command.file);
      if (ticket !== epoch.current) return;
      sent = true;
      const result = await writeApi<{ import_id: number }>((simplified ? "/api/catalog/listing-sources/uploads?sku_policy=style-color-size-v1" : "/api/catalog/listing-sources/uploads"), { operationKey: command.token, rawBody: command.file, headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "X-Original-Filename": encodeURIComponent(command.file.name) } });
      if (ticket === epoch.current) { setUploadUnknown(false); setUpload(undefined); setData(undefined); safeExit.current(); setReviewDirty(false); setUploadRevision(current => current + 1); if(onReview){setLocalId(result.import_id);onListingSelected?.(result.import_id);}else setSearch({ entry: simplified ? "product-intake" : "amazon-listing", listing: String(result.import_id) }); }
    } catch (reason) { if (ticket === epoch.current) { setError(message(reason)); const uncertain = sent && !(reason instanceof ApiRequestError && reason.status < 500); setUploadUnknown(uncertain); if (!uncertain) setUpload(undefined); } }
    finally { if (ticket === epoch.current) setBusy(false); }
  }
  async function compare(nextBindings = bindings) {
    if (!data) return; const ticket = ++epoch.current; setBusy(true); setError(undefined);
    try {
      const result = await writeApi<Result>(`/api/catalog/listing-sources/${data.import_id}/compare`, { idempotent: false, body: nextBindings });
      if (ticket !== epoch.current) return;
      setData(result); setCompared(true); setPage(1); setPending(undefined);
      if (simplified) { setSelections(intakeSelections(result)); setReviewDirty(false); return; }
      setSelections(current => Object.fromEntries(result.source.listing_rows.map(row => {
        const prior = current[row.row_id] ?? initial(row);
        const mapped = result.mappings.find(m => m.report_source_scope_id === bindings[row.sheet] && m.seller_sku === row.seller_sku);
        const sku = result.inventory.find(s => s.sku_id === mapped?.sku_id);
        return [row.row_id, sku && !prior.include ? { ...prior, record_type: "variant", selected_sku_id: sku.sku_id, style_code: sku.style_code, color: sku.standard_color, size: sku.standard_size } : prior];
      })));
    } catch (reason) { if (ticket === epoch.current) { setError(message(reason)); setCompared(false); } }
    finally { if (ticket === epoch.current) setBusy(false); }
  }
  async function save() {
    if (!data) return;
    const command = pending ?? { path: `/api/catalog/listing-sources/${data.import_id}/preview`, token: createOperationKey(), body: { expected_workflow_revision: data.workflow_revision, expected_catalog_publication_revision: data.catalog_publication_revision, bindings, selections: Object.values(selections).map(selectionInput) } };
    const ticket = ++epoch.current; setPending(command); setBusy(true); setError(undefined);
    try {
      const result = await commandApi<{ import_id: number; source_only?: boolean }>(command.path, { ...command.body, operation_token: command.token }, command.token);
      if (ticket === epoch.current) { setSaveUnknown(false); setPending(undefined); setReviewDirty(false); if (result.source_only) { const value = await requestApi<Result>(`/api/catalog/listing-sources/${result.import_id}`); if (ticket === epoch.current) { setData(value); setNotice("父级核对已保存，原始行和操作依据已保留；未创建库存规格或目录版本。"); } } else { safeExit.current(); setReviewDirty(false); if(onReview)onReview(result.import_id);else await navigate(`/catalog/imports/${result.import_id}`); } }
    } catch (reason) { if (ticket === epoch.current) { setError(message(reason)); const unknown = !(reason instanceof ApiRequestError && reason.status < 500); setSaveUnknown(unknown); if (!unknown) { setPending(undefined); if (reason instanceof ApiRequestError && reason.status === 409) setCompared(false); } } }
    finally { if (ticket === epoch.current) setBusy(false); }
  }
  const allRows = data?.source.listing_rows ?? [];
  const rows = allRows.filter(row => !onlyPending || (data?.assessments.find(a => a.row_id === row.row_id)?.state !== "consistent" || row.issues.length));
  const pageRows = rows.slice((page - 1) * 20, page * 20);
  const selectedCount = Object.values(selections).filter(s => s.include && s.record_type === "variant").length;
  if (simplified) return <CatalogProductIntakePanel onEditorDirtyChange={setEditorDirty} onManual={onManual} onResumeSource={onReview?id=>{if(!locked&&!reviewDirty){setLocalId(id);onListingSelected?.(id);}}:undefined} onReviewCandidate={onReview} embedded={!!onReview} onSetup={onSetup} key={data?.import_id || "new"} data={data} enabled={enabled} scopes={scopes} bindings={bindings} selections={selections} busy={busy} unknown={uploadUnknown || saveUnknown} error={error} notice={notice} compared={compared} dirty={reviewDirty} registerExit={fn => { safeExit.current = fn; }} upload={file => { if (!locked && !reviewDirty) void doUpload({ file, token: createOperationKey() }); }} change={change} bind={(sheet, id) => { const next = { ...bindings }; if (id) next[sheet] = Number(id); else delete next[sheet]; setBindings(next); setCompared(false); setReviewDirty(true); if (Object.keys(next).length) void compare(next); else if (data) setSelections(intakeSelections({ ...data, source: { ...data.source, bindings: next } })); }} discard={() => { if (data) { setSelections(intakeSelections(data)); setBindings(data.source.bindings); setReviewDirty(false); } }} retryCompare={() => void compare()} save={() => void save()} retryUnknown={() => { if (uploadUnknown && upload) void doUpload(upload); else if (saveUnknown) void save(); }} recent={recent} />;
  return <section className={styles.operations} aria-label="亚马逊商品清单">
    <header className={styles.heading}><div><h2>亚马逊商品清单</h2><p>上传卖家SKU、ASIN和FNSKU清单，按店铺与官方经营、退货报告核对。图片忽略；原始编码保留。</p></div><LinkButton to="/catalog/production-sources">返回商品规格建档</LinkButton></header>
    {notice && <StatusMessage kind="info" title="核对已保存">{notice}</StatusMessage>}
    {error && <StatusMessage kind="danger" title="操作未完成"><ul>{error.split("\n").map((line, index) => <li key={index}>{line}</li>)}</ul></StatusMessage>}
    {enabled === false && <StatusMessage kind="warning" title="当前账号或环境尚未启用清单建档">请使用具备商品资料管理权限的账号。</StatusMessage>}
    {enabled && <>
      <FormField label="上传亚马逊商品清单" hint="支持含图片的XLSX，最多64MiB、10页、1000条编码记录。自动识别前10行内的卖家SKU／ASIN／FNSKU表头。"><input type="file" accept=".xlsx" disabled={locked} onChange={event => { const file = event.target.files?.[0]; event.target.value = ""; if (file) { if (!file.name.toLowerCase().endsWith(".xlsx") || !file.size || file.size > 64 * 1024 * 1024) setError("请选择64MiB以内且非空的XLSX清单。"); else void doUpload({ file, token: createOperationKey() }); } }} /></FormField>
      {uploadUnknown && upload && <StatusMessage kind="warning" title="上传结果尚不确定">请查询或重发原上传，避免重复登记。<Button disabled={busy} onClick={() => void doUpload(upload)}>查询或重发原上传</Button></StatusMessage>}
      {data && <>
        <section aria-label="清单范围"><h3>{data.source.source_name} · 批次{data.import_id}</h3><a href={`/api/catalog/imports/${data.import_id}/file`} download>下载原始清单</a><p>共{allRows.length}条来源记录。先逐表确认店铺，再核对官方报告；仅款号或无FNSKU不能单独证明是父商品。</p>
          <div className={styles.workflow}>{data.source.sheets.map(sheet => <div key={sheet.name}><FormField label={`${sheet.name} 的店铺账号和站点（必选）`} hint={`${sheet.count}条来源记录；工作表名称仅供参考。`}><Select disabled={locked} value={bindings[sheet.name] ?? ""} onChange={event => { const scopeId = Number(event.target.value); setBindings(current => { const next = { ...current }; if (scopeId) next[sheet.name] = scopeId; else delete next[sheet.name]; return next; }); setCompared(false); setSelections(current => Object.fromEntries(Object.entries(current).map(([key, value]) => allRows.find(r => r.row_id === key)?.sheet === sheet.name ? [key, { ...value, selected_sku_id: null, include: false, use_official: false }] : [key, value]))); }}><option value="">请选择店铺账号和站点</option>{scopes.map(scope => <option key={scope.id} value={scope.id}>{scope.seller_account_display_name} · {scope.marketplace_scope_code}</option>)}</Select></FormField></div>)}</div>
          <Button disabled={locked || !Object.keys(bindings).length} onClick={() => void compare()}>核对官方报表</Button>
          {data.processing && <section aria-label="原清单处理结果"><h3>已保存的处理结果</h3><p>尚未进入有效处理的记录组 {data.processing.remaining_count} 组，重复原行继续保留。下方表单用于新的核对；原批准与保存历史保留。</p>{data.processing.candidates.map(item => <p key={item.import_id}><Link to={item.review_path}>{item.status === "approved" ? `查看已批准候选批次${item.import_id} · V${item.version_number}` : `${["withdrawn", "superseded"].includes(item.status) ? "查看历史候选" : item.status === "rejected" ? "修订已退回候选" : "继续候选"}批次${item.import_id}`}</Link></p>)}</section>}
          {data.stale && <StatusMessage kind="warning" title="原核对依据已变化">原批准和历史保留。请重新核对并建立后继草稿。</StatusMessage>}
          {compared && <p role="status">{data.coverage.message} 当前可用发布版本{data.coverage.members.filter(m => m.version_id).length}份；未出现的报告不能视为已核实。</p>}
          {data.latest_candidate_id && data.latest_candidate_id !== data.import_id && <Link to={`/catalog/imports/${data.latest_candidate_id}`}>查看最近候选批次{data.latest_candidate_id}</Link>}
        </section>
        <section aria-label="清单记录与差异"><div className={css.toolbar}><h3>核对记录</h3><label><input type="checkbox" checked={onlyPending} onChange={event => { setOnlyPending(event.target.checked); setPage(1); }} />仅看需要处理</label><span>已选具体规格{selectedCount}条</span></div>
          {compared && <div className={css.toolbar}><Button variant="quiet" disabled={locked} onClick={() => { setSelections(current => { const next = { ...current }; for (const row of pageRows) { const a = data.assessments.find(item => item.row_id === row.row_id); const s = next[row.row_id]; if (a?.state === "consistent" && a.primary_row === row.row_id && s?.record_type === "variant" && s.style_code && s.color && s.size && !row.issues.length) next[row.row_id] = { ...s, include: true }; } return next; }); }}>选择本页已核对规格</Button><Button variant="quiet" disabled={locked} onClick={() => setSelections(current => Object.fromEntries(Object.entries(current).map(([key, s]) => pageRows.some(r => r.row_id === key) && s.include && data.assessments.find(a => a.row_id === key)?.state === "source_difference" ? [key, { ...s, use_official: true }] : [key, s])))}>本页已选差异采用官方依据</Button><span>仅作用于本页明确范围，原始编码和清单值保留。</span></div>}
          <p>勾选即确认本次处理范围。新规格须确认款号、标准颜色和标准尺码；Seller SKU原文不会被标准化结果改写。相同编码跨店铺分别核对。</p>
          <div className={css.records}>{pageRows.map(row => {
            const selected = selections[row.row_id] ?? initial(row); const assessment = data.assessments.find(a => a.row_id === row.row_id);
            const duplicate = assessment && assessment.primary_row !== row.row_id;
            return <article className={css.record} key={row.row_id} aria-label={`${row.sheet}第${row.row}行 ${row.seller_sku}`}>
              <div className={css.identity}><label><input type="checkbox" checked={selected.include} disabled={locked || !compared || Boolean(duplicate)} onChange={event => change(row.row_id, { include: event.target.checked })} />本次处理</label><strong>{row.seller_sku || "缺少卖家SKU"}</strong><span>{row.sheet} · 第{row.row}行</span><span>{compared ? stateLabels[assessment?.state ?? ""] ?? "待核对" : "待核对官方报表"}</span></div>
              {data.processing?.rows[row.row_id] && <p><Link to={`/catalog/imports/${data.processing.rows[row.row_id]!.import_id}`}>{processingLabels[data.processing.rows[row.row_id]!.state]}{data.processing.rows[row.row_id]!.version_number ? ` · V${data.processing.rows[row.row_id]!.version_number}` : ""}</Link></p>}
              <p>本表ASIN：{row.child_asin || row.asin || "未提供"} · 父ASIN：{row.parent_asin || "未分列"} · FNSKU：{row.fnsku || "未提供"}</p>
              {duplicate ? <p>与本组第{assessment.duplicate_rows[0]?.split("-r")[1]}行重复，合并处理并保留全部来源行。</p> : <>
                {row.issues.length > 0 && <ul className={css.issues}>{row.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>}
                {compared && assessment && <><p>{assessment.message}</p><p>官方子ASIN：{assessment.official_asins.join("、") || "尚无可比记录"} · 官方FNSKU：{assessment.official_fnskus.join("、") || "未提供"}</p>{assessment.fnsku_notice && <p>{assessment.fnsku_notice}</p>}
                  {assessment.state === "source_difference" && <label><input type="checkbox" disabled={locked} checked={selected.use_official} onChange={event => change(row.row_id, { use_official: event.target.checked })} />已核对差异，本次采用官方依据；保留清单原值</label>}
                  <details><summary>查看官方来源和日期（{assessment.observations.length}条）</summary>{assessment.observations.map((obs, index) => <p key={index}>{obs.report_type === "business_report" ? "经营报告" : "退货报告"} · 报告日期{obs.report_date}{obs.event_date ? ` · 事件时间${obs.event_date}` : ""} · 版本{obs.version_id} · 来源行{obs.source_row_id} · 父ASIN {obs.parent_asin || "未提供"} · 子ASIN {obs.child_asin || "未提供"} · FNSKU {obs.fnsku || "未提供"}</p>)}</details>
                </>}
                <div className={css.fields}><FormField label="记录类型"><Select disabled={locked} value={selected.record_type} onChange={event => change(row.row_id, { record_type: event.target.value as Selection["record_type"] })}><option value="unknown">记录类型待确认</option><option value="parent">父级／款式记录</option><option value="variant">具体商品规格</option></Select></FormField>
                  {selected.record_type === "variant" && <FormField label="选择已有商品"><Select disabled={locked} value={selected.selected_sku_id ?? ""} onChange={event => { const sku = data.inventory.find(s => String(s.sku_id) === event.target.value); change(row.row_id, sku ? { selected_sku_id: sku.sku_id, style_code: sku.style_code, color: sku.standard_color, size: sku.standard_size } : { selected_sku_id: null }); }}><option value="">新规格待建档／尚未选择</option>{data.inventory.map(sku => <option key={sku.sku_id} value={sku.sku_id}>{sku.style_code} · {sku.standard_color} · {sku.standard_size} · {sku.internal_display_sku || "正式SKU待补"}</option>)}</Select></FormField>}
                </div>
                {selected.record_type === "parent" && <label><input type="checkbox" checked={selected.confirm_raw_parent} disabled={locked} onChange={event => change(row.row_id, { confirm_raw_parent: event.target.checked })} />已核实父级类型、原始款号及前导零；只保留父级依据，不建立库存规格</label>}
                {selected.record_type === "variant" && <div className={css.fields}>{([['style_code', '款号'], ['color', '标准颜色'], ['size', '标准尺码']] as const).map(([field, label]) => <FormField key={field} label={`${label}（必填）`}><Input disabled={locked || selected.selected_sku_id !== null} maxLength={128} value={selected[field]} onChange={event => change(row.row_id, { [field]: event.target.value })} /></FormField>)}</div>}
                <FormField label="核对依据（规格纠错时必填）"><Input disabled={locked} maxLength={1000} value={selected.note} onChange={event => change(row.row_id, { note: event.target.value })} /></FormField>
              </>}
            </article>;
          })}</div>
          <nav className={styles.pagination} aria-label="清单记录分页"><Button variant="quiet" disabled={locked || page <= 1} onClick={() => setPage(current => current - 1)}>上一页</Button><span>第{page}页 · 共{rows.length}条</span><Button variant="quiet" disabled={locked || page * 20 >= rows.length} onClick={() => setPage(current => current + 1)}>下一页</Button></nav>
          {saveUnknown && <StatusMessage kind="warning" title="保存结果尚不确定">输入已锁定，请查回原保存，避免建立重复候选。</StatusMessage>}
          <Button disabled={busy || uploadUnknown || (!saveUnknown && (!compared || !Object.values(selections).some(s => s.include)))} onClick={() => void save()}>{saveUnknown ? "查询或重发原保存" : (selectedCount ? "保存所选候选并进入审核" : "保存父级核对")}</Button><p>父级、重复和未选行继续保留在原清单。保存候选不会让商品或平台关联生效，后续仍需审核批准。</p>
        </section>
        <section aria-label="核对保存记录"><h3>核对保存记录（共{data.history_total ?? data.check_history?.length ?? 0}次，第{historyPage}页）</h3><p>记录具体操作账号、时间和所选范围；原始清单值在上方保留。审核批准结果可在<Link to="/catalog/versions">目录版本</Link>查看。</p>{data.check_history?.length ? <ol>{data.check_history.map(item => <li key={item.check_id}><strong>{item.actor}</strong>（用户#{item.actor_id}） · {new Date(item.created_at).toLocaleString("zh-CN")} · {item.source_only ? "保存父级核对" : "保存候选核对"} · 批次{item.import_id}<details><summary>查看本次{item.selections.length}条决定与依据</summary><ul>{item.selections.map(selected => { const row = allRows.find(raw => raw.row_id === selected.row_id); return <li key={selected.row_id}>{row ? `${row.sheet}第${row.row}行 ${row.seller_sku}` : selected.row_id} · 账号范围{selected.scope_id} · {selected.record_type === "parent" ? "父级／款式，不建库存规格" : `${selected.style_code} / ${selected.color} / ${selected.size}，${selected.selected_sku_id ? `复用商品#${selected.selected_sku_id}` : "规格候选"}`} · {selected.use_official ? "明确采用官方依据" : "保留来源核对决定"} · 依据：{selected.note || "未另填说明"}</li>; })}</ul></details></li>)}</ol> : <p>本页没有已保存的核对决定。</p>}<nav aria-label="核对记录分页"><Button disabled={historyPage <= 1 || locked} onClick={() => void loadHistory(historyPage - 1)}>上一页记录</Button><Button disabled={!data.history_has_next || locked} onClick={() => void loadHistory(historyPage + 1)}>下一页记录</Button></nav></section>
      </>}
      {!data && <section><h3>继续已有批次</h3><ul className={styles.history}>{recent.map(item => <li key={item.import_id}><Link to={item.review_path ?? `/catalog/production-sources?entry=amazon-listing&listing=${item.import_id}`}>{item.source_name} · 批次{item.import_id}</Link></li>)}</ul></section>}
    </>}
    {busy && <p role="status">正在读取、核对或保存，请等待结果…</p>}
  </section>;
}
