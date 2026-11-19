import { Link } from "react-router-dom";
import { ArrowRight, ChevronLeft, ChevronRight, FileSpreadsheet, History, RefreshCw } from "lucide-react";
import { Button, EmptyState, Skeleton, StatusBadge, StatusMessage } from "../../design-system";
import styles from "./CatalogImportHistoryView.module.css";
export type CatalogHistory = { items: { import_id: number; source_kind: string; record_kind?: string; review_path?: string; source_name?: string; approved_catalog_version_number?: number | null; status: string; workflow_revision: number }[]; has_next: boolean };
const labels: Record<string, string> = { approved: "已批准", draft: "草稿", ready_for_review: "待审核", in_review: "审核中", rejected: "已退回", validation_failed: "校验未通过", parsing: "解析中", parse_failed: "解析失败", needs_attention: "待补全", validated: "已校验", withdrawn: "已撤回", superseded: "已取代", uploaded: "已上传", parsed: "已解析", ready_for_approval: "待批准" };
export function CatalogImportHistoryView({ result, error, page, onReload, onPageChange, onOpenReview }: {
  result?: CatalogHistory; error?: string; page: number; onReload: () => void; onPageChange: (page: number) => void; onOpenReview: () => void;
}) {
  return <section className={styles.panel} aria-label="已有审核批次" aria-busy={!result && !error || undefined}>
    <header className={styles.heading}><div><h2>已有审核批次{result&&<span className={styles.count}>{result.items.length}</span>}</h2></div><Button variant="quiet" icon={<RefreshCw size={17}/>} aria-label="刷新批次" onClick={onReload}/></header>
    {error ? <StatusMessage kind="danger" title="批次读取未完成">{error}<br />点击“刷新批次”重新读取当前页；不会生成新候选。</StatusMessage> : !result ? <div className={styles.loading}><p role="status">正在读取审核批次…</p><Skeleton lines={3} /></div> : <>
      {result.items.length === 0 ? <EmptyState icon={<History />} title={page === 1 ? "暂无审核批次" : "当前页没有审核批次"} description={page === 1 ? "使用上方入口建档或维护商品。" : "可以返回上一页，或刷新当前页核对最新记录。"} /> : <ul className={styles.history}>{result.items.map(item => <li key={item.import_id}>
        <FileSpreadsheet className={styles.fileIcon} aria-hidden="true"/><div className={styles.record}><Link onClick={onOpenReview} aria-label={`批次 #${item.import_id} · ${item.record_kind === "listing_source" ? "查看清单／继续未核记录" : item.status === "approved" ? "查看批准结果" : ["withdrawn", "superseded"].includes(item.status) ? "查看批次" : "继续审核"}`} to={item.review_path ?? `/catalog/imports/${item.import_id}`}><strong>{item.source_name || (item.record_kind === "listing_source" ? "原始商品清单" : item.source_kind === "online" ? "在线候选" : item.source_kind === "production" ? "商品建档候选" : "目录工作簿")}</strong><ArrowRight aria-hidden="true" /></Link><div className={styles.metadata}><span>{item.record_kind === "listing_source" ? "原始清单" : item.source_kind === "online" ? "在线候选" : item.source_kind === "production" ? "建档候选" : "目录工作簿"}</span><span>批次 #{item.import_id}</span><span>修订 {item.workflow_revision}</span></div></div>
        <StatusBadge label={item.status === "approved" && item.approved_catalog_version_number ? `已批准V${item.approved_catalog_version_number}` : labels[item.status] ?? item.status} tone={item.status === "approved" ? "good" : ["validation_failed", "parse_failed"].includes(item.status) ? "bad" : "quiet"} />
      </li>)}</ul>}
      {(page>1||result.has_next)&&<nav className={styles.pagination} aria-label="审核批次分页"><Button icon={<ChevronLeft />} disabled={page === 1} onClick={() => onPageChange(page - 1)}>上一页</Button><span aria-current="page" aria-live="polite">第 {page} 页</span><Button icon={<ChevronRight />} disabled={!result.has_next} onClick={() => onPageChange(page + 1)}>下一页</Button></nav>}
    </>}
  </section>;
}
