import { useState } from "react";
import { CircleCheck, ArrowRight } from "lucide-react";
import { Button, LinkButton } from "../../design-system";
import { ApiRequestError } from "../../api/client";

import { catalogCommand, type CommandResult } from "./catalogApi";
import type { CatalogImportSummary } from "./catalogTypes";

export function CatalogWorkflowActions({ imported, onChanged }: { imported: CatalogImportSummary; onChanged: () => void | Promise<void> }) {
  const [preview, setPreview] = useState<CommandResult>();
  const [previewRevision, setPreviewRevision] = useState<number>();
  const [approvedVersion, setApprovedVersion] = useState<number>();
  const activePreview = previewRevision === imported.workflow_revision ? preview : undefined;
  const [reason, setReason] = useState("批准本次商品主档修订并保留完整审核证据");
  const [replacementExportId, setReplacementExportId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const run = async (command: string, extra: Record<string, unknown> = {}) => {
    setBusy(true); setError(undefined);
    try {
      const result = await catalogCommand(imported.import_id, command, imported.workflow_revision, extra);
      if (command === "approval-preview") { setPreview(result); setPreviewRevision(imported.workflow_revision); }
      else { if (command === "approve" && typeof result.catalog_version_number === "number") setApprovedVersion(result.catalog_version_number); setPreview(undefined); await onChanged(); }
    } catch (reasonValue) { if (reasonValue instanceof ApiRequestError && reasonValue.status === 409) setPreview(undefined); setError(reasonValue instanceof Error ? reasonValue.message : "操作失败。"); }
    finally { setBusy(false); }
  };
  const canApprove = activePreview?.risk === "high" ? imported.permissions.can_approve_high_risk : imported.permissions.can_approve_normal;
  const publishedVersion = approvedVersion ?? imported.approved_catalog_version_number;
  if (imported.status === "approved" || approvedVersion !== undefined) return (
    <section className="catalog-panel catalog-approval-result" aria-label="目录批准结果">
      <div className="catalog-approval-result__summary">
        <CircleCheck aria-hidden="true" className="catalog-approval-result__icon" />
        <div><h2>已批准生效</h2><p role="status">{publishedVersion ? `目录版本 V${publishedVersion} 已生成，可以查看本次批准的商品主档。` : "目录已批准，请到目录版本查看生效结果。"}</p></div>
        {publishedVersion && <span className="catalog-approval-result__version">V{publishedVersion}</span>}
      </div>
      <nav className="catalog-approval-result__actions" aria-label="批准后操作">
        <LinkButton to="/catalog" variant="primary" icon={<ArrowRight />}>查看当前商品主档</LinkButton>
        <LinkButton to="/catalog/versions">查看目录版本</LinkButton>
        <LinkButton to="/catalog/maintenance" variant="quiet">返回批量维护</LinkButton>
      </nav>
      <p className="catalog-approval-result__note">本次批准仅适用于当前批次，其他草稿仍需独立审核。</p>
    </section>
  );
  const hasPrimaryAction = imported.permissions.can_validate || imported.permissions.can_submit || imported.permissions.can_preview;
  return <section className="catalog-panel catalog-workflow"><div className="catalog-panel__heading"><div><p className="section-kicker">审核步骤 3</p><h2>校验与批准</h2><p>按当前状态执行可用操作。提交审核和生成预览都不会让目录生效，只有最后确认批准才会生效。</p></div><span className="catalog-revision">当前修订 {imported.workflow_revision}</span></div><ol className="catalog-approval-path"><li><strong>补全并保存</strong><span>先处理页面中的待办字段</span></li><li><strong>重新校验</strong><span>由服务端确认阻断项与风险</span></li><li><strong>提交并预览</strong><span>核对本次纳入范围和版本</span></li><li><strong>确认批准</strong><span>形成新的已批准目录版本</span></li></ol><div className="catalog-workflow__toolbar"><div aria-label="当前可执行操作" className="catalog-actions catalog-workflow__primary">
    {imported.permissions.can_validate && <Button variant="primary" disabled={busy} onClick={() => void run("validate")} type="button">重新校验</Button>}
    {imported.status === "validated" && imported.validation_run_id == null && <p role="status">文件解析已通过。请先点击“重新校验”，完成目录业务校验后才能提交审核。</p>}
    {imported.permissions.can_submit && <Button variant="primary" disabled={busy} onClick={() => void run("submit")} type="button">提交审核</Button>}
    {imported.permissions.can_preview && <Button variant="primary" disabled={busy} onClick={() => void run("approval-preview")} type="button">生成批准预览</Button>}
    {!hasPrimaryAction && <span className="catalog-workflow__waiting">先完成当前页面的待办，或等待有权限的审核人继续。</span>}
  </div><div aria-label="其他工作流操作" className="catalog-actions catalog-workflow__secondary">
    {imported.permissions.can_reject && <Button disabled={busy} onClick={() => void run("reject", { reason })} type="button">拒绝</Button>}
    {imported.permissions.can_withdraw && <Button disabled={busy} onClick={() => void run("withdraw", { reason })} type="button">撤回</Button>}
    {imported.permissions.can_resume && <Button disabled={busy} onClick={() => void run("resume", { expected_parse_attempt_revision: imported.parse_attempt_revision })} type="button">恢复解析</Button>}
  </div></div>{activePreview && <div className="catalog-approval-preview"><p>风险：{activePreview.risk === "high" ? "高风险（仅管理员可批准）" : activePreview.risk === "normal" ? "普通" : String(activePreview.risk)}</p><p>基于目录发布修订 {String(activePreview.catalog_publication_revision)}；批准会形成完整的新目录版本。</p><p>纳入 {String(activePreview.included_row_count)} 行；仅审计 {String(activePreview.audit_only_row_count)} 行</p><label>批准原因<input onChange={(event) => setReason(event.target.value)} value={reason} /></label>{!canApprove && <p>当前账号无权批准此风险等级，请交由有权限的审核人处理。</p>}{canApprove && <Button variant="primary" disabled={busy || reason.trim().length < 3} onClick={() => void run("approve", {
    expected_catalog_publication_revision: activePreview.catalog_publication_revision,
    projection_digest: activePreview.projection_digest,
    projection_id: activePreview.projection_id,
    reason,
  })} type="button">确认批准目录</Button>}</div>}{imported.permissions.can_rebase && <details className="catalog-workflow__advanced"><summary>高级操作 · 调整目录基准</summary><p>需要切换到新的目录基准时，填写替代导出编号。</p><div className="catalog-workflow__rebase"><label>替代导出编号（export ID）<input inputMode="numeric" onChange={(event) => setReplacementExportId(event.target.value)} value={replacementExportId} /></label><Button disabled={busy || !/^\d+$/.test(replacementExportId)} onClick={() => void run("rebase", { expected_catalog_publication_revision: imported.catalog_publication_revision, replacement_export_id: Number(replacementExportId) })} type="button">调整到新基准</Button></div></details>}{error && <p className="form-error" role="alert">{error}</p>}</section>;
}
