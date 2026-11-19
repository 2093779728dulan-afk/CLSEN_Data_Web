import { Fragment, useState, type ReactNode, type RefObject } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronRight, Pencil, Plus, Search, Warehouse } from "lucide-react";
import { Button, FormField, Input, LinkButton, Pagination, StatusMessage, Table } from "../../design-system";
import { useLoad, useSearchDraft } from "./useProductionApi";
import { ReadContent, ReadState, type WorkbenchStock } from "./WorkbenchFields";
import { type DirectoryPage, type DirectoryRecord, inventoryStates, warehouseTypes } from "./directoryTypes";
import { type Sku, units } from "./types";
import { WarehouseRecords } from "./WarehouseRecords";
import { WarehouseOpeningDialog } from "./WarehouseOpening";
import { FbaWorkspace } from "./FbaWorkspace";
import { WarehouseSourceEvidence } from "./WarehouseSourceEvidence";
import { warehouseTabs } from "./warehouseNavigation";
import { WarehouseTransit } from "./WarehouseTransit";
import styles from "./WarehouseCenter.module.css";

const base = "/api/production/";
export type WarehouseBalance = { warehouse_id: string; owner_id: string; sku_id: string; style_code?: string; sku_label?: string; standard_color?: string; standard_size?: string; on_hand_units: string | null; free_available_units: string | null; qualified_units?: string; pending_units?: string; defective_units?: string; held_units?: string; reserved_units?: string; state: string };
export type WarehouseStock = Omit<WorkbenchStock, "items"> & { items: WarehouseBalance[]; opening_enabled?: boolean };
const groupNames = ["已建账", "未建账", "平台未接入", "非库存地点", "已停用", "状态待核"];
function groupName(record: DirectoryRecord) {
  if (record.status === "INACTIVE") return "已停用";
  return ({ READY: "已建账", FBA_READY: "已建账", UNINITIALIZED: "未建账", NOT_CONNECTED: "平台未接入", NOT_APPLICABLE: "非库存地点" } as Record<string, string>)[record.inventory_state || ""] || "状态待核";
}
export function WarehouseState({ record }: { record: DirectoryRecord }) {
  return <span className={`${styles.badge} ${record.status === "INACTIVE" ? styles.danger : record.inventory_state === "NOT_APPLICABLE" ? styles.muted : record.inventory_state === "READY" ? styles.ready : styles.pending}`}>{record.status === "INACTIVE" ? "已停用" : inventoryStates[record.inventory_state || ""] || "状态待核"}</span>;
}
export function WarehouseCenter({ canWrite, refresh, reload, edit, createRef }: { canWrite: boolean; refresh: number; reload: () => void; edit: (record: DirectoryRecord | "new") => void; createRef: RefObject<HTMLButtonElement | null> }) {
  const { directoryId } = useParams(); const [params, setParams] = useSearchParams();
  const appliedQuery = params.get("q") || "";
  const [query, setQuery] = useSearchDraft(appliedQuery);
  const [pickerOpen, setPickerOpen] = useState(false);
  const list = useLoad<DirectoryPage>(`${base}warehouses?${new URLSearchParams({ q: params.get("q") || "", page: params.get("page") || "1", status: params.get("status") || "", type: params.get("type") || "", country: params.get("country") || "" })}`, refresh, true, true, true);
  const id = directoryId || list.value?.items.find(w => w.status === "ACTIVE" && w.inventory_state === "READY")?.id || list.value?.items[0]?.id;
  const detail = useLoad<DirectoryRecord>(`${base}warehouses/${id}`, refresh, !!id, true, true);
  function filter(values: Record<string, string>) { const next = new URLSearchParams(params); Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key)); next.delete("page"); setParams(next); }
  function warehouseUrl(record: DirectoryRecord) {
    const next = new URLSearchParams();
    for (const key of ["q", "status", "type", "country", "page", "tab"]) if (params.get(key)) next.set(key, params.get(key)!);
    return `/production/warehouses/${record.id}?${next}`;
  }
  return <div className={`${styles.center} ${!pickerOpen ? styles.pickerClosed : ""} ${detail.value?.type === "FBA" ? styles.fbaCenter : ""}`}>
    <aside id="warehouse-picker" className={styles.sidebar} aria-label="仓库切换">
      <header><h1>仓库中心</h1></header>
      {list.value && list.error && <StatusMessage kind="warning" title="仓库列表更新失败">{list.error}</StatusMessage>}
      <form className={styles.search} onSubmit={event => { event.preventDefault(); filter({ q: query.trim() }); }}><Search size={17} aria-hidden="true" /><Input aria-label="搜索仓库名称或编号" type="search" placeholder="搜索仓库名称" value={query} onChange={event => setQuery(event.target.value)} /><Button type="submit" variant="quiet">查找</Button></form>
      {canWrite && <Button ref={createRef} className={styles.createWarehouse} variant="secondary" icon={<Plus size={17} />} onClick={() => edit("new")}>新建仓库</Button>}
      <nav aria-label="仓库列表">{list.value ? <>{groupNames.map(group => {
        const records = list.value!.items.filter(w => groupName(w) === group);
        return !!records.length && <section key={group}><h2>{group} <span>（{records.length}）</span></h2>{records.map(w => <Link key={w.id} to={warehouseUrl(w)} onClick={() => setPickerOpen(false)} aria-label={w.name} aria-current={id === w.id ? "page" : undefined}><Warehouse size={21} aria-hidden="true" /><span><strong>{w.name}</strong></span><ChevronRight size={16} aria-hidden="true" /></Link>)}</section>;
      })}{!list.value.items.length && <p className={styles.empty}>没有匹配的仓库。调整筛选不会修改当前仓库。</p>}</> : <ReadState error={list.error} />}</nav>
      {list.value && list.value.total > 50 && <Pagination page={list.value.page} totalItems={list.value.total} totalPages={Math.ceil(list.value.total / 50)} onPageChange={page => { const next = new URLSearchParams(params); next.set("page", String(page)); setParams(next); }} />}
      {directoryId && detail.value && list.value && !list.value.items.some(w => w.id === directoryId) && <p className={styles.note}>当前查看：{detail.value.name}（不在本页筛选结果中）</p>}
      <Link className={styles.allStock} to="/production/stock">库存总览 / SKU跨仓查询</Link>
    </aside>
    <div className={styles.main}><div className={styles.pickerToggle}><Button variant="secondary" aria-expanded={pickerOpen} aria-controls="warehouse-picker" onClick={() => setPickerOpen(value => !value)}>{pickerOpen ? "收起仓库列表" : "切换仓库"}</Button><span>{detail.value?.name}</span></div>{id ? detail.value && detail.value.id === id ? <WarehouseDetail key={`${id}:${params.get("owner") || detail.value.scopes?.[0]?.owner_id || ""}`} record={detail.value} owner={params.get("owner") || detail.value.scopes?.[0]?.owner_id || ""} canWrite={canWrite} refresh={refresh} reading={detail.loading} readError={detail.error} reload={reload} edit={() => edit(detail.value!)} /> : <><ReadState error={detail.error} />{detail.error && <Button onClick={reload} variant="secondary">重新读取仓库</Button>}</> : list.value ? <div className={styles.empty}><Warehouse size={32} /><h2>从一个仓库开始</h2><p>选择已有仓库，或新建档案。新档案不会自动生成期初库存。</p></div> : <ReadState error={list.error} />}</div>
  </div>;
}
function WarehouseDetail({ record, owner, canWrite, refresh, reading, readError, reload, edit }: { record: DirectoryRecord; owner: string; canWrite: boolean; refresh: number; reading: boolean; readError?: string; reload: () => void; edit: () => void }) {
  const [opening,setOpening]=useState(false);
  const [params, setParams] = useSearchParams(); const rawTab = params.get("tab") || (record.type === "LOCATION" || record.type === "UNCLASSIFIED" && !record.scopes?.length ? "profile" : "stock");
  const tabs = warehouseTabs(record);
  const tab = record.type === "FBA" ? rawTab === "profile" || rawTab === "transit" ? rawTab : "stock" : rawTab === "receive" || rawTab === "ship" ? "records" : ["stock","records","adjust","profile","transit"].includes(rawTab) ? rawTab : "stock";
  const scope = record.scopes?.find(s => s.owner_id === owner && s.warehouse_id === record.id);
  const ready = record.inventory_state === "READY" && !!scope;
  const stock = useLoad<WarehouseStock>(`${base}inventory/availability?warehouse_id=${record.id}&owner_id=${owner}`, refresh, ready, true, true);
  const catalog = useLoad<{ items: Sku[] }>(`${base}skus?contract_version=2`, refresh, ready, true, true);
  // Fail closed on a stale or mismatched response; never aggregate another owner into this view.
  const scopedStock = stock.value ? { ...stock.value, items: stock.value.items.filter(i => i.warehouse_id === record.id && i.owner_id === owner), scopes: stock.value.scopes.filter(s => s.warehouse_id === record.id && s.owner_id === owner) } : undefined;
  const writable = canWrite && record.status === "ACTIVE" && ready && stock.current && catalog.current && !reading && !readError && !!scopedStock?.writes_enabled;
  function change(values: Record<string, string>, reset = false) {
    const next = new URLSearchParams(params);
    if (reset) for (const key of ["receive", "ship", "source_order", "shipment", "receipt_draft", "document", "editor", "operation", "intent", "sku_id", "loan_id", "wizard_draft", "source_quality", "return_tab"]) next.delete(key);
    Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key)); setParams(next);
  }
  return <ReadContent loading={tab === "stock" && record.type !== "FBA" ? stock.initialLoading || catalog.initialLoading : reading || stock.loading || catalog.loading} error={readError || stock.error || catalog.error} retry={reload}>
    <header className={`${styles.heading} ${record.type === "FBA" ? styles.fbaHeading : ""}`}><div><h1 aria-label={record.name}>{record.name} {(record.type !== "FBA" || record.inventory_state !== "FBA_READY" || record.status !== "ACTIVE") && <WarehouseState record={record} />}</h1></div><div className={styles.headerActions}>{record.scopes?.length ? <FormField label="货主"><select value={owner} onChange={event => change({ owner: event.target.value }, true)}>{!scope && <option value={owner}>货权范围待核</option>}{record.scopes.map(s => <option key={s.owner_id} value={s.owner_id}>{s.owner_name}</option>)}</select></FormField> : null}</div></header>
    {canWrite&&record.status==='ACTIVE'&&['中国','CN','China'].includes(record.country||'')&&['FACTORY','OWN','THIRD_PARTY'].includes(record.type||'')&&!record.scopes?.length&&<Button onClick={()=>setOpening(true)}>导入期初库存</Button>}
    {opening&&<WarehouseOpeningDialog warehouseId={record.id} name={record.name} close={()=>setOpening(false)} saved={()=>{setOpening(false);reload();}}/>}
    <nav className={`${styles.tabs} ${record.type === "FBA" ? styles.fbaTabs : ""}`} aria-label="仓库详情">{tabs.map(([key, label]) => <Button key={key} variant="quiet" aria-pressed={tab === key} onClick={() => change({ tab: key, ...(record.type === "FBA" && key === "stock" ? { fba_view: "balance" } : {}) }, true)}>{label}</Button>)}</nav>
    {tab === "stock" && record.source_evidence?.kind === "domestic" && <WarehouseSourceEvidence source={record.source_evidence} />}
    {tab !== "profile" && record.status === "INACTIVE" && <StatusMessage kind="warning" title="此仓已停用，保留查询与历史">不能新建收发或盘点；如需恢复，请编辑资料并填写原因。</StatusMessage>}
    {tab === "profile" ? <WarehouseProfile record={record} canWrite={canWrite} edit={edit} /> : tab === "transit" ? <WarehouseTransit record={record} owner={owner} canWrite={canWrite} refresh={refresh}/> : record.type === "FBA" ? <FbaWorkspace record={record} owner={owner} canWrite={canWrite} refresh={refresh} reload={reload}/> : !ready ? <><StatusMessage kind="info" title={inventoryStates[record.inventory_state || ""] || "货权范围待核"} /><WarehouseProfile record={record} canWrite={canWrite} edit={edit} /></> : !scopedStock ? <><ReadState error={stock.error} />{stock.error && <Button variant="secondary" onClick={reload}>重新读取库存</Button>}</> : tab === "stock" ? <WarehouseInventory stock={scopedStock} catalog={catalog.value?.items || []} catalogError={catalog.error} record={record} owner={owner} writable={writable} /> : <WarehouseRecords skus={catalog.value?.items || []} record={record} owner={owner} stock={scopedStock} writable={writable} canWrite={canWrite} refresh={refresh} reload={reload} adjust={tab === "adjust"} />}
    {ready && !canWrite && <p className={styles.note}>当前账号只读，可查看库存、单据及资料。</p>}
  </ReadContent>;
}
function sum(items: WarehouseBalance[], field: "on_hand_units" | "free_available_units") { return items.some(i => i[field] == null) ? "待核" : units(items.reduce((total, item) => total + BigInt(item[field]!), 0n).toString()); }
export function WarehouseInventory({ stock, catalog, catalogError, record, owner, writable }: { stock: WarehouseStock; catalog: Sku[]; catalogError?: string; record: DirectoryRecord; owner: string; writable: boolean }) {
  const [inventoryParams, setInventoryParams] = useSearchParams();
  const query = inventoryParams.get("stock_q") || "";
  const rawState = inventoryParams.get("stock_state") || "";
  const qualityFilter = (["pending_units", "defective_units", "reserved_units", "held_units"] as const).find(field => field === rawState) || "";
  const productScope = record.inventory_product_scope;
  const goods = inventoryParams.get("stock_goods") === "other" ? "other" : "guangzhou";
  const guangzhouIds = new Set(productScope?.sku_ids);
  const scopeCurrent = !productScope || (productScope.state === "ready" && productScope.warehouse_id === record.id
    && catalog.every(sku => sku.catalog_version === productScope.catalog_version) && !catalogError);
  const inGoods = (skuId: string) => !productScope || (goods === "guangzhou" ? guangzhouIds.has(skuId) : !guangzhouIds.has(skuId));
  const scopedItems = stock.items.filter(item => item.warehouse_id === record.id && item.owner_id === owner && inGoods(item.sku_id));
  const scopedCatalog = catalog.filter(sku => inGoods(sku.sku_id));
  function setInventoryFilter(values: Record<string, string>, replace = false) {
    const next = new URLSearchParams(inventoryParams);
    Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    setInventoryParams(next, { replace });
  }
  const [closed, setClosed] = useState<string[]>([]); const [cell, setCell] = useState<string>();
  function operationUrl(skuId: string, inspection: boolean) {
    const next = new URLSearchParams(inventoryParams);
    for (const key of ["document", "wizard_draft", "loan_id", "source_quality", "intent", "receive", "ship", "source_order", "shipment", "receipt_draft"]) next.delete(key);
    Object.entries({ tab: "adjust", adjust_view: inspection ? "quality" : "count", operation: "new", editor: "1", sku_id: skuId, owner, return_tab: "stock" }).forEach(([key, value]) => next.set(key, value));
    if (inspection) next.set("source_quality", "PENDING");
    return `/production/warehouses/${record.id}?${next}`;
  }
  function dispatchUrl(skuId?:string) {
    const retained=new URLSearchParams(inventoryParams);retained.set("tab","stock");retained.set("owner",owner);
    return `/production/shipments/new?${new URLSearchParams({flow:"guided",purpose:"WAREHOUSE_DISPATCH",warehouse_id:record.id,owner_id:owner,...(skuId?{sku_id:skuId}:{}),return_to:`/production/warehouses/${record.id}?${retained}`})}`;
  }
  const recorded = new Set(scopedItems.map(item => item.sku_id));
  const displayed: WarehouseBalance[] = [...scopedItems, ...scopedCatalog.filter(sku => sku.status === "active" && !recorded.has(sku.sku_id)).map(sku => ({
    warehouse_id: record.id, owner_id: owner, sku_id: sku.sku_id, state: "ready",
    on_hand_units: "0", free_available_units: "0", qualified_units: "0", pending_units: "0", defective_units: "0", held_units: "0", reserved_units: "0",
  }))];
  const allVariants = displayed.map(item => { const sku = catalog.find(s => s.sku_id === item.sku_id); return { item, key: sku?.style_id ? `style:${sku.style_id}` : `sku:${item.sku_id}`, title: sku?.style_code || item.style_code || (sku?.style_id ? `款式编号 ${sku.style_id}` : `SKU ${item.sku_id}（款号待核）`), color: sku?.standard_color || item.standard_color || "颜色待核", size: sku?.standard_size || item.standard_size || "尺码待核" }; });
  const registered = new Set(allVariants.flatMap(v => [JSON.stringify([v.key, v.color, v.size]), JSON.stringify([v.key, null, v.size])]));
  for (const sku of scopedCatalog) {
    const key = sku.style_id ? `style:${sku.style_id}` : `sku:${sku.sku_id}`;
    registered.add(JSON.stringify([key, sku.standard_color || "颜色待核", sku.standard_size || "尺码待核"]));
    registered.add(JSON.stringify([key, null, sku.standard_size || "尺码待核"]));
  }
  const searchedVariants = allVariants.filter(v => [v.title, v.color, v.size, v.item.sku_id].join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const variants = searchedVariants.filter(v => !qualityFilter || v.item[qualityFilter] == null || BigInt(v.item[qualityFilter]) > 0n);
  const sizes = [...new Set(allVariants.map(v => v.size))].sort((a, b) => { const order = ["XS", "S", "M", "L", "XL", "XXL", "3XL"]; const left = order.indexOf(a), right = order.indexOf(b); return (left < 0 ? 99 : left) - (right < 0 ? 99 : right) || a.localeCompare(b, "zh-CN", { numeric: true }); });
  const stockedStyles = new Set(allVariants.filter(v => v.item.on_hand_units == null || BigInt(v.item.on_hand_units) !== 0n).map(v => v.key));
  const groups = [...new Set(variants.map(v => v.key))].filter(key => stockedStyles.has(key)).map(key => ({ key, title: variants.find(v => v.key === key)!.title, variants: variants.filter(v => v.key === key) }));
  const onHand = (items: WarehouseBalance[]) => {
    const value = sum(items, "on_hand_units");
    return <span className={styles.quantity} aria-label={`在库${value}件`}><strong>{value === "0" ? "" : value}</strong></span>;
  };
  if (!scopeCurrent) return <ReadState error={catalogError || "商品目录已变化，请刷新仓库。"} />;
  const returnParams = new URLSearchParams(inventoryParams); returnParams.set("tab", "stock"); returnParams.set("owner", owner);
  return <>
    {productScope && <div className={styles.stockReasons} aria-label="商品范围筛选">{([['guangzhou', '广州店商品'], ['other', '其他成品']] as const).map(([value, label]) => <Button key={value} variant="quiet" aria-pressed={goods === value} onClick={() => { setCell(undefined); setInventoryFilter({ stock_goods: value }); }}>{label}</Button>)}</div>}
    <div className={styles.inventoryToolbar}><div className={styles.totals}><span>在库 <strong>{sum(variants.map(v => v.item), "on_hand_units")}</strong></span></div><div className={styles.stockSearch}><Search size={17} aria-hidden="true" /><Input aria-label="搜索本仓款号、颜色或尺码" type="search" placeholder="搜索款号、颜色、尺码" value={query} onChange={event => setInventoryFilter({ stock_q: event.target.value }, true)} /></div>{writable && <div className={styles.headerActions}><LinkButton variant="primary" to={`/production/orders/receipts/new?${new URLSearchParams({warehouse_id:record.id,owner_id:owner,return_to:`/production/warehouses/${record.id}?${returnParams}`})}`}>入库</LinkButton><LinkButton variant="secondary" to={dispatchUrl()}>出货</LinkButton></div>}</div>
    {catalogError && <ReadState error={catalogError} />}
    <div className={styles.stockReasons} aria-label="库存状态筛选"><Button variant="quiet" aria-pressed={!qualityFilter} onClick={() => setInventoryFilter({ stock_state: "" })}>全部规格</Button>{([["pending_units", "待检"], ["defective_units", "次品"], ["reserved_units", "预留"], ["held_units", "冻结"]] as const).map(([field, label]) => {
      const missing = searchedVariants.some(({ item }) => item[field] == null);
      const amount = missing ? "待核" : units(searchedVariants.reduce((value, { item }) => value + BigInt(item[field]!), 0n).toString());
      return <Button key={field} variant="quiet" aria-pressed={qualityFilter === field} aria-label={`${label} ${amount}`} onClick={() => setInventoryFilter({ stock_state: field })}>{label} {amount === "0" ? "" : amount}</Button>;
    })}</div>
    {(query || qualityFilter) && <Button variant="secondary" className={styles.clearStockFilters} onClick={() => setInventoryFilter({ stock_q: "", stock_state: "" })}>清除库存筛选</Button>}
    {qualityFilter && <p className={styles.note}>按当前状态筛选规格，数量待核的规格仍保留。不同限制可能重叠，不能相加作为不可发总量。</p>}
    <Table className={styles.matrix} aria-label="本仓款色尺码库存" style={{ minWidth: 240 + (sizes.length + 1) * 64 }}>
      <thead><tr><th scope="col">款号</th><th scope="col">颜色</th>{sizes.map(size => <th scope="col" key={size}>{size}</th>)}<th scope="col" className={styles.totalColumn}>合计</th></tr></thead>
      <tbody>{groups.map(group => {
        const collapsed = closed.includes(group.key);
        const colors = [...new Set(group.variants.map(v => v.color))];
        return (collapsed ? [null] : colors).map((color, index) => {
          const rows = color === null ? group.variants : group.variants.filter(v => v.color === color);
          const chosen = color === null ? undefined : rows.find(v => v.item.sku_id === cell);
          return <Fragment key={group.key + ":" + (color ?? "collapsed")}>
            <tr className={index === 0 ? styles.productStart : undefined}>
              <th scope="row" className={styles.styleIdentity}>{index === 0 ? <Button variant="quiet" aria-expanded={!collapsed} icon={collapsed ? <ChevronRight size={15} /> : <ChevronDown size={15} />} onClick={() => setClosed(current => current.includes(group.key) ? current.filter(k => k !== group.key) : [...current, group.key])}>{group.title}</Button> : <span>{group.title}</span>}</th>
              <td className={styles.colorIdentity}>{color ?? <span className={styles.collapsedColors}>{colors.length}种颜色 · 已收起</span>}</td>
              {sizes.map(size => {
                const matches = rows.filter(v => v.size === size);
                const exists = registered.has(JSON.stringify([group.key, color, size]));
                return <td key={size} className={!exists ? styles.absentSize : undefined} title={!exists ? "未建档此尺码" : undefined} aria-label={!exists ? `${group.title} ${color ?? ""} ${size}：未建档此尺码` : undefined}>{!matches.length ? <span className={styles.unregistered} /> : collapsed ? onHand(matches.map(v => v.item)) : matches.map(v => <Button key={v.item.sku_id} variant="quiet" aria-label={`${group.title} ${color} ${size} 库存明细 SKU ${v.item.sku_id}`} aria-expanded={cell === v.item.sku_id} className={cell === v.item.sku_id ? styles.selectedCell : undefined} onClick={() => setCell(current => current === v.item.sku_id ? undefined : v.item.sku_id)}>{onHand([v.item])}</Button>)}</td>;
              })}
              <td className={styles.totalColumn}>{onHand(rows.map(v => v.item))}</td>
            </tr>
            {chosen && <tr className={styles.cellRow}><td colSpan={sizes.length + 3}><section aria-label="规格库存明细"><strong>{group.title} · {chosen.color} / {chosen.size}</strong><dl>{[["在库", chosen.item.on_hand_units], ["当前可发", chosen.item.free_available_units], ["合格", chosen.item.qualified_units], ["待检", chosen.item.pending_units], ["次品", chosen.item.defective_units], ["预留", chosen.item.reserved_units], ["冻结", chosen.item.held_units]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value == null ? "待核" : units(value)}</dd></div>)}</dl>{writable && chosen.item.state === "ready" && <div className={styles.cellActions}><LinkButton variant="primary" to={dispatchUrl(chosen.item.sku_id)}>出货此规格</LinkButton>{chosen.item.pending_units != null && BigInt(chosen.item.pending_units) > 0n && <LinkButton variant="primary" to={operationUrl(chosen.item.sku_id, true)}>处理待检</LinkButton>}<LinkButton variant="secondary" to={operationUrl(chosen.item.sku_id, false)}>盘点此规格</LinkButton></div>}</section></td></tr>}
          </Fragment>;
        });
      })}{!groups.length && <tr><td colSpan={sizes.length + 3}>没有匹配的商品</td></tr>}</tbody>
      {!!groups.length && <tfoot><tr><th colSpan={2}>{query || qualityFilter ? "筛选合计" : "本仓合计"}</th>{sizes.map(size => <td key={size}>{onHand(variants.filter(v => v.size === size).map(v => v.item))}</td>)}<td className={styles.totalColumn}>{onHand(variants.map(v => v.item))}</td></tr></tfoot>}
    </Table>
  </>;
}
const profileLabels: Record<string, string> = { name: "仓库名称", type: "类型", country: "国家 / 地区", region: "所在地区", address: "详细地址", operator: "运营方", contact: "联系人", phone: "联系方式", status: "状态", notes: "备注", external_code: "外部仓码", timezone: "时区", seller_account: "卖家账号", marketplace: "站点", factory_ids: "往来工厂" };
function WarehouseStatusBadge({ status }: { status: string }) {
  const active = status === "ACTIVE";
  const inactive = status === "INACTIVE";
  const label = active ? "启用中" : inactive ? "已停用" : "状态待核";
  return <span aria-label="仓库状态" className={`${styles.badge} ${active ? styles.ready : inactive ? styles.danger : styles.pending}`} data-status-tone={active ? "success" : inactive ? "danger" : "warning"}>{label}</span>;
}
function ProfileFields({ fields }: { fields: [string, ReactNode][] }) { return <dl className={styles.profileFields}>{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || <span className={styles.fieldEmpty}>未填写</span>}</dd></div>)}</dl>; }
function WarehouseProfile({ record, canWrite, edit }: { record: DirectoryRecord; canWrite: boolean; edit: () => void }) {
  return <><div className={styles.profileHeading}><h2>仓库资料</h2>{canWrite && <Button variant="primary" icon={<Pencil size={16} />} onClick={edit}>编辑资料</Button>}</div><div className={styles.profileLayout}><div>
    <section className={styles.profileSection}><h2>基本资料</h2><ProfileFields fields={[["仓库名称", record.name], ["类型", warehouseTypes[record.type || ""]], ["国家 / 地区", [record.country, record.region].filter(Boolean).join(" · ")], ["详细地址", record.address], ["状态", <WarehouseStatusBadge status={record.status} />], ["运营方", record.operator]]} /></section>
    <section className={styles.profileSection}><h2>联系与收货信息</h2><ProfileFields fields={[["联系人", record.contact], ["联系方式", record.phone], ["备注", record.notes]]} /></section>
    <details className={styles.optionalProfile}><summary><ChevronDown size={16} aria-hidden="true" />可选资料（时区、外部仓码及平台信息）</summary><ProfileFields fields={[["时区", record.timezone], ["外部仓码", record.external_code], ["卖家账号", record.seller_account], ["站点", record.marketplace]]} /></details>
    <section className={styles.profileSection}><h2>往来工厂（选填）</h2>{record.factory_ids?.length ? <ul className={styles.factoryLinks}>{record.factory_ids.map(id => <FactoryLink key={id} id={id} />)}</ul> : <p className={styles.note}>尚未登记往来工厂。</p>}<p className={styles.note}>仅记录往来关系；不会自动下单、入库或改变货权。</p></section>
  </div><aside className={styles.history}><h2>资料修改记录</h2><p className={styles.note}>最近100次</p>{record.history?.length ? record.history.map(h => <article key={h.revision}><p>{h.created_at} · {h.actor_name || "操作人待核"}</p><strong>修订 {h.revision}</strong><p>原因：{h.reason}</p><details><summary>查看修改详情</summary><ProfileDiff before={h.before_value} after={h.after_value} /></details></article>) : <p className={styles.note}>暂无资料修改记录。</p>}</aside></div>{canWrite && <div className={styles.deactivate}><Button variant="quiet" onClick={edit}>{record.status === "ACTIVE" ? "管理仓库启停" : "恢复仓库"}</Button><p>在编辑资料中更改状态并填写原因。停用后保留库存及历史查询，不允许新增业务。</p></div>}</>;
}
function FactoryLink({ id }: { id: string }) { const record = useLoad<DirectoryRecord>(`${base}factories/${id}`); return <li><Link to={`/production/factories/${id}`}>{record.value?.name || `工厂编号 ${id}`}</Link>{record.value?.status === "INACTIVE" && <span> · 已停用</span>}{record.error && <span> · 资料读取失败</span>}</li>; }
function ProfileDiff({ before, after }: { before: unknown; after: unknown }) {
  const old = before && typeof before === "object" ? before as Record<string, unknown> : {};
  const next = after && typeof after === "object" ? after as Record<string, unknown> : {};
  const keys = [...new Set([...Object.keys(old), ...Object.keys(next)])].filter(k => profileLabels[k] && JSON.stringify(old[k]) !== JSON.stringify(next[k]));
  const displayValue = (value: unknown): string => {
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") return `${value}`;
    return "已填写";
  };
  const display = (key: string, value: unknown) => {
    if (value == null || value === "") return "未填写";
    if (key === "status") return value === "ACTIVE" ? "启用中" : "已停用";
    if (key === "type") {
      const type = displayValue(value);
      return warehouseTypes[type] || type;
    }
    if (Array.isArray(value)) return value.map(displayValue).join("、") || "未关联";
    return displayValue(value);
  };
  return keys.length ? <dl className={styles.profileDiff}>{keys.map(key => <div key={key}><dt>{profileLabels[key]}</dt><dd>{display(key, old[key])} → {display(key, next[key])}</dd></div>)}</dl> : <p>无可展示的字段变化。</p>;
}

