import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { Link } from "react-router-dom";
import { Plus, Search, X } from "lucide-react";
import { Button, Input, LinkButton, Pagination, StatusMessage, Table } from "../../design-system";
import { OrderCompletionAction } from "./OrderCompletionAction";
import { OrderProgressDialog } from "./OrderProgressDialog";
import { knownOrderSum, orderProductName } from "./orderProgress";
import { statusName, units, type Document, type DocumentPage, type Sku } from "./types";
import type { WarehouseScope } from "./WorkbenchFields";
import styles from "./FactoryOrderOverview.module.css";

export function FactoryOrderOverview({ data, error, loading, catalog, scopes, canWrite, query, setQuery, appliedQuery, change, filters, tools, notice, retry, saved, search, blocked, onCreate, createTrigger, noticeAction }: {
  data?: DocumentPage; error?: string; loading: boolean; catalog: Sku[]; scopes: WarehouseScope[]; canWrite: boolean;
  query: string; setQuery: (query: string) => void; appliedQuery: string; change: (values: Record<string, string>, id?: string, replace?: boolean) => void;
  onCreate: () => void; createTrigger: RefObject<HTMLButtonElement | null>; noticeAction?: ReactNode;
  filters: ReactNode; tools: ReactNode; notice: string; retry: () => void; saved: () => void; search: URLSearchParams; blocked: boolean;
}) {
  const [composing, setComposing] = useState(false);
  const creating = search.get("new") === "1";
  const progress = search.get("progress") === "completed" ? "completed" : search.get("progress") === "all" ? "all" : "active";
  const latestChange = useRef(change); latestChange.current = change;
  useEffect(() => {
    if (creating || composing || query.trim() === appliedQuery) return;
    const timer = window.setTimeout(() => latestChange.current({q:query.trim(),page:"1",new:"",edit:""},"",true),300);
    return () => window.clearTimeout(timer);
  },[query,appliedQuery,composing,creating]);
  const [editor, setEditor] = useState<{ order: Document; line?: string; trigger: HTMLElement }>();
  const actionOrder = data?.items.find(order => order.id === search.get("action_order"));
  const groups = new Map<string, Document[]>();
  for (const order of data?.items || []) { const id = order.factory_id || "unknown"; groups.set(id, [...(groups.get(id) || []), order]); }
  const orderUrl = (order: Document, tab = "progress") => { const next = new URLSearchParams(search); next.set("tab", tab); return `/production/orders/${order.id}?${next}`; };
  return <section className={styles.workspace} aria-label="工厂订单跟进总览">
    <header className={`ui-page-header ${styles.header}`}><div className={styles.title}><h1>订单跟进</h1>{data && <span className={styles.count}>{data.total} 单</span>}</div><div className={styles.actions}>{canWrite && <LinkButton variant="secondary" to={`/production/orders/receipts/new${search.get("factory") ? `?factory=${encodeURIComponent(search.get("factory")!)}` : ""}`}>批量入库</LinkButton>}{canWrite && <LinkButton variant="secondary" to="/production/shipments/intake">仓库出货</LinkButton>}{tools}{canWrite && <Button ref={createTrigger} variant="primary" icon={<Plus size={16}/>} onClick={onCreate}>下单</Button>}</div></header>
    <div className={styles.statusTabs} role="group" aria-label="生产完成状态">{[{value:"active",label:"进行中"},{value:"completed",label:"已完成"},{value:"all",label:"全部"}].map(choice => <Button key={choice.value} variant="quiet" aria-pressed={progress === choice.value} onClick={() => change({progress:choice.value === "active" ? "" : choice.value,page:"1",action_order:""},"")}>{choice.label}{data?.progress_counts && <span>{data.progress_counts[choice.value as keyof NonNullable<DocumentPage["progress_counts"]>]}</span>}</Button>)}</div>
    <div className={styles.filters}><form className={styles.search} onSubmit={event => { event.preventDefault(); if (!composing) change({ q: query.trim(), page: "1", new: "", edit: "" }, "",true); }}><Search size={18} aria-hidden="true"/><Input aria-label="搜索工厂、订单或SKU" type="search" placeholder="搜索款号、订单号或工厂" value={query} onCompositionStart={() => setComposing(true)} onCompositionEnd={() => setComposing(false)} onChange={event => setQuery(event.target.value)} />{query && <Button variant="quiet" aria-label="清除搜索" icon={<X size={16}/>} onClick={() => {setQuery("");change({q:"",page:"1"},"",true);}}/>}</form>{filters}</div>
    {actionOrder && <section className={styles.orderActions} aria-label="订单统一操作"><div className={styles.selectedOrder}><span>已选择</span><strong title={actionOrder.business_number || actionOrder.system_number}>{actionOrder.business_number || actionOrder.system_number}</strong></div><div className={styles.actions}>{canWrite && actionOrder.status === "CONFIRMED" && !blocked && <LinkButton variant="secondary" to={orderUrl(actionOrder, "receive")}>入库</LinkButton>}<LinkButton variant="secondary" to={`/production/overview?overview_view=flow&trace_kind=order&trace_id=${actionOrder.id}`} state={{ordersReturn:`/production/orders?${search}`}}>查看链路</LinkButton><LinkButton variant="secondary" to={orderUrl(actionOrder, "history")}>操作记录</LinkButton><LinkButton variant="secondary" reloadDocument to={`/api/production/orders/${actionOrder.id}/table`}>导出下单表</LinkButton><Button variant="quiet" aria-label="清除订单选择" icon={<X size={16}/>} onClick={() => change({action_order:""},"",true)}/></div></section>}
    {data && search.get("action_order") && !actionOrder && <StatusMessage kind="info" title="所选订单不在当前结果中" action={<Button variant="quiet" onClick={() => change({action_order:""},"",true)}>清除订单选择</Button>}>请重新选择订单。</StatusMessage>}
    {notice && <StatusMessage kind="success" title={notice} action={noticeAction} />}
    {error && <StatusMessage kind="danger" title="订单进度读取失败" action={<Button onClick={retry}>重试读取订单</Button>}>{error}{data && " 当前显示上次读取的内容，更新前请重新读取。"}</StatusMessage>}
    {loading && <p role="status">正在读取订单进度…</p>}
    {data && <>
      {[...groups].map(([factory, orders]) => <section key={factory} className={styles.factory} aria-label={`${orders[0]?.factory_name || "工厂未登记"}订单`}><h2>{orders[0]?.factory_name || "工厂未登记"}</h2>{orders.map(order => {
        const all = order.lines || [];
        const q = appliedQuery.toLocaleLowerCase();
        const wholeOrder = !q || [order.business_number, order.system_number, order.factory_name].some(value => value?.toLocaleLowerCase().includes(q));
        const lines = wholeOrder ? all : all.filter(line => [orderProductName(line, catalog), line.sku_label, catalog.find(sku => sku.sku_id === line.sku_id)?.style_code].some(value => value?.toLocaleLowerCase().includes(q)));
        const planned = order.lines === undefined ? null : knownOrderSum(all.map(line => line.planned_production_units ?? line.expected_units));
        const produced = knownOrderSum(all.map(line => line.produced_units));
        return <article key={order.id} className={styles.order} data-selected={actionOrder?.id === order.id || undefined} aria-label={`订单 ${order.business_number || order.system_number}`}>
          <header className={styles.orderHeader}><div className={styles.orderIdentity}><input type="radio" name="overview-order" aria-label={`选择订单 ${order.business_number || order.system_number}`} checked={actionOrder?.id === order.id} disabled={loading} onChange={() => change({action_order:order.id},"",true)}/><div><h3><Link to={orderUrl(order)} title={order.business_number || order.system_number}>{order.business_number || order.system_number}</Link><small>{statusName[order.status]}{order.tracking_state === "CLOSED" ? " · 跟进已关闭" : ""}</small></h3><p><time>{order.business_date || "日期未登记"}</time> · {scopes.find(scope => scope.warehouse_id === order.receipt_warehouse_id && scope.owner_id === order.receipt_owner_id)?.warehouse_name || "入库仓库未登记"}{order.destination ? ` → ${order.destination}` : ""}</p></div></div><div className={styles.actions}><OrderCompletionAction order={order} canWrite={canWrite} blocked={blocked} saved={() => saved()} reload={retry}/>{canWrite && order.status === "CONFIRMED" && all.some(line => line.tracking_state !== "CLOSED") && <Button variant="secondary" disabled={blocked} onClick={event => setEditor({ order, trigger: event.currentTarget })}>批量更新生产进度</Button>}</div></header>
          <p className={styles.totals}>全单 {all.length}个规格 · 计划生产{planned == null ? "未登记完整" : `${units(planned)}件`} · 已生产{produced == null ? "未登记完整" : `${units(produced)}件`} · 已入库{units(order.received_units)}件</p>
          {!wholeOrder && <p className={styles.note}>当前显示匹配商品的{lines.length}个规格，全单共{all.length}个；上方数量为全单合计。<Link to={orderUrl(order)}>查看完整订单</Link></p>}
          {order.lines === undefined ? <StatusMessage kind="warning" title="产品明细暂不可用">请从订单详情核对，不将缺失明细计作0。</StatusMessage> : <Table aria-label={`${order.business_number || order.system_number}逐产品进度`} className={styles.progressTable}><thead><tr><th>商品规格</th><th>计划生产</th><th>已生产</th><th>已入库</th><th>生产状态</th></tr></thead><tbody>{lines.map(line => <tr key={line.id}><th scope="row">{orderProductName(line, catalog)}{line.tracking_state === "CLOSED" && <small>跟进已关闭</small>}</th><td>{units(line.planned_production_units ?? line.expected_units)}</td><td>{canWrite && !blocked && order.status === "CONFIRMED" && line.tracking_state !== "CLOSED" ? <Button variant="quiet" aria-label={`更新 ${orderProductName(line, catalog)} 生产进度`} onClick={event => setEditor({ order, line: line.id, trigger: event.currentTarget })}>{line.produced_units == null ? "未登记" : units(line.produced_units)}</Button> : line.produced_units == null ? "未登记" : units(line.produced_units)}</td><td>{units(line.received_units)}</td><td>{line.production_status || ""}</td></tr>)}</tbody></Table>}

        </article>;
      })}</section>)}
      {!data.items.length && <p className={styles.empty}>{progress === "active" ? "没有匹配的订单。可切换到已完成或全部查看。" : "没有匹配的订单，请调整筛选或切换完成状态。"}</p>}
      <Pagination itemLabel="订单" page={data.page} totalItems={data.total} totalPages={Math.max(1, Math.ceil(data.total / (data.page_size || 20)))} onPageChange={page => change({ page: String(page) }, "")} />
    </>}
    {editor && <OrderProgressDialog readBlocked={blocked} order={editor.order} catalog={catalog} focusLine={editor.line} returnFocus={editor.trigger} close={() => setEditor(undefined)} saved={() => { setEditor(undefined); saved(); }} />}
  </section>;
}
