import { useBusinessToday } from "./workbenchDate";
import { useCallback, useEffect, useState } from "react";
import { Button, Dialog, FormField, Input, Select, StatusMessage } from "../../design-system";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { useCommand } from "./useProductionApi";
import type { FbaScope, FbaState } from "./fbaTypes";
import type { Sku } from "./types";
import styles from "./FbaWorkspace.module.css";

export function FbaStocktake({ open, close, data, scope, catalog, saved, onGuard }: {
  open: boolean; close: () => void; data: FbaState; scope: FbaScope; catalog: Sku[];
  saved: () => void; onGuard: (value: { dirty: boolean; busy: boolean; unknown: boolean }) => void;
}) {
  const [selected, setSelected] = useState<{ sku: string; revision: string; quantity: string }>();
  const [quantity, setQuantity] = useState("");
  const today = useBusinessToday();
  const [date, setDate] = useState(today);
  const [reason, setReason] = useState("");
  const [discard, setDiscard] = useState(false);
  const reset = useCallback(() => { setSelected(undefined); setQuantity(""); setReason(""); setDiscard(false); }, []);
  const command = useCommand<FbaState>(() => { reset(); close(); saved(); }, saved);
  const { registerSensitivePurge } = useAuthzGeneration();
  useEffect(() => registerSensitivePurge(reset), [registerSensitivePurge, reset]);
  const dirty = open && (!!selected || !!reason);
  useEffect(() => { onGuard({ dirty, busy: command.busy, unknown: command.unknown }); }, [dirty, command.busy, command.unknown, onGuard]);
  const latest = data.stock.items.find(item => item.sku_id === selected?.sku && item.owner_id === scope.owner_id);
  const stale = !!selected && latest?.revision !== selected.revision;
  const locked = command.busy || command.unknown;
  const allowed = new Set(data.identities.filter(item => item.scope_id === scope.id).map(item => item.sku_id));
  const valid = /^(0|[1-9][0-9]{0,17})$/.test(quantity);
  const select = (sku: string) => {
    const stock = data.stock.items.find(item => item.sku_id === sku && item.owner_id === scope.owner_id);
    if (!sku || !stock?.revision || stock.qualified_units == null) { setSelected(undefined); setQuantity(""); return; }
    setSelected({ sku, revision: stock.revision, quantity: stock.qualified_units });
    setQuantity(stock.qualified_units);
  };
  const dismiss = () => { if (locked) return; if (dirty) setDiscard(true); else { reset(); close(); } };
  return <Dialog open={open} onOpenChange={value => { if (!value) dismiss(); }} dismissDisabled={locked} title="调整库存">
    {command.feedback}
    <div className={styles.workspace}>
      <FormField label="商品规格"><Select value={selected?.sku || ""} disabled={locked} onChange={event => select(event.target.value)}>
        <option value="">选择商品规格</option>
        {catalog.filter(sku => allowed.has(sku.sku_id) && sku.status === "active").map(sku => <option key={sku.sku_id} value={sku.sku_id}>{sku.code || sku.label}</option>)}
      </Select></FormField>
      {selected && <dl className={styles.onHandSummary}><dt>当前合格品数量</dt><dd>{selected.quantity}</dd></dl>}
      <FormField label="盘点后合格品数量"><Input inputMode="numeric" value={quantity} disabled={locked || !selected} onChange={event => setQuantity(event.target.value)} /></FormField>
      <FormField label="盘点日期"><Input type="date" value={date} disabled={locked} onChange={event => setDate(event.target.value)} /></FormField>
      <FormField label="调整原因"><Input value={reason} maxLength={2000} disabled={locked} onChange={event => setReason(event.target.value)} /></FormField>
      {stale && <StatusMessage kind="warning" title="库存已更新" action={<Button disabled={locked || !latest?.revision || latest.qualified_units == null} onClick={() => {
        if (selected && latest?.revision && latest.qualified_units != null) setSelected({ ...selected, revision: latest.revision, quantity: latest.qualified_units });
      }}>核对最新库存</Button>} />}
      <div className={styles.actions}><Button variant="secondary" disabled={locked} onClick={dismiss}>取消</Button><Button variant="primary" disabled={locked || stale || !selected || !valid || !reason.trim() || !date} onClick={() => {
        if (selected) command.submit("/api/production/fba/commands/stocktake", { scope_id: scope.id, expected_revision: scope.revision, business_date: date, reason: reason.trim(), lines: [{ sku_id: selected.sku, units: quantity, balance_revision: selected.revision }] });
      }}>确认调整</Button></div>
      {discard && <section role="alert"><strong>放弃未保存的调整？</strong><div className={styles.actions}><Button onClick={() => setDiscard(false)}>继续填写</Button><Button variant="secondary" onClick={() => { reset(); close(); }}>放弃调整</Button></div></section>}
    </div>
  </Dialog>;
}
