import { useEffect, useState } from "react";
import { VersionRowsView } from "./VersionRowsView";
import { requestApi } from "../../api/client";
import type { WorkbenchColumnResponse, WorkbenchRowResponse } from "../../api/generated";

export type VersionRowsResponse = {
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
  return <VersionRowsView versionNo={versionNo} reportDate={reportDate} open={open} onToggle={() => setOpen(!open)} page={page} onPageChange={setPage} response={response} error={error} onRetry={() => setRetry(retry + 1)} />;
}
