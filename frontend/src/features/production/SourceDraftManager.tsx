import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { requestApi, writeApi } from "../../api/client";
import { RequestGate } from "../../api/requestGate";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { LinkButton, Button, FormField, Input, PageHeader, StatusMessage  } from "../../design-system";
import { useProductionLeave } from "./useProductionLeave";
import { type Kind, units } from "./types";
import styles from "./Production.module.css";

type SourceItem = {
  source_id: string; kind: Kind; filename: string; origin: "SAMPLE" | "UPLOAD";
  available: boolean; error?: string; source_units?: string; row_count?: number;
  issue_count?: number; saved?: boolean; revision?: number; business_number?: string;
  business_date?: string; draft_units?: string | null; updated_at?: string; uploaded_at: string;
};
type UploadResult = { item: SourceItem; duplicate: boolean };
const sourceHref = (item: SourceItem) => `/production/source-drafts/${item.kind}?sample=${encodeURIComponent(item.source_id)}`;

export function SourceDraftManager({ canWrite, recordsOnly = false, initialKind }: { canWrite: boolean; recordsOnly?: boolean; initialKind?: Kind }) {
  const [params, setParams] = useSearchParams();
  const [items, setItems] = useState<SourceItem[]>();
  const [readError, setReadError] = useState<string>();
  const [refresh, setRefresh] = useState(0);
  const [kind, setKind] = useState<Kind>(initialKind ?? (params.get("kind") === "shipments" ? "shipments" : "orders"));
  const [file, setFile] = useState<File>();
  const [busy, setBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string>();
  const [result, setResult] = useState<UploadResult>();
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadGate = useRef<RequestGate | undefined>(undefined);
  const { generation, registerSensitivePurge } = useAuthzGeneration();
  useEffect(() => registerSensitivePurge(() => {
    uploadGate.current?.abortAll(); setItems(undefined); setReadError(undefined);
    setFile(undefined); setResult(undefined); setUploadError(undefined); setBusy(false);
    if (fileInput.current) fileInput.current.value = "";
  }), [registerSensitivePurge]);
  useEffect(() => () => { uploadGate.current?.dispose(); uploadGate.current = undefined; }, []);
  useEffect(() => {
    const gate = new RequestGate(); const ticket = gate.begin([refresh], generation);
    setItems(undefined); setReadError(undefined);
    void requestApi<{ items: SourceItem[] }>("/api/production/source-drafts", { signal: ticket.signal })
      .then(value => { if (ticket.isCurrent()) setItems(value.items); })
      .catch((reason: unknown) => { if (ticket.isCurrent()) setReadError(reason instanceof Error ? reason.message : "草稿列表读取未完成。"); });
    return () => gate.dispose();
  }, [generation, refresh]);
  const leave = useProductionLeave(!!file && !result, busy, false);
  async function upload() {
    if (!file || busy) return;
    if (!file.name.toLowerCase().endsWith(".xlsx") || !file.size || file.size > 2_000_000) {
      setUploadError("请选择不超过2MB且非空的XLSX原表。"); fileInput.current?.focus(); return;
    }
    uploadGate.current ??= new RequestGate();
    const ticket = uploadGate.current.begin([kind, file.name], generation);
    setBusy(true); setUploadError(undefined); setResult(undefined);
    try {
      const value = await writeApi<UploadResult>(`/api/production/source-drafts/${kind}/upload?filename=${encodeURIComponent(file.name)}`, {
        rawBody: file, idempotent: false, signal: ticket.signal,
        headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
      });
      if (ticket.isCurrent()) { setResult(value); setRefresh(value => value + 1); }
    } catch (reason) {
      if (ticket.isCurrent()) setUploadError(reason instanceof Error ? reason.message : "上传结果待核实。");
    } finally { if (ticket.isCurrent()) setBusy(false); }
  }
  const scopedItems = items?.filter(item => !initialKind || item.kind === initialKind);
  const visible = scopedItems?.filter(item => (
    (!params.get("q") || `${item.filename} ${item.business_number || ""}`.toLocaleLowerCase().includes(params.get("q")!.toLocaleLowerCase()))
    && (!params.get("kind") || initialKind !== undefined || item.kind === params.get("kind"))
    && (!params.get("saved") || (params.get("saved") === "yes" ? item.saved === true : item.saved === false))
  ));
  return <>{!recordsOnly && <PageHeader eyebrow="PRODUCTION · B 1.1.0 · 本地草稿" title="原表与导入草稿" description="集中管理当前账号的订单表和装箱单来源，接着上次的核对继续编辑。这里的草稿尚未过账，不计入有效订单、出货或库存。" actions={<div className={styles.actions}><LinkButton to="/production/orders">预计订单</LinkButton><LinkButton to="/production/shipments">实际出货</LinkButton></div>} />}
    {!recordsOnly && (canWrite ? <section className={styles.panel} aria-labelledby="source-upload-heading"><h2 id="source-upload-heading">上传已适配原表</h2>
      <form className={styles.body} onSubmit={event => { event.preventDefault(); void upload(); }}>
        <fieldset disabled={busy} className={styles.sourceUploadFields}><legend className={styles.uploadLegend}>选择资料</legend><FormField label="原表类型"><select value={kind} onChange={event => { setKind(event.target.value as Kind); setResult(undefined); setUploadError(undefined); }}><option value="orders">下单表</option><option value="shipments">装箱单（假设已发）</option></select></FormField><FormField label="XLSX原表"><Input ref={fileInput} type="file" accept=".xlsx" onChange={event => { setFile(event.target.files?.[0]); setResult(undefined); setUploadError(undefined); }} /></FormField></fieldset>
        <p className={styles.reviewHint}>{kind === "orders" ? "支持已有9月下单表格式：业务页“9月底发货”，包含下单日期、品名、款号、颜色、SKU及订单数量。" : "支持已有双箱装箱单格式：Sheet1含SKU、ASIN、FNSKU、箱1、箱2及明确合计行；实际出货日期仍待核实。"} 文件须在2MB内；其他格式请先适配。标准模板继续从订单/出货的“标准表格导入”使用。</p>
        <div className={styles.actions}><Button type="submit" loading={busy} disabled={!file || busy}>上传并预览原表</Button><span className={styles.reviewHint}>仅保存独立副本；相同文件会返回已有来源。</span></div>
      </form>
      {uploadError && <StatusMessage kind="danger" title="上传预览未完成"><p>{uploadError}</p><p>输入已保留。连接失败时可查看下方来源列表，或用同一文件重新预览；不会再建第二份来源。</p></StatusMessage>}
      {result && <StatusMessage kind={result.item.available ? "success" : "warning"} title={result.duplicate ? "已找到相同来源" : "原表预览已准备好"}><p>{result.item.filename} · {result.item.row_count}行 · 原表{units(result.item.source_units || "0")}件。{result.duplicate ? "沿用已有来源与草稿。" : "尚未保存编辑草稿。"}</p>{result.item.available ? <Link to={sourceHref(result.item)}>{result.item.saved ? "继续核对这份草稿" : "打开明细并核对"}</Link> : <p>{result.item.error}</p>}</StatusMessage>}
    </section> : <StatusMessage kind="info" title="当前账号只读">可以查看已有来源；上传、编辑和保存需使用管理员或数据管理员账号。草稿与上传按账号独立保存。</StatusMessage>)}
    <section className={styles.panel} aria-labelledby="source-manager-heading"><div className={styles.sourceManagerHeading}><h2 id="source-manager-heading">已有来源与草稿</h2><Button variant="secondary" onClick={() => setRefresh(value => value + 1)}>刷新草稿列表</Button></div>
      <form key={params.toString()} className={styles.fields} onSubmit={event => {
        event.preventDefault(); const form = new FormData(event.currentTarget); const next = new URLSearchParams(params);
        for (const key of ["q", "kind", "saved"]) next.delete(key);
        for (const key of ["q", "kind", "saved"]) { const value = form.get(key); if (typeof value === "string" && value) next.set(key, value); } setParams(next);
      }}><FormField label="查找文件或业务单号"><Input name="q" defaultValue={params.get("q") || ""} /></FormField><FormField label="来源类型"><select disabled={!!initialKind} name="kind" defaultValue={initialKind ?? params.get("kind") ?? ""}><option value="">全部类型</option><option value="orders">下单表</option><option value="shipments">装箱单</option></select></FormField><FormField label="草稿保存状态"><select name="saved" defaultValue={params.get("saved") || ""}><option value="">全部状态</option><option value="yes">已保存草稿</option><option value="no">尚未保存</option></select></FormField><div className={styles.actions}><Button type="submit" variant="secondary">查找草稿</Button><Button variant="quiet" onClick={() => setParams(params.get("source") === "legacy" ? { source: "legacy" } : {})}>清空条件</Button></div></form>
      {!items ? <StatusMessage kind={readError ? "danger" : "info"} title={readError ? "列表读取未完成" : "正在读取草稿…"}>{readError}</StatusMessage> : <>
        <p className={styles.reviewHint} role="status">显示{visible?.length}份，共{scopedItems?.length}份来源 · 已保存{scopedItems?.filter(item => item.saved).length}份草稿。保存状态不代表业务已确认。</p>
        {!visible?.length && <StatusMessage kind="info" title="没有符合条件的来源">可清空条件，或上传一份已适配原表后开始核对。</StatusMessage>}
        <ul className={styles.sourceManagerList}>{visible?.map(item => <li key={`${item.kind}:${item.source_id}`}>
          <div className={styles.sourceManagerIdentity}><strong>{item.filename}</strong><p>{item.kind === "orders" ? "下单表" : "装箱单 · 假设已发"} · {item.origin === "SAMPLE" ? "已有授权副本" : "当前账号上传"}</p>{item.business_number && <p>业务单号：{item.business_number}</p>}</div>
          {item.available ? <><dl><div><dt>原表</dt><dd>{item.row_count}行 / {units(item.source_units || "0")}件</dd></div><div><dt>保存状态</dt><dd>{item.saved ? `草稿修订${item.revision} · ${units(item.draft_units || "0")}件` : "尚未保存"}</dd></div><div><dt>最近保存</dt><dd>{item.updated_at ? new Date(item.updated_at).toLocaleString("zh-CN") : "—"}</dd></div><div><dt>原表问题</dt><dd>{item.issue_count}项 · SKU待匹配</dd></div></dl><Link to={sourceHref(item)} aria-label={`${item.saved ? "继续核对" : "预览原表"}：${item.filename}`}>{item.saved ? "继续核对" : "预览原表"}</Link></> : <StatusMessage kind="warning" title="来源待恢复">{item.error}</StatusMessage>}
        </li>)}</ul>
      </>}
    </section>{leave.prompt}</>;
}
