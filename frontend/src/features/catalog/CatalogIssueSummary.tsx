import { Disclosure } from "../../design-system";
import { LocateFixed, TriangleAlert } from "lucide-react";
import { Button, EmptyState, StatusBadge } from "../../design-system";
import styles from "./CatalogIssueSummary.module.css";
import type { CatalogRowIssue, CatalogSection } from "./catalogTypes";

const FIELDS: Record<string, string> = { standard_name: "标准商品名称", internal_display_sku: "正式SKU", standard_color: "标准颜色", standard_size: "标准尺码", identity_decision: "映射决定" };
const SECTIONS: Record<string, string> = { styles: "款式命名", skus: "SKU 标准化", mappings: "SKU 映射", exceptions: "解析异常" };

export function CatalogIssueSummary({ status, pendingEdits = 0, issues = [], failureReason, onLocate, onSection }: { status: string; pendingEdits?: number; issues?: CatalogRowIssue[]; failureReason?: string | null; onLocate?: (issue: CatalogRowIssue) => void;onSection?:(section:CatalogSection)=>void }) {
  if (status !== "needs_attention" && status !== "parse_failed") return null;
  const grouped=issues.length>6;
  const groups=Object.values(issues.reduce<Record<string,{issue:CatalogRowIssue;count:number}>>((all,issue)=>{const key=`${issue.section}:${issue.field}:${issue.reason_code}`;if(all[key])all[key].count++;else all[key]={issue,count:1};return all;},{}));
  return <aside className={styles.panel} aria-label="商品审核问题">
    <header className={styles.heading}><h2><TriangleAlert aria-hidden="true" />{status === "parse_failed" ? "解析未完成" : pendingEdits ? "上次校验结果" : "审核尚未完成"}</h2><StatusBadge tone="quiet" label={`${issues.length} 条问题`} /></header>
    <p className={styles.description}>{status === "parse_failed" ? "请检查六张工作表、模板表头及公式。文件内容有误时，请修正原文件并到批量维护重新上传；只有可恢复的暂时故障才使用下方“恢复解析”。" : "按分类核对并保存修改，系统会继续检查。原逐行问题与来源证据完整保留。"}</p>
    {pendingEdits > 0 && <p role="status">{pendingEdits} 行修改尚未保存；以下为上次校验的问题，保存后自动更新检查结果。</p>}
    {failureReason && <p className={styles.failure}>原因代码：<code>{failureReason}</code></p>}
    {grouped&&<div className={styles.groups}>{groups.map(({issue,count},index)=><Button variant="secondary" key={index} onClick={()=>onSection?onSection(issue.section):onLocate?.(issue)}>{SECTIONS[issue.section]??issue.section} · {FIELDS[issue.field?.replace(/^\//,"")??""]??"审核决定"} · {count}项</Button>)}</div>}
    {grouped&&<p className={styles.description}>先进入对应分类批量核对建议，原始逐行问题与修订记录保留在下方。</p>}
    <Disclosure open={!grouped}><summary>查看全部逐行问题与证据位置</summary>
    {issues.length > 0 ? <ol className={styles.list}>{issues.map((issue, index) => <li className={styles.issue} key={`${issue.row_key}:${issue.field}:${index}`}>
      <span className={styles.number} aria-hidden="true">{index + 1}</span>
      <div className={styles.detail}><strong>{SECTIONS[issue.section] ?? issue.section} · {FIELDS[issue.field?.replace(/^\//, "") ?? ""] ?? issue.field ?? "审核决定"}：{issue.reason_code === "required" ? "尚未填写或确认" : issue.reason_code === "noncanonical_standard_size" ? "标准尺码请使用3XL，原SKU编码保留" : issue.reason_code === "invalid_standard_name" ? "名称须为文字，最多255个字符；也可以留空待补" : issue.reason_code === "formal_code_decision_required" ? "请选择来源编码或明确待补，并填写确认依据" : issue.reason_code === "mapped_target_formal_code_required" ? "该Seller SKU已纳入目录，请先从来源下拉框确认正式SKU" : issue.reason_code === "formal_code_not_from_source" ? "正式SKU不属于当前来源或已批准编码" : issue.reason_code === "mapping_target_changed" ? "目标规格与本次来源核对结果不一致" : issue.reason_code === "mapped_target_seller_sku_mismatch" ? "正式SKU与当前Seller SKU不一致" : issue.reason_code === "invalid_reference" ? "目标规格不存在或已失效" : issue.reason_code === "reconfirm_required" ? "已保留上批修改，请重新核对并保存" : issue.reason_code}</strong><div className={styles.metadata}><StatusBadge tone={issue.severity === "warning" ? "warn" : issue.severity === "error" || issue.severity === "blocking" ? "bad" : "quiet"} label={issue.severity === "warning" ? "警告" : issue.severity === "error" ? "错误" : issue.severity === "blocking" ? "阻断" : issue.severity} />{issue.row_key ? <code>{issue.row_key}</code> : <span>此项没有行定位信息</span>}</div></div>
      {issue.row_key && onLocate && <Button icon={<LocateFixed />} variant="secondary" onClick={() => onLocate(issue)}>定位问题 {index + 1}</Button>}
    </li>)}</ol> : status === "needs_attention" && <EmptyState title="暂无逐行问题" description="当前响应未包含逐行问题；这不代表当前草稿已通过审核。" />}
    </Disclosure>
  </aside>;
}
