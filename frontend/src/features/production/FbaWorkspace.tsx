import { Disclosure } from "../../design-system";
import { useState } from "react";

import { useSearchParams } from "react-router-dom";
import { Button, FormField, Input, LinkButton, Menu, StatusMessage } from "../../design-system";
import { useCommand, useLoad } from "./useProductionApi";
import { ReadState } from "./WorkbenchFields";
import type { DirectoryRecord } from "./directoryTypes";
import type { Sku } from "./types";
import { FbaDailyUpdate } from "./FbaDailyUpdate";
import { FbaInventoryOverview } from "./FbaInventoryOverview";
import { FbaOpening } from "./FbaOpening";
import { WarehouseSourceEvidence } from "./WarehouseSourceEvidence";
import { FbaReceipts } from "./FbaReceipts";
import { FbaIdentityExtension } from "./FbaIdentityExtension";
import { fbaView } from "./warehouseNavigation";
import { fbaReasons, tracked, fbaKinds, type FbaState, type FbaScope, type FbaIdentity } from "./fbaTypes";
import styles from "./FbaWorkspace.module.css";

const api = "/api/production/fba";
const sum = (values: (string | undefined)[]) => values.reduce((a,v) => a + BigInt(v || "0"),0n).toLocaleString("zh-CN");
export function FbaWorkspace({ record, canWrite, owner, refresh, reload }: { record: DirectoryRecord; canWrite: boolean; owner: string; refresh: number; reload: () => void }) {
  const [params,setParams] = useSearchParams(); const view = fbaView(params);
  const [manualOpen, setManualOpen] = useState(view === "fulfillment" || view === "returns");
  const state = useLoad<FbaState>(`${api}/state?warehouse_id=${record.id}`,refresh,true,true,true);
  const source = useLoad<{report_source_scope_id: number | null; seller_account_display_name: string | null}>("/api/catalog/source-scope",refresh,true,true,true);
  const selectedScope = state.value?.scopes.find(scope => scope.owner_id === owner) || (!owner ? state.value?.scopes[0] : undefined);
  const reportScope = selectedScope?.report_source_scope_id ?? source.value?.report_source_scope_id;
  const catalog = useLoad<{items: Sku[]}>(`/api/production/skus?contract_version=2${reportScope ? `&report_source_scope_id=${reportScope}` : ""}`,refresh,!!state.value && !!source.value,true);
  if (!state.value || !catalog.value || !source.value) return <ReadState error={state.error || catalog.error || source.error} />;
  const data=state.value;
  if (!data.enabled) return <StatusMessage kind="info" title="FBA库存适配未启用">当前仅保留平台档案；普通收发入口不允许向FBA记账。</StatusMessage>;
  if (!data.initialized && record.source_evidence?.kind === "fba") return <WarehouseSourceEvidence source={record.source_evidence} />;
  if (!data.initialized) return canWrite ? <FbaOpening record={record} catalog={catalog.value.items} sourceId={source.value.report_source_scope_id} sourceName={source.value.seller_account_display_name} saved={()=>{const query=new URLSearchParams(params);query.set("fba_view","balance");setParams(query);reload();}} /> : <StatusMessage kind="info" title="FBA期初与身份尚未确认">当前账号只读；未建立期初不代表库存为零。</StatusMessage>;
  const scope=data.scopes.find(s=>s.owner_id===owner) || (!owner ? data.scopes[0] : undefined);
  if (!scope) return <StatusMessage kind="warning" title="货权范围待核">请选择已确认的FBA账号与货权，不能合并其他货主余额。</StatusMessage>;
  const identities=data.identities.filter(i=>i.scope_id===scope.id);
  const writable=canWrite && record.status === "ACTIVE";
  const navigate=(next:string)=>{const query=new URLSearchParams(params);query.set("fba_view",next);setParams(query);};
  const context = <p>{source.value.seller_account_display_name||scope.seller_account} · {scope.marketplace}{scope.simulated&&" · 模拟账簿，真实账号未绑定"}</p>;
  const navigation = <nav className={styles.navigation} aria-label="库存操作">
    {view!=="balance"&&<Button variant="quiet" onClick={()=>navigate("balance")}>返回库存</Button>}
    <Menu label="更多办理" items={([["updates","库存更新"],["receipts","到货验收"],["fulfillment","销售与退货"],["tracking","FBA 商品管理"],["history","操作记录"]] as const).map(([key,label])=>({id:key,label,onSelect:()=>navigate(key)}))}/>
  </nav>;
  return <section className={`${styles.workspace} ${view==="balance" ? styles.balanceWorkspace : ""}`} aria-label="FBA库存工作台">

    {view==="balance" ? <FbaDailyUpdate key={scope.id} data={data} scope={scope} catalog={catalog.value.items} canWrite={writable} actions={navigation} saved={reload}/> : <>{navigation}{view!=="updates"&&<Disclosure className={styles.stockInfo}><summary>{scope.simulated?"店铺信息（模拟）":"店铺信息"}</summary>{context}</Disclosure>}</>}
    {view==="updates" ? <FbaDailyUpdate showStatus key={scope.id} data={data} scope={scope} catalog={catalog.value.items} canWrite={writable} actions={navigation} saved={reload}/> : view==="connect" ? <FbaIdentityExtension scope={scope} identities={identities} catalog={catalog.value.items} canWrite={writable} saved={reload}/> : view==="balance" ? <FbaBalance data={data} scope={scope} identities={identities} catalog={catalog.value.items} /> : view==="receipts" ? <FbaReceipts data={data} scope={scope} catalog={catalog.value.items} canWrite={writable} refresh={refresh} reload={reload} /> : view==="tracking" ? <FbaTracking key={`${scope.id}:${scope.revision}`} scope={scope} identities={identities} catalog={catalog.value.items} canWrite={writable} saved={reload} /> : view==="observation" ? <FbaPhysical key={`${scope.id}:${view}`} data={data} scope={scope} identities={identities} kind="OBSERVATION" canWrite={writable} saved={reload} /> : ["fulfillment","returns"].includes(view) ? <section className={styles.workspace} aria-label="销售与退货"><h2>销售与退货</h2><p>经营日报与退货日报在数据审核中导入并发布。经营日报发布后自动扣减销售数量，退货日报按实物退回记录增加库存。</p><div><LinkButton variant="secondary" to="/">查看已发布日报</LinkButton></div><Disclosure open={manualOpen} onToggle={event=>setManualOpen(event.currentTarget.open)}><summary>手工登记销售或退货</summary><nav className={styles.navigation} aria-label="手工登记类型"><Button variant="quiet" aria-pressed={view==="fulfillment"} onClick={()=>navigate("fulfillment")}>销售出库</Button><Button variant="quiet" aria-pressed={view==="returns"} onClick={()=>navigate("returns")}>退货入库</Button></nav><FbaPhysical key={`${scope.id}:${view}`} data={data} scope={scope} identities={identities} kind={view==="fulfillment"?"FULFILLMENT":"RETURN"} canWrite={writable} saved={reload} /></Disclosure></section> : <FbaHistory data={data} scope={scope} canWrite={writable} saved={reload} />}
    {record.source_evidence?.kind === "fba" && <Disclosure className={styles.balanceDetails}><summary>装箱与验收来源资料</summary><WarehouseSourceEvidence source={record.source_evidence} ledgerReady /></Disclosure>}
  </section>;
}
function FbaTracking({scope,identities,catalog,canWrite,saved}:{scope:FbaScope;identities:FbaIdentity[];catalog:Sku[];canWrite:boolean;saved:()=>void}) {
  const catalogChanged = identities.some(identity => catalog.find(sku => sku.sku_id === identity.sku_id)?.catalog_version !== scope.catalog_version);
  const [reconfirm, setReconfirm] = useState(false);
  const [store, setStore] = useState(scope.store_evidence);
  const [selected, setSelected] = useState(identities.filter(identity => tracked(identity.tracked)).map(identity => identity.sku_id));
  const [reason, setReason] = useState("");
  const command = useCommand<FbaState>(saved);
  const disabled = !canWrite || command.busy || command.unknown;
  function toggle(ids: string[], checked: boolean) {
    setSelected(previous => checked ? [...new Set([...previous, ...ids])] : previous.filter(id => !ids.includes(id)));
  }
  return <section className={styles.panel} aria-label="FBA 商品管理">
    <div className={styles.rowTitle}><h2>FBA 商品管理</h2>{canWrite && <LinkButton variant="quiet" to={`/production/warehouses/${scope.warehouse_id}?owner=${scope.owner_id}&tab=stock&fba_view=connect`}>添加商品</LinkButton>}</div>
    <p>{identities.filter(identity => tracked(identity.tracked)).length}个启用规格 · {identities.filter(identity => !tracked(identity.tracked)).length}个停用规格</p>
    {command.feedback}
    {catalogChanged && <section><h3>核对商品资料更新</h3><StatusMessage kind="warning" title="商品主档已更新，请核对后继续"/><table className={styles.table} aria-label="FBA当前目录身份核对"><thead><tr><th>FBA商品</th><th>当前主档商品</th></tr></thead><tbody>{identities.map(identity => <tr key={identity.sku_id}><td>{identity.seller_sku}</td><td>{catalog.find(sku => sku.sku_id === identity.sku_id)?.code || "待核对"}</td></tr>)}</tbody></table><label className={styles.check}><input type="checkbox" disabled={disabled} checked={reconfirm} onChange={event=>setReconfirm(event.target.checked)}/>已核对原FBA商品身份未变，确认使用当前目录</label></section>}
    <table className={styles.table} aria-label="FBA商品列表"><thead><tr><th>商品规格</th><th>状态</th></tr></thead><tbody>{identities.map(identity => <tr key={identity.sku_id}><th scope="row">{catalog.find(sku => sku.sku_id === identity.sku_id)?.code || identity.seller_sku}</th><td>{tracked(identity.tracked) ? "已启用" : "已停用"}</td></tr>)}</tbody></table>
    {canWrite && <Disclosure className={styles.productSettings}><summary>停用、恢复或更新商品资料</summary>
      <p>勾选需要继续使用的商品，取消勾选后停用。历史库存与收发记录保留。</p>
      {[...new Set(identities.map(identity => identity.style_id))].map(style => {
        const items = identities.filter(identity => identity.style_id === style);
        const title = catalog.find(sku => sku.style_id === style)?.style_code || style;
        return <div key={style} className={styles.row}><label className={styles.check}><input type="checkbox" aria-label={`启用款号 ${title}`} disabled={disabled} checked={items.every(identity => selected.includes(identity.sku_id))} onChange={event=>toggle(items.map(identity=>identity.sku_id),event.target.checked)}/><strong>{title}</strong> 已选{items.filter(identity=>selected.includes(identity.sku_id)).length}个规格</label><Disclosure><summary>选择单个规格</summary><div className={styles.variants}>{items.map(identity=><label className={styles.check} key={identity.sku_id}><input type="checkbox" disabled={disabled} checked={selected.includes(identity.sku_id)} onChange={event=>toggle([identity.sku_id],event.target.checked)}/>{identity.seller_sku}</label>)}</div></Disclosure></div>;
      })}
      <Disclosure><summary>修改报告店铺名</summary><FormField label="报告中的店铺名（Store）" required><Input disabled={disabled} value={store} onChange={event=>setStore(event.target.value)}/></FormField></Disclosure>
      <FormField label="调整原因" required><Input disabled={disabled} value={reason} onChange={event=>setReason(event.target.value)}/></FormField>
      <div><Button disabled={disabled || !reason || !store || catalogChanged && !reconfirm} onClick={()=>command.submit(`${api}/commands/tracking`,{scope_id:scope.id,expected_revision:scope.revision,sku_ids:selected,store_name:store,reconfirm_catalog:catalogChanged&&reconfirm,reason})}>保存商品设置</Button></div>
    </Disclosure>}
  </section>;
}
export function FbaBalance({data,scope,identities,catalog=[]}:{data:FbaState;scope:FbaScope;identities:FbaIdentity[];catalog?:Sku[]}) {
  const items=data.stock.items.filter(i=>i.owner_id===scope.owner_id);const observed=data.actions.filter(a=>a.scope_id===scope.id&&a.kind==="OBSERVATION"&&a.status==="POSTED").sort((a,b)=>Date.parse(b.occurred_at)-Date.parse(a.occurred_at))[0];
  return <FbaInventoryOverview view={data.inventory_view?.[scope.id]} scope={scope} catalog={catalog}>
    <Disclosure className={styles.balanceDetails}><summary>查看详细对账</summary><div className={styles.balanceDetailsBody}><h3>库存与事件对账</h3><p className={styles.note}>明确零期初截止 {scope.cutoff_on} · {scope.opening_basis}。接收事件的SELLABLE表示当时处置，不是今日平台可售快照。</p>
    <dl className={styles.summary}>{[["账面在库",items.some(i=>i.on_hand_units===null)?"待核":sum(items.map(i=>i.on_hand_units||undefined))],["账面可发",items.some(i=>i.free_available_units===null)?"待核":sum(items.map(i=>i.free_available_units||undefined))],["不可售",sum(identities.map(i=>i.unsellable))],["未收待核",data.reconciliation?.[scope.id]?.unreceived_units??"未知"],["平台观察",observed?"有待核对快照":"尚未提供"]].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    <div className={styles.scroll} tabIndex={0}><table className={styles.table} aria-label="FBA库存对账"><thead><tr><th>规格 / 跟踪</th><th>净接收</th><th>销售出库</th><th>实物退回</th><th>在库</th><th>可售</th><th>不可售</th><th>待检</th><th>预留 / 冻结</th><th>事件对账</th><th>平台观察</th></tr></thead><tbody>{identities.map(i=>{const receipt=data.events.filter(e=>e.scope_id===scope.id&&e.sku_id===i.sku_id).reduce((a,e)=>a+BigInt(e.units),0n);const active=data.actions.filter(a=>a.scope_id===scope.id&&a.status==="POSTED");const amount=(kind:string)=>active.filter(a=>a.kind===kind).flatMap(a=>a.payload.lines).filter(l=>l.sku_id===i.sku_id).reduce((a,l)=>a+BigInt(l.units||"0"),0n);const fulfilled=amount("FULFILLMENT"),returned=amount("RETURN");const stock=items.find(s=>s.sku_id===i.sku_id);const comparison=data.reconciliation?.[scope.id]?.rows.find(r=>r.sku_id===i.sku_id)?.observation;const snapshot=comparison?.observed;const counted=(data.stocktakes||[]).filter(e=>e.scope_id===scope.id&&e.sku_id===i.sku_id).reduce((sum,e)=>sum+BigInt(e.units),0n);const expected=receipt-fulfilled+returned+counted;return <tr key={i.sku_id}><th scope="row">{i.seller_sku}<div className={styles.note}>{tracked(i.tracked)?"已跟踪":"未跟踪 · 保留余额"}</div></th><td>{receipt.toString()}</td><td>{fulfilled.toString()}</td><td>{returned.toString()}</td><td>{stock?.on_hand_units??"待核"}</td><td>{i.sellable}</td><td>{i.unsellable}</td><td>{i.pending_units}</td><td>{stock?.reserved_units??"待核"} / {stock?.held_units??"待核"}</td><td>{stock?.on_hand_units==null?"待核":BigInt(stock.on_hand_units)===expected?"一致":"有差异"}</td><td>{snapshot?`可售${snapshot.sellable} / 预留${snapshot.reserved} / 不可售${snapshot.unsellable} / 冻结${snapshot.held}；时点账面可售${comparison?.book_sellable} / 不可售${comparison?.book_unsellable}；观察差额${comparison?.sellable_difference} / ${comparison?.unsellable_difference}`:"未知，未填零"}</td></tr>;})}</tbody></table></div>
    <p className={styles.note}>{observed?`最新观察 ${observed.occurred_at}：${observed.payload.reason}。快照不叠加到库存；与当前账面的截止可能不同。`:"尚无平台结存观察，当前只能核对已登记事件，不能宣称与Amazon实时余额相符。"}</p><div className={styles.actions}><LinkButton to="/products">查看经营与退货分析</LinkButton><LinkButton variant="quiet" to={`/production/warehouses/${scope.warehouse_id}?owner=${scope.owner_id}&tab=stock&fba_view=observation`}>核对Amazon库存</LinkButton><LinkButton to={`${api}/reconciliation/export?warehouse_id=${scope.warehouse_id}&scope_id=${scope.id}`} reloadDocument>导出库存对账（查看）</LinkButton></div>
    </div></Disclosure>
  </FbaInventoryOverview>;
}
function FbaPhysical({data,scope,identities,kind,canWrite,saved}:{data:FbaState;scope:FbaScope;identities:FbaIdentity[];kind:"FULFILLMENT"|"RETURN"|"OBSERVATION";canWrite:boolean;saved:()=>void}) {
  const [values,setValues]=useState<Record<string,Record<string,string>>>({});const [key,setKey]=useState("");const [time,setTime]=useState("");const [reason,setReason]=useState("");const [physical,setPhysical]=useState(false);const [fulfillment,setFulfillment]=useState("");const [bulk,setBulk]=useState("");const [reportIds,setReportIds]=useState<string[]>([]);
  const command=useCommand<FbaState>(()=>{setValues({});setPhysical(false);setKey("");saved();});const disabled=!canWrite||command.busy||command.unknown;const available=identities.filter(i=>tracked(i.tracked));
  const date=/^\d{4}-\d{2}-\d{2}/.test(time)?time.slice(0,10):"";const reports=useLoad<{version_id:number;report_date:string;report_type:string;version_no:number;status:string}[]>(`/api/data-calendar?from=${date}&to=${date}`,0,!!date);
  const title=kind==="FULFILLMENT"?"销售出库":kind==="RETURN"?"退货入库":"Amazon库存核对";
  const put=(sku:string,field:string,value:string)=>setValues(previous=>({...previous,[sku]:{...previous[sku],[field]:value}}));
  function submit(){const lines=available.filter(i=>kind==="OBSERVATION"?values[i.sku_id]?.sellable!==undefined&&values[i.sku_id]?.sellable!=="":!!values[i.sku_id]?.units&&values[i.sku_id]?.units!=="0").map(i=>({sku_id:i.sku_id,...values[i.sku_id],...(kind==="RETURN"?{quality:values[i.sku_id]?.quality||"PENDING",...(values[i.sku_id]?.quality==="DEFECTIVE"?{reason_code:values[i.sku_id]?.reason_code||"WAREHOUSE_DAMAGED"}:{})}:{})}));command.submit(`${api}/commands/actions`,{scope_id:scope.id,kind,event_key:key,occurred_at:time,reason,physical_fact_confirmed:physical,fulfillment_id:fulfillment||undefined,lines,report_version_ids:reportIds});}
  return <section className={styles.panel}><h2>{title}</h2><p className={styles.note}>{kind==="FULFILLMENT"?"经营日报已自动扣减销售数量。同日同规格的手工销售记录会与日报抵扣，避免重复扣减；下单和退款不在此登记。":kind==="RETURN"?"确认实物已退回并关联原实际履约；待检/次品与可售分开，退款不自动恢复可售。":"填写明确时点的实际观察及来源，空白保持未知；保存不会改变任何账面库存。"}</p>{command.feedback}
    {canWrite&&<><fieldset disabled={disabled} className={styles.fields}><FormField label="业务单号或发货编号" required><Input value={key} onChange={e=>setKey(e.target.value)}/></FormField><FormField label="发生时间（含时区）" hint="如2026-10-27T10:00:00-07:00" required><Input value={time} onChange={e=>setTime(e.target.value)}/></FormField><FormField label="登记依据" required><Input value={reason} onChange={e=>setReason(e.target.value)}/></FormField>{kind==="RETURN"&&<FormField label="对应的销售出库记录" required><select value={fulfillment} onChange={e=>setFulfillment(e.target.value)}><option value="">请选择原销售出库记录</option>{data.actions.filter(a=>a.scope_id===scope.id&&a.kind==="FULFILLMENT"&&a.status==="POSTED"&&!a.payload.report_sales_key).map(a=><option value={a.id} key={a.id}>{a.event_key} · {a.occurred_at}</option>)}</select></FormField>}</fieldset>
    {reports.value?.filter(r=>r.status==="published").map(r=><label className={styles.check} key={r.version_id}><input type="checkbox" disabled={disabled} checked={reportIds.includes(String(r.version_id))} onChange={e=>setReportIds(p=>e.target.checked?[...p,String(r.version_id)]:p.filter(id=>id!==String(r.version_id)))}/>关联{r.report_date} {r.report_type==="business_report"?"经营":"退货"} v{r.version_no}（仅作经营关联，不代替实物依据）</label>)}
    {kind==="FULFILLMENT"&&<div className={styles.actions}><FormField label="每个启用商品的出库数量"><Input type="number" min="1" value={bulk} onChange={e=>setBulk(e.target.value)} disabled={disabled}/></FormField><Button disabled={disabled||!bulk} variant="secondary" onClick={()=>setValues(previous=>({...previous,...Object.fromEntries(available.map(i=>[i.sku_id,{...previous[i.sku_id],units:bulk}]))}))}>批量填写出库数量</Button></div>}
    <div className={styles.tracking}>{available.map(i=><div className={styles.row} key={i.sku_id}><strong>{i.seller_sku}</strong><div className={styles.fields}>{kind==="OBSERVATION"?([ ["sellable","观察可售"],["reserved","观察预留"],["unsellable","观察不可售"],["held","观察冻结"] ] as const).map(([field,label])=><FormField key={field} label={`${i.seller_sku} ${label}`}><Input disabled={disabled} inputMode="numeric" value={values[i.sku_id]?.[field]||""} onChange={e=>put(i.sku_id,field,e.target.value)}/></FormField>):<><FormField label={`${i.seller_sku} 实际件数`}><Input disabled={disabled} inputMode="numeric" value={values[i.sku_id]?.units||""} onChange={e=>put(i.sku_id,"units",e.target.value)}/></FormField><FormField label={`${i.seller_sku} 收发货凭据编号`}><Input disabled={disabled} value={values[i.sku_id]?.source_event_ref||""} onChange={e=>put(i.sku_id,"source_event_ref",e.target.value)}/></FormField><FormField label={`${i.seller_sku} 客户订单号`}><Input disabled={disabled} value={values[i.sku_id]?.customer_order_ref||""} onChange={e=>put(i.sku_id,"customer_order_ref",e.target.value)}/></FormField></>}{kind==="RETURN"&&<FormField label={`${i.seller_sku} 退回商品状态`}><select disabled={disabled} value={values[i.sku_id]?.quality||"PENDING"} onChange={e=>put(i.sku_id,"quality",e.target.value)}><option value="PENDING">待检</option><option value="DEFECTIVE">不可售 / 次品</option><option value="QUALIFIED">已确认合格可售</option></select></FormField>}{kind==="RETURN"&&values[i.sku_id]?.quality==="DEFECTIVE"&&<FormField label={`${i.seller_sku} 不可售原因`}><select disabled={disabled} value={values[i.sku_id]?.reason_code||"WAREHOUSE_DAMAGED"} onChange={e=>put(i.sku_id,"reason_code",e.target.value)}>{Object.entries(fbaReasons).filter(([code])=>code!=="UNCLASSIFIED").map(([code,label])=><option key={code} value={code}>{label}</option>)}</select></FormField>}</div></div>)}</div>
    <label className={styles.check}><input type="checkbox" checked={physical} disabled={disabled} onChange={e=>setPhysical(e.target.checked)}/>{kind==="OBSERVATION"?"这是明确时点的库存观察，保存不入账":"已核对实际发生及来源，同一事实尚未在其他入口入账"}</label><div><Button variant="primary" disabled={disabled||!physical||!key||!time||!reason||kind==="RETURN"&&!fulfillment} onClick={submit}>确认{title}</Button></div></>}
    <h3>已登记记录</h3>{data.actions.filter(a=>a.scope_id===scope.id&&a.kind===kind).map(a=><p className={styles.note} key={a.id}>{a.event_key} · {a.occurred_at} · {a.status==="POSTED"?"已登记":"已冲销"} · {a.payload.reason}</p>)}
  </section>;
}
function FbaHistory({data,scope,canWrite,saved}:{data:FbaState;scope:FbaScope;canWrite:boolean;saved:()=>void}) {
  const [reason,setReason]=useState("");const command=useCommand<FbaState>(saved);
  const operations: Record<string,string> = { EXPLICIT_ZERO_OPENING:"建立库存账簿", CONNECT_EXISTING_SKUS:"添加FBA商品", TRACKING:"更新商品设置", REPORT_SALES:"日报销售扣减", FULFILLMENT:"销售出库", RETURN:"退货入库", OBSERVATION:"核对Amazon库存", REVERSE:"撤销记录", POST:"登记库存记录" };
  return <section className={styles.panel}><h2>库存操作记录</h2>{command.feedback}
    <Disclosure><summary>查看或撤销收发记录</summary>
      {canWrite&&<FormField label="撤销原因"><Input disabled={command.busy||command.unknown} value={reason} onChange={e=>setReason(e.target.value)}/></FormField>}
      {data.actions.filter(a=>a.scope_id===scope.id).map(a=><Disclosure key={a.id}>
        <summary>{a.payload.report_sales?.business_date || a.occurred_at.slice(0,10)} · {fbaKinds[a.kind]} · {a.status==="POSTED"?"已登记":"已撤销"}</summary>
        <p>{a.event_key}</p><p>{a.occurred_at} · {a.payload.reason}</p>
        {a.payload.lines.map(line=><p key={line.sku_id}>规格{line.sku_id} · {line.units||"观察"}件 · {line.customer_order_ref||"不适用"} · {line.source_event_ref||"来源见依据"}</p>)}
        {canWrite&&a.status==="POSTED"&&!a.payload.report_sales_key&&<Button variant="secondary" disabled={!reason||command.busy||command.unknown} onClick={()=>command.submit(`${api}/commands/action-reverse`,{action_id:a.id,expected_revision:a.revision,reason})}>撤销这条记录</Button>}
      </Disclosure>)}
    </Disclosure>
    <table className={styles.table} aria-label="FBA操作记录"><thead><tr><th>日期</th><th>操作</th><th>操作人</th><th>说明</th></tr></thead><tbody>{data.history.map((entry,index)=><tr key={index}><td><time dateTime={entry.created_at} title={entry.created_at}>{entry.created_at.slice(0,10)}</time></td><td>{entry.document_kind.toLowerCase() === "stock" ? "盘点调整" : operations[entry.operation_kind] || entry.operation_kind}</td><td>{entry.actor_name}</td><td><Disclosure><summary>查看</summary><p>{entry.reason}</p></Disclosure></td></tr>)}</tbody></table>
  </section>;
}
