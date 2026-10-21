import { Button, EmptyState, Input, Pagination, Skeleton, StatusBadge, StatusMessage, Table } from "../../design-system";
import type { RawFilePreviewResponse } from "../../api/generated";
import css from "./ImportEvidence.module.css";

export type SourcePreviewViewProps = {
  fileName: string;
  open: boolean;
  loading: boolean;
  error?: string;
  table?: RawFilePreviewResponse;
  query: string;
  page: number;
  totalPages: number;
  filteredCount: number;
  visibleRows: { row: string[]; ordinal: number }[];
  onToggle: () => void;
  onRetry: () => void;
  onQueryChange: (value: string) => void;
  onPageChange: (page: number) => void;
};

export function SourcePreviewView({ fileName, open, loading, error, table, query, page, totalPages, filteredCount, visibleRows, onToggle, onRetry, onQueryChange, onPageChange }: SourcePreviewViewProps) {
  return <section aria-label="上传源表预览" className={css.source}>
    <header className={css.heading}>
      <div className={css.identity}><p className={css.kicker}>上传源表 · 只读证据</p><h3>原表前 200 行只读预览</h3><p className={css.fileName}>{fileName}</p><p>完整文件仍可通过下载获取；此处不会修改原表。</p></div>
      <Button aria-expanded={open} variant="secondary" loading={loading} disabled={loading} onClick={onToggle} type="button">{loading ? "正在读取…" : open ? "收起源表" : "查看上传源表"}</Button>
    </header>
    {loading && <div className={css.content} role="status" aria-label="正在读取源表"><Skeleton lines={4} /></div>}
    {error && <div className={css.content}><StatusMessage kind="danger" title="源表读取未完成">{error}<Button variant="quiet" onClick={onRetry} type="button">重试</Button></StatusMessage></div>}
    {open && table && <div className={css.sourceBody}>
      <div className={css.toolbar}>
        <div><strong>预览 {table.row_count} 行 · {table.headers.length} 列</strong><StatusBadge tone="quiet" label={table.truncated ? "文件其余行未加载" : "已到文件末尾"} /></div>
        <label className={css.field}>搜索预览行<Input onChange={event => onQueryChange(event.target.value)} placeholder="仅搜索已返回的预览内容" type="search" value={query} /></label>
      </div>
      {table.headers.length > 0 ? <>
        <Table aria-label="上传源表数据" className={css.previewTable}>
          <thead><tr><th scope="col">行</th>{table.headers.map((header, index) => <th scope="col" key={`${header}-${index}`}>{header || `未命名列 ${index + 1}`}</th>)}</tr></thead>
          <tbody>{visibleRows.map(({ row, ordinal }) => <tr key={ordinal}><th scope="row">{ordinal}</th>{table.headers.map((_, columnIndex) => <td key={columnIndex} title={row[columnIndex] ?? ""}>{row[columnIndex] || "—"}</td>)}</tr>)}</tbody>
        </Table>
        {visibleRows.length === 0 && <EmptyState title="没有找到符合条件的预览记录。" description="搜索仅覆盖已读取的源表预览，试试其他关键词。" />}
        <Pagination page={page} totalPages={totalPages} totalItems={filteredCount} itemLabel="预览行" onPageChange={onPageChange} />
      </> : <EmptyState title="源文件没有可展示的表头或数据行。" description="返回文件选择，核对当前文件和编码。" />}
    </div>}
  </section>;
}
