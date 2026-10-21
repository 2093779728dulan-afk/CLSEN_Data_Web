import { useState } from "react";
import { Button, Dialog, FormField, StatusBadge, StatusMessage } from "../../design-system";
import type { DraftHead, ValidationRun } from "../../api/types";
import type { DraftReviewContext } from "./workflowTypes";
import { auditOperatorLabel, defaultAuditReason, reportTypeAuditLabel, type AuditOperator } from "./auditReason";
import { errorMessage, reportTypeLabel, validationCounts } from "./draftReviewPresentation";
import controlCss from "../../design-system/Control.module.css";
import css from "./DraftPublicationDialog.module.css";

export function PublicationDialog({
  context,
  head,
  validation,
  onCancel,
  onPublish,
  operator,
  publicationProgress,
}: {
  context: DraftReviewContext;
  head: DraftHead;
  validation: ValidationRun;
  onCancel: () => void;
  onPublish: (reason: string) => Promise<void>;
  operator?: AuditOperator;
  publicationProgress?: "building" | "ready" | "failed" | "superseded";
}) {
  const [reason, setReason] = useState(() => defaultAuditReason(
    operator,
    context.publicationMode === "published_move" ? "确认跨日期版本生效" : "确认发布审核版本",
    `${context.reportDate} ${reportTypeAuditLabel(context.reportType)} · 版本 v${head.version_no} · 校验 #${validation.validation_run_id}`,
  ));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const counts = validationCounts(validation);
  const isPublishedMove = context.publicationMode === "published_move";
  const submit = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await onPublish(reason);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open dismissDisabled={busy} onOpenChange={(open) => { if (!open && !busy) onCancel(); }} closeLabel="返回审核" eyebrow="最终发布闸门" title={isPublishedMove ? "跨日期生效确认" : "发布确认"} description={isPublishedMove ? "生效后，来源与目标日期的发布指针会在同一事务中切换。后续修正必须创建新修订。" : "发布后，查看人员将立即读取这个版本。后续修正必须创建新修订。"}>
      <div aria-label="发布确认内容" role="region" tabIndex={busy ? 0 : undefined} aria-busy={busy || undefined} className={css.content}>
        <div className={css.receipt}><div><span>本次校验回执</span><strong>校验 #{validation.validation_run_id}</strong></div><StatusBadge label={validation.result === "passed" ? "校验通过" : "待核对校验"} tone={validation.result === "passed" ? "good" : "warn"} /></div>
        <dl className={css.ledger}>
          <div><dt>报告日期</dt><dd>{context.reportDate}</dd></div>
          <div><dt>报表类型</dt><dd>{reportTypeLabel(context.reportType)}</dd></div>
          <div><dt>版本</dt><dd>v{head.version_no}<small>版本 ID #{head.version_id}</small></dd></div>
          <div><dt>数据修订</dt><dd>r{head.data_revision}</dd></div>
          <div><dt>行数</dt><dd>{validation.summary.row_count} 行</dd></div>
          <div><dt>警告</dt><dd>{counts.warning} 项</dd></div>
        </dl>
        {isPublishedMove && context.publishedMove && <section aria-label="跨日期生效范围" className={css.move}><h3>两侧一起生效</h3><div><span>来源日期</span><strong>{context.publishedMove.source_report_date}</strong><small>数据集 #{context.publishedMove.source_dataset_id} · 发布版本 ID #{context.publishedMove.source_publication.version_id ?? "尚未发布"}</small></div><div><span>目标日期</span><strong>{context.reportDate}</strong><small>数据集 #{head.dataset_id} · 待生效版本 ID #{head.version_id}</small></div></section>}
        <section aria-label="校验合计" className={css.totals}><h3>校验合计</h3><dl>{Object.entries(validation.summary.totals).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl></section>
        {counts.warning > 0 && <StatusMessage kind="warning" title={`包含 ${counts.warning} 项警告`}>请确认审核页中的警告处置与合计后再发布；此处不会清除或重新确认警告。</StatusMessage>}
        <FormField label="发布说明" required hint="说明本次核对与发布的依据；失败后内容保留。"><textarea aria-label="发布说明" className={controlCss.control} disabled={busy} onChange={(event) => setReason(event.target.value)} required rows={3} value={reason} /></FormField>
        {operator && <p className={css.operator}>操作人来源：当前登录会话 · {auditOperatorLabel(operator)}。服务器将按该会话写入发布审计。</p>}
        {publicationProgress === "building" && <StatusMessage kind="info" title="正在准备退货快照">准备完成前不会切换发布指针。请保留当前窗口。</StatusMessage>}
        {publicationProgress === "failed" && <StatusMessage kind="warning" title="快照准备未成功">本次准备不能直接用于发布。请根据操作结果核对或重试。</StatusMessage>}
        {publicationProgress === "ready" && <StatusMessage kind="info" title="退货快照已准备">最终是否生效仍以发布响应为准，请等待当前操作完成。</StatusMessage>}
        {publicationProgress === "superseded" && <StatusMessage kind="warning" title="发布集合已变化">此前准备已失效，当前准备不能直接用于发布。最终结果以本次发布响应为准。</StatusMessage>}
        {error && <StatusMessage kind="danger" title="发布未完成">{error}</StatusMessage>}
        <div className={css.actions}>
          <Button variant="secondary" disabled={busy} onClick={onCancel} type="button">返回审核</Button>
          <Button variant="primary" loading={busy} loadingLabel={isPublishedMove ? "正在生效…" : "正在发布…"} disabled={busy || !reason.trim()} onClick={() => { void submit(); }} type="button">
            {isPublishedMove ? "确认跨日期生效" : "确认发布"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
