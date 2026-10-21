import { Link, useLocation } from "react-router-dom";
import { Button, EmptyState, ErrorState, Pagination } from "../../design-system";
import styles from "./PublishedDetailLedgerPage.module.css";
import { useMemo, useRef, useState, type CSSProperties } from "react";

import { ColumnSettingsPanel } from "../../components/data-table/ColumnSettingsPanel";
import {
  DataTableHeader,
  type DataTableSort,
  type SortCommand,
} from "../../components/data-table/DataTableHeader";
import { useColumnLayout } from "../../components/data-table/useColumnLayout";
import "../../components/data-table/dataTable.css";
import { publishedCsvUrl } from "./publishedDetailsApi";
import type {
  PublishedExportQuery,
  PublishedRowsResponse,
} from "./publishedDetailsTypes";

const EMPTY_COLUMNS: PublishedRowsResponse["columns"] = [];
const SYSTEM_COLUMNS = [
  { className: styles["published-grid__report-date"], label: "报告日期", width: 116 },
  { className: styles["published-grid__version"], label: "发布版本", width: 88 },
  { className: styles["published-grid__row-number"], label: "行号", width: 64 },
] as const;
const SYSTEM_COLUMNS_WIDTH = SYSTEM_COLUMNS.reduce((total, column) => total + column.width, 0);

type ExportQuery = Omit<PublishedExportQuery, "columnIds" | "scopeToken">;

export type ReadonlyPublishedDataGridProps = {
  error?: string;
  exportQuery: ExportQuery;
  label?: string;
  loading: boolean;
  onPageChange: (page: number) => void;
  onRetry: () => void;
  onSort: (command: SortCommand) => void;
  pagination?: boolean;
  response?: PublishedRowsResponse;
  siteId: number | string;
  sort: DataTableSort;
  userId: number | string;
};

function visibleValue(value: string | number | null | undefined): string {
  return value === null || value === undefined ? "—" : String(value);
}

function exportUnavailableReason(response: PublishedRowsResponse | undefined): string | undefined {
  if (!response?.scope_token || response.columns.length === 0) return "需先读取列结构和发布快照。";
  if (!response.permissions.can_export) return "当前账号没有已发布明细导出权限。";
  return undefined;
}

export function ReadonlyPublishedDataGrid({
  error,
  exportQuery,
  label,
  loading,
  onPageChange,
  onRetry,
  onSort,
  pagination: showPagination = true,
  response,
  siteId,
  sort,
  userId,
}: ReadonlyPublishedDataGridProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsTriggerRef = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  const returnTo = encodeURIComponent(location.pathname + location.search);
  const columns = response?.columns ?? EMPTY_COLUMNS;
  const layout = useColumnLayout({
    columns,
    identity: {
      namespace: "published-details",
      reportType: exportQuery.reportType,
      siteId,
      userId,
    },
  });
  const visibleColumns = layout.visibleColumns.flatMap((visibleColumn) => {
    const serverColumn = columns.find((column) => column.column_id === visibleColumn.column_id);
    return serverColumn ? [serverColumn] : [];
  });
  const headerFrozenLeft = Object.fromEntries(
    Object.entries(layout.frozenLeft).map(([columnId, left]) => [columnId, left + SYSTEM_COLUMNS_WIDTH]),
  );
  const exportColumnIds = useMemo(() => {
    const visible = new Set(layout.visibleIds);
    return layout.orderedIds.filter((columnId) => (
      visible.has(columnId) || columns.find((column) => column.column_id === columnId)?.is_key
    ));
  }, [columns, layout.orderedIds, layout.visibleIds]);
  const unavailableReason = exportUnavailableReason(response);
  const exportUrl = response && !unavailableReason && exportColumnIds.length > 0
    ? publishedCsvUrl({
        ...exportQuery,
        columnIds: exportColumnIds,
        scopeToken: response.scope_token,
      })
    : undefined;
  const closeSettings = () => {
    setSettingsOpen(false);
    window.setTimeout(() => settingsTriggerRef.current?.focus(), 0);
  };
  const tableLabel = label ?? `${exportQuery.reportType === "business_report" ? "经营报告" : "退货报告"}已发布原始明细`;
  const pagination = showPagination ? response?.pagination : undefined;

  return <section aria-busy={loading} aria-label={tableLabel} className={styles["published-grid"]}>
    <div className={styles["published-grid__actions"]}>
      <span>{response ? `${response.pagination.total_items.toLocaleString("zh-CN")} 行 · 点击报告日期查看单日摘要` : "等待列结构"}</span>
      <div>
        <button
          aria-controls="published-details-column-settings"
          aria-expanded={settingsOpen}
          disabled={columns.length === 0}
          onClick={() => setSettingsOpen((current) => !current)}
          ref={settingsTriggerRef}
          type="button"
        >列设置</button>
        {exportUrl
          ? <a download href={exportUrl}>导出 CSV</a>
          : <Button aria-describedby="published-grid-export-reason" disabled type="button">导出 CSV</Button>}
      </div>
    </div>
    {!exportUrl && <p className={styles["published-grid__export-reason"]} id="published-grid-export-reason">{unavailableReason ?? "当前没有可导出的可见原始列。"}</p>}
    {settingsOpen && <ColumnSettingsPanel
      columns={columns}
      id="published-details-column-settings"
      layout={layout}
      onChange={() => undefined}
      onClose={closeSettings}
    />}
    {error ? <ErrorState title="已发布明细读取失败" description={error} action={<Button onClick={onRetry}>重新读取明细</Button>} /> : !response ? <div aria-live="polite" className={styles["published-grid__state"]} role="status">正在读取只读明细和列结构…</div>
      : <div className={styles["published-grid__scroll"]} ref={layout.containerRef} role="region" tabIndex={0}>
        <table aria-label={tableLabel} style={{ width: `max(100%, ${SYSTEM_COLUMNS_WIDTH + visibleColumns.reduce((total, column) => total + (layout.widths[column.column_id] ?? 168), 0)}px)` }}>
          <DataTableHeader
            columns={visibleColumns}
            frozenLeft={headerFrozenLeft}
            groups={layout.groups}
            leadingColumns={SYSTEM_COLUMNS}
            onResize={(columnId, width) => layout.resize(columnId, width)}
            onSort={onSort}
            sort={sort}
            widths={layout.widths}
          />
          <tbody>{loading ? Array.from({ length: 5 }, (_, index) => <tr className={styles["published-grid__skeleton"]} key={index}>
            <td colSpan={SYSTEM_COLUMNS.length + visibleColumns.length}><span aria-hidden="true" />{index === 0 && <span className={styles["sr-only"]}>正在更新只读明细</span>}</td>
          </tr>) : response.rows.length === 0 ? <tr><td colSpan={SYSTEM_COLUMNS.length + visibleColumns.length}>
            <EmptyState title="没有匹配当前筛选的已发布明细。" description="可调整日期范围、报表类型或搜索条件。" />
          </td></tr> : response.rows.map((row) => {
            const cells = new Map(row.cells.map((cell) => [cell.column_id, cell.value]));
            return <tr key={`${row.report_date}:${row.version_id}:${row.row_ordinal}`}>
              <th className={styles["published-grid__system-cell"] + " " + styles["published-grid__report-date"]} scope="row" style={{ left: 0, width: SYSTEM_COLUMNS[0].width }}><Link aria-label={`查看 ${row.report_date} 单日摘要`} title="查看单日摘要" to={`/published-details/${row.report_date}?return_to=${returnTo}`}><time dateTime={row.report_date}>{row.report_date}</time></Link></th>
              <td className={styles["published-grid__system-cell"] + " " + styles["published-grid__version"]} style={{ left: SYSTEM_COLUMNS[0].width, width: SYSTEM_COLUMNS[1].width }}>v{row.version_no}</td>
              <td className={styles["published-grid__system-cell"] + " " + styles["published-grid__row-number"]} style={{ left: SYSTEM_COLUMNS[0].width + SYSTEM_COLUMNS[1].width, width: SYSTEM_COLUMNS[2].width }}>{row.row_ordinal}</td>
              {visibleColumns.map((column) => {
                const isFrozen = Object.hasOwn(layout.frozenLeft, column.column_id);
                const width = layout.widths[column.column_id] ?? 168;
                const style: CSSProperties = {
                  maxWidth: width,
                  minWidth: width,
                  width,
                  ...(isFrozen ? { left: headerFrozenLeft[column.column_id], position: "sticky" } : {}),
                };
                const value = visibleValue(cells.get(column.column_id));
                return <td className={isFrozen ? styles["published-grid__identity-cell"] : undefined} key={column.column_id} style={style} title={value}>{value}</td>;
              })}
            </tr>;
          })}</tbody>
        </table>
      </div>}
    {pagination && <footer className={styles["published-grid__pagination"]}><Pagination itemLabel="行" loading={loading} onPageChange={onPageChange} page={pagination.page} totalItems={pagination.total_items} totalPages={pagination.total_pages} /></footer>}
  </section>;
}

export default ReadonlyPublishedDataGrid;
