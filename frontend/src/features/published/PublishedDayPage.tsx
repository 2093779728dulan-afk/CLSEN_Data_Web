import { lazy, Suspense, useEffect, useState } from "react";
import { useMatch, useParams, useSearchParams } from "react-router-dom";
import { requestApi } from "../../api/client";
import type { DailyLedgerResponse, DailyLedgerRow } from "../../api/generated";

import { PublishedDayView } from "./PublishedDayView";

const PublishedMonthTrend = lazy(() => import("./PublishedMonthTrend").then((module) => ({ default: module.PublishedMonthTrend })));

function PublishedDay({ currencyCode, reportDate }: { currencyCode: string; reportDate: string }) {
  const [params] = useSearchParams();
  const requestedReturn = params.get("return_to");
  const returnTo = requestedReturn === "/ledger/published-details" || requestedReturn?.startsWith("/ledger/published-details?") ? requestedReturn : undefined;
  const standalone = Boolean(useMatch("/published-details/:reportDate"));
  const [rows, setRows] = useState<DailyLedgerRow[]>();
  const row = rows?.find((item) => item.report_date === reportDate);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const date = new Date(`${reportDate}T00:00:00Z`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(reportDate) || !Number.isFinite(date.valueOf()) || date.toISOString().slice(0, 10) !== reportDate) {
      setError("报告日期格式无效。");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(undefined);
    setRows(undefined);
    const query = new URLSearchParams({ from: standalone ? `${reportDate.slice(0, 7)}-01` : reportDate, to: reportDate });
    void requestApi<DailyLedgerResponse>(`/api/dashboard/daily-ledger?${query}`, { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setRows(result.rows); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "无法读取已发布数据。"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt, reportDate, standalone]);
  return <PublishedDayView currencyCode={currencyCode} reportDate={reportDate} standalone={standalone} returnTo={returnTo} row={row} error={error} loading={loading} onRetry={() => setAttempt(value => value + 1)}>
    {!loading && !error && standalone && rows && <Suspense fallback={<p role="status">正在载入月内趋势…</p>}><PublishedMonthTrend currencyCode={currencyCode} reportDate={reportDate} rows={rows} /></Suspense>}
  </PublishedDayView>;
}

export function PublishedDayPage({ currencyCode }: { currencyCode: string }) {
  const { reportDate = "" } = useParams();
  return <PublishedDay currencyCode={currencyCode} key={reportDate} reportDate={reportDate} />;
}
