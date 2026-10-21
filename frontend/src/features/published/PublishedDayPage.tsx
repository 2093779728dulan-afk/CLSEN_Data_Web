import { ArrowLeft, CalendarDays, Table2 } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { useMatch, useParams, useSearchParams } from "react-router-dom";
import { requestApi } from "../../api/client";
import type { DailyLedgerResponse, DailyLedgerRow } from "../../api/generated";
import { Button, EmptyState, ErrorState, LinkButton, PageHeader } from "../../design-system";
import styles from "./PublishedDayPage.module.css";

const PublishedMonthTrend = lazy(() => import("./PublishedMonthTrend").then((module) => ({ default: module.PublishedMonthTrend })));

function PublishedDay({ currencyCode, reportDate }: { currencyCode: string; reportDate: string }) {
  const [params] = useSearchParams();
  const requestedReturn = params.get("return_to");
  const returnTo = requestedReturn === "/ledger/published-details" || requestedReturn?.startsWith("/ledger/published-details?") ? requestedReturn : undefined;
  const standalone = Boolean(useMatch("/published-details/:reportDate"));
  const Container = standalone ? "main" : "section";
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
  return <Container id={standalone ? "main-content" : undefined} aria-label="单日只读发布详情" className={styles.page}>
    <PageHeader eyebrow="当前发布版本 · 只读" title={reportDate} description="这里只展示当前发布版本，不包含草稿、失败导入或历史版本。" actions={<nav aria-label="发布数据导航" className={styles.links}>
      {returnTo && <LinkButton icon={<ArrowLeft />} to={returnTo}>返回发布明细</LinkButton>}
      <LinkButton icon={<CalendarDays />} to={`/?month=${reportDate.slice(0, 7)}`} variant="quiet">返回每日总表</LinkButton>
      <LinkButton icon={<Table2 />} to={`/ledger/published-details?from=${reportDate}&to=${reportDate}&mode=rows`} variant="primary">查看当日原始明细</LinkButton>
    </nav>} />
    {loading && <p role="status">正在读取当前发布数据…</p>}
    {error && <ErrorState title="已发布数据读取失败" description={error} action={<Button onClick={() => setAttempt((value) => value + 1)}>重新读取</Button>} />}
    {!loading && !error && !row && <EmptyState title="这个日期没有发布数据" description="可以返回每日总表选择其他日期。" />}
    {!loading && !error && row && <section aria-label="当前发布指标" className={styles.summary}>
      <h2>{row.overall_status === "complete" ? "两类报告均已发布" : "当前发布数据"}</h2>
      <p>{row.pending_summary ?? "无需处理"}</p>
      <dl className={styles.metrics}>
        <div><dt>销售额</dt><dd>{row.sales === null ? "—" : new Intl.NumberFormat("zh-CN", { currency: currencyCode, style: "currency" }).format(Number(row.sales))}</dd></div>
        <div><dt>订购数</dt><dd>{row.units_ordered ?? "—"}</dd></div>
        <div><dt>会话数</dt><dd>{row.sessions ?? "—"}</dd></div>
        <div><dt>转化率</dt><dd>{row.conversion_rate === null ? "—" : `${(Number(row.conversion_rate) * 100).toFixed(2)}%`}</dd></div>
        <div><dt>退货数</dt><dd className={row.return_quantity === null ? styles.metricState : undefined}>{row.return_quantity ?? (row.return_status === "published" ? "暂无数据" : "报告未发布")}</dd></div>
      </dl>
    </section>}
    {!loading && !error && standalone && rows && <Suspense fallback={<p role="status">正在载入月内趋势…</p>}><PublishedMonthTrend currencyCode={currencyCode} reportDate={reportDate} rows={rows} /></Suspense>}
  </Container>;
}
export function PublishedDayPage({ currencyCode }: { currencyCode: string }) {
  const { reportDate = "" } = useParams();
  return <PublishedDay currencyCode={currencyCode} key={reportDate} reportDate={reportDate} />;
}
