import { useEffect, useState } from "react";
import { requestApi } from "../../api/client";
import type { WorkbenchColumnResponse, WorkbenchRowResponse } from "../../api/generated";

type VersionRowsResponse = {
  version_id: number;
  columns: WorkbenchColumnResponse[];
  rows: WorkbenchRowResponse[];
  pagination: { page: number; total_pages: number; total_rows: number };
};

export function VersionRows({ versionId, versionNo, reportDate }: {
  versionId: number; versionNo: number; reportDate: string;
}) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [response, setResponse] = useState<VersionRowsResponse>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    if (!open) return;
    let active = true;
    setResponse(undefined);
    setError(undefined);
    void requestApi<VersionRowsResponse>(`/api/versions/${versionId}/rows?page=${page}&page_size=50`)
      .then((result) => {
        if (result.version_id !== versionId) throw new Error("返回的版本与所选版本不一致，请重新读取。");
        if (active) setResponse(result);
      })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "读取失败"); });
    return () => { active = false; };
  }, [open, page, retry, versionId]);
  return <section className="version-rows" aria-label={`v${versionNo} 数据明细`}>
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
      {open ? "收起版本数据" : "查看此版本数据"}
    </button>
    {open && <>
      <h3>{reportDate} · v{versionNo} 数据明细 · 只读</h3>
      <p>固定查看所选版本，不随当前发布版本变化。受限字段不展示，金额与比率保留存储精度。</p>
      {error ? <div role="alert">{error} <button type="button" onClick={() => setRetry(retry + 1)}>重新读取</button></div>
        : !response ? <p role="status">正在读取版本数据…</p> : <>
          <p>共 {response.pagination.total_rows} 行 · 第 {page} / {response.pagination.total_pages} 页</p>
          <div className="version-rows__scroll" role="region" aria-label="版本数据表格，可横向滚动" tabIndex={0}>
            <table><caption>{reportDate} · v{versionNo}</caption>
              <thead><tr><th scope="col">行</th><th scope="col">状态</th>{response.columns.map((column) => <th scope="col" key={column.column_id}>{column.source_header}</th>)}</tr></thead>
              <tbody>{response.rows.map((row) => <tr key={row.row_id}><th scope="row">{row.row_ordinal}</th><td>{row.row_state === "active" ? "有效" : row.row_state === "excluded" ? "已排除" : "已删除"}</td>{response.columns.map((column) => <td key={column.column_id}>{row.cells.find((cell) => cell.column_id === column.column_id)?.current ?? "—"}</td>)}</tr>)}</tbody>
            </table>
          </div>
          {response.rows.length === 0 && <p>该版本没有数据行。</p>}
          <nav aria-label="版本数据分页"><button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><button type="button" disabled={page >= response.pagination.total_pages} onClick={() => setPage(page + 1)}>下一页</button></nav>
        </>}
    </>}
  </section>;
}
