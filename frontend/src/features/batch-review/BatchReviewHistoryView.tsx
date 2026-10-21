import { RefreshCw } from "lucide-react";
import { Button, EmptyState, ErrorState, Skeleton, StatusBadge } from "../../design-system";
import type { BatchHistory } from "./BatchReviewHistory";
import css from "./BatchReviewHistoryView.module.css";

const labels: Record<string, string> = { preview: "待确认", confirmed: "已确认", running: "执行中", paused: "已暂停", completed: "已完成", completed_with_exceptions: "完成，有待处理项" };
type Props = { page: number; result?: BatchHistory; error?: string; onRetry: () => void; onPageChange: (value: number) => void };
export function BatchReviewHistoryView({ page, result, error, onRetry, onPageChange }: Props) {
  return <section aria-label="已有批量审核任务" className={css.history}>
    <header><div><h2>已有批量审核任务</h2><p>找回预检、暂停或完成的任务。进入执行中的任务会按原流程继续；暂停任务需要手动恢复。</p></div><Button icon={<RefreshCw />} onClick={onRetry} variant="quiet">刷新任务</Button></header>
    {error ? <ErrorState title="任务读取失败" description={error} action={<Button onClick={onRetry}>重新读取任务</Button>} /> : !result ? <div role="status"><p>正在读取任务…</p><Skeleton lines={2} /></div> : <>
      {result.items.length ? <ul>{result.items.map(item => <li key={item.id}><a href={`/review/batch/${item.id}`}>任务 #{item.id} · {labels[item.status] ?? item.status}</a><StatusBadge label={`修订 ${item.revision}`} tone="quiet" /></li>)}</ul> : <EmptyState title="暂无批量审核任务。" description="上传至少两份符合条件的报告后，可在上传队列中发起批量审核。" />}
      <nav aria-label="批量任务分页"><Button disabled={page === 1} onClick={() => onPageChange(page - 1)}>上一页</Button><span> 第 {page} 页 </span><Button disabled={!result.has_next} onClick={() => onPageChange(page + 1)}>下一页</Button></nav>
    </>}
  </section>;
}
