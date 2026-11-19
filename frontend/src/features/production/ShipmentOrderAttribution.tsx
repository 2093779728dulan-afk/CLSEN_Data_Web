import { useCallback, useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { requestApi } from "../../api/client";
import { Button, Input, StatusMessage } from "../../design-system";
import type { Allocation, Document, DocumentPage, Source, Sku } from "./types";
import { productionFieldId } from "./productionForm";
import styles from "./FbaWorkspace.module.css";

const automatic = (source: Source) => source.order_attribution !== "manual" && (!source.allocations.length || source.order_attribution === "automatic");

export function ShipmentOrderAttribution({ sources, shipment, catalog, selectedOrders = "", compact = false, autoFill = false, confirmedSources = [], onOrdersRead, locked, change, search, errors = {} }: {
  sources: Source[]; shipment: Pick<Document, "warehouse_id" | "owner_id" | "destination_id">;
  catalog: Sku[]; selectedOrders?: string; compact?:boolean; autoFill?:boolean; locked: boolean; errors?: Record<string,string>;
  confirmedSources?: Source[]; onOrdersRead?: (orders: Document[]) => void;
  change: (index: number, patch: Partial<Source>) => void;
  search: (source: number, allocation: number) => void;
}) {
  const [result, setResult] = useState<{orders:Document[];complete:boolean;selection:string}>();
  const complete = result?.selection === selectedOrders && result.complete;
  const [error, setError] = useState("");
  const [showCompleted, setShowCompleted] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setError(""); setResult(undefined);
    const ids = selectedOrders.split(",").filter(id => /^[1-9][0-9]*$/.test(id));
    const read = ids.length
      ? Promise.all(ids.map(id => requestApi<Document>(`/api/production/orders/${id}`, { signal: controller.signal }))).then(items => ({ items, total: items.length, page_size: items.length }))
      : requestApi<DocumentPage>("/api/production/orders?status=CONFIRMED&selectable=true&page_size=100", { signal: controller.signal });
    void read.then(result => {
      if (controller.signal.aborted) return;
      setResult({orders:result.items,complete:result.total <= result.page_size,selection:selectedOrders});
      onOrdersRead?.(result.items);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "订单候选读取失败"); });
    return () => controller.abort();
  }, [selectedOrders, onOrdersRead]);
  const candidates = useCallback((sku: string) => {
    const orders = result?.selection === selectedOrders ? result.orders : [];
    return orders.filter(order => order.status === "CONFIRMED" &&
      order.receipt_warehouse_id === shipment.warehouse_id && order.receipt_owner_id === shipment.owner_id &&
      (!order.destination_id || order.destination_id === shipment.destination_id))
      .flatMap(order => (order.lines || []).filter(line => line.sku_id === sku && line.tracking_state !== "CLOSED").map(line => {
        const former = confirmedSources.flatMap(source => source.allocations).filter(allocation => allocation.order_line_id === line.id).reduce((sum, allocation) => sum + BigInt(allocation.units), 0n);
        const remaining = line.expected_units == null || line.actual_units == null ? null : BigInt(line.expected_units) - BigInt(line.actual_units) + former;
        return { order, line, remaining: remaining == null ? null : remaining > 0n ? remaining : 0n };
      }));
  },[result,selectedOrders,shipment.warehouse_id,shipment.owner_id,shipment.destination_id,confirmedSources]);
  const suggestion = useCallback((source: Source, explicit = false) => {
    const found = candidates(source.sku_id).filter(item => item.remaining == null || item.remaining > 0n);
    if (found.length !== 1 || found[0]!.remaining == null) return undefined;
    const target = found[0]!;
    const proposed = sources.filter(item => item.sku_id === source.sku_id && (automatic(item) || explicit && !item.allocations.length));
    const fixed = sources.filter(item => !proposed.includes(item)).flatMap(item => item.allocations).filter(allocation => allocation.order_line_id === target.line.id);
    if (proposed.some(item => !/^[1-9][0-9]*$/.test(item.actual_units)) || fixed.some(allocation => !/^(0|[1-9][0-9]*)$/.test(allocation.units))) return undefined;
    const quantity = proposed.reduce((sum, item) => sum + BigInt(item.actual_units), 0n) + fixed.reduce((sum, allocation) => sum + BigInt(allocation.units), 0n);
    return quantity <= target.remaining! ? target.line : undefined;
  }, [candidates, sources]);
  useEffect(() => {
    if (!autoFill || !complete || locked) return;
    sources.forEach((source,index) => {
      if (!automatic(source)) return;
      const line = suggestion(source);
      if (!line) {
        if (source.order_attribution === "automatic") change(index,{allocations:[],order_attribution:undefined});
        return;
      }
      const allocation = source.allocations[0];
      if (source.allocations.length === 1 && allocation?.order_line_id === line.id && allocation.units === source.actual_units) return;
      change(index,{allocations:[{order_line_id:line.id,units:source.actual_units}],order_attribution:"automatic"});
    });
  },[autoFill,complete,locked,sources,suggestion,change]);
  function setAllocations(index:number,allocations:Allocation[]) {
    change(index,{allocations,order_attribution:"manual"});
  }
  function suggest() {
    sources.forEach((source, index) => {
      const line = suggestion(source, true);
      if (line && !source.allocations.length) change(index, { allocations: [{ order_line_id: line.id, units: source.actual_units }] });
    });
  }
  const completedCount = new Set(sources.flatMap(source => candidates(source.sku_id).filter(item => item.remaining === 0n).map(item => item.line.id))).size;
  const option = ({order, line, remaining}: ReturnType<typeof candidates>[number]) => <option key={line.id} value={line.id}>{order.business_number || `订单 #${order.id} · ${order.system_number.slice(-8)}`} · {remaining == null ? "剩余待核" : `可关联${remaining.toLocaleString("zh-CN")}件`}</option>;
  return <section className={`${styles.workspace} ${compact ? styles.attributionCompact : ""}`} aria-label="来源订单汇总">
    {!compact && <div className={styles.actions}><h3>来源订单</h3><Button variant="secondary" disabled={locked || !complete} onClick={suggest}>填入唯一订单候选</Button></div>}
    {error && <StatusMessage kind="danger" title={error} />}
    {!!completedCount && <div className={styles.actions}><Button variant="quiet" aria-label="显示已发完订单" aria-expanded={showCompleted} disabled={locked} onClick={() => setShowCompleted(value => !value)}>{showCompleted ? "收起已发完订单" : `已发完 · ${completedCount} 项`}</Button></div>}
    <div className={styles.scroll}><table className={styles.table} aria-label="出货订单归属汇总"><thead><tr><th>商品规格</th><th>本批出货</th><th>来源订单</th><th>分配数量</th><th>操作</th></tr></thead><tbody>{sources.flatMap((source, index) => {
      const allocations = source.allocations.length ? source.allocations : [{ order_line_id: "", units: source.actual_units }];
      return allocations.map((allocation, position) => <tr key={`${index}:${position}`}>
        <th id={position===0?productionFieldId(`source-${index}-allocations`):undefined} tabIndex={-1}>{catalog.find(item => item.sku_id === source.sku_id)?.code || source.sku_label || source.sku_id}{position===0&&errors[`source-${index}-allocations`]&&<p className={styles.error}>{errors[`source-${index}-allocations`]}</p>}</th><td>{source.actual_units}</td>
        <td><select id={productionFieldId(`allocation-${index}-${position}-order`)} aria-invalid={!!errors[`allocation-${index}-${position}-order`]} aria-label={`商品${index + 1}来源订单${position + 1}`} disabled={locked} value={allocation.order_line_id} onChange={event => {
          if (event.target.value === "__search__") {
            if (!source.allocations.length) setAllocations(index,allocations);
            search(index,position);
          } else if (event.target.value === "__split__") {
            setAllocations(index,[...allocations,{order_line_id:"",units:""}]);
          } else setAllocations(index,allocations.map((item,n)=>n===position?{...item,order_line_id:event.target.value}:item));
        }}>
          <option value="">请选择来源订单</option>
          {allocation.order_line_id && !candidates(source.sku_id).some(item => item.line.id === allocation.order_line_id) && <option value={allocation.order_line_id}>{allocation.order_business_number || allocation.order_number || `明细 ${allocation.order_line_id}`}</option>}
          <optgroup label="未发完订单">{candidates(source.sku_id).filter(item => item.remaining !== 0n).map(option)}</optgroup>
          {candidates(source.sku_id).some(item => item.remaining === 0n && (showCompleted || item.line.id === allocation.order_line_id)) && <optgroup label="已发完订单 · 超发关联">{candidates(source.sku_id).filter(item => item.remaining === 0n && (showCompleted || item.line.id === allocation.order_line_id)).map(option)}</optgroup>}
          {compact && <><option value="__search__">查找其他订单…</option><option value="__split__">拆分到其他订单…</option></>}
        </select></td>
        <td><Input id={productionFieldId(`allocation-${index}-${position}-units`)} aria-invalid={!!errors[`allocation-${index}-${position}-units`]} aria-label={`商品${index + 1}分配数量${position + 1}`} disabled={locked} inputMode="numeric" value={allocation.units} onChange={event => setAllocations(index,allocations.map((item,n)=>n===position?{...item,units:event.target.value}:item))} /></td>
        <td>{compact ? <Button variant="quiet" disabled={locked || !source.allocations.length} aria-label={`移除商品${index+1}来源订单${position+1}`} title="移除订单关联" icon={<Trash2 size={16}/>} onClick={()=>setAllocations(index,source.allocations.filter((_,n)=>n!==position))}/> : <>
          <Button variant="quiet" disabled={locked} onClick={() => { if (!source.allocations.length) setAllocations(index,allocations); search(index, position); }}>查找</Button>
          <Button variant="quiet" disabled={locked} onClick={() => setAllocations(index,[...allocations,{order_line_id:"",units:""}])}>拆分</Button>
          {!!source.allocations.length && <Button variant="quiet" disabled={locked} onClick={() => setAllocations(index,source.allocations.filter((_,n)=>n!==position))}>移除</Button>}
        </>}</td>
      </tr>);
    })}</tbody></table></div>
    {!complete && !error && <p>候选读取中或未覆盖全部订单，可通过“查找”明确选择。</p>}
  </section>;
}
