import css from "./BatchReviewPage.module.css";
import { Button } from "../../design-system";
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
  return <div className={css["batch-review-table-scroll"]} tabIndex={0}>
    <table className={css["batch-review-table"] + " " + "batch-review-progress-table"}>
      <caption>批量审核处理进度</caption>
      <thead><tr><th scope="col">文件</th><th scope="col">批次</th><th scope="col">目标</th><th scope="col">状态</th><th scope="col">结果与操作</th></tr></thead>
      <tbody>{items.map((item) => <tr key={item.id}>
        <th scope="row">{item.filename}</th><td>#{item.batch_id}</td>
        <td>{item.report_date ?? "未识别"}<br /><span className={css["batch-review-muted"]}>{item.report_type ?? "类型未识别"}</span></td>
        <td><span className={css["batch-review-item-state"] + " " + (css[`batch-review-item-state--${item.status}`] ?? "")}>{STATUS_LABELS[item.status] ?? item.status}</span></td>
        <td>
          {item.reason_message ? <span className={css["batch-review-reason"]}>{item.reason_message}</span> : null}
          {item.outcome_unknown ? <span className={css["batch-review-reason"]}>正在确认服务器结果，请勿重复提交。</span> : null}
          {item.retry_allowed ? <Button variant="quiet" disabled={busyItemId === item.id} onClick={() => onRetry(item)} type="button">{busyItemId === item.id ? "正在重试…" : "重试"}</Button> : null}
          {item.status === "manual_review" && item.manual_review_url ? <a className={css["batch-review-inline-link"]} href={manualReviewUrl(item)}>处理异常</a> : null}
        </td>
      </tr>)}</tbody>
    </table>
  </div>;
}
