import css from "./BatchReviewPage.module.css";
import type { BatchReviewRun } from "./batchReviewTypes";
import { PageHeader, StatusBadge } from "../../design-system";

const RUN_LABELS: Record<string, string> = {
  completed: "已完成",
  completed_with_exceptions: "已完成（有异常）",
  confirmed: "正在启动",
  paused: "已暂停",
  preview: "等待确认",
  running: "处理中",
};

export function BatchReviewSummary({ run }: { run: BatchReviewRun }) {
  const counts = [
    ["总文件", run.summary.total],
    ["可执行", run.summary.eligible + run.summary.active],
    ["处理中", run.summary.active],
    ["待发布", run.summary.ready_for_publish],
    ["人工处理", run.summary.manual_review],
    ["失败", run.summary.failed],
  ] as const;
  return <section aria-label="批量任务摘要" className={css["batch-review-summary"]}>
    <PageHeader eyebrow={`批量任务 #${run.id}`} title="批量审核" description="安全项目只推进到待发布，不会自动发布或覆盖现有版本。"
      meta={<StatusBadge label={RUN_LABELS[run.status] ?? run.status} tone={run.status === "completed" ? "good" : run.status === "paused" || run.status === "completed_with_exceptions" ? "warn" : "quiet"} />}
      actions={<span className={css["batch-review-muted"]}>任务修订 {run.revision}</span>} />
    <dl className={css["batch-review-counts"]}>
      {counts.map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count}</dd></div>)}
    </dl>
  </section>;
}
