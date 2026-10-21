import surfaceCss from "./ReviewSurfaces.module.css";
import { Button, Input } from "../../design-system";
import { useMemo, useState } from "react";

import { requestApi } from "../../api/client";
import type { RawFilePreviewResponse } from "../../api/generated";

type Props = {
  batchId: number;
  encoding: "utf-8-sig" | "utf-8" | "windows-1252";
  fileName: string;
};

const PAGE_SIZE = 50;

export function SourceFilePreview(props: Props) {
  return <SourcePreviewContent key={`${props.batchId}:${props.encoding}`} {...props} />;
}

function SourcePreviewContent({ batchId, encoding, fileName }: Props) {
  const [table, setTable] = useState<RawFilePreviewResponse>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");

  const load = async () => {
    if (table || loading) {
      setOpen(true);
      return;
    }
    setLoading(true);
    setError(undefined);
    try {
      const parameters = new URLSearchParams({ encoding, row_limit: "200" });
      const result = await requestApi<RawFilePreviewResponse>(
        `/api/imports/${batchId}/raw-file/preview?${parameters}`,
      );
      setTable(result);
      setPage(1);
      setOpen(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "源文件暂时无法读取。");
    } finally {
      setLoading(false);
    }
  };

  const filteredRows = useMemo(() => {
    if (!table) return [];
    const needle = query.trim().toLocaleLowerCase();
    return table.rows.map((row, index) => ({ row, ordinal: index + 1 })).filter(({ row }) => !needle || row.some((value) => value.toLocaleLowerCase().includes(needle)));
  }, [query, table]);
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const visibleRows = filteredRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return <section aria-label="上传源表预览" className={surfaceCss["source-preview"]}>
    <header className={surfaceCss["source-preview__header"]}>
      <div><p className="section-kicker">上传源表</p><h3>原表前 200 行只读预览</h3><p>{fileName} · 完整文件仍可通过下载获取</p></div>
      <div className={surfaceCss["source-preview__actions"]}><Button aria-expanded={open} variant="secondary" disabled={loading} onClick={() => { if (open) setOpen(false); else void load(); }} type="button">{loading ? "正在读取…" : open ? "收起源表" : "查看上传源表"}</Button></div>
    </header>
    {error && <p className="form-error" role="alert">{error}<Button variant="quiet" onClick={() => { setTable(undefined); void load(); }} type="button">重试</Button></p>}
    {open && table && <>
      <div className={surfaceCss["source-preview__toolbar"]}><span>预览 {table.row_count} 行 · {table.headers.length} 列{table.truncated ? " · 文件其余行未加载" : " · 已到文件末尾"}</span><label className="search-field">搜索预览行<Input onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="仅搜索已返回的预览内容" type="search" value={query} /></label></div>
      {table.headers.length > 0 ? <div aria-label="上传源表数据" className={surfaceCss["source-preview__scroll"]} role="region" tabIndex={0}><table><thead><tr><th>行</th>{table.headers.map((header, index) => <th key={`${header}-${index}`}>{header || `未命名列 ${index + 1}`}</th>)}</tr></thead><tbody>{visibleRows.map(({ row, ordinal }) => <tr key={ordinal}><th scope="row">{ordinal}</th>{table.headers.map((_, columnIndex) => <td key={columnIndex} title={row[columnIndex] ?? ""}>{row[columnIndex] || "—"}</td>)}</tr>)}</tbody></table>{visibleRows.length === 0 && <p className="table-empty">没有找到符合条件的预览记录。</p>}</div> : <p className="table-empty">源文件没有可展示的表头或数据行。</p>}
      <footer className="table-pagination"><span>第 {page} / {totalPages} 页 · 显示 {visibleRows.length} 行</span><div><Button variant="secondary" disabled={page <= 1} onClick={() => setPage((current) => current - 1)} type="button">上一页</Button><Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)} type="button">下一页</Button></div></footer>
    </>}
  </section>;
}
