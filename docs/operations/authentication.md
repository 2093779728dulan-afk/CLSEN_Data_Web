# HTTP 认证与权限边界

阶段 7 的 API 使用同源 Cookie 会话，不把长期访问令牌写入浏览器存储。

- 登录前，页面先请求 `GET /api/auth/csrf`，将响应中的 `csrf_token` 同时作为 `X-CSRF-Token` 请求头提交给 `POST /api/auth/login`。
- 登录成功后，`clsen_session` 是 `HttpOnly; SameSite=Lax` Cookie；前端不应读取、记录或自行拼接该 Cookie。
- 响应中的 `csrf_token` 同时会保存为可读的 `clsen_csrf` Cookie。所有已登录写请求必须带相同的 `X-CSRF-Token`；缺少、不同或已失效时 API 返回 `403 csrf_invalid`。
- 生产/服务器环境必须设置至少 32 字符的随机 `APP_SESSION_SECRET`，并且必须开启 `APP_SESSION_COOKIE_SECURE=true`。开发与测试环境的非 Secure Cookie 仅用于本机 HTTP 调试。
- 会话默认存活 8 小时，服务端只保存不透明随机令牌及 CSRF 令牌的 SHA-256 哈希。登出会撤销服务端会话，旧 Cookie 即使被重放也会被拒绝。
- 登录失败的计数器目前是单个后端进程内的保护，适合本机 MVP。部署多个 FastAPI 实例前，必须将该限速迁移到共享反向代理或共享持久化存储；否则各实例的限速相互独立。

已经初始化、但 `.env` 缺少 `APP_SESSION_SECRET` 的本地环境，不要重跑数据库初始化。直接在项目根目录执行：

```powershell
.\scripts\ensure-local-session-secret.ps1
```

该命令幂等：已有安全值时只收紧并核验 ACL，缺失或仍为公开占位值时才生成 256 位随机值；密钥不会显示在终端。只有明确需要轮换时才加 `-Rotate`。新值被应用加载后（正在运行的应用进程需重启），轮换只会使轮换前签发且尚未使用的登录前 CSRF 令牌失效，不会更改数据库账号密码，也不会自动撤销数据库中已有的登录会话。若轮换场景还要求已登录用户下线，必须另行按授权执行服务端会话撤销流程；本脚本不会执行该操作。

管理员创建用户和重置密码的幂等账本不保存密码哈希、HMAC 或其他可验证密码猜测的材料，只保存固定的“秘密未存储”标记。相同 `Idempotency-Key` 永远返回首次冻结结果，不会再次写入密码；密码输入发生变化时，客户端必须生成新的幂等键。

角色判断在服务端执行：`admin` 可访问管理 API，`data_manager` 和 `viewer` 不可访问管理 API。后续业务路由应使用 `require_roles(...)` 和需要写入时的 `require_csrf_principal`，不得只依赖前端隐藏按钮。

## 数据库升级后必须刷新运行账号权限

`0010_authentication_sessions` 增加了 `auth_sessions` 表。现有本地数据库升级后，运行账号还需要对该表的 `INSERT` 和 `UPDATE` 权限，权限清单已经更新。由管理员在项目根目录用 PowerShell 7 执行：

```powershell
& '.\scripts\init-database.ps1' `
  -AllowExistingPrimaryDatabase `
  -ForceEnvironmentFile `
  -SkipApplicationAdmin
```

该初始化脚本会重新生成专用数据库账号密码并写入受保护的 `.env`，因此执行前必须停止正在使用旧 `.env` 数据库连接的本地服务。它不应在已有服务器环境直接执行；服务器应采用等价的、受审计的迁移和授权流程。
