import type { ImportReviewState } from "./importReviewReducer";
import type { ImportQueueItem, ReviewEncoding } from "./workflowTypes";

export const REVIEW_RECOVERY_SCHEMA_VERSION = 4;
const ROOT_PREFIX = "clsen:review-flow";

export type ReviewRecovery = {
  materializeReason: string;
  noteBatchIds: number[];
  reviewState: ImportReviewState;
};

type RecoveryIdentity = {
  reportDate: string;
  siteId: number;
  userId: number;
};

type RecoveryEnvelope = ReviewRecovery & RecoveryIdentity & {
  schemaVersion: number;
};

const ENCODINGS = new Set<ReviewEncoding>(["utf-8-sig", "utf-8", "windows-1252"]);
const REPORT_TYPES = new Set(["business_report", "return_report"]);
const STATUSES = new Set(["completed", "existing", "failed", "ready"]);

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function integer(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function date(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function validUpload(value: unknown) {
  if (!record(value) || typeof value.fileName !== "string" || !record(value.upload)) return false;
  return integer(value.upload.batch_id) && value.upload.batch_id > 0;
}

function validInspection(value: unknown) {
  if (!record(value)) return false;
  return typeof value.status === "string"
    && (value.report_type === null || value.report_type === undefined || (typeof value.report_type === "string" && REPORT_TYPES.has(value.report_type)))
    && (value.report_date === null || value.report_date === undefined || date(value.report_date))
    && (value.encoding === null || value.encoding === undefined || ENCODINGS.has(value.encoding as ReviewEncoding))
    && typeof value.ruleset_version === "string"
    && Array.isArray(value.issue_codes)
    && value.issue_codes.every((code) => typeof code === "string");
}

function validParsed(value: unknown) {
  if (!record(value)) return false;
  return integer(value.batch_id)
    && value.batch_id > 0
    && integer(value.parse_attempt_id)
    && value.parse_attempt_id > 0
    && integer(value.parse_baseline_id)
    && value.parse_baseline_id > 0
    && integer(value.confirmation_revision)
    && typeof value.report_type === "string"
    && REPORT_TYPES.has(value.report_type)
    && integer(value.source_row_count);
}

function validExisting(value: unknown) {
  if (!record(value) || !integer(value.batchId) || value.batchId < 1) return false;
  return (value.reportDate === undefined || date(value.reportDate))
    && (value.reportType === undefined
      || (typeof value.reportType === "string" && REPORT_TYPES.has(value.reportType)))
    && (value.stage === undefined || typeof value.stage === "string")
    && (value.workspaceUrl === undefined
      || (typeof value.workspaceUrl === "string" && value.workspaceUrl.startsWith("/review/")));
}

function validQueueItem(value: unknown): value is ImportQueueItem {
  if (!record(value)) return false;
  return typeof value.id === "string"
    && value.id.length > 0
    && date(value.assignedDate)
    && ENCODINGS.has(value.encoding as ReviewEncoding)
    && typeof value.reportType === "string"
    && REPORT_TYPES.has(value.reportType)
    && STATUSES.has(String(value.status))
    && (value.error === undefined || typeof value.error === "string")
    && (value.existing === undefined || validExisting(value.existing))
    && (value.upload === undefined || validUpload(value.upload))
    && (value.inspection === undefined || validInspection(value.inspection))
    && (value.parsed === undefined || validParsed(value.parsed));
}

function validState(value: unknown): value is ImportReviewState {
  if (!record(value) || !record(value.intake) || !Array.isArray(value.importQueue)) return false;
  if (!date(value.intake.assignedDate)
    || !ENCODINGS.has(value.intake.encoding as ReviewEncoding)
    || !REPORT_TYPES.has(String(value.intake.reportType))) return false;
  if (!value.importQueue.every(validQueueItem)) return false;
  const ids = value.importQueue.map((item) => item.id);
  if (new Set(ids).size !== ids.length) return false;
  return value.activeQueueId === undefined
    || (typeof value.activeQueueId === "string" && ids.includes(value.activeQueueId));
}

export function reviewRecoveryKey(identity: RecoveryIdentity) {
  return `${ROOT_PREFIX}:v${REVIEW_RECOVERY_SCHEMA_VERSION}:site:${identity.siteId}:user:${identity.userId}:date:${identity.reportDate}`;
}

export function decodeReviewRecovery(raw: string, identity: RecoveryIdentity): ReviewRecovery | undefined {
  try {
    const value: unknown = JSON.parse(raw);
    if (!record(value)
      || value.schemaVersion !== REVIEW_RECOVERY_SCHEMA_VERSION
      || value.siteId !== identity.siteId
      || value.userId !== identity.userId
      || value.reportDate !== identity.reportDate
      || !validState(value.reviewState)
      || typeof value.materializeReason !== "string"
      || !Array.isArray(value.noteBatchIds)
      || !value.noteBatchIds.every((batchId) => integer(batchId) && batchId > 0)
      || new Set(value.noteBatchIds).size !== value.noteBatchIds.length) return undefined;
    const envelope = value as unknown as RecoveryEnvelope;
    return {
      materializeReason: envelope.materializeReason,
      noteBatchIds: envelope.noteBatchIds,
      reviewState: envelope.reviewState,
    };
  } catch {
    return undefined;
  }
}

export function loadReviewRecovery(identity: RecoveryIdentity, storage: Storage = window.sessionStorage) {
  const key = reviewRecoveryKey(identity);
  const raw = storage.getItem(key);
  if (!raw) return undefined;
  const decoded = decodeReviewRecovery(raw, identity);
  if (!decoded) storage.removeItem(key);
  return decoded;
}

export function saveReviewRecovery(identity: RecoveryIdentity, recovery: ReviewRecovery, storage: Storage = window.sessionStorage) {
  const envelope: RecoveryEnvelope = {
    ...identity,
    ...recovery,
    schemaVersion: REVIEW_RECOVERY_SCHEMA_VERSION,
  };
  storage.setItem(reviewRecoveryKey(identity), JSON.stringify(envelope));
}

export function removeReviewRecovery(identity: RecoveryIdentity, storage: Storage = window.sessionStorage) {
  storage.removeItem(reviewRecoveryKey(identity));
}

export function clearReviewRecoveryForIdentity(siteId: number, userId: number, storage: Storage = window.sessionStorage) {
  const prefix = `${ROOT_PREFIX}:v${REVIEW_RECOVERY_SCHEMA_VERSION}:site:${siteId}:user:${userId}:date:`;
  const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index))
    .filter((key): key is string => key !== null && key.startsWith(prefix));
  for (const key of keys) storage.removeItem(key);
}
