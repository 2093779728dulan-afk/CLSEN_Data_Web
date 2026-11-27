import { Disclosure } from "../../design-system";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiRequestError, requestApi, writeApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { LinkButton, Button, Dialog, FormField, Input, PageHeader, Pagination, StatusBadge, StatusMessage, Table  } from "../../design-system";
import { useProductionLeave } from "../production/useProductionLeave";
import type { Document as ProductionDocument, DocumentPage } from "../production/types";
import { downloadManual, kindLabels, type Decision, type ManualBatch, type ManualCatalogItem, type ManualHistory, type ManualIssue, type ManualKind, type ManualOptions, type ManualResult, type ManualRow, type Profile } from "./manualTablesApi";
import { ManualComparison } from "./ManualComparison";
import type { HandoffPreview } from "./manualTablesApi";
import styles from "../production/Production.module.css";
import local from "./ManualTablePage.module.css";

const initialOptions: ManualOptions = { sheet: "", header_row: null, start_row: null, end_row: null, columns: {}, context: {}, zero_policy: "unknown", decisions: {} };
const stateNames: Record<string, string> = { NEEDS_MAPPING: "字段待对应", NEEDS_REVIEW: "有资料待核对", READY: "提取校验已通过", HANDOFF_PENDING: "移交结果待核实", HANDED_OFF: "已移交原业务流程" };
const fieldNames: Record<string, string> = { style: "款号", color: "颜色", size: "尺码", units: "数量", code: "原商品编码", date: "业务日期", planned_date: "预计出货日期", warehouse: "仓库", total: "原表合计", asin: "ASIN", fnsku: "FNSKU", XS: "XS尺码数量", S: "S尺码数量", M: "M尺码数量", L: "L尺码数量", XL: "XL尺码数量", XXL: "XXL尺码数量", "3XL": "3XL尺码数量", "箱1": "箱1数量", "箱2": "箱2数量" };
type Pending = { action: string; path: string; key: string; body?: unknown; file?: File };
type ManualListItem = Pick<ManualBatch, "id" | "kind" | "filename" | "revision" | "target"> & { state: string; total_units: string };
type IssueGroup = {
  key: string; code: string; title: string; message: string; suggestion: string; blocking: boolean;
  problems: ManualIssue[]; rows: ManualRow[]; sizes: string[]; cells: string[];
};
type FulfillmentMode = "WAREHOUSE_STOCK" | "PRODUCTION_DIRECT";

function readFulfillmentModes(value?: string): Record<string, FulfillmentMode> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    return Object.fromEntries(Object.entries(parsed).filter((entry): entry is [string, FulfillmentMode] => entry[1] === "WAREHOUSE_STOCK" || entry[1] === "PRODUCTION_DIRECT"));
  } catch { return {}; }
}

const groupedIssueCodes = new Set(["quantity_unknown", "sku_unresolved", "code_identity_conflict"]);

function issueGroups(result: ManualResult): IssueGroup[] {
  const grouped = new Map<string, IssueGroup>();
  for (const problem of result.issues) {
    const matchedRow = result.rows.find(row => row.source_ref.sheet === problem.source_ref.sheet && row.source_ref.cell === problem.source_ref.cell)
      ?? result.rows.find(row => row.source_ref.sheet === problem.source_ref.sheet && row.source_ref.row === problem.source_ref.row);
    const quantityUnresolved = matchedRow && (matchedRow.units === null || matchedRow.units === "") && result.issues.some(issue => issue.code === "quantity_unknown" && issue.source_ref.sheet === matchedRow.source_ref.sheet && issue.source_ref.cell === matchedRow.source_ref.cell);
    if (problem.code === "sku_unresolved" && quantityUnresolved) continue;
    const style = matchedRow?.style.trim() ?? ""; const color = matchedRow?.color.trim() ?? "";
    const sourceIdentity = groupedIssueCodes.has(problem.code) && (style || color)
      ? `${style}\u0000${color}`
      : `${problem.source_ref.sheet}\u0000${problem.source_ref.row}`;
    const key = `${problem.code}\u0000${sourceIdentity}\u0000${problem.message}\u0000${problem.suggestion}`;
    const existing = grouped.get(key);
    if (existing) {
      existing.problems.push(problem); existing.blocking ||= problem.blocking;
      if (matchedRow && !existing.rows.some(row => row.source_line_key === matchedRow.source_line_key)) existing.rows.push(matchedRow);
      if (matchedRow?.size && !existing.sizes.includes(matchedRow.size)) existing.sizes.push(matchedRow.size);
      if (problem.source_ref.cell && !existing.cells.includes(problem.source_ref.cell)) existing.cells.push(problem.source_ref.cell);
      continue;
    }
    grouped.set(key, {
      key, code: problem.code, message: problem.message, suggestion: problem.suggestion, blocking: problem.blocking,
      title: style || color ? `${style || "款号待核"} · ${color || "颜色待核"}` : `${problem.source_ref.sheet} · 第${problem.source_ref.row}行`,
      problems: [problem], rows: matchedRow ? [matchedRow] : [], sizes: matchedRow?.size ? [matchedRow.size] : [], cells: problem.source_ref.cell ? [problem.source_ref.cell] : [],
    });
  }
  return [...grouped.values()];
}

function issueGroupLabel(group: IssueGroup) {
  if (group.code === "quantity_unknown") return `${group.problems.length}个尺码数量为空`;
  if (group.code === "sku_unresolved") return `${group.problems.length}个规格待对应商品`;
  if (group.code === "code_identity_conflict") return `${group.problems.length}个规格的原编码与商品不一致`;
  return group.problems.length > 1 ? `${group.problems.length}处同类问题：${group.message}` : group.message;
}

function materialPath(item: ManualListItem) {
  return `/production/${item.kind === "inventory" ? "stock" : item.kind === "orders" ? "orders" : "shipments"}/materials/${item.id}`;
}

function businessActionLabel(item: ManualListItem) {
  if (!item.target?.url) return "继续核对";
  if (item.kind === "inventory") return "打开库存核对";
  return item.kind === "orders" ? "打开订单" : "打开出货单";
}

type ManualPageProps = { view?: "full" | "upload" | "records"; initialKind?: ManualKind; targetUrl?: string };
export function ManualTablePage({ view = "full", initialKind, targetUrl }: ManualPageProps = {}) {
  const { batch_id } = useParams(); const { generation } = useAuthzGeneration();
  return <ManualTableWorkspace key={`${batch_id || "upload"}:${generation}`} view={view} initialKind={initialKind} targetUrl={targetUrl} />;
}

function ManualTableWorkspace({ view = "full", initialKind, targetUrl }: ManualPageProps) {
  const { batch_id: id } = useParams(); const navigate = useNavigate();
  const { generation, registerSensitivePurge } = useAuthzGeneration(); const liveGeneration = useRef(generation); liveGeneration.current = generation;
  const [enabled, setEnabled] = useState<boolean>(); const [batch, setBatch] = useState<ManualBatch>();
  const [allHandoffEnabled, setHandoffEnabled] = useState(false);
  const [inventoryHandoffEnabled, setInventoryHandoffEnabled] = useState(false);
  const [handoffPreview, setHandoffPreview] = useState<HandoffPreview>();
  const [items, setItems] = useState<ManualListItem[]>([]);
  const [listingReady, setListingReady] = useState(false);
  const [listPage, setListPage] = useState(1); const [listTotal, setListTotal] = useState(0);
  const [options, setOptions] = useState<ManualOptions>(initialOptions); const [preview, setPreview] = useState<{ result: ManualResult; preview_hash: string }>();
  const [catalog, setCatalog] = useState<ManualCatalogItem[]>([]); const [profiles, setProfiles] = useState<Profile[]>([]); const [history, setHistory] = useState<ManualHistory[]>([]);
  const [kind, setKind] = useState<ManualKind>(initialKind ?? "inventory"); const [file, setFile] = useState<File>();
  const handoffEnabled = allHandoffEnabled && ((batch?.kind ?? kind) !== "inventory" || inventoryHandoffEnabled);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [success, setSuccess] = useState(""); const [unknown, setUnknown] = useState(false);
  const [query, setQuery] = useState(""); const [issuesOnly, setIssuesOnly] = useState(false); const [page, setPage] = useState(1);
  const [focusedRows, setFocusedRows] = useState<string[]>([]);
  const [setupOpen, setSetupOpen] = useState<boolean>();
  const [expandedRow, setExpandedRow] = useState<string>();
  const [picker, setPicker] = useState<ManualRow>(); const [productQuery, setProductQuery] = useState(""); const [profileName, setProfileName] = useState("");
  const [orderOptions, setOrderOptions] = useState<ProductionDocument[]>([]); const [order, setOrder] = useState<ProductionDocument>();
  const [scopes, setScopes] = useState<{ warehouse_id: string; owner_id: string; warehouse_name: string }[]>([]);
  const pending = useRef<Pending | undefined>(undefined);
  const dirty = Boolean(batch && JSON.stringify(options) !== JSON.stringify(batch.options));
  const leave = useProductionLeave(dirty, busy, unknown);
  const result = preview?.result ?? batch?.result; const locked = busy || unknown || Boolean(batch?.target);

  useEffect(() => () => { liveGeneration.current = -1; }, []);
  useEffect(() => registerSensitivePurge(() => { setBatch(undefined); setCatalog([]); setItems([]); setHistory([]); setOptions(initialOptions); setFile(undefined); setPicker(undefined); setOrder(undefined); setOrderOptions([]); setScopes([]); setProfiles([]); setPreview(undefined); setHandoffPreview(undefined); setError(""); setSuccess(""); setUnknown(false); setBusy(false); pending.current = undefined; }), [registerSensitivePurge]);
  useEffect(() => {
    let active = true; setListingReady(false); setError(""); setBatch(undefined); setPreview(undefined); setSuccess(""); setUnknown(false); pending.current = undefined;
    void (async () => {
      const capabilities = await requestApi<{ enabled: boolean; handoff_enabled?: boolean; inventory_handoff_enabled?: boolean }>("/api/manual-tables/capabilities");
      if (!active) return; setEnabled(capabilities.enabled); setHandoffEnabled(capabilities.handoff_enabled ?? true); setInventoryHandoffEnabled(capabilities.inventory_handoff_enabled ?? true); if (!capabilities.enabled) return;
      const [listing, products, savedProfiles] = await Promise.all([requestApi<{ items: typeof items; total: number }>(`/api/manual-tables/batches?page=${listPage}${view === "records" && initialKind ? `&kind=${initialKind}` : ""}${targetUrl ? `&target_url=${encodeURIComponent(targetUrl)}` : ""}`), requestApi<{ items: ManualCatalogItem[] }>("/api/manual-tables/catalog"), requestApi<{ items: Profile[] }>("/api/manual-tables/profiles")]);
      if (!active) return; setItems(listing.items); setListTotal(listing.total); setListingReady(true); setCatalog(products.items); setProfiles(savedProfiles.items);
      if (id) {
        const value = await requestApi<ManualBatch>(`/api/manual-tables/batches/${id}`); const log = await requestApi<{ items: ManualHistory[] }>(`/api/manual-tables/batches/${id}/history`);
        if (!active) return; setBatch(value); setOptions(value.options); setHistory(log.items);
        if (value.target?.state === "HANDOFF_PENDING" && value.target.command) { pending.current = { action: "handoff", path: `/api/manual-tables/batches/${value.id}/handoff`, key: value.target.token, body: value.target.command }; setUnknown(true); }
      }
    })().catch(reason => { if (active) { setListingReady(true); setError(reason instanceof Error ? reason.message : "资料读取未完成。"); } });
    return () => { active = false; };
    // Listing is loaded with the route; it is not a dependency of this request.
  }, [id, generation, listPage, initialKind, targetUrl, view]);

  function edit(patch: Partial<ManualOptions>) { setOptions(current => ({ ...current, ...patch })); setPreview(undefined); setHandoffPreview(undefined); setSuccess(""); }
  function context(key: string, value: string) { edit({ context: { ...options.context, [key]: value } }); }
  function decide(row: ManualRow, patch: Decision) { setOptions(current => ({ ...current, decisions: { ...current.decisions, [row.source_line_key]: { ...current.decisions[row.source_line_key], ...patch, reason: patch.reason ?? current.decisions[row.source_line_key]?.reason ?? "人工核对原表明细" } } })); setPreview(undefined); setHandoffPreview(undefined); setSuccess(""); }
  function accept(value: ManualBatch) { setBatch(value); setOptions(value.options); setPreview(undefined); setHandoffPreview(undefined); setSuccess("整理资料已保存，当前尚未入账。"); }

  async function perform(operation: Pending, replay = false) {
    const current = replay ? pending.current : operation; if (!current) return;
    pending.current = current; const currentGeneration = liveGeneration.current; setBusy(true); setError(""); let wrote = false;
    try {
      const value = await writeApi<ManualBatch & { target?: ManualBatch["target"] }>(current.path, { body: current.body, rawBody: current.file, operationKey: current.key, headers: current.file ? { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" } : undefined });
      if (currentGeneration !== liveGeneration.current) return;
      wrote = true; pending.current = undefined; setUnknown(false);
      if (current.action === "upload") { leave.allowLeave(); void navigate(`/production/${value.kind === "inventory" ? "stock" : value.kind === "orders" ? "orders" : "shipments"}/materials/${value.id}`); }
      else if (current.action === "save") { accept(value); const log = await requestApi<{ items: ManualHistory[] }>(`/api/manual-tables/batches/${value.id}/history`); if (currentGeneration === liveGeneration.current) setHistory(log.items); }
      else if (current.action === "handoff") { setBatch(b => b ? { ...b, target: value.target } : b); const saved = await requestApi<ManualBatch>(`/api/manual-tables/batches/${id}`); if (currentGeneration !== liveGeneration.current) return; accept(saved); setSuccess("已移交原流程，请打开目标继续核对。尚未自动确认或过账。"); if (saved.target?.url) { leave.allowLeave(); void navigate(saved.target.url); } }
      else { setSuccess("字段对应方案已保存。仅复用列位置，不会复用商品或业务数量。"); const saved = await requestApi<{ items: Profile[] }>("/api/manual-tables/profiles"); if (currentGeneration === liveGeneration.current) setProfiles(saved.items); }
    } catch (reason) {
      if (currentGeneration !== liveGeneration.current) return;
      if (wrote) { setUnknown(false); setError("操作已成功，后续资料读取未完成，请刷新查看结果。"); return; }
      if (reason instanceof ApiRequestError && reason.status < 500) { pending.current = undefined; setUnknown(false); if (current.action === "handoff" && reason.code === "manual_handoff_preview_stale") setHandoffPreview(undefined); } else setUnknown(true);
      setError(reason instanceof Error ? reason.message : "操作未完成，请先核实原操作结果。");
    } finally { if (currentGeneration === liveGeneration.current) setBusy(false); }
  }

  function command(action: "save" | "handoff") {
    if (!batch || (action === "handoff" && !handoffPreview)) return;
    const key = crypto.randomUUID(); const body = { expected_revision: batch.revision, operation_token: key, options, preview_hash: preview?.preview_hash ?? "", reason: "人工表格核对与整理", ...(action === "handoff" ? { target: batch.kind === "inventory" ? "inventory_review" : batch.kind === "orders" ? "order" : "shipment", handoff_preview_hash: handoffPreview!.handoff_preview_hash } : {}) };
    void perform({ action, path: `/api/manual-tables/batches/${batch.id}/${action}`, key, body });
  }
  async function previewBusiness() {
    if (!batch) return; const currentGeneration = liveGeneration.current; setBusy(true); setError(""); setHandoffPreview(undefined);
    try {
      const value = await writeApi<HandoffPreview>(`/api/manual-tables/batches/${batch.id}/handoff-preview`, { idempotent: false, body: { expected_revision: batch.revision, operation_token: crypto.randomUUID(), options, reason: "人工表格核对与整理", target: batch.kind === "inventory" ? "inventory_review" : batch.kind === "orders" ? "order" : "shipment" } });
      if (currentGeneration === liveGeneration.current) setHandoffPreview(value);
    } catch (reason) { if (currentGeneration === liveGeneration.current) setError(reason instanceof Error ? reason.message : "业务衔接预览未完成；尚未创建目标。"); }
    finally { if (currentGeneration === liveGeneration.current) setBusy(false); }
  }
  async function previewInput(nextOptions: ManualOptions = options) {
    if (!batch) return; const currentGeneration = liveGeneration.current; setBusy(true); setError(""); setHandoffPreview(undefined);
    try {
      const value = await writeApi<{ result: ManualResult; preview_hash: string }>(`/api/manual-tables/batches/${batch.id}/preview`, { body: { expected_revision: batch.revision, operation_token: crypto.randomUUID(), options: nextOptions } });
      if (currentGeneration === liveGeneration.current) { setPreview(value); setPage(1); }
    } catch (reason) { if (currentGeneration === liveGeneration.current) setError(reason instanceof Error ? reason.message : "预览未完成。"); }
    finally { if (currentGeneration === liveGeneration.current) setBusy(false); }
  }
  async function checkOperation() {
    if (!id || !pending.current) return; const currentGeneration = liveGeneration.current; setBusy(true);
    try { await requestApi(`/api/manual-tables/batches/${id}/operations/${pending.current.key}`); const saved = await requestApi<ManualBatch>(`/api/manual-tables/batches/${id}`); if (currentGeneration !== liveGeneration.current) return; accept(saved); pending.current = undefined; setUnknown(false); setError(""); }
    catch (reason) { if (currentGeneration === liveGeneration.current) setError(reason instanceof Error ? reason.message : "尚未查到原结果，可以重发原操作。"); }
    finally { if (currentGeneration === liveGeneration.current) setBusy(false); }
  }
  async function exportFile(mode: string) {
    if (!batch) return; const currentGeneration = liveGeneration.current; setBusy(true); setError("");
    try { await downloadManual(batch, mode, query, () => currentGeneration === liveGeneration.current); if (currentGeneration !== liveGeneration.current) return; setSuccess("已导出当前已保存修订；文件包含来源与数量口径说明。"); }
    catch (reason) { if (currentGeneration === liveGeneration.current) setError(reason instanceof Error ? reason.message : "导出失败，请重试。"); }
    finally { if (currentGeneration === liveGeneration.current) setBusy(false); }
  }
  async function loadOrders() {
    const currentGeneration = liveGeneration.current;
    try {
      const [orders, availability] = await Promise.all([requestApi<DocumentPage>("/api/production/orders"), requestApi<{ scopes: typeof scopes }>("/api/production/inventory/availability")]);
      if (currentGeneration !== liveGeneration.current) return; setOrderOptions(orders.items.filter(o => o.status === "CONFIRMED")); setScopes(availability.scopes);
    } catch (reason) { if (currentGeneration === liveGeneration.current) setError(reason instanceof Error ? reason.message : "业务前置读取失败。"); }
  }
  async function selectOrder(orderId: string) {
    if (!orderId) { setOrder(undefined); return; }
    const currentGeneration = liveGeneration.current;
    try { const value = await requestApi<ProductionDocument>(`/api/production/orders/${orderId}`); if (currentGeneration === liveGeneration.current) setOrder(value); }
    catch (reason) { if (currentGeneration === liveGeneration.current) setError(reason instanceof Error ? reason.message : "订单读取失败。"); }
  }

  const visible = (result?.rows ?? []).filter(row => {
    const decision = options.decisions[row.source_line_key];
    const needsMatch = !(decision?.excluded ?? row.excluded) && (decision?.units ?? row.units) !== "0" && !decision?.sku_id && row.match?.status !== "matched";
    return (!query || `${row.style} ${row.color} ${row.size} ${row.code}`.toLowerCase().includes(query.toLowerCase())) && (!issuesOnly || focusedRows.includes(row.source_line_key) || row.issues.length > 0 || needsMatch);
  });
  const columns = result?.samples[0] ?? [];
  const shipmentSkus = Array.from(new Map((result?.rows ?? []).filter(row => !row.excluded && row.units && row.units !== "0" && row.match?.sku_id).map(row => [row.match!.sku_id!, { sku_id: row.match!.sku_id!, label: `${row.style} · ${row.color} / ${row.size}` }])).values());
  const fulfillmentModes = readFulfillmentModes(options.context.fulfillment_modes);
  const historicalPacking = batch?.kind === "packing" && options.context.already_in_snapshot === "true";
  const fulfillmentComplete = shipmentSkus.length > 0 && shipmentSkus.every(item => Boolean(fulfillmentModes[item.sku_id]));
  const hasWarehouseFulfillment = shipmentSkus.some(item => fulfillmentModes[item.sku_id] === "WAREHOUSE_STOCK");
  const snapshotDirectConflict = historicalPacking && Object.values(fulfillmentModes).some(mode => mode === "PRODUCTION_DIRECT");
  const missingContext = batch && batch.kind !== "inventory" ? [!options.context.date && "业务日期", !options.context.source_note?.trim() && "来源说明", batch.kind === "packing" && !historicalPacking && !fulfillmentComplete && "每个出货SKU的货物来源", batch.kind === "packing" && !historicalPacking && options.context.dispatched !== "true" && "确认实际发出", batch.kind === "packing" && !historicalPacking && hasWarehouseFulfillment && !options.context.warehouse_id && "仓库库存出货所用仓库"].filter(Boolean).join("、") : "";
  const groupedIssues = useMemo(() => result ? issueGroups(result) : [], [result]);
  const displayedIssues = groupedIssues.reduce((total, group) => total + group.problems.length, 0);
  const blockingIssues = groupedIssues.reduce((total, group) => total + group.problems.filter(problem => problem.blocking).length, 0);
  const blockingGroups = groupedIssues.filter(group => group.blocking).length;
  const blankQuantityIssues = result?.issues.filter(problem => problem.code === "quantity_unknown" && /空白|斜杠|“\/”/.test(problem.message)).length ?? 0;
  function locateGroup(group: IssueGroup) {
    const row = group.rows[0] ?? result?.rows.find(item => item.source_ref.sheet === group.problems[0]?.source_ref.sheet && item.source_ref.row === group.problems[0]?.source_ref.row);
    if (!row) return;
    setQuery(`${row.style} ${row.color}`.trim()); setFocusedRows(group.rows.map(item => item.source_line_key)); setIssuesOnly(true); setPage(1); setExpandedRow(row.source_line_key);
    setTimeout(() => {
      const target = document.getElementById(`manual-row-${row.source_line_key}`);
      if (!(target instanceof HTMLElement)) return;
      target.scrollIntoView?.({ behavior: "smooth", block: "center" });
      target.focus();
    }, 0);
  }
  return <div className={local.page}>
    {view === "full" && <PageHeader eyebrow="业务录入 · 表格核对" title="人工表格整理" description="核对后继续对应业务。原件与修订保留，整理不会直接入账。" actions={<LinkButton to={batch || initialKind ? `/production/${(batch?.kind ?? initialKind) === "inventory" ? "stock" : (batch?.kind ?? initialKind) === "orders" ? "orders" : "shipments"}/materials` : "/production/imports/records"}>返回业务资料记录</LinkButton>} />}
    {error && <StatusMessage kind="danger" title={unknown ? "结果待核实，请保留原操作" : "暂未完成"}>{error}</StatusMessage>}
    {success && <StatusMessage kind="success" title="操作结果">{success}</StatusMessage>}
    {enabled && !handoffEnabled && <StatusMessage kind="info" title="当前仅开放资料整理">可以上传、核对、保存和导出资料；业务移交暂未开放，不会创建订单、出货或库存核对单。</StatusMessage>}
    {enabled === undefined ? <StatusMessage kind="info" title="正在核对资料权限…" /> : !enabled ? <StatusMessage kind="info" title="当前未启用人工表格整理">原有标准模板、原表和官方报表继续使用原入口。</StatusMessage> : !id ? <>
      {view !== "records" && <section className={styles.panel}><h2>上传人工表格</h2><p className={local.muted}>适用人工编制/人工改排的XLSX。平台官方经营报告和退货报告请继续使用原入口。</p>
        <div className={styles.fields}>{!initialKind && <FormField label="资料类型"><select aria-label="资料类型" value={kind} disabled={busy || unknown} onChange={event => setKind(event.target.value as ManualKind)}>{Object.entries(kindLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></FormField>}<FormField label="人工表格文件" required><Input aria-label="人工表格文件" type="file" accept=".xlsx" disabled={busy || unknown} onChange={event => setFile(event.target.files?.[0])} /></FormField></div>
        <div className={styles.actions}><Button loading={busy} disabled={!file || busy || unknown} onClick={() => { if (file) void perform({ action: "upload", key: crypto.randomUUID(), path: `/api/manual-tables/batches?kind=${kind}&filename=${encodeURIComponent(file.name)}`, file }); }}>上传并提取</Button><span className={local.muted}>文件不超过2MB，相同原件沿用已有批次。</span></div>
        <p>专用虚构样例：{(initialKind ? [initialKind] : ["inventory", "orders", "packing"] as const).map(sample => <a key={sample} className={local.sample} href={`/api/manual-tables/examples/${sample}`}>下载{kindLabels[sample]}表</a>)}</p>
      </section>}
      {view !== "upload" && (!listingReady ? <StatusMessage kind="info" title="正在读取资料记录…" /> : error ? null : <><Table className={local.recordTable} title="资料记录" description="保留原件与核对修订，按状态继续下一步。"><thead><tr><th>文件</th><th>类型</th><th>处理状态</th><th>提取数量</th><th>下一步</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td><span className={local.recordMobileLabel}>文件</span><span>{item.filename}</span></td><td><span className={local.recordMobileLabel}>类型</span><span>{kindLabels[item.kind]}</span></td><td><span className={local.recordMobileLabel}>处理状态</span><span>{item.target ? stateNames[item.target.state] : stateNames[item.state]} · 修订{item.revision}</span></td><td><span className={local.recordMobileLabel}>提取数量</span><span>{item.total_units}件</span></td><td><span className={local.recordMobileLabel}>下一步</span><div className={styles.actions}>{!targetUrl && <Link aria-label={`${businessActionLabel(item)}：${item.filename}`} to={item.target?.url || materialPath(item)}>{businessActionLabel(item)}</Link>}{item.target?.url && <Link aria-label={`查看整理资料：${item.filename}`} to={materialPath(item)}>查看整理资料</Link>}</div></td></tr>)}</tbody></Table><Pagination page={listPage} totalItems={listTotal} totalPages={Math.ceil(listTotal / 30)} onPageChange={setListPage} />{!items.length && <StatusMessage kind="info" title={targetUrl ? "此单据没有人工整理来源" : "还没有人工资料"}>{targetUrl ? "手工填写或标准模板来源请查看上方单据资料来源；这里仅显示与本单据关联的人工原表。" : "可以先下载虚构样例，上传后体验字段对应、问题定位和导出。"}</StatusMessage>}</>)}
    </> : !batch || !result ? <StatusMessage kind="info" title="正在读取原件与已保存决定…" /> : <>
      <ol className={styles.workflowSteps} aria-label="资料处理步骤"><li aria-current={batch.target ? undefined : "step"}>1 核对并保存资料</li><li aria-current={batch.target ? "step" : undefined}>{batch.target?.url ? <Link to={batch.target.url}>2 继续业务核对</Link> : "2 继续业务核对"}</li><li>3 确认业务结果</li></ol>
      <section className={styles.panel}><div className={local.heading}><div><h2>{batch.filename}</h2><p>{kindLabels[batch.kind]} · 修订{batch.revision} · {stateNames[batch.target?.state ?? result.state]}</p></div><div className={local.count}><strong>{result.total_units}</strong><span>件已识别数量</span></div></div><p className={local.muted}>当前有{result.rows.length}条规格明细、{blockingGroups}组待核（涉及{blockingIssues}个规格或单元格）、{result.excluded_rows.length}个说明/空白行。未知数量不计入合计；{batch.target?.url ? "本页保留整理资料，业务结果请查看关联单据。" : "资料仍未过账。"}</p><a href={`/api/manual-tables/batches/${batch.id}/source`}>下载原件</a></section>
      <Disclosure className={`${styles.panel} ${local.setup}`} id="manual-context" open={setupOpen ?? (result.state === "NEEDS_MAPPING" || Boolean(missingContext))} onToggle={event => setSetupOpen(event.currentTarget.open)}><summary className={local.sectionSummary}><h2>1. 字段与业务口径</h2><span>工作表、列对应与整批信息</span></summary><fieldset disabled={locked} className={local.fieldset}><div className={styles.fields}>
        <FormField label="业务工作表"><select aria-label="业务工作表" value={options.sheet || result.sheet || ""} onChange={event => edit({ sheet: event.target.value, profile_id: null, columns: {} })}><option value="">请选择</option>{result.sheets.map(sheet => <option key={sheet.name}>{sheet.name}</option>)}</select></FormField>
        <FormField label="表头行"><Input aria-label="表头行" type="number" min={1} max={20} value={options.header_row ?? result.header_row ?? ""} onChange={event => edit({ header_row: Number(event.target.value) || null })} /></FormField>
        <FormField label="开始行（选填）"><Input type="number" value={options.start_row ?? ""} onChange={event => edit({ start_row: Number(event.target.value) || null })} /></FormField><FormField label="结束行（选填）"><Input type="number" value={options.end_row ?? ""} onChange={event => edit({ end_row: Number(event.target.value) || null })} /></FormField>
        <FormField label="空白及斜杠数量"><select aria-label="空白及斜杠数量" value={options.zero_policy} onChange={event => edit({ zero_policy: event.target.value as ManualOptions["zero_policy"] })}><option value="unknown">保留待核，不自动补0</option><option value="blank_slash_zero">本来源已明确：空白和斜杠为0</option></select></FormField>
        <FormField label={batch.kind === "inventory" ? "库存日期（可先待核）" : batch.kind === "orders" ? "下单日期" : "实际出货日期"}><Input aria-label="业务日期" type="date" value={options.context.date || ""} onChange={event => context("date", event.target.value)} /></FormField>
        <FormField label="来源说明（业务草稿必填）"><Input value={options.context.source_note || ""} onChange={event => context("source_note", event.target.value)} /></FormField><FormField label="来源单号（选填）"><Input value={options.context.number || ""} onChange={event => context("number", event.target.value)} /></FormField>
        <FormField label="仓库名称（按批补充）"><Input value={options.context.warehouse || ""} onChange={event => context("warehouse", event.target.value)} /></FormField>
        {batch.kind === "inventory" && <FormField label="结存口径"><select value={options.context.basis || ""} onChange={event => context("basis", event.target.value)}><option value="">待确认</option><option value="出货后结存">已包含本次出货的结存</option><option value="出货前结存">本次出货前结存</option></select></FormField>}
        <FormField label="复用字段方案"><select value={options.profile_id ? `${options.profile_id}:${options.profile_version}` : ""} onChange={event => { const p = profiles.find(v => `${v.id}:${v.version}` === event.target.value); if (p) edit({ ...p.options_json, profile_id: p.id, profile_version: p.version }); }}><option value="">本次确认</option>{profiles.filter(p => p.kind === batch.kind).map(p => <option key={`${p.id}:${p.version}`} value={`${p.id}:${p.version}`}>{p.name} · v{p.version}</option>)}</select></FormField>
      </div><label><input type="checkbox" checked={options.aggregate_duplicates ?? false} onChange={event => edit({ aggregate_duplicates: event.target.checked })} />已确认同规格来自独立行，移交时汇总（原行保留）</label>{options.aggregate_duplicates && <FormField label="重复规格汇总依据" required><Input value={options.aggregation_reason || ""} onChange={event => edit({ aggregation_reason: event.target.value })} /></FormField>}<Disclosure open={result.state === "NEEDS_MAPPING"}><summary>调整列对应／查看原表样例</summary><p>无表头的列请选择实际含义。这里的SKU只是原编码，不会覆盖商品主档。</p><div className={styles.fields}>{Object.entries({ ...fieldNames, ...Object.fromEntries(Object.keys({ ...result.columns, ...options.columns }).filter(k => k.startsWith("箱")).map(k => [k, `${k}数量`])) }).map(([field, label]) => <FormField key={field} label={label}><select aria-label={`${label}对应列`} value={options.columns[field] ?? result.columns[field] ?? 0} onChange={event => { const next = { ...options.columns }; next[field] = Number(event.target.value); edit({ columns: next, profile_id: null }); }}><option value="0">忽略此字段</option>{columns.map(c => <option key={c.column} value={c.column}>{c.cell.replace(/\d/g, "")}列 · {c.value || "无表头"}</option>)}</select></FormField>)}</div>{batch.kind === "packing" && <Button variant="quiet" onClick={() => { const number = Math.max(2, ...Object.keys({ ...result.columns, ...options.columns }).filter(k => k.startsWith("箱")).map(k => Number(k.slice(1)) || 0)) + 1; if (number <= 80) edit({ columns: { ...options.columns, [`箱${number}`]: 0 } }); }}>添加箱内数量列</Button>}<Table title="原表样例"><tbody>{result.samples.map((row, index) => <tr key={index}>{row.map(cell => <td key={cell.cell}><small>{cell.cell}</small><div>{cell.value || "—"}</div></td>)}</tr>)}</tbody></Table></Disclosure></fieldset>
        <div className={styles.actions}><Button disabled={locked} loading={busy} onClick={() => void previewInput()}>重新提取并预览</Button><Button disabled={locked || !preview} onClick={() => command("save")}>保存本次整理</Button>{dirty && <span className={local.muted}>输入尚未保存，请先预览再保存。</span>}</div>
      </Disclosure>
      <div className={local.workbenchGrid}>
      <section className={`${styles.panel} ${local.issuePanel} ${local.issueRail}`} aria-labelledby="manual-issues-title">
        <div className={local.issueHeading}><div><h2 id="manual-issues-title">2. 待核问题</h2><p>相同款色与原因已合并；数量未明确的空白格暂不重复提示商品对应。</p></div>{groupedIssues.length > 0 && <span>{groupedIssues.length}组 · {displayedIssues}处</span>}</div>
        {blankQuantityIssues > 0 && options.zero_policy === "unknown" && !locked && <div className={local.zeroSuggestion}><div><strong>{blankQuantityIssues}个空白尺码可以一次处理</strong><p>仅当这份表的空白和“/”都表示没有数量时使用；原表不会被修改。</p></div><Button variant="secondary" loading={busy} onClick={() => { const next = { ...options, zero_policy: "blank_slash_zero" as const }; setOptions(next); setPreview(undefined); setSuccess(""); void previewInput(next); }}>空白和斜杠按0重新预览</Button></div>}
        {groupedIssues.length ? <ul className={local.issueGroups}>{groupedIssues.map(group => <li key={group.key} className={group.blocking ? local.blockingIssue : undefined}>
          <div className={local.issueGroupHeader}><div><span>{group.title}</span><strong>{issueGroupLabel(group)}</strong></div><span>{group.problems.length}处</span></div>
          <p>{group.suggestion}</p>
          {(group.sizes.length > 0 || group.cells.length > 0) && <div className={local.issueMeta}>{group.sizes.length > 0 && <span>尺码：{group.sizes.join("、")}</span>}{group.cells.length > 0 && <span>原表：{group.cells.join("、")}</span>}</div>}
          <div className={local.issueActions}>
            {group.code === "hidden_row" && <Button variant="secondary" disabled={locked} onClick={() => { for (const problem of group.problems) for (const row of result.rows.filter(item => item.source_ref.row === problem.source_ref.row)) decide(row, { include_hidden: true, reason: "已核实隐藏行属于本次业务范围" }); }}>确认包含隐藏行</Button>}
            {group.code === "total_mismatch" && <Button variant="secondary" disabled={locked} onClick={() => { for (const problem of group.problems) { const row = result.rows.find(item => item.source_ref.row === problem.source_ref.row); if (row) decide(row, { accept_total: true, reason: "已核实原合计错误，采用明细重算" }); } }}>采用明细重算</Button>}
            {group.rows.length > 0 && <Button variant="quiet" onClick={() => locateGroup(group)}>查看这组明细</Button>}
          </div>
        </li>)}</ul> : <p>当前提取和商品对应没有待核问题；业务日期及入账前置在原流程继续检查。</p>}
      </section>
      <section className={local.reviewSection} aria-labelledby="manual-details-title">
        <header className={local.reviewHeading}>
          <div><h2 id="manual-details-title">3. 标准明细与商品对应</h2><p>先核对数量与商品；需要修改时展开本行，原件和修改原因均保留。</p><p>可确定的格式差异自动整理，原值在每行对照显示；不自动修改编码、数量或合并相似颜色。新规则需重新提取预览后保存。</p></div>
          <span className={local.resultCount}>共 {result.rows.length} 条规格</span>
        </header>
        <div className={local.reviewToolbar}>
          <FormField label="查找款号、颜色、尺码" className={local.searchField}><Input placeholder="搜索款号、颜色、尺码或原编码" value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} /></FormField>
          <label className={local.issueFilter}><input type="checkbox" checked={issuesOnly} onChange={event => { setIssuesOnly(event.target.checked); setPage(1); }} />只看待核明细</label>
          <span className={local.resultCount}>当前 {visible.length} 条</span>
        </div>
        <Table className={local.detailTable} aria-label="标准明细与商品对应">
          <thead><tr><th>商品规格</th><th>原表信息</th><th>核对数量</th><th>商品对应</th><th>操作</th></tr></thead>
          <tbody>{visible.slice((page - 1) * 12, page * 12).map(row => {
            const decision = options.decisions[row.source_line_key];
            const excluded = decision?.excluded ?? row.excluded;
            const selectedSku = catalog.find(item => item.sku_id === (decision?.sku_id ?? row.match?.sku_id));
            const units = decision?.units ?? row.units;
            const rawQuantity = typeof row.raw.quantity === "string" || typeof row.raw.quantity === "number" ? String(row.raw.quantity) : "";
            const changed = JSON.stringify(decision) !== JSON.stringify(batch.options.decisions[row.source_line_key]);
            const expanded = expandedRow === row.source_line_key;
            const matched = Boolean(decision?.sku_id || row.match?.status === "matched");
            return <Fragment key={row.source_line_key}>
              <tr id={`manual-row-${row.source_line_key}`} tabIndex={-1} className={excluded ? local.excludedRow : undefined} data-expanded={expanded || undefined}>
                <td className={local.productCell}><strong>{decision?.style || row.style || "款号待核"}</strong><span>{decision?.color || row.color || "颜色待核"}<span className={local.size}>{decision?.size || row.size || "尺码待核"}</span></span></td>
                <td className={local.sourceCell}><span>{row.code || "未提供原编码"}</span><small>{row.source_ref.sheet}!{row.source_ref.cell} · 原数量 {rawQuantity || "空白"}</small>{row.format_adjustments?.map(change => <small key={change.field} title={change.reason}>格式整理 · {({ style: "款号", color: "颜色", size: "尺码" } as Record<string, string>)[change.field] ?? change.field}：<code>{JSON.stringify(change.before)}</code> → <code>{JSON.stringify(change.after)}</code></small>)}</td>
                <td className={local.quantityCell}><span className={local.mobileLabel}>核对数量</span><strong>{changed && !preview && decision?.boxes ? "待预览" : units || "待核"}</strong>{changed && <small>已改 · {preview ? "已预览" : "待预览"}</small>}</td>
                <td className={local.matchCell}><StatusBadge tone={excluded ? "quiet" : matched ? "good" : units === "0" ? "quiet" : "warn"} label={excluded ? "已排除" : matched ? "已对应" : units === "0" ? "0件 · 无需对应" : "待对应商品"} />{selectedSku && <small>{selectedSku.code || "正式SKU待补"}</small>}</td>
                <td className={local.rowAction}><Button variant="quiet" aria-expanded={expanded} aria-controls={`manual-editor-${row.source_line_key}`} aria-label={`${expanded ? "收起" : "核对"}第${row.source_ref.row}行${row.size}`} onClick={() => setExpandedRow(expanded ? undefined : row.source_line_key)}>{expanded ? "收起" : locked ? "查看明细" : "核对本行"}</Button></td>
              </tr>
              {expanded && <tr className={local.editorRow} id={`manual-editor-${row.source_line_key}`}><td colSpan={5}>
                <div className={local.rowEditor}>
                  <div className={local.editorHeading}><strong>核对 {row.style} · {row.color} / {row.size}</strong><span>原表 {row.source_ref.sheet}!{row.source_ref.cell}</span></div>
                  <fieldset disabled={locked} className={local.fieldset}>
                    <div className={local.editorFields}>
                      {Object.keys(row.boxes).length ? <div className={local.boxFields}>{Object.entries(row.boxes).map(([box, amount]) => <FormField key={box} label={box}><Input aria-label={`第${row.source_ref.row}行${row.size}${box}数量`} inputMode="numeric" value={decision?.boxes?.[box] ?? amount ?? ""} onChange={event => decide(row, { boxes: { ...Object.fromEntries(Object.entries(row.boxes).map(([k, v]) => [k, v ?? ""])), ...decision?.boxes, [box]: event.target.value } })} /></FormField>)}</div> : <FormField label="核对数量" className={local.quantityField}><Input aria-label={`第${row.source_ref.row}行${row.size}核对数量`} inputMode="numeric" value={units ?? ""} onChange={event => decide(row, { units: event.target.value })} /></FormField>}
                      <FormField label="修改或排除原因" className={local.reasonField}><Input aria-label={`第${row.source_ref.row}行${row.size}修改原因`} placeholder="请说明数量调整、商品对应或排除的依据" value={decision?.reason ?? ""} onChange={event => decide(row, { reason: event.target.value })} /></FormField>
                    </div>
                    <div className={local.editorActions}><Button variant="secondary" onClick={() => { setPicker(row); setProductQuery(row.style); }}>{matched ? "更换对应商品" : "选择商品"}</Button><Button variant="quiet" onClick={() => decide(row, { excluded: !excluded })}>{excluded ? "恢复明细" : "排除本行"}</Button><span>{excluded ? "本行不计入整理结果，可随时恢复。" : "修改后请重新预览，再保存本次整理。"}</span></div>
                  </fieldset>
                  {locked && <p className={local.muted}>{batch.target ? "已移交的资料仅供查看，请到原业务流程继续处理。" : "操作处理中，暂不可修改。"}</p>}
                  {row.issues.length > 0 && <ul className={local.rowIssues}>{row.issues.map((issue, index) => <li key={index}>{issue.message} · {issue.suggestion}</li>)}</ul>}
                </div>
              </td></tr>}
            </Fragment>;
          })}</tbody>
        </Table>
        {!visible.length && <p className={local.emptyRows}>{query || issuesOnly ? "没有符合条件的明细，请调整搜索或关闭待核筛选。" : "尚未提取到规格明细，请检查字段与业务口径。"}</p>}
        <Pagination page={page} totalItems={visible.length} totalPages={Math.ceil(visible.length / 12)} onPageChange={setPage} />
      </section>
      </div>
      <div className={local.reviewFooter}><p>{dirty ? preview ? "预览已更新，请保存本次整理。" : "有修改尚未预览，请先预览再保存。" : "当前显示已保存修订；整理不会直接入账。"}</p><div className={styles.actions}><Button disabled={locked} loading={busy} onClick={() => void previewInput()}>预览核对结果</Button><Button variant="primary" disabled={locked || !preview} onClick={() => command("save")}>保存整理结果</Button></div></div>
      <section className={styles.panel}><h2>4. 下一步：{batch.kind === "inventory" ? "库存资料核对" : batch.kind === "orders" ? "核对预计订单" : "核对实际出货"}</h2><p>{batch.kind === "inventory" ? "创建核对单后继续核对盘点资料；不会自动覆盖库存账。" : batch.kind === "orders" ? "生成订单草稿后，再确认实际需求；预计订单不改变仓内库存。" : "生成出货草稿后，再确认实发数量；已包含在结存中的历史出货只关联资料，不重复扣库存。"}</p><Disclosure className={styles.workflowTools}><summary>导出资料及保存字段方案</summary><div className={styles.actions}>{([["standard", "导出标准明细"], ["wide", "导出业务宽表"], ["issues", "导出问题清单"], ["template", "下载标准模板"]] as const).map(([mode, label]) => <Button key={mode} variant="secondary" disabled={busy || dirty || unknown} onClick={() => void exportFile(mode)}>{label}</Button>)}</div><p className={local.muted}>导出当前已保存修订，查找条件作用于全部分页。标准明细和业务宽表可由本入口再次核对；问题清单用于定位修正。</p>
        <div className={styles.actions}><FormField label="字段方案名称"><Input disabled={locked || dirty} value={profileName} onChange={event => setProfileName(event.target.value)} /></FormField><Button variant="quiet" disabled={locked || dirty || !profileName} onClick={() => void perform({ action: "profile", path: "/api/manual-tables/profiles", key: crypto.randomUUID(), body: { batch_id: batch.id, name: profileName } })}>保存列对应方案</Button></div>
        </Disclosure>
        {handoffEnabled && batch.kind === "packing" && <Disclosure onToggle={event => { if (event.currentTarget.open) void loadOrders(); }}><summary>实际出货前置与订单归属</summary><fieldset disabled={locked} className={local.fieldset}>
          <label><input type="checkbox" checked={options.context.dispatched === "true"} onChange={event => context("dispatched", String(event.target.checked))} />已确认实际发出</label>
          <label><input type="checkbox" checked={historicalPacking} onChange={event => context("already_in_snapshot", String(event.target.checked))} />这次出货已包含在库存结存中（仅资料核对，不能重复扣减）</label>
          {!historicalPacking && <section className={styles.panel}><div className={styles.actions}><div><strong>逐SKU选择货物来源</strong><p className={local.muted}>通常先将未选择项设为仓库库存出货，再把2305这类生产完成后直接发出的SKU改为“生产直发”。</p></div><Button variant="secondary" onClick={() => { const next = { ...fulfillmentModes }; shipmentSkus.forEach(item => { next[item.sku_id] ??= "WAREHOUSE_STOCK"; }); context("fulfillment_modes", JSON.stringify(next)); }}>未选择项全部设为仓库库存出货</Button></div>
            <div className={styles.fields}>{shipmentSkus.map((item, index) => <FormField key={item.sku_id} label={`${item.label} · 货物来源`}><select aria-label={`出货来源 ${index + 1} ${item.label}`} value={fulfillmentModes[item.sku_id] || ""} onChange={event => { const next = { ...fulfillmentModes }; if (event.target.value) next[item.sku_id] = event.target.value as FulfillmentMode; else delete next[item.sku_id]; context("fulfillment_modes", JSON.stringify(next)); }}><option value="">请选择</option><option value="WAREHOUSE_STOCK">仓库库存出货（扣库存）</option><option value="PRODUCTION_DIRECT">生产完成后直接出货（不进库存）</option></select></FormField>)}</div>
          </section>}
          <div className={styles.fields}>{historicalPacking && <FormField label="已包含本次出货的库存资料"><select aria-label="已包含出货的库存资料" value={options.context.inventory_batch_id || ""} onChange={event => { const item = items.find(v => v.id === event.target.value); if (item) edit({ context: { ...options.context, inventory_batch_id: item.id, inventory_batch_revision: String(item.revision) } }); }}><option value="">请选择并核对同仓库、日期与结存口径</option>{items.filter(v => v.kind === "inventory").map(v => <option key={v.id} value={v.id}>{v.filename} · 修订{v.revision}</option>)}</select></FormField>}{!historicalPacking && hasWarehouseFulfillment && <FormField label="仓库库存出货所用仓库"><select value={options.context.warehouse_id || ""} onChange={event => { const scope = scopes.find(v => v.warehouse_id === event.target.value); if (scope) edit({ context: { ...options.context, warehouse_id: scope.warehouse_id, owner_id: scope.owner_id, warehouse: scope.warehouse_name } }); }}><option value="">请选择</option>{scopes.map(s => <option key={`${s.warehouse_id}:${s.owner_id}`} value={s.warehouse_id}>{s.warehouse_name}</option>)}</select></FormField>}<FormField label="对应已确认订单"><select value={order?.id || ""} onChange={event => void selectOrder(event.target.value)}><option value="">请选择</option>{orderOptions.map(item => <option key={item.id} value={item.id}>{item.system_number} {item.business_number}</option>)}</select></FormField></div>
          {snapshotDirectConflict && <StatusMessage kind="warning" title="生产直发不能只关联库存结存">请取消“已包含在库存结存中”，转为实际出货草稿；生产直发仍要计入订单实际已发，但不会扣仓库库存。</StatusMessage>}
          {order && <Button variant="secondary" onClick={() => { const allocations: Record<string, { order_line_id: string; units: string }[]> = {}; for (const row of result.rows.filter(r => !r.excluded && r.units && r.units !== "0")) { const line = order.lines?.find(v => v.sku_id === row.match?.sku_id); if (line && row.match?.sku_id) allocations[row.match.sku_id] = [{ order_line_id: line.id, units: row.units! }]; } context("order_lines", JSON.stringify(allocations)); }}>将本批对应规格分配到所选订单</Button>}
        </fieldset></Disclosure>}
        {handoffEnabled && !batch.target && missingContext && <StatusMessage kind="warning" title={`还需补充：${missingContext}`}><a href="#manual-context">到上方“字段与业务口径”补充</a>，预览并保存后再继续。未填写的日期不会自动猜测。</StatusMessage>}
        {!batch.target && handoffEnabled && <>
          <Button variant="secondary" disabled={locked || dirty || Boolean(missingContext) || snapshotDirectConflict || result.state === "NEEDS_MAPPING" || (batch.kind !== "inventory" && result.state !== "READY")} onClick={() => void previewBusiness()}>预览业务衔接</Button>
          {!dirty && handoffPreview && <StatusMessage kind={handoffPreview.candidates.length ? "warning" : "info"} title="业务衔接预览（尚未创建目标）">
            <p>保存修订{handoffPreview.source_revision} · {handoffPreview.source_row_count}条明细 · {handoffPreview.sku_count}个规格 · {handoffPreview.total_units}件；已排除{handoffPreview.excluded_row_count}条。</p>
            <p>目标：{{ inventory_review: "库存资料核对", order: "预计订单草稿", shipment: "实际出货草稿", historical_reference: "历史资料关联" }[handoffPreview.target_kind]}{handoffPreview.business_date ? ` · 业务日期${handoffPreview.business_date}` : ""}。本次只生成草稿或资料关联，库存不变；实际确认仍走原业务流程。</p>
            {handoffPreview.candidates.length > 0 && <><p>发现相似已确认单据，请先打开核对。相同日期和数量不自动视为重复；确属另一笔业务时，请核实来源说明后再继续。</p><ul>{handoffPreview.candidates.map(item => <li key={item.id}><Link to={item.url}>查看相似单据 {item.business_number || item.system_number || item.id}</Link></li>)}</ul></>}
          </StatusMessage>}
        </>}
        {batch.target?.url ? <StatusMessage kind="success" title="整理完成，继续业务核对"><Link to={batch.target.url}>打开目标继续处理</Link>。整理批次不会再次创建目标。</StatusMessage> : handoffEnabled && <Button disabled={locked || dirty || !handoffPreview || Boolean(missingContext) || snapshotDirectConflict || result.state === "NEEDS_MAPPING" || (batch.kind !== "inventory" && result.state !== "READY")} onClick={() => command("handoff")}>{batch.kind === "inventory" ? "创建库存资料核对" : batch.kind === "orders" ? "转为预计订单草稿" : options.context.already_in_snapshot === "true" ? "关联已覆盖的库存资料（不扣库存）" : "转为实际出货草稿"}</Button>}
        <p>移交只创建允许的核对或草稿；实际库存变化、订单确认和出货确认继续使用原流程及权限。</p>

      </section>
      <ManualComparison key={generation} />
      <Table title="操作历史" description="按本站权限记录上传、保存、导出及移交，原数量和修改原因可追溯。"><thead><tr><th>时间</th><th>操作</th><th>操作人</th><th>修订／原因</th></tr></thead><tbody>{history.map(item => <tr key={item.token}><td>{new Date(item.at + (item.at.endsWith("Z") ? "" : "Z")).toLocaleString("zh-CN")}</td><td>{{ UPLOAD: "上传人工原表", SAVE: "保存整理", EXPORT: "导出资料", REIMPORT: "导出资料回导", PROFILE: "保存字段方案", HANDOFF: "移交原流程" }[item.action] || item.action}</td><td>{item.actor_name || `用户 #${item.actor_id}`}</td><td>{item.revision ?? "—"} · {item.reason}{item.changes?.map((change, index) => <p key={index}>{change}</p>)}</td></tr>)}</tbody></Table>
    </>}
    {unknown && <div className={styles.actions}>{id && <Button disabled={busy} onClick={() => void checkOperation()}>核实原操作结果</Button>}<Button disabled={busy} onClick={() => { if (pending.current) void perform(pending.current, true); }}>重发原操作</Button></div>}
    <Dialog open={Boolean(picker)} onOpenChange={open => { if (!open) setPicker(undefined); }} title="选择当前主档商品" description="只保存本行对应与修改依据，不发布颜色别名或创建商品。"><FormField label="搜索款号、颜色、尺码"><Input value={productQuery} onChange={event => setProductQuery(event.target.value)} /></FormField><ul className={local.products}>{catalog.filter(item => item.active && `${item.style} ${item.color} ${item.size} ${item.code || ""}`.toLowerCase().includes(productQuery.toLowerCase())).slice(0, 50).map(item => <li key={item.sku_id}><Button variant="quiet" onClick={() => { if (picker) decide(picker, { sku_id: item.sku_id, style: item.style, color: item.color, size: item.size, reason: options.decisions[picker.source_line_key]?.reason || "人工从当前主档选择对应商品" }); setPicker(undefined); }}>{item.style} · {item.color} / {item.size} · {item.code || "正式SKU待补"}</Button></li>)}</ul><Link to="/catalog/production-sources">找不到商品，进入商品建档</Link></Dialog>
    {leave.prompt}
  </div>;
}
