import { ProductionConfirmDialog } from "./ProductionConfirmDialog";
import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { type FactoryRecord, type WarehouseScope, type WorkbenchStock, ReadContent, ReadState, Fields, WarehouseField } from "./WorkbenchFields";
import { useBusinessToday } from "./workbenchDate";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Download, Factory, Plus, RefreshCw, Search, SlidersHorizontal, X } from "lucide-react";
import { writeApi } from "../../api/client";
import { Button, Dialog, FormField, Input, LinkButton, Menu, Pagination, StatusMessage, Table } from "../../design-system";
import { type Document, type DocumentPage, type OrderLine, type Sku, statusName, units } from "./types";
import { useLoad, useCommand, useSearchDraft } from "./useProductionApi";
import { useProductionLeave } from "./useProductionLeave";
import { OrderOperationPanel } from "./OrderOperationPanel";
import { DestinationField } from "./DirectoryFields"; import { destinationValue } from "./directoryTypes";
import { TableImportReview } from "./TableImportReview";
import { useTableBaseline } from "./useTableBaseline";
import { withoutTableBaseline } from "./tableImportDiff";
import { OrderTableImport, type OrderImportPreview } from "./OrderTableImport";
import { RevisionHistory } from "./ProductionViews";
import styles from "./OrderWorkbench.module.css";
import { FactoryOrderOverview } from "./FactoryOrderOverview";
import { OrderCompletionAction } from "./OrderCompletionAction";
import { OrderProgressDialog } from "./OrderProgressDialog";
import { orderOverviewUrl, orderProductName } from "./orderProgress";
import { orderPending } from "./orderPending";

function orderState(order: Document) {
  if (order.status !== "CONFIRMED") return statusName[order.status];
  if (order.production_completion_state === "COMPLETED") return "已完成";
  if (order.tracking_state === "CLOSED") return "跟进已关闭";
  if (order.lines?.length && order.lines.every(line => line.received_units != null && BigInt(line.received_units) >= BigInt(line.expected_units))) return "已入库";
  if (order.lines?.some(l => l.produced_units != null && BigInt(l.produced_units) > 0n)) return "生产中";
  return "待生产";
}
export function OrderWorkbench({ canWrite, legacy, create = false }: { canWrite: boolean; legacy: ReactNode; create?: boolean }) {
  const { generation } = useAuthzGeneration();
  const capability = useLoad<{ version: number }>("/api/production/workbench");
  // Old, unmigrated experience copies stay on their original functionality.
  if (capability.error || capability.value && typeof capability.value.version !== "number") return <><StatusMessage kind="info" title="当前服务未接入新版工作台">以下为原版入口；不会自动迁移此环境或改写历史资料。</StatusMessage>{legacy}</>;
  if (!capability.value) return <ReadState />;
  return <Workbench key={generation} canWrite={canWrite} create={create} />;
}
function Workbench({ canWrite, create }: { canWrite: boolean; create: boolean }) {
  const { id } = useParams(); const [params] = useSearchParams(); const navigate = useNavigate();
  const [refresh, setRefresh] = useState(0); const [notice, setNotice] = useState("");
  const [createdOrder, setCreatedOrder] = useState<Document>();
  const createTrigger = useRef<HTMLButtonElement>(null);
  const orderDialogReturnFocus = useRef<HTMLElement | null>(null);
  const orderToolsHost = useRef<HTMLSpanElement>(null);
  const location = useLocation();
  const defaultChooserOpen = !id;
  // A tab, refresh or dialog changes history, but not the order-selection context.
  const chooserKey = JSON.stringify([location.pathname, ...["q", "factory", "status", "todo", "page", "progress"].map(key => params.get(key) || "")]);
  const [chooserView, setChooserView] = useState({ key: chooserKey, open: defaultChooserOpen });
  if (chooserView.key !== chooserKey) setChooserView({ key: chooserKey, open: defaultChooserOpen });
  const chooserOpen = chooserView.key === chooserKey ? chooserView.open : defaultChooserOpen;
  const appliedQuery = params.get("q") || "";
  const [query, setQuery] = useSearchDraft(appliedQuery); const [factoryQuery, setFactoryQuery] = useState(""); const [factoryPage, setFactoryPage] = useState(1);
  const newOrder = create || params.get("new") === "1"; const factoryId = params.get("factory") || "";
  const overview = !id;
  const progress = params.get("progress") === "completed" ? "completed" : params.get("progress") === "all" ? "all" : "active";
  const orders = useLoad<DocumentPage>(`/api/production/orders?${new URLSearchParams({ q: params.get("q") || "", factory: factoryId, status: params.get("status") || "", tracking: params.get("todo") || "", page: params.get("page") || "1", page_size: "20", ...(overview ? {progress} : {}) })}`, refresh, true, true, true);
  const factories = useLoad<{ items: FactoryRecord[]; total: number }>(`/api/production/factories?q=${encodeURIComponent(factoryQuery)}&page=${factoryPage}`, refresh, true, true, true);
  const selectedId = id || (newOrder || overview ? undefined : orders.value?.items[0]?.id);
  const selected = useLoad<Document>(`/api/production/orders/${selectedId}`, `${refresh}:${params.get("reload") || ""}`, !!selectedId, true, !newOrder && params.get("edit") !== "1" && !params.get("operation") && !["receive", "ship"].includes(params.get("tab") || ""));
  const needsStock = !!selectedId && ["receive", "ship"].includes(params.get("tab") || "");
  const stock = useLoad<WorkbenchStock>(`/api/production/inventory/availability${needsStock ? "" : "?projection=scopes"}`, refresh, true, true, true);
  const catalog = useLoad<{ items: Sku[] }>("/api/production/skus?contract_version=2");
  function change(values: Record<string, string>, orderId = selectedId, replace = false) {
    const next = new URLSearchParams(params); for (const [key, value] of Object.entries(values)) { if (value) next.set(key, value); else next.delete(key); }
    if (orderId !== selectedId || values.new === "1") { next.delete("operation"); next.delete("shipment"); next.delete("receipt_draft"); }
    void navigate(`/production/orders${orderId ? `/${orderId}` : ""}?${next}`,{replace,state:location.state as unknown});
  }
  function saved(result?: Document, message = "已保存，数量已重新读取。") {
    setCreatedOrder(undefined); setNotice(message); setRefresh(r => r + 1);
    if (result) { const next = new URLSearchParams(params); next.delete("new"); next.delete("edit"); next.delete("shipment"); next.delete("tab"); next.delete("line"); next.set("factory", result.factory_id || "unknown"); void navigate(`/production/orders/${result.id}?${next}`); }
  }
  function openNewOrder(method = "", orderId = selectedId, trigger: HTMLElement | null = createTrigger.current) {
    orderDialogReturnFocus.current = trigger;
    change({new:"1",method},orderId);
  }
  function closeNewOrder() {
    const next = new URLSearchParams(params); next.delete("new"); next.delete("method");
    void navigate({pathname:create ? "/production/orders" : location.pathname,search:next.toString()},{replace:true,state:location.state as unknown});
  }
  function created(result: Document) {
    setCreatedOrder(result);setNotice(result.status === "DRAFT" ? "订单草稿已保存" : "生产单已下达");setRefresh(value => value+1);closeNewOrder();
  }
  const tab = params.get("tab") || "progress"; const order = selected.value?.id === selectedId ? selected.value : undefined;
  const activeFilters = [
    { key: "factory", name: "工厂", value: factoryId, label: factoryId === "unknown" ? "工厂未登记" : factories.value?.items.find(item => item.id === factoryId)?.name || `工厂 ${factoryId}` },
    { key: "q", name: "关键词", value: appliedQuery, label: appliedQuery },
    { key: "status", name: "状态", value: params.get("status"), label: Object.entries(statusName).find(([key]) => key === params.get("status"))?.[1] || params.get("status") },
    { key: "todo", name: "待办", value: params.get("todo"), label: ({ WAIT_PRODUCTION: "待生产 / 待登记", WAIT_RECEIPT: "待入库", WAIT_SHIPMENT: "历史出货筛选" } as Record<string, string>)[params.get("todo") || ""] },
  ].filter(item => item.value);
  const groups = new Map<string, Document[]>();
  for (const item of orders.value?.items || []) { const key = params.get("group") === "0" ? "全部订单" : item.factory_name || "工厂未登记"; groups.set(key, [...(groups.get(key) || []), item]); }
  const blocked = !selected.current || !stock.current || !catalog.current;
  const [factoryPickerOpen, setFactoryPickerOpen] = useState(false);
  const factoryTrigger = useRef<HTMLButtonElement>(null);
  const filterTrigger = useRef<HTMLButtonElement>(null);
  const [filterOpen,setFilterOpen] = useState(false);
  const [filterDraft,setFilterDraft] = useState({status:"",todo:""});
  function applyOrderFilters() {
    setFilterOpen(false);
    const nextProgress = filterDraft.status === "VOID" ? "all" : filterDraft.status === "DRAFT" && progress === "completed" ? "active" : progress;
    change({...filterDraft,progress:nextProgress === "active" ? "" : nextProgress,page:"1",new:"",edit:""},"");
  }
  const factoryLabel = factoryId === "unknown" ? "工厂未登记" : factories.value?.items.find(f => f.id === factoryId)?.name || (factoryId ? "已筛选工厂" : "全部工厂");
  const selectOverviewFactory = (factory: string) => { setFactoryPickerOpen(false); change({ factory, page: "1", new: "", edit: "" }, ""); };
  const overviewFilters = <>
      <Button ref={factoryTrigger} className={styles.overviewFilterChip} variant="secondary" icon={<Factory />} aria-label="选择工厂" aria-haspopup="dialog" aria-expanded={factoryPickerOpen} onClick={() => setFactoryPickerOpen(true)}>{factoryLabel}</Button>
      <Dialog open={factoryPickerOpen} onOpenChange={setFactoryPickerOpen} title="选择工厂" closeLabel="关闭工厂筛选" description="搜索并选择工厂，只筛选订单，不更改订单资料。" returnFocusTarget={factoryTrigger} contentClassName={styles.overviewFactoryDialog}>
        <Input autoFocus aria-label="搜索工厂" type="search" placeholder="输入工厂名称" value={factoryQuery} onChange={e => { setFactoryQuery(e.target.value); setFactoryPage(1); }} />
        <div className={styles.overviewFactoryOptions} aria-label="工厂筛选选项">
          <Button variant="quiet" aria-pressed={!factoryId} onClick={() => selectOverviewFactory("")}>全部工厂</Button>
          <Button variant="quiet" aria-pressed={factoryId === "unknown"} onClick={() => selectOverviewFactory("unknown")}>工厂未登记</Button>
          {factories.loading && <p role="status">正在读取工厂…</p>}
          {factories.current && factories.value?.items.map(f => <Button key={f.id} variant="quiet" aria-label={`筛选工厂：${f.name}`} aria-pressed={factoryId === f.id} onClick={() => selectOverviewFactory(f.id)}>{f.name}<small>{f.order_count || "0"} 单</small></Button>)}
          {factories.current && !factories.value?.items.length && <p>没有匹配的工厂，请调整名称。</p>}
          {factories.error && <ReadState error={factories.error} />}
        </div>
        {factories.value && factories.value.total > 50 && <Pagination page={factoryPage} totalItems={factories.value.total} totalPages={Math.ceil(factories.value.total / 50)} onPageChange={setFactoryPage} />}
      </Dialog>
      <Button ref={filterTrigger} variant="secondary" className={styles.overviewFilterChip} icon={<SlidersHorizontal size={16}/>} aria-haspopup="dialog" aria-expanded={filterOpen} onClick={() => {setFilterDraft({status:params.get("status") || "",todo:params.get("todo") || ""});setFilterOpen(true);}}>筛选{params.get("status") || params.get("todo") ? ` · ${Number(!!params.get("status"))+Number(!!params.get("todo"))}` : ""}</Button>
      <Dialog open={filterOpen} onOpenChange={setFilterOpen} title="筛选订单" closeLabel="关闭订单筛选" returnFocusTarget={filterTrigger} contentClassName={styles.orderFilterDialog}>
        <form onSubmit={event => {event.preventDefault();applyOrderFilters();}}>
          <fieldset><legend>单据状态</legend><div className={styles.filterChoices} role="group" aria-label="单据状态">{[{value:"",label:"全部状态"},{value:"DRAFT",label:"草稿"},{value:"CONFIRMED",label:"已确认"},{value:"VOID",label:"已作废"}].map(choice => <Button key={choice.value} variant="secondary" aria-pressed={filterDraft.status === choice.value} onClick={() => setFilterDraft(value => ({...value,status:choice.value}))}>{choice.label}</Button>)}</div></fieldset>
          <fieldset><legend>待处理事项</legend><div className={styles.filterChoices} role="group" aria-label="待处理事项">{[{value:"",label:"全部事项"},{value:"WAIT_PRODUCTION",label:"待生产"},{value:"WAIT_RECEIPT",label:"待入库"},...(params.get("todo") === "WAIT_SHIPMENT" ? [{value:"WAIT_SHIPMENT",label:"历史出货筛选"}] : [])].map(choice => <Button key={choice.value} variant="secondary" aria-pressed={filterDraft.todo === choice.value} onClick={() => setFilterDraft(value => ({...value,todo:choice.value}))}>{choice.label}</Button>)}</div></fieldset>
          <footer><Button variant="quiet" onClick={() => setFilterDraft({status:"",todo:""})}>重置</Button><div><Button variant="quiet" onClick={() => setFilterOpen(false)}>取消</Button><Button variant="primary" type="submit">应用筛选</Button></div></footer>
        </form>
      </Dialog>
      {!!activeFilters.length && <nav className={styles.activeFilters} aria-label="订单筛选条件">{activeFilters.map(filter => <Button key={filter.key} variant="secondary" icon={<X size={14} aria-hidden="true" />} aria-label={`清除${filter.name}筛选`} onClick={() => change({ [filter.key]: "", page: "1", new: "", edit: "" }, "")}>{filter.name}：{filter.label}</Button>)}<Button variant="quiet" aria-label="清空订单筛选" onClick={() => change({ factory: "", q: "", status: "", todo: "", page: "1", new: "", edit: "" }, "")}>清空筛选</Button></nav>}
  </>;
  const overviewTools = <span ref={orderToolsHost}><Menu label="更多" items={[
    { id: "order-intake", label: "从表格下单", disabled: !canWrite, onSelect: () => openNewOrder("table","",orderToolsHost.current?.querySelector("button") ?? null) },
    { id: "order-materials", label: "订单原表与整理记录", href: "/production/orders/materials" },
    { id: "shipments", label: "全部出货", href: "/production/shipments" },
    { id: "shipment-history", label: "历史订单出货汇总", href: "/production/summary" },
    { id: "order-export", label: "导出订单", href: `/api/production/files/orders/export?${new URLSearchParams({ ...Object.fromEntries(params), tracking: params.get("todo") || "", ...(overview ? {progress} : {}) })}`, reloadDocument: true },
  ]} /></span>;
  const orderDialog = newOrder && canWrite ? <OrderForm dialog returnFocus={orderDialogReturnFocus.current ? orderDialogReturnFocus : createTrigger} blocked={!catalog.current || !stock.current} key="new" skus={catalog.value?.items || []} scopes={stock.value?.scopes || []} stockError={stock.error} onSaved={created} onCancel={closeNewOrder}/> : null;
  if (overview) return <><FactoryOrderOverview data={orders.value} error={orders.error || catalog.error || stock.error} loading={orders.initialLoading || catalog.initialLoading || stock.initialLoading} catalog={catalog.value?.items || []} scopes={stock.value?.scopes || []} canWrite={canWrite} query={query} setQuery={setQuery} appliedQuery={appliedQuery} change={change} filters={overviewFilters} tools={overviewTools} notice={notice} retry={() => setRefresh(r => r + 1)} saved={() => saved()} search={params} blocked={!orders.current || !catalog.current || !stock.current} onCreate={() => openNewOrder("","")} createTrigger={createTrigger} noticeAction={createdOrder && <LinkButton variant="quiet" to={orderOverviewUrl(params).replace("/production/orders",`/production/orders/${createdOrder.id}`)} state={location.state as unknown}>查看新订单</LinkButton>}/>{orderDialog}</>;
  return <section className={`${styles.workbench}${!chooserOpen ? ` ${styles.focusedOrder}` : ""}`} aria-label="生产与出货工作台">
    <div className={styles.listToggle}><LinkButton to={orderOverviewUrl(params)}>工厂订单总览</LinkButton><Button variant="secondary" aria-expanded={chooserOpen} aria-controls="production-order-chooser" onClick={() => setChooserView({ key: chooserKey, open: !chooserOpen })}>{chooserOpen ? "收起订单列表" : "选择其他订单"}</Button>{order?.factory_id && <LinkButton to={`/production/factories/${order.factory_id}`}>查看生产工厂</LinkButton>}{canWrite && !chooserOpen && <Button ref={createTrigger} variant="primary" icon={<Plus />} onClick={event => openNewOrder("",selectedId,event.currentTarget)}>下单</Button>}</div>
    <aside id="production-order-chooser" className={`${styles.chooser} ${!chooserOpen ? styles.chooserClosed : ""}`} aria-label="工厂与订单">
      {orders.value && orders.error && <StatusMessage kind="warning" title="订单列表更新失败">{orders.error}</StatusMessage>}
      <div className={styles.chooserTitle}><h2>订单跟进</h2>{canWrite && <Button ref={createTrigger} variant="primary" icon={<Plus />} onClick={event => openNewOrder("",selectedId,event.currentTarget)}>下单</Button>}</div>
      <form className={styles.search} onSubmit={e => { e.preventDefault(); change({ q: query.trim(), page: "1", new: "", edit: "" }, ""); }}><Search aria-hidden="true" /><Input aria-label="搜索工厂、订单或SKU" type="search" placeholder="搜索工厂、订单或 SKU" value={query} onChange={e => setQuery(e.target.value)} /><Button variant="quiet" type="submit">查找</Button></form>
      <details className={styles.factoryFilter}><summary><Factory aria-hidden="true" />{factoryId === "unknown" ? "工厂未登记" : factories.value?.items.find(f => f.id === factoryId)?.name || (factoryId ? "已筛选工厂" : "全部工厂")}</summary><div className={styles.factoryOptions}><Input aria-label="搜索工厂" type="search" placeholder="输入工厂名称" value={factoryQuery} onChange={e => { setFactoryQuery(e.target.value); setFactoryPage(1); }} /><Button variant="quiet" aria-pressed={!factoryId} onClick={() => change({ factory: "", page: "1", new: "", edit: "" }, "")}>全部工厂</Button><Button variant="quiet" aria-pressed={factoryId === "unknown"} onClick={() => change({ factory: "unknown", page: "1", new: "", edit: "" }, "")}>工厂未登记</Button>{factories.value?.items.map(f => <Button key={f.id} variant="quiet" aria-label={`筛选工厂：${f.name}`} aria-pressed={factoryId === f.id} onClick={() => change({ factory: f.id, page: "1", new: "", edit: "" }, "")}>{f.name}<small>{f.order_count || "0"} 单</small></Button>)}{factories.error && <ReadState error={factories.error} />}{factories.value && factories.value.total > 50 && <Pagination page={factoryPage} totalItems={factories.value.total} totalPages={Math.ceil(factories.value.total / 50)} onPageChange={setFactoryPage} />}</div></details>
      <div className={styles.chooserControls}><select aria-label="订单状态筛选" value={params.get("status") || ""} onChange={e => change({ status: e.target.value, page: "1", new: "", edit: "" }, "")}><option value="">全部状态</option><option value="CONFIRMED">已确认</option><option value="DRAFT">草稿</option><option value="VOID">已作废</option></select><label><input type="checkbox" checked={params.get("group") !== "0"} onChange={e => change({ group: e.target.checked ? "" : "0" })} />按厂分组</label></div>
      <FormField label="待处理事项"><select value={params.get("todo") || ""} onChange={e => change({ todo: e.target.value, page: "1", new: "", edit: "" }, "")}><option value="">全部事项</option><option value="WAIT_PRODUCTION">待生产 / 待登记</option><option value="WAIT_RECEIPT">待入库</option>{params.get("todo") === "WAIT_SHIPMENT" && <option value="WAIT_SHIPMENT">历史出货筛选</option>}</select></FormField>
      {!!activeFilters.length && <nav className={styles.activeFilters} aria-label="订单筛选条件">{activeFilters.map(filter => <Button key={filter.key} variant="secondary" icon={<X size={14} aria-hidden="true" />} aria-label={`清除${filter.name}筛选`} onClick={() => change({ [filter.key]: "", page: "1", new: "", edit: "" }, "")}>{filter.name}：{filter.label}</Button>)}<Button variant="quiet" aria-label="清空订单筛选" onClick={() => change({ factory: "", q: "", status: "", todo: "", page: "1", new: "", edit: "" }, "")}>清空筛选</Button></nav>}
      {!orders.value ? <ReadState error={orders.error} /> : <><div className={styles.orderGroups}>{[...groups].map(([name, items]) => <section key={name}><h2>{name}<small>{items.length} 单（本页）</small></h2>{items.map(item => <Button key={item.id} variant="quiet" className={styles.orderItem} aria-pressed={!newOrder && selectedId === item.id} onClick={() => change({ new: "", edit: "", tab: "", line: "", shipment: "" }, item.id)}><strong>{item.business_number || item.system_number}</strong><span>{item.factory_name || "工厂未登记"}</span><span><time>{item.business_date || "日期未登记"}</time><small>{orderState(item)}</small></span>{item.status === "CONFIRMED" && <span className={styles.pendingNumbers} aria-label="订单待处理数量"><span>待生产 <b>{orderPending(item, "produced_units")}</b></span><span>待入库 <b>{orderPending(item, "received_units")}</b></span></span>}</Button>)}</section>)}{!orders.value.items.length && <p className={styles.empty}>没有匹配的订单。可清除筛选{canWrite ? "，或点击“下单”建立生产单。" : "。"}</p>}</div><Pagination itemLabel="订单" page={orders.value.page} totalItems={orders.value.total} totalPages={Math.max(1, Math.ceil(orders.value.total / 20))} onPageChange={page => change({ page: String(page), new: "", edit: "" }, "")} /></>}
      <details className={styles.tools}><summary>原表与其他工具</summary><Button variant="quiet" disabled={!canWrite} onClick={event => openNewOrder("table",selectedId,event.currentTarget)}>从表格下单</Button><Link to="/production/orders/materials">订单原表与整理记录</Link><Link to="/production/shipments">全部出货</Link><Link to="/production/summary">历史订单出货汇总</Link><a href={`/api/production/files/orders/export?${new URLSearchParams({ ...Object.fromEntries(params), tracking: params.get("todo") || "" })}`}>导出订单</a></details>
    </aside>
    <div className={styles.detail}>
      <ReadContent loading={selected.initialLoading || stock.initialLoading || catalog.initialLoading} error={selected.error || stock.error || catalog.error} retry={() => setRefresh(r => r + 1)}>
      {notice && <StatusMessage kind="success" title={notice} />}{catalog.error && <ReadState error={catalog.error} />}
      {!selectedId ? !orders.value ? <ReadState error={orders.error} /> : <div className={styles.empty}><Factory /><h2>从工厂或订单开始</h2><p>选择一张生产单，在这里连续跟进生产、入库与出货。</p></div> : !order ? <ReadState error={selected.error} /> : <>
        <header className={styles.orderHeader}><div><p className={styles.eyebrow}>生产与出货 · B 1.1.0</p><h1>{order.business_number || order.system_number}<small>{orderState(order)}</small></h1></div><div className={styles.actions}><OrderCompletionAction order={order} canWrite={canWrite} blocked={blocked} saved={() => saved(undefined, "完成状态已保存。")} reload={() => setRefresh(value => value+1)}/><LinkButton variant="secondary" to={`/production/overview?overview_view=flow&trace_kind=order&trace_id=${order.id}`} state={{ordersReturn:`${location.pathname}${location.search}`}}>查看链路</LinkButton><LinkButton to={`/api/production/orders/${order.id}/table`} reloadDocument variant="secondary" icon={<Download />}>导出下单表</LinkButton><Button variant="quiet" icon={<RefreshCw />} onClick={() => { const next = new URLSearchParams(params); next.set("reload", String(Date.now())); void navigate({ search: next.toString() }); }}>刷新</Button>{canWrite && order.status !== "VOID" && <Button variant="secondary" onClick={() => change({ edit: "1" })}>{order.status === "DRAFT" ? "编辑草稿" : "更正订单"}</Button>}</div></header>
        <dl className={styles.metadata}><div><dt>下单日期</dt><dd>{order.business_date || "未登记"}</dd></div><div><dt>生产工厂</dt><dd>{order.factory_name || "未登记"}</dd></div><div><dt>计划入库仓库</dt><dd>{stock.value?.scopes.find(s => s.warehouse_id === order.receipt_warehouse_id && s.owner_id === order.receipt_owner_id)?.warehouse_name || "未登记/待核"}</dd></div><div><dt>计划发货目的地</dt><dd>{order.destination || "未登记"}</dd></div></dl>
        {params.get("edit") === "1" ? canWrite ? <OrderForm blocked={blocked} key={`${order.id}:${order.revision}`} initial={order} skus={catalog.value?.items || []} scopes={stock.value?.scopes || []} stockError={stock.error} onSaved={saved} onCancel={() => change({ edit: "" })} /> : <StatusMessage kind="warning" title="当前账号不能更正" /> : <>
          <nav className={styles.tabs} aria-label="订单操作">{[["progress", "生产跟进"], ["receive", "入库"], ["ship", "历史出货"], ["history", "操作记录"]].map(([key, label]) => <Link key={key} aria-current={tab === key ? "page" : undefined} to={`?${new URLSearchParams({ ...Object.fromEntries(params), tab: key!, new: "", edit: "", operation: "", shipment: "" })}`}>{label}</Link>)}</nav>
          {tab === "progress" ? <ProgressTable catalog={catalog.value?.items || []} order={order} selected={params.get("line") || order.lines?.[0]?.id || ""} onSelect={line => change({ line })} /> : <details className={styles.inlineProgress}><summary>查看本单逐产品进度（下单 / 生产 / 入库 / 出货）</summary><ProgressTable catalog={catalog.value?.items || []} order={order} selected={params.get("line") || order.lines?.[0]?.id || ""} onSelect={line => change({ line })} /></details>}
          <div key={`${order.id}:${tab === "receive" || tab === "ship" || tab === "progress" ? "operation" : order.revision}:${tab}:${params.get("line") || ""}`} className={styles.operation}>
            {tab === "history" ? <OrderHistory order={order} /> : order.status !== "CONFIRMED" ? <OrderStatus blocked={blocked} order={order} canWrite={canWrite} saved={saved} edit={() => change({ edit: "1" })} /> : tab === "ship" && !params.get("shipment") && params.get("operation") !== "guided" ? <OrderShipmentHistory order={order} canWrite={canWrite} /> : tab === "receive" || tab === "ship" ? <OrderOperationPanel mode={tab} order={order} stock={stock.value} stockError={stock.error} blocked={blocked} canWrite={canWrite} saved={() => saved()} /> : <ProgressPanel catalog={catalog.value?.items || []} blocked={blocked} order={order} line={order.lines?.find(l => l.id === params.get("line")) || order.lines?.[0]} canWrite={canWrite} saved={() => saved()} />}
          </div>
        </>}
      </>}
      </ReadContent>
    </div>
  {orderDialog}</section>;
}
function OrderShipmentHistory({ order, canWrite }: { order: Document; canWrite: boolean }) {
  return <><h2>历史出货关联</h2><p className={styles.muted}>这里保留此前明确关联本单的记录。新出货从仓库库存独立建立批次，不要求先选择生产订单。</p>{canWrite && <LinkButton variant="primary" to="/production/shipments/intake">仓库出货</LinkButton>}{order.shipments?.map(shipment => <p key={shipment.id}><LinkButton to={`/production/shipments/${shipment.id}`}>{shipment.business_number || shipment.system_number}</LinkButton> · {shipment.business_date || "日期未登记"} · {statusName[shipment.status]}</p>)}{!order.shipments?.length && <p>本单暂无历史出货关联，不能据此判断仓库有没有出过货。</p>}</>;
}
function ProgressTable({ order, catalog, selected, onSelect }: { catalog: Sku[]; order: Document; selected: string; onSelect: (id: string) => void }) {
  return <div className={styles.progress}><Table title="逐产品进度"><thead><tr><th>选择 / SKU</th><th>下单数量</th><th>已生产</th><th>已入库</th><th>生产状态</th></tr></thead><tbody>{order.lines?.map(line => <tr key={line.id} className={selected === line.id ? styles.selectedRow : undefined}><th scope="row"><label><input type="radio" name="order-line" checked={selected === line.id} onChange={() => onSelect(line.id)} />{orderProductName(line, catalog)}</label>{line.tracking_state === "CLOSED" && <small>跟进已关闭</small>}</th><td>{units(line.expected_units)}</td><td>{line.produced_units == null ? <span className={styles.muted}>未登记</span> : units(line.produced_units)}</td><td>{units(line.received_units)}</td><td>{line.production_status || ""}</td></tr>)}</tbody></Table></div>;
}
function ProgressPanel({ order, line, catalog, canWrite, saved, blocked }: { blocked: boolean; order: Document; line?: OrderLine; catalog: Sku[]; canWrite: boolean; saved: () => void }) {
  const [editor, setEditor] = useState<{ order: Document; line: string; trigger: HTMLElement }>();
  if (!line) return <p>此单尚无产品明细。</p>;
  return <>{canWrite && order.lines?.some(item => item.tracking_state !== "CLOSED") ? <Button variant="secondary" disabled={blocked} onClick={event => setEditor({ order, line: line.id, trigger: event.currentTarget })}>更新生产进度</Button> : <StatusMessage kind="info" title={canWrite ? "此单跟进已关闭" : "当前账号只读"}>可以查看数量和历史；恢复跟进等原有操作仍可从高级订单详情进入。</StatusMessage>}{editor && <OrderProgressDialog readBlocked={blocked} order={editor.order} catalog={catalog} focusLine={editor.line} returnFocus={editor.trigger} close={() => setEditor(undefined)} saved={() => { setEditor(undefined); saved(); }} />}<details className={styles.tools}><summary>更多订单操作</summary><Link to={`/production/orders/${order.id}/legacy`}>关闭/恢复跟进、需求变更及原始明细</Link></details></>;
}
function OrderStatus({ order, canWrite, saved, edit, blocked }: { blocked: boolean; order: Document; canWrite: boolean; saved: (d?: Document) => void; edit: () => void }) {
  const command = useCommand(result => saved(result)); const leave = useProductionLeave(false, command.busy, command.unknown);
  return <><StatusMessage kind="info" title={order.status === "VOID" ? "订单已作废，保留历史" : "订单还是草稿，未产生生产需求"}>确认后才能登记生产进度、实收入库或出货。</StatusMessage>{canWrite && order.status === "DRAFT" && <div className={styles.actions}><Button variant="secondary" disabled={blocked} onClick={edit}>继续编辑草稿</Button><Button disabled={blocked || command.busy || command.unknown} onClick={() => command.submit(`/api/production/orders/${order.id}/confirm`, { expected_revision: order.revision })}>确认订单</Button></div>}{command.feedback}{leave.prompt}</>;
}
function FactoryPicker({ value, name, onChange, onStateChange, required = true }: { value: string; name?: string | null; onChange: (id: string, name: string) => void; onStateChange: (s: { busy: boolean; unknown: boolean }) => void; required?: boolean }) {
  const [page, setPage] = useState(1); const [refresh, setRefresh] = useState(0); const [newName, setNewName] = useState(""); const [factoryDialog, setFactoryDialog] = useState(false);
  const factories = useLoad<{ items: FactoryRecord[]; total: number }>(`/api/production/factories?page=${page}`, refresh);
  const command = useCommand<FactoryRecord>(result => { onChange(result.id, result.name); setFactoryDialog(false); setNewName(""); setRefresh(r => r + 1); });
  useEffect(() => { onStateChange({ busy: command.busy, unknown: command.unknown }); }, [command.busy, command.unknown, onStateChange]);
  return <div className={styles.factoryPicker}>
    <FormField label="生产工厂（一单一家）" required={required}><select required={required} disabled={factories.loading && !value} value={value} onChange={e => onChange(e.target.value, factories.value?.items.find(f => f.id === e.target.value)?.name || "")}><option value="">{required ? "选择承接工厂" : "未登记（保留历史未知）"}</option>{value && !factories.value?.items.some(f => f.id === value) && <option value={value}>{name || "已选工厂"}</option>}{factories.value?.items.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}</select></FormField>
    <Button variant="secondary" icon={<Plus />} onClick={() => setFactoryDialog(true)}>登记新工厂</Button>
    {factories.value && factories.value.total > 50 && <Pagination page={page} totalItems={factories.value.total} totalPages={Math.ceil(factories.value.total / 50)} onPageChange={setPage} />}
    <Dialog open={factoryDialog} onOpenChange={v => { if (!command.busy && !command.unknown) setFactoryDialog(v); }} title="登记新工厂" description="登记后自动选入本单，订单仍需单独保存。" size="medium" contentClassName={styles.factoryDialog}>
      <div className={styles.factoryDialogBody}>
        <FormField label="新工厂全名" hint="请填写可区分的完整名称，已有工厂无需重复登记。"><Input maxLength={120} placeholder="例如：青禾制衣厂" value={newName} disabled={command.busy || command.unknown} onChange={e => setNewName(e.target.value)} /></FormField>
        <div className={styles.factoryDialogNote}><p>联系人、地址及关联仓库，可稍后在“工厂管理”补充。</p><p>放弃本单仍会保留工厂档案；不会创建仓库或库存。</p></div>
        {command.feedback}
      </div>
      <div className={styles.factoryDialogFooter}><Button variant="secondary" disabled={command.busy || command.unknown} onClick={() => setFactoryDialog(false)}>取消登记</Button><Button variant="primary" loading={command.busy} disabled={!newName.trim() || command.unknown} onClick={() => command.submit("/api/production/factories", { name: newName.trim() })}>登记并选择</Button></div>
    </Dialog>
    {factories.error && <div className={styles.factoryFeedback}><ReadState error={factories.error} /></div>}
    {!factoryDialog && command.feedback && <div className={styles.factoryFeedback}>{command.feedback}</div>}
  </div>;
}
function OrderForm({ initial, skus, scopes, stockError, onSaved, onCancel, blocked, dialog = false, returnFocus }: { dialog?: boolean; returnFocus?: RefObject<HTMLElement | null>; blocked: boolean; initial?: Document; skus: Sku[]; scopes: WarehouseScope[]; stockError?: string; onSaved: (d: Document) => void; onCancel: () => void }) {
  const [orderParams] = useSearchParams();
  const [closing, setClosing] = useState(false);
  const [notesOpen,setNotesOpen] = useState(!!withoutTableBaseline(initial?.notes) || !!initial?.manual_source_note);
  const [chosenWarehouse,setChosenWarehouse]=useState<WarehouseScope>();
  const [warehouseQuery,setWarehouseQuery]=useState('');const [warehousePage,setWarehousePage]=useState(1);
  const directory=useLoad<import('./directoryTypes').DirectoryPage>(`/api/production/warehouses?status=ACTIVE&q=${encodeURIComponent(warehouseQuery)}&page=${warehousePage}`);
  const plannedScopes:WarehouseScope[]=(directory.value?.items||[]).filter(w=>['FACTORY','OWN','THIRD_PARTY'].includes(w.type||'')).map(w=>({warehouse_id:w.id,warehouse_name:w.name,owner_id:'1',owner_name:'公司自有'}));
  if(chosenWarehouse&&!plannedScopes.some(s=>s.warehouse_id===chosenWarehouse.warehouse_id&&s.owner_id===chosenWarehouse.owner_id))plannedScopes.push(chosenWarehouse);
  const retained=scopes.find(s=>`${s.warehouse_id}:${s.owner_id}`===`${initial?.receipt_warehouse_id}:${initial?.receipt_owner_id||'1'}`);
  if(retained&&!plannedScopes.some(s=>s.warehouse_id===retained.warehouse_id&&s.owner_id===retained.owner_id))plannedScopes.push(retained);
  const audit = useTableBaseline(initial?.notes, "orders");
  const [importSource, setImportSource] = useState<OrderImportPreview["command"]>({});
  const [importReview, setImportReview] = useState(false);
  const [place, setPlace] = useState(() => destinationValue(initial));
  const [factoryOperation, setFactoryOperation] = useState({ busy: false, unknown: false });
  const [factory, setFactory] = useState(initial?.factory_id || orderParams.get("factory") || ""); const [factoryName, setFactoryName] = useState(initial?.factory_name);
  const [warehouse, setWarehouse] = useState(initial?.receipt_warehouse_id ? `${initial.receipt_warehouse_id}:${initial.receipt_owner_id || "1"}` : "");
  const today = useBusinessToday();
  const [number, setNumber] = useState(initial?.business_number || ""); const [date, setDate] = useState(initial?.business_date || today()); const [note, setNote] = useState(withoutTableBaseline(initial?.notes));
  const [sourceNote, setSourceNote] = useState(initial?.manual_source_note || ""); const [reason, setReason] = useState(""); const [dirty, setDirty] = useState(false); const [mode, setMode] = useState("correct"); const [skuQuery, setSkuQuery] = useState("");
  const [lines, setLines] = useState(initial?.lines?.map(l => ({ sku_id: l.sku_id, expected_units: l.expected_units })) || [{ sku_id: "", expected_units: "" }]);
  const [sourceCheck, setSourceCheck] = useState<{ candidates: { id: string; system_number: string; business_number: string }[]; duplicate_document?: Document; content_matches?: boolean }>(); const [checking, setChecking] = useState(false); const [error, setError] = useState("");
  const command = useCommand(result => { leave.allowLeave(); onSaved(result); }); const leave = useProductionLeave(dirty, checking || command.busy || factoryOperation.busy, command.unknown || factoryOperation.unknown);
  const locked = checking || command.busy || command.unknown || factoryOperation.busy || factoryOperation.unknown;
  function requestClose() {
    if (locked) return;
    if (!dialog) {onCancel();return;}
    if (dirty) {setClosing(true);return;}
    leave.allowLeave();onCancel();
  }
  const confirmed = initial?.status === "CONFIRMED"; const demand = confirmed && mode === "demand-changes";
  async function save(saveMode: string) {
    if (factoryOperation.busy || factoryOperation.unknown || audit.blocked) return;
    let auditedNote: string;
    try { auditedNote = audit.withNote(note); } catch (e) {setError(e instanceof Error ? e.message : "原表核对未完成");return;}
    if ((saveMode === "confirm" || initial) && audit.baseline && !importReview) {setImportReview(true);return;}
    const [receipt_warehouse_id, receipt_owner_id] = warehouse.split(":");
    const body = { ...importSource, ...(audit.baseline ? {_table_baseline_id:audit.baseline.id} : {}), factory_id: factory || null, receipt_warehouse_id: receipt_warehouse_id || null, receipt_owner_id, ...place, business_number: number, business_date: date, notes: auditedNote, manual_source_note: sourceNote, lines, save_mode: saveMode, ...(initial ? { expected_revision: initial.revision, reason } : {}) };
    if (!initial && saveMode === "confirm" && !sourceCheck) { setChecking(true); setError(""); try { const result = await writeApi<{ candidates: { id: string; system_number: string; business_number: string }[]; duplicate_document?: Document; content_matches?: boolean }>("/api/production/sources/orders/check", { body, idempotent: false }); if (result.candidates.length || result.duplicate_document) { setSourceCheck(result);setNotesOpen(true); return; } } catch (e) { setError(e instanceof Error ? e.message : "来源核对失败"); return; } finally { setChecking(false); } }
    command.submit(initial ? `/api/production/orders/${initial.id}${confirmed ? `/${mode}` : ""}` : "/api/production/orders", demand ? { expected_revision: initial.revision, lines, effective_date: date, reason } : body, initial && !confirmed ? "PUT" : "POST");
  }
  const matches = skus.filter(s => s.status === "active" && s.label.toLocaleLowerCase().includes(skuQuery.trim().toLocaleLowerCase()));
  const [receiptWarehouse, receiptOwner] = warehouse.split(":");
  const importContext = JSON.stringify({ factory_id: factory, receipt_warehouse_id: receiptWarehouse || "", receipt_owner_id: receiptOwner || "", destination: place.destination, destination_id: place.destination_id || "", destination_type: place.destination_type || "", manual_source_note: sourceNote });
  const productCount = lines.filter(line => line.sku_id).length;
  const amountsComplete = productCount > 0 && lines.filter(line => line.sku_id).every(line => /^[1-9][0-9]*$/.test(line.expected_units));
  const plannedUnits = amountsComplete ? lines.filter(line => line.sku_id).reduce((sum, line) => sum + BigInt(line.expected_units), 0n).toString() : undefined;
  const content = <section className={`${styles.operation} ${styles.orderForm}`}>{!dialog && <header className={styles.orderFormHeading}><div><h2>{initial ? confirmed ? "更正订单" : "编辑生产单草稿" : "下生产单"}</h2><p>一张生产单交给一家工厂，按商品规格填写计划生产数量。</p></div><span className={styles.orderFormTag}>{initial ? confirmed ? "已确认订单" : "草稿编辑" : "新生产单"}</span></header>}<form onChangeCapture={() => { setDirty(true); setSourceCheck(undefined); setImportReview(false); }} onSubmit={e => { e.preventDefault(); void save(initial && !confirmed ? "draft" : "confirm"); }}><fieldset disabled={blocked || checking || command.busy || command.unknown}>

    {confirmed && <FormField label="修改类型"><select value={mode} onChange={e => setMode(e.target.value)}><option value="correct">录入更正（修正错误）</option><option value="demand-changes">正式需求变更（追加或调整）</option></select></FormField>}
    <section className={styles.orderFormSection} aria-label="订单信息"><div className={styles.orderSectionHeading}><h3>订单信息</h3><span>{demand ? "调整计划数量，保留原单事实" : "指定承接工厂与下单信息"}</span></div><div className={styles.orderBasics}>
    {!demand && <FactoryPicker required={!initial || initial.factory_id != null} onStateChange={setFactoryOperation} value={factory} name={factoryName} onChange={(id, name) => { setFactory(id); setFactoryName(name); setDirty(true); }} />}
    <Fields>{!demand && <FormField label="业务订单号（可选）"><Input maxLength={120} value={number} onChange={e => setNumber(e.target.value)} /></FormField>}<FormField label={demand ? "需求变更生效日期" : "下单日期"} required><Input required type="date" value={date} onChange={e => setDate(e.target.value)} /></FormField></Fields>
    </div></section>
    {!demand && <section className={styles.orderFormSection} aria-label="入库与发货计划"><div className={styles.orderSectionHeading}><h3>入库与发货计划</h3><span>先选计划入库仓，发货目的地可稍后补充</span></div><div className={styles.orderPlanGrid}><div className={styles.orderReceiptPlan}><Input type="search" aria-label="查找计划入库仓" placeholder="搜索仓库" value={warehouseQuery} onChange={e=>{setWarehouseQuery(e.target.value);setWarehousePage(1);}}/><WarehouseField required={!initial || initial.receipt_warehouse_id != null} label="生产完成后入库仓库" scopes={plannedScopes} value={warehouse} onChange={value=>{setWarehouse(value);setChosenWarehouse(plannedScopes.find(s=>`${s.warehouse_id}:${s.owner_id}`===value));}} />{directory.error&&<StatusMessage kind="danger" title="仓库读取失败">{directory.error}</StatusMessage>}{directory.value&&directory.value.total>50&&<Pagination page={warehousePage} totalItems={directory.value.total} totalPages={Math.ceil(directory.value.total/50)} onPageChange={setWarehousePage}/> }</div><details className={`${styles.orderDestination} ${styles.orderDestinationDisclosure}`} open={initial?.destination ? true : undefined}><summary><span>计划发货目的地<small>选填 · 现在可暂不确定</small></span></summary><DestinationField value={place} onChange={v => { setPlace(v); setDirty(true); }} /></details></div></section>}
    <section className={styles.orderFormSection} aria-label="产品明细"><div className={styles.orderSectionHeading}><div><h3>产品明细</h3><p>{productCount ? `${productCount} 个规格 · ${plannedUnits === undefined ? "数量待填写" : `合计 ${units(plannedUnits)} 件`}` : "选择商品规格，填写本次计划生产数量"}</p></div><div className={styles.orderProductSearch}><Search aria-hidden="true" /><Input aria-label="搜索商品规格" placeholder="搜索款号、颜色或尺码" type="search" value={skuQuery} onChange={e => setSkuQuery(e.target.value)} /></div></div>
    {!confirmed && <OrderTableImport inline context={importContext} skus={skus} sourceField={null} ready={!!factory && !!receiptWarehouse && !!receiptOwner} locked={locked} onBusy={setChecking} onSave={() => undefined} onCancel={requestClose} onApply={result => {
      setLines(result.rows.map(row => ({sku_id:row.sku_id,expected_units:row.expected_units})));
      if(result.command.business_date)setDate(result.command.business_date);
      setNumber(result.command.business_number || "");
      if(result.command.destination)setPlace({destination:result.command.destination,destination_id:result.command.destination_id || null,destination_type:result.command.destination_type || "TEXT"});
      const {source_system,source_event_kind,external_event_id,source_batch,_source_digest}=result.command;
      setImportSource({source_system,source_event_kind,external_event_id,source_batch,_source_digest});
      audit.apply(result.table_baseline);setDirty(true);setSourceCheck(undefined);setImportReview(false);
    }}/>}
    <><div className={styles.orderProductTable}><Table aria-label="本单产品"><thead><tr><th>商品规格</th><th>下单数量（件）</th><th>操作</th></tr></thead><tbody>{lines.map((l, i) => <tr key={i}><td><select aria-label={`产品${i + 1}`} required disabled={confirmed && !demand} value={l.sku_id} onChange={e => setLines(v => v.map((x, index) => index === i ? { ...x, sku_id: e.target.value } : x))}><option value="">选择款号 / 颜色 / 尺码</option>{l.sku_id && !matches.some(s => s.sku_id === l.sku_id) && <option value={l.sku_id}>{initial?.lines?.find(x => x.sku_id === l.sku_id)?.sku_label || skus.find(s => s.sku_id === l.sku_id)?.label || "当前规格待核"}</option>}{matches.filter(s => s.sku_id === l.sku_id || !lines.some(x => x.sku_id === s.sku_id)).map(s => <option key={s.sku_id} value={s.sku_id}>{s.label}</option>)}</select></td><td><Input aria-label={`产品${i + 1}下单数量`} required inputMode="numeric" pattern="[1-9][0-9]*" value={l.expected_units} onChange={e => setLines(v => v.map((x, index) => index === i ? { ...x, expected_units: e.target.value } : x))} /></td><td><Button variant="quiet" disabled={lines.length === 1} onClick={() => { setLines(v => v.filter((_, index) => index !== i)); setDirty(true); }}>移除</Button></td></tr>)}</tbody></Table></div>
    {(!confirmed || demand) && <Button variant="secondary" disabled={lines.length >= 500} icon={<Plus />} onClick={() => { setLines(v => [...v, { sku_id: "", expected_units: "" }]); setDirty(true); }}>增加产品</Button>}
    </></section>
    <>
    {!demand && <details className={styles.orderNotesDisclosure} open={notesOpen} onToggle={event => setNotesOpen(event.currentTarget.open)}><summary>备注与来源（选填）</summary><section className={styles.orderFormSection} aria-label="备注与来源"><div className={styles.orderNotesGrid}><FormField label="订单备注（可选）"><textarea maxLength={2000} value={note} onChange={e => setNote(e.target.value)} /></FormField><FormField label="人工来源及区别说明" hint="同日同款同量但确为不同订单时，填写可核实的区别。"><Input maxLength={2000} value={sourceNote} onChange={e => setSourceNote(e.target.value)} /></FormField></div></section></details>}
    {confirmed && <FormField label="修改原因" required><Input required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></FormField>}
    {sourceCheck && <StatusMessage kind="warning" title={sourceCheck.duplicate_document ? "发现已有可靠来源订单" : "请核对同日同款同量的订单"}>{sourceCheck.duplicate_document ? <Link to={`/production/orders/${sourceCheck.duplicate_document.id}`}>打开已有单据，不重复创建</Link> : <>{sourceCheck.candidates.map(c => <p key={c.id}><Link to={`/production/orders/${c.id}`}>{c.business_number || c.system_number}</Link></p>)}<p>确为另一张订单时，填写来源及区别说明，再保存。</p></>}</StatusMessage>}
    {importReview && <TableImportReview baseline={audit.baseline} rows={[{key:"document",label:"订单信息",values:{"下单日期":date,"业务订单号":number}},...lines.filter(line=>line.sku_id).map(line=>({key:line.sku_id,label:skus.find(s=>s.sku_id===line.sku_id)?.label || line.sku_id,values:{"下单数量":line.expected_units}}))]}/>}
    {audit.feedback}
    <footer className={styles.orderFormFooter}><p>{initial ? "修改后保留原单及修订历史" : "保存草稿可稍后继续；确认后生成生产需求"}</p><div className={styles.actions}><Button variant="quiet" onClick={requestClose}>{dialog ? "取消下单" : "返回订单"}</Button>{!initial && <Button variant="secondary" onClick={e => { if (e.currentTarget.form?.reportValidity()) void save("draft"); }}>保存草稿</Button>}<Button variant="primary" type="submit" disabled={!!sourceCheck?.duplicate_document || audit.blocked}>{initial ? confirmed ? "核对并保存修改" : "保存草稿修改" : importReview ? "确认下单" : "核对并确认下单"}</Button></div></footer>
    </>
    </fieldset></form>{stockError && <ReadState error={stockError} />}{error && <StatusMessage kind="danger" title="来源核对未完成">{error}</StatusMessage>}{command.feedback}{leave.prompt}</section>;
  return dialog ? <Dialog open title="下生产单" size="large" closeLabel="关闭下单" contentClassName={styles.orderEntryDialog} closeOnOutsideClick={false} dismissDisabled={locked} returnFocusTarget={returnFocus} onOpenChange={open => {if(!open)requestClose();}}>
    <ProductionConfirmDialog open={closing} onOpenChange={setClosing} title="保留当前填写，还是放弃？" description="放弃后，本次尚未保存的下单内容将被清除。"><Button variant="primary" onClick={() => setClosing(false)}>继续填写</Button><Button variant="danger" onClick={() => {leave.allowLeave();onCancel();}}>放弃并关闭</Button></ProductionConfirmDialog>
    {content}
  </Dialog> : content;
}
function OrderHistory({ order }: { order: Document }) {
  return <><h2>操作记录</h2><p className={styles.muted}>按修订查看修改前后、操作人和原因；入库在“入库”中查看，出货装箱记录在对应批次查看。</p>{order.history?.length ? <RevisionHistory history={order.history} /> : <p>暂无修订记录。</p>}</>;
}
