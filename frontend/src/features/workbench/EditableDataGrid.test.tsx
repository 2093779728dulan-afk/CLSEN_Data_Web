import css from "./DateWorkbenchPage.module.css";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ColumnLayout } from "../../components/data-table/useColumnLayout";
import type { DataTableSort } from "../../components/data-table/DataTableHeader";
import type { CellEditorState, WorkbenchColumn, WorkbenchPage } from "./workbenchTypes";
import { cellKey } from "./workbenchTypes";
import { EditableDataGrid } from "./EditableDataGrid";

const titleColumn: WorkbenchColumn = { column_id: "title", source_header: "Title", standard_field_name: "title", is_key: false, display_order: 1, editable: false, participates_in_statistics: false, value_kind: "text" };
const skuColumn: WorkbenchColumn = { column_id: "sku", source_header: "SKU", standard_field_name: "sku", is_key: true, display_order: 2, editable: true, participates_in_statistics: true, value_kind: "text" };

function page(): WorkbenchPage {
  return {
    actions: ["edit"],
    columns: [titleColumn, skuColumn],
    head: { data_revision: 0, dataset_id: 1, pointed_at: "2026-08-14T00:00:00Z", review_revision: 0, ruleset_version: "test", status: "draft", version_id: 12, version_no: 1 },
    pagination: { page: 1, page_size: 50, total_pages: 1, total_rows: 1 },
    pending_upload_count: 0,
    permissions: { can_create_revision: false, can_edit: true, can_publish: false, can_undo: false, can_upload: false, can_validate: false },
    report_date: "2026-08-14",
    report_type: "business_report",
    rows: [{
      cells: [
        { base: "Very long product title", cell_revision: 0, changed: false, column_id: "title", current: "Very long product title", editable: false },
        { base: "2401-Black-M", cell_revision: 4, changed: true, column_id: "sku", current: "2401-Black-M", editable: true },
      ],
      row_id: 7,
      row_ordinal: 1,
      row_state: "active",
    }],
    source: "draft",
    tabs: [{ report_type: "business_report", source: "draft" }, { report_type: "return_report", source: "empty" }],
    validation: null,
  };
}

const layout: Pick<ColumnLayout, "visibleColumns" | "widths" | "frozenLeft" | "groups" | "resize"> = {
  visibleColumns: [titleColumn, skuColumn],
  widths: { title: 300, sku: 144 },
  frozenLeft: { sku: 0 },
  groups: [
    { key: "product", label: "商品信息", columnIds: ["title", "sku"], colSpan: 2, alignment: "left" },
  ],
  resize: vi.fn(),
};

function renderGrid(options: { editors?: Record<string, CellEditorState>; sort?: DataTableSort } = {}) {
  const workbench = page();
  const onDiscardCell = vi.fn();
  const onEditCell = vi.fn();
  const onSaveCell = vi.fn();
  const onSort = vi.fn();
  render(<EditableDataGrid editors={options.editors ?? {}} layout={layout} onDiscardCell={onDiscardCell} onEditCell={onEditCell} onSaveCell={onSaveCell} onSort={onSort} page={workbench} sort={options.sort ?? null} />);
  return { onDiscardCell, onEditCell, onSaveCell, onSort, workbench };
}

describe("EditableDataGrid", () => {
  it("keeps a saving cell editable and describes its pending status", () => {
    const key = cellKey(12, 7, "sku");
    renderGrid({ editors: { [key]: { input: "Draft 1", state: "saving" } } });
    const input = screen.getByRole("textbox", { name: "SKU，第 1 行" });
    expect(input).toBeEnabled(); expect(input).not.toHaveAttribute("readonly");
    expect(input).toHaveAttribute("aria-busy", "true");
    expect(input).toHaveAccessibleDescription("正在保存…");
    fireEvent.change(input, { target: { value: "Draft 2" } });
    expect(input).toHaveValue("Draft 2");
  });
  it("renders a labelled table with sticky row identity and contained long read-only text", () => {
    renderGrid();

    expect(screen.getByRole("table", { name: "经营报告原始数据" })).toBeVisible();
    expect(screen.getByRole("rowheader", { name: "1" })).toHaveStyle({ left: "0px" });
    expect(screen.getByText("Very long product title")).toHaveClass(css["workbench-cell-value"]!);
    expect(screen.getByText("Very long product title")).toHaveAttribute("title", "Very long product title");
  });

  it("keeps the existing blur, Enter, and Escape edit-save contract", () => {
    const { onDiscardCell, onEditCell, onSaveCell } = renderGrid();
    const input = screen.getByRole("textbox", { name: "SKU，第 1 行" });

    input.focus();
    fireEvent.change(input, { target: { value: "2402-Black-M" } });
    expect(onEditCell).toHaveBeenLastCalledWith(7, skuColumn, "2402-Black-M");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSaveCell).toHaveBeenCalledWith(7, skuColumn, "2402-Black-M", 4);

    fireEvent.change(input, { target: { value: "discarded" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onDiscardCell).toHaveBeenCalledWith(7, skuColumn);
    expect(onSaveCell).toHaveBeenCalledOnce();
  });

  it("keeps error state above group background and exposes the status message", () => {
    const key = cellKey(12, 7, "sku");
    renderGrid({ editors: { [key]: { input: "2401-Black-M", state: "failed", message: "保存失败" } } });

    expect(screen.getByText("保存失败")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "SKU，第 1 行" }).closest("td")).toHaveClass(css["is-changed"]!, css["has-error"]!);
  });
});
