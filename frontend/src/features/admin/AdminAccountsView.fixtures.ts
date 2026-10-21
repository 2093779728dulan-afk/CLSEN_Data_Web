import type { RoleResponse, UserResponse } from "../../api/generated";
import type { Principal } from "../../api/types";
import type { UserFormState } from "./AdminAccountsView";

export const accountPrincipal: Principal = { id: 88, username: "fictional-admin", display_name: "示例管理员", roles: ["admin"] };
export const accountRoles: RoleResponse[] = [
  { code: "admin", description: "账号、站点配置和内部审计" },
  { code: "data_manager", description: "导入、审核与发布数据" },
  { code: "viewer", description: "查看已发布数据" },
];
export const accountUsers: UserResponse[] = [
  { id: 88, username: "fictional-admin", display_name: "示例管理员", email: null, roles: ["admin"], status: "active", last_login_at: "2026-09-12T06:00:00Z", created_at: "2026-08-01T00:00:00Z", updated_at: "2026-09-12T05:00:00Z" },
  { id: 89, username: "demo-reviewer", display_name: "示例审核人员", email: "reviewer@example.invalid", roles: ["data_manager"], status: "active", last_login_at: null, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-09-12T05:00:00Z" },
  { id: 90, username: "demo-viewer", display_name: "示例查看人员", email: null, roles: ["viewer"], status: "disabled", last_login_at: null, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-09-12T05:00:00Z" },
  { id: 91, username: "demo-locked", display_name: "示例锁定账号", email: null, roles: ["viewer"], status: "locked", last_login_at: null, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-09-12T05:00:00Z" },
];
export const emptyAccountForm: UserFormState = { username: "", displayName: "", email: "", password: "", roles: [], status: "active" };
export function accountForm(user: UserResponse): UserFormState {
  return { username: user.username, displayName: user.display_name, email: user.email ?? "", password: "", roles: [...user.roles], status: user.status };
}
