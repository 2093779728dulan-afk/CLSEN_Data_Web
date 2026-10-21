import surfaceCss from "./ReviewSurfaces.module.css";
import { Button } from "../../design-system";
import { useState, type FormEvent } from "react";

import {
  StableOperationKeyStore,
  requestApi,
  writeApi,
} from "../../api/client";
import type {
  CreateImportBatchNoteRequest,
  ImportBatchNoteResponse,
  ReviseImportBatchNoteRequest,
} from "../../api/generated";
import { NoteRevisionEditor } from "./NoteRevisionEditor";

type Props = {
  batchId: number;
};

type LoadState = "idle" | "loading" | "loaded" | "error";

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "批次备注操作未完成。";
}

export function BatchNotePanel({ batchId }: Props) {
  return <BatchNotes key={batchId} batchId={batchId} />;
}

function BatchNotes({ batchId }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [notes, setNotes] = useState<ImportBatchNoteResponse[]>([]);
  const [body, setBody] = useState("");
  const [busyAction, setBusyAction] = useState<"append" | "revise">();
  const [loadError, setLoadError] = useState<string>();
  const [actionError, setActionError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [operationKeys] = useState(() => new StableOperationKeyStore());
  const contentId = `batch-note-panel-${batchId}`;

  const loadNotes = async () => {
    setLoadState("loading");
    setLoadError(undefined);
    try {
      const result = await requestApi<ImportBatchNoteResponse[]>(`/api/imports/${batchId}/notes`);
      setNotes(result);
      setLoadState("loaded");
    } catch (caught) {
      setLoadError(errorMessage(caught));
      setLoadState("error");
    }
  };

  const toggleExpanded = () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (loadState === "idle" || loadState === "error") void loadNotes();
  };

  const appendNote = async (event: FormEvent) => {
    event.preventDefault();
    const trimmedBody = body.trim();
    if (!trimmedBody) return;
    const path = `/api/imports/${batchId}/notes`;
    const requestBody = {
      body: trimmedBody,
      visibility: "internal",
    } satisfies CreateImportBatchNoteRequest;
    const operationKey = operationKeys.forCommand("append-batch-note", path, requestBody);
    setBusyAction("append");
    setActionError(undefined);
    setNotice(undefined);
    try {
      await writeApi<Record<string, unknown>>(path, { body: requestBody, operationKey });
      operationKeys.complete("append-batch-note", operationKey);
      setBody("");
      setNotice("批次备注已追加，历史内容不会被覆盖。");
      await loadNotes();
    } catch (caught) {
      setActionError(errorMessage(caught));
    } finally {
      setBusyAction(undefined);
    }
  };

  const reviseNote = async (
    note: ImportBatchNoteResponse,
    revisedBody: string,
  ) => {
    const path = `/api/imports/${batchId}/notes/${encodeURIComponent(note.note_key)}/revisions`;
    const requestBody = {
      body: revisedBody.trim(),
      visibility: "internal",
      expected_note_id: note.note_id,
      expected_revision_number: note.revision_number,
    } satisfies ReviseImportBatchNoteRequest;
    const operationKey = operationKeys.forCommand(`revise-batch-note:${note.note_key}`, path, requestBody);
    setBusyAction("revise");
    setActionError(undefined);
    setNotice(undefined);
    try {
      await writeApi<Record<string, unknown>>(path, { body: requestBody, operationKey });
      operationKeys.complete(`revise-batch-note:${note.note_key}`, operationKey);
      setNotice(`批次备注 ${note.note_key} 已保存为新修订，旧内容仍可审计。`);
      await loadNotes();
    } catch (caught) {
      setActionError(errorMessage(caught));
      throw caught;
    } finally {
      setBusyAction(undefined);
    }
  };

  const busy = busyAction !== undefined || loadState !== "loaded";

  return (
    <section aria-label={`导入批次 #${batchId} 备注`} className={surfaceCss["batch-note-panel"]}>
      <header className={surfaceCss["batch-note-panel__summary"]}>
        <div className={surfaceCss["batch-note-panel__identity"]} aria-hidden="true">
          <span>批次</span>
          <strong>#{batchId}</strong>
        </div>
        <div>
          <p className="section-kicker">原表级审核证据</p>
          <h3>批次备注</h3>
          <p>记录文件整体的核对结论或补充说明，不改变原始 CSV。</p>
        </div>
        <Button
          aria-controls={contentId}
          aria-expanded={expanded}
          variant="secondary"
          onClick={toggleExpanded}
          type="button"
        >
          {expanded ? "收起批次备注" : "管理批次备注"}
        </Button>
      </header>

      {expanded && (
        <div className={surfaceCss["batch-note-panel__body"]} id={contentId}>
          <section aria-label="已有批次备注" className={surfaceCss["batch-note-panel__ledger"]}>
            <header>
              <h4>已记录备注</h4>
              {loadState === "loaded" && <span>{notes.length} 条</span>}
            </header>
            {loadState === "loading" && <p className="stage-placeholder" role="status">正在读取批次备注…</p>}
            {loadState === "error" && (
              <div className={surfaceCss["batch-note-panel__load-error"]}>
                <p className="form-error" role="alert">{loadError}</p>
                <Button variant="quiet" onClick={() => { void loadNotes(); }} type="button">重新加载批次备注</Button>
              </div>
            )}
            {loadState === "loaded" && notes.length === 0 && <p className="stage-placeholder">这个导入批次还没有备注。</p>}
            {notes.length > 0 && (
              <ul className={surfaceCss["batch-note-list"]}>
                {notes.map((note) => (
                  <li key={note.note_key}>
                    <p>{note.body}</p>
                    <span>{note.author_username} · 仅审核人员 · 第 {note.revision_number} 版</span>
                    <NoteRevisionEditor busy={busy} internalOnly note={note} onRevise={reviseNote} />
                  </li>
                ))}
              </ul>
            )}
          </section>

          <form className={surfaceCss["batch-note-panel__form"]} onSubmit={(event) => { void appendNote(event); }}>
            <div>
              <p className="section-kicker">追加记录</p>
              <h4>补充批次说明</h4>
            </div>
            <label className="field-stack">
              批次备注内容
              <textarea maxLength={4096} onChange={(event) => setBody(event.target.value)} rows={3} value={body} />
            </label>
            <p className="stage-placeholder">批次备注仅审核人员可见，不进入已发布版本的查看页面。</p>
            {actionError && <p className="form-error" role="alert">{actionError}</p>}
            {notice && <p aria-live="polite" className="form-notice">{notice}</p>}
            <Button variant="secondary" disabled={busy || !body.trim()} type="submit">
              {busyAction === "append" ? "正在追加…" : "追加批次备注"}
            </Button>
          </form>
        </div>
      )}
    </section>
  );
}
