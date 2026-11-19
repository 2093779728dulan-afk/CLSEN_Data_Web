import { useEffect, useRef, useState } from "react";
import { UploadCloud } from "lucide-react";
import { Button, Dialog, FormField, Input, LinkButton, Pagination, Select, StatusMessage, Table } from "../../design-system";
import { useProductionLeave } from "../production/useProductionLeave";
import type { Result, Scope, Selection, SourceRow } from "./CatalogListingSourcePage";
import { intakeBlocking, intakeIssues, intakeStateLabels } from "./catalogIntake";
import styles from "./CatalogProductIntakePanel.module.css";

type Props = {
  embedded?:boolean; onManual?:()=>void; onEditorDirtyChange?:(dirty:boolean)=>void; onSetup?:()=>void; onResumeSource?:(id:number)=>void; onReviewCandidate?:(id:number)=>void;
  data?: Result; enabled?: boolean; scopes: Scope[]; bindings: Record<string, number>; selections: Record<string, Selection>;
  busy: boolean; unknown: boolean; error?: string; notice?: string; compared: boolean; dirty: boolean;
  upload: (file: File) => void; change: (id: string, patch: Partial<Selection>) => void; bind: (sheet: string, id: string) => void;
  retryCompare: () => void; save: () => void; retryUnknown: () => void; discard: () => void; registerExit: (fn: () => void) => void;
  recent: { import_id: number; source_name: string; review_path?: string }[];
};

export function CatalogProductIntakePanel(props: Props) {
  const { data, enabled, scopes, bindings, selections, busy, unknown, dirty } = props;
  const [filter, setFilter] = useState("all"); const [query, setQuery] = useState(""); const [page, setPage] = useState(1);
  const [editor, setEditor] = useState<{ row: SourceRow; selection: Selection }>(); const trigger = useRef<HTMLElement | null>(null);
  const [discardEditor,setDiscardEditor]=useState(false);
  const editorRegion=useRef<HTMLElement>(null);const returnToRow=useRef<string|undefined>(undefined);
  const editorDirty=!!editor&&JSON.stringify(editor.selection)!==JSON.stringify(selections[editor.row.row_id]);
  const onEditorDirtyChange=props.onEditorDirtyChange;
  useEffect(()=>{onEditorDirtyChange?.(editorDirty);},[editorDirty,onEditorDirtyChange]);
  const editing=!!editor;
  useEffect(()=>{if(!props.embedded)return;if(editing){(editorRegion.current?.querySelector('input:not([type=checkbox])') as HTMLElement|null)?.focus();}else if(returnToRow.current){document.getElementById(returnToRow.current)?.focus();returnToRow.current=undefined;}},[editing,props.embedded]);
  function closeEditor(){returnToRow.current=trigger.current?.id;setEditor(undefined);setDiscardEditor(false);}
  function cancelEditor(){if(editorDirty)setDiscardEditor(true);else closeEditor();}
  const fileInput = useRef<HTMLInputElement>(null); const dragDepth = useRef(0);
  const [dragActive, setDragActive] = useState(false); const [fileError, setFileError] = useState("");
  const locked = busy || unknown;
  const uploadDisabled = locked || dirty || !scopes.length;
  function acceptFiles(files: File[]) {
    dragDepth.current = 0; setDragActive(false);
    if (uploadDisabled) return;
    setFileError("");
    if (files.length !== 1) { setFileError("每次请上传一个本地XLSX文件，不支持文件夹、多文件或网页链接。"); return; }
    props.upload(files[0]!);
  }
  const soleScope = scopes.length === 1 ? scopes[0] : undefined;
  const scopeConflict = !!soleScope && !!data && data.source.sheets.some(sheet => bindings[sheet.name] !== undefined && bindings[sheet.name] !== soleScope.id);
  const legacy = !!data && data.source.sku_format_policy !== "style-color-size-v1";
  const all = data?.source.listing_rows || [];
  const counts = Object.fromEntries(Object.keys(intakeStateLabels).map(state => [state, all.filter(row => row.registration?.state === state).length]));
  const rows = all.filter(row => (filter === "all" || row.registration?.state === filter) && row.seller_sku.includes(query));
  const issues = all.filter(row => !!bindings[row.sheet] && intakeBlocking(row));
  const selected = all.filter(row => selections[row.row_id]?.include && selections[row.row_id]?.record_type === "variant");
  const reuseCount = selected.filter(row => row.registration?.state === "registered").length;
  const mappingCount = selected.filter(row => data?.assessments.find(item => item.row_id === row.row_id)?.can_map).length;
  const selectedCount = Object.values(selections).filter(item => item.include).length;
  const bound = !!data && Object.keys(bindings).length > 0 && all.filter(row => selections[row.row_id]?.include).every(row => !!bindings[row.sheet]);
  const editorContent=editor ? <>
      {intakeIssues(editor.row).map((issue, index) => <StatusMessage key={index} kind="danger" title={issue} />)}
      {editor.selection.record_type === "variant" && <dl className={styles.spec}><div><dt>款号</dt><dd>{editor.selection.style_code}</dd></div><div><dt>颜色</dt><dd>{editor.selection.color}</dd></div><div><dt>尺码</dt><dd>{editor.selection.size}</dd></div></dl>}
      {!intakeBlocking(editor.row) && <FormField label="人工核对备注"><Input disabled={locked} value={editor.selection.note} maxLength={1000} onChange={event => setEditor({ ...editor, selection: { ...editor.selection, note: event.target.value } })} /></FormField>}
      {editor.row.format_issues?.some(issue => issue.severity === "warning") && <label><input type="checkbox" disabled={locked} checked={editor.selection.include} onChange={event => setEditor({ ...editor, selection: { ...editor.selection, include: event.target.checked, note: event.target.checked ? editor.selection.note || "已核对原表与商品，确认拼写无误，保留原SKU。" : editor.selection.note } })} />已核对原表和商品，确认此拼写无误，保留原SKU</label>}
      <details><summary>查看平台资料与核对依据</summary><p>ASIN：{editor.row.child_asin || editor.row.asin || "未提供"} · FNSKU：{editor.row.fnsku || "未提供"}</p><p>{data?.assessments.find(item => item.row_id === editor.row.row_id)?.message || "尚未核对账号范围"}</p>{data?.assessments.find(item => item.row_id === editor.row.row_id)?.state === "source_difference" && <label><input type="checkbox" checked={editor.selection.use_official} disabled={locked} onChange={event => setEditor({ ...editor, selection: { ...editor.selection, use_official: event.target.checked, include: event.target.checked } })} />已核对差异，本次采用官方依据，原表值保留</label>}</details>
      {data?.inventory.find(sku => sku.sku_id === editor.row.registration?.sku_id)?.style_id && <LinkButton to={`/catalog/styles/${data.inventory.find(sku => sku.sku_id === editor.row.registration?.sku_id)!.style_id}`}>打开商品卡 / 发起修订</LinkButton>}
      <div className={styles.actions}><Button variant="secondary" disabled={locked} onClick={cancelEditor}>取消</Button><Button disabled={locked || intakeBlocking(editor.row)} variant="primary" onClick={() => { props.change(editor.row.row_id, editor.selection); closeEditor(); }}>保留本次核对</Button></div>
      {discardEditor&&<section role="alert"><h4>放弃本行未保留的修改？</h4><Button disabled={locked} onClick={()=>setDiscardEditor(false)}>继续核对</Button><Button variant="danger" disabled={locked} onClick={closeEditor}>放弃本行修改</Button></section>}
  </> : null;
  if(editor&&props.embedded)return <section ref={editorRegion} className={styles.page} aria-label="商品核对"><h3>{editor.row.seller_sku}</h3>{editorContent}</section>;
  return <section className={styles.page} aria-label="产品信息表建档">
    <header className={styles.header}><div>{!props.embedded&&<h2>商品建档</h2>}<p hidden>上传产品表，自动核对已建档商品并预填候选。核对无误后确认，有误先修改原表再上传。</p></div>{props.onManual?<Button variant="secondary" disabled={locked||dirty} onClick={props.onManual}>手工建档</Button>:<LinkButton variant="secondary" to="/catalog/production-sources?entry=specification">手工建档</LinkButton>}</header>
    {!props.embedded&&<ol className={styles.steps} aria-label="商品建档步骤"><li aria-current={!data ? "step" : undefined}>1 上传产品表</li><li aria-current={data && !bound ? "step" : undefined}>2 确认店铺范围</li><li aria-current={data && bound ? "step" : undefined}>3 核对候选并审核</li></ol>}
    {props.error && <StatusMessage kind="danger" title="本次操作未完成">{props.error}</StatusMessage>}
    {props.notice && <StatusMessage kind="info" title={props.notice} />}
    {enabled&&scopes.length===0&&<StatusMessage kind="info" title="请先确认店铺">{props.onSetup?<Button onClick={props.onSetup}>确认店铺</Button>:<LinkButton to="/catalog/maintenance?setup=source">确认店铺</LinkButton>}</StatusMessage>}
    {enabled === false ? <StatusMessage kind="warning" title="当前账号或环境未启用商品建档" /> : enabled === undefined ? <p role="status">正在读取建档权限…</p> : <>
      <div className={styles.upload} role="region" aria-label="产品表上传区" aria-disabled={uploadDisabled} data-dragging={dragActive && !uploadDisabled || undefined}
        onDragEnter={event => { event.preventDefault(); if (!uploadDisabled && event.dataTransfer.types.includes("Files")) { ++dragDepth.current; setDragActive(true); } }}
        onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = uploadDisabled ? "none" : "copy"; }}
        onDragLeave={event => { event.preventDefault(); if (--dragDepth.current <= 0) { dragDepth.current = 0; setDragActive(false); } }}
        onDrop={event => { event.preventDefault(); acceptFiles(Array.from(event.dataTransfer.files)); }}>
        <div className={styles.uploadMain}><UploadCloud size={28} aria-hidden="true" /><div><strong>{dragActive && !uploadDisabled ? "松开以上传产品表" : "将产品信息表拖到这里"}</strong><p hidden id="product-upload-help">每次一个XLSX，最多64MiB、1000条记录。也可点击选择文件。</p></div><Button variant="primary" disabled={uploadDisabled} onClick={() => fileInput.current?.click()} aria-describedby="product-upload-help">选择文件</Button></div>
        <Input ref={fileInput} type="file" hidden aria-label="选择产品信息表" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" disabled={uploadDisabled} onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ""; if (files.length) acceptFiles(files); }} />
        <p hidden>先检查文件类型、大小和实际格式，通过安全检查后再读取商品数据。只需SKU列；图片忽略，ASIN/FNSKU可保留。</p>

        {fileError && <StatusMessage kind="danger" title="文件未上传">{fileError}</StatusMessage>}
        {dirty && <Button variant="quiet" disabled={locked} onClick={props.discard}>放弃本次候选修改</Button>}
        {unknown && <p>上传结果尚待核实，请先处理原操作。</p>}
      </div>
      {unknown && <StatusMessage kind="warning" title="请先核实原操作结果">当前输入已锁定，避免重复上传或保存。<Button disabled={busy} onClick={props.retryUnknown}>查询或重发原操作</Button></StatusMessage>}
      {data ? <>
        {legacy && <StatusMessage kind="info" title="这是历史清单，原记录继续保留">要使用本页的严格SKU检查，请重新上传原表。<LinkButton to={`/catalog/production-sources?entry=amazon-listing&listing=${data.import_id}`}>继续原核对流程</LinkButton></StatusMessage>}
        <div className={styles.source}><strong>{data.source.source_name}</strong><span>{all.length}条记录</span><LinkButton reloadDocument download to={`/api/catalog/imports/${data.import_id}/file`}>下载原始表格</LinkButton></div>
        {scopeConflict&&<StatusMessage kind="warning" title="原资料的店铺归属与当前设置不一致，请核对后再继续。"/>}
        <Table title="本次导入店铺"><thead><tr><th>来源工作表</th><th>规格数</th><th>父级数</th><th>导入店铺</th></tr></thead><tbody>{data.source.sheets.map(sheet => <tr key={sheet.name}><th scope="row">{sheet.name}</th><td>{all.filter(row => row.sheet === sheet.name && row.suggested_type === "variant").length}</td><td>{all.filter(row => row.sheet === sheet.name && row.suggested_type === "parent").length}</td><td><FormField label={`${sheet.name} 对应店铺`} ><Select disabled={locked} value={bindings[sheet.name] || ""} onChange={event => props.bind(sheet.name, event.target.value)}><option value="">本次不导入</option>{scopes.map(scope => <option key={scope.id} value={scope.id}>{scope.seller_account_display_name} · {scope.marketplace_scope_code}</option>)}</Select></FormField></td></tr>)}</tbody></Table>
        {bound && !props.compared && <StatusMessage kind="warning" title="范围已改变，请重新核对"><Button disabled={locked} onClick={props.retryCompare}>重新核对当前目录</Button></StatusMessage>}
        <div className={styles.filters} role="group" aria-label="建档状态筛选"><Button variant="quiet" aria-pressed={filter === "all"} onClick={() => { setFilter("all"); setPage(1); }}>全部 {all.length}</Button>{Object.entries(intakeStateLabels).filter(([state]) => ["registered", "missing", "parent", "error"].includes(state) || counts[state]).map(([state, label]) => <Button key={state} variant="quiet" aria-pressed={filter === state} onClick={() => { setFilter(state); setPage(1); }}>{label} {counts[state]}</Button>)}</div>
        {issues.length > 0 && <StatusMessage kind="danger" title={`${issues.length}行有问题，请修改原表后重新上传`}>原表位置和问题类型见下表。本批暂不保存候选，系统不会自动改SKU。<Button variant="secondary" onClick={() => { setFilter("error"); setPage(1); }}>定位问题行</Button></StatusMessage>}
        <Input type="search" aria-label="查找本表SKU" placeholder="查找本表SKU，区分大小写" value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} />
        <Table title="商品建档检查结果"><thead><tr><th>本批选择</th><th>SKU</th><th>标准尺码</th><th>导入店铺</th><th>建档状态</th><th>原表位置</th><th>检查结果</th><th>核对</th></tr></thead><tbody>{rows.slice((page - 1) * 20, page * 20).map(row => {
          const selection = selections[row.row_id]; const rowIssues = intakeIssues(row); const assessment = data.assessments.find(item => item.row_id === row.row_id);
          const blocked = !bindings[row.sheet] || intakeBlocking(row) || ["conflict", "disabled", "error"].includes(row.registration?.state || "") || assessment && assessment.primary_row !== row.row_id;
          return <tr key={row.row_id}><td><input type="checkbox" aria-label={`选择 ${row.sheet} ${row.seller_sku}`} disabled={locked || blocked || !selection} checked={selection?.include || false} onChange={event => props.change(row.row_id, { include: event.target.checked })} /></td><th scope="row"><code>{row.seller_sku || "SKU为空"}</code></th><td>{data.inventory.find(sku => sku.sku_id === row.registration?.sku_id)?.standard_size || row.suggestion?.size || selection?.size || ""}</td><td>{scopes.find(scope => scope.id === bindings[row.sheet])?.seller_account_display_name || "本次不导入"}</td><td>{intakeStateLabels[row.registration?.state || ""] || "状态待核"}</td><td>{row.sheet} · {row.cell_locations?.seller_sku || `第${row.row}行`}</td><td>{rowIssues.length ? rowIssues.map((issue, index) => <p key={index}>{issue}</p>) : row.suggested_type === "parent" ? "保留父级，不建立库存规格" : row.registration?.state === "registered" ? data.mappings.some(item => item.report_source_scope_id === bindings[row.sheet] && item.seller_sku === row.seller_sku) ? "已关联本店商品" : "复用商品并补齐本店关联" : row.registration?.state === "missing" ? "款号、颜色、尺码已预填" : "请核对身份归属"}{assessment?.state === "source_difference" && <p>平台资料有差异，需在核对中明确选择依据。</p>}</td><td><Button id={`intake-review-${row.row_id}`} variant="quiet" disabled={locked || !selection} onClick={event => { if (selection) { trigger.current = event.currentTarget; setEditor({ row, selection: { ...selection } }); } }}>查看 / 核对</Button></td></tr>;
        })}</tbody></Table>
        {!rows.length && <p>当前筛选没有记录。</p>}
        <Pagination page={page} totalItems={rows.length} totalPages={Math.max(1, Math.ceil(rows.length / 20))} onPageChange={setPage} itemLabel="记录" />
        <footer className={styles.footer}><p>已选{selectedCount}条 · 新增{selected.length-reuseCount}个 · 复用{reuseCount}个 · 店铺关联{mappingCount}个</p><Button variant="primary" disabled={locked || !bound || !props.compared || legacy || issues.length > 0 || !selectedCount} onClick={props.save}>核对无误，保存候选</Button></footer>
        <details><summary>候选记录与后续更正</summary><p hidden>审核前可继续核对本批；审核后误判请从商品卡发起修订，渠道改归属沿原高风险更正流程，原记录保留。</p>{data.processing?.candidates.map(candidate => <p key={candidate.import_id}>{props.onReviewCandidate?<Button disabled={locked||dirty} onClick={()=>props.onReviewCandidate?.(candidate.import_id)}>{candidate.status === "approved" ? "查看已批准记录" : ["withdrawn", "superseded"].includes(candidate.status) ? "查看历史候选" : candidate.status === "rejected" ? "修订已退回候选" : "继续审核 / 修订候选"} #{candidate.import_id}</Button>:<LinkButton to={candidate.review_path}>{candidate.status === "approved" ? "查看已批准记录" : ["withdrawn", "superseded"].includes(candidate.status) ? "查看历史候选" : candidate.status === "rejected" ? "修订已退回候选" : "继续审核 / 修订候选"} #{candidate.import_id}</LinkButton>}</p>)}<LinkButton to="/catalog">打开商品目录</LinkButton></details>
      </> : <section><h3>继续已有资料</h3>{props.recent.length ? props.recent.map(item => <p key={item.import_id}>{props.onResumeSource?<Button disabled={locked||dirty} onClick={()=>item.review_path?.startsWith("/catalog/imports/") ? props.onReviewCandidate?.(item.import_id) : props.onResumeSource?.(item.import_id)}>{item.source_name} · 批次 #{item.import_id}</Button>:<LinkButton to={item.review_path?.startsWith("/catalog/imports/") ? item.review_path : `/catalog/production-sources?entry=product-intake&listing=${item.import_id}`}>{item.source_name} · 批次 #{item.import_id}</LinkButton>}</p>) : <p>上传后即可查看每个SKU的建档状态。</p>}</section>}
    </>}
    {busy && <p role="status">正在读取或核对，请等待…</p>}
    {editor && (props.embedded ? <section aria-label="商品核对"><h3>{editor.row.seller_sku}</h3>{editorContent}</section> : <Dialog open onOpenChange={open => { if (!open) cancelEditor(); }} dismissDisabled={locked} returnFocusTarget={trigger} title={editor.row.seller_sku} description={`${editor.row.sheet} · ${editor.row.cell_locations?.seller_sku || `第${editor.row.row}行`}`} contentClassName={styles.dialog}>
{editorContent}</Dialog>)}

    {!props.embedded&&<IntakeNavigationGuard dirty={dirty||editorDirty} busy={busy} unknown={unknown} registerExit={props.registerExit}/>}
  </section>;
}

function IntakeNavigationGuard({dirty,busy,unknown,registerExit}:{dirty:boolean;busy:boolean;unknown:boolean;registerExit:(fn:()=>void)=>void}) {
 const leave=useProductionLeave(dirty,busy,unknown,['history_page']);
 useEffect(()=>registerExit(leave.allowLeave));
 return leave.prompt;
}
