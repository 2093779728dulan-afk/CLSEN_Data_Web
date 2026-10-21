import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { X } from "lucide-react";
import { Button, EmptyState, Input, Radio, Select, StatusMessage } from "../../design-system";
import controlStyles from "../../design-system/Control.module.css";
import editorStyles from "./CatalogImportSectionTable.module.css";
import styles from "./CatalogImportReview.module.css";

import { saveCatalogMutations } from "./catalogApi";
import { CatalogIdentityOwners } from "./CatalogIdentityOwners";
import type { CatalogReviewOption, CatalogReviewOptionIndex } from "./catalogReviewOptions";
import { isEditableSection, type CatalogImportRow, type CatalogRowIssue, type CatalogSection } from "./catalogTypes";

type FieldMeta = { label: string; options?: readonly [string, string][]; placeholder?: string };
const EDITABLE_FIELDS: Record<CatalogSection, readonly string[]> = {
  evidence: [],
  exceptions: ["action", "target_sku_row_key", "corrected_style_code", "corrected_standard_color", "corrected_standard_size", "exclusion_reason", "note"],
  mappings: ["identity_decision", "target_sku_row_key", "exclusion_reason", "change_reason"],
  skus: ["internal_display_sku", "standard_color", "standard_size", "status", "change_reason"],
  styles: ["style_code", "standard_name", "status", "change_reason"],
};
const FIELD_META: Record<string, FieldMeta> = {
  action: { label: "处理方式", options: [["", "请选择"], ["correct_parse", "更正解析"], ["exclude", "排除"]] },
  change_reason: { label: "修改说明", placeholder: "说明调整原因（可选）" },
  corrected_standard_color: { label: "更正后颜色" }, corrected_standard_size: { label: "更正后尺码" }, corrected_style_code: { label: "更正后款号" }, exclusion_reason: { label: "排除原因" },
  identity_decision: { label: "映射决定", options: [["", "未决定"], ["mapped", "纳入目录"], ["excluded", "排除"]] }, internal_display_sku: { label: "内部展示 SKU" }, note: { label: "备注" },
  standard_color: { label: "标准颜色" }, standard_name: { label: "标准商品名称" }, standard_size: { label: "标准尺码" }, status: { label: "状态", options: [["active", "启用"], ["inactive", "停用"]] }, style_code: { label: "款号" }, target_sku_row_key: { label: "目标 SKU" },
};

// Shared with the toolbar count; preserve the same filtering contract as the table.
// eslint-disable-next-line react-refresh/only-export-components
export function filterCatalogReviewRows(section: CatalogSection, rows: CatalogImportRow[], onlyPending: boolean, query: string) {
  return rows.filter(row => (!onlyPending || isCatalogRowPending(section, row)) && (!query.trim() || `${row.row_key} ${Object.values(row.payload).join(" ")}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())));
}

function text(value: unknown): string { return typeof value === "string" ? value.trim() : ""; }
function sourceIdentity(section: CatalogSection, row: CatalogImportRow): { detail: string; title: string } {
  if (section === "styles") return { title: `款号 ${text(row.payload.style_code) || "未识别"}`, detail: `来源中出现 ${String(row.payload.candidate_seller_sku_count ?? 0)} 个 Seller SKU` };
  if (section === "skus") return { title: text(row.payload.internal_display_sku) || "待确认 SKU", detail: `来源颜色 / 尺码：${text(row.payload.source_color_preview).replace(/[[\]"]/g, "") || "未识别颜色"} / ${text(row.payload.source_size_preview).replace(/[[\]"]/g, "") || "未识别尺码"}` };
  if (section === "mappings") return { title: text(row.payload.seller_sku_preview) || "未识别 Seller SKU", detail: `经营 ${String(row.payload.business_occurrences ?? 0)} 次 · 退货 ${String(row.payload.return_occurrences ?? 0)} 次` };
  if (section === "exceptions") return { title: text(row.payload.seller_sku_preview) || "未识别 Seller SKU", detail: `原因：${text(row.payload.reason_code) || "待确认"}` };
  return { title: "来源证据", detail: "只读" };
}

// This pure helper is shared with the page-level progress summary.
// eslint-disable-next-line react-refresh/only-export-components
export function isCatalogRowPending(section: CatalogSection, row: CatalogImportRow): boolean {
  if (row.projection_state === "audit_only") return false;
  if (section === "styles") return !text(row.payload.standard_name);
  if (section === "skus") return !text(row.payload.internal_display_sku) || !text(row.payload.standard_color) || !text(row.payload.standard_size);
  if (section === "mappings") return !text(row.payload.identity_decision);
  if (section === "exceptions") return !text(row.payload.action);
  return false;
}

function mutationType(section: CatalogSection, row: CatalogImportRow): string {
  if (section === "styles") return row.row_origin === "user_created" ? "create_style" : "update_style";
  if (section === "skus") return row.row_origin === "user_created" ? "create_sku" : "update_sku";
  if (section === "mappings") return row.payload.identity_decision === "excluded" ? "exclude_seller_sku" : row.payload.identity_decision === "mapped" ? "map_seller_sku" : "clear_seller_sku_decision";
  if (section === "exceptions") return row.payload.action === "exclude" ? "resolve_exception_exclude" : "resolve_exception_correct_parse";
  throw new Error("Evidence rows are read-only.");
}

function EditableText({ field, issueId, onChange, rowKey, value }: { issueId?: string; field: string; onChange: (value: string | null) => void; rowKey: string; value: string }) {
  const editor = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const multiline = field === "standard_name" || field === "change_reason";
  const label = FIELD_META[field]?.label ?? field;
  useLayoutEffect(() => {
    if (!multiline || !editor.current) return;
    const element = editor.current;
    const resize = () => { element.style.height = "auto"; element.style.height = `${element.scrollHeight + 2}px`; };
    resize();
    if (typeof ResizeObserver === "undefined") return;
    let width = element.getBoundingClientRect().width;
    const observer = new ResizeObserver(() => {
      const nextWidth = element.getBoundingClientRect().width;
      if (nextWidth !== width) { width = nextWidth; resize(); }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [multiline, value]);
  const props = { "aria-invalid": Boolean(issueId), "aria-describedby": issueId, "aria-label": `${rowKey} ${field}`, onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(event.target.value || null), placeholder: FIELD_META[field]?.placeholder ?? "请输入标准值", value };
  return <div className={editorStyles.clearable}>
    {multiline ? <textarea {...props} className={`${controlStyles.control} ${editorStyles.control}`} ref={editor} rows={1} /> : <Input {...props} className={editorStyles.control} ref={editor} />}
    <Button aria-label={`清空${label}`} className={editorStyles.clear} disabled={!value} icon={<X />} onClick={() => { onChange(null); editor.current?.focus(); }} title={`清空${label}`} variant="quiet" />
  </div>;
}

function SuggestedField({ field, issueId, onChange, options, rowKey, value, showPreview = false }: { issueId?: string; field: string; onChange: (value: string | null) => void; options: CatalogReviewOption[]; rowKey: string; value: string; showPreview?: boolean }) {
  const [manual, setManual] = useState(!options.some((option) => option.value === value) && Boolean(value));
  const label = FIELD_META[field]?.label ?? field;
  if (manual) return <div className={editorStyles.suggested}><EditableText issueId={issueId} field={field} onChange={onChange} rowKey={rowKey} value={value} /><Button aria-label={`从报告候选中选择 ${label}`} className={editorStyles.manualAction} onClick={() => { setManual(false); onChange(options[0]?.value ?? null); }} variant="quiet">选择报告候选</Button></div>;
  return <div className={editorStyles.suggested}><div className={editorStyles.selectable}><Select className={editorStyles.control} aria-invalid={Boolean(issueId)} aria-describedby={issueId} aria-label={`${rowKey} ${field}`} onChange={(event) => { if (event.target.value === "__manual__") { setManual(true); } else onChange(event.target.value || null); }} value={value}>
    <option value="">请选择报告候选</option>{options.map((option) => <option key={option.value} value={option.value}>{field === "standard_color" || field === "standard_size" || field === "internal_display_sku" ? option.value : option.label}</option>)}<option value="__manual__">手动输入其他值…</option>
  </Select><Button aria-label={`清空${label}`} className={editorStyles.selectClear} disabled={!value} icon={<X />} onClick={() => { setManual(true); onChange(null); }} title={`清空${label}`} variant="quiet" /></div>{value && (showPreview || field === "standard_name") && <p className={editorStyles.preview}>{showPreview ? options.find(option => option.value === value)?.label ?? value : value}</p>}</div>;
}

type Draft = { base: CatalogImportRow["payload"]; payload: CatalogImportRow["payload"] };

function changed(section: CatalogSection, draft?: Draft): boolean {
  return Boolean(draft && EDITABLE_FIELDS[section].some(field => (draft.base[field] ?? null) !== (draft.payload[field] ?? null)));
}

const RowEditor = memo(function RowEditor({ canEdit, dirty, identityBlocked, importId, issues, onChange, onSave, onSaved, onUndo, options, payload, row, saved, section, tableSaving, workflowRevision }: {
  active: boolean; canEdit: boolean; dirty: boolean; identityBlocked: boolean; importId: number; onChange: (field: string, value: string | null) => void;
  issues: CatalogRowIssue[]; onUndo: () => void; onSave: () => void; onSaved: (revision: number) => Promise<void>; options: CatalogReviewOptionIndex;
  payload: CatalogImportRow["payload"]; row: CatalogImportRow; saved: boolean; section: CatalogSection;
  tableSaving: boolean; workflowRevision: number;
}) {
  const identity = sourceIdentity(section, row);
  return <tr data-review-row={row.row_key} className={`catalog-review-row${isCatalogRowPending(section, { ...row, payload }) ? " is-pending" : ""}${dirty ? " is-dirty" : ""}`}>
    <td data-label="来源审核项"><strong>{identity.title}</strong><small>{identity.detail}</small>{section === "mappings" && issues.some(issue => issue.row_key === row.row_key && (issue.severity === "error" || issue.severity === "blocking")) && <span className={styles.fieldIssue}>此项有校验问题，请核对下方字段及归属。</span>}</td>
    {EDITABLE_FIELDS[section].map(field => {
      const meta = FIELD_META[field] ?? { label: field };
      const value = String(payload[field] ?? "");
      const suggestions = options[row.row_key]?.[field] ?? [];
      const issue = issues.find(value => (value.severity === "error" || (section === "mappings" && value.severity === "blocking")) && value.row_key === row.row_key && value.field?.replace(/^\//, "") === field);
      const issueId = `review-${importId}-${section}-${encodeURIComponent(row.row_key)}-${field}`;
      const mapping = section === "mappings";
      const hidden = mapping && !issue && ((field === "target_sku_row_key" && payload.identity_decision !== "mapped") || (field === "exclusion_reason" && payload.identity_decision !== "excluded"));
      const readonlyValue = meta.options?.find(([option]) => option === value)?.[1] ?? suggestions.find(option => option.value === value)?.label
        ?? (field === "status" && value === "enabled" ? "启用" : field === "status" && value === "disabled" ? "停用" : value || "—");
      return <td data-label={meta.label} data-review-field={field} hidden={hidden} key={field}>{canEdit ? <fieldset aria-describedby={issue ? issueId : undefined} className={styles.field} disabled={tableSaving}>
        <div className={editorStyles.cellLabel}><span>{meta.label}</span>
          {mapping && field === "identity_decision" ? <div aria-label={`${identity.title} 映射决定`} aria-describedby={issue ? issueId : undefined} className={editorStyles.decisionGroup} role="radiogroup">
            {meta.options?.map(([option, label]) => <Radio checked={value === option} key={option} label={label} name={`mapping-${importId}-${row.row_key}`} onChange={() => onChange(field, option || null)} value={option} />)}
          </div> : meta.options ? <Select className={editorStyles.control} aria-invalid={Boolean(issue)} aria-describedby={issue ? issueId : undefined} aria-label={`${row.row_key} ${field}`} onChange={event => onChange(field, event.target.value || null)} value={value}>
            {meta.options.map(([option, label]) => <option key={option} value={option}>{label}</option>)}
          </Select> : suggestions.length ? <SuggestedField issueId={issue ? issueId : undefined} field={field} onChange={next => onChange(field, next)} options={suggestions} rowKey={row.row_key} value={value} showPreview={(mapping && field === "target_sku_row_key") || (section === "skus" && field === "internal_display_sku")} />
            : <EditableText issueId={issue ? issueId : undefined} field={field} onChange={next => onChange(field, next)} rowKey={row.row_key} value={value} />}
        </div>{issue && <span className={styles.fieldIssue} id={issueId}>{issue.reason_code === "required" ? "尚未填写或确认；修改后请重新校验。" : `${issue.reason_code}；修改后请重新校验。`}</span>}
        {mapping && field === "identity_decision" && !value && <p className={editorStyles.mappingHint}>请选择纳入目录或排除，当前尚未作出映射决定。</p>}
      </fieldset> : mapping || section === "skus" ? <div className={editorStyles.cellLabel}><span>{meta.label}</span>{readonlyValue}</div> : readonlyValue}</td>;
    })}
    <td className="catalog-row-action">{canEdit && <Button aria-label="保存此行" disabled={tableSaving} onClick={onSave} variant="secondary">保存此行</Button>}
      {canEdit && dirty && <Button disabled={tableSaving} onClick={onUndo} variant="quiet">撤销本行修改</Button>}
      {dirty ? <span className={styles.unsaved}>未保存</span> : saved ? <span className="catalog-save-success" role="status">已保存</span> : !canEdit ? <span>只读</span> : null}
    </td>
    {section === "mappings" && <td className="catalog-mapping-details"><details><summary>查看归属、冲突与恢复</summary>
      <div className={styles.field}><CatalogIdentityOwners disabled={identityBlocked || tableSaving || dirty || !canEdit} importId={importId} row={row} revision={workflowRevision} onSaved={onSaved} /></div>
    </details></td>}
  </tr>;
// Hidden rows retain manual-input/identity-recovery state; refresh their props before becoming interactive.
}, (_previous, next) => !next.active);

export function CatalogImportSectionTable({ active = true, busy = false, canEdit = true, identityBlocked = false, importId, issues = [], locate, onlyPending = false, onDraftCountChange, onLocateRow, onSavingChange, onSaved, options = {}, query = "", rows, saveMutations = saveCatalogMutations, section, workflowRevision }: {
  issues?: CatalogRowIssue[]; locate?: { issue: CatalogRowIssue; request: number };
  active?: boolean; busy?: boolean; canEdit?: boolean; identityBlocked?: boolean; importId: number; onlyPending?: boolean;
  onLocateRow?: (rowKey: string) => void;
  onDraftCountChange?: (section: CatalogSection, count: number) => void;
  onSavingChange?: (section: CatalogSection, saving: boolean) => void;
  onSaved: (revision: number) => Promise<void>; options?: CatalogReviewOptionIndex; query?: string;
  rows: CatalogImportRow[]; saveMutations?: typeof saveCatalogMutations; section: CatalogSection; workflowRevision: number;
}) {
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const inFlight = useRef(false);
  const root = useRef<HTMLDivElement>(null);
  const handledLocate = useRef<number | undefined>(undefined);
  const bookmark = useRef<{
    acknowledged?: boolean; element: HTMLElement; rowKey?: string; field?: string; visibleKeys: string[];
    left: number; top: number; x: number; y: number; selection?: [number | null, number | null];
  }>(undefined);
  const [announcement, setAnnouncement] = useState("");
  const [failedRow, setFailedRow] = useState<string>();
  useEffect(() => {
    // Keep edits in other rows when an acknowledged mutation refreshes the projection.
    setDrafts(current => Object.fromEntries(Object.entries(current).filter(([, draft]) => changed(section, draft))));
  }, [rows, section]);
  const dirtyRows = rows.filter(row => drafts[row.row_key] && changed(section, drafts[row.row_key]));
  const dirtyCount = dirtyRows.length;
  const staleRows = dirtyRows.filter(row => EDITABLE_FIELDS[section].some(field => (row.payload[field] ?? null) !== (drafts[row.row_key]?.base[field] ?? null)));
  useEffect(() => { onDraftCountChange?.(section, dirtyCount); }, [dirtyCount, onDraftCountChange, section]);
  // Only build a category's row list while it is visible. Previously visited rows remain mounted.
  const [display, setDisplay] = useState({ rows: active ? rows : [], onlyPending, query });
  if (active && (display.rows !== rows || display.onlyPending !== onlyPending || display.query !== query)) {
    setDisplay({ rows, onlyPending, query });
  }
  const filteredRows = useMemo(() => filterCatalogReviewRows(section, display.rows, display.onlyPending, display.query), [display, section]);
  const focusRow = useCallback((rowKey: string, field?: string) => {
    const row = Array.from(root.current?.querySelectorAll<HTMLElement>("[data-review-row]") ?? []).find(element => element.dataset.reviewRow === rowKey);
    const cells = Array.from(row?.querySelectorAll<HTMLElement>("[data-review-field]") ?? []);
    const cell = cells.find(element => element.dataset.reviewField === field) ?? cells[0];
    const editor = cell?.querySelector<HTMLElement>("input[type='radio']:checked:not(:disabled)") ?? cell?.querySelector<HTMLElement>("input:not(:disabled), textarea:not(:disabled), select:not(:disabled)");
    const target = editor ?? root.current?.querySelector<HTMLElement>("[aria-label='当前分类审核表格']") ?? root.current;
    target?.focus({ preventScroll: true });
    return target;
  }, []);
  useLayoutEffect(() => {
    if (busy || saving || !bookmark.current) return;
    const previous = bookmark.current;
    bookmark.current = undefined;
    // A deliberate move to another category/control during the request wins over restoration.
    if (!root.current?.getClientRects().length || (document.activeElement !== document.body && document.activeElement !== previous.element)) return;
    const position = previous.visibleKeys.indexOf(previous.rowKey ?? "");
    const nextKey = filteredRows.find(row => previous.visibleKeys.indexOf(row.row_key) > position)?.row_key ?? filteredRows.at(-1)?.row_key;
    const sameRow = filteredRows.some(row => row.row_key === previous.rowKey);
    const target = previous.element.isConnected && !previous.element.matches(":disabled")
      ? previous.element : focusRow(sameRow ? previous.rowKey! : nextKey ?? "", previous.field);
    target?.focus({ preventScroll: true });
    if (previous.selection && (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) && target === previous.element) {
      target.setSelectionRange(...previous.selection);
    }
    const scroller = root.current.querySelector<HTMLElement>("[aria-label='当前分类审核表格']");
    if (scroller) { scroller.scrollLeft = previous.left; scroller.scrollTop = previous.top; }
    window.scrollTo(previous.x, previous.y);
    if (previous.rowKey && !sameRow && target) {
      target.scrollIntoView({ block: "nearest", inline: "nearest" });
      if (previous.acknowledged) setAnnouncement(nextKey ? "已保存，已移到下一条可见审核项。" : "已保存，当前筛选下没有剩余审核项。");
    }
  }, [busy, saving, filteredRows, focusRow]);
  useEffect(() => {
    if (!locate || handledLocate.current === locate.request || busy || saving || !root.current?.getClientRects().length) return;
    handledLocate.current = locate.request;
    focusRow(locate.issue.row_key ?? "", locate.issue.field?.replace(/^\//, ""))?.scrollIntoView({ block: "center", inline: "nearest" });
  }, [active, locate, busy, saving, focusRow]);
  function undo(row: CatalogImportRow) {
    if (busy || saving) return;
    setDrafts(current => { const next = { ...current }; delete next[row.row_key]; return next; });
    setError(undefined); setFailedRow(undefined); setNotice(undefined);
    setAnnouncement(`${sourceIdentity(section, row).title} 的本地修改已撤销，恢复当前读取的草稿值。`);
    focusRow(row.row_key);
  }
  function keyboard(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.nativeEvent.isComposing || busy || saving || !canEdit) return;
    const control = event.target;
    if (!(control instanceof HTMLElement)) return;
    const rowKey = control.closest<HTMLElement>("[data-review-row]")?.dataset.reviewRow;
    const field = control.closest<HTMLElement>("[data-review-field]")?.dataset.reviewField;
    if (!rowKey || !field) return;
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.altKey) {
      event.preventDefault(); void save(dirtyRows.slice(0, 500));
    } else if (event.altKey && !event.ctrlKey && !event.metaKey && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      event.preventDefault();
      const index = filteredRows.findIndex(row => row.row_key === rowKey);
      const next = filteredRows[index + (event.key === "ArrowDown" ? 1 : -1)];
      if (next) focusRow(next.row_key, field)?.scrollIntoView({ block: "nearest", inline: "nearest" });
    } else if (event.key === "Escape" && !event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey && ((control instanceof HTMLInputElement && control.type === "text") || control instanceof HTMLTextAreaElement)) {
      const draft = drafts[rowKey];
      if (draft && (draft.payload[field] ?? null) !== (draft.base[field] ?? null)) {
        event.preventDefault(); event.stopPropagation();
        const row = rows.find(value => value.row_key === rowKey);
        if (row) edit(row, field, String(draft.base[field] ?? "") || null);
        setAnnouncement(`${FIELD_META[field]?.label ?? field} 已恢复到开始编辑时的值。`);
      }
    }
  }
  function displayChange(row: CatalogImportRow, field: string, value: CatalogImportRow["payload"][string] | undefined) {
    if (value === null || value === undefined || value === "") return "未填写";
    return FIELD_META[field]?.options?.find(([key]) => key === value)?.[1]
      ?? options[row.row_key]?.[field]?.find(option => option.value === value)?.label ?? String(value);
  }
  function edit(row: CatalogImportRow, field: string, value: string | null) {
    setDrafts(current => {
      const draft = current[row.row_key] ?? { base: row.payload, payload: row.payload };
      return { ...current, [row.row_key]: { ...draft, payload: { ...draft.payload, [field]: value } } };
    });
    setSaved(current => { const next = new Set(current); next.delete(row.row_key); return next; });
    setNotice(undefined);
  }
  async function save(selected: CatalogImportRow[]) {
    if (inFlight.current || busy || !canEdit || !selected.length) return;
    if (selected.some(row => staleRows.some(stale => stale.row_key === row.row_key))) {
      setFailedRow(selected.find(row => staleRows.some(stale => stale.row_key === row.row_key))?.row_key);
      setError("有修改行的服务端内容已变化，请核对最新值并放弃该行旧修改后重新编辑。"); return;
    }
    const active = document.activeElement;
    const scroller = root.current?.querySelector<HTMLElement>("[aria-label='当前分类审核表格']");
    if (active instanceof HTMLElement && root.current?.contains(active)) {
      bookmark.current = {
        element: active, rowKey: active.closest<HTMLElement>("[data-review-row]")?.dataset.reviewRow,
        field: active.closest<HTMLElement>("[data-review-field]")?.dataset.reviewField,
        visibleKeys: filteredRows.map(row => row.row_key), left: scroller?.scrollLeft ?? 0, top: scroller?.scrollTop ?? 0,
        x: window.scrollX, y: window.scrollY,
        selection: active instanceof HTMLTextAreaElement || (active instanceof HTMLInputElement && active.type === "text") ? [active.selectionStart, active.selectionEnd] : undefined,
      };
    }
    setFailedRow(undefined);
    inFlight.current = true; setSaving(true); onSavingChange?.(section, true); setError(undefined); setNotice(undefined);
    let acknowledged = false;
    const submitted = selected.map(row => ({ ...row, payload: drafts[row.row_key]?.payload ?? row.payload }));
    try {
      const result = await saveMutations(importId, workflowRevision, submitted.map(row => ({
        decision_group_key: section === "exceptions" || section === "mappings" ? row.row_key : null,
        payload: row.payload, row_key: section === "exceptions" || section === "mappings" ? null : row.row_key,
        type: mutationType(section, row),
      })));
      if (typeof result.workflow_revision !== "number") throw new Error("响应缺少新的修订号，请重新读取草稿核对保存结果。");
      acknowledged = true;
      if (bookmark.current) bookmark.current.acknowledged = true;
      setDrafts(current => {
        const next = { ...current };
        for (const row of submitted) next[row.row_key] = { base: row.payload, payload: row.payload };
        return next;
      });
      setSaved(current => new Set([...current, ...submitted.map(row => row.row_key)]));
      await onSaved(result.workflow_revision);
      setNotice(`已保存 ${submitted.length} 行草稿。目录尚未批准生效。`);
    } catch (reason) {
      if (!acknowledged) setFailedRow(selected[0]?.row_key);
      const message = reason instanceof Error ? reason.message : "保存失败。";
      setError(acknowledged ? `草稿已保存，但最新明细读取失败。请重新读取草稿，不要重复提交。${message}` : `${message} 编辑内容已保留，请核对后再保存。`);
    } finally { inFlight.current = false; setSaving(false); onSavingChange?.(section, false); }
  }
  return <div className={`${styles.section} ${editorStyles.controls}`} ref={root} onKeyDown={keyboard} tabIndex={-1} role="region" aria-label="当前分类编辑区">
    <span className={styles.srOnly} role="status" aria-live="polite">{announcement}</span>
    {canEdit && isEditableSection(section) && <p className={styles.keyboardHelp}>Tab 切换字段 · Alt + ↑ / ↓ 切换行 · Ctrl / ⌘ + Enter 保存分类 · Esc 撤销当前文本字段</p>}
    {error && <StatusMessage kind="danger" title="保存需要处理" action={failedRow ? <Button disabled={busy || saving} onClick={() => { if (onLocateRow) onLocateRow(failedRow); else focusRow(failedRow)?.scrollIntoView({ block: "center", inline: "nearest" }); }} variant="secondary">返回修改行</Button> : undefined}>{error}</StatusMessage>}
    {staleRows.map(row => <StatusMessage key={row.row_key} kind="warning" title={`${sourceIdentity(section, row).title} 已更新`} action={<Button disabled={busy || saving} onClick={() => undo(row)}>放弃该行旧修改</Button>}>服务端内容已变化，请先核对最新数据再重新编辑；当前修改未被自动覆盖。</StatusMessage>)}
    {notice && <StatusMessage kind="success" title="草稿保存完成">{notice}</StatusMessage>}
    {!rows.length ? <EmptyState title="当前分类没有记录" description="可以切换到其他审核分类。" />
      : !filteredRows.length ? <EmptyState title="没有符合筛选条件的审核项" description={onlyPending ? "当前分类已没有待处理项，或搜索条件没有匹配。" : "请调整搜索条件。"} />
        : <div aria-label="当前分类审核表格" className={styles.tableScroll} role="region" tabIndex={0}><table className={`${styles.table} ${section === "mappings" ? `${editorStyles.reviewCards} ${editorStyles.mappingTable}` : section === "skus" ? `${editorStyles.reviewCards} ${editorStyles.skuTable}` : section === "exceptions" ? editorStyles.exceptionTable : `catalog-review-table catalog-review-table--${section}`}`}><thead><tr><th>来源审核项</th>{EDITABLE_FIELDS[section].map(field => <th key={field}>{FIELD_META[field]?.label ?? field}</th>)}<th>操作</th>{section === "mappings" && <th>身份归属</th>}</tr></thead><tbody>
          {filteredRows.map(row => <RowEditor active={active} issues={issues} onUndo={() => undo(row)} canEdit={canEdit} identityBlocked={identityBlocked || dirtyCount > 0} dirty={Boolean(drafts[row.row_key] && changed(section, drafts[row.row_key]))} importId={importId} key={row.row_key}
            onChange={(field, value) => edit(row, field, value)} onSave={() => void save([row])} onSaved={onSaved} options={options}
            payload={drafts[row.row_key]?.payload ?? row.payload} row={row} saved={saved.has(row.row_key)} section={section} tableSaving={busy || saving} workflowRevision={workflowRevision} />)}
        </tbody></table></div>}
    {dirtyCount > 0 && <details className={styles.changePreview}><summary>核对本次修改 · {dirtyCount} 行（含筛选隐藏的修改）</summary>
      <div className={styles.changes}>{dirtyRows.map(row => {
        const draft = drafts[row.row_key];
        if (!draft) return null;
        return <div className={styles.changeRow} key={row.row_key}><strong>{sourceIdentity(section, row).title}</strong><dl>
          {EDITABLE_FIELDS[section].filter(field => (draft.base[field] ?? null) !== (draft.payload[field] ?? null)).map(field => <div key={field}><dt>{FIELD_META[field]?.label ?? field}</dt><dd><del>{displayChange(row, field, draft.base[field])}</del><span aria-label="改为">→</span><ins>{displayChange(row, field, draft.payload[field])}</ins></dd></div>)}
        </dl></div>;
      })}</div>
    </details>}
    {canEdit && isEditableSection(section) && <div className={styles.saveBar}>
      <div><strong>{dirtyCount ? `${dirtyCount} 行未保存` : "当前分类无未保存修改"}</strong><p>仅更新草稿 · 筛选隐藏的修改也会保存</p></div>
      <Button disabled={!dirtyCount || busy || saving} loading={saving} loadingLabel="正在保存草稿" onClick={() => void save(dirtyRows.slice(0, 500))} variant="primary">
        {dirtyCount > 500 ? "保存本批修改（前500行）" : `保存当前分类修改（${dirtyCount}行）`}
      </Button>
    </div>}
  </div>;
}
