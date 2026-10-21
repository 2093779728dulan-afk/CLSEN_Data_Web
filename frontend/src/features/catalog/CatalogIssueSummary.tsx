import type { CatalogRowIssue } from "./catalogTypes";

const FIELDS: Record<string, string> = { standard_name: "标准商品名称", internal_display_sku: "内部展示 SKU", standard_color: "标准颜色", standard_size: "标准尺码", identity_decision: "映射决定" };
const SECTIONS: Record<string, string> = { styles: "款式命名", skus: "SKU 标准化", mappings: "SKU 映射", exceptions: "解析异常" };

export function CatalogIssueSummary({ status, issues = [], failureReason, onLocate }: { status: string; issues?: CatalogRowIssue[]; failureReason?: string | null; onLocate?: (issue: CatalogRowIssue) => void }) {
  if (status !== "needs_attention" && status !== "parse_failed") return null;
  return <aside className="catalog-issues"><strong>{status === "parse_failed" ? "解析未完成" : "审核尚未完成"}</strong><p>{status === "parse_failed" ? "请检查六张工作表、模板表头及公式。文件内容有误时，请修正原文件并到批量维护重新上传；只有可恢复的暂时故障才使用下方“恢复解析”。" : "点击问题定位到对应行，修改并“保存此行”，再重新校验。这里只展示服务端返回的当前修订问题（最多 500 条）。"}</p>{failureReason && <p>原因代码：{failureReason}</p>}{issues.length > 0 && <ul>{issues.map((issue, index) => <li key={`${issue.row_key}:${issue.field}:${index}`}><span>{SECTIONS[issue.section] ?? issue.section} · {FIELDS[issue.field?.replace(/^\//, "") ?? ""] ?? issue.field ?? "审核决定"}：{issue.reason_code === "required" ? "尚未填写或确认" : issue.reason_code}</span>{issue.row_key && onLocate && <button type="button" onClick={() => onLocate(issue)}>定位问题 {index + 1}</button>}</li>)}</ul>}</aside>;
}
