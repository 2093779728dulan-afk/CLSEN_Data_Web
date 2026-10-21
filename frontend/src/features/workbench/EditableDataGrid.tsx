import css from "./DateWorkbenchPage.module.css";
import cellCss from "./WorkbenchCell.module.css";
import { useEffect, useId, useState, type CSSProperties } from "react";
import { Check, CircleAlert, LoaderCircle, Pencil, TriangleAlert } from "lucide-react";
import { Input } from "../../design-system";

import { DataTableHeader, type DataTableSort, type SortCommand } from "../../components/data-table/DataTableHeader";
import { ROW_NUMBER_WIDTH } from "../../components/data-table/columnPresentation";
import type { ColumnLayout } from "../../components/data-table/useColumnLayout";
import "../../components/data-table/dataTable.css";
import { cellKey, type CellEditorState, type WorkbenchColumn, type WorkbenchPage } from "./workbenchTypes";
import { rowGroupBoundaries } from "./workbenchGrouping";

type GridLayout = Pick<ColumnLayout, "visibleColumns" | "widths" | "frozenLeft" | "groups" | "resize">;

type Props = {
  page: WorkbenchPage;
  editors: Readonly<Record<string, CellEditorState>>;
  layout: GridLayout;
  sort: DataTableSort;
  onDiscardCell: (rowId: number, column: WorkbenchColumn) => void;
  onEditCell: (rowId: number, column: WorkbenchColumn, input: string) => void;
  onSaveCell: (rowId: number, column: WorkbenchColumn, input: string, revision: number) => void;
  onSort: (command: SortCommand) => void;
};

function reportLabel(reportType: WorkbenchPage["report_type"]) {
  return reportType === "business_report" ? "经营报告" : "退货报告";
}

function statusText(editor: CellEditorState | undefined) {
  if (!editor) return undefined;
  if (editor.message) return editor.message;
  if (editor.state === "saving") return "正在保存…";
  if (editor.state === "saved") return "已保存";
  if (editor.state === "editing") return "待保存";
  if (editor.state === "failed" || editor.state === "conflict") return "保存失败，请重试。";
  return undefined;
}

type EditableCellInputProps = {
  authoritativeValue: string;
  column: WorkbenchColumn;
  editor: CellEditorState | undefined;
  revision: number;
  rowId: number;
  rowOrdinal: number;
  onDiscardCell: Props["onDiscardCell"];
  onEditCell: Props["onEditCell"];
  onSaveCell: Props["onSaveCell"];
};

function EditableCellInput({ authoritativeValue, column, editor, revision, rowId, rowOrdinal, onDiscardCell, onEditCell, onSaveCell }: EditableCellInputProps) {
  const [input, setInput] = useState(editor?.input ?? authoritativeValue);
  const descriptionId = useId();
  const failed = editor?.state === "failed" || editor?.state === "conflict";
  const status = statusText(editor);
  const Icon = editor?.state === "saving" ? LoaderCircle : editor?.state === "saved" ? Check : editor?.state === "conflict" ? TriangleAlert : failed ? CircleAlert : Pencil;

  useEffect(() => {
    setInput(editor?.input ?? authoritativeValue);
  }, [authoritativeValue, editor?.input, revision]);

  return <div className={cellCss.editor} data-save-state={editor?.state ?? "clean"}>
    <Input
    aria-describedby={descriptionId}
    aria-invalid={failed || undefined}
    aria-busy={editor?.state === "saving" || undefined}
    className={cellCss.control}
    aria-label={`${column.source_header}，第 ${rowOrdinal} 行`}
    onBlur={(event) => { if (event.currentTarget.value !== authoritativeValue) onSaveCell(rowId, column, event.currentTarget.value, revision); }}
    onChange={(event) => {
      setInput(event.currentTarget.value);
      onEditCell(rowId, column, event.currentTarget.value);
    }}
    onKeyDown={(event) => {
      if (event.key === "Enter") event.currentTarget.blur();
      if (event.key === "Escape") {
        onDiscardCell(rowId, column);
        setInput(authoritativeValue);
        event.currentTarget.value = authoritativeValue;
        event.currentTarget.blur();
      }
    }}
    title={authoritativeValue}
    value={input}
  />
    <div className={[cellCss.feedback, failed && cellCss.error, editor?.state === "saved" && cellCss.saved, !status && cellCss.hint].filter(Boolean).join(" ")} id={descriptionId} role={failed ? "alert" : status ? "status" : undefined}>
      {status && <Icon aria-hidden="true" className={editor?.state === "saving" ? cellCss.spin : undefined} />}
      <div>{editor?.state === "conflict" && <strong>版本冲突</strong>}{editor?.state === "failed" && <strong>未保存</strong>}<span>{status ?? "Enter 保存 · Esc 放弃"}</span>{failed && <small>输入已保留，核对后重新提交；Esc 放弃输入。</small>}</div>
    </div>
  </div>;
}

export function EditableDataGrid({ page, editors, layout, sort, onDiscardCell, onEditCell, onSaveCell, onSort }: Props) {
  const visibleColumns = layout.visibleColumns.flatMap((visibleColumn) => {
    const serverColumn = page.columns.find((column) => column.column_id === visibleColumn.column_id);
    return serverColumn ? [serverColumn] : [];
  });
  const boundaries = rowGroupBoundaries(page.report_type, page.rows, visibleColumns);
  const headerFrozenLeft = Object.fromEntries(Object.entries(layout.frozenLeft).map(([columnId, left]) => [columnId, left + ROW_NUMBER_WIDTH]));
  let groupIndex = -1;

  return <table aria-label={`${reportLabel(page.report_type)}原始数据`} className={css["workbench-grid"]} style={{ width: `max(100%, ${ROW_NUMBER_WIDTH + visibleColumns.reduce((total, column) => total + (layout.widths[column.column_id] ?? 168), 0)}px)` }}>
    <DataTableHeader
      columns={visibleColumns}
      frozenLeft={headerFrozenLeft}
      groups={layout.groups}
      leadingColumn={{ className: css["workbench-row-number"], label: "行", width: ROW_NUMBER_WIDTH }}
      onResize={layout.resize}
      onSort={onSort}
      sort={sort}
      widths={layout.widths}
    />
    <tbody>
      {page.rows.map((row, rowIndex) => {
        const boundary = boundaries[rowIndex]!;
        if (boundary.startsGroup) groupIndex += 1;
        const groupClass = boundary.key === null ? undefined : groupIndex % 2 === 0 ? css["is-group-even"] : css["is-group-odd"];
        return <tr className={`${boundary.startsGroup ? css["is-group-start"] : ""} ${groupClass ?? ""}`.trim()} key={row.row_id}>
          <th className={css["workbench-row-number"]} scope="row" style={{ left: 0, width: ROW_NUMBER_WIDTH }}>
            {row.row_ordinal}
            {boundary.startsGroup && boundary.key && <small aria-hidden="true" className={css["workbench-group-label"]} title={`本页商品组：${boundary.key}`}>{boundary.key}</small>}
          </th>
          {visibleColumns.map((column) => {
            const cell = row.cells.find((item) => item.column_id === column.column_id);
            if (!cell) return null;
            const key = page.head ? cellKey(page.head.version_id, row.row_id, column.column_id) : "";
            const editor = editors[key];
            const visibleValue = String(cell.current ?? "");
            const isFrozen = Object.hasOwn(layout.frozenLeft, column.column_id);
            const style: CSSProperties = {
              width: layout.widths[column.column_id],
              minWidth: layout.widths[column.column_id],
              maxWidth: layout.widths[column.column_id],
              ...(isFrozen ? { left: headerFrozenLeft[column.column_id], position: "sticky" } : {}),
            };
            const status = statusText(editor);
            return <td className={`${isFrozen ? css["workbench-identity-cell"] : ""} ${cell.changed ? css["is-changed"] : ""} ${editor?.state === "failed" || editor?.state === "conflict" ? css["has-error"] : ""}`.trim()} key={column.column_id} style={style}>
              {cell.editable ? <EditableCellInput authoritativeValue={visibleValue} column={column} editor={editor} onDiscardCell={onDiscardCell} onEditCell={onEditCell} onSaveCell={onSaveCell} revision={cell.cell_revision} rowId={row.row_id} rowOrdinal={row.row_ordinal} /> : <span className={css["workbench-cell-value"]} title={visibleValue}>{visibleValue}</span>}
              {!cell.editable && status && <small className={`${css["workbench-cell-status"]} ${editor?.state === "failed" || editor?.state === "conflict" ? css["cell-error"] : ""}`.trim()} role={editor?.state === "failed" || editor?.state === "conflict" ? "alert" : "status"}>{status}</small>}
            </td>;
          })}
        </tr>;
      })}
    </tbody>
  </table>;
}
