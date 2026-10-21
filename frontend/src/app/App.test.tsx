import surfaceCss from "../features/import-review/ReviewSurfaces.module.css";
import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../features/import-review/ImportReviewFlow", () => ({
  ImportReviewFlow: ({
    canFinalizePublishedMove,
    canForceRebuild,
    initialVersionId,
    initialReportType,
    initialBatchId,
    onBatchReviewCreated,
    onReportDateChanged,
    reportDate,
  }: {
    canFinalizePublishedMove?: boolean;
    canForceRebuild?: boolean;
    initialReportType?: "business_report" | "return_report";
    initialVersionId?: number;
    initialBatchId?: number;
    onBatchReviewCreated?: (runId: number) => void;
    onReportDateChanged?: (handoff: {
      reportDate: string;
      reportType: "business_report" | "return_report";
      versionId?: number;
    }) => void;
    reportDate: string;
  }) => (
    <div data-can-finalize-published-move={String(canFinalizePublishedMove ?? false)} data-can-force-rebuild={String(canForceRebuild ?? false)} data-report-type={initialReportType} data-testid="import-review-flow">
      <span>版本 {initialVersionId ?? "new"}</span><span>文件 {initialBatchId ?? "none"}</span>
      <span>报告日 {reportDate}</span>
      <label>测试流程本地状态<input aria-label="测试流程本地状态" defaultValue="" /></label>
      <button onClick={() => onReportDateChanged?.({ reportDate: "2026-08-13", reportType: "return_report" })} type="button">测试批次改日</button>
      <button onClick={() => onReportDateChanged?.({ reportDate: "2026-08-14", reportType: "return_report", versionId: 303 })} type="button">测试草稿改日</button>
      <button onClick={() => onBatchReviewCreated?.(77)} type="button">测试进入批量审核</button>
    </div>
  ),
}));

vi.mock("../features/versions/VersionHistory", () => ({
  VersionHistory: ({
    onMoveRevisionCreated,
    onRevisionCreated,
  }: {
    onMoveRevisionCreated?: (handoff: {
      command: { version_id: number };
      reportType: "return_report";
      targetReportDate: string;
    }) => void;
    onRevisionCreated?: (handoff: {
      command: { version_id: number };
      reportDate: string;
      reportType: "return_report";
    }) => void;
  }) => (
    <main>
      <h1>版本记录</h1>
      <button onClick={() => onRevisionCreated?.({ command: { version_id: 202 }, reportDate: "2026-08-12", reportType: "return_report" })} type="button">
        测试创建修订
      </button>
      <button onClick={() => onMoveRevisionCreated?.({ command: { version_id: 303 }, reportType: "return_report", targetReportDate: "2026-08-13" })} type="button">
        测试创建跨日修订
      </button>
    </main>
  ),
}));

vi.mock("../features/batch-review/BatchReviewPage", () => ({
  BatchReviewPage: () => <main><h1>批量审核任务</h1></main>,
}));

vi.mock("../features/workbench/DateWorkbenchPage", () => ({
  DateWorkbenchPage: ({
    canWrite,
    reportDate,
    siteId,
    userId,
  }: {
    canWrite: boolean;
    reportDate: string;
    siteId: number;
    userId: number;
  }) => <div data-can-write={String(canWrite)} data-report-date={reportDate} data-site-id={siteId} data-testid="date-workbench-route" data-user-id={userId} />,
}));

vi.mock("../features/published-details/PublishedDetailLedgerPage", () => ({
  PublishedDetailLedgerPage: ({
    principal,
    reportingTimezone,
    siteId,
    today,
  }: {
    principal: { roles: string[] };
    reportingTimezone: string;
    siteId: number;
    today: string;
  }) => <main data-reporting-timezone={reportingTimezone} data-roles={principal.roles.join(",")} data-site-id={siteId} data-testid="published-details-route" data-today={today}><h1>跨日期已发布明细</h1></main>,
}));

vi.mock("../features/products/ProductLedgerPage", () => ({
  ProductLedgerPage: ({ today }: { today: string }) => <main data-testid="product-ledger-route" data-today={today}><h1>产品总表</h1></main>,
}));

vi.mock("../features/products/ProductDetailPage", () => ({
  ProductDetailPage: ({ today }: { today: string }) => <main data-testid="product-detail-route" data-today={today}><h1>产品详情</h1></main>,
}));

import { App } from "./App";
import { setSessionCsrfToken } from "../api/client";
import { reviewRecoveryKey } from "../features/import-review/reviewRecovery";
import { PRODUCT_ANALYTICS_SOURCE } from "../features/products/productAnalyticsSource";

let currentUser = { id: 1, username: "viewer", display_name: "查看人员", roles: ["viewer"] };
let calendarDays: Array<{
  report_date: string;
  status: "red" | "yellow" | "blue" | "green" | "gray";
  published_report_types: Array<"business_report" | "return_report">;
  draft_report_types: Array<"business_report" | "return_report">;
  reasons: string[];
}> = [];
let calendarEntries: Array<{
  dataset_id: number;
  report_date: string;
  report_type: "business_report" | "return_report";
  status: "published" | "ready_for_publish" | "draft";
  version_id: number;
  version_no: number;
}> = [];
let siteContext = {
  site_id: 1,
  site_code: "amazon_us",
  display_name: "Amazon US",
  site_config_version_id: 1,
  source_timezone: "America/Los_Angeles",
  reporting_timezone: "America/Los_Angeles",
  currency_code: "USD",
};

function response(payload: unknown) {
  return new Response(JSON.stringify(payload), { headers: { "Content-Type": "application/json" }, status: 200 });
}

function RouteProbe() {
  const location = useLocation();
  return <output data-testid="route-query">{location.search}</output>;
}

function renderApp(initialEntry = "/") {
  return render(<MemoryRouter initialEntries={[initialEntry]}><App /><RouteProbe /></MemoryRouter>);
}

describe("App", () => {
  it("opens an explicit source batch without selecting the old active draft", async () => {
    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    calendarEntries = [{ dataset_id: 11, report_date: "2025-07-18", report_type: "business_report", status: "draft", version_id: 101, version_no: 2 }];
    renderApp("/review-advanced/2025-07-18?report_type=business_report&batch_id=44");
    await screen.findByTestId("import-review-flow");
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId("import-review-flow")).toHaveTextContent("文件 44");
    expect(screen.getByTestId("import-review-flow")).toHaveTextContent("版本 new");
  });

  it("keeps a historical exact draft on the advanced route during strict-mode initialization", async () => {
    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    calendarEntries = [
      { dataset_id: 11, report_date: "2025-07-18", report_type: "business_report", status: "draft", version_id: 101, version_no: 2 },
      { dataset_id: 12, report_date: "2025-07-18", report_type: "return_report", status: "draft", version_id: 202, version_no: 3 },
    ];
    render(<StrictMode><MemoryRouter initialEntries={[{pathname:"/review-advanced/2025-07-18",search:"?report_type=return_report&version_id=202",state:{workbenchReturn:"/published/2025-07-18?report_type=return_report&search=coat"}}]}><App/></MemoryRouter></StrictMode>);
    await waitFor(()=>expect(screen.getByTestId("import-review-flow")).toHaveTextContent("版本 202"));
    expect(screen.getByTestId("import-review-flow")).toHaveTextContent("报告日 2025-07-18");
    expect(screen.getByRole("link",{name:"返回日期表格"})).toHaveAttribute("href","/published/2025-07-18?report_type=return_report&search=coat");
  });
  it("redirects a viewer away from advanced review", async () => {
    renderApp("/review-advanced/2025-07-18?report_type=business_report");
    expect(await screen.findByTestId("date-workbench-route")).toBeVisible();
    expect(screen.queryByTestId("import-review-flow")).not.toBeInTheDocument();
  });

  it.each(["/catalog/maintenance", "/catalog/imports/2", "/catalog/unmatched", "/catalog/versions"])("catalog viewer cannot enter management deep link %s", async (path) => {
    renderApp(path);
    expect(await screen.findByRole("heading", { name: "商品主档尚未初始化" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "批量维护" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "目录工作簿" })).not.toBeInTheDocument();
  });

  it("catalog data manager can open the real maintenance controls", async () => {
    currentUser = { id: 2, username: "manager", display_name: "数据管理员", roles: ["data_manager"] };
    renderApp("/catalog/maintenance");
    expect(await screen.findByRole("heading", { name: "目录工作簿" })).toBeVisible();
    expect(screen.getByRole("link", { name: "批量维护" })).toHaveAttribute("aria-current", "page");
  });
  beforeEach(() => {
    setSessionCsrfToken("test-session-csrf");
    currentUser = { id: 1, username: "viewer", display_name: "查看人员", roles: ["viewer"] };
    calendarDays = [];
    calendarEntries = [];
    siteContext = {
      site_id: 1,
      site_code: "amazon_us",
      display_name: "Amazon US",
      site_config_version_id: 1,
      source_timezone: "America/Los_Angeles",
      reporting_timezone: "America/Los_Angeles",
      currency_code: "USD",
    };
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.includes("/api/auth/me")) return Promise.resolve(response(currentUser));
      if (path.startsWith("/api/catalog/imports?")) return Promise.resolve(response({ items: [], has_next: false }));
      if (path === "/api/catalog/styles") return Promise.resolve(response({ catalog: null }));
      if (path === "/api/catalog/exports/latest") return Promise.resolve(response({ export: null }));
      if (path.includes("/api/data-calendar/site-context")) return Promise.resolve(response(siteContext));
      if (path.includes("/api/data-calendar/days")) return Promise.resolve(response(calendarDays));
      if (path.includes("/api/data-calendar")) return Promise.resolve(response(calendarEntries));
      if (path.includes("/api/dashboard/daily-ledger")) return Promise.resolve(response({ rows: [], publications: [], site_config_versions: [], range: { from_date: "2026-08-01", to_date: "2026-08-31" } }));
      if (path.includes("/api/dashboard/product-ledger")) return Promise.resolve(response({ rows: [], total_rows: 0, page: 1, page_size: 25, sort: "sales", direction: "desc", publications: [], site_config_versions: [], range: { from_date: "2026-08-01", to_date: "2026-08-31" } }));
      if (path.includes("/api/dashboard/summary")) return Promise.resolve(response({ metrics: [], publications: [], site_config_versions: [], range: { from_date: "2026-08-01", to_date: "2026-08-31" } }));
      if (path.includes("/api/dashboard/products")) return Promise.resolve(response({ rows: [], publications: [], site_config_versions: [], range: { from_date: "2026-08-01", to_date: "2026-08-31" } }));
      if (path.includes("/api/dashboard/returns")) return Promise.resolve(response({ basis: "report_date", rows: [], publications: [], site_config_versions: [], range: { from_date: "2026-08-01", to_date: "2026-08-31" } }));
      if (path.includes("/api/versions?")) return Promise.resolve(response([]));
      if (path.includes("/api/admin/roles")) return Promise.resolve(response([]));
      if (path.includes("/api/admin/users")) return Promise.resolve(response([]));
      if (path.includes("/api/admin/site-config-versions")) return Promise.resolve(response([]));
      if (path.includes("/api/admin/audit-events")) return Promise.resolve(response({ items: [], total: 0, limit: 20, offset: 0, next_offset: null }));
      return Promise.resolve(response({}));
    }));
  });

  afterEach(() => { setSessionCsrfToken(undefined); window.localStorage.clear(); window.sessionStorage.clear(); vi.unstubAllGlobals(); });

  it("uses the published ledger as the first screen for a viewer", async () => {
    renderApp();
    expect(await screen.findByRole("heading", { level: 1, name: "发布数据总表" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "每日总表" })).toBeVisible();
    if (PRODUCT_ANALYTICS_SOURCE === "legacy_parser") expect(screen.getByRole("tab", { name: "产品总表" })).toBeVisible();
    else expect(screen.queryByRole("tab", { name: "产品总表" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /数据审核/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "进入今日审核" })).not.toBeInTheDocument();
  });

  it("collapses the desktop sidebar and restores the saved preference", async () => {
    const first = renderApp();
    const collapse = await screen.findByRole("button", { name: "收起侧栏" });

    fireEvent.click(collapse);

    expect(screen.getByRole("button", { name: "展开侧栏" })).toHaveAttribute("aria-expanded", "false");
    expect(document.querySelector(".app-shell")).toHaveAttribute("data-sidebar-collapsed", "true");
    first.unmount();

    renderApp();

    expect(await screen.findByRole("button", { name: "展开侧栏" })).toBeVisible();
  });

  it("preserves a navigation click at first shell appearance", async () => {
    // Click when the asynchronous shell first enters the DOM, before its
    // passive effects flush. Finding the button alone must be sufficient.
    let clicked = false;
    const observer = new MutationObserver(() => {
      const toggle = document.querySelector<HTMLButtonElement>('button[aria-label="打开主导航"]');
      if (clicked || !toggle) return;
      clicked = true;
      fireEvent.click(toggle);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    try {
      renderApp();
      expect(await screen.findByLabelText("关闭主导航", { selector: "button" })).toHaveAttribute("aria-expanded", "true");
    } finally {
      observer.disconnect();
    }
  });

  it("opens and closes the narrow navigation with an explicit keyboard-safe control", async () => {
    renderApp();
    const openNavigation = await screen.findByLabelText("打开主导航", { selector: "button" });

    fireEvent.click(openNavigation);

    const closeNavigation = await screen.findByLabelText("关闭主导航", { selector: "button" });
    expect(closeNavigation).toHaveAttribute("aria-controls", "primary-navigation");
    expect(closeNavigation).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(window, { key: "Escape" });

    expect(await screen.findByLabelText("打开主导航", { selector: "button" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByLabelText("打开主导航", { selector: "button" })).toHaveFocus();
  });

  it("closes the narrow navigation after following a workspace link", async () => {
    renderApp();
    fireEvent.click(await screen.findByLabelText("打开主导航", { selector: "button" }));
    expect(await screen.findByLabelText("关闭主导航", { selector: "button" })).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(screen.getByRole("link", { name: /版本记录/ }));

    expect(await screen.findByRole("heading", { name: "版本记录" })).toBeVisible();
    expect(screen.getByLabelText("打开主导航", { selector: "button" })).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps the role-specific workspace entries inside the migrated shell", async () => {
    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    renderApp();

    expect(await screen.findByRole("link", { name: /数据审核/ })).toBeVisible();
    expect(screen.getByRole("link", { name: /版本记录/ })).toBeVisible();
    expect(screen.queryByRole("link", { name: /管理员控制台/ })).not.toBeInTheDocument();
    expect(screen.getByText("报告时区").closest(".topbar__timezone")).toHaveTextContent("America/Los_Angeles");
  });

  it("uses the current versioned site context instead of a hard-coded timezone", async () => {
    siteContext = {
      ...siteContext,
      display_name: "中国测试站点",
      site_config_version_id: 8,
      source_timezone: "Asia/Shanghai",
      reporting_timezone: "Asia/Shanghai",
      currency_code: "CNY",
    };

    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    renderApp("/review/2026-08-10");

    expect(await screen.findAllByText("中国测试站点")).toHaveLength(2);
    expect(screen.getByText("报告时区").closest(".topbar__timezone")).toHaveTextContent("Asia/Shanghai");
    expect(await screen.findByText("站点报告日 · Asia/Shanghai")).toBeVisible();
  });

  it("renders a 31-day evidence rail and keeps each day independently selectable", async () => {
    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    renderApp("/review/2026-08-10");
    const rail = await screen.findByRole("complementary", { name: /每日证据轨/ });
    expect(within(rail).getAllByRole("listitem").length).toBeGreaterThanOrEqual(28);
    const day = within(rail).getAllByRole("button")[0];
    if (!day) throw new Error("The daily evidence rail is empty.");
    await act(async () => { fireEvent.click(day); await Promise.resolve(); });
    await waitFor(() => expect(within(screen.getByRole("complementary", { name: /每日证据轨/ })).getAllByRole("button")[0]).toHaveAttribute("aria-current", "date"));
  });

  it("renders the server-derived red yellow blue green gray day status", async () => {
    const parts = new Intl.DateTimeFormat("en-US", {
      month: "2-digit",
      timeZone: "America/Los_Angeles",
      year: "numeric",
    }).formatToParts(new Date());
    const year = parts.find((part) => part.type === "year")?.value;
    const month = parts.find((part) => part.type === "month")?.value;
    calendarDays = [{
      report_date: `${year}-${month}-01`,
      status: "red",
      published_report_types: ["business_report", "return_report"],
      draft_report_types: ["business_report"],
      reasons: ["blocking_issues"],
    }];

    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    renderApp(`/review/${year}-${month}-01`);

    const redDay = await screen.findByRole("button", {
      name: /需处理：阻断、导入失败或原文件异常/,
    });
    expect(redDay).toHaveClass(surfaceCss["evidence-day--red"]!);
    expect(within(redDay).getByText("!")).toBeVisible();
  });

  it("lets a data manager switch between both report drafts for one day", async () => {
    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    const parts = new Intl.DateTimeFormat("en-US", {
      day: "2-digit",
      month: "2-digit",
      timeZone: "America/Los_Angeles",
      year: "numeric",
    }).formatToParts(new Date());
    const value = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value;
    const reportDate = `${value("year")}-${value("month")}-${value("day")}`;
    calendarEntries = [
      { dataset_id: 11, report_date: reportDate, report_type: "business_report", status: "draft", version_id: 101, version_no: 2 },
      { dataset_id: 12, report_date: reportDate, report_type: "return_report", status: "ready_for_publish", version_id: 202, version_no: 3 },
    ];

    renderApp(`/review/${reportDate}`);

    const switcher = await screen.findByRole("group", { name: "选择待审核报表" });
    const business = within(switcher).getByRole("button", { name: /经营报告/ });
    const returns = within(switcher).getByRole("button", { name: /退货报告/ });
    await waitFor(() => {
      expect(business).toHaveAttribute("aria-pressed", "true");
      expect(returns).toHaveAttribute("aria-pressed", "false");
    });

    fireEvent.click(returns);

    expect(returns).toHaveAttribute("aria-pressed", "true");
    expect(business).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("import-review-flow")).toHaveTextContent("版本 202");
    expect(screen.getByTestId("import-review-flow")).toHaveAttribute("data-can-finalize-published-move", "false");
    expect(screen.getByTestId("import-review-flow")).toHaveAttribute("data-can-force-rebuild", "false");
  });

  it("only grants the administrator the published-move finalization capability", async () => {
    currentUser = { id: 2, username: "owner", display_name: "管理员", roles: ["admin"] };
    const parts = new Intl.DateTimeFormat("en-US", {
      day: "2-digit",
      month: "2-digit",
      timeZone: "America/Los_Angeles",
      year: "numeric",
    }).formatToParts(new Date());
    const value = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value;
    const reportDate = `${value("year")}-${value("month")}-${value("day")}`;
    calendarEntries = [
      { dataset_id: 11, report_date: reportDate, report_type: "business_report", status: "draft", version_id: 101, version_no: 2 },
    ];

    renderApp(`/review/${reportDate}`);

    expect(await screen.findByTestId("import-review-flow")).toHaveAttribute("data-can-finalize-published-move", "true");
    expect(screen.getByTestId("import-review-flow")).toHaveAttribute("data-can-force-rebuild", "true");
  });

  it("redirects the legacy dashboard route to the published ledger", async () => {
    renderApp("/dashboard");
    expect(await screen.findByRole("heading", { name: "发布数据总表" })).toBeVisible();
    expect(screen.getByRole("link", { name: /发布总表/ })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("link", { name: /数据审核/ })).not.toBeInTheDocument();
  });

  it("renders the version-record route", async () => {
    renderApp("/versions");
    expect(await screen.findByRole("heading", { name: "版本记录" })).toBeVisible();
  });

  it("opens the exact newly created published revision when both report drafts exist", async () => {
    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    calendarEntries = [
      {
        dataset_id: 41,
        report_date: "2026-08-12",
        report_type: "business_report",
        status: "draft",
        version_id: 77,
        version_no: 4,
      },
      {
        dataset_id: 42,
        report_date: "2026-08-12",
        report_type: "return_report",
        status: "draft",
        version_id: 202,
        version_no: 2,
      },
    ];

    renderApp("/versions");
    fireEvent.click(await screen.findByRole("button", { name: "测试创建修订" }));

    expect(await screen.findByRole("heading", { name: "导入先审核，发布后才进入看板" })).toBeVisible();
    await waitFor(() => expect(screen.getByTestId("import-review-flow")).toHaveTextContent("版本 202"));
  });

  it("opens the exact cross-date revision instead of the first target-date draft", async () => {
    currentUser = { id: 2, username: "owner", display_name: "管理员", roles: ["admin"] };
    calendarEntries = [
      { dataset_id: 51, report_date: "2026-08-13", report_type: "business_report", status: "draft", version_id: 111, version_no: 3 },
      { dataset_id: 52, report_date: "2026-08-13", report_type: "return_report", status: "draft", version_id: 303, version_no: 1 },
    ];

    renderApp("/versions");
    fireEvent.click(await screen.findByRole("button", { name: "测试创建跨日修订" }));

    expect(await screen.findByRole("heading", { name: "导入先审核，发布后才进入看板" })).toBeVisible();
    await waitFor(() => expect(screen.getByTestId("import-review-flow")).toHaveTextContent("版本 303"));
  });

  it("keeps the active review flow mounted while internal date changes refresh the calendar", async () => {
    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    calendarEntries = [
      { dataset_id: 41, report_date: "2026-08-12", report_type: "business_report", status: "draft", version_id: 77, version_no: 4 },
      { dataset_id: 42, report_date: "2026-08-12", report_type: "return_report", status: "draft", version_id: 202, version_no: 2 },
    ];

    renderApp("/versions");
    fireEvent.click(await screen.findByRole("button", { name: "测试创建修订" }));
    const flowState = await screen.findByLabelText("测试流程本地状态");
    fireEvent.change(flowState, { target: { value: "尚未提交的本地审核状态" } });
    const fetchMock = vi.mocked(fetch);
    const calendarRequestCount = () => fetchMock.mock.calls.filter(([input]) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return path.startsWith("/api/data-calendar?");
    }).length;
    const beforeDateChange = calendarRequestCount();

    fireEvent.click(screen.getByRole("button", { name: "测试批次改日" }));

    await waitFor(() => expect(screen.getByTestId("import-review-flow")).toHaveTextContent("报告日 2026-08-13"));
    expect(screen.getByLabelText("测试流程本地状态")).toBe(flowState);
    expect(screen.getByLabelText("测试流程本地状态")).toHaveValue("尚未提交的本地审核状态");
    await waitFor(() => expect(calendarRequestCount()).toBeGreaterThan(beforeDateChange));

    fireEvent.click(screen.getByRole("button", { name: "测试草稿改日" }));

    await waitFor(() => expect(screen.getByTestId("import-review-flow")).toHaveTextContent("版本 303"));
    expect(screen.getByTestId("import-review-flow")).toHaveTextContent("报告日 2026-08-14");
    expect(screen.getByLabelText("测试流程本地状态")).toBe(flowState);
    expect(screen.getByLabelText("测试流程本地状态")).toHaveValue("尚未提交的本地审核状态");
  });

  it("does not resolve a day from stale same-month calendar data while an internal move refreshes", async () => {
    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    calendarEntries = [
      { dataset_id: 41, report_date: "2026-08-12", report_type: "business_report", status: "draft", version_id: 77, version_no: 4 },
      { dataset_id: 42, report_date: "2026-08-12", report_type: "return_report", status: "draft", version_id: 202, version_no: 2 },
    ];

    renderApp("/versions");
    fireEvent.click(await screen.findByRole("button", { name: "测试创建修订" }));
    await waitFor(() => expect(screen.getByTestId("import-review-flow")).toHaveTextContent("版本 202"));

    let resolveEntries: (value: Response) => void = () => undefined;
    let resolveDays: (value: Response) => void = () => undefined;
    const pendingEntries = new Promise<Response>((resolve) => { resolveEntries = resolve; });
    const pendingDays = new Promise<Response>((resolve) => { resolveDays = resolve; });
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation((input: string | URL | Request) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/data-calendar/days?")) return pendingDays;
      if (path.startsWith("/api/data-calendar?")) return pendingEntries;
      return Promise.resolve(response({}));
    });

    fireEvent.click(screen.getByRole("button", { name: "测试批次改日" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/data-calendar?"),
      expect.anything(),
    ));
    fireEvent.click(screen.getByRole("button", { name: /选择 8 月 12 日/ }));

    expect(await screen.findByText("正在确认这个日期的活动草稿…")).toBeVisible();
    expect(screen.queryByText("版本 77")).not.toBeInTheDocument();

    await act(async () => {
      resolveEntries(response([]));
      resolveDays(response([]));
      await Promise.all([pendingEntries, pendingDays]);
    });
    await waitFor(() => expect(screen.getByTestId("import-review-flow")).toHaveTextContent("版本 new"));
    expect(screen.getByTestId("import-review-flow")).toHaveTextContent("报告日 2026-08-12");
  });

  it("keeps the administrator route out of the viewer navigation and redirects direct access", async () => {
    renderApp("/admin");
    expect(await screen.findByRole("heading", { name: "发布数据总表" })).toBeVisible();
    expect(screen.queryByRole("link", { name: /管理员控制台/ })).not.toBeInTheDocument();
  });

  it("switches product routes as one release-scoped surface", async () => {
    const ledger = renderApp("/products");
    if (PRODUCT_ANALYTICS_SOURCE === "p0_catalog") expect(await screen.findByTestId("product-ledger-route")).toBeVisible();
    else expect(await screen.findByRole("tab", { name: "产品总表" })).toBeVisible();
    ledger.unmount();
    renderApp("/products/501");
    if (PRODUCT_ANALYTICS_SOURCE === "p0_catalog") expect(await screen.findByTestId("product-detail-route")).toBeVisible();
    else expect(await screen.findByRole("tab", { name: "产品总表" })).toBeVisible();
  });

  it("preserves the return-report route without selecting another report's draft", async () => {
    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    calendarEntries = [{ dataset_id: 11, report_date: "2026-08-10", report_type: "business_report", status: "draft", version_id: 101, version_no: 2 }];
    renderApp("/review/2026-08-10?report_type=return_report&page=1");
    await waitFor(() => expect(screen.getByTestId("import-review-flow")).toHaveAttribute("data-report-type", "return_report"));
    expect(screen.getByTestId("import-review-flow")).toHaveTextContent("版本 new");
    expect(screen.getByTestId("route-query").textContent).toContain("report_type=return_report");
  });

  it("resolves an exception deep link by server calendar facts and version ID", async () => {
    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    calendarEntries = [
      { dataset_id: 11, report_date: "2026-08-10", report_type: "business_report", status: "draft", version_id: 101, version_no: 2 },
      { dataset_id: 12, report_date: "2026-08-10", report_type: "return_report", status: "ready_for_publish", version_id: 202, version_no: 3 },
    ];

    renderApp("/review/2026-08-10?report_type=return_report&version_id=202");

    await waitFor(() => expect(screen.getByTestId("import-review-flow")).toHaveTextContent("版本 202"));
    expect(screen.getByTestId("import-review-flow")).toHaveTextContent("报告日 2026-08-10");
  });

  it.each([
    ["viewer", "viewer"],
    ["data manager", "data_manager"],
    ["administrator", "admin"],
  ])("mounts the viewer-safe published-details route for %s inside the site shell", async (_label, role) => {
    currentUser = { id: 3, username: role, display_name: role, roles: [role] };
    siteContext = { ...siteContext, site_id: 27, reporting_timezone: "Asia/Shanghai" };

    renderApp("/ledger/published-details");

    const route = await screen.findByTestId("published-details-route");
    expect(route).toHaveAttribute("data-site-id", "27");
    expect(route).toHaveAttribute("data-reporting-timezone", "Asia/Shanghai");
    expect(route).toHaveAttribute("data-roles", role);
    expect(route.getAttribute("data-today")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(screen.getByRole("complementary", { name: "主导航" })).toBeVisible();
  });

  it("redirects a viewer's direct review URL to the read-only published day", async () => {
    renderApp("/review/2026-08-10");
    expect(await screen.findByRole("heading", { name: "2026-08-10" })).toBeVisible();
    expect(screen.getByText(/这里只展示当前发布版本/)).toBeVisible();
  });

  it("mounts the independent batch-review route for a data manager", async () => {
    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    renderApp("/review/batch/77");
    expect(await screen.findByRole("heading", { name: "批量审核任务" })).toBeVisible();
    expect(screen.queryByTestId("date-workbench-route")).not.toBeInTheDocument();
  });

  it("does not expose the batch-review route to a viewer", async () => {
    renderApp("/review/batch/77");
    expect(await screen.findByRole("heading", { level: 1, name: "发布数据总表" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "批量审核任务" })).not.toBeInTheDocument();
  });

  it("passes the current principal and site identity to date workbench routes", async () => {
    currentUser = { id: 3, username: "manager", display_name: "录入审核", roles: ["data_manager"] };
    siteContext = { ...siteContext, site_id: 27 };

    const { unmount } = renderApp("/review/2026-08-10");
    expect(await screen.findByTestId("date-workbench-route")).toHaveAttribute("data-user-id", "3");
    expect(screen.getByTestId("date-workbench-route")).toHaveAttribute("data-site-id", "27");
    expect(screen.getByTestId("date-workbench-route")).toHaveAttribute("data-report-date", "2026-08-10");
    unmount();

    renderApp("/published/2026-08-10");
    expect(await screen.findByTestId("date-workbench-route")).toHaveAttribute("data-can-write", "true");
    expect(screen.getByTestId("date-workbench-route")).toHaveAttribute("data-user-id", "3");
    expect(screen.getByTestId("date-workbench-route")).toHaveAttribute("data-site-id", "27");
  });

  it("shows the administrator console only to an administrator", async () => {
    currentUser = { id: 2, username: "owner", display_name: "管理员", roles: ["admin"] };
    renderApp("/admin");
    expect(await screen.findByRole("heading", { name: "管理员控制台" })).toBeVisible();
    expect(screen.getByRole("link", { name: /管理员控制台/ })).toHaveAttribute("href", "/admin");
  });

  it.each([
    ["网络失败", () => Promise.reject(new TypeError("network unavailable"))],
    ["服务端 500", () => Promise.resolve(new Response(JSON.stringify({ error: { message: "logout unavailable" } }), { headers: { "Content-Type": "application/json" }, status: 500 }))],
  ])("在%s时保留仍然有效的会话并允许重试", async (_label, logoutResponse) => {
    const recoveryKey = reviewRecoveryKey({ reportDate: "2026-08-10", siteId: 1, userId: 1 });
    window.sessionStorage.setItem(recoveryKey, "keep-on-failure");
    const fetchMock = vi.mocked(fetch);
    renderApp();
    expect(await screen.findByRole("heading", { name: "发布数据总表" })).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/dashboard/daily-ledger"), expect.anything()));
    fetchMock.mockImplementationOnce(logoutResponse);

    fireEvent.click(screen.getByRole("button", { name: "退出" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("退出失败，当前会话仍然有效，请重试。");
    expect(screen.getByText("查看人员")).toBeVisible();
    expect(screen.getByRole("button", { name: "退出" })).toBeEnabled();
    expect(window.sessionStorage.getItem(recoveryKey)).toBe("keep-on-failure");
  });

  it("成功退出时只清理当前身份的审核恢复数据", async () => {
    const recoveryKey = reviewRecoveryKey({ reportDate: "2026-08-10", siteId: 1, userId: 1 });
    const otherUserKey = reviewRecoveryKey({ reportDate: "2026-08-10", siteId: 1, userId: 2 });
    window.sessionStorage.setItem(recoveryKey, "current");
    window.sessionStorage.setItem(otherUserKey, "other");
    window.sessionStorage.setItem("another-app", "keep");
    const fetchMock = vi.mocked(fetch);
    renderApp();
    expect(await screen.findByRole("heading", { name: "发布数据总表" })).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/dashboard/daily-ledger"), expect.anything()));
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    fireEvent.click(screen.getByRole("button", { name: "退出" }));

    expect(await screen.findByRole("heading", { name: "从原表开始，确认后再发布。" })).toBeVisible();
    expect(window.sessionStorage.getItem(recoveryKey)).toBeNull();
    expect(window.sessionStorage.getItem(otherUserKey)).toBe("other");
    expect(window.sessionStorage.getItem("another-app")).toBe("keep");
  });

  it("在服务端确认会话已失效时安全清理本地身份", async () => {
    const recoveryKey = reviewRecoveryKey({ reportDate: "2026-08-10", siteId: 1, userId: 1 });
    window.sessionStorage.setItem(recoveryKey, "current");
    window.sessionStorage.setItem("another-app", "keep");
    const fetchMock = vi.mocked(fetch);
    renderApp();
    expect(await screen.findByRole("heading", { name: "发布数据总表" })).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/dashboard/daily-ledger"), expect.anything()));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ error: { message: "会话已失效" } }), { headers: { "Content-Type": "application/json" }, status: 401 }));

    fireEvent.click(screen.getByRole("button", { name: "退出" }));

    expect(await screen.findByRole("heading", { name: "从原表开始，确认后再发布。" })).toBeVisible();
    expect(screen.queryByText("查看人员")).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem(recoveryKey)).toBeNull();
    expect(window.sessionStorage.getItem("another-app")).toBe("keep");
  });
});
