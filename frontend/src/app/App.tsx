import surfaceCss from "../features/import-review/ReviewSurfaces.module.css";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { LogOut, Menu, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  ApiRequestError,
  issueLoginCsrfToken,
  requestApi,
  setSessionCsrfToken,
  writeApi,
} from "../api/client";
import { closeSessionBoundary, establishSessionBoundary } from "../api/sessionRevocation";
import type { CalendarDay, CalendarEntry, CalendarDayStatus, Principal, ReportType } from "../api/types";
import { Button, ErrorState, FormField, Input, LinkButton, Skeleton, StatusMessage } from "../design-system";
import { AdminConsole } from "../features/admin/AdminConsole";
import { BatchReviewPage } from "../features/batch-review/BatchReviewPage";
import { CatalogNavigationProvider } from "../features/catalog/CatalogNavigationContext";
import { CatalogMaintenancePage } from "../features/catalog/CatalogMaintenancePage";
import { CatalogHomePage } from "../features/catalog/CatalogHomePage";
import { CatalogImportPage } from "../features/catalog/CatalogImportPage";
import { CatalogLayout } from "../features/catalog/CatalogLayout";
import { CatalogStylePage } from "../features/catalog/CatalogStylePage";
import { CatalogUnmatchedPage } from "../features/catalog/CatalogUnmatchedPage";
import { CatalogVersionsPage } from "../features/catalog/CatalogVersionsPage";
import { PublishedDashboard } from "../features/dashboard/PublishedDashboard";
import { ImportReviewFlow } from "../features/import-review/ImportReviewFlow";
import { clearReviewRecoveryForIdentity } from "../features/import-review/reviewRecovery";
import type { ReviewLocationHandoff } from "../features/import-review/workflowTypes";
import { PublishedDayPage } from "../features/published/PublishedDayPage";
import { PublishedDetailLedgerPage } from "../features/published-details/PublishedDetailLedgerPage";
import { ProductLedgerPage } from "../features/products/ProductLedgerPage";
import { ProductDetailPage } from "../features/products/ProductDetailPage";
import { PRODUCT_ANALYTICS_SOURCE, productAnalyticsBundleMarker } from "../features/products/productAnalyticsSource";
import { DateWorkbenchPage } from "../features/workbench/DateWorkbenchPage";
import { VersionHistory } from "../features/versions/VersionHistory";
import { AuthzGenerationProvider } from "./AuthzGenerationContext";
import styles from "./AppShell.module.css";

type ReportDay = { day: number; month: number; year: number };

type SiteContext = {
  site_id: number;
  site_code: string;
  display_name: string;
  site_config_version_id: number;
  source_timezone: string;
  reporting_timezone: string;
  currency_code: string;
};

type ReviewFocus = {
  epoch: number;
  reportDate: string;
  reportType?: ReportType;
  resolved: boolean;
  versionId?: number;
};

type ReviewFocusRequest = Omit<ReviewFocus, "epoch">;

const SIDEBAR_COLLAPSED_KEY = "clsen.workspace.sidebar-collapsed";

function savedSidebarCollapsed() {
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
  } catch {
    return false;
  }
}

function currentReportDay(timeZone: string, now = new Date()): ReportDay {
  const parts = new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "numeric",
    timeZone,
    year: "numeric",
  }).formatToParts(now);
  const get = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((part) => part.type === type)?.value);
  return { day: get("day"), month: get("month"), year: get("year") };
}

function isoDate(day: ReportDay) {
  return `${day.year}-${String(day.month).padStart(2, "0")}-${String(day.day).padStart(2, "0")}`;
}

function reportDayFromIso(value: string): ReportDay {
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) throw new Error("报告日期格式无效。");
  return { year, month, day };
}

function fullDate(day: ReportDay) {
  return `${day.year} 年 ${day.month} 月 ${day.day} 日`;
}

function monthRange(day: ReportDay) {
  const last = new Date(day.year, day.month, 0).getDate();
  return { from: `${day.year}-${String(day.month).padStart(2, "0")}-01`, to: `${day.year}-${String(day.month).padStart(2, "0")}-${last}` };
}

function AppShell({ children, principal, siteContext, online, logoutBusy, logoutError, onLogout }: { children: React.ReactNode; principal: Principal; siteContext: SiteContext; online: boolean; logoutBusy: boolean; logoutError?: string; onLogout: () => void }) {
  const location = useLocation();
  const isAdmin = principal.roles.includes("admin");
  const canWrite = isAdmin || principal.roles.includes("data_manager");
  const today = isoDate(currentReportDay(siteContext.reporting_timezone));
  const [sidebarCollapsed, setSidebarCollapsed] = useState(savedSidebarCollapsed);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const mobileNavigationToggle = useRef<HTMLButtonElement>(null);
  const previousNavigationPath = useRef(location.pathname);
  useEffect(() => {
    if (previousNavigationPath.current === location.pathname) return;
    previousNavigationPath.current = location.pathname;
    setNavigationOpen(false);
  }, [location.pathname]);
  useEffect(() => {
    if (!navigationOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setNavigationOpen(false);
      mobileNavigationToggle.current?.focus();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [navigationOpen]);
  const toggleSidebar = () => {
    setSidebarCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      } catch {
        // The shell remains usable when browser storage is unavailable.
      }
      return next;
    });
  };
  const navLinkClass = ({ isActive }: { isActive: boolean }) => `${styles.navigationLink}${isActive ? ` ${styles.navigationLinkActive}` : ""}`;
  return <>
    <a className={styles.skipLink} href="#main-content">跳到主要内容</a>
    <div className={`app-shell ${styles.shell}${sidebarCollapsed ? ` ${styles.shellCollapsed}` : ""}${navigationOpen ? ` ${styles.navigationOpen}` : ""}`} data-product-analytics-source={productAnalyticsBundleMarker()} data-sidebar-collapsed={sidebarCollapsed || undefined}>
      <aside aria-label="主导航" className={styles.sidebar}>
        <div className={styles.brand}><span className={styles.brandMonogram}>CL</span><span className={styles.brandIdentity}><strong>CLSEN</strong><small>每日数据核验台</small></span><button aria-expanded={!sidebarCollapsed} aria-label={sidebarCollapsed ? "展开侧栏" : "收起侧栏"} className={styles.desktopSidebarToggle} onClick={toggleSidebar} title={sidebarCollapsed ? "展开侧栏" : "收起侧栏"} type="button">{sidebarCollapsed ? <PanelLeftOpen aria-hidden="true" /> : <PanelLeftClose aria-hidden="true" />}</button><button aria-controls="primary-navigation" aria-expanded={navigationOpen} aria-label={navigationOpen ? "关闭主导航" : "打开主导航"} className={styles.mobileNavigationToggle} onClick={() => setNavigationOpen((current) => !current)} ref={mobileNavigationToggle} type="button">{navigationOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}</button></div>
        <nav aria-label="工作区" className={styles.navigation} id="primary-navigation">
          <NavLink className={navLinkClass} end title={sidebarCollapsed ? "发布总表" : undefined} to="/"><span className={styles.navigationMark}>表</span><span className={styles.navigationLabel}>发布总表</span></NavLink>
          <NavLink className={navLinkClass} title={sidebarCollapsed ? "商品主档" : undefined} to="/catalog"><span className={styles.navigationMark}>品</span><span className={styles.navigationLabel}>商品主档</span></NavLink>
          {PRODUCT_ANALYTICS_SOURCE === "p0_catalog" && <NavLink className={navLinkClass} title={sidebarCollapsed ? "产品分析" : undefined} to="/products"><span className={styles.navigationMark}>析</span><span className={styles.navigationLabel}>产品分析</span></NavLink>}
          {canWrite && <NavLink className={navLinkClass} title={sidebarCollapsed ? "数据审核" : undefined} to={`/review/${today}`}><span className={styles.navigationMark}>审</span><span className={styles.navigationLabel}>数据审核</span></NavLink>}
          <NavLink className={navLinkClass} title={sidebarCollapsed ? "版本记录" : undefined} to="/versions"><span className={styles.navigationMark}>版</span><span className={styles.navigationLabel}>版本记录</span></NavLink>
          {isAdmin && <NavLink className={navLinkClass} title={sidebarCollapsed ? "管理员控制台" : undefined} to="/admin"><span className={styles.navigationMark}>管</span><span className={styles.navigationLabel}>管理员控制台</span></NavLink>}
        </nav>
        <div className={styles.boundary}><span className={styles.boundaryLabel}>数据边界</span><strong>{siteContext.display_name}</strong><span>报告日按站点时区隔离</span></div>
        <div className={styles.connectionState}><span aria-hidden="true" className={styles.avatar}>{principal.display_name.slice(0, 1).toUpperCase()}</span><span className={styles.connectionIdentity}><strong>{principal.display_name}</strong><small aria-live="polite"><i aria-hidden="true" className={`${styles.connectionSignal}${online ? ` ${styles.connectionSignalLive}` : ""}`} />{online ? "已连接 API" : "API 不可用"}<span> · {principal.roles.join(" / ")}</span></small></span><Button aria-label={logoutBusy ? "退出中" : "退出"} className={styles.logoutButton} disabled={logoutBusy} icon={<LogOut />} loading={logoutBusy} onClick={onLogout} title="退出登录" variant="quiet">退出</Button></div>
      </aside>
      <div className={styles.workspace}><header className={styles.topbar}><div className={styles.topbarContext}><span>当前工作区</span><p><strong>{siteContext.display_name}</strong><i aria-hidden="true" /><span>每日数据</span></p></div><div className={styles.topbarMeta}><span className={styles.environmentTag}>LOCAL</span><span className={`topbar__timezone ${styles.topbarTimezone}`}><small>报告时区</small><strong>{siteContext.reporting_timezone}</strong></span></div></header>{logoutError && <div className={styles.sessionError}><StatusMessage action={<Button disabled={logoutBusy} loading={logoutBusy} onClick={onLogout} variant="secondary">重试退出</Button>} kind="danger" title="退出没有完成">{logoutError}</StatusMessage></div>}{children}</div>
    </div>
  </>;
}

function LoginPage({ onLogin }: { onLogin: (principal: Principal) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(undefined);
    try {
      const token = await issueLoginCsrfToken();
      const payload = await requestApi<{ user: Principal; csrf_token: string }>("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": token }, body: JSON.stringify({ username, password }) });
      setSessionCsrfToken(payload.csrf_token);
      onLogin(payload.user);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法登录。"); } finally { setBusy(false); }
  };
  return <main className={styles.loginPage} id="main-content"><section aria-labelledby="login-title" className={styles.loginCard}><div className={styles.loginBrand}><span aria-hidden="true">CL</span><p>CLSEN · REVIEW ACCESS</p></div><h1 id="login-title">从原表开始，确认后再发布。</h1><p className={styles.loginIntroduction}>使用你的系统账号进入每日数据审核与已发布看板。</p><form className={styles.loginForm} onSubmit={(event) => { void submit(event); }}><FormField label="账号" required><Input autoComplete="username" onChange={(event) => setUsername(event.target.value)} required value={username} /></FormField><FormField label="密码" required><Input autoComplete="current-password" onChange={(event) => setPassword(event.target.value)} required type="password" value={password} /></FormField>{error && <StatusMessage kind="danger" title="无法登录">{error}</StatusMessage>}<Button loading={busy} type="submit" variant="primary">登录工作台</Button></form></section></main>;
}

function AppLoadingState({ message }: { message: string }) {
  return <main aria-live="polite" className={styles.loginPage} id="main-content"><section className={`${styles.loginCard} ${styles.loadingCard}`}><div className={styles.loginBrand}><span aria-hidden="true">CL</span><p>CLSEN · DATA REVIEW</p></div><h1>{message}</h1><Skeleton lines={3} /></section></main>;
}

const CALENDAR_DAY_PRESENTATION: Record<CalendarDayStatus, { label: string; mark: string }> = {
  red: { label: "需处理：阻断、导入失败或原文件异常", mark: "!" },
  yellow: { label: "审核中：草稿、警告或导入处理中", mark: "审" },
  blue: { label: "部分发布：仅一类报表已发布", mark: "单" },
  green: { label: "完整发布：两类报表均已发布", mark: "发" },
  gray: { label: "无数据", mark: "无" },
};

function DayRail({ days, selected, onSelect }: { days: CalendarDay[]; selected: ReportDay; onSelect: (day: ReportDay) => void }) {
  const statuses = useMemo(() => new Map(days.map((day) => [day.report_date, day.status])), [days]);
  const count = new Date(selected.year, selected.month, 0).getDate();
  return <aside aria-label={`${selected.month} 月每日证据轨`} className={surfaceCss["evidence-rail"]}><div className={surfaceCss["evidence-rail__heading"]}><span className={surfaceCss["evidence-rail__month"]}>{String(selected.year).slice(2)}.{String(selected.month).padStart(2, "0")}</span><span className={surfaceCss["evidence-rail__label"]}>每日证据</span></div><ol className={surfaceCss["evidence-list"]}>{Array.from({ length: count }, (_, index) => index + 1).map((day) => { const value = { ...selected, day }; const date = isoDate(value); const status = statuses.get(date) ?? "gray"; const presentation = CALENDAR_DAY_PRESENTATION[status]; return <li key={day}><button aria-current={day === selected.day ? "date" : undefined} aria-label={`选择 ${selected.month} 月 ${day} 日，${presentation.label}`} className={surfaceCss["evidence-day"] + " " + (surfaceCss[`evidence-day--${status}`] ?? "")} onClick={() => onSelect(value)} type="button"><time dateTime={date}>{String(day).padStart(2, "0")}</time><span className={surfaceCss["evidence-day__line"]} /><span className={surfaceCss["evidence-day__status"]}>{presentation.mark}</span></button></li>; })}</ol><p className={surfaceCss["evidence-rail__foot"]}><span className="status-dot" />每日隔离 · 红黄蓝绿灰</p></aside>;
}

function ReviewPage({
  focus,
  onBatchReviewCreated,
  onFlowLocationChanged,
  onResolveFocus,
  onSelect,
  principal,
  reportingTimezone,
  selected,
  siteId,
}: {
  focus: ReviewFocus;
  onBatchReviewCreated: (runId: number) => void;
  onFlowLocationChanged: (handoff: ReviewLocationHandoff) => void;
  onResolveFocus: (request: ReviewFocusRequest & { epoch: number }) => void;
  onSelect: (request: ReviewFocusRequest) => void;
  principal: Principal;
  reportingTimezone: string;
  selected: ReportDay;
  siteId: number;
}) {
  const [entries, setEntries] = useState<CalendarEntry[]>([]);
  const [calendarDays, setCalendarDays] = useState<CalendarDay[]>([]);
  const [loadedRange, setLoadedRange] = useState<string>();
  const [calendarRefreshEpoch, setCalendarRefreshEpoch] = useState(0);
  const [error, setError] = useState<string>();
  const reloadSequence = useRef(0);
  const range = monthRange(selected);
  const rangeKey = `${range.from}:${range.to}`;
  const selectedDate = isoDate(selected);

  const reload = useCallback(async () => {
    const sequence = reloadSequence.current + 1;
    reloadSequence.current = sequence;
    setLoadedRange(undefined);
    try {
      const [nextEntries, nextDays] = await Promise.all([
        requestApi<CalendarEntry[]>(`/api/data-calendar?from=${range.from}&to=${range.to}`),
        requestApi<CalendarDay[]>(`/api/data-calendar/days?from=${range.from}&to=${range.to}`),
      ]);
      if (reloadSequence.current !== sequence) return;
      setEntries(nextEntries);
      setCalendarDays(nextDays);
      setLoadedRange(rangeKey);
      setError(undefined);
    } catch (reason) {
      if (reloadSequence.current !== sequence) return;
      setError(reason instanceof Error ? reason.message : "无法读取数据日历。");
    }
  }, [range.from, range.to, rangeKey]);

  useEffect(() => {
    void reload();
  }, [calendarRefreshEpoch, reload]);

  const selectedEntries = entries.filter((entry) => entry.report_date === selectedDate);
  const draftEntries = selectedEntries.filter((entry) => entry.status !== "published");

  useEffect(() => {
    if (
      focus.resolved
      || focus.reportDate !== selectedDate
      || loadedRange !== rangeKey
    ) return;
    const preferredVersion = focus.versionId
      ? draftEntries.find((entry) => entry.version_id === focus.versionId)
      : undefined;
    const preferredDraft = focus.reportType
      ? draftEntries.find((entry) => entry.report_type === focus.reportType)
      : undefined;
    const activeDraft = preferredVersion ?? (focus.reportType ? preferredDraft : draftEntries[0]);
    onResolveFocus({
      epoch: focus.epoch,
      reportDate: selectedDate,
      reportType: activeDraft?.report_type ?? focus.reportType,
      resolved: true,
      versionId: activeDraft?.version_id,
    });
  }, [
    draftEntries,
    focus.epoch,
    focus.reportDate,
    focus.reportType,
    focus.resolved,
    focus.versionId,
    loadedRange,
    onResolveFocus,
    rangeKey,
    selectedDate,
  ]);

  const focusReady = focus.resolved && focus.reportDate === selectedDate;
  const activeVersionId = focusReady ? focus.versionId : undefined;
  const canWrite = principal.roles.includes("admin") || principal.roles.includes("data_manager");

  const selectDay = (day: ReportDay) => {
    const reportDate = isoDate(day);
    const rangeIsCurrent = loadedRange === rangeKey;
    const activeDraft = rangeIsCurrent
      ? entries.find((entry) => (
        entry.report_date === reportDate && entry.status !== "published"
      ))
      : undefined;
    onSelect({
      reportDate,
      reportType: activeDraft?.report_type,
      resolved: rangeIsCurrent,
      versionId: activeDraft?.version_id,
    });
  };

  const changeReportDraft = (entry: CalendarEntry) => {
    if (entry.version_id === activeVersionId) return;
    onSelect({
      reportDate: selectedDate,
      reportType: entry.report_type,
      resolved: true,
      versionId: entry.version_id,
    });
  };

  const flowLocationChanged = (handoff: ReviewLocationHandoff) => {
    setLoadedRange(undefined);
    onFlowLocationChanged(handoff);
    setCalendarRefreshEpoch((current) => current + 1);
  };

  return <div className={surfaceCss["review-layout"]}><DayRail days={calendarDays} onSelect={selectDay} selected={selected} /><main className="main-content" id="main-content"><header className={surfaceCss["review-command-bar"]}><div><p className="eyebrow"><span>DAILY REVIEW</span><span className="eyebrow__rule" /><span>每日核验工作台</span></p><h1>导入先审核，发布后才进入看板</h1><p><strong>{fullDate(selected)}</strong> · 选择报告类型，完成当前一步。</p><p className={surfaceCss["review-command-bar__boundary"]}>未发布数据不会出现在经营看板</p></div><section className={surfaceCss["day-docket"]}><div className={surfaceCss["day-docket__heading"]}><p>当前工作日</p><span>REPORT DATE</span></div><h2>{fullDate(selected)}</h2><p className={surfaceCss["day-docket__timezone"]}>站点报告日 · {reportingTimezone}</p><ul className={surfaceCss["report-status-list"]}>{(["business_report", "return_report"] as const).map((type) => { const typedEntries = selectedEntries.filter((item) => item.report_type === type); const entry = typedEntries.find((item) => item.status !== "published") ?? typedEntries[0]; const publication = typedEntries.find((item) => item.status === "published"); const state = entry ? `${entry.status} · v${entry.version_no}${publication && publication.version_id !== entry.version_id ? ` · 当前发布 v${publication.version_no}` : ""}` : "尚未导入"; return <li className={surfaceCss["report-status"]} key={type}><span className={surfaceCss["report-status__index"] + " " + (surfaceCss[`report-status__index--${entry?.status ?? "empty"}`] ?? "")} /><span><strong>{type === "business_report" ? "经营报告" : "退货报告"}</strong><small>{type === "business_report" ? "Business report" : "Return report"}</small></span><span className={surfaceCss["report-status__state"]}>{state}</span></li>; })}</ul></section></header>{error && <p className="form-error" role="alert">{error}</p>}<section className={surfaceCss["review-route"]}><div className="section-heading"><div><p className="section-kicker">当前日期工作区</p><h2>{draftEntries.length ? "继续处理待审核报告" : "从原表开始新的审核"}</h2></div><p>日期已隔离</p></div>{canWrite && draftEntries.length > 0 && <div aria-label="选择待审核报表" className={surfaceCss["draft-report-switcher"]} role="group">{draftEntries.map((entry) => <button aria-pressed={entry.version_id === activeVersionId} className={entry.version_id === activeVersionId ? surfaceCss["draft-report-switcher__button"] + " " + surfaceCss["draft-report-switcher__button--active"] : surfaceCss["draft-report-switcher__button"]} key={entry.version_id} onClick={() => changeReportDraft(entry)} type="button"><strong>{entry.report_type === "business_report" ? "经营报告" : "退货报告"}</strong><span>草稿 v{entry.version_no}</span></button>)}</div>}{canWrite ? focusReady ? <ImportReviewFlow canFinalizePublishedMove={principal.roles.includes("admin")} canForceRebuild={principal.roles.includes("admin")} initialReportType={focus.reportType} initialVersionId={focus.versionId} key={`review-focus:${focus.epoch}`} onBatchReviewCreated={onBatchReviewCreated} onPublished={() => setCalendarRefreshEpoch((current) => current + 1)} onReportDateChanged={flowLocationChanged} operator={principal} reportDate={selectedDate} siteId={siteId} userId={principal.id} /> : !error && <p className="workspace-loading">正在确认这个日期的活动草稿…</p> : <p className="viewer-boundary">查看人员只能读取已发布数据，不能进入导入、草稿或发布流程。</p>}</section></main></div>;
}

function ReviewRoutePage({
  focus,
  onBatchReviewCreated,
  onFlowLocationChanged,
  onResolveFocus,
  onSelect,
  principal,
  reportingTimezone,
  siteId,
}: {
  focus: ReviewFocus;
  onBatchReviewCreated: (runId: number) => void;
  onFlowLocationChanged: (handoff: ReviewLocationHandoff) => void;
  onResolveFocus: (request: ReviewFocusRequest & { epoch: number }) => void;
  onSelect: (request: ReviewFocusRequest) => void;
  principal: Principal;
  reportingTimezone: string;
  siteId: number;
}) {
  const { reportDate = "" } = useParams();
  const [searchParams] = useSearchParams();
  const requestedType = searchParams.get("report_type");
  const requestedBatchId = Number(searchParams.get("batch_id"));
  const sourceBatchId = Number.isSafeInteger(requestedBatchId) && requestedBatchId > 0 ? requestedBatchId : undefined;
  const routeReportType: ReportType | undefined = requestedType === "business_report" || requestedType === "return_report" ? requestedType : undefined;
  const requestedVersionId = Number(searchParams.get("version_id"));
  const routeVersionId = Number.isSafeInteger(requestedVersionId) && requestedVersionId > 0 ? requestedVersionId : undefined;
  const valid = /^\d{4}-\d{2}-\d{2}$/.test(reportDate);
  const routeInitialized = useRef(false);
  const routeIdentity = `${reportDate}:${routeReportType ?? ""}:${routeVersionId ?? ""}`;
  const previousRouteIdentity = useRef(routeIdentity);
  const routeChanged = routeInitialized.current && previousRouteIdentity.current !== routeIdentity;
  const routeIsAuthoritative = !routeInitialized.current || routeChanged;
  const routeFocusDiffers = focus.reportDate !== reportDate
    || (routeReportType !== undefined && focus.reportType !== routeReportType)
    || (routeVersionId !== undefined && focus.versionId !== routeVersionId);
  useEffect(() => {
    if (!sourceBatchId && valid && routeFocusDiffers && routeIsAuthoritative) {
      onSelect({ reportDate, reportType: routeReportType, resolved: false, versionId: routeVersionId });
    }
    routeInitialized.current = true;
    previousRouteIdentity.current = routeIdentity;
  }, [onSelect, reportDate, routeFocusDiffers, routeIdentity, routeIsAuthoritative, routeReportType, routeVersionId, sourceBatchId, valid]);
  if (!valid) return <Navigate replace to="/" />;
  if (sourceBatchId && (principal.roles.includes("admin") || principal.roles.includes("data_manager"))) {
    return <main className="main-content" id="main-content"><h1>从指定文件重新审核</h1><p>正在处理批次 #{sourceBatchId} 的原始文件。核对预览后选择替换或合并，新草稿仍需审核发布。</p><ImportReviewFlow key={`source:${siteId}:${principal.id}:${sourceBatchId}`} initialBatchId={sourceBatchId} canForceRebuild={principal.roles.includes("admin")} canFinalizePublishedMove={principal.roles.includes("admin")} onBatchReviewCreated={onBatchReviewCreated} onPublished={() => undefined} operator={principal} reportDate={reportDate} siteId={siteId} userId={principal.id} /></main>;
  }
  if (routeFocusDiffers && routeIsAuthoritative) {
    return <main className="main-content" id="main-content"><p className="workspace-loading">正在进入日期审核…</p></main>;
  }
  return <ReviewPage focus={focus} onBatchReviewCreated={onBatchReviewCreated} onFlowLocationChanged={onFlowLocationChanged} onResolveFocus={onResolveFocus} onSelect={onSelect} principal={principal} reportingTimezone={reportingTimezone} selected={reportDayFromIso(focus.reportDate)} siteId={siteId} />;
}

function ReviewWorkbenchReturn() {
  const location = useLocation();
  const { reportDate = "" } = useParams();
  const [parameters] = useSearchParams();
  const previous = (location.state as { workbenchReturn?: string } | null)?.workbenchReturn;
  const target = previous && /^\/(?:review|published)\/\d{4}-\d{2}-\d{2}(?:\?|$)/.test(previous) ? previous : `/review/${reportDate}?report_type=${parameters.get("report_type") === "return_report" ? "return_report" : "business_report"}`;
  return <nav aria-label="返回日期工作台" style={{ padding: "16px 24px" }}><LinkButton to={target}>返回日期表格</LinkButton></nav>;
}

function ViewerReviewRedirect() {
  const { reportDate = "" } = useParams();
  return <Navigate replace to={`/published/${reportDate}`} />;
}

function DateWorkbenchRoute({ canWrite, siteId, userId }: { canWrite: boolean; siteId: number; userId: number }) {
  const { reportDate = "" } = useParams();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(reportDate)) return <Navigate replace to="/" />;
  return <DateWorkbenchPage canWrite={canWrite} reportDate={reportDate} siteId={siteId} userId={userId} />;
}

function DashboardRoute({ currencyCode, initialMonth, principal }: { currencyCode: string; initialMonth: string; principal: Principal }) {
  const [parameters] = useSearchParams();
  if (PRODUCT_ANALYTICS_SOURCE === "p0_catalog" && parameters.get("tab") === "products") {
    return <Navigate replace to="/products" />;
  }
  return <PublishedDashboard currencyCode={currencyCode} initialMonth={initialMonth} principal={principal} productAnalyticsSource={PRODUCT_ANALYTICS_SOURCE} />;
}

export function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [principal, setPrincipal] = useState<Principal>();
  const [checked, setChecked] = useState(false);
  const [siteContext, setSiteContext] = useState<SiteContext>();
  const [siteContextError, setSiteContextError] = useState<string>();
  const [selected, setSelected] = useState<ReportDay>(() => currentReportDay("UTC"));
  const [reviewFocus, setReviewFocus] = useState<ReviewFocus>(() => ({
    epoch: 0,
    reportDate: isoDate(selected),
    resolved: false,
  }));
  const [online, setOnline] = useState(true);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [logoutError, setLogoutError] = useState<string>();
  useEffect(() => { void requestApi<Principal>("/api/auth/me").then((user) => { establishSessionBoundary(); setPrincipal(user); }).catch(() => { setOnline(false); }).finally(() => setChecked(true)); }, []);
  const siteContextLoadSequence = useRef(0);
  const reloadSiteContext = useCallback(async () => {
    const sequence = ++siteContextLoadSequence.current;
    const context = await requestApi<SiteContext>("/api/data-calendar/site-context");
    if (sequence !== siteContextLoadSequence.current) return;
    setSiteContext(context);
    setSiteContextError(undefined);
    const currentDay = currentReportDay(context.reporting_timezone);
    setSelected(currentDay);
    setReviewFocus((current) => ({
      ...current,
      reportDate: isoDate(currentDay),
      resolved: false,
    }));
  }, []);
  useEffect(() => {
    if (!principal || siteContext) return;
    void reloadSiteContext().catch((reason: unknown) => {
      setSiteContextError(reason instanceof Error ? reason.message : "无法读取站点配置。");
    });
  }, [principal, reloadSiteContext, siteContext]);
  const selectReviewFocus = useCallback((request: ReviewFocusRequest) => {
    setSelected(reportDayFromIso(request.reportDate));
    setReviewFocus((current) => ({
      ...request,
      epoch: current.epoch + 1,
    }));
  }, []);
  const selectReviewRouteFocus = useCallback((request: ReviewFocusRequest) => {
    selectReviewFocus(request);
    if (location.pathname.startsWith("/review-advanced/")) {
      const parameters = new URLSearchParams();
      if (request.reportType) parameters.set("report_type", request.reportType);
      if (request.versionId) parameters.set("version_id", String(request.versionId));
      void navigate(`/review-advanced/${request.reportDate}?${parameters}`, { replace: true, state: location.state as unknown });
    } else {
      const parameters = new URLSearchParams(location.search);
      if (request.reportType) parameters.set("report_type", request.reportType);
      else parameters.delete("report_type");
      if (request.versionId) parameters.set("version_id", String(request.versionId));
      else parameters.delete("version_id");
      parameters.delete("batch_id");
      parameters.set("page", "1");
      void navigate(`/review/${request.reportDate}?${parameters}`, { replace: true });
    }
  }, [location.pathname, location.search, location.state, navigate, selectReviewFocus]);
  const resolveReviewFocus = useCallback((request: ReviewFocusRequest & { epoch: number }) => {
    setReviewFocus((current) => {
      if (
        current.epoch !== request.epoch
        || current.reportDate !== request.reportDate
        || current.resolved
      ) return current;
      return request;
    });
  }, []);
  const updateReviewLocation = useCallback((handoff: ReviewLocationHandoff) => {
    setSelected(reportDayFromIso(handoff.reportDate));
    setReviewFocus((current) => ({
      ...current,
      reportDate: handoff.reportDate,
      reportType: handoff.reportType,
      resolved: true,
      versionId: handoff.versionId,
    }));
    const parameters = new URLSearchParams({ report_type: handoff.reportType });
    if (handoff.versionId) parameters.set("version_id", String(handoff.versionId));
    void navigate(`/review/${handoff.reportDate}?${parameters}`);
  }, [navigate]);
  const openBatchReview = useCallback((runId: number) => {
    void navigate(`/review/batch/${runId}`);
  }, [navigate]);
  const clearSession = useCallback(() => {
    if (principal && siteContext) clearReviewRecoveryForIdentity(siteContext.site_id, principal.id);
    closeSessionBoundary();
    setSessionCsrfToken(undefined); setPrincipal(undefined); setSiteContext(undefined); setLogoutError(undefined);
  }, [principal, siteContext]);
  const logout = async () => {
    if (logoutBusy) return;
    setLogoutBusy(true); setLogoutError(undefined);
    try {
      await writeApi<void>("/api/auth/logout", { idempotent: false });
      clearSession();
    } catch (reason) {
      if (reason instanceof ApiRequestError && reason.status === 401) {
        clearSession();
      } else {
        const detail = reason instanceof Error ? reason.message : "无法联系服务器。";
        setLogoutError(`退出失败，当前会话仍然有效，请重试。${detail}`);
      }
    } finally {
      setLogoutBusy(false);
    }
  };
  if (!checked) return <AppLoadingState message="正在连接数据核验台…" />;
  if (!principal) return <LoginPage onLogin={(user) => { establishSessionBoundary(); setOnline(true); setPrincipal(user); }} />;
  if (siteContextError) return <main className={styles.loginPage} id="main-content"><section className={`${styles.loginCard} ${styles.stateCard}`}><ErrorState action={<Button onClick={() => { setSiteContextError(undefined); void reloadSiteContext().catch((reason: unknown) => setSiteContextError(reason instanceof Error ? reason.message : "无法读取站点配置。")); }} variant="primary">重新读取站点配置</Button>} description={siteContextError} title="站点配置不可用" /></section></main>;
  if (!siteContext) return <AppLoadingState message="正在读取当前站点配置…" />;
  const isAdmin = principal.roles.includes("admin");
  const canWrite = isAdmin || principal.roles.includes("data_manager");
  const selectedMonth = `${selected.year}-${String(selected.month).padStart(2, "0")}`;
  const today = isoDate(currentReportDay(siteContext.reporting_timezone));
  const reviewRoute = <ReviewRoutePage focus={reviewFocus} onBatchReviewCreated={openBatchReview} onFlowLocationChanged={updateReviewLocation} onResolveFocus={resolveReviewFocus} onSelect={selectReviewRouteFocus} principal={principal} reportingTimezone={siteContext.reporting_timezone} siteId={siteContext.site_id} />;
  return <AuthzGenerationProvider boundary={{ principalId: principal.id, roles: principal.roles, siteConfigVersionId: siteContext.site_config_version_id, siteId: siteContext.site_id }} onRevoked={clearSession}><AppShell logoutBusy={logoutBusy} logoutError={logoutError} online={online} onLogout={() => void logout()} principal={principal} siteContext={siteContext}><CatalogNavigationProvider key={`${principal.id}:${[...principal.roles].sort().join(",")}:${siteContext.site_id}:${siteContext.site_config_version_id}`}><Routes><Route element={<PublishedDetailLedgerPage principal={principal} reportingTimezone={siteContext.reporting_timezone} siteId={siteContext.site_id} today={today} />} path="/ledger/published-details" /><Route element={<DashboardRoute currencyCode={siteContext.currency_code} initialMonth={selectedMonth} principal={principal} />} path="/" /><Route element={PRODUCT_ANALYTICS_SOURCE === "p0_catalog" ? <ProductLedgerPage today={today} /> : <Navigate replace to="/?tab=products" />} path="/products" /><Route element={PRODUCT_ANALYTICS_SOURCE === "p0_catalog" ? <ProductDetailPage today={today} /> : <Navigate replace to="/?tab=products" />} path="/products/:style_id" /><Route element={<Navigate replace to="/" />} path="/dashboard" /><Route element={<CatalogLayout canManage={canWrite}><CatalogHomePage canManage={canWrite} /></CatalogLayout>} path="/catalog" /><Route element={<CatalogLayout canManage={canWrite}><CatalogStylePage /></CatalogLayout>} path="/catalog/styles/:style_id" /><Route element={canWrite ? <CatalogLayout canManage><CatalogImportPage /></CatalogLayout> : <Navigate replace to="/catalog" />} path="/catalog/imports/:import_id" /><Route element={canWrite ? <CatalogLayout canManage><CatalogUnmatchedPage /></CatalogLayout> : <Navigate replace to="/catalog" />} path="/catalog/unmatched" /><Route element={canWrite ? <CatalogLayout canManage><CatalogMaintenancePage /></CatalogLayout> : <Navigate replace to="/catalog" />} path="/catalog/maintenance" /><Route element={canWrite ? <CatalogLayout canManage><CatalogVersionsPage /></CatalogLayout> : <Navigate replace to="/catalog" />} path="/catalog/versions" /><Route element={canWrite ? <BatchReviewPage /> : <Navigate replace to="/" />} path="/review/batch/:runId" /><Route element={canWrite ? <><DateWorkbenchRoute canWrite siteId={siteContext.site_id} userId={principal.id} /><section className="advanced-review" aria-label="高级审核与发布控制">{reviewRoute}</section></> : <ViewerReviewRedirect />} path="/review/:reportDate" /><Route element={<><DateWorkbenchRoute canWrite={canWrite} siteId={siteContext.site_id} userId={principal.id} /><section className="advanced-review" aria-label="已发布详情"><PublishedDayPage currencyCode={siteContext.currency_code} /></section></>} path="/published/:reportDate" /><Route element={canWrite ? <><ReviewWorkbenchReturn />{reviewRoute}</> : <ViewerReviewRedirect />} path="/review-advanced/:reportDate" /><Route element={<PublishedDayPage currencyCode={siteContext.currency_code} />} path="/published-details/:reportDate" /><Route element={<VersionHistory initialReportDate={isoDate(selected)} onFilterChange={({ reportDate, reportType }) => selectReviewFocus({ reportDate, reportType, resolved: false })} onMoveRevisionCreated={(handoff) => { selectReviewFocus({ reportDate: handoff.targetReportDate, reportType: handoff.reportType, resolved: true, versionId: handoff.command.version_id }); void navigate(`/review/${handoff.targetReportDate}`); }} onRevisionCreated={(handoff) => { selectReviewFocus({ reportDate: handoff.reportDate, reportType: handoff.reportType, resolved: true, versionId: handoff.command.version_id }); void navigate(`/review/${handoff.reportDate}`); }} principal={principal} />} path="/versions" /><Route element={isAdmin ? <AdminConsole onSiteConfigCreated={() => { void reloadSiteContext(); }} principal={principal} /> : <Navigate replace to="/" />} path="/admin" /><Route element={<Navigate replace to="/" />} path="*" /></Routes></CatalogNavigationProvider></AppShell></AuthzGenerationProvider>;
}
