import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ createPreflight: vi.fn() }));
vi.mock("./batchReviewApi", () => ({ BatchReviewApi: class { createPreflight = mocks.createPreflight; } }));

import { BatchReviewEntry } from "./BatchReviewEntry";

describe("BatchReviewEntry", () => {
  beforeEach(() => { mocks.createPreflight.mockReset(); });

  it.each([{ batchIds: [] }, { batchIds: [1] }, { batchIds: [1, 1] }])("stays hidden with fewer than two unique server batches", ({ batchIds }) => {
    render(<BatchReviewEntry batchIds={batchIds} onCreated={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "批量审核" })).not.toBeInTheDocument();
  });

  it("deduplicates IDs and hands the created run to navigation", async () => {
    const onCreated = vi.fn(); mocks.createPreflight.mockResolvedValue({ id: 88 });
    const user = userEvent.setup(); render(<BatchReviewEntry batchIds={[12, 11, 12]} onCreated={onCreated} />);
    await user.click(screen.getByRole("button", { name: "批量审核" }));
    expect(mocks.createPreflight).toHaveBeenCalledWith([11, 12]);
    expect(onCreated).toHaveBeenCalledWith(88);
  });

  it("stays hidden when the caller does not grant batch-review navigation", () => {
    render(<BatchReviewEntry batchIds={[11, 12]} />);
    expect(screen.queryByRole("button", { name: "批量审核" })).not.toBeInTheDocument();
  });
});
