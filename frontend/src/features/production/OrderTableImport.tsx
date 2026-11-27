import { Disclosure } from "../../design-system";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Download } from "lucide-react";
import { Link } from "react-router-dom";
import { writeApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, FormField, Input, LinkButton, StatusMessage, Table } from "../../design-system";
import type { Document, Sku } from "./types";
import { units } from "./types";
import styles from "./OrderWorkbench.module.css";

export type OrderImportPreview = {
  table_baseline?: import("./TableImportReview").TableBaseline;
  preview_id: string; filename: string; issues: { row: number; message: string }[];
  rows: { sku_id: string; sku_label: string; expected_units: string }[];
  command: { business_number?: string; business_date?: string; destination?: string; destination_id?: string; destination_type?: string; source_system?: string; source_event_kind?: string; external_event_id?: string; source_batch?: string; _source_digest?: string };
  duplicate_document?: Document;
  source_check?: { candidates: Document[]; duplicate_document?: Document; content_matches?: boolean };
  source_table?: {
    sheet: string; source_units: string; excluded_sheets: string[]; excluded_rows: number[];
    rows: { source_row: number; order_date: string; style_code: string; sku_code: string; expected_units: string; sku_label?: string; mapping_status: string }[];
  };
};

export function OrderTableImport({ context, ready, locked, skus, sourceField, onBusy, onSave, onCancel, onDirtyChange, cancelLabel = "返回订单", inline = false, onApply }: {
  inline?: boolean; onApply?: (result: OrderImportPreview) => void;
  context: string; ready: boolean; locked: boolean;
  skus: Sku[]; sourceField: ReactNode;
  onBusy: (busy: boolean) => void; onSave: (preview: string) => void;
  onCancel: () => void; onDirtyChange?: (dirty: boolean) => void; cancelLabel?: string;
}) {
  const [templatesOpen,setTemplatesOpen]=useState(false);
  const [file, setFile] = useState<File>();
  const [result, setResult] = useState<{ context: string; preview: OrderImportPreview }>();
  useEffect(() => {onDirtyChange?.(!!file || !!result);},[file,result,onDirtyChange]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const { generation, registerSensitivePurge } = useAuthzGeneration();
  const current = useRef({ context, generation }); current.current = { context, generation };
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => registerSensitivePurge(() => { setFile(undefined); setResult(undefined); setError(undefined); }), [registerSensitivePurge]);
  const preview = result?.context === context ? result.preview : undefined;
  async function upload(selected = file) {
    const file = selected;
    if (!file || !ready || busy || locked) return;
    if (!file.name.toLowerCase().endsWith(".xlsx") || file.size > 2_000_000 || file.size === 0) { setResult(undefined); setError("请选择不超过2MB的标准XLSX文件。"); return; }
    setBusy(true); onBusy(true); setError(undefined); setResult(undefined);
    const start = { context, generation };
    try {
      const query = new URLSearchParams({ ...JSON.parse(context) as Record<string, string>, filename: file.name, mode: "create", workbench_order: "true" });
      const value = await writeApi<OrderImportPreview>(`/api/production/files/orders/preview?${query}`, { rawBody: file, headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }, idempotent: false });
      if (active.current && current.current.context === start.context && current.current.generation === start.generation) {
        if (inline && !value.issues.length && value.rows.length && !value.duplicate_document && !value.source_check?.duplicate_document && value.source_check?.content_matches !== false) onApply?.(value);
        else setResult({ context, preview: value });
      }
    } catch (reason) {
      if (active.current && current.current.context === start.context && current.current.generation === start.generation) setError(reason instanceof Error ? reason.message : "表格预览失败，请重新上传。");
    } finally { if (active.current) { setBusy(false); onBusy(false); } }
  }
  const existing = preview?.duplicate_document || (preview?.source_check?.content_matches ? preview.source_check.duplicate_document : undefined);
  const conflict = preview?.source_check?.content_matches === false;
  if (inline) return <section className={styles.inlineImport} aria-label="下单表格导入">
    <div className={styles.importToolbar}><Input aria-label="下单XLSX文件（不超过2MB）" type="file" accept=".xlsx" disabled={!ready || locked || busy} onChange={event => {const selected=event.target.files?.[0];setFile(selected);if(selected)void upload(selected);event.target.value="";}}/><LinkButton to="/api/production/files/orders/template?version=v4" reloadDocument download icon={<Download/>} variant="quiet">下载下单模板</LinkButton></div>
    {!ready && <p>选择工厂和计划入库仓后，可直接导入到下方商品表。</p>}
    {busy && <p role="status">正在读取下单表…</p>}
    {error && <StatusMessage kind="danger" title="导入未完成，原填写内容已保留">{error}</StatusMessage>}
    {preview && <StatusMessage kind={existing?"info":"danger"} title={existing?"此来源已登记，请打开原订单":"表格未填入，原填写内容已保留"}>{preview.issues.map((issue,i)=><p key={i}>第{issue.row}行 {issue.message}</p>)}{(existing || preview.source_check?.duplicate_document) && <Link to={`/production/orders/${(existing || preview.source_check!.duplicate_document)!.id}`}>打开原订单核对</Link>}</StatusMessage>}
    {preview?.source_table && <Table aria-label="原下单表四字段核对"><thead><tr><th>原表行</th><th>款号</th><th>SKU</th><th>数量</th><th>商品关联</th></tr></thead><tbody>{preview.source_table.rows.map(row=><tr key={row.source_row}><td>{row.source_row}</td><td>{row.style_code}</td><td>{row.sku_code}</td><td>{row.expected_units}</td><td>{row.sku_label || "未唯一关联，请先核对商品资料"}</td></tr>)}</tbody></Table>}
    <div><Button variant="quiet" aria-expanded={templatesOpen} onClick={()=>setTemplatesOpen(!templatesOpen)}>{templatesOpen?"收起其他模板":"其他模板与原表"}</Button>{templatesOpen && <><div className={styles.actions}><LinkButton variant="quiet" reloadDocument download to="/api/production/files/orders/template?version=v3">规格ID模板</LinkButton><LinkButton variant="quiet" reloadDocument download to="/api/production/files/orders/template">旧SKU模板</LinkButton><LinkButton variant="quiet" reloadDocument download to="/api/production/files/orders/template?version=v2">含来源模板</LinkButton><Link to="/production/orders/intake?method=table&layout=raw">其他排版原表整理</Link></div></>}</div>
  </section>;
  return <div className={styles.orderImport}>
    <header className={styles.importHeading}><div><h3>从表格添加产品</h3><p>一份表格对应一张生产单，使用上方所选工厂和仓库。</p></div><LinkButton to="/api/production/files/orders/template?version=v4" reloadDocument icon={<Download />} variant="secondary">下载下单模板</LinkButton></header>
    <div className={styles.importUpload}><FormField label="下单XLSX文件（不超过2MB）" hint="最新版只读取下单日期、款号、SKU和订单数量；原八列表中的出货日期、品名、颜色及图片忽略。旧v1/v2/v3模板继续支持。"><Input type="file" accept=".xlsx" disabled={locked || busy} onChange={e => { setFile(e.target.files?.[0]); setResult(undefined); setError(undefined); }} /></FormField></div>
    <div className={styles.importActions}><div className={styles.actions}><Button variant="primary" disabled={!file || !ready || locked || busy} loading={busy} onClick={() => void upload()}>读取并预览</Button><Button variant="quiet" disabled={locked || busy} onClick={onCancel}>{cancelLabel}</Button></div><p role="status">{!ready ? "请先选择生产工厂和入库仓库及货权" : !file ? "请选择文件后预览" : "先预览核对，再生成草稿；不会直接下单。"}</p></div>
    <div className={styles.importHelp}>
      <Disclosure className={styles.importCatalog}><summary>商品规格填写参考</summary><Table title="商品规格填写参考"><thead><tr><th>商品规格ID（v3）</th><th>款号 / 颜色 / 尺码</th><th>SKU编码（v1/v2）</th></tr></thead><tbody>{skus.filter(s => s.status === "active").map(s => <tr key={s.sku_id}><td>{s.sku_id}</td><td>{s.label}</td><td>{s.code || "尚未登记，请使用v3"}</td></tr>)}</tbody></Table></Disclosure>
      <Disclosure className={styles.importDisclosure}><summary>来源及区别说明（可选）</summary><div>{sourceField}</div></Disclosure>
      <Disclosure className={styles.importDisclosure}><summary>填写规则、旧模板与其他原表</summary><div><p>默认v4模板仅四列：下单日期、款号、SKU、订单数量。也支持这四列齐全的原八列下单表，按表头选择唯一业务页，排除合计及旧测算页。日期以单元格为准；SKU按当前目录及来源范围匹配，不按编码拆分猜测身份。每份一张订单、同一下单日期，数量为正整数。</p><p>导出的下单表回导先核对原订单，不新增第二笔；内容更改请回原订单更正。无编码商品可使用原v3规格ID模板，旧v1/v2及原表整理继续保留。</p><div className={styles.actions}><a href="/api/production/files/orders/template?version=v3">规格ID模板（v3）</a><a href="/api/production/files/orders/template">SKU编码模板（v1）</a><a href="/api/production/files/orders/template?version=v2">含来源模板（v2）</a><Link to="/production/orders/intake?method=table">其他原表整理</Link></div></div></Disclosure>
    </div>
    {result && !preview && <StatusMessage kind="info" title="整单信息已变更，请重新预览" />}
    {error && <StatusMessage kind="danger" title="预览未完成">{error}</StatusMessage>}
    {preview && <section className={styles.importPreview}>
      <h3>导入预览 · {preview.filename}</h3>
      <dl className={styles.metadata}><div><dt>业务订单号</dt><dd>{preview.command.business_number || "未填写"}</dd></div><div><dt>下单日期</dt><dd>{preview.command.business_date || "待核对"}</dd></div><div><dt>计划发货目的地</dt><dd>{preview.command.destination || "暂未确定"}</dd></div></dl>
      {!!preview.issues.length && <StatusMessage kind="danger" title="请修正表格问题后重新预览">{preview.issues.map((issue, i) => <p key={i}>{issue.row ? `第${issue.row}行：` : ""}{issue.message}</p>)}</StatusMessage>}
      {existing && <StatusMessage kind="info" title="来源已登记，不重复生成订单"><Link to={`/production/orders/${existing.id}`}>打开已有订单：{existing.business_number || existing.system_number}</Link></StatusMessage>}
      {conflict && <StatusMessage kind="danger" title="可靠来源内容冲突，请打开原订单核对">{preview.source_check?.duplicate_document && <Link to={`/production/orders/${preview.source_check.duplicate_document.id}`}>打开原订单</Link>}</StatusMessage>}
      {!existing && !conflict && !!preview.source_check?.candidates.length && <StatusMessage kind="warning" title="发现同日同款同量的候选订单">{preview.source_check.candidates.map(candidate => <p key={candidate.id}><Link to={`/production/orders/${candidate.id}`}>{candidate.business_number || candidate.system_number}</Link></p>)}请核对是否重复；确为另一张订单时，展开“来源及区别说明”补充依据并重新预览。草稿仍须单独确认下单。</StatusMessage>}
      {preview.source_table ? <><p>业务页：{preview.source_table.sheet} · {preview.source_table.rows.length}条明细 · 有效正整数合计{units(preview.source_table.source_units)}件。已排除{preview.source_table.excluded_rows.length}行合计或说明{preview.source_table.excluded_sheets.length ? `及工作表：${preview.source_table.excluded_sheets.join("、")}` : ""}。</p><Table title="原下单表四字段核对"><thead><tr><th>原表行</th><th>下单日期</th><th>款号</th><th>SKU</th><th>订单数量（件）</th><th>商品关联</th></tr></thead><tbody>{preview.source_table.rows.map(row => <tr key={row.source_row}><td>{row.source_row}</td><td>{row.order_date || "待核对"}</td><td>{row.style_code || "待核对"}</td><td>{row.sku_code || "待核对"}</td><td>{row.expected_units || "待核对"}</td><td>{row.sku_label || "未唯一关联，请先核对商品资料"}</td></tr>)}</tbody></Table></> : <Table title="已识别产品"><thead><tr><th>明细序号</th><th>商品规格</th><th>计划生产数量（件）</th></tr></thead><tbody>{preview.rows.map((row, index) => <tr key={index}><td>{index + 1}</td><td>{row.sku_label}</td><td>{units(row.expected_units)}</td></tr>)}</tbody></Table>}
      {!preview.issues.length && !existing && !conflict && preview.rows.length > 0 && <><p className={styles.muted}>生成草稿后，可继续核对并单独确认下单；此操作不登记生产、不入库，也不出货。</p><Button variant="primary" disabled={locked || busy} onClick={() => onSave(preview.preview_id)}>生成订单草稿</Button></>}
    </section>}
  </div>;
}
