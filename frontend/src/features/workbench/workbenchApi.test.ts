import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "../../api/client";

const mocks = vi.hoisted(() => ({
  requestApi: vi.fn(),
  writeApi: vi.fn(),
}));

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, requestApi: mocks.requestApi, writeApi: mocks.writeApi };
});

import { prepareReturnDedupStaging, uploadWorkbenchImport } from "./workbenchApi";

const input = {
  datasetId: 4,
  operationToken: "5d6ae201-1635-47bf-a342-01108cb6c206",
  proposedVersionId: 8,
  reportDate: "2026-08-27",
};

describe("prepareReturnDedupStaging", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    mocks.requestApi.mockReset();
    mocks.writeApi.mockReset();
  });

  it("skips staging for a legacy source scope with no revision pair", async () => {
    mocks.requestApi.mockResolvedValue([{
      dataset_id: 4,
      dedup_publication_revision: null,
      publication_revision: null,
    }]);

    await expect(prepareReturnDedupStaging(input)).resolves.toBeUndefined();
    expect(mocks.writeApi).not.toHaveBeenCalled();
  });

  it("fails closed when only one legacy revision is missing", async () => {
    mocks.requestApi.mockResolvedValue([{
      dataset_id: 4,
      dedup_publication_revision: null,
      publication_revision: 2,
    }]);

    await expect(prepareReturnDedupStaging(input)).rejects.toThrow("revision 状态不完整");
    expect(mocks.writeApi).not.toHaveBeenCalled();
  });

  it("stops polling after the bounded staging deadline", async () => {
    vi.useFakeTimers();
    mocks.requestApi.mockResolvedValue([{
      dataset_id: 4,
      dedup_publication_revision: 3,
      publication_revision: 2,
    }]);
    mocks.writeApi.mockResolvedValue({
      job_id: 9,
      status: "building",
      status_url: "/api/publications/return-dedup-staging/9",
    });
    const preparing = prepareReturnDedupStaging(input, undefined, { maxWaitMs: 1 });
    const outcome = preparing.catch((reason: unknown) => reason);
    await vi.advanceTimersByTimeAsync(1);
    const error = await outcome;

    expect(error).toBeInstanceOf(ApiRequestError);
    expect((error as ApiRequestError).code).toBe("return_dedup_staging_timeout");
    expect(mocks.requestApi).toHaveBeenCalledTimes(1);
  });
});


it("sends the selected report type with workbench uploads", async () => {
  mocks.writeApi.mockResolvedValue({ status: "confirmation_required" });
  const file = new File(["synthetic"], "sample.csv");
  await uploadWorkbenchImport("2026-08-13", file, "operation", "return_report");
  expect(mocks.writeApi).toHaveBeenCalledWith("/api/workbench/imports?report_date=2026-08-13&expected_report_type=return_report", expect.objectContaining({ rawBody: file, operationKey: "operation" }));
});
