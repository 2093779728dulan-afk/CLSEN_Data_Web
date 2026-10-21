import { useMemo, useState } from "react";

import type { DataTableColumn, ColumnLayoutCommands } from "./useColumnLayout";

export type ColumnSettingsLayout = ColumnLayoutCommands & {
  orderedIds: readonly string[];
  visibleIds: readonly string[];
  widths: Readonly<Record<string, number>>;
};

type Props = {
  columns: readonly DataTableColumn[];
  id?: string;
  layout: ColumnSettingsLayout;
  onChange: () => void;
  onClose: () => void;
};

export function ColumnSettingsPanel({ columns, id, layout, onChange, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [draggingId, setDraggingId] = useState<string>();
  const byId = useMemo(() => new Map(columns.map((column) => [column.column_id, column])), [columns]);
  const visibleIds = new Set(layout.visibleIds);
  const orderedColumns = layout.orderedIds.map((id) => byId.get(id)).filter((column): column is DataTableColumn => Boolean(column));
  const visibleIdentityCount = orderedColumns.filter((column) => column.is_key && visibleIds.has(column.column_id)).length;
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const matchingColumns = orderedColumns.filter((column) => !normalizedQuery || `${column.source_header} ${column.standard_field_name ?? ""}`.toLocaleLowerCase().includes(normalizedQuery));
  const changed = (command: () => void) => { command(); onChange(); };

  return <section aria-label="列设置" className="column-settings-panel" id={id}>
    <header><h2>列设置</h2><button aria-label="关闭列设置" onClick={onClose} type="button">×</button></header>
    <label className="column-settings-panel__search">搜索列<input aria-label="搜索列" onChange={(event) => setQuery(event.target.value)} type="search" value={query} /></label>
    <ul aria-label="列顺序和显示">
      {matchingColumns.map((column) => {
        const visible = visibleIds.has(column.column_id);
        const isLastIdentity = visible && column.is_key && visibleIdentityCount <= 1;
        const orderIndex = orderedColumns.findIndex((item) => item.column_id === column.column_id);
        const previous = orderedColumns[orderIndex - 1];
        const next = orderedColumns[orderIndex + 1];
        const afterNext = orderedColumns[orderIndex + 2];
        return <li draggable key={column.column_id} onDragEnd={() => setDraggingId(undefined)} onDragOver={(event) => event.preventDefault()} onDragStart={() => setDraggingId(column.column_id)} onDrop={() => { if (draggingId && draggingId !== column.column_id) changed(() => layout.move(draggingId, column.column_id)); setDraggingId(undefined); }}>
          <label><input aria-label={column.source_header} checked={visible} disabled={isLastIdentity} onChange={(event) => changed(() => layout.setVisible(column.column_id, event.target.checked))} type="checkbox" />{column.source_header}</label>
          <span className="column-settings-panel__moves">
            <button aria-label={`将 ${column.source_header} 上移`} disabled={!previous} onClick={() => previous && changed(() => layout.move(column.column_id, previous.column_id))} type="button">↑</button>
            <button aria-label={`将 ${column.source_header} 下移`} disabled={!next} onClick={() => next && changed(() => layout.move(column.column_id, afterNext?.column_id ?? null))} type="button">↓</button>
          </span>
        </li>;
      })}
      <li className="column-settings-panel__drop-end" onDragOver={(event) => event.preventDefault()} onDrop={() => { if (draggingId) changed(() => layout.move(draggingId, null)); setDraggingId(undefined); }}>
        <button aria-label="将拖动列放到末尾" type="button">拖到末尾</button>
      </li>
    </ul>
    <footer>
      <button onClick={() => changed(() => layout.showStatisticalOnly())} type="button">只显示统计字段</button>
      <button onClick={() => changed(() => layout.restoreSourceOrder())} type="button">恢复原始顺序</button>
      <button onClick={() => changed(() => layout.resetWidths())} type="button">重置列宽</button>
    </footer>
  </section>;
}
