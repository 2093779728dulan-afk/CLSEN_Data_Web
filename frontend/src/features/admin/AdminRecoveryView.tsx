import type { FormEvent } from "react";
import { Button, Checkbox, FormField, Skeleton, StatusBadge, StatusMessage } from "../../design-system";
import type { AdminForceRebuildContext } from "./AdminConsole";
import css from "./AdminRecoveryView.module.css";

type Props = {
  context?: AdminForceRebuildContext;
  loading: boolean;
  loadFailed: boolean;
  busy: boolean;
  reason: string;
  confirmed: boolean;
  error?: string;
  notice?: string;
  onRetry: () => void;
  onReasonChange: (value: string) => void;
  onConfirmedChange: (value: boolean) => void;
  onSubmit: (event: FormEvent) => void;
};

export function AdminRecoveryView({ context, loading, loadFailed, busy, reason, confirmed, error, notice, onRetry, onReasonChange, onConfirmedChange, onSubmit }: Props) {
  return <section aria-labelledby="admin-recovery-title" className={css.workspace}>
    <header className={css.heading}><div><h2 id="admin-recovery-title">草稿强制重建</h2><p>从导入冲突开始，保留版本校验与人工确认。</p></div><StatusBadge label="管理员专用" tone="warn" /></header>
    {loading ? <div role="status" aria-label="正在载入恢复前置状态" className={css.loading}><Skeleton height={100} /><Skeleton height={180} /></div>
      : loadFailed ? <StatusMessage kind="danger" title="恢复前置状态读取失败" action={<Button onClick={onRetry} variant="secondary">重新读取</Button>}>{error ?? "请重新读取管理状态后再继续。"}</StatusMessage>
      : <>
        {notice && <StatusMessage kind="success" title="重建结果">{notice}</StatusMessage>}
        {error && <StatusMessage kind="danger" title="重建未完成">{error}</StatusMessage>}
        {context ? <div className={css.layout}>
          <aside className={css.summary} aria-label="重建来源上下文"><h3>已锁定的来源</h3><p>以下标识来自审核上下文，只读展示。</p><dl>
            <div><dt>报表日期</dt><dd>{context.reportDate}</dd></div>
            <div><dt>活动草稿 ID</dt><dd>#{context.expectedActiveDraft.version_id}</dd></div>
            <div><dt>数据／审核修订</dt><dd>{context.expectedActiveDraft.data_revision} / {context.expectedActiveDraft.review_revision}</dd></div>
            <div><dt>导入批次 ID</dt><dd>#{context.batchId}</dd></div>
            <div><dt>解析基线 ID</dt><dd>#{context.parseBaselineId}</dd></div>
            <div><dt>发布版本 ID</dt><dd>{context.expectedPublicationVersionId === null ? "尚未发布" : `#${context.expectedPublicationVersionId}`}</dd></div>
          </dl></aside>
          <form aria-label="强制重建草稿" className={css.form} onSubmit={onSubmit}>
            <div><h3>说明重建原因</h3><p>旧草稿将被废弃，新草稿必须重新完成校验和人工确认。</p></div>
            <StatusMessage kind="warning" title="已发布版本保持不变">重建只生成新草稿，不会自动批准或发布。提交时仍核对活动草稿与发布指针。</StatusMessage>
            <FormField label="重建原因" required hint="填写本次解析基线或来源更正的原因，便于后续审计。"><textarea className={css.textarea} disabled={busy} onChange={event => onReasonChange(event.target.value)} required rows={4} value={reason} /></FormField>
            <Checkbox checked={confirmed} disabled={busy} onChange={event => onConfirmedChange(event.target.checked)} label="我确认不会绕过校验，也不会覆盖已发布版本。" />
            <footer className={css.actions}><span>{busy ? "正在提交，请等待结果。" : "填写原因并确认后方可提交。"}</span><Button disabled={!confirmed || !reason.trim()} loading={busy} type="submit" variant="danger">{busy ? "正在重建…" : "强制重建草稿"}</Button></footer>
          </form>
        </div> : <div className={css.entry}>
          <StatusBadge label="需要导入上下文" tone="quiet" /><h3>强制重建从导入冲突进入</h3>
          <p>为避免手工输入版本、解析基线或发布指针，此处不会接受自由填写的数据库 ID。请在“数据审核”中上传并解析新原表；目标日期已有活动草稿时，管理员会看到经过服务器预览的“强制重建活动草稿”选项。</p>
          <ol className={css.steps}><li><strong>上传并解析原表</strong><span>在目标日期的数据审核中使用新的来源文件。</span></li><li><strong>核对导入冲突</strong><span>检查活动草稿、解析基线与发布版本。</span></li><li><strong>确认重建，再校验</strong><span>填写原因；新草稿仍需校验和人工确认。</span></li></ol>
        </div>}
      </>}
  </section>;
}
