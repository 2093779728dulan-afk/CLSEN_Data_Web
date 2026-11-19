import type { Result, Selection, SourceRow } from "./CatalogListingSourcePage";

/** Read only a four-byte prefix after cheap metadata checks; the server validates OOXML. */
export async function checkProductUpload(file: File): Promise<void> {
  if (!file.name.toLowerCase().endsWith(".xlsx") || /[\\/]/.test(file.name) || [...file.name].some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127) || file.name.length > 512) throw new Error("请选择.xlsx产品信息表；不支持旧版.xls、CSV、压缩包或程序文件。");
  if (!file.size) throw new Error("文件为空，请检查后重新选择。");
  if (file.size > 64 * 1024 * 1024) throw new Error("文件超过64MiB，请拆分后上传。");
  if (file.type && !["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream", "application/zip", "application/x-zip-compressed"].includes(file.type)) throw new Error("文件声明的类型与XLSX不符，请用Excel或WPS另存为.xlsx后上传。");
  const prefix = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(new Error("无法检查本地文件，请确认文件可读取后重新选择。"));
    reader.onabort = () => reject(new Error("文件检查已取消，请重新选择。"));
    reader.readAsArrayBuffer(file.slice(0, 4));
  });
  const bytes = new Uint8Array(prefix);
  if (bytes.length !== 4 || bytes[0] !== 0x50 || bytes[1] !== 0x4b || bytes[2] !== 0x03 || bytes[3] !== 0x04) throw new Error("文件内容不像有效的XLSX，不能只修改扩展名；请另存为.xlsx后上传。");
}

export const intakeStateLabels: Record<string, string> = { registered: "已建档", missing: "待建档", parent: "父级资料", error: "格式错误", conflict: "身份冲突", disabled: "已停用待核", needs_review: "待人工核对" };

export function intakeSelections(data: Result): Record<string, Selection> {
  return Object.fromEntries(data.source.listing_rows.map(row => {
    const saved = data.source.selections.find(item => item.row_id === row.row_id);
    if (saved) return [row.row_id, { ...saved, include: saved.include && !!data.source.bindings[row.sheet] }];
    const assessment = data.assessments.find(item => item.row_id === row.row_id);
    const state = row.registration?.state;
    const sku = data.inventory.find(item => item.sku_id === row.registration?.sku_id);
    const mapped = data.mappings.some(item => item.report_source_scope_id === data.source.bindings[row.sheet] && item.seller_sku === row.seller_sku && item.sku_id === sku?.sku_id);
    const valid = !!data.source.bindings[row.sheet] && !mapped && !row.issues.length && !row.format_issues?.length && !["error", "conflict", "disabled", "needs_review"].includes(state || "");
    const selection: Selection = {
      row_id: row.row_id, include: valid && (!assessment || assessment.primary_row === row.row_id) && !["source_conflict", "official_conflict", "source_difference"].includes(assessment?.state || ""),
      record_type: row.suggested_type, selected_sku_id: sku?.sku_id ?? null,
      style_code: sku?.style_code ?? row.suggestion?.style_code ?? "", color: sku?.standard_color ?? row.suggestion?.color ?? "", size: sku?.standard_size ?? row.suggestion?.size ?? "",
      use_official: false, confirm_raw_parent: row.suggested_type === "parent", note: "",
    };
    return [row.row_id, selection];
  }));
}

const issueLabels: Record<string, string> = { SKU_WHITESPACE: "空白字符", SKU_STRUCTURE: "格式结构", SKU_STYLE: "款号格式", SKU_COMPONENT_ORDER: "排列顺序", SKU_COLOR_CASE: "颜色大小写", SKU_SIZE_CASE: "尺码大小写", SKU_SIZE_INVALID: "尺码无效", SKU_COLOR_SPELLING_REVIEW: "颜色拼写待核" };
export function intakeBlocking(row: SourceRow) { return row.issues.length > 0 || !!row.format_issues?.some(issue => issue.severity !== "warning"); }

export function intakeIssues(row: SourceRow) {
  return row.format_issues?.length ? row.format_issues.map(issue => `${issue.cell} · ${issueLabels[issue.code] || "资料问题"}：${issue.message}`) : row.issues;
}
