import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { requestApi } from "../../api/client";
import { CatalogImportHistory } from "./CatalogImportHistory";
vi.mock("../../api/client", () => ({ requestApi: vi.fn() }));
afterEach(() => vi.resetAllMocks());
it("recovers approved and unfinished batches without creating candidates", async () => {
  vi.mocked(requestApi).mockResolvedValue({ items: [{ import_id: 1, status: "approved", source_kind: "online", workflow_revision: 3 }, { import_id: 2, status: "needs_attention", source_kind: "xlsx", workflow_revision: 1 }], has_next: false });
  render(<MemoryRouter><CatalogImportHistory /></MemoryRouter>);
  expect(await screen.findByRole("link", { name: "批次 #1 · 查看批准结果" })).toHaveAttribute("href", "/catalog/imports/1");
  expect(screen.getByRole("link", { name: "批次 #2 · 继续审核" })).toHaveAttribute("href", "/catalog/imports/2");
  expect(requestApi).toHaveBeenCalledWith("/api/catalog/imports?page=1");
});
