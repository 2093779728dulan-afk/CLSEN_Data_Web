import { BatchNotesView } from "./BatchNotesView";
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

  return <BatchNotesView
    batchId={batchId} expanded={expanded} contentId={contentId} loadState={loadState} notes={notes}
    body={body} busy={busy} busyAction={busyAction} loadError={loadError} actionError={actionError} notice={notice}
    onToggle={toggleExpanded} onRetry={() => { void loadNotes(); }} onBodyChange={setBody}
    onAppend={(event) => { void appendNote(event); }}
    renderRevision={(note) => <NoteRevisionEditor busy={busy} internalOnly note={note} onRevise={reviseNote} />}
  />;
}
