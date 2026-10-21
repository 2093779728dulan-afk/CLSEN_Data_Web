import css from "./BatchReviewPage.module.css";
import type { BatchReviewItem } from "./batchReviewTypes";
import { Checkbox, EmptyState, Table } from "../../design-system";

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
  if (item.reason_code === "already_materialized") return "已生成数据版本";
  if (item.reason_code === "duplicate_target_in_run") return "任务内目标重复";
  if (!item.report_date || !item.report_type) return "目标未确定";
  return item.status === "eligible" ? "目标为空" : "目标待核实";
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
  if (items.length === 0) return <EmptyState title="此任务没有文件可审核" description="返回上传队列，核对原文件后再建立预检。" />;
  return <div className={css["batch-review-table-scroll"]}>
    <Table className={css["batch-review-table"]}>
      <caption>批量审核预检清单</caption>
      <thead><tr>
        <th scope="col">选择</th><th scope="col">文件</th><th scope="col">批次</th>
        <th scope="col">报告日期</th><th scope="col">报表类型</th><th scope="col">编码</th>
        <th scope="col">识别</th><th scope="col">目标状态</th><th scope="col">预计动作</th>
      </tr></thead>
      <tbody>{items.map((item) => {
        const eligible = item.status === "eligible";
        return <tr key={item.id}>
          <td data-label="选择"><Checkbox label={<span className={css["selection-label"]}>{`选择 ${item.filename}`}</span>}
            checked={eligible && selectedIds.has(item.id)}
            disabled={!eligible}
            onChange={(event) => onToggle(item.id, event.currentTarget.checked)}
          /></td>
          <th scope="row">{item.filename}</th>
          <td data-label="批次">#{item.batch_id}</td><td data-label="报告日期">{item.report_date ?? "未识别"}</td>
          <td data-label="报表类型">{reportTypeLabel(item.report_type)}</td><td data-label="编码">{item.encoding ?? "未识别"}</td>
          <td data-label="识别">{recognitionLabel(item.recognition_status)}</td><td data-label="目标状态">{targetLabel(item)}</td>
          <td data-label="预计动作" className={css.result}>{eligible ? "完整校验后进入待发布" : <span className={css["batch-review-reason"]}>{item.reason_message ?? "需人工处理"}</span>}</td>
        </tr>;
      })}</tbody>
    </Table>
  </div>;
}
