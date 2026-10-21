# 可切换应用发布管理设计规格

日期：2026-08-12
状态：完整设计已确认，等待书面规格审阅；尚未实施
里程碑：阶段 11B

## 1. 背景与当前状态

当前系统已经具备单机 Docker Compose 服务器部署、MySQL 迁移、加密备份、隔离恢复验证、HTTPS 入口以及应用健康检查。现有升级流程仍是在服务器上拉取代码、现场构建镜像、执行迁移，再重建长期运行服务。

当前仓库尚不具备可操作的应用版本库和版本切换能力：

- backend、worker、migrate 和 frontend 服务仍由生产 Compose 使用本地 build 构建。
- 没有绑定 Git 提交、组件镜像 digest、数据库兼容范围和测试证明的不可变发布清单。
- 没有 current release、previous stable release 或未完成发布事务的持久状态。
- 没有选择历史应用版本、预演、发布、失败回切和崩溃恢复的统一 PowerShell 入口。
- 现有文档只允许在人工确认数据库兼容后回滚已知镜像，明确禁止盲目降级数据库。
- 阶段 11A 设计了 Agent Runtime 内部版本记录和 current pointer，但它不能替代整套前端、后端、worker 和 Runtime 的应用版本发布。

当前已实现的每日业务数据发布版本、站点配置版本和未来的 Agent Runtime 内部版本都继续独立存在。阶段 11B 只管理应用制品和部署，不移动每日数据发布指针，不修改业务数据，也不把数据库恢复伪装成普通应用回滚。

## 2. 已确认的产品决定

阶段 11B 采用以下已确认决策：

1. 管理员可以在服务器 PowerShell 中选择任意满足安全条件的历史应用版本进行发布。
2. 不提供网页管理入口，主应用和 Agent Runtime 都不得持有 Docker 控制权限。
3. 受保护默认分支 master 的完整流水线通过后，GitHub 自动构建并登记一个可发布版本；生产服务器不会自动升级。
4. 初始版本序列使用 v11A.1.N，其中 N 为只增不减的正整数构建号。
5. 默认保留最近 20 个可发布版本；长期保留版本不参与普通淘汰。
6. 采用事务式单槽发布，允许短暂停机，不维持长期运行的蓝绿双槽。
7. 发布脚本自动完成加密备份、隔离恢复验证、兼容性检查和允许的向前迁移。
8. 数据库不自动降级。迁移后必须同时兼容目标版本和本次发布开始时正在运行的源版本；成功提交后，该源版本才成为上一稳定版本。
9. 目标启动失败时，只有本次发布冻结的源版本通过当前数据库兼容验证，才允许自动重新启动；否则保持维护状态。
10. 升级和回滚本质上都是“发布一个已批准版本”，必须走完全相同的检查和审计流程。

## 3. 目标

阶段 11B 需要实现：

1. 为每个通过门禁的 master 提交生成可追溯、不可覆盖的应用版本。
2. 让生产服务器只部署签名发布清单中固定的镜像 digest，不再现场构建应用。
3. 让管理员能够列出、检查、预演和发布最近 20 个或长期保留的安全版本。
4. 在应用切换前验证供应链身份、组件完整性、配置、Secret、磁盘、备份和数据库兼容性。
5. 以明确状态机执行短停机切换，并在每一步留下不含业务内容和秘密的审计记录。
6. 在目标应用失败且数据库仍兼容时自动恢复本次发布开始时冻结的源应用版本。
7. 在迁移部分失败、数据库状态不确定或旧版本兼容性不成立时保持维护状态，禁止猜测性恢复。
8. 保留当前版、上一稳定版和长期保留版所需制品，避免清理破坏回滚能力。
9. 为以后升级到蓝绿发布保留相同的发布清单、兼容合同和版本状态，不把单槽细节泄漏到应用代码。

## 4. 非目标

首版不包含：

- 提交到 master 后自动部署生产环境。
- 在网页管理页面选择版本、调用 Docker 或显示宿主机凭据。
- 任意数据库 downgrade、自动覆盖式恢复生产数据库或回退业务数据。
- 零停机、流量百分比灰度、多服务器滚动升级、Kubernetes 或跨区域发布。
- 将 MySQL、原始业务文件、备份卷、密钥环或站点数据打包进应用版本。
- 使用 latest、可移动镜像标签、未签名本地镜像或任意 Git 提交直接部署。
- 允许跳过签名、备份、恢复、兼容性或健康门禁的普通生产参数。
- 用应用版本切换替代每日数据回滚、站点配置修订、Agent kill switch 或 Agent Runtime 内部版本控制。
- 承诺所有历史版本永远可以在线发布。版本必须仍有制品、未被撤销并兼容当前数据库。

## 5. 术语与版本轴

### 5.1 应用发布版本

应用发布版本是一个不可拆分的制品集合，至少包含：

- frontend 镜像；
- backend API 镜像；
- worker 镜像；
- migrate 镜像；
- 阶段 11A 的 Agent control plane 与 Agent Runtime 镜像；
- 这些组件使用的生产 Compose 模板和受控配置 schema；
- 数据库、公共 API、Agent 控制协议及浏览器客户端兼容声明。

worker 和 migrate 可以复用 backend 的同一镜像 digest，但发布清单仍需分别声明服务角色，防止部署时混用其他版本。

### 5.2 独立版本轴

以下版本不能混为一个数字，也不能被应用发布隐式改写：

- 每日业务数据发布版本；
- 站点配置版本；
- 数据库 Alembic revision；
- Agent Runtime、模型、提示词、工具和校验器内部版本；
- 备份 artifact 格式版本；
- 应用发布版本 v11A.1.N；
- 发布清单格式版本。

应用发布清单只声明它支持哪些版本及准备激活哪个 Agent Runtime bundle。旧回答、业务发布版本和站点配置引用保持不变。

### 5.3 “任意版本”的准确含义

管理员可选择的目标必须同时满足：

- 已由可信流水线完成并进入 approved 状态；
- 制品仍可从注册表获取，或作为当前/上一稳定版本完整保存在本机受保护缓存；
- 签名、来源证明、SBOM 和组件 digest 验证成功；
- 未进入 revoked 状态；
- 当前数据库 revision 位于目标的读写兼容集合，或存在一个允许的向前迁移路径；
- 迁移后的 revision 同时受目标版本和本次发布开始时的 current 版本支持；该 current 在发布成功后成为 previous_stable；
- 配置、Secret 和运行环境满足目标版本合同。

不满足任一条件的历史版本仍可审计，但不能通过普通发布命令上线。

## 6. 总体架构

### 6.1 三个信任域

系统分为三个边界清晰的信任域。

GitHub 构建域负责：

- 对受保护 master 提交运行完整测试；
- 构建应用镜像；
- 生成 SBOM、来源证明和漏洞扫描结果；
- 分配版本号；
- 生成并签署不可变发布清单；
- 将完整版本原子地标记为 approved；
- 发布一个带单调 generation、有效期和前序摘要的签名 release catalog，作为 approved、revoked、archived 和 long_term_retained 的唯一中央权威。

服务器发布控制域负责：

- 使用独立 PowerShell 控制器读取版本库；
- 用专用只读注册表凭据拉取镜像；
- 验证发布清单、签名、来源和 digest；
- 串行执行备份、迁移、切换、验证和恢复；
- 持久化本机发布事务与 current/previous 指针；
- 在成功后登记不含业务内容的部署回执。

应用运行域负责：

- 提供 frontend、backend、worker 和 Agent 服务；
- 使用现有最小权限数据库、文件和 Secret 边界；
- 暴露版本一致性和健康探针；
- 不接触宿主机 Docker socket、注册表发布权限或发布状态私钥。

### 6.2 稳定部署基座

单槽发布不会把所有服务器基础设施一起替换。以下内容属于稳定部署基座：

- MySQL 及其数据卷和 TLS 材料；
- raw、backup、restore、keyring 等持久卷；
- 宿主机 PowerShell 发布控制器和受保护状态目录；
- 能在应用停止时继续提供维护页的稳定 HTTPS edge；
- 发布锁、凭据和发布日志；
- Docker 网络与应用槽位的稳定服务发现合同。

稳定基座的升级使用独立维护流程，不能由被发布的应用版本自我替换。这样旧应用启动失败时，发布控制器、维护页和 MySQL 仍可用。

实施时必须把现有单一 Compose 拆为稳定 base project 与可替换 app project。两者通过名称固定的 external edge/data 网络和受控卷合同连接。base project 中的 edge 使用受保护、原子替换的 edge-mode 文件在 maintenance 与 app-upstream 之间切换；文件写入、Nginx 配置校验、reload 和实际响应验证必须全部成功，journal 才记录 mode 完成。现有 Nginx 对 backend/frontend 的启动依赖必须移出稳定基座，否则应用停止时维护页无法独立工作。

### 6.3 单槽应用组

应用槽位同一时刻只运行一个发布版本。所有应用容器带有以下不可变标签：

- release version；
- release manifest digest；
- source Git SHA；
- deployment operation UUID；
- service role。

发布控制器通过实际镜像 digest 和容器标签核对运行状态，不能只相信 Compose 项目名或本地状态文件。

## 7. 自动版本编号

### 7.1 格式

初始版本格式固定为 v11A.1.N：

- N 是十进制正整数；
- 不允许前导零；
- 版本按 N 的整数值排序，不能按字符串或 SemVer 推断；
- 版本号一经分配永不复用；
- 允许因失败或隔离产生空号；
- 发布序列前缀的改变必须通过独立评审，不能由普通构建自动推断。

`v11A.1.N` 是本里程碑已确认的初始自动编号形式，不宣称它符合 SemVer。阶段 11A/11B 以后若进入新的产品序列，必须显式配置新的不可变前缀和兼容策略，不能让脚本根据分支名、日期或当前最大标签自行改名。

### 7.2 分配与并发

版本发布 job 使用固定的仓库级串行并发组，禁止 cancel-in-progress。完整测试和制品门禁通过后，才进入编号与最终发布区段。

分配规则为：

1. 若同一 source SHA 已存在 approved 发布，重跑只核对其不可变内容并幂等结束。
2. 否则读取受保护仓库中的全部历史编号记录，包括失败后已经占用的保留号，计算下一整数。
3. 使用 GitHub 原子创建语义建立绑定该 source SHA 的不可变版本 tag；tag 创建成功就是编号占用事实，后续失败也不能删除或复用。
4. 若发生冲突，禁止覆盖；重新读取状态并安全失败或申请新编号。
5. 部分上传、签名失败或最终门禁失败不能标记为 approved。

不能使用“读取最大标签后无锁写回”的方式，也不能把可重置或可重跑的工作流计数当作唯一可信编号。

## 8. 发布清单

### 8.1 不可变清单

每个版本只有一份规范化发布清单。初始格式使用独立的 release_manifest_format 标识，未知格式必须拒绝。清单至少包含：

- application_release_version；
- release series 和整数 ordinal；
- source repository、受保护 ref、完整 Git SHA；
- 构建工作流身份、run identity 和构建时间；
- 各服务的 OCI repository、平台和 sha256 digest；
- Compose artifact 的 digest；
- 配置 schema 版本和必需 Secret 名称集合，不包含 Secret 值；
- 目标 Alembic head；
- 目标版本明确支持的数据库读写 revision 集合或经签名的兼容关系；
- 与上一稳定版本共同运行所需的 expand/contract 兼容声明；
- public API、browser client、Agent control protocol 和 runtime bundle 兼容版本；
- Agent Runtime 默认 bundle 及允许 bundle；
- SBOM、来源证明、签名、扫描报告和门禁结果的 digest；
- 发布清单自身的 canonical digest。

金额、密码、访问令牌、证书私钥、数据库 URL、用户数据和业务配置值不能进入清单。

### 8.2 完整发布的原子可见性

构建过程可以产生临时 SHA 标签或隔离制品，但服务器版本列表只读取 GitHub Release 中的最终 signed approved record。该 Release 绑定受保护且不可覆盖的 `v11A.1.N` tag，附带发布清单及其签名/证明引用，并以非 draft、非 prerelease 状态作为 approved 可见性标志。只有所有必需组件、证明和签名均存在且相互引用一致后，发布 job 才在最后一步创建该 Release；不存在“先 approved 后补组件”的状态。

同一版本号、Git SHA 或镜像显示标签被重新指向时，生产仍只信任签名清单中的 digest。任何清单绑定冲突都使版本进入不可发布状态。

### 8.3 签名版本目录

GitHub Release 证明一个版本曾完整形成；签名 release catalog 是服务器判断版本当前能否发布的唯一中央权威。catalog 至少包含：

- 单调递增 generation、generated_at、expires_at 和 previous_catalog_digest；
- 每个已知版本的 manifest digest、注册状态和状态发生时间；
- long_term_retained 标记；
- revoked/archived 的关闭式原因码；
- catalog 自身 digest、签名和签名工作流身份。

服务器持久化 last accepted generation 和 digest，拒绝 generation 回退、前序链断裂、过期 catalog、未知状态转换或签名身份不匹配。普通 list 可以显示上次缓存结果并明确标记 stale；inspect、WhatIf 和 deploy 必须获得未过期 catalog。catalog 不可用或过期时禁止开始新发布，但不影响当前健康应用继续服务。状态更新顺序固定为先保护/生成所需 OCI 制品，再发布新 catalog；归档清理则先发布 archived catalog 并等待生产回执不再引用，最后删除制品。

## 9. GitHub 流水线与供应链

### 9.1 分支和工作流边界

自动产版前必须先满足：

- master 是受保护的默认分支；
- 必需 CI 检查通过后才能合并；
- 禁止 force-push 和删除受保护分支、版本引用；
- 管理员不能静默绕过必需门禁；
- v11A.1.* 使用不可覆盖的 tag/ruleset 规则；
- 工作流依赖固定到完整 commit SHA，而不是可移动主版本标签；
- 仓库只允许 GitHub 官方和明确审核的 Action。

若未来将默认分支改名为 main，必须先完成仓库、ruleset 和工作流迁移。阶段 11B 不同时匹配 master 与 main，避免非预期分支获得发布权限。

### 9.2 最小权限

普通测试 job 保持 contents read。只有最终发布 job 可获得目标包的 packages write；需要签名和来源证明的 job 才获得最小的 OIDC 与 attestation 权限。PR 工作流、任意分支工作流和测试容器都不能获得生产发布权限。

生产版本必须从受保护 master 的 source SHA 重新构建，不能直接采用 PR 上传的镜像或不受信任 artifact。

### 9.3 制品门禁

一个版本至少通过以下门禁后才可 approved：

- backend、frontend、Agent Runtime 的锁定依赖安装与普通离线测试；
- MySQL 8.0 与 8.4 兼容和迁移测试；
- frontend 类型、单元和浏览器流程测试；
- 容器合同与最小权限测试；
- 数据库 N/N-1 兼容矩阵；
- 备份和恢复合同；
- 镜像内容、Secret 和敏感文件扫描；
- SBOM 和构建来源证明生成；
- 发布清单 canonicalization、签名和交叉 digest 验证；
- 不存在未批准的 Critical 漏洞或策略明确阻止的 High 漏洞。

安全例外必须是有负责人、理由、截止时间和受影响 digest 的结构化记录。过期例外自动使尚未部署的版本不可发布，不允许使用自由文本临时绕过生产脚本。

### 9.4 基础镜像和生产 Compose

应用 Dockerfile 的基础镜像以及稳定部署基座中的 MySQL、Nginx、Alpine 等镜像都必须按 digest 固定。应用发布使用的生产 Compose：

- 只能包含 image@sha256 形式的应用镜像引用；
- 不能包含应用 build；
- 不能使用 latest；
- 不能只依赖可移动 tag；
- 不能混合来自不同发布清单的组件。

基础设施 digest 的升级属于基座维护，不由普通应用版本切换暗中完成。

## 10. 服务器凭据与权限

### 10.1 发布操作身份

发布脚本只能由受控的宿主机发布管理员身份运行。该身份拥有 Docker 控制能力，因此在安全等级上等同于宿主机高权限管理员，不能授予 Web 应用账号、普通查看人员或 Agent Runtime。

宿主机通过 ACL 限制以下内容：

- 发布控制器；
- release state 和 journal；
- registry credential；
- deployment receipt credential；
- Compose 渲染目录；
- 下载的签名清单和证明；
- 本机受保护镜像缓存元数据。

实现合同为：使用一个不能交互登录普通应用、且不被服务进程复用的专用本地 OS 发布身份；只有该身份和显式 break-glass 管理员可写发布目录并调用 Docker。脚本及稳定基座清单在运行前核对受保护路径、预期所有者、ACL 无继承漂移和批准文件 SHA-256；不从当前目录或可写 PATH 搜索辅助程序。PowerShell transcript、Docker 输出和结构化日志经过固定字段 allowlist，任何 registry token、数据库 Secret 路径内容和命令参数 Secret canary 出现都使验收失败。

### 10.2 GitHub 与 GHCR 凭据

服务器使用专用机器身份读取版本和 GHCR 包：

- 只允许读取指定仓库和包；
- 不具备源码写入、版本覆盖、包删除或 tag 修改权限；
- 不复用个人 gh 登录；
- 通过操作系统 credential helper 或等效严格 ACL secret store 保存；
- 通过 stdin 或受保护文件传递，不出现在命令行、Compose、环境转储或日志；
- 只存在于宿主机，不注入应用容器。

成功部署回执使用独立、权限更窄的凭据，只能写部署状态，不能发布或删除包。若回执暂时失败，本机进入 committed_pending_receipt 并重试；中央清理在生产回执过期时必须暂停，而不是猜测哪些版本可删除。

### 10.3 数据库和应用 Secret

现有 root、migrator、app、backup、Agent reader 和 session Secret 继续分离。迁移所需高权限只进入一次性迁移进程，并按既有 grant → verify → migrate → finally revoke → reverse verify 控制流收敛。

版本切换不轮换 session secret，因此用户会话可延续。清单只声明 Secret 合同，不读取、复制或上传 Secret 值。

## 11. 服务器状态与独占控制

### 11.1 权威状态

服务器使用受保护的追加式 deployment journal 记录：

- 单调序号；
- operation UUID；
- 发起时间和完成时间；
- 发起的 OS 身份；
- `source_release`、`target_release` 和两份 manifest digest；其中 `source_release` 永远等于本次 operation 创建时实际运行且已提交的 current，不等于 operation 开始前记录的 previous_stable；
- source 的实际容器 digest、Agent Runtime current pointer、edge mode 和配置 schema；这些值在 operation 内冻结，构成唯一自动恢复候选；
- 预检、备份、迁移、排空、启动、验证和恢复的关闭式结果码；
- 实际容器 digest；
- current release 和 previous stable release；
- 数据库 revision before/after；
- 部署回执状态。

日志不得包含数据库内容、问题、回答、文件名、密码、令牌、证书私钥或原始 provider 错误。current/previous 快照是 journal 的派生缓存，通过同目录临时文件、完整 flush 和原子替换更新；崩溃恢复以 journal、容器实际 digest 和数据库实际 revision 共同判定。

operation 开始前的 previous_stable 只用于审计和保留，不能作为本次失败的自动恢复目标。只有成功提交 target 后，`current=target` 且 `previous_stable=source_release`；若 operation 中止或回切，current/previous 均保持开始前的值。

### 11.2 锁与维护边界

任一 publish、rollback、backup、restore、migration 或基座维护操作都必须遵循同一锁顺序：

1. 宿主机 deployment lock；
2. 数据库维护屏障；
3. 具体备份、迁移或恢复子锁。

不能反向获取锁。普通定时备份发现发布进行中时应排队或安全退出，不能并发读取一个正在迁移的数据库。

锁包含持有者、operation UUID 和心跳。进程消失不等于可以直接删除锁；恢复逻辑必须先核对 journal、容器和数据库，再决定接管。

## 12. 发布命令

统一入口为 ops/release.ps1，至少提供：

    pwsh .\ops\release.ps1 list
    pwsh .\ops\release.ps1 inspect -Version v11A.1.23
    pwsh .\ops\release.ps1 status
    pwsh .\ops\release.ps1 history
    pwsh .\ops\release.ps1 recover -OperationId <uuid>
    pwsh .\ops\release.ps1 deploy -Version v11A.1.23 -WhatIf
    pwsh .\ops\release.ps1 deploy -Version v11A.1.23

命令语义：

- list 默认显示最近 20 个、长期保留版本、本机 current 和 previous。
- inspect 显示签名身份、Git SHA、镜像 digest、数据库和协议兼容状态、撤销/归档状态及门禁摘要。
- status 将 journal、容器 digest、edge 模式和数据库 revision 做一致性核对。
- history 显示不含内容的本机发布事务。
- recover 只接管一个已存在且未终止的 operation，并严格执行第 14.2 节决策表；它不能改选 target。
- deploy 既用于升级，也用于选择旧版本回滚。
- WhatIf 只读取和计算，不拉取镜像、不创建备份、不迁移、不切换容器、不写 journal。
- 目标等于 current 时幂等返回，不重新迁移或重启。

list、inspect、status、history 和 WhatIf 均为严格只读命令：不得获取写锁、接管陈旧锁、拉取制品、reload edge、启动/停止容器或写 journal。若发现未终止事务，它们返回 recovery_required。只有 deploy 在确认无未终止事务时可以新建发布；显式 `recover -OperationId <uuid>` 才能在核对专用 OS 身份、陈旧锁和状态证据后接管同一 operation。recover 不允许选择新 target。

生产模式不提供 SkipBackup、SkipSignature、SkipCompatibility、SkipMigrationCheck、SkipHealth 或 ForceDeploy 等绕过参数。紧急灾备使用单独文档化的 break-glass 流程，不能伪装成普通 deploy。

## 13. 动态版本状态

版本注册状态包括：

- building：尚未形成完整版本，仅 CI 可见；
- approved：完整、签名且通过自动门禁；
- revoked：发现安全、数据或供应链问题，永久禁止普通发布；
- archived：审计记录保留，但中央镜像可能已清理，普通发布不可用。

以下是环境相关叠加状态，不改写注册状态：

- current；
- previous_stable；
- long_term_retained；
- compatible；
- incompatible；
- locally_cached；
- deployment_in_progress。

revoked 是终止性安全状态。若误撤销或修复后希望重新发布，应生成新版本和新证明，不能把原记录静默改回 approved。

## 14. 发布事务状态机

### 14.1 正常路径

一次发布必须按以下顺序执行：

1. requested
   解析严格版本号，获取 deployment lock，生成 operation UUID；从已提交 journal 与实际容器中冻结 `source_release=current`、operation 开始前的 previous、组件 digest、Agent Runtime pointer、edge mode 和数据库 revision/fingerprint。两者不一致时进入 manual_intervention，不能猜测 source。

2. catalog_verified
   获取未过期且 generation 单调前进的签名 release catalog 和目标发布清单，验证仓库、工作流、master ref、签名、来源证明、SBOM、注册状态和 digest。

3. compatibility_planned
   读取实际 Alembic revision；计算是否无需迁移或仅需允许的向前迁移；验证迁移后 target 与冻结 source 的支持交集。operation 开始前的 previous 不参与本次自动恢复资格判断。

4. artifacts_prepared
   验证磁盘空间并按 digest 拉取所有 target 镜像，确认冻结 source 的完整镜像与证明仍在本机；离线渲染生产 Compose；确认没有 build、latest、仅标签或跨版本组件。

5. target_preflight_passed
   在不连接生产写接口的隔离环境检查镜像启动、配置 schema、Secret 名称、容器用户、只读根文件系统和协议合同。

6. backup_verified
   创建新的加密备份，完成制品解密校验，并把这份备份恢复到随机隔离数据库和目录；恢复验证失败时不进入维护窗口。

7. isolated_compatibility_verified
   在隔离恢复副本上用 target migrate digest 升级到计划 revision，验证 schema fingerprint、权限和 definer；在只含隔离副本与合成 canary 的环境中，分别运行 target 与冻结 source 的读写合同。二者任一失败都不迁移生产。无写生产探针不能替代这项证据。

8. maintenance_entered
   稳定 edge 切换到维护页，拒绝新业务请求；backend、worker 和 Agent 停止接受新工作。

9. work_drained
   等待 HTTP 请求、数据库写事务、worker 租约和 Agent 运行在明确上限内结束。Agent 创建被停止；仍在运行的 Agent 按阶段 11A fencing 和 possible-charge 规则安全终结，不能跨应用版本续跑。

从步骤 10 到步骤 16，数据库 writer fence 的唯一权威持有者是宿主机发布控制器管理的专用 fence-holder，不是 migrate、backend、worker 或普通 PowerShell 调用连接。holder 必须持续心跳；operation journal 冻结其进程身份与数据库 connection identity。发布控制器只有在步骤 16 或恢复表明确要求的 source 重启之前，才能请求它显式释放。

10. source_stopped_and_writer_fenced
    停止冻结 source 的 backend、worker、Agent control/runtime 及所有可能连接业务数据库的应用进程，禁用其 Docker 自动重启，再停止 frontend；确认 source 容器均不运行、MySQL process list 中没有 app/worker/Agent 会话。随后由发布控制器启动专用 fence-holder，以独立数据库连接获取现有数据库维护屏障的命名锁与 barrier-row 排他锁，并在 journal 记录数据库 connection identity、operation UUID 和获取完成证据。稳定 edge、MySQL、备份和发布控制器继续运行。未完成这些反向验证不得执行任何 DDL。

11. migration_started
    在调用 migrate digest 前先持久化 intent、计划 revision 和预期 schema fingerprint。该状态之后的任何中断都必须把生产 schema 视为未知，直至实际检查证明其精确状态。

12. migration_verified
    在 fence-holder 继续阻止普通 writer 的同时，使用只允许本次 operation 的独立迁移身份运行已验证 target migrate digest；迁移身份不通过普通应用 writer engine 获取共享 barrier lock。完成后检查实际 schema fingerprint、最小权限、view definer、触发器、Alembic revision，以及临时迁移权限的反向收敛。任一不匹配进入 manual_intervention。MySQL DDL 的隐式 commit 发生在迁移连接上，不得释放 fence-holder 的独立连接和锁。

13. source_recovery_verified
    将签名兼容合同、步骤 7 的隔离副本 source 读写结果、生产实际 schema fingerprint，以及冻结 source 镜像对生产数据库的无写 compatibility probe 组合验证。全部通过才具有自动恢复资格；无写 probe 单独通过不能证明 source 可安全读写。

14. target_started_fenced
    用 target manifest digest 启动唯一应用槽位，但保持应用级维护 fence：API 不接受业务写入，worker 不领取任务，Agent 不创建或领取运行，edge 继续显示维护页。

15. target_verified_fenced
    核对实际镜像 digest，等待必需容器健康；验证数据库 revision、HTTPS、登录和授权只读流程、worker/Agent 暂停状态、Agent control/runtime 隔离状态及 public readiness 独立性。真实业务写入冒烟仍只在步骤 7 的隔离副本执行。

16. writer_fence_released
    target 仍保持应用级维护 fence，worker 与 Agent 仍暂停，edge 仍显示维护页。先持久化 release intent，再让专用 fence-holder 在同一数据库连接上提交/回滚 barrier-row 事务并释放命名锁；核对返回值、connection identity 和 `IS_USED_LOCK`/等价所有权检查均证明本 operation 不再持有屏障，最后停止 fence-holder 并写 completion。结果未知或残留锁不允许激活 target。

17. target_activated
    在 edge 仍为维护页时解除 target 应用 fence，启动 worker 与 Agent 的正常领取能力，并验证 target 操作健康；此时只允许内部受控后台活动，尚无外部用户流量。

18. traffic_restored
    稳定 edge 原子恢复到 target upstream，验证公开 HTTPS、release identity 和浏览器 release handshake。若失败，按恢复表回切 source 或保持维护。

19. commit_recorded
    在确认 edge 实际指向健康 target 后，追加 journal 并原子更新派生快照为 `current=target`、`previous_stable=source_release`。operation 开始前 previous 仍保留在不可变 journal。该状态不是中央回执成功终态，但本机 current 已与实际流量一致。

20. committed 或 committed_pending_receipt
    本机成功证据完整后上传不含业务内容的部署回执。上传成功进入 committed；若只有回执暂时失败，进入 committed_pending_receipt，target 继续服务但禁止新发布，直至同一 operation 补齐回执并进入 committed。

每个有副作用的步骤均先追加 `<step>_intent`，完成后才追加上述 durable state；intent 没有 completion 时按“可能已经发生”处理。每一步只有前一步产生完整且可验证的记录后才能进入。中间状态不能显示为成功发布。

允许的结果状态只有：

- aborted：生产数据库和 committed current/previous 未改变，source 流量已验证恢复；
- rolled_back：source 曾停止或 target 曾启动/提交，但已按冻结证据恢复 source；current/previous 恢复 operation 开始前值；
- committed：target 正在服务且中央回执完成；
- committed_pending_receipt：target 正在服务，只有中央回执待补；
- manual_intervention：实际 schema、容器、edge 或指针无法安全归类，保持维护且禁止新 operation。

`recovery` 是 recover 命令的执行模式，不是可以掩盖真实阶段的结果状态。

### 14.2 崩溃与失败决策表

recover 必须重新验证 journal 链、intent/completion、实际容器 digest、edge mode、数据库 revision/fingerprint、连接会话和备份证明，再按下表执行唯一允许的策略：

| 最后可证明边界 | 允许的自动处理 | 无法满足条件时 |
|---|---|---|
| requested 至 isolated_compatibility_verified | 清理临时制品；current/source 继续服务；记录 aborted | manual_intervention |
| maintenance_entered 或 work_drained，且 source 未停止、数据库 fingerprint 未变 | 恢复 source admission，验证 source 健康后原子恢复 edge；记录 aborted | manual_intervention |
| source_stopped_and_writer_fenced，且没有 migration_started intent、数据库 fingerprint 未变 | 写入 barrier release intent；按步骤 16 的同一连接/所有权规则显式释放并验证屏障；完成后用冻结 digest 重启 source，验证后恢复 edge；记录 rolled_back | 屏障释放未知或其他检查失败时进入 manual_intervention |
| migration_started intent 存在但 migration_verified 不存在 | 检查实际 schema。只有它精确等于迁移前 fingerprint，或精确等于计划 fingerprint 且完整 source recovery 组合证据通过，才可先按步骤 16 显式释放屏障，再重启 source并记录 rolled_back | 保持维护并进入 manual_intervention；禁止自动 downgrade |
| migration_verified 至 writer_fence_released 之前 | 停止任何 target 进程；只有 source_recovery_verified 对当前实际 schema 仍成立时，才可按步骤 16 显式释放屏障、重启冻结 source并记录 rolled_back | manual_intervention |
| writer_fence_released 至 traffic_restored 之前 | 核对数据库屏障确实未被本 operation 或未知连接持有；停止 target，必要时重新获取屏障确认无 writer 后再按 source recovery 证据恢复 source；启动 source 前显式释放并验证该新屏障 | manual_intervention |
| traffic_restored 已有完成证据但 commit_recorded 不存在 | 核对 edge 实际指向、target digest 和健康；完全一致则记录 current/previous 并继续回执，否则按 source recovery 规则回切 | manual_intervention |
| commit_recorded 已存在但尚未形成结果 | current 必须已等于实际服务的健康 target；一致则只完成部署回执，不再重启或迁移；若证据漂移则停止外部流量并进入人工处置 | manual_intervention |
| committed_pending_receipt | 不切换容器、数据库或 edge，只重试同一签名部署回执；成功后进入 committed | 回执仍失败则保持该状态并告警 |
| committed、aborted 或 rolled_back | 终止状态，只读核对；禁止重复副作用 | 证据漂移则创建事故并进入独立 manual_intervention 处置，不能改写原终态 |

manual_intervention 不自动释放逻辑发布占用。专用 OS 发布身份执行同一 operation 的 recover 后，只有形成 committed、aborted 或 rolled_back 才能开始新 deploy；break-glass 灾备另行审计。

fence-holder 进程或数据库连接消失会让 MySQL 自动释放会话锁，但这只是一条需要检测的事实，不是成功 completion。recover 发现 holder 消失时必须确认 `IS_USED_LOCK`/barrier-row 所有权、实际 schema 和所有业务连接；只有能证明屏障已释放且没有未知 writer 时，才按表继续。任何 release intent 没有可验证 completion 都失败关闭。

### 14.3 维护页和短暂停机

维护页由稳定 edge 提供，不依赖目标应用。进入维护状态后：

- 返回固定中文说明和 Retry-After；
- 不泄漏版本、容器、数据库或错误细节；
- edge-healthz 仍可用于运维；
- public app readiness 明确不可用，不能把维护页 200 当作应用健康；
- 管理员可以从宿主机 status 查看真实状态。

系统不承诺固定停机时长。实际时间取决于排空、迁移和健康验证结果，不在未经测量时给出性能数字。

## 15. 数据库兼容与迁移

### 15.1 Expand/contract 规则

普通发布只允许 expand-compatible 迁移，例如：

- 新增可空字段或带安全默认值的字段；
- 新增表、索引、视图或触发器；
- 先双写/兼容读取，再在后续发布收敛的格式演进；
- 保留旧版本所需对象和语义。

同一个普通发布不得：

- 删除或重命名旧版本仍读取的表、列、视图或枚举值；
- 缩窄字段、改变旧值语义或重写不可变业务版本；
- 删除旧 API/Agent 协议仍依赖的数据；
- 把不可逆数据转换与应用切换捆绑；
- 依赖自动 Alembic downgrade 恢复。

contract 清理必须在确认所有允许回滚版本、长期运行任务、旧浏览器合同和恢复流程都不再依赖旧结构后，通过单独版本执行。执行后，相应旧应用版本自动变为 incompatible。

### 15.2 兼容合同

不能通过字符串比较 Alembic revision 判断兼容。CI 和发布清单必须使用迁移图及明确的受支持 revision 关系。

对目标版本 T、本次 operation 冻结的源版本 S 和迁移后数据库 D，普通发布至少证明：

- T 可在 D 上完成启动、读写和运维合同；
- S 可在 D 上安全启动和读写；operation 开始前的 previous_stable 不参与本次自动恢复证明；
- T 使用的 migrate image 从当前实际 revision 到 D 只有已批准的向前路径；
- D 的对象、权限、view definer 和触发器与清单完全一致；
- 没有未分类或部分应用的 migration。

上述 S/T 读写证明先在“本次备份恢复副本经 target migrate 升级到 D”之后用合成 canary 完成；生产迁移后的 S 无写 probe 只确认连接、schema fingerprint 和启动前合同。只有签名兼容声明、隔离副本读写结果、生产 fingerprint 和无写 probe 四者一致，才可认定 S 具备自动恢复资格。

选择更旧版本时，若它直接支持当前 D，则可以不降级数据库直接发布；若只支持较旧 revision，则显示 incompatible 并拒绝。

### 15.3 MySQL 非事务 DDL

MySQL DDL 不能被描述为完整事务回滚。迁移失败时可能已经留下部分对象，因此：

- 发布控制器立即保持 maintenance；
- 禁止自动执行 downgrade；
- 读取实际 schema，而不只读取 alembic_version；
- 只有冻结 source 的完整恢复组合证据对实际残留 schema 通过，才可自动重新启动它；
- probe 不通过时进入 manual_intervention；
- 从已验证备份恢复时，先恢复到隔离数据库，完整验证后再由明确的灾备流程切换，不能覆盖式猜测修复生产库。

## 16. Agent Runtime 协调

应用发布和 Agent Runtime 内部版本指针需要保持一致：

- 发布清单列出该应用版本内实际存在且兼容的 Runtime bundle digest。
- 进入维护后停止新 Agent run，并让已有 run 完成或按 fencing 规则终止。
- 目标启动前验证 agent_runtime_current 是否属于目标允许集合。
- 如需切换指针，使用阶段 11A 的 append-only runtime version、CAS current pointer 和审计机制；不能原地改写旧版本记录。
- 目标失败并恢复上一应用时，同样按审计指针恢复上一应用允许的 Runtime bundle。
- 旧回答继续引用原 run 的模型、提示词、工具、校验器和镜像 digest；应用发布不能重写历史 provenance。

阶段 11B 首版不新增普通用户模型选择，也不让应用发布回滚自动重跑旧问题。

## 17. 浏览器与会话兼容

单槽切换后，用户浏览器可能仍运行旧 frontend JavaScript。为避免旧客户端向新 backend 发出不兼容写请求：

- index.html 使用可重新验证/不长期缓存策略；
- 带内容 hash 的静态资源可长期缓存；
- frontend 构建内嵌 release manifest digest；
- backend 响应公开一个不含秘密的 current release identity；
- 所有变更型请求携带 client release identity；
- backend 发现客户端版本不在允许集合时，在执行业务写入前返回关闭式 client_release_mismatch；
- frontend 收到 mismatch 后保存不了解的表单内容不得自动重放，提示用户刷新并重新确认；
- 懒加载旧 chunk 失败时触发受控整页刷新。

会话密钥和 Cookie 合同保持兼容，因此切换本身不要求用户重新登录。若某版本需要破坏性会话格式变化，它不能进入普通可回滚发布窗口。

## 18. 失败恢复

### 18.1 目标启动或验证失败

若迁移未开始，停止目标并恢复本次 operation 冻结的 source 即可；source 就是 operation 开始时的 current。

若迁移已完成：

1. 停止目标应用；
2. 核对 actual database revision 和 schema fingerprint；
3. 重新核对冻结 source 的签名兼容合同、迁移后隔离副本读写结果和生产无写探针；
4. 完整组合证据通过时，用 operation 冻结的 source digest 与 Runtime pointer 启动 source；
5. 验证核心健康后恢复流量并记录 rolled_back；
6. 任一证据失败时保持维护页并进入 manual_intervention。

自动恢复不会修改业务数据指针，不执行数据库 downgrade，也不会把失败目标标记为 current。

### 18.2 进程、Docker 或主机中断

每个有副作用的步骤开始前和完成后都写 journal。只读 status 或新的 deploy 发现非终止状态时返回 recovery_required；只有显式 recover 可以接管并执行恢复：

- 验证 lock 持有者是否仍存活；
- 读取 edge 当前模式；
- 读取运行容器的真实 digest 和 operation label；
- 读取数据库实际 revision、迁移对象和权限；
- 核对备份/恢复证明；
- 严格按照第 14.2 节决策表继续恢复或保持维护。

不能仅因为目标容器正在运行就推断发布成功，也不能仅因为状态文件写了 current 就忽略 digest 不一致。

### 18.3 回执或注册表暂时不可用

开始普通发布前必须取得未过期、generation 不回退且链到本机 last accepted digest 的签名 release catalog 和完整目标制品。发布提交后若仅部署回执上传失败：

- 健康目标不因审计网络故障被反复切走；
- 本机状态为 committed_pending_receipt；
- 控制器持续有限重试并告警；
- 中央清理发现生产回执过期时全部暂停；
- 下一次发布前必须先修复未完成回执。

## 19. 版本保留、归档与撤销

### 19.1 默认保留

中央版本库默认保留最近 20 个 approved 且未撤销版本的完整镜像和 OCI referrer。以下版本额外受保护：

- 显式 long_term_retained；
- 最新生产 deployment receipt 指向的 current；
- 上一个成功生产 deployment receipt 指向的 previous_stable；
- 仍处于未完成发布事务的 source 或 target；
- 恢复演练明确引用的版本。

本机镜像清理也必须保护 current、previous_stable 和未完成事务目标。清理 multi-arch 镜像时必须同时保护平台子清单、签名、SBOM 和 provenance，不能留下表面存在但无法验证的版本。

### 19.2 长期保留

长期保留通过受保护 GitHub 工作流或等效中央审核操作设置，不使用生产 GHCR 只读凭据。标记和取消标记都追加审计。取消后版本仍需满足普通最近 20 和部署引用规则，才能被清理。

### 19.3 归档

归档只删除可重新拉取和普通发布所需的大体积制品，不删除：

- 版本号；
- Git SHA；
- 发布清单摘要；
- 签名和门禁摘要；
- 撤销记录；
- 部署历史；
- 审计时间和原因码。

已归档版本不能通过普通 deploy 自动重建。若确需恢复，必须从同一 source SHA 重新走当前可信流水线生成新版本号。

### 19.4 撤销

安全、数据正确性或供应链事件可以将版本标记为 revoked。清理和服务器 list 都读取签名 release catalog。若 current 被撤销：

- 告警并阻止以 revoked 版本为 target、与事故无关的横向普通部署和任何门禁绕过；
- 不盲目停止仍提供关键业务的应用；
- 允许专用发布管理员执行受限的 `deploy-away-from-revoked-current`：target 必须 compatible、approved 且未撤销，仍执行正常 deploy 的全部签名、备份、迁移、恢复和健康门禁，只额外记录关闭式事故原因；
- 若事件要求立即停服，使用稳定维护页和独立事故流程。

## 20. 健康与验收探针

目标版本至少提供：

- 进程存活探针；
- public readiness；
- 数据库 revision/权限兼容探针；
- worker heartbeat 和停止领取新任务能力；
- frontend release identity；
- browser/backend release mismatch 处理；
- Agent control plane、Runtime、mTLS 和 kill-switch 隔离状态；
- 版本、manifest digest 和实际 image digest 的一致性证明。

目标预检和上线后验证必须分开：

- 预检在隔离环境验证配置和完整业务读写流程；
- 生产上线后只执行安全、可审计且不篡改真实业务数据的健康与授权检查；
- 业务写入冒烟使用刚恢复的隔离库或专用合成环境；
- 生产探针不得发布、回滚或编辑真实每日数据；
- Agent/DeepSeek 依赖故障不能让现有公共 readiness 假失败，但发布验收仍单独检查 Agent 子系统处于清单声明的安全状态。

## 21. 测试策略

### 21.1 单元与合同测试

至少覆盖：

- 严格版本号解析、整数排序、空号和不复用；
- canonical manifest、重复 JSON key、未知格式和 digest 计算；
- 版本注册状态及不可逆 revoked；
- compatible/incompatible 动态计算；
- journal 状态转换和终止状态不可变；
- release state 原子替换和损坏检测；
- Compose 禁止 build、latest、仅标签和跨版本组件；
- PowerShell 参数集不包含生产绕过开关；
- 工作流权限、受保护 ref 和 Action SHA 固定合同；
- Secret 不进入命令行、日志、镜像层、SBOM 和清单。

### 21.2 集成测试

使用临时本地 OCI registry、测试签名身份、一次性 MySQL 和临时发布目录覆盖：

- 完整 signed release 拉取；
- tag 被移动但 digest 验证仍安全；
- 清单、SBOM、provenance 或一个组件被篡改；
- 两个发布进程并发；
- 定时备份与发布竞争；
- 无迁移发布；
- expand 迁移；
- 目标版本与本次冻结 source 版本兼容；
- 选择更旧但兼容的版本；
- 选择需数据库 downgrade 的版本被拒绝；
- Agent Runtime pointer 与应用 manifest 不一致；
- session 延续和旧浏览器 mismatch。

### 21.3 故障注入

在每个状态边界终止 PowerShell、Docker 或目标容器，并验证下一次恢复结果。特别覆盖：

- 镜像只拉取一部分；
- 备份加密或隔离恢复失败；
- 进入维护后进程退出；
- worker/Agent 排空超时；
- MySQL DDL 部分成功后迁移失败；
- reverse privilege verification 失败；
- source recovery 组合证据失败；
- target readiness 失败；
- 流量恢复前后主机中断；
- journal 写入中断；
- 部署回执上传失败；
- 注册表暂时不可达。

### 21.4 服务器演练

上线门禁要求在与目标服务器等价的隔离环境完成：

1. 部署一个已批准基线版本；
2. 创建合成业务数据并验证审核、发布、看板和 Agent 安全状态；
3. 发布一个带 expand 迁移的新版本；
4. 验证会话、数据、worker、备份和权限；
5. 选择上一稳定版本重新发布；
6. 证明数据库未降级且旧应用仍正确读写；
7. 注入目标启动失败并证明自动恢复；
8. 注入部分 DDL 失败并证明系统保持维护而非错误恢复；
9. 验证 current、previous 和长期保留制品不会被清理；
10. 保存版本、digest、revision、时间戳和关闭式结果，不保存业务内容或 Secret。

这些步骤是验收协议，不代表当前已经通过，也不能据此编造停机时间或性能结果。

## 22. 运维与告警

至少监控：

- current release、previous stable 和实际容器 digest 不一致；
- deployment journal 存在非终止状态；
- maintenance 模式持续超过预期运维窗口；
- production deployment receipt 过期；
- current/previous 制品在中央或本机缺失；
- 签名、release catalog 或 provenance 验证失败；
- 备份或隔离恢复失败；
- 数据库 revision 不在 current manifest 支持集合；
- migration 权限未反向收敛；
- Agent Runtime pointer 不在 current release 允许集合；
- 浏览器 release mismatch 异常增加；
- 可用磁盘不足以同时保留 current、previous、target、备份和恢复副本。

告警只包含 release version、digest、operation UUID、关闭式错误码和时间，不包含业务数据或凭据。

## 23. 与阶段 11A 的关系

阶段 11A 的 18 个任务先实现只读 Agent 功能、内部 Runtime 版本、控制面、备份 v2 和当前单套服务器部署。阶段 11B 在 11A 完成后实施，避免同时重写 Agent 容器拓扑和应用发布方式。

阶段 11B 将复用：

- Agent Runtime 不可变版本和 current pointer；
- kill switch、fencing 和持久运行状态；
- mTLS 与 Runtime 网络隔离；
- 备份格式 v2 和恢复 canary；
- MySQL 8.0/8.4 兼容矩阵；
- 目标环境性能与发布门禁。

阶段 11B 不改变 11A 的事实权威、只读工具、不可变快照或人工纠错闭环。若实现中需要改变这些边界，必须单独更新 11A 规格并重新批准。

## 24. 风险与明确边界

### 24.1 数据库风险

最大风险是 MySQL 非事务 DDL 产生部分迁移。设计通过 expand/contract、备份与隔离恢复、双版本兼容探针和维护态失败关闭降低风险，但不能把自动恢复应用描述成数据库事务回滚。

### 24.2 宿主机权限风险

能控制 Docker 的 PowerShell 身份可以控制整台应用主机。该能力只存在于宿主机受控账号，不能通过 Web API 暴露，也不能把 Docker socket 挂载进任何应用或 Agent 容器。

### 24.3 供应链风险

可移动标签、未固定 Action、过宽工作流权限、缺少签名或错误的 OIDC 身份约束都可能让恶意镜像看起来像合法版本。发布前必须先完成仓库保护和供应链门禁。

### 24.4 存储风险

最近 20 个版本、current、previous、长期保留、签名 referrer、备份和恢复副本会占用磁盘。发布前必须计算完整峰值空间，空间不足时在任何停服或迁移前拒绝。

### 24.5 可用性风险

单槽方案明确接受短暂停机。稳定维护页、完整预检和失败回切降低影响，但不承诺零停机。若未来业务要求无感发布，应在相同 manifest 与兼容合同上新增蓝绿槽位，而不是弱化现有检查。

## 25. 完成定义

阶段 11B 只有同时满足以下条件才算完成：

1. 受保护 master 成功后能自动形成不可覆盖的 v11A.1.N approved 版本。
2. 发布清单、镜像、SBOM、provenance 和签名均绑定同一 source SHA 与 digest。
3. 生产 Compose 不再现场构建应用，也不使用 latest 或仅标签镜像。
4. PowerShell 能列出、检查、预演和发布安全历史版本。
5. 普通发布无法绕过签名、备份、隔离恢复、兼容性、迁移和健康门禁。
6. 目标失败时，在上一版实际兼容的前提下自动恢复；不兼容时保持维护。
7. 数据库从不因普通应用回滚而自动 downgrade。
8. current、previous、长期保留和未完成事务制品不会被错误清理。
9. 并发、篡改、断电、部分 DDL、回执失败和恢复演练全部通过。
10. 文档给出日常发布、历史版本选择、撤销、归档、事故恢复和基座升级的明确命令与证据要求。

在上述证据形成前，现有 ops/DEPLOYMENT.md 中的人工升级流程仍是唯一已实现方式，不能声称系统已经支持随时切换应用版本。
