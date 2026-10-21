import type { FormEvent, ReactNode } from "react";
import type { UndoablePublishedMoveResponse, VersionDetailResponse, VersionSummaryResponse } from "../../api/generated";
import { Button, Checkbox, Dialog, Input, Radio, StatusMessage } from "../../design-system";
import controlStyles from "../../design-system/Control.module.css";
import { formatTimestamp, reportTypeLabel } from "./versionPresentation";
import type { MoveDecision, MoveTargetPreview } from "./VersionHistory";
import styles from "./VersionCommandViews.module.css";

type CommandFormProps = {
  onClose: () => void;
  onSubmit: (event: FormEvent) => void;
  reason: string;
  onReasonChange: (value: string) => void;
  submitting: boolean;
};
function CommandFrame({ label, title, description, submitting, onClose, onSubmit, children, wide = false }: {
  label: string; title: ReactNode; description: string; submitting: boolean;
  onClose: () => void; onSubmit: (event: FormEvent) => void; children: ReactNode; wide?: boolean;
}) {
  return <Dialog open accessibleLabel={label} title={title} description={description}
    closeLabel={`关闭${label}`} dismissDisabled={submitting} size={wide ? "large" : "medium"}
    onOpenChange={open => { if (!open && !submitting) onClose(); }}>
    <form aria-label={label} aria-busy={submitting || undefined} className={styles.form} onSubmit={onSubmit}>{children}</form>
  </Dialog>;
}

export function RevisionConfirmationView({ source, reason, onReasonChange, submitting, error, onClose, onSubmit }: CommandFormProps & { source: VersionDetailResponse; error?: string }) {
  return <CommandFrame label="创建发布修订" title={<>基于 v{source.version_no} 创建修订</>} description="建立新的审核草稿" submitting={submitting} onClose={onClose} onSubmit={onSubmit}>
<p>当前发布版本保持在线；系统会创建一个新的审核草稿，审核并发布后才会切换发布指针。</p>
        <dl>
          <div><dt>报告日</dt><dd>{source.report_date}</dd></div>
          <div><dt>当前发布</dt><dd>v{source.version_no}</dd></div>
        </dl>
        <label>
          修订原因
          <textarea className={controlStyles.control}
            disabled={submitting}
            onChange={(event) => {
              onReasonChange(event.target.value);
            }}
            required
            rows={4}
            value={reason}
          />
        </label>
        {error && <StatusMessage kind="danger" title="操作未完成">{error}</StatusMessage>}
        <footer>
          <Button variant="secondary" disabled={submitting} onClick={onClose} type="button">取消</Button>
          <Button variant="primary" disabled={submitting || !reason.trim()} loading={submitting} loadingLabel="正在提交…" type="submit">
            确认创建修订
          </Button>
        </footer>
  </CommandFrame>;
}

export function MoveConfirmationView({ source, targetDate, targetPreview, decision, reason, onReasonChange, submitting, checking, forceRebuild, forceConfirmed, onForceConfirmedChange, changeTargetDate, changeDecision, onInspectTarget, commandReady, mergeReady, mergeMatrix, moveError, submitLabel, onClose, onSubmit }: CommandFormProps & {
  source: VersionSummaryResponse; targetDate: string; targetPreview?: MoveTargetPreview; decision?: MoveDecision;
  checking: boolean; forceRebuild: boolean; forceConfirmed: boolean; onForceConfirmedChange: (value: boolean) => void;
  changeTargetDate: (value: string) => void; changeDecision: (value: MoveDecision) => void; onInspectTarget: () => void;
  commandReady: boolean; mergeReady: boolean; mergeMatrix?: ReactNode; moveError?: string; submitLabel: string;
}) {
  return <CommandFrame label="已发布数据跨日期移动" title="移动当前发布版本" description="选择目标日期并核对处理方式" wide submitting={submitting} onClose={onClose} onSubmit={onSubmit}>
<div className={styles.route} aria-label="移动日期范围">
          <div><span>来源报告日</span><strong>{source.report_date}</strong><small>v{source.version_no} 保持发布</small></div>
          <span aria-hidden="true">→</span>
          <div><span>目标报告日</span><strong>{targetDate || "尚未选择"}</strong><small>{reportTypeLabel(source.report_type)}</small></div>
        </div>

        <div className={styles.targetCheck}>
          <label>目标报告日<Input disabled={submitting} max="9999-12-31" min="2000-01-01" onChange={(event) => changeTargetDate(event.target.value)} required type="date" value={targetDate} /></label>
          <Button variant="secondary" disabled={submitting || checking || !targetDate || targetDate === source.report_date} onClick={() => { onInspectTarget(); }} type="button" loading={checking} loadingLabel="正在检查…">检查目标日期</Button>
        </div>

        {targetPreview?.kind === "empty" && (
          <section className={styles.targetState}>
            <strong>目标日期尚无数据</strong>
            <p>将创建新的目标数据集和活动草稿；来源发布版本在审核期间继续生效。</p>
          </section>
        )}

        {targetPreview?.kind === "published" && (
          <section className={styles.targetState}>
            <strong>目标日期已有发布版本 v{targetPreview.publication.version_no}</strong>
            <p>选择如何生成审核草稿。此步骤不会立即切换任一日期的发布指针。</p>
            <fieldset className={styles.decisions}>
              <legend>目标处理方式</legend>
              <Radio aria-label="合并目标发布版本" checked={decision === "merge_published"} disabled={submitting} name="published-target" onChange={() => changeDecision("merge_published")} label="合并目标发布版本" description="保留目标与来源数据，行冲突由服务端阻断，绝不自动覆盖。" />
              <Radio aria-label="替换目标发布版本" checked={decision === "replace_published"} disabled={submitting} name="published-target" onChange={() => changeDecision("replace_published")} label="替换目标发布版本" description="审核草稿只以来源版本为基础；最终生效仍需完整校验和确认。" />
              <Radio aria-label="取消本次移动" checked={decision === "client_cancel"} disabled={submitting} name="published-target" onChange={() => changeDecision("client_cancel")} label="取消本次移动" description="关闭流程，不向服务器发送写请求。" />
            </fieldset>
          </section>
        )}

        {targetPreview?.kind === "active_draft" && (
          <section className={styles.targetState}>
            <strong>目标日期已有活动草稿 v{targetPreview.draft.version_no}</strong>
            <p>所有选项都绑定当前草稿修订与指针时间；目标状态变化时服务器将拒绝命令。</p>
            <fieldset className={styles.decisions}>
              <legend>活动草稿处理方式</legend>
              <Radio aria-label="合并到活动草稿" checked={decision === "merge_draft"} disabled={submitting} name="draft-target" onChange={() => changeDecision("merge_draft")} label="合并到活动草稿" description="生成合并草稿并保留两侧谱系，旧活动草稿作为已审计前序版本封存。" />
              <Radio aria-label="记录取消，保留活动草稿" checked={decision === "cancel_draft"} disabled={submitting} name="draft-target" onChange={() => changeDecision("cancel_draft")} label="记录取消，保留活动草稿" description="服务器记录取消决定，不修改来源发布或目标草稿。" />
              {targetPreview.publication && <Radio aria-label="强制重建并合并目标发布" checked={decision === "force_merge"} disabled={submitting} name="draft-target" onChange={() => changeDecision("force_merge")} label="强制重建并合并目标发布" description="废弃当前活动草稿，以目标发布版本与来源版本合并重建。" />}
              <Radio aria-label="强制重建，仅保留来源版本" checked={decision === "force_replace"} disabled={submitting} name="draft-target" onChange={() => changeDecision("force_replace")} label="强制重建，仅保留来源版本" description="废弃当前活动草稿，新草稿只复制来源发布版本。" />
            </fieldset>
          </section>
        )}

        {targetPreview?.kind === "pointerless" && (
          <section className={styles.targetState}>
            <strong>目标日期只有历史版本，但没有活动草稿或当前发布指针。</strong>
            <p>当前移动 API 无法可靠表达这个目标状态，系统不会猜测或自动覆盖。</p>
          </section>
        )}

        {targetPreview?.kind === "invalid" && (
          <section className={styles.targetState}>
            <strong>目标指针状态不完整</strong><p>{targetPreview.message} 系统不会继续创建草稿。</p>
          </section>
        )}

        {targetPreview && decision && decision !== "client_cancel" && targetPreview.kind !== "pointerless" && targetPreview.kind !== "invalid" && (
          <label>移动原因<textarea className={controlStyles.control} disabled={submitting} maxLength={1000} onChange={(event) => { onReasonChange(event.target.value); }} required rows={3} value={reason} /></label>
        )}

        {mergeMatrix}

        {forceRebuild && (
          <Checkbox checked={forceConfirmed} disabled={submitting} onChange={(event) => { onForceConfirmedChange(event.target.checked); }} label="我确认目标活动草稿会被废弃，但审计记录会保留。" />
        )}

        {moveError && <StatusMessage kind="danger" title="操作未完成">{moveError}</StatusMessage>}
        <StatusMessage kind="warning" title="生效范围">这里只创建目标日期的审核草稿。来源发布数据在最终审核生效前不会被撤下。</StatusMessage>
        <footer>
          <Button variant="secondary" disabled={submitting} onClick={onClose} type="button">返回版本记录</Button>
          {decision === "client_cancel" ? (
            <Button variant="secondary" disabled={submitting} onClick={onClose} type="button">关闭且不创建移动草稿</Button>
          ) : commandReady ? (
            <Button variant={forceRebuild ? "danger" : "primary"} disabled={submitting || !reason.trim() || (forceRebuild && !forceConfirmed) || !mergeReady} type="submit" loading={submitting} loadingLabel="正在提交…">{submitLabel}</Button>
          ) : null}
        </footer>
  </CommandFrame>;
}

export function UndoMoveConfirmationView({ move, reason, onReasonChange, submitting, undoError, onClose, onSubmit }: CommandFormProps & { move: UndoablePublishedMoveResponse; undoError?: string }) {
  return <CommandFrame label="撤销跨日期移动确认" title="撤销跨日期移动" description="核对两个报告日的恢复范围" wide submitting={submitting} onClose={onClose} onSubmit={onSubmit}>
<p>系统将同时锁定两个报告日，并在一个事务内恢复两侧发布指针。</p>
        <div className={styles.route} aria-label="撤销后的日期恢复路线">
          <div>
            <span>恢复来源报告日</span>
            <strong>{move.source_report_date}</strong>
            <small>恢复版本 #{move.restore_source_version_id}</small>
          </div>
          <span aria-hidden="true">←</span>
          <div>
            <span>撤销目标报告日</span>
            <strong>{move.target_report_date}</strong>
            <small>{move.restore_target_version_id === null ? "恢复为无发布版本" : `恢复版本 #${move.restore_target_version_id}`}</small>
          </div>
        </div>

        <dl>
          <div><dt>当前目标版本</dt><dd>#{move.moved_target_version_id}</dd></div>
          <div><dt>原移动命令</dt><dd>#{move.move_command_id}</dd></div>
          <div><dt>移动完成时间</dt><dd>{formatTimestamp(move.completed_at)}</dd></div>
        </dl>
        <label>
          撤销原因
          <textarea className={controlStyles.control}
            disabled={submitting}
            maxLength={1000}
            onChange={(event) => {
              onReasonChange(event.target.value);
            }}
            required
            rows={4}
            value={reason}
          />
        </label>
        {undoError && <StatusMessage kind="danger" title="操作未完成">{undoError}</StatusMessage>}
        <StatusMessage kind="warning" title="生效范围">任一日期已有新发布或活动草稿时，服务器会拒绝整个操作，不会只恢复一侧。</StatusMessage>
        <footer>
          <Button variant="secondary" disabled={submitting} onClick={onClose} type="button">保留当前移动</Button>
          <Button variant="danger" disabled={submitting || !reason.trim()} loading={submitting} loadingLabel="正在提交…" type="submit">
            确认撤销跨日期移动
          </Button>
        </footer>
  </CommandFrame>;
}

export function RollbackConfirmationView({ current, target, reportDate, reportType, reason, onReasonChange, submitting, error, onClose, onSubmit }: CommandFormProps & {
  current: VersionSummaryResponse; target: VersionSummaryResponse; reportDate: string; reportType: VersionSummaryResponse["report_type"]; error?: string;
}) {
  return <CommandFrame label="管理员回滚确认" title={<>回滚到 v{target.version_no}</>} description="恢复已核验的历史发布版本" submitting={submitting} onClose={onClose} onSubmit={onSubmit}>
    <p>只切换 {reportDate} · {reportTypeLabel(reportType)} 的发布指针。</p>
    <dl><div><dt>当前发布</dt><dd>v{current.version_no}</dd></div><div><dt>回滚目标</dt><dd>v{target.version_no}</dd></div></dl>
    <label>回滚原因<textarea className={controlStyles.control} disabled={submitting} onChange={event => onReasonChange(event.target.value)} required rows={4} value={reason} /></label>
    {error && <StatusMessage kind="danger" title="回滚未完成">{error}</StatusMessage>}
    <StatusMessage kind="warning" title="生效范围">回滚不会删除当前版本；系统会追加一条发布事件，并立即让看板读取目标版本。</StatusMessage>
    <footer><Button disabled={submitting} onClick={onClose}>取消</Button><Button variant="danger" disabled={submitting || !reason.trim()} loading={submitting} loadingLabel="正在回滚…" type="submit">确认回滚到 v{target.version_no}</Button></footer>
  </CommandFrame>;
}
