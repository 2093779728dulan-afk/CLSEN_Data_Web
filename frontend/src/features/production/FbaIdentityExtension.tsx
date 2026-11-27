import { Disclosure } from "../../design-system";
import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, LinkButton, StatusMessage, Table } from "../../design-system";
import { FbaFileUpload } from "./FbaFileUpload";
import { useCommand, useLoad } from "./useProductionApi";
import { useProductionLeave } from "./useProductionLeave";
import type { FbaCatalogProducts, FbaIdentity, FbaMapping, FbaScope, FbaState } from "./fbaTypes";
import type { OverviewGuard } from "./stockOverview";
import type { Sku } from "./types";
import styles from "./FbaWorkspace.module.css";

export function FbaIdentityExtension({ scope, identities, catalog, canWrite, saved, embedded = false, skuIds, onGuardChange }: {
  scope: FbaScope; identities: FbaIdentity[]; catalog: Sku[]; canWrite: boolean; saved: (state: FbaState) => void;
  embedded?: boolean; skuIds?: string[]; onGuardChange?: (guard: OverviewGuard) => void;
}) {
  const [params] = useSearchParams();
  const [rows, setRows] = useState<FbaMapping[]>([]);
  const [source, setSource] = useState<{ source_id: string; report_source_scope_id: string }>();
  const [confirmed, setConfirmed] = useState(false);
  const [connected, setConnected] = useState(0);
  const [sourceRows, setSourceRows] = useState(0);
  const [fileGuard, setFileGuard] = useState<OverviewGuard>({ dirty: false, busy: false, unknown: false });
  const command = useCommand<FbaState>(result => {
    setConnected(rows.length || ready.length); setRows([]); setSource(undefined); setConfirmed(false); saved(result);
  });
  const dirty = !!rows.length || fileGuard.dirty;
  const busy = command.busy || fileGuard.busy;
  const unknown = command.unknown || fileGuard.unknown;
  useEffect(() => { onGuardChange?.({ dirty, busy, unknown }); }, [dirty, busy, unknown, onGuardChange]);
  useEffect(() => () => onGuardChange?.({ dirty: false, busy: false, unknown: false }), [onGuardChange]);
  const locked = !canWrite || command.busy || command.unknown || fileGuard.busy || fileGuard.unknown;
  const existing = new Set(identities.map(identity => identity.sku_id));
  const products = useLoad<FbaCatalogProducts>(`/api/production/fba/catalog-products?report_source_scope_id=${scope.report_source_scope_id}`, 0, canWrite && !embedded);
  const ready = (products.value?.identities || []).filter(row=>!existing.has(row.sku_id) && row.store===scope.store_evidence && (!skuIds || skuIds.includes(row.sku_id)));
  const invalid = rows.some(row => !row.sku_id || existing.has(row.sku_id) || row.store !== scope.store_evidence || skuIds && !skuIds.includes(row.sku_id));
  const options = catalog.filter(sku => !skuIds || skuIds.includes(sku.sku_id));
  const returnTo = params.get("return_to");
  const returnUrl = returnTo?.startsWith("/production/") ? returnTo : `/production/warehouses/${scope.warehouse_id}?owner=${scope.owner_id}&tab=stock&fba_view=tracking`;
  if (!scope.simulated) return <StatusMessage kind="warning" title="请先核对新规格的库存基线">当前接入入口适用于已确认零期初的体验账簿。</StatusMessage>;
  const content = <section className={styles.panel} aria-label="核对FBA商品资料" data-embedded={embedded || undefined}>
    <h2>{embedded ? "核对本批新商品" : "添加FBA商品"}</h2>
    <p>使用{scope.store_evidence}的商品资料。</p>
    {connected > 0 && <StatusMessage kind="success" title={`已启用 ${connected} 个规格`}>可返回原接收表继续核对数量。</StatusMessage>}
    {command.feedback}
    {canWrite && !!ready.length && !source && <div className={styles.productSetup}><strong>已自动带入 {ready.length} 个商品规格</strong><Button variant="primary" disabled={locked||!products.current} onClick={()=>command.submit("/api/production/fba/commands/extend-identities",{scope_id:scope.id,expected_revision:scope.revision,identity_mode:"catalog",catalog_version:products.value!.catalog_version,identities:ready,explicit_zero_opening:true,reason:"复用已审核商品资料，明确确认新接入规格在原截止日库存为零"})}>启用已带入商品</Button></div>}
    <Disclosure open={!ready.length || !!source}><summary>补充商品资料</summary>
    {canWrite && <FbaFileUpload identity path={`/api/production/fba/mapping-preview?report_source_scope_id=${scope.report_source_scope_id}`} label="FBA商品资料CSV" disabled={locked} onGuardChange={setFileGuard} saved={result => {
      if ("identities" in result) {
        setSourceRows(result.identities.length);
        setRows(result.identities.filter(row => !skuIds || !row.sku_id || skuIds.includes(row.sku_id))); setSource({ source_id: result.source_id, report_source_scope_id: result.report_source_scope_id }); setConfirmed(false); setConnected(0);
      }
    }} />}
    {source && skuIds && <p>原资料{sourceRows}行，本批核对{rows.length}行。</p>}
    {source && !rows.length && <StatusMessage kind="warning" title="未找到本批新商品">请核对文件中的卖家SKU及商品主档对应关系。</StatusMessage>}
    {!!rows.length && <Table aria-label="FBA商品资料核对">
      <thead><tr><th>Seller SKU</th><th>对应商品规格</th><th>ASIN</th><th>FNSKU</th></tr></thead>
      <tbody>{rows.map((row, index) => <tr key={`${index}:${row.seller_sku}`}>
        <th scope="row">{row.seller_sku}</th>
        <td><select aria-label={`${row.seller_sku} 对应商品规格`} value={row.sku_id} disabled={locked} onChange={event => { setRows(current => current.map((item, number) => number === index ? { ...item, sku_id: event.target.value } : item)); setConfirmed(false); }}>
          <option value="">选择已建档规格</option>{options.map(sku => <option key={sku.sku_id} value={sku.sku_id}>{sku.code || sku.label}</option>)}
        </select>{existing.has(row.sku_id) && <p className={styles.error}>本仓已有此规格</p>}{row.store !== scope.store_evidence && <p className={styles.error}>来源店铺与本仓不一致</p>}</td>
        <td>{row.asin}</td><td>{row.fnsku}</td>
      </tr>)}</tbody>
    </Table>}
    {!!rows.length && <label className={styles.check}><input type="checkbox" checked={confirmed} disabled={locked || fileGuard.dirty} onChange={event => setConfirmed(event.target.checked)} />已核对平台资料，确认这些新接入规格在{scope.cutoff_on}的期初库存为零</label>}
    <div className={styles.actions}>
      {!embedded && <LinkButton variant="quiet" to={returnUrl}>返回验收或商品管理</LinkButton>}
      {canWrite && <Button disabled={locked || fileGuard.dirty || !source || !rows.length || invalid || !confirmed} onClick={() => command.submit("/api/production/fba/commands/extend-identities", {
        scope_id: scope.id, expected_revision: scope.revision, identities: rows, identity_source: source,
        identities_confirmed: confirmed, explicit_zero_opening: confirmed, reason: "核对对应商品规格及本仓平台资料，接入当前FBA账簿",
      })}>确认并启用商品</Button>}
    </div></Disclosure>
  </section>;
  return embedded ? content : <IdentityLeaveGuard dirty={dirty} busy={busy} unknown={unknown}>{content}</IdentityLeaveGuard>;
}

function IdentityLeaveGuard({ dirty, busy, unknown, children }: OverviewGuard & { children: ReactNode }) {
  const leave = useProductionLeave(dirty, busy, unknown);
  return <>{leave.prompt}{children}</>;
}
