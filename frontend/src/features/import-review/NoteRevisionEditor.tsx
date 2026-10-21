import { Button, Select } from "../../design-system";
import { useEffect, useState, type FormEvent } from "react";

type RevisableNote = {
  body: string;
  note_id: number;
  note_key: string;
  revision_number: number;
  visibility: "internal" | "viewer_visible";
};

type Props<T extends RevisableNote> = {
  busy: boolean;
  internalOnly?: boolean;
  note: T;
  onRevise: (
    note: T,
    body: string,
    visibility: "internal" | "viewer_visible",
  ) => Promise<void>;
};

export function NoteRevisionEditor<T extends RevisableNote>({ busy, internalOnly = false, note, onRevise }: Props<T>) {
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(note.body);
  const [visibility, setVisibility] = useState(internalOnly ? "internal" : note.visibility);
  const [error, setError] = useState<string>();

  useEffect(() => {
    setBody(note.body);
    setVisibility(internalOnly ? "internal" : note.visibility);
  }, [internalOnly, note.body, note.note_id, note.visibility]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    try {
      await onRevise(note, body, internalOnly ? "internal" : visibility);
      setEditing(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "备注修订未保存。");
    }
  };

  if (!editing) {
    return (
      <Button variant="quiet" disabled={busy} onClick={() => setEditing(true)} type="button">
        修订备注
      </Button>
    );
  }

  return (
    <form onSubmit={(event) => { void submit(event); }}>
      <label className="field-stack">
        修订后的备注
        <textarea
          aria-label={`修订备注 ${note.note_key}`}
          autoFocus
          maxLength={4096}
          onChange={(event) => setBody(event.target.value)}
          rows={3}
          value={body}
        />
      </label>
      {internalOnly ? (
        <p className="stage-placeholder">批次备注仅审核人员可见，不进入已发布版本的查看页面。</p>
      ) : (
        <label className="field-stack">
          可见范围
          <Select
            aria-label={`修订备注 ${note.note_key} 的可见范围`}
            onChange={(event) => setVisibility(event.target.value as typeof visibility)}
            value={visibility}
          >
            <option value="internal">仅审核人员</option>
            <option value="viewer_visible">查看人员可见</option>
          </Select>
        </label>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="dialog-actions">
        <Button variant="quiet" disabled={busy} onClick={() => { setEditing(false); setError(undefined); }} type="button">取消修订</Button>
        <Button variant="secondary" disabled={busy || !body.trim()} type="submit">保存新修订</Button>
      </div>
    </form>
  );
}
