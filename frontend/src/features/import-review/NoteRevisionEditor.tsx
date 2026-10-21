import { Button, FormField, Select, StatusBadge, StatusMessage } from "../../design-system";
import { useEffect, useRef, useState, type FormEvent } from "react";
import controlCss from "../../design-system/Control.module.css";
import css from "./NoteRevisionEditor.module.css";

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
  const [pending, setPending] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);
  const locked = busy || pending;

  useEffect(() => {
    setBody(note.body);
    setVisibility(internalOnly ? "internal" : note.visibility);
  }, [internalOnly, note.body, note.note_id, note.visibility]);

  useEffect(() => {
    if (editing) wasEditing.current = true;
    else if (wasEditing.current && !locked) {
      trigger.current?.focus();
      wasEditing.current = false;
    }
  }, [editing, locked]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (locked || !body.trim()) return;
    setError(undefined);
    setPending(true);
    try {
      await onRevise(note, body, internalOnly ? "internal" : visibility);
      setEditing(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "备注修订未保存。");
    } finally {
      setPending(false);
    }
  };

  if (!editing) {
    return (
      <Button ref={trigger} variant="quiet" disabled={locked} onClick={() => setEditing(true)} type="button">
        修订备注
      </Button>
    );
  }

  return (
    <form aria-label={`备注修订 ${note.note_key}`} className={css.revisionForm} onSubmit={(event) => { void submit(event); }}>
      <header className={css.heading}><strong>修订备注</strong><StatusBadge label={`当前第 ${note.revision_number} 版`} tone="quiet" /></header>
      <p className={css.hint}>保存会追加新修订；已有内容仍保留在审计历史中。</p>
      <FormField label="修订后的备注" hint={`${body.length} / 4096 字符`}>
        <textarea
          aria-label={`修订备注 ${note.note_key}`}
          autoFocus
          className={controlCss.control}
          disabled={locked}
          maxLength={4096}
          onChange={(event) => setBody(event.target.value)}
          rows={3}
          value={body}
        />
      </FormField>
      {internalOnly ? (
        <p className={css.hint}>批次备注仅审核人员可见，不进入已发布版本的查看页面。</p>
      ) : (
        <FormField label="可见范围" hint="此设置适用于本次新修订。">
          <Select
            aria-label={`修订备注 ${note.note_key} 的可见范围`}
            disabled={locked}
            onChange={(event) => setVisibility(event.target.value as typeof visibility)}
            value={visibility}
          >
            <option value="internal">仅审核人员</option>
            <option value="viewer_visible">查看人员可见</option>
          </Select>
        </FormField>
      )}
      {error && <StatusMessage kind="danger" title="备注修订未保存">{error} 修订内容已保留，请核对后重试。</StatusMessage>}
      <div className={css.revisionActions}>
        <Button variant="quiet" disabled={locked} onClick={() => { setEditing(false); setError(undefined); }} type="button">取消修订</Button>
        <Button aria-label={locked ? "正在保存新修订" : undefined} variant="secondary" loading={locked} loadingLabel="正在保存…" disabled={locked || !body.trim()} type="submit">保存新修订</Button>
      </div>
    </form>
  );
}
