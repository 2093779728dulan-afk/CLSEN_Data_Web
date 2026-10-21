import type { FormEvent, ReactNode } from "react";
import type { ImportBatchNoteResponse } from "../../api/generated";
import { Button, EmptyState, Skeleton, StatusBadge, StatusMessage } from "../../design-system";
import css from "./ImportEvidence.module.css";

export type BatchNotesViewProps = {
  batchId: number; expanded: boolean; contentId: string;
  loadState: "idle" | "loading" | "loaded" | "error";
  notes: ImportBatchNoteResponse[];
  body: string; busy: boolean; busyAction?: "append" | "revise";
  loadError?: string; actionError?: string; notice?: string;
  onToggle: () => void; onRetry: () => void; onBodyChange: (value: string) => void;
  onAppend: (event: FormEvent) => void;
  renderRevision: (note: ImportBatchNoteResponse) => ReactNode;
};

export function BatchNotesView({ batchId, expanded, contentId, loadState, notes, body, busy, busyAction, loadError, actionError, notice, onToggle, onRetry, onBodyChange, onAppend, renderRevision }: BatchNotesViewProps) {
  return <section aria-label={`导入批次 #${batchId} 备注`} className={css.notes}>
    <header className={css.heading}>
      <div className={css.identity}><p className={css.kicker}>原表级审核证据 · 批次 #{batchId}</p><h3>批次备注</h3><p>记录文件整体的核对结论或补充说明，不改变原始 CSV。</p></div>
      <Button aria-controls={contentId} aria-expanded={expanded} variant="secondary" onClick={onToggle} type="button">{expanded ? "收起批次备注" : "管理批次备注"}</Button>
    </header>
    {expanded && <div className={css.notesBody} id={contentId}>
      <section aria-label="已有批次备注" className={css.ledger}>
        <header className={css.ledgerHeading}><h4>已记录备注</h4>{loadState === "loaded" && <StatusBadge label={`${notes.length} 条`} tone="quiet" />}</header>
        {loadState === "loading" && <div role="status" aria-label="正在读取批次备注"><p className={css.hint}>正在读取批次备注…</p><Skeleton lines={3} /></div>}
        {loadState === "error" && <StatusMessage kind="danger" title="批次备注读取未完成">{loadError}<Button variant="quiet" onClick={onRetry} type="button">重新加载批次备注</Button></StatusMessage>}
        {loadState === "loaded" && notes.length === 0 && <EmptyState title="这个导入批次还没有备注。" description="核对文件后，在下方追加说明。" />}
        {notes.length > 0 && <ul className={css.noteList}>{notes.map(note => <li key={note.note_key}>
          <div className={css.noteMeta}><span>{note.author_username} · 仅审核人员</span><StatusBadge label={`第 ${note.revision_number} 版`} tone="quiet" /></div>
          <p className={css.noteBody}>{note.body}</p>
          {renderRevision(note)}
        </li>)}</ul>}
      </section>
      <form className={css.appendForm} onSubmit={onAppend}>
        <div><p className={css.kicker}>追加记录</p><h4>补充批次说明</h4></div>
        <label className={css.field}>批次备注内容<textarea maxLength={4096} onChange={event => onBodyChange(event.target.value)} rows={3} value={body} /></label>
        <p className={css.hint}>批次备注仅审核人员可见，不进入已发布版本的查看页面。</p>
        {actionError && <StatusMessage kind="danger" title="备注未保存">{actionError}</StatusMessage>}
        {notice && <StatusMessage kind="success" title="备注操作结果">{notice}</StatusMessage>}
        <Button variant="secondary" loading={busyAction === "append"} disabled={busy || !body.trim()} type="submit">{busyAction === "append" ? "正在追加…" : "追加批次备注"}</Button>
      </form>
    </div>}
  </section>;
}
