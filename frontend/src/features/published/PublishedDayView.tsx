import type { ReactNode } from "react";
import { ArrowLeft, CalendarDays, RefreshCw, Table2 } from "lucide-react";
import type { DailyLedgerRow } from "../../api/generated";
import { Button, EmptyState, ErrorState, LinkButton, PageHeader, Skeleton, StatusBadge, type StatusTone } from "../../design-system";
import css from "./PublishedDayView.module.css";

type Props = { currencyCode: string; reportDate: string; standalone: boolean; returnTo?: string; row?: DailyLedgerRow; error?: string; loading: boolean; onRetry: () => void; children?: ReactNode };
const reportLabels: Record<DailyLedgerRow["business_status"], string> = { blocked: "阻断", draft: "草稿", failed: "失败", future: "未来日期", missing: "未发布", processing: "处理中", published: "已发布" };
function reportTone(status: DailyLedgerRow["business_status"]): StatusTone { return status === "published" ? "good" : status === "blocked" || status === "failed" ? "bad" : status === "missing" || status === "future" ? "quiet" : "warn"; }

export function PublishedDayView({ currencyCode, reportDate, standalone, returnTo, row, error, loading, onRetry, children }: Props) {
  const Container = standalone ? "main" : "section";
  return <Container id={standalone ? "main-content" : undefined} aria-label="单日只读发布详情" className={css.page}>
    <PageHeader eyebrow="当前发布版本 · 只读" title={reportDate} description="这里只展示当前发布版本，不包含草稿、失败导入或历史版本。" meta={<StatusBadge tone="quiet" label={`报告币种 ${currencyCode}`} />} actions={<nav aria-label="发布数据导航" className={css.links}>
      {returnTo && <LinkButton icon={<ArrowLeft />} to={returnTo}>返回发布明细</LinkButton>}
      <LinkButton icon={<CalendarDays />} to={`/?month=${reportDate.slice(0, 7)}`} variant="quiet">返回每日总表</LinkButton>
      <LinkButton icon={<Table2 />} to={`/ledger/published-details?from=${reportDate}&to=${reportDate}&mode=rows`} variant="primary">查看当日原始明细</LinkButton>
    </nav>} />
    {loading && <div className={css.loading} role="status" aria-label="正在读取当前发布数据"><p>正在读取当前发布数据…</p><Skeleton lines={3} height={40} /></div>}
    {error && <ErrorState title="已发布数据读取失败" description={error} action={<Button icon={<RefreshCw />} onClick={onRetry}>重新读取</Button>} />}
    {!loading && !error && !row && <EmptyState title="这个日期没有发布数据" description="可以返回每日总表选择其他日期。" />}
    {!loading && !error && row && <section aria-label="当前发布指标" className={css.summary}>
      <header className={css.summaryHeader}><div><h2>{row.overall_status === "complete" ? "两类报告均已发布" : "当前发布数据"}</h2><p>{row.pending_summary ?? "无需处理"}</p></div><time dateTime={reportDate}>{reportDate}</time></header>
      <div className={css.sources} aria-label="报告发布状态">
        <div><span>经营报告</span><StatusBadge label={reportLabels[row.business_status]} tone={reportTone(row.business_status)} /></div>
        <div><span>退货报告</span><StatusBadge label={reportLabels[row.return_status]} tone={reportTone(row.return_status)} /></div>
      </div>
      <dl className={css.metrics}>
        <div><dt>销售额</dt><dd>{row.sales === null ? "—" : new Intl.NumberFormat("zh-CN", { currency: currencyCode, style: "currency" }).format(Number(row.sales))}</dd></div>
        <div><dt>订购数</dt><dd>{row.units_ordered ?? "—"}</dd></div>
        <div><dt>会话数</dt><dd>{row.sessions ?? "—"}</dd></div>
        <div><dt>转化率</dt><dd>{row.conversion_rate === null ? "—" : `${(Number(row.conversion_rate) * 100).toFixed(2)}%`}</dd></div>
        <div><dt>退货数</dt><dd className={row.return_quantity === null ? css.metricState : undefined}>{row.return_quantity ?? (row.return_status === "published" ? "暂无数据" : "报告未发布")}</dd></div>
      </dl>
      <p className={css.note}>这是所选报告日的发布读数。缺报或缺值不会补成零；月内累计与单日指标分别展示。</p>
    </section>}
    {children}
  </Container>;
}
