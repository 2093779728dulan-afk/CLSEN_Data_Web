import { Disclosure } from "../../design-system";
import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, ChevronRight, ClipboardList, Download, FileText, RefreshCw, Search, Truck } from "lucide-react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { ApiRequestError, requestApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, Input, LinkButton, StatusMessage, Table } from "../../design-system";
import { type Document, type Sku, units } from "./types";
import { transportSummary, type TransportState } from "./transport";
import styles from "./ProductionOverview.module.css";
import { useLoad, useRefreshOnReturn } from "./useProductionApi";
import { orderProductName } from "./orderProgress";
import { OrderCompletionAction } from "./OrderCompletionAction";
import { OverviewBatchProgress } from "./OverviewBatchProgress";
import type { TransitItem } from "./WarehouseTransit";
import { OverviewTransitOpening } from "./OverviewTransitOpening";

type Directory = { id: string; name: string; type?: string; status?: string };
type Page<T> = { items: T[]; total: number; page_size: number };
type Binding = { allocation_id: string | null; units: string; received_units: string; settled_units: string; carton_id: string; source_line_id: string };
type Destination = { bindings: Binding[] };
type Stock = { warehouse_id: string; owner_id: string; sku_id: string; state: string; on_hand_units: string | null; free_available_units: string | null; pending_units: string; defective_units: string };
type Scope = { warehouse_id: string; owner_id: string; warehouse_name: string; owner_name: string };
type StockResult = { items: Stock[]; scopes: Scope[] };
type Loan = { warehouse_id: string; owner_id: string; is_active: string | boolean | number; outstanding_units: string };
type Trace = { shipment: Document; transport: TransportState; allocated: bigint; received: bigint | null; settled: bigint | null; bindings: Binding[] };
type Row = { order: Document; traces: Trace[] };
type Overview = { batches: TransitItem[]; batchError?: string; rows: Row[]; factories: Directory[]; warehouses: Directory[]; stock: StockResult; loans: Loan[]; loansLimited: boolean; counts: { countDrafts: number }; loadedAt: string };
const sum = (values: (string | bigint)[]) => values.reduce<bigint>((a, v) => a + BigInt(v), 0n);
const n = (v: bigint | null | undefined) => v == null ? "待核" : v.toLocaleString("zh-CN");
const numeric = (v: unknown): v is string => typeof v === "string" && /^[0-9]+$/.test(v);
async function pages<T>(path: string, signal: AbortSignal): Promise<T[]> {
  const first = await requestApi<Page<T>>(`${path}${path.includes("?") ? "&" : "?"}page=1`, { signal });
  const count = Math.ceil(first.total / first.page_size);
  const rest: T[] = [];
  for (let page = 2; page <= count; page++) rest.push(...(await requestApi<Page<T>>(`${path}${path.includes("?") ? "&" : "?"}page=${page}`, { signal })).items);
  return [...first.items, ...rest];
}
async function loadBatches(signal: AbortSignal): Promise<TransitItem[]> {
  type BatchPage = Page<TransitItem> & { detail_scope: string };
  const items: TransitItem[] = [];
  let count = 1;
  for (let page = 1; page <= count; page++) {
    const result = await requestApi<BatchPage>(`/api/production/inventory/transit-batches?page_size=100&page=${page}`, { signal });
    if (result.detail_scope !== "whole_batch") throw new Error("未返回完整批次范围，请核对服务版本。");
    items.push(...result.items); count = Math.ceil(result.total / result.page_size);
  }
  return items;
}
async function loadOverview(signal: AbortSignal): Promise<Overview> {
  const [orderList, activeFactories, inactiveFactories, warehouses, stock, loans, counts, batchResult] = await Promise.all([
    pages<Document>("/api/production/orders?page_size=100", signal),
    pages<Directory>("/api/production/factories?status=ACTIVE", signal),
    pages<Directory>("/api/production/factories?status=INACTIVE", signal),
    pages<Directory>("/api/production/warehouses", signal),
    requestApi<StockResult>("/api/production/inventory/availability", { signal }),
    requestApi<{ items: Loan[]; limit: number }>("/api/production/inventory/loans", { signal }),
    requestApi<{ total: number }>("/api/production/inventory/documents?page=1&page_size=1&kind=ADJUST&status=draft", { signal }),
    loadBatches(signal).then(items => ({items, error: undefined})).catch((error: unknown) => ({items: [] as TransitItem[], error: error instanceof Error ? error.message : "出货进度读取失败"})),
  ]);
  const orders = await Promise.all(orderList.filter(o => o.status === "CONFIRMED").map(o => requestApi<Document>(`/api/production/orders/${o.id}`, { signal })));
  const shipmentIds = [...new Set(orders.flatMap(o => (o.shipments || []).filter(s => s.status === "CONFIRMED").map(s => s.id)))];
  const shipments = await Promise.all(shipmentIds.map(async id => {
    const [shipment, destination, transport] = await Promise.all([requestApi<Document>(`/api/production/shipments/${id}`, { signal }), requestApi<Destination>(`/api/production/inventory/destination-state?shipment_id=${encodeURIComponent(id)}`, { signal }), requestApi<TransportState>(`/api/production/inventory/transport-state?shipment_id=${encodeURIComponent(id)}`, { signal })]);
    return { shipment, destination, transport };
  }));
  const rows = orders.map(order => {
    const lineIds = new Set((order.lines || []).map(l => l.id));
    const traces: Trace[] = [];
    for (const { shipment, destination, transport } of shipments) {
      const allocations = (shipment.sources || []).flatMap(s => s.allocations).filter(a => lineIds.has(a.order_line_id));
      if (!allocations.length) continue;
      const allocated = sum(allocations.map(a => a.units));
      const ids = new Set(allocations.map(a => a.id).filter((id): id is string => !!id));
      const bindings = destination.bindings.filter(b => b.allocation_id != null && ids.has(b.allocation_id));
      const mapped = sum(bindings.map(b => b.units));
      const complete = ids.size === allocations.length && mapped === allocated && bindings.every(b => numeric(b.received_units) && numeric(b.settled_units));
      traces.push({ shipment, transport, allocated, received: complete ? sum(bindings.map(b => b.received_units)) : null, settled: complete ? sum(bindings.map(b => b.settled_units)) : null, bindings });
    }
    return { order, traces };
  });
  const factories = [...activeFactories, ...inactiveFactories];
  return { batches: batchResult.items, batchError: batchResult.error, rows, factories, warehouses, stock, loans: loans.items, loansLimited: loans.items.length >= loans.limit, counts: { countDrafts: counts.total }, loadedAt: new Date().toLocaleString("zh-CN") };
}
function destinationTotals(traces: Trace[], actual?: string) {
  if (actual != null && numeric(actual) && sum(traces.map(t => t.allocated)) !== BigInt(actual)) return { received: null, unsettled: null, settled: null };
  if (traces.some(t => t.received == null || t.settled == null)) return { received: null, unsettled: null, settled: null };
  const shipped = sum(traces.map(t => t.allocated)); const received = sum(traces.map(t => t.received!)); const settled = sum(traces.map(t => t.settled!));
  return { received, settled, unsettled: shipped - received - settled };
}
function stockTotal(items: Stock[], field: "on_hand_units" | "free_available_units" | "pending_units" | "defective_units") {
  if (!items.length || items.some(item => item[field] == null || !numeric(item[field]))) return null;
  return sum(items.map(item => item[field]!));
}
function scopeStockTotal(stock: StockResult, warehouse: string, field: "pending_units" | "defective_units") {
  const scopes = stock.scopes.filter(scope => !warehouse || scope.warehouse_id === warehouse);
  const items = stock.items.filter(item => !warehouse || item.warehouse_id === warehouse);
  if (!scopes.length || scopes.some(scope => !items.some(item => item.warehouse_id === scope.warehouse_id && item.owner_id === scope.owner_id))) return null;
  return stockTotal(items, field);
}
function csv(value: string | number | undefined | null) { const text = String(value ?? "待核"); return `"${(/^[=+@\t\r-]/.test(text) ? "'" : "") + text.replaceAll('"', '""')}"`; }
function exportRows(rows: Row[]) {
  const head = ["订单", "工厂", "预计", "生产", "生产实收", "历史订单关联出货", "历史关联目的仓实收", "历史关联未收待核", "历史关联少收结案", "历史关联运输摘要（按整批出货，不作订单数量分配）"];
  const body = rows.map(({ order, traces }) => { const d = destinationTotals(traces, order.actual_units); const lines = order.lines || []; const produced = lines.length && lines.every(l => numeric(l.produced_units)) ? sum(lines.map(l => l.produced_units!)).toString() : "未登记"; return [order.business_number || order.system_number, order.factory_name || "待核", order.expected_units, produced, order.received_units, order.actual_units, d.received?.toString(), d.unsettled?.toString(), d.settled?.toString(), traces.length ? traces.map(t => `${t.shipment.business_number || t.shipment.system_number}: ${transportSummary(t.transport)}`).join("；") : "暂无历史关联出货"]; });
  const blob = new Blob(["\ufeff", [head, ...body].map(row => row.map(csv).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" }); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "业务总览.csv"; a.click(); URL.revokeObjectURL(url);
}
function metric(label: string, value: string, detail?: string, percent?: number) {
  return <div className={styles.metric}><div className={styles.amount}><strong>{label}</strong><b>{value}</b></div>{percent !== undefined && <div className={`${styles.progress} ${percent === 100 ? styles.complete : ""}`}><progress aria-label={`${({ "已生产": "工厂生产", "已入库": "生产入库", "已出货": "实际出货" } as Record<string, string>)[label] || label}占计划比例`} max={100} value={percent} /><span>{percent}%</span></div>}{detail && <small>{detail}</small>}</div>;
}
function ratio(amount: bigint | null, expected: string | undefined) { if (amount == null || !numeric(expected) || BigInt(expected) === 0n) return undefined; const tenths = (amount * 1000n + BigInt(expected) / 2n) / BigInt(expected); return Number(tenths > 1000n ? 1000n : tenths) / 10; }
function remaining(amount: bigint | null, expected: string | undefined, label: string) { return amount == null || !numeric(expected) || BigInt(expected) <= amount ? undefined : `${label} ${n(BigInt(expected) - amount)} 件`; }
function ProductionOverviewTable({ canWrite = false, viewSwitch }: { canWrite?: boolean; viewSwitch?: ReactNode }) {
  const [expandedOrders, setExpandedOrders] = useState<string[]>([]);
  const [params, setParams] = useSearchParams(); const location = useLocation(); const { generation, registerSensitivePurge } = useAuthzGeneration();
  const [result, setResult] = useState<{ generation: number; pending: boolean; data?: Overview; error?: string }>(); const request = useRef<AbortController | null>(null); const [refresh, setRefresh] = useState(0); const [search, setSearch] = useState(params.get("q") || "");
  useEffect(() => { setSearch(params.get("q") || ""); }, [params]);
  useEffect(() => registerSensitivePurge(() => { request.current?.abort(); setResult(undefined); setExpandedOrders([]); }), [registerSensitivePurge]);
  useEffect(() => { const c = new AbortController(); request.current = c; setResult(previous => ({ generation, pending: true, data: previous?.generation === generation ? previous.data : undefined })); void loadOverview(c.signal).then(data => { if (!c.signal.aborted) setResult({ generation, pending: false, data }); }).catch((e: unknown) => { if (!c.signal.aborted) setResult(previous => ({ generation, pending: false, data: e instanceof ApiRequestError && [401,403].includes(e.status) ? undefined : previous?.generation === generation ? previous.data : undefined, error: e instanceof Error ? e.message : "读取失败" })); }); return () => c.abort(); }, [generation, refresh]);
  useRefreshOnReturn(() => setRefresh(value => value + 1));
  const catalog = useLoad<{items: Sku[]}>("/api/production/skus?contract_version=2", refresh);
  const data = result?.generation === generation ? result.data : undefined; const error = result?.generation === generation ? result.error : undefined;
  const q = (params.get("q") || "").trim().toLocaleLowerCase(); const factory = params.get("factory") || ""; const warehouse = params.get("warehouse") || ""; const page = Math.max(1, Number(params.get("page")) || 1);
  const matchingRows = (data?.rows || []).filter(({ order, traces }) => (!factory || order.factory_id === factory) && (!warehouse || order.receipt_warehouse_id === warehouse || traces.some(t => t.shipment.destination_id === warehouse || t.shipment.warehouse_id === warehouse)) && (!q || [order.system_number, order.business_number, order.factory_name, ...(order.lines || []).map(l => l.sku_label)].some(v => (v || "").toLocaleLowerCase().includes(q))));
  const progress = params.get("progress") === "completed" ? "completed" : params.get("progress") === "all" ? "all" : "active";
  const completedCount = matchingRows.filter(row => row.order.production_completion_state === "COMPLETED").length;
  const rows = matchingRows.filter(row => progress === "all" || (row.order.production_completion_state === "COMPLETED") === (progress === "completed"));
  const maxPage = Math.max(1, Math.ceil(rows.length / 20)); const visible = rows.slice((Math.min(page, maxPage) - 1) * 20, Math.min(page, maxPage) * 20);
  const update = (key: string, value: string) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); if (!["page", "batch_page"].includes(key)) { next.delete("page"); next.delete("batch_page"); } setParams(next); };
  const returnTo = `${location.pathname}${location.search}`; const linkState = { overviewReturn: returnTo };
  const pending = data ? scopeStockTotal(data.stock, warehouse, "pending_units") : null;
  const defective = data ? scopeStockTotal(data.stock, warehouse, "defective_units") : null;
  const stockNeedsAttention = pending != null && pending > 0n || defective != null && defective > 0n;
  const clearFilters = () => { const next = new URLSearchParams(params); for (const key of ["q", "factory", "warehouse", "page", "batch_page"]) next.delete(key); setParams(next); };
  return <div className={styles.overview}>
    <header className={styles.pageHeader}>
      <div className={styles.heading}><h1>业务总览</h1>{viewSwitch}</div>
      <div className={styles.actions}>
        <Button variant="quiet" icon={<ClipboardList size={17}/>} onClick={() => document.getElementById("overview-todos")?.scrollIntoView({ behavior: "smooth", block: "center" })}>处理待办</Button>
        <Button variant="quiet" icon={<Download size={17}/>} disabled={!data || result?.pending || !!error} onClick={() => exportRows(rows)}>导出概览</Button>
        <LinkButton variant="primary" to="/production/shipments" state={linkState} icon={<Truck size={17}/>}>查看出货批次</LinkButton>
      </div>
    </header>
    <form className={styles.filters} onSubmit={event => { event.preventDefault(); update("q", search.trim()); }}>
      <div className={styles.search}><Search size={18} aria-hidden="true"/><Input aria-label="订单号 / 款号" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索款号、订单或出货批次"/><Button type="submit" variant="quiet">搜索</Button></div>
      <label>生产工厂<select value={factory} onChange={event => update("factory", event.target.value)}><option value="">全部工厂</option>{data?.factories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>仓库<select value={warehouse} onChange={event => update("warehouse", event.target.value)}><option value="">全部仓库</option>{data?.warehouses.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {(q || factory || warehouse) && <Button variant="quiet" onClick={clearFilters}>清空筛选</Button>}
      <Button variant="quiet" icon={<RefreshCw size={17}/>} onClick={() => setRefresh(value => value + 1)}>刷新</Button>
    </form>
    {!data && !error && <p role="status">正在读取订单、库存和接收数据…</p>}
    {error && <StatusMessage kind="danger" title="总览读取未完成" action={<Button onClick={() => setRefresh(value => value + 1)}>重试</Button>}>{error}</StatusMessage>}
    {data && <>
      <nav className={styles.flowStages} aria-label="业务进度范围"><span>下单</span><span>工厂生产</span><span>生产入库</span><span>仓库出货</span><span>运输跟踪</span><span>目的仓入库</span></nav>
      <div className={styles.layout}>
        <div className={styles.primary}>
          <section className={styles.card} aria-labelledby="overview-orders-title">
            <header className={styles.sectionHeader}><h2 id="overview-orders-title">生产订单进度</h2><span className={styles.count}>{rows.length} 单</span></header>
            <div className={styles.statusTabs} role="group" aria-label="生产完成状态">{[{key:"active",label:"进行中",count:matchingRows.length-completedCount},{key:"completed",label:"已完成",count:completedCount},{key:"all",label:"全部",count:matchingRows.length}].map(choice => <Button key={choice.key} variant="quiet" aria-pressed={progress === choice.key} onClick={() => update("progress",choice.key === "active" ? "" : choice.key)}>{choice.label} {choice.count}</Button>)}</div>
            {!rows.length ? <p className={styles.empty}>{progress === "active" ? "当前没有需要继续跟进的订单。" : progress === "completed" ? "还没有人工确认完成的订单。" : "当前筛选没有已确认订单。"}</p> : <div className={styles.matrix} role="region" aria-label="订单流转矩阵" tabIndex={0}>
              <table className={styles.orderTable} aria-label="生产订单进度">
                <colgroup><col/><col className={styles.factoryColumn}/><col className={styles.numberColumn}/><col className={styles.numberColumn}/><col className={styles.numberColumn}/><col className={styles.phaseColumn}/><col className={styles.completionColumn}/><col className={styles.toggleColumn}/></colgroup>
                <thead><tr><th scope="col">商品 / 订单</th><th scope="col">工厂</th><th scope="col" className={styles.numeric}>下单</th><th scope="col" className={styles.numeric}>已生产</th><th scope="col" className={styles.numeric}>已入库</th><th scope="col">入库进度 / 仓库</th><th scope="col">跟进</th><th scope="col"><span className={styles.srOnly}>展开明细</span></th></tr></thead>
                {visible.map(({ order, traces }) => {
                  const lines = order.lines || [];
                  const produced = lines.length && lines.every(line => numeric(line.produced_units)) ? sum(lines.map(line => line.produced_units!)) : null;
                  const received = numeric(order.received_units) ? BigInt(order.received_units) : null;
                  const pendingReceipt = lines.length && lines.every(line => numeric(line.produced_units) && numeric(line.received_units))
                    ? sum(lines.map(line => { const amount = BigInt(line.produced_units!) - BigInt(line.received_units!) - BigInt(line.production_direct_units || "0"); return amount > 0n ? amount : 0n; })) : null;
                  const styleCodes = [...new Set(lines.map(line => catalog.value?.items.find(sku => sku.sku_id === line.sku_id)?.style_code).filter(Boolean))].join("、");
                  const number = order.business_number || order.system_number;
                  const open = expandedOrders.includes(order.id);
                  return <tbody key={order.id} aria-label={`订单 ${number}`}>
                    <tr className={styles.orderRow} data-expanded={open || undefined}>
                      <th scope="row" className={styles.orderHeading}>
                        <div className={styles.orderIdentity}><Link to={`/production/orders/${order.id}`} state={linkState} title={number}>{styleCodes || number}</Link><span className={styles.specCount}>{order.lines === undefined ? "明细待核" : `${lines.length}规格`}</span></div>
                        {styleCodes && <span className={styles.orderCode} title={number}>{number}</span>}
                      </th>
                      <td className={styles.factoryName}>{order.factory_name || "工厂待核"}</td>
                      <td className={styles.numeric}>{metric("下单", `${units(order.expected_units)} 件`)}</td>
                      <td className={styles.numeric}>{metric("已生产", produced == null ? "未登记" : `${n(produced)} 件`, remaining(produced, order.expected_units, "待产"), ratio(produced, order.expected_units))}</td>
                      <td className={styles.numeric}>{metric("已入库", `${units(order.received_units)} 件`, pendingReceipt == null ? "待入库未登记" : pendingReceipt > 0n ? `待入库 ${n(pendingReceipt)} 件` : undefined, ratio(received, order.expected_units))}</td>
                      <td className={styles.phaseCell}><strong>{!numeric(order.received_units) ? "入库待核" : numeric(order.expected_units) && BigInt(order.received_units) >= BigInt(order.expected_units) ? "已入库" : BigInt(order.received_units) > 0n ? "部分入库" : produced == null ? "生产待登记" : produced > 0n ? "生产中" : "待生产"}</strong><span>{data.warehouses.find(item => item.id === order.receipt_warehouse_id)?.name || "入库仓未登记"}</span></td>
                      <td className={styles.completionCell}><OrderCompletionAction order={order} canWrite={canWrite} reload={() => setRefresh(value => value+1)} saved={updated => setResult(previous => previous?.data ? {...previous,data:{...previous.data,rows:previous.data.rows.map(row => row.order.id === updated.id ? {...row,order:updated} : row)}} : previous)}/></td>
                      <td className={styles.toggleCell}><Button className={styles.traceToggle} variant="quiet" aria-expanded={open} aria-controls={`overview-order-${order.id}-trace`} aria-label={`${open ? "收起" : "展开"}规格与出货批次`} onClick={() => setExpandedOrders(current => open ? current.filter(id => id !== order.id) : [...current, order.id])}>{open ? "收起" : "查看"}</Button></td>
                    </tr>
                    {open && <tr className={styles.detailRow}><td colSpan={8}><section className={styles.traceBody} id={`overview-order-${order.id}-trace`} aria-label={`${order.business_number || order.system_number}规格与出货批次`}><header className={styles.traceHeader}><h3>规格与出货批次</h3><Link className={styles.tableLink} to={`/production/orders/${order.id}`} state={linkState}>查看订单与办理</Link></header><Table className={styles.traceTable} aria-label={`${order.system_number}规格`}><thead><tr><th>商品规格</th><th>计划</th><th>生产</th><th>生产入库</th></tr></thead><tbody>{lines.map(line => <tr key={line.id}><td>{orderProductName(line,catalog.value?.items || [])}</td><td>{units(line.expected_units)}</td><td>{line.produced_units == null ? "未登记" : units(line.produced_units)}</td><td>{units(line.received_units)}</td></tr>)}</tbody></Table>{!!order.receipts?.length && <Disclosure className={styles.batchEvidence}><summary>生产入库记录</summary><Table aria-label={`${number}生产入库记录`}><thead><tr><th>日期</th><th>仓库</th><th>商品</th><th>入库数量</th><th>状态</th></tr></thead><tbody>{order.receipts.map(receipt => <tr key={`${receipt.document_id}:${receipt.line_number}:${receipt.order_line_id}`}><td><Link to={`/production/stock/movements/${receipt.document_id}`} state={linkState}>{receipt.business_date}</Link></td><td>{data.warehouses.find(item => item.id === receipt.warehouse_id)?.name || "仓库待核"}</td><td>{orderProductName(lines.find(line => line.id === receipt.order_line_id) || {sku_id:receipt.sku_id},catalog.value?.items || [])}</td><td>{units(receipt.units)}</td><td>{receipt.status === "POSTED" ? "已入库" : "已冲销"}</td></tr>)}</tbody></Table></Disclosure>}{traces.length ? traces.map(t => <p key={t.shipment.id}><Link to={`/production/shipments/${t.shipment.id}`} state={linkState}>{t.shipment.business_number || t.shipment.system_number}</Link> · 历史订单分配 {n(t.allocated)} · 实收 {n(t.received)} · 结案 {n(t.settled)} · 目的地 {t.shipment.destination || "待核"}<span className={styles.transportTrace}>{transportSummary(t.transport)} · <Link to={`/production/shipments/${t.shipment.id}#transport`} state={linkState}>查看运输与历史</Link></span></p>) : <p className={styles.traceEmpty}>本单暂无明确的出货关联，仓库出货请在下方“出货与到仓进度”查看。</p>}</section></td></tr>}
                  </tbody>;
                })}
              </table>
            </div>}
            {maxPage > 1 && <div className={styles.pager}><Button variant="quiet" disabled={page <= 1} onClick={() => update("page", String(page - 1))}>上一页</Button><span>{Math.min(page, maxPage)} / {maxPage}</span><Button variant="quiet" disabled={page >= maxPage} onClick={() => update("page", String(page + 1))}>下一页</Button></div>}
          </section>
          <OverviewTransitOpening refresh={refresh} warehouse={warehouse} query={q} catalog={catalog.value?.items || []} enabled={!factory} retry={() => setRefresh(value => value+1)}/>
          <OverviewBatchProgress items={data.batches} error={data.batchError} warehouse={warehouse} query={q} catalog={catalog.value?.items || []} page={Math.max(1,Number(params.get("batch_page")) || 1)} changePage={value => update("batch_page",String(value))} refresh={refresh} saved={() => setRefresh(value => value+1)} canWrite={canWrite} linkState={linkState}/>
          <Disclosure className={`${styles.card} ${styles.factorySection}`}>
            <summary><h2>工厂与仓库协同</h2></summary>
            <div className={styles.tableScroll} tabIndex={0}><table className={styles.compactTable} aria-label="工厂与仓库协同"><thead><tr><th>工厂</th><th className={styles.numeric}>订单</th><th>计划入库仓</th><th><span className={styles.srOnly}>操作</span></th></tr></thead><tbody>{data.factories.filter(item => !factory || item.id === factory).map(item => {
              const own = rows.filter(row => row.order.factory_id === item.id);
              const planned = [...new Set(own.map(row => row.order.receipt_warehouse_id).filter((id): id is string => !!id))].map(id => data.warehouses.find(record => record.id === id)?.name || `仓库${id}（待核）`);
              return <tr key={item.id}><td>{item.name}</td><td className={styles.numeric}>{own.length} 单</td><td>{planned.length ? planned.join("、") : "未登记"}</td><td><Link className={styles.tableLink} to={`/production/factories/${item.id}`} state={linkState}>查看工厂</Link></td></tr>;
            })}</tbody></table></div>
          </Disclosure>
        </div>
        <aside className={styles.support} aria-label="库存与待办">
          <section className={styles.card}>
            <header className={styles.sectionHeader}><h2>仓库当前状态</h2></header>
            <div className={styles.tableScroll} tabIndex={0}><table className={`${styles.compactTable} ${styles.warehouseTable}`} aria-label="仓库当前状态"><thead><tr><th>仓库</th><th className={styles.numeric}>在库</th><th><span className={styles.srOnly}>操作</span></th></tr></thead><tbody>{data.warehouses.filter(item => item.status === "ACTIVE" && (!warehouse || item.id === warehouse)).map(item => {
              const scopes = data.stock.scopes.filter(scope => scope.warehouse_id === item.id);
              const items = data.stock.items.filter(record => record.warehouse_id === item.id);
              const complete = scopes.every(scope => items.some(record => record.owner_id === scope.owner_id));
              const onHand = complete ? stockTotal(items, "on_hand_units") : null;
              return <tr key={item.id}><td>{item.name}</td><td className={styles.numeric}>{scopes.length ? n(onHand) : item.type === "FBA" ? "FBA 未接入" : "尚未建账"}</td><td><Link className={styles.tableLink} to={`/production/warehouses/${item.id}`} state={linkState} aria-label="查看仓库"><ChevronRight size={18} aria-hidden="true"/></Link></td></tr>;
            })}</tbody></table></div>
          </section>
          <section id="overview-todos" className={styles.card}>
            <header className={styles.sectionHeader}><h2>待办与异常</h2></header>
            <div className={styles.todo}>
              <Link className={stockNeedsAttention ? styles.attention : undefined} to="/production/stock/movements" state={linkState}><AlertCircle size={18}/><span>待检 <b>{n(pending)}</b> · 次品 <b>{n(defective)}</b></span><ChevronRight size={16}/></Link>
              <Link to="/production/stock/movements" state={linkState}><ClipboardList size={18}/><span>盘点草稿 <b>{data.counts.countDrafts} 笔</b></span><ChevronRight size={16}/></Link>
              <Link to="/production/stock/loans" state={linkState}><FileText size={18}/><span>借出未还 <b>{data.loansLimited ? "查看明细" : `${n(sum(data.loans.filter(loan => (loan.is_active === true || loan.is_active === 1 || loan.is_active === "1") && (!warehouse || loan.warehouse_id === warehouse)).map(loan => loan.outstanding_units)))} 件`}</b></span><ChevronRight size={16}/></Link>
              <Link to="/production/shipments" state={linkState}><Truck size={18}/><span>到仓核验</span><ChevronRight size={16}/></Link>
            </div>
          </section>
        </aside>
      </div>
      <footer><Disclosure className={styles.footnote}><summary>统计口径</summary><p>当前站点 · 数据读取于 {data.loadedAt} · 各业务分别读取，操作后请刷新。</p><p>生产完成筛选仅影响生产订单，不隐藏出货批次；工厂筛选只用于生产订单。仓库出货不按相同SKU推断生产订单归属，只有明确来源分配才显示关联。订单的仓库筛选包含计划入库仓及历史关联出货仓；生产入库、目的仓实收与当前在库分别统计。未收不代表在途，待检与次品不计入当前可发。</p></Disclosure></footer>
    </>}
  </div>;
}

const ProgressOverview = lazy(() => import("./ProductionProgressOverview"));
export function ProductionOverview({canWrite = false}: {canWrite?: boolean}) {
  const [params, setParams] = useSearchParams();
  const viewSwitch = <div className={styles.viewSwitch} role="group" aria-label="总览展示方式">{["flow", "table"].map(view => <Button key={view} variant="quiet" aria-pressed={(params.get("overview_view") === "table" ? "table" : "flow") === view} onClick={() => {const next=new URLSearchParams(params);next.set("overview_view",view);setParams(next);}}>{view === "flow" ? "链路" : "表格"}</Button>)}</div>;
  return params.get("overview_view") === "table" ? <ProductionOverviewTable canWrite={canWrite} viewSwitch={viewSwitch}/> : <Suspense fallback={<p role="status">正在载入进度链…</p>}><ProgressOverview canWrite={canWrite} viewSwitch={viewSwitch}/></Suspense>;
}
