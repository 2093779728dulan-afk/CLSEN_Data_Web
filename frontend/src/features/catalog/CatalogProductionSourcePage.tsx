import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ApiRequestError, requestApi, writeApi, commandApi, createOperationKey } from "../../api/client";
import { Button, FormField, Input, LinkButton, Select, StatusMessage, Table } from "../../design-system";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import styles from "./CatalogOperations.module.css";
import { CatalogListingSourcePage } from "./CatalogListingSourcePage";
import { skuSuggestion } from "./catalogReviewSuggestions";
import { workflowLabel } from "./catalogImportState";

type Source = { source_name: string; report_source_scope_id?: number; channel_evidence?: string; rows: { style_code: string; color: string; size: string; formal_sku?: string | null; selected_sku_id?: number }[] };
type Preview = { catalog_publication_revision: number; counts: Record<string, number>; blocking_fields: number; format_adjustments?: { source_row: number; location: string; field: string; before: string; after: string; reason: string }[]; observations: { source_row: number; style_code: string; color: string; size: string; action: string; sku_id?: string; formal_sku?: string | null; code_status?: string }[] };
function readableError(reason: unknown, fallback: string) { return reason instanceof Error && /[\u3400-\u9fff]/.test(reason.message) ? reason.message : fallback; }

type Saved = { review_path?: string; approved_catalog_version_number?: number | null; record_kind?: string; source_schema?: string | null; import_id: number; status: string; source_name: string; actor: string; created_at: string };
const labels: Record<string, string> = { REUSE_EXISTING: "复用已有规格", REVIEW_DISABLED: "已有产品或规格已停用，需核实", ADD_SPECIFICATION: "已有产品补规格", REVIEW_NEW_PRODUCT: "新产品待核", DUPLICATE_SOURCE_ROW: "重复来源行，保留依据" };

export function CatalogProductionSourcePage() {
  const [search] = useSearchParams();
  return search.get("entry") === "specification" || search.has("style") || search.has("color") || search.has("size") ? <CatalogSpecificationSourcePage /> : search.get("entry")==="amazon-listing"?<CatalogListingSourcePage/>:<Navigate replace to={`/catalog/maintenance${search.size?`?${search.toString()}`:""}`}/>;
}

export type CatalogPrimaryAction={label:string;disabled:boolean;run:()=>void};
export function CatalogSpecificationSourcePage({embedded=false,onGuardChange,onReview,onPrimaryAction}:{onPrimaryAction?:(action:CatalogPrimaryAction|undefined)=>void;embedded?:boolean;onGuardChange?:(guard:{dirty:boolean;busy:boolean;unknown:boolean})=>void;onReview?:(id:number)=>void}={}) {
  const navigate = useNavigate();
  const { generation, registerSensitivePurge } = useAuthzGeneration();
  const epoch = useRef(0);
  const [enabled, setEnabled] = useState<boolean>();
  const [inputMode,setInputMode]=useState<'sku'|'columns'>(()=>new URLSearchParams(window.location.search).has('style')?'columns':'sku');
  const [skuText,setSkuText]=useState('');
  const [sourceName, setSourceName] = useState("");
  const [scopes, setScopes] = useState<{ id: number; seller_account_display_name: string; marketplace_scope_code: string }[]>([]);
  const [scope, setScope] = useState("");
  const [evidence, setEvidence] = useState("");
  const [text, setText] = useState(() => { const q = new URLSearchParams(window.location.search); return "款号\t颜色\t尺码\t正式SKU\n" + (q.get("style") ? `${q.get("style")}\t${q.get("color") ?? ""}\t${q.get("size") ?? ""}\t` : ""); });
  const [format, setFormat] = useState<"csv" | "tsv" | "xlsx">("tsv");
  const [preview, setPreview] = useState<Preview>();
  const [source, setSource] = useState<Source>();
  const [pending, setPending] = useState<{ operation_token: string; expected_catalog_publication_revision: number; source: Source }>();
  const [unknown, setUnknown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [recent, setRecent] = useState<Saved[]>([]);
  const locked = busy || unknown;
  useEffect(() => registerSensitivePurge(() => { ++epoch.current; setSourceName("");setSkuText("");setInputMode("sku"); setText(""); setSource(undefined); setPreview(undefined); setPending(undefined); setUnknown(false); setBusy(false); setRecent([]); setError(undefined); setScopes([]); setScope(""); setEvidence(""); }), [registerSensitivePurge]);
  useEffect(() => {
    const lifetime = epoch;
    const controller = new AbortController();
    void requestApi<{ enabled: boolean; can_manage: boolean; scopes: typeof scopes }>("/api/catalog/production-sources/capabilities", { signal: controller.signal }).then(async value => {
      if (controller.signal.aborted) return;
      setEnabled(value.enabled && value.can_manage); setScopes(value.scopes ?? []);
      if (embedded && value.scopes?.length === 1) {
        setScope(String(value.scopes[0]!.id));
        setEvidence("用户在商品建档中确认本次商品属于已选店铺；提供Seller SKU时同时确认平台关联");
      }
      if (value.enabled && value.can_manage) {
        const result = await requestApi<{ items: Saved[] }>("/api/catalog/production-sources", { signal: controller.signal });
        if (!controller.signal.aborted) setRecent(result.items);
      }
    }).catch(reason => { if (!controller.signal.aborted) setError(readableError(reason, "来源入口读取失败，请检查连接后重试。")); });
    return () => { ++lifetime.current; controller.abort(); };
  }, [generation, embedded]);
  const initialText="款号\t颜色\t尺码\t正式SKU\n";
  useEffect(()=>onGuardChange?.({dirty:!!sourceName||text!==initialText,busy,unknown}),[sourceName,text,scope,evidence,busy,unknown,onGuardChange,initialText]);
  function changed() { ++epoch.current; setPreview(undefined); setSource(undefined); setPending(undefined); setError(undefined); }
  async function file(file: File | undefined) {
    if (!file || locked) return;
    changed();
    const ticket = epoch.current;
    setBusy(true);
    try {
      if (file.size > 1_000_000) throw new Error("规格表最多1MB、1000行，请缩小本批范围。");
      if (!/\.(xlsx|csv|tsv)$/i.test(file.name)) throw new Error("请选择XLSX、CSV或TSV规格表。其他文件请先转换为支持的格式。");
      if (!file.size) throw new Error("文件为空，请添加表头和规格后重新上传。");
      const kind = file.name.toLowerCase().endsWith(".xlsx") ? "xlsx" : file.name.toLowerCase().endsWith(".csv") ? "csv" : "tsv";
      const content = kind === "xlsx" ? await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => typeof reader.result === "string" ? resolve(reader.result.split(",")[1] ?? "") : reject(new Error("文件读取失败。")); reader.onerror = () => reject(new Error("文件读取失败。")); reader.readAsDataURL(file); }) : await file.text();
      if (kind !== "xlsx" && content.includes("\uFFFD")) throw new Error("文件文字出现乱码，请从原表另存为UTF-8编码的CSV/TSV或XLSX后重新上传。");
      if (ticket === epoch.current) { setInputMode("columns");setText(content); setSourceName(file.name); setFormat(kind); await check(file.name, content, kind, ticket); }
    } catch (reason) { if (ticket === epoch.current) setError(readableError(reason, "表格文件无法读取，请检查连接后重新选择文件。")); }
    finally { if (ticket === epoch.current) setBusy(false); }
  }
  async function check(name: string, content: string, kind: "csv" | "tsv" | "xlsx", ticket: number) {
    if (!name.trim() || name.length > 128) throw new Error("资料名称不能为空且最多128个字符，请修改名称或缩短文件名。");
    if (!content.trim()) throw new Error("表格为空，请填写表头和至少一行规格。");
    const { preview: checked, ...parsed } = await writeApi<Source & { preview?: Preview }>("/api/catalog/production-sources/parse", { idempotent: false, body: { source_name: name, content, format: kind } });
    if (ticket !== epoch.current) return;
    if (scope && !evidence.trim()) throw new Error("已选择渠道账号，请填写渠道关联依据后重新预览。表格内容已保留。");
    if (scope) { parsed.report_source_scope_id = Number(scope); parsed.channel_evidence = evidence; }
    const result = !scope && checked ? checked : await writeApi<Preview>("/api/catalog/production-sources/preview", { idempotent: false, body: parsed });
    if (ticket === epoch.current) { setSource(parsed); setPreview(result); setPending(undefined);return {source:parsed,preview:result}; }
  }
  async function prepare(enterReview=false) {
    const ticket = epoch.current;
    setBusy(true); setError(undefined); setPreview(undefined); setSource(undefined);
    try {
      if(inputMode==='sku'){
        const lines=skuText.split(/\r?\n/).map((code,index)=>({code,index:index+1})).filter(row=>row.code!=='');
        const invalid=lines.filter(row=>!skuSuggestion(row.code));
        if(!lines.length)throw new Error('请填写至少一个SKU，每行一个。');
        if(invalid.length)throw new Error(invalid.map(row=>`第${row.index}行：SKU须按款号-颜色-尺码填写并保留大小写，例如1101-Navy-L。原值：${row.code}`).join('\n'));
      }
      const prepared=await check(sourceName,text,format,ticket);
      if(enterReview&&prepared&&ticket===epoch.current){
        const reuse=prepared.preview.observations.filter(row=>row.action==='REUSE_EXISTING'&&Number.isSafeInteger(Number(row.sku_id))&&Number(row.sku_id)>0);
        prepared.source.rows=prepared.source.rows.map((row,index)=>{const found=reuse.find(item=>item.source_row===index+1);return found?{...row,selected_sku_id:Number(found.sku_id)}:row;});
        setSource(prepared.source);
        if(prepared.preview.observations.some(row=>row.sku_id&&!prepared.source.rows[row.source_row-1]?.selected_sku_id))throw new Error('有规格需要核对已有商品，请在下方预览中确认后继续。');
        await save(prepared);
      }
    }
    catch (reason) { if (ticket === epoch.current) setError(readableError(reason, "表格检查未完成，请检查连接后重新检查。输入已保留。")); }
    finally { if (ticket === epoch.current) setBusy(false); }
  }
  async function save(prepared?:{source:Source;preview:Preview}) {
    const currentSource=prepared?.source??source;const currentPreview=prepared?.preview??preview;
    if (!currentSource || !currentPreview || (busy&&!prepared)) return;
    const ticket = epoch.current;
    const command = pending ?? { operation_token: createOperationKey(), expected_catalog_publication_revision: currentPreview.catalog_publication_revision, source:currentSource };
    setPending(command); setBusy(true); setError(undefined);
    try {
      const result = await commandApi<{ import_id: number }>("/api/catalog/production-sources", command, command.operation_token);
      if (ticket === epoch.current) { setUnknown(false); if(onReview)onReview(result.import_id);else await navigate(`/catalog/imports/${result.import_id}`); }
    } catch (reason) {
      if (ticket !== epoch.current) return;
      if (reason instanceof ApiRequestError && reason.status < 500) {
        setUnknown(false); setPending(undefined);
        if (reason.status === 409) { setPreview(undefined); setSource(undefined); }
      } else setUnknown(true);
      setError(reason instanceof ApiRequestError && reason.status === 409 ? "商品目录或批次状态已变化，请重新预览候选，再保存。" : readableError(reason, "保存结果尚不确定，请查询或重发原保存。"));
    } finally { if (ticket === epoch.current) setBusy(false); }
  }
  const primaryRun=useRef<()=>void>(()=>undefined);
  primaryRun.current=()=>{if(unknown||preview)void save();else void prepare(inputMode==='sku');};
  const invokePrimary=useCallback(()=>primaryRun.current(),[]);
  const primaryLabel=unknown?'查询或重发原保存':preview?'保存候选并进入审核':inputMode==='sku'?'检查并进入审核':'预览商品候选';
  const primaryDisabled=enabled!==true||busy||(!unknown&&(preview?preview.observations.some(row=>row.sku_id&&!source?.rows[row.source_row-1]?.selected_sku_id):!sourceName.trim()||Boolean(scope&&!evidence.trim())));
  useEffect(()=>{onPrimaryAction?.({label:primaryLabel,disabled:primaryDisabled,run:invokePrimary});return()=>onPrimaryAction?.(undefined);},[onPrimaryAction,primaryLabel,primaryDisabled,invokePrimary]);
  return <section className={styles.operations} aria-label="商品建档候选">
    <header className={styles.heading}><div><h2>手工建档</h2><p hidden>登记“是什么商品”：款号、颜色、尺码及已有正式SKU。先检查，再保存候选，审核批准后进入商品主档。</p></div></header>
    {error && <StatusMessage kind="danger" title="操作未完成"><ul>{error.split("\n").map((line, index) => <li key={index}>{line}</li>)}</ul>输入会保留在当前页面。</StatusMessage>}
    {enabled === undefined ? <p role="status">{error ? "入口权限未读取成功，请刷新后重试。" : "正在读取入口权限…"}</p> : enabled === false ? <StatusMessage kind="warning" title="当前环境尚未启用商品建档">此入口需要环境启用，且使用管理员或资料管理员账号。</StatusMessage> : <>
      {!embedded&&<Link className={styles.action} to="/catalog/production-sources?entry=amazon-listing">导入亚马逊商品清单（Seller SKU／ASIN／FNSKU）</Link>}
      <details aria-label="建档填写说明"><summary>模板与填写帮助</summary>
        <p>适用于新商品建档或已有款式补充颜色、尺码。已有完整规格可在<Link to="/catalog">商品目录</Link>查找；件数、库位和收发记录请到<Link to="/production/stock">库存管理</Link>办理。</p>
        <LinkButton variant="secondary" reloadDocument to="/api/catalog/production-sources/template" download>下载商品建档模板（XLSX）</LinkButton>
        <p hidden>一行填写一个“款号＋颜色＋尺码”，不要填写各尺码的库存数量。模板已设为文本格式；从原表粘贴时请仅粘贴值，保留前导零。</p>
        <div className={styles.workflow}>
          <div><strong>款号、颜色、尺码 · 必填</strong><p hidden>按已核实的原文填写。可确定的格式差异自动整理，并展示原值对照；优先沿用已有主档写法，新颜色仍需审核确认。</p></div>
          <div><strong>正式SKU · 选填</strong><p hidden>填写有依据的正式编码；以Amazon Seller SKU为正式码时，直接使用该编码原文。保留大小写、连字符和前导零，不自行拼接。未知可留空，审核时确认待补。</p></div>
          <div><strong>Seller SKU · 渠道关联</strong><p hidden>按账号和站点关联。下方选填渠道账号并提供依据，再审核生效。系统内部ID由系统生成，不需要填写。</p></div>
        </div>
        <details><summary>统一格式要求</summary><p hidden>款号、颜色、尺码均用文本单元格，空格及全角英数字可整理为标准写法，颜色和尺码统一大小写；原文始终保留。正式SKU逐字保留，不自动改码。不可见字符、乱码、多个主档写法冲突仍须核对；不会合并相似颜色。字体、字号和列宽不影响识别。</p></details>
      </details>
      <div className={styles.methodTabs} role="group" aria-label="填写方式"><Button variant={inputMode==='sku'?'primary':'secondary'} disabled={locked} onClick={()=>setInputMode('sku')}>按SKU填写</Button><Button variant={inputMode==='columns'?'primary':'secondary'} disabled={locked} onClick={()=>setInputMode('columns')}>分列填写或导入</Button></div>
      {inputMode==='sku'?<section className={styles.manualEntry}><h3>填写SKU，系统补齐规格</h3><FormField label={embedded && scope ? "Seller SKU清单（每行一个）" : "SKU清单（每行一个）"}><textarea rows={6} disabled={locked} value={skuText} placeholder={'1101-Navy-L\n1101-Navy-M'} onChange={event=>{changed();const value=event.target.value;setSkuText(value);setFormat('tsv');if(!sourceName)setSourceName(`手工建档-${new Date().toLocaleDateString('en-CA')}`);setText('款号\t颜色\t尺码\t正式SKU\n'+value.split(/\r?\n/).filter(Boolean).map(code=>{const spec=skuSuggestion(code);return spec?`${spec.style_code}\t${spec.color}\t${spec.size}\t${code}`:'';}).join('\n'));}}/></FormField><details><summary>资料名称（可选修改）</summary><FormField label="资料名称（必填）"><Input disabled={locked} value={sourceName} onChange={event=>{changed();setSourceName(event.target.value);}}/></FormField></details></section>:<>
      <FormField label="资料名称（必填）"><Input disabled={locked} value={sourceName} onChange={event => { changed(); setSourceName(event.target.value); }} /></FormField>
      <FormField label="选择规格表（选填）" hint="选择后自动检查。单页XLSX或UTF-8 CSV/TSV，最多1MB、1000行；表头依次为款号、颜色、尺码，可选第四列正式SKU。编码和规格须为文本。"><input type="file" accept=".xlsx,.csv,.tsv" disabled={locked} onChange={event => { const selected = event.target.files?.[0]; event.target.value = ""; void file(selected); }} /></FormField>
      {format === "xlsx" ? <p>已读取 {sourceName}，请查看页面检查提示；修改原文件后可重新选择同名文件。<Button disabled={locked} variant="quiet" onClick={() => { changed(); setFormat("tsv"); setText("款号\t颜色\t尺码\t正式SKU\n"); }}>改为手工或粘贴</Button></p> : <>
        <FormField label="资料内容（必填）" hint="可粘贴表格，或手工填写一行明确规格。"><textarea aria-label="资料内容（必填）" rows={8} disabled={locked} value={text} onChange={event => { changed(); setText(event.target.value); }} /></FormField>
        <label>分隔格式 <select disabled={locked} value={format} onChange={event => { changed(); setFormat(event.target.value as "csv" | "tsv"); }}><option value="tsv">表格制表符 / TSV</option><option value="csv">逗号 / CSV</option></select></label>
      </>}
      </>}
      {embedded && scopes.length === 1 ? <p>店铺 {scopes[0]!.seller_account_display_name} · {inputMode === "sku" ? "本次SKU作为本店Seller SKU，随建档确认关联" : "批准后归入本店"}</p> : scopes.length === 1 && (!scope || scope === String(scopes[0]!.id)) ? <label><input type="checkbox" checked={!!scope} disabled={locked} onChange={event => { changed(); setScope(event.target.checked ? String(scopes[0]!.id) : ""); }} />关联平台商品资料（选填）</label> : <FormField label="渠道账号/站点（选填）" hint="仅在有渠道依据时选择；否则正式编码可审核，渠道关联保持待核。"><Select disabled={locked} value={scope} onChange={event => { changed(); setScope(event.target.value); }}><option value="">暂不申请渠道关联</option>{scopes.map(item => <option key={item.id} value={item.id}>{item.seller_account_display_name} · {item.marketplace_scope_code}</option>)}</Select></FormField>}
      {scope && !(embedded && scopes.length === 1) && <FormField label="渠道关联依据（必填）"><Input disabled={locked} value={evidence} onChange={event => { changed(); setEvidence(event.target.value); }} placeholder="如本账号Seller SKU清单及核对说明" /></FormField>}
      <Button hidden={embedded&&!!onPrimaryAction} variant="primary" disabled={locked || !sourceName.trim() || Boolean(scope && !evidence.trim())} onClick={() => void prepare(inputMode==='sku')}>{inputMode==='sku'?'检查并进入审核':'预览商品候选'}</Button>
      {busy && <p role="status">正在检查或处理资料，请等待结果…</p>}
      {!!preview?.format_adjustments?.length && <section aria-label="格式整理说明"><h3>已整理 {preview.format_adjustments.length} 处格式</h3><p hidden>以下是本次候选采用的写法；原文保留，尚未修改主档，也未改变正式SKU或数量。</p><Table aria-label="格式整理对照"><thead><tr><th>原位置</th><th>字段</th><th>整理前（引号内为原文）</th><th>整理后</th><th>依据</th></tr></thead><tbody>{preview.format_adjustments.map((change, index) => <tr key={index}><td>{change.location}</td><td>{({ style_code: "款号", color: "颜色", size: "尺码" } as Record<string, string>)[change.field] ?? change.field}</td><td><code>{JSON.stringify(change.before)}</code></td><td><code>{JSON.stringify(change.after)}</code></td><td>{change.reason}</td></tr>)}</tbody></Table></section>}
      {preview && <section className={styles.exportPanel} aria-label="候选范围预览"><h3>表格检查通过，共{preview.observations.length}条规格</h3><p hidden>格式与已知身份冲突检查已通过，尚未保存或生效。新产品、颜色、尺码及缺少的正式SKU仍需审核确认。</p><p>{Object.entries(preview.counts).map(([key, value]) => `${labels[key] ?? key} ${value} 行`).join(" · ")}。还有 {preview.blocking_fields} 个字段需在审核页补齐。</p><Table aria-label="来源规格与处理建议"><thead><tr><th>规格序号</th><th>候选款号</th><th>候选颜色</th><th>候选尺码</th><th>本表正式SKU</th><th>处理建议</th></tr></thead><tbody>{preview.observations.map(row => <tr key={row.source_row}><td>{row.source_row}</td><td>{row.style_code}</td><td>{row.color}</td><td>{row.size}</td><td>{source?.rows[row.source_row - 1]?.formal_sku || "未提供"}</td><td>{row.sku_id ? <Select aria-label={`第${row.source_row}行选择已有商品`} disabled={locked} value={source?.rows[row.source_row - 1]?.selected_sku_id ?? ""} onChange={event => { const value = Number(event.target.value); setPending(undefined); setSource(current => current && ({ ...current, rows: current.rows.map((item, index) => index === row.source_row - 1 ? { ...item, selected_sku_id: value || undefined } : item) })); }}><option value="">请选择已有商品</option><option value={row.sku_id}>{row.style_code} · {row.color} · {row.size} · {row.formal_sku || "正式SKU待补"} · {labels[row.action]}</option></Select> : labels[row.action] ?? row.action}</td></tr>)}</tbody></Table>
        <p hidden>相似颜色会分别保留为候选；复用只认定主档中相同的颜色、尺码，不自动批准绑定。</p>
        {unknown && <StatusMessage kind="warning" title="保存结果尚不确定">输入已锁定。请重发原保存查回结果；刷新后也可在下方最近批次查找，避免重新建档。</StatusMessage>}
        <Button hidden={embedded&&!!onPrimaryAction} variant="primary" disabled={busy || preview.observations.some(row => row.sku_id && !source?.rows[row.source_row - 1]?.selected_sku_id)} onClick={() => void save()}>{unknown ? "查询或重发原保存" : "保存候选并进入审核"}</Button>
      </section>}
      {!embedded&&<section aria-label="最近商品建档批次"><h3>最近批次</h3>{recent.length ? <ul className={styles.history}>{recent.map(item => <li key={item.import_id}><div><Link to={item.review_path ?? (item.source_schema === "amazon_listing_v1" ? `/catalog/production-sources?entry=amazon-listing&listing=${item.import_id}` : `/catalog/imports/${item.import_id}`)}>{item.source_name} · 批次 {item.import_id}</Link><p>{item.record_kind === "listing_source" ? "原始清单 · 继续未核记录" : item.status === "approved" && item.approved_catalog_version_number ? `已批准V${item.approved_catalog_version_number}` : workflowLabel(item)} · 操作账号 {item.actor} · {new Date(item.created_at).toLocaleString("zh-CN")}</p></div></li>)}</ul> : <p>尚无商品建档批次。保存候选后可在这里继续审核。</p>}</section>}
    </>}
  </section>;
}
