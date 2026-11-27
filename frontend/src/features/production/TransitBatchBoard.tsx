import { Disclosure } from "../../design-system";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, FormField, Input, LinkButton, Pagination, StatusMessage, Table } from "../../design-system";
import { useLoad, useSearchDraft } from "./useProductionApi";
import type { TransitItem } from "./WarehouseTransit";
import { TransitOpening, type TransitOpeningRow } from "./TransitOpening";
import { stockAmount } from "./stockOverview";
import { transportStatus, transportTime } from "./transport";
import styles from "./TransitBatchBoard.module.css";

type BatchPage = { items: TransitItem[]; total: number; page: number; page_size: number; as_of: string; detail_scope: string; opening_balances?: TransitOpeningRow[] };
const stages: Record<string, string> = { RECEIVED: "已收清", EXCEPTION: "运输异常", ARRIVAL_CHECK: "到仓待核", SETTLED: "差异已结案", IN_TRANSIT: "运输中", UNREGISTERED: "运输未登记 / 待核" };
const quantity = (value: string | null | undefined) => value == null ? "待核" : `${value}件`;
const eta = (item: TransitItem) => item.transport.record?.arrival_local ? transportTime(item.transport.record.arrival_local, item.transport.record.arrival_timezone) : "未填写";

export function TransitBatchBoard({ refresh, selectedId, legacySku, change, open, onReady, verify, canWrite = false }: {
  refresh: number; selectedId?: string; legacySku?: string;
  change: (values: Record<string, string>) => void;
  open: (id: string, trigger: HTMLElement) => void;
  onReady?: () => void;
  canWrite?: boolean; verify?: (item: TransitItem, trigger: HTMLElement) => void;
}) {
  const [params] = useSearchParams();
  const page = /^[1-9][0-9]{0,5}$/.test(params.get("stock_batch_page") || "") ? Number(params.get("stock_batch_page")) : 1;
  const query = params.get("stock_batch_q") || "", node = params.get("stock_batch_node") || "";
  const [draft, setDraft] = useSearchDraft(query);
  const [revision, setRevision] = useState(0);
  const data = useLoad<BatchPage>(`/api/production/inventory/transit-batches?${new URLSearchParams({ page: String(page), page_size: "5", q: query, node, ...(legacySku ? { sku_id: legacySku } : {}) })}`, `${refresh}:${revision}`, true, true);
  const { current: boardCurrent, value: boardValue } = data;
  useEffect(() => { if (boardCurrent) onReady?.(); }, [boardCurrent, boardValue, onReady]);
  const value = data.value?.detail_scope === "whole_batch" ? data.value : undefined;
  return <aside className={styles.board} aria-label="整批运输看板">
    <header className={styles.heading}><div><h2 tabIndex={-1} data-transit-heading>运输看板</h2><p>按整批查看 · 全部仓库</p></div></header>
    <p className={styles.note}>每批只列一次；批内包含全部SKU，不随左侧库存筛选改变。在途、签收和ETA均不增加在库。</p>
    {legacySku && <StatusMessage kind="info" title="旧SKU运输链接已转为整批查询">当前列出包含SKU {legacySku}的批次，每批仍显示全部规格。<Button variant="quiet" onClick={() => change({ stock_detail: "stock", sku_detail: "", stock_batch_page: "" })}>查看全部批次</Button></StatusMessage>}
    <Disclosure className={styles.filters}><summary>筛选运输批次{query || node ? "（已筛选）" : ""}</summary><form onSubmit={event => { event.preventDefault(); change({ stock_batch_q: draft.trim(), stock_batch_page: "" }); }}>
      <FormField label="运输批次或SKU"><Input value={draft} onChange={event => setDraft(event.target.value)} /></FormField>
      <FormField label="最新物流节点"><select value={node} onChange={event => change({ stock_batch_node: event.target.value, stock_batch_page: "" })}><option value="">全部节点</option><option value="IN_TRANSIT">已发运 / 运输中</option><option value="ARRIVED">物流到达</option><option value="SIGNED">物流签收</option><option value="EXCEPTION">运输异常</option><option value="UNREGISTERED">运输未登记</option></select></FormField>
      <div><Button type="submit" variant="secondary">查找批次</Button><Button variant="quiet" onClick={() => { setDraft(""); change({ stock_batch_q: "", stock_batch_node: "", stock_batch_page: "" }); }}>清除运输筛选</Button></div>
    </form></Disclosure>
    {data.error && <StatusMessage kind="danger" title="运输看板读取未完成">{data.error}。旧内容仅供参考，失败不当成没有运输。<Button onClick={() => setRevision(v => v + 1)}>重试运输</Button></StatusMessage>}
    {data.value && !value && <StatusMessage kind="danger" title="运输批次范围未确认">服务未返回整批范围，不能把单SKU数量显示为整批数量。</StatusMessage>}
    {!data.value && !data.error && <p role="status">正在读取运输批次…</p>}
    {value && <><div className={styles.cards}>{value.items.map(item => <article className={styles.card} key={item.id}>
      <Button data-transit-batch={item.id} aria-expanded={selectedId === item.id} aria-label={`查看整批运输 ${item.business_number || item.system_number}`} variant="quiet" className={styles.batchButton} onClick={event => open(item.id, event.currentTarget)}><strong>{item.business_number || item.system_number}</strong><span>{stages[item.stage] || "批次状态待核"}</span></Button>
      <p className={styles.route}>{item.source_name || "来源待核"} → {item.destination_name || "目的仓待核"}</p>
      <p>{new Set(item.sources.map(source => source.sku_id)).size}个SKU · 已发{quantity(item.shipped_units)} · 实收{quantity(item.received_units)} · 未收{quantity(item.unreceived_units)}</p>
      <p className={styles.note}>预计到达 {eta(item)}</p>{item.eta_overdue && <p className={styles.warning}>已超过ETA，尚无到达记录</p>}{canWrite&&verify&&data.current&&item.destination_id&&!["RECEIVED","SETTLED"].includes(item.stage)&&<Button variant="secondary" aria-label={`开始到仓核验 ${item.business_number||item.system_number}`} onClick={event=>verify(item,event.currentTarget)}>开始到仓核验</Button>}
    </article>)}</div><TransitOpening rows={value.opening_balances}/>{!value.items.length && !value.opening_balances?.length && <StatusMessage kind="info" title="当前没有匹配的运输批次">可调整运输筛选；没有记录不代表库存为零。</StatusMessage>}
      <Pagination itemLabel="批次" page={value.page} totalItems={value.total} totalPages={Math.max(1, Math.ceil(value.total / value.page_size))} onPageChange={next => change({ stock_batch_page: String(next) })} />
      <p className={styles.note}>本页{value.items.length}批 / 共{value.total}批，包含运输、待核及接收历史；读取于{value.as_of}。</p>
    </>}
  </aside>;
}

export function TransitBatchDetail({ id, refresh, canWrite, verify }: { id: string; refresh: number; canWrite: boolean; verify?: (item: TransitItem, trigger: HTMLElement) => void }) {
  const [revision, setRevision] = useState(0);
  const valid = /^[1-9][0-9]*$/.test(id);
  const data = useLoad<BatchPage>(`/api/production/inventory/transit-batches?${new URLSearchParams({ shipment_id: id, page_size: "1" })}`, `${refresh}:${revision}`, valid, true);
  const item = data.value?.detail_scope === "whole_batch" ? data.value.items.find(batch => batch.id === id) : undefined;
  if (!valid) return <StatusMessage kind="danger" title="运输批次标识无效">请从运输看板选择明确批次。</StatusMessage>;
  return <section className={styles.detail} aria-label="整批运输明细">
    
    {data.error && <StatusMessage kind="danger" title="整批运输读取未完成">{data.error}。旧内容仅供参考，不能当成零。<Button onClick={() => setRevision(v => v + 1)}>重试整批</Button></StatusMessage>}
    {!data.value && !data.error && <p role="status">正在读取整批货物…</p>}
    {data.value && !item && <StatusMessage kind="warning" title="当前范围没有这笔完整批次">请返回运输看板重选；不会用其他批次或单SKU代替。</StatusMessage>}
    {item && <><header><h3>{item.business_number || item.system_number}</h3><p>{stages[item.stage] || "状态待核"} · {item.source_name || "来源待核"} → {item.destination_name || "目的仓待核"}</p></header>
      <dl className={styles.metrics}>{[["整批已发", item.shipped_units], ["累计实收", item.received_units], ["未收", item.unreceived_units], ["差异已结案", item.settled_units]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{quantity(value)}</dd></div>)}</dl>
      <p className={styles.note}>整批所有规格，货权 {item.owner_id}；未收含待核及结案差异，不等于运输中。FBA为本地事件账，物流签收及ETA不自动入库。</p>
      <p>实际发出：{item.departed ? transportTime(item.departed.occurred_local, item.departed.timezone) : "未登记"}</p><p>预计到达：{eta(item)}</p><p>物流到达：{item.arrived ? transportTime(item.arrived.occurred_local, item.arrived.timezone) : "未登记"}</p><p>仓库实收日：{item.receipt_dates.length ? item.receipt_dates.join(" / ") : "未登记"} · 耗时：{item.duration_hours == null ? "待核" : `${item.duration_hours}小时`}</p>
      {item.transport.source_revision_current === false && <StatusMessage kind="warning" title="运输资料仍关联原出货修订">请在原出货核对更正后的来源和运输资料。</StatusMessage>}
      <Table title="整批SKU明细"><thead><tr><th>商品规格 / SKU</th><th>已发</th><th>实收</th><th>未收</th><th>货物来源</th></tr></thead><tbody>{item.sources.map(source => <tr key={source.id}><th>{source.sku_label}<small> · SKU {source.sku_id}</small></th><td>{stockAmount(source.actual_units)}</td><td>{stockAmount(source.received_units)}</td><td>{stockAmount(source.unreceived_units)}</td><td><Disclosure><summary>查看发货来源</summary>{source.bindings.length ? source.bindings.map(binding => <p key={`${binding.carton_id}:${binding.allocation_id}`}>{binding.carton_id?`发货箱 ${item.cartons?.find(box=>String(box.id)===binding.carton_id)?.number||"箱号待核"}`:"本批货物"} · 发出{binding.units}件，已收{binding.received_units}件</p>) : <p>本批出货来源尚未核对，实收数量保持待核。</p>}{source.allocations.map((allocation, index) => <p key={index}>关联订单 {allocation.order_number} · {allocation.units}件</p>)}{!source.allocations.length&&<p>{["LOGISTICS_TRANSFER","WAREHOUSE_DISPATCH"].includes(item.dispatch_purpose)?"按仓库库存出货，无需关联生产订单。":"关联订单尚未登记。"}</p>}</Disclosure></td></tr>)}</tbody></Table>
      <Disclosure><summary>物流节点（{item.transport.events.length}条）</summary>{item.transport.events.length ? item.transport.events.map(event => <article key={event.id}><strong>{transportStatus[event.event_kind]}</strong><p>{transportTime(event.occurred_local, event.timezone)}</p><p>{event.location} · {event.description}</p><p>依据：{event.source_reference || "未登记"}{event.event_kind === "SIGNED" && ` · 承运商累计签收 ${quantity(event.signed_units)}`}</p></article>) : <p>运输节点未登记，不能推断已发运或到达。</p>}</Disclosure>
      <footer><LinkButton variant="secondary" to={`/production/shipments/${item.id}#transport`}>查看原出货与运输</LinkButton>{canWrite && data.current && item.destination_id && <Button variant="primary" disabled={!verify||["RECEIVED","SETTLED"].includes(item.stage)} onClick={event=>verify?.(item,event.currentTarget)}>开始到仓核验</Button>}</footer>
    </>}
  </section>;
}
