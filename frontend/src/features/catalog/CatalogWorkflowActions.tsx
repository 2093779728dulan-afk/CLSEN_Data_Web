import { useState } from "react";
import { CircleCheck, ArrowRight, LoaderCircle, ShieldCheck } from "lucide-react";
import { Button, FormField, Input, LinkButton, StatusBadge, StatusMessage } from "../../design-system";
import css from "./CatalogWorkflowActions.module.css";
import { ApiRequestError } from "../../api/client";

import { catalogCommand, type CommandResult } from "./catalogApi";
import type { CatalogImportSummary } from "./catalogTypes";

export function CatalogWorkflowActions({ blockedReason, imported, onChanged, command: executeCommand = catalogCommand }: { blockedReason?: string; imported: CatalogImportSummary; onChanged: () => void | Promise<void>; command?: typeof catalogCommand }) {
  const [preview, setPreview] = useState<CommandResult>();
  const [previewRevision, setPreviewRevision] = useState<number>();
  const [approvedVersion, setApprovedVersion] = useState<number>();
  const activePreview = previewRevision === imported.workflow_revision ? preview : undefined;
  const [reason, setReason] = useState("批准本次商品主档修订并保留完整审核证据");
  const [replacementExportId, setReplacementExportId] = useState("");
  const [busy, setBusy] = useState(false);
  const disabled = busy || Boolean(blockedReason);
  const [error, setError] = useState<string>();
  const run = async (command: string, extra: Record<string, unknown> = {}) => {
    if (blockedReason || busy) return;
    setBusy(true); setError(undefined);
    try {
      const result = await executeCommand(imported.import_id, command, imported.workflow_revision, extra);
      if (command === "approval-preview") { setPreview(result); setPreviewRevision(imported.workflow_revision); }
      else { if (command === "approve" && typeof result.catalog_version_number === "number") setApprovedVersion(result.catalog_version_number); setPreview(undefined); await onChanged(); }
    } catch (reasonValue) { if (reasonValue instanceof ApiRequestError && reasonValue.status === 409) setPreview(undefined); setError(reasonValue instanceof Error ? reasonValue.message : "操作失败。"); }
    finally { setBusy(false); }
  };
  const canApprove = activePreview?.risk === "high" ? imported.permissions.can_approve_high_risk : imported.permissions.can_approve_normal;
  const publishedVersion = approvedVersion ?? imported.approved_catalog_version_number;
  if (imported.status === "approved" || approvedVersion !== undefined) return (
    <section className={css.panel} aria-label="目录批准结果">
      <div className={css.result}><CircleCheck aria-hidden="true" /><div><p className={css.eyebrow}>审核完成</p><h2>已批准生效</h2><p role="status">{publishedVersion ? `目录版本 V${publishedVersion} 已生成，可以查看本次批准的商品主档。` : "目录已批准，请到目录版本查看生效结果。"}</p></div>{publishedVersion && <StatusBadge tone="good" label={`V${publishedVersion}`} />}</div>
      <nav className={css.actions} aria-label="批准后操作"><LinkButton to="/catalog" variant="primary" icon={<ArrowRight />}>查看当前商品主档</LinkButton><LinkButton to="/catalog/versions">查看目录版本</LinkButton><LinkButton to="/catalog/maintenance" variant="quiet">返回批量维护</LinkButton></nav>
      <p className={css.note}>本次批准仅适用于当前批次，其他草稿仍需独立审核。</p>
    </section>
  );
  const hasPrimaryAction = imported.permissions.can_validate || imported.permissions.can_submit || imported.permissions.can_preview;
  const needsReason = Boolean(activePreview || imported.permissions.can_reject || imported.permissions.can_withdraw);
  return <section className={css.panel} aria-label="商品目录校验与批准" aria-busy={busy || undefined}>
    <header className={css.heading}><div><p className={css.eyebrow}>审核步骤 3</p><h2>校验与批准</h2><p>提交审核和生成预览都不会让目录生效；核对范围后，再确认批准。</p></div><StatusBadge tone="quiet" label={`当前修订 ${imported.workflow_revision}`} /></header>
    <ol className={css.path}><li><strong>补全并保存</strong><span>处理待办字段</span></li><li><strong>重新校验</strong><span>确认阻断项与风险</span></li><li><strong>提交并预览</strong><span>核对纳入范围</span></li><li><strong>确认批准</strong><span>生成新的目录版本</span></li></ol>
    {blockedReason && <StatusMessage kind="warning" title="先完成当前修改">{blockedReason}</StatusMessage>}
    <div className={css.actions} role="group" aria-label="当前可执行操作">
      {imported.permissions.can_validate && <Button variant="primary" disabled={disabled} onClick={() => void run("validate")} type="button">重新校验</Button>}
      {imported.status === "validated" && imported.validation_run_id == null && <p role="status">文件解析已通过。请先点击“重新校验”，完成目录业务校验后才能提交审核。</p>}
      {imported.permissions.can_submit && <Button variant="primary" disabled={disabled} onClick={() => void run("submit")} type="button">提交审核</Button>}
      {imported.permissions.can_preview && <Button variant="primary" disabled={disabled} onClick={() => void run("approval-preview")} type="button">生成批准预览</Button>}
      {!hasPrimaryAction && <p className={css.note}>先完成当前页面的待办，或等待有权限的审核人继续。</p>}
    </div>
    {activePreview && <div className={css.preview} aria-label="批准预览"><div className={css.previewHeading}><ShieldCheck aria-hidden="true" /><h3>核对本次批准</h3></div>
      <p>风险：{activePreview.risk === "high" ? "高风险（仅管理员可批准）" : activePreview.risk === "normal" ? "普通" : String(activePreview.risk)}</p>
      <dl className={css.metrics}><div><dt>纳入目录</dt><dd>{String(activePreview.included_row_count)} <small>行</small></dd></div><div><dt>仅保留审计</dt><dd>{String(activePreview.audit_only_row_count)} <small>行</small></dd></div><div><dt>目录发布修订</dt><dd>{String(activePreview.catalog_publication_revision)}</dd></div></dl>
      <p className={css.note}>批准会形成完整的新目录版本；预览只适用于当前草稿修订。</p>
      {!canApprove && <StatusMessage kind="warning" title="当前账号无权批准">此风险等级需要有权限的审核人处理。</StatusMessage>}
    </div>}
    {needsReason && <FormField label={activePreview ? "批准原因" : "操作原因"} hint={activePreview ? "至少 3 个字符；该说明随本次批准保留。" : "该说明随拒绝或撤回保留，请说明处理依据。"}><Input disabled={disabled} onChange={(event) => setReason(event.target.value)} value={reason} /></FormField>}
    {(activePreview || imported.permissions.can_reject || imported.permissions.can_withdraw || imported.permissions.can_resume) && <div className={css.actions} role="group" aria-label="审核决定">
      {activePreview && canApprove && <Button variant="primary" disabled={disabled || reason.trim().length < 3} onClick={() => void run("approve", {
        expected_catalog_publication_revision: activePreview.catalog_publication_revision,
        projection_digest: activePreview.projection_digest,
        projection_id: activePreview.projection_id,
        reason,
      })} type="button">确认批准目录</Button>}
      {imported.permissions.can_reject && <Button disabled={disabled} onClick={() => void run("reject", { reason })} type="button">拒绝</Button>}
      {imported.permissions.can_withdraw && <Button disabled={disabled} onClick={() => void run("withdraw", { reason })} type="button">撤回</Button>}
      {imported.permissions.can_resume && <Button disabled={disabled} onClick={() => void run("resume", { expected_parse_attempt_revision: imported.parse_attempt_revision })} type="button">恢复解析</Button>}
    </div>}
    {imported.permissions.can_rebase && <details className={css.advanced}><summary>高级操作 · 调整目录基准</summary><div className={css.rebase}><p>切换到新的目录基准时，填写已生成的替代导出编号。调整后请重新校验并生成批准预览。</p><div className={css.rebaseForm}><FormField label="替代导出编号（export ID）" hint="填写导出编号，例如 8002；只接受数字。"><Input disabled={disabled} inputMode="numeric" onChange={(event) => setReplacementExportId(event.target.value)} value={replacementExportId} /></FormField><Button disabled={disabled || !/^\d+$/.test(replacementExportId)} onClick={() => void run("rebase", { expected_catalog_publication_revision: imported.catalog_publication_revision, replacement_export_id: Number(replacementExportId) })} type="button">调整到新基准</Button></div></div></details>}
    {busy && <p className={css.pending} role="status"><LoaderCircle aria-hidden="true" className={css.spin} />正在执行操作，请等待结果…</p>}
    {error && <StatusMessage kind="danger" title="操作未完成">{error} 输入内容已保留；核对后重新操作。</StatusMessage>}
  </section>;
}
