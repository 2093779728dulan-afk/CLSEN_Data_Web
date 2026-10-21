import { useState } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { Principal } from "../api/types";
import { PageHeader, StatusMessage } from "../design-system";
import { ProductLedgerView } from "../features/products/ProductLedgerView";
import { ledgerCategories, ledgerFixture } from "../features/products/ProductLedgerView.fixtures";
import { parseProductLedgerSearch, serializeProductLedgerSearch, updateProductLedgerView } from "../features/products/productLedgerState";
import { WorkspaceShell } from "./WorkspaceShell";

type Scenario = "reference" | "manager" | "viewer" | "collapsed" | "offline" | "logout-busy" | "logout-failure" | "navigation" | "navigation-failure";
function ShellStory({ scenario }: { scenario: Scenario }) {
  const location = useLocation();
  const [logoutError, setLogoutError] = useState<string | undefined>(scenario.endsWith("failure") ? "示例网络中断，当前会话仍保留。" : undefined);
  const [signedOut, setSignedOut] = useState(false);
  const [view, setView] = useState(parseProductLedgerSearch(new URLSearchParams("from=2026-07-25&to=2026-08-24"), "2026-08-24"));
  const [draft, setDraft] = useState({ from: view.from, to: view.to, search: view.search });
  const [showNames, setShowNames] = useState(false);
  const response = { ...ledgerFixture("reference"), sort: view.sort, direction: view.direction, page: view.page, page_size: view.page_size };
  const roles: Principal["roles"] = [scenario === "viewer" ? "viewer" : scenario === "manager" ? "data_manager" : "admin"];
  if (signedOut) return <main className="page" id="main-content"><StatusMessage kind="success" title="已退出示例会话">可以重新登录工作台。</StatusMessage></main>;
  const title = location.pathname === "/" ? "发布总表" : location.pathname.startsWith("/catalog") ? "商品主档" : location.pathname.startsWith("/review") ? "数据审核" : location.pathname.startsWith("/admin") ? "管理员控制台" : "版本记录";
  return <WorkspaceShell analyticsSource="p0_catalog" logoutBusy={scenario === "logout-busy"} logoutError={logoutError} onLogout={() => { setLogoutError(undefined); setSignedOut(true); }} online={scenario !== "offline"}
    principal={{ id: 88, username: "demo-workspace", display_name: "示例操作人员", roles }} today="2026-08-24" siteContext={{ site_id: 1, site_code: "DEMO", display_name: "示例美国站点", site_config_version_id: 2, source_timezone: "America/Los_Angeles", reporting_timezone: "America/Los_Angeles", currency_code: "USD" }}>
    {location.pathname.startsWith("/products") ? <ProductLedgerView today="2026-08-24" view={view} canonical={serializeProductLedgerSearch(view).toString()} categories={ledgerCategories} draft={draft} response={response} loading={false} refreshing={false} showNames={showNames}
      onDraftChange={change => setDraft(current => ({ ...current, ...change }))} onShowNamesChange={setShowNames} onSubmit={event => { event.preventDefault(); setView(current => updateProductLedgerView(current, draft)); }} onUpdate={change => setView(current => updateProductLedgerView(current, change))} onRetry={() => undefined} />
      : <main className="page" id="main-content" tabIndex={-1}><PageHeader title={title} description="使用主导航切换工作区。" /></main>}
  </WorkspaceShell>;
}
const meta = {
  title: "Pages/Workspace Shell", component: ShellStory, parameters: { layout: "fullscreen" }, args: { scenario: "reference" },
  decorators: [(Story, context) => <MemoryRouter initialEntries={["/products"]} key={context.args.scenario}><Story /></MemoryRouter>],
  beforeEach: context => { window.localStorage.setItem("clsen.workspace.sidebar-collapsed", String(context.args.scenario === "collapsed")); },
} satisfies Meta<typeof ShellStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = {};
export const Manager: Story = { args: { scenario: "manager" } };
export const Viewer: Story = { args: { scenario: "viewer" } };
export const Collapsed: Story = { args: { scenario: "collapsed" } };
export const Offline: Story = { args: { scenario: "offline" } };
export const LogoutBusy: Story = { args: { scenario: "logout-busy" } };
export const LogoutFailure: Story = { args: { scenario: "logout-failure" } };
export const Navigation: Story = { args: { scenario: "navigation" } };
export const NavigationFailure: Story = { args: { scenario: "navigation-failure" } };
