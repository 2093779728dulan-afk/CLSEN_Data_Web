import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { VersionRows } from "./VersionRows";
import { requestApi } from "../../api/client";
vi.mock("../../api/client", () => ({ requestApi: vi.fn() }));
afterEach(() => vi.resetAllMocks());
it("reads the selected historical version only and renders zero without editing", async () => {
  vi.mocked(requestApi).mockResolvedValue({ version_id: 7, columns: [{ column_id: "sales", source_header: "销售额" }], rows: [{ row_id: 1, row_ordinal: 1, row_state: "active", cells: [{ column_id: "sales", current: "83.980000" }] }, { row_id: 2, row_ordinal: 2, row_state: "active", cells: [{ column_id: "sales", current: 0 }] }], pagination: { page: 1, total_rows: 2, total_pages: 1 } });
  render(<VersionRows versionId={7} versionNo={1} reportDate="2026-07-07" />);
  expect(requestApi).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "查看此版本数据" }));
  expect(await screen.findByText("83.980000")).toBeVisible();
  expect(screen.getByText("0")).toBeVisible();
  expect(requestApi).toHaveBeenCalledWith("/api/versions/7/rows?page=1&page_size=50");
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});
it("rejects data for a different version", async () => {
  vi.mocked(requestApi).mockResolvedValue({ version_id: 15 });
  render(<VersionRows versionId={7} versionNo={1} reportDate="2026-07-07" />);
  await userEvent.click(screen.getByRole("button", { name: "查看此版本数据" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("版本不一致");
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
