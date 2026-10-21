import type { FormEvent } from "react";
import { Pencil, UserPlus } from "lucide-react";
import type { RoleResponse, UserResponse } from "../../api/generated";
import type { Principal } from "../../api/types";
import { Button, Checkbox, Dialog, EmptyState, FormField, Input, PageHeader, Select, Skeleton, StatusBadge, StatusMessage, Table } from "../../design-system";
import css from "./AdminAccountsView.module.css";

export type AdminSection = "users" | "site" | "audit" | "maintenance" | "recovery";
export type UserFormState = {
  displayName: string; email: string; password: string; roles: string[];
  status: UserResponse["status"]; username: string;
};

function roleLabel(code: string) {
  return ({ admin: "管理员", data_manager: "数据管理员", viewer: "查看人员" } as Record<string, string>)[code] ?? code;
}
function lastLogin(value: string | null) {
  if (!value) return "—";
  const instant = new Date(value);
  return Number.isNaN(instant.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", hour12: false, timeStyle: "short" }).format(instant);
}
function AccountStatus({ user }: { user: UserResponse }) {
  return <StatusBadge label={user.status === "active" ? "启用" : user.status === "disabled" ? "停用" : "已锁定"} tone={user.status === "active" ? "good" : user.status === "disabled" ? "quiet" : "warn"} />;
}
function RoleChoices({ roles, selected, disabled, onChange }: { roles: RoleResponse[]; selected: string[]; disabled: boolean; onChange: (roles: string[]) => void }) {
  return <fieldset className={css.roleFieldset} disabled={disabled}><legend>角色</legend><p className={css.hint}>至少选择一个角色，可组合分配。</p><div className={css.roles}>
    {roles.map(role => <Checkbox key={role.code} checked={selected.includes(role.code)} label={roleLabel(role.code)} description={role.description}
      onChange={event => onChange(event.target.checked ? [...selected, role.code] : selected.filter(code => code !== role.code))} />)}
  </div></fieldset>;
}
function AccountFields({ form, editing, busy, onChange }: { form: UserFormState; editing: boolean; busy: boolean; onChange: (changes: Partial<UserFormState>) => void }) {
  return <fieldset className={css.fields} disabled={busy}>
    <legend className={css.srOnly}>{editing ? "编辑账号信息" : "创建账号信息"}</legend>
    {!editing && <FormField label="账号" required><Input autoComplete="off" required value={form.username} onChange={event => onChange({ username: event.target.value })} /></FormField>}
    <FormField label="显示名" required><Input required value={form.displayName} onChange={event => onChange({ displayName: event.target.value })} /></FormField>
    <FormField label="邮箱（可选）"><Input autoComplete="off" type="email" value={form.email} onChange={event => onChange({ email: event.target.value })} /></FormField>
    <FormField label="账号状态"><Select value={form.status} onChange={event => onChange({ status: event.target.value as UserResponse["status"] })}><option value="active">启用</option><option value="disabled">停用</option><option value="locked">锁定</option></Select></FormField>
    <FormField label={editing ? "新密码（留空则不修改）" : "临时密码"} required={!editing} hint={editing ? "留空保留原密码；设置新密码会撤销现有会话。" : "至少 12 位，仅在本次提交中使用，不会回显。"}>
      <Input autoComplete="new-password" minLength={12} required={!editing} type="password" value={form.password} onChange={event => onChange({ password: event.target.value })} />
    </FormField>
  </fieldset>;
}

export function AdminAccessBoundary() {
  return <section className={css.boundary}><PageHeader eyebrow="访问权限" title="管理员权限边界" description="当前账号不能读取用户、站点配置或内部审计。" /><StatusMessage kind="warning" title="需要管理员权限">请使用已有管理员账号进入控制台。</StatusMessage></section>;
}
export function AdminWorkspaceHeader({ principal, section, onSectionChange }: { principal: Principal; section: AdminSection; onSectionChange: (section: AdminSection) => void }) {
  return <>
    <PageHeader eyebrow="系统管理" title="管理员控制台" description="管理账号、报告口径与审核记录。每次变更保留历史。"
      actions={<aside aria-label="当前管理边界" className={css.operator}><StatusBadge label="管理员" tone="quiet" /><strong>{principal.display_name}</strong></aside>} />
    <nav aria-label="管理员功能" className={css.navigation}>{([ ["users", "账号与角色"], ["site", "站点配置"], ["audit", "内部审计"], ["maintenance", "备份与任务"], ["recovery", "草稿恢复"] ] as const).map(([value, label]) =>
      <Button key={value} type="button" variant={section === value ? "secondary" : "quiet"} aria-current={section === value ? "page" : undefined} onClick={() => onSectionChange(value)}>{label}</Button>)}</nav>
  </>;
}

export type AdminAccountsViewProps = {
  users: UserResponse[]; roles: RoleResponse[]; initialLoading: boolean; loadFailed: boolean; busyAction?: string; error?: string; notice?: string;
  showCreate: boolean; createForm: UserFormState; editingUser?: UserResponse; editForm: UserFormState;
  onRetry: () => void; onToggleCreate: () => void; onCreateChange: (changes: Partial<UserFormState>) => void; onCreate: (event: FormEvent) => void;
  onEdit: (user: UserResponse) => void; onEditChange: (changes: Partial<UserFormState>) => void; onCloseEdit: () => void; onUpdate: (event: FormEvent) => void;
};
export function AdminAccountsView({ users, roles, initialLoading, loadFailed, busyAction, error, notice, showCreate, createForm, editingUser, editForm, onRetry, onToggleCreate, onCreateChange, onCreate, onEdit, onEditChange, onCloseEdit, onUpdate }: AdminAccountsViewProps) {
  const createBusy = busyAction === "create-user"; const updateBusy = busyAction === "update-user";
  const errorMessage = error && <StatusMessage kind="danger" title={editingUser ? "账号修改未完成" : loadFailed ? "管理资料读取未完成" : "账号操作未完成"}
    action={loadFailed ? <Button variant="secondary" type="button" onClick={onRetry}>重新载入管理资料</Button> : undefined}>{error}</StatusMessage>;
  const editAction = (user: UserResponse) => <Button aria-label={`编辑 ${user.username}`} icon={<Pencil />} variant="quiet" disabled={busyAction !== undefined} type="button" onClick={() => onEdit(user)}>编辑</Button>;
  const roleBadges = (user: UserResponse) => <div className={css.badges}>{user.roles.map(role => <StatusBadge key={role} label={roleLabel(role)} tone="quiet" />)}</div>;
  return <section aria-label="账号与角色管理" className={css.accounts}>
    <header className={css.heading}><div><p className={css.kicker}>账号台账</p><h2>账号与角色</h2><p>按职责分配权限，停用账号仍保留历史。</p></div><Button icon={<UserPlus />} disabled={initialLoading || loadFailed || busyAction !== undefined} onClick={onToggleCreate} type="button">{showCreate ? "收起创建表单" : "新建账号"}</Button></header>
    {!editingUser && errorMessage}
    {notice && <StatusMessage kind="success" title="账号操作结果">{notice}</StatusMessage>}
    {initialLoading ? <div role="status" aria-label="正在载入权限与审计台账"><Skeleton lines={4} /></div> : !loadFailed && <>
      {showCreate && <form aria-label="创建账号" className={css.createForm} onSubmit={onCreate}>
        <header><h3>创建账号</h3><p className={css.hint}>至少分配一个角色；临时密码不少于 12 位。</p></header>
        <AccountFields form={createForm} editing={false} busy={createBusy} onChange={onCreateChange} />
        <RoleChoices disabled={createBusy} roles={roles} selected={createForm.roles} onChange={selected => onCreateChange({ roles: selected })} />
        <div className={css.actions}><Button loading={createBusy} disabled={createBusy || createForm.roles.length === 0} type="submit">{createBusy ? "正在创建…" : "创建账号"}</Button></div>
      </form>}
      {users.length === 0 ? <EmptyState title="还没有可管理的账号。" description="使用“新建账号”为同事分配角色。" /> : <>
        <div className={css.ledgerHeading}><strong>{users.length} 个账号</strong><span>账号名固定；密码不在台账中展示。</span></div>
        <Table className={css.ledger} role="table" aria-label="账号台账"><thead role="rowgroup"><tr role="row"><th role="columnheader" scope="col">账号</th><th role="columnheader" scope="col">权限</th><th role="columnheader" scope="col">状态 / 最近登录</th><th role="columnheader" scope="col">操作</th></tr></thead><tbody role="rowgroup">{users.map(user => <tr role="row" key={user.id}>
          <td role="cell"><div className={css.identity}><strong>{user.display_name}</strong><code>@{user.username}</code><span>{user.email ?? "未设置邮箱"}</span></div></td><td role="cell">{roleBadges(user)}</td><td role="cell"><div className={css.identity}><AccountStatus user={user} /><span>最近登录 · {lastLogin(user.last_login_at)}</span></div></td><td role="cell">{editAction(user)}</td>
        </tr>)}</tbody></Table>
      </>}
    </>}
    <Dialog open={editingUser !== undefined} onOpenChange={open => { if (!open) onCloseEdit(); }} title={`编辑 @${editingUser?.username ?? ""}`} eyebrow={`账号 #${editingUser?.id ?? ""}`} description="修改显示信息、状态和角色。账号名保持不变。" closeLabel="关闭账号编辑" size="large">
      {editingUser && <form aria-label={`编辑 ${editingUser.username}`} className={css.editForm} onSubmit={onUpdate}>
        <AccountFields form={editForm} editing busy={updateBusy} onChange={onEditChange} />
        <RoleChoices roles={roles} disabled={updateBusy} selected={editForm.roles} onChange={selected => onEditChange({ roles: selected })} />
        <p className={css.hint}>密码重置或停用账号会撤销该账号的现有会话。</p>
        {errorMessage}
        <div className={css.actions}><Button variant="quiet" type="button" onClick={onCloseEdit}>取消</Button><Button loading={updateBusy} disabled={updateBusy || editForm.roles.length === 0} type="submit">{updateBusy ? "正在保存…" : "保存账号修改"}</Button></div>
      </form>}
    </Dialog>
  </section>;
}
