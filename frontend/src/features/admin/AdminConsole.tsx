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
  AuditEventResponse,
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
import "./AdminConsole.css";
import { WorkerObservabilityPanel } from "./WorkerObservabilityPanel";

type AdminSection = "users" | "site" | "audit" | "maintenance" | "recovery";
type UserStatus = UserResponse["status"];

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

type UserFormState = {
  displayName: string;
  email: string;
  password: string;
  roles: string[];
  status: UserStatus;
  username: string;
};

type SiteFormState = {
  changeReason: string;
  currencyCode: string;
  effectiveAt: string;
  reportingTimezone: string;
  siteId: string;
  sourceTimezone: string;
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
const SENSITIVE_AUDIT_KEY = /(?:order|tracking|license|customer|message|订单|物流|牌照|客户|留言)/iu;

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

function formatTimestamp(value: string | null) {
  if (!value) return "—";
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    hour12: false,
    timeStyle: "short",
  }).format(instant);
}

function dateTimeLocalValue(instant = new Date()) {
  const local = new Date(instant.getTime() - instant.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function safeAuditValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(safeAuditValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !SENSITIVE_AUDIT_KEY.test(key))
        .map(([key, item]) => [key, safeAuditValue(item)]),
    );
  }
  return value;
}

function roleLabel(code: string) {
  if (code === "admin") return "管理员";
  if (code === "data_manager") return "数据管理员";
  if (code === "viewer") return "查看人员";
  return code;
}

function statusLabel(status: UserStatus) {
  if (status === "active") return "启用";
  if (status === "disabled") return "停用";
  return "已锁定";
}

function UserRoleFields({
  disabled,
  onChange,
  roles,
  selected,
}: {
  disabled: boolean;
  onChange: (roles: string[]) => void;
  roles: RoleResponse[];
  selected: string[];
}) {
  return (
    <fieldset className="admin-console__role-fieldset" disabled={disabled}>
      <legend>角色</legend>
      <div className="admin-console__role-options">
        {roles.map((role) => (
          <label key={role.code}>
            <input
              aria-label={roleLabel(role.code)}
              checked={selected.includes(role.code)}
              onChange={(event) => {
                onChange(event.target.checked
                  ? [...selected, role.code]
                  : selected.filter((code) => code !== role.code));
              }}
              type="checkbox"
            />
            <span><strong>{roleLabel(role.code)}</strong><small>{role.description}</small></span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function UserLedger({
  busy,
  onEdit,
  users,
}: {
  busy: boolean;
  onEdit: (user: UserResponse) => void;
  users: UserResponse[];
}) {
  return (
    <div className="admin-console__user-ledger">
      <div className="admin-console__ledger-head" aria-hidden="true">
        <span>账号</span><span>权限</span><span>状态 / 最近登录</span><span>操作</span>
      </div>
      {users.map((user) => (
        <article className="admin-console__user-row" key={user.id}>
          <div>
            <strong>{user.display_name}</strong>
            <span className="admin-console__mono">@{user.username}</span>
            <small>{user.email ?? "未设置邮箱"}</small>
          </div>
          <div className="admin-console__chips">
            {user.roles.map((role) => <span key={role}>{roleLabel(role)}</span>)}
          </div>
          <div>
            <span className={`admin-console__status admin-console__status--${user.status}`}>
              {statusLabel(user.status)}
            </span>
            <small>最近登录 · {formatTimestamp(user.last_login_at)}</small>
          </div>
          <button
            aria-label={`编辑 ${user.username}`}
            className="admin-console__text-action"
            disabled={busy}
            onClick={() => onEdit(user)}
            type="button"
          >
            编辑
          </button>
        </article>
      ))}
      {users.length === 0 && <p className="admin-console__empty">还没有可管理的账号。</p>}
    </div>
  );
}

function AuditLedger({ items }: { items: AuditEventResponse[] }) {
  return (
    <ol className="admin-console__audit-ledger">
      {items.map((item) => (
        <li key={item.id}>
          <span className="admin-console__audit-node" aria-hidden="true" />
          <article>
            <header>
              <div>
                <strong>{item.event_type}</strong>
                <span>{item.actor_username ?? "系统"} · {formatTimestamp(item.occurred_at)}</span>
              </div>
              <code>#{item.id}</code>
            </header>
            <dl>
              <div><dt>对象</dt><dd>{item.object_type} {item.object_id ? `#${item.object_id}` : ""}</dd></div>
              <div><dt>站点</dt><dd>{item.site_id ?? "—"}</dd></div>
              <div><dt>请求</dt><dd>{item.request_id ?? "—"}</dd></div>
            </dl>
            {Object.keys(item.redacted_payload).length > 0 && (
              <pre>{JSON.stringify(safeAuditValue(item.redacted_payload), null, 2)}</pre>
            )}
          </article>
        </li>
      ))}
      {items.length === 0 && <li className="admin-console__empty">当前筛选条件下没有审计记录。</li>}
    </ol>
  );
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
      if (active) setError(errorMessage(reason));
    }).finally(() => {
      if (active) setInitialLoading(false);
    });
    return () => { active = false; };
  }, [canAdminister]);

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

  if (!canAdminister) {
    return (
      <section className="admin-console admin-console--boundary" aria-labelledby="admin-boundary-title">
        <span className="admin-console__boundary-mark" aria-hidden="true">锁</span>
        <div>
          <p className="admin-console__kicker">ADMIN BOUNDARY</p>
          <h1 id="admin-boundary-title">管理员权限边界</h1>
          <p>当前账号不能读取用户、站点配置或内部审计。</p>
        </div>
      </section>
    );
  }

  return (
    <main className={`admin-console${section === "maintenance" ? " admin-console--maintenance" : ""}`} id="main-content">
      <header className={`admin-console__hero${section === "maintenance" ? " admin-console__hero--compact" : ""}`}>
        <div>
          <p className="admin-console__kicker">ACCESS &amp; EVIDENCE CONTROL</p>
          <h1>管理员控制台</h1>
          <p>账号、时区口径和审计记录都以可追溯版本维护。密码只在本次表单提交中使用，不会回显。</p>
        </div>
        <aside aria-label="当前管理边界" className="admin-console__scope-card">
          <span>当前权限</span>
          <strong>{principal.display_name}</strong>
          <small>admin · 全部站点管理能力</small>
        </aside>
      </header>

      <nav aria-label="管理员功能" className="admin-console__tabs">
        {([
          ["users", "账号与角色"],
          ["site", "站点配置"],
          ["audit", "内部审计"],
          ["maintenance", "备份与任务"],
          ["recovery", "草稿恢复"],
        ] as const).map(([value, label]) => (
          <button
            aria-current={section === value ? "page" : undefined}
            key={value}
            onClick={() => setSection(value)}
            type="button"
          >
            {label}
          </button>
        ))}
      </nav>

      {notice && <p className="admin-console__notice" aria-live="polite">{notice}</p>}
      {error && <p className="admin-console__error" role="alert">{error}</p>}
      {initialLoading && <p className="admin-console__loading">正在载入权限与审计台账…</p>}

      {!initialLoading && section === "users" && (
        <section className="admin-console__panel" aria-labelledby="admin-users-title">
          <header className="admin-console__panel-heading">
            <div><p>ACCOUNT LEDGER</p><h2 id="admin-users-title">账号与角色</h2></div>
            <button className="admin-console__primary" onClick={() => {
              setShowCreateUser((visible) => {
                if (visible) {
                  setCreateUserForm(EMPTY_USER_FORM);
                  createUserKey.current = undefined;
                }
                return !visible;
              });
              setError(undefined);
              setNotice(undefined);
            }} type="button">{showCreateUser ? "收起创建表单" : "新建账号"}</button>
          </header>

          {showCreateUser && (
            <form aria-label="创建账号" className="admin-console__form" onSubmit={(event) => { void submitCreateUser(event); }}>
              <div className="admin-console__form-heading">
                <div><span>NEW ACCOUNT</span><h3>创建账号</h3></div>
                <p>至少分配一个角色；临时密码不少于 12 位。</p>
              </div>
              <div className="admin-console__field-grid">
                <label>账号<input autoComplete="off" onChange={(event) => changeCreateUser({ username: event.target.value })} required value={createUserForm.username} /></label>
                <label>显示名<input onChange={(event) => changeCreateUser({ displayName: event.target.value })} required value={createUserForm.displayName} /></label>
                <label>邮箱（可选）<input autoComplete="off" onChange={(event) => changeCreateUser({ email: event.target.value })} type="email" value={createUserForm.email} /></label>
                <label>临时密码<input autoComplete="new-password" minLength={12} onChange={(event) => changeCreateUser({ password: event.target.value })} required type="password" value={createUserForm.password} /></label>
                <label>账号状态<select onChange={(event) => changeCreateUser({ status: event.target.value as UserStatus })} value={createUserForm.status}><option value="active">启用</option><option value="disabled">停用</option><option value="locked">锁定</option></select></label>
              </div>
              <UserRoleFields disabled={busyAction === "create-user"} onChange={(nextRoles) => changeCreateUser({ roles: nextRoles })} roles={roles} selected={createUserForm.roles} />
              <button className="admin-console__primary" disabled={busyAction === "create-user" || createUserForm.roles.length === 0} type="submit">{busyAction === "create-user" ? "正在创建…" : "创建账号"}</button>
            </form>
          )}

          <UserLedger busy={busyAction !== undefined} onEdit={beginEditUser} users={users} />

          {editingUser && (
            <div className="admin-console__dialog-layer" role="presentation">
              <form aria-label={`编辑 ${editingUser.username}`} className="admin-console__dialog" onSubmit={(event) => { void submitUpdateUser(event); }}>
                <header><div><span>ACCOUNT #{editingUser.id}</span><h3>编辑 @{editingUser.username}</h3></div><button aria-label="关闭账号编辑" onClick={closeEditUser} type="button">×</button></header>
                <label>显示名<input onChange={(event) => changeEditUser({ displayName: event.target.value })} required value={editUserForm.displayName} /></label>
                <label>邮箱（可选）<input onChange={(event) => changeEditUser({ email: event.target.value })} type="email" value={editUserForm.email} /></label>
                <label>账号状态<select onChange={(event) => changeEditUser({ status: event.target.value as UserStatus })} value={editUserForm.status}><option value="active">启用</option><option value="disabled">停用</option><option value="locked">锁定</option></select></label>
                <label>新密码（留空则不修改）<input autoComplete="new-password" minLength={12} onChange={(event) => changeEditUser({ password: event.target.value })} type="password" value={editUserForm.password} /></label>
                <UserRoleFields disabled={busyAction === "update-user"} onChange={(nextRoles) => changeEditUser({ roles: nextRoles })} roles={roles} selected={editUserForm.roles} />
                <p className="admin-console__form-note">密码重置或停用账号会撤销该账号的现有会话。</p>
                <footer><button className="admin-console__secondary" onClick={closeEditUser} type="button">取消</button><button className="admin-console__primary" disabled={busyAction === "update-user" || editUserForm.roles.length === 0} type="submit">{busyAction === "update-user" ? "正在保存…" : "保存账号修改"}</button></footer>
              </form>
            </div>
          )}
        </section>
      )}

      {!initialLoading && section === "site" && (
        <section className="admin-console__panel" aria-labelledby="admin-site-title">
          <header className="admin-console__panel-heading">
            <div><p>VERSIONED REPORTING RULES</p><h2 id="admin-site-title">站点配置版本</h2></div>
            <button className="admin-console__primary" onClick={beginCreateSite} type="button">新建配置版本</button>
          </header>
          {currentSiteConfig && (
            <article className="admin-console__current-config">
              <span className="admin-console__config-seal">CURRENT</span>
              <div><small>{currentSiteConfig.site_display_name}</small><strong>v{currentSiteConfig.version_number}</strong></div>
              <dl>
                <div><dt>源时区</dt><dd>{currentSiteConfig.source_timezone}</dd></div>
                <div><dt>统计时区</dt><dd>{currentSiteConfig.reporting_timezone}</dd></div>
                <div><dt>币种</dt><dd>{currentSiteConfig.currency_code}</dd></div>
                <div><dt>生效时间</dt><dd>{formatTimestamp(currentSiteConfig.effective_at)}</dd></div>
              </dl>
            </article>
          )}
          {showCreateSite && (
            <form aria-label="创建站点配置版本" className="admin-console__form" onSubmit={(event) => { void submitSiteConfig(event); }}>
              <div className="admin-console__form-heading"><div><span>NEW CONFIG VERSION</span><h3>创建站点配置版本</h3></div><p>保存后成为当前版本，旧版本永久保留。</p></div>
              <div className="admin-console__field-grid">
                <label>站点 ID<input min={1} onChange={(event) => changeSiteForm({ siteId: event.target.value })} required type="number" value={siteForm.siteId} /></label>
                <label>源时区<input onChange={(event) => changeSiteForm({ sourceTimezone: event.target.value })} required value={siteForm.sourceTimezone} /></label>
                <label>统计时区<input onChange={(event) => changeSiteForm({ reportingTimezone: event.target.value })} required value={siteForm.reportingTimezone} /></label>
                <label>币种<input maxLength={3} minLength={3} onChange={(event) => changeSiteForm({ currencyCode: event.target.value })} required value={siteForm.currencyCode} /></label>
                <label>生效时间（本机时区）<input onChange={(event) => changeSiteForm({ effectiveAt: event.target.value })} required type="datetime-local" value={siteForm.effectiveAt} /></label>
                <label className="admin-console__field-wide">变更原因<textarea onChange={(event) => changeSiteForm({ changeReason: event.target.value })} required rows={3} value={siteForm.changeReason} /></label>
              </div>
              <div className="admin-console__form-actions"><button className="admin-console__secondary" onClick={() => setShowCreateSite(false)} type="button">取消</button><button className="admin-console__primary" disabled={busyAction === "create-site"} type="submit">{busyAction === "create-site" ? "正在创建…" : "创建配置版本"}</button></div>
            </form>
          )}
          <ol className="admin-console__config-history">
            {siteConfigs.map((config) => (
              <li className={config.is_current ? "admin-console__config-history--current" : ""} key={config.id}>
                <span>v{config.version_number}</span>
                <div><strong>{config.change_reason ?? "未填写变更原因"}</strong><small>{config.source_timezone} → {config.reporting_timezone} · {config.currency_code}</small></div>
                <time dateTime={config.created_at}>{formatTimestamp(config.created_at)}</time>
              </li>
            ))}
          </ol>
        </section>
      )}

      {!initialLoading && section === "audit" && (
        <section className="admin-console__panel" aria-labelledby="admin-audit-title">
          <header className="admin-console__panel-heading">
            <div><p>APPEND-ONLY EVIDENCE</p><h2 id="admin-audit-title">内部审计</h2></div>
            <span className="admin-console__count">{auditPage?.total ?? 0} 条记录</span>
          </header>
          <form aria-label="筛选审计记录" className="admin-console__audit-filter" onSubmit={(event) => { void submitAuditFilter(event); }}>
            <label>事件类型<input onChange={(event) => setAuditTypeDraft(event.target.value)} placeholder="例如 admin.user_updated" value={auditTypeDraft} /></label>
            <button className="admin-console__secondary" disabled={busyAction === "audit"} type="submit">应用筛选</button>
          </form>
          <p className="admin-console__privacy-note">这里只展示服务端脱敏后的管理事件，不提供原始订单号、物流牌照或客户留言。</p>
          <AuditLedger items={auditPage?.items ?? []} />
          <nav aria-label="审计分页" className="admin-console__pagination">
            <button className="admin-console__secondary" disabled={busyAction === "audit" || auditOffset === 0} onClick={() => { void changeAuditPage(Math.max(0, auditOffset - ADMIN_AUDIT_PAGE_SIZE)); }} type="button">上一页</button>
            <span>第 {Math.floor(auditOffset / ADMIN_AUDIT_PAGE_SIZE) + 1} 页</span>
            <button className="admin-console__secondary" disabled={busyAction === "audit" || auditPage?.next_offset == null} onClick={() => { if (auditPage?.next_offset != null) void changeAuditPage(auditPage.next_offset); }} type="button">下一页</button>
          </nav>
        </section>
      )}

      {!initialLoading && section === "maintenance" && (
        <section aria-label="备份与后台任务" className="admin-console__panel admin-console__panel--maintenance">
          {maintenance ? (
            <>
              <WorkerObservabilityPanel
                onRefresh={() => { void loadMaintenance(); }}
                pageRefreshedAt={maintenanceRefreshedAt ?? new Date(maintenance.observed_at)}
                refreshError={maintenanceRefreshError}
                refreshing={maintenanceRefreshing}
                status={maintenance}
              />
              <section aria-labelledby="maintenance-summary-title" className="admin-console__maintenance-summary">
                <header className="admin-console__maintenance-summary-heading">
                  <div><span>LOCAL SAFEGUARDS</span><h3 id="maintenance-summary-title">备份与后台任务</h3></div>
                  <p>状态只读 · 操作留在本机</p>
                </header>
                <div className="admin-console__maintenance-metrics">
                  <article className={maintenance.write_lock.warning ? "admin-console__metric admin-console__metric--danger" : "admin-console__metric"}><span>写屏障</span><strong>{maintenance.write_lock.held ? "维护中" : "空闲"}</strong><small>{maintenance.write_lock.held ? `已连续观测 ${Math.round(maintenance.write_lock.observed_seconds)} 秒` : "读写服务正常"}</small></article>
                  <article className={maintenance.outbox.failed ? "admin-console__metric admin-console__metric--danger" : "admin-console__metric"}><span>后台任务</span><strong>{maintenance.outbox.pending + maintenance.outbox.processing}</strong><small>待处理 {maintenance.outbox.pending} · 失败 {maintenance.outbox.failed}</small></article>
                  <article className="admin-console__metric"><span>成功备份</span><strong>{maintenance.backups.filter((item) => item.status === "succeeded").length}</strong><small>此处显示最近 20 次</small></article>
                  <article className="admin-console__metric"><span>恢复演练</span><strong>{maintenance.restores.filter((item) => item.status === "succeeded").length}</strong><small>最近成功记录</small></article>
                </div>
                <p className="admin-console__privacy-note">页面只展示状态和不可逆标识。创建备份、密钥轮换和隔离恢复仍通过本机受保护脚本执行，不会把数据库凭据或密钥传到浏览器。</p>
                <div className="admin-console__maintenance-grid">
                  <section><h3>最近备份</h3><ol className="admin-console__maintenance-list">{maintenance.backups.map((item) => <li key={item.id}><div><strong>{item.status === "succeeded" ? "成功" : item.status}</strong><code>{item.backup_uuid.slice(0, 12)}</code></div><span>{formatTimestamp(item.completed_at ?? item.started_at)}</span><small>{item.raw_file_count} 个原始对象 · {item.publication_count} 个发布指针 · schema {item.schema_revision}{item.failure_code ? ` · ${item.failure_code}` : ""}</small><em>{item.restore_verified_at ? `已恢复验证 ${formatTimestamp(item.restore_verified_at)}` : "尚未恢复演练"}</em></li>)}{maintenance.backups.length === 0 && <li className="admin-console__empty">尚无备份记录。运行本机备份脚本后，记录会显示在这里。</li>}</ol></section>
                  <section><h3>最近恢复验证</h3><ol className="admin-console__maintenance-list">{maintenance.restores.map((item) => <li key={item.id}><div><strong>{item.status === "succeeded" ? "成功" : item.status}</strong><code>{item.verification_uuid.slice(0, 12)}</code></div><span>{formatTimestamp(item.completed_at ?? item.started_at)}</span><small>{item.target_database_name}</small>{item.failure_code && <em>{item.failure_code}</em>}</li>)}{maintenance.restores.length === 0 && <li className="admin-console__empty">尚无恢复验证记录。完成隔离恢复演练后，结果会显示在这里。</li>}</ol></section>
                </div>
              </section>
            </>
          ) : maintenanceRefreshing
            ? <p className="admin-console__loading">正在载入维护与 Worker 状态…</p>
            : <p className="admin-console__empty">维护状态尚未载入。{maintenanceRefreshError ? ` ${maintenanceRefreshError}` : ""}</p>}
        </section>
      )}

      {!initialLoading && section === "recovery" && (
        <section className="admin-console__panel" aria-labelledby="admin-recovery-title">
          <header className="admin-console__panel-heading"><div><p>CONTROLLED REBUILD</p><h2 id="admin-recovery-title">草稿强制重建</h2></div></header>
          {forceRebuildContext ? (
            <form aria-label="强制重建草稿" className="admin-console__danger-zone" onSubmit={(event) => { void submitForceRebuild(event); }}>
              <div><span>管理员专用</span><h3>重建 v{forceRebuildContext.expectedActiveDraft.version_id} 的活动草稿</h3><p>{forceRebuildContext.reportDate} · 旧草稿将被废弃，新草稿必须重新完成校验和人工确认。</p></div>
              <label>重建原因<textarea onChange={(event) => { setForceReason(event.target.value); forceRebuildKey.current = undefined; }} required rows={3} value={forceReason} /></label>
              <label className="admin-console__confirm-check"><input checked={forceConfirmed} onChange={(event) => { setForceConfirmed(event.target.checked); forceRebuildKey.current = undefined; }} type="checkbox" />我确认不会绕过校验，也不会覆盖已发布版本。</label>
              <button className="admin-console__danger-action" disabled={!forceConfirmed || !forceReason.trim() || busyAction === "force-rebuild"} type="submit">{busyAction === "force-rebuild" ? "正在重建…" : "强制重建草稿"}</button>
            </form>
          ) : (
            <div className="admin-console__context-required">
              <strong>强制重建从导入冲突进入</strong>
              <p>为避免手工输入版本、解析基线或发布指针，此处不会接受自由填写的数据库 ID。请在“数据审核”中上传并解析新原表；目标日期已有活动草稿时，管理员会看到经过服务器预览的“强制重建活动草稿”选项。</p>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
