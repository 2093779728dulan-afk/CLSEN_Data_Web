import type { ReactNode } from "react";
import { Button, Checkbox, ErrorState, Input, Radio, Select, Skeleton, StatusBadge, StatusMessage } from "../../design-system";
import type { DraftHead, ReviewWorkspace, ValidationRun, VersionSummary } from "../../api/types";
import type { DraftReviewContext } from "./workflowTypes";
import { auditOperatorLabel, type AuditOperator } from "./auditReason";
import { reportTypeLabel } from "./draftReviewPresentation";
import css from "./DraftReviewView.module.css";

export type DraftReviewViewProps = {
  context: DraftReviewContext; head: DraftHead; published: boolean; workspace?: ReviewWorkspace; validation?: ValidationRun;
  counts?: { blocking: number; warning: number }; busyAction?: string; error?: string; notice?: string; operator?: AuditOperator;
  note: string; noteVisibility: "internal" | "viewer_visible"; readyReason: string; targetDate: string; moveReason: string;
  draftMovePreview?: { kind: "empty"; reportDate: string } | { kind: "active_draft"; activeDraft: VersionSummary; publication?: VersionSummary; reportDate: string } | { kind: "published"; publication: VersionSummary; reportDate: string };
  draftMoveDecision?: "merge" | "replace" | "cancel"; draftMoveMerge: { ready: boolean };
  discardReason: string; discardConfirmed: boolean; reparseBatchId?: number; canFinalizePublishedMove: boolean;
  onDiscarded?: () => void; onReparseSource?: (id: number) => Promise<void>;
  setNote: (v: string) => void; setNoteVisibility: (v: "internal" | "viewer_visible") => void; setReadyReason: (v: string) => void;
  changeTargetDate: (v: string) => void; changeMoveReason: (v: string) => void; changeDraftMoveDecision: (v: "merge" | "replace" | "cancel") => void;
  setDiscardReason: (v: string) => void; setDiscardConfirmed: (v: boolean) => void; setReparseBatchId: (v: number) => void;
  saveNote: () => Promise<void> | void; runValidation: () => Promise<void> | void; markReady: () => Promise<void> | void;
  inspectDraftMoveTarget: () => Promise<void> | void; confirmDraftMoveDecision: () => Promise<void> | void;
  discardDraft: (reparse: boolean) => Promise<void> | void; resetDiscardOperation: () => void; setShowPublish: (v: boolean) => void; onRefresh: () => void;
  dataTable?: ReactNode; versionNotes?: ReactNode; mergeMatrix?: ReactNode; publicationDialog?: ReactNode;
};

export function DraftReviewView({ context, head, published, workspace, validation, counts, busyAction, error, notice, operator, note, noteVisibility, readyReason, targetDate, moveReason, draftMovePreview, draftMoveDecision, draftMoveMerge, discardReason, discardConfirmed, reparseBatchId, canFinalizePublishedMove, onDiscarded, onReparseSource, setNote, setNoteVisibility, setReadyReason, changeTargetDate, changeMoveReason, changeDraftMoveDecision, setDiscardReason, setDiscardConfirmed, setReparseBatchId, saveNote, runValidation, markReady, inspectDraftMoveTarget, confirmDraftMoveDecision, discardDraft, resetDiscardOperation, setShowPublish, onRefresh, dataTable, versionNotes, mergeMatrix, publicationDialog }: DraftReviewViewProps) {
  if (published) {
    return (
      <section aria-live="polite" className={css["publication-receipt"]}>
        <span className={css["publication-receipt__seal"]}>发</span>
        <div><p className="section-kicker">发布回执</p><h2>{context.publicationMode === "published_move" ? `跨日期移动 v${head.version_no} 已生效` : `版本 v${head.version_no} 已发布`}</h2><p>{context.publicationMode === "published_move" && context.publishedMove ? `${context.publishedMove.source_report_date} → ${context.reportDate} 已原子切换发布指针。` : `${context.reportDate} · ${reportTypeLabel(context.reportType)} 已进入只读看板。`}</p></div>
      </section>
    );
  }

  return (
    <section className={css["draft-workbench"]}>
      <header className={css["workbench-heading"]}>
        <div>
          <p className="section-kicker">差异优先审核</p>
          <h2>草稿审核 · v{head.version_no}</h2>
          <p>{context.reportDate} · {reportTypeLabel(context.reportType)} · 数据修订 r{head.data_revision} / 审核修订 r{head.review_revision}</p>
        </div>
        <StatusBadge label={head.status === "draft" ? "草稿" : "待发布"} tone={head.status === "draft" ? "quiet" : "good"} />
      </header>

      {workspace ? dataTable : error ? <ErrorState title="无法读取草稿" description={error} action={<Button onClick={onRefresh}>重新读取草稿</Button>} /> : <div className={css.loading} role="status"><p>正在读取草稿行、差异与校验问题…</p><Skeleton lines={4} /></div>}

      <div className={css["review-grid"]}>
        <section className={css["review-stage"]}>
          <div className={css["review-stage__heading"]}><span>01</span><div><h3>版本备注</h3><p>补充审核依据；备注只追加，不覆盖历史。</p></div></div>
          {versionNotes}
          <label className="field-stack">备注内容<textarea onChange={(event) => setNote(event.target.value)} rows={3} value={note} /></label>
          <label className="field-stack">可见范围<Select onChange={(event) => setNoteVisibility(event.target.value as typeof noteVisibility)} value={noteVisibility}><option value="internal">仅审核人员</option><option value="viewer_visible">查看人员可见</option></Select></label>
          <Button variant="secondary" loading={busyAction === "note"} disabled={busyAction === "note" || !note.trim()} onClick={() => { void saveNote(); }} type="button">{busyAction === "note" ? "正在保存…" : "追加备注"}</Button>
        </section>

        <section className={css["review-stage"]}>
          <div className={css["review-stage__heading"]}><span>02</span><div><h3>校验草稿</h3><p>检查行数、合计、字段格式和来源差异。</p></div></div>
          {!validation ? (
            <Button variant="primary" loading={busyAction === "validation"} disabled={busyAction === "validation" || head.status !== "draft"} onClick={() => { void runValidation(); }} type="button">{busyAction === "validation" ? "正在校验…" : "运行草稿校验"}</Button>
          ) : (
            <div className={css["validation-receipt"]} aria-live="polite">
              <div className={css["validation-receipt__counts"]}><strong className={counts?.blocking ? css["count--blocking"] : ""}>阻断项 {counts?.blocking}</strong><strong className={counts?.warning ? css["count--warning"] : ""}>警告 {counts?.warning}</strong><strong>行数 {validation.summary.row_count}</strong></div>
              <dl>{Object.entries(validation.summary.totals).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
              <Button variant="quiet" loading={busyAction === "validation"} disabled={busyAction === "validation" || head.status !== "draft"} onClick={() => { void runValidation(); }} type="button">重新校验</Button>
            </div>
          )}
          {counts && counts.blocking > 0 && <p className={`${css["gate-message"]} ${css["gate-message--blocking"]}`}>先修正阻断项，再重新运行校验。</p>}
          {counts && counts.blocking === 0 && counts.warning > 0 && <p className={`${css["gate-message"]} ${css["gate-message--warning"]}`}>需要逐项确认警告后再继续发布。</p>}
        </section>

        <section className={css["review-stage"]}>
          <div className={css["review-stage__heading"]}><span>03</span><div><h3>确认校验结果</h3><p>核对报告日期、类型和校验合计后留痕确认。</p></div></div>
          {validation && validation.result === "passed" && counts?.blocking === 0 && counts.warning === 0 && head.status === "draft" ? <>
            <label className="field-stack">审核确认说明<textarea onChange={(event) => setReadyReason(event.target.value)} rows={3} value={readyReason} /></label>
            {operator && <p className="stage-placeholder">操作人来源：当前登录会话 · {auditOperatorLabel(operator)}。</p>}
            <Button variant="primary" loading={busyAction === "ready"} disabled={busyAction === "ready" || !readyReason.trim()} onClick={() => { void markReady(); }} type="button">{busyAction === "ready" ? "正在确认…" : "确认结果并标记待发布"}</Button>
          </> : head.status === "ready_for_publish" ? <p className={`${css["gate-message"]} ${css["gate-message--passed"]}`}>已锁定本次校验回执，可以进入最终发布确认。</p> : <p className="stage-placeholder">先完成草稿校验，通过后即可填写确认说明。</p>}
        </section>
      </div>

      <details className={css["draft-maintenance"]} name="draft-maintenance">
        <summary>调整草稿日期</summary>
        <p>系统会先读取目标日期的活动草稿和发布版本；有冲突时由你明确选择，不会自动覆盖。</p>
        <div className={css["draft-maintenance__form"]}>
          <label className="field-stack">目标报告日<Input onChange={(event) => changeTargetDate(event.target.value)} type="date" value={targetDate} /></label>
          <label className="field-stack field-stack--wide">移动原因<textarea onChange={(event) => changeMoveReason(event.target.value)} rows={3} value={moveReason} /></label>
          {operator && <p className={`stage-placeholder ${css["draft-maintenance__operator"]}`}>默认说明已带入当前操作人和草稿来源；目标日期会随本次命令一并记录。</p>}
          {(!draftMovePreview || draftMovePreview.kind === "empty") && <Button variant="secondary" loading={busyAction === "move"} disabled={busyAction === "move" || targetDate === context.reportDate || !moveReason.trim()} onClick={() => { void inspectDraftMoveTarget(); }} type="button">{busyAction === "move" ? "正在检查目标日…" : "检查目标日期"}</Button>}
        </div>
        {draftMovePreview && draftMovePreview.kind !== "empty" && (
          <fieldset className={css["target-conflict"]}>
            <legend>目标日期已有数据，请选择处理方式</legend>
            <div className={css["target-conflict__ledger"]}>
              <span>{draftMovePreview.reportDate} · {reportTypeLabel(context.reportType)}</span>
              {draftMovePreview.kind === "active_draft" && <strong>活动草稿 v{draftMovePreview.activeDraft.version_no}</strong>}
              {draftMovePreview.kind === "active_draft" && draftMovePreview.publication && <strong>发布版本 v{draftMovePreview.publication.version_no}</strong>}
              {draftMovePreview.kind === "published" && <strong>发布版本 v{draftMovePreview.publication.version_no}</strong>}
            </div>
            <div className={css["target-choice"]}><Radio aria-label={draftMovePreview.kind === "active_draft" ? "合并到目标活动草稿" : "合并目标发布版本"} checked={draftMoveDecision === "merge"} disabled={busyAction === "move"} name="draft-move-decision" onChange={() => changeDraftMoveDecision("merge")} label={<> {draftMovePreview.kind === "active_draft" ? "合并到目标活动草稿" : "合并目标发布版本"} </>} description={<> 保留目标数据并加入当前草稿。逐行冲突不会自动覆盖；当前没有逐行决定时，服务端会阻断并要求人工处理。 </>} /></div>
            {draftMovePreview.kind === "published" && <div className={css["target-choice"]}><Radio aria-label="替换目标发布版本" checked={draftMoveDecision === "replace"} disabled={busyAction === "move"} name="draft-move-decision" onChange={() => changeDraftMoveDecision("replace")} label={<> 替换目标发布版本 </>} description={<> 移动后的草稿仅采用当前草稿数据；目标发布版本仍保留在版本历史中。 </>} /></div>}
            <div className={css["target-choice"]}><Radio aria-label="取消，保留当前所属日期" checked={draftMoveDecision === "cancel"} disabled={busyAction === "move"} name="draft-move-decision" onChange={() => changeDraftMoveDecision("cancel")} label={<> 取消，保留当前所属日期 </>} description={<> 不移动草稿，不发送写请求。 </>} /></div>
            {draftMoveDecision === "merge" && mergeMatrix}
            <Button variant={draftMoveDecision === "cancel" ? "secondary" : "primary"} loading={busyAction === "move"} disabled={busyAction === "move" || !draftMoveDecision || !moveReason.trim() || (draftMoveDecision === "merge" && !draftMoveMerge.ready)} onClick={() => { void confirmDraftMoveDecision(); }} type="button">{busyAction === "move" ? "正在处理…" : draftMoveDecision === "cancel" ? "确认取消" : "按所选方式更改日期"}</Button>
          </fieldset>
        )}
      </details>

      {(onDiscarded || onReparseSource) && (
        <details className={`${css["draft-maintenance"]} ${css["draft-disposition"]}`} name="draft-maintenance">
          <summary>重新解析或废弃草稿</summary>
          <p>旧草稿、人工修改和备注会完整保留在审计历史中，但不会自动套用到新的解析结果。</p>
          {onReparseSource && workspace && workspace.source_batches.length > 0 && <label className="field-stack">重新解析的来源批次<Select onChange={(event) => setReparseBatchId(Number(event.target.value))} value={reparseBatchId}>{workspace.source_batches.map((source) => <option key={source.batch_id} value={source.batch_id}>导入批次 #{source.batch_id}</option>)}</Select></label>}
          <label className="field-stack">处置原因<textarea onChange={(event) => { setDiscardReason(event.target.value); resetDiscardOperation(); }} rows={3} value={discardReason} /></label>
          {operator && <p className="stage-placeholder">操作人来源：当前登录会话 · {auditOperatorLabel(operator)}。</p>}
          <Checkbox checked={discardConfirmed} onChange={(event) => setDiscardConfirmed(event.target.checked)} label="我确认当前草稿将被废弃，历史记录不会删除。" />
          <div className={`dialog-actions ${css["draft-disposition__actions"]}`}>
            {onDiscarded && <Button variant="secondary" loading={busyAction === "discard"} disabled={busyAction === "discard" || !discardConfirmed || !discardReason.trim()} onClick={() => { void discardDraft(false); }} type="button">只废弃当前草稿</Button>}
            {onReparseSource && reparseBatchId && <Button variant="primary" loading={busyAction === "discard"} disabled={busyAction === "discard" || !discardConfirmed || !discardReason.trim()} onClick={() => { void discardDraft(true); }} type="button">废弃并重新解析来源文件</Button>}
          </div>
        </details>
      )}

      {notice && <StatusMessage kind="success" title="操作结果">{notice}</StatusMessage>}
      {workspace && error && <StatusMessage kind="danger" title="操作未完成">{error}</StatusMessage>}
      {head.status === "ready_for_publish" && validation && (
        context.publicationMode === "published_move" && !canFinalizePublishedMove ? (
          <div aria-live="polite" className={css["publish-gate"]} role="status"><div><p className="section-kicker">04 · 管理员生效</p><strong>审核已完成，需管理员最终生效</strong><span>这是已发布数据的跨日期移动。来源日期仍保持发布，当前账号不能使用普通发布完成切换。</span></div></div>
        ) : context.publicationMode === "published_move" && !context.publishedMove ? (
          <div className={css["publish-gate"]} role="alert"><div><p className="section-kicker">04 · 管理员生效</p><strong>无法恢复跨日期移动上下文</strong><span>请刷新当前日期；在服务端上下文恢复前不会开放普通发布。</span></div></div>
        ) : (
          <div className={css["publish-gate"]}><div><p className="section-kicker">04 · {context.publicationMode === "published_move" ? "跨日期生效" : "发布"}</p><strong>{context.publicationMode === "published_move" ? "跨日期移动已通过审核闸门" : "草稿已通过审核闸门"}</strong><span>{context.publicationMode === "published_move" ? "最终确认会同时切换来源和目标日期的发布指针。" : "最后一次确认不会修改数据，只切换该日期的发布指针。"}</span></div><Button variant="primary" onClick={() => setShowPublish(true)} type="button">{context.publicationMode === "published_move" ? "打开跨日期生效确认" : "打开发布确认"}</Button></div>
        )
      )}
      {publicationDialog}
    </section>
  );
}
