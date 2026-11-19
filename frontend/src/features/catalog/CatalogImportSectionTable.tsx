import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { X } from "lucide-react";
import { Button, EmptyState, Input, Radio, Select, StatusMessage } from "../../design-system";
import controlStyles from "../../design-system/Control.module.css";
import editorStyles from "./CatalogImportSectionTable.module.css";
import styles from "./CatalogImportReview.module.css";

import { ApiRequestError } from "../../api/client";
import { saveCatalogMutations } from "./catalogApi";
import { reviewSuggestion } from "./catalogReviewSuggestions";
import { CatalogIdentityOwners } from "./CatalogIdentityOwners";
import type { CatalogReviewOption, CatalogReviewOptionIndex } from "./catalogReviewOptions";
import { isEditableSection, type CatalogDraftSaveAction, type CatalogSaveRecovery, type CatalogImportRow, type CatalogRowIssue, type CatalogSection } from "./catalogTypes";

type FieldMeta = { label: string; options?: readonly [string, string][]; placeholder?: string };
const EDITABLE_FIELDS: Record<CatalogSection, readonly string[]> = {
  evidence: [],
  exceptions: ["action", "target_sku_row_key", "corrected_style_code", "corrected_standard_color", "corrected_standard_size", "exclusion_reason", "note"],
  mappings: ["identity_decision", "target_sku_row_key", "exclusion_reason", "change_reason"],
  skus: ["internal_display_sku", "code_status", "code_evidence", "standard_color", "standard_size", "status", "change_reason"],
  styles: ["style_code", "standard_name", "status", "change_reason"],
};
const FIELD_META: Record<string, FieldMeta> = {
  action: { label: "处理方式", options: [["", "请选择"], ["correct_parse", "更正解析"], ["exclude", "排除"]] },
  change_reason: { label: "修改说明", placeholder: "说明调整原因（可选）" },
  corrected_standard_color: { label: "更正后颜色" }, corrected_standard_size: { label: "更正后尺码" }, corrected_style_code: { label: "更正后款号" }, exclusion_reason: { label: "排除原因" },
  identity_decision: { label: "映射决定", options: [["", "未决定"], ["mapped", "纳入目录"], ["excluded", "排除"]] }, internal_display_sku: { label: "正式SKU" }, code_status: { label: "编码确认", options: [["", "请选择"], ["legacy", "保留历史编码（未确认为正式）"], ["pending", "身份已确认，正式SKU待补"], ["confirmed", "正式SKU已确认"]] }, code_evidence: { label: "确认依据", placeholder: "填写编码来源，或身份已确认但编码待补的依据" }, note: { label: "备注" },
  standard_color: { label: "标准颜色" }, standard_name: { label: "标准商品名称", placeholder: "选填，可留空并在后续补充" }, standard_size: { label: "标准尺码" }, status: { label: "状态", options: [["active", "启用"], ["inactive", "停用"]] }, style_code: { label: "款号" }, target_sku_row_key: { label: "目标 SKU" },
};

// Shared with the toolbar count; preserve the same filtering contract as the table.
// eslint-disable-next-line react-refresh/only-export-components
export function filterCatalogReviewRows(section: CatalogSection, rows: CatalogImportRow[], onlyPending: boolean, query: string) {
  return rows.filter(row => (!onlyPending || isCatalogRowPending(section, row)) && (!query.trim() || `${row.row_key} ${Object.values(row.payload).join(" ")} ${section === "styles" && !text(row.payload.standard_name) ? "名称待补" : ""}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())));
}

function text(value: unknown): string { return typeof value === "string" ? value.trim() : ""; }
function sourceIdentity(section: CatalogSection, row: CatalogImportRow, productionSource = false): { detail: string; title: string } {
  if (section === "styles") return { title: `款号 ${text(row.payload.style_code) || "未识别"}`, detail: row.payload.candidate_seller_sku_count == null ? "来源依据见批次记录" : `来源中出现 ${String(row.payload.candidate_seller_sku_count)} 个 Seller SKU` };
  if (section === "skus") return { title: [text(row.payload.source_style_code), text(row.payload.internal_display_sku) || (row.payload.code_status === "pending" ? "正式SKU待补" : "待确认 SKU")].filter(Boolean).join(" · "), detail: row.payload.source_color_preview == null && row.row_origin === "user_created" ? `已登记标准规格：${text(row.payload.standard_color) || "待确认颜色"} / ${text(row.payload.standard_size) || "待确认尺码"}；原文见来源证据` : `来源颜色 / 尺码：${text(row.payload.source_color_preview).replace(/[[\]"]/g, "") || "未识别颜色"} / ${text(row.payload.source_size_preview).replace(/[[\]"]/g, "") || "未识别尺码"}` };
  if (section === "mappings") return { title: text(row.payload.seller_sku_preview) || "未识别 Seller SKU", detail: productionSource && row.payload.business_occurrences === undefined ? "来源清单记录；官方报表依据见清单核对页面" : `经营 ${String(row.payload.business_occurrences ?? 0)} 次 · 退货 ${String(row.payload.return_occurrences ?? 0)} 次` };
  if (section === "exceptions") return { title: text(row.payload.seller_sku_preview) || "未识别 Seller SKU", detail: `原因：${text(row.payload.reason_code) || "待确认"}` };
  return { title: "来源证据", detail: "只读" };
}

// This pure helper is shared with the page-level progress summary.
// eslint-disable-next-line react-refresh/only-export-components
export function isCatalogRowPending(section: CatalogSection, row: CatalogImportRow): boolean {
  if (row.projection_state === "audit_only") return false;
  if (section === "styles") return Boolean(row.payload.reconfirm_required) || !text(row.payload.style_code);
  if (section === "skus") return Boolean(row.payload.reconfirm_required) || (!text(row.payload.internal_display_sku) && row.payload.code_status !== "pending") || (["pending", "confirmed"].includes(text(row.payload.code_status)) && !text(row.payload.code_evidence)) || !text(row.payload.standard_color) || !text(row.payload.standard_size) || (text(row.payload.standard_size) !== "3XL" && ["XXXL", "3XL"].includes(text(row.payload.standard_size).normalize("NFKC").trim().toUpperCase()));
  if (section === "mappings") return !text(row.payload.identity_decision);
  if (section === "exceptions") return !text(row.payload.action);
  return false;
}

function mutationType(section: CatalogSection, row: CatalogImportRow): string {
  if (section === "styles") return "update_style";
  if (section === "skus") return "update_sku";
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
  const props = { "aria-invalid": Boolean(issueId), "aria-describedby": issueId, "aria-label": `${rowKey} ${field}`, maxLength: field === "standard_name" ? 255 : undefined, onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(event.target.value || null), placeholder: FIELD_META[field]?.placeholder ?? "请输入标准值", value };
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
    <option value="">{field === "standard_name" ? "暂不填写，后续补充名称" : "请选择报告候选"}</option>{options.map((option) => <option key={option.value} value={option.value}>{field === "standard_color" || field === "standard_size" || field === "internal_display_sku" ? option.value : option.label}</option>)}<option value="__manual__">手动输入其他值…</option>
  </Select><Button aria-label={`清空${label}`} className={editorStyles.selectClear} disabled={!value} icon={<X />} onClick={() => { setManual(true); onChange(null); }} title={`清空${label}`} variant="quiet" /></div>{value && (showPreview || field === "standard_name") && <p className={editorStyles.preview}>{showPreview ? options.find(option => option.value === value)?.label ?? value : value}</p>}</div>;
}

type Draft = { base: CatalogImportRow["payload"]; payload: CatalogImportRow["payload"] };

function changed(section: CatalogSection, draft?: Draft): boolean {
  return Boolean(draft && EDITABLE_FIELDS[section].some(field => (draft.base[field] ?? null) !== (draft.payload[field] ?? null)));
}

const RowEditor = memo(function RowEditor({ canEdit, dirty, identityBlocked, importId, issues, onChange, onSave, onSaved, onUndo, options, payload, productionSource, row, saved, section, tableSaving, workflowRevision }: {
  active: boolean; canEdit: boolean; dirty: boolean; identityBlocked: boolean; importId: number; onChange: (field: string, value: string | null) => void;
  issues: CatalogRowIssue[]; onUndo: () => void; onSave: () => void; onSaved: (revision: number) => Promise<void>; options: CatalogReviewOptionIndex;
  payload: CatalogImportRow["payload"]; row: CatalogImportRow; saved: boolean; section: CatalogSection;
  productionSource: boolean; tableSaving: boolean; workflowRevision: number;
}) {
  const identity = sourceIdentity(section, row, productionSource);
  const awaitingCheck = (issue: CatalogRowIssue) => {
    if (!dirty) return false;
    const field = issue.field?.replace(/^\//, "");
    if (issue.reason_code === "required" && field) return Boolean(text(payload[field])) && payload[field] !== row.payload[field];
    const codeChanged = ["internal_display_sku", "code_status", "code_evidence"].some(key => payload[key] !== row.payload[key]);
    if (issue.reason_code === "formal_code_decision_required") return codeChanged && ["confirmed", "pending"].includes(text(payload.code_status)) && Boolean(text(payload.code_evidence)) && (payload.code_status === "pending" || Boolean(text(payload.internal_display_sku)));
    if (issue.reason_code === "mapped_target_formal_code_required") return codeChanged && payload.code_status === "confirmed" && Boolean(text(payload.internal_display_sku)) && Boolean(text(payload.code_evidence));
    return false;
  };
  return <tr data-review-row={row.row_key} className={`catalog-review-row${isCatalogRowPending(section, { ...row, payload }) ? " is-pending" : ""}${dirty ? " is-dirty" : ""}`}>
    <td data-label="来源审核项"><strong>{identity.title}</strong><small>{identity.detail}</small>{section === "mappings" && issues.some(issue => issue.row_key === row.row_key && !awaitingCheck(issue) && (issue.severity === "error" || issue.severity === "blocking")) && <span className={styles.fieldIssue}>此项有校验问题，请核对下方字段及归属。</span>}</td>
    {EDITABLE_FIELDS[section].map(field => {
      const meta = FIELD_META[field] ?? { label: field };
      const value = String(payload[field] ?? "");
      const suggestions = options[row.row_key]?.[field] ?? [];
      const skuChoice = section === "skus" && field === "internal_display_sku" ? row.display_sku_choice ?? (productionSource ? { options: [], message: "尚未取得编码候选，请重新读取草稿。" } : undefined) : undefined;
      const specificationChanged = payload.standard_color !== row.payload.standard_color || payload.standard_size !== row.payload.standard_size;
      const fieldIssues = issues.filter(value => (value.severity === "error" || (section === "mappings" && value.severity === "blocking")) && value.row_key === row.row_key && value.field?.replace(/^\//, "") === field);
      const serverIssue = fieldIssues.find(issue => !awaitingCheck(issue)) ?? fieldIssues[0];
      const pendingCheck = serverIssue && awaitingCheck(serverIssue);
      const issue = pendingCheck ? undefined : serverIssue;
      const issueId = `review-${importId}-${section}-${encodeURIComponent(row.row_key)}-${field}`;
      const mapping = section === "mappings";
      const hidden = mapping && !issue && ((field === "target_sku_row_key" && payload.identity_decision !== "mapped") || (field === "exclusion_reason" && payload.identity_decision !== "excluded"));
      const readonlyValue = meta.options?.find(([option]) => option === value)?.[1] ?? suggestions.find(option => option.value === value)?.label
        ?? (field === "status" && value === "enabled" ? "启用" : field === "status" && value === "disabled" ? "停用" : value || (field === "standard_name" ? "名称待补" : "—"));
      return <td data-label={meta.label} data-review-field={field} hidden={hidden} key={field}>{canEdit ? <fieldset aria-describedby={issue ? issueId : undefined} className={styles.field} disabled={tableSaving}>
        <div className={editorStyles.cellLabel}><span>{meta.label}</span>
          {row.payload.reconfirm_required && (field === "internal_display_sku" || field === "standard_name") && <p>已保留上批修改，请重新核对并保存。</p>}
          {skuChoice ? <div className={editorStyles.suggested}>
            <Select className={editorStyles.control} aria-label={`${row.row_key} ${field}`} aria-invalid={Boolean(issue)} aria-describedby={`${issueId}-choice`} disabled={payload.code_status === "pending" || specificationChanged || !skuChoice.options.length} value={value} onChange={event => onChange(field, event.target.value || null)}>
              <option value="">{skuChoice.options.length ? "请选择来源中的正式编码" : "暂无正式编码，可选择待补"}</option>
              {value && !skuChoice.options.some(option => option.value === value) && <option value={value} disabled>{value}（待核对）</option>}
              {skuChoice.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </Select>
            <p className={editorStyles.preview} id={`${issueId}-choice`}>{specificationChanged ? "规格已修改，请先保存并重新读取候选，再选择编码。" : skuChoice.message || "仅选择本规格的来源编码；选择后保存，再校验与批准。"}</p>
          </div> : mapping && field === "identity_decision" ? <div aria-label={`${identity.title} 映射决定`} aria-describedby={issue ? issueId : undefined} className={editorStyles.decisionGroup} role="radiogroup">
            {meta.options?.map(([option, label]) => <Radio checked={value === option} key={option} label={label} name={`mapping-${importId}-${row.row_key}`} onChange={() => onChange(field, option || null)} value={option} />)}
          </div> : meta.options ? <Select className={editorStyles.control} aria-invalid={Boolean(issue)} aria-describedby={issue ? issueId : undefined} aria-label={`${row.row_key} ${field}`} onChange={event => onChange(field, event.target.value || null)} value={value}>
            {meta.options.filter(([option]) => !productionSource || field !== "code_status" || option !== "legacy" || Boolean(row.payload.system_sku_id && row.payload.approved_formal_sku)).map(([option, label]) => <option key={option} value={option}>{label}</option>)}
          </Select> : suggestions.length ? <SuggestedField issueId={issue ? issueId : undefined} field={field} onChange={next => onChange(field, next)} options={suggestions} rowKey={row.row_key} value={value} showPreview={(mapping && field === "target_sku_row_key") || (section === "skus" && field === "internal_display_sku")} />
            : <EditableText issueId={issue ? issueId : undefined} field={field} onChange={next => onChange(field, next)} rowKey={row.row_key} value={value} />}
        </div>{field === "standard_name" && <p className={editorStyles.preview}>{value.trim() ? "名称可后续修订；商品身份与业务关联保持不变。" : "名称待补（选填）；可继续校验与建档，后续参考官方报告补充。"}</p>}{issue && <span className={styles.fieldIssue} id={issueId}>{issue.reason_code === "required" ? "尚未填写或确认；修改后请重新校验。" : `${issue.reason_code === "noncanonical_standard_size" ? "标准尺码请使用3XL，原SKU编码保留" : issue.reason_code === "invalid_standard_name" ? "名称须为文字，最多255个字符；也可以留空待补" : issue.reason_code === "formal_code_decision_required" ? "请选择来源编码或明确待补，并填写依据" : issue.reason_code === "mapped_target_formal_code_required" ? "本规格已被Seller SKU纳入目录，请先从来源下拉框确认正式SKU" : issue.reason_code === "formal_code_not_from_source" ? "正式SKU不属于当前来源或已批准编码" : issue.reason_code === "mapping_target_seller_sku_mismatch" ? "正式SKU与当前Seller SKU不一致" : issue.reason_code === "reconfirm_required" ? "请重新核对保留的修改" : issue.reason_code}；修改后请重新校验。`}</span>}
        {pendingCheck && <span role="status">已修改，保存后自动检查</span>}
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

export function CatalogImportSectionTable({ active = true, busy = false, canEdit = true, identityBlocked = false, importId, issues = [], locate, onlyPending = false, onDraftCountChange, onLocateRow, onSavingChange, onSaveAction, onRecoverConflict, onSaved, options = {}, productionSource = false, query = "", rows, saveMutations = saveCatalogMutations, section, workflowRevision }: {
  issues?: CatalogRowIssue[]; locate?: { issue: CatalogRowIssue; request: number };
  active?: boolean; busy?: boolean; canEdit?: boolean; identityBlocked?: boolean; importId: number; onlyPending?: boolean;
  onLocateRow?: (rowKey: string) => void;
  onDraftCountChange?: (section: CatalogSection, count: number) => void;
  onSavingChange?: (section: CatalogSection, saving: boolean) => void;
  onRecoverConflict?: () => Promise<CatalogSaveRecovery>;
  onSaveAction?: (action: CatalogDraftSaveAction | undefined) => void;
  onSaved: (revision: number) => Promise<void>; options?: CatalogReviewOptionIndex; query?: string;
  productionSource?: boolean; rows: CatalogImportRow[]; saveMutations?: typeof saveCatalogMutations; section: CatalogSection; workflowRevision: number;
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
  const remoteFields = (row: CatalogImportRow) => [...new Set([...Object.keys(row.payload), ...Object.keys(drafts[row.row_key]?.base ?? {})])].filter(field => (row.payload[field] ?? null) !== (drafts[row.row_key]?.base[field] ?? null));
  const staleRows = dirtyRows.filter(row => remoteFields(row).length > 0);
  const canKeepLocal = (row: CatalogImportRow) => canEdit && row.projection_state === "included" && remoteFields(row).every(field => EDITABLE_FIELDS[section].includes(field));
  function keepLocal(row: CatalogImportRow) {
    if (busy || saving || !canKeepLocal(row)) return;
    setDrafts(current => {
      const draft = current[row.row_key];
      if (!draft) return current;
      const patch = Object.fromEntries(EDITABLE_FIELDS[section].filter(field => (draft.base[field] ?? null) !== (draft.payload[field] ?? null)).map(field => [field, draft.payload[field] ?? null]));
      return { ...current, [row.row_key]: { base: row.payload, payload: { ...row.payload, ...patch } } };
    });
    setError(undefined); setFailedRow(undefined);
  }
  useEffect(() => { onDraftCountChange?.(section, dirtyCount); }, [dirtyCount, onDraftCountChange, section]);
  // Only build a category's row list while it is visible. Previously visited rows remain mounted.
  const [display, setDisplay] = useState({ rows: active ? rows : [], onlyPending, query });
  if (active && (display.rows !== rows || display.onlyPending !== onlyPending || display.query !== query)) {
    setDisplay({ rows, onlyPending, query });
  }
  const filteredRows = useMemo(() => filterCatalogReviewRows(section, display.rows, display.onlyPending, display.query), [display, section]);
  const suggestions=filteredRows.filter(row=>!drafts[row.row_key]||!changed(section,drafts[row.row_key])).flatMap(row=>{const patch=reviewSuggestion(section,row,options,issues);return patch?[{row,patch}]:[];});
  const [suggestionKeys,setSuggestionKeys]=useState<string[]>([]);
  function acceptSuggestions(){
    if(busy||saving||!canEdit)return;
    const chosen=suggestions.filter(s=>suggestionKeys.includes(s.row.row_key)).slice(0,500);
    setDrafts(current=>{const next={...current};for(const {row,patch} of chosen)next[row.row_key]={base:row.payload,payload:{...row.payload,...patch}};return next;});setSuggestionKeys([]);setNotice('已填入所选建议，请核对后统一保存；尚未批准生效。');
  }

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
      const clearNewCode = (row.display_sku_choice && !row.payload.system_sku_id && (field === "standard_color" || field === "standard_size")) || (field === "code_status" && value === "pending");
      return { ...current, [row.row_key]: { ...draft, payload: { ...draft.payload, ...(clearNewCode ? { internal_display_sku: null } : {}), ...(field === "internal_display_sku" && value ? { code_status: "confirmed", code_evidence: row.payload.source_code_evidence ?? draft.payload.code_evidence } : {}), reconfirm_required: null, [field]: value } } };
    });
    setSaved(current => { const next = new Set(current); next.delete(row.row_key); return next; });
    setNotice(undefined);
  }
  async function save(selected: CatalogImportRow[], fromFixedAction = false) {
    if (inFlight.current || busy || !canEdit || !selected.length) return;
    if (selected.some(row => row.projection_state === "audit_only")) { setError("所选记录已转为只读来源证据，请核对最新状态；未提交本地修改。"); return; }
    if (selected.some(row => staleRows.some(stale => stale.row_key === row.row_key))) {
      setFailedRow(selected.find(row => staleRows.some(stale => stale.row_key === row.row_key))?.row_key);
      setError("有修改行的服务端内容已变化，请核对最新值并放弃该行旧修改后重新编辑。"); return;
    }
    const active = document.activeElement;
    const scroller = root.current?.querySelector<HTMLElement>("[aria-label='当前分类审核表格']");
    if (active instanceof HTMLElement && (fromFixedAction || root.current?.contains(active))) {
      bookmark.current = {
        element: active, rowKey: active.closest<HTMLElement>("[data-review-row]")?.dataset.reviewRow ?? (fromFixedAction ? selected[0]?.row_key : undefined),
        field: active.closest<HTMLElement>("[data-review-field]")?.dataset.reviewField,
        visibleKeys: filteredRows.map(row => row.row_key), left: scroller?.scrollLeft ?? 0, top: scroller?.scrollTop ?? 0,
        x: window.scrollX, y: window.scrollY,
        selection: active instanceof HTMLTextAreaElement || (active instanceof HTMLInputElement && active.type === "text") ? [active.selectionStart, active.selectionEnd] : undefined,
      };
    }
    setFailedRow(undefined);
    inFlight.current = true; setSaving(true); onSavingChange?.(section, true); setError(undefined); setNotice(undefined);
    let acknowledged = false;
    const submitted = selected.map(row => ({ ...row, payload: { ...(drafts[row.row_key]?.payload ?? row.payload), ...(row.payload.reconfirm_required ? { reconfirm_required: null } : {}) } }));
    try {
      const mutations = submitted.map(row => ({
        decision_group_key: section === "exceptions" || section === "mappings" ? row.row_key : null,
        payload: row.payload, row_key: section === "exceptions" || section === "mappings" ? null : row.row_key,
        type: mutationType(section, row),
      }));
      let result;
      try { result = await saveMutations(importId, workflowRevision, mutations); }
      catch (reason) {
        if (!(reason instanceof ApiRequestError) || reason.status !== 409 || reason.code !== "catalog_workflow_revision_conflict" || !onRecoverConflict) throw reason;
        setAnnouncement("正在同步最新草稿，当前输入会保留。");
        const latest = await onRecoverConflict();
        if (!latest.canEdit) throw new Error("批次已结束或当前账号无权编辑，未再次提交；本地修改仍保留。");
        if (!latest.unchanged) throw new Error("最新草稿已读回，其他位置的内容发生变化；请核对本地修改与下方最新值后保存。");
        if (latest.workflowRevision <= workflowRevision) throw reason;
        result = await saveMutations(importId, latest.workflowRevision, mutations);
      }
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
      const message = reason instanceof ApiRequestError && reason.status === 409
        ? reason.code === "catalog_workflow_revision_conflict" ? "批次仍在变化，已停止自动重试；请重新读取草稿后核对。"
          : reason.code === "catalog_draft_reservation_conflict" ? "商品归属与已有审核记录冲突，请核对待审核批次、已生效归属或排除依据，再继续本次审核。"
          : reason.code === "catalog_publication_revision_conflict" || reason.code === "catalog_projection_stale" ? "目录已有新版本，请核对当前目录基准后继续，当前修改保留。"
          : reason.code === "outcome_unknown" || reason.code === "idempotency_key_reused" ? "本次保存结果需要核实，请保留窗口，不要重复提交。"
          : `保存未完成（${reason.code}），当前输入保留，请核对批次状态。`
        : reason instanceof Error ? reason.message : "保存失败。";
      setError(acknowledged ? `草稿已保存，但最新明细读取失败。请重新读取草稿，不要重复提交。${message}` : `${message} 编辑内容已保留，请核对后再保存。`);
    } finally { inFlight.current = false; setSaving(false); onSavingChange?.(section, false); }
  }
  const saveCurrent = useRef<() => void>(() => undefined);
  saveCurrent.current = () => { void save(dirtyRows.slice(0, 500), true); };
  const invokeSave = useCallback(() => saveCurrent.current(), []);
  useEffect(() => {
    if (!active) return;
    onSaveAction?.(canEdit && dirtyCount > 0 ? {
      label: dirtyCount > 500 ? "保存本批修改（前500行）" : `保存当前分类修改（${dirtyCount}行）`,
      disabled: busy || saving, run: invokeSave,
    } : undefined);
  }, [active, canEdit, dirtyCount, busy, saving, invokeSave, onSaveAction]);
  useEffect(() => {
    if (active) return () => onSaveAction?.(undefined);
  }, [active, onSaveAction]);
  return <div className={`${styles.section} ${editorStyles.controls}`} ref={root} onKeyDown={keyboard} tabIndex={-1} role="region" aria-label="当前分类编辑区">
    {canEdit&&suggestions.length>0&&<details open className={editorStyles.suggestions}><summary>可批量核对 {suggestions.length} 条明确来源建议</summary><p>核对唯一来源编码、颜色尺码或已明确目标，歧义项仍须单独判断。</p><label><input type="checkbox" disabled={busy||saving} checked={suggestions.slice(0,500).every(s=>suggestionKeys.includes(s.row.row_key))} onChange={e=>setSuggestionKeys(e.target.checked?suggestions.slice(0,500).map(s=>s.row.row_key):[])}/>选择本批建议（最多500条）</label><ul>{suggestions.slice(0,500).map(({row,patch})=><li key={row.row_key}><label><input type="checkbox" disabled={busy||saving} checked={suggestionKeys.includes(row.row_key)} onChange={e=>setSuggestionKeys(keys=>e.target.checked?[...keys,row.row_key]:keys.filter(k=>k!==row.row_key))}/><strong>{patch.internal_display_sku??sourceIdentity(section,row,productionSource).title}</strong><span>{Object.entries(patch).filter(([key])=>!['code_evidence','change_reason'].includes(key)).map(([key,value])=>`${FIELD_META[key]?.label??key}：${displayChange(row,key,value)}`).join(' · ')}</span></label></li>)}</ul><Button variant="secondary" disabled={busy||saving||!suggestionKeys.some(k=>suggestions.some(s=>s.row.row_key===k))} onClick={acceptSuggestions}>采用所选建议</Button></details>}

    <span className={styles.srOnly} role="status" aria-live="polite">{announcement}</span>
    {canEdit && isEditableSection(section) && <p className={styles.keyboardHelp}>Tab 切换字段 · Alt + ↑ / ↓ 切换行 · Ctrl / ⌘ + Enter 保存分类 · Esc 撤销当前文本字段</p>}
    {error && <StatusMessage kind="danger" title="保存需要处理" action={failedRow ? <Button disabled={busy || saving} onClick={() => { if (onLocateRow) onLocateRow(failedRow); else focusRow(failedRow)?.scrollIntoView({ block: "center", inline: "nearest" }); }} variant="secondary">返回修改行</Button> : undefined}>{error}</StatusMessage>}
    {staleRows.map(row => <StatusMessage key={row.row_key} kind="warning" title={`${sourceIdentity(section, row).title} 已更新`} action={<><Button disabled={busy || saving} onClick={() => undo(row)}>放弃该行旧修改</Button>{canKeepLocal(row) && <Button disabled={busy || saving} onClick={() => keepLocal(row)}>保留我的修改</Button>}</>}>
      <p>最新值与本地修改不同，请核对后选择；输入未被覆盖。</p>
      <dl>{remoteFields(row).filter(field => EDITABLE_FIELDS[section].includes(field)).map(field => <div key={field}><dt>{FIELD_META[field]?.label ?? field}</dt><dd>最新：{displayChange(row, field, row.payload[field])}；我的输入：{displayChange(row, field, drafts[row.row_key]?.payload[field])}</dd></div>)}</dl>
      {!canKeepLocal(row) && <p>商品身份、来源或编辑权限已变化，请按最新资料重新核对。</p>}
    </StatusMessage>)}
    {notice && <StatusMessage kind={dirtyCount ? "info" : "success"} title={dirtyCount ? "修改尚未保存" : "草稿保存完成"}>{notice}</StatusMessage>}
    {!rows.length ? <EmptyState title="当前分类没有记录" description="可以切换到其他审核分类。" />
      : !filteredRows.length ? <EmptyState title="没有符合筛选条件的审核项" description={onlyPending ? "当前分类已没有待处理项，或搜索条件没有匹配。" : "请调整搜索条件。"} />
        : <div aria-label="当前分类审核表格" className={styles.tableScroll} role="region" tabIndex={0}><table className={`${styles.table} ${section === "mappings" ? `${editorStyles.reviewCards} ${editorStyles.mappingTable}` : section === "skus" ? `${editorStyles.reviewCards} ${editorStyles.skuTable}` : section === "exceptions" ? editorStyles.exceptionTable : `catalog-review-table catalog-review-table--${section}`}`}><thead><tr><th>来源审核项</th>{EDITABLE_FIELDS[section].map(field => <th key={field}>{FIELD_META[field]?.label ?? field}</th>)}<th>操作</th>{section === "mappings" && <th>身份归属</th>}</tr></thead><tbody>
          {filteredRows.map(row => <RowEditor active={active} issues={issues} onUndo={() => undo(row)} canEdit={canEdit} identityBlocked={identityBlocked || dirtyCount > 0} dirty={Boolean(drafts[row.row_key] && changed(section, drafts[row.row_key]))} importId={importId} key={row.row_key}
            onChange={(field, value) => edit(row, field, value)} onSave={() => void save([row])} onSaved={onSaved} options={options}
            payload={drafts[row.row_key]?.payload ?? row.payload} productionSource={productionSource} row={row} saved={saved.has(row.row_key)} section={section} tableSaving={busy || saving} workflowRevision={workflowRevision} />)}
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
