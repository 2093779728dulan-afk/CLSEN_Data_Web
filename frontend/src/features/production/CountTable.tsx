import { useEffect, useRef, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { writeApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, Input, LinkButton, StatusMessage, Table } from "../../design-system";
import type { OperationLine } from "./StockOperationWizard";
import type { QualityBalance } from "./StockMovementFields";
import type { Sku } from "./types";
import { units } from "./types";
import type { TableBaseline } from "./TableImportReview";
import styles from "./OrderWorkbench.module.css";

const countQualities: Record<string, string> = { QUALIFIED: "合格", PENDING: "待检", DEFECTIVE: "次品" };
export type CountImport = { filename: string; rows: OperationLine[]; issues: { row: number; message: string }[]; table_baseline?: TableBaseline };
export function CountTableImport({ warehouse, owner, locked, onBusy, onApply }: { warehouse: string; owner: string; locked: boolean; onBusy: (value: boolean) => void; onApply: (result: CountImport) => void }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const { generation, registerSensitivePurge } = useAuthzGeneration();
  const current = useRef({ warehouse, owner, generation }); current.current = { warehouse, owner, generation };
  const active = useRef(true);
  useEffect(() => {active.current=true;return()=>{active.current=false;};},[]);
  useEffect(() => registerSensitivePurge(()=>setError("")),[registerSensitivePurge]);
  const query = new URLSearchParams({ warehouse_id:warehouse,owner_id:owner });
  async function upload(file: File) {
    if (locked || busy) return;
    if (!file.name.toLowerCase().endsWith(".xlsx") || !file.size || file.size>2_000_000) {setError("请选择不超过2MB且非空的盘点XLSX文件。");return;}
    const start = current.current;
    const same = () => active.current && JSON.stringify(current.current)===JSON.stringify(start);
    setBusy(true);onBusy(true);setError("");
    try {
      const result = await writeApi<CountImport>(`/api/production/inventory/count-table/preview?${query}&filename=${encodeURIComponent(file.name)}`, { rawBody:file,headers:{"Content-Type":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},idempotent:false });
      if (!same()) return;
      if (result.issues.length || !result.rows.length) setError(result.issues.map(issue=>`第${issue.row}行 ${issue.message}`).join("；") || "没有已填写的实盘总数。");
      else onApply(result);
    } catch(e) {if(same())setError(e instanceof Error?e.message:"盘点表读取失败。");}
    finally {if(active.current){setBusy(false);onBusy(false);}}
  }
  return <section className={styles.inlineImport} aria-label="盘点表格导入"><div className={styles.importToolbar}><Input type="file" aria-label="盘点XLSX文件（不超过2MB）" accept=".xlsx" disabled={locked || busy || !warehouse} onChange={event=>{const file=event.target.files?.[0];if(file)void upload(file);event.target.value="";}}/><LinkButton variant="quiet" reloadDocument download to={`/api/production/inventory/count-table/template?${query}`}>下载盘点模板</LinkButton></div>{busy && <p role="status">正在读取盘点表…</p>}{error && <StatusMessage kind="danger" title="导入未完成，原填写内容已保留">{error}</StatusMessage>}</section>;
}

export function CountTable({ lines, skus, balanceFor, change, add, remove, errorFor }: {
  lines: OperationLine[]; skus: Sku[]; balanceFor: (line: OperationLine) => QualityBalance | undefined;
  change: (index:number,key:keyof OperationLine,value:string) => void; add: () => void; remove: (index:number) => void; errorFor: (line: OperationLine) => string | undefined;
}) {
  return <><Table aria-label="盘点商品明细"><thead><tr><th>款号 / 规格</th><th>货品状态</th><th>账面数</th><th>实盘总数</th><th>差额</th><th>操作</th></tr></thead><tbody>{lines.map((line,index)=>{
    const balance=balanceFor(line);
    const book=line.quality==="QUALIFIED"?balance?.qualified_units:line.quality==="PENDING"?balance?.pending_units:line.quality==="DEFECTIVE"?balance?.defective_units:undefined;
    const delta=book!=null && /^(0|[1-9][0-9]*)$/.test(line.units)?BigInt(line.units)-BigInt(book):undefined;
    const error=errorFor(line);
    return <tr key={index}><td><select required aria-label={`盘点商品${index+1}`} value={line.sku_id} onChange={event=>change(index,"sku_id",event.target.value)}><option value="">选择款号 / 颜色 / 尺码</option>{skus.filter(sku=>sku.status==="active" || sku.sku_id===line.sku_id).map(sku=><option key={sku.sku_id} value={sku.sku_id}>{sku.label}</option>)}</select></td><td><select required aria-label={`盘点商品${index+1}状态`} value={line.quality} onChange={event=>change(index,"quality",event.target.value)}><option value="">选择状态</option>{Object.entries(countQualities).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></td><td>{book==null?"待核":units(book)}</td><td><Input required aria-label={`盘点商品${index+1}实盘总数`} inputMode="numeric" pattern="0|[1-9][0-9]{0,17}" aria-invalid={!!error} value={line.units} onChange={event=>change(index,"units",event.target.value)}/>{error && <span role="alert" className={styles.danger}>{error}</span>}</td><td className={delta!=null && delta<0n?styles.danger:undefined}>{delta==null?"待核":`${delta>0n?"+":""}${units(delta.toString())}`}</td><td><Button variant="quiet" icon={<Trash2/>} aria-label={`移除盘点商品${index+1}`} disabled={lines.length===1} onClick={()=>remove(index)}/></td></tr>;
  })}</tbody></Table><Button variant="secondary" icon={<Plus/>} disabled={lines.length>=500} onClick={add}>增加商品</Button></>;
}
