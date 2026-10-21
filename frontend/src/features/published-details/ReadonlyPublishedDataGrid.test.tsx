import { MemoryRouter } from "react-router-dom";
import { render as renderUi, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PublishedRowsResponse } from "./publishedDetailsTypes";
import { ReadonlyPublishedDataGrid } from "./ReadonlyPublishedDataGrid";

const render = (ui: React.ReactNode) => renderUi(ui, { wrapper: MemoryRouter });

const skuColumnId = "8e4555a0-5397-4b36-b165-0af347ba05b9";
const unitsColumnId = "c441f9f4-796d-49f0-a0be-2627f7047562";

const response: PublishedRowsResponse = {
  columns: [
    {
      column_id: skuColumnId,
      display_order: 0,
      is_key: true,
      participates_in_statistics: false,
      source_header: "Seller SKU",
      standard_field_name: "seller_sku",
      value_kind: "text",
    },
    {
      column_id: unitsColumnId,
      display_order: 1,
      is_key: false,
      participates_in_statistics: true,
      source_header: "Units Ordered",
      standard_field_name: "units_ordered",
      value_kind: "integer",
    },
  ],
  pagination: { page: 2, page_size: 25, total_items: 76, total_pages: 4 },
  permissions: { can_export: true },
  publications: [],
  range: { from_date: "2026-08-01", to_date: "2026-08-14" },
  rows: [{
    cells: [
      { column_id: skuColumnId, value: "2401-WHITE-S" },
      { column_id: unitsColumnId, value: null },
    ],
    published_at: "2026-08-14T08:30:00Z",
    report_date: "2026-08-14",
    row_ordinal: 7,
    version_id: 31,
    version_no: 4,
  }],
  scope_token: "scope-one",
};

function renderGrid(overrides: Partial<React.ComponentProps<typeof ReadonlyPublishedDataGrid>> = {}) {
  const onPageChange = vi.fn();
  const onSort = vi.fn();
  render(<ReadonlyPublishedDataGrid
    exportQuery={{
      direction: "desc",
      from: "2026-08-01",
      reportType: "business_report",
      search: "2401",
      sortColumnId: unitsColumnId,
      to: "2026-08-14",
    }}
    loading={false}
    onPageChange={onPageChange}
    onRetry={vi.fn()}
    onSort={onSort}
    response={response}
    siteId={9}
    sort={{ columnId: unitsColumnId, direction: "desc" }}
    userId={7}
    {...overrides}
  />);
  return { onPageChange, onSort };
}

describe("ReadonlyPublishedDataGrid", () => {
  beforeEach(() => window.localStorage.clear());

  it("renders two header layers with three mandatory system columns and read-only cells", () => {
    renderGrid();

    const table = screen.getByRole("table", { name: "经营报告已发布原始明细" });
    const headers = within(table).getAllByRole("columnheader");
    expect(headers.map((header) => header.textContent)).toEqual(expect.arrayContaining([
      "报告日期", "发布版本", "行号", "商品信息", "其他", "Seller SKU", "Units Ordered统计",
    ]));
    expect(within(table).getByRole("button", { name: "按 Seller SKU 排序" }).closest("th")).toHaveAttribute("aria-sort", "none");
    expect(within(table).getByRole("button", { name: "按 Units Ordered 排序" }).closest("th")).toHaveAttribute("aria-sort", "descending");
    expect(headers.findIndex((header) => header.textContent === "报告日期")).toBeLessThan(headers.findIndex((header) => header.textContent === "发布版本"));
    expect(headers.findIndex((header) => header.textContent === "发布版本")).toBeLessThan(headers.findIndex((header) => header.textContent === "行号"));
    expect(screen.getByText("2026-08-14")).toBeVisible();
    expect(screen.getByText("v4")).toBeVisible();
    expect(screen.getByText("2401-WHITE-S")).toBeVisible();
    expect(screen.getByText("—")).toBeVisible();
    expect(within(table).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(table).queryByText("保存")).not.toBeInTheDocument();
    expect(within(table).queryByText("上传")).not.toBeInTheDocument();
    expect(within(table).queryByText("发布")).not.toBeInTheDocument();
  });

  it("emits server sort and pagination commands and exposes a real CSV download", async () => {
    const user = userEvent.setup();
    const { onPageChange, onSort } = renderGrid();

    await user.click(screen.getByRole("button", { name: "按 Units Ordered 排序" }));
    expect(onSort).toHaveBeenCalledWith({ columnId: unitsColumnId, direction: null });
    await user.click(screen.getByRole("button", { name: "上一页" }));
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(onPageChange).toHaveBeenNthCalledWith(1, 1);
    expect(onPageChange).toHaveBeenNthCalledWith(2, 3);

    const download = screen.getByRole("link", { name: "导出 CSV" });
    expect(download).toHaveAttribute("download");
    expect(download).toHaveAttribute("href", `/api/published-details/export.csv?report_type=business_report&from=2026-08-01&to=2026-08-14&scope_token=scope-one&column_id=${skuColumnId}&column_id=${unitsColumnId}&search=2401&sort_column_id=${unitsColumnId}&direction=desc`);
  });

  it("persists raw-column visibility in the published-details namespace", async () => {
    const user = userEvent.setup();
    renderGrid();

    await user.click(screen.getByRole("button", { name: "列设置" }));
    await user.click(screen.getByRole("checkbox", { name: "Units Ordered" }));

    expect(screen.queryByRole("columnheader", { name: "Units Ordered" })).not.toBeInTheDocument();
    expect(window.localStorage.getItem("clsen:data-table:v1:published-details:user:7:site:9:report:business_report")).toContain(unitsColumnId);
    const download = screen.getByRole("link", { name: "导出 CSV" });
    const href = download.getAttribute("href");
    expect(href).not.toBeNull();
    const parameters = new URL(href!, "http://localhost").searchParams;
    expect(parameters.getAll("column_id")).toEqual([skuColumnId]);
  });

  it("keeps export disabled with an explicit reason until token and schema are ready", () => {
    renderGrid({ response: undefined });

    expect(screen.queryByRole("link", { name: "导出 CSV" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导出 CSV" })).toBeDisabled();
    expect(screen.getByText("需先读取列结构和发布快照。" )).toBeVisible();
  });
});
