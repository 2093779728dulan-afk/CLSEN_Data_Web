import { useRef, useState } from "react";
import { Button, FormField, Input, LinkButton, StatusMessage, Table } from "../../design-system";
import { FbaFileUpload } from "./FbaFileUpload";
import { useCommand, useLoad } from "./useProductionApi";
import type { DirectoryRecord } from "./directoryTypes";
import type { Sku } from "./types";
import type { FbaCatalogProducts, FbaMapping, FbaState } from "./fbaTypes";
import styles from "./FbaWorkspace.module.css";

export function FbaOpening({record,catalog,sourceId,sourceName,saved}:{record:DirectoryRecord;catalog:Sku[];sourceId:number|null;sourceName:string|null;saved:()=>void}) {
  const [refresh, setRefresh] = useState(0);
  const products = useLoad<FbaCatalogProducts>(`/api/production/fba/catalog-products?report_source_scope_id=${sourceId}`, refresh, !!sourceId);
  const [identitySource, setIdentitySource] = useState<{source_id:string;report_source_scope_id:string}>();
  const [fileRows, setFileRows] = useState<FbaMapping[]>([]);
  const [uploadRevision, setUploadRevision] = useState(0);
  const [fileGuard, setFileGuard] = useState({dirty:false,busy:false,unknown:false});
  const [cutoff, setCutoff] = useState("");
  const [owner, setOwner] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [reason, setReason] = useState("");
  const [zero, setZero] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [validated, setValidated] = useState(false);
  const opening = useRef<HTMLElement>(null);
  const command = useCommand<FbaState>(saved);
  const disabled = command.busy || command.unknown || fileGuard.busy || fileGuard.unknown;
  const identities = identitySource ? fileRows : products.value?.identities || [];
  const store = identitySource ? fileRows[0]?.store || "" : products.value?.store || sourceName || "";
  const issues: Record<string,string> = {};
  if(!cutoff) issues.cutoff = "请选择期初截止日期";
  if(!/^[1-9][0-9]*$/.test(owner)) issues.owner = "请填写有效的货主编号";
  if(!ownerName.trim()) issues.ownerName = "请填写货主名称";
  if(!reason.trim()) issues.reason = "请填写期初依据";
  if(!sourceId) issues.identity = "请先在商品建档中确认店铺";
  else if(fileGuard.dirty) issues.identity = "请先读取当前选择的商品资料";
  else if(!identitySource && !products.current) issues.identity = products.error || "正在读取已审核商品资料，请稍候";
  else if(!identities.length) issues.identity = "请先补齐商品资料，再启用FBA库存";
  else if(identities.some(row => !row.sku_id)) issues.identity = "请完成文件中商品的对应关系";
  else if(store !== sourceName) issues.identity = "文件中的店铺与本仓已确认店铺不一致";
  if(!zero) issues.zero = "请确认截止日期的模拟库存为零";
  if(identitySource && !confirmed) issues.confirmed = "请确认补充文件中的商品对应关系";
  const error = (field:string) => validated ? issues[field] : undefined;
  function submit() {
    setValidated(true);
    const field = Object.keys(issues)[0];
    if(field) {
      const target = opening.current?.querySelector<HTMLElement>(`[data-opening-field="${field}"]`);
      target?.scrollIntoView?.({block:"center",behavior:window.matchMedia?.("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});
      target?.focus({preventScroll:true});
      if(target) { target.classList.remove(styles.attention!); void target.offsetWidth; target.classList.add(styles.attention!); }
      return;
    }
    command.submit("/api/production/fba/commands/scopes", {
      warehouse_id:record.id, owner_id:owner, owner_name:ownerName,
      seller_account:record.seller_account, marketplace:record.marketplace,
      report_source_scope_id:String(sourceId), store_evidence:store,
      cutoff_on:cutoff, reason, explicit_zero_opening:zero, simulated:true,
      identities, ...(identitySource ? {identity_source:identitySource,identities_confirmed:confirmed} : {identity_mode:"catalog",catalog_version:products.value!.catalog_version}),
    });
  }
  return <section ref={opening} className={`${styles.panel} ${styles.opening}`} aria-label="启用FBA库存">
    <header className={styles.rowTitle}><h2>启用FBA库存</h2><span>{sourceName || "店铺待确认"} · 美国站</span></header>
    {command.feedback}
    <fieldset className={styles.fields} disabled={disabled}>
      <FormField label="期初截止日期" required error={error("cutoff")}><Input data-opening-field="cutoff" type="date" value={cutoff} onChange={event=>setCutoff(event.target.value)}/></FormField>
      <FormField label="货主编号" required error={error("owner")}><Input data-opening-field="owner" inputMode="numeric" value={owner} onChange={event=>setOwner(event.target.value)}/></FormField>
      <FormField label="货主名称" required error={error("ownerName")}><Input data-opening-field="ownerName" value={ownerName} onChange={event=>setOwnerName(event.target.value)}/></FormField>
      <FormField label="期初依据" required error={error("reason")}><Input data-opening-field="reason" value={reason} onChange={event=>setReason(event.target.value)}/></FormField>
    </fieldset>
    {!sourceId && <StatusMessage kind="warning" title="请先在商品建档中确认店铺"/>}
    {sourceId && !identitySource && (products.error ? <StatusMessage kind="danger" title="商品资料读取未完成" action={<Button variant="secondary" onClick={()=>setRefresh(value=>value+1)}>重新读取</Button>}>{products.error}</StatusMessage> : !products.value ? <p role="status">正在读取已审核商品资料…</p> : <div className={styles.productSetup}>
      <strong>已自动带入 {identities.length} 个商品规格</strong>
      {!!products.value.issues.length && <details><summary>{products.value.issues.length} 个规格待补充，可在首次到货时处理</summary><ul>{products.value.issues.map(issue=><li key={issue.sku_id}>{issue.label} · {issue.message}</li>)}</ul></details>}
      {!!identities.length && <details><summary>查看商品资料</summary><div className={styles.scroll}><Table aria-label="自动带入的商品资料"><thead><tr><th>商品规格</th><th>ASIN</th><th>FNSKU</th></tr></thead><tbody>{identities.map(row=><tr key={row.sku_id}><td>{row.seller_sku}</td><td>{row.asin}</td><td>{row.fnsku}</td></tr>)}</tbody></Table></div></details>}
    </div>)}
    <details className={styles.productSetup}>
      <summary>补充商品资料</summary>
      <FbaFileUpload key={uploadRevision} identity path={`/api/production/fba/mapping-preview?report_source_scope_id=${sourceId||""}`} label="FBA商品资料CSV" disabled={disabled||!sourceId} onGuardChange={setFileGuard} saved={result=>{if("identities" in result){setFileRows(result.identities);setIdentitySource({source_id:result.source_id,report_source_scope_id:result.report_source_scope_id});setConfirmed(false);}}}/>
      {(identitySource || fileGuard.dirty) && <Button variant="quiet" disabled={disabled} onClick={()=>{setIdentitySource(undefined);setFileRows([]);setConfirmed(false);setFileGuard({dirty:false,busy:false,unknown:false});setUploadRevision(value=>value+1);}}>使用已审核商品资料</Button>}
      {identitySource && <>
        <div className={styles.actions}><span>已读取 {fileRows.length} 个规格</span><LinkButton to={`/api/production/fba/mapping-source/${identitySource.source_id}?report_source_scope_id=${identitySource.report_source_scope_id}`} reloadDocument download>查看身份原表</LinkButton></div>
        <div className={styles.scroll}><Table aria-label="补充商品对应关系"><thead><tr><th>Seller SKU</th><th>对应商品规格</th></tr></thead><tbody>{fileRows.map((row,index)=><tr key={index}><td>{row.seller_sku}</td><td><select aria-label={`${row.seller_sku} 对应商品规格`} disabled={disabled} value={row.sku_id} onChange={event=>{setFileRows(previous=>previous.map((item,n)=>n===index?{...item,sku_id:event.target.value}:item));setConfirmed(false);}}><option value="">请选择商品规格</option>{catalog.map(sku=><option key={sku.sku_id} value={sku.sku_id}>{sku.code || sku.label}</option>)}</select></td></tr>)}</tbody></Table></div>
        <label className={styles.check}><input data-opening-field="confirmed" type="checkbox" checked={confirmed} disabled={disabled} onChange={event=>setConfirmed(event.target.checked)}/>已核对补充文件中的商品对应关系</label>
      </>}
    </details>
    {error("identity") && <p data-opening-field="identity" tabIndex={-1} role="alert" className={styles.fieldError}>{error("identity")}</p>}
    <label className={styles.check}><input data-opening-field="zero" type="checkbox" checked={zero} disabled={disabled} onChange={event=>setZero(event.target.checked)}/>确认截止日期各商品库存为0（本次模拟）</label>
    {(error("zero") || error("confirmed")) && <p role="alert" className={styles.fieldError}>{error("zero") || error("confirmed")}</p>}
    <div><Button variant="primary" disabled={disabled} onClick={submit}>确认零期初并启用</Button></div>
  </section>;
}
