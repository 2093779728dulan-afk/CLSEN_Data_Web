import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { PresentableColumn } from "../../features/workbench/workbenchTypes";
import {
  loadColumnPreferences,
  preferenceKey,
  saveColumnPreferences,
  type ColumnPreferenceIdentity,
  type ResolvedColumnPreferences,
} from "./columnPreferences";
import { clampColumnWidth, frozenColumnIds, groupVisibleColumns, recommendedWidth } from "./columnPresentation";

export type DataTableColumn = PresentableColumn & { participates_in_statistics?: boolean };

export type ColumnLayoutCommands = {
  resize(columnId: string, width: number): void;
  move(columnId: string, beforeColumnId: string | null): void;
  setVisible(columnId: string, visible: boolean): void;
  showStatisticalOnly(): void;
  restoreSourceOrder(): void;
  resetWidths(): void;
};

export type ColumnLayout = ColumnLayoutCommands & {
  containerRef: React.RefObject<HTMLDivElement | null>;
  orderedIds: string[];
  visibleIds: string[];
  orderedColumns: DataTableColumn[];
  visibleColumns: DataTableColumn[];
  widths: Record<string, number>;
  groups: ReturnType<typeof groupVisibleColumns>;
  frozenIds: string[];
  frozenLeft: Record<string, number>;
  viewportWidth: number;
};

type UseColumnLayoutArgs = {
  columns: readonly DataTableColumn[];
  identity: ColumnPreferenceIdentity;
  viewportWidth?: number;
};

function sourceIds(columns: readonly DataTableColumn[]) {
  return columns
    .map((column, index) => ({ column, index }))
    .sort((left, right) => left.column.display_order - right.column.display_order || left.index - right.index)
    .map(({ column }) => column.column_id);
}

function hiddenIds(preferences: ResolvedColumnPreferences) {
  const visible = new Set(preferences.visibleIds);
  return preferences.orderedIds.filter((id) => !visible.has(id));
}

/**
 * Keeps presentation preferences local to a user/site/report combination.
 * Commands commit their final state; pointer movement is deliberately handled
 * by DataTableHeader so only a completed resize reaches `resize`.
 */
export function useColumnLayout({ columns, identity, viewportWidth }: UseColumnLayoutArgs): ColumnLayout {
  const key = preferenceKey(identity);
  const columnsRef = useRef(columns);
  columnsRef.current = columns;
  const [preferences, setPreferences] = useState<ResolvedColumnPreferences>(() => loadColumnPreferences(key, columns));
  const containerRef = useRef<HTMLDivElement>(null);
  const [measuredWidth, setMeasuredWidth] = useState<number>();

  useEffect(() => {
    setPreferences(loadColumnPreferences(key, columns));
  }, [columns, key]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (typeof width === "number" && Number.isFinite(width)) setMeasuredWidth(width);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  const commit = useCallback((next: ResolvedColumnPreferences) => {
    setPreferences(next);
    saveColumnPreferences(key, { version: 1, order: next.orderedIds, hidden: hiddenIds(next), widths: next.widths });
  }, [key]);

  const orderedColumns = useMemo(() => {
    const byId = new Map(columns.map((column) => [column.column_id, column]));
    return preferences.orderedIds.map((id) => byId.get(id)).filter((column): column is DataTableColumn => Boolean(column));
  }, [columns, preferences.orderedIds]);
  const visibleColumns = useMemo(() => {
    const visible = new Set(preferences.visibleIds);
    return orderedColumns.filter((column) => visible.has(column.column_id));
  }, [orderedColumns, preferences.visibleIds]);

  const resize = useCallback((columnId: string, width: number) => {
    if (!columnsRef.current.some((column) => column.column_id === columnId)) return;
    commit({ ...preferences, widths: { ...preferences.widths, [columnId]: clampColumnWidth(width) } });
  }, [commit, preferences]);

  const move = useCallback((columnId: string, beforeColumnId: string | null) => {
    if (columnId === beforeColumnId || !preferences.orderedIds.includes(columnId)) return;
    const remaining = preferences.orderedIds.filter((id) => id !== columnId);
    const index = beforeColumnId === null ? remaining.length : remaining.indexOf(beforeColumnId);
    remaining.splice(index < 0 ? remaining.length : index, 0, columnId);
    commit({ ...preferences, orderedIds: remaining });
  }, [commit, preferences]);

  const setVisible = useCallback((columnId: string, visible: boolean) => {
    const column = columnsRef.current.find((item) => item.column_id === columnId);
    if (!column) return;
    const current = new Set(preferences.visibleIds);
    const visibleIdentityCount = preferences.visibleIds.filter((id) => columnsRef.current.find((item) => item.column_id === id)?.is_key).length;
    if (!visible && column.is_key && visibleIdentityCount <= 1) return;
    if (visible) current.add(columnId); else current.delete(columnId);
    commit({ ...preferences, visibleIds: preferences.orderedIds.filter((id) => current.has(id)) });
  }, [commit, preferences]);

  const showStatisticalOnly = useCallback(() => {
    const visible = new Set(columnsRef.current.filter((column) => column.is_key || column.participates_in_statistics).map((column) => column.column_id));
    commit({ ...preferences, visibleIds: preferences.orderedIds.filter((id) => visible.has(id)) });
  }, [commit, preferences]);

  const restoreSourceOrder = useCallback(() => {
    commit({ ...preferences, orderedIds: sourceIds(columnsRef.current) });
  }, [commit, preferences]);

  const resetWidths = useCallback(() => {
    commit({ ...preferences, widths: Object.fromEntries(columnsRef.current.map((column) => [column.column_id, recommendedWidth(column)])) });
  }, [commit, preferences]);

  const resolvedViewportWidth = measuredWidth ?? viewportWidth ?? (typeof window === "undefined" ? 0 : window.innerWidth);
  const frozen = frozenColumnIds(identity.reportType, visibleColumns, preferences.widths, resolvedViewportWidth);
  const frozenSet = new Set(frozen);
  const frozenIds = visibleColumns.filter((column) => frozenSet.has(column.column_id)).map((column) => column.column_id);
  const frozenLeft: Record<string, number> = {};
  let left = 0;
  for (const id of frozenIds) {
    frozenLeft[id] = left;
    left += preferences.widths[id] ?? recommendedWidth(visibleColumns.find((column) => column.column_id === id)!);
  }

  return {
    containerRef, orderedIds: preferences.orderedIds, visibleIds: preferences.visibleIds, orderedColumns, visibleColumns,
    widths: preferences.widths, groups: groupVisibleColumns(identity.reportType, visibleColumns), frozenIds, frozenLeft,
    viewportWidth: resolvedViewportWidth, resize, move, setVisible, showStatisticalOnly, restoreSourceOrder, resetWidths,
  };
}
