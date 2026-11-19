import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Trash2 } from "lucide-react";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, Input, LinkButton } from "../../design-system";
import { productionFieldId } from "./productionForm";
import { useLoad } from "./useProductionApi";
import { units, type Source } from "./types";
import styles from "./WarehouseDispatchTable.module.css";

type Balance = { state:string; dispatch_allowed_units:string|null; on_hand_units:string|null; free_available_units:string|null; own_reserved_units?:string|null; held_units?:string|null; qualified_units?:string|null; pending_units?:string|null; defective_units?:string|null; unassessed_units?:string|null; missing?:string };
type Fact = { value?:Balance; current:boolean; error?:string };
type Plan = {id:string;sku_id:string;warehouse_id:string;direction:string;source_reference:string;planned_on:string|null;remaining_units:string};
export type DispatchTableValidation = { pending:boolean; error?:string; field?:string };
const number=(value?:string|null)=>value!=null&&/^[0-9]{1,19}$/.test(value)&&BigInt(value)<=9223372036854775807n?BigInt(value):undefined;

function AvailabilityRead({identity,path,changed}:{identity:string;path:string;changed:(identity:string,fact:Fact)=>void}) {
 const {value,current,error}=useLoad<Balance>(path);
 useEffect(()=>changed(identity,{value,current,error}),[identity,changed,value,current,error]);
 return null;
}

export function WarehouseDispatchTable({sources,options,warehouse,owner,warehouseName,destination,date,plans,fieldErrors,locked,refresh,change,add,remove,validationChanged}:{
 sources:Source[];options:{value:string;label:string}[];warehouse:string;owner:string;warehouseName:string;destination:string;date:string;plans:Plan[];fieldErrors:Record<string,string>;locked:boolean;refresh:number;
 change:(index:number,patch:Partial<Source>)=>void;add:()=>void;remove:(index:number)=>void;validationChanged:(state:DispatchTableValidation)=>void;
}) {
 const [facts,setFacts]=useState<Record<string,Fact>>({});const [revision,setRevision]=useState(0);const [expanded,setExpanded]=useState<number>();
 const {generation,registerSensitivePurge}=useAuthzGeneration();
 useEffect(()=>registerSensitivePurge(()=>setFacts({})),[registerSensitivePurge]);
 const changed=useCallback((identity:string,fact:Fact)=>setFacts(current=>({...current,[identity]:fact})),[]);
 const reads=useMemo(()=>[...new Set(sources.map(s=>s.sku_id).filter(Boolean))].map(sku=>{
  const ids=[...new Set(sources.filter(s=>s.sku_id===sku).flatMap(s=>s.allocations.map(a=>a.order_line_id)).filter(Boolean))].sort().join(",");
  return {sku,identity:`${generation}:${refresh}:${revision}:${warehouse}:${owner}:${sku}:${ids}`,path:`/api/production/inventory/availability?${new URLSearchParams({warehouse_id:warehouse,owner_id:owner,sku_id:sku,order_line_ids:ids})}`};
 }),[sources,warehouse,owner,generation,refresh,revision]);
 const validation=useMemo<DispatchTableValidation>(()=>{
  for(const read of reads){
   const fact=facts[read.identity];
   if(!fact||!fact.current&&!fact.error)return {pending:true};
   if(fact.error)return {pending:false,error:"当前可发量读取失败，请刷新后再继续。"};
   const allowed=fact.value?.state==="ready"?number(fact.value.dispatch_allowed_units):undefined;
   if(allowed===undefined)return {pending:false,error:"当前可发量待核，核实后才能继续出货。"};
   const total=sources.filter(s=>s.sku_id===read.sku).reduce((sum,s)=>sum+(number(s.actual_units)??0n),0n);
   if(total>allowed)return {pending:false,error:`商品本批合计超过当前可发量，不足${units((total-allowed).toString())}件。`,field:`source-${sources.findIndex(source=>source.sku_id===read.sku)}-units`};
  }
  return {pending:false};
 },[reads,facts,sources]);
 useEffect(()=>validationChanged(validation),[validationChanged,validation]);
 const table=useRef<HTMLTableElement>(null);
 function nextQuantity(event:React.KeyboardEvent<HTMLInputElement>,index:number){
  if(event.key!=="Enter"&&event.key!=="ArrowDown"&&event.key!=="ArrowUp")return;
  event.preventDefault();const fields=table.current?.querySelectorAll<HTMLInputElement>("input[data-dispatch-quantity]");
  const next=fields?.[index+(event.key==="ArrowUp"||event.shiftKey?-1:1)];if(next){next.focus();next.select();}
 }
 return <section className={styles.workspace} aria-label="编辑本批出货商品">
  {reads.map(read=><AvailabilityRead key={read.identity} {...read} changed={changed}/>)}
  <header className={styles.context}><strong>{warehouseName||"来源仓待选"} → {destination||"目的地待填"}</strong><span>{date}</span><Button variant="quiet" disabled={locked||!reads.length} onClick={()=>setRevision(value=>value+1)}>刷新可发量</Button></header>
  <div className={styles.scroll} tabIndex={0} aria-label="出货商品表格滚动区"><table ref={table} className={styles.table} aria-label="本批商品出货表"><colgroup><col className={styles.productColumn}/><col className={styles.availableColumn}/><col className={styles.quantityColumn}/><col className={styles.actionColumn}/></colgroup><thead><tr><th>商品规格</th><th>当前可发</th><th>本次出货</th><th><span className={styles.srOnly}>操作</span></th></tr></thead><tbody>
   {sources.map((source,index)=>{
    const read=reads.find(item=>item.sku===source.sku_id);const fact=read?facts[read.identity]:undefined;
    const balance=fact?.current?fact.value:undefined;const allowed=balance?.state==="ready"?number(balance.dispatch_allowed_units):undefined;
    const total=sources.filter(item=>item.sku_id===source.sku_id).reduce((sum,item)=>sum+(number(item.actual_units)??0n),0n);
    const shortage=allowed!==undefined&&total>allowed?total-allowed:0n;
    const invalid=!!fieldErrors[`source-${index}-units`]||!!source.actual_units&&(!/^[1-9][0-9]{0,18}$/.test(source.actual_units)||number(source.actual_units)===undefined);
    const issue=shortage>0n?`不足${units(shortage.toString())}件`:invalid?"请输入有效件数":undefined;
    const label=options.find(option=>option.value===source.sku_id)?.label||source.sku_label||source.import_code||"请选择商品";
    return <Fragment key={source.id||index}><tr className={issue?styles.shortage:undefined}>
     <td><select aria-label={`出货SKU ${index+1}`} id={productionFieldId(`source-${index}-sku`)} title={label} value={source.sku_id} disabled={locked} onChange={event=>change(index,{sku_id:event.target.value,plan_id:null,allocations:[]})}><option value="">{source.import_code ? `${source.import_code}（待匹配）` : "请选择商品"}</option>{options.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select>{fieldErrors[`source-${index}-sku`]&&<small className={styles.error}>{fieldErrors[`source-${index}-sku`]}</small>}</td>
     <td className={allowed===undefined&&(source.sku_id||source.import_code)?styles.pending:issue?styles.error:undefined}><span>{!source.sku_id&&!source.import_code?"—":allowed===undefined?"待核":units(allowed.toString())}</span></td>
     <td><Input data-dispatch-quantity aria-label={`本次实际数量 ${index+1}`} id={productionFieldId(`source-${index}-units`)} aria-invalid={!!issue} aria-describedby={issue?`dispatch-issue-${index}`:undefined} disabled={locked} inputMode="numeric" maxLength={19} value={source.actual_units} onKeyDown={event=>nextQuantity(event,index)} onChange={event=>change(index,{actual_units:event.target.value})}/>{issue&&<small className={styles.error} id={`dispatch-issue-${index}`} role="status">{issue}</small>}</td>
     <td><div className={styles.rowActions}><Button variant="quiet" className={styles.expand} disabled={locked} aria-label={`查看商品${index+1}详情`} title={expanded===index?"收起商品明细":"展开商品明细"} aria-expanded={expanded===index} aria-controls={expanded===index?productionFieldId(`source-${index}-details`):undefined} icon={expanded===index?<ChevronUp size={16}/>:<ChevronDown size={16}/>} onClick={()=>setExpanded(value=>value===index?undefined:index)}/>{(sources.length>1||source.import_row!==undefined)&&<Button variant="quiet" className={styles.remove} disabled={locked} aria-label={`移除商品${index+1}`} title={`移除商品${index+1}`} icon={<Trash2 size={16}/>} onClick={()=>{setExpanded(value=>value===index?undefined:value!==undefined&&value>index?value-1:value);remove(index);}}/>}</div></td>
    </tr>{expanded===index&&<tr><td colSpan={4} id={productionFieldId(`source-${index}-details`)} className={styles.details}><strong>{label}</strong>{fact?.error&&<p role="alert">{fact.error}，请刷新可发量。</p>}
     <dl>{[["实际在库",balance?.on_hand_units],["自由可发",balance?.free_available_units],["自有预留",balance?.own_reserved_units],["冻结",balance?.held_units],["合格",balance?.qualified_units],["待检",balance?.pending_units],["次品",balance?.defective_units],["质量未核",balance?.unassessed_units]].map(([name,value])=><div key={name}><dt>{name}</dt><dd>{number(value)===undefined?"待核":units(value!)}</dd></div>)}</dl>
     {balance?.missing&&<p>{balance.missing}</p>}<details className={styles.planDisclosure} open={source.plan_id?true:undefined}><summary>出库安排（{source.plan_id?"已关联":"可选"}）</summary><p>已有提前登记的出货计划时才需要关联，确认发货后计入该计划的完成量。不关联也可以出货，计划不增加当前可发库存。</p><label className={styles.plan}>关联已有安排<select aria-label={`来源 ${index+1} 的预计出库安排（可选）`} disabled={locked} value={source.plan_id||""} onChange={event=>change(index,{plan_id:event.target.value||null})}><option value="">不关联预计出库安排</option>{plans.filter(plan=>plan.direction==="OUT"&&plan.sku_id===source.sku_id&&plan.warehouse_id===warehouse&&(BigInt(plan.remaining_units)>0n||plan.id===source.plan_id)).map(plan=><option key={plan.id} value={plan.id}>{plan.source_reference} · {plan.planned_on||"日期待安排"} · 剩余{plan.remaining_units}件</option>)}</select></label><p>同一商品按本批合计核对；待检、次品和质量未核不计入可发，确认发货时会再次校验。</p></details>
     <div className={styles.actions}><LinkButton variant="quiet" to="/production/stock">查看库存及占用</LinkButton>{source.plan_id&&<LinkButton variant="quiet" to={`/production/stock/plans#plan-${source.plan_id}`}>查看关联安排</LinkButton>}</div>
    </td></tr>}</Fragment>;
   })}
  </tbody></table></div>
  <Button className={styles.add} variant="secondary" disabled={locked} onClick={add}>添加商品</Button>
 </section>;
}
