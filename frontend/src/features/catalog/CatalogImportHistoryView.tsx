import { Link } from "react-router-dom";
import { ArrowRight, ChevronLeft, ChevronRight, FileSpreadsheet, History, RefreshCw } from "lucide-react";
import { Button, EmptyState, Skeleton, StatusBadge, StatusMessage } from "../../design-system";
import styles from "./CatalogImportHistoryView.module.css";
export type CatalogHistory = { items: { import_id: number; source_kind: string; status: string; workflow_revision: number }[]; has_next: boolean };
const labels: Record<string, string> = { approved: "已批准", draft: "草稿", ready_for_review: "待审核", in_review: "审核中", rejected: "已退回", validation_failed: "校验未通过", parsing: "解析中", parse_failed: "解析失败", needs_attention: "待补全", validated: "已校验", withdrawn: "已撤回", superseded: "已取代", uploaded: "已上传", parsed: "已解析", ready_for_approval: "待批准" };
export function CatalogImportHistoryView({ result, error, page, onReload, onPageChange, onOpenReview }: {
  result?: CatalogHistory; error?: string; page: number; onReload: () => void; onPageChange: (page: number) => void; onOpenReview: () => void;
}) {
  return <section className={styles.panel} aria-label="已有审核批次" aria-busy={!result && !error || undefined}>
    <header className={styles.heading}><div><h2><History aria-hidden="true" />已有审核批次</h2><p>继续处理已有批次，或查看已批准结果，无需重新生成候选。</p></div><Button icon={<RefreshCw />} onClick={onReload}>刷新批次</Button></header>
    {error ? <StatusMessage kind="danger" title="批次读取未完成">{error}<br />点击“刷新批次”重新读取当前页；不会生成新候选。</StatusMessage> : !result ? <div className={styles.loading}><p role="status">正在读取审核批次…</p><Skeleton lines={3} /></div> : <>
      <div className={styles.summary}><span>本页 <strong>{result.items.length}</strong> 个批次</span><span>在线候选与文件导入统一记录</span></div>
      {result.items.length === 0 ? <EmptyState icon={<History />} title={page === 1 ? "暂无审核批次，可在下方生成候选。" : "当前页没有审核批次"} description={page === 1 ? "生成并建立审核草稿后，可从这里继续处理。" : "可以返回上一页，或刷新当前页核对最新记录。"} /> : <ul className={styles.history}>{result.items.map(item => <li key={item.import_id}>
        <div className={styles.record}><Link onClick={onOpenReview} to={`/catalog/imports/${item.import_id}`}><strong>批次 #{item.import_id}</strong><span> · {item.status === "approved" ? "查看批准结果" : ["withdrawn", "superseded"].includes(item.status) ? "查看批次" : "继续审核"}</span><ArrowRight aria-hidden="true" /></Link><div className={styles.metadata}><span><FileSpreadsheet aria-hidden="true" />{item.source_kind === "online" ? "在线候选" : "文件导入"}</span><span>修订 <strong>{item.workflow_revision}</strong></span></div></div>
        <StatusBadge label={labels[item.status] ?? item.status} tone={item.status === "approved" ? "good" : ["validation_failed", "parse_failed"].includes(item.status) ? "bad" : "quiet"} />
      </li>)}</ul>}
      <nav className={styles.pagination} aria-label="审核批次分页"><Button icon={<ChevronLeft />} disabled={page === 1} onClick={() => onPageChange(page - 1)}>上一页</Button><span aria-current="page" aria-live="polite">第 {page} 页</span><Button icon={<ChevronRight />} disabled={!result.has_next} onClick={() => onPageChange(page + 1)}>下一页</Button></nav>
    </>}
  </section>;
}
