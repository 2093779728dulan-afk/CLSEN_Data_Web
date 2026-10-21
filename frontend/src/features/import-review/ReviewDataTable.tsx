import css from "./ReviewDataTable.module.css";
import cellCss from "./CellReviewDrawer.module.css";
import rowCss from "./RowReviewDrawer.module.css";
import controlCss from "../../design-system/Control.module.css";
import { Button, Checkbox, Dialog, EmptyState, FormField, Input, Pagination, SearchInput, Select, StatusBadge, StatusMessage } from "../../design-system";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import type {
  ReviewCell,
  ReviewFieldContract,
  ReviewIssue,
  ReviewNote,
  ReviewRow,
  ReviewWorkspace,
  TypedFieldValue,
} from "../../api/types";
import { IssueReviewPanel } from "./IssueReviewPanel";
import { NoteRevisionEditor } from "./NoteRevisionEditor";
import { auditOperatorLabel, defaultAuditReason, type AuditOperator } from "./auditReason";

type RestoreSource =
  | { source_kind: "previous"; field_change_id: number }
  | { source_kind: "parent"; parent_version_id: number }
  | { source_kind: "source"; source_batch_id: number; parsed_source_row_id: number };

type Props = {
  busy: boolean;
  onAddRow: (
    sourceBatchId: number,
    values: Record<string, TypedFieldValue>,
    reason: string,
  ) => Promise<void>;
  onAddCellNote: (
    row: ReviewRow,
    cell: ReviewCell,
    body: string,
    visibility: "internal" | "viewer_visible",
  ) => Promise<void>;
  onAddRowNote: (
    row: ReviewRow,
    body: string,
    visibility: "internal" | "viewer_visible",
  ) => Promise<void>;
  onChangeRowState: (
    row: ReviewRow,
    operation: "exclude" | "restore",
    reason: string,
  ) => Promise<void>;
  onPageChange: (page: number) => void;
  onRestoreField: (
    row: ReviewRow,
    cell: ReviewCell,
    source: RestoreSource,
    reason: string,
  ) => Promise<void>;
  onReviewIssue: (
    issue: ReviewIssue,
    action: "acknowledge" | "resolve" | "reopen",
    comment: string,
  ) => Promise<void>;
  onReviseNote: (
    note: ReviewNote,
    body: string,
    visibility: "internal" | "viewer_visible",
  ) => Promise<void>;
  onSetField: (
    row: ReviewRow,
    cell: ReviewCell,
    value: TypedFieldValue,
    reason: string,
  ) => Promise<void>;
  operator?: AuditOperator;
  workspace: ReviewWorkspace;
};

function displayValue(value: TypedFieldValue | null) {
  if (!value || value.type === "null" || value.value === null) return "—";
  return String(value.value);
}

function editValue(contract: ReviewFieldContract, raw: string, useNull: boolean): TypedFieldValue {
  if (useNull) return { type: "null", value: null };
  if (contract.kind === "integer") {
    if (!raw.trim()) throw new Error("请输入有效整数。");
    const parsed = Number(raw);
    if (!Number.isSafeInteger(parsed)) throw new Error("请输入有效整数。");
    return { type: "integer", value: parsed };
  }
  if (contract.kind === "decimal") {
    if (!/^-?(?:\d+|\d*\.\d+)$/.test(raw.trim())) throw new Error("请输入有效小数。");
    return { type: "decimal", value: raw.trim() };
  }
  if (contract.kind === "utc_datetime") {
    if (!raw.endsWith("Z") || Number.isNaN(Date.parse(raw))) throw new Error("请输入以 Z 结尾的 UTC 时间。");
    return { type: "utc_datetime", value: raw };
  }
  return { type: "text", value: raw };
}

function CellDrawer({
  busy,
  cell,
  contract,
  onAddCellNote,
  onClose,
  onRestoreField,
  onReviseNote,
  onSetField,
  operator,
  row,
  source,
}: {
  busy: boolean;
  cell: ReviewCell;
  contract: ReviewFieldContract;
  onAddCellNote: Props["onAddCellNote"];
  onClose: () => void;
  onRestoreField: Props["onRestoreField"];
  onReviseNote: Props["onReviseNote"];
  onSetField: Props["onSetField"];
  operator?: AuditOperator;
  row: ReviewRow;
  source: string;
}) {
  const [rawValue, setRawValue] = useState(displayValue(cell.current) === "—" ? "" : displayValue(cell.current));
  const [useNull, setUseNull] = useState(cell.current.type === "null");
  const editReasonDefault = defaultAuditReason(operator, `修改第 ${row.row_ordinal} 行字段 ${cell.field_name}`, source);
  const restoreReasonDefault = defaultAuditReason(operator, `恢复第 ${row.row_ordinal} 行字段 ${cell.field_name}`, source);
  const [editReason, setEditReason] = useState(editReasonDefault);
  const [restoreReason, setRestoreReason] = useState(restoreReasonDefault);
  const [parentVersionId, setParentVersionId] = useState(cell.parent_restore_options[0]?.parent_version_id ?? 0);
  const [note, setNote] = useState("");
  const [noteVisibility, setNoteVisibility] = useState<"internal" | "viewer_visible">("internal");
  const [error, setError] = useState<string>();
  const currentValueType = cell.current.type;
  const currentValue = cell.current.value;

  useEffect(() => {
    setRawValue(currentValue === null ? "" : String(currentValue));
    setUseNull(currentValueType === "null");
  }, [currentValue, currentValueType]);

  useEffect(() => {
    setEditReason(editReasonDefault);
    setRestoreReason(restoreReasonDefault);
  }, [editReasonDefault, restoreReasonDefault]);

  const submitEdit = async () => {
    setError(undefined);
    try {
      await onSetField(row, cell, editValue(contract, rawValue, useNull), editReason);
      setEditReason(editReasonDefault);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "字段修改未完成。");
    }
  };

  const restore = async (source: RestoreSource) => {
    setError(undefined);
    try {
      await onRestoreField(row, cell, source, restoreReason);
      setRestoreReason(restoreReasonDefault);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "恢复操作未完成。");
    }
  };

  const addNote = async () => {
    setError(undefined);
    try {
      await onAddCellNote(row, cell, note, noteVisibility);
      setNote("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "备注未保存。");
    }
  };

  const latestChange = cell.history[0];
  return (
    <Dialog open accessibleLabel="字段对照" presentation="drawer" closeLabel="关闭字段对照" dismissDisabled={busy}
      title={<>{cell.field_name}<span className={cellCss.rowLabel}>第 {row.row_ordinal} 行</span></>}
      description="核对源文件、版本基础与当前草稿。修改、恢复及备注分别保留记录。" eyebrow="字段核对"
      onOpenChange={open => { if (!open && !busy) onClose(); }}>
      <div aria-label="字段对照内容" role="region" tabIndex={busy ? 0 : undefined} className={cellCss.content}>
        <div className={cellCss.identity}><span>行 ID #{row.row_id} · 字段 {cell.field_name}</span><StatusBadge label={cell.changed_from_source ? "与源文件不同" : "与源文件一致"} tone={cell.changed_from_source ? "warn" : "quiet"} /></div>
        <dl className={cellCss.comparison}>
          <div><dt>源文件值</dt><dd>{displayValue(cell.source)}</dd></div>
          <div><dt>版本基础值</dt><dd>{displayValue(cell.base)}</dd></div>
          <div className={cellCss.current}><dt>当前草稿值</dt><dd>{displayValue(cell.current)}</dd></div>
        </dl>
        <p className={cellCss.contract}>{contract.kind} · {contract.nullable ? "允许空值" : "必填"}{contract.scale !== null ? ` · ${contract.scale} 位小数` : ""}</p>
        {error && <StatusMessage kind="danger" title="字段操作未完成">{error}</StatusMessage>}
        {contract.editable ? <section className={cellCss.section} aria-label="修正当前值"><h3>修正当前值</h3>
          <FormField label="当前值" hint="保存只修改当前草稿字段；原始值仍保留。"><Input disabled={busy || useNull} onChange={(event) => setRawValue(event.target.value)} value={rawValue} /></FormField>
          {contract.nullable && <Checkbox label="设为空值" checked={useNull} disabled={busy} onChange={(event) => setUseNull(event.target.checked)} />}
          <FormField label="修改原因"><textarea className={controlCss.control} disabled={busy} onChange={(event) => setEditReason(event.target.value)} rows={3} value={editReason} /></FormField>
          <Button variant="primary" loading={busy} loadingLabel="正在处理…" disabled={busy || !editReason.trim()} onClick={() => { void submitEdit(); }} type="button">保存字段修改</Button>
        </section> : <StatusMessage kind="info" title="字段不可直接编辑">当前字段的编辑规则由报表合同决定。</StatusMessage>}
        <section className={cellCss.section} aria-label="恢复一个已记录的值"><h3>恢复一个已记录的值</h3>
          {latestChange || cell.parent_restore_options.length > 0 || cell.source_restore_option ? <>
            <FormField label="恢复原因"><textarea className={controlCss.control} disabled={busy} onChange={(event) => setRestoreReason(event.target.value)} rows={3} value={restoreReason} /></FormField>
            <div className={cellCss.restoreActions}>
              {latestChange && <Button variant="secondary" disabled={busy || !restoreReason.trim()} onClick={() => { void restore({ source_kind: "previous", field_change_id: latestChange.id }); }} type="button">撤销本次修改</Button>}
              {cell.parent_restore_options.length > 0 && <><FormField label="父版本"><Select disabled={busy} onChange={(event) => setParentVersionId(Number(event.target.value))} value={parentVersionId}>{cell.parent_restore_options.map((option) => <option key={option.parent_version_id} value={option.parent_version_id}>版本 ID #{option.parent_version_id} · {displayValue(option.value)}</option>)}</Select></FormField><Button variant="secondary" disabled={busy || !restoreReason.trim()} onClick={() => { void restore({ source_kind: "parent", parent_version_id: parentVersionId }); }} type="button">恢复父版本值</Button></>}
              {cell.source_restore_option && <Button variant="secondary" disabled={busy || !restoreReason.trim()} onClick={() => { const source = cell.source_restore_option; if (source) void restore({ source_kind: "source", source_batch_id: source.source_batch_id, parsed_source_row_id: source.parsed_source_row_id }); }} type="button">恢复源文件值</Button>}
            </div>
          </> : <p className={cellCss.hint}>当前字段暂无可恢复的历史或来源值。</p>}
        </section>
        {operator && <p className={cellCss.hint}>操作人来源：当前登录会话 · {auditOperatorLabel(operator)}。默认原因可补充修改。</p>}
        <section className={cellCss.section} aria-label="字段备注"><h3>字段备注</h3>
          {cell.notes.length > 0 ? <ul className={cellCss.notes}>{cell.notes.map((item) => <li key={item.note_key}><p>{item.body}</p><small>{item.author_username} · {item.visibility === "internal" ? "仅审核人员" : "查看人员可见"} · 第 {item.revision_number} 版</small><NoteRevisionEditor busy={busy} note={item} onRevise={onReviseNote} /></li>)}</ul> : <p className={cellCss.hint}>尚无字段备注。</p>}
          <FormField label="备注内容"><textarea className={controlCss.control} disabled={busy} onChange={(event) => setNote(event.target.value)} rows={2} value={note} /></FormField>
          <FormField label="可见范围"><Select disabled={busy} onChange={(event) => setNoteVisibility(event.target.value as typeof noteVisibility)} value={noteVisibility}><option value="internal">仅审核人员</option><option value="viewer_visible">查看人员可见</option></Select></FormField>
          <Button variant="secondary" disabled={busy || !note.trim()} onClick={() => { void addNote(); }} type="button">追加字段备注</Button>
        </section>
        <section className={cellCss.section} aria-label="字段历史"><h3>字段历史</h3>
          {cell.history.length ? <ol className={cellCss.history}>{cell.history.map((item) => <li key={item.id}><header><strong>{item.operation}</strong><span>r{item.data_revision} · {item.actor_username}</span></header><dl><div><dt>修改前</dt><dd>{displayValue(item.before)}</dd></div><div><dt>修改后</dt><dd>{displayValue(item.after)}</dd></div></dl><p>{item.reason}</p></li>)}</ol> : <p className={cellCss.hint}>这个字段还没有人工修改。</p>}
        </section>
      </div>
    </Dialog>
  );
}

function AddRowDrawer({
  busy,
  fields,
  onAddRow,
  onClose,
  operator,
  sourceBatchIds,
  source,
}: {
  busy: boolean;
  fields: ReviewFieldContract[];
  onAddRow: Props["onAddRow"];
  onClose: () => void;
  operator?: AuditOperator;
  sourceBatchIds: number[];
  source: string;
}) {
  const [sourceBatchId, setSourceBatchId] = useState(sourceBatchIds[0] ?? 0);
  const [rawValues, setRawValues] = useState<Record<string, string>>(
    () => Object.fromEntries(fields.map((field) => [field.name, ""])),
  );
  const [nullFields, setNullFields] = useState<Set<string>>(
    () => new Set(fields.filter((field) => field.nullable && !field.required_on_add).map((field) => field.name)),
  );
  const [reason, setReason] = useState(() => defaultAuditReason(operator, "新增纠错行", source));
  const [error, setError] = useState<string>();

  useEffect(() => {
    setReason(defaultAuditReason(operator, "新增纠错行", source));
  }, [operator, source]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    try {
      if (!sourceBatchId) throw new Error("当前草稿没有可用于关联的来源批次。");
      const values: Record<string, TypedFieldValue> = {};
      for (const field of fields) {
        const useNull = nullFields.has(field.name);
        const raw = rawValues[field.name] ?? "";
        if (field.required_on_add && (useNull || !raw.trim())) {
          throw new Error(`新增行必须填写 ${field.name}。`);
        }
        values[field.name] = editValue(field, raw, useNull);
      }
      await onAddRow(sourceBatchId, values, reason);
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "新增行未保存。");
    }
  };

  return (
    <Dialog open accessibleLabel="新增纠错行" presentation="drawer" closeLabel="关闭新增纠错行" dismissDisabled={busy}
      title="新增纠错行" eyebrow="人工纠错" description="补录遗漏的有效行，并关联当前草稿的来源批次。原始文件保持不变。"
      onOpenChange={open => { if (!open && !busy) onClose(); }}>
      <div className={cellCss.content} role="region" aria-label="新增纠错行内容" tabIndex={busy ? 0 : undefined}>
        <StatusMessage kind="info" title="补录到当前草稿">新增行需要完整填写必填字段；保存后需重新校验。</StatusMessage>
        {!sourceBatchIds.length && <StatusMessage kind="warning" title="没有可关联的来源批次">当前草稿暂无可用来源，暂时不能新增纠错行。请先核对导入来源。</StatusMessage>}
        {error && <StatusMessage kind="danger" title="新增行未保存">{error}</StatusMessage>}
        <form className={rowCss.form} onSubmit={(event) => { void submit(event); }}>
          <section className={cellCss.section} aria-label="来源与原因"><h3>来源与原因</h3>
            <FormField label="来源批次"><Select disabled={busy || !sourceBatchIds.length} onChange={(event) => setSourceBatchId(Number(event.target.value))} value={sourceBatchId}>{sourceBatchIds.length ? sourceBatchIds.map((batchId) => <option key={batchId} value={batchId}>导入批次 #{batchId}</option>) : <option value={0}>当前页没有可用来源批次</option>}</Select></FormField>
            <FormField label="新增原因"><textarea className={controlCss.control} disabled={busy} onChange={(event) => setReason(event.target.value)} required rows={3} value={reason} /></FormField>
          </section>
          <section className={cellCss.section} aria-label="完整行数据"><h3>完整行数据</h3>
            <div className={rowCss.dataGrid}>{fields.map((field) => {
              const useNull = nullFields.has(field.name);
              return <div className={rowCss.field} key={field.name}><FormField label={field.name + (field.required_on_add ? "（新增必填）" : "")} hint={field.scale !== null ? `${field.scale} 位小数` : undefined}><Input aria-label={`新增行字段 ${field.name}`} disabled={busy || useNull} inputMode={field.kind === "integer" || field.kind === "decimal" ? "decimal" : "text"} maxLength={field.max_length ?? undefined} onChange={(event) => setRawValues((current) => ({ ...current, [field.name]: event.target.value }))} value={rawValues[field.name] ?? ""} /></FormField>{field.nullable && !field.required_on_add && <Checkbox label={`字段 ${field.name} 使用空值`} checked={useNull} disabled={busy} onChange={(event) => setNullFields((current) => { const next = new Set(current); if (event.target.checked) next.add(field.name); else next.delete(field.name); return next; })} />}</div>;
            })}</div>
          </section>
          <div className={rowCss.actions}><Button variant="quiet" disabled={busy} onClick={onClose} type="button">取消新增</Button><Button variant="primary" loading={busy} loadingLabel="正在保存…" disabled={busy || !sourceBatchId || !reason.trim()} type="submit">保存新增行</Button></div>
        </form>
      </div>
    </Dialog>
  );
}

function RowStateDrawer({
  busy,
  onAddRowNote,
  onChangeRowState,
  onClose,
  operator,
  onReviseNote,
  row,
  source,
}: {
  busy: boolean;
  onAddRowNote: Props["onAddRowNote"];
  onChangeRowState: Props["onChangeRowState"];
  onClose: () => void;
  operator?: AuditOperator;
  onReviseNote: Props["onReviseNote"];
  row: ReviewRow;
  source: string;
}) {
  const operation = row.row_state === "active" ? "exclude" : "restore";
  const [reason, setReason] = useState(() => defaultAuditReason(
    operator,
    `${operation === "exclude" ? "排除" : "恢复"}第 ${row.row_ordinal} 行`,
    source,
  ));
  const [note, setNote] = useState("");
  const [noteVisibility, setNoteVisibility] = useState<"internal" | "viewer_visible">("internal");
  const [error, setError] = useState<string>();
  const cannotRestoreSourceDeletion = row.row_state === "deleted" && row.base_row_id !== null;

  useEffect(() => {
    setReason(defaultAuditReason(
      operator,
      `${operation === "exclude" ? "排除" : "恢复"}第 ${row.row_ordinal} 行`,
      source,
    ));
  }, [operation, operator, row.row_ordinal, source]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    try {
      await onChangeRowState(row, operation, reason);
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "行状态未更改。");
    }
  };

  const addNote = async () => {
    setError(undefined);
    try {
      await onAddRowNote(row, note, noteVisibility);
      setNote("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "行备注未保存。");
    }
  };

  return (
    <Dialog open accessibleLabel="行状态操作" presentation="drawer" closeLabel="关闭行状态操作" dismissDisabled={busy}
      title={operation === "exclude" ? "排除处理行" : "恢复处理行"} eyebrow={`第 ${row.row_ordinal} 行`}
      description="调整当前草稿的行状态，来源与操作历史继续保留。"
      onOpenChange={open => { if (!open && !busy) onClose(); }}>
      <div className={cellCss.content} role="region" aria-label="行状态操作内容" tabIndex={busy ? 0 : undefined}>
        <div className={cellCss.identity}><span>行 ID #{row.row_id}</span><StatusBadge label={row.row_state === "active" ? "参与合计" : row.row_state === "excluded" ? "已排除" : "已删除"} tone={row.row_state === "active" ? "good" : "warn"} /></div>
        <dl className={rowCss.facts}><div><dt>当前状态</dt><dd>{row.row_state}</dd></div><div><dt>来源</dt><dd>{row.base_row_id === null ? "人工新增" : "版本基础行"}</dd></div><div><dt>逻辑行</dt><dd>{row.logical_row_id}</dd></div></dl>
        <StatusMessage kind={operation === "exclude" ? "warning" : "info"} title={operation === "exclude" ? "排除后的影响" : "恢复后的影响"}>{operation === "exclude" ? "排除后该行不进入合计或发布结果，原始来源与历史仍保留。" : "恢复后该行重新进入当前草稿与下一次校验。"}</StatusMessage>
        {cannotRestoreSourceDeletion && <StatusMessage kind="danger" title="当前来源行不能恢复">来源行不能从“已删除”恢复；请由管理员检查异常状态。</StatusMessage>}
        {error && <StatusMessage kind="danger" title="行操作未完成">{error}</StatusMessage>}
        <form className={rowCss.form} onSubmit={(event) => { void submit(event); }}><section className={cellCss.section} aria-label="处理说明"><h3>{operation === "exclude" ? "排除说明" : "恢复说明"}</h3><FormField label="处理原因"><textarea className={controlCss.control} disabled={busy} onChange={(event) => setReason(event.target.value)} required rows={3} value={reason} /></FormField></section><div className={rowCss.actions}><Button variant="quiet" disabled={busy} onClick={onClose} type="button">取消</Button><Button variant={operation === "exclude" ? "danger" : "primary"} loading={busy} loadingLabel="正在处理…" disabled={busy || cannotRestoreSourceDeletion || !reason.trim()} type="submit">{operation === "exclude" ? "排除这一行" : "恢复这一行"}</Button></div></form>
        <section className={cellCss.section} aria-label="行备注"><h3>行备注</h3>{row.notes.length > 0 ? <ul className={cellCss.notes}>{row.notes.map((item) => <li key={item.note_key}><p>{item.body}</p><small>{item.author_username} · {item.visibility === "internal" ? "仅审核人员" : "查看人员可见"} · 第 {item.revision_number} 版</small><NoteRevisionEditor busy={busy} note={item} onRevise={onReviseNote} /></li>)}</ul> : <p className={cellCss.hint}>尚无行备注。</p>}<FormField label="行备注内容"><textarea className={controlCss.control} disabled={busy} onChange={(event) => setNote(event.target.value)} rows={3} value={note} /></FormField><FormField label="行备注可见范围"><Select disabled={busy} onChange={(event) => setNoteVisibility(event.target.value as typeof noteVisibility)} value={noteVisibility}><option value="internal">仅审核人员</option><option value="viewer_visible">查看人员可见</option></Select></FormField><Button variant="secondary" disabled={busy || !note.trim()} onClick={() => { void addNote(); }} type="button">追加行备注</Button></section>
        <section className={cellCss.section} aria-label="状态历史"><h3>状态历史</h3>{row.history.length ? <ol className={cellCss.history}>{row.history.map((item) => <li key={item.id}><header><strong>{item.operation}</strong><span>r{item.data_revision} · {item.actor_username}</span></header><p>{item.reason}</p></li>)}</ol> : <p className={cellCss.hint}>这行还没有状态修改记录。</p>}</section>
      </div>
    </Dialog>
  );
}

type SortState = {
  direction: "ascending" | "descending";
  fieldName: string;
};

const KEY_FIELD_NAMES = new Set(["sku", "asin", "child_asin"]);

function compareCells(left: ReviewCell | undefined, right: ReviewCell | undefined) {
  const leftValue = displayValue(left?.current ?? null);
  const rightValue = displayValue(right?.current ?? null);
  if (leftValue === "—" && rightValue !== "—") return 1;
  if (rightValue === "—" && leftValue !== "—") return -1;
  return leftValue.localeCompare(rightValue, "zh-CN", {
    numeric: true,
    sensitivity: "base",
  });
}

function cellKey(rowId: number, fieldName: string) {
  return `${rowId}:${fieldName}`;
}

export function ReviewDataTable({ busy, onAddCellNote, onAddRow, onAddRowNote, onChangeRowState, onPageChange, onRestoreField, onReviewIssue, onReviseNote, onSetField, operator, workspace }: Props) {
  const [query, setQuery] = useState("");
  const [changedOnly, setChangedOnly] = useState(true);
  const [rowState, setRowState] = useState<"all" | ReviewRow["row_state"]>("all");
  const [focusedField, setFocusedField] = useState("all");
  const [sort, setSort] = useState<SortState>();
  const [differenceCursor, setDifferenceCursor] = useState(-1);
  const [selected, setSelected] = useState<{ rowId: number; fieldName: string }>();
  const [rowActionId, setRowActionId] = useState<number>();
  const [addingRow, setAddingRow] = useState(false);
  const cellButtons = useRef(new Map<string, HTMLButtonElement>());
  const keyFieldNames = useMemo(
    () => new Set(
      workspace.fields
        .filter((field) => KEY_FIELD_NAMES.has(field.name))
        .slice(0, 2)
        .map((field) => field.name),
    ),
    [workspace.fields],
  );
  const visibleFields = useMemo(
    () => focusedField === "all"
      ? workspace.fields
      : workspace.fields.filter((field) => keyFieldNames.has(field.name) || field.name === focusedField),
    [focusedField, keyFieldNames, workspace.fields],
  );
  const visibleFieldNames = useMemo(
    () => new Set(visibleFields.map((field) => field.name)),
    [visibleFields],
  );
  const keyFieldIndexes = useMemo(
    () => new Map(
      visibleFields
        .filter((field) => keyFieldNames.has(field.name))
        .map((field, index) => [field.name, index]),
    ),
    [keyFieldNames, visibleFields],
  );
  const filteredRows = useMemo(() => workspace.rows.filter((row) => {
    if (rowState !== "all" && row.row_state !== rowState) return false;
    if (changedOnly && !row.cells.some((cell) => visibleFieldNames.has(cell.field_name) && (cell.changed_from_base || cell.changed_from_source))) return false;
    if (!query.trim()) return true;
    const needle = query.trim().toLocaleLowerCase();
    return row.cells.some((cell) => visibleFieldNames.has(cell.field_name) && displayValue(cell.current).toLocaleLowerCase().includes(needle));
  }), [changedOnly, query, rowState, visibleFieldNames, workspace.rows]);
  const rows = useMemo(() => {
    if (!sort) return filteredRows;
    const direction = sort.direction === "ascending" ? 1 : -1;
    return [...filteredRows].sort((left, right) => {
      const compared = compareCells(
        left.cells.find((cell) => cell.field_name === sort.fieldName),
        right.cells.find((cell) => cell.field_name === sort.fieldName),
      );
      return compared === 0
        ? left.row_ordinal - right.row_ordinal
        : compared * direction;
    });
  }, [filteredRows, sort]);
  const differences = useMemo(
    () => rows.flatMap((row) => visibleFields.flatMap((field) => {
      const cell = row.cells.find((item) => item.field_name === field.name);
      return cell && (cell.changed_from_base || cell.changed_from_source)
        ? [{ fieldName: field.name, rowId: row.row_id }]
        : [];
    })),
    [rows, visibleFields],
  );

  useEffect(() => {
    if (focusedField !== "all" && !workspace.fields.some((field) => field.name === focusedField)) {
      setFocusedField("all");
    }
  }, [focusedField, workspace.fields]);

  useEffect(() => {
    setDifferenceCursor(-1);
  }, [changedOnly, focusedField, query, rowState, sort, workspace.head.version_id, workspace.pagination.page]);

  const selectCell = (rowId: number, fieldName: string) => {
    const index = differences.findIndex((item) => item.rowId === rowId && item.fieldName === fieldName);
    if (index >= 0) setDifferenceCursor(index);
    setAddingRow(false);
    setRowActionId(undefined);
    setSelected({ rowId, fieldName });
  };

  const moveDifference = (direction: -1 | 1) => {
    if (!differences.length) return;
    const nextIndex = differenceCursor < 0
      ? direction > 0 ? 0 : differences.length - 1
      : (differenceCursor + direction + differences.length) % differences.length;
    const next = differences[nextIndex];
    if (!next) return;
    setDifferenceCursor(nextIndex);
    setAddingRow(false);
    setRowActionId(undefined);
    setSelected({ rowId: next.rowId, fieldName: next.fieldName });
  };

  const toggleSort = (fieldName: string) => {
    setSort((current) => current?.fieldName === fieldName
      ? { fieldName, direction: current.direction === "ascending" ? "descending" : "ascending" }
      : { fieldName, direction: "ascending" });
  };

  const handleCellKeyDown = (
    event: ReactKeyboardEvent<HTMLButtonElement>,
    rowIndex: number,
    fieldIndex: number,
  ) => {
    let targetRow = rowIndex;
    let targetField = fieldIndex;
    if (event.key === "ArrowLeft") targetField -= 1;
    else if (event.key === "ArrowRight") targetField += 1;
    else if (event.key === "ArrowUp") targetRow -= 1;
    else if (event.key === "ArrowDown") targetRow += 1;
    else if (event.key === "Home") targetField = 0;
    else if (event.key === "End") targetField = visibleFields.length - 1;
    else return;
    const target = rows[targetRow];
    const field = visibleFields[targetField];
    if (!target || !field) return;
    event.preventDefault();
    cellButtons.current.get(cellKey(target.row_id, field.name))?.focus();
  };

  const selectedRow = selected ? workspace.rows.find((row) => row.row_id === selected.rowId) : undefined;
  const selectedCell = selectedRow?.cells.find((cell) => cell.field_name === selected?.fieldName);
  const selectedContract = workspace.fields.find((field) => field.name === selected?.fieldName);
  const rowAction = rowActionId ? workspace.rows.find((row) => row.row_id === rowActionId) : undefined;
  const sourceBatchIds = workspace.source_batches.map((source) => source.batch_id);
  const auditSource = `草稿 v${workspace.head.version_no} · 数据修订 r${workspace.head.data_revision}`;

  return <>
    <section className={css["review-data"]} aria-label="草稿数据对照">
      <header className={css.toolbar}>
        <div className={css.summary}>
          <div><h3>源值、基础值与当前值</h3><p>先定位差异，再打开单元格核对来源与修改记录。搜索、筛选及排序仅作用于当前页。</p></div>
          <Button variant="secondary" disabled={busy || !sourceBatchIds.length} onClick={() => { setSelected(undefined); setRowActionId(undefined); setAddingRow(true); }} title={sourceBatchIds.length ? undefined : "当前页没有可关联的来源批次"} type="button">新增纠错行</Button>
        </div>
        <div className={css.controls}>
          <FormField label="搜索当前页"><SearchInput onValueChange={setQuery} placeholder="SKU、ASIN 或数值" value={query} clearLabel="清除当前页搜索" /></FormField>
          <FormField label="显示字段"><Select onChange={(event) => { setFocusedField(event.target.value); setSort(undefined); }} value={focusedField}><option value="all">全部字段</option>{workspace.fields.map((field) => <option key={field.name} value={field.name}>{field.name}</option>)}</Select></FormField>
          <FormField label="行状态"><Select onChange={(event) => setRowState(event.target.value as typeof rowState)} value={rowState}><option value="all">全部</option><option value="active">有效</option><option value="excluded">已排除</option><option value="deleted">已删除</option></Select></FormField>
        </div>
        <div className={css.reviewLine}>
          <Checkbox checked={changedOnly} onChange={(event) => setChangedOnly(event.target.checked)} label="仅看差异" />
          <div aria-label="差异导航" className={css.differenceNav} role="group">
            <Button variant="quiet" disabled={busy || !differences.length} onClick={() => moveDifference(-1)} type="button">上一处差异</Button>
            <output aria-live="polite" aria-label="当前页差异数量">{differenceCursor < 0 ? `${differences.length} 处` : `${differenceCursor + 1} / ${differences.length}`}</output>
            <Button variant="quiet" disabled={busy || !differences.length} onClick={() => moveDifference(1)} type="button">下一处差异</Button>
          </div>
        </div>
        <div className={css.legend}><span><i aria-hidden="true" className={css.sourceMarker} />源表差异</span><span><i aria-hidden="true" />版本差异</span><strong>显示当前页 {rows.length} / {workspace.rows.length} 行</strong></div>
      </header>
      {!sourceBatchIds.length && <StatusMessage kind="info" title="暂不能新增纠错行">当前草稿没有可关联的来源批次，请先核对导入来源。</StatusMessage>}
      <div className={css["review-table-scroll"]} role="region" aria-label="可横向滚动的草稿数据表" tabIndex={0}>
        <table className={css["review-table"]}>
          <thead><tr><th className={css.rowKey} scope="col">行</th><th className={css.state} scope="col">状态</th>{visibleFields.map((field) => {
            const keyIndex = keyFieldIndexes.get(field.name);
            const nextDirection = sort?.fieldName === field.name && sort.direction === "ascending" ? "降序" : "升序";
            const style = keyIndex !== undefined ? ({ "--review-key-offset": `${keyIndex * 160}px` } as CSSProperties) : undefined;
            return <th scope="col" aria-sort={sort?.fieldName === field.name ? sort.direction : "none"} className={keyIndex !== undefined ? css["review-table__key-field"] : undefined} key={field.name} style={style}><button aria-label={`按 ${field.name} ${nextDirection}排序`} className={css.sort} onClick={() => toggleSort(field.name)} type="button">{field.name}{field.included_in_totals && <span>合计</span>}<i aria-hidden="true">{sort?.fieldName === field.name ? sort.direction === "ascending" ? "↑" : "↓" : "↕"}</i></button></th>;
          })}</tr></thead>
          <tbody>{rows.map((row, rowIndex) => <tr key={row.row_id}>
            <th className={css.rowKey} scope="row">{row.row_ordinal}</th>
            <td className={`${css.state} ${css.cell}`}><button aria-label={`管理第 ${row.row_ordinal} 行状态，当前 ${row.row_state}`} onClick={() => { setSelected(undefined); setAddingRow(false); setRowActionId(row.row_id); }} type="button"><span>{row.row_state === "active" ? "有效" : row.row_state === "excluded" ? "已排除" : "已删除"}</span><small>{row.row_state === "active" ? "排除" : "恢复"}</small></button></td>
            {visibleFields.map((field, fieldIndex) => {
              const cell = row.cells.find((item) => item.field_name === field.name);
              const keyIndex = keyFieldIndexes.get(field.name);
              const style = keyIndex !== undefined ? ({ "--review-key-offset": `${keyIndex * 160}px` } as CSSProperties) : undefined;
              if (!cell) return <td className={keyIndex !== undefined ? css["review-table__key-field"] : undefined} key={field.name} style={style}>—</td>;
              const sourceChanged = cell.changed_from_source;
              const changed = cell.changed_from_base || sourceChanged;
              const classes = [css.cell, changed && css.changed, sourceChanged && css.sourceDifferent, keyIndex !== undefined && css["review-table__key-field"]].filter(Boolean).join(" ");
              const differenceLabel = `${sourceChanged ? "，与源表不同" : ""}${cell.changed_from_base ? "，与基础版本不同" : ""}`;
              return <td className={classes} key={field.name} style={style}><button aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown Home End" aria-label={`${field.name}，当前值 ${displayValue(cell.current)}${differenceLabel}`} title={displayValue(cell.current)} onClick={() => selectCell(row.row_id, field.name)} onKeyDown={(event) => handleCellKeyDown(event, rowIndex, fieldIndex)} ref={(node) => { const key = cellKey(row.row_id, field.name); if (node) cellButtons.current.set(key, node); else cellButtons.current.delete(key); }} type="button"><span>{displayValue(cell.current)}</span>{changed && <small>{sourceChanged ? "源表差异" : "版本差异"}</small>}</button></td>;
            })}
          </tr>)}</tbody>
        </table>
        {!rows.length && <div className={css.empty}><EmptyState title={workspace.rows.length ? "当前筛选没有匹配行" : "当前页没有数据行"} description={workspace.rows.length ? "搜索与差异筛选仅作用于当前页，可清除筛选重新核对。" : "请核对当前页与导入来源；其他页的记录仍以分页结果为准。"} action={workspace.rows.length ? <Button variant="secondary" onClick={() => { setQuery(""); setFocusedField("all"); setRowState("all"); setChangedOnly(false); setSort(undefined); }} type="button">清除当前页筛选</Button> : undefined} /></div>}
      </div>
      <footer className={css.footer}><Pagination page={workspace.pagination.page} totalPages={workspace.pagination.total_pages} totalItems={workspace.pagination.total_rows} itemLabel="数据行" loading={busy} onPageChange={onPageChange} /><p>方向键移动单元格 · Enter 打开对照 · SKU / ASIN 列在宽屏固定</p></footer>
    </section>
    <IssueReviewPanel busy={busy} issues={workspace.latest_full_validation?.issues ?? []} onReviewIssue={onReviewIssue} />
    {addingRow && <AddRowDrawer busy={busy} fields={workspace.fields} onAddRow={onAddRow} onClose={() => setAddingRow(false)} operator={operator} source={auditSource} sourceBatchIds={sourceBatchIds} />}
    {rowAction && <RowStateDrawer busy={busy} onAddRowNote={onAddRowNote} onChangeRowState={onChangeRowState} onClose={() => setRowActionId(undefined)} onReviseNote={onReviseNote} operator={operator} row={rowAction} source={auditSource} />}
    {selectedRow && selectedCell && selectedContract && <CellDrawer busy={busy} cell={selectedCell} contract={selectedContract} onAddCellNote={onAddCellNote} onClose={() => setSelected(undefined)} onRestoreField={onRestoreField} onReviseNote={onReviseNote} onSetField={onSetField} operator={operator} row={selectedRow} source={auditSource} />}
  </>;
}
