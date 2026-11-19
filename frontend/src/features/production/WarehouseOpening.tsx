import { ProductionConfirmDialog } from "./ProductionConfirmDialog";
import { useEffect, useRef, useState } from 'react';
import { Button, Dialog, FormField, Input, LinkButton, StatusMessage, Table } from '../../design-system';
import { writeApi } from '../../api/client';
import { useCommand, useLoad } from './useProductionApi';
import { useProductionLeave } from './useProductionLeave';
import type { Sku } from './types';
import styles from './Production.module.css';

type Guard = { dirty: boolean; busy: boolean; unknown: boolean };
export function WarehouseOpeningDialog({ warehouseId, name, saved, close }: { warehouseId: string; name: string; saved: () => void; close: () => void }) {
  const [guard,setGuard]=useState<Guard>({dirty:false,busy:false,unknown:false});
  const [closing,setClosing]=useState(false);
  const leave=useProductionLeave(guard.dirty,guard.busy,guard.unknown,[]);
  return <Dialog open title={`${name} · 期初库存`} size="large" dismissDisabled={guard.busy||guard.unknown} closeOnOutsideClick={false} onOpenChange={open=>{if(!open){if(guard.dirty)setClosing(true);else close();}}}>
    <ProductionConfirmDialog open={closing} onOpenChange={setClosing} title="还有未保存的期初内容" description="继续填写，或放弃尚未保存的期初输入。"><Button onClick={()=>setClosing(false)}>继续填写</Button><Button variant="danger" onClick={()=>{leave.allowLeave();close();}}>放弃并关闭</Button></ProductionConfirmDialog>
    <WarehouseOpening warehouseId={warehouseId} onGuardChange={setGuard} saved={()=>{leave.allowLeave();saved();}}/>{leave.prompt}
  </Dialog>;
}
export function WarehouseOpening({warehouseId,saved,onGuardChange}:{warehouseId:string;saved:()=>void;onGuardChange?:(guard:Guard)=>void}) {
 const catalog=useLoad<{items:Sku[]}>('/api/production/skus?contract_version=2');
 const policy=useLoad<{opening_enabled?:boolean;scopes:{warehouse_id:string}[]}>('/api/production/inventory/availability');
 const [cutoff,setCutoff]=useState('');const [reason,setReason]=useState('');const [source,setSource]=useState(`FICTIONAL-OPENING-${warehouseId}`);
 const [uploaded,setUploaded]=useState<{source_id:string;filename:string}>();
 const [amounts,setAmounts]=useState<Record<string,string>>({});const [preview,setPreview]=useState(false);const [dirty,setDirty]=useState(false);const [reading,setReading]=useState(false);const [error,setError]=useState('');const fileRef=useRef<HTMLInputElement>(null);
 const command=useCommand<Record<string,unknown>>(result=>{if(result.revision){setDirty(false);saved();}else setPreview(true);});
 useEffect(()=>onGuardChange?.({dirty,busy:command.busy||reading,unknown:command.unknown}),[dirty,command.busy,command.unknown,reading,onGuardChange]);
 const qualities=[['QUALIFIED','合格'],['PENDING','待检'],['DEFECTIVE','次品']] as const;
 const locked=command.busy||command.unknown||reading;
 async function importFile(file:File){
  if(!/\.xlsx$/i.test(file.name)||file.size===0||file.size>2*1024*1024){setError('请选择2MiB以内的非空XLSX期初表。');return;}
  setReading(true);setError('');
  try{const result=await writeApi<{source_id:string;filename:string;lines:{sku_id:string;quality:string;units:string}[]}>(`/api/production/inventory/opening-table/parse?filename=${encodeURIComponent(file.name)}`,{idempotent:false,rawBody:file,headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}});setUploaded({source_id:result.source_id,filename:result.filename});setAmounts(Object.fromEntries(result.lines.map(line=>[`${line.sku_id}:${line.quality}`,line.units])));setDirty(true);setPreview(false);}
  catch(e){setError(e instanceof Error?e.message:'期初表读取失败。');}finally{setReading(false);}
 }
 if(catalog.error||policy.error)return <StatusMessage kind="danger" title="期初资料读取失败">{catalog.error||policy.error}</StatusMessage>;
 if(!catalog.value||!policy.value)return <p role="status">正在读取期初资料…</p>;
 if(policy.value.opening_enabled===false)return <StatusMessage kind="warning" title="当前环境未开放期初登记"/>;
 if(policy.value.scopes.some(scope=>scope.warehouse_id===warehouseId))return <StatusMessage kind="info" title="本仓已建账">后续实际到货请办理入库；不能重复导入期初。</StatusMessage>;
 return <form onChangeCapture={()=>{setDirty(true);setPreview(false);}} onSubmit={event=>{event.preventDefault();const chosen=catalog.value!.items.filter(sku=>qualities.some(([quality])=>amounts[`${sku.sku_id}:${quality}`]!==undefined&&amounts[`${sku.sku_id}:${quality}`]!==''));if(!chosen.length||chosen.some(sku=>qualities.some(([quality])=>!/^(0|[1-9][0-9]*)$/.test(amounts[`${sku.sku_id}:${quality}`]||'')))){setError('请明确填写所选SKU的三类数量；没有填0，未知不能留作0。');return;}setError('');command.submit(`/api/production/inventory/openings/${preview?'confirm':'preview'}`,{warehouse_id:warehouseId,owner_id:'1',cutoff_on:cutoff,source_reference:source,reason,...(uploaded?{opening_source:uploaded}:{}),lines:chosen.flatMap(sku=>qualities.map(([quality])=>({sku_id:sku.sku_id,quality,units:amounts[`${sku.sku_id}:${quality}`]})))});}}>
 <fieldset disabled={locked}><div className={styles.filters}><FormField label="期初截止日期" required><Input type="date" required value={cutoff} onChange={e=>setCutoff(e.target.value)}/></FormField><FormField label="来源编号" required><Input required value={source} onChange={e=>setSource(e.target.value)}/></FormField><FormField label="期初依据" required><Input required value={reason} onChange={e=>setReason(e.target.value)}/></FormField></div>
 <div className={styles.actions}><LinkButton to="/api/production/inventory/opening-table/template" reloadDocument download>下载期初模板</LinkButton><input ref={fileRef} type="file" accept=".xlsx" aria-label="导入期初库存表" onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void importFile(file);}}/><Button onClick={()=>{setAmounts(Object.fromEntries(catalog.value!.items.flatMap(sku=>qualities.map(([quality])=>[`${sku.sku_id}:${quality}`,'0']))));setDirty(true);setPreview(false);}}>本仓全部规格设为零期初</Button></div>
 {uploaded&&<LinkButton to={`/api/production/inventory/opening-table/source/${uploaded.source_id}`} reloadDocument download>查看导入原表：{uploaded.filename}</LinkButton>}
 {error&&<StatusMessage kind="danger" title="期初表未完成">{error}</StatusMessage>}
 <Table aria-label="期初库存明细"><thead><tr><th>SKU</th>{qualities.map(([,name])=><th key={name}>{name}</th>)}</tr></thead><tbody>{catalog.value.items.map(sku=><tr key={sku.sku_id}><th scope="row">{sku.code||sku.label}</th>{qualities.map(([quality,name])=><td key={quality}><Input aria-label={`${sku.code||sku.label}${name}期初`} inputMode="numeric" value={amounts[`${sku.sku_id}:${quality}`]??''} onChange={e=>setAmounts(current=>({...current,[`${sku.sku_id}:${quality}`]:e.target.value}))}/></td>)}</tr>)}</tbody></Table>
 {preview&&<StatusMessage kind="info" title="预览通过，尚未建账">核对后确认期初库存。</StatusMessage>}<Button type="submit" variant="primary">{preview?'确认期初库存':'预览期初库存'}</Button>{command.feedback}</fieldset></form>;
}
