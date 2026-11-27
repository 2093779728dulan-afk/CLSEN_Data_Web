import { Disclosure } from "../../design-system";
import { useState } from "react";

import { Link } from "react-router-dom";
import { Button, Pagination, StatusMessage, Table } from "../../design-system";
import { ArrivalVerificationWindow } from "./ArrivalVerification";
import { orderProductName } from "./orderProgress";
import { transportStatus, transportTime } from "./transport";
import type { Sku } from "./types";
import type { TransitItem } from "./WarehouseTransit";
import styles from "./ProductionOverview.module.css";

const stages: Record<string, string> = { RECEIVED: "已入库", SETTLED: "差异已结案", ARRIVAL_CHECK: "到仓待核", EXCEPTION: "运输异常", IN_TRANSIT: "运输中", UNREGISTERED: "运输未登记" };
const amount = (value: string | null) => value == null ? "待核" : BigInt(value).toLocaleString("zh-CN");

export function OverviewBatchProgress({ items, error, warehouse, query, catalog, page, changePage, refresh, saved, canWrite, linkState }: {
  items: TransitItem[]; error?: string; warehouse: string; query: string; catalog: Sku[]; page: number; changePage: (page: number) => void;
  refresh: number; saved: () => void; canWrite: boolean; linkState: { overviewReturn: string };
}) {
  const [expanded, setExpanded] = useState<string[]>([]);
  const [arrival, setArrival] = useState<{ item: TransitItem; trigger: HTMLElement }>();
  const matching = items.filter(item => (!warehouse || item.warehouse_id === warehouse || item.destination_id === warehouse) && (!query || [item.system_number, item.business_number, item.source_name, item.destination_name, item.transport.record?.tracking_number, ...item.sources.map(source => orderProductName(source, catalog))].some(value => value?.toLocaleLowerCase().includes(query))));
  const totalPages = Math.max(1, Math.ceil(matching.length / 20));
  const currentPage = Math.min(page, totalPages);
  return <section className={styles.card} aria-labelledby="overview-batches-title">
    <header className={styles.sectionHeader}><h2 id="overview-batches-title">出货与到仓进度</h2>{!error && <span className={styles.count}>{matching.length} 批</span>}</header>
    {error ? <StatusMessage kind="danger" title="出货进度读取未完成" action={<Button onClick={saved}>重试出货进度</Button>}>{error}</StatusMessage> : !matching.length ? <p className={styles.empty}>当前筛选没有已确认的出货批次。</p> : <div className={styles.matrix} role="region" aria-label="出货与到仓进度" tabIndex={0}>
      <table className={styles.batchTable} aria-label="出货批次进度">
        <colgroup><col/><col/><col/><col className={styles.batchNumber}/><col className={styles.batchNumber}/><col className={styles.batchNumber}/><col className={styles.toggleColumn}/></colgroup>
        <thead><tr><th>批次 / 商品</th><th>流向</th><th>当前进度 / 地点</th><th className={styles.numeric}>已发</th><th className={styles.numeric}>已入库</th><th className={styles.numeric}>未收</th><th><span className={styles.srOnly}>展开批次</span></th></tr></thead>
        {matching.slice((currentPage - 1) * 20, currentPage * 20).map(item => {
          const number = item.business_number || item.system_number;
          const open = expanded.includes(item.id);
          const latest = item.transport.latest_event;
          const location = item.stage === "RECEIVED" ? item.destination_name : latest?.location;
          const stylesInBatch = [...new Set(item.sources.map(source => catalog.find(sku => sku.sku_id === source.sku_id)?.style_code || orderProductName(source, catalog)))].join("、");
          return <tbody key={item.id} aria-label={`出货批次 ${number}`}>
            <tr className={styles.batchRow}>
              <th scope="row"><Link className={styles.batchIdentity} title={number} to={`/production/shipments/${item.id}`} state={linkState}>{number}</Link><span className={styles.batchSubline}>{stylesInBatch || "商品待核"}</span></th>
              <td><span className={styles.routeName}>{item.source_name || "来源待核"}</span><span className={styles.batchSubline}>→ {item.destination_name || "目的仓待核"}</span></td>
              <td><strong className={item.stage === "EXCEPTION" ? styles.batchWarning : undefined}>{stages[item.stage] || "进度待核"}</strong><span className={styles.batchSubline}>{location || "地点未登记"}</span>{item.eta_overdue && <span className={styles.batchWarning}>已超过预计到达</span>}</td>
              <td className={styles.numeric} data-label="已发">{amount(item.shipped_units)}</td><td className={styles.numeric} data-label="已入库">{amount(item.received_units)}</td><td className={styles.numeric} data-label="未收">{amount(item.unreceived_units)}</td>
              <td className={styles.toggleCell}><Button variant="quiet" className={styles.traceToggle} aria-label={`${open ? "收起" : "展开"}批次 ${number}`} aria-expanded={open} aria-controls={`overview-batch-${item.id}`} onClick={() => setExpanded(value => open ? value.filter(id => id !== item.id) : [...value, item.id])}>{open ? "收起" : "查看"}</Button></td>
            </tr>
            {open && <tr className={styles.detailRow}><td colSpan={7}><section className={styles.traceBody} id={`overview-batch-${item.id}`} aria-label={`${number}流转明细`}>
              <header className={styles.traceHeader}><h3>本批货物进度</h3><div className={styles.actions}><Link className={styles.tableLink} to={`/production/shipments/${item.id}#transport`} state={linkState}>查看运输记录</Link>{canWrite && item.destination_id && item.owner_id && !["RECEIVED", "SETTLED"].includes(item.stage) && <Button variant="primary" onClick={event => setArrival({ item, trigger: event.currentTarget })}>开始到仓核验</Button>}</div></header>
              <dl className={styles.batchDates}><div><dt>出库日期</dt><dd>{item.business_date || "未登记"}</dd></div><div><dt>实际发运</dt><dd>{item.departed ? transportTime(item.departed.occurred_local, item.departed.timezone) : "未登记"}</dd></div><div><dt>预计到达</dt><dd>{item.transport.record?.arrival_local ? transportTime(item.transport.record.arrival_local, item.transport.record.arrival_timezone) : "未登记"}</dd></div><div><dt>入库日期</dt><dd>{item.receipt_dates.join("、") || "尚无入库记录"}</dd></div></dl>
              {item.transport.source_revision_current === false && <StatusMessage kind="warning" title="出货已更正，运输资料待核对"/>}
              <Table className={styles.traceTable} aria-label={`${number}商品进度`}><thead><tr><th>款号 / 颜色 / 尺码</th><th>已发</th><th>已入库</th><th>未收</th></tr></thead><tbody>{item.sources.map(source => <tr key={source.id}><th scope="row">{orderProductName(source, catalog)}</th><td>{amount(source.actual_units)}</td><td>{amount(source.received_units)}</td><td>{amount(source.unreceived_units)}</td></tr>)}</tbody></Table>
              <Disclosure className={styles.batchEvidence}><summary>物流节点与依据</summary>{item.transport.events.length ? <ol>{item.transport.events.map(event => <li key={event.id}><strong>{transportStatus[event.event_kind]}</strong> · {event.location || "地点未登记"}<p>{transportTime(event.occurred_local, event.timezone)} · {event.description || ""}</p><p>依据：{event.source_reference || "未登记"}</p></li>)}</ol> : <p>尚未登记物流节点，不能根据未收数量推断货物位置。</p>}</Disclosure>
            </section></td></tr>}
          </tbody>;
        })}
      </table>
    </div>}
    {!error && totalPages > 1 && <Pagination itemLabel="批次" page={currentPage} totalItems={matching.length} totalPages={totalPages} onPageChange={changePage}/>}
    {arrival && <ArrivalVerificationWindow item={arrival.item} canWrite={canWrite} refresh={refresh} saved={() => { setArrival(undefined); saved(); }} close={() => setArrival(undefined)} returnFocus={arrival.trigger}/>}
  </section>;
}
