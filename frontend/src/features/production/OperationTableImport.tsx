import { Disclosure } from "../../design-system";
import { useEffect, useRef, useState } from "react";
import { Download, Upload } from "lucide-react";
import { writeApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, FormField, Input, LinkButton, StatusMessage } from "../../design-system";
import type { Carton, Document } from "./types";
import styles from "./OrderWorkbench.module.css";

export type OperationImportPreview = {
  table_baseline?: import("./TableImportReview").TableBaseline;
  kind: "receipt" | "packing"; filename: string; source_digest: string;
  source_files?: {source_id:string;source_layout:"standard"|"packing_totals";filename:string;source_digest:string}[];
  warehouse_id?: string; owner_id?: string; source_id?: string; order_id: string; order_revision: string; total_units: string; box_count: number;
  issues: { row: number; message: string; sheet?:string; cell?:string; source_filename?:string; source_row?:number; stage?: "reading" | "business" }[];
  source_row_count?:number; source_total_units?:string|null;
  source_layout?: "standard" | "packing_totals";
  source_rows?: { row: number; sku_code: string; sku_id?: string; units: string | null; source_cell: string; source_filename?:string; source_row?:number }[];
  rows: { row: number; sku_id: string; order_line_id: string; sku_label: string; qualified_units?: string; pending_units?: string; defective_units?: string; box_number?: string; units?: string }[];
  cartons: Carton[];
};

export function OperationTableImport({ kind, order, warehouse, batch = false, inline = false, existing, context, eligible, locked, onBusy, onApply }: {
  kind: "receipt" | "packing"; order?: Document; warehouse?: {warehouse_id:string;owner_id:string}; batch?: boolean; context: string; eligible: string[];
  inline?: boolean; existing?:OperationImportPreview; locked: boolean; onBusy: (busy: boolean) => void; onApply: (result: OperationImportPreview) => void;
}) {
  const [file, setFile] = useState<File>();
  const [layout,setLayout]=useState("standard");
  const [result, setResult] = useState<{ context: string; preview: OperationImportPreview }>();
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const { generation, registerSensitivePurge } = useAuthzGeneration();
  const current = useRef({ context, generation }); current.current = { context, generation };
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => registerSensitivePurge(() => { setFile(undefined); setResult(undefined); setError(""); }), [registerSensitivePurge]);
  const preview = result?.context === context ? result.preview : undefined;
  const readingIssues = preview?.issues.filter(issue => issue.stage !== "business") ?? [];
  const businessIssues = preview?.issues.filter(issue => issue.stage === "business") ?? [];
  const endpoint = warehouse ? "/api/production/shipments/table" : batch ? "/api/production/receipt-batches/table" : `/api/production/orders/${order!.id}/tables/${kind}`;
  const scopeQuery = new URLSearchParams(warehouse ? warehouse : batch ? { orders: order!.revision } : { expected_revision: order!.revision });
  async function upload(selectedFiles = file ? [file] : []) {
    if (!selectedFiles.length || locked || busy) return;
    if (selectedFiles.some(selectedFile => !selectedFile.name.toLowerCase().endsWith(".xlsx") || !selectedFile.size || selectedFile.size > 2_000_000)) { setError("请选择不超过2MB且非空的XLSX文件。"); return; }
    const start = { context, generation };
    setBusy(true); onBusy(true); setError(""); setResult(undefined);
    try {
      const previews:OperationImportPreview[] = [];
      for (const selectedFile of selectedFiles) {
        const query = new URLSearchParams(scopeQuery); query.set("filename", selectedFile.name);
        if(warehouse&&layout!=="standard")query.set("layout",layout);
        const preview = await writeApi<OperationImportPreview>(`${endpoint}/preview?${query}`, { rawBody: selectedFile, headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }, idempotent: false });
        if (!active.current || current.current.context !== start.context || current.current.generation !== start.generation) return;
        previews.push(preview);
      }
      let value = previews[0]!;
      if (warehouse && inline && (previews.length > 1 || existing)) {
        const originals = existing ? existing.source_files || [{...existing,source_id:existing.source_id!,source_layout:existing.source_layout||"standard"}] : [];
        const sources = [...originals, ...previews].map(preview=>({source_id:preview.source_id,layout:preview.source_layout||"standard"}));
        if (sources.length > 20) throw new Error("同一批最多合并20份装箱单，请分批出货。");
        value = await writeApi<OperationImportPreview>(`${endpoint}/combine`, {body:{...warehouse,sources},idempotent:false});
      }
      if (!active.current || current.current.context !== start.context || current.current.generation !== start.generation) return;
      if (value.kind !== kind || (warehouse ? value.warehouse_id !== warehouse.warehouse_id || value.owner_id !== warehouse.owner_id : value.order_id !== order!.id || value.order_revision !== order!.revision) || value.rows.some(row => !eligible.includes(row.sku_id) || !warehouse && !order!.lines?.some(line => line.id === row.order_line_id && line.sku_id === row.sku_id))) { setError("预览来源或可操作商品范围已改变，请重新核对当前操作范围。"); return; }
      if (inline && value.source_rows?.length && value.issues.every(issue => issue.stage === "business")) onApply(value);
      else if (value.issues.length || !value.rows.length) setResult({ context, preview: value });
      else onApply(value);
    } catch (reason) {
      if (active.current && current.current.context === start.context && current.current.generation === start.generation) setError(reason instanceof Error ? reason.message : "表格预览未完成，请重新读取。");
    } finally { if (active.current) { setBusy(false); onBusy(false); } }
  }
  if (inline) return <section className={styles.inlineImport} aria-label={warehouse ? "仓库出货表格导入" : kind === "receipt" ? "入库表格导入" : "装箱表格导入"}>
    <div className={styles.importToolbar}>
      {warehouse && <select aria-label="表格格式" disabled={locked || busy} value={layout} onChange={event => { setLayout(event.target.value); setResult(undefined); setError(""); }}><option value="standard">标准数量表</option><option value="packing_totals">原装箱单（按总数量）</option></select>}
      <Input ref={fileInput} hidden={kind === "receipt"} aria-label="本次导入的XLSX文件（不超过2MB）" type="file" accept=".xlsx" multiple={!!warehouse} disabled={locked || busy} onChange={event => { const selected = Array.from(event.target.files || []); setFile(selected[0]); if (selected.length) void upload(selected); event.target.value = ""; }} />
      {kind === "receipt" && <Button icon={<Upload size={16} />} loading={busy} loadingLabel="读取中" disabled={locked} onClick={() => fileInput.current?.click()}>导入表格</Button>}
      <LinkButton reloadDocument download icon={<Download />} variant="quiet" aria-label={kind === "receipt" ? "下载入库模板" : undefined} to={`${endpoint}/template?${scopeQuery}`}>{warehouse ? "下载出货模板" : kind === "receipt" ? "下载模板" : "下载装箱模板"}</LinkButton>
    </div>
    {busy && kind !== "receipt" && <p role="status">正在读取表格…</p>}
    {error && <StatusMessage kind="danger" title="导入未完成，原填写内容已保留">{error}</StatusMessage>}
    {preview && <StatusMessage kind="danger" title="请修正原表后重新导入">{readingIssues.map((issue,index) => <p key={index}>{issue.source_filename ? `${issue.source_filename} 第${issue.source_row}行` : `第${issue.row}行`} {issue.message}</p>)}</StatusMessage>}
  </section>;
  return <section className={`${styles.orderImport} ${styles.importUpload} ${preview?.source_rows ? styles.originalRead : ""}`} aria-label={warehouse ? "仓库出货表格导入" : kind === "receipt" ? "入库表格导入" : "装箱表格导入"}>
    {!preview?.source_rows && <>
    <header className={styles.importHeading}><div><h3>{warehouse ? "导入本批出货明细" : kind === "receipt" ? "从表格填入入库数量" : "从表格填入装箱明细"}</h3></div><LinkButton reloadDocument download icon={<Download />} variant="secondary" to={`${endpoint}/template?${scopeQuery}`}>{warehouse ? "下载出货模板" : kind === "receipt" ? "下载入库模板" : "下载装箱模板"}</LinkButton></header>
    {warehouse&&<FormField label="表格格式" hint={layout==="packing_totals"?"第一列作为SKU，读取“总数量”；忽略箱号、合计和重量尺寸，空白工作表不参与导入。":undefined}><select aria-label="表格格式" disabled={locked||busy} value={layout} onChange={event=>{setLayout(event.target.value);setResult(undefined);setError("");}}><option value="standard">标准数量表</option><option value="packing_totals">原装箱单（按总数量）</option></select></FormField>}
    <FormField label="本次导入的XLSX文件（不超过2MB）"><Input type="file" accept=".xlsx" disabled={locked || busy} onChange={event => { setFile(event.target.files?.[0]); setResult(undefined); setError(""); }} /></FormField>
    <Disclosure><summary>导入说明</summary><p>将替换未保存的数量{kind === "packing" && !warehouse ? "和箱明细" : ""}，不会直接入库或发货。{batch && "同商品跨订单请分别填量；空数量行不登记。"}</p></Disclosure><div className={styles.importActions}><Button variant="secondary" loading={busy} disabled={!file || locked} onClick={() => void upload()}>读取并填入下方表格</Button></div>
    </>}
    {result && !preview && <StatusMessage kind="info" title="当前操作范围已改变，请重新预览表格" />}
    {error && <StatusMessage kind="danger" title="导入预览未完成">{error}</StatusMessage>}
    {preview?.source_rows ? <section className={styles.importPreview} aria-label="原装箱单读取结果">
      <StatusMessage kind={readingIssues.length ? "danger" : "info"} title={readingIssues.length ? "原单有内容待核对" : "原单读取完成"}>
        <p>{preview.source_row_count}个规格 · {preview.source_total_units != null ? `共${preview.source_total_units}件` : "总数量待核"}</p>
        {readingIssues.map((issue, index) => <p key={index}>{issue.sheet} 第{issue.row}行（{issue.cell}） {issue.message}</p>)}
      </StatusMessage>
      <div className={styles.originalRows}><table aria-label="原单商品明细"><thead><tr><th scope="col">SKU</th><th scope="col">数量</th></tr></thead><tbody>
        {preview.source_rows.map(row => <tr key={row.row}><td title={`第${row.row}行 ${row.source_cell}`}>{row.sku_code}</td><td>{row.units ?? "待核"}</td></tr>)}
      </tbody></table></div>
      {businessIssues.length > 0 && <Disclosure><summary>后续出货校验（{businessIssues.length}项）</summary><p>商品与库存核对完成后可填入出货表。原填写内容已保留。</p>{businessIssues.map((issue, index) => <p key={index}>{issue.sheet} 第{issue.row}行 {issue.message}</p>)}</Disclosure>}
      <Button variant="quiet" disabled={locked || busy} onClick={() => { setResult(undefined); setFile(undefined); setError(""); }}>重新选择文件</Button>
    </section> : preview && <StatusMessage kind="danger" title="表格未填入，原填写内容已保留">{preview.source_row_count!==undefined&&<p>原单已读取{preview.source_row_count}个规格，{preview.source_total_units!=null?`共${preview.source_total_units}件`:"总数量待核"}；请先处理以下问题。</p>}{preview.issues.length ? preview.issues.map((issue, index) => <p key={index}>{issue.sheet?`${issue.sheet} `:""}{issue.row ? `第${issue.row}行${issue.cell?`（${issue.cell}）`:""}：` : ""}{issue.message}</p>) : <p>没有可填入的数量，请在模板填写本次实际数量。</p>}<p>修正源文件后重新读取，或收起导入继续手工填写。</p></StatusMessage>}
  </section>;
}
