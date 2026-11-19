import { useBusinessToday } from "./workbenchDate";
import { CountTable, CountTableImport } from "./CountTable";
import { TableImportReview } from "./TableImportReview";
import { useTableBaseline } from "./useTableBaseline";
import { stockImportRows, withoutTableBaseline } from "./tableImportDiff";
import { useEffect, useRef, useState, type ComponentProps } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiRequestError, requestApi, StableOperationKeyStore, writeApi } from "../../api/client";
import { RequestGate } from "../../api/requestGate";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, Dialog, FormField, Input, LinkButton, Menu, PageHeader, Pagination, StatusMessage, Table } from "../../design-system";
import { useProductionLeave } from "./useProductionLeave";
import { type Allocation, type Document, type DocumentPage, type ProductionReceiptSource, type Sku, units } from "./types";
import styles from "./Production.module.css";
import recordStyles from "./StockRecords.module.css";
import { ChevronDown } from "lucide-react";
import { MovementSkuSelect, QualityMovementFields, StockImpact, type StockImpacts } from "./StockMovementFields";
import { WarehouseOpening } from "./WarehouseOpening";
import { WarehouseRecordStatus, WarehouseRecordSteps } from "./WarehouseRecordStatus";
import warehouseStyles from "./WarehouseCenter.module.css";
import { QualityMovementWizard, type QualityPreview } from "./QualityMovementWizard";
import { StockOperationWizard } from "./StockOperationWizard";
import { InventoryOverviewSheet } from "./inventory-sheet/InventoryOverviewSheet";
import { SkuAcrossWarehouses } from "./SkuAcrossWarehouses";
import { overviewSearchParams, type OverviewSource, type OverviewAction, type OverviewGuard } from "./stockOverview";

type RecordValue = Record<string, unknown>;
export type Balance = { catalog_version?: string; warehouse_id: string; owner_id: string; sku_id: string; sku_label?: string; style_code?: string; display_sku?: string | null; standard_color?: string; standard_size?: string; identity_status?: "mapped" | "pending"; state: "ready" | "not_ready" | "shortage"; on_hand_units: string | null; free_available_units: string | null; dispatch_allowed_units: string | null; unassessed_units?: string; missing?: string; qualified_units?: string; pending_units?: string; defective_units?: string; held_units?: string; reserved_units?: string; loan_outstanding_units?: string; revision?: string; cutoff_on?: string; source_reference?: string; projected_on_hand_units?: string; plans?: RecordValue[]; opening_metadata?: { review_id?: string; review_revision?: string; owner_state?: string; quantity_basis?: string } };
type MovementLine = { sku_id: string; units: string; quality: string; purpose: string; counterparty?: string; target_quality?: string; location_from?: string; location_to?: string; borrower?: string; borrow_purpose?: string; due_on?: string; loan_id?: string; plan_id?: string; counted_on?: string; evidence?: string; production_allocations?: Allocation[] };
type Movement = { id: string; kind: string; warehouse_id: string; owner_id: string; status: string; revision: string; business_date: string; reason: string; lines: MovementLine[]; loan_ids?: string[]; production_sources?: ProductionReceiptSource[] };
type Items<T> = { items: T[] };
type StockPolicy = { writes_enabled?: boolean; opening_enabled?: boolean; production_receipts_supported?: boolean; items: Balance[] };
const kinds: Record<string, string> = { IN: "入库", OUT: "出库", MOVE: "内部变更", ADJUST: "盘点调整" };
const qualities: Record<string, string> = { QUALIFIED: "合格", PENDING: "待检", DEFECTIVE: "次品" };
const qualityNames: Record<string, string> = { ...qualities, UNASSESSED: "质量未核" };
const purposes: Record<string, string> = { OPENING: "登记期初", RECEIPT: "实际入库", PRODUCTION_RECEIPT: "生产实收入库（关联订单）", OTHER: "其他渠道入库", RETURN: "借用归还", SALES_RETURN: "实际退回", TAKE: "普通取走", CONSUME: "领用/消耗", GIFT: "赠送/送样", BORROW: "借出需归还", SCRAP: "报废", RETURN_SUPPLIER: "退供", QUALITY: "质量变更", LOCATION: "库位变更", DAMAGE: "有依据的实际损坏", COUNT: "实盘总数" };
const actions: Record<string, string> = { OPENING_SUPERSEDE: "更正版期初接替", OPENING_EXTEND: "补齐期初规格", WAREHOUSE_CONVENTION: "采用仓库库存口径", CREATE_DRAFT: "保存草稿", CONFIRM: "确认过账", CORRECT: "更正原记录", REVERSE: "冲销录入错误", OPENING: "登记期初", RESERVE: "预留", RELEASE: "释放预留", FREEZE: "冻结", UNFREEZE: "解冻", SETTLE: "在外结清", RESCHEDULE: "更改归还安排", PLAN: "登记收发安排", CANCEL: "取消安排", UPDATE: "更改安排", COMPLETE_SHIPMENT: "实际发货完成安排", RESTORE_SHIPMENT: "发货更正恢复安排", CONSUME_RESERVATION: "出货消费预留", RESTORE_CONSUMPTION: "发货更正恢复预留", RELEASE_CONSUMPTION: "发货更正释放预留" };
const documentNames: Record<string, string> = { stock: "库存单", opening: "期初", reservation: "订单预留", hold: "库存冻结", loan: "借出记录", plan: "收发安排" };
const intentGroups = [
  { label: "入库", items: [["IN", "入库", "采购、生产或其他渠道的货物到仓"], ["RETURN", "借出归还", "原借出实物返回仓库"]] },
  { label: "出库", items: [["OUT", "取走或消耗", "领用、送样、报废或退供"], ["BORROW", "借出", "离开仓库并继续跟踪归还"]] },
  { label: "调整", items: [["ADJUST", "盘点调整", "按实盘总数修正库存"], ["MOVE", "状态或库位", "货品状态或库位发生变化"]] },
] as const;
function display(value: unknown): string { return typeof value === "string" || typeof value === "number" || typeof value === "boolean" ? `${value}` : "—"; }
const quantity = (value?: string | null) => value == null ? "未就绪" : units(value);
function sumStock(items: Balance[], field: "on_hand_units" | "free_available_units") {
  if (items.some(item => item[field] == null)) return null;
  return items.reduce((sum, item) => sum + BigInt(item[field]!), 0n).toString();
}
const remaining = (item: RecordValue) => BigInt(display(item.units)) - BigInt(display(item.consumed_units || "0")) - BigInt(display(item.released_units || "0"));
function localTime(value: unknown) { const date = new Date(display(value)); return Number.isNaN(date.valueOf()) ? display(value) : new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", dateStyle: "medium", timeStyle: "medium" }).format(date); }
const base = "/api/production/inventory";
function useRead<T>(path: string, refresh = 0, enabled = true) {
  const [value, setValue] = useState<T>(); const [error, setError] = useState<string>(); const { generation, registerSensitivePurge } = useAuthzGeneration();
  useEffect(() => registerSensitivePurge(() => { setValue(undefined); setError(undefined); }), [registerSensitivePurge]);
  useEffect(() => { if (!enabled) { setValue(undefined); setError(undefined); return; } const gate = new RequestGate(); const ticket = gate.begin([path, refresh], generation); setValue(undefined); setError(undefined); void requestApi<T>(path, { signal: ticket.signal }).then(v => { if (ticket.isCurrent()) setValue(v); }).catch((e: unknown) => { if (ticket.isCurrent()) setError(e instanceof Error ? e.message : "读取未完成"); }); return () => gate.dispose(); }, [path, refresh, generation, enabled]);
  return { value, error };
}
function ReadState({ error }: { error?: string }) { return <StatusMessage kind={error ? "danger" : "info"} title={error ? "库存未能读取" : "正在读取库存…"}>{error}</StatusMessage>; }
function useStockLabels() {
  const catalog = useRead<{ items: Sku[] }>("/api/production/skus?contract_version=2");
  const inventory = useRead<{ scopes: { warehouse_id: string; warehouse_name: string }[] }>(`${base}/availability`);
  return {
    variant: (id: string) => catalog.value?.items.find(s => s.sku_id === id),
    sku: (id: unknown) => catalog.value?.items.find(s => s.sku_id === display(id))?.label || `SKU ${display(id)}（${catalog.error ? "商品名称读取失败" : catalog.value ? "身份待核" : "商品名称读取中"}）`,
    warehouse: (id: unknown) => inventory.value?.scopes.find(s => s.warehouse_id === display(id))?.warehouse_name || `仓库 ${display(id)}（${inventory.error ? "名称读取失败" : inventory.value ? "名称待核" : "名称读取中"}）`,
  };
}
type Pending = { path: string; body: RecordValue; key: string };
function useStockCommand(onSuccess: (result: RecordValue) => void, onRejected?: () => void, showSuccess = true) {
  const [busy, setBusy] = useState(false); const [unknown, setUnknown] = useState(false); const [error, setError] = useState<string>(); const [success, setSuccess] = useState<{ message: string; link?: string }>();
  const pending = useRef<Pending | undefined>(undefined); const keys = useRef(new StableOperationKeyStore()); const mounted = useRef(true); const { generation, registerSensitivePurge, purgeSensitiveState } = useAuthzGeneration(); const auth = useRef(generation); auth.current = generation;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => registerSensitivePurge(() => { pending.current = undefined; keys.current = new StableOperationKeyStore(); setUnknown(false); setError(undefined); setSuccess(undefined); }), [registerSensitivePurge]);
  async function run(command: Pending, query = false) {
    if (busy) return; setBusy(true); setError(undefined); const start = auth.current;
    try { const result = query ? await requestApi<RecordValue>(`/api/production/commands/${command.key}`) : await writeApi<RecordValue>(command.path, { body: command.body, operationKey: command.key }); if (mounted.current && auth.current === start) { pending.current = undefined; keys.current = new StableOperationKeyStore(); setUnknown(false); const id = result.id == null ? undefined : display(result.id); const preview = !!result.preview_hash || command.path.endsWith("/preview"); setSuccess({ message: preview ? "预览已生成，尚未保存实际事实。" : `${command.path.includes("/release") || command.path.includes("/cancel") ? "已按本次数量保存" : result.status === "POSTED" ? "已过账" : result.status === "DRAFT" ? "草稿已保存" : "操作已保存"}${id ? `，记录 ${id}` : ""}。`, link: !preview && id ? command.path.includes("/documents") ? `/production/stock/movements/${id}` : command.path.includes("/plans") ? `/production/stock/plans#plan-${id}` : undefined : undefined }); onSuccess(result); } }
    catch (e) { if (!mounted.current || auth.current !== start) return; if (e instanceof ApiRequestError && e.status === 403) { purgeSensitiveState(); return; } const uncertain = query || !(e instanceof ApiRequestError) || e.status >= 500; setUnknown(uncertain); if (!uncertain) { pending.current = undefined; onRejected?.(); } setError(e instanceof Error ? e.message : "保存未完成"); }
    finally { if (mounted.current && auth.current === start) setBusy(false); }
  }
  function submit(path: string, body: RecordValue) { if (busy || unknown || pending.current) return; setSuccess(undefined); const key = keys.current.forCommand("stock", path, body); const command = { path, key, body: { ...body, operation_token: key } }; pending.current = command; void run(command); }
  return { submit, busy, unknown, feedback: <>{showSuccess && success && <StatusMessage kind="success" title="操作已完成">{success.message}{success.link && <Link to={success.link}>查看记录</Link>} 列表重读失败时请先查询记录，不要重复提交。</StatusMessage>}{error && <StatusMessage kind={unknown ? "warning" : "danger"} title={unknown ? "保存结果未知，先核实原操作" : "操作未完成"}>{error}{unknown && <div className={styles.actions}><Button disabled={busy} onClick={() => { if (pending.current) void run(pending.current, true); }}>查询原操作结果</Button><Button disabled={busy} onClick={() => { if (pending.current) void run(pending.current); }}>重发原操作</Button></div>}</StatusMessage>}</> };
}
function NumberField({ label, value, onChange, allowZero = false, disabled = false, hint, error, markRequired = false }: { error?: string; disabled?: boolean; label: string; value: string; onChange: (value: string) => void; allowZero?: boolean; hint?: string; markRequired?: boolean }) { return <FormField label={label} required={markRequired} hint={hint} error={error}><Input disabled={disabled} required inputMode="numeric" pattern={allowZero ? "0|[1-9][0-9]*" : "[1-9][0-9]*"} value={value} onChange={e => onChange(e.target.value)} /></FormField>; }
function Select({ label, value, choices, onChange, disabled = false, markRequired = false }: { disabled?: boolean; label: string; value: string; choices: Record<string, string>; onChange: (value: string) => void; markRequired?: boolean }) { return <FormField label={label} required={markRequired}><select disabled={disabled} required value={value} onChange={e => onChange(e.target.value)}>{Object.entries(choices).map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></FormField>; }
function SkuSelect({ value, onChange, skus, disabled = false, markRequired = false }: { disabled?: boolean; value: string; onChange: (value: string) => void; skus: Sku[]; markRequired?: boolean }) { return <FormField label="商品颜色与尺码" required={markRequired}><select disabled={disabled} required value={value} onChange={e => onChange(e.target.value)}><option value="">选择已知SKU</option>{skus.map(s => <option key={s.sku_id} value={s.sku_id}>{s.label}</option>)}</select></FormField>; }
function WarehouseSelect({ value, onChange, disabled = false, onDefault, markRequired = false }: { value: string; onChange: (value: string) => void; disabled?: boolean; onDefault?: (value: string) => void; markRequired?: boolean }) {
  const { value: inventory, error } = useRead<{ scopes: { warehouse_id: string; warehouse_name: string }[] }>(`${base}/availability`); const initialized = useRef(false);
  useEffect(() => { if (!disabled && !initialized.current && inventory?.scopes.length) { initialized.current = true; if (!inventory.scopes.some(scope => scope.warehouse_id === value)) (onDefault || onChange)(inventory.scopes[0]!.warehouse_id); } }, [inventory, value, onChange, onDefault, disabled]);
  return <FormField label="仓库" required={markRequired}><select disabled={disabled} required={markRequired} value={value} onChange={e => onChange(e.target.value)}>{inventory?.scopes.length ? inventory.scopes.map(scope => <option key={scope.warehouse_id} value={scope.warehouse_id}>{scope.warehouse_name}</option>) : <option value={value}>{error ? "仓库信息读取失败" : inventory ? "尚无已登记仓库" : "正在读取仓库信息…"}</option>}</select></FormField>;
}
function StockRecordPanel({ inline, ...props }: ComponentProps<typeof Dialog> & { inline?: boolean }) {
  const trigger = useRef<HTMLElement | null>(null);
  const content = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!inline) return;
    if (props.open) { trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; content.current?.focus({preventScroll:true}); content.current?.scrollIntoView?.({block:"start"}); }
    else if (trigger.current?.isConnected) trigger.current.focus({preventScroll:true});
  }, [inline, props.open]);
  if (!inline) return <Dialog {...props} />;
  return props.open ? <section ref={content} tabIndex={-1} className={styles.panel} aria-label={typeof props.title === "string" ? props.title : undefined}>
    <header><h3>{props.title}</h3>{props.description && <p>{props.description}</p>}<Button variant="quiet" disabled={props.dismissDisabled} onClick={() => props.onOpenChange(false)}>返回记录</Button></header>
    {props.children}
  </section> : null;
}
function StockHome({ canWrite, value, error, catalogValue, catalogError, refreshStock, action, onGuardChange, onAction }: { canWrite: boolean; value?: { items: Balance[]; scopes: {warehouse_id:string;warehouse_name:string;owner_id?:string;owner_name?:string}[] }; error?: string; catalogValue?: Sku[]; catalogError?: string; refreshStock: () => void; action?: OverviewAction; onAction?: (action: OverviewAction) => void; onGuardChange?: (guard: OverviewGuard) => void }) {
  const [scopeError,setScopeError]=useState<string>();
  const [refresh, setRefresh] = useState(0); const reservations = useRead<Items<RecordValue>>(`${base}/reservations`, refresh); const holds = useRead<Items<RecordValue>>(`${base}/holds`, refresh);
  const [occupancyOpen, setOccupancyOpen] = useState(action?.kind === "reserve"); const [control, setControl] = useState("reservations"); const [sku, setSku] = useState(action?.sku_id || ""); const [warehouse, setWarehouse] = useState(action?.warehouse_id || "1"); const [owner, setOwner] = useState(action?.owner_id || "1"); const [amount, setAmount] = useState(""); const [orderLine, setOrderLine] = useState(""); const [orderSearch, setOrderSearch] = useState(""); const candidates = useRead<Items<Document>>(`/api/production/orders?status=CONFIRMED&selectable=true&page_size=50&sku=${encodeURIComponent(sku)}&q=${encodeURIComponent(orderSearch)}`, 0, occupancyOpen && control === "reservations" && Boolean(sku)); const [reason, setReason] = useState(""); const [release, setRelease] = useState<{ item: RecordValue; resource: string; amount: string; reason: string }>(); const [releaseTouched, setReleaseTouched] = useState(false); const [touched, setTouched] = useState(false); const catalog = { value: catalogValue ? {items:catalogValue} : undefined, error: catalogError }; const command = useStockCommand(() => { setRelease(undefined); setReleaseTouched(false); setTouched(false); setRefresh(v => v + 1); refreshStock(); setAmount(""); setReason(""); });
  const currentSkuLabel = (id: string) => catalog.value?.items.find(item => item.sku_id === id)?.label || value?.items.find(item => item.sku_id === id && item.identity_status === "pending")?.sku_label || `SKU ${id}（${catalog.error ? "商品名称读取失败" : catalog.value ? "身份待核" : "商品名称读取中"}）`;
  const leave = useProductionLeave(touched || releaseTouched, command.busy, command.unknown, overviewSearchParams);
  useEffect(() => { onGuardChange?.({dirty:touched || releaseTouched,busy:command.busy,unknown:command.unknown,blocked:leave.blocked}); }, [touched,releaseTouched,command.busy,command.unknown,leave.blocked,onGuardChange]);
  const [selectedBalance, setSelectedBalance] = useState<Balance>();
  const [selectedCellBalances, setSelectedCellBalances] = useState<Balance[]>([]);
  const warehouseName = (id: string) => value?.scopes.find(scope => scope.warehouse_id === id)?.warehouse_name || `仓库 ${id}（名称待核）`;
  const visibleOccupancy = (items?: RecordValue[]) => (items || []).filter(item => !action?.sku_id || (display(item.sku_id) === action.sku_id && display(item.warehouse_id) === action.warehouse_id && display(item.owner_id || "1") === action.owner_id));
  const noOccupancy = !!reservations.value && !!holds.value && !reservations.value.items.length && !holds.value.items.length;

  return <div className={styles.stockOverview}>{(reservations.error || holds.error) && <Button onClick={()=>setRefresh(value=>value+1)}>重新读取占用</Button>}
    {(!action || action.kind === "source") && <section aria-label="原始库存记录（按仓库与货权）" hidden={!!selectedBalance || !!release}>{value ? <Table title="原始库存记录"><thead><tr><th>库存SKU</th><th>仓库与货权</th><th>在库 / 可发</th><th>来源日期</th></tr></thead><tbody>{value.items.map(item=><tr key={`${item.warehouse_id}:${item.owner_id}:${item.sku_id}`}><th scope="row"><Button variant="quiet" aria-label={`查看${item.style_code || catalog.value?.items.find(sku=>sku.sku_id===item.sku_id)?.style_code || currentSkuLabel(item.sku_id)} ${item.standard_color || "颜色待核"} ${item.standard_size || "尺码待核"}库存明细`} onClick={()=>{setSelectedCellBalances(value.items.filter(value=>value.sku_id===item.sku_id));setSelectedBalance(item);}}>查看{currentSkuLabel(item.sku_id)}原始记录</Button></th><td>{warehouseName(item.warehouse_id)} · {value.scopes.find(scope=>scope.warehouse_id===item.warehouse_id&&scope.owner_id===item.owner_id)?.owner_name || `货权 ${item.owner_id}`}</td><td>{quantity(item.on_hand_units)} / {quantity(item.free_available_units)}</td><td>{item.cutoff_on || "待补"}</td></tr>)}</tbody></Table> : <ReadState error={error}/>}</section>}
    <StockRecordPanel inline={!!action} contentClassName={styles.productionDialog} open={!!selectedBalance} onOpenChange={open => { if (!open) setSelectedBalance(undefined); }} title="库存明细" description={selectedBalance ? currentSkuLabel(selectedBalance.sku_id) : undefined}>
      {selectedBalance && <div className={styles.stockDetail}>
        {selectedCellBalances.length > 1 && <section aria-label="本格库存记录"><h3>分条查看库存</h3><p>本格包含{selectedCellBalances.length}条库存记录，合计{quantity(sumStock(selectedCellBalances, "on_hand_units"))}件；各条商品身份、来源与操作分别保留。</p><div className={styles.actions}>{selectedCellBalances.map((item, index) => <Button key={`${item.warehouse_id}:${item.owner_id}:${item.sku_id}`} variant="secondary" aria-pressed={item === selectedBalance} onClick={() => setSelectedBalance(item)}>记录{index + 1} · {warehouseName(item.warehouse_id)} · {currentSkuLabel(item.sku_id)} · {quantity(item.on_hand_units)}件{item.identity_status === "pending" ? " · 商品身份待核" : ""}</Button>)}</div></section>}
        <p className={styles.stockDetailContext}>{warehouseName(selectedBalance.warehouse_id)} · {value?.scopes.find(scope=>scope.warehouse_id===selectedBalance.warehouse_id && scope.owner_id===selectedBalance.owner_id)?.owner_name || `货权 ${selectedBalance.owner_id}`} · 来源日期 {selectedBalance.cutoff_on || "待补"}</p>
        <p className={styles.stockDetailContext}>来源依据：{selectedBalance.source_reference || "待补"}</p><p className={styles.stockDetailContext}>来源颜色：{selectedBalance.standard_color || catalog.value?.items.find(item => item.sku_id === selectedBalance.sku_id)?.standard_color || "颜色待核"}</p>
        <dl className={styles.stockDetailTotals}><div><dt>实际在库</dt><dd>{quantity(selectedBalance.on_hand_units)}<small>件</small></dd></div><div><dt>当前自由可发</dt><dd>{quantity(selectedBalance.free_available_units)}{selectedBalance.free_available_units != null && <small>件</small>}</dd></div></dl>
        {selectedBalance.state !== "ready" && <StatusMessage kind={selectedBalance.state === "shortage" ? "danger" : "warning"} title={selectedBalance.state === "shortage" ? "存在缺口，暂停发货" : selectedBalance.identity_status === "pending" ? "商品身份待核，禁止过账" : selectedBalance.on_hand_units == null ? "期初资料待补" : "数量已登记，可发待核"}>{selectedBalance.missing || (selectedBalance.state === "shortage" ? "库存与冻结、预留存在缺口，请先核对占用和实际库存。" : "期初资料尚未齐备，当前不能计算可发数量。")}</StatusMessage>}
        {selectedBalance.opening_metadata?.quantity_basis === "NORMAL_DISPATCHABLE_V1" && <p className={styles.stockDetailNote}>仓库表按正常可发库存登记；待检、次品、冻结等异常单独记录，无需逐规格重复核对质量。</p>}
        <section><h3>货品状态</h3><dl className={styles.stockDetailList}><div><dt>质量未核</dt><dd>{quantity(selectedBalance.unassessed_units)} 件</dd></div><div><dt>已确认合格</dt><dd>{quantity(selectedBalance.qualified_units)} 件</dd></div><div><dt>已确认待检</dt><dd>{quantity(selectedBalance.pending_units)} 件</dd></div><div><dt>已确认次品</dt><dd>{quantity(selectedBalance.defective_units)} 件</dd></div></dl>{selectedBalance.unassessed_units && selectedBalance.unassessed_units !== "0" && <p className={styles.stockDetailNote}>其中{quantity(selectedBalance.unassessed_units)}件尚未划分质量；已确认数量为0不代表没有实物。</p>}</section>
        {canWrite && selectedBalance.owner_id === "1" && selectedBalance.identity_status !== "pending" && selectedBalance.pending_units != null && BigInt(selectedBalance.pending_units) > 0n && (onAction ? <Button onClick={()=>onAction({kind:"inspect",sku_id:selectedBalance.sku_id,warehouse_id:selectedBalance.warehouse_id,owner_id:selectedBalance.owner_id})}>处理当前待检库存</Button> : <Link to={`/production/stock/movements/new?intent=INSPECT&sku_id=${selectedBalance.sku_id}&warehouse_id=${selectedBalance.warehouse_id}&owner_id=${encodeURIComponent(selectedBalance.owner_id)}`}>处理当前待检库存</Link>)}
        <section><h3>占用与借出</h3><dl className={styles.stockDetailList}><div><dt>冻结</dt><dd>{quantity(selectedBalance.held_units)} 件</dd></div><div><dt>预留</dt><dd>{quantity(selectedBalance.reserved_units)} 件</dd></div><div><dt>借出未还</dt><dd>{quantity(selectedBalance.loan_outstanding_units)} 件</dd></div></dl><p className={styles.stockDetailNote}>冻结和预留不减少实物；借出在外的数量不计入仓内实际。</p></section>
        <div className={styles.stockDetailLinks}>{canWrite && selectedBalance.identity_status !== "pending" && (onAction ? <Button onClick={()=>onAction({kind:"movement",sku_id:selectedBalance.sku_id,warehouse_id:selectedBalance.warehouse_id,owner_id:selectedBalance.owner_id})}>为此商品登记变动</Button> : <Link to={`/production/stock/movements/new?sku_id=${encodeURIComponent(selectedBalance.sku_id)}&warehouse_id=${encodeURIComponent(selectedBalance.warehouse_id)}&owner_id=${encodeURIComponent(selectedBalance.owner_id)}`}>为此商品登记变动</Link>)}<Link to={selectedBalance.opening_metadata?.review_id ? `/production/inventory?review=${encodeURIComponent(selectedBalance.opening_metadata.review_id)}` : "/production/inventory"}>查看来源资料</Link><Link to="/production/stock/history">查看操作历史</Link></div>
      </div>}
    </StockRecordPanel>
    {canWrite && action?.kind !== "source" && <details hidden={!!release} open={action?.kind === "reserve"} className={`${styles.panel} ${styles.workflowTools}`} onToggle={event => setOccupancyOpen(event.currentTarget.open)}><summary>预留或冻结库存</summary>{occupancyOpen && <form className={styles.body} onChangeCapture={() => { setTouched(true); setScopeError(undefined); }} onSubmit={e => { e.preventDefault(); const balance = value?.items.find(b => b.sku_id === sku && b.warehouse_id === warehouse && b.owner_id === owner); if (!balance || balance.identity_status === "pending") { setScopeError("当前SKU与仓库、货权不匹配，请重新选择库存SKU。"); return; } command.submit(`${base}/${control}`, { warehouse_id: warehouse, owner_id: owner, sku_id: sku, units: amount, reason, ...(control === "reservations" ? { order_line_id: orderLine } : {}), ...(balance?.revision ? { expected_balance_revision: balance.revision } : {}) }); }}>{scopeError && <StatusMessage kind="warning" title="请选择有效的库存范围">{scopeError}</StatusMessage>}<fieldset disabled={command.busy || command.unknown}><div className={styles.filters}><Select label="占用类型" value={control} choices={{ reservations: "为订单明确预留", holds: "冻结合格货品" }} onChange={setControl} /><FormField label="库存SKU"><select required value={sku ? `${warehouse}:${owner}:${sku}` : ""} onChange={e => { const [w, o, s] = e.target.value.split(":"); setWarehouse(w || "1"); setOwner(o || "1"); setSku(s || ""); setOrderLine(""); }}><option value="">选择库存SKU</option>{value?.items.filter(b => b.identity_status !== "pending").map(b => <option key={`${b.warehouse_id}:${b.owner_id}:${b.sku_id}`} value={`${b.warehouse_id}:${b.owner_id}:${b.sku_id}`}>{currentSkuLabel(b.sku_id)}（{value.scopes?.find(scope => scope.warehouse_id === b.warehouse_id)?.warehouse_name || `仓库 ${b.warehouse_id}（名称待核）`}） · {value.scopes?.find(scope=>scope.warehouse_id===b.warehouse_id && scope.owner_id===b.owner_id)?.owner_name || `货权 ${b.owner_id}`}</option>)}</select></FormField><WarehouseSelect value={warehouse} onChange={setWarehouse} /><FormField label="货权"><select value={owner} onChange={event=>{setOwner(event.target.value);setOrderLine("");}}>{value?.scopes.filter(scope=>scope.warehouse_id===warehouse).map(scope=><option key={scope.owner_id || "1"} value={scope.owner_id || "1"}>{scope.owner_name || `货权 ${scope.owner_id || "1"}`}</option>)}</select></FormField><NumberField label="占用数量" value={amount} onChange={setAmount} />{control === "reservations" && <><FormField label="关联订单搜索"><Input value={orderSearch} onChange={e => setOrderSearch(e.target.value)} placeholder="业务单号或系统单号" /></FormField><FormField label="为哪张订单预留"><select required value={orderLine} onChange={e => setOrderLine(e.target.value)}><option value="">选择同SKU的已确认订单</option>{candidates.value?.items.flatMap(order => (order.lines || []).filter(line => line.sku_id === sku && line.tracking_state !== "CLOSED").map(line => <option key={line.id} value={line.id}>{order.business_number || order.system_number} · {line.sku_label} · 待跟进{line.pending_units || line.difference_units}件</option>))}</select></FormField></>}<FormField label="占用原因"><Input required value={reason} onChange={e => setReason(e.target.value)} /></FormField></div><Button type="submit">确认占用</Button></fieldset></form>}</details>}
    {(reservations.value || reservations.error) && (holds.value || holds.error) && <details hidden={!!release} className={styles.stockOccupancy} open={action?.kind === "release" || !noOccupancy ? true : undefined}><summary>预留与冻结 <span>{noOccupancy ? "暂无占用记录" : "查看占用及释放记录"}</span></summary>
    {[{ name: "订单预留", resource: "reservations", data: reservations }, { name: "库存冻结", resource: "holds", data: holds }].map(group => <Table key={group.resource} title={group.name}><thead><tr><th>对象</th><th>原占用</th><th>已消费/释放</th><th>原因</th><th>操作</th></tr></thead><tbody>{visibleOccupancy(group.data.value?.items).map(item => <tr key={display(item.id)}><td>{catalog.value?.items.find(s => s.sku_id === display(item.sku_id))?.label || `SKU ${display(item.sku_id)}（身份待核）`}{item.order_business_number ? ` · 订单${display(item.order_business_number)}` : item.order_line_id ? ` · 订单行${display(item.order_line_id)}（业务号待核）` : ""}<br />{value?.scopes?.find(scope => scope.warehouse_id === display(item.warehouse_id))?.warehouse_name || `仓库 ${display(item.warehouse_id)}（名称待核）`}</td><td>{quantity(display(item.units))}</td><td>消费{quantity(display(item.consumed_units || "0"))} · 释放{quantity(display(item.released_units))}</td><td>{display(item.reason)}</td><td>{canWrite && remaining(item) > 0n && <Button disabled={command.busy || command.unknown} onClick={() => setRelease({ item, resource: group.resource, amount: remaining(item).toString(), reason: "" })}>核对释放</Button>}</td></tr>)}{!visibleOccupancy(group.data.value?.items).length && <tr><td colSpan={5}>{group.data.error || "没有占用记录"}</td></tr>}</tbody></Table>)}</details>}<StockRecordPanel inline={!!action} contentClassName={styles.productionDialog} open={!!release} onOpenChange={open => { if (!open) { setRelease(undefined); setReleaseTouched(false); } }} dismissDisabled={command.busy || command.unknown} title={release?.resource === "reservations" ? "确认释放订单预留" : "确认解冻库存"} description="释放只改变当前可发占用，不改变仓内实际件数。">
      {release && <form onSubmit={e => { e.preventDefault(); command.submit(`${base}/${release.resource}/${display(release.item.id)}/release`, { expected_revision: release.item.revision, units: release.amount, reason: release.reason }); }}><p>{catalog.value?.items.find(s => s.sku_id === display(release.item.sku_id))?.label || `SKU ${display(release.item.sku_id)}（身份待核）`} · {value?.scopes?.find(scope => scope.warehouse_id === display(release.item.warehouse_id))?.warehouse_name || `仓库 ${display(release.item.warehouse_id)}`}</p><p>{release.item.order_business_number ? `关联订单 ${display(release.item.order_business_number)} · ` : ""}当前有效占用 {quantity(remaining(release.item).toString())} 件。</p><NumberField label="本次释放件数" value={release.amount} onChange={amount => { setReleaseTouched(true); setRelease({ ...release, amount }); }} /><FormField label="实际释放原因"><Input required value={release.reason} onChange={e => { setReleaseTouched(true); setRelease({ ...release, reason: e.target.value }); }} /></FormField><div className={styles.dialogActions}><Button variant="secondary" disabled={command.busy || command.unknown} onClick={() => { setRelease(undefined); setReleaseTouched(false); }}>返回</Button><Button type="submit" disabled={command.busy || command.unknown}>确认释放</Button></div>{command.feedback}</form>}
    </StockRecordPanel>{!release && command.feedback}{leave.prompt}
  </div>;
}

function Opening({ canWrite }: { canWrite: boolean }) {
 const [params]=useSearchParams();const navigate=useNavigate();const [guard,setGuard]=useState({dirty:false,busy:false,unknown:false});const leave=useProductionLeave(guard.dirty,guard.busy,guard.unknown);
 if(!canWrite)return <StatusMessage kind="warning" title="当前账号不能登记期初"/>;
 const warehouse=params.get('warehouse_id')||'1';
 return <><PageHeader title="期初库存"/><WarehouseOpening warehouseId={warehouse} onGuardChange={setGuard} saved={()=>{leave.allowLeave();void navigate(`/production/warehouses/${warehouse}?tab=stock`);}}/>{leave.prompt}</>;
}

function Movements({ canWrite }: { canWrite: boolean }) {
  const { value, error } = useRead<Items<Movement>>(`${base}/documents`);
  const labels = useStockLabels();
  return <div className={recordStyles.page}>
    <PageHeader title="库存记录" actions={canWrite && <LinkButton to="/production/stock/movements/new">登记库存变动</LinkButton>} />
    {value ? <Table className={styles.stockRecordTable} aria-label="库存记录">
      <thead><tr><th>单据与商品</th><th>发生日期</th><th>仓库</th><th>数量与状态</th><th>依据</th></tr></thead>
      <tbody>{value.items.map(record => {
        const products = [...new Set(record.lines.map(line => labels.sku(line.sku_id)))].join("、");
        const total = record.lines.reduce((sum, line) => sum + BigInt(line.units), 0n);
        return <tr key={record.id}>
          <td data-label="单据与商品"><Link to={`/production/stock/movements/${record.id}`}>{kinds[record.kind]} #{record.id}</Link><span className={recordStyles.listProduct} title={products}>{products}</span></td>
          <td data-label="发生日期">{record.business_date}</td>
          <td data-label="仓库">{labels.warehouse(record.warehouse_id)}</td>
          <td data-label="数量与状态"><div className={recordStyles.product}><strong>{units(total.toString())} 件</strong><WarehouseRecordStatus status={record.status} kind={record.kind} /></div></td>
          <td data-label="依据">{withoutTableBaseline(record.reason)}</td>
        </tr>;
      })}{!value.items.length && <tr><td colSpan={5}>暂无库存变动。登记实际发生的业务后，记录会显示在这里。</td></tr>}</tbody>
    </Table> : <ReadState error={error} />}
  </div>;
}
const defaultPurpose = { IN: "RECEIPT", OUT: "TAKE", MOVE: "QUALITY", ADJUST: "COUNT" };
function ProductionReceiptAllocations({ sku, allocations, onChange }: { sku: string; allocations: Allocation[]; onChange: (value: Allocation[]) => void }) {
  const [query, setQuery] = useState(""); const [page, setPage] = useState(1);
  const orders = useRead<DocumentPage>(`/api/production/orders?status=CONFIRMED&sku=${encodeURIComponent(sku)}&q=${encodeURIComponent(query)}&page=${page}&page_size=20`, 0, !!sku);
  const choices = orders.value?.items.flatMap(o => (o.lines || []).filter(l => l.sku_id === sku).map(l => ({ id: l.id, label: `${o.business_number || o.system_number} · 预计${units(l.expected_units)}件` }))) || [];
  const update = (index: number, field: "order_line_id" | "units", value: string) => onChange(allocations.map((a, i) => i === index ? { ...a, [field]: value } : a));
  return <fieldset><legend>生产实收来源订单 *</legend><p hidden>只登记已实际到仓的货物，完工通知不增加库存。分配合计须等于本次入库；实收与已发分开，不据此判断是否完工。</p>
    {!sku ? <p>请先选择本次入库的商品。</p> : <><FormField label="查找来源订单"><Input value={query} onChange={e => { setQuery(e.target.value); setPage(1); }} placeholder="订单号／系统编号" /></FormField>
      {orders.error ? <ReadState error={orders.error} /> : !orders.value ? <p role="status">正在读取同商品来源订单…</p> : !choices.length && <p role="status">当前条件下没有同商品的已确认订单，请调整搜索；不按名称或日期自动关联。</p>}
      {allocations.map((a, index) => <div key={index} className={styles.filters}><FormField label={`来源订单行${index + 1}`} required><select required value={a.order_line_id} onChange={e => update(index, "order_line_id", e.target.value)}><option value="">选择同商品已确认订单</option>{a.order_line_id && !choices.some(c => c.id === a.order_line_id) && <option value={a.order_line_id}>{`已选订单行 ${a.order_line_id}（可搜索核对）`}</option>}{choices.filter(c => c.id === a.order_line_id || !allocations.some(other => other.order_line_id === c.id)).map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select></FormField><NumberField markRequired label={`订单分配件数${index + 1}`} value={a.units} onChange={value => update(index, "units", value)} />{allocations.length > 1 && <Button variant="quiet" onClick={() => onChange(allocations.filter((_, i) => i !== index))}>移除分配{index + 1}</Button>}</div>)}
      <Button variant="secondary" onClick={() => onChange([...allocations, { order_line_id: "", units: "" }])}>增加来源订单</Button>
      {orders.value && orders.value.total > 20 && <Pagination itemLabel="来源订单" page={page} totalItems={orders.value.total} totalPages={Math.ceil(orders.value.total / 20)} onPageChange={setPage} />}
    </>}
  </fieldset>;
}
function ProductionReceiptPreview({ sources }: { sources?: ProductionReceiptSource[] }) {
  if (!sources?.length) return null;
  return <section><h2>生产实收关联预览</h2><p hidden>确认后计入下列订单的累计实收，不增加订单已发。预览不改变库存或来源记录。</p><Table title="来源订单分配"><thead><tr><th>入库明细</th><th>来源订单</th><th>实收分配件数</th></tr></thead><tbody>{sources.map(s => <tr key={`${s.line_number}:${s.order_line_id}`}><td>明细{s.line_number}</td><td><Link to={`/production/orders/${s.order_id}`}>{s.order_business_number || s.order_number}</Link></td><td>{units(s.units)}</td></tr>)}</tbody></Table></section>;
}
function NewMovement({ canWrite, receiptSupported }: { canWrite: boolean; receiptSupported: boolean }) {
  const [params] = useSearchParams(); const orderId = params.get("order_id");
  const source = useRead<Document>(`/api/production/orders/${encodeURIComponent(orderId || "")}`, 0, !!orderId && canWrite && receiptSupported);
  if (!params.has("order_id")) return <MovementEditor key={params.get("intent") === "INSPECT" ? params.toString() : "independent"} canWrite={canWrite} />;
  if (!canWrite) return <StatusMessage kind="warning" title="查看人员不能登记库存变动" />;
  if (!orderId) return <StatusMessage kind="warning" title="来源订单编号无效，请返回订单核对。" />;
  if (!receiptSupported) return <StatusMessage kind="warning" title="当前服务尚未支持订单生产实收入口，请返回订单核对。" />;
  if (source.error) return <><ReadState error={source.error} /><Link to={`/production/orders/${encodeURIComponent(orderId)}`}>返回来源订单</Link></>;
  if (!source.value || source.value.id !== orderId) return <ReadState />;
  if (source.value.status !== "CONFIRMED") return <StatusMessage kind="warning" title="来源订单尚未确认或已作废，不能从此订单登记生产实收。" />;
  if (!source.value.lines?.length) return <StatusMessage kind="warning" title="来源订单没有可用商品明细，请返回订单核对。" />;
  return <MovementEditor key={orderId} sourceOrder={source.value} canWrite={canWrite} />;
}
type WarehouseMovementContext = { warehouse_id: string; owner_id: string; kind: string; intent: string; sku_id?: string; loan_id?: string; source_quality?: string };
function MovementEditor({ initial, sourceOrder, canWrite, context, onSaved, wizard = false, onClose, preservedSearchParams, onGuardChange }: { initial?: Movement; sourceOrder?: Document; canWrite: boolean; context?: WarehouseMovementContext; onSaved?: (id: string) => void; wizard?: boolean; onClose?: () => void; preservedSearchParams?: readonly string[]; onGuardChange?: (guard: OverviewGuard) => void }) {
  const guided = wizard && (!initial || initial.status === "DRAFT") && !!context;
  const [wizardStep, setWizardStep] = useState(0);
  const [wizardDraft, setWizardDraft] = useState<Pick<Movement, "id" | "revision" | "status"> | undefined>(initial);
  const [autoPreview, setAutoPreview] = useState(false);
  const wizardForm = useRef<HTMLFormElement>(null);
  const [urlParams, setUrlParams] = useSearchParams();
  const params = context ? new URLSearchParams(Object.entries(context).filter((entry): entry is [string, string] => typeof entry[1] === "string")) : urlParams;
  const inspection = !initial && !sourceOrder && params.get("intent") === "INSPECT"; const owner = initial?.owner_id || params.get("owner_id") || "1";
  const [stockRefresh, setStockRefresh] = useState(0);
  const today = useBusinessToday();
  const navigate = useNavigate(); const catalog = useRead<{ items: Sku[] }>("/api/production/skus?contract_version=2"); const plans = useRead<Items<RecordValue>>(`${base}/plans`); const loans = useRead<Items<RecordValue>>(`${base}/loans`, stockRefresh); const [kind, setKind] = useState(initial?.kind || (sourceOrder ? "IN" : inspection ? "MOVE" : params.get("kind") || (params.get("loan_id") ? "IN" : ""))); const [intent, setIntent] = useState(sourceOrder ? "IN" : inspection ? "INSPECT" : initial?.lines[0]?.purpose === "BORROW" ? "BORROW" : initial?.lines[0]?.purpose === "RETURN" || params.get("loan_id") ? "RETURN" : initial?.kind || params.get("intent") || params.get("kind") || ""); const [warehouse, setWarehouse] = useState(initial?.warehouse_id || params.get("warehouse_id") || "1"); const [date, setDate] = useState(initial?.business_date || today()); const [reason, setReason] = useState(initial?.status === "DRAFT" ? withoutTableBaseline(initial.reason) : "");
  const [lines, setLines] = useState<MovementLine[]>(initial?.lines || [{ sku_id: sourceOrder ? "" : params.get("sku_id") || "", units: "", quality: inspection || (!sourceOrder && params.get("kind") === "MOVE" && params.get("source_quality") === "PENDING") ? "PENDING" : params.get("intent") === "BORROW" ? "QUALIFIED" : "", purpose: sourceOrder ? "PRODUCTION_RECEIPT" : inspection ? "QUALITY" : params.get("loan_id") ? "RETURN" : params.get("intent") === "BORROW" ? "BORROW" : defaultPurpose[(params.get("kind") || "OUT") as keyof typeof defaultPurpose], target_quality: "", loan_id: sourceOrder || inspection ? undefined : params.get("loan_id") || undefined, plan_id: sourceOrder || inspection ? undefined : params.get("plan_id") || undefined }]); const [touched, setTouched] = useState(false); const [correctionPreview, setCorrectionPreview] = useState<RecordValue>();
  const audit = useTableBaseline(initial?.reason, kind === "ADJUST" ? "count" : "receipt");
  const [importBusy,setImportBusy] = useState(false);
  const qualityWorkflow = kind === "MOVE" && !inspection;
  const stock = useRead<{ items: Balance[]; scopes: { warehouse_id: string; warehouse_name: string; owner_id?: string; owner_name?: string }[]; production_receipts_supported?: boolean }>(`${base}/availability`, stockRefresh);
  const [associationNotice, setAssociationNotice] = useState("");
  const lockedOrigin = !initial && !sourceOrder && !inspection && !!(params.get("loan_id") || params.get("plan_id"));
  const origin = params.get("loan_id") ? loans.value?.items.find(l => display(l.id) === params.get("loan_id")) : plans.value?.items.find(p => display(p.id) === params.get("plan_id"));
  const originError = lockedOrigin && origin && (display(origin.sku_id) !== lines[0]?.sku_id || display(origin.warehouse_id) !== warehouse || display(origin.owner_id) !== owner) ? "关联记录的商品或仓库不一致，请返回原记录重新进入。" : undefined;
  function lineError(line: MovementLine) {
    if (!line.sku_id) return undefined;
    const balance = stock.value?.items.find(b => b.sku_id === line.sku_id && b.warehouse_id === warehouse && b.owner_id === owner);
    if (stock.value && (!balance || balance.state === "not_ready")) return "该商品在此仓库的期初未就绪；可保存草稿，暂不能确认库存。";
    return undefined;
  }
  function quantityError(line: MovementLine) {
    if (kind === "ADJUST" && line.sku_id && line.quality && lines.filter(item => item.sku_id === line.sku_id && item.quality === line.quality).length > 1) return "同一商品同一货品状态只填写一条实盘总数，请合并重复明细。";
    if (guided && intent === "BORROW" && line.sku_id && /^[1-9][0-9]*$/.test(line.units)) {
      if (line.quality !== "QUALIFIED") return "借出只允许使用合格库存，请核对货品状态。";
      const available = stock.value?.items.find(item => item.sku_id === line.sku_id && item.warehouse_id === warehouse && item.owner_id === owner)?.free_available_units;
      const requested = lines.filter(item => item.sku_id === line.sku_id && /^[1-9][0-9]*$/.test(item.units)).reduce((sum, item) => sum + BigInt(item.units), 0n);
      if (available != null && requested > BigInt(available)) return `本次同商品借出合计${units(requested.toString())}件，当前可发仅${units(available)}件，请核对数量。`;
    }
    if (kind === "MOVE" && line.purpose === "LOCATION" && line.location_from?.trim() && line.location_from.trim() === line.location_to?.trim()) return "来源与目标库位不能相同，请核对实际移动位置。";
    if (kind === "MOVE" && line.purpose !== "LOCATION" && line.quality && line.target_quality === line.quality && !line.location_from && !line.location_to) return "质量处理需选择不同的目标状态；只换位置请选择移动库位。";
    if (qualityWorkflow && initial?.status !== "POSTED" && line.sku_id && line.quality && /^[1-9][0-9]*$/.test(line.units)) {
      const balance = stock.value?.items.find(item => item.sku_id === line.sku_id && item.warehouse_id === warehouse && item.owner_id === owner);
      const available = line.quality === "QUALIFIED" ? balance?.qualified_units : line.quality === "PENDING" ? balance?.pending_units : line.quality === "DEFECTIVE" ? balance?.defective_units : undefined;
      if (available != null) {
        if (BigInt(line.units) > BigInt(available)) return `本次填写${units(line.units)}件，当前${qualities[line.quality]}仅${units(available)}件，请减少数量或核对商品及来源状态。`;
        const netOut = lines.filter(item => item.sku_id === line.sku_id && /^[1-9][0-9]*$/.test(item.units)).reduce((sum, item) => sum + (item.quality === line.quality ? BigInt(item.units) : 0n) - (item.target_quality === line.quality ? BigInt(item.units) : 0n), 0n);
        if (netOut > BigInt(available)) return `同商品本次从${qualities[line.quality]}净转出${units(netOut.toString())}件，当前仅${units(available)}件，请核对各条数量。`;
      }
    }
    if (inspection && line.sku_id) {
      const pending = stock.value?.items.find(b => b.sku_id === line.sku_id && b.warehouse_id === warehouse && b.owner_id === owner)?.pending_units;
      if (pending == null) return "当前待检数量尚未核实，不能保存处理草稿。";
      if (BigInt(pending) === 0n) return "当前没有待检库存，无需重复处理。";
      const requested = lines.filter(l => l.sku_id === line.sku_id && /^[1-9][0-9]*$/.test(l.units)).reduce((sum, l) => sum + BigInt(l.units), 0n);
      if (requested > BigInt(pending)) return `同商品本次处理合计${requested}件，当前待检仅${pending}件，请核对。`;
    }
    if (line.purpose === "PRODUCTION_RECEIPT") {
      const allocations = line.production_allocations || [];
      if (!allocations.length || allocations.some(a => !a.order_line_id || !/^[1-9][0-9]*$/.test(a.units))) return sourceOrder ? "请选择此订单的商品，并填写本次实际入库件数。" : "请为生产实收选择来源订单并填写分配件数。";
      if (/^[0-9]+$/.test(line.units) && allocations.reduce((sum, a) => sum + BigInt(a.units), 0n) !== BigInt(line.units)) return "订单分配合计必须等于本次件数。";
    }
    if (line.purpose !== "RETURN" || !line.loan_id || !/^[0-9]+$/.test(line.units)) return undefined;
    const loan = loans.value?.items.find(l => display(l.id) === line.loan_id);
    const returning = lines.filter(item => item.loan_id === line.loan_id && /^[1-9][0-9]*$/.test(item.units)).reduce((sum, item) => sum + BigInt(item.units), 0n);
    if (loan && initial?.status !== "POSTED" && returning > BigInt(display(loan.outstanding_units))) return `本次最多归还 ${units(display(loan.outstanding_units))} 件，请核对原借出记录。`;
    return undefined;
  }
  function changeWarehouse(value: string) { setTouched(true); setWarehouse(value); setLines(current => current.map(line => ({ ...line, loan_id: undefined, plan_id: undefined }))); setAssociationNotice("仓库已切换，请重新核对商品及关联记录。"); }
  const intentChoices = { "": "请选择本次操作", IN: "入库", OUT: "取走或消耗", BORROW: "借出（需要归还）", RETURN: "借出归还", ADJUST: "盘点调整", MOVE: "货品状态或库位变更", INSPECT: "待检处理" };
  function changeIntent(value: string) { audit.apply(undefined); setTouched(true); setIntent(value); const nextKind = value === "BORROW" ? "OUT" : value === "RETURN" ? "IN" : value; setKind(nextKind); setLines(current => current.map(line => ({ sku_id: line.sku_id, units: "", quality: "", purpose: value === "BORROW" ? "BORROW" : value === "RETURN" ? "RETURN" : defaultPurpose[nextKind as keyof typeof defaultPurpose], target_quality: "" }))); if (kind) setAssociationNotice("操作已切换，请重新核对数量、货品状态和关联记录。"); }

  const command = useStockCommand(result => {
    if (result.preview_hash) { setCorrectionPreview(result); if (guided) setWizardStep(3); return; }
    if (guided && result.status === "DRAFT") { setWizardDraft(result as unknown as Movement); setTouched(false); setCorrectionPreview(undefined); setWizardStep(3); setAutoPreview(true); return; }
    leave.allowLeave(); if (onSaved) onSaved(display(result.id)); else void navigate(`/production/stock/movements/${display(result.id)}`);
  }, () => setCorrectionPreview(undefined), !guided);
  const leave = useProductionLeave(touched, command.busy || autoPreview || importBusy, command.unknown, preservedSearchParams);
  useEffect(() => { onGuardChange?.({dirty:touched,busy:command.busy || autoPreview,unknown:command.unknown,blocked:leave.blocked}); }, [touched,command.busy,autoPreview,command.unknown,leave.blocked,onGuardChange]);
  useEffect(() => { if (autoPreview && wizardDraft && !command.busy && !command.unknown) { setAutoPreview(false); command.submit(`${base}/documents/${wizardDraft.id}/preview`, { expected_revision: wizardDraft.revision }); } }, [autoPreview, wizardDraft, command]);
  useEffect(() => { if (guided && wizardDraft && !touched && !autoPreview && !command.busy && !command.unknown && urlParams.get("wizard_draft") !== wizardDraft.id) { const next = new URLSearchParams(urlParams); next.set("wizard_draft", wizardDraft.id); setUrlParams(next, { replace: true }); } }, [guided, wizardDraft, touched, autoPreview, command.busy, command.unknown, urlParams, setUrlParams]);

  function update(index: number, key: keyof MovementLine, value: string) { setTouched(true); setCorrectionPreview(undefined); if ((key === "sku_id" || key === "purpose") && (lines[index]?.loan_id || lines[index]?.plan_id || lines[index]?.production_allocations?.length)) setAssociationNotice(sourceOrder ? "商品已切换，来源已更新为当前订单的对应明细；请重新核对本次数量和货品状态。" : "商品或用途已切换，原关联记录已清除；请重新选择适用记录。"); setLines(current => current.map((line, i) => { if (i !== index) return line; if ((qualityWorkflow || guided) && key === "sku_id" && value !== line.sku_id) return { ...line, sku_id: value, units: "", quality: intent === "BORROW" ? "QUALIFIED" : "", target_quality: "", location_from: undefined, location_to: undefined, loan_id: undefined, plan_id: undefined }; if (qualityWorkflow && key === "purpose" && value !== line.purpose) return { ...line, purpose: value, target_quality: value === "LOCATION" ? line.quality : "", location_from: undefined, location_to: undefined, counted_on: undefined, evidence: undefined, loan_id: undefined, plan_id: undefined }; if (qualityWorkflow && key === "quality" && line.purpose !== "LOCATION") return { ...line, quality: value, target_quality: line.target_quality === value ? "" : line.target_quality }; if (sourceOrder && (key === "sku_id" || key === "units")) { const sku = key === "sku_id" ? value : line.sku_id; const amount = key === "units" ? value : line.units; const source = sourceOrder.lines?.find(l => l.sku_id === sku); return { ...line, [key]: value, loan_id: undefined, plan_id: undefined, production_allocations: source ? [{ order_line_id: source.id, units: amount }] : [] }; } if (key === "sku_id") { return { ...line, sku_id: value, loan_id: undefined, plan_id: undefined, production_allocations: line.purpose === "PRODUCTION_RECEIPT" ? [{ order_line_id: "", units: "" }] : undefined }; } if (key === "purpose") { line = { ...line, loan_id: undefined, plan_id: undefined, borrower: undefined, due_on: undefined, production_allocations: value === "PRODUCTION_RECEIPT" ? [{ order_line_id: "", units: "" }] : undefined }; } if (key === "purpose" && value === "LOCATION") return { ...line, purpose: value, target_quality: line.quality }; if (key === "quality" && line.purpose === "LOCATION") return { ...line, quality: value, target_quality: value }; return { ...line, [key]: value }; })); }
  const allowed = sourceOrder ? ["PRODUCTION_RECEIPT"] : inspection ? ["QUALITY"] : intent === "RETURN" ? ["RETURN"] : intent === "BORROW" ? ["BORROW"] : kind === "IN" ? ["RECEIPT", ...(stock.value?.production_receipts_supported ? ["PRODUCTION_RECEIPT"] : []), "OTHER", "SALES_RETURN"] : kind === "OUT" ? ["TAKE", "CONSUME", "GIFT", "SCRAP", "RETURN_SUPPLIER"] : kind === "MOVE" ? ["QUALITY", "LOCATION", "DAMAGE"] : ["COUNT"];
  if (initial) for (const line of initial.lines) if (!allowed.includes(line.purpose)) allowed.push(line.purpose);
  if (!canWrite) return <StatusMessage kind="warning" title="查看人员不能登记库存变动" />;
  const effective = guided ? wizardDraft || initial : initial;
  function saveMovement() { if (importBusy || audit.blocked || !kind || originError || (lockedOrigin && !origin) || lines.some(line => quantityError(line))) return; let auditedReason: string;try{auditedReason=audit.withNote(reason);}catch(e){setAssociationNotice(e instanceof Error?e.message:"原表核对未完成");return;} command.submit(effective ? `${base}/documents/${effective.id}/${effective.status === "POSTED" ? correctionPreview ? "correct" : "preview" : "update"}` : `${base}/documents`, { kind, warehouse_id: warehouse, owner_id: owner, business_date: date, reason:auditedReason, lines: lines.map(line => Object.fromEntries(Object.entries(kind === "ADJUST" ? { ...line, counted_on: guided ? date : line.counted_on || date } : line).filter(([key, value]) => value !== undefined && (!["plan_id", "loan_id"].includes(key) || !!value)))), ...(effective ? { expected_revision: effective.revision } : {}), ...(effective?.status === "POSTED" ? { mode: "correct", ...(correctionPreview ? { preview_hash: correctionPreview.preview_hash } : {}) } : {}) });  }
  function advanceWizard() {
    if (importBusy || audit.blocked || command.busy || command.unknown || !wizardForm.current?.reportValidity()) return;
    if (intent === "RETURN" && (!loans.value || lines.some(line => !scopedLoan(line)))) return;
    if (wizardStep === 1 && !stock.value) return;
    if (wizardStep === 1 && lines.some(line => quantityError(line))) { wizardForm.current.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(); return; }
    if (kind === "ADJUST" && wizardStep === 0 && lines.some(line=>quantityError(line))) return;
    if (wizardStep < 2) setWizardStep(kind === "ADJUST" ? 2 : wizardStep + 1); else saveMovement();
  }
  function closeWizard() {
    if (command.busy || command.unknown || autoPreview) return;
    if (wizardDraft && onSaved) onSaved(wizardDraft.id); else onClose?.();
  }
  function scopedLoan(line: MovementLine) { return loans.value?.items.find(item => display(item.id) === line.loan_id && display(item.sku_id) === line.sku_id && display(item.warehouse_id) === warehouse && display(item.owner_id) === owner && item.is_active !== false && BigInt(display(item.outstanding_units)) > 0n); }
  const countEditor = <><details><summary>其他排版原表</summary><Link to="/production/stock/intake?method=table&layout=raw">打开原表整理与核对</Link></details><p>填写实盘总数，0表示明确没有；空白未填。差额仅供核对，确认前由后台重新计算。</p><CountTableImport warehouse={warehouse} owner={owner} locked={command.busy || command.unknown || autoPreview} onBusy={setImportBusy} onApply={result=>{
    setLines(result.rows.map(line=>({...line,evidence:`表格盘点：${result.filename}`,counted_on:date})));audit.apply(result.table_baseline);setTouched(true);setCorrectionPreview(undefined);if(!reason)setReason(`表格盘点：${result.filename}`);
  }}/><CountTable lines={lines} skus={catalog.value?.items || []} balanceFor={line=>stock.value?.items.find(balance=>balance.state!=="not_ready" && balance.sku_id===line.sku_id && balance.warehouse_id===warehouse && balance.owner_id===owner)} change={update} errorFor={quantityError} add={()=>{setLines(value=>[...value,{sku_id:"",quality:"",units:"",purpose:"COUNT"}]);setTouched(true);setCorrectionPreview(undefined);}} remove={index=>{setLines(value=>value.filter((_,i)=>i!==index));setTouched(true);setCorrectionPreview(undefined);}}/></>;
  const importReview = <TableImportReview baseline={audit.baseline} rows={stockImportRows(kind,lines,id=>catalog.value?.items.find(sku=>sku.sku_id===id)?.label || id)}/>
  if (guided && !qualityWorkflow && canWrite) return <><StockOperationWizard
    mode={kind === "ADJUST" ? "count" : intent === "RETURN" ? "return" : "borrow"}
    countEditor={countEditor} importReview={importReview} step={wizardStep} lines={lines} skus={catalog.value?.items || []}
    balanceFor={line => stock.value?.items.find(item => item.sku_id === line.sku_id && item.warehouse_id === warehouse && item.owner_id === owner)}
    loanFor={line => { const loan = scopedLoan(line); return loan ? { id: display(loan.id), borrower: display(loan.borrower), outstanding_units: display(loan.outstanding_units) } : undefined; }}
    scopeLabel={`${stock.value?.scopes.find(scope => scope.warehouse_id === warehouse)?.warehouse_name || `仓库 ${warehouse}`} · ${stock.value?.scopes.find(scope => scope.warehouse_id === warehouse && (!scope.owner_id || scope.owner_id === owner))?.owner_name || `货主 ${owner}`}`}
    inventoryState={stock.error ? "error" : stock.value ? "ready" : "loading"} refreshInventory={() => { setCorrectionPreview(undefined); setStockRefresh(value => value + 1); }}
    loansReady={!!loans.value && !loans.error} loansValid={!!loans.value && !loans.error && (intent !== "RETURN" || lines.every(line => !!scopedLoan(line)))}
    date={date} reason={reason} dirty={touched} draftId={wizardDraft?.id} preview={correctionPreview as unknown as QualityPreview | undefined}
    busy={command.busy || autoPreview || importBusy} unknown={command.unknown} feedback={<>{audit.feedback}{command.feedback}{originError && <StatusMessage kind="danger" title={originError} />}{catalog.error && <ReadState error={catalog.error} />}{stock.error && <ReadState error={stock.error} />}{loans.error && <ReadState error={loans.error} />}</>}
    formRef={wizardForm} quantityError={quantityError} change={update}
    changeDate={value => { setDate(value); setTouched(true); setCorrectionPreview(undefined); }} changeReason={value => { setReason(value); setTouched(true); setCorrectionPreview(undefined); }}
    add={() => { setLines(value => [...value, { sku_id: "", units: "", quality: intent === "BORROW" ? "QUALIFIED" : "", purpose: kind === "ADJUST" ? "COUNT" : "BORROW" }]); setTouched(true); setCorrectionPreview(undefined); }}
    remove={index => { setLines(value => value.filter((_, i) => i !== index)); setTouched(true); setCorrectionPreview(undefined); }}
    go={step => { if (!command.busy && !command.unknown && step <= wizardStep) setWizardStep(step); }} advance={advanceWizard} close={closeWizard}
    previewAgain={() => { if (wizardDraft && !touched) command.submit(`${base}/documents/${wizardDraft.id}/preview`, { expected_revision: wizardDraft.revision }); }}
    confirm={() => { if (wizardDraft && correctionPreview && !touched) command.submit(`${base}/documents/${wizardDraft.id}/confirm`, { expected_revision: wizardDraft.revision, preview_hash: correctionPreview.preview_hash }); }}
  />{leave.prompt}</>;
  if (guided && qualityWorkflow && canWrite) return <><QualityMovementWizard
    step={wizardStep} lines={lines} skus={catalog.value?.items || []} balances={stock.value?.items || []}
    inventoryState={stock.error ? "error" : stock.value ? "ready" : "loading"} refreshInventory={() => { setCorrectionPreview(undefined); setStockRefresh(value => value + 1); }}
    warehouse={warehouse} warehouseName={stock.value?.scopes.find(scope => scope.warehouse_id === warehouse)?.warehouse_name || `仓库 ${warehouse}`}
    owner={owner} ownerName={stock.value?.scopes.find(scope => scope.warehouse_id === warehouse && (!scope.owner_id || scope.owner_id === owner))?.owner_name || `货主 ${owner}`}
    date={date} reason={reason} dirty={touched} draftId={wizardDraft?.id} preview={correctionPreview as unknown as QualityPreview | undefined}
    busy={command.busy || autoPreview} unknown={command.unknown} feedback={<>{command.feedback}{catalog.error && <ReadState error={catalog.error} />}{stock.error && <ReadState error={stock.error} />}</>}
    formRef={wizardForm} lineError={lineError} quantityError={quantityError} change={update}
    changeDate={value => { setDate(value); setTouched(true); setCorrectionPreview(undefined); }}
    changeReason={value => { setReason(value); setTouched(true); setCorrectionPreview(undefined); }}
    add={() => { setLines(value => [...value, { sku_id: "", units: "", quality: "", purpose: "QUALITY", target_quality: "" }]); setTouched(true); setCorrectionPreview(undefined); }}
    remove={index => { setLines(value => value.filter((_, i) => i !== index)); setTouched(true); setCorrectionPreview(undefined); }}
    go={step => { if (!command.busy && !command.unknown && step <= wizardStep) setWizardStep(step); }}
    advance={advanceWizard} close={closeWizard}
    previewAgain={() => { if (wizardDraft && !touched) command.submit(`${base}/documents/${wizardDraft.id}/preview`, { expected_revision: wizardDraft.revision }); }}
    confirm={() => { if (wizardDraft && correctionPreview && !touched) command.submit(`${base}/documents/${wizardDraft.id}/confirm`, { expected_revision: wizardDraft.revision, preview_hash: correctionPreview.preview_hash }); }}
  />{leave.prompt}</>;
  return <><PageHeader title={sourceOrder ? "从订单登记生产实收" : initial ? `${initial.status === "POSTED" ? "更正" : "编辑"}库存单${initial.id}` : qualityWorkflow ? "登记质量或位置变化" : intent ? `登记${intentChoices[intent as keyof typeof intentChoices]}` : "登记库存业务"} description={sourceOrder ? "从此订单选择本次到仓规格，填写实际数量和货品状态，再预览确认。" : inspection ? "登记实际检验完成的数量，明确转为合格或次品；不增加或减少仓内实物总数。" : qualityWorkflow ? "选择商品，填写实际变化与数量，保存草稿后核对库存影响，再确认生效。" : "先选择实际发生的业务，再填写商品与数量。保存草稿后核对库存变化，再确认生效。"} />{sourceOrder && <section className={styles.panel}><h2>本次来源订单</h2><p><Link to={`/production/orders/${sourceOrder.id}`}>{sourceOrder.business_number || sourceOrder.system_number}</Link></p><p hidden>仅从此订单选择商品；本次件数将等量关联该订单，无需重复填写分配量。仓库、货品状态和实际数量请按本次到仓核对，不从预计量或差额自动生成。</p></section>}<form className={[styles.body, (qualityWorkflow || kind === "ADJUST") && styles.qualityEditor].filter(Boolean).join(" ")} onChangeCapture={() => setCorrectionPreview(undefined)} onSubmit={e => { e.preventDefault(); saveMovement(); }}><fieldset disabled={command.busy || command.unknown || importBusy}>{qualityWorkflow ? <div className={styles.movementScope}><strong>{stock.value?.scopes.find(scope => scope.warehouse_id === warehouse)?.warehouse_name || `仓库 ${warehouse}`}</strong><span>{stock.value?.scopes.find(scope => scope.warehouse_id === warehouse && (!scope.owner_id || scope.owner_id === owner))?.owner_name || `货主 ${owner}`} · 同仓处理，实物总数不变</span></div> : <p role="note">当前仓库编号 {warehouse} · 货权编号 {owner}（沿原单或入口上下文）。带 * 的字段必填；已有默认值也请核对。其余字段可留空，草稿和预览都不会改变实际库存。</p>}{!(qualityWorkflow && (initial || context)) && <>{initial || lockedOrigin || sourceOrder || inspection || context ? <div className={styles.filters}><Select markRequired label="本次操作" value={intent} choices={{ [intent]: sourceOrder ? "生产实收入库（关联订单）" : intentChoices[intent as keyof typeof intentChoices] || kinds[kind]! }} disabled onChange={changeIntent} /></div> : <fieldset className={styles.intentPicker}><legend>本次操作 *</legend><div className={styles.intentGroups}>{intentGroups.map(group => <section key={group.label}><h2>{group.label}</h2><div>{group.items.map(([value, label, description]) => <Button key={value} variant={intent === value ? "primary" : "secondary"} aria-pressed={intent === value} className={styles.intentChoice} onClick={() => changeIntent(value)}><span><strong>{label}</strong><small>{description}</small></span></Button>)}</div></section>)}</div></fieldset>}</>}{kind && !qualityWorkflow && <div className={styles.filters}><WarehouseSelect markRequired disabled={!!initial || lockedOrigin || !!context} value={warehouse} onDefault={setWarehouse} onChange={changeWarehouse} /><FormField label="实际发生日期" required><Input required type="date" value={date} onChange={e => { setTouched(true); setDate(e.target.value); }} /></FormField><FormField label="来源依据/更正原因" required><Input required value={reason} onChange={e => { setTouched(true); setReason(e.target.value); }} /></FormField></div>}
    {associationNotice && <p role="status">{associationNotice}</p>}{originError && <StatusMessage kind="danger" title={originError} />}{lockedOrigin && !origin && <StatusMessage kind="warning" title="正在核对关联记录">{loans.error || plans.error || (loans.value && plans.value ? "关联记录不存在，请返回原记录重新进入。" : "读取完成后才能保存。")}</StatusMessage>}
    {kind && <>{kind === "ADJUST" ? <>{countEditor}<Table aria-label="盘点日期与证据"><thead><tr><th>商品</th><th>实盘截止</th><th>盘点证据</th></tr></thead><tbody>{lines.map((line,index)=><tr key={index}><td>{catalog.value?.items.find(sku=>sku.sku_id===line.sku_id)?.label || "商品待选"}</td><td><Input required type="date" aria-label={`盘点商品${index+1}截止日期`} value={line.counted_on || date} onChange={event=>update(index,"counted_on",event.target.value)}/></td><td><Input required aria-label={`盘点商品${index+1}证据`} maxLength={2000} value={line.evidence || ""} onChange={event=>update(index,"evidence",event.target.value)}/></td></tr>)}</tbody></Table></> : lines.map((line, index) => <section key={index} className={styles.panel} aria-label={`变动明细${index + 1}`}><h2>{qualityWorkflow ? "商品处理 " : "明细"}{index + 1}</h2>{qualityWorkflow && ["QUALITY", "LOCATION", "DAMAGE"].includes(line.purpose) ? <QualityMovementFields inventoryState={stock.error ? "error" : stock.value ? "ready" : "loading"} line={line} skus={catalog.value?.items || []} locked={lockedOrigin || (!!initial && !!(line.plan_id || line.loan_id))} error={lineError(line)} quantityError={quantityError(line)} balance={stock.value?.items.find(balance => balance.sku_id === line.sku_id && balance.warehouse_id === warehouse && balance.owner_id === owner)} onChange={(key, value) => update(index, key, value)} /> : <div className={styles.filters}><MovementSkuSelect value={line.sku_id} skus={(catalog.value?.items || []).filter(sku => !sourceOrder || sourceOrder.lines?.some(l => l.sku_id === sku.sku_id))} locked={lockedOrigin || (!!initial && !!(line.plan_id || line.loan_id))} error={lineError(line)} onChange={v => update(index, "sku_id", v)} />{allowed.length > 1 && <Select markRequired label="用途" value={line.purpose} choices={Object.fromEntries(allowed.map(v => [v, purposes[v]!]))} disabled={lockedOrigin} onChange={v => update(index, "purpose", v)} />}<Select markRequired label={inspection ? "来源货品状态" : "货品状态"} disabled={inspection} value={line.quality} choices={{ "": "请核对实际货品状态", ...qualities }} onChange={v => update(index, "quality", v)} /><NumberField markRequired label={kind === "ADJUST" ? "实际盘点件数" : "本次件数"} hint={kind === "ADJUST" ? "填写该状态下的实盘总数，可填0；不要填写增减差额。" : undefined} error={quantityError(line)} allowZero={kind === "ADJUST"} value={line.units} onChange={v => update(index, "units", v)} />
      {(kind === "IN" || kind === "OUT") && line.purpose !== "BORROW" && <FormField label="来源/实际领用对象（可选）"><Input value={line.counterparty || ""} onChange={e => update(index, "counterparty", e.target.value)} /></FormField>}{line.purpose === "BORROW" && <><FormField label="实际借用人/对象" required><Input required value={line.borrower || ""} onChange={e => update(index, "borrower", e.target.value)} /></FormField><FormField label="借用用途（可选）"><Input value={line.borrow_purpose || ""} onChange={e => update(index, "borrow_purpose", e.target.value)} /></FormField><FormField label="约定归还日期（可仍未知）"><Input type="date" value={line.due_on || ""} onChange={e => update(index, "due_on", e.target.value)} /></FormField></>}
      {line.purpose === "PRODUCTION_RECEIPT" && !sourceOrder && <ProductionReceiptAllocations key={line.sku_id} sku={line.sku_id} allocations={line.production_allocations || []} onChange={value => { setTouched(true); setCorrectionPreview(undefined); setLines(current => current.map((item, i) => i === index ? { ...item, production_allocations: value } : item)); }} />}
      {line.purpose === "RETURN" && <FormField label="原借出记录" required><select required disabled={lockedOrigin} value={line.loan_id || ""} onChange={e => update(index, "loan_id", e.target.value)}><option value="">选择同商品、同仓库的未还借出</option>{loans.value?.items.filter(loan => display(loan.sku_id) === line.sku_id && display(loan.warehouse_id) === warehouse && display(loan.owner_id) === owner && (BigInt(display(loan.outstanding_units)) > 0n || display(loan.id) === line.loan_id)).map(loan => <option key={display(loan.id)} value={display(loan.id)}>{display(loan.borrower)} · {display(loan.purpose)} · 待归还{display(loan.outstanding_units)}件 · {display(loan.due_on || "日期待安排")}</option>)}</select></FormField>}
      {kind === "MOVE" && <><Select markRequired label={inspection ? "检验结果" : "目标货品状态"} disabled={line.purpose === "LOCATION"} value={line.target_quality || ""} choices={inspection ? { "": "请选择检验结果", QUALIFIED: "合格", DEFECTIVE: "次品" } : { "": "请选择变更后的状态", ...qualities }} onChange={v => update(index, "target_quality", v)} />{!inspection && <><FormField label="来源库位" required={(line.target_quality || "PENDING") === line.quality} hint="同一货品状态仅换库位时，来源与目标库位都必填且须不同；不用于跨仓调拨。"><Input required={(line.target_quality || "PENDING") === line.quality} value={line.location_from || ""} onChange={e => update(index, "location_from", e.target.value)} /></FormField><FormField label="目标库位" required={(line.target_quality || "PENDING") === line.quality}><Input required={(line.target_quality || "PENDING") === line.quality} value={line.location_to || ""} onChange={e => update(index, "location_to", e.target.value)} /></FormField></>}</>}
      {(kind === "ADJUST" || line.purpose === "DAMAGE") && <><FormField label="实盘截止日期" required><Input required type="date" value={line.counted_on || ""} onChange={e => update(index, "counted_on", e.target.value)} /></FormField><FormField label="盘点/损坏证据" required><Input required value={line.evidence || ""} onChange={e => update(index, "evidence", e.target.value)} /></FormField></>}
      {(kind === "IN" || kind === "OUT") && line.purpose !== "RETURN" && <FormField label="关联收发安排（可选）"><select disabled={lockedOrigin} value={line.plan_id || ""} onChange={e => update(index, "plan_id", e.target.value)}><option value="">不关联安排，按独立实际事实登记</option>{plans.value?.items.filter(plan => !plan.loan_id && display(plan.direction) === kind && display(plan.warehouse_id) === warehouse && display(plan.owner_id) === owner && display(plan.sku_id) === line.sku_id && (BigInt(display(plan.remaining_units)) > 0n || display(plan.id) === line.plan_id)).map(plan => <option key={display(plan.id)} value={display(plan.id)}>{display(plan.source_reference)} · {display(plan.planned_on || "日期待安排")} · 剩余{display(plan.remaining_units)}件</option>)}</select></FormField>}
    </div>}{inspection && <p role="note">当前待检 {quantity(stock.value?.items.find(b => b.sku_id === line.sku_id && b.warehouse_id === warehouse && b.owner_id === owner)?.pending_units)} 件。这是此商品在当前仓库的待检总余额，不是本次入库批次的剩余量；来源入库记录不随检验改写。</p>}{lines.length > 1 && <Button variant="quiet" onClick={() => { setTouched(true); setCorrectionPreview(undefined); setLines(current => current.filter((_, i) => i !== index)); }}>移除此行</Button>}</section>)}
    {qualityWorkflow && <section className={styles.panel} aria-label="发生时间与依据"><h2>发生时间与依据</h2><div className={styles.filters}>{!context && !initial && <WarehouseSelect markRequired value={warehouse} onDefault={setWarehouse} onChange={changeWarehouse} />}<FormField label="实际发生日期" required><Input required type="date" value={date} onChange={event => { setTouched(true); setDate(event.target.value); }} /></FormField><FormField label="来源依据/更正原因" required><Input required value={reason} placeholder="例如：检验记录、复核说明或移库记录" onChange={event => { setTouched(true); setReason(event.target.value); }} /></FormField></div><p className={styles.movementHint}>保存草稿不改变库存。保存后预览本次变化，核对无误再确认。</p></section>}
    {correctionPreview && <><ProductionReceiptPreview sources={correctionPreview.production_sources as ProductionReceiptSource[] | undefined} /><StockImpact impacts={correctionPreview.impacts as StockImpacts | undefined} skuName={id => catalog.value?.items.find(s => s.sku_id === id)?.label || `SKU ${id}`} warehouseName={id => stock.value?.scopes.find(s => s.warehouse_id === id)?.warehouse_name || `仓库 ${id}`} /><StatusMessage kind="info" title="更正预览完成，尚未改变库存">确认后保存下列净变化；当前数量在确认前一直有效。修改输入需重新预览。</StatusMessage><Table title="更正净变化（尚未保存）"><thead><tr><th>商品颜色与尺码</th><th>货品状态</th><th>库存增减件数</th></tr></thead><tbody>{(correctionPreview.changes as { sku_id: string; quality: string; delta_units: string }[]).map((change, index) => <tr key={index}><td>{catalog.value?.items.find(sku => sku.sku_id === change.sku_id)?.label || change.sku_id}</td><td>{qualities[change.quality]}</td><td>{BigInt(change.delta_units) > 0n ? "+" : ""}{units(change.delta_units)}</td></tr>)}</tbody></Table></>}
    {kind==="ADJUST" && <details><summary>核对原表修改</summary>{importReview}</details>}{audit.feedback}<div className={styles.actions}>{!lockedOrigin && kind !== "ADJUST" && <Button variant="secondary" onClick={() => { setTouched(true); setCorrectionPreview(undefined); setLines(current => [...current, { sku_id: "", units: "", quality: inspection ? "PENDING" : params.get("intent") === "BORROW" ? "QUALIFIED" : "", purpose: sourceOrder ? "PRODUCTION_RECEIPT" : inspection ? "QUALITY" : intent === "BORROW" ? "BORROW" : intent === "RETURN" ? "RETURN" : defaultPurpose[kind as keyof typeof defaultPurpose], target_quality: "" }]); }}>增加明细</Button>}<Button disabled={!!originError || (lockedOrigin && !origin) || (inspection && !stock.value)} type="submit">{initial?.status === "POSTED" ? correctionPreview ? "确认库存更正" : "预览库存更正" : "保存库存草稿"}</Button></div></>}</fieldset></form>{inspection && stock.error && <ReadState error={stock.error} />}{catalog.error && <ReadState error={catalog.error} />}{command.feedback}{leave.prompt}</>;
}
function MovementDetail({ canWrite, edit = false }: { canWrite: boolean; edit?: boolean }) {
  const { id } = useParams(); const [refresh, setRefresh] = useState(0); const { value, error } = useRead<Movement>(`${base}/documents/${id}`, refresh);
  if (!value) return <ReadState error={error} />; return edit ? <MovementEditor key={value.revision} initial={value} canWrite={canWrite} /> : <MovementDetails value={value} canWrite={canWrite} onRefresh={() => setRefresh(v => v + 1)} />;
}
function MovementDetails({ value, canWrite, onRefresh, onEdit, embedded = false, preservedSearchParams, onGuardChange }: { value: Movement; canWrite: boolean; onRefresh: () => void; onEdit?: () => void; embedded?: boolean; preservedSearchParams?: readonly string[]; onGuardChange?: (guard: OverviewGuard) => void }) {
  const labels = useStockLabels();
  const [preview, setPreview] = useState<RecordValue>();
  const [reason, setReason] = useState("");
  const [reverseOpen, setReverseOpen] = useState(false);
  const actionTarget = useRef<HTMLDivElement>(null);
  const command = useStockCommand(result => {
    if (result.preview_hash) setPreview(result);
    else {
      setPreview(undefined);
      setReason("");
      setReverseOpen(false);
      onRefresh();
    }
  }, () => setPreview(undefined), embedded);
  const leave = useProductionLeave(!!reason, command.busy, command.unknown, preservedSearchParams);
  useEffect(() => { onGuardChange?.({dirty:!!reason,busy:command.busy,unknown:command.unknown,blocked:leave.blocked}); }, [reason,command.busy,command.unknown,leave.blocked,onGuardChange]);
  if (embedded && (value.kind === "IN" || value.kind === "OUT")) {
    const incoming = value.kind === "IN";
    const draft = value.status === "DRAFT";
    const rows = [...new Set(value.lines.map(line => line.sku_id))].map(sku => ({ sku, variant: labels.variant(sku), lines: value.lines.filter(line => line.sku_id === sku) }));
    const pending = value.lines.filter(line => line.quality === "PENDING").reduce((sum, line) => sum + BigInt(line.units), 0n);
    return <div className={warehouseStyles.movementReview}>
      <header className={warehouseStyles.reviewHeading}><h2>{draft ? `核对${incoming ? "入库" : "出库"}草稿` : incoming ? "入库记录详情" : "出库记录详情"}</h2><span>单号：库存单 {value.id}<WarehouseRecordStatus status={value.status} kind={value.kind} /></span></header>
      <WarehouseRecordSteps status={value.status} preview={!!preview} outbound={!incoming} />
      <div className={warehouseStyles.recordContext}><span>{value.business_date} · {labels.warehouse(value.warehouse_id)} · 修订 {value.revision}</span>{value.production_sources?.length ? <p>入库来源：{[...new Map(value.production_sources.map(source => [source.order_id || source.order_line_id, source])).values()].map(source => <Link key={source.order_id || source.order_line_id} to={`/production/orders/${source.order_id}`}>{source.order_business_number || source.order_number || `订单行 ${source.order_line_id}`}</Link>)}</p> : <p>{incoming ? "入库来源" : "实际领用对象"}：{[...new Set(value.lines.map(line => line.counterparty).filter(Boolean))].join("、") || "见下方依据"}</p>}</div>
      <section><h3>商品明细（{rows.length}）</h3><Table aria-label="收发商品明细"><thead><tr><th>款号</th><th>颜色</th><th>尺码</th><th>合格</th><th>待检</th><th>次品</th><th>{incoming ? "本次实收" : "本次出库"}</th></tr></thead><tbody>{rows.map(row => <tr key={row.sku}><th scope="row">{row.variant?.style_code || `SKU ${row.sku}`}</th><td>{row.variant?.standard_color || "待核"}</td><td>{row.variant?.standard_size || "待核"}</td>{["QUALIFIED", "PENDING", "DEFECTIVE"].map(quality => <td key={quality}>{units(row.lines.filter(line => line.quality === quality).reduce((sum, line) => sum + BigInt(line.units), 0n).toString())}</td>)}<td>{units(row.lines.reduce((sum, line) => sum + BigInt(line.units), 0n).toString())}</td></tr>)}</tbody></Table></section>
      {preview && <StockImpact compact impacts={preview.impacts as StockImpacts | undefined} skuName={labels.sku} warehouseName={labels.warehouse} />}
      <StatusMessage kind={value.status === "REVERSED" ? "danger" : draft ? "warning" : "success"} title={value.status === "REVERSED" ? "原记录已冲销，历史保留" : draft ? incoming ? "草稿尚未入库" : "草稿尚未出库" : incoming ? "已入库，库存与来源记录已保存" : "已出库，库存与历史已保存"}>{draft ? preview ? "请核对以上库存变化。" : "预览库存变化后再确认。" : "可在操作历史中核对这笔记录。"}{incoming && pending > 0n && (draft ? ` 待检 ${units(pending.toString())} 件不计入当前可发。` : ` 本单登记待检 ${units(pending.toString())} 件，后续检验见实时库存。`)}</StatusMessage>
      <MovementImportReview value={value} label={id=>labels.sku(id)}/><details className={warehouseStyles.recordEvidence}><summary>{incoming ? "入库" : "出库"}依据与备注</summary><p>{withoutTableBaseline(value.reason)}</p>{value.lines.map((line, index) => <p key={index}>{labels.sku(line.sku_id)} · {purposes[line.purpose] || line.purpose} · {units(line.units)} 件</p>)}</details>
      {canWrite && value.status !== "REVERSED" && <div className={warehouseStyles.reviewActions}>{draft && incoming && value.production_sources?.length && value.production_sources.every(source => source.order_id && source.order_id === value.production_sources?.[0]?.order_id) ? <LinkButton variant="secondary" to={`/production/warehouses/${value.warehouse_id}?${new URLSearchParams({ owner: value.owner_id, tab: "records", mode: "receive", receive: "1", source_order: value.production_sources[0]!.order_id!, receipt_draft: value.id })}`}>继续分步编辑入库草稿</LinkButton> : <Button variant="secondary" disabled={command.busy || command.unknown} onClick={onEdit}>{draft ? "返回编辑" : "更正录入错误"}</Button>}{draft && <Button variant="primary" disabled={command.busy || command.unknown} onClick={() => command.submit(`${base}/documents/${value.id}/${preview ? "confirm" : "preview"}`, { expected_revision: value.revision, ...(preview ? { preview_hash: preview.preview_hash } : {}) })}>{preview ? incoming ? "确认入库" : "确认出库" : "预览库存影响"}</Button>}</div>}
      {canWrite && value.status === "POSTED" && <details className={warehouseStyles.recordEvidence}><summary>原记录有误，需要冲销</summary><form onSubmit={event => { event.preventDefault(); command.submit(`${base}/documents/${value.id}/reverse`, { expected_revision: value.revision, reason }); }}><FormField label="冲销录入错误的原因（实物退回请另登记入库）"><Input required disabled={command.busy || command.unknown} value={reason} onChange={event => setReason(event.target.value)} /></FormField><Button variant="secondary" disabled={command.busy || command.unknown} type="submit">确认原记录错误并冲销</Button></form></details>}
      {!preview && command.feedback}<Link to="/production/stock/history">查看操作人与变更历史</Link>{leave.prompt}
    </div>;
  }
  const draft = value.status === "DRAFT";
  const total = value.lines.reduce((sum, line) => sum + BigInt(line.units), 0n);
  const quantityLabel = value.status === "REVERSED" ? "原记录数量" : { IN: "本次入库", OUT: "本次出库", MOVE: "变更数量", ADJUST: "实盘数量" }[value.kind] || "本次数量";
  const editAction = canWrite && value.status === "POSTED" ? {
    id: "edit", label: "更正录入错误", disabled: command.busy || command.unknown,
    ...(onEdit ? { onSelect: onEdit } : { href: `/production/stock/movements/${value.id}/edit` }),
  } : undefined;
  return <article className={recordStyles.page}>
    <PageHeader title={`${kinds[value.kind]}记录 #${value.id}`} actions={<div ref={actionTarget} className={recordStyles.actions} tabIndex={-1}>
      {!embedded && <LinkButton variant="secondary" to="/production/stock/movements">返回库存记录</LinkButton>}
      <Menu label="更多" items={[
        ...(editAction ? [editAction] : []),
        { id: "history", label: "查看操作历史", href: "/production/stock/history", disabled: command.busy || command.unknown },
        ...(canWrite && value.status === "POSTED" ? [{ id: "reverse", label: "冲销错误记录", danger: true, disabled: command.busy || command.unknown, onSelect: () => setReverseOpen(true) }] : []),
      ]} />
    </div>} />
    <div className={recordStyles.meta}>
      <WarehouseRecordStatus status={value.status} kind={value.kind} />
      <span>{value.business_date}</span><span>{labels.warehouse(value.warehouse_id)}</span>
      <span>{new Set(value.lines.map(line => line.sku_id)).size} 个规格</span>
      <span className={recordStyles.total}>{quantityLabel}<strong>{units(total.toString())}</strong>件</span>
    </div>
    {draft && <StatusMessage kind="info" title="草稿，不影响库存">核对商品和数量，预览后确认。</StatusMessage>}
    {value.status === "REVERSED" && <StatusMessage kind="warning" title="原记录已冲销，历史保留" />}
    <Table className={recordStyles.lines} aria-label="库存商品明细">
      <thead><tr><th>商品规格</th><th>数量</th><th>货品状态与用途</th><th>来源与关联</th></tr></thead>
      <tbody>{value.lines.map((line, index) => {
        const variant = labels.variant(line.sku_id);
        return <tr key={index}>
          <td><div className={recordStyles.product}><strong>{variant?.code || labels.sku(line.sku_id)}</strong>{variant?.style_code && <span className={recordStyles.secondary}>款号 {variant.style_code}</span>}</div></td>
          <td>{units(line.units)}</td>
          <td><div className={recordStyles.product}><span>{qualityNames[line.quality]}{line.target_quality ? ` → ${qualityNames[line.target_quality]}` : ""}</span><span className={recordStyles.secondary}>{line.purpose === "PRODUCTION_RECEIPT" ? "生产入库" : purposes[line.purpose]}</span>
            {canWrite && value.status === "POSTED" && value.kind === "IN" && value.owner_id === "1" && line.quality === "PENDING" && <LinkButton variant="quiet" to={`/production/stock/movements/new?intent=INSPECT&sku_id=${line.sku_id}&warehouse_id=${value.warehouse_id}`}>处理此商品待检库存</LinkButton>}
          </div></td>
          <td><div className={recordStyles.association}>
            {line.borrower && <span>{line.borrower}</span>}
            {line.counterparty && <span>{line.counterparty}</span>}
            {line.loan_id && <span>借出 #{line.loan_id}</span>}{line.plan_id && <span>安排 #{line.plan_id}</span>}
            {line.production_allocations?.map(allocation => {
              const source = value.production_sources?.find(item => item.order_line_id === allocation.order_line_id);
              const reference = source?.order_business_number || source?.order_number;
              return source?.order_id ? <Link key={allocation.order_line_id} to={`/production/orders/${source.order_id}`} title={reference}>订单 #{source.order_id}{" "}<span>{units(allocation.units)} 件</span></Link> : <span key={allocation.order_line_id}>来源订单行 {allocation.order_line_id} · {units(allocation.units)} 件</span>;
            })}
            {!line.borrower && !line.counterparty && !line.loan_id && !line.plan_id && !line.production_allocations?.length && <span className={recordStyles.secondary}>—</span>}
          </div></td>
        </tr>;
      })}</tbody>
    </Table>
    <details className={recordStyles.evidence}>
      <summary>依据与记录信息<span>修订 {value.revision}</span><ChevronDown aria-hidden="true" size={16} /></summary>
      <p>{withoutTableBaseline(value.reason)}</p><MovementImportReview value={value} label={labels.sku} />
      {value.lines.map((line, index) => (line.location_from || line.location_to || line.evidence) && <p key={index}>{labels.sku(line.sku_id)}{line.location_from && ` · 来源库位 ${line.location_from}`}{line.location_to && ` · 目标库位 ${line.location_to}`}{line.evidence && ` · ${line.evidence}`}</p>)}
    </details>
    {canWrite && draft && <div className={recordStyles.actions}>
      {onEdit ? <Button variant="secondary" disabled={command.busy || command.unknown} onClick={onEdit}>编辑草稿</Button> : <LinkButton variant="secondary" to={`/production/stock/movements/${value.id}/edit`} aria-disabled={command.busy || command.unknown} onClick={event => { if (command.busy || command.unknown) event.preventDefault(); }}>编辑草稿</LinkButton>}
      {!preview && <Button variant="primary" disabled={command.busy || command.unknown} onClick={() => command.submit(`${base}/documents/${value.id}/preview`, { expected_revision: value.revision })}>预览库存影响</Button>}
    </div>}
    {preview && <>
      {embedded && <div role="status" aria-label="库存确认步骤">草稿 → 预览 → 确认（尚未过账）</div>}
      <ProductionReceiptPreview sources={preview.production_sources as ProductionReceiptSource[] | undefined} />
      <StockImpact impacts={preview.impacts as StockImpacts | undefined} skuName={labels.sku} warehouseName={labels.warehouse} />
      <details className={recordStyles.evidence}><summary>货品状态增减明细<ChevronDown aria-hidden="true" size={16} /></summary><Table aria-label="服务端预览（尚未过账）"><thead><tr><th>商品规格</th><th>货品状态</th><th>增减数量</th></tr></thead><tbody>{(preview.changes as { sku_id: string; quality: string; delta_units: string }[]).map((change, index) => <tr key={index}><td>{labels.sku(change.sku_id)}</td><td>{qualityNames[change.quality]}</td><td>{units(change.delta_units)}</td></tr>)}</tbody></Table></details>
      {canWrite && draft && <div className={recordStyles.actions}><Button variant="primary" disabled={command.busy || command.unknown} onClick={() => command.submit(`${base}/documents/${value.id}/confirm`, { expected_revision: value.revision, preview_hash: preview.preview_hash })}>{value.lines.length === 1 && value.kind !== "ADJUST" ? `确认${purposes[value.lines[0]!.purpose]} ${units(value.lines[0]!.units)} 件` : `确认${kinds[value.kind]}（${value.lines.length}项）`}</Button></div>}
    </>}
    {!reverseOpen && command.feedback}
    <Dialog open={reverseOpen} title="冲销错误记录" description={`库存单 ${value.id} · ${labels.warehouse(value.warehouse_id)}`} dismissDisabled={command.busy || command.unknown} returnFocusTarget={actionTarget} onOpenChange={open => { setReverseOpen(open); if (!open) setReason(""); }}>
      <form className={recordStyles.reverseForm} onSubmit={event => { event.preventDefault(); command.submit(`${base}/documents/${value.id}/reverse`, { expected_revision: value.revision, reason }); }}>
        <p>用于撤回录入错误的库存变动，原单和操作历史会保留。实物退回请另登记入库。</p>
        <FormField label="冲销原因" required><Input required disabled={command.busy || command.unknown} value={reason} onChange={event => setReason(event.target.value)} /></FormField>
        {command.feedback}
        <div className={recordStyles.actions}><Button variant="secondary" disabled={command.busy || command.unknown} onClick={() => { setReverseOpen(false); setReason(""); }}>取消</Button><Button variant="danger" disabled={command.busy || command.unknown || !reason.trim()} type="submit">确认冲销</Button></div>
      </form>
    </Dialog>
    {leave.prompt}
  </article>;
}
// Reuse the full workspace's service commands and leave guard inside the warehouse view.
export function WarehouseMovement({ id, context, canWrite, refresh, saved, editing = false, edit, close, inline = false, preservedSearchParams, onGuardChange }: { id?: string; context: WarehouseMovementContext; canWrite: boolean; refresh: number; saved: (id: string) => void; editing?: boolean; edit: () => void; close?: () => void; inline?: boolean; preservedSearchParams?: readonly string[]; onGuardChange?: (guard: OverviewGuard) => void }) {
  const [params] = useSearchParams();
  const [resumeId] = useState(() => !id ? params.get("wizard_draft") || undefined : undefined);
  const lookup = id || resumeId;
  const document = useRead<Movement>(`${base}/documents/${lookup}`, refresh, !!lookup);
  if (lookup && !document.value) return <ReadState error={document.error} />;
  if (resumeId && document.value && (document.value.kind !== context.kind || document.value.lines.some(line => context.intent === "BORROW" ? line.purpose !== "BORROW" : context.intent === "RETURN" ? line.purpose !== "RETURN" : context.kind === "ADJUST" ? line.purpose !== "COUNT" : !["QUALITY", "LOCATION", "DAMAGE"].includes(line.purpose)))) return <StatusMessage kind="danger" title="此草稿不属于当前操作类型" />;
  if (document.value && (document.value.warehouse_id !== context.warehouse_id || document.value.owner_id !== context.owner_id)) return <StatusMessage kind="danger" title="单据不属于当前仓库及货主">请返回原记录核对；未开放此处的预览或确认。</StatusMessage>;
  if (resumeId && document.value && document.value.status !== "DRAFT") return <MovementDetails value={document.value} canWrite={canWrite} embedded preservedSearchParams={preservedSearchParams} onGuardChange={onGuardChange} onRefresh={() => saved(resumeId)} />;
  return !id || editing ? <MovementEditor key={`${lookup || "new"}:${document.value?.revision || ""}:${JSON.stringify(context)}`} initial={document.value} canWrite={canWrite} context={context} onSaved={saved} preservedSearchParams={preservedSearchParams} onGuardChange={onGuardChange} wizard={!inline && (context.kind === "MOVE" || context.kind === "ADJUST" || ["BORROW", "RETURN"].includes(context.intent))} onClose={close} /> : <MovementDetails key={`${id}:${document.value!.revision}`} value={document.value!} canWrite={canWrite} embedded preservedSearchParams={preservedSearchParams} onGuardChange={onGuardChange} onEdit={edit} onRefresh={() => saved(id)} />;
}
function Loans({ canWrite, preservedSearchParams, onGuardChange, context, onReturn, onBorrow }: { canWrite: boolean; context?: OverviewAction; onReturn?: (loan: RecordValue) => void; onBorrow?: () => void; preservedSearchParams?: readonly string[]; onGuardChange?: (guard: OverviewGuard) => void }) {
  const labels = useStockLabels(); const [refresh, setRefresh] = useState(0); const { value, error } = useRead<Items<RecordValue>>(`${base}/loans`, refresh); const [selected, setSelected] = useState<RecordValue>(); const [action, setAction] = useState("reschedule"); const [date, setDate] = useState(""); const [amount, setAmount] = useState(""); const [reason, setReason] = useState(""); const [touched, setTouched] = useState(false); const command = useStockCommand(() => { setSelected(undefined); setTouched(false); setReason(""); setAmount(""); setRefresh(v => v + 1); }); const leave = useProductionLeave(touched, command.busy, command.unknown, preservedSearchParams);
  useEffect(() => { onGuardChange?.({dirty:touched,busy:command.busy,unknown:command.unknown,blocked:leave.blocked}); }, [touched,command.busy,command.unknown,leave.blocked,onGuardChange]);
  const scopedLoans = value ? value.items.filter(item=>!context?.sku_id || (display(item.sku_id)===context.sku_id && display(item.warehouse_id)===context.warehouse_id && display(item.owner_id || "1")===context.owner_id)) : [];
  return <><PageHeader title="借出与归还" actions={canWrite && (onBorrow ? <Button onClick={onBorrow}>登记借出</Button> : <LinkButton to="/production/stock/movements/new?kind=OUT&intent=BORROW">登记借出</LinkButton>)} />{value ? scopedLoans.length ? <Table className={styles.stockRecordTable} title="借还记录"><thead><tr><th>借出/SKU</th><th>借用人</th><th>借出/归还/结清</th><th>未还</th><th>归还安排</th><th>操作</th></tr></thead><tbody>{scopedLoans.map(l => <tr key={display(l.id)}><td data-label="借出与商品"><Link to={`/production/stock/movements/${display(l.document_id)}`}>借出{display(l.id)}</Link><br />{labels.sku(l.sku_id)}<br />{labels.warehouse(l.warehouse_id)}</td><td data-label="借用人">{display(l.borrower)}<br />{display(l.purpose)}</td><td data-label="借出/归还/结清">{display(l.borrowed_units)} / {display(l.returned_units)} / {display(l.settled_units)}</td><td data-label="未还">{display(l.outstanding_units)}</td><td data-label="归还安排">{display(l.due_on || "日期待安排")}{l.overdue ? " · 逾期待核" : ""}{l.is_active === false ? " · 原借出已冲销" : ""}</td><td data-label="操作">{canWrite && l.is_active !== false && BigInt(display(l.outstanding_units)) > 0n && <div className={styles.actions}>{onReturn ? <Button variant="secondary" onClick={()=>onReturn(l)}>登记部分归还</Button> : <Link to={`/production/stock/movements/new?loan_id=${display(l.id)}&sku_id=${display(l.sku_id)}&warehouse_id=${display(l.warehouse_id)}`}>登记部分归还</Link>}<Button variant="secondary" onClick={() => { setSelected(l); setDate(display(l.due_on || "")); }}>安排/结清</Button></div>}</td></tr>)}</tbody></Table> : <section className={styles.loanEmpty} aria-labelledby="loan-empty-title"><h2 id="loan-empty-title">目前没有借出记录</h2><p hidden>普通取走或消耗不会生成归还任务。需要跟踪归还时，请登记为“借出”。</p>{canWrite && (onBorrow ? <Button onClick={onBorrow}>登记借出</Button> : <Link className={styles.stockPrimaryAction} to="/production/stock/movements/new?kind=OUT&intent=BORROW">登记借出</Link>)}</section> : <ReadState error={error} />}
    {selected && <section className={styles.panel}><h2>处理借出{display(selected.id)}</h2><form onChangeCapture={() => setTouched(true)} onSubmit={e => { e.preventDefault(); command.submit(`${base}/loans/${display(selected.id)}/${action}`, { expected_revision: selected.revision, reason, ...(action === "settle" ? { units: amount } : { due_on: date }) }); }}><fieldset disabled={command.busy || command.unknown}><Select label="处理方式" value={action} choices={{ reschedule: "更改预计归还日期", settle: "在外转消耗/赠送/损失结清" }} onChange={setAction} />{action === "settle" ? <NumberField label="本次结清件数" value={amount} onChange={setAmount} /> : <FormField label="预计归还日（可未知）"><Input type="date" value={date} onChange={e => setDate(e.target.value)} /></FormField>}<FormField label="处理依据"><Input required value={reason} onChange={e => setReason(e.target.value)} /></FormField><Button type="submit">确认处理</Button></fieldset></form></section>}{command.feedback}{leave.prompt}</>;
}
function Plans({ canWrite }: { canWrite: boolean }) {
  const [params, setParams] = useSearchParams();
  const [refresh, setRefresh] = useState(0);
  const date = params.get("as_of") || new Date().toISOString().slice(0, 10);
  const forecast = useRead<Items<Balance> & { excluded_pending: RecordValue[] }>(`${base}/forecast?as_of=${date}`, refresh);
  const plans = useRead<Items<RecordValue>>(`${base}/plans`, refresh);
  const catalog = useRead<{ items: Sku[] }>("/api/production/skus?contract_version=2");
  const labels = useStockLabels();
  const [warehouse, setWarehouse] = useState("1");
  const [sku, setSku] = useState("");
  const [direction, setDirection] = useState("IN");
  const [planned, setPlanned] = useState("");
  const [amount, setAmount] = useState("");
  const [source, setSource] = useState("");
  const [reason, setReason] = useState("");
  const [selectedPlan, setSelectedPlan] = useState<RecordValue>();
  const [planAction, setPlanAction] = useState("update");
  const [confirmation, setConfirmation] = useState<{ plan: RecordValue; amount: string; reason: string }>();
  const [touched, setTouched] = useState(false);
  const command = useStockCommand(() => {
    setSelectedPlan(undefined); setConfirmation(undefined); setTouched(false);
    setAmount(""); setSource(""); setReason(""); setRefresh(v => v + 1);
  });
  const leave = useProductionLeave(touched, command.busy, command.unknown);
  const selectPlan = (p: RecordValue) => {
    setSelectedPlan(p); setPlanAction("update"); setWarehouse(display(p.warehouse_id)); setSku(display(p.sku_id));
    setDirection(display(p.direction)); setPlanned(display(p.planned_on || "")); setAmount(display(p.units));
    setSource(display(p.source_reference)); setReason(""); setTouched(false);
  };
  const linkToActual = (p: RecordValue, sales: boolean) => {
    const query = new URLSearchParams({ plan_id: display(p.id), sku_id: display(p.sku_id), warehouse_id: display(p.warehouse_id) });
    if (typeof p.owner_id === "string" || typeof p.owner_id === "number") query.set("owner_id", String(p.owner_id));
    if (sales) { query.set("flow","guided");query.set("purpose","WAREHOUSE_DISPATCH");query.set("return_to",`/production/stock/forecast?${params}`);return `/production/shipments/new?${query}`; }
    query.set("kind", display(p.direction));
    return `/production/stock/movements/new?${query}`;
  };
  return <>
    <PageHeader title="预计库存与收发安排" />
    <FormField label="预计截至日期"><Input type="date" min={new Date().toISOString().slice(0, 10)} value={date} onChange={e => { if (e.target.value) setParams({ as_of: e.target.value }); }} /></FormField>
    {forecast.value ? <>
      <Table title={`截至 ${date} 的预计库存`}><thead><tr><th>商品/仓库</th><th>仓内实际</th><th>剩余预计入库</th><th>剩余预计出库</th><th>预计在库</th><th>当前可发</th></tr></thead><tbody>{forecast.value.items.map(b => {
        const included = b.plans || [];
        const incoming = included.filter(p => p.direction === "IN").reduce((sum, p) => sum + BigInt(display(p.remaining_units)), 0n);
        const outgoing = included.filter(p => p.direction === "OUT").reduce((sum, p) => sum + BigInt(display(p.remaining_units)), 0n);
        return <tr key={`${b.warehouse_id}:${b.owner_id}:${b.sku_id}`}><td>{labels.sku(b.sku_id)}<br />{labels.warehouse(b.warehouse_id)}<details><summary>查看计入的安排（{included.length}）</summary>{included.length ? included.map(p => <p key={display(p.id)}><Link to={`#plan-${display(p.id)}`}>{display(p.source_reference)}</Link> · {display(p.planned_on)} · {p.direction === "IN" ? "+" : "−"}{quantity(display(p.remaining_units))}件</p>) : <p>截至此日没有待完成安排。</p>}</details></td><td>{quantity(b.on_hand_units)}</td><td>+{units(incoming.toString())}</td><td>−{units(outgoing.toString())}</td><td>{quantity(b.projected_on_hand_units)}</td><td>{quantity(b.free_available_units)}</td></tr>;
      })}</tbody></Table>
      <StatusMessage kind="info" title={`未计入预测的待核安排：${forecast.value.excluded_pending.length} 条`}>无日期或逾期安排需先核对实际状态，不能假定已经完成。</StatusMessage>
      {!!forecast.value.excluded_pending.length && <Table title="无日期或逾期待核"><thead><tr><th>商品/仓库</th><th>来源与方向</th><th>原定日期</th><th>待处理数量</th></tr></thead><tbody>{forecast.value.excluded_pending.map(p => <tr key={display(p.id)}><td>{labels.sku(p.sku_id)}<br />{labels.warehouse(p.warehouse_id)}</td><td><Link to={`#plan-${display(p.id)}`}>{display(p.source_reference)}</Link> · {p.direction === "IN" ? "预计入库" : "预计出库"}</td><td>{display(p.planned_on || "日期待安排")}</td><td>{quantity(display(p.remaining_units))}</td></tr>)}</tbody></Table>}
    </> : <ReadState error={forecast.error} />}
    {canWrite && <section className={styles.panel}><h2>{selectedPlan ? `处理安排 ${display(selectedPlan.id)}` : "登记有依据的收发安排"}</h2>
      <form onSubmit={e => { e.preventDefault(); if (selectedPlan && planAction === "cancel") { setConfirmation({ plan: selectedPlan, amount, reason }); return; } command.submit(selectedPlan ? `${base}/plans/${display(selectedPlan.id)}/update` : `${base}/plans`, { warehouse_id: warehouse, owner_id: "1", sku_id: sku, direction, planned_on: planned, units: amount, source_reference: source, reason, ...(selectedPlan ? { expected_revision: selectedPlan.revision } : {}) }); }}>
        <fieldset disabled={command.busy || command.unknown}><div className={styles.filters}>
          {selectedPlan && <Select label="安排处理方式" value={planAction} choices={{ update: "修改数量/日期", cancel: "取消部分剩余量" }} onChange={value => { setTouched(true); setPlanAction(value); setAmount(display(value === "cancel" ? selectedPlan.remaining_units : selectedPlan.units)); }} />}
          <WarehouseSelect disabled={!!selectedPlan} value={warehouse} onDefault={setWarehouse} onChange={v => { setTouched(true); setWarehouse(v); }} />
          <SkuSelect disabled={!!selectedPlan} value={sku} skus={catalog.value?.items || []} onChange={v => { setTouched(true); setSku(v); }} />
          <Select disabled={!!selectedPlan} label="安排方向" value={direction} choices={{ IN: "预计入库", OUT: "预计出库" }} onChange={v => { setTouched(true); setDirection(v); }} />
          <NumberField label={selectedPlan && planAction === "cancel" ? "本次取消件数" : "计划总件数"} value={amount} onChange={v => { setTouched(true); setAmount(v); }} />
          <FormField label="预计日期（可未知）"><Input disabled={!!selectedPlan && planAction === "cancel"} type="date" value={planned} onChange={e => { setTouched(true); setPlanned(e.target.value); }} /></FormField>
          <FormField label="来源依据编号"><Input disabled={!!selectedPlan} required value={source} onChange={e => { setTouched(true); setSource(e.target.value); }} /></FormField>
          <FormField label="安排说明/处理原因"><Input required value={reason} onChange={e => { setTouched(true); setReason(e.target.value); }} /></FormField>
        </div><Button type="submit">{selectedPlan ? planAction === "cancel" ? "核对取消影响" : "保存安排变更" : "保存收发安排"}</Button>{selectedPlan && <Button variant="secondary" onClick={() => { setSelectedPlan(undefined); setTouched(false); setAmount(""); setSource(""); setReason(""); }}>改为登记另一安排</Button>}</fieldset>
      </form>
    </section>}
    <Table title="安排及剩余量"><thead><tr><th>来源/仓库</th><th>商品/方向</th><th>日期</th><th>计划/完成/取消/剩余</th><th>操作</th></tr></thead><tbody>{plans.value?.items.map(p => <tr id={`plan-${display(p.id)}`} key={display(p.id)}><td>{display(p.source_reference)}<br />{labels.warehouse(p.warehouse_id)}</td><td>{labels.sku(p.sku_id)} · {p.direction === "IN" ? "预计入库" : "预计出库"}</td><td>{display(p.planned_on || "日期待安排")}</td><td>{display(p.units)} / {display(p.completed_units)} / {display(p.cancelled_units)} / <strong>{display(p.remaining_units)}</strong></td><td>{p.loan_id ? <Link to="/production/stock/loans">从原借出处理</Link> : canWrite && BigInt(display(p.remaining_units)) > 0n && <div className={styles.actions}>
      {p.direction === "IN" ? <Link to={linkToActual(p, false)}>登记实际入库</Link> : <><Link to={linkToActual(p, true)}>登记销售发货</Link><Link to={linkToActual(p, false)}>登记普通取走/消耗</Link></>}
      <Button variant="secondary" disabled={command.busy || command.unknown} onClick={() => selectPlan(p)}>修改日期/数量</Button>
      <Button disabled={command.busy || command.unknown} onClick={() => setConfirmation({ plan: p, amount: display(p.remaining_units), reason: "" })}>取消剩余</Button>
    </div>}</td></tr>)}{!plans.value?.items.length && <tr><td colSpan={5}>{plans.error || "暂无收发安排"}</td></tr>}</tbody></Table>
    <Dialog contentClassName={styles.productionDialog} open={!!confirmation} onOpenChange={open => { if (!open) { setConfirmation(undefined); if (!selectedPlan) setTouched(false); } }} dismissDisabled={command.busy || command.unknown} title="确认取消收发安排" description="只减少预计剩余量，不代表货物实际入库或出库。">
      {confirmation && <form onSubmit={e => { e.preventDefault(); command.submit(`${base}/plans/${display(confirmation.plan.id)}/cancel`, { expected_revision: confirmation.plan.revision, units: confirmation.amount, reason: confirmation.reason }); }}><p>{labels.sku(confirmation.plan.sku_id)} · {labels.warehouse(confirmation.plan.warehouse_id)} · {display(confirmation.plan.source_reference)}</p><p>目前剩余 {quantity(display(confirmation.plan.remaining_units))} 件；本次取消量由你确认。</p><NumberField label="本次取消件数" value={confirmation.amount} onChange={value => { setTouched(true); setConfirmation({ ...confirmation, amount: value }); }} /><FormField label="实际取消原因"><Input required value={confirmation.reason} onChange={e => { setTouched(true); setConfirmation({ ...confirmation, reason: e.target.value }); }} /></FormField><div className={styles.dialogActions}><Button variant="secondary" disabled={command.busy || command.unknown} onClick={() => { setConfirmation(undefined); if (!selectedPlan) setTouched(false); }}>返回</Button><Button disabled={command.busy || command.unknown} type="submit">确认取消</Button></div>{command.feedback}</form>}
    </Dialog>
    <Button variant="secondary" disabled={command.busy || command.unknown} onClick={() => setRefresh(v => v + 1)}>重新读取安排</Button>{command.feedback}{leave.prompt}
  </>;
}
function HistoryLines({ before, after, skuName }: { before: MovementLine[]; after: MovementLine[]; skuName: (id: string) => string }) {
  const describe = (line: MovementLine) => `${skuName(line.sku_id)} · ${qualityNames[line.quality] || line.quality} · ${purposes[line.purpose] || line.purpose}${line.borrower ? ` · 实际借用人 ${line.borrower}` : ""}`;
  if (!before.length && !after.length) return null;
  if (before.length <= 1 && after.length <= 1) return <Table title="逐行数量变化"><thead><tr><th>内容</th><th>修改前</th><th>修改后</th></tr></thead><tbody><tr><td>商品、状态与用途</td><td>{before[0] ? describe(before[0]) : "—"}</td><td>{after[0] ? describe(after[0]) : "—"}</td></tr><tr><td>本次件数</td><td>{before[0] ? `${units(before[0].units)} 件` : "—"}</td><td>{after[0] ? `${units(after[0].units)} 件` : "—"}</td></tr></tbody></Table>;
  return <><p>以下分别列出操作前后明细供核对，不按行号推测对应关系。</p><Table title="变更前明细"><thead><tr><th>商品、状态与用途</th><th>件数</th></tr></thead><tbody>{before.map((line, i) => <tr key={i}><td>{describe(line)}</td><td>{units(line.units)}</td></tr>)}{!before.length && <tr><td colSpan={2}>无</td></tr>}</tbody></Table><Table title="变更后明细"><thead><tr><th>商品、状态与用途</th><th>件数</th></tr></thead><tbody>{after.map((line, i) => <tr key={i}><td>{describe(line)}</td><td>{units(line.units)}</td></tr>)}{!after.length && <tr><td colSpan={2}>无</td></tr>}</tbody></Table></>;
}
function History() {
  const [params, setParams] = useSearchParams();
  const { value, error } = useRead<Items<RecordValue> & { actors?: { actor_id: string; actor_name: string }[] }>(`${base}/history?${params}`);
  const labels = useStockLabels();
  const fields: Record<string, string> = { status: "状态", units: "数量", completed_units: "已完成", remaining_units: "剩余安排", returned_units: "已归还", settled_units: "在外结清", released_units: "已释放", consumed_units: "已消费预留", due_on: "预计归还日", planned_on: "预计收发日", cancelled_units: "已取消", business_date: "实际发生日期", source_reference: "来源依据" };
  const readable = (key: string, value: unknown) => key === "status" ? ({ DRAFT: "草稿", POSTED: "已过账", REVERSED: "已冲销" } as Record<string, string>)[display(value)] || display(value) : display(value);
  return <><PageHeader title="库存操作历史" />
    <form className={styles.filters} key={params.toString()} onSubmit={e => { e.preventDefault(); const form = new FormData(e.currentTarget); const next = new URLSearchParams(); for (const [name, value] of form) if (typeof value === "string" && value) next.set(name, value); setParams(next); }}>
      <FormField label="操作人员"><select name="actor_id" defaultValue={params.get("actor_id") || ""}><option value="">全部已记录人员</option>{value?.actors?.map(actor => <option key={actor.actor_id} value={actor.actor_id}>{actor.actor_name}</option>)}</select></FormField>
      <FormField label="登记日期从"><Input type="date" name="from" defaultValue={params.get("from") || ""} /></FormField><FormField label="日期至"><Input type="date" name="to" defaultValue={params.get("to") || ""} /></FormField>
      <FormField label="动作"><select name="action" defaultValue={params.get("action") || ""}><option value="">全部动作</option>{Object.entries(actions).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></FormField><Button type="submit">查询用户操作</Button><Button variant="secondary" onClick={() => setParams({})}>清空条件</Button>
    </form>
    {value ? <section className={styles.panel}>{value.items.map((item, index) => {
      const before = item.before_value && typeof item.before_value === "object" ? item.before_value as RecordValue : {};
      const after = item.after_value && typeof item.after_value === "object" ? item.after_value as RecordValue : {};
      const oldLines = Array.isArray(before.lines) ? before.lines as MovementLine[] : [];
      const newLines = Array.isArray(after.lines) ? after.lines as MovementLine[] : [];
      const changed = Object.entries(fields).filter(([key]) => before[key] !== after[key] && (before[key] != null || after[key] != null));
      return <details key={`${display(item.document_kind)}:${display(item.document_id)}:${display(item.revision)}:${index}`}><summary>{display(item.actor_name || `账号${display(item.actor_id)}`)} · {actions[display(item.operation_kind)] || display(item.operation_kind)} · {localTime(item.created_at)}</summary>
        <p>{documentNames[display(item.document_kind)] || display(item.document_kind)} {display(item.document_id)} · 修订 {display(item.revision)} · 原因：{display(item.reason || "未记录")}</p>
        {!!(before.sku_id || after.sku_id) && <p>{labels.sku(after.sku_id || before.sku_id)} · {labels.warehouse(after.warehouse_id || before.warehouse_id)}</p>}
        <Table title="可读变更"><thead><tr><th>内容</th><th>修改前</th><th>修改后</th></tr></thead><tbody>{changed.map(([key, title]) => <tr key={key}><td>{title}</td><td>{readable(key, before[key] ?? "—")}</td><td>{readable(key, after[key] ?? "—")}</td></tr>)}{!changed.length && <tr><td colSpan={3}>本次变动见逐行明细及操作原因。</td></tr>}</tbody></Table>
        <HistoryLines before={oldLines} after={newLines} skuName={labels.sku} />
        <details><summary>技术ID与原始变更</summary><p>操作用户ID：{display(item.actor_id)} · UTC原时间：{display(item.created_at)}</p><pre>{JSON.stringify({ before: item.before_value, after: item.after_value }, null, 2)}</pre></details>
      </details>;
    })}{!value.items.length && <p>该条件下没有操作记录。</p>}<p>最多展示最近200条；可用用户、日期和动作缩小范围。</p></section> : <ReadState error={error} />}
  </>;
}
function OverviewMovement({ context, canWrite, refresh, saved, onGuardChange }: { context: OverviewAction; canWrite: boolean; refresh: number; saved: () => void; onGuardChange: (guard: OverviewGuard) => void }) {
  const [id,setId]=useState<string>();const [editing,setEditing]=useState(true);
  if(!context.warehouse_id || !context.owner_id || !context.sku_id) return <StatusMessage kind="warning" title="请选择明确的库存仓库与货权"/>;
  return <WarehouseMovement inline id={id} context={{warehouse_id:context.warehouse_id,owner_id:context.owner_id,sku_id:context.sku_id,loan_id:context.loan_id,kind:["borrow","out"].includes(context.kind) ? "OUT" : ["inspect","quality"].includes(context.kind) ? "MOVE" : context.kind === "count" ? "ADJUST" : "IN",intent:context.kind === "borrow" ? "BORROW" : context.kind === "out" ? "OUT" : context.kind === "quality" ? "MOVE" : context.kind === "count" ? "ADJUST" : context.kind === "return" ? "RETURN" : context.kind === "inspect" ? "INSPECT" : "IN"}} canWrite={canWrite} refresh={refresh} saved={value=>{setId(value);setEditing(false);onGuardChange({dirty:false,busy:false,unknown:false});saved();}} editing={editing} edit={()=>setEditing(true)} preservedSearchParams={overviewSearchParams} onGuardChange={onGuardChange}/>;
}
function StockIndex({canWrite,canOpen,stockSource}:{canWrite:boolean;canOpen:boolean;stockSource:OverviewSource}) {
  const [params] = useSearchParams();
  if (params.get("view") === "sheet") return <InventoryOverviewSheet />;
  return <SkuAcrossWarehouses stockSource={stockSource} canWrite={canWrite} canOpen={canOpen} renderTools={context => context.action.kind === "loans" ? <Loans key={JSON.stringify(context.action)} context={context.action} onBorrow={()=>context.startAction({...context.action,kind:"borrow"})} onReturn={loan=>context.startAction({kind:"return",warehouse_id:display(loan.warehouse_id),owner_id:context.action.owner_id,sku_id:display(loan.sku_id),loan_id:display(loan.id)})} canWrite={canWrite} preservedSearchParams={overviewSearchParams} onGuardChange={context.onGuardChange}/> : context.action.kind === "movement" || context.action.kind === "borrow" || ["inspect","return","out","quality","count"].includes(context.action.kind) ? <OverviewMovement key={JSON.stringify(context.action)} context={context.action} canWrite={canWrite} refresh={0} saved={context.refresh} onGuardChange={context.onGuardChange}/> : <StockHome key={JSON.stringify(context.action)} canWrite={canWrite} value={context.stock} error={context.stockError} catalogValue={context.catalog} catalogError={context.catalogError} refreshStock={context.refresh} action={context.action} onAction={context.startAction} onGuardChange={context.onGuardChange}/>}/>;
}

function StockPages({ canWrite, canOpen, readOnly, loading, receiptSupported, stockSource }: { stockSource:OverviewSource; canWrite: boolean; canOpen: boolean; readOnly: boolean; loading: boolean; receiptSupported: boolean }) { return <Routes><Route index element={<StockIndex stockSource={stockSource} canWrite={canWrite} canOpen={canOpen} />} /><Route path="opening" element={loading ? <ReadState /> : readOnly || !canOpen ? <Navigate replace to="/production/stock" /> : <Opening canWrite={canWrite} />} /><Route path="movements" element={<Movements canWrite={canWrite} />} /><Route path="movements/new" element={loading ? <ReadState /> : readOnly ? <Navigate replace to="/production/stock" /> : <NewMovement canWrite={canWrite} receiptSupported={receiptSupported} />} /><Route path="movements/:id" element={<MovementDetail canWrite={canWrite} />} /><Route path="movements/:id/edit" element={loading ? <ReadState /> : readOnly ? <Navigate replace to="/production/stock" /> : <MovementDetail canWrite={canWrite} edit />} /><Route path="loans" element={<Loans canWrite={canWrite} />} /><Route path="plans" element={<Plans canWrite={canWrite} />} /><Route path="history" element={<History />} /><Route path="*" element={<Navigate replace to="/production/stock" />} /></Routes>; }

export function StockWorkspace({ canWrite }: { canWrite: boolean }) {
  const { generation, registerSensitivePurge } = useAuthzGeneration(); const [epoch, setEpoch] = useState(0); const { pathname } = useLocation();
  const [policyRefresh,setPolicyRefresh] = useState(0);
  const policy = useRead<StockPolicy & {scopes:{warehouse_id:string;warehouse_name:string;owner_id:string;owner_name:string}[]}>(`${base}/availability${pathname === "/production/stock" ? "?overview=1" : ""}`,policyRefresh);
  useEffect(() => registerSensitivePurge(() => setEpoch(value => value + 1)), [registerSensitivePurge]);
  if (policy.error && pathname !== "/production/stock") return <ReadState error={policy.error} />;
  const readOnly = policy.value?.writes_enabled === false; const canOpen = !readOnly && policy.value?.opening_enabled !== false;
  const recordFilters = ["/production/stock/movements", "/production/stock/loans", "/production/stock/history"].includes(pathname);
  return <>{readOnly && <aside className={styles.stockReadOnly} aria-label="当前操作范围"><strong>库存仅开放查询</strong><span>{policy.value?.items.length ? "可查看数量、来源和操作历史；收发、借还、预留及发货暂未开放。" : "尚未登记期初，不代表库存为0。请先查看来源资料；收发等操作暂未开放。"}</span></aside>}{policy.value?.writes_enabled === true && !canOpen && <aside className={styles.stockReadOnly} aria-label="当前操作范围"><strong>{canWrite ? "库存日常登记已开放" : "当前账号仅可查看库存"}</strong><span>{canWrite ? "可登记入库、取走、借还及异常；期初入口当前关闭。订单和出货请到对应单据页面操作。" : "可查看库存数量、来源和操作历史；需要登记时请由有权限的账号操作。"}</span></aside>}{recordFilters && <nav className={styles.workflowRecordFilters} aria-label="库存记录筛选"><span>查看记录</span>{[["/production/stock/movements", "库存变动"], ["/production/stock/loans", "借出与归还"], ["/production/stock/history", "操作历史"], ["/production/stock/materials", "资料核对"]].map(([to, label]) => <Link key={to} to={to!} aria-current={pathname === to ? "page" : undefined}>{label}</Link>)}</nav>}<StockPages stockSource={{...policy,loading:!policy.value && !policy.error,reload:()=>setPolicyRefresh(v=>v+1)}} key={`${generation}:${epoch}`} canOpen={canOpen} canWrite={canWrite && !!policy.value && !readOnly} readOnly={readOnly} loading={!policy.value} receiptSupported={policy.value?.production_receipts_supported === true} /></>;
}

function MovementImportReview({value,label}:{value:Movement;label:(id:string)=>string}){
  const audit=useTableBaseline(value.reason,value.kind==="ADJUST"?"count":"receipt");
  return <>{audit.feedback}<TableImportReview baseline={audit.baseline} rows={stockImportRows(value.kind,value.lines,label)}/></>;
}
