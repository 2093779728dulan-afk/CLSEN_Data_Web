import { useEffect, useRef, useState } from "react";
import { ApiRequestError, createOperationKey, requestApi, writeApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, Dialog, FormField, Input, StatusMessage, Table } from "../../design-system";
import type { InventorySnapshot, StockRow } from "./InventorySnapshotPage";
import { inventorySizes } from "./inventoryPreparation";
import { units } from "./types";
import { useProductionLeave } from "./useProductionLeave";
import styles from "./Production.module.css";

export type Review = { review_id: string; source_identity: string; revision: number; can_manage: boolean; writes_enabled?: boolean; source_view_available?: boolean; source: InventorySnapshot; effective: InventorySnapshot & { cutoff_note: string }; overrides: { rows?: Record<string, Record<string, string | null>> } };
export type ProductReference = { sku_id: string; catalog_version_id: string; catalog_publication_revision: string };
export type ProductLink = ProductReference & { style_id: string; style_code: string; standard_color: string; standard_size: string; code: string | null; cell: string };
export type Change = { type: "set_location"; source_key: string; value: string } | { type: "set_stocktake_date"; value: string | null } | { type: "set_cutoff_note"; value: string } | { type: "set_size_quantity"; source_key: string; size: string; value: string | null } | { type: "set_reviewed_total"; source_key: string; value: string | null } | { type: "set_product"; source_key: string; size: string; value: ProductReference | null } | { type: "restore_source_field"; source_key?: string; field: string };
type Preview = { preview_hash: string; before: Record<string, string | number>; after: Record<string, string | number>; stocktaken_on: string | null; cutoff_note: string };
type Command = { source_identity: string; expected_revision: number; changes: Change[]; reason: string; preview_hash: string };
type Receipt = { saved_revision: number; operation_id: string; replayed: boolean };
export type Edit = { mode: "location" | "date" | "quantity" | "product"; rows: StockRow[]; product?: { size: string; value: ProductReference | null; label: string }; returnFocusTarget?: HTMLButtonElement | null };
const message = (error: unknown) => error instanceof Error && /[\u3400-\u9fff]/.test(error.message) ? error.message : "核对操作未完成，请检查连接；保存结果不明时先查询原操作。";

export function InventoryReviewPreview({ preview }: { preview: Preview }) {
  return <section aria-label="保存影响预览"><h3>影响预览</h3><Table><thead><tr><th>项目</th><th>之前</th><th>之后</th></tr></thead><tbody>{[["本仓核对数量", "warehouse_1_units"], ["本仓款数", "product_count"], ["款色数", "color_count"], ["仓库待核行", "warehouse_pending"], ["尺码待核格", "unknown_cells"], ["合计未齐行", "incomplete_total_rows"]].map(([label, key]) => <tr key={key}><th>{label}</th><td>{preview.before[key!]}</td><td>{preview.after[key!]}</td></tr>)}</tbody></Table><p>盘点日：{preview.stocktaken_on || "仍待确认"} · 截止：{preview.cutoff_note || "仍待确认"}。商品对应按尺码单独保存，过账继续关闭。</p></section>;
}

export function InventoryReviewNotice({ error, operationId, saved }: { error?: string; operationId?: string; saved?: number }) {
  return <>{error && <StatusMessage kind="danger" title="请核对操作结果"><p id="inventory-review-error">{error}</p></StatusMessage>}{saved !== undefined && <StatusMessage kind="success" title={`已保存核对修订 ${saved}`}>展示会读取当前最新版本；历史保留此操作回执。</StatusMessage>}{operationId && <StatusMessage kind="warning" title="保存结果待确认">操作ID：{operationId}。输入已锁定；先查询原操作，未查到也只重试同一操作。</StatusMessage>}</>;
}

export function InventoryReviewDialog({ review, edit, onClose, onReload, onForbidden }: { review: Review; edit: Edit; onClose: () => void; onReload: () => Promise<Review>; onForbidden: () => void }) {
  const [basis, setBasis] = useState(review);
  const [reason, setReason] = useState(edit.mode === "product" ? "核对库存来源与商品规格的对应关系" : "");
  const [location, setLocation] = useState("");
  const [stockDate, setStockDate] = useState(review.effective.stocktaken_on || "");
  const [cutoff, setCutoff] = useState(review.effective.cutoff_note || "");
  const [quantities, setQuantities] = useState<Record<string, string>>(() => Object.fromEntries(edit.rows.flatMap(row => [...inventorySizes.map(size => [row.source_key + "|" + size, row.quantities[size]?.state === "LITERAL" ? row.quantities[size]?.units || "0" : ""]), [row.source_key + "|total", row.reviewed_total !== undefined ? row.reviewed_total || "" : row.source_total.state === "LITERAL" ? row.source_total.units || "" : ""]])) as Record<string, string>);
  const [restores, setRestores] = useState<Change[]>([]);
  const [preview, setPreview] = useState<Preview>();
  const [pending, setPending] = useState<{ id: string; body: Command }>();
  const [error, setError] = useState<string>();
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<number>();
  const [dirty, setDirty] = useState(false);
  const leave = useProductionLeave(dirty, busy, !!pending);
  const returnFocusTarget = useRef(edit.returnFocusTarget || null);
  const alive = useRef(true);
  const { registerSensitivePurge } = useAuthzGeneration();
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => registerSensitivePurge(() => { alive.current = false; setPending(undefined); setPreview(undefined); setQuantities({}); setReason(""); onClose(); }), [registerSensitivePurge, onClose]);
  useEffect(() => { const leave = (event: BeforeUnloadEvent) => { if (dirty || pending) event.preventDefault(); }; window.addEventListener("beforeunload", leave); return () => window.removeEventListener("beforeunload", leave); }, [dirty, pending]);
  function changed() { setDirty(true); setPreview(undefined); setError(undefined); }
  function close() { if (!busy && (!dirty && !pending || window.confirm(pending ? "保存结果尚未确认，离开后请从历史核对。仍要离开吗？" : "放弃未保存的核对输入吗？"))) onClose(); }
  function changes(): Change[] {
    if (edit.mode === "product" && edit.product) return [{ type: "set_product", source_key: edit.rows[0]!.source_key, size: edit.product.size, value: edit.product.value }];
    if (restores.length) return restores;
    if (edit.mode === "location") {
      if (!location) throw new Error("请选择仓库归属，系统不会默认确认。");
      return edit.rows.map(row => ({ type: "set_location", source_key: row.source_key, value: location }));
    }
    if (edit.mode === "date") return [{ type: "set_stocktake_date", value: stockDate || null }, { type: "set_cutoff_note", value: cutoff }];
    const result: Change[] = [];
    for (const row of edit.rows) {
      for (const size of inventorySizes) {
        const value = quantities[row.source_key + "|" + size] || "";
        if (value && !/^(0|[1-9][0-9]{0,17})$/.test(value)) throw new Error(row.source_key + " " + size + "请输入18位以内非负整数，留空表示未知。");
        const original = row.quantities[size]?.state === "LITERAL" ? row.quantities[size]?.units : null;
        if ((value || null) !== original) result.push({ type: "set_size_quantity", source_key: row.source_key, size, value: value || null });
      }
      const total = quantities[row.source_key + "|total"] || "";
      if (total && !/^(0|[1-9][0-9]{0,17})$/.test(total)) throw new Error("合计请输入18位以内非负整数，留空表示未知。");
      const originalTotal = row.reviewed_total !== undefined ? row.reviewed_total : row.source_total.state === "LITERAL" ? row.source_total.units : null;
      if ((total || null) !== originalTotal) result.push({ type: "set_reviewed_total", source_key: row.source_key, value: total || null });
    }
    if (!result.length) throw new Error("没有需要保存的变更。");
    return result;
  }
  async function makePreview() {
    setBusy(true); setError(undefined);
    try {
      if (!reason.trim()) throw new Error("请填写核对依据或更正原因。");
      const body = { source_identity: basis.source_identity, expected_revision: basis.revision, changes: changes(), reason };
      const value = await writeApi<Preview>(`/api/production/inventory-reviews/${basis.review_id}/preview`, { body, idempotent: false });
      if (alive.current) { setPreview(value); setConflict(false); }
    } catch (failure) { if (failure instanceof ApiRequestError && failure.status === 403) { onForbidden(); return; } if (alive.current) { setError(message(failure)); setConflict(failure instanceof ApiRequestError && failure.status === 409); } }
    finally { if (alive.current) setBusy(false); }
  }
  async function reconcile() {
    setBusy(true);
    try { const next = await onReload(); if (alive.current) { setBasis(next); setPreview(undefined); setPending(undefined); setConflict(false); setError("已读取版本 " + next.revision + "。输入保留；请比较最新资料，再点击预览，不会自动覆盖。"); } }
    catch (failure) { if (failure instanceof ApiRequestError && failure.status === 403) { onForbidden(); return; } if (alive.current) setError(message(failure)); }
    finally { if (alive.current) setBusy(false); }
  }
  async function submitted(receipt: Receipt) {
    if (!alive.current) return;
    setSaved(receipt.saved_revision); setPending(undefined); setDirty(false); setPreview(undefined);
    try { await onReload(); } catch (failure) { if (alive.current) setError("已保存修订 " + receipt.saved_revision + "，但当前结果读取未完成：" + message(failure)); }
  }
  async function send(operation = pending) {
    if (!operation && !preview) return;
    const input = operation || { id: createOperationKey(), body: { source_identity: basis.source_identity, expected_revision: basis.revision, changes: changes(), reason, preview_hash: preview!.preview_hash } };
    setPending(input); setBusy(true); setError(undefined);
    try { const receipt = await writeApi<Receipt>(`/api/production/inventory-reviews/${basis.review_id}/commands`, { body: input.body, operationKey: input.id }); await submitted(receipt); }
    catch (failure) {
      if (failure instanceof ApiRequestError && failure.status === 403) { onForbidden(); return; }
      if (alive.current) {
        if (failure instanceof ApiRequestError && failure.status < 500) { setPending(undefined); setConflict(failure.status === 409); }
        setError(message(failure));
      }
    } finally { if (alive.current) setBusy(false); }
  }
  async function findReceipt() {
    if (!pending) return;
    setBusy(true); setError(undefined);
    try { const receipt = await requestApi<Receipt>(`/api/production/inventory-reviews/${basis.review_id}/operations/${pending.id}`); await submitted(receipt); }
    catch (failure) { if (failure instanceof ApiRequestError && failure.status === 403) { onForbidden(); return; } if (alive.current) setError(message(failure)); }
    finally { if (alive.current) setBusy(false); }
  }
  function restore(field: string, source_key?: string) { changed(); setRestores([{ type: "restore_source_field", field, ...(source_key ? { source_key } : {}) }]); }
  const locked = busy || !!pending || saved !== undefined;
  const labels: Record<Edit["mode"], string> = { location: "处理仓库归属", date: "核对盘点日期与截止", quantity: "核对尺码数量与合计", product: edit.product?.value ? "保存商品对应" : "解除商品对应" };
  return <Dialog contentClassName={styles.productionDialog} returnFocusTarget={returnFocusTarget} open onOpenChange={open => { if (!open) close(); }} title={labels[edit.mode]} description={`固定来源 ${review.source.filename} · 修订 ${basis.revision}，核对决定不产生库存过账。`} size="large">
    <div className={styles.inventoryReviewForm}>
      {edit.mode === "product" && edit.product && <><p>来源：{edit.rows[0]!.style_code} · {edit.rows[0]!.color || edit.rows[0]!.color_note} / {edit.product.size} · {edit.rows[0]!.source_key}</p><p>{edit.product.value ? "本次对应：" + edit.product.label + " · 商品规格身份 #" + edit.product.value.sku_id : "本次解除已保存的对应，来源和历史保留。"}</p><p>仅保存该尺码的商品对应，不更改数量，也不产生库存过账。</p></>}
      {edit.mode === "location" && <><ul>{edit.rows.map(row => <li key={row.source_key}>{row.style_code} · {row.color} · {units(row.stock_units)}件 · 原仓库：{row.location || "空白"} · {row.source_key}</li>)}</ul><FormField label="本次仓库归属"><select disabled={locked} value={location} onChange={event => { changed(); setRestores([]); setLocation(event.target.value); }}><option value="">请选择（不默认归属）</option><option value="WAREHOUSE_1">{review.source.source_kind === "MANUAL" ? review.source.warehouse_note || "本次核对仓库" : "花都仓库1号"}</option><option value="OUTSIDE_SCOPE">明确不属于本仓</option><option value="UNCONFIRMED">仍待确认</option></select></FormField>{edit.rows.map(row => <Button key={row.source_key} disabled={locked} variant="quiet" onClick={() => restore("location", row.source_key)}>恢复{row.source_key}原仓库决定</Button>)}</>}
      {edit.mode === "date" && <><p>原始整理日期：{review.source.organized_on || "未知"}；不作为盘点日期默认值。</p><FormField label="实际盘点日期（留空仍待确认）"><Input aria-describedby={error ? "inventory-review-error" : undefined} type="date" disabled={locked} value={stockDate} onChange={event => { changed(); setRestores([]); setStockDate(event.target.value); }} /></FormField><FormField label="库存截止说明"><Input aria-describedby={error ? "inventory-review-error" : undefined} disabled={locked} maxLength={1000} value={cutoff} onChange={event => { changed(); setRestores([]); setCutoff(event.target.value); }} /></FormField><Button disabled={locked} variant="quiet" onClick={() => restore("stocktaken_on")}>恢复原始盘点日期</Button><Button disabled={locked} variant="quiet" onClick={() => restore("cutoff_note")}>恢复原始截止说明</Button></>}
      {edit.mode === "quantity" && edit.rows.map(row => <section key={row.source_key}><h3>{row.style_code} · {row.color} · {row.source_key}</h3><p>原表合计：{row.source_total.raw || "未知"}；已知尺码和：{units(row.literal_units)}。留空是未知，填写0表示明确为0；差额不自动分摊。</p><Table title="本次数量核对"><thead><tr><th>字段</th><th>原文</th><th>本次确认值</th><th>恢复</th></tr></thead><tbody>{[...inventorySizes, "total"].map(size => <tr key={size}><th scope="row">{size === "total" ? "确认合计" : size}</th><td>{size === "total" ? row.source_total.raw || "空白" : row.quantities[size]?.raw || "空白/未记录"}</td><td><Input aria-describedby={error ? "inventory-review-error" : undefined} aria-label={row.source_key + " " + size} inputMode="numeric" maxLength={18} disabled={locked} value={quantities[row.source_key + "|" + size]} placeholder="未知" onChange={event => { changed(); setRestores([]); setQuantities(value => ({ ...value, [row.source_key + "|" + size]: event.target.value })); }} /></td><td><Button disabled={locked} variant="quiet" onClick={() => restore(size === "total" ? "reviewed_total" : size, row.source_key)}>恢复原值</Button></td></tr>)}</tbody></Table></section>)}
      {!!restores.length && <StatusMessage kind="info" title="本次将恢复所选原值">其他输入本次不提交；仍需填写原因、预览后保存。</StatusMessage>}
      <FormField label="核对依据 / 更正原因"><Input aria-describedby={error ? "inventory-review-error" : undefined} disabled={locked} maxLength={1000} value={reason} onChange={event => { changed(); setReason(event.target.value); }} /></FormField>
      <InventoryReviewNotice error={error} saved={saved} operationId={pending?.id} />
      {conflict && edit.mode === "product" && <StatusMessage kind="warning" title="请重新核对商品对应">本次尚未保存。资料或商品目录已变化，请返回后重新查看对应并确认。<Button disabled={busy} onClick={onClose}>返回重新核对商品</Button></StatusMessage>}
      {conflict && edit.mode !== "product" && <><p>最新读取版本{basis.revision}；本次输入保留。最新盘点日：{basis.effective.stocktaken_on || "未知"}，截止：{basis.effective.cutoff_note || "未知"}。</p><ul>{edit.rows.map(row => { const latest = [...basis.effective.rows, ...basis.effective.unconfirmed_rows, ...(basis.effective.outside_rows || [])].find(value => value.source_key === row.source_key); return <li key={row.source_key}>{row.source_key} · 最新仓库：{latest?.location_group} · 合计：{latest?.stock_units}</li>; })}</ul><Button disabled={busy} onClick={() => void reconcile()}>读取最新版本并保留输入</Button></>}
      {preview && <InventoryReviewPreview preview={preview} />}
      <div className={styles.actions}>{saved === undefined && !pending && !(conflict && edit.mode === "product") && <Button disabled={busy} onClick={() => void makePreview()}>预览核对影响</Button>}{preview && !pending && <Button disabled={busy} onClick={() => void send()}>保存核对结果</Button>}{pending && <><Button disabled={busy} onClick={() => void findReceipt()}>查询原操作结果</Button><Button disabled={busy} onClick={() => void send()}>以同一操作重试</Button></>}<Button disabled={busy} variant="secondary" onClick={close}>{saved !== undefined ? "完成并返回" : "取消"}</Button></div>
    </div>{leave.prompt}
  </Dialog>;
}
