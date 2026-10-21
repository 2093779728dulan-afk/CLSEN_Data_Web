import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { Button } from "../../design-system";

import { saveCatalogMutation } from "./catalogApi";
import { CatalogIdentityOwners } from "./CatalogIdentityOwners";
import type { CatalogReviewOption, CatalogReviewOptionIndex } from "./catalogReviewOptions";
import { isEditableSection, type CatalogImportRow, type CatalogSection } from "./catalogTypes";

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

function EditableText({ field, onChange, rowKey, value }: { field: string; onChange: (value: string | null) => void; rowKey: string; value: string }) {
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
  const props = { "aria-label": `${rowKey} ${field}`, onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(event.target.value || null), placeholder: FIELD_META[field]?.placeholder ?? "请输入标准值", value };
  return <div className={`catalog-clearable-field${multiline ? " catalog-name-field" : ""}`}>
    {multiline ? <textarea {...props} ref={editor} rows={1} /> : <input {...props} ref={editor} />}
    <button aria-label={`清空${label}`} className="catalog-field-clear" disabled={!value} onClick={() => { onChange(null); editor.current?.focus(); }} title={`清空${label}`} type="button">×</button>
  </div>;
}

function SuggestedField({ field, onChange, options, rowKey, value }: { field: string; onChange: (value: string | null) => void; options: CatalogReviewOption[]; rowKey: string; value: string }) {
  const [manual, setManual] = useState(!options.some((option) => option.value === value) && Boolean(value));
  const label = FIELD_META[field]?.label ?? field;
  if (manual) return <div className="catalog-suggested-field"><EditableText field={field} onChange={onChange} rowKey={rowKey} value={value} /><button aria-label={`从报告候选中选择 ${label}`} onClick={() => { setManual(false); onChange(options[0]?.value ?? null); }} type="button">选择报告候选</button></div>;
  return <div className="catalog-suggested-field"><div className="catalog-clearable-field"><select aria-label={`${rowKey} ${field}`} onChange={(event) => { if (event.target.value === "__manual__") { setManual(true); } else onChange(event.target.value || null); }} value={value}>
    <option value="">请选择报告候选</option>{options.map((option) => <option key={option.value} value={option.value}>{field === "standard_color" || field === "standard_size" || field === "internal_display_sku" ? option.value : option.label}</option>)}<option value="__manual__">手动输入其他值…</option>
  </select><button aria-label={`清空${label}`} className="catalog-field-clear" disabled={!value} onClick={() => { setManual(true); onChange(null); }} title={`清空${label}`} type="button">×</button></div>{field === "standard_name" && value && <p className="catalog-name-preview">{value}</p>}</div>;
}

function RowEditor({ canEdit, importId, onSavingChange, onSaved, options, row, section, tableSaving, workflowRevision }: { canEdit: boolean; importId: number; onSavingChange: (saving: boolean) => void; onSaved: (revision: number) => Promise<void>; options: CatalogReviewOptionIndex; row: CatalogImportRow; section: CatalogSection; tableSaving: boolean; workflowRevision: number }) {
  const [payload, setPayload] = useState(row.payload); const [busy, setBusy] = useState(false); const [error, setError] = useState<string>(); const [saved, setSaved] = useState(false);
  useEffect(() => { setPayload(row.payload); setSaved(false); }, [row]);
  const save = async () => { setBusy(true); onSavingChange(true); setError(undefined); setSaved(false); try { const result = await saveCatalogMutation(importId, workflowRevision, { decision_group_key: section === "exceptions" || section === "mappings" ? row.row_key : null, payload, row_key: section === "exceptions" || section === "mappings" ? null : row.row_key, type: mutationType(section, { ...row, payload }) }); if (typeof result.workflow_revision !== "number") throw new Error("响应缺少新的修订号。"); await onSaved(result.workflow_revision); setSaved(true); } catch (reason) { setError(reason instanceof Error ? reason.message : "保存失败。"); } finally { setBusy(false); onSavingChange(false); } };
  const pending = isCatalogRowPending(section, { ...row, payload }); const identity = sourceIdentity(section, row);
  if (!canEdit) return <tr><td><strong>{identity.title}</strong><small>{identity.detail}</small></td>{EDITABLE_FIELDS[section].map(field => <td key={field}>{String(row.payload[field] ?? "—")}</td>)}<td>只读</td></tr>;
  return <tr className={pending ? "catalog-review-row is-pending" : "catalog-review-row"}><td data-label="来源审核项"><strong>{identity.title}</strong><small>{identity.detail}</small></td>{EDITABLE_FIELDS[section].map((field) => { const meta = FIELD_META[field] ?? { label: field }; const value = String(payload[field] ?? ""); const suggestions = options[row.row_key]?.[field] ?? []; return <td data-label={meta.label} key={field}><div className="catalog-cell-label"><span>{meta.label}</span>{meta.options ? <select aria-label={`${row.row_key} ${field}`} onChange={(event) => setPayload((current) => ({ ...current, [field]: event.target.value || null }))} value={value}>{meta.options.map(([option, label]) => <option key={option} value={option}>{label}</option>)}</select> : suggestions.length ? <SuggestedField field={field} onChange={(next) => setPayload((current) => ({ ...current, [field]: next }))} options={suggestions} rowKey={row.row_key} value={value} /> : <EditableText field={field} onChange={(next) => setPayload((current) => ({ ...current, [field]: next }))} rowKey={row.row_key} value={value} />}</div></td>; })}<td className="catalog-row-action">{isEditableSection(section) && <Button aria-label="保存此行" disabled={busy || tableSaving} loading={busy} onClick={() => void save()} variant="primary">保存此行</Button>}{saved && <span className="catalog-save-success" role="status">已保存</span>}{error && <span className="form-error" role="alert">{error}</span>}</td>{section === "mappings" && <td className="catalog-mapping-details"><details><summary>归属、冲突与恢复</summary><CatalogIdentityOwners importId={importId} row={row} revision={workflowRevision} onSaved={onSaved} /></details></td>}</tr>;
}

export function CatalogImportSectionTable({ canEdit = true, importId, onlyPending = false, onSaved, options = {}, query = "", rows, section, workflowRevision }: { canEdit?: boolean; importId: number; onlyPending?: boolean; onSaved: (revision: number) => Promise<void>; options?: CatalogReviewOptionIndex; query?: string; rows: CatalogImportRow[]; section: CatalogSection; workflowRevision: number }) {
  const [saving, setSaving] = useState(false);
  const filteredRows = useMemo(() => rows.filter((row) => (!onlyPending || isCatalogRowPending(section, row)) && (!query.trim() || `${row.row_key} ${Object.values(row.payload).join(" ")}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))), [onlyPending, query, rows, section]);
  if (!rows.length) return <p className="catalog-empty">当前分类没有记录。</p>;
  if (!filteredRows.length) return <p className="catalog-empty">没有符合筛选条件的审核项。{onlyPending && " 当前分类已没有待处理项。"}</p>;
  return <div className="catalog-table-scroll"><table className={`catalog-review-table catalog-review-table--${section}`}><thead><tr><th>来源审核项</th>{EDITABLE_FIELDS[section].map((field) => <th key={field}>{FIELD_META[field]?.label ?? field}</th>)}<th>操作</th></tr></thead><tbody>{filteredRows.map((row) => <RowEditor canEdit={canEdit} importId={importId} key={row.row_key} onSavingChange={setSaving} onSaved={onSaved} options={options} row={row} section={section} tableSaving={saving} workflowRevision={workflowRevision} />)}</tbody></table></div>;
}
