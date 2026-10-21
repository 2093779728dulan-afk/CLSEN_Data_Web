import type { FormEvent, ReactNode } from "react";
import { ArrowLeft, Search } from "lucide-react";
import type { ReportType } from "../../api/generated";
import { Button, FormField, Input, LinkButton, PageHeader, StatusBadge, Tabs } from "../../design-system";
import type { PublishedDetailsMode } from "./publishedDetailsTypes";
import css from "./PublishedDetailLedgerView.module.css";

export type PublishedDetailLedgerViewProps = {
  siteId: number; displayName: string; reportingTimezone: string;
  reportType: ReportType; mode: PublishedDetailsMode;
  range: { from_date: string; to_date: string };
  dateDraft: { from: string; to: string }; dateError?: string;
  searchDraft: string; resolvingRange: boolean; stagedReason?: string; conflictNotice?: string;
  count?: number; children: ReactNode; rangeError?: ReactNode;
  onReportType: (value: ReportType) => void; onMode: (value: PublishedDetailsMode) => void;
  onDateDraft: (value: { from: string; to: string }) => void;
  onApplyDates: (event: FormEvent) => void; onSearchDraft: (value: string) => void;
  onSearch: (event: FormEvent) => void; onQuickRange: (value: 7 | 30 | "month" | "all") => void;
};

export function PublishedDetailLedgerView(props: PublishedDetailLedgerViewProps) {
  const { siteId, displayName, reportingTimezone, reportType, mode, range, dateDraft, dateError, searchDraft, resolvingRange, stagedReason, conflictNotice, count, children, rangeError } = props;
  const results = <section className={css.results} id="published-ledger-results" aria-label={mode === "summary" ? "按日期摘要结果" : "全部明细结果"}>
    <header className={css.resultsHeader}><div><p>当前发布快照</p><h2>{mode === "summary" ? "按日期摘要" : "全部明细"}</h2></div>{count !== undefined && <StatusBadge tone="quiet" label={`${count.toLocaleString("zh-CN")} ${mode === "rows" ? "行" : "个发布日期"}`} />}</header>
    {children}
  </section>;
  const content = <>
    <section className={css.filters} aria-label="已发布明细筛选">
      <form className={css.dateForm} onSubmit={props.onApplyDates}>
        <FormField label="开始日期"><Input aria-label="开始日期" aria-invalid={Boolean(dateError)} type="date" value={dateDraft.from} onChange={event => props.onDateDraft({ ...dateDraft, from: event.target.value })} /></FormField>
        <FormField label="结束日期"><Input aria-label="结束日期" aria-invalid={Boolean(dateError)} type="date" value={dateDraft.to} onChange={event => props.onDateDraft({ ...dateDraft, to: event.target.value })} /></FormField>
        <Button type="submit">应用日期范围</Button>
      </form>
      <div className={css.quickRanges} role="group" aria-label="快捷日期范围">
        <Button variant="quiet" onClick={() => props.onQuickRange(7)}>7 天</Button><Button variant="quiet" onClick={() => props.onQuickRange(30)}>30 天</Button><Button variant="quiet" onClick={() => props.onQuickRange("month")}>本月</Button><Button variant="quiet" disabled={resolvingRange} onClick={() => props.onQuickRange("all")}>全部已发布</Button>
      </div>
      <form className={css.searchForm} onSubmit={props.onSearch}>
        <FormField label="搜索原始字段或报告日期"><Input aria-label="搜索已发布原始字段和报告日期" type="search" maxLength={200} placeholder="原始字段或 YYYY-MM-DD" value={searchDraft} onChange={event => props.onSearchDraft(event.target.value.slice(0, 200))} /></FormField>
        <Button type="submit" icon={<Search />}>搜索</Button>
      </form>
      {stagedReason && <div className={css.staged}><div><Button disabled aria-describedby="published-ledger-stage-reason">列设置</Button><Button disabled aria-describedby="published-ledger-stage-reason">导出 CSV</Button></div><p id="published-ledger-stage-reason">{stagedReason}</p></div>}
      {dateError && <p className={css.error} role="alert">{dateError}</p>}
      {rangeError}
    </section>
    {conflictNotice && <p className={css.notice} role="status" aria-live="assertive">{conflictNotice}</p>}
    <Tabs ariaLabel="查看方式" value={mode} onValueChange={value => props.onMode(value === "rows" ? "rows" : "summary")} items={[{ value: "summary", label: "按日期摘要", content: results }, { value: "rows", label: "全部明细", content: results }]} />
  </>;
  return <main className={css.page} data-site-id={siteId} id="main-content">
    <PageHeader eyebrow="已发布明细台账 · 只读" title="跨日期已发布明细" description="比较选定范围内每天的当前发布快照，并在原范围内展开一个日期。" actions={<LinkButton to={`/?month=${range.from_date.slice(0, 7)}`} icon={<ArrowLeft />}>发布数据总表</LinkButton>} />
    <dl className={css.scope}><div><dt>当前范围</dt><dd>{range.from_date} — {range.to_date}</dd></div><div><dt>报告口径</dt><dd>{reportType === "business_report" ? "经营报告原始明细" : "退货报告原始明细"}</dd></div><div><dt>读取身份</dt><dd>{displayName} · 只读</dd></div><div><dt>报告时区</dt><dd>{reportingTimezone}</dd></div></dl>
    <Tabs ariaLabel="报表类型" value={reportType} onValueChange={value => props.onReportType(value === "return_report" ? "return_report" : "business_report")} items={[{ value: "business_report", label: "经营明细", content }, { value: "return_report", label: "退货明细", content }]} />
  </main>;
}
