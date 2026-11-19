import { ProductionConfirmDialog } from "./ProductionConfirmDialog";
import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronRight, Info } from "lucide-react";
import { Button, Dialog, FormField, Input, Menu, PageHeader, StatusMessage, Table } from "../../design-system";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { useCommand, useLoad } from "./useProductionApi";
import type { Sku } from "./types";
import type { Balance } from "./StockWorkspace";
import type { WarehouseScope } from "./WorkbenchFields";
import { StockDetailWindow } from "./StockDetailWindow";
import { StockQuantityDetail } from "./StockQuantityDetail";
import { TransitBatchBoard, TransitBatchDetail } from "./TransitBatchBoard";
import type { TransitItem } from "./WarehouseTransit";
import { ArrivalVerification } from "./ArrivalVerification";
import { stockAmount as amount, stockSum as sum, type OverviewStock, type OverviewSource, type OverviewTools, type OverviewAction, type OverviewGuard } from "./stockOverview";
import styles from "./SkuAcrossWarehouses.module.css";

type Variant = Sku & { historical?: boolean };
type Group = { id: string; label: string; variants: Variant[]; historical: boolean };
type DisplaySettings = { style_ids: string[]; revision: string; can_manage: boolean };

type TransportCounts = { sku_id: string; in_transit_units: string | null; arrival_check_units: string | null; unregistered_units: string | null; exception_units: string | null; unknown_sources: number };
type TransportSummary = { items: TransportCounts[]; totals: TransportCounts; full_scope: boolean; as_of: string };
const styleId = (sku: Sku) => sku.style_id || `sku-${sku.sku_id}`;
function groupsOf(catalog: Sku[], balances: Balance[]): Group[] {
  const groups = new Map<string, Group>();
  for (const sku of catalog) {
    const id = styleId(sku); const group = groups.get(id) || { id, label: sku.style_code || (sku.style_id ? `款式 ${sku.style_id}` : sku.code || sku.label), variants: [], historical: false };
    group.variants.push(sku); groups.set(id, group);
  }
  for (const balance of balances) if (balance.identity_status === "pending" || !catalog.some(sku => sku.sku_id === balance.sku_id)) {
    const id = `history:${balance.sku_id}`; const group = groups.get(id) || { id, label: `身份待核 · ${balance.sku_label || balance.sku_id}`, variants: [], historical: true };
    if (!group.variants.length) group.variants.push({ sku_id: balance.sku_id, code: balance.display_sku || balance.sku_label || `历史SKU ${balance.sku_id}`, label: balance.sku_label || balance.sku_id, standard_color: balance.standard_color, standard_size: balance.standard_size, catalog_version: balance.catalog_version || "", status: "unknown", historical: true });
    groups.set(id, group);
  }
  const sizes = ["XS", "S", "M", "L", "XL", "XXL", "3XL"];
  for (const group of groups.values()) group.variants.sort((a, b) => (a.standard_color || "").localeCompare(b.standard_color || "", "zh-CN") || (sizes.indexOf(a.standard_size || "") < 0 ? 99 : sizes.indexOf(a.standard_size!)) - (sizes.indexOf(b.standard_size || "") < 0 ? 99 : sizes.indexOf(b.standard_size!)) || (a.code || a.label).localeCompare(b.code || b.label, "zh-CN", { numeric: true }));
  return [...groups.values()].sort((a, b) => Number(a.historical) - Number(b.historical) || a.label.localeCompare(b.label, "zh-CN", { numeric: true }));
}
export function SkuAcrossWarehouses({ canWrite = false, renderTools, stockSource }: { stockSource?: OverviewSource; canWrite?: boolean; canOpen?: boolean; renderTools?: (context: OverviewTools) => ReactNode }) {
  const workspaceRef=useRef<HTMLElement>(null);const navigate=useNavigate();const location=useLocation();const [params,setParams]=useSearchParams();const [refresh,setRefresh]=useState(0);const [filtersOpen,setFiltersOpen]=useState(false);const [summaryOpen,setSummaryOpen]=useState(false);
  const { preferenceScope, registerSensitivePurge } = useAuthzGeneration();
  const display = useLoad<DisplaySettings>("/api/production/inventory/display-settings", refresh, true, true);
  const watchedIds = display.value?.style_ids || [];
  const [picker,setPicker] = useState<{scope:string;query:string;ids:string[]}>();
  useEffect(() => registerSensitivePurge(() => setPicker(undefined)), [registerSensitivePurge]);
  const settingsCommand = useCommand<DisplaySettings>(() => {
    setPicker(undefined);
    setRefresh(value => value + 1);
    stockSource?.reload();
  });
  const [action,setAction]=useState<OverviewAction>();const [actionOpen,setActionOpen]=useState(false);const [pendingAction,setPendingAction]=useState<OverviewAction>();
  const [guard,setGuard]=useState<OverviewGuard>({dirty:false,busy:false,unknown:false});const onGuardChange=useCallback((next:OverviewGuard)=>setGuard(next),[]);
  const [arrival,setArrival]=useState<TransitItem>();const [pendingArrival,setPendingArrival]=useState<{item:TransitItem;trigger:HTMLElement}>();const [arrivalClosing,setArrivalClosing]=useState(false);
  const [arrivalGuard,setArrivalGuard]=useState<OverviewGuard>({dirty:false,busy:false,unknown:false});const onArrivalGuard=useCallback((next:OverviewGuard)=>setArrivalGuard(next),[]);
  const catalog=useLoad<{items:Sku[]}>("/api/production/skus?contract_version=2",refresh,true,true);
  const ownStock=useLoad<OverviewStock>("/api/production/inventory/availability?overview=1",refresh,!stockSource,true);const stock=stockSource||ownStock;
  const transit=useLoad<TransportSummary>("/api/production/inventory/transport-summary",refresh,true,true);
  const balances=stock.value?.items||[];const scopes=stock.value?.scopes||[];const mapped=balances.filter(item=>item.identity_status!=="pending");const groups=groupsOf(catalog.value?.items||[],balances);
  const query=params.get('stock_q')||params.get('q')||'';const identity=params.get('identity')||'';
  const selectedGroup=groups.find(group=>watchedIds.includes(group.id)&&group.variants.some(sku=>sku.sku_id===params.get('sku_id')));const selected=selectedGroup?.variants.find(sku=>sku.sku_id===params.get('sku_id'));
  const requestedGroup=selectedGroup?.id||params.get('style_id');
  const filtered=groups.filter(group=>watchedIds.includes(group.id)).map(group=>({...group,variants:group.variants.filter(sku=>(!identity||(identity==='pending')===group.historical)&&`${group.label} ${sku.code||''} ${sku.label} ${sku.standard_color||''} ${sku.standard_size||''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))})).filter(group=>group.variants.length);
  const expanded=new Set(params.has('stock_styles')?(params.get('stock_styles')||'').split(','):(requestedGroup?[requestedGroup]:[]));
  const totalTransit=transit.value?.full_scope?transit.value.totals:undefined;
  const buttons=useRef(new Map<string,HTMLButtonElement>());const trigger=useRef<HTMLElement|null>(null);const [anchor,setAnchor]=useState<HTMLElement|null>(null);
  const warehouse=params.get('stock_scope')||undefined;const owner=params.get('stock_owner')||undefined;const transport=params.get('stock_detail')==='transport';
  const selectedKey=`${selected?.sku_id}:${warehouse||''}:${owner||''}:${transport?'transport':'stock'}`;
  const batchId=params.get('stock_batch')||undefined;const showBatch=!!batchId;const legacyTransportSku=transport&&params.get('sku_detail')==='1'&&selected&&!selectedGroup?.historical?selected.sku_id:undefined;
  const showDetail=!!selected&&params.get('sku_detail')==='1'&&expanded.has(selectedGroup!.id)&&!showBatch&&!transport;
  useEffect(()=>{if(guard.blocked)setActionOpen(true);},[guard.blocked]);
  const windowOpen=!!arrival || showBatch || showDetail || !!action && (actionOpen || !!guard.blocked);
  const handling=!arrival && !!action && (actionOpen || !!guard.blocked);
  useEffect(()=>{if(showDetail){const next=buttons.current.get(selectedKey)||buttons.current.get(`${selected?.sku_id}:::stock`)||null;if(next){trigger.current=next;setAnchor(next);}}},[showDetail,selectedKey,selected?.sku_id,stock.value,catalog.value]);
  useEffect(()=>{if(showBatch&&!arrival){const target=[...(workspaceRef.current?.querySelectorAll<HTMLElement>('[data-transit-batch]')||[])].find(element=>element.dataset.transitBatch===batchId)||workspaceRef.current?.querySelector<HTMLElement>('[data-transit-heading]')||null;if(target){trigger.current=target;setAnchor(target);}}},[showBatch,batchId,refresh,arrival]);
  const pendingBatchFocus=useRef<string|undefined>(undefined);
  const onBatchReady=useCallback(()=>{const id=pendingBatchFocus.current;if(!id)return;if(document.querySelector('dialog[open]')){pendingBatchFocus.current=undefined;return;}const target=[...(workspaceRef.current?.querySelectorAll<HTMLElement>('[data-transit-batch]')||[])].find(element=>element.dataset.transitBatch===id);if(target){target.focus({preventScroll:true});pendingBatchFocus.current=undefined;}},[]);
  function closeWindow(){if(guard.busy||guard.unknown||arrivalGuard.busy||arrivalGuard.unknown)return;if(arrival){if(arrivalGuard.dirty){setArrivalClosing(true);return;}dismissArrival();return;}if(showBatch&&!arrival){const target=[...(workspaceRef.current?.querySelectorAll<HTMLElement>('[data-transit-batch]')||[])].find(element=>element.dataset.transitBatch===batchId);if(target){trigger.current=target;setAnchor(target);pendingBatchFocus.current=undefined;}else pendingBatchFocus.current=batchId;}setActionOpen(false);update({sku_detail:'',sku_page:'',stock_batch:'',stock_detail:'stock'});}


  function update(values:Record<string,string>,cell?:string){const next=new URLSearchParams(params);for(const[key,value]of Object.entries(values)){if(value)next.set(key,value);else next.delete(key);}setParams(next,{state:{...(location.state as object||{}),...(cell?{stockCell:cell}:{})}});}
  function toggle(group:Group){const next=new Set(expanded);if(next.has(group.id))next.delete(group.id);else next.add(group.id);update({stock_styles:[...next].filter(Boolean).join(',')||'-',...(selectedGroup?.id===group.id&&!next.has(group.id)?{sku_detail:''}:{})});}
  function valuesFor(variant:Variant,historical:boolean){return balances.filter(item=>item.sku_id===variant.sku_id&&(item.identity_status==='pending'||!catalog.value?.items.some(sku=>sku.sku_id===item.sku_id))===historical);}
  const reload=()=>{setRefresh(value=>value+1);stockSource?.reload();};
  function startAction(next:OverviewAction){if(!windowOpen){const opener=workspaceRef.current?.querySelector<HTMLButtonElement>('button[aria-label="更多"]')||null;trigger.current=opener;setAnchor(opener);}if(action&&(guard.dirty||guard.busy||guard.unknown)&&JSON.stringify(next)!==JSON.stringify(action)){setPendingAction(next);return;}setAction(next);setActionOpen(true);}

  function dismissArrival(){setArrival(undefined);setArrivalClosing(false);setArrivalGuard({dirty:false,busy:false,unknown:false});setActionOpen(false);update({stock_batch:"",sku_detail:"",stock_detail:"stock"});}
  function activateArrival(item:TransitItem,opener:HTMLElement){setAction(undefined);setActionOpen(false);setGuard({dirty:false,busy:false,unknown:false});setArrivalGuard({dirty:false,busy:false,unknown:false});setArrivalClosing(false);setArrival(item);trigger.current=opener;setAnchor(opener.closest("dialog")?[...(workspaceRef.current?.querySelectorAll<HTMLElement>("[data-transit-batch]")||[])].find(element=>element.dataset.transitBatch===item.id)||opener:opener);update({stock_batch:item.id,stock_detail:'batch',sku_detail:''});}
  function startArrival(item:TransitItem,opener:HTMLElement){if(guard.busy||guard.unknown)return;if(action&&guard.dirty){setPendingArrival({item,trigger:opener});setActionOpen(true);return;}activateArrival(item,opener);}
  function cell(variant:Variant,values:Balance[],scope?:WarehouseScope,label?:string){
    const key=`${variant.sku_id}:${scope?.warehouse_id||''}:${scope?.owner_id||''}:stock`;const open=showDetail&&selectedKey===key;
    const onHand=scope&&!values.length?null:sum(values,'on_hand_units',!!stock.value);
    return <Button ref={element=>{if(element)buttons.current.set(key,element);else buttons.current.delete(key);}} variant="quiet" className={`${styles.quantityButton} ${label?styles.identityButton:""}`} aria-expanded={open} aria-label={`${variant.code||variant.label} · ${scope?`${scope.warehouse_name} · ${scope.owner_name}`:'全部仓库'} · 查看明细`} onClick={event=>{setActionOpen(false);trigger.current=event.currentTarget;setAnchor(event.currentTarget);update({style_id:groups.find(group=>group.variants.some(item=>item.sku_id===variant.sku_id))!.id,sku_id:variant.sku_id,sku_detail:open?'':'1',stock_styles:[...new Set([...expanded,styleId(variant)])].filter(Boolean).join(','),stock_scope:scope?.warehouse_id||'',stock_owner:scope?.owner_id||'',stock_detail:'stock',stock_batch:'',sku_page:''},key);}}><span><strong>{label||amount(onHand)}</strong>{!scope&&!values.length&&stock.value&&<small>未登记 · 各仓待核</small>}</span></Button>;
  }
  const pickerOpen = picker?.scope === preferenceScope && display.value?.can_manage === true;
  const pickerGroups = groups.filter(group=>group.label.toLocaleLowerCase().includes((picker?.query||'').trim().toLocaleLowerCase()));
  function applyStyles(){
    if (!picker || !display.value?.can_manage) return;
    settingsCommand.submit("/api/production/inventory/display-settings", {
      expected_revision: display.value.revision, style_ids: [...new Set(picker.ids)],
    });
  }
  const more=[{id:'sheet',label:'库存变动总表首页',onSelect:()=>navigate('/home')},{id:'summary',label:summaryOpen?'隐藏库存汇总':'查看库存汇总',onSelect:()=>setSummaryOpen(value=>!value)},{id:'source',label:'原始库存记录与来源',onSelect:()=>startAction({kind:'source'})},{id:'materials',label:'库存资料核对',onSelect:()=>navigate('/production/stock/materials')},...(canWrite?[{id:'manual',label:'手工登记库存',onSelect:()=>navigate('/production/stock/movements/new')},{id:'intake',label:'更新库存',onSelect:()=>navigate('/production/stock/intake')},{id:'reserve',label:'预留或冻结库存（全范围）',onSelect:()=>startAction({kind:'reserve'})} ]:[]),{id:'release',label:canWrite?'预留与冻结记录／释放':'预留与冻结记录',onSelect:()=>startAction({kind:'release'})},{id:'plans',label:'预计库存',onSelect:()=>navigate('/production/stock/plans')},{id:'loans',label:'借出与归还',onSelect:()=>navigate('/production/stock/loans')},{id:'history',label:'操作历史',onSelect:()=>navigate('/production/stock/history')},...(action?[{id:'current',label:'继续当前办理',onSelect:()=>setActionOpen(true)}]:[])];
  return <section ref={workspaceRef} className={styles.workspace} aria-label="库存总览工作台">
    <PageHeader title="库存总览" actions={<>{display.value?.can_manage && <Button variant="secondary" disabled={display.loading||!catalog.value||guard.dirty||guard.busy||guard.unknown||arrivalGuard.dirty||arrivalGuard.busy||arrivalGuard.unknown} onClick={()=>setPicker({scope:preferenceScope,query:'',ids:[...watchedIds]})}>设置展示款号</Button>}<Button variant="secondary" aria-expanded={filtersOpen} aria-controls="stock-overview-filters" onClick={()=>setFiltersOpen(value=>!value)}>筛选</Button><Menu label="更多" items={more}/></>} />
    <Dialog open={pickerOpen} onOpenChange={open=>{if(!open)setPicker(undefined);}} title="设置展示款号" description="保存后，当前站点所有账号的库存总览使用这份清单。" dismissDisabled={settingsCommand.busy || settingsCommand.unknown} closeLabel="关闭款号选择">
      <div className={styles.stylePicker}>
        <fieldset disabled={settingsCommand.busy || settingsCommand.unknown} className={styles.stylePicker}>
        <Input aria-label="搜索可选款号" type="search" placeholder="输入款号查找" value={picker?.query||''} onChange={event=>setPicker(current=>current?{...current,query:event.target.value}:current)}/>
        <div className={styles.pickerActions}><span>已选 {picker?.ids.length||0} 款</span><Button variant="quiet" onClick={()=>setPicker(current=>current?{...current,ids:[...new Set([...current.ids,...pickerGroups.map(group=>group.id)])]}:current)}>全选搜索结果</Button><Button variant="quiet" onClick={()=>setPicker(current=>current?{...current,ids:[]}:current)}>清空选择</Button></div>
        <div className={styles.styleOptions} role="group" aria-label="可选款号">{pickerGroups.map(group=><label key={group.id}><input type="checkbox" aria-label={`选择款号${group.label}`} checked={picker?.ids.includes(group.id)||false} onChange={event=>setPicker(current=>current?{...current,ids:event.target.checked?[...current.ids,group.id]:current.ids.filter(id=>id!==group.id)}:current)}/><strong>{group.label}</strong><small>{group.variants.length}个SKU{group.historical?' · 身份待核':''}</small></label>)}{!pickerGroups.length&&<p>没有匹配的款号，请调整搜索。</p>}</div>
        <div className={styles.pickerActions}><Button variant="primary" onClick={applyStyles}>保存展示范围</Button><Button variant="secondary" onClick={()=>setPicker(undefined)}>取消</Button></div>
        </fieldset>
        {settingsCommand.feedback}
        {settingsCommand.errorCode === "display_revision_conflict" && <Button onClick={() => { setPicker(undefined); reload(); }}>重新读取展示清单</Button>}
      </div>
    </Dialog>
    {display.error && <StatusMessage kind="danger" title="展示范围读取未完成" action={<Button onClick={reload}>重新读取展示范围</Button>}>{display.error}</StatusMessage>}
    {summaryOpen&&<section className={styles.summary} aria-label="展示范围库存与整批运输汇总"><dl>{[["在库", sum(balances, "on_hand_units", !!stock.value), "已登记实物，不含在途"], ["账面可发", sum(mapped, "free_available_units", !!stock.value), "各仓可发合计，不能跨仓放行"], ["运输中", totalTransit?.in_transit_units, "发出未收，不计入在库"], ["到仓待核", totalTransit?.arrival_check_units, "到达未收清，不计入在库"]].map(([label, value, note]) => <div key={label}><dt>{label}</dt><dd>{amount(value)}<small>件</small></dd><p>{note}</p></div>)}</dl><p className={styles.summaryScope}>在库与可发按共享展示款号统计，运输按本站整批发运统计。{totalTransit && (totalTransit.unregistered_units !== "0" || totalTransit.exception_units !== "0") && <> 未登记运输待核 {amount(totalTransit.unregistered_units)}件 · 异常 {amount(totalTransit.exception_units)}件。</>}</p></section>}
    {catalog.error&&<StatusMessage kind="danger" title="款号列表读取未完成">{catalog.error}。已读款号保留，可刷新重试。</StatusMessage>}
    {stock.error&&<StatusMessage kind="danger" title="库存读取未完成">{stock.error}。已读数量保留，失败不作为零。<Button onClick={reload}>重试库存读取</Button></StatusMessage>}
    {transit.error&&<StatusMessage kind="danger" title="运输摘要读取未完成">{transit.error}。运输数量保持待核，可刷新重试。</StatusMessage>}
    {!catalog.value&&!catalog.error&&<p role="status">正在读取款号与SKU…</p>}
    {filtersOpen&&<section id="stock-overview-filters" className={styles.filterPanel} aria-label="库存筛选"><FormField label="筛选款号、颜色或SKU（可选）"><Input value={query} onChange={event=>update({stock_q:event.target.value,q:'',sku_detail:''})}/></FormField><FormField label="商品对应状态"><select value={identity} onChange={event=>update({identity:event.target.value,sku_detail:''})}><option value="">全部库存</option><option value="mapped">已对应服务器商品</option><option value="pending">商品身份待核</option></select></FormField><Button onClick={()=>update({stock_q:'',q:'',identity:''})}>清除筛选</Button><Button variant="quiet" onClick={()=>setFiltersOpen(false)}>收起筛选</Button></section>}
    <div className={styles.overviewColumns}>
    <div className={styles.singleTable}>
    <Table aria-label="多款库存总表" className={styles.unifiedTable}><thead><tr><th scope="col">款号</th><th scope="col">颜色</th><th scope="col">尺码</th>{scopes.map(scope=><th scope="col" className={styles.scopeHeading} key={`${scope.warehouse_id}:${scope.owner_id}`} title={scope.warehouse_name}><span>{scope.warehouse_name.replace(/\s*[（(].*$/, "")}</span></th>)}</tr></thead><tbody>{filtered.map(group=>{
      const records=group.variants.flatMap(variant=>valuesFor(variant,group.historical));const open=expanded.has(group.id);
      return <Fragment key={group.id}><tr className={styles.styleRow} data-stock-style={group.id}><th scope="row" colSpan={3}><Button variant="quiet" className={styles.styleToggle} aria-label={`${open?'收起':'展开'}款号${group.label}`} aria-expanded={open} aria-controls={`stock-style-${encodeURIComponent(group.id)}`} onClick={()=>toggle(group)}>{open?<ChevronDown size={18}/>:<ChevronRight size={18}/>}<strong>{group.label}</strong>{group.historical&&<small>身份待核 · 禁止过账</small>}</Button></th>{scopes.map(scope=><td key={`${scope.warehouse_id}:${scope.owner_id}`}>{amount(sum(records.filter(value=>value.warehouse_id===scope.warehouse_id&&value.owner_id===scope.owner_id),'on_hand_units',!!stock.value))}</td>)}</tr>
      {open&&group.variants.map((variant,index)=>{const values=valuesFor(variant,group.historical);return <tr key={variant.sku_id} id={index===0?`stock-style-${encodeURIComponent(group.id)}`:undefined} className={selected?.sku_id===variant.sku_id?styles.selectedSku:undefined}><th scope="row" className={styles.styleCell}>{group.label}</th><td className={styles.colorCell}>{cell(variant,values,undefined,variant.standard_color||'颜色待核')}{group.historical&&<small>商品身份待核</small>}</td><td className={styles.sizeCell}>{variant.standard_size||'尺码待核'}{group.variants.some(other=>other.sku_id!==variant.sku_id&&other.standard_color===variant.standard_color&&other.standard_size===variant.standard_size)&&<small>{variant.code||variant.label}</small>}</td>{scopes.map(scope=><td key={`${scope.warehouse_id}:${scope.owner_id}`}>{cell(variant,values.filter(value=>value.warehouse_id===scope.warehouse_id&&value.owner_id===scope.owner_id),scope)}</td>)}</tr>;})}</Fragment>;
    })}</tbody></Table>
    {!display.value && !display.error && <p role="status">正在读取展示范围…</p>}
    {!filtered.length&&catalog.value&&display.value&&<StatusMessage kind="info" title={!watchedIds.length ? "管理员尚未设置展示款号" : "没有符合当前筛选的款号"}>{display.value.can_manage ? "点击“设置展示款号”维护共享清单。" : "请联系管理员或数据管理员设置展示款号。"}</StatusMessage>}
    {((params.get('sku_id')&&!selected)||(params.get('style_id')&&!groups.some(group=>group.id===params.get('style_id')&&watchedIds.includes(group.id))))&&catalog.value&&<StatusMessage kind="warning" title="原链接不在当前展示范围">请在当前展示款号中选择商品，或联系管理员核对范围。</StatusMessage>}
    </div>
    <TransitBatchBoard canWrite={canWrite&&!guard.busy&&!guard.unknown} verify={startArrival} onReady={onBatchReady} refresh={refresh} selectedId={batchId} legacySku={legacyTransportSku} change={values=>update(values)} open={(id,opener)=>{trigger.current=opener;setAnchor(opener);setActionOpen(false);update({stock_batch:id,sku_detail:'',stock_detail:'batch'},`batch:${id}`);}} />
    </div>
    <p className={styles.note}><Info size={14} aria-hidden="true"/>点击款号展开/收起；点击在库数量查看明细与办理。整批运输在运输看板独立查看。主表为已选款号{query||identity?'及当前筛选':''}范围；运输看板仍显示全部批次；合计仅含已建账；未知显示待核，在途不计在库，FBA为本地事件账。</p>

    <StockDetailWindow viewKey={`${arrival?`arrival:${arrival.id}`:handling?JSON.stringify(action):showBatch?`batch:${batchId}`:selectedKey}:${!!pendingAction}:${!!guard.blocked}`} open={windowOpen} title={arrival ? "到仓核验" : handling ? (action?.kind==='source'?'原始库存记录与来源':'库存办理') : showBatch?'运输批次':selected?.code||selected?.label||'库存明细'} closeLabel={arrival?"关闭到仓核验":handling?'收起办理':showBatch?'关闭运输批次':'关闭数量明细'} dismissDisabled={guard.busy||guard.unknown||arrivalGuard.busy||arrivalGuard.unknown} onClose={closeWindow} returnFocus={anchor}>
      {!arrival&&(selected||showBatch)&&action&&<nav className={styles.windowTabs} aria-label="库存窗口内容"><Button variant="quiet" aria-pressed={!handling} onClick={()=>{setActionOpen(false);update({sku_detail:showBatch?'':'1'});}}>{showBatch?'批次明细':'库存明细'}</Button><Button variant="quiet" aria-pressed={handling} onClick={()=>setActionOpen(true)}>当前办理</Button></nav>}
      {!!pendingAction&&<ProductionConfirmDialog open onOpenChange={open=>{if(!open)setPendingAction(undefined);}} title={guard.unknown?"先核实保存结果":"还有未保存的办理内容"} description={guard.unknown?"先查询当前操作结果，避免重复记账。":"更换办理内容前，请继续完成或明确放弃当前输入。"}><Button variant="primary" onClick={()=>{setPendingAction(undefined);setActionOpen(true);}}>继续当前办理</Button>{!guard.unknown&&<Button variant="danger" disabled={guard.busy} onClick={()=>{setAction(pendingAction);setPendingAction(undefined);setGuard({dirty:false,busy:false,unknown:false});setActionOpen(true);}}>放弃并更换</Button>}</ProductionConfirmDialog>}
      {!!pendingArrival&&<ProductionConfirmDialog open onOpenChange={open=>{if(!open)setPendingArrival(undefined);}} title="还有未保存的库存办理" description="请继续原办理，或明确放弃输入后开始到仓核验。"><Button onClick={()=>setPendingArrival(undefined)}>继续原办理</Button><Button variant="danger" disabled={guard.busy||guard.unknown} onClick={()=>{const pending=pendingArrival;setPendingArrival(undefined);activateArrival(pending.item,pending.trigger);}}>放弃原输入并开始核验</Button></ProductionConfirmDialog>}
      {arrivalClosing&&<ProductionConfirmDialog open onOpenChange={setArrivalClosing} title="还有未保存的核验内容" description="继续填写，或明确放弃当前输入后关闭核验。"><Button onClick={()=>setArrivalClosing(false)}>继续核验</Button><Button variant="danger" onClick={dismissArrival}>放弃并关闭核验</Button></ProductionConfirmDialog>}
      {arrival&&<ArrivalVerification item={arrival} refresh={refresh} canWrite={canWrite} saved={reload} onGuardChange={onArrivalGuard}/>}
      <div hidden={handling||!!arrival}>{showBatch&&<TransitBatchDetail id={batchId} refresh={refresh} canWrite={canWrite} verify={startArrival} />}{showDetail&&<StockQuantityDetail variant={selected} historical={selectedGroup!.historical} stock={stock.value} values={valuesFor(selected,selectedGroup!.historical)} warehouse={warehouse} owner={owner} transport={false} page={Math.max(1,Number(params.get('sku_page'))||1)} refresh={refresh} canWrite={canWrite&&!stock.error} changePage={page=>update({sku_page:String(page)})} selectScope={(warehouse,owner)=>update({stock_scope:warehouse,stock_owner:owner})} act={startAction}/>}</div>
      {action&&renderTools&&<section id="stock-overview-action" className={styles.windowAction} hidden={!handling} aria-label="库存按需办理">{renderTools({stock:stock.value,catalog:catalog.value?.items,stockError:stock.error,catalogError:catalog.error,refresh:reload,variants:groups.flatMap(group=>group.variants),historical:false,action,startAction,onGuardChange})}</section>}
    </StockDetailWindow>
  </section>;
}
