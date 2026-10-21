import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  requestApi: vi.fn(),
  writeApi: vi.fn(),
}));

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, requestApi: mocks.requestApi, writeApi: mocks.writeApi };
});

import { BatchReviewApi } from "./batchReviewApi";

describe("BatchReviewApi", () => {
  beforeEach(() => {
    mocks.requestApi.mockReset();
    mocks.writeApi.mockReset();
    mocks.writeApi.mockResolvedValue({ id: 1, items: [] });
  });

  it("deduplicates and sorts server batch IDs for preflight", async () => {
    await new BatchReviewApi().createPreflight([8, 3, 8]);
    expect(mocks.writeApi).toHaveBeenCalledWith(
      "/api/imports/batch-reviews/preflight",
      expect.objectContaining({ body: { batch_ids: [3, 8] } }),
    );
  });

  it("sends revision and versioned confirmation statement", async () => {
    await new BatchReviewApi().confirm(4, 7, [9, 2]);
    expect(mocks.writeApi).toHaveBeenCalledWith(
      "/api/imports/batch-reviews/4/confirm",
      expect.objectContaining({
        body: {
          expected_revision: 7,
          selected_item_ids: [2, 9],
          confirmation_accepted: true,
          confirmation_statement_version: "batch-review-confirmation-v1",
        },
      }),
    );
  });
});
