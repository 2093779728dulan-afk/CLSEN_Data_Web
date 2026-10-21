import { ChevronDown, ChevronUp, RefreshCw } from "lucide-react";
import { Button, EmptyState, ErrorState, Pagination, Skeleton, Table } from "../../design-system";
import type { VersionRowsResponse } from "./VersionRows";
import css from "./VersionRowsView.module.css";

type Props = { versionNo: number; reportDate: string; open: boolean; onToggle: () => void; page: number; onPageChange: (value: number) => void; response?: VersionRowsResponse; error?: string; onRetry: () => void };
export function VersionRowsView({ versionNo, reportDate, open, onToggle, page, onPageChange, response, error, onRetry }: Props) {
  return <section className={css.rows} aria-label={`v${versionNo} 数据明细`}>
    <Button icon={open ? <ChevronUp /> : <ChevronDown />} aria-expanded={open} onClick={onToggle}>{open ? "收起版本数据" : "查看此版本数据"}</Button>
    {open && <>
      <h3>{reportDate} · v{versionNo} 数据明细 · 只读</h3>
      <p>固定查看所选版本，不随当前发布版本变化。受限字段不展示，金额与比率保留存储精度。</p>
      {error ? <ErrorState title="版本数据读取失败" description={error} action={<Button icon={<RefreshCw />} onClick={onRetry}>重新读取</Button>} />
        : !response ? <div role="status"><p>正在读取版本数据…</p><Skeleton lines={3} /></div> : <>
          <div className={css.scroll} role="region" aria-label="版本数据表格，可横向滚动" tabIndex={0}>
            <Table aria-label={`${reportDate} · v${versionNo}`}><caption>{reportDate} · v{versionNo}</caption>
              <thead><tr><th scope="col">行</th><th scope="col">状态</th>{response.columns.map(column => <th scope="col" key={column.column_id}>{column.source_header}</th>)}</tr></thead>
              <tbody>{response.rows.map(row => <tr key={row.row_id}><th scope="row">{row.row_ordinal}</th><td>{row.row_state === "active" ? "有效" : row.row_state === "excluded" ? "已排除" : "已删除"}</td>{response.columns.map(column => <td key={column.column_id}>{row.cells.find(cell => cell.column_id === column.column_id)?.current ?? "—"}</td>)}</tr>)}</tbody>
            </Table>
          </div>
          {response.rows.length === 0 && <EmptyState title="该版本没有数据行。" />}
          <Pagination itemLabel="数据行" page={page} totalItems={response.pagination.total_rows} totalPages={response.pagination.total_pages} onPageChange={onPageChange} />
        </>}
    </>}
  </section>;
}
