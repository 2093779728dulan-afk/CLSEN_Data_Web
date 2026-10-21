import { useEffect, useRef, useState } from "react";

import type { ColumnGroupSpan } from "./columnPresentation";
import { clampColumnWidth, recommendedWidth } from "./columnPresentation";
import type { DataTableColumn } from "./useColumnLayout";

export type SortDirection = "asc" | "desc";
export type DataTableSort = { columnId: string; direction: SortDirection } | null;
export type SortCommand = { columnId: string; direction: SortDirection | null };

type Props = {
  groups: readonly ColumnGroupSpan[];
  columns: readonly DataTableColumn[];
  widths: Readonly<Record<string, number>>;
  frozenLeft: Readonly<Record<string, number>>;
  sort: DataTableSort;
  onSort: (command: SortCommand) => void;
  onResize: (columnId: string, width: number) => void;
  leadingColumn?: { label: string; className?: string; width: number };
  leadingColumns?: readonly { label: string; className?: string; width: number }[];
};

function nextSort(sort: DataTableSort, columnId: string): SortCommand {
  if (sort?.columnId !== columnId) return { columnId, direction: "asc" };
  if (sort.direction === "asc") return { columnId, direction: "desc" };
  return { columnId, direction: null };
}

export function DataTableHeader({ groups, columns, widths, frozenLeft, sort, onSort, onResize, leadingColumn, leadingColumns }: Props) {
  const [draftWidths, setDraftWidths] = useState<Record<string, number>>({});
  const pointerStart = useRef<{
    columnId: string;
    clientX: number;
    pointerId: number;
    target: HTMLButtonElement;
    width: number;
    onMove: (event: PointerEvent) => void;
    onEnd: (event: PointerEvent) => void;
  } | undefined>(undefined);

  const clearPointerResize = () => {
    const active = pointerStart.current;
    if (!active) return;
    window.removeEventListener("pointermove", active.onMove);
    window.removeEventListener("pointerup", active.onEnd);
    window.removeEventListener("pointercancel", active.onEnd);
    if (active.target.hasPointerCapture?.(active.pointerId)) active.target.releasePointerCapture?.(active.pointerId);
    pointerStart.current = undefined;
    setDraftWidths((current) => {
      const remaining = { ...current };
      delete remaining[active.columnId];
      return remaining;
    });
  };

  useEffect(() => () => clearPointerResize(), []);

  const orderedLeadingColumns = leadingColumns ?? (leadingColumn ? [leadingColumn] : []);
  let leadingLeft = 0;

  return <thead className="data-table-header">
    <tr className="data-table-header__groups">
      {orderedLeadingColumns.map((column, index) => {
        const left = leadingLeft;
        leadingLeft += column.width;
        return <th
          className={`data-table-header__leading ${column.className ?? ""}`.trim()}
          key={`${column.label}:${index}`}
          rowSpan={2}
          scope="col"
          style={{ left, maxWidth: column.width, minWidth: column.width, width: column.width }}
        >{column.label}</th>;
      })}
      {groups.map((group, index) => <th colSpan={group.colSpan} key={`${group.key}:${index}`} scope="colgroup">{group.label}</th>)}
    </tr>
    <tr className="data-table-header__columns">
      {columns.map((column) => {
        const width = clampColumnWidth(draftWidths[column.column_id] ?? widths[column.column_id] ?? recommendedWidth(column));
        const isFrozen = Object.hasOwn(frozenLeft, column.column_id);
        const ariaSort = sort?.columnId === column.column_id ? sort.direction === "asc" ? "ascending" : "descending" : "none";
        const stickyStyle = isFrozen ? { left: frozenLeft[column.column_id], width } : { width };
        return <th aria-sort={ariaSort} className={isFrozen ? "data-table-header__frozen" : undefined} key={column.column_id} onClick={() => onSort(nextSort(sort, column.column_id))} scope="col" style={stickyStyle} title={column.source_header}>
          <button aria-label={`按 ${column.source_header} 排序`} className="data-table-header__sort" onClick={(event) => { event.stopPropagation(); onSort(nextSort(sort, column.column_id)); }} type="button">
            <span>{column.source_header}</span>{column.participates_in_statistics && <small>统计</small>}<i aria-hidden="true">{ariaSort === "ascending" ? "↑" : ariaSort === "descending" ? "↓" : "↕"}</i>
          </button>
          <button
            aria-label={`调整“${column.source_header}”列宽`}
            className="data-table-resizer"
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
              event.preventDefault();
              onResize(column.column_id, width + (event.key === "ArrowLeft" ? -8 : 8));
            }}
            onPointerDown={(event) => {
              event.stopPropagation();
              clearPointerResize();
              const startWidth = width;
              const onMove = (moveEvent: PointerEvent) => {
                const active = pointerStart.current;
                if (!active || active.pointerId !== moveEvent.pointerId) return;
                setDraftWidths((current) => ({ ...current, [column.column_id]: clampColumnWidth(startWidth + moveEvent.clientX - event.clientX) }));
              };
              const onEnd = (endEvent: PointerEvent) => {
                const active = pointerStart.current;
                if (!active || active.pointerId !== endEvent.pointerId) return;
                const finalWidth = clampColumnWidth(startWidth + endEvent.clientX - event.clientX);
                const shouldPersist = endEvent.type === "pointerup";
                clearPointerResize();
                if (shouldPersist) onResize(column.column_id, finalWidth);
              };
              pointerStart.current = { columnId: column.column_id, clientX: event.clientX, pointerId: event.pointerId, target: event.currentTarget, width: startWidth, onMove, onEnd };
              event.currentTarget.setPointerCapture?.(event.pointerId);
              window.addEventListener("pointermove", onMove);
              window.addEventListener("pointerup", onEnd);
              window.addEventListener("pointercancel", onEnd);
            }}
            type="button"
          />
        </th>;
      })}
    </tr>
  </thead>;
}
