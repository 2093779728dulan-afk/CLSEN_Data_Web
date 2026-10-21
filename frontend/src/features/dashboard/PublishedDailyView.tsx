import { ArrowRight, CalendarDays, CircleCheck, RefreshCw } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import type { DailyLedgerRow } from "../../api/generated";
import { Button, EmptyState, ErrorState, FormField, Input, PageHeader, Select, Skeleton, StatusBadge, Table, Tabs, type StatusTone } from "../../design-system";
import css from "./PublishedDailyView.module.css";

type Props = {
  month: string; range: { from: string; to: string }; currencyCode: string;
  canWrite: boolean; allowLegacyProducts: boolean; rows: DailyLedgerRow[]; totalRows: number;
  completeCount: number; incompleteCount: number; status: string; loading: boolean; error?: string;
  onMonthChange: (month: string) => void; onStatusChange: (status: string) => void;
  onTabChange: (tab: string) => void; onRetry: () => void; onReviewToday: () => void;
  onOpenDay: (destination: string) => void;
};
const statusLabels: Record<DailyLedgerRow["overall_status"], string> = { blocked: "阻断", complete: "完整发布", empty: "无数据", future: "未来日期", partial: "部分发布", review: "审核中" };
const tones: Record<DailyLedgerRow["overall_status"], StatusTone> = { blocked: "bad", complete: "good", empty: "quiet", future: "quiet", partial: "warn", review: "warn" };
const reportLabels: Record<DailyLedgerRow["business_status"], string> = { blocked: "阻断", draft: "草稿", failed: "失败", future: "未来", missing: "缺失", processing: "处理中", published: "已发布" };
const integer = (value: number | null) => value === null ? "—" : value.toLocaleString("zh-CN");

export function PublishedDailyView({ month, range, currencyCode, canWrite, allowLegacyProducts, rows, totalRows, completeCount, incompleteCount, status, loading, error, onMonthChange, onStatusChange, onTabChange, onRetry, onReviewToday, onOpenDay }: Props) {
  const location = useLocation();
  const orderedRows = [...rows].sort((left, right) => left.report_date.localeCompare(right.report_date));
  const integrity = loading ? "正在核对本月数据" : error ? "本月完整度暂不可用" : totalRows === 0 ? "本月暂无日期记录" : incompleteCount === 0 ? "本月无需补齐" : `${incompleteCount} 个日期待补齐`;
  const table = <>
    <section className={css.toolbar} aria-label="总表工具栏">
      <FormField label="状态"><Select aria-label="日期状态" value={status} onChange={event => onStatusChange(event.target.value)}>
        <option value="all">全部日期</option><option value="complete">完整发布</option><option value="partial">部分发布</option><option value="review">审核中</option><option value="blocked">阻断</option><option value="empty">无数据</option>
      </Select></FormField>
      <span aria-live="polite"><StatusBadge label={integrity} tone={loading || error || totalRows === 0 ? "quiet" : incompleteCount === 0 ? "good" : "warn"} /></span>
      <Link className={css.link} to={`/ledger/published-details?from=${range.from}&to=${range.to}`}>发布明细<ArrowRight aria-hidden="true" size={16} /></Link>
    </section>
    <section className={css.summary} aria-label="本月日期完整度">
      <div><span>本月日期记录</span><strong>{loading || error ? "—" : totalRows}<small> 日</small></strong></div>
      <div><span>完整发布</span><strong>{loading || error ? "—" : completeCount}<small> 日</small></strong></div>
      <div><span>待补齐日期</span><strong>{loading || error ? "—" : incompleteCount}<small> 日</small></strong></div>
      <p>完整度按本月全部记录统计，不随筛选变化。未来日期与完全无活动日期不计入待补齐；缺报以“—”显示，不能当作零。</p>
    </section>
    {error && <ErrorState title="总表读取失败" description={error} action={<Button icon={<RefreshCw />} onClick={onRetry}>重新读取</Button>} />}
    <section className={css.sheet} aria-busy={loading} aria-label="每日发布总表">
      {!error && <Table className={css.table} title="每日发布记录" description={loading ? "正在读取当前月范围…" : `显示 ${rows.length} / ${totalRows} 个日期 · 经营值来自当前发布版本 · 币种 ${currencyCode}`}>
        <thead><tr>{["报告日", "状态", "经营报告", "退货报告", "销售额", "订购数", "会话数", "转化率", "退货数", "待办"].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
        <tbody>{loading ? <tr><td colSpan={10}><div role="status" aria-label="正在读取每日发布总表"><Skeleton lines={8} height={32} /></div></td></tr> : orderedRows.map(row => {
          const destination = `${canWrite ? "/review" : "/published"}/${row.report_date}`;
          return <tr key={row.report_date} tabIndex={0} onClick={() => onOpenDay(destination)} onKeyDown={event => { if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onOpenDay(destination); } }}>
            <th scope="row" data-label="报告日"><time dateTime={row.report_date}>{row.report_date}</time></th>
            <td data-label="状态"><StatusBadge label={statusLabels[row.overall_status]} tone={tones[row.overall_status]} /></td>
            <td data-label="经营报告">{reportLabels[row.business_status]}</td><td data-label="退货报告">{reportLabels[row.return_status]}</td>
            <td data-label="销售额">{row.sales === null ? "—" : new Intl.NumberFormat("zh-CN", { currency: currencyCode, maximumFractionDigits: 2, style: "currency" }).format(Number(row.sales))}</td>
            <td data-label="订购数">{integer(row.units_ordered)}</td><td data-label="会话数">{integer(row.sessions)}</td>
            <td data-label="转化率">{row.conversion_rate === null ? "—" : `${(Number(row.conversion_rate) * 100).toFixed(2)}%`}</td><td data-label="退货数">{integer(row.return_quantity)}</td>
            <td data-label="待办" className={css.todo}>{row.pending_summary ? <span>{row.pending_summary}</span> : <span className={css.clear}><CircleCheck size={14} aria-hidden="true" />无需处理</span>}<Link className={css.link} to={destination} state={{ returnTo: location.pathname + location.search }} aria-label={`${canWrite ? "审核" : "查看"} ${row.report_date}`} onClick={event => event.stopPropagation()} onKeyDown={event => event.stopPropagation()}>{canWrite ? "进入审核" : "查看日期"}<ArrowRight size={14} aria-hidden="true" /></Link></td>
          </tr>;
        })}</tbody>
      </Table>}
      {!loading && !error && !rows.length && <EmptyState title="这个月份没有符合条件的日期记录" description={status !== "all" && totalRows > 0 ? "当前筛选未匹配到日期，清除状态筛选可查看本月其他记录。" : "未来日期和完全无活动的日期不会计入待补齐。"} action={status !== "all" ? <Button onClick={() => onStatusChange("all")}>清除状态筛选</Button> : undefined} />}
    </section>
  </>;
  return <main className={css.page} id="main-content">
    <PageHeader eyebrow="当前发布口径" title="发布数据总表" description="按月核对日期完整度与商品表现；表内经营值仅来自当前发布版本。" meta={<><time dateTime={month}>{month}</time><StatusBadge label={canWrite ? "数据管理视图" : "只读发布视图"} tone="quiet" /></>} actions={<><FormField label="查看月份"><Input aria-label="统计月份" type="month" value={month} onChange={event => onMonthChange(event.target.value)} /></FormField>{canWrite && <Button variant="primary" icon={<CalendarDays />} onClick={onReviewToday}>进入今日审核</Button>}</>} />
    <Tabs ariaLabel="发布总表类型" value="daily" onValueChange={onTabChange} items={[{ value: "daily", label: "每日总表", content: table }, ...(allowLegacyProducts ? [{ value: "products", label: "产品总表", content: null }] : [])]} />
  </main>;
}
