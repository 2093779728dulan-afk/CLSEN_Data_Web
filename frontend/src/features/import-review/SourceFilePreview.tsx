import { SourcePreviewView } from "./SourcePreviewView";
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

  return <SourcePreviewView
    fileName={fileName} open={open} loading={loading} error={error} table={table}
    query={query} page={page} totalPages={totalPages} filteredCount={filteredRows.length} visibleRows={visibleRows}
    onToggle={() => { if (open) setOpen(false); else void load(); }}
    onRetry={() => { setTable(undefined); void load(); }}
    onQueryChange={(value) => { setQuery(value); setPage(1); }} onPageChange={setPage}
  />;
}
