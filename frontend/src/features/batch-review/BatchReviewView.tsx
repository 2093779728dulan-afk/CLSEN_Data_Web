import { RefreshCw } from "lucide-react";
import { Button, Checkbox, ErrorState, LinkButton, Skeleton, StatusMessage } from "../../design-system";
import { BatchReviewSummary } from "./BatchReviewSummary";
import { BatchReviewPreflightTable } from "./BatchReviewPreflightTable";
import { BatchReviewProgressTable } from "./BatchReviewProgressTable";
import { BatchReviewCompletionActions } from "./BatchReviewCompletionActions";
import type { BatchReviewItem, BatchReviewRun } from "./batchReviewTypes";
import css from "./BatchReviewPage.module.css";

type Props = {
  run?: BatchReviewRun; loading: boolean; error?: string; selectedIds: ReadonlySet<number>; accepted: boolean;
  busyAction?: string; busyItemId?: number; onRefresh: () => void; onToggle: (id: number, selected: boolean) => void;
  onAccept: (value: boolean) => void; onConfirm: () => void; onChangeState: (action: "pause" | "resume") => void;
  onRetry: (item: BatchReviewItem) => void;
};

export function BatchReviewView({ run, loading, error, selectedIds, accepted, busyAction, busyItemId, onRefresh, onToggle, onAccept, onConfirm, onChangeState, onRetry }: Props) {
  return <main className={css["batch-review-page"]} id="main-content">
    <nav aria-label="批量审核导航"><LinkButton to="/versions">返回版本记录</LinkButton></nav>
    {loading ? <div role="status"><p>正在读取批量任务…</p><Skeleton lines={4} /></div> : !run ?
      <ErrorState title="无法打开批量审核" description={error} action={<Button icon={<RefreshCw />} onClick={onRefresh}>重新读取</Button>} /> : <>
        <BatchReviewSummary run={run} />
        {error && <StatusMessage kind="danger" title="批量任务操作未完成" action={<Button icon={<RefreshCw />} onClick={onRefresh}>重新读取任务</Button>}>{error}</StatusMessage>}
        {run.status === "preview" ? <section aria-labelledby="batch-review-preflight-title" className={css["batch-review-panel"]}>
          <div className={css["batch-review-heading-row"]}><div><p className={css.kicker}>核对日期与报表类型</p><h2 id="batch-review-preflight-title">核对文件清单</h2></div><Button variant="quiet" icon={<RefreshCw />} onClick={onRefresh}>刷新预检</Button></div>
          <p className={css["batch-review-safety-note"]}>只选择预检通过的文件。重复目标、已有草稿和其他异常需分别处理。</p>
          <BatchReviewPreflightTable items={run.items} onToggle={onToggle} selectedIds={selectedIds} />
          <footer className={css.confirmation}>
            <Checkbox checked={accepted} label="我已核对所选文件的报告日期和报表类型。" onChange={event => onAccept(event.currentTarget.checked)} />
            <Button variant="primary" loading={busyAction === "confirm"} disabled={!accepted || selectedIds.size === 0 || busyAction === "confirm"} onClick={onConfirm}>{busyAction === "confirm" ? "正在开始…" : `开始批量审核（${selectedIds.size} 项）`}</Button>
          </footer>
        </section> : <section aria-labelledby="batch-review-progress-title" className={css["batch-review-panel"]}>
          <div className={css["batch-review-heading-row"]}><div><p className={css.kicker}>从保存的任务状态继续</p><h2 id="batch-review-progress-title">处理进度</h2></div><div className={css["batch-review-actions"]}>
            {run.allowed_actions.includes("pause") && <Button variant="quiet" loading={busyAction === "pause"} disabled={busyAction === "pause"} onClick={() => onChangeState("pause")}>{busyAction === "pause" ? "正在暂停…" : "暂停批量处理"}</Button>}
            {run.allowed_actions.includes("resume") && <Button variant="primary" loading={busyAction === "resume"} disabled={busyAction === "resume"} onClick={() => onChangeState("resume")}>{busyAction === "resume" ? "正在恢复…" : "恢复批量处理"}</Button>}
            <Button variant="quiet" icon={<RefreshCw />} onClick={onRefresh}>刷新状态</Button>
          </div></div>
          {run.status === "paused" && <StatusMessage kind="warning" title="任务已暂停">已完成的结果会保留。点击恢复批量处理，继续剩余项目。</StatusMessage>}
          <BatchReviewProgressTable busyItemId={busyItemId} items={run.items} onRetry={onRetry} />
        </section>}
        <BatchReviewCompletionActions run={run} />
      </>}
  </main>;
}
