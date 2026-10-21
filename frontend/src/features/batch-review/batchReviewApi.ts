import {
  ApiRequestError,
  StableOperationKeyStore,
  requestApi,
  writeApi,
} from "../../api/client";
import type {
  BatchReviewItemResponse,
  BatchReviewRunResponse,
  ConfirmRequest,
  PreflightRequest,
  RevisionRequest,
} from "../../api/generated";
import { CONFIRMATION_STATEMENT_VERSION } from "./batchReviewTypes";

export class BatchReviewApi {
  readonly #keys = new StableOperationKeyStore();

  async createPreflight(batchIds: readonly number[]): Promise<BatchReviewRunResponse> {
    const body: PreflightRequest = { batch_ids: [...new Set(batchIds)].sort((a, b) => a - b) };
    const path = "/api/imports/batch-reviews/preflight";
    return this.#writeRun("preflight", path, body);
  }

  getRun(runId: number): Promise<BatchReviewRunResponse> {
    return requestApi(`/api/imports/batch-reviews/${runId}`);
  }

  async confirm(
    runId: number,
    revision: number,
    selectedItemIds: readonly number[],
  ): Promise<BatchReviewRunResponse> {
    const body: ConfirmRequest = {
      expected_revision: revision,
      selected_item_ids: [...new Set(selectedItemIds)].sort((a, b) => a - b),
      confirmation_accepted: true,
      confirmation_statement_version: CONFIRMATION_STATEMENT_VERSION,
    };
    return this.#writeRun(`confirm:${runId}`, `/api/imports/batch-reviews/${runId}/confirm`, body);
  }

  async advance(runId: number, itemId: number, serverOperationToken?: string | null): Promise<BatchReviewItemResponse> {
    const path = `/api/imports/batch-reviews/${runId}/items/${itemId}/advance`;
    const slot = `advance:${runId}:${itemId}`;
    const operationKey = serverOperationToken ?? this.#keys.forCommand(slot, path, null);
    try {
      const response = await writeApi<BatchReviewItemResponse>(path, { operationKey });
      this.#keys.complete(slot, operationKey);
      return response;
    } catch (error) {
      if (error instanceof ApiRequestError && error.code === "outcome_unknown") {
        const run = await this.getRun(runId);
        const item = run.items.find((candidate) => candidate.id === itemId);
        if (item) return item;
      }
      throw error;
    }
  }

  pause(runId: number, revision: number): Promise<BatchReviewRunResponse> {
    return this.#revisionCommand("pause", runId, revision);
  }

  resume(runId: number, revision: number): Promise<BatchReviewRunResponse> {
    return this.#revisionCommand("resume", runId, revision);
  }

  retry(runId: number, itemId: number, revision: number): Promise<BatchReviewRunResponse> {
    const body: RevisionRequest = { expected_revision: revision };
    return this.#writeRun(
      `retry:${runId}:${itemId}`,
      `/api/imports/batch-reviews/${runId}/items/${itemId}/retry`,
      body,
    );
  }

  #revisionCommand(action: "pause" | "resume", runId: number, revision: number) {
    const body: RevisionRequest = { expected_revision: revision };
    return this.#writeRun(
      `${action}:${runId}:${revision}`,
      `/api/imports/batch-reviews/${runId}/${action}`,
      body,
    );
  }

  async #writeRun(slot: string, path: string, body: unknown): Promise<BatchReviewRunResponse> {
    const operationKey = this.#keys.forCommand(slot, path, body);
    const response = await writeApi<BatchReviewRunResponse>(path, { body, operationKey });
    this.#keys.complete(slot, operationKey);
    return response;
  }
}
