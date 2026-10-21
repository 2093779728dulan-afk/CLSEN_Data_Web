import css from "./BatchReviewPage.module.css";
import type { BatchReviewItem } from "./batchReviewTypes";

function reportTypeLabel(value: string | null) {
  if (value === "business_report") return "经营报告";
  if (value === "return_report") return "退货报告";
  return "未识别";
}

function recognitionLabel(value: string) {
  return value === "recognized" ? "已识别" : "需核对";
}

function targetLabel(item: BatchReviewItem) {
  if (item.reason_code === "active_draft_exists") return "已有活动草稿";
  if (item.reason_code === "publication_exists") return "已有发布版本";
  if (!item.report_date || !item.report_type) return "目标未确定";
  return "目标为空";
}

export function BatchReviewPreflightTable({
  items,
  selectedIds,
  onToggle,
}: {
  items: readonly BatchReviewItem[];
  selectedIds: ReadonlySet<number>;
  onToggle: (itemId: number, selected: boolean) => void;
}) {
  return <div className={css["batch-review-table-scroll"]} tabIndex={0}>
    <table className={css["batch-review-table"]}>
      <caption>批量审核预检清单</caption>
      <thead><tr>
        <th scope="col">选择</th><th scope="col">文件</th><th scope="col">批次</th>
        <th scope="col">报告日期</th><th scope="col">报表类型</th><th scope="col">编码</th>
        <th scope="col">识别</th><th scope="col">目标状态</th><th scope="col">预计动作</th>
      </tr></thead>
      <tbody>{items.map((item) => {
        const eligible = item.status === "eligible";
        return <tr key={item.id}>
          <td><label className={css["batch-review-checkbox"]}><input
            aria-label={`选择 ${item.filename}`}
            checked={eligible && selectedIds.has(item.id)}
            disabled={!eligible}
            onChange={(event) => onToggle(item.id, event.currentTarget.checked)}
            type="checkbox"
          /><span className={"sr-only"}>选择</span></label></td>
          <th scope="row">{item.filename}</th>
          <td>#{item.batch_id}</td><td>{item.report_date ?? "未识别"}</td>
          <td>{reportTypeLabel(item.report_type)}</td><td>{item.encoding ?? "未识别"}</td>
          <td>{recognitionLabel(item.recognition_status)}</td><td>{targetLabel(item)}</td>
          <td>{eligible ? "完整校验后进入待发布" : <span className={css["batch-review-reason"]}>{item.reason_message ?? "需人工处理"}</span>}</td>
        </tr>;
      })}</tbody>
    </table>
  </div>;
}
