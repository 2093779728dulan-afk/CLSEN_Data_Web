import { Disclosure } from "../../design-system";
import { useBusinessToday } from "./workbenchDate";
import { ArrowLeft, Download, Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiRequestError, requestApi, writeApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, ClickSpark, Dialog, FormField, GlideSelectField, Input, Menu, PageHeader, PageTransition, Pagination, StatusMessage, Table, LinkButton } from "../../design-system";
import { DocumentContent, DocumentTable, ProductionProductTable, SummaryContent } from "./ProductionViews";
import { type Carton, type Document, type DocumentPage, type Kind, type Sku, type Source, type Summary, kindName, units } from "./types";
import { productionFieldId, validateProductionInput } from "./productionForm";
import { useProductionLeave } from "./useProductionLeave";
import { CatalogReferencePanel, CatalogCandidateCell, type CatalogReferenceResult } from "./CatalogReference";
import { OperationTableImport, type OperationImportPreview } from "./OperationTableImport";
import { ShipmentOrderAttribution } from "./ShipmentOrderAttribution";
import { DispatchImportChanges } from "./DispatchImportChanges";
import { ProductionImportCenter } from "./ProductionImportCenter";
import { SourceDraftManager } from "./SourceDraftManager";
import { ManualTablePage } from "../manual-tables/ManualTablePage";
import { InventorySnapshotPage } from "./InventorySnapshotPage";
import { StockWorkspace } from "./StockWorkspace";
import { ProductionNavigation } from "./ProductionNavigation";
import { ShipmentSourceDraftPage } from "./ShipmentSourceDraftPage";
import { DraftQuantityChange, SourceDraftReview, type DraftReviewItem } from "./SourceDraftReview";
import styles from "./Production.module.css";
import { useLoad, useCommand } from "./useProductionApi";
import { BatchReceiptPage } from "./BatchReceiptPage";
import { OrderWorkbench } from "./OrderWorkbench";
import { DirectoryWorkspace } from "./DirectoryWorkspace";
import { ReadState, WarehouseField, type WorkbenchStock } from "./WorkbenchFields";
import { DestinationField } from "./DirectoryFields";
import { destinationValue } from "./directoryTypes";
import { GuidedOperationLayout } from "./GuidedOperationLayout";
import { ProductionOperationDialog } from "./ProductionOperationDialog";
import { WarehouseDispatchTable, type DispatchTableValidation } from "./WarehouseDispatchTable";
import { DraftShipmentConfirm } from "./WorkbenchOperations";
import { TransportPanel } from "./TransportPanel";
import { ShipmentCartons } from "./ShipmentCartons";
import { packingError } from "./shipmentPacking";
import wizardStyles from "./QualityMovementWizard.module.css";
import { ProductionBuildNotice } from "./ProductionBuildNotice";
import { ArrivalVerificationWindow } from "./ArrivalVerification";
import { ProductionOverview } from "./ProductionOverview";

function Layout({ children }: { children: ReactNode }) {
  const location = useLocation(); const { pathname } = location;
  const state: unknown = location.state;
  const overviewReturnRef = useRef("");
  if (pathname === "/production/overview") overviewReturnRef.current = "";
  else if (state && typeof state === "object" && "overviewReturn" in state && typeof state.overviewReturn === "string" && /^\/production\/overview(?:\?|$)/.test(state.overviewReturn)) overviewReturnRef.current = state.overviewReturn;
  const overviewReturn = overviewReturnRef.current || "/production/overview";
  const sourceReturn=new URLSearchParams(location.search).get("return_to")||"";
  const returnTarget=/^\/production\/(?:warehouses\/[1-9][0-9]*|orders(?:\/[1-9][0-9]*)?|overview|stock(?:\/forecast)?)(?:\?|$)/.test(sourceReturn)?sourceReturn:overviewReturn;
  const returnLabel=returnTarget.startsWith("/production/orders")?"返回订单跟进":returnTarget.startsWith("/production/warehouses/")?"返回仓库":returnTarget.startsWith("/production/stock")?"返回库存":"返回业务总览";
  const warehouseFocusMode = pathname === "/production/warehouses" || pathname.startsWith("/production/warehouses/");
  const flatWorkspace = pathname === "/production/factories" || pathname.startsWith("/production/factories/") || /^\/production\/orders(?:\/\d+|\/new)?$/.test(pathname);
  const refinedPage = ["/production/orders", "/production/factories", "/production/warehouses"].some(path => pathname === path || pathname.startsWith(`${path}/`));
  const body = <div className={styles.body}><ProductionBuildNotice />{children}</div>;
  // Master-detail workspaces retain their chooser; only the selected detail reloads.
  return <ClickSpark><main id="main-content" className={`${styles.workspace}${refinedPage ? ` ${styles.refinedWorkspace}` : ""}${warehouseFocusMode ? ` ${styles.warehouseWorkspace}` : ""}${flatWorkspace ? ` ${styles.flatWorkspace}` : ""}`}>{pathname !== "/production/overview" && <div className={styles.workspaceNavigation}><ProductionNavigation /><Link className={styles.overviewReturn} to={returnTarget}><ArrowLeft size={16} aria-hidden="true" />{returnLabel}</Link></div>}{refinedPage ? body : <PageTransition key={pathname}>{body}</PageTransition>}</main></ClickSpark>;
}
function Filters({ summary = false, kind = "orders", onDemoMode }: { summary?: boolean; kind?: Kind; onDemoMode?: (demo: boolean) => void }) {
  const [params, setParams] = useSearchParams();
  const [expanded, setExpanded] = useState(false);
  const skus = useLoad<{ items: Sku[]; demo: boolean; order_source_drafts?: boolean; shipment_source_drafts?: boolean }>("/api/production/skus?contract_version=2");
  useEffect(() => { onDemoMode?.(skus.value?.demo === true); }, [onDemoMode, skus.value]);
  const labels: Record<string, string> = { q: "单号", status: "状态", from: summary ? "订单日期从" : "业务日期从", to: "日期至", shipment_from: "出货日期从", shipment_to: "出货日期至", sku: "SKU", order: "关联订单", tracking: "跟进" };
  const active = [...params].filter(([key, value]) => labels[key] && value);
  const advancedCount = active.filter(([key]) => ["from", "to", "order", "tracking"].includes(key)).length;
  const skuField = <FormField label="SKU"><select key={skus.value ? "ready" : "loading"} name="sku" defaultValue={params.get("sku") || ""}><option value="">全部SKU</option>{skus.value?.items.map(s => <option key={s.sku_id} value={s.sku_id}>{s.label}</option>)}</select></FormField>;
  const dates = <><FormField label={summary ? "订单日期从" : "业务日期从"}><Input type="date" name="from" defaultValue={params.get("from") || ""} /></FormField><FormField label="至"><Input type="date" name="to" defaultValue={params.get("to") || ""} /></FormField></>;
  const orderField = <FormField label="关联系统订单号（可选）"><Input name="order" defaultValue={params.get("order") || ""} placeholder="PO-…" /></FormField>;
  return <section className={styles.filterPanel} aria-label="查询筛选">
    <div className={styles.filterHeading}><h2>查询筛选</h2><div className={styles.filterToolbar}><Button className={styles.filterToggle} aria-expanded={expanded} aria-controls="production-filters" variant="secondary" onClick={() => setExpanded(!expanded)}>{expanded ? "收起筛选" : `展开筛选${active.length ? `（${active.length}项）` : ""}`}</Button><Button variant="quiet" onClick={() => setParams({})}>清空筛选</Button></div></div>
    {!!active.length && <p className={styles.filterSummary}>当前条件：{active.map(([key, value]) => `${labels[key]} ${key === "sku" ? skus.value?.items.find(s => s.sku_id === value)?.label || value : ({ CONFIRMED: "已确认", DRAFT: "草稿", VOID: "已作废", OPEN: "跟进中", CLOSED: "含已关闭行", UNSHIPPED: "未出货", PARTIAL: "部分出货", OVERAGE: "超发" } as Record<string, string>)[value] || value}`).join("；")}</p>}
    <form id="production-filters" className={`${summary ? styles.filters : styles.documentFilterForm} ${expanded ? "" : styles.collapsedFilters}`} onSubmit={e => { e.preventDefault(); const form = new FormData(e.currentTarget); const next = new URLSearchParams(); for (const [key, value] of form) if (typeof value === "string" && value) next.set(key, value); next.set("page", "1"); setParams(next); setExpanded(false); }} key={params.toString()}>
      {summary ? <>{dates}<FormField label="出货日期从（可选）"><Input type="date" name="shipment_from" defaultValue={params.get("shipment_from") || ""} /></FormField><FormField label="出货日期至（可选）"><Input type="date" name="shipment_to" defaultValue={params.get("shipment_to") || ""} /></FormField>{skuField}{orderField}<Button type="submit" variant="secondary">应用筛选</Button></> : <>
        <div className={`${styles.filters} ${styles.documentQuickFilters}`}><FormField label="单号搜索"><Input name="q" defaultValue={params.get("q") || ""} /></FormField><FormField label="状态"><select name="status" defaultValue={params.get("status") || ""}><option value="">全部状态</option><option value="DRAFT">草稿</option><option value="CONFIRMED">已确认</option><option value="VOID">已作废</option></select></FormField>{skuField}<Button type="submit" variant="secondary">应用筛选</Button></div>
        <Disclosure className={styles.advancedFilters} open={advancedCount > 0}><summary>更多筛选{advancedCount ? `（${advancedCount}项）` : ""}</summary><div className={styles.filters}>{dates}{orderField}{kind === "orders" && <FormField label="跟进筛选"><select name="tracking" defaultValue={params.get("tracking") || ""}><option value="">全部</option><option value="OPEN">跟进中</option><option value="CLOSED">含已关闭行</option><option value="UNSHIPPED">未出货（跟进中）</option><option value="PARTIAL">部分出货</option><option value="OVERAGE">超发</option></select></FormField>}</div></Disclosure>
      </>}
    </form>
  </section>;
}
function ListPage({ kind, canWrite }: { kind: Kind; canWrite: boolean }) {
  const [params, setParams] = useSearchParams();
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [demo, setDemo] = useState(false); const [experienceOpen, setExperienceOpen] = useState(false); const experienceTrigger = useRef<HTMLButtonElement>(null);
  const { value, error } = useLoad<DocumentPage>(`/api/production/${kind}?${params}`);
  const catalog = useLoad<{items:Sku[]}>("/api/production/skus?contract_version=2", 0, kind === "shipments");
  return <><div className={styles.documentPageHeader}><PageHeader title={kind === "shipments" ? "仓库出货" : kindName[kind]} actions={<div className={styles.documentPageActions}>{canWrite && <LinkButton to={`/production/${kind}/intake`} variant="primary" icon={<Plus />}>{kind === "orders" ? "新增订单" : "新建仓库出货"}</LinkButton>}<a className={styles.documentExport} href={`/api/production/files/${kind}/export?${params}`}><Download aria-hidden="true" />导出查询结果</a>{demo && <Button ref={experienceTrigger} variant="quiet" onClick={() => setExperienceOpen(true)}>体验流程</Button>}</div>} /></div>{demo && <p className={styles.documentScopeNote}>独立虚构体验 · 花都工厂与仓库1号同址，当前记录不代表真实库存或发运事实。</p>}<Filters kind={kind} onDemoMode={setDemo} />{kind === "orders" && <div className={styles.trackingFilters} aria-label="订单跟进快捷筛选">{[{ key: "", label: "全部" }, { key: "UNSHIPPED", label: "未出货" }, { key: "PARTIAL", label: "部分出货" }, { key: "OVERAGE", label: "超发" }].map(choice => <Button key={choice.key} variant="secondary" aria-pressed={(params.get("tracking") || "") === choice.key} onClick={() => { const next = new URLSearchParams(params); if (choice.key) next.set("tracking", choice.key); else next.delete("tracking"); next.set("page", "1"); setParams(next); }}>{choice.label}</Button>)}</div>}
    {demo && <Dialog contentClassName={styles.productionDialog} open={experienceOpen} onOpenChange={setExperienceOpen} returnFocusTarget={experienceTrigger} size="large" title="订单与出货体验流程" description="当前仅为虚构演练环境。库存启用后，实际发货同时按当前可发量校验；原100件演练可先在库存账准备足够的虚构期初或入库。可以先查看样例，再用一张新订单走完下面的流程；已保存的试验记录不必重置。">
      <div className={styles.body}><section className={styles.panel}><h3>先查看已有样例</h3><p><Link to="/production/orders/5">基础样例：预计100 → 两批40＋30 → 累计70、差额30</Link></p><p><Link to="/production/orders/11">关闭、恢复与需求变更：展开修订历史查看过程</Link> · 当前预计175、累计80、待跟进95。</p><p><Link to="/production/orders/17">来源与超发：查看同量另一批的核对记录</Link> · 当前累计110、差额-10、超发10。</p><p>这些单据保留此前演练结果；下面的预期数量适用于新建的体验订单，不能拿全局汇总直接比较。</p></section>
        {canWrite ? <section className={styles.panel}><h3>动手走一遍完整流程</h3><ol className={styles.experienceSteps}>
          <li><strong>创建预计订单</strong><p><Link to="/production/orders/new">创建一张新的体验订单</Link>，或<Link to="/production/orders/import">从标准表格导入订单</Link>；下载模板后填写同样的订单资料。选择一个虚构SKU，预计填100件，填写业务日期、便于辨认的体验单号和人工来源说明，然后“保存并确认”。数量默认留空，也可主动“载入虚构示例”。</p><p>预期：预计100、累计0、差额100、待跟进100。</p></li>
          <li><strong>登记第一批40件</strong><p>在刚创建的订单详情点击“记录本次出货”，实际数量和该订单分配数量都填40；核对SKU、日期，发运用途选择“订单对外发运（已交接）”，填写人工来源说明并确认。</p><p>预期：预计100、累计40、差额60。</p></li>
          <li><strong>另建第二批30件</strong><p>回到同一订单，再次“记录本次出货”，实际量和分配量都填30。每次发运是一张独立出货单。</p><p>预期：累计70、差额30、待跟进30。</p></li>
          <li><strong>刷新并对账</strong><p>刷新订单详情，进入<Link to="/production/summary">数量汇总</Link>，用该订单的完整系统号筛选，再导出结果。保持未限定出货日期，比较预计100、全部累计70和差额30。</p></li>
          <li><strong>关闭并恢复剩余跟进</strong><p>回到订单，点击“关闭跟进”，选择该SKU行并填写原因。关闭后再点“恢复跟进”，查看修订历史。</p><p>预期：关闭时关闭量30、待跟进0，预计与累计不变；恢复后当前关闭量0、待跟进30，旧关闭记录保留。</p></li>
          <li><strong>正式追加需求</strong><p>恢复后点击“需求变更”，把预计100改为150，填写生效日期和原因并提交。</p><p>预期：预计150、累计70、差额80、待跟进80。录错数字使用“录入更正”，它与正式需求变更分别留痕。</p></li>
          <li><strong>体验Excel来源核对</strong><p>从“标准表格导入”下载模板。v1兼容原字段，v2带可靠来源字段。一份文件对应一张单据；先预览问题和数量影响，再确认。同一可靠来源内容一致应返回已有单据，不再次增加数量；另一合法批次需有实际区别依据。</p></li>
        </ol><StatusMessage kind="info" title="遇到疑似重复或保存失败">同日、同SKU和同量可能触发候选核对。确认是本次新演练后填写来源区别说明再继续。修订冲突先刷新核对；提交结果未知时查询原操作或重发原操作，页面会保留实际已提交结果。</StatusMessage></section> : <StatusMessage kind="info" title="当前账号只读">可以查看上面的样例、汇总和修订历史。动手创建、更正及关闭需要管理员或数据管理员账号。</StatusMessage>}
      </div>
    </Dialog>}
    <Disclosure className={styles.workflowTools}><summary>原表与待完成资料</summary><Link to={`/production/${kind}/materials`}>查看{kind === "orders" ? "订单" : "出货"}资料记录</Link><p>未完成的整理保留在这里；已生成的草稿直接在本页业务记录中继续。</p><p><Link to="/production/products">查看生产可用规格</Link> · <Link to="/catalog">维护商品主档</Link></p></Disclosure>{kind === "orders" && <Disclosure className={styles.workflowTools} onToggle={event => setSummaryOpen(event.currentTarget.open)}><summary>查看订单数量汇总</summary>{summaryOpen && <OrderSummaryPanel />}</Disclosure>}
    {value ? <><DocumentTable kind={kind} catalog={catalog.value?.items} items={value.items} filtered={[...params].some(([key, value]) => key !== "page" && !!value)} /><Pagination itemLabel={kind === "orders" ? "订单" : "出货单"} page={value.page} totalItems={value.total} totalPages={Math.max(1, Math.ceil(value.total / value.page_size))} onPageChange={page => { const next = new URLSearchParams(params); next.set("page", String(page)); setParams(next); }} /></> : <ReadState error={error} />}
  </>;
}
function ProductionProducts() {
  const { value, error } = useLoad<{ items: Sku[]; demo: boolean }>("/api/production/skus?contract_version=2");
  return <><PageHeader title="生产商品基础" description="查看可用于订单、出货和库存的商品规格；商品信息由商品主档统一维护。" />{value ? <><StatusMessage kind="info" title={value.demo ? "独立虚构商品身份" : "当前站点已发布商品读源"}>{value.demo ? "仅使用独立虚构商品；正式SKU和渠道关系由主档审核维护。此处不代表真实主档已接通。" : "商品修订与审核继续由商品主档唯一维护；生产页面只读取。"}</StatusMessage><ProductionProductTable items={value.items} /></> : <ReadState error={error} />}</>;
}
function OrderSummaryPanel() {
  const { value, error } = useLoad<Summary>("/api/production/summary?");
  return <div className={styles.body}><p className={styles.workflowNote}>汇总全部有效订单；草稿和作废单据不计入。按日期、商品查询可使用高级汇总。</p><div className={styles.actions}><Link to="/production/summary">高级汇总查询</Link><a href="/api/production/files/summary/export">导出汇总</a></div>{value ? <SummaryContent summary={value} /> : <ReadState error={error} />}</div>;
}

function OrderStockPanel({ document }: { document: Document }) {
  const { value, error } = useLoad<{ items: { sku_id: string; warehouse_id: string; state: string; free_available_units: string | null }[]; scopes: { warehouse_id: string; warehouse_name: string }[] }>("/api/production/inventory/availability");
  return <>{value ? <><Table title="当前自由可发" description="按仓库查看当前余量；本订单已预留的数量仍由实际出货确认时核对。"><thead><tr><th>商品规格</th><th>仓库及当前自由可发</th></tr></thead><tbody>{document.lines?.map(line => {
    const balances = value.items.filter(item => item.sku_id === line.sku_id);
    return <tr key={line.id}><td>{line.sku_label}</td><td>{balances.length ? balances.map(item => <p key={item.warehouse_id}>{value.scopes.find(scope => scope.warehouse_id === item.warehouse_id)?.warehouse_name || "仓库名称待核"}：{item.state === "ready" && item.free_available_units != null ? `${units(item.free_available_units)} 件` : "可发待核"}</p>) : "尚未登记此规格，不能视为0件"}</td></tr>;
  })}</tbody></Table><Link to="/production/stock">查看库存总览与占用明细</Link></> : <ReadState error={error} />}</>;
}

function DocumentSourceRecords({ kind, id }: { kind: Kind; id: string }) {
  const [open, setOpen] = useState(false);
  return <Disclosure className={styles.workflowTools} onToggle={event => setOpen(event.currentTarget.open)}><summary>查看原表与整理记录</summary>{open && <ManualTablePage view="records" initialKind={kind === "orders" ? "orders" : "packing"} targetUrl={`/production/${kind}/${id}`} />}</Disclosure>;
}

function SummaryPage() {
  const [params] = useSearchParams();
  const { value, error } = useLoad<Summary>(`/api/production/summary?${params}`);
  return <><PageHeader eyebrow="ORDER → SHIPMENT" title="预计与实际汇总" description="仅核对此前明确关联生产订单的历史出货；新的仓库独立出货不计入此表。下单、生产、入库请看订单跟进；本表差额不能判断库存或生产进度。" actions={<a href={`/api/production/files/summary/export?${params}`}>导出汇总</a>} /><Filters summary />{value ? <SummaryContent summary={value} /> : <ReadState error={error} />}</>;
}
type LineInput = { id?: string; sku_id: string; expected_units: string };
type SourceCheck = { candidates: Pick<Document, "id" | "system_number" | "business_number" | "business_date" | "status">[]; duplicate_document?: Document; content_matches?: boolean };
const sourceFields = { source_system: "来源单位／系统", source_event_kind: "来源事件类别", external_event_id: "外部事件号", source_batch: "来源批次（可选）" } as const;
function DispatchStock({ source, warehouse, owner = "1" }: { source: Source; warehouse: string; owner?: string }) {
  const [refresh, setRefresh] = useState(0);
  const ids = [...new Set(source.allocations.map(a => a.order_line_id).filter(Boolean))].join(",");
  const state = useLoad<{ state: string; on_hand_units: string | null; free_available_units: string | null; own_reserved_units?: string; dispatch_allowed_units: string | null; held_units?: string; reserved_units?: string; qualified_units?: string | null; pending_units?: string | null; defective_units?: string | null; unassessed_units?: string | null; missing?: string }>(`/api/production/inventory/availability?warehouse_id=${warehouse}&owner_id=${owner}&sku_id=${source.sku_id || "0"}&order_line_ids=${encodeURIComponent(ids)}`, refresh, !!source.sku_id);
  if (!source.sku_id) return null;
  const b = state.value;
  return <section aria-label="当前出货库存核对">
    {state.error ? <StatusMessage kind="warning" title="可发量暂未核实">{state.error}</StatusMessage> : !b ? <StatusMessage kind="info" title="正在读取服务端可发量…" /> : <StatusMessage kind={b.state === "ready" ? "info" : "warning"} title={b.state === "ready" ? `本次当前允许 ${b.dispatch_allowed_units} 件` : b.state === "shortage" ? "库存存在预留/冻结缺口，暂停发货" : "当前可发尚未就绪"}>
      <p>仓内实际 {b.on_hand_units ?? "未知"} · 自由可发 {b.free_available_units ?? "未就绪"} · 本次自有预留 {b.own_reserved_units ?? "0"} · 冻结 {b.held_units ?? "0"} 件。</p>
      <p>合格 {b.qualified_units ?? "未核实"} · 待检 {b.pending_units ?? "未核实"} · 次品 {b.defective_units ?? "未核实"} · 质量未核 {b.unassessed_units ?? "未核实"} 件。待检、次品和质量未核数量不计入当前可发；检验结果确认后可在此刷新，不会改动已填出货内容。</p>
      {b.missing && <p>{b.missing}</p>}
      <p>确认时服务端重新核对合并后的全部来源量；预计量不能放行，读取可发量不代表预留库存。</p>
      <Link to="/production/stock">查看库存及占用</Link>
    </StatusMessage>}
    <Button variant="secondary" disabled={!state.value && !state.error} onClick={() => setRefresh(value => value + 1)}>刷新当前可发量</Button>
  </section>;
}
function Editor({ kind, initial }: { kind: Kind; initial?: Document }) {
  const navigate = useNavigate(); const [params] = useSearchParams();const editorLocation=useLocation();
  const returnTo = params.get("return_to") || "";
  const sourceReturn=/^\/production\/(?:warehouses\/[1-9][0-9]*|orders(?:\/[1-9][0-9]*)?|overview|stock(?:\/forecast)?)(?:\?|$)/.test(returnTo)?returnTo:"";
  const contextQuery=sourceReturn?`?${new URLSearchParams({return_to:sourceReturn})}`:"";
  const back=initial?`/production/${kind}/${initial.id}${contextQuery}`:sourceReturn||`/production/${kind}`;

  const guided = kind === "shipments" && params.get("action") !== "allocation-corrections" && (params.get("flow") === "guided" || params.get("purpose") === "WAREHOUSE_DISPATCH" || initial?.dispatch_purpose === "WAREHOUSE_DISPATCH" || !!initial?.destination && !!initial.cartons);
  const [guideStep, setGuideStep] = useState(0);
  const [tableBusy,setTableBusy] = useState(false); const [imported,setImported] = useState<OperationImportPreview>();
  const [confirmation, setConfirmation] = useState({ busy: false, unknown: false });
  const [place, setPlace] = useState(() => destinationValue(initial));
  const [boxes, setBoxes] = useState<Carton[]>(initial?.cartons || [{ number: "", items: [] }]);
  const mutation = initial && params.get("action") ? params.get("action") : "correct";
  const demand = !!initial && kind === "orders" && mutation === "demand-changes";
  const allocationOnly = !!initial && kind === "shipments" && mutation === "allocation-corrections";
  const [effectiveDate, setEffectiveDate] = useState(""); const [overageReason, setOverageReason] = useState("");
  const catalog = useLoad<{ items: Sku[]; demo: boolean }>("/api/production/skus?contract_version=2");
  const [orderSearch, setOrderSearch] = useState(""); const [orderPage, setOrderPage] = useState(1);
  const preferred = useLoad<Document>(`/api/production/orders/${params.get("order_id") || "0"}`, 0, kind === "shipments" && !!params.get("order_id"));
  const today = useBusinessToday();
  const [business, setBusiness] = useState(initial?.business_number || ""); const [date, setDate] = useState(initial?.business_date || today());
  const [notes, setNotes] = useState(initial?.notes || ""); const [reason, setReason] = useState(allocationOnly ? "用户整批核对来源订单归属" : "");
  const [provenance, setProvenance] = useState(Object.fromEntries(Object.keys(sourceFields).map(key => [key, initial?.[key as keyof typeof sourceFields] || ""])));
  const reviewReference = initial?.manual_source_note?.match(/出货校对=(dispatch-review-[a-f0-9]{64})/)?.[1];
  const reviewSnapshot = useLoad<{baseline:OperationImportPreview;rows:{source_row:number|null;line_id?:string|null;sku_id:string;actual_units:string}[]}>(`/api/production/shipments/table/reviews/${reviewReference}`,0,!!reviewReference);
  const restoredReview = useRef(false);
  const importedBaseline = useRef<OperationImportPreview | undefined>(undefined);
  const [reviewRestoreError,setReviewRestoreError] = useState("");
  const [manualNote, setManualNote] = useState((initial?.manual_source_note || "").split("\n").filter(line => !/^出货校对=dispatch-review-[a-f0-9]{64}$/.test(line) && !/^出货原表.+；sha256=[a-f0-9]{64}；来源=upload-shipments-[a-f0-9]{64}$/.test(line)).join("\n"));
  const [stockRefresh, setStockRefresh] = useState(0);
  const [warehouse, setWarehouse] = useState(initial?.warehouse_id || params.get("warehouse_id") || (!initial && params.get("purpose") === "WAREHOUSE_DISPATCH" ? "" : "1")); const stockScopes = useLoad<WorkbenchStock>("/api/production/inventory/availability", stockRefresh, kind === "shipments"); const selectedWarehouse = useRef(!!params.get("warehouse_id"));
  const stockPlans = useLoad<{ items: { id: string; sku_id: string; warehouse_id: string; direction: string; source_reference: string; planned_on: string | null; remaining_units: string }[] }>("/api/production/inventory/plans", 0, kind === "shipments");
  const [purpose, setPurpose] = useState(initial?.dispatch_purpose || (params.get("purpose") === "LOGISTICS_TRANSFER" ? "LOGISTICS_TRANSFER" : params.get("purpose") === "WAREHOUSE_DISPATCH" ? "WAREHOUSE_DISPATCH" : "OUTWARD_ORDER"));
  const transfer = purpose === "LOGISTICS_TRANSFER"; const warehouseDispatch = purpose === "WAREHOUSE_DISPATCH";
  const warehouseSheet=warehouseDispatch&&(!initial||initial.status==="DRAFT");
  const [dispatchValidation,setDispatchValidation]=useState<DispatchTableValidation>({pending:false});
  const cartonless = warehouseDispatch && !initial?.cartons?.length;
  const [dispatchOwner, setDispatchOwner] = useState(initial?.owner_id || params.get("owner_id") || "");
  const shipmentOwner = warehouseDispatch ? dispatchOwner : initial?.owner_id || params.get("owner_id") || "1";
  const dispatchScopes = stockScopes.value?.scopes.filter(scope => scope.warehouse_status === "ACTIVE" && ["OWN","FACTORY","THIRD_PARTY"].includes(scope.warehouse_type || "")) || [];
  const dispatchScopeReady = !warehouseDispatch || stockScopes.current && stockScopes.value?.writes_enabled === true && dispatchScopes.some(scope => scope.warehouse_id === warehouse && scope.owner_id === shipmentOwner);
  function changePurpose(next: string) { setPurpose(next); if (next === "LOGISTICS_TRANSFER" || next === "WAREHOUSE_DISPATCH") setSources(rows => rows.map(row => ({...row, allocations: [], plan_id: null, fulfillment_mode: "WAREHOUSE_STOCK"}))); }
  const sourceSubmitRef = useRef<HTMLButtonElement>(null); const [sourceReview, setSourceReview] = useState<SourceCheck>(); const [checking, setChecking] = useState(false); const [checkError, setCheckError] = useState<string>();
  const mounted = useRef(true); useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [lines, setLines] = useState<LineInput[]>(initial?.lines?.map(l => ({ id: l.id, sku_id: l.sku_id, expected_units: l.expected_units })) || [{ sku_id: "", expected_units: "" }]);
  const [sources, setSources] = useState<Source[]>(initial?.sources?.map(source => ({ ...source, fulfillment_mode: source.fulfillment_mode || "WAREHOUSE_STOCK" })) || [{ sku_id: params.get("sku_id") || "", plan_id: params.get("plan_id") || null, fulfillment_mode: "WAREHOUSE_STOCK", actual_units: "", allocations: [] }]);
  const baseline = useRef({ warehouse, business, date, notes, provenance, manualNote, purpose, dispatchOwner, effectiveDate, overageReason, reason, lines, sources, place, boxes });
  useEffect(() => {
    const saved = reviewSnapshot.value;
    if (!saved || restoredReview.current || !initial?.sources) return;
    restoredReview.current = true;
    const remaining = [...saved.rows];
    const restored = initial.sources.map(source => {
      const existing = remaining.findIndex(row => row.line_id === source.id && row.sku_id === source.sku_id && row.actual_units === source.actual_units);
      const index = existing >= 0 ? existing : remaining.findIndex(row => !row.line_id && row.sku_id === source.sku_id && row.actual_units === source.actual_units);
      const row = index < 0 ? undefined : remaining.splice(index,1)[0];
      return {...source, fulfillment_mode:source.fulfillment_mode || "WAREHOUSE_STOCK", import_row:row?.source_row ?? undefined,
        import_code:saved.baseline.source_rows?.find(original => original.row === row?.source_row)?.sku_code};
    });
    if (saved.baseline.warehouse_id !== initial.warehouse_id || saved.baseline.owner_id !== initial.owner_id || remaining.length || saved.rows.length !== initial.sources.length) {
      setReviewRestoreError("已保存商品与原表修改记录不一致，请重新导入核对后保存。");
      return;
    }
    baseline.current.sources = restored;
    importedBaseline.current = saved.baseline;
    setSources(restored);
    setImported(saved.baseline);
  },[initial,reviewSnapshot.value]);
  useEffect(() => { if (!warehouseDispatch && !initial && !selectedWarehouse.current && stockScopes.value?.scopes[0]) { selectedWarehouse.current = true; const next = stockScopes.value.scopes[0].warehouse_id; setWarehouse(next); baseline.current.warehouse = next; } }, [initial, stockScopes.value, warehouseDispatch]);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [targets, setTargets] = useState<Document[]>([]);
  const rememberTargets = useCallback((incoming: Document[]) => setTargets(current => Array.from(new Map([...current, ...incoming].map(order => [order.id, order])).values())), []);
  const [picker, setPicker] = useState<{ source: number; allocation: number }>();
  const pickerSku = picker ? sources[picker.source]?.sku_id || "" : "";
  const candidates = useLoad<DocumentPage>(`/api/production/orders?status=CONFIRMED&page=${orderPage}&selectable=true&sku=${encodeURIComponent(pickerSku)}&q=${encodeURIComponent(orderSearch)}`, 0, kind === "shipments" && !!pickerSku);
  useEffect(() => { const incoming = [...(candidates.value?.items || []), ...(preferred.value ? [preferred.value] : [])]; setTargets(current => Array.from(new Map([...current, ...incoming].map(o => [o.id, o])).values())); }, [candidates.value, preferred.value]);
  useEffect(() => { if (initial || warehouseDispatch || !preferred.value?.lines?.length) return; const l = preferred.value.lines.find(line => line.tracking_state !== "CLOSED"); if (!l) return; setSources(current => { const first = current[0]; if (!first || current.length !== 1 || first.sku_id || first.allocations.length) return current; baseline.current.sources = [{ ...baseline.current.sources[0]!, sku_id: l.sku_id, allocations: [{ order_line_id: l.id, units: "" }] }]; return [{ ...first, sku_id: l.sku_id, allocations: [{ order_line_id: l.id, units: first.actual_units }] }]; }); }, [initial, preferred.value, warehouseDispatch]);
  const finish=(result:Document)=>{leave.allowLeave();void navigate(`/production/${kind}/${result.id}${contextQuery}${kind==="shipments"&&result.status==="CONFIRMED"?"#transport":""}`,{state:editorLocation.state as unknown});};
  const command = useCommand(finish);
  const locked = command.busy || command.unknown || checking || tableBusy || confirmation.busy || confirmation.unknown;
  const dirty = imported !== importedBaseline.current || JSON.stringify(baseline.current) !== JSON.stringify({ warehouse, business, date, notes, provenance, manualNote, purpose, dispatchOwner, effectiveDate, overageReason, reason, lines, sources, place, boxes });
  const leave = useProductionLeave(dirty, locked, command.unknown || confirmation.unknown);
  const preferredOpen = preferred.value?.lines?.find(line => line.tracking_state !== "CLOSED");
  const preferredClosed = !!preferred.value?.lines?.length && !preferredOpen;
  function focusField(key: string) { requestAnimationFrame(() => document.getElementById(productionFieldId(key))?.focus()); }
  async function save(mode: "draft" | "confirm", reviewed = false) {
    if (locked) return;
    if(reviewReference && (!restoredReview.current || reviewSnapshot.error || reviewRestoreError)){setCheckError(reviewRestoreError || reviewSnapshot.error || "正在读取原表修改记录，请稍后再保存。");return;}
    if(imported&&(imported.warehouse_id!==warehouse||imported.owner_id!==shipmentOwner)){setCheckError("仓库或货主已改变，请重新读取当前范围的出货表；原填写内容保留。");return;}
    if (!dispatchScopeReady) { setCheckError("请先选择已建账且可办理出货的来源仓库；读取失败或状态待核时不能保存或发货。"); setGuideStep(0); return; }
    if (guided && mode === "confirm") {
      if (!place.destination.trim()) { setCheckError("请选择或填写实际目的地。"); setGuideStep(0); return; }
      const issue = cartonless ? undefined : packingError(packingProducts, boxes);
      if (issue) { setCheckError(issue); setGuideStep(2); return; }
    }
    const errors = validateProductionInput(kind, { date, lines, sources, reason, effectiveDate, demand, transfer, warehouseDispatch, allocationOnly, confirmedEdit: initial?.status === "CONFIRMED", confirm: mode === "confirm" });
    if (warehouseDispatch) sources.forEach((source, i) => { if (!stockScopes.value?.items.some(item => item.warehouse_id === warehouse && item.owner_id === shipmentOwner && item.sku_id === source.sku_id)) errors[`source-${i}-sku`] = "该商品在当前来源仓及货权未建账，请重新选择；原填写数量已保留。"; });
    setFieldErrors(errors); setCheckError(undefined);
    const firstError = Object.keys(errors)[0];
    if (firstError) { if (guided) setGuideStep(firstError === "date" ? 0 : firstError === "reason" ? 3 : 1); focusField(firstError); return; }
    if(mode==="confirm"&&warehouseSheet&&(dispatchValidation.pending||dispatchValidation.error)){setCheckError(dispatchValidation.error||"正在核对当前可发量，请稍后再继续。");return;}
    let reviewId = reviewReference;
    if (imported && cartonless) {
      setChecking(true);
      try {
        const saved = await writeApi<{review_id:string}>("/api/production/shipments/table/reviews",{body:{
          source_id:imported.source_id, layout:imported.source_layout || "standard",
          ...(imported.source_files ? {sources:imported.source_files.map(file=>({source_id:file.source_id,layout:file.source_layout}))} : {}),
          warehouse_id:warehouse, owner_id:shipmentOwner,
          rows:sources.map(source => ({source_row:source.import_row ?? null,line_id:source.id ?? null,sku_id:source.sku_id,actual_units:source.actual_units})),
        },idempotent:false});
        if (!mounted.current) return;
        reviewId = saved.review_id;
      } catch (error) {
        if (mounted.current) setCheckError(error instanceof Error ? error.message : "原表修改记录未保存，请重试。");
        return;
      } finally { if (mounted.current) setChecking(false); }
    }
    const body: Record<string, unknown> = { ...provenance, manual_source_note: [manualNote, imported ? `出货原表${imported.filename}；sha256=${imported.source_digest}；来源=${imported.source_id}` : "", reviewId ? `出货校对=${reviewId}` : ""].filter(Boolean).join("\n"), ...(kind === "shipments" ? { dispatch_purpose: purpose, ...(sources.some(source => source.fulfillment_mode !== "PRODUCTION_DIRECT") ? { warehouse_id: warehouse, owner_id: shipmentOwner } : {}) } : {}), ...(guided ? { ...place, ...(cartonless ? {cartons:null} : {cartons: boxes.filter(box => box.number.trim() || box.items.some(item => /^[1-9][0-9]*$/.test(item.units))).map(box => ({ number: box.number.trim(), items: box.items.filter(item => /^[1-9][0-9]*$/.test(item.units)) }))}) } : {}), overage_reason: overageReason, business_number: business, business_date: date, notes, ...(kind === "orders" ? { lines } : { sources: sources.map(s => ({ id: s.id, replaces_source_id: s.replaces_source_id, sku_id: s.sku_id, plan_id: s.fulfillment_mode === "PRODUCTION_DIRECT" ? null : s.plan_id ?? null, fulfillment_mode: s.fulfillment_mode || "WAREHOUSE_STOCK", actual_units: s.actual_units, allocations: s.allocations.map(a => ({ order_line_id: a.order_line_id, units: a.units })) })) }) };
    if (!initial && mode === "confirm" && !reviewed) {
      setChecking(true); setCheckError(undefined);
      try { const check = await writeApi<SourceCheck>(`/api/production/sources/${kind}/check`, { body, idempotent: false }); if (!mounted.current) return; if (check.candidates.length || check.duplicate_document) { setSourceReview(check); return; } }
      catch (e) { if (mounted.current) setCheckError(e instanceof Error ? e.message : "来源核对未完成。"); return; }
      finally { if (mounted.current) setChecking(false); }
    }
    if (initial) { body.expected_revision = initial.revision; if (initial.status === "CONFIRMED") body.reason = reason; if (demand) body.effective_date = effectiveDate; }
    else body.save_mode = mode;
    const path = `/api/production/${kind}${initial ? `/${initial.id}${initial.status === "CONFIRMED" ? `/${demand ? "demand-changes" : allocationOnly ? "allocation-corrections" : "correct"}` : ""}` : ""}`;
    command.submit(path, body, initial?.status === "DRAFT" ? "PUT" : "POST");
    setSourceReview(undefined);
  }
  const skuOptions = catalog.value?.items.filter(s => !warehouseDispatch || stockScopes.value?.items.some(item => item.warehouse_id === warehouse && item.owner_id === shipmentOwner && item.sku_id === s.sku_id) || sources.some(source => source.sku_id === s.sku_id)).map(s => ({ value: s.sku_id, label: s.code || (s.style_code && s.standard_color && s.standard_size ? `${s.style_code} · ${s.standard_color} · ${s.standard_size}` : s.label) })) || [];
  function stockOptionLabel(sku: string) { if (!warehouseDispatch) return ""; const balance=stockScopes.value?.items.find(item => item.warehouse_id===warehouse && item.owner_id===shipmentOwner && item.sku_id===sku); return balance ? ` · 可发${balance.state === "ready" && balance.free_available_units != null ? `${units(balance.free_available_units)}件` : "待核"}` : " · 本仓未建账"; }
  function changeSource(index: number, patch: Partial<Source>) { setFieldErrors({}); setSources(current => current.map((s, i) => i === index ? { ...s, ...patch } : s)); }
  const proposedOverages: { label: string; quantity: string }[] = [];
  if (demand && initial?.lines) for (const line of lines) {
    const old = initial.lines.find(l => l.sku_id === line.sku_id);
    if (old && /^[0-9]+$/.test(line.expected_units)) { const over = BigInt(old.actual_units) - BigInt(line.expected_units); if (over > 0n) proposedOverages.push({ label: old.sku_label, quantity: over.toString() }); }
  }
  if (kind === "shipments") for (const target of targets) for (const line of target.lines || []) {
    const current = sources.flatMap(s => s.allocations).filter(a => a.order_line_id === line.id);
    if (!current.length || !current.every(a => /^[0-9]+$/.test(a.units))) continue;
    const former = initial?.sources?.flatMap(s => s.allocations).filter(a => a.order_line_id === line.id).reduce((sum, a) => sum + BigInt(a.units), 0n) || 0n;
    const over = BigInt(line.actual_units) - former + current.reduce((sum, a) => sum + BigInt(a.units), 0n) - BigInt(line.expected_units);
    if (over > 0n) proposedOverages.push({ label: `${target.business_number || target.system_number} · ${line.sku_label}`, quantity: over.toString() });
  }
  const packingProducts = [...new Set(sources.filter(source => source.sku_id).map(source => source.sku_id))].map(sku_id => ({ sku_id, label: skuOptions.find(option => option.value === sku_id)?.label || `SKU ${sku_id}`, units: sources.filter(source => source.sku_id === sku_id).reduce((sum, source) => sum + (/^[1-9][0-9]*$/.test(source.actual_units) ? BigInt(source.actual_units) : 0n), 0n).toString() }));
  function applyDispatchTable(result:OperationImportPreview) {
    if (cartonless) {
      const originalRows:NonNullable<OperationImportPreview["source_rows"]> = result.source_rows ?? result.rows.map(row => ({row:row.row,sku_code:row.sku_label,sku_id:row.sku_id,units:row.units ?? null,source_cell:""}));
      const previousRows = new Set(imported?.source_rows?.map(row=>row.row));
      const appending = !!imported && !!result.source_files && result.source_files[0]?.source_id === imported.source_id;
      const usedSources = new Set<Source>();
      const next = originalRows.flatMap<Source>(row => {
        if (appending && previousRows.has(row.row)) {
          const current = sources.find(source=>source.import_row===row.row);
          return current ? [current] : [];
        }
        const previous = appending ? undefined : sources.find(source => !!row.sku_id && source.sku_id === row.sku_id && !usedSources.has(source));
        if (previous) usedSources.add(previous);
        return [{
          ...previous,
          sku_id:row.sku_id || "", sku_label:row.sku_code, import_code:row.sku_code, import_row:row.row,
          actual_units:row.units ?? "", allocations:[], fulfillment_mode:"WAREHOUSE_STOCK",
          plan_id:previous?.plan_id || null,
        }];
      });
      if (appending) next.push(...sources.filter(source=>source.import_row===undefined && !!source.sku_id));
      setSources(next);
    } else {
      const totals = new Map<string,bigint>();
      for (const row of result.rows) totals.set(row.sku_id,(totals.get(row.sku_id) || 0n)+BigInt(row.units!));
      setSources([...totals].map(([sku_id,quantity]) => ({...sources.find(source => source.sku_id === sku_id),sku_id,actual_units:String(quantity),allocations:[],fulfillment_mode:"WAREHOUSE_STOCK"})));
      setBoxes(result.cartons.length ? result.cartons : [{number:"",items:[]}]);
    }
    setImported(result); setManualNote(previous => previous || `表格资料：${result.filename}`); setFieldErrors({}); setCheckError("");
  }
  const importOriginals = imported?.source_files ? <Disclosure><summary>查看{imported.source_files.length}份出货原表</summary>{imported.source_files.map(file=><LinkButton key={file.source_id} variant="quiet" to={`/api/production/shipments/table/sources/${file.source_id}`} reloadDocument download>{file.filename}</LinkButton>)}</Disclosure> : <LinkButton variant="quiet" to={`/api/production/shipments/table/sources/${imported?.source_id}`} reloadDocument download>查看出货原表</LinkButton>;
  const dispatchImport = warehouseDispatch && !allocationOnly && <OperationTableImport inline={cartonless} existing={cartonless ? imported : undefined} kind="packing" warehouse={{warehouse_id:warehouse,owner_id:shipmentOwner}} context={JSON.stringify({warehouse,owner:shipmentOwner})} eligible={stockScopes.value?.items.filter(item=>item.warehouse_id===warehouse&&item.owner_id===shipmentOwner).map(item=>item.sku_id)||[]} locked={locked||!dispatchScopeReady} onBusy={setTableBusy} onApply={applyDispatchTable}/>;
  const unmatchedImported = sources.filter(source => !source.sku_id && source.import_code).length;
  const dispatchCount = new Set(sources.map(source => source.sku_id || source.import_code).filter(Boolean)).size;
  const dispatchTotal = sources.reduce((sum,source) => sum + (/^[1-9][0-9]{0,18}$/.test(source.actual_units) ? BigInt(source.actual_units) : 0n),0n).toString();
  const steps = cartonless ? ["来源与目的地", "本批出货明细", initial?.status === "CONFIRMED" ? "核对更正" : "核对并发货"] : ["来源与目的地", "填写出货数量", "完成装箱", initial?.status === "CONFIRMED" ? "核对更正" : "核对并发货"];
  const visibleGuideStep=cartonless && guideStep===3 ? 2 : guideStep;
  function advanceGuide() {
    if (locked) return;
    setCheckError(undefined);
    if (guideStep === 0 && !dispatchScopeReady) { setCheckError("请选择已建账且可办理出货的来源仓库；FBA源出库不在此入口办理。"); return; }
    if (guideStep === 0 && (!date || !place.destination.trim())) { setCheckError(!date ? "请选择业务日期。" : "请选择或填写实际目的地。"); return; }
    if (guideStep === 1) {
      const errors = validateProductionInput("shipments", { date, lines, sources, reason, effectiveDate, demand: false, transfer, warehouseDispatch, confirmedEdit: false, confirm: true });
      if (warehouseDispatch) sources.forEach((source, i) => { if (!stockScopes.value?.items.some(item => item.warehouse_id === warehouse && item.owner_id === shipmentOwner && item.sku_id === source.sku_id)) errors[`source-${i}-sku`] = "该商品在当前来源仓及货权未建账，请重新选择。"; });
      if (cartonless && imported) sources.forEach((source,index) => {
        if (!source.sku_id && source.import_code) delete errors[`source-${index}-sku`];
      });
      setFieldErrors(errors);
      if (Object.keys(errors).length) { focusField(Object.keys(errors)[0]!); return; }
      if(warehouseSheet&&(dispatchValidation.pending||dispatchValidation.error)){setCheckError(dispatchValidation.error||"正在核对当前可发量，请稍后再继续。");if(dispatchValidation.field)focusField(dispatchValidation.field);return;}
    }
    if (guideStep === 2) { const issue = packingError(packingProducts, boxes); if (issue) { setCheckError(issue); return; } }
    setGuideStep(value => cartonless && value===1 ? 3 : Math.min(3, value + 1));
  }
  const dispatchWarehouseName=dispatchScopes.find(scope=>scope.warehouse_id===warehouse&&scope.owner_id===shipmentOwner)?.warehouse_name||"来源仓待核";
  const sourceEvidence = <>
    <FormField label="人工来源及区别说明"><Input disabled={locked || demand || allocationOnly} maxLength={2000} value={manualNote} onChange={e => setManualNote(e.target.value)} /></FormField>
      <Disclosure><summary>可靠来源凭据（有资料时填写）</summary><div className={styles.fields}>{Object.entries(sourceFields).map(([key, label]) => <FormField label={label} key={key}><Input disabled={locked || initial?.status === "CONFIRMED"} value={provenance[key] || ""} maxLength={key === "source_event_kind" ? 64 : 120} onChange={e => setProvenance(current => ({ ...current, [key]: e.target.value }))} /></FormField>)}</div><p>前三项共同标识事件，批次用于区分合法分批。按原始凭据填写；业务显示号不是唯一键。</p></Disclosure>
      {kind === "shipments" && !warehouseDispatch && <FormField label="发运用途">{guided ? <select aria-label="发运用途" disabled={locked || allocationOnly} value={purpose} onChange={event => changePurpose(event.target.value)}>{([{ value: "OUTWARD_ORDER", label: "订单对外发运（已交接）" }, { value: "INTERNAL_HANDOVER", label: "同址厂内移交" }, { value: "PRODUCTION_COMPLETION", label: "生产完工" }, { value: "WAREHOUSE_RECEIPT", label: "仓库入库" }, { value: "LOGISTICS_TRANSFER", label: "仓间运输发运（不累计订单）" }, { value: "LEGACY_UNCLASSIFIED", label: "旧资料（用途未核对）" }]).map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : <GlideSelectField value={purpose} disabled={locked || allocationOnly} ariaLabel="发运用途" onChange={changePurpose} options={[{ value: "OUTWARD_ORDER", label: "订单对外发运（已交接）" }, { value: "INTERNAL_HANDOVER", label: "同址厂内移交" }, { value: "PRODUCTION_COMPLETION", label: "生产完工" }, { value: "WAREHOUSE_RECEIPT", label: "仓库入库" }, { value: "LOGISTICS_TRANSFER", label: "仓间运输发运（不累计订单）" }, { value: "LEGACY_UNCLASSIFIED", label: "旧资料（用途未核对）" }]} />}</FormField>}

  </>;
  const editor = <>{transfer && <StatusMessage kind="info" title="仓间运输发运">使用本仓已入库成品，货权保持不变；本单独立扣来源库存，不再次累计生产订单已发。运输时间与预计到达在确认后登记，目的仓实收后才增加目的库存。</StatusMessage>}{!guided && <PageHeader title={`${initial ? demand ? "需求变更 · " : allocationOnly ? "调整订单归属 · " : initial.status === "CONFIRMED" ? "更正" : "编辑草稿" : "创建"}${kindName[kind]}`} description={allocationOnly ? "只调整订单归属，来源身份、SKU、发运日期和实际件数保持。" : demand ? "正式追加、减少需求或新增SKU行；累计实际出货保持。" : initial ? "每个数量均为整数件数。录入更正保留前值及原因。" : "可手工录入，也可从标准XLSX导入。一份文件对应一张单据，导入先预览后确认。"} actions={!initial && <Button variant="secondary" disabled={locked} onClick={() => { void navigate(`/production/${kind}/intake?method=table`); }}>从Excel导入</Button>} />}
    {!guided && !initial && kind === "shipments" && <StatusMessage kind="info" title="按步骤办理出货"><LinkButton variant="secondary" to={`?${new URLSearchParams({ ...Object.fromEntries(params), flow: "guided" })}`}>使用分步出货向导</LinkButton><p>保留已选商品、来源订单及关联安排，按步骤填写目的地和装箱明细。</p></StatusMessage>}
    {catalog.value?.demo && !initial && <Button variant="quiet" disabled={locked || preferredClosed} onClick={() => { setFieldErrors({}); const sku = preferredOpen?.sku_id || catalog.value?.items[0]?.sku_id || ""; if (kind === "orders") setLines([{ sku_id: sku, expected_units: "100" }]); else setSources([{ sku_id: sku, actual_units: "40", allocations: preferredOpen ? [{ order_line_id: preferredOpen.id, units: "40" }] : [] }]); }}>载入虚构示例</Button>}
    {preferredClosed && <StatusMessage kind="warning" title="关联订单已关闭跟进" action={<Link to={`/production/orders/${preferred.value?.id}`}>返回订单，先恢复跟进</Link>}>没有可登记出货的开放明细。恢复所需SKU行后，再从订单记录本次出货。</StatusMessage>}
    {!!proposedOverages.length && <StatusMessage kind="warning" title="保存后的超发提示">{proposedOverages.map(o => <p key={o.label}>{o.label}：超发{o.quantity}件。保留真实数量并填写说明，保存时会按最新数据复核。</p>)}</StatusMessage>}
    {imported&&(warehouseSheet?<div className={styles.dispatchImportSource}><span title={imported.filename}>{imported.filename}</span><strong>原表{imported.source_total_units ?? imported.total_units}件</strong>{importOriginals}</div>:<StatusMessage kind="info" title={`已填入${imported.total_units}件${cartonless ? "" : ` · ${imported.box_count}箱`}`}>{importOriginals}</StatusMessage>)}{command.feedback}{kind === "shipments" && command.errorCode === "insufficient_available_stock" && <p className={styles.secondary}>仓库库存出货商品：{Array.from(new Set(sources.filter(source => source.fulfillment_mode !== "PRODUCTION_DIRECT").map(source => source.sku_id))).map(id => `${skuOptions.find(option => option.value === id)?.label || `SKU ${id}（身份待核）`}（SKU ${id}）`).join("、")}。请按提示的当前允许量调整本次出货，确认时服务端会重新核对。</p>}{!catalog.value && <ReadState error={catalog.error} />}
    {checkError && <StatusMessage kind="danger" title={guided ? "请核对本次出货" : "来源核对未完成"}>{checkError}</StatusMessage>}
    {!!Object.keys(fieldErrors).length && <StatusMessage kind="danger" title="请完善以下信息"><ul>{Object.entries(fieldErrors).map(([key, message]) => <li key={key}><button type="button" className={styles.errorLink} onClick={() => focusField(key)}>{message}</button></li>)}</ul></StatusMessage>}
    <form className={styles.body} onChangeCapture={() => setFieldErrors({})} onSubmit={e => { e.preventDefault(); if (guided) advanceGuide(); else void save("draft"); }}><fieldset style={guided && guideStep !== 0 ? { display: "none" } : undefined} disabled={locked || demand || allocationOnly} className={`${styles.panel} ${guided&&warehouseDispatch?styles.shipmentSetup:""}`}><legend>单据信息</legend>{!(guided&&warehouseDispatch)&&<div className={styles.fields}><FormField label="业务单号（可选）"><Input value={business} maxLength={120} onChange={e=>setBusiness(e.target.value)}/></FormField><FormField label="业务日期" required error={fieldErrors.date}><Input id={productionFieldId("date")} type="date" value={date} onChange={e=>setDate(e.target.value)}/></FormField><FormField label="备注"><Input value={notes} maxLength={2000} onChange={e=>setNotes(e.target.value)}/></FormField></div>}{guided&&warehouseDispatch&&<><div className={styles.shipmentRoute}><WarehouseField label="来源仓库" scopes={dispatchScopes} value={warehouse&&shipmentOwner?`${warehouse}:${shipmentOwner}`:""} onChange={value=>{const [nextWarehouse,nextOwner]=value.split(":");selectedWarehouse.current=true;setWarehouse(nextWarehouse||"");setDispatchOwner(nextOwner||"");}}/><DestinationField compact required value={place} onChange={setPlace} defaultFba={!initial} onDefault={next=>{setPlace(next);baseline.current.place=next;}}/><FormField label="业务日期" required error={fieldErrors.date}><Input id={productionFieldId("date")} type="date" value={date} onChange={e=>setDate(e.target.value)}/></FormField></div>{stockScopes.error&&<StatusMessage kind="danger" title="来源仓库存读取失败" action={<Button variant="secondary" onClick={()=>setStockRefresh(value=>value+1)}>重新读取来源库存</Button>}>{stockScopes.error}</StatusMessage>}{stockScopes.value&&!dispatchScopes.length&&<StatusMessage kind="warning" title="没有可办理出货的已建账仓库">请先核对仓库和库存账；FBA库存沿原平台事件流程管理。</StatusMessage>}<Disclosure className={styles.shipmentNotes}><summary>单号与备注（选填）</summary><div className={styles.fields}><FormField label="业务单号（可选）"><Input value={business} maxLength={120} onChange={e=>setBusiness(e.target.value)}/></FormField><FormField label="备注"><Input value={notes} maxLength={2000} onChange={e=>setNotes(e.target.value)}/></FormField></div></Disclosure></>}{guided && !warehouseDispatch && <DestinationField required value={place} onChange={setPlace} defaultFba={warehouseDispatch && !initial} onDefault={next => { setPlace(next); baseline.current.place = next; }} />}</fieldset>
    <fieldset style={guided && guideStep !== 1 ? { display: "none" } : undefined} disabled={locked} data-dispatch-table={warehouseSheet||undefined} className={`${styles.panel} ${warehouseSheet?styles.dispatchTablePanel:""}`}>{kind === "shipments" && !warehouseDispatch && sources.some(source => source.fulfillment_mode !== "PRODUCTION_DIRECT") && <FormField label="仓库库存出货所用仓库" hint="仅用于选择“仓库库存出货”的明细；生产直发不进入仓库、不扣仓库库存。"><select disabled={allocationOnly} value={warehouse} onChange={e => { selectedWarehouse.current = true; setWarehouse(e.target.value); }}>{stockScopes.value?.scopes.length ? stockScopes.value.scopes.map(w => <option key={w.warehouse_id} value={w.warehouse_id}>{w.warehouse_name}</option>) : <option value={warehouse}>演练默认仓库（库存尚未启用）</option>}</select></FormField>}<legend>{kind === "orders" ? "预计SKU明细" : transfer ? "本次仓间发运明细" : warehouseDispatch ? "本次仓库出货商品" : "本次实际出货及订单归属"}</legend>{warehouseDispatch&&dispatchImport}
      {kind === "orders" ? <>{lines.map((line, i) => <div key={i} className={styles.line}><FormField label={`SKU ${i + 1}`} required error={fieldErrors[`line-${i}-sku`]} hint={skuOptions.find(o => o.value === line.sku_id)?.label}><GlideSelectField id={productionFieldId(`line-${i}-sku`)} ariaLabel={`SKU ${i + 1}`} placeholder="请选择SKU" menuWidth={340} disabled={locked || (initial?.status === "CONFIRMED" && !!line.id)} options={skuOptions} value={line.sku_id} onChange={value => { setFieldErrors({}); setLines(current => current.map((l, n) => n === i ? { ...l, sku_id: value } : l)); }} /></FormField><FormField label={`预计数量 ${i + 1}`} required error={fieldErrors[`line-${i}-units`]}><Input id={productionFieldId(`line-${i}-units`)} inputMode="numeric" value={line.expected_units} onChange={e => setLines(current => current.map((l, n) => n === i ? { ...l, expected_units: e.target.value } : l))} /></FormField><Button disabled={locked || lines.length === 1} variant="quiet" onClick={() => { setFieldErrors({}); setLines(lines.filter((_, n) => n !== i)); }}>移除明细</Button></div>)}<Button disabled={initial?.status === "CONFIRMED" && !demand} variant="secondary" onClick={() => setLines([...lines, { sku_id: skuOptions[0]?.value || "", expected_units: "" }])}>添加SKU明细</Button></> : <>
        {allocationOnly?<ShipmentOrderAttribution onOrdersRead={rememberTargets} confirmedSources={initial?.status === "CONFIRMED" ? initial.sources : undefined} errors={fieldErrors} sources={sources} shipment={{warehouse_id:warehouse,owner_id:shipmentOwner,destination_id:initial?.destination_id}} catalog={catalog.value?.items||[]} locked={locked} change={changeSource} search={(source,allocation)=>setPicker({source,allocation})}/>:warehouseSheet?<WarehouseDispatchTable sources={sources} options={skuOptions} warehouse={warehouse} owner={shipmentOwner} warehouseName={dispatchScopes.find(scope=>scope.warehouse_id===warehouse&&scope.owner_id===shipmentOwner)?.warehouse_name||""} destination={place.destination} date={date} plans={stockPlans.value?.items||[]} fieldErrors={fieldErrors} locked={locked} refresh={stockRefresh} validationChanged={setDispatchValidation} change={(index,patch)=>{setCheckError(undefined);if(patch.sku_id!==undefined){const source=sources[index];const original=initial?.sources?.find(s=>s.id===(source?.id||source?.replaces_source_id));changeSource(index,{...patch,id:original&&original.sku_id===patch.sku_id?original.id:undefined,replaces_source_id:original&&original.sku_id!==patch.sku_id?original.id:undefined});}else changeSource(index,patch);}} add={()=>setSources(current=>[...current,{sku_id:skuOptions[0]?.value||"",fulfillment_mode:"WAREHOUSE_STOCK",actual_units:"",allocations:[]}])} remove={index=>{setCheckError(undefined);setFieldErrors({});setSources(current=>current.length>1?current.filter((_,i)=>i!==index):[{sku_id:"",actual_units:"",fulfillment_mode:"WAREHOUSE_STOCK",allocations:[]}]);}}/>:<>
        {sources.map((source, i) => <section className={styles.panel} key={i}><div className={styles.line}><FormField label={`出货SKU ${i + 1}`} required error={fieldErrors[`source-${i}-sku`]} hint={skuOptions.find(o => o.value === source.sku_id)?.label}>{guided ? <select id={productionFieldId(`source-${i}-sku`)} aria-label={`出货SKU ${i + 1}`} disabled={locked || allocationOnly} value={source.sku_id} onChange={event => { const value = event.target.value; { const original = initial?.sources?.find(s => s.id === (source.id || source.replaces_source_id)); changeSource(i, { id: original && original.sku_id === value ? original.id : undefined, replaces_source_id: original && original.sku_id !== value ? original.id : undefined, sku_id: value, plan_id: null, allocations: [] }); } }}><option value="">请选择出货SKU</option>{skuOptions.map(option => <option key={option.value} value={option.value}>{option.label}{stockOptionLabel(option.value)}</option>)}</select> : <GlideSelectField id={productionFieldId(`source-${i}-sku`)} ariaLabel={`出货SKU ${i + 1}`} placeholder="请选择出货SKU" menuWidth={340} disabled={locked || allocationOnly} options={skuOptions} value={source.sku_id} onChange={value => { const original = initial?.sources?.find(s => s.id === (source.id || source.replaces_source_id)); changeSource(i, { id: original && original.sku_id === value ? original.id : undefined, replaces_source_id: original && original.sku_id !== value ? original.id : undefined, sku_id: value, plan_id: null, allocations: [] }); }} />}</FormField><FormField label={`本次实际数量 ${i + 1}`} required error={fieldErrors[`source-${i}-units`]}><Input id={productionFieldId(`source-${i}-units`)} disabled={allocationOnly} inputMode="numeric" value={source.actual_units} onChange={e => changeSource(i, { actual_units: e.target.value })} /></FormField><FormField label={`货物来源 ${i + 1}`}>{warehouseDispatch ? <p>仓库库存出货</p> : <select aria-label={`货物来源 ${i + 1}`} disabled={allocationOnly || transfer} value={source.fulfillment_mode || "WAREHOUSE_STOCK"} onChange={e => changeSource(i, { fulfillment_mode: e.target.value as Source["fulfillment_mode"], plan_id: e.target.value === "PRODUCTION_DIRECT" ? null : source.plan_id })}><option value="WAREHOUSE_STOCK">仓库库存出货</option><option value="PRODUCTION_DIRECT">生产完成后直接出货</option></select>}</FormField><Button variant="quiet" disabled={locked || allocationOnly || sources.length === 1} onClick={() => { setFieldErrors({}); setSources(sources.filter((_, n) => n !== i)); }}>移除来源</Button></div>
          {source.fulfillment_mode === "PRODUCTION_DIRECT" ? <StatusMessage kind="info" title="生产直发，不影响仓库库存">这批货从生产完成后直接发出，仍计入实际出货和订单履约；不入库、不扣库存，也不占用预计出库安排。</StatusMessage> : <>{!transfer && !allocationOnly && <><FormField label={`来源 ${i + 1} 的预计出库安排（可选）`}><select disabled={locked || allocationOnly} value={source.plan_id || ""} onChange={e => changeSource(i, { plan_id: e.target.value || null })}><option value="">不关联预计出库安排</option>{stockPlans.value?.items.filter(plan => plan.direction === "OUT" && plan.sku_id === source.sku_id && plan.warehouse_id === warehouse && (BigInt(plan.remaining_units) > 0n || plan.id === source.plan_id)).map(plan => <option key={plan.id} value={plan.id}>{plan.source_reference} · {plan.planned_on || "日期待安排"} · 剩余 {plan.remaining_units} 件</option>)}</select></FormField>{source.plan_id && <Link to={`/production/stock/plans#plan-${source.plan_id}`}>查看关联安排</Link>}</>}{!allocationOnly && (!initial || initial.status !== "CONFIRMED" || initial.stock_tracked) && <DispatchStock source={source} warehouse={warehouse} owner={shipmentOwner} />}</>}{!transfer && (!warehouseDispatch || allocationOnly) && <>{source.allocations.map((a, n) => <div className={styles.allocation} key={n}><FormField label={`来源 ${i + 1} 的订单分配 ${n + 1}`} required error={fieldErrors[`allocation-${i}-${n}-order`]}><Button id={productionFieldId(`allocation-${i}-${n}-order`)} className={styles.relationButton} disabled={locked} onClick={() => setPicker({ source: i, allocation: n })}>{(() => { const order = targets.find(o => o.lines?.some(l => l.id === a.order_line_id)); const line = order?.lines?.find(l => l.id === a.order_line_id); return order && line ? <><strong>{order.business_number || `订单 ${order.system_number.slice(-8)}`}</strong><span>{order.business_date} · {line.sku_label}</span><span>预计{units(line.expected_units)} · 已发{units(line.actual_units)} · 待跟进{units(line.pending_units)}件 · {line.tracking_state === "CLOSED" ? "已关闭" : "跟进中"}</span><small>系统编号：{order.system_number}</small></> : a.order_business_number || a.order_number || "选择已确认订单明细"; })()}</Button></FormField><FormField label={`分配数量 ${i + 1}-${n + 1}`} required error={fieldErrors[`allocation-${i}-${n}-units`]}><Input id={productionFieldId(`allocation-${i}-${n}-units`)} inputMode="numeric" value={a.units} onChange={e => changeSource(i, { allocations: source.allocations.map((old, j) => j === n ? { ...old, units: e.target.value } : old) })} /></FormField><Button variant="quiet" onClick={() => changeSource(i, { allocations: source.allocations.filter((_, j) => j !== n) })}>移除分配</Button></div>)}
          <div className={styles.actions}>{source.allocations.length === 1 && <Button variant="secondary" disabled={locked || !/^[1-9][0-9]*$/.test(source.actual_units) || !source.allocations[0]?.order_line_id} onClick={() => changeSource(i, { allocations: source.allocations.map(a => ({ ...a, units: source.actual_units })) })}>全部分配到此订单</Button>}<Button id={productionFieldId(`source-${i}-allocations`)} variant="secondary" onClick={() => changeSource(i, { allocations: [...source.allocations, { order_line_id: "", units: source.actual_units }] })}>添加订单分配</Button></div>{fieldErrors[`source-${i}-allocations`] && <p role="alert" className={styles.fieldError}>{fieldErrors[`source-${i}-allocations`]}</p>}<p aria-live="polite">{(() => { if (![source.actual_units, ...source.allocations.map(a => a.units)].every(v => /^[0-9]+$/.test(v))) return "填写本次实际数量后，再核对订单分配。"; const total = source.allocations.reduce((sum, a) => sum + BigInt(a.units), 0n); const unallocated = BigInt(source.actual_units) - total; return `已分配 ${total} 件，${unallocated < 0n ? `多分配 ${-unallocated}` : `未分配 ${unallocated}`} 件。确认时分配合计须等于本次实际数量。`; })()}</p></>}
        </section>)}<Button disabled={allocationOnly} variant="secondary" onClick={() => setSources([...sources, { sku_id: skuOptions[0]?.value || "", fulfillment_mode: "WAREHOUSE_STOCK", actual_units: "", allocations: [] }])}>添加出货来源</Button>
      </>}
      </>}
    </fieldset>
    <Dialog contentClassName={styles.productionDialog} open={!!picker} onOpenChange={open => { if (!open) setPicker(undefined); }} title="选择已确认订单明细" description="只显示当前SKU的开放明细；按单号、日期、已发与待跟进核对归属。">
      <FormField label="查找已确认订单"><Input value={orderSearch} onChange={e => { setOrderSearch(e.target.value); setOrderPage(1); }} placeholder="系统号或业务单号" /></FormField>
      {candidates.error && <ReadState error={candidates.error} />}
      {!candidates.value && !candidates.error && <ReadState />}
      <div className={styles.choiceList}>{candidates.value?.items.flatMap(o => (o.lines || []).filter(l => l.tracking_state !== "CLOSED" && l.sku_id === (picker ? sources[picker.source]?.sku_id : "")).map(l => <Button variant="secondary" className={styles.relationButton} key={l.id} onClick={() => { if (!picker) return; const source = sources[picker.source]; if (!source) return; changeSource(picker.source, { allocations: source.allocations.map((a, n) => n === picker.allocation ? { order_line_id: l.id, units: a.units } : a) }); setPicker(undefined); }}><strong>{o.business_number || `订单 ${o.system_number.slice(-8)}`}</strong><span>{o.business_date} · {l.sku_label}</span><span>预计{units(l.expected_units)} · 已发{units(l.actual_units)} · 待跟进{units(l.pending_units)}件</span><small>系统编号：{o.system_number}</small></Button>))}{candidates.value?.total === 0 && <p>没有匹配的开放明细，请调整单号搜索，或返回订单恢复所需SKU行。</p>}</div>
      {candidates.value && <><Pagination itemLabel="订单" page={candidates.value.page} totalItems={candidates.value.total} totalPages={Math.max(1, Math.ceil(candidates.value.total / candidates.value.page_size))} onPageChange={setOrderPage} /><p>已按当前SKU筛选，可搜索或切页查找匹配订单。</p></>}<div className={styles.dialogActions}><Button variant="secondary" onClick={() => setPicker(undefined)}>取消选择</Button></div>
    </Dialog>
    {initial?.status === "CONFIRMED" && (!guided || guideStep === 3) && <FormField label={demand ? "需求变更原因" : allocationOnly ? "归属调整原因" : "更正原因"} required error={fieldErrors.reason}><Input id={productionFieldId("reason")} disabled={locked} value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} /></FormField>}
    {demand && <FormField label="需求变更生效日期" required error={fieldErrors.effectiveDate}><Input id={productionFieldId("effectiveDate")} type="date" disabled={locked} value={effectiveDate} onChange={e => setEffectiveDate(e.target.value)} /></FormField>}
    {guided&&guideStep===3&&warehouseSheet&&<Disclosure open={!!params.get("source_orders") || sources.some(source=>source.allocations.length)}><summary>来源订单（可选）</summary><ShipmentOrderAttribution onOrdersRead={rememberTargets} confirmedSources={initial?.status === "CONFIRMED" ? initial.sources : undefined} compact autoFill={!initial && !!params.get("source_orders")} errors={fieldErrors} sources={sources} shipment={{warehouse_id:warehouse,owner_id:shipmentOwner,destination_id:place.destination_id}} selectedOrders={params.get("source_orders")||""} catalog={catalog.value?.items||[]} locked={locked} change={changeSource} search={(source,allocation)=>setPicker({source,allocation})}/></Disclosure>}
    {guided&&guideStep===3&&warehouseSheet&&<section className={`${styles.panel} ${styles.dispatchReview}`} aria-label="本批出货核对">
      <h2>本批出货核对</h2>
      {unmatchedImported > 0 && <StatusMessage kind="warning" title={`${unmatchedImported}个商品待匹配`}>可以核对原表修改，完成商品匹配和库存核验后可保存或发货。</StatusMessage>}
      {(reviewSnapshot.error || reviewRestoreError) && <StatusMessage kind="danger" title="原表修改记录待核">{reviewSnapshot.error || reviewRestoreError}</StatusMessage>}
      {imported && cartonless && <DispatchImportChanges imported={imported} sources={sources} options={skuOptions}/>}
      <dl className={styles.dispatchReviewFacts}><div><dt>来源仓库</dt><dd>{dispatchWarehouseName}</dd></div><div><dt>目的地</dt><dd>{place.destination}</dd></div><div><dt>发运日期</dt><dd>{date}</dd></div></dl>
      <Table aria-label="出货商品核对" className={styles.dispatchReviewTable}><thead><tr><th>产品规格</th><th>本次出货</th><th>来源仓库</th></tr></thead><tbody>{sources.map((source,index)=><tr key={source.id||index}><th scope="row">{skuOptions.find(option=>option.value===source.sku_id)?.label||source.sku_label||source.import_code||source.sku_id}</th><td>{units(source.actual_units)}件</td><td>{dispatchWarehouseName}{source.plan_id&&<small>关联安排{source.plan_id}</small>}</td></tr>)}</tbody></Table>
    </section>}
    {guided && guideStep === 3 && !warehouseSheet && <section className={styles.panel}><h2>{cartonless ? "本批出货核对" : "本次出货与装箱核对"}</h2><dl>{warehouseSheet&&<><dt>来源仓库</dt><dd>{dispatchScopes.find(scope=>scope.warehouse_id===warehouse&&scope.owner_id===shipmentOwner)?.warehouse_name||"来源仓待核"}</dd></>}<dt>目的地</dt><dd>{place.destination}</dd><dt>发运日期</dt><dd>{date}</dd>{!cartonless&&<><dt>箱数</dt><dd>{boxes.filter(box => box.number.trim()).length}箱</dd></>}</dl><Table title="出货商品核对"><thead><tr><th>产品规格</th><th>本次出货</th><th>来源</th>{!warehouseDispatch && <th>订单分配</th>}</tr></thead><tbody>{sources.map((source, index) => <tr key={index}><th scope="row">{skuOptions.find(option => option.value === source.sku_id)?.label || source.sku_id}</th><td>{source.actual_units}件</td><td>{source.fulfillment_mode === "PRODUCTION_DIRECT" ? "生产直发" : "仓库库存出货"}{source.plan_id && ` · 关联安排${source.plan_id}`}</td>{!warehouseDispatch && <td>{source.allocations.map((item, n) => <p key={n}>{targets.find(target => target.lines?.some(line => line.id === item.order_line_id))?.business_number || item.order_business_number || item.order_number || `订单明细${item.order_line_id}`} · {item.units}件</p>)}</td>}</tr>)}</tbody></Table></section>}
    <section style={guided&&guideStep!==3?{display:"none"}:undefined} className={`${styles.panel} ${warehouseSheet?styles.dispatchEvidence:""}`}>
      {warehouseSheet?<Disclosure><summary>补充资料（选填）</summary>{sourceEvidence}</Disclosure>:<><h2>资料来源</h2>{sourceEvidence}</>}
    </section>
    <Dialog contentClassName={styles.productionDialog} returnFocusTarget={sourceSubmitRef} open={!!sourceReview} onOpenChange={open => { if (!open) setSourceReview(undefined); }} title={sourceReview?.duplicate_document ? "可靠来源已有记录" : "疑似重复，请核对来源"} description="相同日期、SKU及数量可能属于不同事件。核对凭据后再提交。" dismissDisabled={locked}>
      {sourceReview?.duplicate_document ? <><Link className={styles.sourceReference} to={`/production/${kind}/${sourceReview.duplicate_document.id}`}>{sourceReview.duplicate_document.system_number}</Link><p>{sourceReview.content_matches ? "业务内容一致，返回原单据，不增加数量。" : "业务内容不同，请打开原单据更正；不能另建同一事件。"}</p></> : <>{sourceReview?.candidates.map(item => <p key={item.id}><Link className={styles.sourceReference} target="_blank" rel="noreferrer" to={`/production/${kind}/${item.id}`}>{item.business_number || item.system_number}</Link> · {item.business_date}</p>)}<FormField label="核对后的来源区别说明" required><Input value={manualNote} disabled={locked} maxLength={2000} onChange={e => setManualNote(e.target.value)} /></FormField></>}
      <div className={styles.dialogActions}><Button variant="secondary" disabled={locked} onClick={() => setSourceReview(undefined)}>返回核对</Button>{(!sourceReview?.duplicate_document || sourceReview.content_matches) && <Button disabled={locked || (!sourceReview?.duplicate_document && !manualNote.trim())} onClick={() => void save("confirm", true)}>{sourceReview?.duplicate_document ? "返回已有单据" : "已核对为另一事件，继续登记"}</Button>}</div>
    </Dialog>
    {guided && !cartonless && guideStep === 2 && <fieldset disabled={locked} className={styles.panel}>{warehouseDispatch&&<Disclosure><summary>从表格导入数量与装箱</summary>{dispatchImport}</Disclosure>}<ShipmentCartons products={packingProducts} boxes={boxes} change={setBoxes} /></fieldset>}
    {kind === "shipments" && !transfer && (!warehouseDispatch || proposedOverages.length > 0 || command.errorCode === "overage_reason_required") && (!guided || guideStep === 3) && <FormField label="超发说明（若超过预计）" hint="超过预计仍记录真实发生数量，填写原因。"><Input disabled={locked} value={overageReason} onChange={e => setOverageReason(e.target.value)} /></FormField>}
    <div style={guided ? { display: "none" } : undefined} className={`${styles.actions} ${styles.submitActions}`}><Button type="submit" loading={command.busy} disabled={locked || !catalog.value}>{initial?.status === "CONFIRMED" ? demand ? "提交需求变更" : allocationOnly ? "提交归属调整" : "提交更正" : "保存草稿"}</Button>{!initial && <Button ref={sourceSubmitRef} disabled={locked || !catalog.value} onClick={() => { void save("confirm"); }}>保存并确认</Button>}<Link to={initial ? `/production/${kind}/${initial.id}` : `/production/${kind}`}>返回</Link></div></form>{leave.prompt}
  </>;
  return guided ? <ProductionOperationDialog contentClassName={warehouseSheet&&guideStep>0?styles.dispatchGridDialog:warehouseDispatch&&guideStep===0?styles.shipmentSetupDialog:undefined} title={warehouseDispatch ? initial ? cartonless ? "仓库出货明细" : "仓库出货装箱" : "新建仓库出货" : transfer ? "仓间运输发运" : initial ? "出货装箱" : "新建出货单"} description={warehouseDispatch ? "按来源仓现存库存建立独立出货批次，不以生产订单为前置" : transfer ? "独立来源仓出库，不累计生产订单已发；运输与目的实收另行登记" : "多订单／混合来源出货 · 原有分配与关联安排保留"} close={() => { void navigate(back); }}>
    <div className={wizardStyles.form}><GuidedOperationLayout wide={warehouseSheet} step={visibleGuideStep} steps={steps} summaries={[place.destination || "目的地待填", `${packingProducts.reduce((sum, product) => sum + BigInt(product.units), 0n)}件`, ...(!cartonless ? [`${boxes.filter(box => box.number.trim()).length}箱`] : []), "草稿不扣库存"]} contextTitle="本次出货" context={<p>{warehouseDispatch ? `${dispatchScopes.find(scope => scope.warehouse_id === warehouse && scope.owner_id === shipmentOwner)?.warehouse_name || "来源仓待选"} · 按当前可发办理，不关联生产订单。` : transfer ? "本仓已入库成品独立发往目的仓，不关联生产订单或销售安排。" : "可分配多个订单，保留每条来源及预计出库安排。"}</p>} title={steps[visibleGuideStep]!} lead={guideStep === 0 ? "先确认来源仓库、实际目的地与日期；本批信息不表示已签收。" : guideStep === 1 ? warehouseDispatch ? "选择本仓已有库存的商品，填写本批实际件数。0可发、待核和未登记不作为发货依据。" : transfer ? "逐项选择商品与来源仓，按当前可发填写；不关联生产订单分配。" : "逐项选择商品、货物来源、当前仓库与订单分配；预计量不用于放行。" : guideStep === 2 ? "按商品汇总装箱，箱号及件数与本次出货分别核对。" : warehouseDispatch ? cartonless ? "核对商品及数量后确认实际发货。" : "核对来源仓、商品件数、装箱及依据后，单独确认实际发货。" : "核对商品、来源、分配、装箱及依据后，单独确认实际发货。"} busy={locked} unknown={command.unknown || confirmation.unknown} go={index=>setGuideStep(cartonless&&index===2?3:index)} footerNote={initial?.status === "CONFIRMED" ? "更正保留原记录及原因，确认后按净变化重新核对。" : "保存草稿不扣库存，确认实际发货后才生效。"} actions={<>{warehouseSheet&&guideStep>0&&<span className={styles.dispatchTotals} aria-live="polite">已选{dispatchCount}个规格 · 合计{units(dispatchTotal)}件</span>}<Button variant="secondary" disabled={locked} onClick={() => { if (guideStep) setGuideStep(value => cartonless&&value===3?1:value-1); else void navigate(back); }}>{guideStep ? "上一步" : "取消"}</Button>{guideStep > 0 && (!initial || initial.status === "DRAFT") && <Button variant="secondary" disabled={locked || !catalog.value || !!unmatchedImported} onClick={() => void save("draft")}>{initial ? "保存草稿修改" : cartonless ? "保存草稿" : "保存装箱草稿"}</Button>}{guideStep < 3 ? <Button variant="primary" disabled={locked || !catalog.value} onClick={advanceGuide}>下一步</Button> : initial?.status === "DRAFT" ? <DraftShipmentConfirm document={initial} dirty={dirty || !cartonless && !!packingError(packingProducts, boxes)} onStateChange={setConfirmation} saved={finish} compact /> : <Button variant="primary" disabled={locked || !catalog.value || !!unmatchedImported} onClick={() => void save("confirm")}>{initial?.status === "CONFIRMED" ? "确认保存出货更正" : "确认已实际发货"}</Button>}</>}>{editor}</GuidedOperationLayout></div>
  </ProductionOperationDialog> : editor;
}
function OrderReceiptEntry({ order, disabled }: { order: Document; disabled: boolean }) {
  const navigate = useNavigate();
  const policy = useLoad<{ writes_enabled?: boolean; production_receipts_supported?: boolean }>("/api/production/inventory/availability");
  if (!policy.value?.writes_enabled || !policy.value.production_receipts_supported) return null;
  return <Button variant="secondary" disabled={disabled} onClick={() => { void navigate(`/production/stock/movements/new?order_id=${order.id}`); }}>登记生产实收</Button>;
}
function DetailPage({ kind, canWrite, edit = false }: { kind: Kind; canWrite: boolean; edit?: boolean }) {
  const [stockOpen, setStockOpen] = useState(false);
  const [destinationReceiptTrigger, setDestinationReceiptTrigger] = useState<HTMLButtonElement>();
  const [arrivalRefresh, setArrivalRefresh] = useState(0);
  const actionsRef = useRef<HTMLDivElement>(null); const trackingReturnRef = useRef<HTMLButtonElement>(null); const voidReturnRef = useRef<HTMLButtonElement>(null);
  const { id } = useParams(); const [detailParams] = useSearchParams(); const [trackingAction, setTrackingAction] = useState<"close-tracking" | "reopen-tracking">(); const [selectedLines, setSelectedLines] = useState<string[]>([]); const [refresh, setRefresh] = useState(0); const [voidOpen, setVoidOpen] = useState(false); const [reason, setReason] = useState(""); const navigate = useNavigate();
  const { value, error } = useLoad<Document>(`/api/production/${kind}/${id}`, refresh);
  const catalog = useLoad<{items:Sku[]}>("/api/production/skus?contract_version=2", refresh, kind === "shipments" && !edit);
  const command = useCommand(result => { if (result.deleted) void navigate(`/production/${kind}`); else if (result.id !== id) void navigate(`/production/${kind}/${result.id}`); else { setVoidOpen(false); setTrackingAction(undefined); setRefresh(r => r + 1); } });
  if (!value) return <ReadState error={error} />;
  if (edit) return canWrite && value.status !== "VOID" ? <Editor kind={kind} initial={value} key={`${value.id}:${value.revision}:${detailParams.get("action") || "correct"}`} /> : <StatusMessage kind="warning" title="当前记录不可编辑" />;
  const returnTo=detailParams.get("return_to")||"";
  const sourceReturn=/^\/production\/(?:warehouses\/[1-9][0-9]*|orders(?:\/[1-9][0-9]*)?|overview|stock(?:\/forecast)?)(?:\?|$)/.test(returnTo)?returnTo:"";
  const shipmentEdit=`/production/shipments/${id}/edit${sourceReturn?`?${new URLSearchParams({return_to:sourceReturn})}`:""}`;
  const locked = command.busy || command.unknown;
  const allClosed = kind === "orders" && !!value.lines?.length && value.lines.every(l => l.tracking_state === "CLOSED");
  function openTracking(action: "close-tracking" | "reopen-tracking", trigger?: HTMLButtonElement) { trackingReturnRef.current = trigger || actionsRef.current?.querySelector<HTMLButtonElement>('[aria-label="更多操作"]') || null; setReason(""); setSelectedLines(value?.lines?.filter(l => action === "close-tracking" ? l.tracking_state !== "CLOSED" : l.tracking_state === "CLOSED").map(l => l.id) || []); setTrackingAction(action); }
  const selectedQuantity = value.lines?.filter(l => selectedLines.includes(l.id)).reduce((sum, l) => sum + BigInt(trackingAction === "close-tracking" ? l.pending_units || "0" : l.closed_units || "0"), 0n) || 0n;
  return <><PageHeader title={value.business_number || kindName[kind]} eyebrow={value.system_number} actions={canWrite && <div ref={actionsRef} className={styles.actions}>{value.status === "DRAFT" && <><LinkButton to={`/production/${kind}/${id}/edit`}>编辑草稿</LinkButton>{kind === "shipments" && value.destination && (value.cartons || value.dispatch_purpose === "WAREHOUSE_DISPATCH") ? <LinkButton variant="primary" to={shipmentEdit}>核对并确认出货</LinkButton> : <Button disabled={locked} onClick={() => command.submit(`/api/production/${kind}/${id}/confirm`, { expected_revision: value.revision })}>确认单据</Button>}<Button disabled={locked} variant="quiet" onClick={() => command.submit(`/api/production/${kind}/${id}`, { expected_revision: value.revision }, "DELETE")}>删除草稿</Button></>}{value.status === "CONFIRMED" && <>{kind === "orders" ? <Button disabled={locked} onClick={e => { void e; void navigate("/production/shipments/intake"); }}>仓库出货</Button> : <Button disabled={locked} onClick={() => { void navigate(shipmentEdit); }}>更正实际出货</Button>}{kind === "orders" && value.received_units !== undefined && <OrderReceiptEntry order={value} disabled={locked} />}<Menu label="更多操作" items={[
      { id: "file", label: "文件更正", disabled: locked, onSelect: () => { void navigate(`/production/${kind}/import?target_id=${id}`); } },
      ...(kind === "orders" ? [
        { id: "correction", label: "录入更正", disabled: locked, onSelect: () => { void navigate(`/production/orders/${id}/edit`); } },
        { id: "demand", label: "需求变更", disabled: locked, onSelect: () => { void navigate(`/production/orders/${id}/edit?action=demand-changes`); } },
        { id: "close", label: "关闭跟进", disabled: locked || allClosed, onSelect: () => openTracking("close-tracking") },
        { id: "reopen", label: "恢复跟进", disabled: locked || !value.lines?.some(l => l.tracking_state === "CLOSED"), onSelect: () => openTracking("reopen-tracking") },
      ] : [{ id: "allocation", label: "调整订单归属", disabled: locked, onSelect: () => { void navigate(`/production/shipments/${id}/edit?action=allocation-corrections`); } }]),
      { id: "void", label: "作废记录", danger: true, disabled: locked, onSelect: () => { voidReturnRef.current = actionsRef.current?.querySelector<HTMLButtonElement>('[aria-label="更多操作"]') || null; setReason(""); setVoidOpen(true); } },
    ]} /></>}</div>} />{allClosed && value.status === "CONFIRMED" && <StatusMessage kind="info" title="所有SKU行已关闭跟进">如需补录出货，请先恢复相应SKU行；原预计、出货和历史记录保留。</StatusMessage>}{command.feedback}{kind === "shipments" && command.errorCode === "insufficient_available_stock" && <p className={styles.secondary}>本单据商品：{value.sources?.map(source => `${source.sku_label || `SKU ${source.sku_id}（身份待核）`}（SKU ${source.sku_id}）`).join("、")}。请按提示的当前允许量调整本次出货。</p>}<DocumentContent kind={kind} document={value} catalog={catalog.value?.items} />{canWrite && import.meta.env.VITE_MANUAL_TABLES_ENABLED === "true" && <DocumentSourceRecords kind={kind} id={value.id} />}{kind === "orders" && <Disclosure className={styles.workflowTools} onToggle={event => setStockOpen(event.currentTarget.open)}><summary>发货前查看当前可发库存</summary>{stockOpen && <OrderStockPanel document={value} />}</Disclosure>}
    {kind === "shipments" && id && <TransportPanel key={`${id}:${arrivalRefresh}`} shipmentId={id} canWrite={canWrite} onReceive={value.status==="CONFIRMED"&&canWrite&&value.destination_id&&value.owner_id?setDestinationReceiptTrigger:undefined} />}
    {destinationReceiptTrigger && <ArrivalVerificationWindow item={{ id: value.id, destination_id: value.destination_id || null, owner_id: value.owner_id || "", business_number: value.business_number, system_number: value.system_number, source_name: null }} returnFocus={destinationReceiptTrigger} canWrite={canWrite} refresh={arrivalRefresh} close={() => setDestinationReceiptTrigger(undefined)} saved={() => setArrivalRefresh(current => current + 1)} />}
    <Dialog contentClassName={styles.productionDialog} returnFocusTarget={trackingReturnRef} open={!!trackingAction} onOpenChange={open => { if (!open) setTrackingAction(undefined); }} title={trackingAction === "close-tracking" ? "关闭跟进" : "恢复跟进"} description="按选定SKU行执行，原因和数量快照保留。关闭不改变预计或已发；恢复成功后可继续核对修改。" dismissDisabled={command.busy || command.unknown}>
      <div className={styles.trackingSelection}>{value.lines?.filter(l => trackingAction === "close-tracking" ? l.tracking_state !== "CLOSED" : l.tracking_state === "CLOSED").map(l => <label className={styles.trackingRow} key={l.id}><input type="checkbox" disabled={command.busy || command.unknown} checked={selectedLines.includes(l.id)} onChange={e => setSelectedLines(current => e.target.checked ? [...current, l.id] : current.filter(id => id !== l.id))} /><span><strong>{l.sku_label}</strong><small>预计{units(l.expected_units)} · 已发{units(l.actual_units)} · 待跟进{units(l.pending_units)}件</small></span></label>)}<p aria-live="polite">已选{selectedLines.length}个SKU行 · {trackingAction === "close-tracking" ? `本次关闭待跟进${selectedQuantity}件` : `当前关闭剩余${selectedQuantity}件，恢复后重新核对待跟进`}。预计与累计已发不变。</p></div>
      <FormField label="跟进操作原因" required><Input disabled={command.busy || command.unknown} value={reason} onChange={e => setReason(e.target.value)} /></FormField>{command.feedback}
      <div className={styles.dialogActions}><Button variant="secondary" disabled={command.busy || command.unknown} onClick={() => setTrackingAction(undefined)}>取消</Button><Button disabled={!reason.trim() || !selectedLines.length || command.busy || command.unknown} onClick={() => { if (trackingAction) command.submit(`/api/production/orders/${id}/${trackingAction}`, { expected_revision: value.revision, line_ids: selectedLines, reason }); }}>{trackingAction === "close-tracking" ? "确认关闭跟进" : "确认恢复跟进"}</Button></div>
    </Dialog>
    <Dialog contentClassName={styles.productionDialog} returnFocusTarget={voidReturnRef} open={voidOpen} onOpenChange={setVoidOpen} title="作废已确认记录" description="原记录和修订保留。有效出货引用会阻止订单作废。" dismissDisabled={command.busy || command.unknown}><FormField label="作废原因" required><Input value={reason} disabled={command.busy || command.unknown} onChange={e => setReason(e.target.value)} /></FormField>{command.feedback}<div className={styles.dialogActions}><Button variant="secondary" disabled={command.busy || command.unknown} onClick={() => setVoidOpen(false)}>取消</Button><Button variant="danger" disabled={!reason.trim() || command.busy || command.unknown} onClick={() => command.submit(`/api/production/${kind}/${id}/void`, { expected_revision: value.revision, reason })}>确认作废</Button></div></Dialog>
  </>;
}
type Preview = { template_version: string; source_check?: SourceCheck; preview_id: string; filename: string; digest: string; issues: { row: number; message: string }[]; rows: Record<string, string>[]; command: Record<string, unknown>; before: Document | null; duplicate_document?: Document; changes: { field: string; before: string; after: string; change: string }[]; quantity_preview: { expected_units?: string; actual_units: string; difference_units?: string }; order_impact?: { order_number: string; sku_label: string; before_actual: string; after_actual: string; after_difference: string }[] };
function ImportPage({ kind }: { kind: Kind }) {
  const [params] = useSearchParams(); const navigate = useNavigate();
  const [file, setFile] = useState<File>(); const [reason, setReason] = useState(""); const [manualNote, setManualNote] = useState(""); const [overageReason, setOverageReason] = useState("");
  const [preview, setPreview] = useState<Preview>(); const [busy, setBusy] = useState(false); const [error, setError] = useState<string>();
  const catalog = useLoad<{ items: Sku[] }>("/api/production/skus?contract_version=2");
  const command = useCommand(result => { leave.allowLeave(); void navigate(`/production/${kind}/${result.id}`); });
  const leave = useProductionLeave(!!file || !!reason || !!manualNote || !!overageReason, busy || command.busy, command.unknown);
  const { generation, registerSensitivePurge } = useAuthzGeneration(); const auth = useRef(generation); auth.current = generation;
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => registerSensitivePurge(() => { setPreview(undefined); setFile(undefined); }), [registerSensitivePurge]);
  async function upload() {
    if (!file || busy || command.unknown) return;
    setBusy(true); setError(undefined); setPreview(undefined); const start = auth.current;
    try {
      const query = new URLSearchParams({ mode: params.get("target_id") ? "correct" : "create", target_id: params.get("target_id") || "", reason, manual_source_note: manualNote, overage_reason: overageReason, filename: file.name });
      const result = await writeApi<Preview>(`/api/production/files/${kind}/preview?${query}`, { rawBody: file, headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }, idempotent: false });
      if (active.current && start === auth.current) setPreview(result);
    } catch (e) { if (active.current && start === auth.current) setError(e instanceof Error ? e.message : "预览失败。"); }
    finally { if (active.current && start === auth.current) setBusy(false); }
  }
  const locked = busy || command.busy || command.unknown;
  const existing = preview?.source_check?.content_matches === false ? undefined : preview?.duplicate_document || (preview?.source_check?.content_matches ? preview.source_check.duplicate_document : undefined);
  return <><Link className={styles.workflowReturn} to={`/production/${kind}/intake?method=table`}>返回录入流程，选择其他表格方式</Link><PageHeader title={`${params.get("target_id") ? "文件更正" : "标准表格导入"} · ${kindName[kind]}`} description="一份文件对应一张单据：下载模板 → 填写资料 → 上传预览 → 核对后确认。预览不会改变有效数量。" actions={<div className={styles.actions}><a href={`/api/production/files/${kind}/template`}>下载基础模板（v1）</a><a href={`/api/production/files/${kind}/template?version=v2`}>下载含来源模板（v2）</a></div>} />
    <section className={styles.panel}><FormField label="标准XLSX文件（不超过2MB）"><Input type="file" accept=".xlsx" disabled={locked} onChange={e => { setFile(e.target.files?.[0]); setPreview(undefined); }} /></FormField>
    {params.get("target_id") && <FormField label="整单更正原因" required><Input value={reason} disabled={locked} onChange={e => { setReason(e.target.value); setPreview(undefined); }} /></FormField>}
    <p>{kind === "orders" ? "填写业务订单号、下单日期、SKU、预计数量和备注。" : "填写系统订单号和每笔分配数量；同SKU多订单分配会汇成一个出货来源，数量只计一次。"} 超出Excel安全精度的数量使用文本单元格。更正文件必须包含整张单据的全部明细。</p>
    <Disclosure><summary>模板怎么选、SKU怎么填写</summary><div className={styles.body}><p>基础模板适用于人工资料；含来源模板另提供凭据字段，只填写真实已有的来源，不能编造外部事件号。</p><p>保持模板页名和表头。日期填写YYYY-MM-DD，数量为大于0的整数件数。SKU填写编码，不是商品名称或内部ID。</p>{catalog.error ? <ReadState error={catalog.error} /> : <ul>{catalog.value?.items.map(s => <li key={s.sku_id}><code>{s.code}</code> · {s.label}</li>)}</ul>}</div></Disclosure>
    <FormField label="导入人工来源及区别说明"><Input disabled={locked} maxLength={2000} value={manualNote} onChange={e => { setManualNote(e.target.value); setPreview(undefined); }} /></FormField>
    {kind === "shipments" && <FormField label="导入超发说明"><Input disabled={locked} value={overageReason} maxLength={2000} onChange={e => { setOverageReason(e.target.value); setPreview(undefined); }} /></FormField>}
    <Button disabled={!file || locked} loading={busy} onClick={() => void upload()}>读取并预览</Button></section>
    {error && <StatusMessage kind="danger" title="预览未完成">{error}</StatusMessage>}{command.feedback}
    {preview && <section className={styles.panel}><h2>导入预览 · {preview.filename}</h2><p>{preview.before ? `整单更正 · ${preview.before.business_number || preview.before.system_number} · 修订${preview.before.revision}` : existing ? "已有来源 · 返回原单据，不新增数量" : preview.source_check?.content_matches === false ? "来源内容冲突 · 请打开原单据核对" : "待新增单据 · 核对明细后确认"} · {preview.rows.length}条已识别明细</p>
      {!!preview.issues.length && <StatusMessage kind="danger" title="请处理问题后重新上传">{preview.issues.map((issue, i) => <p key={i}>{issue.row ? `第${issue.row}行：` : ""}{issue.message}</p>)}</StatusMessage>}
      {existing && <StatusMessage kind="info" title={preview.duplicate_document ? "这份文件已登记" : "这个可靠来源已登记"}><Link to={`/production/${kind}/${existing.id}`}>{existing.business_number || existing.system_number}</Link> · 返回原单据当前状态，不再次增加数量，无需为相似候选另填区别说明。</StatusMessage>}
      {!existing && !preview.source_check?.duplicate_document && !!preview.source_check?.candidates.length && <StatusMessage kind="warning" title="可能是同日同量的另一批，请核对来源">{preview.source_check.candidates.map(c => <p key={c.id}><Link className={styles.sourceReference} target="_blank" rel="noreferrer" to={`/production/${kind}/${c.id}`}>{c.business_number || c.system_number}</Link> · {c.business_date}</p>)}确认是合法不同批次后，请填写上方来源区别说明并重新预览。</StatusMessage>}
      {preview.source_check?.content_matches === false && preview.source_check.duplicate_document && <StatusMessage kind="danger" title="可靠来源内容冲突"><Link to={`/production/${kind}/${preview.source_check.duplicate_document.id}`}>{preview.source_check.duplicate_document.business_number || preview.source_check.duplicate_document.system_number}</Link> · 打开原记录更正，不能另建同一事件。</StatusMessage>}
      {!existing && preview.source_check?.content_matches !== false && <p>{kind === "orders" ? `拟保存预计 ${preview.quantity_preview.expected_units} 件，有效出货 ${preview.quantity_preview.actual_units} 件，差额 ${preview.quantity_preview.difference_units} 件。` : `本次实际出货 ${preview.quantity_preview.actual_units} 件。`}</p>}
      <Table title="已识别的文件明细" description="按文件中的顺序展示已识别明细；有问题的行见上方提示，需修正后重新上传。"><thead><tr><th>明细序号</th><th>SKU</th>{kind === "shipments" && <th>对应系统订单号</th>}<th>{kind === "orders" ? "预计数量" : "分配数量"}</th></tr></thead><tbody>{preview.rows.map((row, i) => <tr key={i}><td>{i + 1}</td><td>{row.sku_label}</td>{kind === "shipments" && <td>{row.order_number}</td>}<td>{units(row.expected_units || row.units)}件</td></tr>)}</tbody></Table>
      {!!preview.changes.length && <Table title="新增、更改与删除明细"><thead><tr><th>内容</th><th>修改前</th><th>修改后</th><th>变更</th></tr></thead><tbody>{preview.changes.map((c, i) => <tr key={i}><td>{c.field}</td><td>{c.before || "—"}</td><td>{c.after || "—"}</td><td>{c.change}</td></tr>)}</tbody></Table>}
      {!!preview.order_impact?.length && <Table title="确认后的订单数量影响" description="确认时仍会重新核对当前状态和修订。"><thead><tr><th>订单 / SKU</th><th>当前累计</th><th>拟变更后累计</th><th>拟变更后差额</th></tr></thead><tbody>{preview.order_impact.map((o, i) => <tr key={i}><td>{o.order_number}<small className={styles.secondary}>{o.sku_label}</small></td><td>{o.before_actual}</td><td>{o.after_actual}</td><td>{o.after_difference}</td></tr>)}</tbody></Table>}
      <Disclosure><summary>核对文件摘要与完整技术字段</summary><p>标准{preview.template_version} · 文件摘要 {preview.digest}</p><pre>{JSON.stringify(preview.rows, null, 2)}</pre></Disclosure>
      <Button disabled={locked || !!preview.issues.length || (preview.source_check?.content_matches === false) || (!!preview.source_check?.candidates.length && !manualNote.trim() && !existing)} loading={command.busy} onClick={() => command.submit(`/api/production/files/previews/${preview.preview_id}/confirm`, {})}>{preview.before ? "确认整单更正" : existing ? "返回已有单据" : "确认导入并保存"}</Button>
    </section>}{leave.prompt}
  </>;
}
export function ProductionWorkspace({ canWrite }: { canWrite: boolean }) {
  const { search, hash, pathname } = useLocation();
  if (/^\/production\/(factories|warehouses)(\/|$)/.test(pathname)) return <Layout><Routes>{(["factories", "warehouses"] as const).map(kind => <Route key={kind} path={`${kind}/:directoryId?`} element={<DirectoryWorkspace key={kind} kind={kind} canWrite={canWrite} />} />)}</Routes></Layout>;
  return <Layout><Routes><Route index element={<Navigate replace to="/production/orders" />} /><Route path="overview" element={<ProductionOverview canWrite={canWrite} />} /><Route path="imports" element={<ProductionImportCenter canWrite={canWrite} />} /><Route path="imports/records" element={<ProductionImportCenter canWrite={canWrite} records />} /><Route path="stock/intake" element={<ProductionImportCenter canWrite={canWrite} business="inventory" />} /><Route path="stock/materials" element={<ProductionImportCenter canWrite={canWrite} business="inventory" records />} /><Route path="stock/materials/:batch_id" element={<ManualTablePage initialKind="inventory" />} /><Route path="products" element={<ProductionProducts />} /><Route path="stock/*" element={<StockWorkspace canWrite={canWrite} />} /><Route path="inventory" element={<InventorySnapshotPage />} /><Route path="inventory/source" element={<InventorySnapshotPage sourceOnly />} /><Route path="source-drafts" element={<SourceDraftManager canWrite={canWrite} />} /><Route path="manual-tables" element={<ManualTablePage />} /><Route path="manual-tables/:batch_id" element={<ManualTablePage />} /><Route path="source-drafts/orders" element={<OrderSourceDraftPage canWrite={canWrite} />} /><Route path="source-drafts/shipments" element={<ShipmentSourceDraftPage canWrite={canWrite} />} /><Route path="orders/source-drafts" element={<Navigate replace to={`/production/source-drafts/orders${search}${hash}`} />} /><Route path="shipments/source-drafts" element={<Navigate replace to={`/production/source-drafts/shipments${search}${hash}`} />} />{(["orders", "shipments"] as const).map(kind => <Route key={kind} path={kind}><Route index element={kind === "orders" ? <OrderWorkbench canWrite={canWrite} legacy={<ListPage kind={kind} canWrite={canWrite} />} /> : <ListPage kind={kind} canWrite={canWrite} />} /><Route path="intake" element={<ProductionImportCenter canWrite={canWrite} business={kind === "orders" ? "orders" : "packing"} />} /><Route path="materials" element={<ProductionImportCenter canWrite={canWrite} business={kind === "orders" ? "orders" : "packing"} records />} /><Route path="materials/:batch_id" element={<ManualTablePage initialKind={kind === "orders" ? "orders" : "packing"} />} /><Route path="import" element={canWrite ? <ImportPage kind={kind} /> : <StatusMessage kind="warning" title="查看人员不能导入" />} /><Route path="new" element={canWrite ? kind === "orders" ? <OrderWorkbench canWrite={canWrite} create legacy={<Editor kind={kind} />} /> : <Editor kind={kind} /> : <StatusMessage kind="warning" title="查看人员不能创建单据" />} /><Route path=":id" element={kind === "orders" ? <OrderWorkbench canWrite={canWrite} legacy={<DetailPage kind={kind} canWrite={canWrite} />} /> : <DetailPage kind={kind} canWrite={canWrite} />} /><Route path=":id/legacy" element={<DetailPage kind={kind} canWrite={canWrite} />} /><Route path=":id/edit" element={<DetailPage kind={kind} canWrite={canWrite} edit />} /></Route>)}<Route path="orders/receipts/new" element={<BatchReceiptPage canWrite={canWrite} />} /><Route path="summary" element={<SummaryPage />} /></Routes></Layout>;
}

type DraftInput = { source_digest: string; revision: number; business_number: string; business_date: string; notes: string; lines: { source_row: number; expected_units: string; review_note: string }[] };
type SavedSourceDraft = DraftInput & { last_save_key: string; updated_at: string; draft_units: string };
type OrderSource = { catalog_reference?: CatalogReferenceResult; sample_id: string; filename: string; source_digest: string; business_date: string; sheet: string; source_units: string; excluded_sheets: string[]; excluded_rows: number[]; issues: { row: number; message: string }[]; rows: { source_row: number; order_date: string; product_name: string; style_code: string; color: string; sku_code: string; expected_units: string; source_note: string }[]; saved_draft: SavedSourceDraft | null };

function OrderSourceDraftPage({ canWrite }: { canWrite: boolean }) {
  const [params] = useSearchParams(); const sampleId = params.get("sample") || "september-11";
  const [refresh, setRefresh] = useState(0);
  const samples = useLoad<{ items: { sample_id: string; filename: string }[] }>("/api/production/order-source-drafts");
  const source = useLoad<OrderSource>(`/api/production/order-source-drafts/${encodeURIComponent(sampleId)}`, refresh);
  return <><PageHeader eyebrow="PRODUCTION · B 1.1.0 · 本地副本" title="下单表 · 预览与导入草稿" description="本页显示已适配下单表副本，草稿按当前账号独立保存。本站有效订单和出货仍为虚构演练；正式商品绑定待确认，草稿不能确认正式订单或计入汇总。" actions={<div className={styles.actions}><LinkButton to="/production/source-drafts">原表与导入草稿</LinkButton><LinkButton to="/production/orders">返回预计订单</LinkButton></div>} />
    {samples.value && <nav className={styles.actions} aria-label="选择真实下单表">{samples.value.items.map(sample => <Link key={sample.sample_id} className={styles.sourceReference} aria-current={sample.sample_id === sampleId ? "page" : undefined} to={`?sample=${encodeURIComponent(sample.sample_id)}`}>{sample.filename}</Link>)}</nav>}
    {!source.value ? <ReadState error={source.error || samples.error} /> : <OrderSourceDraftEditor key={`${source.value.sample_id}:${refresh}`} source={source.value} canWrite={canWrite} onReload={() => setRefresh(value => value + 1)} />}
  </>;
}

function OrderSourceDraftEditor({ source, canWrite, onReload }: { source: OrderSource; canWrite: boolean; onReload: () => void }) {
  const initialState = useRef<DraftInput>(source.saved_draft ? { source_digest: source.source_digest, revision: source.saved_draft.revision, business_number: source.saved_draft.business_number, business_date: source.saved_draft.business_date, notes: source.saved_draft.notes, lines: source.saved_draft.lines } : { source_digest: source.source_digest, revision: 0, business_number: "", business_date: source.business_date, notes: "", lines: source.rows.map(row => ({ source_row: row.source_row, expected_units: row.expected_units, review_note: "" })) });
  const initial = initialState.current;
  const [input, setInput] = useState<DraftInput>(initial);
  const [baseline, setBaseline] = useState(JSON.stringify(initial));
  const [saved, setSaved] = useState(source.saved_draft);
  const [busy, setBusy] = useState(false); const [unknown, setUnknown] = useState(false);
  const [error, setError] = useState<string>(); const [success, setSuccess] = useState(false);
  const [reloadOpen, setReloadOpen] = useState(false); const reloadTrigger = useRef<HTMLButtonElement>(null);
  const [invalidRow, setInvalidRow] = useState<number>();
  const pending = useRef<{ key: string; body: DraftInput } | undefined>(undefined);
  const { generation, registerSensitivePurge } = useAuthzGeneration();
  const currentGeneration = useRef(generation); currentGeneration.current = generation;
  useEffect(() => registerSensitivePurge(() => { setInput({ ...initial, business_number: "", notes: "", lines: [] }); setSaved(null); setError(undefined); pending.current = undefined; }), [registerSensitivePurge, initial]);
  const leave = useProductionLeave(JSON.stringify(input) !== baseline, busy, unknown);
  const validQuantities = input.lines.every(line => /^[1-9]\d{0,17}$/.test(line.expected_units));
  const total = validQuantities ? input.lines.reduce((sum, line) => sum + BigInt(line.expected_units), 0n).toString() : undefined;
  const originalByRow = new Map(source.rows.map(row => [row.source_row, row.expected_units]));
  const changedCount = input.lines.filter(line => line.expected_units !== originalByRow.get(line.source_row)).length;
  const path = `/api/production/order-source-drafts/${source.sample_id}`;
  function accept(result: SavedSourceDraft) {
    const next: DraftInput = { source_digest: result.source_digest, revision: result.revision, business_number: result.business_number, business_date: result.business_date, notes: result.notes, lines: result.lines };
    setInput(next); setBaseline(JSON.stringify(next)); setSaved(result); setUnknown(false); setSuccess(true); pending.current = undefined;
  }
  async function save(retry = false) {
    if (!retry) {
      const invalid = input.lines.find(line => !/^[1-9]\d{0,17}$/.test(line.expected_units));
      if (invalid || !input.business_date) { setInvalidRow(invalid?.source_row); setError(invalid ? `原表第${invalid.source_row}行：请填写正整数件数。` : "请填写下单日期。"); document.getElementById(invalid ? `source-quantity-${invalid.source_row}` : "source-order-date")?.focus(); return; }
      pending.current = { key: crypto.randomUUID(), body: input };
    }
    const operation = pending.current; if (!operation) return;
    const atGeneration = generation; setBusy(true); setError(undefined); setSuccess(false);
    try {
      const result = await writeApi<SavedSourceDraft>(path, { body: operation.body, operationKey: operation.key });
      if (atGeneration === currentGeneration.current) accept(result);
    } catch (reason) {
      if (atGeneration !== currentGeneration.current) return;
      if (reason instanceof ApiRequestError && reason.status >= 400 && reason.status < 500) { pending.current = undefined; setUnknown(false); } else setUnknown(true);
      setError(reason instanceof Error ? reason.message : "保存未完成，请先核实当前草稿。");
    } finally { if (atGeneration === currentGeneration.current) setBusy(false); }
  }
  async function checkSaved() {
    const atGeneration = generation; setBusy(true);
    try {
      const result = await requestApi<OrderSource>(path);
      if (atGeneration !== currentGeneration.current) return;
      if (result.saved_draft && pending.current && result.saved_draft.last_save_key === pending.current.key) { accept(result.saved_draft); setError(undefined); }
      else setError("当前未查到这次保存；可以重发原操作，或继续核实。输入保持锁定。");
    } catch (reason) { if (atGeneration === currentGeneration.current) setError(reason instanceof Error ? reason.message : "核实未完成。"); }
    finally { if (atGeneration === currentGeneration.current) setBusy(false); }
  }
  const locked = busy || unknown || !canWrite;
  function restoreQuantity(sourceRow?: number) {
    setInput(value => ({ ...value, lines: value.lines.map(line => sourceRow === undefined || line.source_row === sourceRow ? { ...line, expected_units: originalByRow.get(line.source_row)! } : line) }));
    setSuccess(false); setError(undefined); setInvalidRow(undefined);
  }
  const invalidQuantity = input.lines.find(line => !/^[1-9]\d{0,17}$/.test(line.expected_units));
  const reviewItems: DraftReviewItem[] = [
    ...(!input.business_date || (source.business_date && input.business_date !== source.business_date) ? [{ key: "date", title: input.business_date ? "草稿下单日期有调整" : "缺下单日期", detail: input.business_date ? `原表${source.business_date}，当前草稿${input.business_date}；请核对调整依据。` : "请补填草稿下单日期。", targetId: locked ? "source-draft-information" : "source-order-date", actionLabel: "定位下单日期" }] : []),
    ...(invalidQuantity ? [{ key: "quantity", title: `第${invalidQuantity.source_row}行数量待修正`, detail: "预计数量须为正整数；当前总差额尚不可核对。", targetId: locked ? `source-sku-${invalidQuantity.source_row}` : `source-quantity-${invalidQuantity.source_row}`, actionLabel: "定位数量问题" }] : []),
    ...source.issues.map((issue, index) => ({ key: `source-${index}`, title: `原表第${issue.row}行待核对`, detail: issue.message, targetId: `source-sku-${issue.row}`, actionLabel: `定位第${issue.row}行` })),
    { key: "skus", title: `SKU待匹配：${source.rows.length}条`, detail: "正式商品尚未绑定；下方主档核对展示只读候选或未匹配结果。原编码及说明保留。", targetId: `source-sku-${source.rows[0]?.source_row}`, actionLabel: "查看SKU明细" },
  ];
  return <><section className={styles.panel}><h2>{source.filename}</h2><dl className={styles.metadata}><div><dt>主业务页</dt><dd>{source.sheet}</dd></div><div><dt>原表下单日期</dt><dd>{source.business_date || "待核对"}</dd></div><div><dt>明细数</dt><dd>{source.rows.length}条</dd></div><div><dt>原表预计数量</dt><dd>{units(source.source_units)}件</dd></div><div><dt>导入草稿数量</dt><dd>{total ? `${units(total)}件` : "待修正数量"}</dd></div><div><dt>SKU匹配</dt><dd>{source.rows.length}条尚未正式绑定</dd></div><div><dt>保存状态</dt><dd>{saved ? `导入草稿 · 修订${saved.revision}` : "尚未保存"}</dd></div></dl>
    <p>只读取主业务明细。已排除辅助页{source.excluded_sheets.join("、") || "（无）"}及无商品明细的第{source.excluded_rows.join("、") || "—"}行；出货日期列和页名中的发货安排不代表实际已发。</p>
    <StatusMessage kind="info" title="保留原表，先核对草稿">原SKU尚未正式绑定商品ID；只读主档候选见下方核对结果。可填写草稿数量和核对说明；保存不会改原表，也不会创建有效订单。原SKU和原备注保留，不自动修改或合并。</StatusMessage>
  </section>
  <CatalogReferencePanel reference={source.catalog_reference} />
  <SourceDraftReview items={reviewItems} changedCount={changedCount} totalDifference={total === undefined ? undefined : (BigInt(total) - BigInt(source.source_units)).toString()} disabled={locked} onRestoreAll={() => restoreQuantity()} />
  <form className={styles.body} onSubmit={event => { event.preventDefault(); void save(); }} onChangeCapture={() => { setError(undefined); setSuccess(false); }}>
    <fieldset id="source-draft-information" tabIndex={-1} disabled={locked} className={`${styles.panel} ${styles.reviewTarget}`}><legend>导入草稿资料</legend><div className={styles.fields}><FormField label="业务单号（可选）"><Input value={input.business_number} maxLength={120} onChange={event => setInput({ ...input, business_number: event.target.value })} /></FormField><FormField label="下单日期" required><Input id="source-order-date" type="date" value={input.business_date} onChange={event => setInput({ ...input, business_date: event.target.value })} /></FormField><FormField label="草稿备注"><Input value={input.notes} maxLength={2000} onChange={event => setInput({ ...input, notes: event.target.value })} /></FormField></div></fieldset>
    <Table className={styles.sourceDraftTable} title="原表明细与草稿核对" description="原始编码、颜色和备注按原行保留。草稿数量与核对说明独立保存；尚未绑定正式SKU。窄屏可左右滑动查看完整明细。"><thead><tr><th>原行</th><th>商品 / 款号</th><th>颜色 / 原SKU</th><th>原数量</th><th>草稿数量</th><th>原备注 / 核对说明</th><th>关联状态</th></tr></thead><tbody>{source.rows.map((row, index) => <tr key={row.source_row} className={input.lines[index]?.expected_units !== row.expected_units ? styles.changedDraftRow : undefined}><td>{row.source_row}</td><td>{row.product_name}<small className={styles.secondary}>款号 {row.style_code}</small></td><td id={`source-sku-${row.source_row}`} tabIndex={-1} className={styles.reviewTarget}>{row.color}<small className={styles.secondary}>{row.sku_code}</small></td><td>{row.expected_units}件</td><td><Input id={`source-quantity-${row.source_row}`} aria-label={`原表第${row.source_row}行草稿数量`} aria-invalid={invalidRow === row.source_row} disabled={locked} inputMode="numeric" value={input.lines[index]?.expected_units || ""} onChange={event => { setInvalidRow(undefined); setInput({ ...input, lines: input.lines.map(line => line.source_row === row.source_row ? { ...line, expected_units: event.target.value } : line) }); }} /><DraftQuantityChange original={row.expected_units} current={input.lines[index]?.expected_units || ""} disabled={locked} inputId={`source-quantity-${row.source_row}`} onRestore={() => restoreQuantity(row.source_row)} /></td><td>{row.source_note && <p>{row.source_note}</p>}<Input aria-label={`原表第${row.source_row}行核对说明`} maxLength={300} disabled={locked} value={input.lines[index]?.review_note || ""} onChange={event => setInput({ ...input, lines: input.lines.map(line => line.source_row === row.source_row ? { ...line, review_note: event.target.value } : line) })} /></td><td><CatalogCandidateCell reference={source.catalog_reference} sourceRow={row.source_row} /></td></tr>)}</tbody></Table>
    {error && <StatusMessage kind="danger" title={unknown ? "保存结果待核实" : "草稿未保存"}>{error}</StatusMessage>}
    {success && <StatusMessage kind="success" title="导入草稿已保存">刷新后可继续核对。当前仍未创建有效订单。</StatusMessage>}
    {!canWrite && <StatusMessage kind="info" title="查看人员只读">可以查看原表明细，不能修改或保存草稿。</StatusMessage>}
    <div className={styles.actions}>{canWrite && !unknown && <Button type="submit" disabled={busy} loading={busy}>保存导入草稿</Button>}{unknown && <><Button disabled={busy} onClick={() => { void checkSaved(); }}>核实当前草稿</Button><Button variant="secondary" disabled={busy} onClick={() => { void save(true); }}>重发原保存操作</Button></>}<Button ref={reloadTrigger} variant="secondary" disabled={busy || unknown} onClick={() => { if (JSON.stringify(input) !== baseline) setReloadOpen(true); else onReload(); }}>重新载入草稿</Button></div>
    {saved && <p>上次保存：{new Date(saved.updated_at).toLocaleString("zh-CN")} · 草稿修订{saved.revision}</p>}
  </form><Dialog contentClassName={styles.productionDialog} open={reloadOpen} onOpenChange={setReloadOpen} returnFocusTarget={reloadTrigger} title="重新载入已保存草稿" description="当前未保存的草稿输入会被放弃，原表数据保持。"><div className={styles.guardActions}><Button variant="secondary" onClick={() => setReloadOpen(false)}>继续核对</Button><Button onClick={onReload}>放弃输入并重新载入</Button></div></Dialog>{leave.prompt}</>;
}
