import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { requestApi } from "../../api/client";
import type { DailyLedgerResponse } from "../../api/generated";
import { PublishedDayPage } from "./PublishedDayPage";
vi.mock("../../api/client", () => ({ requestApi: vi.fn() }));
const api = vi.mocked(requestApi);
const empty: DailyLedgerResponse = { publications: [], site_config_versions: [], range: { from_date: "2026-08-10", to_date: "2026-08-10" }, rows: [] };
function result(date: string, sales: string): DailyLedgerResponse {
  return { ...empty, rows: [{ report_date: date, sales, units_ordered: 6, sessions: 60, conversion_rate: "0.1", return_quantity: null, overall_status: "partial", business_status: "published", return_status: "missing", counts_as_incomplete: true, pending_summary: "退货报告缺失", reasons: [] }] };
}
function open(date = "2026-08-10") {
  return render(<MemoryRouter initialEntries={[`/published-details/${date}`]}><Link to="/published-details/2026-08-11">下一日期</Link><Routes><Route path="/published-details/:reportDate" element={<PublishedDayPage currencyCode="USD" />} /></Routes></MemoryRouter>);
}
afterEach(() => vi.resetAllMocks());
it("renders empty results instead of an endless loading state", async () => {
  api.mockResolvedValue(empty); open();
  expect(await screen.findByText("这个日期没有发布数据")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
});
it("retries failures and links to the exact day of original details", async () => {
  api.mockRejectedValueOnce(new Error("网络不可用")).mockResolvedValueOnce(result("2026-08-10", "120.25")); open();
  expect(await screen.findByRole("alert")).toHaveTextContent("网络不可用");
  expect(api.mock.calls[0]?.[0]).toBe("/api/dashboard/daily-ledger?from=2026-08-01&to=2026-08-10");
  await userEvent.click(screen.getByRole("button", { name: "重新读取" }));
  expect(await screen.findByText("10.00%")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "查看当日原始明细" })).toHaveAttribute("href", "/ledger/published-details?from=2026-08-10&to=2026-08-10&mode=rows");
});
it("cancels the previous date and ignores its late response", async () => {
  let resolveOld!: (value: DailyLedgerResponse) => void;
  api.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; })).mockResolvedValueOnce(result("2026-08-11", "222.22")); open();
  await userEvent.click(screen.getByRole("link", { name: "下一日期" }));
  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  expect(api.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
  await act(async () => { resolveOld(result("2026-08-10", "999.99")); await Promise.resolve(); });
  expect(screen.getByRole("heading", { name: "2026-08-11" })).toBeInTheDocument();
  expect(screen.queryByText(/999\.99/)).not.toBeInTheDocument();
});
it("rejects impossible calendar dates before requesting data", async () => {
  open("2026-02-31");
  expect(await screen.findByRole("alert")).toHaveTextContent("报告日期格式无效");
  expect(api).not.toHaveBeenCalled();
});

it.each([
  [null, "missing", "报告未发布"],
  [null, "published", "暂无数据"],
  [0, "published", "0"],
] as const)("distinguishes return quantity %s and publication %s", async (quantity, status, label) => {
  const payload = result("2026-08-10", "120.25");
  payload.rows[0]!.return_quantity = quantity;
  payload.rows[0]!.return_status = status;
  api.mockResolvedValue(payload); open();
  await screen.findByRole("heading", { name: "当前发布数据" });
  expect(within(screen.getByRole("region", { name: "当前发布指标" })).getByText("退货数").nextElementSibling).toHaveTextContent(label);
});
