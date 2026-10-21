import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Columns3, GripVertical, RotateCcw, X } from "lucide-react";
import { Button, Checkbox, EmptyState, SearchInput } from "../../design-system";
import css from "./ColumnSettingsPanel.module.css";

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
  const panel = useRef<HTMLElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [draggingId, setDraggingId] = useState<string>();
  const byId = useMemo(() => new Map(columns.map((column) => [column.column_id, column])), [columns]);
  const visibleIds = new Set(layout.visibleIds);
  const orderedColumns = layout.orderedIds.map((id) => byId.get(id)).filter((column): column is DataTableColumn => Boolean(column));
  const visibleIdentityCount = orderedColumns.filter((column) => column.is_key && visibleIds.has(column.column_id)).length;
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const matchingColumns = orderedColumns.filter((column) => !normalizedQuery || `${column.source_header} ${column.standard_field_name ?? ""}`.toLocaleLowerCase().includes(normalizedQuery));
  const changed = (command: () => void) => { command(); onChange(); };
  useEffect(() => {
    search.current?.focus({ preventScroll: true });
    panel.current?.scrollIntoView?.({ block: "nearest" });
  }, []);

  return <section aria-label="列设置" className={`column-settings-panel ${css.panel}`} id={id} ref={panel} onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } }}>
    <header className={css.heading}>
      <div className={css.title}><Columns3 aria-hidden="true" /><h2>列设置</h2></div>
      <Button aria-label="关闭列设置" className={css.iconButton} icon={<X />} onClick={onClose} variant="quiet" />
    </header>
    <p className={css.description}>调整当前表格的显示与顺序，不改变报表数据。</p>
    <SearchInput aria-label="搜索列" clearLabel="清空列搜索" onValueChange={setQuery} placeholder="搜索列名或标准字段" ref={search} value={query} />
    <div className={css.summary}><span>显示 {visibleIds.size} / {orderedColumns.length} 列</span><span>{normalizedQuery ? `匹配 ${matchingColumns.length} 列` : "拖动或用箭头排序"}</span></div>
    {matchingColumns.length === 0 && <EmptyState title={orderedColumns.length === 0 ? "暂无可设置的列" : "没有匹配的列"} description={orderedColumns.length === 0 ? "读取表格列结构后即可设置。" : "试试其他列名或清空搜索。"} action={query ? <Button onClick={() => setQuery("")}>清空列搜索</Button> : undefined} />}
    <ul aria-label="列顺序和显示" className={css.list}>
      {matchingColumns.map((column) => {
        const visible = visibleIds.has(column.column_id);
        const isLastIdentity = visible && column.is_key && visibleIdentityCount <= 1;
        const orderIndex = orderedColumns.findIndex((item) => item.column_id === column.column_id);
        const previous = orderedColumns[orderIndex - 1];
        const next = orderedColumns[orderIndex + 1];
        const afterNext = orderedColumns[orderIndex + 2];
        return <li className={css.item} data-dragging={draggingId === column.column_id || undefined} data-visible={visible} draggable key={column.column_id} onDragEnd={() => setDraggingId(undefined)} onDragOver={(event) => event.preventDefault()} onDragStart={() => setDraggingId(column.column_id)} onDrop={(event) => { event.preventDefault(); if (draggingId && draggingId !== column.column_id) changed(() => layout.move(draggingId, column.column_id)); setDraggingId(undefined); }}>
          <GripVertical aria-hidden="true" className={css.grip} />
          <div className={css.column}>
            <Checkbox aria-label={column.source_header} checked={visible} disabled={isLastIdentity} label={column.source_header} onChange={(event) => changed(() => layout.setVisible(column.column_id, event.target.checked))} />
            {column.is_key && <span className={css.keyHint}>{isLastIdentity ? "最后一列标识 · 必须保留" : "标识字段"}</span>}
          </div>
          <span className={css.moves}>
            <Button aria-label={`将 ${column.source_header} 上移`} className={css.iconButton} disabled={!previous} icon={<ArrowUp />} onClick={() => previous && changed(() => layout.move(column.column_id, previous.column_id))} variant="quiet" />
            <Button aria-label={`将 ${column.source_header} 下移`} className={css.iconButton} disabled={!next} icon={<ArrowDown />} onClick={() => next && changed(() => layout.move(column.column_id, afterNext?.column_id ?? null))} variant="quiet" />
          </span>
        </li>;
      })}
      {matchingColumns.length > 0 && <li className={css.dropEnd} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (draggingId) changed(() => layout.move(draggingId, null)); setDraggingId(undefined); }}>
        <span aria-label="将拖动列放到末尾" role="region"><GripVertical aria-hidden="true" />拖到这里，放至末尾</span>
      </li>}
    </ul>
    <footer className={css.footer}>
      <Button disabled={columns.length === 0} onClick={() => changed(() => layout.showStatisticalOnly())}>只显示统计字段</Button>
      <div className={css.resetActions}><Button disabled={columns.length === 0} icon={<RotateCcw />} onClick={() => changed(() => layout.restoreSourceOrder())} variant="quiet">恢复原始顺序</Button>
      <Button disabled={columns.length === 0} onClick={() => changed(() => layout.resetWidths())} variant="quiet">重置列宽</Button></div>
    </footer>
    <p className={css.note}>设置保存在当前浏览器，按账号、站点和报表类型分别记忆。</p>
  </section>;
}
