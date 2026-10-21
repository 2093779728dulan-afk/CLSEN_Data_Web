import { useEffect, useRef, useState, type ReactNode } from "react";
import { BarChart3, ClipboardCheck, History, LayoutDashboard, LogOut, Menu, Package, PanelLeftClose, PanelLeftOpen, ShieldCheck } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import type { Principal } from "../api/types";
import { Button, Dialog, StatusMessage } from "../design-system";
import styles from "./AppShell.module.css";

export type WorkspaceSiteContext = {
  site_id: number;
  site_code: string;
  display_name: string;
  site_config_version_id: number;
  source_timezone: string;
  reporting_timezone: string;
  currency_code: string;
};

export type WorkspaceShellProps = {
  children: ReactNode;
  principal: Principal;
  siteContext: WorkspaceSiteContext;
  today: string;
  analyticsSource: "p0_catalog" | "legacy_parser";
  online: boolean;
  logoutBusy: boolean;
  logoutError?: string;
  onLogout: () => void;
};

const SIDEBAR_COLLAPSED_KEY = "clsen.workspace.sidebar-collapsed";
const roleNames: Record<string, string> = { admin: "管理员", data_manager: "数据管理员", viewer: "查看人员" };
function savedSidebarCollapsed() {
  try { return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true"; }
  catch { return false; }
}

/** Shared application navigation; Radix Dialog supplies the shadcn Sheet interaction. */
export function WorkspaceShell({ children, principal, siteContext, today, analyticsSource, online, logoutBusy, logoutError, onLogout }: WorkspaceShellProps) {
  const location = useLocation();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(savedSidebarCollapsed);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const previousNavigationPath = useRef(location.pathname);
  const mobileNavigationToggle = useRef<HTMLButtonElement>(null);
  const isAdmin = principal.roles.includes("admin");
  const canWrite = isAdmin || principal.roles.includes("data_manager");
  const entries = [
    { label: "发布总表", to: "/", section: "/", icon: LayoutDashboard },
    { label: "商品主档", to: "/catalog", section: "/catalog", icon: Package },
    ...(analyticsSource === "p0_catalog" ? [{ label: "产品分析", to: "/products", section: "/products", icon: BarChart3 }] : []),
    ...(canWrite ? [{ label: "数据审核", to: `/review/${today}`, section: "/review", icon: ClipboardCheck }] : []),
    { label: "版本记录", to: "/versions", section: "/versions", icon: History },
    ...(isAdmin ? [{ label: "管理员控制台", to: "/admin", section: "/admin", icon: ShieldCheck }] : []),
  ];
  const activeEntry = entries.find(entry => entry.section === "/" ? location.pathname === "/" : location.pathname === entry.section || location.pathname.startsWith(`${entry.section}/`) || entry.section === "/review" && location.pathname.startsWith("/review-advanced/"));
  useEffect(() => {
    if (previousNavigationPath.current === location.pathname) return;
    previousNavigationPath.current = location.pathname;
    setNavigationOpen(false);
  }, [location.pathname]);
  // A responsive resize must not leave a modal hiding the now-visible desktop navigation.
  useEffect(() => {
    if (!navigationOpen) return;
    const closeAtDesktop = () => { if (window.innerWidth > 860) setNavigationOpen(false); };
    window.addEventListener("resize", closeAtDesktop);
    return () => window.removeEventListener("resize", closeAtDesktop);
  }, [navigationOpen]);
  const toggleSidebar = () => {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    try { window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next)); }
    catch { /* The sidebar remains usable without browser storage. */ }
  };
  const navigation = (inDrawer = false) => <nav aria-label="工作区" className={`${styles.navigation}${inDrawer ? ` ${styles.drawerNavigation}` : ""}`} id={inDrawer ? "mobile-primary-navigation" : "primary-navigation"}>
    {entries.map(({ label, to, icon: Icon }) => {
      const active = activeEntry?.label === label;
      return <NavLink aria-current={active ? "page" : false} aria-label={label} className={`${styles.navigationLink}${active ? ` ${styles.navigationLinkActive}` : ""}`} end={to === "/"} key={to} onClick={() => setNavigationOpen(false)} title={label} to={to}>
        <span aria-hidden="true" className={styles.navigationMark}><Icon /></span><span className={styles.navigationLabel}>{label}</span>
      </NavLink>;
    })}
  </nav>;
  const connection = (inDrawer = false) => <div className={`${styles.connectionState}${inDrawer ? ` ${styles.drawerConnection}` : ""}`}>
    <span aria-hidden="true" className={styles.avatar}>{principal.display_name.slice(0, 1).toUpperCase()}</span>
    <span className={styles.connectionIdentity}><strong title={principal.display_name}>{principal.display_name}</strong><small>{principal.roles.map(role => roleNames[role] ?? role).join(" / ")}</small></span>
    <Button aria-label={logoutBusy ? "退出中" : "退出"} className={styles.logoutButton} disabled={logoutBusy} icon={<LogOut />} loading={logoutBusy} onClick={onLogout} title="退出登录" variant="quiet">退出</Button>
  </div>;
  const logoutFailure = logoutError && <StatusMessage action={<Button disabled={logoutBusy} loading={logoutBusy} onClick={onLogout} variant="secondary">重试退出</Button>} kind="danger" title="退出没有完成">{logoutError}</StatusMessage>;
  return <>
    <a className={styles.skipLink} href="#main-content">跳到主要内容</a>
    <div className={`app-shell ${styles.shell}${sidebarCollapsed ? ` ${styles.shellCollapsed}` : ""}`} data-product-analytics-source={analyticsSource} data-sidebar-collapsed={sidebarCollapsed || undefined}>
      <aside aria-label="主导航" className={styles.sidebar}>
        <div className={styles.brand}>
          <span aria-hidden="true" className={styles.brandMonogram}>CL</span><span className={styles.brandIdentity}><strong>CLSEN</strong><small>每日数据核验台</small></span>
          <Button aria-expanded={!sidebarCollapsed} aria-label={sidebarCollapsed ? "展开侧栏" : "收起侧栏"} className={styles.desktopSidebarToggle} icon={sidebarCollapsed ? <PanelLeftOpen /> : <PanelLeftClose />} onClick={toggleSidebar} title={sidebarCollapsed ? "展开侧栏" : "收起侧栏"} variant="quiet" />
          <button aria-controls={navigationOpen ? "mobile-primary-navigation" : undefined} aria-expanded={navigationOpen} aria-haspopup="dialog" aria-label="打开主导航" className={styles.mobileNavigationToggle} onClick={() => setNavigationOpen(true)} ref={mobileNavigationToggle} type="button"><Menu aria-hidden="true" /><span>导航</span></button>
        </div>
        {navigation()}
        <div className={styles.boundary}><span className={styles.boundaryLabel}>当前站点</span><strong>{siteContext.display_name}</strong><span>报告日期以站点时区为准</span></div>
        {connection()}
      </aside>
      <div className={styles.workspace}>
        <header className={styles.topbar}><div className={styles.topbarContext}><span>当前工作区</span><p><strong>{siteContext.display_name}</strong><i aria-hidden="true" /><span>{activeEntry?.label ?? "数据工作台"}</span></p></div>
          <div className={styles.topbarMeta}><span aria-live="polite" className={`${styles.connectionIndicator}${online ? ` ${styles.connected}` : ""}`}><i aria-hidden="true" />{online ? "已连接" : "连接不可用"}</span><span className={`topbar__timezone ${styles.topbarTimezone}`}><small>报告时区</small><strong>{siteContext.reporting_timezone}</strong></span></div>
        </header>
        {logoutError && !navigationOpen && <div className={styles.sessionError}>{logoutFailure}</div>}
        {children}
      </div>
    </div>
    <Dialog closeLabel="关闭主导航" contentClassName={styles.navigationDrawer} description={`${siteContext.display_name} · ${principal.roles.map(role => roleNames[role] ?? role).join(" / ")}`} eyebrow="CLSEN" onOpenChange={setNavigationOpen} open={navigationOpen} presentation="drawer" title="工作区导航">
      {navigation(true)}
      <div className={styles.drawerSite}><strong>{siteContext.display_name}</strong><span>报告时区 · {siteContext.reporting_timezone}</span><span aria-live="polite">{online ? "已连接" : "连接不可用"}</span></div>
      {logoutError && <div className={styles.drawerFailure}>{logoutFailure}</div>}
      {connection(true)}
    </Dialog>
  </>;
}
