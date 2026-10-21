import type { ReactNode } from "react";
import { CalendarDays, FileSearch, RefreshCw } from "lucide-react";
import type { CalendarDay, CalendarDayStatus, CalendarEntry } from "../api/types";
import { Button, LinkButton, PageHeader, Spinner, StatusBadge, StatusMessage } from "../design-system";
import styles from "./AdvancedReviewWorkspaceView.module.css";

type ReportDay = { day: number; month: number; year: number };
const dayStates: Record<CalendarDayStatus, { label: string; mark: string }> = {
  red: { label: "需处理：阻断、导入失败或原文件异常", mark: "!" },
  yellow: { label: "审核中：草稿、警告或导入处理中", mark: "审" },
  blue: { label: "部分发布：仅一类报表已发布", mark: "单" },
  green: { label: "完整发布：两类报表均已发布", mark: "发" },
  gray: { label: "无数据", mark: "无" },
};
function dateOf(day: ReportDay) { return `${day.year}-${String(day.month).padStart(2, "0")}-${String(day.day).padStart(2, "0")}`; }
function dateLabel(day: ReportDay) { return `${day.year} 年 ${day.month} 月 ${day.day} 日`; }
function DailyEvidenceRail({ days, selected, known, onSelect }: { days: CalendarDay[]; selected: ReportDay; known: boolean; onSelect: (day: ReportDay) => void }) {
  const statuses = new Map(days.map(day => [day.report_date, day.status]));
  const count = new Date(selected.year, selected.month, 0).getDate();
  return <aside aria-label={`${selected.month} 月每日证据轨`} className={styles.rail} tabIndex={0}>
    <div className={styles.railHeading}><CalendarDays aria-hidden="true" /><div><strong>{selected.year} 年 {selected.month} 月</strong><span>每日审核状态</span></div></div>
    <ol className={styles.days}>{Array.from({ length: count }, (_, index) => index + 1).map(day => {
      const value = { ...selected, day }; const date = dateOf(value); const status = known ? statuses.get(date) ?? "gray" : undefined;
      const state = status ? dayStates[status] : { label: "状态待确认", mark: "—" };
      return <li key={date}><button aria-current={day === selected.day ? "date" : undefined} aria-label={`选择 ${selected.month} 月 ${day} 日，${state.label}`} className={`${styles.day}${status ? ` ${styles[status]}` : ""}`} onClick={() => onSelect(value)} type="button"><time dateTime={date}>{String(day).padStart(2, "0")}</time><span aria-hidden="true">{state.mark}</span></button></li>;
    })}</ol>
    <div aria-label="每日状态说明" className={styles.legend}>{Object.entries(dayStates).map(([status, state]) => <span key={status}><i aria-hidden="true" className={styles[status]} />{state.label.split("：")[0]}</span>)}</div>
    <p className={styles.railFoot}>每个报告日独立审核与发布</p>
  </aside>;
}

export type AdvancedReviewWorkspaceViewProps = {
  selected: ReportDay;
  calendarDays: CalendarDay[];
  entries: CalendarEntry[];
  calendarKnown: boolean;
  loading: boolean;
  error?: string;
  reportingTimezone: string;
  canWrite: boolean;
  activeVersionId?: number;
  onSelect: (day: ReportDay) => void;
  onSelectDraft: (entry: CalendarEntry) => void;
  onRetry: () => void;
  children?: ReactNode;
};

/** Date/report/version presentation shared by App and Storybook; commands remain in App/ImportReviewFlow. */
export function AdvancedReviewWorkspaceView({ selected, calendarDays, entries, calendarKnown, loading, error, reportingTimezone, canWrite, activeVersionId, onSelect, onSelectDraft, onRetry, children }: AdvancedReviewWorkspaceViewProps) {
  const selectedEntries = entries.filter(entry => entry.report_date === dateOf(selected));
  const drafts = selectedEntries.filter(entry => entry.status !== "published");
  return <div className={styles.layout}>
    <DailyEvidenceRail days={calendarDays} known={calendarKnown} onSelect={onSelect} selected={selected} />
    <main className={styles.main} id="main-content">
      <PageHeader eyebrow="日期审核" title="导入先审核，发布后才进入看板" description={<><strong>{dateLabel(selected)}</strong> · 选择报告类型，完成当前一步。</>} meta={<StatusBadge label="未发布数据不进入经营看板" tone="quiet" />} />
      <section aria-label="当前工作日" className={styles.docket}>
        <div className={styles.dateContext}><CalendarDays aria-hidden="true" /><div><strong>{dateLabel(selected)}</strong><span>站点报告日 · {reportingTimezone}</span></div></div>
        <ul className={styles.reports}>{(["business_report", "return_report"] as const).map(type => {
          const typed = selectedEntries.filter(entry => entry.report_type === type); const entry = typed.find(item => item.status !== "published") ?? typed[0]; const publication = typed.find(item => item.status === "published");
          const label = !calendarKnown ? "待确认" : entry?.status === "published" ? "已发布" : entry?.status === "ready_for_publish" ? "待发布" : entry ? "审核中" : "尚未导入";
          return <li key={type}><strong>{type === "business_report" ? "经营报告" : "退货报告"}</strong><StatusBadge label={label} tone={!calendarKnown || !entry ? "quiet" : entry.status === "published" ? "good" : "warn"} /><span>{calendarKnown && entry ? `版本 v${entry.version_no}` : "—"}{calendarKnown && publication && entry && publication.version_id !== entry.version_id ? ` · 当前发布 v${publication.version_no}` : ""}</span></li>;
        })}</ul>
      </section>
      {loading && <div aria-label="正在读取日期状态" className={styles.loading} role="status"><Spinner aria-hidden="true" />正在读取日期状态，审核内容保留。</div>}
      {!loading && error && <StatusMessage action={<Button className={styles.retry} icon={<RefreshCw />} onClick={onRetry} variant="secondary">重新读取日期状态</Button>} kind="danger" title="日期状态读取失败">{error} 当前报表状态尚未确认，请重试后核对。</StatusMessage>}
      <section aria-label="当前日期工作区" className={styles.flow}>
        <div className={styles.flowHeading}><div><p>当前日期工作区</p><h2>{calendarKnown && drafts.length ? "继续处理待审核报告" : calendarKnown ? "从原表开始新的审核" : "核对日期与活动草稿"}</h2></div><StatusBadge label="日期已隔离" tone="quiet" /></div>
        {canWrite && calendarKnown && drafts.length > 0 && <div aria-label="选择待审核报表" className={styles.switcher} role="group">{drafts.map(entry => <Button aria-pressed={entry.version_id === activeVersionId} key={entry.version_id} onClick={() => onSelectDraft(entry)} variant={entry.version_id === activeVersionId ? "primary" : "secondary"}>{entry.report_type === "business_report" ? "经营报告" : "退货报告"} · 草稿 v{entry.version_no}</Button>)}</div>}
        {canWrite ? children : <StatusMessage kind="info" title="此账号仅可查看已发布数据">查看人员不能进入导入、草稿或发布流程。</StatusMessage>}
      </section>
    </main>
  </div>;
}

export function SourceBatchReviewView({ batchId, children }: { batchId: number; children: ReactNode }) {
  return <main className={styles.main} id="main-content"><PageHeader eyebrow="指定来源" title="从指定文件重新审核" description={`正在处理批次 #${batchId} 的原始文件。核对预览后选择替换或合并，新草稿仍需审核发布。`} meta={<StatusBadge label={`来源批次 #${batchId}`} tone="quiet" />} /><StatusMessage kind="info" title="重新审核不会直接发布">原始文件与现有发布数据保留，生成的新草稿仍需完成审核与发布确认。</StatusMessage><section className={styles.sourceFlow}>{children}</section></main>;
}

export function ReviewWorkbenchReturnView({ target }: { target: string }) {
  return <nav aria-label="返回日期工作台" className={styles.returnNavigation}><LinkButton icon={<FileSearch />} to={target}>返回日期表格</LinkButton></nav>;
}
