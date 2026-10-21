import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { requestApi } from "../../api/client";
import { BatchReviewHistory } from "./BatchReviewHistory";
vi.mock("../../api/client", () => ({ requestApi: vi.fn() }));
afterEach(() => vi.resetAllMocks());
it("links a paused run without issuing workflow commands", async () => {
  vi.mocked(requestApi).mockResolvedValue({ items: [{ id: 7, status: "paused", revision: 2 }], has_next: false });
  render(<BatchReviewHistory />);
  expect(await screen.findByRole("link", { name: "任务 #7 · 已暂停" })).toHaveAttribute("href", "/review/batch/7");
  expect(requestApi).toHaveBeenCalledTimes(1);
  expect(requestApi).toHaveBeenCalledWith("/api/imports/batch-reviews?page=1");
});
