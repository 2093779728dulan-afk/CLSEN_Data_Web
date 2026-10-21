import type {
  BatchReviewItemResponse,
  BatchReviewRunResponse,
  BatchReviewSummaryResponse,
} from "../../api/generated";

export type BatchReviewItem = BatchReviewItemResponse;
export type BatchReviewRun = BatchReviewRunResponse;
export type BatchReviewSummary = BatchReviewSummaryResponse;

export const CONFIRMATION_STATEMENT_VERSION = "batch-review-confirmation-v1";

export function queuedItems(run: BatchReviewRun): BatchReviewItem[] {
  return run.items.filter((item) => item.recovery_available);
}
