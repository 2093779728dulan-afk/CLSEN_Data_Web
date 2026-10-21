import type { DataTableReportType, WorkbenchColumn, WorkbenchRow } from "./workbenchTypes";

export type RowGroupBoundary = { key: string | null; startsGroup: boolean };

function columnName(column: WorkbenchColumn) {
  return `${column.standard_field_name ?? ""} ${column.source_header}`.normalize("NFC").toLocaleLowerCase();
}

function hasToken(column: WorkbenchColumn, token: string) {
  return new RegExp(`(^|[^a-z])${token}($|[^a-z])`).test(columnName(column));
}

function isParentAsin(column: WorkbenchColumn) {
  const name = columnName(column);
  return /parent[ _-]*asin/.test(name) || /asin[ _-]*parent/.test(name);
}

function isSku(column: WorkbenchColumn) {
  return hasToken(column, "sku") && !/fnsku/.test(columnName(column));
}

function isAsin(column: WorkbenchColumn) {
  return !isParentAsin(column) && hasToken(column, "asin");
}

function nonEmptyCellValue(row: WorkbenchRow, column: WorkbenchColumn | undefined) {
  if (!column) return null;
  const value = row.cells.find((cell) => cell.column_id === column.column_id)?.current;
  const text = value === null || value === undefined ? "" : String(value).trim();
  return text || null;
}

function firstColumn(columns: readonly WorkbenchColumn[], predicate: (column: WorkbenchColumn) => boolean) {
  return columns.find(predicate);
}

/**
 * Resolves a display-only product identity from visible cells. It deliberately
 * does not alter the server's row order or use values outside the current row.
 */
export function groupKey(reportType: DataTableReportType, row: WorkbenchRow, columns: readonly WorkbenchColumn[]): string | null {
  const sku = nonEmptyCellValue(row, firstColumn(columns, isSku));

  if (reportType === "return_report") {
    return sku ?? nonEmptyCellValue(row, firstColumn(columns, isAsin));
  }

  const parentAsin = nonEmptyCellValue(row, firstColumn(columns, isParentAsin));
  if (parentAsin) return parentAsin;
  if (!sku) return null;

  // Only the established numeric-style `款号-颜色-尺码` form can collapse
  // variants to a style code. Every other non-empty SKU stays distinct.
  const styleCode = /^(\d+)-[^-\s]+-[^-\s]+$/.exec(sku)?.[1];
  return styleCode ?? sku;
}

/**
 * Marks boundaries by comparing adjacent rows as received on this server page.
 * The first usable identity is a local (not cross-page) boundary.
 */
export function rowGroupBoundaries(
  reportType: DataTableReportType,
  rows: readonly WorkbenchRow[],
  columns: readonly WorkbenchColumn[],
): RowGroupBoundary[] {
  let previousKey: string | null = null;
  let hasPreviousKey = false;

  return rows.map((row) => {
    const key = groupKey(reportType, row, columns);
    const startsGroup = key !== null && (!hasPreviousKey || previousKey !== key);
    previousKey = key;
    hasPreviousKey = key !== null;
    return { key, startsGroup };
  });
}
