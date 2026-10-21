import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import type { StyleCardResponse } from "./productAnalyticsTypes";
import { VariantReviewTable } from "./VariantReviewTable";

const metric = (value: string | number) => ({ value, value_state: "observed", is_partial: false });
const rows = [
  { sku_id: "1", internal_display_sku: "DEMO-Blue-M", standard_color: "Blue", standard_size: "M", seller_sku_aliases: [], metrics: { sales: metric("75.00"), units: metric(3), returns: metric(1), sessions: metric(10), conversion: metric("0.300000") } },
  { sku_id: "2", internal_display_sku: "DEMO-Red-L", standard_color: "Red", standard_size: "L", seller_sku_aliases: [], metrics: { sales: metric("25.00"), units: metric(1), returns: metric(2), sessions: metric(10), conversion: metric("0.100000") } },
];
const response = { variants: rows, summary: { metrics: { sales: metric("100.00") } }, effective_return_basis: "event_date" } as unknown as StyleCardResponse;

it("sorts actual variants and keeps the whole-style denominator when filtering", () => {
  render(<VariantReviewTable response={response} />);
  expect(screen.getAllByRole("row")[1]).toHaveTextContent("DEMO-Blue-M");
  fireEvent.click(screen.getByRole("button", { name: "变体退货关注" }));
  expect(screen.getAllByRole("row")[1]).toHaveTextContent("DEMO-Red-L");
  expect(screen.getAllByRole("row")[1]).toHaveTextContent("200.00%");
  fireEvent.change(screen.getByRole("combobox", { name: "筛选颜色" }), { target: { value: "Blue" } });
  expect(screen.queryByText("DEMO-Red-L")).not.toBeInTheDocument();
  expect(screen.getByText("占比 75.00%")).toBeVisible();
  fireEvent.change(screen.getByRole("combobox", { name: "筛选尺码" }), { target: { value: "L" } });
  expect(screen.getByText(/没有匹配的实际变体/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "清除变体筛选" }));
  expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(3);
  expect(response.variants[0]?.sku_id).toBe("1");
});
