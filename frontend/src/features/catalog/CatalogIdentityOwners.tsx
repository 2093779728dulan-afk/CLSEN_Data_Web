import { useState } from "react";
import { ArrowUpRight, Layers, Link2, LoaderCircle, Package, RotateCcw } from "lucide-react";
import { Button, EmptyState, FormField, Input, StatusBadge, StatusMessage } from "../../design-system";
import { requestApi } from "../../api/client";
import { saveCatalogMutation } from "./catalogApi";
import type { CatalogImportRow } from "./catalogTypes";
import css from "./CatalogIdentityOwners.module.css";

export type IdentityOwners = {
  drafts: Array<{ import_id: number; decision_kind: string }>;
  formal: Array<{ sku_id: number; style_id: number }>;
  ignored: Array<{ catalog_version_id: number; reason: string }>;
};

function readOwners(importId: number, rowKey: string) {
  return requestApi<IdentityOwners>(`/api/catalog/imports/${importId}/identity-owners/${encodeURIComponent(rowKey)}`);
}

export function CatalogIdentityOwners({ importId, row, revision, onSaved, disabled = false, loadOwners = readOwners, saveMutation = saveCatalogMutation }: {
  importId: number; row: CatalogImportRow; revision: number; onSaved: (revision: number) => Promise<void>;
  disabled?: boolean; loadOwners?: typeof readOwners; saveMutation?: typeof saveCatalogMutation;
}) {
  const [owners, setOwners] = useState<IdentityOwners>();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<{ kind: "read" | "restore" | "refresh"; message: string }>();
  const [phase, setPhase] = useState<"read" | "restore" | "refresh">();
  const [acknowledgedRevision, setAcknowledgedRevision] = useState<number>();
  const busy = phase !== undefined;
  const restored = acknowledgedRevision !== undefined && revision <= acknowledgedRevision;
  const refreshFailed = error?.kind === "refresh";

  async function inspect() {
    if (busy || disabled) return;
    setError(undefined); setPhase("read");
    try { setOwners(await loadOwners(importId, row.row_key)); }
    catch (e) { setError({ kind: "read", message: e instanceof Error ? e.message : "无法读取归属" }); }
    finally { setPhase(undefined); }
  }
  async function restore() {
    if (busy || disabled || restored || !reason.trim()) return;
    setError(undefined); setPhase("restore");
    let acknowledged = false;
    try {
      const value = await saveMutation(importId, revision, {
        type: "restore_seller_sku_review", decision_group_key: row.row_key, row_key: null,
        payload: { change_reason: reason.trim() },
      });
      if (typeof value.workflow_revision !== "number") throw new Error("响应缺少修订号");
      setAcknowledgedRevision(value.workflow_revision);
      acknowledged = true;
      setPhase("refresh");
      await onSaved(value.workflow_revision);
    } catch (e) { setError({ kind: acknowledged ? "refresh" : "restore", message: e instanceof Error ? e.message : "恢复失败" }); }
    finally { setPhase(undefined); }
  }
  async function retryRead() {
    if (busy || acknowledgedRevision === undefined) return;
    setError(undefined); setPhase("refresh");
    try { await onSaved(acknowledgedRevision); }
    catch (e) { setError({ kind: "refresh", message: e instanceof Error ? e.message : "无法读取最新草稿" }); }
    finally { setPhase(undefined); }
  }

  return <section className={css.panel} aria-label="身份归属与审核恢复" aria-busy={busy || undefined}>
    <header className={css.heading}><h3><Link2 aria-hidden="true" />身份归属</h3><Button loading={phase === "read"} loadingLabel="正在读取归属" disabled={busy || disabled} onClick={() => void inspect()} type="button">查看归属与冲突</Button></header>
    {owners && <section aria-label="身份归属" className={css.owners}>
      {!owners.formal.length && !owners.drafts.length && !owners.ignored.length ? <EmptyState title="尚无正式归属或草稿占用。" description="当前读取结果也没有正式忽略记录；请继续核对来源和目标 SKU。" /> : <>
        {!!owners.formal.length && <section className={css.group} aria-label="已批准归属"><div className={css.groupHeading}><h4>已批准归属</h4><StatusBadge tone="quiet" label={`${owners.formal.length} 项`} /></div><ul>{owners.formal.map(owner => <li key={owner.sku_id}><a className={css.ownerLink} aria-label={`商品 STYLE #${owner.style_id}`} href={`/catalog/styles/${owner.style_id}`}><Package aria-hidden="true" className={css.objectIcon} /><span className={css.ownerContent}><strong>商品 STYLE #{owner.style_id}</strong><span className={css.identifier}>SKU #{owner.sku_id}</span></span><ArrowUpRight aria-hidden="true" className={css.linkArrow} /></a></li>)}</ul></section>}
        {!!owners.drafts.length && <section className={css.group} aria-label="草稿占用"><div className={css.groupHeading}><h4>草稿占用</h4><StatusBadge tone="quiet" label={`${owners.drafts.length} 项`} /></div><ul>{owners.drafts.map(owner => <li key={owner.import_id}><a className={css.ownerLink} aria-label={`审核批次 #${owner.import_id}`} href={`/catalog/imports/${owner.import_id}`}><Layers aria-hidden="true" className={css.objectIcon} /><span className={css.ownerContent}><strong>审核批次 #{owner.import_id}</strong><StatusBadge tone={owner.decision_kind === "excluded" ? "warn" : "quiet"} label={`草稿${owner.decision_kind === "excluded" ? "排除" : "映射"}占用`} /></span><ArrowUpRight aria-hidden="true" className={css.linkArrow} /></a></li>)}</ul></section>}
        {!!owners.ignored.length && <section className={css.group} aria-label="已忽略记录"><div className={css.groupHeading}><h4>已忽略记录</h4><StatusBadge tone="quiet" label={`${owners.ignored.length} 项`} /></div><ul>{owners.ignored.map(owner => <li key={owner.catalog_version_id}><strong>目录版本 #{owner.catalog_version_id} 已忽略</strong><p>{owner.reason}</p></li>)}</ul></section>}
      </>}
      <p className={css.note}>冲突时请先核对来源和相关批次；撤回占用草稿后可重试。已批准身份转移保留高风险限制。</p>
    </section>}
    {row.payload.identity_decision === "excluded" && <div className={css.restore}>
      <FormField label="恢复审核原因" hint="说明来源复核依据；恢复只修改当前草稿，不会解除正式忽略。"><Input className={css.control} disabled={busy || disabled || restored} value={reason} onChange={e => setReason(e.target.value)} /></FormField>
      <Button icon={<RotateCcw />} loading={phase === "restore"} loadingLabel="正在恢复草稿" disabled={busy || disabled || restored || !reason.trim()} onClick={() => void restore()} type="button">恢复到待审核</Button>
      <p className={css.note}>正式忽略在重新映射并由管理员批准后解除。</p>
    </div>}
    {phase === "refresh" && <p className={css.pending} role="status"><LoaderCircle aria-hidden="true" className={css.spin} />正在重新读取草稿…</p>}
    {restored && !error && !busy && <StatusMessage kind="success" title="草稿已恢复到待审核">请在当前草稿继续核对映射；正式目录尚未改变。</StatusMessage>}
    {error && <StatusMessage kind="danger" title={refreshFailed ? "草稿已恢复，最新明细读取失败" : "操作未完成"} action={refreshFailed ? <Button disabled={busy} onClick={() => void retryRead()}>重新读取草稿</Button> : undefined}>{error.message} {refreshFailed ? "请重新读取草稿，不要重复提交恢复。" : "输入原因已保留；若归属已显示，它是上次读取结果，请重新核对后再操作。"}</StatusMessage>}
  </section>;
}
