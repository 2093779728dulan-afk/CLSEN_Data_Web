import css from "./BatchReviewPage.module.css";
import type { BatchReviewRun } from "./batchReviewTypes";

function manualReviewUrl(item: BatchReviewRun["items"][number]) {
  if (!item.manual_review_url || !item.version_id) return item.manual_review_url ?? undefined;
  const separator = item.manual_review_url.includes("?") ? "&" : "?";
  return `${item.manual_review_url}${separator}version_id=${item.version_id}`;
}

export function BatchReviewCompletionActions({ run }: { run: BatchReviewRun }) {
  const hasReady = run.summary.ready_for_publish > 0;
  const exceptions = run.items.filter((item) => item.status === "manual_review" || item.status === "failed");
  if (!hasReady && exceptions.length === 0) return null;
  return <section aria-labelledby="batch-review-completion-title" className={css["batch-review-completion"]}>
    <h2 id="batch-review-completion-title">后续操作</h2>
    <div className={css["batch-review-actions"]}>
      {hasReady ? <a className={css.link} href={`/versions?batch_review_run_id=${run.id}`}>查看全部待发布草稿</a> : null}
      {exceptions.map((item) => item.manual_review_url ? <a className={css.link} href={manualReviewUrl(item)} key={item.id}>处理 {item.filename}</a> : null)}
    </div>
    {hasReady ? <p>待发布草稿仍需按现有发布门禁逐项发布。</p> : null}
  </section>;
}
