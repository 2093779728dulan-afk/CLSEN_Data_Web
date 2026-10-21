import type { BatchReviewItem, BatchReviewRun } from "./batchReviewTypes";

export function sampleItem(changes: Partial<BatchReviewItem> = {}): BatchReviewItem {
  return {
    attempt_count: 0, batch_id: 11, dataset_id: null, encoding: "utf-8-sig", filename: "business-2026-09-12.csv", id: 101,
    manual_review_url: "/review/2026-09-12?report_type=business_report", operation_token: null, outcome_unknown: false,
    reason_code: null, reason_message: null, recognition_status: "recognized", recovery_available: false,
    report_date: "2026-09-12", report_type: "business_report", retry_allowed: false, selected: true, status: "eligible",
    validation_run_id: null, version_id: null, ...changes,
  };
}

export function sampleRun(status = "preview"): BatchReviewRun {
  const items = [sampleItem(), sampleItem({ batch_id: 12, id: 102, filename: "returns-2026-09-13.csv", report_date: "2026-09-13", report_type: "return_report", manual_review_url: "/review/2026-09-13?report_type=return_report" }),
    sampleItem({ batch_id: 13, id: 103, filename: "duplicate-2026-09-12.csv", selected: false, status: "manual_review", reason_code: "duplicate_target_in_run", reason_message: "本任务已有文件指向同一日期和报表类型，请逐项核对。" })];
  if (status !== "preview") {
    items[0] = sampleItem({ status: "ready_for_publish", dataset_id: 41, version_id: 53 });
    items[1] = { ...items[1]!, status: status === "running" || status === "paused" ? "queued" : "failed", attempt_count: 1,
      operation_token: "8b90d72f-69f8-42a7-b122-d691e9ad9001", recovery_available: status === "running", retry_allowed: status === "completed_with_exceptions",
      reason_message: status === "completed_with_exceptions" ? "示例：上次处理失败，可按任务状态重试。" : null };
  }
  if (status === "completed") {
    items.splice(2);
    for (const item of items) { item.status = "ready_for_publish"; item.version_id = item.id + 100; item.dataset_id = item.id + 200; item.reason_message = null; item.retry_allowed = false; }
  }
  return recompute({ id: 81, revision: 4, status, allowed_actions: status === "preview" ? ["confirm"] : status === "paused" ? ["resume"] : status === "running" ? ["pause"] : [], items,
    summary: { active: 0, eligible: 0, failed: 0, manual_review: 0, ready_for_publish: 0, skipped: 0, total: 0 } });
}

export function recompute(run: BatchReviewRun): BatchReviewRun {
  return { ...run, summary: { total: run.items.length, eligible: run.items.filter(i => i.status === "eligible").length,
    active: run.items.filter(i => ["queued", "parsing", "materializing", "validating"].includes(i.status)).length,
    failed: run.items.filter(i => i.status === "failed").length, manual_review: run.items.filter(i => i.status === "manual_review").length,
    ready_for_publish: run.items.filter(i => i.status === "ready_for_publish").length, skipped: run.items.filter(i => i.status === "skipped").length } };
}
