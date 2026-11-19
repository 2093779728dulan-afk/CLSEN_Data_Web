import { useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { AlertTriangle, ClipboardCheck, PackageCheck, Plus, Search } from "lucide-react";
import { Button, FormField, Input, LinkButton, Pagination, StatusMessage, Table } from "../../design-system";
import type { DirectoryRecord } from "./directoryTypes";
import type { Document, DocumentPage, Sku } from "./types";
import { units } from "./types";
import { useLoad, useSearchDraft } from "./useProductionApi";
import { ReadContent } from "./WorkbenchFields";
import { WarehouseMovement } from "./StockWorkspace";
import { orderProductName } from "./orderProgress";
import { WarehouseOrderPanel } from "./WarehouseOrderPanel";
import { WarehouseRecordStatus, WarehouseRecordSteps } from "./WarehouseRecordStatus";
import { DraftShipmentConfirm } from "./WorkbenchOperations";
import { useProductionLeave } from "./useProductionLeave";
import { DestinationReceiptPicker } from "./DestinationReceiptDialog";
import type { WarehouseStock } from "./WarehouseCenter";
import styles from "./WarehouseCenter.module.css";

type MovementLine = { sku_id: string; units: string; quality: string; purpose: string };
type MovementSummary = { id: string; warehouse_id: string; owner_id: string; kind: string; status: string; business_date: string; reason: string; revision?: string; lines?: MovementLine[] };
type DestinationSummary = { id: string; shipment_id: string; status: string; business_date: string | null; reason: string; units: string };
type WarehouseLoan = { id: string; warehouse_id: string; owner_id: string; sku_id: string; borrower: string; outstanding_units: string; is_active?: boolean };
type View = "receive" | "ship";
type AdjustView = "count" | "quality" | "loan";
const total = (lines?: MovementLine[]) => lines ? lines.reduce((sum, line) => sum + BigInt(line.units || "0"), 0n).toString() : undefined;

export function WarehouseRecords({ record, owner, stock, skus, writable, canWrite, refresh, reload, adjust }: { record: DirectoryRecord; owner: string; stock: WarehouseStock; skus: Sku[]; writable: boolean; canWrite: boolean; refresh: number; reload: () => void; adjust: boolean }) {
  const [destinationOpen, setDestinationOpen] = useState(false);
  const [destinationSource, setDestinationSource] = useState("");
  const [params, setParams] = useSearchParams();
  const appliedQuery = params.get("record_q") || "";
  const [query, setQuery] = useSearchDraft(appliedQuery);
  const status = params.get("record_status") || "";
  const date = params.get("record_date") || "";
  const location = useLocation();
  const defaultListOpen = !params.has("document") && !params.has("shipment");
  const [listView, setListView] = useState({ key: location.key, open: defaultListOpen });
  if (listView.key !== location.key) setListView({ key: location.key, open: defaultListOpen });
  const listOpen = listView.key === location.key ? listView.open : defaultListOpen;
  const view = (params.get("mode") === "ship" ? "ship" : "receive") as View;
  const page = Math.max(1, Number(params.get("record_page")) || 1);
  const shipmentPage = Math.max(1, Number(params.get("shipment_page")) || 1);
  const documentQuery = new URLSearchParams({ warehouse_id: record.id, owner_id: owner });
  if (!adjust) Object.entries({ page: String(page), page_size: "10", kind: view === "receive" ? "IN" : "OUT", q: appliedQuery, status, from: date, to: date }).forEach(([key, value]) => { if (value) documentQuery.set(key, value); });
  const documents = useLoad<{ items: MovementSummary[]; total?: number; page?: number; page_size?: number }>(`/api/production/inventory/documents?${documentQuery}`, refresh, true, true);
  const destinations = useLoad<{ items: DestinationSummary[] }>(`/api/production/inventory/destination-receipts?${new URLSearchParams({ warehouse_id: record.id, owner_id: owner })}`, refresh, !adjust && view === "receive", true);
  const shipmentQuery = new URLSearchParams({ warehouse_id: record.id, owner_id: owner, page: String(shipmentPage), page_size: "20", q: appliedQuery, from: date, to: date, status: ({ complete: "CONFIRMED", draft: "DRAFT", cancelled: "VOID" } as Record<string, string>)[status] || "" });
  const shipments = useLoad<DocumentPage>(`/api/production/shipments?${shipmentQuery}`, refresh, !adjust && view === "ship", true);
  const adjustView = (["count", "quality", "loan"].includes(params.get("adjust_view") || "") ? params.get("adjust_view") : "count") as AdjustView;
  const loans = useLoad<{ items: WarehouseLoan[] }>("/api/production/inventory/loans", refresh, !!adjust && adjustView === "loan", true);
  const outstandingLoans = (loans.value?.items || []).filter(item => item.warehouse_id === record.id && item.owner_id === owner && item.is_active !== false && BigInt(item.outstanding_units) > 0n);
  const editing = params.get("editor") === "1";
  const operation = adjust && params.get("operation") === "new";
  function change(values: Record<string, string>) {
    const next = new URLSearchParams(params);
    for (const key of ["receive", "ship", "source_order", "shipment", "receipt_draft", "document", "editor", "operation", "sku_id", "loan_id", "wizard_draft", "source_quality", "return_tab"]) next.delete(key);
    Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    setParams(next);
  }
  const scoped = (documents.value?.items || []).filter(item => item.warehouse_id === record.id && item.owner_id === owner);
  const recordItems = scoped.filter(item => view === "receive" ? item.kind === "IN" : item.kind === "OUT");
  const adjustItems = scoped.filter(item => adjustView === "count" ? item.kind === "ADJUST" : adjustView === "quality" ? item.kind === "MOVE" : item.lines?.some(line => ["BORROW", "RETURN"].includes(line.purpose)));
  const matches = (itemStatus: string, itemDate: string | null, text: string) => {
    const statusMatches = !status || (status === "complete" ? ["POSTED", "CONFIRMED"].includes(itemStatus) : status === "cancelled" ? ["REVERSED", "VOID"].includes(itemStatus) : itemStatus === "DRAFT");
    return statusMatches && (!date || itemDate === date) && text.toLocaleLowerCase().includes(appliedQuery.trim().toLocaleLowerCase());
  };
  const filtered = (adjust ? adjustItems : recordItems).filter(item => matches(item.status, item.business_date, [item.id, item.reason, item.business_date, ...(item.lines || []).flatMap(line => [line.sku_id, line.purpose])].join(" ")));
  const filteredShipments = (shipments.value?.items || []).filter(item => item.warehouse_id === record.id && item.owner_id === owner && matches(item.status, item.business_date, [item.id, item.business_number, item.system_number, item.destination, item.business_date].join(" ")));
  const selected = params.get("document") || filtered[0]?.id || "";
  const selectedShipment = !adjust && view === "ship" && !params.has("ship") ? params.get("shipment") || (!selected ? filteredShipments[0]?.id : undefined) : undefined;
  const context = adjust ? {
    warehouse_id: record.id,
    owner_id: owner,
    kind: adjustView === "count" ? "ADJUST" : adjustView === "quality" ? "MOVE" : params.get("loan_id") ? "IN" : "OUT",
    intent: adjustView === "count" ? "ADJUST" : adjustView === "quality" ? "MOVE" : params.get("loan_id") ? "RETURN" : "BORROW",
    ...(params.get("sku_id") ? { sku_id: params.get("sku_id")! } : {}),
    ...(params.get("loan_id") ? { loan_id: params.get("loan_id")! } : {}),
    ...(adjustView === "quality" && params.get("source_quality") === "PENDING" ? { source_quality: "PENDING" } : {}),
  } : { warehouse_id: record.id, owner_id: owner, kind: view === "receive" ? "IN" : "OUT", intent: view === "receive" ? "IN" : "OUT" };
  function saved(id: string) {
    reload();
    const next = new URLSearchParams(params); next.set("document", id); next.delete("operation"); next.delete("editor"); next.delete("wizard_draft"); setParams(next);
  }
  const panel = !adjust && (params.get("receive") === "1" || params.get("ship") === "1");
  return <ReadContent loading={documents.loading || shipments.loading || loans.loading} error={documents.error || shipments.error} retry={reload}>
    {adjust ? <nav className={styles.subtabs} aria-label="盘点与异常类型">{([["count", "盘点数量"], ["quality", "质量与库位"], ["loan", "借出与归还"]] as const).map(([key, label]) => <Button key={key} variant="quiet" aria-pressed={adjustView === key} onClick={() => change({ tab: "adjust", adjust_view: key })}>{label}</Button>)}</nav> : <nav className={styles.subtabs} aria-label="收发记录类型">{([["receive", "入库"], ["ship", "出货"]] as const).map(([key, label]) => <Button key={key} variant="quiet" aria-pressed={view === key} onClick={() => change({ tab: "records", mode: key, record_page: "1", shipment_page: "1" })}>{label}</Button>)}</nav>}
    {adjust && adjustView === "loan" && <section className={styles.loanBalances} aria-label="本仓待归还"><h2>待归还</h2><p>从原借出登记本次实际归还；待检归还不直接增加可发。</p>{loans.error ? <StatusMessage kind="danger" title="借还余额读取失败"><Button variant="secondary" onClick={reload}>重新读取借还余额</Button></StatusMessage> : loans.loading || !loans.value ? <p role="status">正在读取借还余额…</p> : outstandingLoans.length ? <Table title="本仓未还借出"><thead><tr><th>原借出</th><th>商品</th><th>借用人</th><th>未还</th><th>操作</th></tr></thead><tbody>{outstandingLoans.map(loan => <tr key={loan.id}><td>借出{loan.id}</td><td>{orderProductName({sku_id:loan.sku_id},skus)}</td><td>{loan.borrower}</td><td>{units(loan.outstanding_units)}件</td><td>{writable ? <Button variant="secondary" aria-label={`登记归还：借出${loan.id}`} onClick={() => change({ tab: "adjust", adjust_view: "loan", operation: "new", editor: "1", loan_id: loan.id, sku_id: loan.sku_id })}>登记归还</Button> : "仅查看"}</td></tr>)}</tbody></Table> : <p>当前仓库及货主没有未还借出。</p>}</section>}
    {!adjust && view === "receive" && writable && <Button variant="secondary" onClick={() => { setDestinationSource(""); setDestinationOpen(true); }}>登记目的仓实收</Button>}
    {destinationOpen && <DestinationReceiptPicker warehouseId={record.id} ownerId={owner} initialShipmentId={destinationSource} canWrite={writable} close={() => { setDestinationOpen(false); reload(); }} saved={() => {}} />}
    {!adjust && <Button variant="secondary" className={styles.recordToggle} aria-expanded={listOpen} onClick={() => setListView({ key: location.key, open: !listOpen })}>{listOpen ? "收起记录列表" : "返回记录列表"}</Button>}
    <div className={[styles.recordLayout, !adjust && !listOpen && styles.recordFocused, adjust && styles.recordLayoutSingle].filter(Boolean).join(" ")}>
      <section className={styles.recordList}>
        <header><div><h2>{adjust ? adjustView === "count" ? "盘点记录" : adjustView === "quality" ? "质量与库位记录" : "借出与归还记录" : "收发记录"}</h2></div>{writable && !adjust ? <LinkButton variant="primary" icon={<Plus size={16}/>} to={view === "ship" ? `/production/shipments/new?${new URLSearchParams({flow:"guided",purpose:"WAREHOUSE_DISPATCH",warehouse_id:record.id,owner_id:owner,return_to:`/production/warehouses/${record.id}?tab=records&mode=ship&owner=${owner}`})}` : `/production/orders/receipts/new?${new URLSearchParams({warehouse_id:record.id,owner_id:owner,return_to:`/production/warehouses/${record.id}?tab=records&mode=receive&owner=${owner}`})}`}>{view==="ship"?"新建出货单":"新建入库"}</LinkButton> : writable && <Button variant="primary" icon={<Plus size={16} />} onClick={() => adjust ? change({ tab: "adjust", adjust_view: adjustView, operation: "new", editor: "1" }) : change({ tab: "records", mode: view, [view === "receive" ? "receive" : "ship"]: "1" })}>{adjust ? adjustView === "count" ? "新建盘点" : adjustView === "quality" ? "登记变化" : "登记借出" : view === "receive" ? "新建入库" : "新建出货单"}</Button>}</header>
        {adjust && <p className={styles.recordScope}>最近200笔库存记录</p>}
        {!adjust && view === "receive" && <section aria-label="目的仓实收记录"><h3>目的仓实收</h3>{destinations.error ? <StatusMessage kind="danger" title="实收记录读取失败">{destinations.error}</StatusMessage> : destinations.value ? <Table aria-label="目的仓实收列表"><thead><tr><th>接收</th><th>状态</th><th>件数</th></tr></thead><tbody>{destinations.value.items.map(item => <tr key={item.id}><th scope="row"><Button variant="quiet" onClick={() => { setDestinationSource(item.shipment_id); setDestinationOpen(true); }}>接收{item.id} · 出货{item.shipment_id}</Button></th><td>{item.status === "POSTED" ? "已入库" : item.status === "DRAFT" ? "草稿" : "已撤销"}</td><td>{units(item.units)}件</td></tr>)}</tbody></Table> : <p role="status">正在读取目的仓实收…</p>}</section>}
        <form className={styles.recordSearch} onSubmit={event => { event.preventDefault(); change({ record_q: query.trim(), record_page: "1", shipment_page: "1" }); }}><Search size={17} aria-hidden="true" /><Input aria-label="搜索本仓记录" type="search" placeholder="搜索单号、目的地或依据" value={query} onChange={event => setQuery(event.target.value)} /><Button type="submit" variant="quiet">查询</Button></form>
        <div className={styles.recordFilters}><FormField label="记录状态"><select value={status} onChange={event => change({ record_status: event.target.value, record_page: "1", shipment_page: "1" })}><option value="">全部状态</option><option value="draft">草稿</option><option value="complete">{adjust ? "已过账" : view === "receive" ? "已入库" : "已完成出库 / 发货"}</option><option value="cancelled">已冲销 / 已作废</option></select></FormField><FormField label="记录日期"><Input type="date" value={date} onChange={event => change({ record_date: event.target.value, record_page: "1", shipment_page: "1" })} /></FormField>{(status || date || appliedQuery || query) && <Button variant="quiet" onClick={() => { setQuery(""); change({ record_status: "", record_date: "", record_q: "", record_page: "1", shipment_page: "1" }); }}>清空</Button>}</div>
        {documents.error && <StatusMessage kind="danger" title="本仓库存记录读取失败">{documents.error}</StatusMessage>}
        {documents.value ? <Table aria-label={adjust ? "盘点与异常记录" : view === "receive" ? "入库记录" : "出库记录"}><thead><tr><th>单号</th><th>状态</th><th>数量</th><th>日期</th></tr></thead><tbody>{filtered.map(item => { const amount = total(item.lines); return <tr key={item.id} aria-current={!selectedShipment && selected === item.id ? "true" : undefined}><th scope="row"><Button variant="quiet" onClick={() => change({ tab: adjust ? "adjust" : "records", ...(adjust ? { adjust_view: adjustView } : { mode: view }), document: item.id })}>库存单 {item.id}</Button><small>{item.reason || "依据未填写"}</small></th><td><WarehouseRecordStatus status={item.status} kind={item.kind} /></td><td>{amount == null ? "待核" : `${units(amount)}件`}</td><td>{item.business_date}</td></tr>; })}{!filtered.length && <tr><td colSpan={4}>当前范围没有匹配记录。未知和未读取不会显示为0。</td></tr>}</tbody></Table> : !documents.error && <p className={styles.note}>正在读取本仓记录…</p>}
        {!adjust && documents.value?.total != null && <Pagination itemLabel="库存记录" page={documents.value.page || page} totalItems={documents.value.total} totalPages={Math.max(1, Math.ceil(documents.value.total / 10))} onPageChange={value => change({ record_page: String(value) })} />}
        {!adjust && view === "ship" && <section className={styles.shipmentList}><h3>发货与装箱批次</h3>{shipments.error && <StatusMessage kind="danger" title="发货批次读取失败">{shipments.error}</StatusMessage>}{shipments.value && <Table aria-label="发货与装箱记录"><thead><tr><th>单号 / 目的地</th><th>状态</th><th>数量</th></tr></thead><tbody>{filteredShipments.map(item => <tr key={item.id} aria-current={selectedShipment === item.id ? "true" : undefined}><th scope="row"><Button variant="quiet" onClick={() => change({ tab: "records", mode: "ship", shipment: item.id })}>{item.business_number || item.system_number}</Button><small>{item.destination || "目的地待核"} · {item.business_date}</small></th><td><WarehouseRecordStatus status={item.status} shipment /></td><td>{units(item.actual_units)}件</td></tr>)}{!filteredShipments.length && <tr><td colSpan={3}>当前范围没有发货批次或装箱草稿。</td></tr>}</tbody></Table>}{shipments.value && <Pagination itemLabel="发货批次" page={shipments.value.page || shipmentPage} totalItems={shipments.value.total} totalPages={Math.max(1, Math.ceil(shipments.value.total / 20))} onPageChange={value => change({ shipment_page: String(value) })} />}</section>}
        {adjust && adjustView === "loan" && <p className={styles.loanLink}><Link to="/production/stock/loans">查看完整借还余额及登记归还</Link></p>}

      </section>
      <section className={adjust && (operation || (editing && scoped.find(item => item.id === selected)?.status === "DRAFT")) ? styles.recordModalHost : styles.recordDetail} aria-label={adjust ? "盘点与异常详情" : "收发记录详情"}>
        {panel ? <WarehouseOrderPanel mode={view} record={record} owner={owner} stock={stock} canWrite={canWrite} close={() => change({ tab: "records", mode: view })} saved={reload} refresh={refresh} /> : selectedShipment ? <WarehouseShipmentDetails key={selectedShipment} id={selectedShipment} record={record} owner={owner} canWrite={writable} refresh={refresh} reload={reload} skus={skus} /> : selected || operation ? <WarehouseMovement key={`${operation ? "new" : selected}:${JSON.stringify(context)}`} id={operation ? undefined : selected || undefined} context={context} canWrite={canWrite} refresh={refresh} editing={editing} edit={() => { const next = new URLSearchParams(params); next.set("editor", "1"); setParams(next); }} saved={saved} close={() => change(params.get("return_tab") === "stock" ? { tab: "stock" } : { tab: "adjust", adjust_view: adjustView, ...(selected ? { document: selected } : {}) })} /> : <div className={styles.detailEmpty}>{adjust ? <ClipboardCheck size={34} /> : view === "receive" ? <PackageCheck size={34} /> : <AlertTriangle size={34} />}<h2>{adjust ? "选择一笔记录核对" : view === "receive" ? "选择入库记录或新建入库" : "选择出库记录或新建出货单"}</h2><p>{adjust ? "草稿、预览和确认分别显示；未确认不会改变库存。" : "入库草稿确认前不改变库存；装箱草稿不会扣库存或计入已发。"}</p></div>}
      </section>
    </div>
  </ReadContent>;
}

function WarehouseShipmentDetails({ id, record, owner, canWrite, refresh, reload, skus }: { id: string; record: DirectoryRecord; owner: string; canWrite: boolean; refresh: number; reload: () => void; skus:Sku[] }) {
  const document = useLoad<Document>(`/api/production/shipments/${id}`, refresh);
  const [commandState, setCommandState] = useState({ busy: false, unknown: false });
  const [reviewing, setReviewing] = useState(false);
  const leave = useProductionLeave(false, commandState.busy, commandState.unknown);
  const item = document.value;
  if (!item) return <StatusMessage kind={document.error ? "danger" : "info"} title={document.error ? "发货批次读取失败" : "正在读取发货批次"}>{document.error}</StatusMessage>;
  if (item.warehouse_id !== record.id || item.owner_id !== owner) return <StatusMessage kind="danger" title="发货批次不属于当前仓库及货主" />;
  return <div className={styles.movementReview}><header className={styles.reviewHeading}><h2>{item.status === "DRAFT" ? "核对装箱草稿" : "发货批次详情"}</h2><WarehouseRecordStatus status={item.status} shipment /></header><p className={styles.note}>单号：{item.business_number || item.system_number} · {item.business_date}</p><WarehouseRecordSteps status={item.status} shipment preview={reviewing} /><div className={styles.destinationSummary}><span>发往目的地</span><strong>{item.destination || "目的地待核"}</strong><small>发货记录表示本仓交接，不表示目的仓已签收。</small></div><section><h3>出货商品明细</h3><Table aria-label="发货商品明细"><thead><tr><th>商品规格</th><th>数量</th><th>来源订单</th></tr></thead><tbody>{item.sources?.map((source, index) => <tr key={source.id || index}><th scope="row">{orderProductName(source,skus)}</th><td>{units(source.actual_units)}件</td><td>{source.allocations.map(allocation => <p key={allocation.order_line_id}>{allocation.order_id ? <Link to={`/production/orders/${allocation.order_id}`}>{allocation.order_business_number || allocation.order_number || `订单 ${allocation.order_id}`}</Link> : `订单行 ${allocation.order_line_id}`} · {units(allocation.units)}件</p>)}</td></tr>)}</tbody></Table></section><section><h3>装箱明细（{item.cartons?.length || 0}箱）</h3><Table aria-label="发货装箱明细"><thead><tr><th>箱号</th><th>商品规格</th><th>件数</th></tr></thead><tbody>{item.cartons?.flatMap(box => box.items.map((line, index) => <tr key={`${box.id || box.number}:${index}`}><th scope="row">{box.number}</th><td>{orderProductName({sku_id:line.sku_id,sku_label:item.sources?.find(source => source.sku_id === line.sku_id)?.sku_label},skus)}</td><td>{units(line.units)}</td></tr>))}{!item.cartons?.length && <tr><td colSpan={3}>尚未登记装箱明细。</td></tr>}</tbody></Table></section>{item.status === "DRAFT" ? <StatusMessage kind="warning" title="装箱草稿尚未扣库存">核对目的地、商品及装箱数量后，再确认实际发货。</StatusMessage> : <StatusMessage kind={item.status === "VOID" ? "danger" : "success"} title={item.status === "VOID" ? "本批已作废，原记录保留" : "本批已确认发货"}>实际数量与库存结果可从完整单据及操作历史核对。</StatusMessage>}{canWrite && item.status === "DRAFT" && <DraftShipmentConfirm document={item} dirty={false} saved={reload} onStateChange={setCommandState} onReviewChange={setReviewing} compact />}{canWrite && item.status === "DRAFT" && item.sources?.length && item.sources.every(source => source.allocations.length && source.allocations.every(allocation => allocation.order_id && allocation.order_id === item.sources?.[0]?.allocations[0]?.order_id)) ? <LinkButton variant="secondary" to={`?${new URLSearchParams({ tab: "records", mode: "ship", ship: "1", owner, source_order: item.sources[0]!.allocations[0]!.order_id!, shipment: id })}`}>继续分步编辑装箱草稿</LinkButton> : null}<LinkButton variant="secondary" to={`/production/shipments/${id}`}>打开完整出货单，查看历史或编辑</LinkButton>{leave.prompt}</div>;
}

