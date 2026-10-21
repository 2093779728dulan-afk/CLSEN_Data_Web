import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PresentableColumn } from "../../features/workbench/workbenchTypes";
import { ColumnSettingsPanel } from "./ColumnSettingsPanel";
import { useColumnLayout } from "./useColumnLayout";

const columns: PresentableColumn[] = [
  { column_id: "sku", source_header: "SKU", standard_field_name: "sku", is_key: true, display_order: 1 },
  { column_id: "sessions", source_header: "Sessions", standard_field_name: "sessions", is_key: false, display_order: 2 },
];

function renderPanel(visibleIds = ["sku", "sessions"]) {
  const layout = {
    orderedIds: ["sku", "sessions"], visibleIds, widths: { sku: 144, sessions: 104 },
    resize: vi.fn(), move: vi.fn(), setVisible: vi.fn(), showStatisticalOnly: vi.fn(), restoreSourceOrder: vi.fn(), resetWidths: vi.fn(),
  };
  render(<ColumnSettingsPanel columns={columns} layout={layout} onChange={vi.fn()} onClose={vi.fn()} />);
  return layout;
}

describe("ColumnSettingsPanel", () => {
  it("searches, changes visibility, reorders, and exposes reset commands", () => {
    const layout = renderPanel();
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索列" }), { target: { value: "session" } });
    expect(screen.queryByText("SKU")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Sessions" }));
    expect(layout.setVisible).toHaveBeenCalledWith("sessions", false);

    fireEvent.change(screen.getByRole("searchbox", { name: "搜索列" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "将 Sessions 上移" }));
    expect(layout.move).toHaveBeenCalledWith("sessions", "sku");
    fireEvent.click(screen.getByRole("button", { name: "恢复原始顺序" }));
    fireEvent.click(screen.getByRole("button", { name: "重置列宽" }));
    expect(layout.restoreSourceOrder).toHaveBeenCalledOnce();
    expect(layout.resetWidths).toHaveBeenCalledOnce();
  });

  it("can show a column again after hiding it and drag a column to the end", () => {
    const layout = {
      orderedIds: ["sku", "sessions"], visibleIds: ["sku", "sessions"], widths: { sku: 144, sessions: 104 },
      resize: vi.fn(), move: vi.fn(), setVisible: vi.fn(), showStatisticalOnly: vi.fn(), restoreSourceOrder: vi.fn(), resetWidths: vi.fn(),
    };
    const view = render(<ColumnSettingsPanel columns={columns} layout={layout} onChange={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Sessions" }));
    expect(layout.setVisible).toHaveBeenLastCalledWith("sessions", false);
    view.rerender(<ColumnSettingsPanel columns={columns} layout={{ ...layout, visibleIds: ["sku"] }} onChange={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Sessions" }));
    expect(layout.setVisible).toHaveBeenLastCalledWith("sessions", true);

    fireEvent.dragStart(screen.getByText("SKU").closest("li")!);
    fireEvent.drop(screen.getByRole("region", { name: "将拖动列放到末尾" }));
    expect(layout.move).toHaveBeenCalledWith("sku", null);
  });

  it("disables the last visible identity column", () => {
    renderPanel(["sku"]);
    expect(screen.getByRole("checkbox", { name: "SKU" })).toBeDisabled();
  });

  it("moves a middle column down and then into the final position using real layout state", () => {
    const statefulColumns: PresentableColumn[] = [
      columns[0]!,
      columns[1]!,
      { column_id: "sales", source_header: "Sales", standard_field_name: "sales", is_key: false, display_order: 3 },
      { column_id: "title", source_header: "Title", standard_field_name: "title", is_key: false, display_order: 4 },
    ];
    const Harness = () => {
      const layout = useColumnLayout({
        columns: statefulColumns,
        identity: { namespace: "workbench", reportType: "business_report", siteId: 31, userId: 41 },
        viewportWidth: 1280,
      });
      return <ColumnSettingsPanel columns={statefulColumns} layout={layout} onChange={() => undefined} onClose={() => undefined} />;
    };
    render(<Harness />);
    const renderedOrder = () => screen.getAllByRole("listitem")
      .flatMap((item) => Array.from(item.querySelectorAll("label"), (label) => label.textContent));

    fireEvent.click(screen.getByRole("button", { name: "将 Sessions 下移" }));
    expect(renderedOrder()).toEqual(["SKU", "Sales", "Sessions", "Title"]);

    fireEvent.click(screen.getByRole("button", { name: "将 Sessions 下移" }));
    expect(renderedOrder()).toEqual(["SKU", "Sales", "Title", "Sessions"]);
  });
});
