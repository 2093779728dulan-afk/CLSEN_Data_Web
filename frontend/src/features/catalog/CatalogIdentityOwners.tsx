import { useState } from "react";
import { Button } from "../../design-system";
import { requestApi } from "../../api/client";
import { saveCatalogMutation } from "./catalogApi";
import type { CatalogImportRow } from "./catalogTypes";

type Owners = {
  drafts: Array<{ import_id: number; decision_kind: string }>;
  formal: Array<{ sku_id: number; style_id: number }>;
  ignored: Array<{ catalog_version_id: number; reason: string }>;
};

export function CatalogIdentityOwners({ importId, row, revision, onSaved }: {
  importId: number; row: CatalogImportRow; revision: number; onSaved: (revision: number) => Promise<void>;
}) {
  const [owners, setOwners] = useState<Owners>();
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function inspect() {
    setError(""); setBusy(true);
    try { setOwners(await requestApi<Owners>(`/api/catalog/imports/${importId}/identity-owners/${encodeURIComponent(row.row_key)}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "无法读取归属"); }
    finally { setBusy(false); }
  }
  async function restore() {
    setError(""); setBusy(true);
    try {
      const value = await saveCatalogMutation(importId, revision, {
        type: "restore_seller_sku_review", decision_group_key: row.row_key, row_key: null,
        payload: { change_reason: reason.trim() },
      });
      if (typeof value.workflow_revision !== "number") throw new Error("响应缺少修订号");
      await onSaved(value.workflow_revision);
    } catch (e) { setError(e instanceof Error ? e.message : "恢复失败"); }
    finally { setBusy(false); }
  }
  return <div>
    <Button disabled={busy} onClick={() => void inspect()} type="button">查看归属与冲突</Button>
    {owners && <div aria-label="身份归属">
      {owners.formal.map(owner => <p key={owner.sku_id}>已批准归属：<a href={`/catalog/styles/${owner.style_id}`}>商品 STYLE #{owner.style_id}</a> / SKU #{owner.sku_id}</p>)}
      {owners.drafts.map(owner => <p key={owner.import_id}>草稿{owner.decision_kind === "excluded" ? "排除" : "映射"}占用：<a href={`/catalog/imports/${owner.import_id}`}>审核批次 #{owner.import_id}</a></p>)}
      {owners.ignored.map(owner => <p key={owner.catalog_version_id}>目录版本 #{owner.catalog_version_id} 已忽略：{owner.reason}</p>)}
      {!owners.formal.length && !owners.drafts.length && !owners.ignored.length && <p>尚无正式归属或草稿占用。</p>}
      <p>冲突时请先核对来源和相关批次；撤回占用草稿后可重试。已批准身份转移保留高风险限制。</p>
    </div>}
    {row.payload.identity_decision === "excluded" && <div>
      <label>恢复审核原因<input value={reason} onChange={e => setReason(e.target.value)} /></label>
      <Button disabled={busy || !reason.trim()} onClick={() => void restore()} type="button">恢复到待审核</Button>
      <p>恢复只修改当前草稿；正式忽略在重新映射并由管理员批准后解除。</p>
    </div>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
