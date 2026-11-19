import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ReportProductMatch } from "./ReportProductMatch";
const api = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock("../../api/client", () => ({ requestApi: api.read }));
vi.mock("../../app/AuthzGenerationContext", () => ({ useAuthzGeneration: () => ({ generation: 1 }) }));
afterEach(() => { cleanup(); api.read.mockReset(); });
it("shows the compact matched count without requiring another confirmation", async () => {
  api.read.mockResolvedValue({ matched: 18, excluded: 0, total: 18, issues: [] });
  render(<MemoryRouter><ReportProductMatch versionId={2} revision={1}/></MemoryRouter>);
  expect(await screen.findByText("已匹配18个商品")).toBeVisible();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("opens only exceptions and refreshes after their repair", async () => {
  api.read.mockResolvedValueOnce({ matched: 16, excluded: 0, total: 18, issues: [{ seller_sku: "New-Blue-L", message: "尚未关联本店商品" }] }).mockResolvedValue({ matched: 18, excluded: 0, total: 18, issues: [] });
  render(<MemoryRouter><ReportProductMatch versionId={2} revision={1}/></MemoryRouter>);
  await screen.findByText(/16个商品/);
  await userEvent.click(screen.getByText("查看需处理商品"));
  expect(screen.getByRole("table")).toHaveTextContent("New-Blue-L");
  await userEvent.click(screen.getByRole("button", { name: "刷新匹配结果" }));
  expect(await screen.findByText("已匹配18个商品")).toBeVisible();
});
