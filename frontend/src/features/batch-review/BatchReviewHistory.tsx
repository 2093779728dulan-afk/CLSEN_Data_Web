import { useEffect, useState } from "react";
import { BatchReviewHistoryView } from "./BatchReviewHistoryView";
import { requestApi } from "../../api/client";
export type BatchHistory = { items: { id: number; status: string; revision: number }[]; has_next: boolean };

export function BatchReviewHistory() {
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<BatchHistory>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    let active = true;
    setResult(undefined); setError(undefined);
    void requestApi<BatchHistory>(`/api/imports/batch-reviews?page=${page}`).then((value) => { if (active) setResult(value); }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "任务读取失败"); });
    return () => { active = false; };
  }, [page, retry]);
  return <BatchReviewHistoryView page={page} result={result} error={error} onRetry={() => setRetry(retry + 1)} onPageChange={setPage} />;
}
