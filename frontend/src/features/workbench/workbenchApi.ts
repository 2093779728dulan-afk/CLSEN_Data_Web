import { ApiRequestError, createOperationKey, requestApi, writeApi } from "../../api/client";
import type { ReportType } from "../../api/types";
import type {
  ConfirmWorkbenchImportRequest,
  ReturnDedupStagingRequest,
  ReturnDedupStagingResponse,
  VersionSummaryResponse,
  WorkbenchCellMutationResponse,
  WorkbenchChangePageResponse,
  WorkbenchImportResponse,
  WorkbenchRevisionResponse,
} from "../../api/generated";
import type { WorkbenchCellWrite, WorkbenchPage } from "./workbenchTypes";

type VersionWithReturnDedupRevisions = VersionSummaryResponse & {
  dedup_publication_revision: number | null;
  publication_revision: number | null;
};

export type ReturnDedupStagingInput = {
  datasetId: number;
  operationToken: string;
  proposedVersionId: number;
  reportDate: string;
};

export class ReturnDedupStagingSupersededError extends Error {
  constructor() {
    super("退货发布集合在准备期间已变化，请按最新状态重新准备。");
    this.name = "ReturnDedupStagingSupersededError";
  }
}

function abortError(signal?: AbortSignal) {
  return signal?.reason instanceof Error
    ? signal.reason
    : new DOMException("The operation was aborted.", "AbortError");
}

function waitForPoll(signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError(signal));
      return;
    }
    const onAbort = () => {
      globalThis.clearTimeout(timer);
      reject(abortError(signal));
    };
    const timer = globalThis.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, 500);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

async function loadReturnDedupRevisions(reportDate: string, datasetId: number, signal?: AbortSignal) {
  const versions = await requestApi<VersionWithReturnDedupRevisions[]>(
    `/api/versions?report_date=${encodeURIComponent(reportDate)}&report_type=return_report`,
    { signal },
  );
  const version = versions.find((item) => item.dataset_id === datasetId);
  if (!version) {
    throw new Error("无法读取退货发布 revision；当前操作未发送。");
  }
  if (version.publication_revision == null && version.dedup_publication_revision == null) {
    return undefined;
  }
  if (!Number.isSafeInteger(version.publication_revision) || !Number.isSafeInteger(version.dedup_publication_revision)) {
    throw new Error("退货发布 revision 状态不完整；当前操作未发送。");
  }
  return {
    dedupPublicationRevision: version.dedup_publication_revision as number,
    publicationRevision: version.publication_revision as number,
  };
}

function stagingFailure(job: ReturnDedupStagingResponse) {
  const reason = job.failure_reason ? `（${job.failure_reason}）` : "";
  return new ApiRequestError(
    409,
    "return_dedup_staging_failed",
    `退货去重准备失败${reason}，发布指针保持不变。`,
  );
}

export async function prepareReturnDedupStaging(
  input: ReturnDedupStagingInput,
  onStatus?: (status: ReturnDedupStagingResponse["status"]) => void,
  options: { maxWaitMs?: number; signal?: AbortSignal } = {},
) {
  const maxWaitMs = options.maxWaitMs ?? 120_000;
  if (!Number.isFinite(maxWaitMs) || maxWaitMs <= 0) {
    throw new Error("退货去重准备最大等待时间必须大于零。");
  }
  const controller = new AbortController();
  const onAbort = () => controller.abort(abortError(options.signal));
  if (options.signal?.aborted) onAbort();
  else options.signal?.addEventListener("abort", onAbort, { once: true });
  const timeout = globalThis.setTimeout(() => controller.abort(stagingTimeout()), maxWaitMs);
  try {
    const revisions = await loadReturnDedupRevisions(input.reportDate, input.datasetId, controller.signal);
    if (!revisions) return undefined;
    const body = {
      dataset_id: input.datasetId,
      expected_dedup_publication_revision: revisions.dedupPublicationRevision,
      expected_publication_revision: revisions.publicationRevision,
      operation_token: input.operationToken,
      proposed_version_id: input.proposedVersionId,
    } satisfies ReturnDedupStagingRequest;
    let job = await writeApi<ReturnDedupStagingResponse>(
      "/api/publications/return-dedup-staging",
      { body, operationKey: input.operationToken, signal: controller.signal },
    );
    let retried = false;
    for (;;) {
      onStatus?.(job.status);
      if (job.status === "ready") return job;
      if (job.status === "superseded") {
        throw new ReturnDedupStagingSupersededError();
      }
      if (job.status === "failed") {
        if (!job.retry_allowed || retried) throw stagingFailure(job);
        const retryToken = createOperationKey();
        job = await writeApi<ReturnDedupStagingResponse>(
          `/api/publications/return-dedup-staging/${job.job_id}/retry`,
          {
            body: {
              expected_job_revision: job.next_job_revision,
              operation_token: retryToken,
              proposed_set_digest: job.proposed_set_digest,
            },
            operationKey: retryToken,
            signal: controller.signal,
          },
        );
        retried = true;
        continue;
      }
      await waitForPoll(controller.signal);
      job = await requestApi<ReturnDedupStagingResponse>(job.status_url, { signal: controller.signal });
    }
  } finally {
    globalThis.clearTimeout(timeout);
    options.signal?.removeEventListener("abort", onAbort);
  }
}

function stagingTimeout() {
  return new ApiRequestError(
    504,
    "return_dedup_staging_timeout",
    "退货去重准备等待超时，发布指针保持不变；可稍后使用同一操作重试。",
  );
}

export function loadWorkbench(
  reportDate: string,
  reportType: string,
  query: URLSearchParams,
  signal?: AbortSignal,
) {
  const parameters = new URLSearchParams(query);
  parameters.set("report_type", reportType);
  return requestApi<WorkbenchPage>(`/api/workbench/dates/${reportDate}?${parameters}`, { signal });
}

export function writeWorkbenchCell(
  versionId: number,
  rowId: number,
  columnId: string,
  body: WorkbenchCellWrite,
  operationKey: string,
) {
  return writeApi<WorkbenchCellMutationResponse>(
    `/api/workbench/versions/${versionId}/rows/${rowId}/cells/${columnId}`,
    { body, method: "PATCH", operationKey },
  );
}

export function undoWorkbench(versionId: number, body: object, operationKey: string) {
  return writeApi<WorkbenchCellMutationResponse>(
    `/api/workbench/versions/${versionId}/undo`,
    { body, operationKey },
  );
}

export function createWorkbenchRevision(
  reportDate: string,
  reportType: string,
  publishedVersionId: number,
  operationKey: string,
) {
  return writeApi<WorkbenchRevisionResponse>(
    `/api/workbench/dates/${reportDate}/${reportType}/revision`,
    {
      body: {
        published_version_id: publishedVersionId,
        reason: "从日期工作台修改当前发布版本",
      },
      operationKey,
    },
  );
}

export function loadWorkbenchChanges(versionId: number) {
  return requestApi<WorkbenchChangePageResponse>(
    `/api/workbench/versions/${versionId}/changes?page=1&page_size=50`,
  );
}

export function uploadWorkbenchImport(
  reportDate: string,
  file: File,
  operationKey: string,
  expectedReportType: ReportType,
) {
  const parameters = new URLSearchParams({ report_date: reportDate, expected_report_type: expectedReportType });
  return writeApi<WorkbenchImportResponse>(`/api/workbench/imports?${parameters}`, {
    headers: {
      "Content-Type": file.type || "text/csv",
      "X-Original-Filename": encodeURIComponent(file.name),
    },
    operationKey,
    rawBody: file,
  });
}

export function confirmWorkbenchImport(
  batchId: number,
  body: ConfirmWorkbenchImportRequest,
  operationKey: string,
) {
  return writeApi<WorkbenchImportResponse>(
    `/api/workbench/imports/${batchId}/confirm`,
    { body, operationKey },
  );
}
