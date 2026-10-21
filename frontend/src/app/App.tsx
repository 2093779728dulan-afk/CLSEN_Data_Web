import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  ApiRequestError,
  issueLoginCsrfToken,
  requestApi,
  setSessionCsrfToken,
  writeApi,
} from "../api/client";
import { closeSessionBoundary, establishSessionBoundary } from "../api/sessionRevocation";
import type { CalendarDay, CalendarEntry, Principal, ReportType } from "../api/types";
import { Spinner } from "../design-system";
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
import { PRODUCT_ANALYTICS_SOURCE } from "../features/products/productAnalyticsSource";
import { DateWorkbenchPage } from "../features/workbench/DateWorkbenchPage";
import { VersionHistory } from "../features/versions/VersionHistory";
import { AuthzGenerationProvider } from "./AuthzGenerationContext";
import { WorkspaceShell, type WorkspaceSiteContext } from "./WorkspaceShell";
import { AdvancedReviewWorkspaceView, ReviewWorkbenchReturnView, SourceBatchReviewView } from "./AdvancedReviewWorkspaceView";
import { LoginView, SessionStateView } from "./SessionEntryView";

type ReportDay = { day: number; month: number; year: number };

type SiteContext = WorkspaceSiteContext;

type ReviewFocus = {
  epoch: number;
  reportDate: string;
  reportType?: ReportType;
  resolved: boolean;
  versionId?: number;
};

type ReviewFocusRequest = Omit<ReviewFocus, "epoch">;

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

function monthRange(day: ReportDay) {
  const last = new Date(day.year, day.month, 0).getDate();
  return { from: `${day.year}-${String(day.month).padStart(2, "0")}-01`, to: `${day.year}-${String(day.month).padStart(2, "0")}-${last}` };
}

function AppShell(props: Omit<React.ComponentProps<typeof WorkspaceShell>, "today" | "analyticsSource">) {
  const today = isoDate(currentReportDay(props.siteContext.reporting_timezone));
  return <WorkspaceShell {...props} analyticsSource={PRODUCT_ANALYTICS_SOURCE} today={today} />;
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
  return <LoginView username={username} password={password} busy={busy} error={error} onUsernameChange={setUsername} onPasswordChange={setPassword} onSubmit={event => { void submit(event); }} />;
}

function AppLoadingState({ message }: { message: string }) {
  return <SessionStateView message={message} />;
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
  const [calendarLoading, setCalendarLoading] = useState(true);
  const reloadSequence = useRef(0);
  const range = monthRange(selected);
  const rangeKey = `${range.from}:${range.to}`;
  const selectedDate = isoDate(selected);

  const reload = useCallback(async () => {
    const sequence = reloadSequence.current + 1;
    reloadSequence.current = sequence;
    setLoadedRange(undefined);
    setCalendarLoading(true);
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
    } finally {
      if (reloadSequence.current === sequence) setCalendarLoading(false);
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

  return <AdvancedReviewWorkspaceView selected={selected} calendarDays={calendarDays} entries={entries} calendarKnown={loadedRange === rangeKey} loading={calendarLoading} error={error} reportingTimezone={reportingTimezone} canWrite={canWrite} activeVersionId={activeVersionId} onSelect={selectDay} onSelectDraft={changeReportDraft} onRetry={() => void reload()}>
    {canWrite && (focusReady ? <ImportReviewFlow canFinalizePublishedMove={principal.roles.includes("admin")} canForceRebuild={principal.roles.includes("admin")} initialReportType={focus.reportType} initialVersionId={focus.versionId} key={`review-focus:${focus.epoch}`} onBatchReviewCreated={onBatchReviewCreated} onPublished={() => setCalendarRefreshEpoch((current) => current + 1)} onReportDateChanged={flowLocationChanged} operator={principal} reportDate={selectedDate} siteId={siteId} userId={principal.id} /> : !error && <div aria-label="正在确认活动草稿" role="status"><Spinner aria-hidden="true" /> 正在确认这个日期的活动草稿…</div>)}
  </AdvancedReviewWorkspaceView>;
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
    return <SourceBatchReviewView batchId={sourceBatchId}><ImportReviewFlow key={`source:${siteId}:${principal.id}:${sourceBatchId}`} initialBatchId={sourceBatchId} canForceRebuild={principal.roles.includes("admin")} canFinalizePublishedMove={principal.roles.includes("admin")} onBatchReviewCreated={onBatchReviewCreated} onPublished={() => undefined} operator={principal} reportDate={reportDate} siteId={siteId} userId={principal.id} /></SourceBatchReviewView>;
  }
  if (routeFocusDiffers && routeIsAuthoritative) {
    return <main className="page" id="main-content"><div aria-label="正在进入日期审核" role="status"><Spinner aria-hidden="true" /> 正在进入日期审核…</div></main>;
  }
  return <ReviewPage focus={focus} onBatchReviewCreated={onBatchReviewCreated} onFlowLocationChanged={onFlowLocationChanged} onResolveFocus={onResolveFocus} onSelect={onSelect} principal={principal} reportingTimezone={reportingTimezone} selected={reportDayFromIso(focus.reportDate)} siteId={siteId} />;
}

function ReviewWorkbenchReturn() {
  const location = useLocation();
  const { reportDate = "" } = useParams();
  const [parameters] = useSearchParams();
  const previous = (location.state as { workbenchReturn?: string } | null)?.workbenchReturn;
  const target = previous && /^\/(?:review|published)\/\d{4}-\d{2}-\d{2}(?:\?|$)/.test(previous) ? previous : `/review/${reportDate}?report_type=${parameters.get("report_type") === "return_report" ? "return_report" : "business_report"}`;
  return <ReviewWorkbenchReturnView target={target} />;
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
      void navigate(`/review/${request.reportDate}?${parameters}`, { replace: true, state: location.state as unknown });
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
  if (siteContextError) return <SessionStateView error={siteContextError} onRetry={() => { setSiteContextError(undefined); void reloadSiteContext().catch((reason: unknown) => setSiteContextError(reason instanceof Error ? reason.message : "无法读取站点配置。")); }} />;
  if (!siteContext) return <AppLoadingState message="正在读取当前站点配置…" />;
  const isAdmin = principal.roles.includes("admin");
  const canWrite = isAdmin || principal.roles.includes("data_manager");
  const selectedMonth = `${selected.year}-${String(selected.month).padStart(2, "0")}`;
  const today = isoDate(currentReportDay(siteContext.reporting_timezone));
  const reviewRoute = <ReviewRoutePage focus={reviewFocus} onBatchReviewCreated={openBatchReview} onFlowLocationChanged={updateReviewLocation} onResolveFocus={resolveReviewFocus} onSelect={selectReviewRouteFocus} principal={principal} reportingTimezone={siteContext.reporting_timezone} siteId={siteContext.site_id} />;
  return <AuthzGenerationProvider boundary={{ principalId: principal.id, roles: principal.roles, siteConfigVersionId: siteContext.site_config_version_id, siteId: siteContext.site_id }} onRevoked={clearSession}><AppShell logoutBusy={logoutBusy} logoutError={logoutError} online={online} onLogout={() => void logout()} principal={principal} siteContext={siteContext}><CatalogNavigationProvider key={`${principal.id}:${[...principal.roles].sort().join(",")}:${siteContext.site_id}:${siteContext.site_config_version_id}`}><Routes><Route element={<PublishedDetailLedgerPage principal={principal} reportingTimezone={siteContext.reporting_timezone} siteId={siteContext.site_id} today={today} />} path="/ledger/published-details" /><Route element={<DashboardRoute currencyCode={siteContext.currency_code} initialMonth={selectedMonth} principal={principal} />} path="/" /><Route element={PRODUCT_ANALYTICS_SOURCE === "p0_catalog" ? <ProductLedgerPage today={today} /> : <Navigate replace to="/?tab=products" />} path="/products" /><Route element={PRODUCT_ANALYTICS_SOURCE === "p0_catalog" ? <ProductDetailPage today={today} /> : <Navigate replace to="/?tab=products" />} path="/products/:style_id" /><Route element={<Navigate replace to="/" />} path="/dashboard" /><Route element={<CatalogLayout canManage={canWrite}><CatalogHomePage canManage={canWrite} /></CatalogLayout>} path="/catalog" /><Route element={<CatalogLayout canManage={canWrite}><CatalogStylePage /></CatalogLayout>} path="/catalog/styles/:style_id" /><Route element={canWrite ? <CatalogLayout canManage><CatalogImportPage /></CatalogLayout> : <Navigate replace to="/catalog" />} path="/catalog/imports/:import_id" /><Route element={canWrite ? <CatalogLayout canManage><CatalogUnmatchedPage /></CatalogLayout> : <Navigate replace to="/catalog" />} path="/catalog/unmatched" /><Route element={canWrite ? <CatalogLayout canManage><CatalogMaintenancePage /></CatalogLayout> : <Navigate replace to="/catalog" />} path="/catalog/maintenance" /><Route element={canWrite ? <CatalogLayout canManage><CatalogVersionsPage /></CatalogLayout> : <Navigate replace to="/catalog" />} path="/catalog/versions" /><Route element={canWrite ? <BatchReviewPage /> : <Navigate replace to="/" />} path="/review/batch/:runId" /><Route element={canWrite ? <><DateWorkbenchRoute canWrite siteId={siteContext.site_id} userId={principal.id} /><section className="advanced-review" aria-label="高级审核与发布控制">{reviewRoute}</section></> : <ViewerReviewRedirect />} path="/review/:reportDate" /><Route element={<><DateWorkbenchRoute canWrite={canWrite} siteId={siteContext.site_id} userId={principal.id} /><section className="advanced-review" aria-label="已发布详情"><PublishedDayPage currencyCode={siteContext.currency_code} /></section></>} path="/published/:reportDate" /><Route element={canWrite ? <><ReviewWorkbenchReturn />{reviewRoute}</> : <ViewerReviewRedirect />} path="/review-advanced/:reportDate" /><Route element={<PublishedDayPage currencyCode={siteContext.currency_code} />} path="/published-details/:reportDate" /><Route element={<VersionHistory initialReportDate={isoDate(selected)} onFilterChange={({ reportDate, reportType }) => selectReviewFocus({ reportDate, reportType, resolved: false })} onMoveRevisionCreated={(handoff) => { selectReviewFocus({ reportDate: handoff.targetReportDate, reportType: handoff.reportType, resolved: true, versionId: handoff.command.version_id }); void navigate(`/review/${handoff.targetReportDate}`); }} onRevisionCreated={(handoff) => { selectReviewFocus({ reportDate: handoff.reportDate, reportType: handoff.reportType, resolved: true, versionId: handoff.command.version_id }); void navigate(`/review/${handoff.reportDate}`); }} principal={principal} />} path="/versions" /><Route element={isAdmin ? <AdminConsole onSiteConfigCreated={() => { void reloadSiteContext(); }} principal={principal} /> : <Navigate replace to="/" />} path="/admin" /><Route element={<Navigate replace to="/" />} path="*" /></Routes></CatalogNavigationProvider></AppShell></AuthzGenerationProvider>;
}
