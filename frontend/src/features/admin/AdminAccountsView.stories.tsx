import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { StatusMessage } from "../../design-system";
import { AdminAccessBoundary, AdminAccountsView, AdminWorkspaceHeader, type AdminSection } from "./AdminAccountsView";
import { accountForm, accountPrincipal, accountRoles, accountUsers, emptyAccountForm } from "./AdminAccountsView.fixtures";
import css from "./AdminAccountsView.module.css";

type Scenario = "reference" | "create" | "creating" | "create-failure" | "editing" | "saving" | "edit-failure" | "conflict" | "last-admin-protected" | "loading" | "read-failure" | "empty" | "access-denied" | "updated";
function AccountsPage({ scenario = "reference" }: { scenario?: Scenario }) {
  const [users, setUsers] = useState(scenario === "empty" ? [] : structuredClone(accountUsers).map(user => scenario === "conflict" && user.id === 90 ? { ...user, display_name: "示例其他管理员已修改", updated_at: "2026-09-12T08:00:00Z" } : user));
  const [section, setSection] = useState<AdminSection>("users");
  const [showCreate, setShowCreate] = useState(["create", "creating", "create-failure"].includes(scenario));
  const [createForm, setCreateForm] = useState(["creating", "create-failure"].includes(scenario) ? { ...emptyAccountForm, username: "fictional-colleague", displayName: "示例新同事", password: "Synthetic-only-123!", status: "disabled" as const, roles: ["viewer"] } : { ...emptyAccountForm, roles: [] as string[] });
  const [editingUser, setEditingUser] = useState(["editing", "saving", "edit-failure", "last-admin-protected"].includes(scenario) ? accountUsers[scenario === "last-admin-protected" ? 0 : 2] : undefined);
  const [editForm, setEditForm] = useState(accountForm(accountUsers[scenario === "last-admin-protected" ? 0 : 2]!));
  const [loadFailed, setLoadFailed] = useState(scenario === "read-failure");
  const [error, setError] = useState<string | undefined>(scenario === "create-failure" ? "示例：创建结果暂时无法确认，表单内容已保留。" : scenario === "edit-failure" ? "示例：修改结果暂时无法确认，当前编辑内容已保留。" : scenario === "conflict" ? "账号已被其他管理员修改；已载入最新值，请重新确认后再保存。" : scenario === "last-admin-protected" ? "示例：不能停用或移除最后一个启用的管理员。" : scenario === "read-failure" ? "示例：管理资料暂不可读，请重试。" : undefined);
  const [notice, setNotice] = useState<string | undefined>(scenario === "updated" ? "示例账号已更新，仅更新样板内存。" : undefined);
  if (scenario === "access-denied") return <AdminAccessBoundary />;
  return <main className={css.reference}>
    <AdminWorkspaceHeader principal={accountPrincipal} section={section} onSectionChange={setSection} />
    {section === "users" ? <AdminAccountsView users={users} roles={accountRoles} initialLoading={scenario === "loading"} loadFailed={loadFailed}
      busyAction={scenario === "creating" ? "create-user" : scenario === "saving" ? "update-user" : undefined} error={error} notice={notice}
      showCreate={showCreate} createForm={createForm} editingUser={editingUser} editForm={editForm}
      onRetry={() => { setLoadFailed(false); setError(undefined); }} onToggleCreate={() => { setShowCreate(!showCreate); setCreateForm({ ...emptyAccountForm, roles: [] }); setError(undefined); setNotice(undefined); }}
      onCreateChange={changes => setCreateForm(current => ({ ...current, ...changes }))}
      onCreate={event => { event.preventDefault(); setUsers(current => [...current, { ...accountUsers[2]!, id: 100 + current.length, username: createForm.username.trim(), display_name: createForm.displayName.trim(), email: createForm.email.trim() || null, roles: [...createForm.roles], status: createForm.status }]); setCreateForm({ ...emptyAccountForm, roles: [] }); setError(undefined); setNotice("已创建虚构账号，仅更新样板内存。 "); }}
      onEdit={user => { setEditingUser(user); setEditForm(accountForm(user)); setError(undefined); setNotice(undefined); }}
      onEditChange={changes => setEditForm(current => ({ ...current, ...changes }))} onCloseEdit={() => { setEditingUser(undefined); setEditForm({ ...emptyAccountForm, roles: [] }); }}
      onUpdate={event => { event.preventDefault(); if (!editingUser) return; if (scenario === "last-admin-protected") { setError("示例：不能停用或移除最后一个启用的管理员。"); return; } setUsers(current => current.map(user => user.id === editingUser.id ? { ...user, display_name: editForm.displayName, email: editForm.email.trim() || null, roles: [...editForm.roles], status: editForm.status } : user)); setEditingUser(undefined); setError(undefined); setNotice("已更新虚构账号，仅更新样板内存。 "); }}
    /> : <StatusMessage kind="info" title="此批样板仅覆盖账号与角色">已选中“{({ site: "站点配置", audit: "内部审计", maintenance: "备份与任务", recovery: "草稿恢复" } as Record<string, string>)[section]}”。可返回“账号与角色”继续体验；实际页面保留对应功能。</StatusMessage>}
    <p className={css.disclaimer}>账号、角色记录及状态均为虚构。创建和编辑只更新样板内存，不请求 API，不创建真实账号或修改真实权限；密码不会展示在台账中。</p>
  </main>;
}
const meta = { title: "Pages/Admin Accounts", component: AccountsPage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof AccountsPage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Create: Story = { args: { scenario: "create" } };
export const Creating: Story = { args: { scenario: "creating" } };
export const CreateFailure: Story = { args: { scenario: "create-failure" } };
export const Editing: Story = { args: { scenario: "editing" } };
export const Saving: Story = { args: { scenario: "saving" } };
export const EditFailure: Story = { args: { scenario: "edit-failure" } };
export const Conflict: Story = { args: { scenario: "conflict" } };
export const LastAdminProtected: Story = { args: { scenario: "last-admin-protected" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const AccessDenied: Story = { args: { scenario: "access-denied" } };
export const Updated: Story = { args: { scenario: "updated" } };
