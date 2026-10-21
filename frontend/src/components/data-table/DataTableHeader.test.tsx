import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PresentableColumn } from "../../features/workbench/workbenchTypes";
import { groupVisibleColumns } from "./columnPresentation";
import { DataTableHeader } from "./DataTableHeader";

const columns: PresentableColumn[] = [
  { column_id: "sku", source_header: "SKU", standard_field_name: "sku", is_key: true, display_order: 1 },
  { column_id: "sessions", source_header: "Sessions", standard_field_name: "sessions", is_key: false, display_order: 2 },
  { column_id: "title", source_header: "Title", standard_field_name: "title", is_key: true, display_order: 3 },
];

describe("DataTableHeader", () => {
  it("renders exactly two semantic header rows, including split groups", () => {
    render(<table><DataTableHeader columns={columns} frozenLeft={{ sku: 0 }} groups={groupVisibleColumns("business_report", columns)} onResize={vi.fn()} onSort={vi.fn()} sort={{ columnId: "sku", direction: "asc" }} widths={{ sku: 144, sessions: 104, title: 300 }} /></table>);

    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(screen.getByRole("columnheader", { name: "SKU" })).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getAllByRole("columnheader", { name: "商品信息" })).toHaveLength(2);
    expect(screen.getAllByRole("columnheader", { name: "商品信息" }).every((node) => node.getAttribute("scope") === "colgroup")).toBe(true);
    expect(screen.getByRole("columnheader", { name: "Sessions" })).toHaveAttribute("scope", "col");
  });

  it("keeps ordered leading columns sticky with cumulative offsets", () => {
    render(<table><DataTableHeader
      columns={columns}
      frozenLeft={{ sku: 268 }}
      groups={groupVisibleColumns("business_report", columns)}
      leadingColumns={[
        { label: "报告日期", width: 116 },
        { label: "发布版本", width: 88 },
        { label: "行号", width: 64 },
      ]}
      onResize={vi.fn()}
      onSort={vi.fn()}
      sort={null}
      widths={{ sku: 144, sessions: 104, title: 300 }}
    /></table>);

    expect(screen.getByRole("columnheader", { name: "报告日期" })).toHaveStyle({ left: "0px", width: "116px" });
    expect(screen.getByRole("columnheader", { name: "发布版本" })).toHaveStyle({ left: "116px", width: "88px" });
    expect(screen.getByRole("columnheader", { name: "行号" })).toHaveStyle({ left: "204px", width: "64px" });
    expect(screen.getByRole("columnheader", { name: "SKU" })).toHaveStyle({ left: "268px" });
  });

  it("emits tri-state server sort commands and shows draft pointer width before persisting on release", () => {
    const onSort = vi.fn();
    const onResize = vi.fn();
    const props = { columns, frozenLeft: {}, groups: groupVisibleColumns("business_report", columns), onResize, onSort, widths: { sku: 144, sessions: 104, title: 300 } };
    const view = render(<table><DataTableHeader {...props} sort={{ columnId: "sku", direction: "asc" }} /></table>);

    fireEvent.click(screen.getByRole("button", { name: "按 SKU 排序" }));
    view.rerender(<table><DataTableHeader {...props} sort={{ columnId: "sku", direction: "desc" }} /></table>);
    fireEvent.click(screen.getByRole("button", { name: "按 SKU 排序" }));
    expect(onSort).toHaveBeenNthCalledWith(1, { columnId: "sku", direction: "desc" });
    expect(onSort).toHaveBeenNthCalledWith(2, { columnId: "sku", direction: null });

    const resizer = screen.getByRole("button", { name: "调整“SKU”列宽" });
    fireEvent(resizer, new MouseEvent("pointerdown", { bubbles: true, clientX: 100 }));
    fireEvent(resizer, new MouseEvent("pointermove", { bubbles: true, clientX: 132 }));
    expect(screen.getByRole("columnheader", { name: "SKU" })).toHaveStyle({ width: "176px" });
    expect(onResize).not.toHaveBeenCalled();
    fireEvent(resizer, new MouseEvent("pointerup", { bubbles: true, clientX: 132 }));
    expect(onResize).toHaveBeenCalledOnce();
    expect(onResize).toHaveBeenCalledWith("sku", 176);
    fireEvent(window, new MouseEvent("pointerup", { bubbles: true, clientX: 132 }));
    expect(onResize).toHaveBeenCalledOnce();

    fireEvent.keyDown(resizer, { key: "ArrowLeft" });
    expect(onResize).toHaveBeenLastCalledWith("sku", 136);
  });

  it("does not persist a cancelled or unmounted pointer resize", () => {
    const onResize = vi.fn();
    const props = { columns, frozenLeft: {}, groups: groupVisibleColumns("business_report", columns), onResize, onSort: vi.fn(), sort: null, widths: { sku: 144, sessions: 104, title: 300 } };
    const view = render(<table><DataTableHeader {...props} /></table>);
    const resizer = screen.getByRole("button", { name: "调整“SKU”列宽" });

    fireEvent(resizer, new MouseEvent("pointerdown", { bubbles: true, clientX: 100 }));
    fireEvent(resizer, new MouseEvent("pointermove", { bubbles: true, clientX: 132 }));
    fireEvent(resizer, new MouseEvent("pointercancel", { bubbles: true, clientX: 132 }));
    expect(onResize).not.toHaveBeenCalled();
    expect(screen.getByRole("columnheader", { name: "SKU" })).toHaveStyle({ width: "144px" });

    fireEvent(resizer, new MouseEvent("pointerdown", { bubbles: true, clientX: 100 }));
    view.unmount();
    fireEvent(window, new MouseEvent("pointerup", { bubbles: true, clientX: 132 }));
    expect(onResize).not.toHaveBeenCalled();
  });
});
