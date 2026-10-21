import type {
  DraftHead,
  InspectionResponse,
  PublicationPointer,
  ReportType,
  SuccessfulParse,
  UploadResponse,
} from "../../api/types";
import type { PublishedMoveContextResponse } from "../../api/generated";

export type PublishedMoveReviewContext = PublishedMoveContextResponse;

export type DraftReviewContext = {
  head: DraftHead;
  publicationMode: "ordinary" | "published_move";
  publishedMove: PublishedMoveReviewContext | null;
  reportDate: string;
  reportType: ReportType;
  rulesetVersion: string;
  sourceRowCount?: number;
  sourceBatchId?: number;
  publication?: PublicationPointer;
};

export type ReviewLocationHandoff = {
  reportDate: string;
  reportType: ReportType;
  versionId?: number;
};

export type ReviewEncoding = "utf-8-sig" | "utf-8" | "windows-1252";

export type UploadSession = {
  fileName: string;
  upload: UploadResponse | { batch_id: number };
};

export type ExistingImportBatch = {
  batchId: number;
  reportDate?: string;
  reportType?: ReportType;
  stage?: string;
  workspaceUrl?: string;
};

export type ImportQueueItem = {
  assignedDate: string;
  encoding: ReviewEncoding;
  error?: string;
  existing?: ExistingImportBatch;
  id: string;
  inspection?: InspectionResponse;
  parsed?: SuccessfulParse;
  reportType: ReportType;
  status: "completed" | "existing" | "failed" | "ready";
  upload?: UploadSession;
};
