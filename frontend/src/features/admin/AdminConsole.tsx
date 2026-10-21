import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import { ApiRequestError, requestApi } from "../../api/client";
import type {
  AuditEventPageResponse,
  CreateSiteConfigVersionRequest,
  CreateUserRequest,
  DraftMutationResponse,
  ForceRebuildDraftRequest,
  MaintenanceStatusResponse,
  RoleResponse,
  SiteConfigVersionResponse,
  UpdateUserRequest,
  UserResponse,
  VersionExpectationRequest,
} from "../../api/generated";
import type { Principal } from "../../api/types";
import { AdminAccessBoundary, AdminAccountsView, AdminWorkspaceHeader, type AdminSection, type UserFormState } from "./AdminAccountsView";
import css from "./AdminAccountsView.module.css";
import { StatusMessage } from "../../design-system";
import { AdminAuditView } from "./AdminAuditView";
import { SiteConfigurationView, type SiteFormState } from "./SiteConfigurationView";
import "./AdminConsole.css";
import { AdminRecoveryView } from "./AdminRecoveryView";
import { AdminMaintenanceView } from "./AdminMaintenanceView";


export type AdminForceRebuildContext = {
  batchId: number;
  expectedActiveDraft: VersionExpectationRequest;
  expectedPublicationVersionId: number | null;
  parseBaselineId: number;
  reportDate: string;
  versionId: number;
};

export type AdminConsoleProps = {
  forceRebuildContext?: AdminForceRebuildContext;
  initialSiteId?: number;
  onForceRebuilt?: (result: DraftMutationResponse) => void;
  onSiteConfigCreated?: (config: SiteConfigVersionResponse) => void;
  principal: Principal;
};



const EMPTY_USER_FORM: UserFormState = {
  displayName: "",
  email: "",
  password: "",
  roles: [],
  status: "active",
  username: "",
};

const ADMIN_AUDIT_PAGE_SIZE = 20;

function makeUuid() {
  if (typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}

function readCookie(name: string) {
  const prefix = `${encodeURIComponent(name)}=`;
  const item = document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : undefined;
}

async function adminWrite<T>(
  path: string,
  method: "POST" | "PATCH",
  body: unknown,
  operationKey: string,
) {
  const csrfToken = readCookie("clsen_csrf");
  if (!csrfToken) {
    throw new ApiRequestError(403, "csrf_missing", "当前会话缺少写入凭据，请退出后重新登录。");
  }
  return requestApi<T>(path, {
    body: JSON.stringify(body),
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": operationKey,
      "X-CSRF-Token": csrfToken,
    },
    method,
  });
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "操作未完成，请稍后再试。";
}

function dateTimeLocalValue(instant = new Date()) {
  const local = new Date(instant.getTime() - instant.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function AdminConsole({
  forceRebuildContext,
  initialSiteId = 1,
  onForceRebuilt,
  onSiteConfigCreated,
  principal,
}: AdminConsoleProps) {
  const canAdminister = principal.roles.includes("admin");
  const [section, setSection] = useState<AdminSection>("users");
  const [roles, setRoles] = useState<RoleResponse[]>([]);
  const [users, setUsers] = useState<UserResponse[]>([]);
  const [siteConfigs, setSiteConfigs] = useState<SiteConfigVersionResponse[]>([]);
  const [auditPage, setAuditPage] = useState<AuditEventPageResponse>();
  const [maintenance, setMaintenance] = useState<MaintenanceStatusResponse>();
  const [maintenanceRefreshedAt, setMaintenanceRefreshedAt] = useState<Date>();
  const [maintenanceRefreshing, setMaintenanceRefreshing] = useState(false);
  const [maintenanceRefreshError, setMaintenanceRefreshError] = useState<string | null>(null);
  const [auditOffset, setAuditOffset] = useState(0);
  const [auditType, setAuditType] = useState("");
  const [auditTypeDraft, setAuditTypeDraft] = useState("");
  const [initialLoading, setInitialLoading] = useState(canAdminister);
  const [initialLoadAttempt, setInitialLoadAttempt] = useState(0);
  const [initialLoadFailed, setInitialLoadFailed] = useState(false);
  const [busyAction, setBusyAction] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [error, setError] = useState<string>();

  const [showCreateUser, setShowCreateUser] = useState(false);
  const [createUserForm, setCreateUserForm] = useState<UserFormState>(EMPTY_USER_FORM);
  const createUserKey = useRef<string | undefined>(undefined);

  const [editingUser, setEditingUser] = useState<UserResponse>();
  const [editUserForm, setEditUserForm] = useState<UserFormState>(EMPTY_USER_FORM);
  const updateUserKey = useRef<string | undefined>(undefined);

  const [showCreateSite, setShowCreateSite] = useState(false);
  const [siteForm, setSiteForm] = useState<SiteFormState>({
    changeReason: "",
    currencyCode: "USD",
    effectiveAt: dateTimeLocalValue(),
    reportingTimezone: "America/Los_Angeles",
    siteId: String(initialSiteId),
    sourceTimezone: "America/Los_Angeles",
  });
  const siteConfigKey = useRef<string | undefined>(undefined);

  const [forceReason, setForceReason] = useState("");
  const [forceConfirmed, setForceConfirmed] = useState(false);
  const forceRebuildKey = useRef<string | undefined>(undefined);
  const maintenanceRequestInFlight = useRef(false);

  const loadUsers = useCallback(async () => {
    const nextUsers = await requestApi<UserResponse[]>("/api/admin/users");
    setUsers(nextUsers);
    return nextUsers;
  }, []);

  const loadAudit = useCallback(async (offset: number, eventType = auditType) => {
    const params = new URLSearchParams({
      limit: String(ADMIN_AUDIT_PAGE_SIZE),
      offset: String(offset),
    });
    if (eventType) params.set("event_type", eventType);
    const page = await requestApi<AuditEventPageResponse>(`/api/admin/audit-events?${params.toString()}`);
    setAuditPage(page);
    setAuditOffset(page.offset);
    return page;
  }, [auditType]);

  const loadMaintenance = useCallback(async () => {
    if (maintenanceRequestInFlight.current) return;
    maintenanceRequestInFlight.current = true;
    setMaintenanceRefreshing(true);
    setMaintenanceRefreshError(null);
    try {
      const status = await requestApi<MaintenanceStatusResponse>("/api/admin/maintenance");
      setMaintenance(status);
      setMaintenanceRefreshedAt(new Date());
    } catch (reason) {
      setMaintenanceRefreshError(errorMessage(reason));
    } finally {
      maintenanceRequestInFlight.current = false;
      setMaintenanceRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (section === "maintenance" && maintenance === undefined) {
      void loadMaintenance();
    }
  }, [loadMaintenance, maintenance, section]);

  useEffect(() => {
    if (section !== "maintenance" || maintenance === undefined) return;
    const refreshSeconds = Math.min(
      maintenance.worker.thresholds.refresh_seconds,
      15,
    );
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadMaintenance();
    }, refreshSeconds * 1_000);
    return () => window.clearInterval(timer);
  }, [loadMaintenance, maintenance, section]);

  useEffect(() => {
    if (!canAdminister) {
      setInitialLoading(false);
      return;
    }
    let active = true;
    setInitialLoading(true);
    setInitialLoadFailed(false);
    setError(undefined);
    void Promise.all([
      requestApi<RoleResponse[]>("/api/admin/roles"),
      requestApi<UserResponse[]>("/api/admin/users"),
      requestApi<SiteConfigVersionResponse[]>("/api/admin/site-config-versions"),
      requestApi<AuditEventPageResponse>(`/api/admin/audit-events?limit=${ADMIN_AUDIT_PAGE_SIZE}&offset=0`),
    ]).then(([nextRoles, nextUsers, nextConfigs, nextAudit]) => {
      if (!active) return;
      setRoles(nextRoles);
      setUsers(nextUsers);
      setSiteConfigs(nextConfigs);
      setAuditPage(nextAudit);
    }).catch((reason: unknown) => {
      if (active) { setError(errorMessage(reason)); setInitialLoadFailed(true); }
    }).finally(() => {
      if (active) setInitialLoading(false);
    });
    return () => { active = false; };
  }, [canAdminister, initialLoadAttempt]);

  const currentSiteConfig = useMemo(
    () => siteConfigs.find((config) => config.is_current) ?? siteConfigs[0],
    [siteConfigs],
  );

  const resetCreateKey = () => { createUserKey.current = undefined; };
  const changeCreateUser = (changes: Partial<UserFormState>) => {
    resetCreateKey();
    setCreateUserForm((current) => ({ ...current, ...changes }));
  };

  const submitCreateUser = async (event: FormEvent) => {
    event.preventDefault();
    setBusyAction("create-user");
    setNotice(undefined);
    setError(undefined);
    const payload: CreateUserRequest = {
      display_name: createUserForm.displayName.trim(),
      email: createUserForm.email.trim() || null,
      password: createUserForm.password,
      roles: createUserForm.roles,
      status: createUserForm.status,
      username: createUserForm.username.trim(),
    };
    createUserKey.current ??= makeUuid();
    try {
      const created = await adminWrite<UserResponse>(
        "/api/admin/users",
        "POST",
        payload,
        createUserKey.current,
      );
      setUsers((current) => [...current.filter((user) => user.id !== created.id), created]);
      setCreateUserForm(EMPTY_USER_FORM);
      createUserKey.current = undefined;
      setNotice(`账号 ${created.username} 已创建。`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusyAction(undefined);
    }
  };

  const beginEditUser = (user: UserResponse) => {
    setEditingUser(user);
    setEditUserForm({
      displayName: user.display_name,
      email: user.email ?? "",
      password: "",
      roles: [...user.roles],
      status: user.status,
      username: user.username,
    });
    updateUserKey.current = undefined;
    setError(undefined);
    setNotice(undefined);
  };

  const changeEditUser = (changes: Partial<UserFormState>) => {
    updateUserKey.current = undefined;
    setEditUserForm((current) => ({ ...current, ...changes }));
  };

  const closeEditUser = () => {
    setEditingUser(undefined);
    setEditUserForm(EMPTY_USER_FORM);
    updateUserKey.current = undefined;
  };

  const submitUpdateUser = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingUser) return;
    setBusyAction("update-user");
    setNotice(undefined);
    setError(undefined);
    const payload: UpdateUserRequest = {
      display_name: editUserForm.displayName.trim(),
      email: editUserForm.email.trim() || null,
      expected_updated_at: editingUser.updated_at,
      roles: editUserForm.roles,
      status: editUserForm.status,
      ...(editUserForm.password ? { new_password: editUserForm.password } : {}),
    };
    updateUserKey.current ??= makeUuid();
    try {
      const updated = await adminWrite<UserResponse>(
        `/api/admin/users/${editingUser.id}`,
        "PATCH",
        payload,
        updateUserKey.current,
      );
      setUsers((current) => current.map((user) => user.id === updated.id ? updated : user));
      closeEditUser();
      setNotice(`账号 ${updated.username} 已更新。${editUserForm.password ? "现有会话已撤销。" : ""}`);
    } catch (reason) {
      if (reason instanceof ApiRequestError && reason.code === "user_version_conflict") {
        closeEditUser();
        try {
          await loadUsers();
        } catch (reloadReason) {
          setError(`账号已被其他管理员修改，且最新值载入失败：${errorMessage(reloadReason)}`);
          return;
        }
        setError("账号已被其他管理员修改；已载入最新值，请重新确认后再保存。");
      } else {
        setError(errorMessage(reason));
      }
    } finally {
      setBusyAction(undefined);
    }
  };

  const beginCreateSite = () => {
    setSection("site");
    setShowCreateSite(true);
    setSiteForm({
      changeReason: "",
      currencyCode: currentSiteConfig?.currency_code ?? "USD",
      effectiveAt: dateTimeLocalValue(),
      reportingTimezone: currentSiteConfig?.reporting_timezone ?? "America/Los_Angeles",
      siteId: String(currentSiteConfig?.site_id ?? initialSiteId),
      sourceTimezone: currentSiteConfig?.source_timezone ?? "America/Los_Angeles",
    });
    siteConfigKey.current = undefined;
    setError(undefined);
    setNotice(undefined);
  };

  const changeSiteForm = (changes: Partial<SiteFormState>) => {
    siteConfigKey.current = undefined;
    setSiteForm((current) => ({ ...current, ...changes }));
  };

  const submitSiteConfig = async (event: FormEvent) => {
    event.preventDefault();
    setBusyAction("create-site");
    setError(undefined);
    setNotice(undefined);
    const effective = new Date(siteForm.effectiveAt);
    if (Number.isNaN(effective.getTime())) {
      setBusyAction(undefined);
      setError("请选择有效的生效时间。");
      return;
    }
    const payload: CreateSiteConfigVersionRequest = {
      change_reason: siteForm.changeReason.trim(),
      currency_code: siteForm.currencyCode.trim().toUpperCase(),
      effective_at: effective.toISOString(),
      reporting_timezone: siteForm.reportingTimezone.trim(),
      site_id: Number(siteForm.siteId),
      source_timezone: siteForm.sourceTimezone.trim(),
    };
    siteConfigKey.current ??= makeUuid();
    try {
      const created = await adminWrite<SiteConfigVersionResponse>(
        "/api/admin/site-config-versions",
        "POST",
        payload,
        siteConfigKey.current,
      );
      setSiteConfigs((current) => [
        created,
        ...current
          .filter((config) => config.id !== created.id)
          .map((config) => config.site_id === created.site_id ? { ...config, is_current: false } : config),
      ]);
      setShowCreateSite(false);
      setSiteForm((current) => ({ ...current, changeReason: "" }));
      siteConfigKey.current = undefined;
      setNotice(`站点配置 v${created.version_number} 已创建并设为当前版本。`);
      onSiteConfigCreated?.(created);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusyAction(undefined);
    }
  };

  const submitAuditFilter = async (event: FormEvent) => {
    event.preventDefault();
    setBusyAction("audit");
    setError(undefined);
    const nextType = auditTypeDraft.trim();
    setAuditType(nextType);
    try {
      await loadAudit(0, nextType);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusyAction(undefined);
    }
  };

  const changeAuditPage = async (offset: number) => {
    setBusyAction("audit");
    setError(undefined);
    try {
      await loadAudit(offset);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusyAction(undefined);
    }
  };

  const submitForceRebuild = async (event: FormEvent) => {
    event.preventDefault();
    if (!forceRebuildContext) return;
    setBusyAction("force-rebuild");
    setError(undefined);
    setNotice(undefined);
    const payload: ForceRebuildDraftRequest = {
      batch_id: forceRebuildContext.batchId,
      expected_active_draft: forceRebuildContext.expectedActiveDraft,
      expected_publication_version_id: forceRebuildContext.expectedPublicationVersionId,
      parse_baseline_id: forceRebuildContext.parseBaselineId,
      reason: forceReason.trim(),
      report_date: forceRebuildContext.reportDate,
    };
    forceRebuildKey.current ??= makeUuid();
    try {
      const result = await adminWrite<DraftMutationResponse>(
        `/api/admin/drafts/${forceRebuildContext.versionId}/force-rebuild`,
        "POST",
        payload,
        forceRebuildKey.current,
      );
      setForceReason("");
      setForceConfirmed(false);
      forceRebuildKey.current = undefined;
      setNotice(`草稿已重建为 v${result.version_no}；新草稿仍需重新校验。`);
      onForceRebuilt?.(result);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusyAction(undefined);
    }
  };

  if (!canAdminister) return <AdminAccessBoundary />;

  return (
    <main className={`admin-console ${css.workspace}${section === "maintenance" ? " admin-console--maintenance" : ""}`} id="main-content">
      <AdminWorkspaceHeader principal={principal} section={section} onSectionChange={setSection} />
      {section !== "users" && section !== "site" && section !== "audit" && section !== "recovery" && notice && <StatusMessage kind="success" title="操作结果">{notice}</StatusMessage>}
      {section !== "users" && section !== "site" && section !== "audit" && section !== "recovery" && error && <StatusMessage kind="danger" title="操作未完成">{error}</StatusMessage>}
      {section !== "users" && section !== "site" && section !== "audit" && section !== "recovery" && initialLoading && <p className="admin-console__loading">正在载入权限与审计台账…</p>}
      {section === "users" && <AdminAccountsView users={users} roles={roles} initialLoading={initialLoading} loadFailed={initialLoadFailed} busyAction={busyAction} error={error} notice={notice}
        showCreate={showCreateUser} createForm={createUserForm} editingUser={editingUser} editForm={editUserForm}
        onRetry={() => setInitialLoadAttempt(current => current + 1)}
        onToggleCreate={() => {
          setShowCreateUser((visible) => {
            if (visible) { setCreateUserForm(EMPTY_USER_FORM); createUserKey.current = undefined; }
            return !visible;
          });
          setError(undefined); setNotice(undefined);
        }}
        onCreateChange={changeCreateUser} onCreate={event => { void submitCreateUser(event); }}
        onEdit={beginEditUser} onEditChange={changeEditUser} onCloseEdit={closeEditUser} onUpdate={event => { void submitUpdateUser(event); }}
      />}

      {section === "site" && <SiteConfigurationView configs={siteConfigs} currentConfig={currentSiteConfig} initialLoading={initialLoading} loadFailed={initialLoadFailed} busy={busyAction === "create-site"} error={error} notice={notice}
        showCreate={showCreateSite} form={siteForm} onRetry={() => setInitialLoadAttempt(current => current + 1)}
        onBeginCreate={beginCreateSite} onCancel={() => setShowCreateSite(false)} onChange={changeSiteForm} onCreate={event => { void submitSiteConfig(event); }}
      />}

      {section === "audit" && <AdminAuditView page={auditPage} offset={auditOffset} pageSize={ADMIN_AUDIT_PAGE_SIZE} filter={auditTypeDraft} appliedFilter={auditType}
        initialLoading={initialLoading} loadFailed={initialLoadFailed} busy={busyAction === "audit"} error={error}
        onFilterChange={setAuditTypeDraft} onFilter={event => { void submitAuditFilter(event); }}
        onPage={next => { void changeAuditPage(next); }} onRetry={() => setInitialLoadAttempt(current => current + 1)}
      />}

      {!initialLoading && section === "maintenance" && <AdminMaintenanceView status={maintenance} refreshing={maintenanceRefreshing} refreshError={maintenanceRefreshError}
        pageRefreshedAt={maintenanceRefreshedAt} onRefresh={() => { void loadMaintenance(); }}
      />}

      {section === "recovery" && <AdminRecoveryView context={forceRebuildContext} loading={initialLoading} loadFailed={initialLoadFailed} busy={busyAction === "force-rebuild"} reason={forceReason} confirmed={forceConfirmed} error={error} notice={notice}
        onRetry={() => setInitialLoadAttempt(current => current + 1)}
        onReasonChange={value => { setForceReason(value); forceRebuildKey.current = undefined; }}
        onConfirmedChange={value => { setForceConfirmed(value); forceRebuildKey.current = undefined; }}
        onSubmit={event => { void submitForceRebuild(event); }}
      />}
    </main>
  );
}
