import css from "./BatchReviewPage.module.css";
import { Button, EmptyState, StatusBadge, Table } from "../../design-system";
import type { BatchReviewItem } from "./batchReviewTypes";

const STATUS_LABELS: Record<string, string> = {
  eligible: "等待确认",
  failed: "处理失败",
  manual_review: "需要人工处理",
  materializing: "正在生成草稿",
  parsing: "正在解析",
  queued: "排队中",
  ready_for_publish: "待发布",
  skipped: "已取消选择",
  validating: "正在完整校验",
};

function manualReviewUrl(item: BatchReviewItem) {
  if (!item.manual_review_url || !item.version_id) return item.manual_review_url ?? undefined;
  const separator = item.manual_review_url.includes("?") ? "&" : "?";
  return `${item.manual_review_url}${separator}version_id=${item.version_id}`;
}

export function BatchReviewProgressTable({
  items,
  busyItemId,
  onRetry,
}: {
  items: readonly BatchReviewItem[];
  busyItemId?: number;
  onRetry: (item: BatchReviewItem) => void;
}) {
  if (items.length === 0) return <EmptyState title="此任务没有处理项目" description="刷新状态，或返回版本记录核对任务。" />;
  return <div className={css["batch-review-table-scroll"]}>
    <Table className={css["batch-review-table"] + " " + "batch-review-progress-table"}>
      <caption>批量审核处理进度</caption>
      <thead><tr><th scope="col">文件</th><th scope="col">批次</th><th scope="col">目标</th><th scope="col">状态</th><th scope="col">结果与操作</th></tr></thead>
      <tbody>{items.map((item) => <tr key={item.id}>
        <th scope="row">{item.filename}</th><td data-label="批次">#{item.batch_id}</td>
        <td data-label="目标">{item.report_date ?? "未识别"}<br /><span className={css["batch-review-muted"]}>{item.report_type === "business_report" ? "经营报告" : item.report_type === "return_report" ? "退货报告" : "类型未识别"}</span></td>
        <td data-label="状态"><StatusBadge label={STATUS_LABELS[item.status] ?? item.status} tone={item.status === "ready_for_publish" ? "good" : item.status === "failed" ? "bad" : item.status === "manual_review" ? "warn" : "quiet"} /></td>
        <td data-label="结果与操作" className={css.result}>
          {item.reason_message ? <span className={css["batch-review-reason"]}>{item.reason_message}</span> : null}
          {item.outcome_unknown ? <span className={css["batch-review-reason"]}>正在确认服务器结果，请勿重复提交。</span> : null}
          {item.retry_allowed ? <Button variant="quiet" loading={busyItemId === item.id} disabled={busyItemId === item.id} onClick={() => onRetry(item)} type="button">{busyItemId === item.id ? "正在重试…" : "重试"}</Button> : null}
          {item.status === "manual_review" && item.manual_review_url ? <a className={css["batch-review-inline-link"]} href={manualReviewUrl(item)}>处理异常</a> : null}
        </td>
      </tr>)}</tbody>
    </Table>
  </div>;
}
