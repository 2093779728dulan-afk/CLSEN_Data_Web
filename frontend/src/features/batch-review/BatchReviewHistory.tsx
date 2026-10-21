import { useEffect, useState } from "react";
import { requestApi } from "../../api/client";
type History = { items: { id: number; status: string; revision: number }[]; has_next: boolean };
const labels: Record<string, string> = { preview: "待确认", confirmed: "已确认", running: "执行中", paused: "已暂停", completed: "已完成", completed_with_exceptions: "完成，有待处理项" };
export function BatchReviewHistory() {
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<History>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    let active = true;
    setResult(undefined); setError(undefined);
    void requestApi<History>(`/api/imports/batch-reviews?page=${page}`).then((value) => { if (active) setResult(value); }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "任务读取失败"); });
    return () => { active = false; };
  }, [page, retry]);
  return <section aria-label="已有批量审核任务" className="version-history__boundary">
    <h2>已有批量审核任务</h2><p>找回预检、暂停或完成的任务。进入执行中的任务会按原流程继续；暂停任务需要手动恢复。</p>
    <button type="button" onClick={() => setRetry(retry + 1)}>刷新任务</button>
    {error ? <p role="alert">{error}</p> : !result ? <p role="status">正在读取任务…</p> : <>
      {result.items.length ? <ul>{result.items.map((item) => <li key={item.id}><a href={`/review/batch/${item.id}`}>任务 #{item.id} · {labels[item.status] ?? item.status}</a> · 修订 {item.revision}</li>)}</ul> : <p>暂无批量审核任务。上传至少两份符合条件的报告后，可在上传队列中发起批量审核。</p>}
      <button type="button" disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</button><span> 第 {page} 页 </span><button type="button" disabled={!result.has_next} onClick={() => setPage(page + 1)}>下一页</button>
    </>}
  </section>;
}
