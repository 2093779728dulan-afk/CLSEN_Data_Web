import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { DailyLedgerRow } from "../../api/generated";
import { PublishedMonthTrend } from "./PublishedMonthTrend";

const rows: DailyLedgerRow[] = [1, 3].map((day) => ({ report_date: `2025-07-0${day}`, business_status: "published", return_status: "missing", overall_status: "partial", sales: "10.00", units_ordered: 2, sessions: 10, conversion_rate: "0.2", return_quantity: null, counts_as_incomplete: true, reasons: [], pending_summary: null }));

it("renders a gap without a connecting segment and exposes exact dates in the data table", async () => {
  render(<PublishedMonthTrend currencyCode="USD" reportDate="2025-07-03" rows={rows} />);
  const chart = screen.getByRole("img", { name: /销售额月内每日趋势/ });
  expect(chart.querySelectorAll("polyline")).toHaveLength(0);
  expect(screen.getByText("前一日暂无可比数据")).toBeInTheDocument();
  await userEvent.click(screen.getByText("查看逐日数据 · 销售额"));
  const table = screen.getByRole("table");
  expect(within(table).getByRole("row", { name: /2025-07-02/ })).toHaveTextContent("暂无可用数据");
  expect(within(table).getByRole("row", { name: /2025-07-03/ })).toHaveTextContent("US$10.00");
});

it("switches metric via the shared control and leaves missing returns unplotted", async () => {
  render(<PublishedMonthTrend currencyCode="USD" reportDate="2025-07-03" rows={rows} />);
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "趋势指标" }), "return_quantity");
  expect(screen.getByText("这个范围暂无可绘制的数据")).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.getByText("当日暂无可比数据")).toBeInTheDocument();
});
