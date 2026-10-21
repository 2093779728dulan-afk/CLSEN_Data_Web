# 每日数据审核与可视化平台实施计划

日期：2026-08-06

对应设计：[每日数据审核与可视化平台设计规格](../specs/2026-08-06-daily-data-review-platform-design.md)

状态：设计与实施计划已确认；阶段 4 全量门禁及阶段 5 本地 MySQL 8.0 专项验收已完成；阶段 5 的 MySQL 8.4 由 PR 兼容矩阵 CI 验证；阶段 8–9 的本地功能范围、隔离 MySQL 全量门禁和体验数据已完成；阶段 10A 已在本地测试库完成真实加密备份和随机隔离恢复演练，本地 MVP 功能范围完成。阶段 10B 已在本机 Docker Engine 29.6.2、Compose 5.3.1 中完成 MySQL 8.4.11 容器、镜像、迁移往返、HTTPS、完整分组、20 读 1 写一致性和加密备份恢复的自动验收；远程 CI/PR 状态仍以实际运行结果为准。阶段 8 的 Playwright 用例是严格 API mock 驱动的浏览器状态机与命令合同测试，不是真实 FastAPI + MySQL 全栈 E2E。正式库升级、真实机器强制断电恢复和真实服务器域名/证书上线仍须在对应环境单独演练。

## 1. 交付目标

首个可用版本在本机完成以下闭环：

1. 三类账号登录与服务端权限校验。
2. 选择报告日期并上传经营报告或退货报告。
3. 保留原始文件，创建不可变解析尝试和解析基线。
4. 自动校验应用是否准确录入 CSV。
5. 人工对照、纠错、备注和确认警告。
6. 按“日期 + 报表类型”发布、修订、回滚和隔离数据。
7. 查看已发布经营指标、商品表现和退货洞察。
8. 记录完整版本谱系、审计事件和备份清单。

首版保留 Agent 工具接口边界，但不接入具体模型、不允许 Agent 写数据。本地 MVP 在阶段 10A 完成；服务器容器部署是独立阶段 10B，只有 Docker、CI 或服务器环境可用并完成实际演练后才交付，不以未经运行的配置文件冒充完成。

## 2. 当前环境与兼容策略

已确认本机环境：

- Windows / PowerShell 7.6.4（使用 `pwsh`；数据库脚本不支持 Windows PowerShell 5.1）。
- Node.js `24.18.1`。
- pnpm `11.16.0`。
- Python `3.14.6`。
- MySQL Server `8.0.46`，Windows 服务 `MySQL80` 正在运行。
- Docker Engine `29.6.2` 与 Docker Compose `5.3.1` 已可用；阶段 10B 使用独立容器卷，不连接本机 MySQL。

实施约定：

- 本地开发先使用现有 MySQL 8.0.46，不要求先安装 Docker。
- 数据库迁移只使用 MySQL 8.0 与 8.4 都支持的功能；服务器正式环境目标为 MySQL 8.4 LTS。
- 后端统一使用 Python `>=3.14,<3.15`；本地、CI 与服务器镜像使用同一 Python 3.14 次版本线，避免双版本环境漂移。
- MySQL 驱动使用 PyMySQL，并安装 `cryptography` 以支持 MySQL 8.4 默认的 `caching_sha2_password`；生产数据库连接使用 TLS，不启用已弃用的 `mysql_native_password`。
- 后端使用同步 SQLAlchemy 2 与同步 FastAPI 路由；约 20 名用户无需引入异步数据库复杂度，连接池首版设为 10、最大溢出 20，并通过负载测试校准。
- 应用事务隔离级别使用 `READ COMMITTED`，依靠规格定义的唯一约束、条件更新和 `SELECT ... FOR UPDATE` 明确控制并发。
- 后端依赖由 `backend/requirements.in` 与带哈希的 `backend/requirements.lock` 固定；Ruff 和 mypy 的语法目标均为 Python 3.14。
- 阶段 5 开始前，必须在 Python 3.14 与 MySQL 8.0/8.4 组合环境完成安装、迁移与核心数据库测试。当前电脑缺少的 MySQL 8.4 环境可通过并行安装、受控远程测试机或 CI 提供，但不能以“代码看起来兼容”代替验证。
- 前端使用 pnpm，并提交锁文件。
- 所有秘密仅保存在未跟踪的 `.env` 中，仓库只提交 `.env.example`。

## 3. 目标目录结构

```text
D:\CLSEN_Data_Web
├─ backend/
│  ├─ app/
│  │  ├─ api/                 # FastAPI 路由与请求/响应模型
│  │  ├─ auth/                # 登录、会话、CSRF、角色权限
│  │  ├─ db/                  # SQLAlchemy、事务与仓储
│  │  ├─ imports/             # 文件租约、存储、报表识别、解析尝试
│  │  ├─ datasets/            # 每日数据集、版本、发布、回滚、日期移动
│  │  ├─ validation/          # 两阶段校验、规则集和审核事件
│  │  ├─ analytics/           # 看板查询与聚合口径
│  │  ├─ agent_tools/         # 后续 Agent 可调用的只读服务边界
│  │  └─ worker/              # outbox 与孤儿文件对账任务
│  ├─ alembic/
│  ├─ tests/
│  │  ├─ unit/
│  │  ├─ integration/
│  │  └─ fixtures/synthetic/
│  ├─ pyproject.toml
│  ├─ requirements.in
│  ├─ requirements.lock
│  └─ alembic.ini
├─ frontend/
│  ├─ src/
│  │  ├─ app/                 # 路由、布局、权限边界
│  │  ├─ api/                 # 由 OpenAPI 生成的类型与客户端
│  │  ├─ features/auth/
│  │  ├─ features/data-calendar/
│  │  ├─ features/import-review/
│  │  ├─ features/versions/
│  │  └─ features/dashboard/
│  └─ tests/
├─ tools/                     # 独立 golden manifest 工具
├─ scripts/                   # 本地启动、数据库初始化、备份与恢复
├─ .github/workflows/         # 仓库接入远程后执行兼容性矩阵；本地阶段可用等价测试机
├─ ops/                       # Docker Compose、Nginx、服务器说明
├─ data/                      # 本地持久化数据，全部忽略
└─ docs/
```

## 4. 质量门槛

每个阶段必须满足：

- 新行为先有失败测试或固定验收样本，再实现功能。
- 后端格式化、类型检查、单元测试和集成测试全部通过。
- 前端 lint、类型检查、组件测试全部通过。
- 数据库结构只通过 Alembic 迁移变化，不手工修改正式结构。
- 不提交原始 CSV、订单号、客户留言、数据库密码或备份文件。
- 每个阶段形成一个范围清晰、可回滚的 Git 提交。

建议质量工具：

- Python：pytest、Ruff、mypy、coverage。
- API/数据库：FastAPI TestClient、SQLAlchemy 2、Alembic、PyMySQL。
- 前端：Vite、React、TypeScript、Vitest、Testing Library、ESLint。
- 端到端：Playwright，在核心页面完成后引入。

## 5. 分阶段实施

### 阶段 0：建立可信数据基线

目标：在业务解析器出现前，独立记录 62 份现有 CSV 的期望结果。

新增文件：

- `tools/build_golden_manifest.py`
- `tools/verify_golden_manifest.py`
- `tools/README.md`
- `backend/tests/fixtures/synthetic/business-report.csv`
- `backend/tests/fixtures/synthetic/return-report.csv`
- `.gitignore` 增加 `/data/golden/` 和 `/backend/tests/fixtures/private/`

实施步骤：

1. 使用 Python 标准库 `csv` 编写独立工具，不引用后续业务解析器代码。
2. 为每个真实文件记录 SHA-256、类型、识别日期、原始表头、行数、关键标识集合哈希、数值合计、退货事件日集合和代表性长文本哈希。
3. 输出到被 Git 忽略的 `data/golden/golden-manifest.json`。
4. 工具二次读取清单并验证所有文件未变化。
5. 生成两份去标识化合成 CSV，提交到仓库供单元测试使用。
6. 人工抽查至少一份经营报告和一份退货报告，并确认当前已知事实：31 份退货报告共 449 行、141 行事件日与文件名报告日不同。

验收命令：

```powershell
python tools/build_golden_manifest.py --source .\表格 --output .\data\golden\golden-manifest.json
python tools/verify_golden_manifest.py --source .\表格 --manifest .\data\golden\golden-manifest.json
git status --short --ignored
```

期望：验证成功；真实 CSV 和 golden manifest 都不会进入 Git。

建议提交：`test: establish independent CSV golden baseline`

### 阶段 1：项目骨架与本地开发入口

目标：建立可启动、可测试、无业务逻辑的前后端骨架。

新增重点文件：

- `backend/pyproject.toml`
- `backend/requirements.in`
- `backend/requirements.lock`
- `backend/app/main.py`
- `backend/app/config.py`
- `backend/tests/unit/test_health.py`
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/src/main.tsx`
- `frontend/src/app/App.tsx`
- `scripts/dev-backend.ps1`
- `scripts/dev-frontend.ps1`
- `.env.example`
- `.github/workflows/compatibility.yml`

实施步骤：

1. 创建 FastAPI 应用、`/api/health/live` 与 `/api/health/ready`。
2. 配置结构化日志、请求 ID、统一错误响应和安全 CORS 白名单。
3. 创建 React + TypeScript + Vite 应用和基础路由。
4. 配置 Ruff、mypy、pytest、ESLint、Vitest 和 TypeScript 严格模式。
5. 生成带哈希的后端依赖锁；安装时使用锁文件并以 `--no-deps` 安装本地包，避免解析出未锁定依赖。
6. 增加 Python 3.14 安装与测试任务；MySQL 兼容矩阵在阶段 2 扩展。
7. 本地脚本分别启动前端和后端；暂不隐藏依赖错误。

验收命令：

```powershell
python -m venv .\.venv
.\.venv\Scripts\python -m pip install --require-hashes -r .\backend\requirements.lock
.\.venv\Scripts\python -m pip install -e .\backend --no-deps
.\.venv\Scripts\python -m pytest .\backend\tests
pnpm --dir .\frontend install
pnpm --dir .\frontend lint
pnpm --dir .\frontend test --run
pnpm --dir .\frontend build
```

期望：后端健康检查测试通过，前端显示空应用壳，所有质量命令通过。

建议提交：`chore: scaffold web application`

### 阶段 2：MySQL、迁移、账号与站点配置

目标：建立数据库基础、专用运行账号和三类应用角色。

本地验收状态（2026-08-07）：

- PowerShell 7.6.4 下的初始化流程已在 MySQL 8.0.46 实际完成，正式库与测试库、三类专用数据库账号和首个应用管理员均已创建。
- MySQL 8.0.46 已通过空库升级、`upgrade head → downgrade base → upgrade head`、逐版本升级、数据库约束和最小权限测试；正式库已只读核验为 revision `0005`，初始角色、站点配置、管理员角色和命名索引完整。
- 本机没有 Docker；阶段 2 本地验收时，MySQL 8.4 兼容矩阵与容器 TLS 尚未实际运行。后续 GitHub Actions 已于 2026-08-08 在 Linux MySQL 8.0/8.4 服务容器中实际完成 TLS 连接、迁移、约束和最小权限测试；这不代表阶段 10B 的完整服务器容器部署已验收。

迁移顺序：

- `0001_users_roles_sites.py`
- `0002_files_imports_parse_attempts.py`
- `0003_datasets_versions_baselines.py`
- `0004_validation_changes_audit.py`
- `0005_publication_outbox.py`

实施步骤：

1. 创建专用数据库 `clsen_data` 和测试数据库 `clsen_data_test`；迁移账号、应用运行账号和备份账号分离。运行账号不能拥有建库权限，备份账号只获得一致性 dump 所需的最小读取权限。
2. 建立 SQLAlchemy 会话、事务封装和 Alembic。
3. 数据库和表使用 `utf8mb4`，数据库会话时区固定为 UTC；时间字段由应用按明确站点时区转换。
4. 实现设计规格中的唯一约束、复合外键、活动草稿指针与发布指针。
5. 创建 `admin`、`data_manager`、`viewer` 角色。
6. 创建版本化 `amazon_us` 站点配置，默认币种 USD、源时区 `America/Los_Angeles`、报表统计时区 `America/Los_Angeles`；两个时区独立保存，不能继承宿主机或浏览器设置。
7. 密码使用 Argon2 哈希；首次管理员账号通过一次性命令创建，不在迁移中写默认密码。
8. 运行账号对审计与修改事件表只有插入和读取权限，不允许更新或删除。
9. 为所有日期、版本、SKU、ASIN、订单号和事件时间查询建立必要索引。
10. `0002` 中先创建不含“当前成功解析尝试”外键的 `import_batches`，再创建引用批次的 `parse_attempts`，最后通过 `ALTER TABLE` 加回批次指针，显式解决循环外键。
11. 已经应用的迁移文件永久不可修改；阶段 3 之后的结构调整只能新增 `0006+` 迁移。
12. 在 MySQL 8.0.46 与 8.4 上分别测试逐版本升级和空库升级；8.4 账号使用 `caching_sha2_password` 与 TLS。

关键测试：

- 重复 `(report_date, report_type)` 被拒绝。
- 同一数据集不能有两个活动草稿指针或发布指针。
- 指针不能引用其他数据集版本。
- 普通运行账号不能更新或删除追加式事件。
- MySQL 8.0.46 上能从空库升级到最新迁移。
- MySQL 8.0.46 与 8.4 都能从每个历史迁移逐步升级到下一版，并通过约束测试。

验收命令：

```powershell
.\.venv\Scripts\alembic -c .\backend\alembic.ini upgrade head
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_migrations.py
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_database_constraints.py
.\scripts\test-mysql-matrix.ps1 -Versions '8.0','8.4'
```

需要的人工输入：首次执行数据库初始化时，由管理员在本机安全提示中输入 MySQL 管理凭据和应用管理员密码；这些值不能出现在命令历史或日志中。若本机不并行安装 MySQL 8.4，则阶段 2 可先完成本地功能，但必须在进入阶段 5 前由远程测试机或 CI 补齐上述 8.4 门槛。

建议提交：`feat: add database schema and access control`

### 阶段 3：原始文件存储与幂等上传

目标：安全保存原始 CSV，并处理文件系统与 MySQL 不能共用事务的问题。

本地验收状态（2026-08-07）：

- 已新增迁移 `0006_raw_file_integrity_status.py`；正式库与测试库均已升级到 revision `0006`，运行账号已获得完整性状态表所需的 INSERT/UPDATE 权限且没有 DELETE 权限。
- 已实现 SHA-256 内容寻址存储、上传租约、流式限额与续租、非覆盖硬链接发布、重复批次冲突、提交确认丢失恢复、过期临时文件及孤儿内容隔离、引用文件完整性阻断状态。
- Windows 运行时只接受固定 NTFS 卷并使用目录句柄 flush；`init-database.ps1` 创建的默认存储根已核验为私有、受保护 DACL。手工覆盖 `APP_STORAGE_ROOT` 时仍须由运维人员施加并核验等价 ACL，阶段 3 不宣称运行时会自行验证 Windows DACL。POSIX 目录使用 `0700`、文件使用 `0600`，并在目录项变更后执行目录 `fsync`。
- 本机完整门禁结果为后端 198 个测试通过、2 个平台条件测试跳过，覆盖率 80%；Ruff、mypy、前端 lint、类型检查、5 个前端测试和生产构建通过。
- 阶段 3 本地验收时无法验证 MySQL 8.4、POSIX 权限实测和机器强制断电恢复。后续 Ubuntu CI 已实际通过 POSIX 权限位与普通用户目录符号链接测试，MySQL 8.4 矩阵也已在上述范围内通过；真实机器强制断电恢复仍未验证。
- 阶段 3 只交付存储、仓储、领域服务和对账边界；原始文件 HTTP 下载路由及角色授权在阶段 7 接入，后台调度与隔离区保留策略在阶段 10A 接入。

实现组件：

- 内容寻址存储：`sha256/<前两位>/<完整哈希>`。
- 上传临时目录与 `file_ingest_leases`。
- 导入批次状态机。
- 孤儿内容对象对账任务。
- 文件缺失系统告警。

实施顺序：

1. 先写失败测试：重复上传、相同哈希存储对象复用、数据库提交失败、过期租约和并发孤儿扫描。
2. 临时目录与正式目录启动时验证处于同一文件系统。
3. 上传时先创建租约，再流式写文件、计算哈希、原子移动，最后提交数据库引用。
4. 同哈希对象已存在时重新校验大小和哈希后复用，禁止覆盖。
5. 文件内容对象复用与导入批次去重分开处理：若哈希已关联到现有导入批次，默认返回冲突响应、现有批次 ID 和跳转地址，不创建第二个批次；管理员也只能进入已有批次，不能用重复上传覆盖它。
6. 对账任务只隔离超过 24 小时、没有有效租约且没有引用的对象，并在移动前二次检查。
7. 原始文件下载接口仅向管理员和数据管理员开放。

关键测试区分两层去重：未引用的同哈希内容对象可以安全复用并创建首个批次；同哈希已关联现有批次时返回该批次且批次数不增加。

验收命令：

```powershell
.\.venv\Scripts\python -m pytest .\backend\tests\unit\imports
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_file_ingest.py --require-mysql
```

建议提交：`feat: add immutable content-addressed imports`

### 阶段 4：报表识别、解析尝试与解析基线

目标：证明系统可以准确读取两类真实 CSV，并保留所有解析尝试。

实现与本地验收状态（2026-08-07）：

- 已通过新增迁移 `0007_report_parsing_contracts.py` 分离系统识别类型、人工确认类型和当前成功解析的生效类型；误识别纠正继续使用同一导入批次，只有成功终态事务会原子切换生效类型和当前成功指针。
- `report_date` 是最新人工选择的业务日期，独立于解析成功；除确认并解析外，使用独立 `ChangeReportDateCommand` 修改日期。该命令不递增解析 `confirmation_revision`，只更新日期并写结果为 `applied` 的审计，不创建解析尝试或基线，也不切换旧成功指针或生效类型；批次处于 `processing`、`rejected` 或已被 `version_input_batches` 物化时拒绝直接修改。
- 已实现当前 22 列经营报告与 13 列退货报告的确定性识别和解析，支持 UTF-8 BOM、UTF-8、Windows-1252、严格 CSV、Decimal、比例、UTC、IANA 时区和 DST 校验。规则以冻结 Python 数据结构保存在代码中，不增加运行时 YAML 依赖。
- `parse_attempts` 只写不可变成功/失败终态；运行租约由 `import_batches` 的 token、命令摘要、开始时间和追加式审计表达。`ConfirmAndParseCommand` 与 `ChangeReportDateCommand` 都要求调用方提供可稳定重试的 UUID token，并将全部命令字段绑定为 SHA-256 摘要；服务不得临时生成 token。相同 token 与完整相同命令可恢复提交确认丢失，改变批次或任一命令字段时拒绝。
- `parse_operation_tokens` 与 `report_date_operation_tokens` 是两个命令类型各自的不可变全局归属账本；活动批次和成功/失败终态尝试以复合外键绑定解析 token、批次和摘要。`0007` 降级若发现失败尝试的类型无法由 `0006` 单一批次类型表达，会在任何 DDL 前预检拒绝。
- 62 份私有 CSV 已与独立 golden manifest 强制回归一致；测试不输出真实订单号或留言。MySQL 8.0 已完成最新 `0007` 的干净测试库重建、空库升级、逐版本升降级、历史数据回填、约束、上传和解析工作流验证。最终本地全后端门禁为 299 项通过、2 项因 Windows 不支持 POSIX 权限位和普通用户目录符号链接而跳过，覆盖率 83%；Ruff、mypy、前端 lint/typecheck/5 项组件测试/生产构建、golden 校验和敏感文件检查全部通过。
- 2026-08-08，GitHub Actions push run `31229705137` 与 PR run `31229707357` 全部通过：Ubuntu/Windows 的 Python 3.14 后端门禁、Node 24/pnpm 11 前端门禁，以及 MySQL 8.0/8.4 的 TLS 连接、迁移、约束和最小权限测试均为绿色。Ubuntu 离线套件为 196 项通过、3 项跳过、102 项因 `mysql` 标记被排除；POSIX 权限位与普通用户目录符号链接测试在 Linux 上实际通过。MySQL 8.4 job `93030942216` 使用 `caching_sha2_password` 和 `REQUIRE SSL`，三类数据库连接均实际协商 TLS；迁移矩阵 12 项、数据库约束与工作流 51 项测试通过。该 CI 范围不包含真实机器强制断电恢复，也不代表阶段 10B 的完整服务器部署已验收。
- 当前本地正式库保持在 `0006`，测试库为 `0007`；在进入相应的正式库变更流程前，不提前迁移正式库。
- 运行账号对两张 token 账本只需要 `SELECT`、`INSERT`，不得拥有 `UPDATE`、`DELETE`。本地测试运行账号已同步两张新表的 `INSERT` 并通过 2 项真实权限测试，确认可以登记但不能更新或删除；其他既有环境升级 `0007` 后仍必须由数据库管理员按 `scripts/database-privileges.json` 同步授权并核对实际权限。
- 已知限制：解析租约暂时没有心跳；解析读取有严格大小上限但仍整文件进入内存。当前真实文件很小，进入大文件或后台 worker 场景前必须补心跳/主动恢复与流式解析。真实机器强制断电恢复仍未验证，不能由 CI 容器或进程故障测试替代。

规则与解析文件：

- `backend/app/parsers/rules.py`
- `backend/app/parsers/recognition.py`
- `backend/app/parsers/parser.py`
- `backend/app/parsers/repository.py`
- `backend/app/parsers/workflow.py`

实施步骤：

1. 识别文件名日期、报表类型、UTF-8/UTF-8 BOM 和明确支持的其他编码。
2. 使用标准 CSV 语义处理引号、逗号、换行和长文本。
3. 每次解析只在终态事务创建新的 `parse_attempts` 和 `parsed_source_rows`；不创建需要后续 UPDATE 的运行中尝试，也不修改失败或旧尝试。
4. 解析尝试固定本次实际使用的报表类型和站点配置版本；允许同一站点的新配置用于后续重解析，但不能把其他站点配置混入该批次。
5. 按规则集生成不可变类型化解析基线和摘要哈希；只有成功尝试可以拥有基线，基线类型必须与尝试类型一致。
6. 金额用 Decimal，百分比保存为比例，事件时间保存为 UTC。
7. 无时区事件时间只有在该解析尝试引用的版本化站点源时区已配置时才允许解析；解析结果固定为 UTC，不受后续站点配置变化影响。
8. 将业务解析结果与独立 golden manifest 对账。
9. 增加解析器版本字段，保证未来代码变化不会重写历史基线。
10. 将 `ConfirmAndParseCommand.operation_token` 设为服务入口必填的稳定 UUID；调用方必须在首次请求前生成并在重试时复用，服务拒绝缺失或非 UUID token，且不得临时生成替代值。将批次、类型、日期、编码、站点配置版本和操作者纳入完整命令摘要，实现确认与终态提交丢失恢复；同 token 同命令返回原结果，同 token 改变批次或任一字段时拒绝。
11. 实现独立 `ChangeReportDateCommand`：同样要求调用方提供稳定 UUID token，并将批次、目标日期和操作者纳入完整命令摘要。锁定批次后，只允许状态既非 `processing` 也非 `rejected` 且尚未被 `version_input_batches` 物化的批次直接更新 `report_date`；不递增解析 `confirmation_revision`，不创建 `parse_attempts`、`parsed_source_rows` 或 `parse_baselines`，不修改当前成功解析指针或当前生效报表类型。每个成功执行或同日幂等执行都写唯一的 `import_report_date_change_applied` 审计，提交确认丢失时通过 token 账本和审计恢复且不重复写入。
12. 创建不可变 `parse_operation_tokens` 与 `report_date_operation_tokens` 全局归属账本；活动批次和成功/失败终态尝试通过复合外键绑定同一解析 token、批次和摘要。`0007` downgrade 在 DDL 前预检无法由 `0006` 表达的失败尝试类型并拒绝有损降级。运行账号仅获得两表的 `SELECT`、`INSERT`；升级已有本地数据库后由管理员同步新表的 `INSERT` 授权，不能授予 `UPDATE`、`DELETE`。

关键测试：

- 当前 22 列经营报告字段映射准确。
- 当前 13 列退货报告字段映射准确。
- `US$111.98`、`15.90%`、B2B 字段和带偏移时间转换准确。
- 无偏移时间按独立源时区转换；缺少源时区时产生阻断错误。
- 在不同操作系统 `TZ` 和浏览器时区模拟值下运行，解析 UTC 结果保持一致。
- 买家留言中的逗号、引号和长文本完整保留。
- 重解析创建新尝试，失败不影响当前成功尝试。
- 开始解析、成功终态或失败终态已经提交但响应丢失后，同 token 重试不增加 confirmation revision、attempt 或 baseline。
- 同 token 改变日期、类型、编码、站点配置、批次或操作者时被拒绝。
- 确认并解析缺少稳定 operation token 时在服务入口被拒绝，服务不会为请求临时生成 token。
- 独立修改报告日期要求稳定 UUID token；同 token 改变批次、日期或操作者时被拒绝。成功执行只写一条 `applied` 审计，不改变解析确认修订、attempt、baseline、当前成功指针或生效类型；提交确认丢失后重试不重复写入。
- `processing`、`rejected` 和已被 `version_input_batches` 物化的批次直接修改日期均被拒绝且日期不变；物化后的日期调整留给阶段 5 草稿迁移。
- 活动批次或终态尝试不能通过复合外键绑定错配的解析 token、批次或命令摘要；两张 token 账本不允许运行账号更新或删除。
- `0007` downgrade 遇到无法由 `0006` 表达的失败尝试类型时，在任何结构变更前拒绝。
- 62 份真实文件全部满足 golden manifest。

验收命令：

```powershell
.\.venv\Scripts\python -m pytest .\backend\tests\unit\parsers
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_parse_workflow.py --require-mysql
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_real_csv_regression.py
```

建议提交：`feat: parse Amazon reports into immutable baselines`

### 阶段 5：每日数据集、版本基础快照与草稿事务

目标：先实现每日隔离、草稿、谱系、合并、替换和未发布草稿改日期；最终发布依赖阶段 6 的校验结果，因此不在本阶段提前实现。

实现与本地验收状态（2026-08-08）：

- `0008`、每日数据集隔离、不可变基础快照、草稿合并/替换/废弃、未发布草稿改日、操作账本及专用数据集锁已实现。
- 本机 MySQL 8.0.46 实际通过：草稿事务与改日 20 项，阶段 5 Schema 与数据库约束 75 项，完整迁移历史 12 项；完整后端为 420 项通过、2 项 Windows 平台条件跳过，覆盖率 85%。
- 前端 lint、类型检查、5 项组件测试和生产构建通过；62 份私有 CSV 与独立 golden manifest 一致，敏感文件 Git 门禁通过。
- 本地测试库已确认在 `0008`，正式库保持在 `0006`。上述结果仅证明本机 MySQL 8.0；MySQL 8.4 结果以 PR 的兼容矩阵 CI 为准。既有环境升级到 `0008` 后、恢复应用写入前，仍须同步 manifest v2 权限并核对所有数据集均存在锁行。

实施步骤：

1. 新增 `0008_draft_versioning_contracts.py`，强化草稿指针、版本终态和跨类型谱系约束，为 `version_base_rows` 增加 `row_state`，创建 `draft_operation_tokens`、`draft_operation_results` 与 `draft_disposition_events` 三张不可变账本表，并创建及回填专用 `daily_dataset_locks` 同步表。
2. 实现 `(report_date, report_type)` 数据集查找或创建服务。
3. 从解析基线或父版本创建不可变 `version_base_snapshots`。
4. 合并时固定成员顺序、来源批次、逻辑行 ID 和逐行冲突决定。
5. 只通过 `dataset_drafts` 指向一个活动草稿。
6. 新文件并入已有活动草稿时，锁定并封存旧草稿状态，把其处理行当前值、`row_state` 和逻辑行身份与新解析基线冻结进后继草稿的基础快照，再在同一事务废弃旧草稿并切换活动指针。不要复制 `field_changes`、`row_changes` 等追加式修改事件；前任历史只通过 `version_parent_versions` 谱系追溯。
7. 数据管理员可以显式废弃自己正在处理的未发布草稿；管理员可以强制废弃任意活动草稿。两者都写追加式处置事件，废弃版本不能直接发布。
8. 阶段 5 的物化、强制重建、废弃和未发布草稿改日命令都要求调用方在首次请求前生成稳定 UUID，并在重试时复用。完整命令和操作者进入规范化摘要；`draft_operation_tokens` 永久绑定 token、命令类型、摘要和操作者，同 token 改变任一绑定字段时拒绝。
9. 每个已应用或已取消命令只向 `draft_operation_results` 写入一次终态结果，并冻结首次结果的数据集、版本号、状态、两类修订号和来源谱系；之后版本发生编辑、替代或废弃时，同 token 重试仍返回首次结果。废弃、替代、强制重建和改日另外写 `draft_disposition_events`，三张账本都禁止 UPDATE 或 DELETE。
10. 实现 `data_revision` 与 `review_revision` 两套乐观并发控制。
11. 固定阶段 5 锁序：claim operation token 后，以 `FOR SHARE` 固定 actor 与角色关系的权限快照。每个数据集在同一事务拥有一条 `daily_dataset_locks` 记录；后端按 dataset ID 升序实际更新 `lock_revision` 取得同步行的排他锁，再普通读取不可变 `daily_datasets`，不得用联表 `FOR UPDATE` 间接要求数据集表写权限。唯一键创建竞争的失败方可用一次 `FOR SHARE` 当前读发现已提交胜者，随后仍更新同步行。物化和强制重建先锁直接输入批次及当前 baseline，再锁 dataset lock、活动/发布指针和父版本；废弃按 dataset lock、活动版本处理；改日先按 dataset ID 升序锁来源与目标 dataset lock，再锁实际 source/target version。所有父版本锁定后，显式汇总继承输入并按 batch ID 锁对应 `import_batches`，最后读取或锁定行。
12. 对 MySQL `1213` 和 `1205` 使用完整事务重试：每次新建事务、复用同一 token，并在重放前恢复已有终态结果；首次失败后最多重试 3 次，即总尝试最多 4 次，不能从保存点或事务中段继续。连接失效只尝试一次结果恢复，找不到终态时报告结果未知，不盲目重放。
13. 服务必须用活动草稿指针、可编辑状态和修订号条件更新阻止晚到写入。同时记录剩余威胁：迁移/数据库管理员账号或任何可绕过服务直接写 SQL 的凭据仍能绕过服务层终态守卫；阶段 6 发布上线前统一评估数据库级终态守卫，并完成迁移、管理员、运行和人工运维凭据隔离决策。
14. 实现 `reassign_unpublished_draft_date`：数据管理员可以把仅来源于未发布上传批次的草稿改到另一日期；批次一旦被 `version_input_batches` 物化，阶段 4 的 `ChangeReportDateCommand` 必须拒绝直接改日，由本服务在目标数据集创建新版本，把来源草稿当前值、`row_state` 和逻辑行身份冻结进新基础快照，再原子废弃来源草稿。不要复制来源修改事件，也不能就地改写批次日期或版本的 `dataset_id`。
15. 目标日期已有发布版本时，改日期必须选择以新文件合并或替换目标草稿，目标当前发布版本保持不变；目标已有活动草稿时只能创建合并后继草稿或取消，管理员另有强制重建权限。
16. 草稿谱系包含已发布版本并意图迁出原日期时，拒绝数据管理员的普通改日期请求，交由阶段 6 的管理员已发布跨日期移动流程。
17. 将 `0008` 三张新账本表和 `daily_dataset_locks` 加入 `scripts/database-privileges.json`。三张账本只授予运行账号 `SELECT`、`INSERT`；锁表授予 `SELECT`、`INSERT` 和仅限 `lock_revision` 的列级 `UPDATE`，不授予整表 `UPDATE` 或 `DELETE`，其技术值不得承载业务含义。权限 manifest 升级为版本 2，初始化脚本、本地矩阵和 CI 必须从同一清单生成列级授权。迁移不会自动扩展既有环境权限；每个环境升级后必须由数据库管理员同步并核对，不能据迁移成功推断授权已完成。本地初始化必须在写入环境文件和报告成功前，以双向反连接和计数核对全部数据集锁行；持续 readiness 检查留给阶段 10B 的部署健康门禁。

并发测试不得使用 SQLite、内存替身或共享数据库连接。测试使用至少两个真实 MySQL 独立连接和同步屏障，按固定顺序复现事务交错；同一套用例必须在 MySQL 8.0 与 8.4 各执行一次。

关键测试：

- 任意一天的修改不会改变其他日期或报表类型。
- 两人同时创建草稿时只有一个成功。
- 新批次并入活动草稿时旧草稿被封存；后继基础快照冻结前任当前值、`row_state` 和逻辑行身份，不复制追加式修改事件，活动指针原子切换且历史可沿谱系追溯。
- 同一业务指纹在目标或来源侧出现多行时，系统要求并保存完整的目标行 × 来源行决定矩阵；同一行不能被互相矛盾地选择或排除，结果不依赖决定输入顺序。
- 只有管理员能强制废弃现有活动草稿并重建，旧草稿仍可审计但不能直接发布。
- 数据管理员能移动仅来源于未发布上传的草稿，但不能借此移动已发布版本。
- 改日期目标为空、已有发布版本、已有活动草稿时分别执行正确的创建、合并/替换、合并/取消语义。
- 目标冲突或事务失败时来源草稿和目标状态均保持不变。
- 每个草稿写命令都拒绝缺失或非 UUID token；同 token、同命令恢复首次冻结结果，同 token 改变命令或操作者时拒绝，已取消结果也可以幂等恢复。
- 版本在首次命令成功后被编辑、替代或废弃，不会改变 `draft_operation_results` 返回的首次状态和修订号；token、result 和 disposition 账本不能由运行账号更新或删除。
- `0008` 升级后 `daily_dataset_locks` 行数与 `daily_datasets` 一致，孤儿锁行被外键拒绝；运行账号可以创建锁行并更新 `lock_revision` 取得排他锁，但不能更新 `dataset_id` 或删除锁行，也不需要获得 `daily_datasets` 的 `UPDATE` 权限。
- 两个真实 MySQL 独立连接按同步屏障交错时仍遵循共享权限快照、数据集 ID、继承批次 ID 和行的锁序；`1213`/`1205` 只触发完整事务重试，首次失败后最多重试 3 次，耗尽后不留下部分状态。

验收命令：

```powershell
.\.venv\Scripts\python -m pytest .\backend\tests\unit\datasets
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_draft_transactions.py .\backend\tests\integration\test_draft_date_reassignment.py --require-mysql
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_stage_five_schema.py .\backend\tests\integration\test_database_constraints.py --require-mysql
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_migrations.py --require-mysql
.\scripts\test-mysql-matrix.ps1 -Versions '8.0','8.4'
```

建议提交：`feat: add isolated daily draft versioning`

### 阶段 6：两阶段校验、人工纠错与审核状态

目标：证明自动解析保真、允许所有人工差异被完整解释，并在这些校验基础上完成发布、回滚与已发布跨日期移动。

实施步骤：

1. 实现“源行 → 解析基线”的自动解析保真校验。
2. 实现“版本基础快照 + 修改事件 → 当前草稿”的可解释差异校验。
3. 建立 `validation_runs`、不可变问题和追加式审核事件。
4. 实现字段修改、行新增、排除、恢复和三种恢复值操作。
5. `data_change_events.event_kind` 必须通过新的复合鉴别外键与 `field_changes` / `row_changes` 子类型一致；父事件与唯一子记录仍由同一服务事务和重放校验保证。
6. 实现批次、行、字段备注：首版批次备注固定为 `internal`，只供录入审核人员和管理员查看；行、字段及版本备注支持 `internal` / `viewer_visible`，只有明确标记为查看人员可见的已发布版本备注才进入查看页面。
7. 数据变化递增 `data_revision` 并使旧校验失效。
8. `dataset_drafts.version_status` 由 `ON UPDATE RESTRICT` 复合外键绑定 `dataset_versions.status`。活动版本在 `draft` 与 `ready_for_publish` 间切换时，事务必须先持有对应 `daily_dataset_locks` 锁并锁定指针与版本，保存原 `pointed_at`，按预期 dataset、version 和旧状态条件删除草稿指针，再条件更新版本状态和修订号，最后以同一 dataset、version、新状态及原 `pointed_at` 重建指针；任一步失败必须整体回滚。禁止分别直接更新父状态或子冗余状态。
9. 警告确认和发布备注只递增 `review_revision`，避免校验确认循环。
10. 实现结构错误的重新解析流程，旧人工修改保留但不自动套用。
11. 实现合并重复冲突：保留来源、保留目标或有理由地保留两行。
12. 实现最终发布事务：锁定数据集与版本，重新核对活动草稿、数据修订、审核修订、成功校验和警告确认，随后按预期版本和状态删除草稿指针，将版本封存为 `published`，再切换发布指针并写 outbox。
13. 实现基于当前发布版本的普通修订和仅管理员可执行的同数据集回滚。
14. 实现管理员已发布跨日期移动：审核期间来源发布版本继续生效；来源存在其他活动草稿时阻止；目标已有发布版本时明确合并、替换或取消；目标已有活动草稿时明确合并、取消或管理员强制重建。
15. 跨日期最终发布按固定顺序锁住两侧数据集，在同一事务撤下来源并发布目标；移动撤销也必须通过双侧原子事务，不能单边回滚。
16. 所有发布、回滚和跨日期命令使用幂等键；MySQL `1213`/`1205` 必须回滚后重试完整事务，首次失败后最多重试 3 次，即总尝试最多 4 次。

发布并发测试使用至少两个真实 MySQL 独立连接和同步屏障，不得使用 SQLite、内存替身或共享连接；同一套用例在 MySQL 8.0 与 8.4 各执行一次。

关键测试：

- 自动解析行数与合计不一致时阻断。
- 合法人工修改按净变化对账后可以发布。
- 无审计事件的数据差异阻断发布。
- 确认警告后可使用同一数据修订的成功校验发布。
- 确认后再次编辑数据会让旧校验失效。
- 人工新增行不能执行“恢复源文件值”。
- 活动版本 `draft ↔ ready_for_publish` 在持有数据集锁的单事务中按“删旧指针 → 条件更新版本 → 按原 `pointed_at` 重建新状态指针”成功；直接更新父状态或子状态均被数据库拒绝，任一步故障回滚后原指针、状态和时间戳完整保留。
- 用屏障固定“保存与发布交错”，发布先条件删除活动指针再封存版本，晚到编辑不能修改已经封存的版本。
- 回滚目标只能是同数据集曾发布版本。
- 跨日期审核期间来源版本持续生效，最终成功时两侧一次生效。
- 目标已有发布版本或活动草稿时，合并、替换、取消和强制重建权限符合规格。
- 跨日期事务任一步骤故障时两侧全部回滚，移动撤销不能只恢复一侧。
- 两个相反方向的跨日期移动不会造成未处理死锁、双重发布或数据丢失。
- 提交成功但响应丢失后，相同幂等键重试返回第一次结果。
- MySQL `1213`/`1205` 超过总尝试上限后不留下部分状态。

验收命令：

```powershell
.\.venv\Scripts\python -m pytest .\backend\tests\unit\validation
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_review_workflow.py
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_publication_transactions.py
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_publication_concurrency.py
.\scripts\test-runtime-matrix.ps1 -PythonVersion 3.14 -MySQLVersions 8.0,8.4 -Suite publication
```

建议提交：`feat: add auditable review and publication workflow`

### 阶段 7：认证、权限与稳定 API 合同

目标：把前述服务通过安全、可生成客户端的 API 暴露。

认证方案：

- 同源 HttpOnly 会话 Cookie。
- `SameSite=Lax`，服务器环境启用 `Secure`。
- 所有写请求使用 CSRF Token。
- 登录限速、会话过期和登录审计。

主要 API 分组：

- `/api/auth/*`
- `/api/data-calendar/*`
- `/api/imports/*`
- `/api/datasets/*`
- `/api/drafts/*`
- `/api/validation-runs/*`
- `/api/versions/*`
- `/api/dashboard/*`
- `/api/admin/*`

必须明确实现的管理与日期接口：

- `POST /api/drafts/{id}/reassign-date`：数据管理员和管理员移动仅来源于未发布上传的草稿。
- `POST /api/admin/versions/{id}/move-date`：管理员启动已发布跨日期移动。
- `POST /api/admin/drafts/{id}/force-rebuild`：管理员强制废弃活动草稿并重建，仍不能绕过校验。
- `/api/admin/users` 与 `/api/admin/roles`：用户和角色管理。
- `/api/admin/site-config-versions`：源时区、统计时区和币种的版本化配置。
- `/api/admin/audit-events`：只读审计查询。
- `/api/admin/backups`：阶段 10A 接入备份状态和验证结果。

实施步骤：

1. 为每个用例建立 Pydantic 请求/响应模型和明确错误码。
2. 在后端路由与服务层执行角色校验，不能依赖前端隐藏按钮。
3. 为修改和发布请求使用版本号、幂等键与冲突响应。
4. 从 FastAPI OpenAPI 生成前端 TypeScript 类型和客户端。
5. 对订单号、物流牌照和留言实施服务端字段级脱敏。
6. 为每个写端点建立 `admin`、`data_manager`、`viewer` 三角色权限矩阵，并对允许与拒绝路径做服务端集成测试。
7. 增加 API 合同测试，防止前后端字段漂移。

权限验收：

- 管理员拥有全部权限。
- 数据管理员可以上传、纠错、审核、发布并调整仅来源于未发布上传的草稿日期；不能移动已发布版本、回滚、强制重建他人草稿或管理用户。
- 查看人员只能查询已发布汇总数据，不能访问草稿和原文件。

负向权限测试还必须验证：数据管理员不能修改规则集、删除原始文件、查看管理员级内部审计或执行批量回滚；查看人员不能访问编辑页面/API、内部备注、审计详情、原始留言或备份入口；只有管理员能管理站点配置版本、强制重建草稿、查看完整审计和启动恢复验证。

建议提交：`feat: expose secured review APIs`

### 阶段 8：数据日历与审核工作台

目标：交付可由数据管理员完成日常工作的前端界面。

当前交付范围：

- 已接通登录、数据日历、日期隔离的导入与识别确认、草稿审核、版本记录和管理员控制台。
- 审核行由服务端分页读取，前端固定每页 50 行。当前没有浏览器虚拟滚动；固定 SKU/ASIN 等关键列、当前页搜索与排序、字段聚焦、上一处/下一处差异以及方向键单元格导航，共同作为更稳定的键盘和辅助技术可访问性替代。
- 导入目标已有活动草稿时，管理员可直接在服务器预览过的导入冲突选择中执行“强制重建活动草稿”；不接受从管理员控制台自由填写数据库 ID。旧草稿和审计历史保留，新草稿仍须重新校验和人工确认。
- 已发布数据跨日期移动先在目标日期创建审核草稿，审核期间来源发布版本继续生效。数据管理员可以完成草稿审核，但只有管理员能执行最终生效；最终生效同时切换两侧发布指针。满足当前指针前置条件时，管理员可从版本记录执行双侧原子撤销。
- 浏览器主流程用 Playwright 和严格 API fixture 验证“上传 → 审核 → 发布 → 查看版本”的 UI 状态机、写命令载荷、CSRF 与幂等键合同；该用例不会启动 FastAPI 或 MySQL，不能描述为真实全栈 E2E。后端 MySQL 集成测试与这个浏览器合同测试是两条独立证据链。

页面顺序：

1. 登录页。
2. 数据日历。
3. 单日数据详情。
4. 上传与日期选择对话框。
5. 导入处理状态页。
6. 差异优先审核工作台。
7. 版本历史与回滚页。
8. 管理员用户/角色、站点配置、审计和草稿强制重建页。

交互要求：

- 日历按红、黄、蓝、绿、灰优先级展示状态。
- 上传前可选日期，上传后显示识别日期差异。
- 待审核详情提供“更改所属日期”；数据管理员只能移动未发布上传草稿，管理员处理已发布跨日期移动，界面分别展示目标日期合并、替换、取消和冲突结果。
- 审核表按服务端每页 50 行分页，固定关键列，并支持搜索、过滤、表头排序、字段聚焦、差异导航和方向键操作；这是当前替代虚拟滚动的可访问性方案。
- 点击单元格打开对照抽屉，展示源值、基础值、当前值、转换规则和历史。
- 明确区分“撤销本次修改”“恢复父版本值”“恢复源文件值”。
- 阻断项、警告和人工修改采用不同语义色，不只依赖颜色传达状态。
- 发布对话框显示日期、报表类型、行数、合计、警告和版本。
- 所有页面支持窄屏查看、键盘焦点和减少动画偏好。

前端测试：

- 权限路由和按钮可见性。
- 日历状态优先级。
- 上传日期识别与冲突选择。
- 未发布草稿更改日期的成功、目标冲突和权限拒绝流程。
- 审核单元格编辑、并发冲突和三种恢复操作。
- 阻断错误不能发布，已确认警告可以发布。
- Playwright 以严格 API mock 完成“上传 → 审核 → 发布 → 查看版本”浏览器主流程，并对未处理请求失败关闭；它验证 UI 状态机和 HTTP 命令合同，不代表真实 FastAPI + MySQL 全栈 E2E。

干净机器首次运行端到端测试前执行：

```powershell
pnpm --dir .\frontend exec playwright install chromium
```

建议提交：`feat: build daily import review workspace`

### 阶段 9：经营看板与只读分析边界

目标：让查看人员只消费当前已发布版本。

当前交付范围（不等同于最终全量验收）：

- 已发布看板可按月份查看销售额、订购数、会话数、转化率和退货数，切换每日趋势指标，并查看 SKU/ASIN 表现排名与退货原因、处置状态和商品构成。
- 退货数据可在“报告所属日”和“退货事件日”之间切换；页面同时展示实际读取的发布版本、站点配置版本、币种和统计时区，便于人工追溯口径。
- 看板查询只读取当前发布指针，草稿、失败导入和历史非当前版本不会混入默认经营结果。查看人员可在版本记录中追溯已发布历史和查看人员可见备注，但不能读取活动草稿、内部备注，也不能进入导入、编辑、发布或管理员流程。
- `agent_tools` 仅保留只读服务边界和版本引用能力，当前没有接入模型，也没有 Agent 写入入口。
- 本地体验入口使用隔离测试库；它不证明正式库已经升级，也不替代备份恢复或服务器部署验收。
- 2026-08-11 在干净的 `clsen_data_test` 上完成本地全量门禁：后端 857 项通过、2 项因 Windows 不支持 POSIX 权限位和普通用户目录符号链接而跳过，覆盖率 83%；Ruff、格式检查、mypy、前端 lint/typecheck、71 项组件测试、生产构建、1 项严格 API fixture 驱动的 Chromium E2E、OpenAPI 客户端漂移检查、62 份 CSV golden manifest 和 `git diff --check` 均通过。
- 门禁后重新生成隔离体验数据：`2026-08-01` 指向已发布版本 88，`2026-08-02` 保留活动草稿版本 89；正式库只读复核仍为 revision `0006`，未运行迁移。

首版看板：

- 销售额、订购数量、会话数、转化率和退货数量。
- 经营指标按 `report_date` 的趋势。
- 退货按报告所属日/事件日切换，并显示 `America/Los_Angeles` 等当前站点统计时区。
- SKU/ASIN 商品表现排序。
- 退货原因、处置状态和商品分布。
- 版本与日期口径说明。

实施步骤：

1. 所有查询经 `dataset_publications` 过滤当前发布版本。
2. 首版直接查询 MySQL，不引入外部缓存。
3. 事件日查询显式使用版本化 `site_config_version_id`。
4. 查询服务返回数据版本和站点配置版本，供页面及未来 Agent 引用。
5. 建立 `agent_tools` 只读服务接口，但不连接模型。
6. 查看人员不能获取完整订单号、物流牌照或原始单笔留言。

关键测试：

- 草稿和历史版本不进入看板。
- 发布新版本后查询立即切换。
- 报告日与事件日口径结果独立、标注准确。
- 更改站点统计时区后事件日结果按新配置重算。
- Agent 工具边界没有任意 SQL 或写方法。

建议提交：`feat: add published-data operations dashboard`

### 阶段 10A：本地备份、恢复与后台任务

目标：在当前无 Docker 的电脑上完成可验证的本地恢复能力；这是本地 MVP 的必过门槛。

本地验收状态（2026-08-11）：

- 测试库已升级到 revision `0019`。应用写事务在首次写入前取得专用单行屏障的共享 InnoDB 锁，备份以 named lock 防止并行维护并取得同一行的独占锁；真实测试证明并发业务写事务不会被彼此串行化，备份持锁时业务写入失败关闭、读取继续可用，认证会话活跃时间采用非阻塞遥测更新，不会把只读页面变成被备份阻塞的写请求。
- 使用最小权限 `clsen_backup` 账号在最终事务边界下创建 AES-256-GCM 加密备份 `09c75880cc304313850fd25316c40eb8`，数据库 dump、清单和 2 个内容对象共 4 个加密制品全部通过大小、SHA-256 与 GCM 标签复核；快照 ID 为 11，状态为 `succeeded`。故障注入还证明 `mysqldump` 启动失败时，预先提交的 `running` 记录会可靠转为 `failed`，不会因屏障事务回滚而丢失审计证据。
- 此前备份 `1657ad8828974d98b5ca08c3b26635e0` 已恢复到随机数据库 `clsen_restore_5cbfd95a5e184a3bab88264aff85854e` 和同名随机文件目录，迁移版本、原始文件、发布指针、数据版本、审计数量、当前站点配置指针及所有文件哈希均一致；恢复验证状态为 `succeeded`，结果按默认策略保留。`0019` 只增加数据库内的屏障哨兵，不改变加密备份或恢复格式。
- Windows 脚本使用 .NET ACL API 重入保护密钥环、备份目录和临时凭据，避免已受保护路径再次调用 `Set-Acl` 时错误要求 `SeSecurityPrivilege`。测试库体验数据的备份显式传入实际 `StorageRoot`，目录与数据库引用不一致时失败关闭。
- 最终本地门禁为 Ruff 格式及规则检查通过、mypy 187 个源文件通过、非 MySQL 后端 647 项通过与 2 项 Windows 条件跳过、写屏障/备份最小权限/故障审计/并发事务/维护 API 定向 MySQL 9 项通过、前端 lint/typecheck/72 项组件测试/生产构建通过、62 份 CSV golden manifest 一致、OpenAPI 客户端无漂移、PowerShell 全脚本语法和 `git diff --check` 通过。正式库最后只读复核为 revision `0006`、42 张表、0 个触发器，未运行迁移或写入。

新增文件：

- `backend/app/maintenance/backup.py`
- `backend/alembic/versions/00xx_backup_snapshots.py`（使用届时下一个可用 revision）
- `backend/alembic/versions/0019_maintenance_write_barrier.py`
- `scripts/backup.ps1`
- `scripts/restore-verify.ps1`
- `scripts/run-worker.ps1`
- `docs/operations/local-maintenance.md`
- `docs/user-guide/import-review.md`
- `docs/user-guide/dashboard.md`

一致性备份流程：

1. 所有应用写事务在首次写入前取得 `maintenance_write_barrier` 单行的共享 InnoDB 锁并持有到事务结束；并发写事务可以共享该锁。备份进程先持有按数据库隔离的 MySQL named lock 防止并行维护，再取得同一行的独占锁，从而等待既有写事务结束并暂停新的导入最终提交、数据编辑、发布和配置修改，读请求继续服务。
2. 等待活动文件租约结束，并在 MySQL 中创建 `backup_snapshots` 与本次已引用内容对象清单。
3. 屏障保持期间使用 `mysqldump --single-transaction --quick --routines --triggers --events --hex-blob --default-character-set=utf8mb4 --no-tablespaces` 创建一致性数据库快照。
4. 数据库 dump 完成后释放写屏障；原始内容对象不可变，可在屏障外按快照清单复制。
5. 生成包含数据库备份 ID、站点配置版本、文件存储键、大小、SHA-256、发布指针数量和审计事件数量的清单。
6. 使用 Python `cryptography` 以 AES-256-GCM 加密数据库 dump、文件对象和清单；每份备份记录 `key_id`。当前密钥保存在仓库外、受 Windows ACL 保护的密钥环中，同时将独立恢复副本保存在另一故障域的受保护位置，例如企业密码库或加密离线介质。
7. 只有解密抽检、清单哈希和所有内容对象验证成功后，才把备份标记为成功。
8. 默认保留 30 份每日成功备份；清理前确认至少存在一个已通过恢复演练的备份。

备份脚本通过提交或回滚释放独占行锁，并在 `finally` 中显式释放 advisory lock；即使脚本崩溃，数据库连接断开也会自动释放两类锁。应用启动与健康检查验证 named lock 是否被异常长时间持有。故障测试分别在 dump 开始前和进行中终止备份进程，并确认新的写事务可以恢复。

密钥轮换生成新的活动 `key_id`，后续备份使用新密钥；只要历史备份仍引用旧 `key_id`，旧密钥就必须保留。每次轮换后使用独立恢复副本完成一次临时环境恢复演练，确认本机密钥文件丢失时仍能解密。

凭据不得通过命令行参数传入。脚本使用受限权限的临时 MySQL option file 或 `mysql_config_editor` 登录路径，执行后清理临时凭据文件。

安全恢复流程：

1. `restore-verify.ps1` 生成随机数据库名 `clsen_restore_<uuid>` 和位于明确测试根目录下的随机文件目录。
2. 脚本拒绝把 `clsen_data`、工作区根目录、磁盘根目录或任何已有生产文件根作为目标。
3. 解密并恢复到临时目标，验证迁移版本、文件哈希、发布指针、版本数量和审计数量。
4. 输出验证报告；只有验证完成后才允许管理员选择保留或清理临时目标。
5. 清理前再次解析并确认目标仍位于指定恢复测试根目录内，绝不默认覆盖或删除生产数据。

后台任务与文档：

- outbox worker 使用幂等消费和重试，处理汇总重算及站点配置变化。
- worker 重启或同一事件重复投递不得重复应用结果。
- 管理员页面接入备份状态、最近恢复验证和失败原因。
- 提供本地 Windows 运行、日常备份、恢复演练和故障排查说明。
- 提供数据管理员/查看人员使用手册，覆盖导入、审核、发布、修订和常见错误。

验收命令：

```powershell
.\scripts\backup.ps1 -Destination .\data\backups
.\scripts\restore-verify.ps1 -BackupRoot .\data\backups -TemporaryRoot .\data\restore-tests
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_backup_write_barrier.py
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_backup_key_rotation.py
.\.venv\Scripts\python -m pytest .\backend\tests\integration\test_outbox_worker.py
```

验收要求：从随机空数据库和空文件目录恢复完整测试备份；所有文件哈希、发布指针和审计数量一致；整个过程没有覆盖正式数据库或文件。

建议提交：`ops: add safe local backup and recovery`

### 阶段 10B：服务器容器部署

目标：在 Docker/CI 或服务器可用后验证约 20 人部署。写出配置文件不等于本阶段完成，所有容器必须实际构建和运行通过。

本地容器验收状态（2026-08-11）：

- 已交付 MySQL 8.4.11、Python 3.14.7、Node 24、Nginx HTTPS、FastAPI、worker、迁移、维护和随机恢复验证容器；MySQL 仅在内部网络开放并强制 TLS，运行账号使用最小权限，秘密通过 Docker secrets 注入，长期服务以非 root、只读根文件系统和移除 capabilities 的方式运行。
- `pwsh .\ops\verify-deployment.ps1` 已完整成功执行。该脚本实际构建全部 profile 镜像，启动并等待 MySQL/backend/worker/frontend/nginx 健康，验证 HTTPS readiness 与 HSTS/CSP/nosniff，重建隔离库 `clsen_data_test_container`，执行迁移往返 28 项、数据库约束 69 项、阶段 5/6 的 18/7 项、草稿事务/日期调整 13/9 项、管理/认证/审核工作区 47 项、发布流程/并发 17 项、发布看板 3 项及额外 MySQL 分组 47 项，全部通过。
- 真实 HTTPS 并发测试使用 20 个独立 viewer 完成共 100 次已发布看板读取，并同时执行 1 次 data_manager 发布；只观察到完整旧版本或完整新版本，1 项通过。自动验收随后创建 AES-256-GCM 加密备份 `9754fba7950442a4843fe97315256435`，并以验证 UUID `78b4562e3a69427f9aeb5ed76280b4c4` 成功恢复到随机数据库和随机文件目录；验证目标已由 `--cleanup` 在成功后清理。
- 自动脚本的首次完整执行暴露并修复了 PowerShell 7.6 对 `-d`/`-e` 通用参数缩写的误解析，以及响应头字典不能使用 `.Contains(string)` 的兼容问题；合同测试覆盖这些回归点。整个验收只操作 Docker 卷和容器测试库，没有连接或迁移本机正式库。
- 上述结果完成阶段 10B 的本地 Docker 交付验收；共享服务器上线前仍需替换真实域名可信证书、配置防火墙和异地密钥/备份，并在目标服务器按 `ops/DEPLOYMENT.md` 再运行一次完整验收。远程 CI/PR 结果由对应 checks 页面记录，不以本文静态记录替代。

新增文件：

- `ops/docker-compose.yml`
- `ops/nginx/default.conf`
- `ops/DEPLOYMENT.md`

实施步骤：

1. 提供 Nginx、前端、FastAPI、worker 和 MySQL 8.4 的 Docker Compose。
2. Python 镜像固定 3.14，并从带哈希依赖锁安装；MySQL 使用 `caching_sha2_password` 与内部 TLS。
3. MySQL 只在容器内部网络开放；Nginx 提供 HTTPS、安全响应头和合理上传大小限制。
4. 在 Docker 可用环境执行镜像构建、空库迁移、健康检查、真实备份恢复和升级测试。
5. 使用 20 个并发只读用户和 1 个发布操作进行负载与一致性验证。
6. 验证 Python 3.14/MySQL 8.4 的完整后端套件，而不只验证容器能启动。

验收命令：

```powershell
docker compose -f .\ops\docker-compose.yml config
docker compose -f .\ops\docker-compose.yml build --pull
docker compose -f .\ops\docker-compose.yml up -d
docker compose -f .\ops\docker-compose.yml exec backend alembic upgrade head
docker compose -f .\ops\docker-compose.yml exec backend python -m pytest tests/integration
```

阶段 10B 的本地 Docker 验收已完成。真实服务器上线不是代码提交自动完成的操作：必须在目标主机替换可信证书、配置公网边界与异地恢复材料，并再次运行完整部署验收；这不会触碰或替代当前本机正式库。

建议提交：`ops: add verified server deployment`

### 阶段 11：Agent 接入（后续独立里程碑）

在 MVP 验收后再选择具体模型。接入时只允许调用阶段 9 已验证的只读工具：

- 查询日期范围经营指标。
- 查询 SKU/ASIN 表现。
- 查询退货原因与事件趋势。
- 返回数据版本、站点配置版本和计算口径。
- 生成纠错建议，但建议只能由人工转入草稿。

Agent 里程碑需要单独设计提示词版本、工具权限、引用展示、评测集和费用控制，不与首版数据平台同时上线。

## 6. 阶段性演示点

为减少长周期黑盒开发，安排四次可操作演示：

1. 数据基线演示：展示 62 份文件清单、哈希、行数与合计。
2. 后端可信导入演示：上传一份经营报告和一份退货报告，查看解析尝试、基线与校验。
3. 审核工作台演示：完成纠错、警告确认、备注和发布，并验证另一日期不受影响。
4. MVP 演示：使用三类账号完成上传、发布、看板、修订和管理员回滚。

每次演示通过后再进入后续页面或运维阶段。

## 7. 完整验收命令

在本地原生环境执行：

```powershell
.\.venv\Scripts\python -m ruff check .\backend
.\.venv\Scripts\python -m mypy --config-file .\backend\pyproject.toml .\backend\app .\backend\tests
.\.venv\Scripts\python -m pytest .\backend\tests --require-mysql --cov=app --cov-report=term-missing
pnpm --dir .\frontend lint
pnpm --dir .\frontend typecheck
pnpm --dir .\frontend test --run
pnpm --dir .\frontend build
pnpm --dir .\frontend exec playwright install chromium
pnpm --dir .\frontend exec playwright test
python .\tools\verify_golden_manifest.py --source .\表格 --manifest .\data\golden\golden-manifest.json
.\scripts\test-runtime-matrix.ps1 -PythonVersion 3.14 -MySQLVersions 8.0,8.4 -Suite all
.\scripts\backup.ps1 -Destination .\data\backups
.\scripts\restore-verify.ps1 -BackupRoot .\data\backups -TemporaryRoot .\data\restore-tests
git diff --check
git status --short
```

服务器或 Docker 可用后追加：

```powershell
docker compose -f .\ops\docker-compose.yml config
docker compose -f .\ops\docker-compose.yml build --pull
docker compose -f .\ops\docker-compose.yml up -d
docker compose -f .\ops\docker-compose.yml exec backend alembic upgrade head
docker compose -f .\ops\docker-compose.yml exec backend python -m pytest tests/integration
```

## 8. 实施完成定义

MVP 只有在以下条件全部满足时才算完成：

- 62 份真实 CSV 与独立 golden manifest 全部一致。
- 上传不会直接进入看板，必须经过审核发布。
- 任何人工差异都可由追加式修改记录完整解释。
- 任意一天、任意报表类型都能独立修订且不影响其他数据集。
- 数据管理员能调整未发布上传草稿的日期，只有管理员能移动已发布版本。
- 发布、回滚和跨日期移动通过事务与并发测试。
- 管理员、数据管理员和查看人员权限通过服务端负向测试。
- 查看人员只能看到已发布、已脱敏的数据。
- 本地备份完成一次从零恢复演练。
- Python 3.14 与 MySQL 8.0/8.4 的兼容矩阵全部通过。
- 全部质量命令通过，仓库不包含真实订单数据或秘密。
- 设计规格、数据库迁移、运行说明与用户操作说明保持一致。

以上条件完成即代表本地 MVP 完成。阶段 10B 的本地 Docker 镜像构建、容器运行、迁移、集成测试、并发一致性和恢复演练已经通过；真实服务器上线仍以目标主机上的域名证书、网络边界、异地恢复材料和再次验收结果为准。

## 9. P0 后继实施边界（2026-08-20）

本计划已完成的日报表结构与原始行保持不可变。P0 只能追加 dataset scope assignment 与 Seller SKU match-key sidecar，并在新 dataset/日报导入/日期改派/materialization 的既有事务中维护唯一 assignment；禁止把账号、Marketplace 或目录身份回写原日报表。

所有退货发布入口必须经同一个 return-dedup staging service/coordination helper，worker 只生成 proposed snapshot，不推进 current。publish、rollback、published move 和 undo 的最终短事务同时 CAS publication/dedup pointer；旧 UI 必须显示 building、等待、失败、可重试和命令恢复，不能把 staging 成功之前的版本冒充 published。该工作属于 `2026-08-20-product-style-variant-analytics-foundation-implementation.md` Tasks 4–5，不重开或改写本计划已完成阶段。
