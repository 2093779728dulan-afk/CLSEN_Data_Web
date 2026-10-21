import { LocateFixed, TriangleAlert } from "lucide-react";
import { Button, EmptyState, StatusBadge } from "../../design-system";
import styles from "./CatalogIssueSummary.module.css";
import type { CatalogRowIssue } from "./catalogTypes";

const FIELDS: Record<string, string> = { standard_name: "标准商品名称", internal_display_sku: "内部展示 SKU", standard_color: "标准颜色", standard_size: "标准尺码", identity_decision: "映射决定" };
const SECTIONS: Record<string, string> = { styles: "款式命名", skus: "SKU 标准化", mappings: "SKU 映射", exceptions: "解析异常" };

export function CatalogIssueSummary({ status, issues = [], failureReason, onLocate }: { status: string; issues?: CatalogRowIssue[]; failureReason?: string | null; onLocate?: (issue: CatalogRowIssue) => void }) {
  if (status !== "needs_attention" && status !== "parse_failed") return null;
  return <aside className={styles.panel} aria-label="商品审核问题">
    <header className={styles.heading}><h2><TriangleAlert aria-hidden="true" />{status === "parse_failed" ? "解析未完成" : "审核尚未完成"}</h2><StatusBadge tone="quiet" label={`${issues.length} 条问题`} /></header>
    <p className={styles.description}>{status === "parse_failed" ? "请检查六张工作表、模板表头及公式。文件内容有误时，请修正原文件并到批量维护重新上传；只有可恢复的暂时故障才使用下方“恢复解析”。" : "点击问题定位到对应行，保存修改后重新校验。这里只展示服务端返回的当前修订问题（最多 500 条）。"}</p>
    {failureReason && <p className={styles.failure}>原因代码：<code>{failureReason}</code></p>}
    {issues.length > 0 ? <ol className={styles.list}>{issues.map((issue, index) => <li className={styles.issue} key={`${issue.row_key}:${issue.field}:${index}`}>
      <span className={styles.number} aria-hidden="true">{index + 1}</span>
      <div className={styles.detail}><strong>{SECTIONS[issue.section] ?? issue.section} · {FIELDS[issue.field?.replace(/^\//, "") ?? ""] ?? issue.field ?? "审核决定"}：{issue.reason_code === "required" ? "尚未填写或确认" : issue.reason_code}</strong><div className={styles.metadata}><StatusBadge tone={issue.severity === "warning" ? "warn" : issue.severity === "error" || issue.severity === "blocking" ? "bad" : "quiet"} label={issue.severity === "warning" ? "警告" : issue.severity === "error" ? "错误" : issue.severity === "blocking" ? "阻断" : issue.severity} />{issue.row_key ? <code>{issue.row_key}</code> : <span>此项没有行定位信息</span>}</div></div>
      {issue.row_key && onLocate && <Button icon={<LocateFixed />} variant="secondary" onClick={() => onLocate(issue)}>定位问题 {index + 1}</Button>}
    </li>)}</ol> : status === "needs_attention" && <EmptyState title="暂无逐行问题" description="当前响应未包含逐行问题；这不代表当前草稿已通过审核。" />}
  </aside>;
}
