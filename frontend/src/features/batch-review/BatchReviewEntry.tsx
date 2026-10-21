import { Button } from "../../design-system";
import { useMemo, useState } from "react";

import { BatchReviewApi } from "./batchReviewApi";

export function BatchReviewEntry({
  batchIds,
  onCreated,
}: {
  batchIds: readonly number[];
  onCreated?: (runId: number) => void;
}) {
  const uniqueIds = useMemo(() => [...new Set(batchIds)].sort((a, b) => a - b), [batchIds]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const api = useMemo(() => new BatchReviewApi(), []);
  if (!onCreated || uniqueIds.length < 2) return null;

  const create = async () => {
    setBusy(true); setError(undefined);
    try {
      const run = await api.createPreflight(uniqueIds);
      onCreated(run.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法创建批量审核预检。");
    } finally {
      setBusy(false);
    }
  };

  return <aside className="batch-review-entry" aria-label="批量审核入口">
    <div><strong>批量审核 {uniqueIds.length} 个服务器批次</strong><p>一次核对日期与类型，安全项目最多三项并行推进到待发布。</p></div>
    <Button variant="primary" disabled={busy} onClick={() => void create()} type="button">{busy ? "正在创建预检…" : "批量审核"}</Button>
    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </aside>;
}
