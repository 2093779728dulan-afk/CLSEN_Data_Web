import { Disclosure } from "../../design-system";
import { useState } from "react";
import { Button, FormField, LinkButton, Menu, Pagination, StatusMessage } from "../../design-system";
import { useLoad } from "./useProductionApi";
import type { Balance } from "./StockWorkspace";
import type { Sku } from "./types";
import type { TransitItem } from "./WarehouseTransit";
import { useStockWindowContainer } from "./stockOverview";
import { transportTime } from "./transport";
import { stockAmount, stockSum, type OverviewAction, type OverviewStock } from "./stockOverview";
import styles from "./SkuAcrossWarehouses.module.css";

type Place = { warehouse_id: string; warehouse_name: string; owner_id: string | null; owner_name: string | null; balance: Balance | null; incoming: { items: TransitItem[]; total: number }; outgoing: { items: TransitItem[]; total: number } };
type Locations = { items: Place[]; page: number; page_size: number; total: number };
export function StockQuantityDetail({ variant, historical, stock, values, warehouse, owner, transport, page, refresh, canWrite, changePage, selectScope, act }: {
  variant: Sku; historical: boolean; stock?: OverviewStock; values: Balance[]; warehouse?: string; owner?: string; transport: boolean; page: number; refresh: number; canWrite: boolean;
  changePage: (page: number) => void; selectScope: (warehouse: string, owner: string) => void; act: (action: OverviewAction) => void;
}) {
  const [retry,setRetry]=useState(0);
  const menuContainer=useStockWindowContainer();
  const locations=useLoad<Locations>(`/api/production/inventory/sku-locations?${new URLSearchParams({sku_id:variant.sku_id,page:String(page),overview:"1"})}`,`${refresh}:${retry}`,!historical,true);
  const scoped=warehouse?values.filter(value=>value.warehouse_id===warehouse&&value.owner_id===owner):values;
  const scope=stock?.scopes.find(scope=>scope.warehouse_id===warehouse&&scope.owner_id===owner);
  const scopeName=scope?scope.warehouse_name:warehouse?'原仓库/货权已不在当前范围':'全部已建账仓库 · 合计只读';
  const scopeDisplay=scopeName;
  const legal=!!scope&&scoped.length>0&&!historical&&scoped.every(value=>value.identity_status!=='pending');
  const selectedPlaces=locations.value?.items.filter(place=>!warehouse||(place.warehouse_id===warehouse&&place.owner_id===owner))||[];
  const legs=new Map<string,TransitItem>();
  for(const place of selectedPlaces)for(const direction of [place.incoming,place.outgoing])for(const leg of direction.items)legs.set(leg.id,leg);
  const labels:Record<string,string>={IN_TRANSIT:'运输中',ARRIVAL_CHECK:'到仓待核',UNREGISTERED:'运输未登记',EXCEPTION:'运输异常',RECEIVED:'已收清',SETTLED:'已结案'};
  return <div className={styles.popoverBody}>
      <p className={styles.scopeContext} title={scopeName}>{scopeDisplay}</p>
      {historical&&<StatusMessage kind="warning" title="历史商品身份待核">保留原记录，不猜配当前款号或运输，禁止过账。</StatusMessage>}
      {!transport&&<><section aria-label="当前SKU质量与占用"><dl className={styles.popoverMetrics}>{([['on_hand_units','在库'],['free_available_units','可发'],['qualified_units','合格'],['defective_units','不可售'],['reserved_units','预留'],['held_units','冻结']] as const).map(([key,label])=><div key={key}><dt>{label}</dt><dd>{stockAmount(stockSum(scoped,key,!!stock))}<small>件</small></dd></div>)}</dl><p className={styles.secondaryMetrics}>{([["pending_units","待检"],["unassessed_units","质量未核"],["loan_outstanding_units","借出未还"]] as const).map(([key,label])=><span key={key}>{label}<b>{stockAmount(stockSum(scoped,key,!!stock))}</b>件</span>)}</p></section>
      {!scoped.length&&<p className={styles.note}>未登记库存记录，各仓建账情况待核；未登记不作为实际库存为零。</p>}
      {scoped.some(value=>value.state!=='ready')&&<StatusMessage kind="warning" title="当前可发需核对">{scoped.find(value=>value.missing)?.missing||'期初或占用尚待核对；存在缺口的范围暂停发货。'}</StatusMessage>}
      <Disclosure className={styles.recordDetails}><summary>来源与历史 · {scoped.length}条库存记录</summary>{scoped.map(value=><article key={`${value.warehouse_id}:${value.owner_id}`}><strong>{stock?.scopes.find(scope=>scope.warehouse_id===value.warehouse_id&&scope.owner_id===value.owner_id)?.warehouse_name||`仓库 ${value.warehouse_id}`} · {stock?.scopes.find(scope=>scope.warehouse_id===value.warehouse_id&&scope.owner_id===value.owner_id)?.owner_name||`货权 ${value.owner_id}`}</strong><p>来源颜色：{value.standard_color || variant.standard_color || "待核"}</p>{value.opening_metadata?.quantity_basis === "NORMAL_DISPATCHABLE_V1" && <p>仓库表按正常可发库存登记；待检、次品、冻结等异常单独记录。</p>}{value.opening_metadata?.review_revision && <p>核对修订 {value.opening_metadata.review_revision} · 货权状态 {value.opening_metadata.owner_state || "待核"}</p>}<p>来源日期 {value.cutoff_on||'待补'} · {value.source_reference||'来源编号待核'}</p><LinkButton variant="quiet" to={value.opening_metadata?.review_id?`/production/inventory?review=${encodeURIComponent(value.opening_metadata.review_id)}`:'/production/inventory'}>查看来源资料</LinkButton></article>)}<LinkButton variant="quiet" to="/production/stock/history">操作历史</LinkButton>{warehouse && owner && <Button variant="quiet" onClick={()=>act({kind:"release",sku_id:variant.sku_id,warehouse_id:warehouse,owner_id:owner})}>查看占用记录</Button>}</Disclosure></>}
      {transport&&<section aria-label="当前SKU运输与ETA"><h3>运输与预计到达</h3><p className={styles.note}>按SKU{warehouse?'及当前仓库/货权':'全部仓库'}查询；同一运输腿只列一次。发出未收不计在库，FBA为本地事件账。</p>
      {locations.error&&<StatusMessage kind="danger" title="运输明细读取未完成" action={<Button onClick={()=>setRetry(value=>value+1)}>重试明细</Button>}>{locations.error}。失败不当成零。</StatusMessage>}
      {!locations.value&&!locations.error&&!historical&&<p role="status">正在读取关联仓库与运输…</p>}
      {locations.value&&<>{!legs.size&&<p>本页没有关联运输；分页及各仓更多入口保留。</p>}{[...legs.values()].map(leg=><article className={styles.compactLeg} key={leg.id}><header><LinkButton variant="quiet" to={`/production/shipments/${leg.id}#transport`}>{leg.business_number||leg.system_number}</LinkButton><span>{labels[leg.stage]||'状态待核'} · {stockAmount(leg.unreceived_units==null?null:(BigInt(leg.unreceived_units)-BigInt(leg.settled_units||'0')).toString())}件未收</span></header><p>{leg.source_name||'来源待核'} → {leg.destination_name||'目的地待核'}</p><p>已发 {stockAmount(leg.shipped_units)}件 · 实收 {stockAmount(leg.received_units)}件 · 结案 {stockAmount(leg.settled_units)}件</p><p>预计到达 {leg.transport.record?.arrival_local?transportTime(leg.transport.record.arrival_local,leg.transport.record.arrival_timezone):'未填写'}</p></article>)}{selectedPlaces.map(place=><div key={`${place.warehouse_id}:${place.owner_id}`}>{(['incoming','outgoing']as const).map(direction=>place[direction].total>place[direction].items.length&&<LinkButton key={direction} variant="quiet" to={`/production/warehouses/${place.warehouse_id}?${new URLSearchParams({tab:'transit',transit_direction:direction,sku_id:variant.sku_id,...(place.owner_id?{owner:place.owner_id}:{})})}`}>查看{place.warehouse_name}{direction==='incoming'?'待运入':'待运出'}全部{place[direction].total}批</LinkButton>)}</div>)}<Pagination itemLabel="仓库/货权范围" page={page} totalItems={locations.value.total} totalPages={Math.ceil(locations.value.total/locations.value.page_size)||1} onPageChange={changePage}/><p className={styles.note}>每仓每方向最多列20批，全量数量以上方摘要为准。</p></>}
      </section>}
      {canWrite&&!historical&&<footer className={styles.popoverActions}><FormField label="办理仓库"><select value={warehouse&&owner?`${warehouse}:${owner}`:""} onChange={event=>{const [w,o]=event.target.value.split(':');selectScope(w!,o!);}}><option value="">全部已建账仓库（合计只读）</option>{stock?.scopes.filter(scope=>values.some(value=>value.warehouse_id===scope.warehouse_id&&value.owner_id===scope.owner_id)).map(scope=><option key={`${scope.warehouse_id}:${scope.owner_id}`} value={`${scope.warehouse_id}:${scope.owner_id}`}>{scope.warehouse_name}</option>)}</select></FormField>
      <Menu label="办理" portalContainer={menuContainer} items={([['movement','入库'],['out','取走或消耗'],['quality','质量或库位变更'],['count','盘点调整'],['reserve','预留或冻结库存'],['release','释放预留或冻结'],['borrow','借出库存'],['loans','借出与归还'],...(scoped.some(value=>BigInt(value.pending_units||'0')>0n)?[['inspect','处理当前待检库存'] as const]:[])]as const).map(([kind,label])=>({id:kind,label,disabled:!legal,onSelect:()=>{if(scope)act({kind,sku_id:variant.sku_id,warehouse_id:scope.warehouse_id,owner_id:scope.owner_id});}}))}/>{!warehouse&&<p className={styles.note}>合计仅供查看；办理需明确仓库与货权。</p>}</footer>}
    </div>;
}
